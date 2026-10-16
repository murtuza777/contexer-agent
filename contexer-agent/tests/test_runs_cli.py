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
