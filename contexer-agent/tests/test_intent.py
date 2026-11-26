"""Intent: a written, editable statement of what the app should do, built from the goal and every correction."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import HumanMessage

from contexer.contract.store import ensure_contexer_dir
from contexer.crew.intent import MAX_QUESTIONS, run_intent
from contexer.intent.store import IntentSpec, IntentStore, SavedCheck
from contexer.verification.checks import Check
from tests.fakes import ScriptedChatModel, submit

pytestmark = pytest.mark.anyio

GOAL = "Users can add, complete and delete tasks, and the remaining count stays correct"

ADD = {
    "steps": [
        {"action": "fill", "target": {"placeholder": "What needs doing?"}, "value": "Buy milk"},
        {"action": "click", "target": {"role": "button", "name": "Add"}},
    ],
    "expect": [{"kind": "visible", "target": {"text": "Buy milk"}}],
}
COUNT = {**ADD, "expect": [{"kind": "text", "target": {"test_id": "remaining-count"}, "equals": "1 left"}]}
DELETE = {
    "steps": [*ADD["steps"], {"action": "click", "target": {"role": "button", "name": "Delete Buy milk"}}],
    "expect": [{"kind": "hidden", "target": {"text": "Buy milk"}}],
}
# Not a check: a locator with two strategies, and an expectation with no comparator.
BROKEN_LOCATOR = {"steps": [{"action": "click", "target": {"role": "button", "text": "Add"}}], "expect": [{"kind": "no_errors"}]}
BROKEN_EXPECT = {"steps": [], "expect": [{"kind": "text", "target": {"test_id": "remaining-count"}}]}


def _check(check_id: str, description: str, check: dict[str, Any]) -> dict[str, Any]:
    return {"id": check_id, "description": description, "check": check}


def _saved(check_id: str, check: dict[str, Any], source: str = "draft", **extra: Any) -> SavedCheck:
    return SavedCheck(id=check_id, description=check_id, check=Check.model_validate(check), source=source, **extra)  # type: ignore[arg-type]


# -- the store -----------------------------------------------------------------


def test_an_intent_is_a_markdown_file_a_person_can_read_and_edit(tmp_path: Path) -> None:
    store = IntentStore(tmp_path)
    spec = IntentSpec(
        id=store.id_for(GOAL),
        goal=GOAL,
        behaviours=["Adding a task shows it in the list", "Completing a task lowers the remaining count"],
        assumptions=["Tasks are not kept after a reload"],
    )
    path = store.save(spec)

    assert path == tmp_path / ".contexer" / "intent" / "users-can-add-complete-delete-tasks.md"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# ")
    assert "## Goal" in text and GOAL in text
    assert "- Adding a task shows it in the list" in text
    assert "## Assumptions" in text and "- Tasks are not kept after a reload" in text
    assert store.load(spec.id).behaviours == spec.behaviours

    # A person edits the file by hand; the next load is what they wrote.
    edited = text.replace("- Adding a task shows it in the list", "- Adding a task shows it at the top of the list\n- Empty tasks are refused")
    path.write_text(edited, encoding="utf-8")
    loaded = IntentStore(tmp_path).load(spec.id)
    assert loaded.behaviours == [
        "Adding a task shows it at the top of the list",
        "Empty tasks are refused",
        "Completing a task lowers the remaining count",
    ]
    assert loaded.goal == GOAL and loaded.assumptions == spec.assumptions


def test_a_correction_given_in_one_run_is_in_the_intent_the_next_run_loads(tmp_path: Path) -> None:
    first = IntentStore(tmp_path)
    spec = IntentSpec(id=first.id_for(GOAL), goal=GOAL, behaviours=["Deleting a task removes it"])
    first.save(spec)
    first.append_correction(spec.id, "Deleting should ask first", on="2026-11-18")

    second = IntentStore(tmp_path)  # a later run
    loaded = second.find(GOAL)
    assert loaded is not None
    assert [(c.on, c.text) for c in loaded.corrections] == [("2026-11-18", "Deleting should ask first")]
    # What the agents read contains the goal, the behaviours and the correction.
    text = loaded.as_text()
    assert GOAL in text and "Deleting a task removes it" in text and "Deleting should ask first" in text
    assert "- 2026-11-18: Deleting should ask first" in second.path_for(spec.id).read_text(encoding="utf-8")


def test_the_index_lists_every_feature_and_the_latest_is_the_one_last_saved(tmp_path: Path) -> None:
    store = IntentStore(tmp_path)
    assert store.list() == [] and store.latest() is None and store.find(GOAL) is None
    store.save(IntentSpec(id="todo-basics", goal=GOAL))
    store.save(IntentSpec(id="sign-in", goal="Members can sign in and out"))

    assert sorted(s.id for s in store.list()) == ["sign-in", "todo-basics"]
    latest = store.latest()
    assert latest is not None and latest.id == "sign-in"
    index = (tmp_path / ".contexer" / "intent" / "index.md").read_text(encoding="utf-8")
    assert "[todo-basics](todo-basics.md)" in index and "Members can sign in and out" in index

    store.append_correction("todo-basics", "The count says '1 left', never '1 lefts'")
    assert store.latest().id == "todo-basics"  # type: ignore[union-attr]
    with pytest.raises(Exception, match="no-such-feature"):
        store.load("no-such-feature")


def test_checks_are_stored_next_to_the_intent_and_load_unchanged(tmp_path: Path) -> None:
    store = IntentStore(tmp_path)
    store.save(IntentSpec(id="todo-basics", goal=GOAL))
    checks = [_saved("adds", ADD), _saved("count", COUNT, source="confirmed", kind="bug")]
    store.save_checks("todo-basics", checks)

    assert store.load_checks("todo-basics") == checks
    assert store.load_checks("another") == []
    assert (tmp_path / ".contexer" / "intent" / "todo-basics.checks.json").is_file()


def test_intent_and_skills_are_committed_with_the_project_and_an_old_gitignore_is_upgraded(tmp_path: Path) -> None:
    contexer = ensure_contexer_dir(tmp_path)
    ignore = (contexer / ".gitignore").read_text(encoding="utf-8")
    assert "!/contracts/" in ignore and "!/intent/" in ignore and "!/skills/" in ignore

    # The file 0.4 wrote is replaced; one a person changed is left alone.
    (contexer / ".gitignore").write_text("/*\n!/.gitignore\n!/contracts/\n", encoding="utf-8")
    ensure_contexer_dir(tmp_path)
    assert "!/intent/" in (contexer / ".gitignore").read_text(encoding="utf-8")
    (contexer / ".gitignore").write_text("/*\n!/contracts/\n# mine\n", encoding="utf-8")
    ensure_contexer_dir(tmp_path)
    assert (contexer / ".gitignore").read_text(encoding="utf-8") == "/*\n!/contracts/\n# mine\n"


# -- the Intent agent ------------------------------------------------------------


async def test_an_unambiguous_goal_gives_a_spec_valid_checks_and_no_questions(tmp_path: Path) -> None:
    model = ScriptedChatModel(
        submit(
            behaviours=["Adding a task shows it in the list", "The remaining count goes up by one for each task added"],
            checks=[_check("adds-task", "Adding a task shows it", ADD), _check("count-after-add", "One task: 1 left", COUNT)],
        )
    )
    result = await run_intent(
        GOAL,
        model,
        repo_summary="Project: todo\nFramework: static",
        ui_snapshot='- button "Add"\n- placeholder="What needs doing?"',
        run_dir=tmp_path,
    )

    assert result.status == "ok" and result.questions == [] and result.dropped == []
    assert result.spec.goal == GOAL and result.spec.id == "users-can-add-complete-delete-tasks"
    assert result.spec.behaviours == [
        "Adding a task shows it in the list",
        "The remaining count goes up by one for each task added",
    ]
    assert [(c.id, c.source) for c in result.checks] == [("adds-task", "draft"), ("count-after-add", "draft")]
    assert all(isinstance(c.check, Check) for c in result.checks)
    assert result.checks[0].check == Check.model_validate(ADD)
    # The agent was given the goal, the project and the page as it is.
    task = model.seen[0][1]
    assert isinstance(task, HumanMessage)
    for given in (GOAL, "Framework: static", 'button "Add"'):
        assert given in task.content
    assert (tmp_path / "agents" / "intent.jsonl").is_file()


async def test_a_question_needs_two_readings_and_at_most_three_are_asked(tmp_path: Path) -> None:
    def question(text: str, a: str = "Ask before deleting", b: str = "Delete at once") -> dict[str, str]:
        return {"question": text, "reading_a": a, "reading_b": b}

    model = ScriptedChatModel(
        submit(
            behaviours=["Deleting a task removes it"],
            questions=[
                question("Should deleting ask first?"),
                question("Is this even a question?", b=""),  # one reading: nothing to choose between
                question("Same thing twice?", a="Keep tasks", b="keep tasks "),  # no difference
                question("Are tasks kept after a reload?", "Yes, kept", "No, gone"),
                question("May a task be empty?", "Refused", "Allowed"),
                question("Is there a limit?", "100 tasks", "No limit"),
            ],
        )
    )
    result = await run_intent(GOAL, model, run_dir=tmp_path)

    assert MAX_QUESTIONS == 3
    assert [q.question for q in result.questions] == [
        "Should deleting ask first?",
        "Are tasks kept after a reload?",
        "May a task be empty?",
    ]
    assert result.spec.assumptions == []


async def test_yes_skips_the_questions_and_records_the_assumption_taken(tmp_path: Path) -> None:
    model = ScriptedChatModel(
        submit(
            behaviours=["Deleting a task removes it"],
            questions=[{"question": "Should deleting ask first?", "reading_a": "Delete at once", "reading_b": "Ask before deleting"}],
            assumptions=["The list starts empty"],
        )
    )
    result = await run_intent(GOAL, model, assume=True, run_dir=tmp_path)

    assert result.questions == []
    assert result.spec.assumptions == [
        "The list starts empty",
        "Delete at once (assumed without asking; the other reading was: Ask before deleting)",
    ]
    assert "assumed without asking" in result.spec.to_markdown()


async def test_an_invalid_check_is_sent_back_once_then_dropped_and_reported(tmp_path: Path) -> None:
    model = ScriptedChatModel(
        submit(
            behaviours=["Adding works"],
            checks=[
                _check("adds-task", "Adding a task shows it", ADD),
                _check("clicks-add", "Clicking Add", BROKEN_LOCATOR),
                _check("count", "Count is right", BROKEN_EXPECT),
            ],
        ),
        # The agent fixes one and gets the other wrong again.
        submit(checks=[_check("clicks-add", "Clicking Add", ADD), _check("count", "Count is right", BROKEN_EXPECT)]),
    )
    result = await run_intent(GOAL, model, run_dir=tmp_path)

    assert result.status == "ok"
    assert [c.id for c in result.checks] == ["adds-task", "clicks-add"]
    [(dropped_id, reason)] = result.dropped
    assert dropped_id == "count" and "needs equals, contains, matches" in reason
    assert len(model.seen) == 2  # sent back exactly once
    sent_back = model.seen[1][1].content
    assert "clicks-add" in sent_back and "exactly one of" in sent_back
    assert "count" in sent_back and "adds-task" not in sent_back  # only the invalid ones


async def test_a_correction_updates_the_spec_and_regenerates_only_the_checks_it_affects(tmp_path: Path) -> None:
    stored = IntentSpec(id="todo-basics", goal=GOAL, behaviours=["Adding a task shows it", "Deleting a task removes it"])
    existing = [
        _saved("adds-task", ADD),
        _saved("deletes-task", DELETE),
        _saved("old-count", COUNT),
        _saved("confirmed-count", COUNT, source="confirmed", kind="works"),
    ]
    asks_first = {
        "steps": [*ADD["steps"], {"action": "click", "target": {"role": "button", "name": "Delete Buy milk"}}],
        "expect": [{"kind": "visible", "target": {"role": "dialog"}}],
    }
    model = ScriptedChatModel(
        submit(
            behaviours=["Adding a task shows it", "Deleting a task asks for confirmation first, then removes it"],
            checks=[_check("deletes-task", "Deleting asks first", asks_first)],
            remove_checks=["old-count", "confirmed-count", "never-existed"],
        )
    )
    result = await run_intent(
        GOAL, model, stored=stored, existing_checks=existing, correction="Deleting should ask first", run_dir=tmp_path
    )

    assert result.spec.id == "todo-basics"
    assert [c.text for c in result.spec.corrections] == ["Deleting should ask first"]
    assert result.spec.corrections[0].on  # dated by code
    assert "asks for confirmation first" in result.spec.behaviours[1]
    by_id = {c.id: c for c in result.checks}
    assert list(by_id) == ["adds-task", "deletes-task", "confirmed-count"]
    assert by_id["adds-task"] is existing[0]  # untouched, not regenerated
    assert by_id["deletes-task"].check == Check.model_validate(asks_first)
    # A check that replay confirmed is evidence; the agent cannot remove it.
    assert by_id["confirmed-count"] is existing[3]
    task = model.seen[0][1].content
    assert "Deleting should ask first" in task
    for check_id in ("adds-task", "deletes-task", "old-count"):
        assert check_id in task


async def test_a_model_error_still_keeps_the_correction_and_the_checks(tmp_path: Path) -> None:
    stored = IntentSpec(id="todo-basics", goal=GOAL, behaviours=["Adding a task shows it"])
    existing = [_saved("adds-task", ADD)]
    model = ScriptedChatModel(RuntimeError("Error code: 429 - rate limit exceeded"))

    result = await run_intent(
        GOAL, model, stored=stored, existing_checks=existing, correction="Deleting should ask first", run_dir=tmp_path
    )

    assert result.status == "model_error" and "429" in result.error
    assert [c.text for c in result.spec.corrections] == ["Deleting should ask first"]
    assert result.spec.behaviours == ["Adding a task shows it"]
    assert result.checks == existing


async def test_the_stored_intent_is_part_of_what_the_agent_reads(tmp_path: Path) -> None:
    stored = IntentSpec(id="todo-basics", goal=GOAL, behaviours=["Empty tasks are refused"])
    stored = stored.with_correction("The count never goes below zero", on="2026-11-01")
    model = ScriptedChatModel(submit(behaviours=["Empty tasks are refused", "The count never goes below zero"]))

    result = await run_intent(GOAL, model, stored=stored, run_dir=tmp_path)

    task = model.seen[0][1].content
    assert "Empty tasks are refused" in task and "The count never goes below zero" in task
    assert [c.on for c in result.spec.corrections] == ["2026-11-01"]  # kept, not rewritten


async def test_the_intent_agent_takes_the_step_cap_it_is_given(tmp_path: Path) -> None:
    import json

    model = ScriptedChatModel(submit(behaviours=["A task can be added"]))
    await run_intent(GOAL, model, run_dir=tmp_path, max_steps=2)
    start = json.loads((tmp_path / "agents" / "intent.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert start["max_steps"] == 2
