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


def test_draft_shows_how_its_checks_fare_on_the_app_before_approval(
    todo_app: Path, monkeypatch: pytest.MonkeyPatch, fake_llm
) -> None:
    from contexer.cli import gate_cli

    add_a = [
        {"action": "fill", "target": {"placeholder": "What needs doing?"}, "value": "A"},
        {"action": "click", "target": {"role": "button", "name": "Add"}},
    ]
    reply = json.dumps(
        {
            "summary": "todo",
            "acceptance_criteria": [
                {"id": "shows-task", "description": "Adding shows the task",
                 "check": {"steps": add_a, "expect": [{"kind": "visible", "target": {"text": "A"}}]}},
                {"id": "wrong-count", "description": "A made-up count",
                 "check": {"steps": add_a,
                           "expect": [{"kind": "text", "target": {"test_id": "remaining-count"}, "equals": "5 left"}]}},
                {"id": "archive-all", "description": "Archive all tasks (not built yet)",
                 "check": {"steps": [{"action": "click", "target": {"role": "button", "name": "Archive all"}}],
                           "expect": [{"kind": "count", "target": {"role": "listitem"}, "max": 0}]}},
            ],
        }
    )
    monkeypatch.setattr(gate_cli, "compiler_llm", lambda *_: fake_llm(reply))
    result = _invoke("contract", "draft", "Users can archive all tasks", "--dir", str(todo_app), "--id", "archive")

    assert result.exit_code == 0, result.output
    out = " ".join(result.output.split())
    assert "Tried on the app as it is now" in out
    assert "already pass" in out and "shows-task" in out
    assert "1 fail" in out and "wrong-count" in out and "5 left" in out
    assert "1 could not run" in out and "archive-all" in out
    # The preview informs the reviewer; it never approves anything.
    assert ContractStore(todo_app).load("archive").status == "draft"


FREE_TIER_429 = "OpenRouter rate limit or credits exceeded: Rate limit exceeded: free-models-per-day. Add 10 credits"


def test_a_rate_limited_draft_says_why_and_is_never_auto_approved(
    todo_app: Path, monkeypatch: pytest.MonkeyPatch, fake_llm
) -> None:
    from contexer.cli import run_cli
    from contexer.llm.base import LLMRateLimitError

    monkeypatch.setattr(run_cli, "compiler_llm", lambda *_: fake_llm(LLMRateLimitError(FREE_TIER_429)))
    result = _invoke("run", "Users can archive all tasks", "--dir", str(todo_app), "--yes")

    assert result.exit_code == 2, result.output
    out = " ".join(result.output.split())
    assert "Weak draft" in out and "free-models-per-day" in out
    assert "daily free-model limit is used up" in out
    assert "--yes never approves a weak draft" in out
    drafts = [c for c in ContractStore(todo_app).list() if c.id != "todo-basics"]
    assert [c.status for c in drafts] == ["draft"]  # kept for review, not approved


def test_an_agent_without_credit_gets_a_way_forward(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import shutil as _shutil

    from contexer.cli.run_cli import agent_hint
    from contexer.controller.run import RunOutcome

    no_credit = RunOutcome(
        run_id="r", contract_id="c", agent="claude-code", terminal="agent_error",
        reason="The coding agent did not complete: api_error: Credit balance is too low",
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(_shutil, "which", lambda name: "opencode" if name == "opencode" else None)
    assert "--agent opencode" in (agent_hint(no_credit) or "")
    monkeypatch.setattr(_shutil, "which", lambda name: None)
    assert "npm i -g opencode-ai" in (agent_hint(no_credit) or "")
    monkeypatch.delenv("OPENROUTER_API_KEY")
    assert "--agent" in (agent_hint(no_credit) or "")
    # Other failures (a real bug in the work) get no account hint.
    failed = no_credit.model_copy(update={"terminal": "failed_checks", "reason": "Not all checks passed"})
    assert agent_hint(failed) is None
