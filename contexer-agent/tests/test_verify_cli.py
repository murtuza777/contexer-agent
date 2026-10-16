"""End to end: `contexer verify` / `replay` against a real static app, exit codes and evidence."""

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from contexer.cli import app
from contexer.contract import ContractStore
from contexer.evidence.report import render_report
from contexer.gate.models import RunResult

FIXTURE = Path(__file__).resolve().parents[1] / "bench" / "fixtures" / "todo"


@pytest.fixture
def todo_app(tmp_path: Path) -> Path:
    target = tmp_path / "todo"
    shutil.copytree(FIXTURE / "app", target, ignore=shutil.ignore_patterns("runs"))
    return target


def _invoke(*args: str):
    return CliRunner().invoke(app, list(args))


def _latest_run(project: Path) -> Path:
    runs = sorted((project / ".contexer" / "runs").iterdir())
    return runs[-1]


def test_replay_passes_on_the_good_app_and_writes_evidence(todo_app: Path) -> None:
    result = _invoke("replay", "--dir", str(todo_app), "--trace", "off")
    assert result.exit_code == 0, result.output

    run = _latest_run(todo_app)
    data = json.loads((run / "result.json").read_text(encoding="utf-8"))
    assert data["decision"]["outcome"] == "pass"
    assert data["decision"]["verified"] == 7
    assert "html" not in (data.get("load") or {})  # bulky page capture stays out of result.json

    report = (run / "report.html").read_text(encoding="utf-8")
    assert "Pass" in report and "data:image/jpeg;base64," in report


def test_verify_exits_1_and_reports_expected_vs_actual_on_a_real_bug(todo_app: Path) -> None:
    shutil.copyfile(FIXTURE / "bugs" / "count-ignores-done" / "app.js", todo_app / "app.js")
    result = _invoke("verify", "--contract", "todo-basics", "--dir", str(todo_app), "--json")
    assert result.exit_code == 1, result.output

    run = _latest_run(todo_app)
    loaded = RunResult.model_validate_json((run / "result.json").read_text(encoding="utf-8"))
    refuted = [
        r.criterion_id
        for o in loaded.contracts
        for r in (o.verification.criteria_results if o.verification else [])
        if r.verdict == "refuted"
    ]
    assert refuted == ["complete-decrements"]
    report = render_report(loaded)
    assert "Expected" in report and "2 left" in report


def test_modified_contract_needs_action(todo_app: Path) -> None:
    store = ContractStore(todo_app)
    contract = store.load("todo-basics")
    contract.goal = contract.goal + " (edited)"
    store.save(contract)
    result = _invoke("replay", "--dir", str(todo_app), "--trace", "off")
    assert result.exit_code == 2, result.output


def test_verify_needs_a_goal_or_contract(todo_app: Path) -> None:
    result = _invoke("verify", "--dir", str(todo_app))
    assert result.exit_code != 0


def test_weak_rule_based_draft_is_flagged_before_approval() -> None:
    import io

    from rich.console import Console

    from contexer.cli.gate_cli import warn_if_weak_draft
    from contexer.contract import Contract

    out = io.StringIO()
    console = Console(file=out, width=120)
    warn_if_weak_draft(console, Contract(id="x", goal="g", source="rules"))
    assert "Weak draft" in out.getvalue()

    out.truncate(0)
    warn_if_weak_draft(console, Contract(id="y", goal="g", source="llm"))
    assert out.getvalue() == ""
