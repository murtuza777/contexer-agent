"""Unit tests for OpenRouter tool calling integration and message serialization."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from contexer.llm.base import ToolCallRequest
from contexer.llm.openrouter import OpenRouterProvider


class TestOpenRouterToolIntegration:
    """OpenRouter tool message construction and response extraction."""

    def test_build_user_message(self) -> None:
        provider = OpenRouterProvider(api_key="sk-or-v1-test_key")
        msg = provider.build_user_message("Hello from user")
        assert msg["role"] == "user"
        assert msg["content"] == "Hello from user"

    def test_build_assistant_tool_calls_message(self) -> None:
        provider = OpenRouterProvider(api_key="sk-or-v1-test_key")
        call = ToolCallRequest(name="list_directory", arguments={"path": "src"}, call_id="call_123")
        msg = provider.build_assistant_tool_calls_message([call])
        assert msg["role"] == "assistant"
        assert len(msg["tool_calls"]) == 1
        tc = msg["tool_calls"][0]
        assert tc["id"] == "call_123"
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "list_directory"
        assert json.loads(tc["function"]["arguments"]) == {"path": "src"}

    def test_build_tool_messages(self) -> None:
        provider = OpenRouterProvider(api_key="sk-or-v1-test_key")
        msgs = provider.build_tool_messages([("list_directory", "main.py\nutils.py", "call_123")])
        assert len(msgs) == 1
        msg = msgs[0]
        assert msg["role"] == "tool"
        assert msg["tool_call_id"] == "call_123"
        assert msg["name"] == "list_directory"
        assert msg["content"] == "main.py\nutils.py"

    def test_generate_with_mocked_tool_call(self) -> None:
        provider = OpenRouterProvider(api_key="sk-or-v1-test_key")

        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_abc_456"
        mock_tool_call.type = "function"
        mock_tool_call.function.name = "list_directory"
        mock_tool_call.function.arguments = json.dumps({"path": "."})

        mock_choice = MagicMock()
        mock_choice.message.content = ""
        mock_choice.message.tool_calls = [mock_tool_call]

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.model = "google/gemma-4-31b-it:free"
        mock_response.usage = None

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        res = asyncio.run(provider.generate("What files are here?"))
        assert len(res.tool_calls) == 1
        assert res.tool_calls[0].name == "list_directory"
        assert res.tool_calls[0].arguments == {"path": "."}
        assert res.tool_calls[0].call_id == "call_abc_456"

    def test_stream_with_mocked_tool_call(self) -> None:
        provider = OpenRouterProvider(api_key="sk-or-v1-test_key")

        class MockFunctionChunk:
            def __init__(self, name: str | None = None, arguments: str | None = None) -> None:
                self.name = name
                self.arguments = arguments

        class MockToolCallDelta:
            def __init__(self, index: int, id: str | None = None, func: MockFunctionChunk | None = None) -> None:
                self.index = index
                self.id = id
                self.function = func

        class MockDelta:
            def __init__(self, content: str | None = None, tool_calls: list | None = None) -> None:
                self.content = content
                self.tool_calls = tool_calls

        class MockChunkChoice:
            def __init__(self, delta: MockDelta, finish_reason: str | None = None) -> None:
                self.delta = delta
                self.finish_reason = finish_reason

        class MockChunk:
            def __init__(self, delta: MockDelta, finish_reason: str | None = None) -> None:
                self.choices = [MockChunkChoice(delta, finish_reason)]

        async def mock_stream():
            # Chunk 1: Tool call init with id and name
            yield MockChunk(
                MockDelta(
                    tool_calls=[
                        MockToolCallDelta(
                            index=0,
                            id="call_stream_1",
                            func=MockFunctionChunk(name="read_file", arguments='{"path": "RE'),
                        )
                    ]
                )
            )
            # Chunk 2: Tool call argument chunk continuation
            yield MockChunk(
                MockDelta(
                    tool_calls=[
                        MockToolCallDelta(
                            index=0,
                            func=MockFunctionChunk(arguments='ADME.md"}'),
                        )
                    ]
                ),
                finish_reason="tool_calls",
            )

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_stream())
        provider._client = mock_client

        async def collect():
            chunks = []
            async for chunk in provider.stream("Read readme"):
                chunks.append(chunk)
            return chunks

        chunks = asyncio.run(collect())
        tool_call_chunks = [c for c in chunks if c.tool_calls]
        assert len(tool_call_chunks) >= 1
        final_tool_calls = tool_call_chunks[-1].tool_calls
        assert len(final_tool_calls) == 1
        assert final_tool_calls[0].name == "read_file"
        assert final_tool_calls[0].arguments == {"path": "README.md"}
        assert final_tool_calls[0].call_id == "call_stream_1"
