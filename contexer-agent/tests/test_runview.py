"""The run view: what a person sees while `contexer run` works.

Two things are drawn from the same events. Lines that stay (an attempt, what the agent did, the verdict
with the checks that failed) read the same in a terminal, in a CI log and pasted into an issue. And, in
a terminal only, a block that is redrawn in place: every check with its state, what is happening now,
the time and the money.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console

from contexer.cli.runview import RunView
from contexer.graph.context import RunEvent

CHECKS = [
    {"id": "add", "description": "Adding a task shows it in the list", "executable": True},
    {"id": "count", "description": "Completing a task lowers the remaining count", "executable": True},
    {"id": "delete", "description": "Deleting a task removes it and lowers the count", "executable": True},
]


def _view(width: int = 100, verbose: bool = False) -> tuple[RunView, Console]:
    console = Console(record=True, width=width, force_terminal=False, color_system=None)
    return RunView(console, verbose=verbose), console


def _send(view: RunView, kind: str, message: str = "", at: float = 0.0, **data: Any) -> None:
    view.handle(RunEvent(kind, message, data, at))


def _first_attempt(view: RunView) -> None:
    _send(view, "checks", contract_id="todo", goal="A todo list", checks=CHECKS, earlier_checks=0)
    _send(view, "attempt-start", n=1, doing="implementing", fresh=False, agent="claude-code")
    _send(view, "phase", "Attempt 1: implementing with claude-code")
    _send(view, "agent", "Read app.js")
    _send(view, "agent", "Edit app.js")
    _send(view, "agent-done", "Agent done — 1 file(s) changed (23s, $0.65)", at=23, n=1, status="completed", seconds=23.0, cost_usd=0.65, files=1, spent_usd=0.65)
    _send(view, "phase", "Attempt 1: proving 3 checks in Chromium", n=1, proving=3)
    _send(
        view, "verdict", "Attempt 1: FAIL: 2 verified, 1 refuted, 0 unverified", at=31, n=1, outcome="fail", verified=2, refuted=1, unverified=0,
        checks=[
            {"id": "add", "verdict": "verified", "evidence": "Executed in browser"},
            {"id": "count", "verdict": "refuted", "evidence": 'expected text of [data-testid="remaining-count"] equals "0 left", got "1 left"'},
            {"id": "delete", "verdict": "verified", "evidence": "Executed in browser"},
        ],
        others_failing=0,
    )  # fmt: skip


def test_the_lines_that_stay_say_each_attempt_and_name_the_checks_that_failed() -> None:
    view, console = _view()
    _first_attempt(view)
    text = console.export_text()

    assert "Attempt 1 · implementing with claude-code" in text
    assert "1 file changed · 23s · $0.65" in text
    assert "2 of 3 checks proven · 1 failed" in text
    assert "Completing a task lowers the remaining count" in text and '"1 left"' in text  # the check that failed, and why
    assert "Adding a task shows it in the list" not in text  # a check that passed is not repeated in the log
    assert "Read app.js" not in text and "Edit app.js" not in text  # tool calls are for the live line, not the log


def test_verbose_keeps_the_agents_tool_calls_in_the_log() -> None:
    view, console = _view(verbose=True)
    _first_attempt(view)
    assert "Read app.js" in console.export_text()


def test_a_pass_is_one_line() -> None:
    view, console = _view()
    _send(view, "checks", contract_id="todo", goal="g", checks=CHECKS, earlier_checks=4)
    _send(view, "attempt-start", n=1, doing="implementing", fresh=False, agent="claude-code")
    _send(view, "verdict", "Attempt 1: PASS", n=1, outcome="pass", verified=7, refuted=0, unverified=0,
          checks=[{"id": c["id"], "verdict": "verified", "evidence": ""} for c in CHECKS], others_failing=0)  # fmt: skip
    text = console.export_text()
    assert "3 of 3 checks proven" in text and "4 earlier checks still pass" in text
    assert text.count("\n") <= 4


def test_what_this_change_broke_elsewhere_is_said() -> None:
    view, console = _view()
    _send(view, "checks", contract_id="todo", goal="g", checks=CHECKS, earlier_checks=4)
    _send(view, "attempt-start", n=1, doing="implementing", fresh=False, agent="x")
    _send(view, "verdict", "Attempt 1: FAIL", n=1, outcome="fail", verified=5, refuted=2, unverified=0,
          checks=[{"id": c["id"], "verdict": "verified", "evidence": ""} for c in CHECKS], others_failing=2)  # fmt: skip
    assert "2 earlier checks broke" in console.export_text()


def test_decisions_and_review_notes_are_lines_too() -> None:
    view, console = _view()
    _first_attempt(view)
    _send(view, "strategy", "Triage: fresh approach. The same check failed twice in the same way.", move="fresh_approach", source="model", n=1)
    _send(view, "strategy", move="repair_same_session", source="rules", n=1)  # the default move needs no line
    _send(view, "review", "Review: 2 note(s), 1 to fix", notes=2, to_fix=1, high=1)
    text = console.export_text()
    assert "fresh approach" in text and "failed twice" in text
    assert "Review: 2 note(s), 1 to fix" in text
    assert text.count("repair") == 0


def test_the_live_block_lists_every_check_with_its_state_and_what_is_happening_now() -> None:
    view, console = _view()
    _first_attempt(view)
    _send(view, "attempt-start", at=40, n=2, doing="repairing", fresh=False, agent="claude-code")
    _send(view, "phase", "Attempt 2: repairing with claude-code")
    _send(view, "agent", "Edit app.js")
    console.clear()
    block = Console(record=True, width=100, force_terminal=False, color_system=None)
    block.print(view.live_block(now=65.0))
    text = block.export_text()

    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    assert lines[0].startswith("Attempt 2 · repairing")
    assert any("Adding a task shows it in the list" in line for line in lines)  # all three checks, each on a line
    failing = next(line for line in lines if "Completing a task" in line)
    assert '"1 left"' in failing  # what the last attempt saw, next to the check it has to fix
    assert any("Agent working" in line and "1 tool call" in line and "Edit app.js" in line for line in lines)
    assert "1m 05s" in lines[-1] and "$0.65" in lines[-1]  # the footer: time and money so far


def test_before_the_first_verdict_every_check_is_waiting() -> None:
    view, _ = _view()
    _send(view, "checks", contract_id="todo", goal="g", checks=CHECKS, earlier_checks=0)
    _send(view, "attempt-start", n=1, doing="implementing", fresh=False, agent="claude-code")
    block = Console(record=True, width=100, force_terminal=False, color_system=None)
    block.print(view.live_block(now=3.0))
    text = block.export_text()
    assert text.count("Adding a task") == 1 and "proven" not in text and "$" not in text


def test_a_narrow_terminal_cuts_long_lines_instead_of_wrapping_them() -> None:
    view, _ = _view(width=50)
    long = [{"id": "x", "description": "A very long description of a behaviour that goes on and on past any sensible width", "executable": True}]
    _send(view, "checks", contract_id="todo", goal="g", checks=long, earlier_checks=0)
    _send(view, "attempt-start", n=1, doing="implementing", fresh=False, agent="claude-code")
    block = Console(record=True, width=50, force_terminal=False, color_system=None)
    block.print(view.live_block(now=1.0))
    lines = block.export_text().splitlines()
    assert all(len(line) <= 50 for line in lines) and sum("A very long" in line for line in lines) == 1


def test_many_checks_are_summarised_so_the_block_stays_on_one_screen() -> None:
    view, _ = _view()
    many = [{"id": f"c{n}", "description": f"Behaviour number {n}", "executable": True} for n in range(40)]
    _send(view, "checks", contract_id="todo", goal="g", checks=many, earlier_checks=0)
    _send(view, "attempt-start", n=1, doing="implementing", fresh=False, agent="claude-code")
    block = Console(record=True, width=100, force_terminal=False, color_system=None)
    block.print(view.live_block(now=1.0))
    text = block.export_text()
    assert len(text.splitlines()) <= 20 and "more" in text


def test_the_footer_shows_what_the_run_has_spent_not_the_last_turn_twice() -> None:
    view, _ = _view()
    _first_attempt(view)  # one turn at $0.65; the event carries the run's total so far
    _send(view, "attempt-start", at=40, n=2, doing="repairing", fresh=False, agent="claude-code")
    _send(view, "agent-done", "x", at=80, n=2, status="completed", seconds=30.0, cost_usd=0.50, files=1, spent_usd=1.15)
    block = Console(record=True, width=100, force_terminal=False, color_system=None)
    block.print(view.live_block(now=81.0))
    assert "$1.15" in block.export_text()


def test_a_tool_call_names_a_file_by_its_path_in_the_project(tmp_path) -> None:
    console = Console(record=True, width=100, force_terminal=False, color_system=None)
    view = RunView(console, project=tmp_path)
    _send(view, "checks", contract_id="todo", goal="g", checks=CHECKS, earlier_checks=0)
    _send(view, "attempt-start", n=1, doing="implementing", fresh=False, agent="claude-code")
    _send(view, "agent", f"Edit {tmp_path / 'src' / 'app.js'}")
    block = Console(record=True, width=100, force_terminal=False, color_system=None)
    block.print(view.live_block(now=2.0))
    text = block.export_text()
    assert "Edit src/app.js" in text and str(tmp_path) not in text


def test_while_the_checks_run_the_status_line_does_not_repeat_the_agents_last_tool_call() -> None:
    view, _ = _view()
    _send(view, "checks", contract_id="todo", goal="g", checks=CHECKS, earlier_checks=0)
    _send(view, "attempt-start", n=1, doing="implementing", fresh=False, agent="claude-code")
    _send(view, "agent", "Edit app.js")
    _send(view, "agent-done", "x", at=20, n=1, status="completed", seconds=20.0, cost_usd=0.5, files=1, spent_usd=0.5)
    _send(view, "phase", "Attempt 1: proving 3 checks in Chromium", at=21, n=1, proving=3)
    block = Console(record=True, width=100, force_terminal=False, color_system=None)
    block.print(view.live_block(now=25.0))
    text = block.export_text()
    assert "Proving 3 checks in Chromium" in text and "Edit app.js" not in text and "tool call" not in text
