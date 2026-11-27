"""A change that leaves one job as a patch and is published by another (SEC-10).

The job that builds holds no token that can write, so it cannot push. It writes the change as a patch. The job
that pushes was not there when the coding agent ran: it believes nothing in the patch. These tests make
patches with real git in temporary repositories, the hostile ones included, and publish them to a local remote.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from contexer.contract import ContractStore
from contexer.controller.models import RunOutcome
from contexer.github.handoff import (
    MAX_PATCH_BYTES,
    HandoffError,
    make_patch,
    patch_problems,
    plan_handoff,
    publish_patch,
)
from tests.test_issue_flow import FakeGitHub, _contract, git

CONTRACT_FILE = ".contexer/contracts/todo-basics.json"
PNG = bytes(range(256)) * 4  # not text: a patch has to carry it byte for byte


class Repos:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.remote = tmp_path / "remote.git"
        git(tmp_path, "init", "--quiet", "--bare", "-b", "main", str(self.remote))
        seed = self.clone("seed")
        (seed / "app.js").write_text("count = all\n", encoding="utf-8")
        (seed / "old.txt").write_text("to be deleted\n", encoding="utf-8")
        (seed / ".contexer" / "contracts").mkdir(parents=True)
        (seed / ".contexer" / "contracts" / "earlier.json").write_text("{}\n", encoding="utf-8")
        git(seed, "add", "-A")
        git(seed, "commit", "--quiet", "-m", "the app")
        git(seed, "push", "--quiet", "-u", "origin", "HEAD:main")

    def clone(self, name: str) -> Path:
        path = self.tmp / name
        git(self.tmp, "clone", "--quiet", str(self.remote), str(path))
        for setting in (("user.name", "Dev"), ("user.email", "dev@example.com"), ("core.autocrlf", "false")):
            git(path, "config", *setting)
        return path

    def heads(self) -> list[str]:
        return sorted(line.split("refs/heads/")[1] for line in git(self.remote, "show-ref", "--heads").splitlines())


@pytest.fixture
def repos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repos:
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/todo")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    return Repos(tmp_path)


def _outcome(*changed: str) -> RunOutcome:
    return RunOutcome(run_id="r1", contract_id="todo-basics", agent="scripted", terminal="failed_checks", reason="1 refuted", changed_files=list(changed))


def _approved():
    return _contract().approved_by("alice")


def _staged(clone: Path) -> bytes:
    return subprocess.run(["git", "diff", "--cached", "--binary", "--full-index", "HEAD"], cwd=clone, capture_output=True, check=True).stdout


def test_a_change_made_in_one_checkout_is_published_from_another(repos: Repos) -> None:
    built = repos.clone("built")
    plan = plan_handoff(built)  # before the agent works, as in a run
    (built / "app.js").write_text("count = open only\n", encoding="utf-8")
    (built / "logo.png").write_bytes(PNG)
    (built / "old.txt").unlink()
    (built / "untouched-by-the-run.txt").write_text("other work in the checkout\n", encoding="utf-8")
    ContractStore(built).save(_approved())
    patch = make_patch(plan, _outcome("app.js", "logo.png", "old.txt"), _approved())
    assert patch and b"untouched-by-the-run" not in patch
    assert git(built, "status", "--porcelain", "--untracked-files=no").split() == ["M", "app.js", "D", "old.txt"]  # nothing staged

    fresh = repos.clone("fresh")
    fake = FakeGitHub()
    handoff = publish_patch(plan_handoff(fresh), patch, _outcome(), _contract(), approved_by="alice", issue=7, client_factory=fake.client)

    assert handoff.pushed and handoff.is_pull_request and handoff.branch == "contexer/todo-basics"
    assert repos.heads() == ["contexer/todo-basics", "main"]
    assert git(repos.remote, "show", "contexer/todo-basics:app.js") == "count = open only"
    published = subprocess.run(["git", "show", "contexer/todo-basics:logo.png"], cwd=repos.remote, capture_output=True, check=True).stdout
    assert published == PNG
    files = git(repos.remote, "ls-tree", "-r", "--name-only", "contexer/todo-basics").splitlines()
    assert "old.txt" not in files and CONTRACT_FILE in files and "untouched-by-the-run.txt" not in files
    assert git(repos.remote, "rev-list", "--count", "main..contexer/todo-basics") == "1"
    pull = fake.pulls[0]
    assert pull["head"] == "contexer/todo-basics" and pull["base"] == "main" and "Closes #7" in pull["body"]
    assert "approved by alice" in pull["body"]
    # The job that pushed never had the change in its files: nothing of it could have been run there.
    assert (fresh / "app.js").read_text(encoding="utf-8") == "count = all\n" and not (fresh / "logo.png").exists()
    assert git(fresh, "status", "--porcelain") == "" and git(fresh, "branch", "--show-current") == "main"


def test_nothing_changed_makes_no_patch(repos: Repos) -> None:
    built = repos.clone("built")
    plan = plan_handoff(built)  # before the agent works, as in a run
    assert make_patch(plan, _outcome(), _approved()) is None


def _workflow(clone: Path) -> None:
    (clone / ".github" / "workflows").mkdir(parents=True)
    (clone / ".github" / "workflows" / "leak.yml").write_text("on: push\n", encoding="utf-8")
    git(clone, "add", "-A")


def _symlink(clone: Path) -> None:
    blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=clone, input=b"/etc/passwd", capture_output=True, check=True)
    git(clone, "update-index", "--add", "--cacheinfo", f"120000,{blob.stdout.decode().strip()},notes.txt")


def _submodule(clone: Path) -> None:
    git(clone, "update-index", "--add", "--cacheinfo", f"160000,{git(clone, 'rev-parse', 'HEAD')},vendor")


def _another_contract(clone: Path) -> None:
    (clone / ".contexer" / "contracts" / "always-passes.json").write_text("{}\n", encoding="utf-8")
    git(clone, "add", "-A")


def _deleted_contract(clone: Path) -> None:
    git(clone, "rm", "--quiet", ".contexer/contracts/earlier.json")


def _contract_in_a_subfolder(clone: Path) -> None:
    (clone / "docs" / ".contexer" / "contracts").mkdir(parents=True)
    (clone / "docs" / ".contexer" / "contracts" / "x.json").write_text("{}\n", encoding="utf-8")
    git(clone, "add", "-A")


def _weaker_checks(clone: Path) -> None:
    weaker = _contract().model_copy(update={"criteria": _contract().criteria[:1]}).approved_by("alice")
    ContractStore(clone).save(weaker)
    git(clone, "add", "-A")


def _approval_by_someone_else(clone: Path) -> None:
    ContractStore(clone).save(_contract().approved_by("mallory"))
    git(clone, "add", "-A")


def _not_a_contract(clone: Path) -> None:
    (clone / CONTRACT_FILE).write_text("not json\n", encoding="utf-8")
    git(clone, "add", "-A")


@pytest.mark.parametrize(
    ("stage", "says"),
    [
        (_workflow, "under .github/"),
        (_symlink, "symbolic link"),
        (_submodule, "submodule"),
        (_another_contract, "contract other than the approved one"),
        (_deleted_contract, "contract other than the approved one"),
        (_contract_in_a_subfolder, "contract other than the approved one"),
        (_weaker_checks, "does not hold the checks that were approved"),
        (_approval_by_someone_else, "does not record the approval"),
        (_not_a_contract, "does not hold the checks that were approved"),
    ],
)
def test_a_hostile_patch_is_refused_and_nothing_is_pushed(repos: Repos, stage: Callable[[Path], None], says: str) -> None:
    hostile = repos.clone("hostile")
    (hostile / "app.js").write_text("count = open only\n", encoding="utf-8")  # beside a change that is fine
    git(hostile, "add", "-A")
    stage(hostile)
    fresh = repos.clone("fresh")
    fake = FakeGitHub()
    with pytest.raises(HandoffError, match=says):
        publish_patch(plan_handoff(fresh), _staged(hostile), _outcome(), _contract(), approved_by="alice", client_factory=fake.client)
    assert repos.heads() == ["main"] and fake.pulls == []
    assert git(fresh, "status", "--porcelain") == ""


def _written_by_hand(path: str) -> bytes:
    return f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n+++ b/{path}\n@@ -0,0 +1 @@\n+echo stolen\n".encode()


@pytest.mark.parametrize(
    "patch",
    [
        _written_by_hand("../outside.txt"),
        _written_by_hand(".git/hooks/pre-push"),
        _written_by_hand(".GIT/hooks/pre-push"),
        _written_by_hand("src/../../outside.txt"),
        b"this is not a patch\n",
        b"",
        b"x" * (MAX_PATCH_BYTES + 1),
        # It applies only to a file that says something else: the base is not the one this job checked out.
        b"diff --git a/app.js b/app.js\n--- a/app.js\n+++ b/app.js\n@@ -1 +1 @@\n-count = something else\n+count = open only\n",
    ],
    ids=["above-the-repository", "git-hook", "git-hook-other-case", "dot-dot-inside", "not-a-patch", "empty", "too-large", "another-base"],
)
def test_a_patch_git_cannot_apply_inside_the_repository_is_refused(repos: Repos, patch: bytes) -> None:
    fresh = repos.clone("fresh")
    fake = FakeGitHub()
    with pytest.raises(HandoffError):
        publish_patch(plan_handoff(fresh), patch, _outcome(), _contract(), approved_by="alice", client_factory=fake.client)
    assert repos.heads() == ["main"] and fake.pulls == []
    assert not (repos.tmp / "outside.txt").exists() and not (fresh / ".git" / "hooks" / "pre-push").exists()


def test_a_patch_that_adds_a_secret_is_not_pushed(repos: Repos) -> None:
    built = repos.clone("built")
    plan = plan_handoff(built)  # before the agent works, as in a run
    key = "sk-ant-" + "api03-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0"
    (built / "config.js").write_text(f'const ANTHROPIC_API_KEY = "{key}";\n', encoding="utf-8")
    patch = make_patch(plan, _outcome("config.js"), _approved())
    assert patch
    fresh = repos.clone("fresh")
    fake = FakeGitHub()
    with pytest.raises(HandoffError, match="looks like a secret") as refused:
        publish_patch(plan_handoff(fresh), patch, _outcome(), _contract(), approved_by="alice", client_factory=fake.client)
    assert key not in str(refused.value) and "config.js" in str(refused.value)
    assert repos.heads() == ["main"] and fake.pulls == []


def test_the_hooks_of_the_checkout_that_pushes_are_not_run(repos: Repos) -> None:
    built = repos.clone("built")
    plan = plan_handoff(built)  # before the agent works, as in a run
    (built / "app.js").write_text("count = open only\n", encoding="utf-8")
    patch = make_patch(plan, _outcome("app.js"), _approved())
    assert patch
    fresh = repos.clone("fresh")
    ran = repos.tmp / "hook-ran"
    for name in ("pre-commit", "commit-msg", "pre-push"):
        hook = fresh / ".git" / "hooks" / name
        hook.write_text(f"#!/bin/sh\necho ran > '{ran.as_posix()}'\n", encoding="utf-8")
        hook.chmod(0o755)
    publish_patch(plan_handoff(fresh), patch, _outcome(), _contract(), approved_by="alice", client_factory=FakeGitHub().client)
    assert repos.heads() == ["contexer/todo-basics", "main"] and not ran.exists()


def test_what_the_other_job_said_cannot_add_a_line_to_the_commit(repos: Repos) -> None:
    built = repos.clone("built")
    plan = plan_handoff(built)  # before the agent works, as in a run
    (built / "app.js").write_text("count = open only\n", encoding="utf-8")
    patch = make_patch(plan, _outcome("app.js"), _approved())
    assert patch
    said = _outcome().model_copy(update={"run_id": "r1)\n\nCo-authored-by: Someone <someone@example.com>", "reason": "x\n\nCloses #1"})
    fake = FakeGitHub()
    publish_patch(plan_handoff(repos.clone("fresh")), patch, said, _contract(), approved_by="alice", issue=7, client_factory=fake.client)
    message = git(repos.remote, "log", "-1", "--format=%B", "contexer/todo-basics")
    assert "Co-authored-by" not in message and "run unknown" in message and "\nCloses" not in message
    assert "Closes #1" not in fake.pulls[0]["body"] and "Closes #7" in fake.pulls[0]["body"]


def test_the_rules_for_a_path() -> None:
    fine = [("100644", "src/app.js"), ("100755", "bin/run"), ("000000", "old.txt"), ("100644", CONTRACT_FILE), ("100644", "docs/github/x.md")]
    assert patch_problems(fine, CONTRACT_FILE) == []
    for mode, path in [
        ("100644", ".github/workflows/ci.yml"),
        ("000000", ".github/CODEOWNERS"),
        ("100644", ".GitHub/workflows/ci.yml"),
        ("120000", "link"),
        ("160000", "vendor"),
        ("100644", ".contexer/contracts/other.json"),
        ("100644", "a\nb.txt"),
        ("100644", "a\\b.txt"),
        ("100644", "x/.git/config"),
    ]:
        assert patch_problems([(mode, path)], CONTRACT_FILE), path
