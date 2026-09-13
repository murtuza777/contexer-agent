"""Tests for the ContexerAgent tool loop and multi-turn execution."""

import asyncio
from typing import Any, AsyncIterator
from unittest.mock import MagicMock

import pytest

from contexer.llm.base import LLMChunk, LLMProvider, LLMResponse, ToolCallRequest
from contexer.runtime.agent import AgentResult, AgentState, ContexerAgent
from contexer.tools.registry import ToolRegistry
from contexer.tools.schemas import ListDirectoryArgs, ReadFileArgs, Tool


class MockMultiTurnLLM(LLMProvider):
    """Mock LLM simulating multi-turn tool calling before emitting text."""

    def __init__(self, turns: list[LLMResponse]) -> None:
        self.turns = list(turns)
        self.call_count = 0
        self.calls: list[Any] = []

    @property
    def name(self) -> str:
        return "mock_multi_turn"

    @property
    def model(self) -> str:
        return "mock-model"

    def validate_configuration(self) -> tuple[bool, str | None]:
        return True, None

    async def generate(
        self,
        prompt: str | list[Any],
        system_instruction: str | None = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        self.calls.append(prompt)
        if self.call_count < len(self.turns):
            response = self.turns[self.call_count]
            self.call_count += 1
            return response
        return LLMResponse(text="Final fallback", model="mock-model")

    async def stream(
        self,
        prompt: str | list[Any],
        system_instruction: str | None = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMChunk]:
        if self.call_count < len(self.turns):
            response = self.turns[self.call_count]
            self.call_count += 1
            if response.tool_calls:
                yield LLMChunk(tool_calls=response.tool_calls)
            else:
                for word in response.text.split():
                    yield LLMChunk(text=word + " ")


class TestAgentToolLoop:
    """Agent tool calling, sequential turns, and callback verification."""

    def test_single_tool_call_loop(self) -> None:
        # Turn 1: Model asks for list_directory
        # Turn 2: Model returns synthesized answer
        turn1 = LLMResponse(
            tool_calls=[ToolCallRequest(name="list_directory", arguments={"path": "."})]
        )
        turn2 = LLMResponse(text="The repository contains main.py and README.md.")

        llm = MockMultiTurnLLM([turn1, turn2])
        registry = ToolRegistry()
        registry.register(
            Tool(
                name="list_directory",
                description="List directory",
                args_schema=ListDirectoryArgs,
                handler=lambda path=".": "main.py\nREADME.md",
            )
        )

        agent = ContexerAgent(llm=llm, tool_registry=registry)

        started_tools = []
        ended_tools = []

        result = asyncio.run(
            agent.process_message(
                "What files are here?",
                on_tool_start=lambda name: started_tools.append(name),
                on_tool_end=lambda name, success: ended_tools.append((name, success)),
            )
        )

        assert result.state == AgentState.COMPLETED
        assert result.response == "The repository contains main.py and README.md."
        assert result.tool_calls == ["list_directory"]
        assert started_tools == ["list_directory"]
        assert ended_tools == [("list_directory", True)]
        assert llm.call_count == 2

    def test_sequential_multi_tool_loop(self) -> None:
        # Turn 1: list_directory
        # Turn 2: read_file
        # Turn 3: final answer
        turn1 = LLMResponse(
            tool_calls=[ToolCallRequest(name="list_directory", arguments={"path": "."})]
        )
        turn2 = LLMResponse(
            tool_calls=[ToolCallRequest(name="read_file", arguments={"path": "README.md"})]
        )
        turn3 = LLMResponse(text="This project is Contexer.")

        llm = MockMultiTurnLLM([turn1, turn2, turn3])
        registry = ToolRegistry()
        registry.register(
            Tool(
                name="list_directory",
                description="List directory",
                args_schema=ListDirectoryArgs,
                handler=lambda path=".": "README.md",
            )
        )
        registry.register(
            Tool(
                name="read_file",
                description="Read file",
                args_schema=ReadFileArgs,
                handler=lambda path, offset=0, limit=500: "# Contexer Project",
            )
        )

        agent = ContexerAgent(llm=llm, tool_registry=registry)
        result = asyncio.run(agent.process_message("Explain what this project is."))

        assert result.state == AgentState.COMPLETED
        assert result.response == "This project is Contexer."
        assert result.tool_calls == ["list_directory", "read_file"]
        assert llm.call_count == 3

    def test_stream_tool_loop_with_callbacks(self) -> None:
        turn1 = LLMResponse(
            tool_calls=[ToolCallRequest(name="list_directory", arguments={"path": "."})]
        )
        turn2 = LLMResponse(text="Files listed.")

        llm = MockMultiTurnLLM([turn1, turn2])
        registry = ToolRegistry()
        registry.register(
            Tool(
                name="list_directory",
                description="List directory",
                args_schema=ListDirectoryArgs,
                handler=lambda path=".": "main.py",
            )
        )

        agent = ContexerAgent(llm=llm, tool_registry=registry)

        tool_starts = []
        tool_ends = []
        stream_started = []

        async def run_stream():
            tokens = []
            async for token in agent.stream_message(
                "List files",
                on_tool_start=lambda name: tool_starts.append(name),
                on_tool_end=lambda name, succ: tool_ends.append((name, succ)),
                on_stream_start=lambda: stream_started.append(True),
            ):
                tokens.append(token)
            return "".join(tokens)

        text = asyncio.run(run_stream())
        assert "Files listed." in text
        assert tool_starts == ["list_directory"]
        assert tool_ends == [("list_directory", True)]
        assert stream_started == [True]

    def test_stall_guard_identical_loop_warning(self) -> None:
        call = ToolCallRequest(name="read_file", arguments={"path": "same.txt", "offset": 0, "limit": 500})
        turn1 = LLMResponse(tool_calls=[call])
        turn2 = LLMResponse(tool_calls=[call])
        turn3 = LLMResponse(tool_calls=[call])
        turn4 = LLMResponse(text="Stopped looping.")

        llm = MockMultiTurnLLM([turn1, turn2, turn3, turn4])
        registry = ToolRegistry()
        executed_outputs = []

        def mock_read(path, offset=0, limit=500):
            return "File contents"

        registry.register(
            Tool(
                name="read_file",
                description="Read file",
                args_schema=ReadFileArgs,
                handler=mock_read,
            )
        )

        agent = ContexerAgent(llm=llm, tool_registry=registry)
        result = asyncio.run(agent.process_message("Read same file repeatedly"))

        assert result.state == AgentState.COMPLETED
        assert result.response == "Stopped looping."
        assert llm.call_count == 4
        # Verify the 3rd turn message passed to LLM has the loop warning injected in tool results
        third_call_messages = llm.calls[3]
        serialized_messages = str(third_call_messages)
        assert (
            "LOOP WARNING: Tool 'read_file' has been called 3 times consecutively" in serialized_messages
            or r"LOOP WARNING: Tool \'read_file\' has been called 3 times consecutively" in serialized_messages
        )
