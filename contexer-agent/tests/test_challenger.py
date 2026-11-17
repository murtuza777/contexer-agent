"""The Challenger: a second look at each confirmed bug that can set one aside, and can never add one.

It exists because of a measured failure. On a held-out app the Tester booked one slot, clicked a second
without typing a name again, was told "Enter your name" by the app, and reported "booking a second slot
fails". The finding replays every time, so replay alone confirmed it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import HumanMessage

from contexer.browser.freeze import Confirmed
from contexer.crew.budget import Budget
from contexer.crew.challenger import challenge
from contexer.crew.tester import Finding
from contexer.verification.checks import Check, CheckResult, ExpectationOutcome
from tests.fakes import ScriptedChatModel, submit

pytestmark = pytest.mark.anyio

INTENT = "Visitors can book a free time slot with their name; a name is required"


def _confirmed(title: str, steps: list[dict[str, Any]], messages: list[str] | None = None) -> Confirmed:
    expectation = {"kind": "text", "target": {"test_id": "slot-1000"}, "contains": "Booked by Bob"}
    finding = Finding.model_validate(
        {"kind": "bug", "title": title, "steps": steps, "expectation": expectation, "observed": '"10:00 · Free"', "messages": messages or []}
    )
    result = CheckResult(
        criterion_id="x",
        passed=False,
        outcomes=[ExpectationOutcome(description="text of slot-1000 contains Booked by Bob", passed=False, actual='"10:00 · Free"')],
    )
    return Confirmed(finding=finding, check=Check(steps=finding.steps, expect=[finding.expectation]), criterion_id="x", result=result)


FILL = {"action": "fill", "target": {"label": "Your name"}, "value": "Bob"}
BOOK_9 = {"action": "click", "target": {"role": "button", "name": "Book 09:00"}}
BOOK_10 = {"action": "click", "target": {"role": "button", "name": "Book 10:00"}}

# The measured false alarm: no name was typed before the second booking, and the app said so.
SKIPPED_NAME = _confirmed("Booking a second slot fails after the first booking", [FILL, BOOK_9, BOOK_10], ["Enter your name"])
# A real bug: the name was typed and the slot still was not booked.
REAL = _confirmed("Booking a slot with a name does not book it", [FILL, BOOK_10])


async def test_a_finding_whose_steps_skipped_a_stated_condition_is_set_aside_with_the_reason(tmp_path: Path) -> None:
    model = ScriptedChatModel(
        submit(
            verdicts=[
                {"finding": 1, "verdict": "tester_error", "reason": "No name was entered before the second booking; the app asked for one."},
                {"finding": 2, "verdict": "stands", "reason": ""},
            ]
        )
    )
    result = await challenge([SKIPPED_NAME, REAL], INTENT, model, run_dir=tmp_path)

    assert [c.finding.title for c in result.standing] == [REAL.finding.title]
    [(set_aside, reason)] = result.set_aside
    assert set_aside.finding.title == SKIPPED_NAME.finding.title and "No name was entered" in reason
    assert len(model.seen) == 1 and model.bound_tools == ["submit"]  # one call, no tools
    assert (tmp_path / "agents" / "challenger.jsonl").is_file()


async def test_the_challenger_reads_the_intent_the_steps_and_what_the_app_said(tmp_path: Path) -> None:
    model = ScriptedChatModel(submit(verdicts=[]))
    await challenge([SKIPPED_NAME], INTENT, model, run_dir=tmp_path)

    task = model.seen[0][1]
    assert isinstance(task, HumanMessage)
    for given in (INTENT, 'click button "Book 10:00"', "Booked by Bob", '"10:00 · Free"', "Enter your name"):
        assert given in task.content
    # What the app showed is data, like any page text.
    at = task.content.index("Enter your name")
    assert task.content.rfind("<untrusted", 0, at) > task.content.rfind("</untrusted>", 0, at)


async def test_it_can_only_remove(tmp_path: Path) -> None:
    """Whatever it answers, no finding appears that the replay did not confirm, and none is renamed."""
    model = ScriptedChatModel(
        submit(
            verdicts=[
                {"finding": 7, "verdict": "tester_error", "reason": "There is no finding 7."},
                {"finding": 1, "verdict": "a brand new critical bug", "reason": "Trust me."},
                {"finding": 0, "verdict": "tester_error", "reason": "Nor a finding 0."},
            ]
        )
    )
    result = await challenge([REAL], INTENT, model, run_dir=tmp_path)

    assert result.standing == [REAL] and result.set_aside == []


async def test_a_bug_is_never_dropped_because_the_challenger_failed_or_said_nothing(tmp_path: Path) -> None:
    for model in (
        ScriptedChatModel(RuntimeError("Error code: 429 - rate limit exceeded")),
        ScriptedChatModel(submit(verdicts=[])),
        ScriptedChatModel(submit(verdicts=[{"finding": 1, "verdict": "tester_error", "reason": "   "}])),  # no reason, no removal
    ):
        result = await challenge([REAL], INTENT, model, run_dir=tmp_path)
        assert result.standing == [REAL] and result.set_aside == []


async def test_nothing_to_challenge_and_no_budget_left_make_no_model_call(tmp_path: Path) -> None:
    model = ScriptedChatModel()
    assert (await challenge([], INTENT, model, run_dir=tmp_path)).standing == []

    spent = Budget(max_tokens=10)
    spent.spend(10, 5)
    result = await challenge([REAL], INTENT, model, run_dir=tmp_path, budget=spent)
    assert result.standing == [REAL] and model.seen == []
