"""Transcripts: every agent step is on disk afterwards, with no secret in it; tracing is opt-in."""

from __future__ import annotations

import importlib.abc
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from pydantic import BaseModel

from contexer.crew import AgentSpec, run_agent
from contexer.crew.transcript import Masker, Transcript, read_transcript, tracing_callbacks
from contexer.verification.checks import MASK
from tests.fakes import ScriptedChatModel, calls, submit

pytestmark = pytest.mark.anyio

PASSWORD = "hunter2-correct-horse"
API_KEY = "sk-or-v1-" + "a1b2c3d4" * 6


class Report(BaseModel):
    summary: str


SPEC = AgentSpec(name="tester", system_prompt="You test web apps.", output_schema=Report)


@tool
def read_page(page: str) -> str:
    """Read a page of the app."""
    return f"{page}: signed in as admin with password {PASSWORD}; key {API_KEY}"


def _lines(run_dir: Path, agent: str = "tester") -> list[dict[str, Any]]:
    return read_transcript(run_dir / "agents" / f"{agent}.jsonl")


async def test_one_line_per_model_call_and_tool_call_with_timing_and_tokens(tmp_path: Path) -> None:
    model = ScriptedChatModel(calls(("read_page", {"page": "home"}), text="Looking."), submit(summary="fine"))
    result = await run_agent(SPEC, model, [read_page], "Test the app.", run_dir=tmp_path)

    assert result.transcript == tmp_path / "agents" / "tester.jsonl"
    lines = _lines(tmp_path)
    assert [line["event"] for line in lines] == ["start", "model", "tool", "model", "end"]
    assert all(line["agent"] == "tester" and line["at"].endswith("Z") for line in lines)

    start, first, called, second, end = lines
    assert start["input"] == "Test the app." and start["tools"] == ["read_page", "submit"]
    assert start["model"] == "model 'scripted-model'" and start["max_steps"] == SPEC.max_steps
    assert (first["step"], first["tokens_in"], first["tokens_out"]) == (1, 10, 5)
    assert first["text"] == "Looking."
    assert first["tool_calls"] == [{"name": "read_page", "args": {"page": "home"}}]
    assert first["seconds"] >= 0 and called["seconds"] >= 0
    assert (called["step"], called["name"], called["args"], called["status"]) == (1, "read_page", {"page": "home"}, "success")
    assert second["tool_calls"] == [{"name": "submit", "args": {"summary": "fine"}}]
    assert (end["status"], end["steps"], end["tool_calls"]) == ("ok", 2, 1)
    assert (end["tokens_in"], end["tokens_out"], end["output"]) == (20, 10, {"summary": "fine"})


async def test_a_secret_in_a_tool_result_is_masked_in_the_transcript_and_before_the_model_sees_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", API_KEY)
    model = ScriptedChatModel(
        calls(("read_page", {"page": f"login?password={PASSWORD}"})),
        submit(summary=f"The password {PASSWORD} is shown on the page"),
    )
    result = await run_agent(SPEC, model, [read_page], "Test the app.", run_dir=tmp_path, secrets=[PASSWORD])

    raw = (tmp_path / "agents" / "tester.jsonl").read_text(encoding="utf-8")
    assert PASSWORD not in raw and API_KEY not in raw
    called = next(line for line in _lines(tmp_path) if line["event"] == "tool")
    assert called["result"] == f"login?password={MASK}: signed in as admin with password {MASK}; key {MASK}"
    assert called["args"] == {"page": f"login?password={MASK}"}
    assert _lines(tmp_path)[-1]["output"] == {"summary": f"The password {MASK} is shown on the page"}
    # The model never received the secret either: what a tool returns is masked before it becomes a prompt.
    [observed] = [m for m in model.seen[1] if isinstance(m, ToolMessage)]
    assert PASSWORD not in observed.content and API_KEY not in observed.content and MASK in observed.content
    assert result.status == "ok"


async def test_anything_shaped_like_an_api_key_is_masked_even_when_nobody_named_it(tmp_path: Path) -> None:
    model = ScriptedChatModel(calls(("read_page", {"page": "settings"})), submit(summary="ok"))
    await run_agent(SPEC, model, [read_page], "Test the app.", run_dir=tmp_path)

    raw = (tmp_path / "agents" / "tester.jsonl").read_text(encoding="utf-8")
    assert API_KEY not in raw and "sk-or-v1-...[MASKED]" in raw


