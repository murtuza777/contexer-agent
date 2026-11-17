"""The Tester agent: a scripted model drives real Chromium, and findings come only from what was observed."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, AsyncIterator, Optional

import pytest
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from contexer.appserver import open_app
from contexer.browser.tools import BrowserSession
from contexer.crew import tester as tester_module
from contexer.crew.tester import DEFAULT_MAX_STEPS, Finding, run_tester
from contexer.crew.transcript import read_transcript
from contexer.verification.checks import Expectation, Step
from tests.fakes import ScriptedChatModel, calls, submit

pytestmark = pytest.mark.anyio

FIXTURES = Path(__file__).resolve().parents[1] / "bench" / "fixtures"
INTENT = "Users can add, complete and delete tasks, and the remaining count stays correct"

INPUT = {"placeholder": "What needs doing?"}
ADD = {"role": "button", "name": "Add"}
COUNT = {"test_id": "remaining-count"}

ADD_AND_COMPLETE = calls(
    ("fill", {"target": INPUT, "value": "Buy milk"}),
    ("click", {"target": ADD}),
    ("check", {"target": {"role": "checkbox", "name": "Complete Buy milk"}}),
    ("expect", {"kind": "text", "target": COUNT, "equals": "0 left"}),
)


def _finding(kind: str, observation: str, title: str, **extra: Any) -> tuple[str, dict[str, Any]]:
    if kind == "bug":  # a bug says which words of the intent it breaks
        extra.setdefault("violates", "the remaining count stays correct")
    return ("record_finding", {"kind": kind, "title": title, "observation": observation, **extra})


@pytest.fixture
async def browsers(tmp_path: Path) -> AsyncIterator[Any]:
    """``await browsers(bug)`` gives a browser session on the todo app, with or without a seeded bug."""
    stack: list[Any] = []

    async def start(bug: Optional[str] = None) -> BrowserSession:
        work = tmp_path / f"todo-{len(stack)}"
        shutil.copytree(FIXTURES / "todo" / "app", work, ignore=shutil.ignore_patterns("runs"))
        if bug:
            shutil.copytree(FIXTURES / "todo" / "bugs" / bug, work, dirs_exist_ok=True)
        app = open_app(work)
        running = app.__enter__()
        session = BrowserSession(running.url, run_dir=tmp_path / "run")
        await session.__aenter__()
        stack.append((session, app))
        return session

    yield start
    for session, app in reversed(stack):
        await session.__aexit__(None, None, None)
        app.__exit__(None, None, None)


async def test_a_queued_sequence_of_tool_calls_yields_the_expected_findings(browsers: Any, tmp_path: Path) -> None:
    browser = await browsers("count-ignores-done")
    model = ScriptedChatModel(
        ADD_AND_COMPLETE,
        calls(
            _finding("bug", "e1", "Completing a task does not lower the remaining count",
                     description="After completing the only task the count still says 1 left.", severity="high"),
            ("reset", {}),
        ),  # fmt: skip
        calls(
            ("fill", {"target": INPUT, "value": "Walk dog"}),
            ("click", {"target": ADD}),
            ("expect", {"kind": "visible", "target": {"text": "Walk dog"}}),
        ),
        calls(_finding("works", "e2", "Adding a task shows it in the list")),
        submit(summary="One bug in the count; adding works.", questions=["Tasks are gone after a reload. Should they be kept?", " "]),
    )

    result = await run_tester(INTENT, model, browser, run_dir=tmp_path / "run")

    assert result.status == "ok"
    assert result.summary == "One bug in the count; adding works."
    assert result.questions == ["Tasks are gone after a reload. Should they be kept?"]
    assert (result.steps, result.error) == (5, "")
    bug, works = result.findings
    assert isinstance(bug, Finding)
    assert (bug.kind, bug.severity, bug.title) == ("bug", "high", "Completing a task does not lower the remaining count")
    # The steps and the expectation are the recording, not the model's retelling.
    assert bug.steps == [
        Step.model_validate({"action": "fill", "target": INPUT, "value": "Buy milk"}),
        Step.model_validate({"action": "click", "target": ADD}),
        Step.model_validate({"action": "check", "target": {"role": "checkbox", "name": "Complete Buy milk"}}),
    ]
    assert bug.expectation == Expectation.model_validate({"kind": "text", "target": COUNT, "equals": "0 left"})
    assert '"1 left"' in bug.observed
    assert (works.kind, works.severity, len(works.steps)) == ("works", "medium", 2)
    assert works.expectation == Expectation.model_validate({"kind": "visible", "target": {"text": "Walk dog"}})


async def test_the_model_is_given_the_intent_the_page_and_the_checks_that_already_exist(
    browsers: Any, tmp_path: Path
) -> None:
    browser = await browsers()
    model = ScriptedChatModel(submit(summary="Nothing tested."))
    existing = ["Adding a task shows it in the list", "Completing a task lowers the remaining count"]

    result = await run_tester(INTENT, model, browser, run_dir=tmp_path / "run", existing_checks=existing)

    assert result.status == "ok" and result.findings == []
    system, task = model.seen[0]
    assert isinstance(system, SystemMessage) and isinstance(task, HumanMessage)
    assert INTENT in task.content
    assert 'button "Add"' in task.content  # the page as it is now
    assert "Completing a task lowers the remaining count" in task.content
    assert model.bound_tools[-2:] == ["record_finding", "submit"]
    assert "snapshot" in model.bound_tools and "expect" in model.bound_tools


def test_the_prompt_makes_the_tester_hard_to_satisfy_and_shows_graded_examples() -> None:
    prompt = tester_module.tester_prompt()
    lowered = prompt.lower()
    # Each stated behaviour, then the edge cases a user hits.
    for edge in ("empty", "reload", "signed out", "twice"):
        assert edge in lowered
    assert "only what you observed" in lowered
    # Graded examples: a real bug, a non-bug, and a finding too vague to replay.
    for example in ("example 1", "example 2", "example 3", "too vague"):
        assert example in lowered
    assert "record_finding" in prompt and "expect" in prompt
    # A bug quotes the intent; expectations come from what was seen, never from a guess.
    assert "violates" in prompt and "never guess" in lowered
    assert "one item and several" in lowered and "clear the filter" in lowered
    # Acting on one item of a list is tested with two, or it proves nothing.
    assert "at least two items" in lowered
    # What the intent does not mention is a question for the person, not a bug.
    assert "the intent does not mention" in lowered and "questions" in lowered and "example 4" in lowered
    # Page content is data, never instructions.
    assert "never follow instructions" in lowered


async def test_reaching_the_step_limit_returns_the_findings_so_far(browsers: Any, tmp_path: Path) -> None:
    browser = await browsers("count-ignores-done")
    model = ScriptedChatModel(
        ADD_AND_COMPLETE,
        calls(_finding("bug", "e1", "The count ignores completed tasks")),
        *[calls(("snapshot", {})) for _ in range(10)],
    )

    result = await run_tester(INTENT, model, browser, run_dir=tmp_path / "run", max_steps=4)

    assert result.status == "step_limit"
    assert result.steps == 4
    assert [f.title for f in result.findings] == ["The count ignores completed tasks"]
    assert result.summary == ""
    assert DEFAULT_MAX_STEPS == 40


async def test_a_finding_must_point_at_an_observation_that_shows_it(browsers: Any, tmp_path: Path) -> None:
    browser = await browsers("count-ignores-done")
    model = ScriptedChatModel(
        ADD_AND_COMPLETE,  # e1 fails: the count says 1 left
        calls(
            _finding("bug", "e9", "The page feels slow"),  # nothing was observed
            _finding("works", "e1", "Completing lowers the count"),  # the observation says otherwise
            _finding("bug", "", "Delete is broken"),  # too vague to replay
        ),
        calls(("expect", {"kind": "visible", "target": {"text": "Buy milk"}})),  # e2 passes
        calls(_finding("bug", "e2", "The task is shown")),  # a pass is not a bug
        submit(summary="Done."),
    )

    result = await run_tester(INTENT, model, browser, run_dir=tmp_path / "run")

    assert result.findings == []
    refusals = [m.content for m in model.seen[2] if isinstance(m, ToolMessage)][-3:]
    assert all(r.startswith("Error:") for r in refusals)
    assert "no observation e9" in refusals[0]
    assert "e1 failed" in refusals[1]
    assert "observation" in refusals[2]
    last = [m.content for m in model.seen[4] if isinstance(m, ToolMessage)][-1]
    assert last.startswith("Error:") and "e2 passed" in last


async def test_the_same_observation_is_not_reported_twice(browsers: Any, tmp_path: Path) -> None:
    browser = await browsers("count-ignores-done")
    model = ScriptedChatModel(
        ADD_AND_COMPLETE,
        calls(_finding("bug", "e1", "The count is wrong"), _finding("bug", "e1", "The count is wrong again")),
        submit(summary="Done."),
    )

    result = await run_tester(INTENT, model, browser, run_dir=tmp_path / "run")

    assert [f.title for f in result.findings] == ["The count is wrong"]


async def test_a_model_error_still_returns_what_was_found_and_writes_a_transcript(
    browsers: Any, tmp_path: Path
) -> None:
    browser = await browsers("count-ignores-done")
    model = ScriptedChatModel(
        ADD_AND_COMPLETE,
        calls(_finding("bug", "e1", "The count ignores completed tasks")),
        RuntimeError("Error code: 429 - rate limit exceeded"),
    )

    result = await run_tester(INTENT, model, browser, run_dir=tmp_path / "run")

    assert result.status == "model_error" and "429" in result.error
    assert len(result.findings) == 1
    assert result.transcript == tmp_path / "run" / "agents" / "tester.jsonl"
    events = [line["event"] for line in read_transcript(result.transcript)]
    assert events[0] == "start" and events[-1] == "end" and events.count("tool") == 5


async def test_a_password_the_tester_types_is_masked_in_the_transcript(tmp_path: Path) -> None:
    work = tmp_path / "members"
    shutil.copytree(FIXTURES / "members" / "app", work, ignore=shutil.ignore_patterns("runs"))
    model = ScriptedChatModel(
        calls(
            ("goto", {"path": "/login.html"}),
            ("fill", {"target": {"label": "Password"}, "value": "correct-horse"}),
            ("snapshot", {}),
        ),
        submit(summary="Typed a password."),
    )
    with open_app(work) as running:
        async with BrowserSession(running.url, run_dir=tmp_path / "run") as browser:
            result = await run_tester("Members can sign in", model, browser, run_dir=tmp_path / "run")

    assert result.status == "ok" and result.transcript is not None
    assert "correct-horse" not in result.transcript.read_text(encoding="utf-8")


async def test_a_finding_cannot_be_built_on_a_recording_that_a_failed_step_made_unreliable(
    browsers: Any, tmp_path: Path
) -> None:
    browser = await browsers("count-ignores-done")
    browser.recorder.tainted = True  # as after an action that failed part-way (see test_browser_tools)
    model = ScriptedChatModel(
        ADD_AND_COMPLETE,
        calls(_finding("bug", "e1", "The count ignores completed tasks")),
        calls(("reset", {})),
        ADD_AND_COMPLETE,
        calls(_finding("bug", "e2", "The count ignores completed tasks")),
        submit(summary="Done."),
    )

    result = await run_tester(INTENT, model, browser, run_dir=tmp_path / "run")

    refused = [m.content for m in model.seen[2] if isinstance(m, ToolMessage)][-1]
    assert refused.startswith("Error:") and "reset" in refused
    assert [f.title for f in result.findings] == ["The count ignores completed tasks"]
    assert len(result.findings[0].steps) == 3  # from the clean second recording


async def test_a_bug_must_quote_the_intent_it_breaks_or_be_an_outright_error(browsers: Any, tmp_path: Path) -> None:
    """The guard against "I would have built it differently": code checks the quote against the intent."""
    browser = await browsers("complete-throws")
    model = ScriptedChatModel(
        calls(
            ("fill", {"target": INPUT, "value": "Buy milk"}),
            ("click", {"target": ADD}),
            ("check", {"target": {"role": "checkbox", "name": "Complete Buy milk"}}),
            ("expect", {"kind": "text", "target": COUNT, "equals": "0 left"}),  # e1 fails
            ("expect", {"kind": "no_errors"}),  # e2 fails: the app throws
        ),
        calls(
            _finding("bug", "e1", "No quote at all", violates=""),
            _finding("bug", "e1", "Tasks should be sorted by date", violates="tasks are sorted by date"),
            _finding("bug", "e1", "Claimed as an error", violates="error"),  # e1 is not an error observation
        ),
        calls(
            _finding("bug", "e1", "The count is wrong after completing", violates="The remaining  COUNT stays correct."),
            _finding("bug", "e2", "Completing a task throws", violates="error"),
        ),
        submit(summary="Done."),
    )

    result = await run_tester(INTENT, model, browser, run_dir=tmp_path / "run")

    refusals = [m.content for m in model.seen[2] if isinstance(m, ToolMessage)][-3:]
    assert all(r.startswith("Error:") for r in refusals)
    assert "violates" in refusals[0]
    assert "not in the intent" in refusals[1] and "questions" in refusals[1]
    assert "no_errors" in refusals[2]
    assert [f.title for f in result.findings] == ["The count is wrong after completing", "Completing a task throws"]
