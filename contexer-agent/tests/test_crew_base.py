"""``run_agent``: the loop every Contexer agent runs in, driven by a scripted model."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from contexer.crew import AgentSpec, run_agent
from contexer.crew.base import MAX_CORRECTIONS
from tests.fakes import ScriptedChatModel, calls, says, submit

pytestmark = pytest.mark.anyio


class Verdict(BaseModel):
    """What the test agent hands in."""

    summary: str
    bugs: int = Field(ge=0)


def _spec(**overrides: Any) -> AgentSpec:
    values: dict[str, Any] = {"name": "tester", "system_prompt": "You test web apps.", "output_schema": Verdict}
    return AgentSpec(**{**values, **overrides})


@tool
def look(page: str) -> str:
    """Describe a page of the app."""
    return f"{page}: a list with 2 tasks"


@tool
def broken(page: str) -> str:
    """A tool that always fails."""
    raise RuntimeError(f"browser crashed on {page}")


def _tool_messages(model: ScriptedChatModel, call: int) -> list[ToolMessage]:
    return [m for m in model.seen[call] if isinstance(m, ToolMessage)]


async def test_success_runs_the_tools_then_returns_the_validated_answer(tmp_path: Path) -> None:
    model = ScriptedChatModel(calls(("look", {"page": "home"})), submit(summary="works", bugs=0))
    result = await run_agent(_spec(max_output_tokens=1234), model, [look], "Test the todo app.", run_dir=tmp_path)

    assert result.status == "ok"
    assert result.output == Verdict(summary="works", bugs=0)
    assert (result.steps, result.tool_calls) == (2, 1)
    assert (result.tokens_in, result.tokens_out) == (20, 10)
    assert result.cost_usd is None  # this model reports no prices
    assert result.error == ""
    # The model was given the tools plus `submit`, the system prompt, the task and the token limit.
    assert model.bound_tools == ["look", "submit"]
    system, task = model.seen[0]
    assert isinstance(system, SystemMessage) and system.content.startswith("You test web apps.")
    assert "`submit`" in system.content
    assert isinstance(task, HumanMessage) and task.content == "Test the todo app."
    assert model.options[0]["max_tokens"] == 1234
    # The tool's result reached the model on the next call.
    [observed] = _tool_messages(model, 1)
    assert (observed.content, observed.status) == ("home: a list with 2 tasks", "success")


async def test_the_step_limit_ends_a_run_that_never_hands_in_an_answer(tmp_path: Path) -> None:
    model = ScriptedChatModel(*[calls(("look", {"page": f"p{i}"})) for i in range(10)])
    result = await run_agent(_spec(max_steps=3), model, [look], "Go.", run_dir=tmp_path)

    assert result.status == "step_limit"
    assert result.output is None
    assert (result.steps, result.tool_calls) == (3, 3)
    assert len(model.seen) == 3  # not one model call more than allowed
    assert "3 steps" in result.error


async def test_the_timeout_ends_a_run_and_keeps_what_was_counted(tmp_path: Path) -> None:
    model = ScriptedChatModel(*[calls(("look", {"page": "home"})) for _ in range(50)], delay=0.05)
    result = await run_agent(_spec(timeout=0.2, max_steps=50), model, [look], "Go.", run_dir=tmp_path)

    assert result.status == "timeout"
    assert result.output is None
    assert 1 <= result.steps < 50
    assert result.duration_seconds < 2
    assert "0.2 seconds" in result.error


async def test_an_invalid_answer_is_sent_back_and_the_corrected_one_is_accepted(tmp_path: Path) -> None:
    model = ScriptedChatModel(submit(summary="works", bugs="many"), submit(summary="works", bugs=2))
    result = await run_agent(_spec(), model, [], "Go.", run_dir=tmp_path)

    assert result.status == "ok"
    assert result.output == Verdict(summary="works", bugs=2)
    assert result.steps == 2
    [correction] = _tool_messages(model, 1)
    assert correction.status == "error"
    assert "bugs:" in correction.content and "call the `submit` tool again" in correction.content


async def test_an_answer_that_stays_invalid_ends_the_run_after_two_corrections(tmp_path: Path) -> None:
    model = ScriptedChatModel(*[submit(summary="works") for _ in range(10)])
    result = await run_agent(_spec(), model, [], "Go.", run_dir=tmp_path)

    assert result.status == "invalid_output"
    assert result.output is None
    assert result.steps == MAX_CORRECTIONS + 1 == 3
    assert "bugs: Field required" in result.error


async def test_an_answer_written_as_json_text_is_accepted_and_plain_talk_is_sent_back(tmp_path: Path) -> None:
    model = ScriptedChatModel(
        says("I think the app is fine."),
        says('Here it is:\n```json\n{"summary": "fine", "bugs": 0}\n```'),
    )
    result = await run_agent(_spec(), model, [], "Go.", run_dir=tmp_path)

    assert result.status == "ok"
    assert result.output == Verdict(summary="fine", bugs=0)
    nudge = model.seen[1][-1]
    assert isinstance(nudge, HumanMessage) and "Call the `submit` tool" in nudge.content


async def test_a_tool_that_raises_reaches_the_model_as_an_error_and_the_run_goes_on(tmp_path: Path) -> None:
    model = ScriptedChatModel(
        calls(("broken", {"page": "cart"})),
        calls(("look", {"page": "cart"})),
        submit(summary="cart page crashes the browser tool", bugs=1),
    )
    result = await run_agent(_spec(), model, [look, broken], "Go.", run_dir=tmp_path)

    assert result.status == "ok"
    assert (result.steps, result.tool_calls) == (3, 2)
    [failure] = _tool_messages(model, 1)
    assert failure.status == "error"
    assert failure.content == "Error: RuntimeError: browser crashed on cart"


async def test_a_tool_that_does_not_exist_and_bad_arguments_are_errors_the_model_can_recover_from(
    tmp_path: Path,
) -> None:
    model = ScriptedChatModel(
        calls(("teleport", {"to": "admin"}), ("look", {"wrong": 1})),
        submit(summary="ok", bugs=0),
    )
    result = await run_agent(_spec(), model, [look], "Go.", run_dir=tmp_path)

    assert result.status == "ok"
    unknown, bad_args = _tool_messages(model, 1)
    assert unknown.status == "error" and "no tool named 'teleport'" in unknown.content
    assert "look, submit" in unknown.content
    assert bad_args.status == "error" and "page" in bad_args.content


async def test_a_model_error_ends_the_run_with_the_reason_and_no_key_in_it(tmp_path: Path) -> None:
    key = "sk-or-v1-" + "a1b2c3d4" * 6
    model = ScriptedChatModel(calls(("look", {"page": "home"})), RuntimeError(f"Error code: 401 - bad key {key}"))
    result = await run_agent(_spec(), model, [look], "Go.", run_dir=tmp_path)

    assert result.status == "model_error"
    assert result.output is None
    assert result.steps == 2
    assert "401" in result.error and key not in result.error


async def test_a_model_that_cannot_call_tools_is_named_in_the_error(tmp_path: Path) -> None:
    model = ScriptedChatModel(RuntimeError("Error code: 404 - No endpoints found that support tool use."))
    result = await run_agent(_spec(), model, [look], "Go.", run_dir=tmp_path)

    assert result.status == "model_error"
    assert "model 'scripted-model' cannot call tools" in result.error


async def test_cost_is_added_up_when_the_provider_reports_it(tmp_path: Path) -> None:
    def priced(message: AIMessage, cost: float) -> AIMessage:
        message.response_metadata = {"token_usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": cost}}
        return message

    model = ScriptedChatModel(
        priced(calls(("look", {"page": "home"})), 0.002), priced(submit(summary="ok", bugs=0), 0.001)
    )
    result = await run_agent(_spec(), model, [look], "Go.", run_dir=tmp_path)

    assert result.cost_usd == pytest.approx(0.003)


async def test_an_answer_handed_in_with_other_calls_ends_the_run_and_every_call_gets_a_result(
    tmp_path: Path,
) -> None:
    model = ScriptedChatModel(
        calls(("look", {"page": "home"}), ("submit", {"summary": "ok", "bugs": 0}), ("look", {"page": "late"}))
    )
    result = await run_agent(_spec(), model, [look], "Go.", run_dir=tmp_path)

    assert result.status == "ok"
    assert result.tool_calls == 1  # the call after the answer was not run
    results = [m for m in result.messages if isinstance(m, ToolMessage)]
    assert [m.content for m in results] == [
        "home: a list with 2 tasks",
        "Accepted.",
        "Not run: the answer was already handed in.",
    ]


async def test_plain_functions_work_as_tools_and_structured_results_become_json(tmp_path: Path) -> None:
    def count_tasks(page: str) -> dict[str, int]:
        """Count the tasks on a page."""
        return {"tasks": 2}

    async def wait_for(seconds: int) -> str:
        """Wait a moment."""
        return f"waited {seconds}"

    model = ScriptedChatModel(
        calls(("count_tasks", {"page": "home"}), ("wait_for", {"seconds": 1})), submit(summary="ok", bugs=0)
    )
    result = await run_agent(_spec(), model, [count_tasks, wait_for], "Go.", run_dir=tmp_path)

    assert result.status == "ok"
    assert [m.content for m in _tool_messages(model, 1)] == ['{"tasks": 2}', "waited 1"]


async def test_a_tool_may_not_take_the_name_submit(tmp_path: Path) -> None:
    @tool
    def submit(form: str) -> str:  # noqa: F811 - the clash is the point
        """Submit a form on the page."""
        return "sent"

    with pytest.raises(ValueError, match="'submit' is taken"):
        await run_agent(_spec(), ScriptedChatModel(), [submit], "Go.", run_dir=tmp_path)


async def test_no_run_dir_is_fine(tmp_path: Path) -> None:
    result = await run_agent(_spec(), ScriptedChatModel(submit(summary="ok", bugs=0)), [], "Go.", run_dir=None)
    assert result.status == "ok"
