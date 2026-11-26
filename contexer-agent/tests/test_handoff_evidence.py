"""Screenshots in the pull request, when asked for (DX-2): real git, a local remote, a fake GitHub API.

No browser and no network: the outcome and its screenshots are built by hand.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest
import typer
from rich.console import Console
from typer.testing import CliRunner

from contexer.cli import app
from contexer.contract.models import Contract
from contexer.controller import RunOutcome
from contexer.evidence.report import _data_uri
from contexer.evidence.screenshots import MAX_IMAGE_BYTES, check_screenshots
from contexer.github.handoff import hand_off, plan_handoff
from contexer.verification.checks import CheckResult
from contexer.verification.models import CriterionResult, VerificationResult
from tests.test_handoff import FakeGitHub
from tests.test_handoff_inert import changed, checkout, git  # noqa: F401  (a fixture and helpers)

JPEG = b"\xff\xd8\xff\xe0" + b"contexer test image" * 4
LEAK = 'const SERVICE_KEY = "' + "q7Rk2ZpX9vLm" + "4TnB8sWd3Yf6" + '";\n'


@pytest.fixture(autouse=True)
def _on_a_persons_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("GITHUB_ACTIONS", "GITHUB_RUN_ID", "GITHUB_SERVER_URL"):
        monkeypatch.delenv(name, raising=False)


def run_with_screens(root: Path, files: dict[str, str] | None = None, **rows: tuple[bool, str | None]) -> tuple[RunOutcome, Contract]:
    """A run that changed app.js and judged each named check, with a screenshot where a path is given.

    A relative path is written as a JPEG inside the run's folder; an absolute one is used as it is.
    """
    outcome, contract = changed(root, files or {"app.js": "let count = 1;\n"})
    run = root / ".contexer" / "runs" / "r1"
    results = []
    for check_id, (passed, shot) in rows.items():
        path = None
        if shot is not None:
            path = Path(shot) if Path(shot).is_absolute() else run / shot
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(JPEG + check_id.encode())
        check = CheckResult(criterion_id=check_id, passed=passed, screenshot=str(path) if path else None)
        results.append(CriterionResult(criterion_id=check_id, description=f"About {check_id}", passed=passed, method="assertion", check_result=check))
    assert outcome.final is not None
    outcome.final.contracts[0].verification = VerificationResult(passed=all(r.passed for r in results), criteria_results=results)
    run.mkdir(parents=True, exist_ok=True)
    return outcome.model_copy(update={"run_dir": str(run)}), contract


def remote_heads(root: Path) -> dict[str, str]:
    """The remote's branches, by name."""
    lines = git(root, "ls-remote", "--heads", "origin").splitlines()
    return {ref.removeprefix("refs/heads/"): sha for sha, ref in (line.split("\t") for line in lines)}


TWO = {"adds-a-task": (True, "attempt-2/checks/c1/adds-a-task.jpg"), "counts left": (False, "attempt-2/checks/c1/counts_left.jpg")}


# -- what is pushed -------------------------------------------------------------------------------


