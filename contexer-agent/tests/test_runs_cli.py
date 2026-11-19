"""`contexer runs` lists verifications and agent runs from their evidence files."""

import json
import re
from pathlib import Path

from typer.testing import CliRunner

from contexer.cli import app


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_lists_newest_first_with_outcomes(tmp_path: Path) -> None:
    runs = tmp_path / ".contexer" / "runs"
    _write(
        runs / "20261015-100000-aaaa" / "result.json",
        {"decision": {"outcome": "fail", "verified": 6, "refuted": 1, "unverified": 0},
         "contracts": [{"contract": {"id": "todo-basics"}}]},
    )
    _write(
        runs / "20261015-110000-bbbb" / "run.json",
        {"terminal": "succeeded", "agent": "claude-code", "contract_id": "todo-basics",
         "attempts": [{}, {}], "cost_usd": 0.42},
    )
    (runs / "20261015-110000-bbbb" / "report.html").write_text("<html>", encoding="utf-8")
    (runs / "not-a-run").mkdir()

    result = CliRunner().invoke(app, ["runs", "--dir", str(tmp_path)], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    out = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    lines = [line for line in out.splitlines() if line.startswith("2026")]
    assert lines[0].startswith("20261015-110000-bbbb") and "succeeded" in lines[0] and "$0.42" in lines[0]
    assert lines[1].startswith("20261015-100000-aaaa") and "fail" in lines[1] and "6✓ 1✗ 0?" in lines[1]
    assert len(lines) == 2


def test_no_runs_says_how_to_start(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["runs", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "No runs yet" in result.output


def test_stats_say_how_runs_ended_and_what_a_proven_run_cost(tmp_path: Path) -> None:
    from contexer.cli.runs_cli import run_stats

    runs = tmp_path / ".contexer" / "runs"
    note = {"severity": "high", "category": "logic", "backed": False}
    _write(runs / "20261101-100000-aaaa" / "run.json", {"terminal": "succeeded", "attempts": [{}], "cost_usd": 1.0, "crew_cost_usd": 0.1,
                                                        "duration_seconds": 100, "review": [], "engine": "graph"})
    _write(runs / "20261101-110000-bbbb" / "run.json", {"terminal": "succeeded", "attempts": [{}, {}, {}], "cost_usd": 3.0, "crew_cost_usd": None,
                                                        "duration_seconds": 300, "review": [note, {**note, "severity": "low"}], "engine": "graph"})
    _write(runs / "20261101-120000-cccc" / "run.json", {"terminal": "failed_checks", "attempts": [{}, {}, {}], "cost_usd": 6.0,
                                                        "duration_seconds": 400, "engine": "graph"})
    _write(runs / "20261101-130000-dddd" / "run.json", {"terminal": "needs_human", "attempts": [], "cost_usd": 0.0, "duration_seconds": 5})
    _write(runs / "20261101-140000-eeee" / "result.json", {"decision": {"outcome": "pass"}})  # a verification, not an agent run
    (runs / "20261101-150000-ffff").mkdir()
    (runs / "20261101-150000-ffff" / "run.json").write_text("{not json", encoding="utf-8")

    stats = run_stats(tmp_path)
    assert (stats.runs, stats.succeeded) == (4, 2)
    assert stats.endings == {"succeeded": 2, "failed_checks": 1, "needs_human": 1}
    assert stats.first_try == 1 and stats.attempts_per_success == 2.0
    assert stats.cost_usd == 10.1 and stats.cost_per_success == 5.05  # everything spent, over what was proven
    assert stats.spent_without_proof == 6.0
    assert stats.runs_with_high_note == 1 and stats.median_seconds == 200

    result = CliRunner().invoke(app, ["runs", "--stats", "--dir", str(tmp_path)], env={"COLUMNS": "200"})
    out = " ".join(re.sub(r"\x1b\[[0-9;]*m", "", result.output).split())
    assert result.exit_code == 0, result.output
    assert "2 of 4 runs ended with every check proven" in out and "$5.05 per proven run" in out
    assert "failed_checks 1" in out and "$6.00 spent on runs that proved nothing" in out


def test_stats_with_no_runs_say_so(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["runs", "--stats", "--dir", str(tmp_path)])
    assert result.exit_code == 0 and "No agent runs" in result.output
