"""The reviewer benchmark: diffs with one planted issue each, and clean diffs that must not raise an alarm."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import HumanMessage
from typer.testing import CliRunner

from contexer.bench.reviewer import case_diff, discover_cases, results_markdown, run_reviewer_bench
from contexer.cli import app as cli
from contexer.crew.reviewer import changed_files
from tests.fakes import ScriptedChatModel, submit

pytestmark = pytest.mark.anyio

CASES = Path(__file__).resolve().parents[1] / "bench" / "reviewer"


def test_there_are_ten_planted_and_ten_clean_cases_and_each_is_a_real_diff() -> None:
    cases = discover_cases(CASES)
    planted = [c for c in cases if c.planted is not None]
    assert len(planted) == 10 and len(cases) - len(planted) == 10
    for case in cases:
        diff = case_diff(case)
        assert diff.strip(), case.name
        if case.planted is not None:
            assert case.planted.file in changed_files(diff), case.name  # the issue is in a file the diff touches


async def test_the_scan_alone_flags_what_it_can_see_and_is_quiet_on_clean_diffs() -> None:
    seen: list[str] = []
    report = await run_reviewer_bench(CASES, None, on_case=lambda run: seen.append(run.name))

    cases = {c.name: c for c in discover_cases(CASES)}
    assert len(seen) == 20 and report.agent == "scan"
    for run in report.runs:
        case = cases[run.name]
        if case.planted is not None:
            assert run.flagged == case.planted.scan, run.name  # each case says whether a scan can see it
            assert run.flagged_by == ("scan" if run.flagged else "")
        else:
            assert run.false_high == 0, (run.name, run.notes)
    assert (report.planted, report.clean, report.false_high_notes, report.clean_with_high) == (10, 10, 0, 0)
    assert report.flagged == sum(1 for c in cases.values() if c.planted is not None and c.planted.scan)
    assert report.flagged < 10  # wrong logic is not something a pattern finds; that is the model's part


async def test_a_models_note_counts_only_on_the_planted_file_and_a_high_note_on_clean_code_is_a_false_alarm(tmp_path: Path) -> None:
    def answer(messages: list[Any]) -> Any:
        task = next(m for m in messages if isinstance(m, HumanMessage)).text
        if "src/list.js" in task and "number * PAGE_SIZE" in task:  # the off-by-one case
            return submit(notes=[{"file": "src/list.js", "line": 4, "severity": "high", "category": "logic", "explanation": "Page 1 skips the first ten."}])
        if "gap: 12px" in task:  # a clean case
            return submit(notes=[{"file": "src/cart.css", "line": 1, "severity": "high", "category": "security", "explanation": "Not a real problem."}])
        return submit(notes=[])

    model = ScriptedChatModel(*[answer] * 4)
    report = await run_reviewer_bench(CASES, model, only=["off-by-one-page", "clean-style-only", "user-text-as-html", "clean-rename"])

    runs = {r.name: r for r in report.runs}
    assert runs["off-by-one-page"].flagged and runs["off-by-one-page"].flagged_by == "reviewer"
    assert not runs["user-text-as-html"].flagged  # the model said nothing: a miss, counted as one
    assert runs["clean-style-only"].false_high == 1 and runs["clean-rename"].false_high == 0
    assert (report.planted, report.flagged, report.clean, report.clean_with_high, report.false_high_notes) == (2, 1, 2, 1, 1)
    assert report.agent == "reviewer" and report.tokens_in > 0

    text = results_markdown(report)
    assert "| 2 | 1 |" in text and "off-by-one-page" in text and "user-text-as-html" in text
    assert "clean-style-only" in text  # the false alarm is named


async def test_repeats_review_every_case_again_and_the_results_give_each_rate_its_interval() -> None:
    from contexer.bench.stats import Rate

    report = await run_reviewer_bench(CASES, None, only=["secret-in-source", "off-by-one-page", "clean-rename"], repeats=3)

    assert [(r.name, r.repeat) for r in report.runs][:4] == [
        ("clean-rename", 0), ("off-by-one-page", 0), ("secret-in-source", 0), ("clean-rename", 1),
    ]  # fmt: skip
    assert (report.planted, report.flagged, report.clean, report.clean_with_high) == (6, 3, 3, 0)
    assert (report.repeats, report.suite) == (3, "reviewer")
    assert report.rates() == {"planted issues flagged": Rate(3, 6), "clean diffs with a false high": Rate(0, 3)}

    text = results_markdown(report)
    assert "Each case ran 3 times" in text
    assert "planted issues flagged 3/6, 50% (95% interval 19% to 81%)" in text
    assert "clean diffs with a false high 0/3, 0% (95% interval 0% to 56%)" in text
    assert "Not flagged: `off-by-one-page`." in text  # named once, not once per repeat
    assert "Flagged: `secret-in-source` (scan)." in text


def test_the_command_repeats_the_reviewer_suite(tmp_path: Path) -> None:
    shutil.copytree(CASES, tmp_path / "reviewer")
    (tmp_path / "fixtures").mkdir()
    out = tmp_path / "reviewer.json"
    result = CliRunner().invoke(
        cli,
        ["bench", "--suite", "reviewer", "--agent", "scan", "--fixtures", str(tmp_path / "fixtures"), "--repeats", "2",
         "--out", str(out), "--compare", str(CASES.parent / "does-not-exist.json")],
    )  # fmt: skip
    assert result.exit_code == 2  # the report to compare with is looked for first

    result = CliRunner().invoke(
        cli,
        ["bench", "--suite", "reviewer", "--agent", "scan", "--fixtures", str(tmp_path / "fixtures"), "--repeats", "2", "--out", str(out)],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    data = json.loads(out.read_text(encoding="utf-8"))
    assert (data["planted"], data["flagged"], data["clean"], data["repeats"]) == (20, 8, 20, 2)
    assert "planted issues flagged 8/20, 40% (95% interval 22% to 61%)" in " ".join(result.output.split())


async def test_an_unknown_case_is_an_error() -> None:
    with pytest.raises(ValueError, match="no case"):
        await run_reviewer_bench(CASES, None, only=["does-not-exist"])


def test_the_command_runs_the_reviewer_suite_with_the_scan_and_writes_the_report(tmp_path: Path) -> None:
    shutil.copytree(CASES, tmp_path / "reviewer")  # a whole run writes its results page next to the cases
    (tmp_path / "fixtures").mkdir()
    out = tmp_path / "reviewer.json"
    result = CliRunner().invoke(
        cli, ["bench", "--suite", "reviewer", "--agent", "scan", "--fixtures", str(tmp_path / "fixtures"), "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["planted"] == 10 and data["clean"] == 10 and data["false_high_notes"] == 0
    assert out.with_suffix(".md").is_file()
    assert "| 10 | 4 |" in (tmp_path / "reviewer-results" / "scan.md").read_text(encoding="utf-8")