def test_screenshots_go_to_a_commit_with_no_parent_on_their_own_branch(checkout: Path) -> None:  # noqa: F811
    plan = plan_handoff(checkout)
    main_before = remote_heads(checkout)["main"]
    outcome, contract = run_with_screens(checkout, **TWO)
    github = FakeGitHub()
    handoff = hand_off(plan, outcome, contract, client_factory=github.factory, screenshots=True)
    assert handoff is not None and handoff.is_pull_request, handoff

    heads = remote_heads(checkout)
    branch = f"contexer-evidence/c1-{handoff.commit[:8]}"
    assert set(heads) == {"main", "contexer/c1", branch} and heads["main"] == main_before
    remote = checkout.parent / "remote.git"
    assert git(remote, "rev-list", "--parents", "-n", "1", heads[branch]) == heads[branch]  # no parent
    assert git(remote, "ls-tree", "-r", "--name-only", heads[branch]).splitlines() == ["01-adds-a-task.jpg", "02-counts-left.jpg"]
    shot = Path(outcome.run_dir) / "attempt-2" / "checks" / "c1" / "counts_left.jpg"
    assert git(remote, "rev-parse", f"{heads[branch]}:02-counts-left.jpg") == git(checkout, "hash-object", "--no-filters", str(shot))
    assert git(remote, "log", "-1", "--format=%an <%ae>", heads[branch]) == "Contexer <contexer@users.noreply.github.com>"

    # The checkout is as the hand-off leaves it without screenshots: on the work's branch, nothing else.
    assert git(checkout, "branch", "--show-current") == "contexer/c1"
    assert git(checkout, "branch", "--list", "contexer-evidence/*") == ""
    assert git(checkout, "status", "--porcelain", "--untracked-files=no") == ""
    assert git(checkout, "show", "--name-only", "--format=", "HEAD").splitlines() == ["app.js"]

    body = github.pulls[0]["body"]
    done, screens, how = (body.index(f"### {title}") for title in ("Definition of done", "Screenshots", "How it got here"))
    assert done < screens < how
    section = body[screens:how]
    link = f"https://github.com/acme/todo/blob/{branch}"
    assert f"![Screenshot]({link}/02-counts-left.jpg?raw=true)" in section and f"({link}/01-adds-a-task.jpg?raw=true)" in section
    opened, folded = section.split("<details>")
    assert "counts left" in opened and "last screen" in opened and "02-counts-left.jpg" in opened  # the failed check, open
    assert "01-adds-a-task.jpg" in folded and "</details>" in folded  # the passed one, folded away
    assert f"`{branch}`" in opened and "pushed" in opened and "Deleting" in opened
    assert handoff.note == ""


def test_nothing_is_pushed_and_the_body_says_nothing_unless_asked(checkout: Path) -> None:  # noqa: F811
    plan = plan_handoff(checkout)
    outcome, contract = run_with_screens(checkout, **TWO)
    github = FakeGitHub()
    handoff = hand_off(plan, outcome, contract, client_factory=github.factory)
    assert handoff is not None and handoff.is_pull_request
    assert set(remote_heads(checkout)) == {"main", "contexer/c1"}
    assert "creenshot" not in github.pulls[0]["body"].split("### How it got here")[0]


def test_a_change_that_adds_a_secret_pushes_no_screenshots_either(checkout: Path) -> None:  # noqa: F811
    plan = plan_handoff(checkout)
    outcome, contract = run_with_screens(checkout, {"app.js": LEAK}, **TWO)
    handoff = hand_off(plan, outcome, contract, client_factory=FakeGitHub().factory, screenshots=True)
    assert handoff is not None and not handoff.pushed and "secret" in handoff.note
    assert set(remote_heads(checkout)) == {"main"}


