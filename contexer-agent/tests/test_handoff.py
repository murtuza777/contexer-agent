"""Handing a run over as a branch and a pull request: real git, a local remote, a fake GitHub API."""

import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from contexer.agents import ScriptedAgent
from contexer.contract import ContractStore
from contexer.controller import RunController, RunSettings
from contexer.github.api import GitHubClient
from contexer.github.handoff import HandoffError, hand_off, plan_handoff, pull_request_body
from contexer.verification.runner import CheckRunner

pytestmark = pytest.mark.anyio

FIXTURE = Path(__file__).resolve().parents[1] / "bench" / "fixtures" / "todo"
GOOD_JS = (FIXTURE / "app" / "app.js").read_text(encoding="utf-8")
COUNT_BUG_JS = (FIXTURE / "bugs" / "count-ignores-done" / "app.js").read_text(encoding="utf-8")


def git(cwd: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return out.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A checkout of the todo app on main, pushed to a bare remote, with the count bug committed.

    The approved contract is not committed yet, as after `contexer run "GOAL"` drafts it.
    """
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--quiet", "--bare", str(remote))
    root = tmp_path / "work"
    shutil.copytree(FIXTURE / "app", root, ignore=shutil.ignore_patterns("runs"))
    (root / "app.js").write_bytes(COUNT_BUG_JS.encode("utf-8"))
    git(root, "init", "--quiet", "-b", "main")
    git(root, "config", "user.name", "Dev")
    git(root, "config", "user.email", "dev@example.com")
    git(root, "config", "core.autocrlf", "false")
    git(root, "add", "-A", "--", ".", ":!.contexer/contracts")
    git(root, "commit", "--quiet", "-m", "todo app")
    git(root, "remote", "add", "origin", str(remote))
    git(root, "push", "--quiet", "-u", "origin", "main")
    (root / "notes.txt").write_text("my own scratch notes\n", encoding="utf-8")  # untracked, not the agent's
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/todo")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    return root


class FakeGitHub:
    def __init__(self, draft_supported: bool = True) -> None:
        self.pulls: list[dict] = []
        self.draft_supported = draft_supported

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-token"
        if request.method == "POST" and request.url.path == "/repos/acme/todo/pulls":
            payload = json.loads(request.content)
            if payload["draft"] and not self.draft_supported:
                return httpx.Response(422, json={"message": "Validation Failed", "errors": [
                    {"message": "Draft pull requests are not supported in this repository."}]})
            self.pulls.append(payload)
            return httpx.Response(201, json={"html_url": f"https://github.com/acme/todo/pull/{len(self.pulls)}",
                                             "draft": payload["draft"]})
        return httpx.Response(404, json={"message": "Not Found"})

    def factory(self, repo: str, token: str) -> GitHubClient:
        return GitHubClient(repo, token, transport=httpx.MockTransport(self.handler))


async def _run(root: Path, turns: list[dict]):
    contract = ContractStore(root).load("todo-basics")
    fast = CheckRunner(action_timeout=1.5, expect_timeout=1.0)
    outcome = await RunController(root, ScriptedAgent(turns), RunSettings(max_repair_rounds=0), runner=fast).run(contract)
    return outcome, contract


async def test_a_proven_run_becomes_a_ready_pull_request_with_only_its_own_changes(repo: Path) -> None:
    plan = plan_handoff(repo)
    assert (plan.base, plan.remote, plan.repo) == ("main", "origin", "acme/todo")
    outcome, contract = await _run(repo, [{"app.js": GOOD_JS}])
    assert outcome.terminal == "succeeded" and outcome.changed_files == ["app.js"]

    github = FakeGitHub()
    handoff = hand_off(plan, outcome, contract, issue=7, client_factory=github.factory)
    assert handoff is not None and handoff.is_pull_request and not handoff.draft
    assert handoff.url == "https://github.com/acme/todo/pull/1"
    assert handoff.branch == "contexer/todo-basics" and handoff.pushed

    committed = git(repo, "show", "--name-only", "--format=%s", "HEAD").splitlines()
    assert committed[0].startswith(contract.goal[:40])
    assert sorted(committed[2:]) == [".contexer/contracts/todo-basics.json", "app.js"]  # not notes.txt
    assert git(repo, "branch", "--show-current") == "contexer/todo-basics"
    assert git(repo, "ls-remote", "--heads", "origin", "contexer/todo-basics")

    pull = github.pulls[0]
    assert (pull["base"], pull["head"], pull["draft"]) == ("main", "contexer/todo-basics", False)
    assert "All 7 checks proven in a real browser" in pull["body"]
    assert "Closes #7" in pull["body"]
    assert pull["body"].count("| ✅ |") == 7


async def test_an_unfinished_run_opens_a_draft_that_says_what_fails(repo: Path) -> None:
    plan = plan_handoff(repo)
    outcome, contract = await _run(repo, [{"app.js": COUNT_BUG_JS + "\n// still wrong\n"}])
    assert outcome.terminal != "succeeded" and outcome.changed_files == ["app.js"]
    github = FakeGitHub(draft_supported=False)  # e.g. a private repository on a free plan
    handoff = hand_off(plan, outcome, contract, client_factory=github.factory)
    assert handoff is not None and handoff.is_pull_request
    pull = github.pulls[0]
    assert pull["draft"] is False and pull["title"].startswith("[Draft] ")
    assert "Not done yet" in pull["body"] and "| ❌ |" in pull["body"]
    assert "Closes #" not in pull["body"]


async def test_a_taken_branch_name_gets_a_suffix_and_no_token_gives_a_link(repo: Path, monkeypatch) -> None:
    git(repo, "branch", "contexer/todo-basics")
    plan = plan_handoff(repo)
    outcome, contract = await _run(repo, [{"app.js": GOOD_JS}])
    monkeypatch.delenv("GITHUB_TOKEN")
    monkeypatch.setattr("contexer.github.handoff.github_token", lambda: None)
    handoff = hand_off(plan, outcome, contract)
    assert handoff is not None and handoff.branch == "contexer/todo-basics-2"
    assert not handoff.is_pull_request and handoff.pushed
    assert handoff.url == "https://github.com/acme/todo/compare/main...contexer/todo-basics-2?expand=1"


async def test_a_run_that_changed_nothing_hands_nothing_over(repo: Path) -> None:
    plan = plan_handoff(repo)
    outcome, contract = await _run(repo, [{}])
    assert outcome.changed_files == []
    assert hand_off(plan, outcome, contract, client_factory=FakeGitHub().factory) is None
    assert git(repo, "branch", "--show-current") == "main"


def test_the_checkout_is_checked_before_anything_is_spent(repo: Path, tmp_path: Path) -> None:
    (repo / "app.js").write_text("// my unsaved work\n", encoding="utf-8")
    with pytest.raises(HandoffError, match="uncommitted changes in app.js"):
        plan_handoff(repo)
    git(repo, "checkout", "--quiet", "--", "app.js")

    git(repo, "checkout", "--quiet", "--detach")
    with pytest.raises(HandoffError, match="detached"):
        plan_handoff(repo)

    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(HandoffError, match="not in a git repository"):
        plan_handoff(plain)
    git(plain, "init", "--quiet")
    with pytest.raises(HandoffError, match="no commits yet"):
        plan_handoff(plain)


async def test_a_project_inside_a_monorepo_commits_paths_from_the_repository_root(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "mono"
    shutil.copytree(FIXTURE / "app", root / "apps" / "todo", ignore=shutil.ignore_patterns("runs"))
    project = root / "apps" / "todo"
    (project / "app.js").write_bytes(COUNT_BUG_JS.encode("utf-8"))
    git(root, "init", "--quiet", "-b", "main")
    git(root, "config", "user.name", "Dev")
    git(root, "config", "user.email", "dev@example.com")
    git(root, "add", "-A")
    git(root, "commit", "--quiet", "-m", "mono")
    plan = plan_handoff(project)
    assert plan.root == root.resolve() and plan.remote is None
    outcome, contract = await _run(project, [{"app.js": GOOD_JS}])
    handoff = hand_off(plan, outcome, contract)
    assert handoff is not None and not handoff.pushed and "no remote" in handoff.note
    files = git(root, "show", "--name-only", "--format=", "HEAD").splitlines()
    assert files == ["apps/todo/app.js"]  # the contract was committed before, unchanged


def test_the_body_links_the_workflow_run_in_actions(monkeypatch) -> None:
    from contexer.contract.models import Contract
    from contexer.controller.run import RunOutcome

    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/todo")
    outcome = RunOutcome(run_id="r1", contract_id="c", agent="opencode", terminal="failed_checks", reason="2 refuted")
    body = pull_request_body(outcome, Contract(id="c", goal="Users can | pipe"))
    assert "https://github.com/acme/todo/actions/runs/42" in body
    assert "> Users can | pipe" in body
