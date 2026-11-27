"""The issue flow in two jobs (SEC-10): one builds with a token that cannot write, the other publishes.

``contexer issue event --hand-over DIR`` is the first job: it drafts or builds and leaves what it would have
posted and pushed in DIR. ``contexer issue publish DIR`` is the second: it holds the write token, runs nothing
of the project, and reads who approved what from the event and the issue again.

The workflow itself cannot be run from a test. What is checked of it is its text: the permissions of each
job, and that the publishing job has no step that runs a command of the project.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from typer.testing import CliRunner

from contexer.cli import app, init_cli
from contexer.cli.issue_cli import HANDOVER_FILE, PATCH_FILE, Handover
from contexer.github.issues import find_draft
from tests.test_issue_flow import BOT, COUNT_BUG_JS, GOOD_JS, FakeGitHub, _post_draft, git, github  # noqa: F401  (github is a fixture)

REPO = Path(__file__).resolve().parents[2]


class NoWriteGitHub(FakeGitHub):
    """GitHub as a token with ``contents: read`` and ``issues: read`` sees it: every write is refused."""

    def __init__(self, shared: FakeGitHub, can_push: bool | None = False) -> None:
        super().__init__()
        self.comments, self.roles, self.can_push = shared.comments, shared.roles, can_push
        self.refused: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.method != "GET":
            self.refused.append(f"{request.method} {request.url.path}")
            return httpx.Response(403, json={"message": "Resource not accessible by integration"})
        if request.url.path == "/repos/acme/todo" and self.can_push is not None:
            return httpx.Response(200, json={"permissions": {"pull": True, "push": self.can_push}})
        return super().handler(request)


class Jobs:
    """The two jobs of one workflow run: the same event, two checkouts, two tokens."""

    def __init__(self, fake: FakeGitHub, root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.fake, self.first, self.tmp, self.monkeypatch = fake, root, tmp_path, monkeypatch
        self.left = tmp_path / "left"
        self.second = tmp_path / "second"
        git(tmp_path, "clone", "--quiet", "-b", "main", str(tmp_path / "remote.git"), str(self.second))
        self.reader = NoWriteGitHub(fake)
        self.turns = tmp_path / "turns.json"
        self.turns.write_text(json.dumps([{"app.js": GOOD_JS}]), encoding="utf-8")

    def event(self, name: str, payload: dict[str, Any]) -> None:
        file = self.tmp / "event.json"
        file.write_text(json.dumps(payload), encoding="utf-8")
        self.monkeypatch.setenv("GITHUB_EVENT_NAME", name)
        self.monkeypatch.setenv("GITHUB_EVENT_PATH", str(file))

    def says(self, body: str, login: str = "alice") -> None:
        self.fake.comments.append({"id": 60 + len(self.fake.comments), "body": body, "user": {"login": login, "type": "User"}})
        self.event("issue_comment", {"action": "created", "issue": {"number": 7}, "comment": {"body": body, "user": {"login": login}}})

    def build(self) -> Any:
        self.monkeypatch.setattr("contexer.cli.issue_cli.GitHubClient", self.reader.client)
        self.monkeypatch.setattr("contexer.github.handoff.GitHubClient", self.reader.client)
        args = ["issue", "event", "--dir", str(self.first), "--agent", "scripted", "--model", str(self.turns), "--hand-over", str(self.left)]
        return CliRunner().invoke(app, args)

    def publish(self) -> Any:
        self.monkeypatch.setattr("contexer.cli.issue_cli.GitHubClient", self.fake.client)
        self.monkeypatch.setattr("contexer.github.handoff.GitHubClient", self.fake.client)
        return CliRunner().invoke(app, ["issue", "publish", str(self.left), "--dir", str(self.second)])

    def heads(self) -> list[str]:
        return sorted(line.split("refs/heads/")[1] for line in git(self.tmp / "remote.git", "show-ref", "--heads").splitlines())

    def handover(self) -> Handover:
        return Handover.model_validate_json((self.left / HANDOVER_FILE).read_bytes())


@pytest.fixture
def jobs(github, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Jobs:  # noqa: F811
    fake, root = github
    return Jobs(fake, root, tmp_path, monkeypatch)


def test_an_approved_issue_is_built_with_no_write_token_and_published_by_the_second_job(jobs: Jobs) -> None:
    _post_draft(jobs.fake)
    jobs.says("/contexer approve")

    built = jobs.build()
    assert built.exit_code == 0, built.output
    assert jobs.reader.refused == []  # it did not try to post or push: it has nothing to do it with
    assert jobs.heads() == ["main"] and jobs.fake.pulls == [] and len(jobs.fake.comments) == 2
    assert (jobs.left / PATCH_FILE).is_file() and jobs.handover().outcome is not None

    published = jobs.publish()
    assert published.exit_code == 0, published.output
    pull = jobs.fake.pulls[0]
    assert "Closes #7" in pull["body"] and pull["head"] == "contexer/todo-basics" and not pull["draft"]
    assert "All 7 checks proven" in pull["body"] and "approved by alice" in pull["body"]
    status = jobs.fake.comments[-1]["body"]
    assert "✅ Done: all 7 checks proven" in status and "https://github.com/acme/todo/pull/8" in status and "Attempt 1" in status
    assert jobs.heads() == ["contexer/todo-basics", "main"]
    shown = subprocess.run(["git", "show", "contexer/todo-basics:app.js"], cwd=jobs.tmp / "remote.git", capture_output=True, check=True)
    assert shown.stdout.decode("utf-8").replace("\r\n", "\n") == GOOD_JS.replace("\r\n", "\n")
    # The job with the write token never had the change in its files.
    assert (jobs.second / "app.js").read_text(encoding="utf-8") == COUNT_BUG_JS


def test_the_first_job_refuses_to_build_when_its_token_can_write(jobs: Jobs) -> None:
    _post_draft(jobs.fake)
    jobs.says("/contexer approve")
    jobs.reader.can_push = True
    built = jobs.build()
    assert built.exit_code == 3
    assert "contents: read" in jobs.handover().stopped
    assert (jobs.first / "app.js").read_text(encoding="utf-8") == COUNT_BUG_JS  # no agent ran
    jobs.publish()
    assert "contents: read" in jobs.fake.comments[-1]["body"] and jobs.fake.pulls == []


def test_a_draft_is_made_by_the_first_job_and_posted_by_the_second(jobs: Jobs) -> None:
    jobs.monkeypatch.setattr("contexer.cli.issue_cli.compiler_llm", lambda _project: None)  # no model: rule-based draft
    jobs.monkeypatch.setattr("contexer.cli.run_cli.crew_model", lambda *_a, **_k: None)
    jobs.event("issues", {"action": "labeled", "label": {"name": "contexer"}, "issue": {"number": 7}, "sender": {"login": "bob"}})
    built = jobs.build()
    assert built.exit_code == 0, built.output
    assert jobs.reader.refused == [] and jobs.fake.comments == []

    published = jobs.publish()
    assert published.exit_code == 0, published.output
    assert len(jobs.fake.comments) == 1
    _, contract, edited = find_draft(jobs.fake.comments)
    assert contract.id.startswith("issue-7-") and not edited and "Remaining count ignores done tasks" in contract.goal


def test_a_refusal_in_the_first_job_is_said_on_the_issue_by_the_second(jobs: Jobs) -> None:
    _post_draft(jobs.fake)
    jobs.says("/contexer approve", login="mallory")
    assert jobs.build().exit_code == 2
    assert jobs.reader.refused == [] and not (jobs.left / PATCH_FILE).exists()
    jobs.publish()
    assert "only people with write access" in jobs.fake.comments[-1]["body"] and jobs.fake.pulls == []


def _built(jobs: Jobs) -> None:
    _post_draft(jobs.fake)
    jobs.says("/contexer approve")
    assert jobs.build().exit_code == 0


def test_the_second_job_checks_the_approver_itself(jobs: Jobs) -> None:
    """What the first job left says a run was approved and passed. Whether the approver may approve is asked again."""
    _built(jobs)
    jobs.fake.roles["alice"] = "read"
    assert jobs.publish().exit_code == 2
    assert jobs.fake.pulls == [] and jobs.heads() == ["main"]
    assert "only people with write access" in jobs.fake.comments[-1]["body"]


def test_the_second_job_publishes_only_the_checks_that_are_on_the_issue(jobs: Jobs) -> None:
    _built(jobs)
    draft = jobs.fake.comments[0]
    draft["body"] = draft["body"].replace('"goal": "', '"goal": "Something else. ', 1)  # the issue now asks for other checks
    assert jobs.publish().exit_code == 3
    assert jobs.fake.pulls == [] and jobs.heads() == ["main"]
    assert "does not hold the checks that were approved" in jobs.fake.comments[-1]["body"]


def test_the_second_job_does_not_publish_checks_that_changed_after_the_approval(jobs: Jobs) -> None:
    _built(jobs)
    jobs.fake.comments[0]["updated_at"] = "2026-11-27T10:05:00Z"
    said = {"body": "/contexer approve", "user": {"login": "alice"}, "created_at": "2026-11-27T10:00:00Z"}
    jobs.event("issue_comment", {"action": "created", "issue": {"number": 7}, "comment": said})
    assert jobs.publish().exit_code == 3
    assert jobs.fake.pulls == [] and "changed after" in jobs.fake.comments[-1]["body"]


def test_what_was_left_for_another_issue_or_nothing_at_all_is_not_published(jobs: Jobs) -> None:
    _built(jobs)
    left = jobs.handover()
    (jobs.left / HANDOVER_FILE).write_text(left.model_copy(update={"issue": 8}).model_dump_json(), encoding="utf-8")
    assert jobs.publish().exit_code == 3
    (jobs.left / HANDOVER_FILE).unlink()
    assert jobs.publish().exit_code == 3
    (jobs.left / HANDOVER_FILE).write_text('{"command": "build", "issue": 7, "outcome": {"run_id": 1}}', encoding="utf-8")
    assert jobs.publish().exit_code == 3
    assert jobs.fake.pulls == [] and jobs.heads() == ["main"]


def test_a_hostile_change_left_by_the_first_job_is_not_pushed_and_the_issue_says_why(jobs: Jobs) -> None:
    _built(jobs)
    hostile = jobs.tmp / "hostile"
    git(jobs.tmp, "clone", "--quiet", "-b", "main", str(jobs.tmp / "remote.git"), str(hostile))
    (hostile / ".github" / "workflows").mkdir(parents=True)
    (hostile / ".github" / "workflows" / "leak.yml").write_text("on: push\n", encoding="utf-8")
    git(hostile, "add", "-A")
    patch = subprocess.run(["git", "diff", "--cached", "--binary", "HEAD"], cwd=hostile, capture_output=True, check=True).stdout
    (jobs.left / PATCH_FILE).write_bytes(patch)
    assert jobs.publish().exit_code == 3
    assert jobs.fake.pulls == [] and jobs.heads() == ["main"]
    assert "under .github/" in jobs.fake.comments[-1]["body"]


def test_text_the_first_job_left_is_shown_and_does_nothing(jobs: Jobs) -> None:
    _built(jobs)
    left = jobs.handover()
    assert left.outcome is not None
    said = left.model_copy(update={"lines": ["```", "@bob see #1"], "outcome": left.outcome.model_copy(update={"terminal": "failed_checks", "reason": "x @bob closes #1"})})
    (jobs.left / HANDOVER_FILE).write_text(said.model_dump_json(), encoding="utf-8")
    assert jobs.publish().exit_code == 0
    status, pull = jobs.fake.comments[-1]["body"], jobs.fake.pulls[0]
    assert pull["draft"]
    for text in (status, pull["body"], pull["title"]):
        assert "@bob" not in text and "#1" not in text


# -- the workflow and the two actions, as text ------------------------------------------------


def _workflow() -> dict[str, Any]:
    return yaml.safe_load(init_cli.ISSUES_WORKFLOW.format(working_directory="app"))


def _action(*parts: str) -> dict[str, Any]:
    return yaml.safe_load((REPO.joinpath(*parts) / "action.yml").read_text(encoding="utf-8"))


def _uses(steps: list[dict[str, Any]]) -> list[str]:
    return [str(step["uses"]).split("@")[0] for step in steps if "uses" in step]


def test_the_job_that_builds_has_no_permission_that_writes() -> None:
    workflow = _workflow()
    assert workflow.get("permissions") == {}  # a job gets only what it names
    build = workflow["jobs"]["build"]
    assert build["permissions"] and all(level == "read" for level in build["permissions"].values())
    assert build["permissions"]["contents"] == "read"
    checkout, contexer = build["steps"]
    assert checkout["uses"].startswith("actions/checkout@") and checkout["with"]["persist-credentials"] is False
    assert contexer["uses"] == "murtuza777/contexer-agent/issue@main" and contexer["with"]["hand-over"] is True
    assert "github-token" not in contexer["with"]  # the job's own token, which can only read
    assert "secrets.GITHUB_TOKEN" not in json.dumps(build) and "github.token" not in json.dumps(build)


def test_the_job_that_publishes_has_the_write_token_and_runs_nothing_of_the_project() -> None:
    workflow = _workflow()
    publish = workflow["jobs"]["publish"]
    assert publish["needs"] == "build"
    assert publish["permissions"] == {"contents": "write", "issues": "write", "pull-requests": "write"}
    assert "secrets." not in json.dumps(publish)  # no model key: nothing here calls a model
    assert not any("run" in step for step in publish["steps"])
    assert _uses(publish["steps"]) == ["actions/checkout", "murtuza777/contexer-agent/issue/publish"]
    checkout = publish["steps"][0]
    assert checkout["with"] == {"persist-credentials": False}  # the default branch as it is, never the change
    # It runs when the first job failed too (a run that did not pass still opens a draft), not when it found nothing to do.
    condition = str(publish["if"])
    assert "!cancelled()" in condition and "needs.build.outputs.command" in condition
    assert workflow["jobs"]["build"]["outputs"]["command"] == "${{ steps.contexer.outputs.command }}"


def test_the_publish_action_installs_contexer_and_runs_only_it() -> None:
    action = _action("issue", "publish")
    steps = action["runs"]["steps"]
    assert _uses(steps) == ["actions/setup-python", "actions/download-artifact"]
    scripts = [str(step["run"]) for step in steps if "run" in step]
    assert len(scripts) == 2
    install, publish = scripts
    assert install.strip() == 'python -m pip install --quiet "${{ github.action_path }}/../../contexer-agent"'
    assert publish.strip() == 'contexer issue publish "$CONTEXER_LEFT" --label "$CONTEXER_LABEL"'
    for word in ("npm", "node", "playwright", "pytest", "make", "issue event", "issue build", "issue draft"):
        assert word not in "\n".join(scripts), word
    download = next(step for step in steps if str(step.get("uses", "")).startswith("actions/download-artifact@"))
    assert download["with"]["path"].startswith("${{ runner.temp }}/")  # outside the checkout
    assert download["with"]["name"] == "contexer-hand-over-${{ github.event.issue.number }}"


def test_the_issue_action_leaves_its_work_as_an_artifact_only_when_asked() -> None:
    action = _action("issue")
    assert action["inputs"]["hand-over"]["default"] == "false"  # a workflow written before the split works as it did
    steps = action["runs"]["steps"]
    upload = next(step for step in steps if step.get("name") == "Upload what the publishing job needs")
    assert "inputs.hand-over == 'true'" in upload["if"] and "always()" in upload["if"]
    assert upload["with"]["name"] == "contexer-hand-over-${{ github.event.issue.number }}"
    assert upload["with"]["path"].startswith("${{ runner.temp }}/")
    run = next(step for step in steps if step.get("name") == "Contexer")
    assert 'if [ "$CONTEXER_HAND_OVER" = "true" ]; then args+=(--hand-over "$RUNNER_TEMP/contexer-hand-over"); fi' in run["run"]


def test_init_writes_the_two_job_workflow(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    result = CliRunner().invoke(app, ["init", "--dir", str(tmp_path), "--repo-root", str(tmp_path), "--issues"])
    assert result.exit_code == 0, result.output
    written = yaml.safe_load((tmp_path / ".github" / "workflows" / "contexer-issues.yml").read_text(encoding="utf-8"))
    assert set(written["jobs"]) == {"build", "publish"}