def test_no_screenshots_without_a_token(checkout: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setattr("contexer.github.handoff.github_token", lambda: None)
    plan = plan_handoff(checkout)
    outcome, contract = run_with_screens(checkout, **TWO)
    handoff = hand_off(plan, outcome, contract, screenshots=True)
    assert handoff is not None and handoff.pushed and not handoff.is_pull_request
    assert set(remote_heads(checkout)) == {"main", "contexer/c1"}


def test_no_screenshots_for_a_remote_that_is_not_github(checkout: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)  # the remote is a folder: not GitHub
    plan = plan_handoff(checkout)
    assert plan.repo is None
    outcome, contract = run_with_screens(checkout, **TWO)
    handoff = hand_off(plan, outcome, contract, screenshots=True)
    assert handoff is not None and handoff.pushed and "merge request" in handoff.note
    assert set(remote_heads(checkout)) == {"main", "contexer/c1"}


def test_a_remote_that_refuses_the_branch_still_gets_its_pull_request(checkout: Path) -> None:  # noqa: F811
    hook = checkout.parent / "remote.git" / "hooks" / "update"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text('#!/bin/sh\ncase "$1" in refs/heads/contexer-evidence/*) echo "protected" >&2; exit 1;; esac\n', encoding="utf-8", newline="\n")
    hook.chmod(0o755)
    plan = plan_handoff(checkout)
    outcome, contract = run_with_screens(checkout, **TWO)
    github = FakeGitHub()
    handoff = hand_off(plan, outcome, contract, client_factory=github.factory, screenshots=True)
    assert handoff is not None and handoff.is_pull_request and handoff.url == "https://github.com/acme/todo/pull/1"
    assert set(remote_heads(checkout)) == {"main", "contexer/c1"}
    assert "screenshots" in handoff.note and "could not be pushed" in handoff.note
    assert "### Screenshots" not in github.pulls[0]["body"]


def test_a_pull_request_that_cannot_be_opened_leaves_a_note_about_the_pushed_screenshots(checkout: Path) -> None:  # noqa: F811
    plan = plan_handoff(checkout)
    outcome, contract = run_with_screens(checkout, **TWO)
    github = FakeGitHub()
    github.handler = lambda request: httpx.Response(403, json={"message": "Resource not accessible"})  # type: ignore[method-assign]
    handoff = hand_off(plan, outcome, contract, client_factory=github.factory, screenshots=True)
    assert handoff is not None and not handoff.is_pull_request
    branch = f"contexer-evidence/c1-{handoff.commit[:8]}"
    assert branch in remote_heads(checkout)
    assert branch in handoff.note and "delete" in handoff.note.lower()


def test_asking_for_screenshots_when_the_run_kept_none_says_so(checkout: Path) -> None:  # noqa: F811
    plan = plan_handoff(checkout)
    outcome, contract = run_with_screens(checkout, **{"adds-a-task": (True, None)})
    github = FakeGitHub()
    handoff = hand_off(plan, outcome, contract, client_factory=github.factory, screenshots=True)
    assert handoff is not None and handoff.is_pull_request
    assert set(remote_heads(checkout)) == {"main", "contexer/c1"}
    assert "no screenshots" in handoff.note.lower() and "### Screenshots" not in github.pulls[0]["body"]


def test_the_persons_own_pre_push_hook_does_not_run_for_the_screenshots(checkout: Path, tmp_path: Path) -> None:  # noqa: F811
    seen = tmp_path / "pushed.txt"
    hook = checkout / ".git" / "hooks" / "pre-push"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text("#!/bin/sh\ncat >> '" + seen.as_posix() + "'\n", encoding="utf-8", newline="\n")
    hook.chmod(0o755)
    plan = plan_handoff(checkout)  # it was there before the run, so it runs for the work's own push
    outcome, contract = run_with_screens(checkout, **TWO)
    handoff = hand_off(plan, outcome, contract, client_factory=FakeGitHub().factory, screenshots=True)
    assert handoff is not None and f"contexer-evidence/c1-{handoff.commit[:8]}" in remote_heads(checkout)
    pushed = seen.read_text(encoding="utf-8")
    assert "refs/heads/contexer/c1" in pushed and "contexer-evidence" not in pushed


def test_in_actions_the_artifact_is_named_as_both_actions_upload_it(checkout: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from contexer.github.handoff import pull_request_body

    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    outcome, contract = run_with_screens(checkout, **TWO)
    body = pull_request_body(outcome, contract)
    # action.yml uploads `contexer-report`, issue/action.yml `contexer-report-issue-<n>-<attempt>`.
    assert "name starts with `contexer-report`" in body and "`contexer-report` artifact" not in body
    assert "https://github.com/acme/todo/actions/runs/42" in body


# -- which files count ----------------------------------------------------------------------------


def test_only_a_jpeg_inside_the_run_folder_counts_and_a_trace_never_does(checkout: Path, tmp_path: Path) -> None:  # noqa: F811
    outside = tmp_path / "elsewhere" / "shot.jpg"
    outside.parent.mkdir()
    outside.write_bytes(JPEG)
    env = checkout / ".env"
    env.write_text("SERVICE_KEY=made-up-value\n", encoding="utf-8")
    outcome, contract = run_with_screens(
        checkout,
        good=(True, "attempt-1/checks/c1/good.jpg"),
        outside=(True, str(outside)),
        dotenv=(False, str(env)),
        climbs=(True, "attempt-1/../../../../.env"),
    )  # fmt: skip
    run = Path(outcome.run_dir)
    renamed = run / "renamed.jpg"  # a text file with an image's name
    renamed.write_text("SERVICE_KEY=made-up-value\n", encoding="utf-8")
    png = run / "page.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    large = run / "large.jpg"
    large.write_bytes(JPEG + b"0" * MAX_IMAGE_BYTES)
    trace = run / "trace.jpg"  # even an image: a check's trace is never what is published
    trace.write_bytes(JPEG)
    assert outcome.final is not None and outcome.final.contracts[0].verification is not None
    rows = outcome.final.contracts[0].verification.criteria_results
    for name, path in (("renamed", renamed), ("png", png), ("large", large), ("missing", run / "gone.jpg")):
        rows.append(CriterionResult(criterion_id=name, description=name, passed=True, check_result=CheckResult(criterion_id=name, passed=True, screenshot=str(path))))
    rows.append(CriterionResult(criterion_id="traced", description="traced", passed=True, check_result=CheckResult(criterion_id="traced", passed=True, trace=str(trace))))

    shots = check_screenshots(outcome.final, contract.id, outcome.run_dir)
    assert [(s.check_id, s.name, s.passed) for s in shots] == [("good", "01-good.jpg", True)]
    assert shots[0].data.startswith(JPEG)
    assert check_screenshots(outcome.final, "another-contract", outcome.run_dir) == []
    assert check_screenshots(outcome.final, contract.id, "") == [] and check_screenshots(None, contract.id, outcome.run_dir) == []


def test_the_report_inlines_only_an_image_from_its_own_run_folder(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "r1"
    run.mkdir(parents=True)
    inside = run / "shot.jpg"
    inside.write_bytes(JPEG)
    outside = tmp_path / "shot.jpg"
    outside.write_bytes(JPEG)
    env = tmp_path / ".env"
    env.write_text("SERVICE_KEY=made-up-value\n", encoding="utf-8")
    renamed = run / "renamed.png"
    renamed.write_text("SERVICE_KEY=made-up-value\n", encoding="utf-8")
    assert _data_uri(str(inside), str(run)).startswith("data:image/jpeg;base64,")
    for path in (outside, env, renamed, run / ".." / ".." / ".env"):
        assert _data_uri(str(path), str(run)) == "", path
    assert _data_uri(str(env)) == "" and _data_uri(str(renamed)) == ""  # with no folder given, still only an image


# -- the switch -----------------------------------------------------------------------------------


def test_run_has_a_switch_for_screenshots_that_goes_with_a_pull_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLUMNS", "200")
    def plain(text: str) -> str:
        return re.sub(r"\x1b\[[0-9;]*m", "", text)  # CI colours the usage text

    shown = CliRunner().invoke(app, ["run", "--help"])
    assert "--screenshots" in plain(shown.output)
    refused = CliRunner().invoke(app, ["run", "Users can add a task", "--dir", str(tmp_path), "--screenshots"])
    assert refused.exit_code == 2 and "--pr" in plain(refused.output)


def test_the_switch_reaches_the_hand_off(checkout: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from contexer.cli import run_cli

    plan = plan_handoff(checkout)
    outcome, contract = run_with_screens(checkout, **TWO)
    asked: list[bool] = []
    monkeypatch.setattr(run_cli, "hand_off", lambda *_a, screenshots=False, **_k: asked.append(screenshots))
    for wanted in (True, False):
        with pytest.raises(typer.Exit):
            run_cli._finish(Console(quiet=True), outcome, contract, plan, True, None, False, screenshots=wanted)
    assert asked == [True, False]
    with pytest.raises(typer.Exit):
        run_cli._finish(Console(quiet=True), outcome, contract, plan, True, None, False)
    assert asked == [True, False, False]  # off unless asked
