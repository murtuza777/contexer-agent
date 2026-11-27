"""`contexer run --plain`: the run for a CI log, a pipe and a screen reader.

No colour, nothing redrawn, no symbols that carry meaning: a mark is a word (`ok:`, `not ok:`,
`warning:`), a separator is a comma, and a line is as long as what it says, so nothing is wrapped.
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from contexer.cli import app as cli
from contexer.cli import run_cli, term
from contexer.cli.runview import RunView
from contexer.graph.context import RunEvent
from tests.loop_helpers import CONTRACT_ID, COUNT_BUG_JS, GOOD_JS, copy_todo

CHECKS = [
    {"id": "add", "description": "Adding a task shows it in the list", "executable": True},
    {"id": "count", "description": "Completing a task lowers the remaining count", "executable": True},
]


@pytest.fixture(autouse=True)
def unicode_marks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(term, "_encodable", lambda char: True)  # the marks a UTF-8 terminal gets


def _plain_console() -> tuple[Any, io.StringIO]:
    out = io.StringIO()
    return term.plain_console(out), out


def test_a_plain_console_says_marks_as_words_and_separators_as_commas() -> None:
    console, out = _plain_console()
    term.header(console, "run", "A todo list")
    term.note(console, "warn", "The draft is weak")
    console.print(f"{term.mark('pass')} [green]3 of 3 checks proven[/] [dim]·[/] 4 earlier checks still pass")
    console.print(f"  {term.mark('fail')} [red]1 of 3 checks proven[/]")
    console.print(f"  {term.mark('open')} [yellow]2 of 3 checks proven[/]")
    term.bullets(console, ["The app has one user"])
    term.fields(console, [("Report", "runs/1/report.html"), ("Took", "12s · $0.10 agent spend")])
    lines = out.getvalue().splitlines()
    assert "contexer run, A todo list" in lines
    assert "warning: The draft is weak" in lines
    assert "ok: 3 of 3 checks proven, 4 earlier checks still pass" in lines
    assert "  not ok: 1 of 3 checks proven" in lines and "  open: 2 of 3 checks proven" in lines
    assert "  - The app has one user" in lines
    assert "  Took        12s, $0.10 agent spend" in lines
    assert term.is_plain(console) and out.getvalue().isascii() and "\x1b" not in out.getvalue()
    assert all(line == line.rstrip() for line in lines)  # no padding at the end of a line


def test_a_plain_console_does_not_wrap_a_long_line() -> None:
    console, out = _plain_console()
    long = "word " * 200
    term.fields(console, [("Report", long.strip())])
    assert long.strip() in out.getvalue()


def test_the_run_view_on_a_plain_console_is_one_line_per_event_and_draws_no_block() -> None:
    console, out = _plain_console()
    view = RunView(console, max_attempts=3)

    def send(kind: str, message: str = "", at: float = 0.0, **data: Any) -> None:
        view.handle(RunEvent(kind, message, data, at))

    send("checks", contract_id="todo", goal="A todo list", checks=CHECKS, earlier_checks=0)
    send("phase-quiet", "Reading the project to plan the work")
    send("attempt-start", n=1, doing="implementing", fresh=False, agent="claude-code")
    send("agent", "Edit app.js")
    send("agent-done", "x", at=23, n=1, status="completed", seconds=23.0, cost_usd=0.65, files=1, spent_usd=0.65)
    send("phase", "Attempt 1: proving 2 checks in Chromium", n=1, proving=2)
    send(
        "verdict", "Attempt 1: FAIL", at=31, n=1, outcome="fail",
        checks=[
            {"id": "add", "verdict": "verified", "evidence": "Executed in browser"},
            {"id": "count", "verdict": "refuted", "evidence": 'expected "0 left", got "1 left"'},
        ],
        others_failing=0,
    )  # fmt: skip
    send("strategy", "Triage: fresh approach. The same check failed twice.", n=1)
    assert view._live is None  # nothing is redrawn
    lines = [line for line in out.getvalue().splitlines() if line.strip()]
    assert lines == [
        "  Reading the project to plan the work",
        "> Attempt 1, implementing with claude-code",
        "  1 file changed, 23s, $0.65",
        "  not ok: 1 of 2 checks proven, 1 failed",
        '      not ok: Completing a task lowers the remaining count: expected "0 left", got "1 left"',
        "  warning: Triage: fresh approach. The same check failed twice.",
    ]


# -- the command -------------------------------------------------------------------------------------


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("CONTEXER_ENGINE", raising=False)
    monkeypatch.setattr(run_cli, "compiler_llm", lambda *_a, **_k: None)
    monkeypatch.setattr(run_cli, "crew_model", lambda *_a, **_k: None)
    return copy_todo(tmp_path)


def _run(project: Path, tmp_path: Path, *args: str) -> Any:
    turns = tmp_path / "turns.json"
    turns.write_text(json.dumps([{"app.js": COUNT_BUG_JS}, {"app.js": GOOD_JS}]), encoding="utf-8")
    return CliRunner().invoke(
        cli, ["run", "--dir", str(project), "--agent", "scripted", "--model", str(turns), "--contract", CONTRACT_ID, *args]
    )


def test_a_plain_run_is_ascii_lines_with_no_colour_no_redraw_and_no_wrapping(project: Path, tmp_path: Path) -> None:
    result = _run(project, tmp_path, "--plain")
    out = result.output
    assert result.exit_code == 0, out
    assert out.isascii() and "\x1b" not in out and "\r" not in out.replace("\r\n", "\n")
    lines = out.splitlines()
    assert any(line.startswith("contexer run, ") for line in lines)
    assert "> Attempt 1, implementing with scripted" in lines and "> Attempt 2, repairing with scripted" in lines
    assert any(re.fullmatch(r"  not ok: \d+ of \d+ checks proven, \d+ failed", line) for line in lines), out
    assert any(line.startswith("ok: Succeeded, ") for line in lines)
    # A long value is one line: the path of the report is not folded at 80 columns.
    [report] = [line for line in lines if line.lstrip().startswith("Report")]
    assert report.endswith("report.html")
    assert all(line == line.rstrip() for line in lines)


def test_plain_and_json_are_two_forms_of_output_and_one_is_chosen(project: Path, tmp_path: Path) -> None:
    result = _run(project, tmp_path, "--plain", "--json", "--yes")
    assert result.exit_code == 2 and "--plain" in result.output and "--json" in result.output
    assert not (project / ".contexer" / "runs").exists()


def test_an_error_of_a_plain_run_has_no_box_around_it(project: Path, tmp_path: Path) -> None:
    result = _run(project, tmp_path, "--plain", "--correct", "Make it blue")
    assert result.exit_code == 2 and "--correct" in result.output
    assert result.output.isascii(), result.output
