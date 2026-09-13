"""Tests for agent runtime event streaming, event dataclasses, and cooperative cancellation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, AsyncIterator

import pytest

from contexer.config.settings import ContexerConfig
from contexer.llm.base import LLMChunk, LLMProvider, LLMResponse, ToolCallRequest
from contexer.runtime.agent import ContexerAgent
from contexer.runtime.events import (
    AgentEndEvent,
    AgentErrorEvent,
    AgentEvent,
    AgentEventType,
    AgentStartEvent,
    TextCompleteEvent,
    TextDeltaEvent,
    ToolCallCompleteEvent,
    ToolCallStartEvent,
)
from contexer.tools.base import ToolResult


def test_agent_event_dataclasses() -> None:
    start = AgentEvent.agent_start("Hello", run_id="123")
    assert isinstance(start, AgentStartEvent)
    assert start.type == AgentEventType.AGENT_START
    assert start.data == {"message": "Hello", "run_id": "123"}

    delta = AgentEvent.text_delta("world")
    assert isinstance(delta, TextDeltaEvent)
    assert delta.type == AgentEventType.TEXT_DELTA
    assert delta.data == {"content": "world"}

    res = ToolResult.success_result("output")
    complete = AgentEvent.tool_call_complete("call_1", "read_file", res)
    assert isinstance(complete, ToolCallCompleteEvent)
    assert complete.type == AgentEventType.TOOL_CALL_COMPLETE
    assert complete.data["success"] is True


class MockStreamingProvider(LLMProvider):
    """Provider yielding a tool call then final text chunks."""

    def __init__(self) -> None:
        self.turns = 0

    @property
    def name(self) -> str:
        return "mock_provider"

    @property
    def model(self) -> str:
        return "mock_model"

    def validate_configuration(self) -> tuple[bool, str | None]:
        return True, None

    async def generate(
        self,
        prompt: str | list[Any],
        system_instruction: str | None = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        return LLMResponse(text="non-streaming response")

    async def stream(
        self,
        prompt: str | list[Any],
        system_instruction: str | None = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMChunk]:
        self.turns += 1
        if self.turns == 1:
            yield LLMChunk(
                tool_calls=[
                    ToolCallRequest(
                        name="list_directory",
                        arguments={"path": "."},
                        call_id="call_list",
                    )
                ]
            )
        else:
            yield LLMChunk(text="Here are ")
            yield LLMChunk(text="the files.")


def test_agent_run_event_stream(tmp_path: Path) -> None:
    (tmp_path / "test.txt").write_text("hello", encoding="utf-8")
    provider = MockStreamingProvider()
    agent = ContexerAgent(
        config=ContexerConfig(approval_policy="auto"),
        llm=provider,
        repo_path=tmp_path,
    )

    async def _collect() -> list[AgentEvent]:
        collected = []
        async for event in agent.run("List files"):
            collected.append(event)
        return collected

    events = asyncio.run(_collect())

    event_types = [e.type for e in events]
    assert AgentEventType.AGENT_START in event_types
    assert AgentEventType.TOOL_CALL_START in event_types
    assert AgentEventType.TOOL_CALL_COMPLETE in event_types
    assert AgentEventType.TEXT_DELTA in event_types
    assert AgentEventType.TEXT_COMPLETE in event_types
    assert AgentEventType.AGENT_END in event_types

    # First event is start
    assert events[0].type == AgentEventType.AGENT_START

    # Final event is end
    assert events[-1].type == AgentEventType.AGENT_END


def test_cooperative_cancellation(tmp_path: Path) -> None:
    provider = MockStreamingProvider()
    agent = ContexerAgent(
        config=ContexerConfig(approval_policy="auto"),
        llm=provider,
        repo_path=tmp_path,
    )

    # Request cancellation before run starts
    agent.session.request_cancel()
    assert agent.session.cancel_requested is True

    async def _collect() -> list[AgentEvent]:
        collected = []
        async for event in agent.run("List files"):
            collected.append(event)
        return collected

    events = asyncio.run(_collect())

    event_types = [e.type for e in events]
    assert AgentEventType.AGENT_START in event_types
    # Should exit immediately with text delta or end event
    assert AgentEventType.TOOL_CALL_START not in event_types
    assert events[-1].type == AgentEventType.AGENT_END
