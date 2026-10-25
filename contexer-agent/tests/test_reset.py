"""`[app] reset` runs before every check, so checks don't see each other's server-side data."""

import shutil
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from contexer.appserver.reset import reset_command, run_reset
from contexer.cli import app
from contexer.gate.models import RunResult

FIXTURE = Path(__file__).resolve().parents[1] / "bench" / "fixtures" / "todo"
PYTHON = f'"{sys.executable}"'  # a path with spaces on many machines, so it must be quoted


def test_reset_command_fills_in_the_running_app() -> None:
    assert reset_command("curl -X POST {url}/api/reset", "http://127.0.0.1:5173/") == (
        "curl -X POST http://127.0.0.1:5173/api/reset"
    )
    assert reset_command("npm run db:reset -- --port {port}", "http://127.0.0.1:5173/") == (
        "npm run db:reset -- --port 5173"
    )


def test_run_reset_reports_success_failure_and_output(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text("open('done.txt', 'w').write('1')\n", encoding="utf-8")
    (tmp_path / "bad.py").write_text("print('database is locked'); raise SystemExit(3)\n", encoding="utf-8")
    assert run_reset(f"{PYTHON} ok.py", tmp_path) is None
    assert (tmp_path / "done.txt").read_text() == "1"
    problem = run_reset(f"{PYTHON} bad.py", tmp_path)
    assert problem is not None and "exited with code 3" in problem and "database is locked" in problem


@pytest.fixture
def todo_app(tmp_path: Path) -> Path:
    target = tmp_path / "todo"
    shutil.copytree(FIXTURE / "app", target, ignore=shutil.ignore_patterns("runs"))
    return target


def _replay(project: Path) -> tuple[int, RunResult]:
    result = CliRunner().invoke(app, ["replay", "--dir", str(project), "--trace", "off"])
    run = sorted((project / ".contexer" / "runs").iterdir())[-1]
    return result.exit_code, RunResult.model_validate_json((run / "result.json").read_text(encoding="utf-8"))


def test_reset_runs_before_every_check(todo_app: Path) -> None:
    (todo_app / "reset.py").write_text("open('resets.txt', 'a').write('x')\n", encoding="utf-8")
    (todo_app / "contexer.toml").write_text(f"[app]\nreset = '{PYTHON} reset.py'\n", encoding="utf-8")
    code, result = _replay(todo_app)

    assert code == 0, result.decision.reasons
    checks = sum(len(o.verification.criteria_results) for o in result.contracts if o.verification)
    assert (todo_app / "resets.txt").read_text() == "x" * checks


def test_a_failing_reset_blocks_the_checks_without_refuting_them(todo_app: Path) -> None:
    (todo_app / "reset.py").write_text("print('cannot reach the database'); raise SystemExit(1)\n", encoding="utf-8")
    (todo_app / "contexer.toml").write_text(f"[app]\nreset = '{PYTHON} reset.py'\n", encoding="utf-8")
    code, result = _replay(todo_app)

    assert code == 2 and result.decision.outcome == "needs_action"
    assert result.decision.refuted == 0
    assert any("[app] reset" in r and "cannot reach the database" in r for r in result.decision.reasons)