async def test_a_run_that_ends_on_a_limit_or_an_error_still_closes_its_transcript(tmp_path: Path) -> None:
    slow = ScriptedChatModel(*[calls(("read_page", {"page": "home"})) for _ in range(50)], delay=0.05)
    spec = AgentSpec(name="slow", system_prompt="x", output_schema=Report, timeout=0.2, max_steps=50)
    await run_agent(spec, slow, [read_page], "Go.", run_dir=tmp_path)
    assert _lines(tmp_path, "slow")[-1]["status"] == "timeout"

    failing = ScriptedChatModel(RuntimeError("Error code: 500 - upstream broke"))
    spec = AgentSpec(name="failing", system_prompt="x", output_schema=Report)
    await run_agent(spec, failing, [], "Go.", run_dir=tmp_path)
    start, failed_call, end = _lines(tmp_path, "failing")
    assert failed_call["event"] == "model" and "500" in failed_call["error"]
    assert (end["status"], "500" in end["error"]) == ("model_error", True)


async def test_a_second_run_of_the_same_agent_appends_and_odd_names_make_safe_files(tmp_path: Path) -> None:
    for _ in range(2):
        await run_agent(SPEC, ScriptedChatModel(submit(summary="ok")), [], "Go.", run_dir=tmp_path)
    assert [line["event"] for line in _lines(tmp_path)] == ["start", "model", "end"] * 2

    spec = AgentSpec(name="../re viewer", system_prompt="x", output_schema=Report)
    result = await run_agent(spec, ScriptedChatModel(submit(summary="ok")), [], "Go.", run_dir=tmp_path)
    assert result.transcript == tmp_path / "agents" / "re-viewer.jsonl"


async def test_without_a_run_folder_nothing_is_written(tmp_path: Path) -> None:
    result = await run_agent(SPEC, ScriptedChatModel(submit(summary="ok")), [], "Go.", run_dir=None)
    assert result.transcript is None
    Transcript(None, "tester").write("model", text="hello")  # a no-op, not an error
    assert list(tmp_path.iterdir()) == []


def test_the_masker_reaches_nested_values_and_leaves_short_words_alone() -> None:
    masker = Masker([PASSWORD, "ab"], env={"GITHUB_TOKEN": "ghp_abcdefghijklmnop"})
    data = {"args": {"value": PASSWORD, "list": [f"x {PASSWORD}", 3, None]}, "note": "ab ghp_abcdefghijklmnop"}
    assert masker.data(data) == {"args": {"value": MASK, "list": [f"x {MASK}", 3, None]}, "note": f"ab {MASK}"}


# -- Langfuse ------------------------------------------------------------------


class _RefuseLangfuse(importlib.abc.MetaPathFinder):
    def find_spec(self, name: str, path: Any, target: Any = None) -> None:
        if name == "langfuse" or name.startswith("langfuse."):
            raise AssertionError("langfuse was imported although tracing is not configured")
        return None


@pytest.fixture
def no_langfuse_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    for name in [n for n in os.environ if n.startswith("LANGFUSE_")]:
        monkeypatch.delenv(name)


async def test_without_langfuse_variables_nothing_is_imported_and_no_callback_is_attached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_langfuse_variables: None
) -> None:
    for name in [n for n in sys.modules if n == "langfuse" or n.startswith("langfuse.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(sys, "meta_path", [_RefuseLangfuse(), *sys.meta_path])

    assert tracing_callbacks() == []
    model = ScriptedChatModel(submit(summary="ok"))
    result = await run_agent(SPEC, model, [], "Go.", run_dir=tmp_path)

    assert result.status == "ok"
    assert "langfuse" not in sys.modules
    assert model.callbacks_seen == [0]  # the model call carried no callback handler at all


async def test_with_langfuse_variables_the_handler_follows_every_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[str] = []

    class CallbackHandler(BaseCallbackHandler):
        def on_chat_model_start(self, serialized: Any, messages: Any, **kwargs: Any) -> None:
            started.append("model call")

    package = types.ModuleType("langfuse")
    module = types.ModuleType("langfuse.langchain")
    module.CallbackHandler = CallbackHandler  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langfuse", package)
    monkeypatch.setitem(sys.modules, "langfuse.langchain", module)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test-secret")

    model = ScriptedChatModel(calls(("read_page", {"page": "home"})), submit(summary="ok"))
    await run_agent(SPEC, model, [read_page], "Go.", run_dir=tmp_path)

    assert started == ["model call", "model call"]


def test_langfuse_variables_without_the_package_warn_and_leave_tracing_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "langfuse", None)  # importing it now raises ImportError
    monkeypatch.setitem(sys.modules, "langfuse.langchain", None)
    env = {"LANGFUSE_PUBLIC_KEY": "pk-lf-test", "LANGFUSE_SECRET_KEY": "sk-lf-test-secret"}
    with pytest.warns(UserWarning, match=r"contexer-agent\[tracing\]"):
        assert tracing_callbacks(env) == []
    assert tracing_callbacks({"LANGFUSE_PUBLIC_KEY": "pk-lf-test"}) == []  # half configured is not configured
