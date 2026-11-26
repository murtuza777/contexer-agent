"""``trace.jsonl``: one file per run with every run event, model call and tool call, and no content."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.tools import tool
from pydantic import BaseModel

from contexer.controller import RunSettings
from contexer.crew import AgentSpec, run_agent
from contexer.crew.budget import Budget
from contexer.crew.transcript import SEMCONV_VERSION, Masker, Trace, read_transcript
from contexer.evidence.rundir import TRACE_FILE, RunDir
from contexer.graph import GraphController
from contexer.graph.context import RunEvent
from contexer.verification.checks import MASK
from tests.fakes import AgentScript, ScriptedChatModel, calls, submit
from tests.loop_helpers import COUNT_BUG_JS, GOOD_JS, RecordingAgent, contract, copy_todo, fast_runner

pytestmark = pytest.mark.anyio

PASSWORD = "hunter2-correct-horse"
PAGE_TEXT = "Welcome back, Dana"
TASK = "Test the checkout of the shop."


class Report(BaseModel):
    summary: str


SPEC = AgentSpec(name="tester", system_prompt="You test web apps.", output_schema=Report)


@tool
def read_page(page: str) -> str:
    """Read a page of the app."""
    if page == "crash":
        raise RuntimeError("the browser closed")
    return f"{page}: {PAGE_TEXT}; password {PASSWORD}"


def _trace(run_dir: Path) -> list[dict[str, Any]]:
    return read_transcript(run_dir / TRACE_FILE)


def _calls(run_dir: Path, kind: str) -> list[dict[str, Any]]:
    return [line for line in _trace(run_dir) if line["event"] == kind]


async def test_a_model_call_and_a_tool_call_are_one_line_each_under_a_version_line(tmp_path: Path) -> None:
    first = calls(("read_page", {"page": "home"}), text="Looking.", tokens=(100, 20))
    first.usage_metadata["input_token_details"] = {"cache_read": 60}  # type: ignore[index]
    first.response_metadata = {"finish_reason": "tool_calls", "model_name": "scripted-model-2026-01"}
    model = ScriptedChatModel(first, submit(summary="fine"))
    await run_agent(SPEC, model, [read_page], TASK, run_dir=tmp_path)

    head, chat, called, last = _trace(tmp_path)
    assert (head["event"], head["semconv"]) == ("trace", SEMCONV_VERSION)
    assert chat["event"] == "model" and chat["gen_ai.operation.name"] == "chat"
    assert chat["gen_ai.agent.name"] == "tester"
    assert chat["gen_ai.provider.name"] == "scripted"
    assert (chat["gen_ai.request.model"], chat["gen_ai.response.model"]) == ("scripted-model", "scripted-model-2026-01")
    assert (chat["gen_ai.usage.input_tokens"], chat["gen_ai.usage.output_tokens"]) == (100, 20)
    assert chat["gen_ai.usage.cache_read.input_tokens"] == 60
    assert chat["gen_ai.response.finish_reasons"] == ["tool_calls"]
    assert chat["contexer.step"] == 1 and chat["contexer.seconds"] >= 0
    assert (chat["contexer.cost_usd"], chat["contexer.cost_estimated"]) == (None, False)
    assert called["event"] == "tool" and called["gen_ai.operation.name"] == "execute_tool"
    assert (called["gen_ai.agent.name"], called["gen_ai.tool.name"]) == ("tester", "read_page")
    assert called["contexer.tool.status"] == "ok" and called["contexer.seconds"] >= 0
    # A provider that reports no cached tokens and no answering model: not known, not zero.
    assert last["gen_ai.usage.cache_read.input_tokens"] is None and last["gen_ai.response.model"] is None
    assert all(line["time"].endswith("Z") for line in (head, chat, called, last))


async def test_a_tool_call_is_ok_repaired_or_failed(tmp_path: Path) -> None:
    model = ScriptedChatModel(
        calls(("read_page", {"page": 7})),  # does not fit the schema
        calls(("read_page", {"page": "home"})),  # the repair
        calls(("read_page", {"page": "crash"}), ("teleport", {"to": "admin"})),  # the tool raises; no such tool
        calls(("read_page", {"page": "cart"})),
        submit(summary="fine"),
    )
    await run_agent(SPEC, model, [read_page], TASK, run_dir=tmp_path)

    assert [(line["gen_ai.tool.name"], line["contexer.tool.status"]) for line in _calls(tmp_path, "tool")] == [
        ("read_page", "failed"),
        ("read_page", "repaired"),
        ("read_page", "failed"),
        ("teleport", "failed"),
        ("read_page", "ok"),
    ]


async def test_the_trace_holds_no_prompt_no_page_text_and_no_secret(tmp_path: Path) -> None:
    model = ScriptedChatModel(
        calls(("read_page", {"page": f"login?password={PASSWORD}"}), text="I will read the login page."),
        submit(summary=f"The page says {PAGE_TEXT}"),
    )
    await run_agent(SPEC, model, [read_page], TASK, run_dir=tmp_path, secrets=[PASSWORD])

    raw = (tmp_path / TRACE_FILE).read_text(encoding="utf-8")
    for content in (TASK, "You test web apps.", PAGE_TEXT, "I will read the login page.", "login?", PASSWORD):
        assert content not in raw
    # The content is where it was: in the agent's own transcript, masked.
    assert PAGE_TEXT in (tmp_path / "agents" / "tester.jsonl").read_text(encoding="utf-8")


async def test_a_failed_model_call_is_a_line_with_the_kind_of_error(tmp_path: Path) -> None:
    await run_agent(SPEC, ScriptedChatModel(RuntimeError("Error code: 500 - upstream broke")), [], TASK, run_dir=tmp_path)

    [failed] = _calls(tmp_path, "model")
    assert failed["error.type"] == "RuntimeError"
    assert failed["gen_ai.agent.name"] == "tester" and failed["contexer.seconds"] >= 0


async def test_a_cost_worked_out_from_rates_is_marked_as_an_estimate(tmp_path: Path) -> None:
    priced = submit(summary="fine")
    priced.response_metadata = {"token_usage": {"cost": 0.002}}
    await run_agent(SPEC, ScriptedChatModel(priced), [], TASK, run_dir=tmp_path / "reported")
    budget = Budget(input_usd_per_mtok=1.0, output_usd_per_mtok=2.0)
    await run_agent(SPEC, ScriptedChatModel(submit(summary="fine")), [], TASK, run_dir=tmp_path / "rated", budget=budget)

    [reported] = _calls(tmp_path / "reported", "model")
    [rated] = _calls(tmp_path / "rated", "model")
    assert (reported["contexer.cost_usd"], reported["contexer.cost_estimated"]) == (0.002, False)
    assert rated["contexer.cost_usd"] == pytest.approx((10 * 1.0 + 5 * 2.0) / 1_000_000)
    assert rated["contexer.cost_estimated"] is True


async def test_every_agent_of_a_run_writes_to_the_same_file_under_one_version_line(tmp_path: Path) -> None:
    other = AgentSpec(name="reviewer", system_prompt="You review diffs.", output_schema=Report)
    await run_agent(SPEC, ScriptedChatModel(submit(summary="ok")), [], TASK, run_dir=tmp_path)
    await run_agent(other, ScriptedChatModel(submit(summary="ok")), [], TASK, run_dir=tmp_path)

    lines = _trace(tmp_path)
    assert [line["event"] for line in lines] == ["trace", "model", "model"]
    assert [line["gen_ai.agent.name"] for line in lines[1:]] == ["tester", "reviewer"]


async def test_without_a_run_folder_there_is_no_trace(tmp_path: Path) -> None:
    await run_agent(SPEC, ScriptedChatModel(submit(summary="ok")), [], TASK, run_dir=None)
    Trace(None).write({"event": "app"})  # a no-op, not an error
    assert list(tmp_path.iterdir()) == []


def test_a_trace_line_is_masked_and_written_the_way_json_output_writes_it(tmp_path: Path) -> None:
    trace = Trace(tmp_path, Masker([PASSWORD]))
    trace.write({"event": "app", "at": 1.5, "message": f"Signed in with {PASSWORD} ✓"})

    raw = (tmp_path / TRACE_FILE).read_text(encoding="utf-8")
    assert PASSWORD not in raw
    assert raw.splitlines()[1] == json.dumps(
        {"event": "app", "at": 1.5, "message": f"Signed in with {MASK} ✓"}, ensure_ascii=True
    )


def test_a_run_folder_names_its_trace(tmp_path: Path) -> None:
    assert RunDir(run_id="r1", path=tmp_path).trace_jsonl == tmp_path / "trace.jsonl"


# -- a whole run ---------------------------------------------------------------------------------


def _diagnoser_that_repairs_a_call() -> AgentScript:
    return AgentScript(
        diagnoser=[
            calls(("read_file", {"path": ["app.js"]})),  # a list where a string belongs
            calls(("read_file", {"path": "app.js"})),
            submit(cause="remaining() counts every task.", files=["app.js"], instruction="Count only open tasks."),
        ]
    )


async def test_a_run_has_its_events_its_model_calls_and_its_tool_calls_in_one_trace(tmp_path: Path) -> None:
    project = copy_todo(tmp_path)
    seen: list[RunEvent] = []
    agent = RecordingAgent([{"app.js": COUNT_BUG_JS}, {"app.js": GOOD_JS}])
    controller = GraphController(
        project,
        agent,
        RunSettings(max_repair_rounds=2),
        runner=fast_runner(),
        model=_diagnoser_that_repairs_a_call(),
        on_detail=seen.append,
    )
    outcome = await controller.run(contract(project))

    assert outcome.terminal == "succeeded"
    lines = (Path(outcome.run_dir) / TRACE_FILE).read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines]
    assert rows[0]["event"] == "trace" and rows[0]["semconv"] == SEMCONV_VERSION
    # Every event a view or `--json` is handed is in the file, in order, as the line `--json` prints.
    printed = [json.dumps(event.as_json(), ensure_ascii=True, default=str) for event in seen]
    assert printed and [line for line, row in zip(lines, rows, strict=True) if "time" not in row] == printed
    diagnoser = [row for row in rows if row.get("gen_ai.agent.name") == "diagnoser"]
    assert [row["event"] for row in diagnoser] == ["model", "tool", "model", "tool", "model"]
    assert [row["contexer.tool.status"] for row in diagnoser if row["event"] == "tool"] == ["failed", "repaired"]
    # No prompt: neither the coding agent's nor the Diagnoser's task, nor what the Diagnoser read.
    raw = "\n".join(lines)
    plain = [line.strip() for line in COUNT_BUG_JS.splitlines() if '"' not in line and "\\" not in line]
    source_line = max(plain, key=len)
    assert len(source_line) > 20 and source_line not in raw
    assert agent.prompts[0].splitlines()[0] not in raw


async def test_run_json_counts_the_repaired_tool_calls_of_each_agent(tmp_path: Path) -> None:
    project = copy_todo(tmp_path)
    agent = RecordingAgent([{"app.js": COUNT_BUG_JS}, {"app.js": GOOD_JS}])
    controller = GraphController(
        project, agent, RunSettings(max_repair_rounds=2), runner=fast_runner(), model=_diagnoser_that_repairs_a_call()
    )
    outcome = await controller.run(contract(project))

    assert {row.agent: row.repaired_calls for row in outcome.agents}["diagnoser"] == 1
    saved = json.loads((Path(outcome.run_dir) / "run.json").read_text(encoding="utf-8"))
    by_agent = {row["agent"]: row["repaired_calls"] for row in saved["agents"]}
    assert by_agent["diagnoser"] == 1
    assert all(count == 0 for name, count in by_agent.items() if name != "diagnoser")
