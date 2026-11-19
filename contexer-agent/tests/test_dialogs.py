"""Browser dialogs in checks: a confirmation is something a check answers, not something the app must lose.

A real run passed every check by removing a "Delete this entry?" confirmation: the check clicked Delete,
the browser dismissed the dialog nobody answered, nothing was deleted, and the only way to pass was to
take the question away. A check can now answer the dialog, a dialog nobody answered is named in the
failure, and a confirmation that disappears from the diff is found by the review's scan.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from contexer.crew.reviewer import prescan
from contexer.verification.checks import Check
from contexer.verification.runner import CheckRunner
from contexer.workflow.app_server import StaticAppServer
from contexer.workflow.criteria import CHECK_DSL_GUIDE

pytestmark = pytest.mark.anyio

APP = """<!doctype html><html><head><meta charset="utf-8"><title>Entries</title></head><body>
<ul><li id="row">Headache <button id="del" aria-label="Delete Headache">Delete</button></li></ul>
<button id="hello">Say hello</button><p id="said"></p>
<script>
  document.getElementById("del").addEventListener("click", () => {
    if (confirm("Delete this symptom entry?")) document.getElementById("row").remove();
  });
  document.getElementById("hello").addEventListener("click", () => {
    alert("Saved."); document.getElementById("said").textContent = "said";
  });
</script></body></html>
"""
DELETE = {"action": "click", "target": {"role": "button", "name": "Delete Headache"}}
GONE = {"kind": "hidden", "target": {"text": "Headache"}}
STILL_THERE = {"kind": "visible", "target": {"text": "Headache"}}


@pytest.fixture
def app_url(tmp_path: Path):
    (tmp_path / "index.html").write_text(APP, encoding="utf-8")
    with StaticAppServer(tmp_path) as server:
        yield server.url


@pytest.fixture
def runner() -> CheckRunner:
    return CheckRunner(action_timeout=1.0, expect_timeout=1.0)


def check(steps: list[dict], expect: list[dict]) -> Check:
    return Check.model_validate({"steps": steps, "expect": expect})


async def test_a_check_can_accept_the_confirmation_the_next_step_opens(app_url: str, runner: CheckRunner) -> None:
    [result] = await runner.run(app_url, [("delete", check([{"action": "accept_dialog"}, DELETE], [GONE]))])
    assert result.passed, result.failure_report()
    assert result.dialogs == ['confirm "Delete this symptom entry?" (accepted)']


async def test_a_check_can_dismiss_it_and_the_entry_stays(app_url: str, runner: CheckRunner) -> None:
    [result] = await runner.run(app_url, [("keep", check([{"action": "dismiss_dialog"}, DELETE], [STILL_THERE]))])
    assert result.passed, result.failure_report()
    assert result.dialogs == ['confirm "Delete this symptom entry?" (dismissed)']


async def test_a_dialog_nobody_answered_is_dismissed_and_the_failure_says_so(app_url: str, runner: CheckRunner) -> None:
    [result] = await runner.run(app_url, [("delete", check([DELETE], [GONE]))])
    assert not result.passed
    assert result.dialogs == ['confirm "Delete this symptom entry?" (dismissed: no step of the check answered it)']
    report = result.failure_report()
    assert "Delete this symptom entry?" in report and "accept_dialog" in report  # what to change is the check, and it says so


async def test_an_answer_covers_one_dialog_only(app_url: str, runner: CheckRunner) -> None:
    again = {"action": "click", "target": {"role": "button", "name": "Say hello"}}
    [result] = await runner.run(
        app_url, [("two", check([{"action": "accept_dialog"}, again, again], [{"kind": "text", "target": {"css": "#said"}, "equals": "said"}]))]
    )
    assert result.passed  # an alert only has OK: answering it either way lets the page go on
    assert result.dialogs == ['alert "Saved." (accepted)', 'alert "Saved." (dismissed: no step of the check answered it)']


async def test_an_answer_no_dialog_came_for_fails_the_check(app_url: str, runner: CheckRunner) -> None:
    again = {"action": "click", "target": {"role": "button", "name": "Say hello"}}
    [result] = await runner.run(app_url, [("none", check([again, {"action": "accept_dialog"}], [{"kind": "visible", "target": {"css": "#said"}}]))])
    assert not result.passed
    assert "no dialog" in result.failure_report().lower()  # a check that expects a question the app never asks


def test_the_steps_read_as_words_and_take_no_target() -> None:
    steps = check([{"action": "accept_dialog"}, {"action": "dismiss_dialog"}, DELETE], [GONE]).steps
    assert steps[0].describe() == "accept the dialog the next step opens"
    assert steps[1].describe() == "dismiss the dialog the next step opens"
    with pytest.raises(ValidationError):
        check([DELETE, {"action": "answer_dialog"}], [GONE])


def test_the_agents_that_draft_checks_are_told_about_dialogs() -> None:
    assert "accept_dialog" in CHECK_DSL_GUIDE and "dismiss_dialog" in CHECK_DSL_GUIDE
    assert "before the step that opens it" in CHECK_DSL_GUIDE


def test_a_confirmation_removed_from_the_code_is_found_by_the_scan() -> None:
    removed = "\n".join(
        [
            "diff --git a/src/Symptoms.tsx b/src/Symptoms.tsx",
            "--- a/src/Symptoms.tsx",
            "+++ b/src/Symptoms.tsx",
            "@@ -40,3 +40,1 @@",
            '-            onClick={() => confirm("Delete this symptom entry?") && del.mutate(s.id)}',
            "+            onClick={() => del.mutate(s.id)}",
            "",
        ]
    )
    [note] = prescan(removed)
    assert (note.file, note.severity, note.category, note.backed) == ("src/Symptoms.tsx", "medium", "logic", True)
    assert "confirmation" in note.explanation and "accept_dialog" in note.explanation
    kept = removed.replace("+            onClick={() => del.mutate(s.id)}", '+            onClick={() => window.confirm("Delete?") && del.mutate(s.id)}')
    assert prescan(kept) == []  # reworded, still asked
