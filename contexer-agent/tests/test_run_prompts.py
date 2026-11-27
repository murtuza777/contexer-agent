"""What the coding agent was asked is kept (OBS-2): one file per attempt, masked, shown in the report.

The prompt holds text from the app and can hold page content. It is evidence: it stays in the run
folder, which no snapshot and so no hand-off ever holds.
"""

from pathlib import Path

import pytest

from contexer.checkpoint import ShadowRepo
from contexer.controller import RunSettings
from contexer.evidence.report import render_report
from contexer.evidence.rundir import PROMPT_FILE
from contexer.evidence.test_report import ConfirmedFinding, ExplorationResult, render_test_report
from contexer.gate.models import AgentRunSummary, AttemptRow, GateDecision, RunResult
from contexer.graph import GraphController
from contexer.verification.checks import MASK
from tests.loop_helpers import COUNT_BUG_JS, GOOD_JS, RecordingAgent, contract, copy_todo, fast_runner

MADE_UP_TOKEN = "made-up-token-0123456789"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


@pytest.mark.anyio
async def test_each_attempts_prompt_is_kept_masked_and_shown_in_the_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = copy_todo(tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", MADE_UP_TOKEN)
    # The page shows a token next to the count, so what the browser saw, and with it the repair prompt, holds it.
    leaking = COUNT_BUG_JS.replace("${left} left", "${left} left " + MADE_UP_TOKEN)
    assert leaking != COUNT_BUG_JS
    agent = RecordingAgent([{"app.js": leaking}, {"app.js": GOOD_JS}])
    outcome = await GraphController(project, agent, RunSettings(max_repair_rounds=2), runner=fast_runner()).run(contract(project))

    assert outcome.terminal == "succeeded", outcome.reason
    run_dir = Path(outcome.run_dir)
    first = (run_dir / "attempt-1" / PROMPT_FILE).read_text(encoding="utf-8")
    second = (run_dir / "attempt-2" / PROMPT_FILE).read_text(encoding="utf-8")
    assert first == agent.prompts[0]  # word for word what was sent
    assert "complete-decrements" in second and MADE_UP_TOKEN not in second
    assert second == agent.prompts[1].replace(MADE_UP_TOKEN, MASK)

    report = (run_dir / "report.html").read_text(encoding="utf-8")
    assert report.count("What the coding agent was asked") == 2
    assert "complete-decrements" in report and f"attempt-2/{PROMPT_FILE}" in report
    assert MADE_UP_TOKEN not in report

    # No snapshot holds the run folder, so the files a hand-off commits (what changed between snapshots) never include it.
    shadow = ShadowRepo(project)
    assert not [p for p in shadow.changed_paths(outcome.attempts[0].snapshot, shadow.snapshot()) if ".contexer" in p]


def _report(run: Path, attempts: list[int]) -> str:
    summary = AgentRunSummary(agent="scripted", terminal="failed_checks", attempts=[AttemptRow(n=n, kind="repair") for n in attempts])
    result = RunResult(
        run_id="r1", project_dir=str(run), started_at="", decision=GateDecision(outcome="fail"), contracts=[],
        contexer_version="0", run_dir=str(run), agent_run=summary,
    )  # fmt: skip
    return render_report(result)


def test_the_report_shows_a_prompt_as_text_and_only_where_one_was_kept(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "r1"
    (run / "attempt-1").mkdir(parents=True)
    (run / "attempt-1" / PROMPT_FILE).write_text("Fix it. <script>alert(1)</script>", encoding="utf-8")
    (run / "attempt-2").mkdir()  # a run from before prompts were kept, or a turn that never began
    report = _report(run, [1, 2])
    assert report.count("What the coding agent was asked") == 1
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in report and "<script>alert" not in report


def test_a_prompt_file_that_is_a_link_out_of_the_run_folder_is_not_shown(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "r1"
    (run / "attempt-1").mkdir(parents=True)
    outside = tmp_path / ".env"
    outside.write_text("SERVICE_KEY=made-up-value\n", encoding="utf-8")
    try:
        (run / "attempt-1" / PROMPT_FILE).symlink_to(outside)
    except OSError:
        pytest.skip("this account cannot create a link")
    assert "made-up-value" not in _report(run, [1])


def test_a_very_long_prompt_is_cut_in_the_report_and_says_so(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "r1"
    (run / "attempt-1").mkdir(parents=True)
    (run / "attempt-1" / PROMPT_FILE).write_text("start " + "x" * 300_000 + " the-end", encoding="utf-8")
    report = _report(run, [1])
    assert "start " in report and "the-end" not in report and "the whole text is in" in report


def test_the_test_report_inlines_only_an_image_from_its_own_run_folder(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "r1"
    run.mkdir(parents=True)
    (run / "inside.jpg").write_bytes(JPEG)
    (tmp_path / "outside.jpg").write_bytes(JPEG)

    def report(screenshot: Path) -> str:
        bug = ConfirmedFinding(title="t", criterion_id="c1", check=["goto /"], evidence="e", screenshot=str(screenshot))
        return render_test_report(ExplorationResult(intent="i", outcome="bugs", bugs=[bug], run_id="r1", project_dir=str(tmp_path), run_dir=str(run)))

    assert "data:image/jpeg;base64," in report(run / "inside.jpg")
    assert "data:image" not in report(tmp_path / "outside.jpg")
