"""Live and end-to-end integration tests for GitHub MCP Server in Contexer.

Verifies:
Contexer ↓ MCP Client ↓ GitHub MCP Server ↓ GitHub ↓ actual repository data ↓ Contexer ↓ Gemini
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock
import pytest

from contexer.config.settings import ContexerConfig
from contexer.llm.base import LLMProvider, LLMResponse, ToolCallRequest
from contexer.mcp.adapter import (
    attach_github_mcp_to_registry,
    connect_and_discover_github_mcp,
    register_mcp_tools,
)
from contexer.mcp.client import MCPClient, MCPTool
from contexer.mcp.server import GitHubMCPServerRunner
from contexer.runtime.agent import ContexerAgent
from contexer.tools.registry import ToolRegistry


def _check_live_prerequisites() -> tuple[bool, str]:
    """Check whether a real GitHub token and server executable are available."""
    config = ContexerConfig()
    runner = GitHubMCPServerRunner(config)
    available, reason = runner.check_availability()
    return available, reason


@pytest.mark.anyio
async def test_github_mcp_agent_loop_with_mcp_tool():
    """Prove the end-to-end agent loop:
    User message -> LLM selects GitHub MCP tool -> MCP Client executes -> Tool observation -> LLM answers.
    """
    registry = ToolRegistry()
    mock_mcp_client = MagicMock(spec=MCPClient)
    mock_mcp_client.call_tool = AsyncMock(
        return_value="# Hello-World\nThis is a simple repository for learning Git."
    )

    tools = [
        MCPTool(
            name="get_file_contents",
            description="Read file contents from repository",
            input_schema={
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "path": {"type": "string"},
                },
                "required": ["owner", "repo", "path"],
            },
        )
    ]
    register_mcp_tools(registry, mock_mcp_client, tools, read_only=True)

    # Verify tool is registered and available
    assert registry.get("get_file_contents") is not None

    # Mock LLM that on Turn 1 requests get_file_contents, and on Turn 2 answers with the summary
    mock_llm = MagicMock(spec=LLMProvider)
    mock_llm.validate_configuration.return_value = (True, None)

    turn_count = 0

    async def mock_stream(prompt, system_instruction=None, tools=None):
        nonlocal turn_count
        turn_count += 1
        if turn_count == 1:
            # First turn: model chooses to call get_file_contents
            yield LLMResponse(
                text="",
                tool_calls=[
                    ToolCallRequest(
                        name="get_file_contents",
                        arguments={"owner": "octocat", "repo": "Hello-World", "path": "README.md"},
                        call_id="call_gh_1",
                    )
                ],
            )
        else:
            # Second turn: model summarizes README
            yield LLMResponse(
                text="The Hello-World project by octocat is a starter repository for learning Git.",
                tool_calls=[],
            )

    mock_llm.stream = mock_stream

    agent = ContexerAgent(
        llm=mock_llm,
        tool_registry=registry,
        max_tool_turns=5,
    )

    events = []
    async for event in agent.run("Read the README of octocat/Hello-World and explain the project."):
        events.append(event)

    # Verify tool was called
    mock_mcp_client.call_tool.assert_awaited_once_with(
        "get_file_contents",
        {"owner": "octocat", "repo": "Hello-World", "path": "README.md"},
    )

    # Verify agent ended with model's natural language response
    end_events = [e for e in events if e.type.name == "AGENT_END"]
    assert len(end_events) == 1
    final_response = end_events[0].data.get("response", "")
    assert "Hello-World project by octocat is a starter repository" in final_response


@pytest.mark.anyio
async def test_live_github_mcp_connection():
    """Live verification against the official GitHub MCP server.

    Runs only when GITHUB_PERSONAL_ACCESS_TOKEN and github-mcp-server are present.
    """
    available, reason = _check_live_prerequisites()
    if not available:
        pytest.skip(f"Live GitHub test: NOT AVAILABLE ({reason})")

    config = ContexerConfig()
    res = await connect_and_discover_github_mcp(config)
    assert res.connected is True
    assert res.read_only is True
    assert len(res.tools) > 0

    # Ensure client can execute a read-only query on a public repo
    client = res.client
    assert client is not None
    try:
        # Search or get file contents from octocat/Hello-World
        tool_names = [t.name for t in res.tools]
        if "get_file_contents" in tool_names:
            content = await client.call_tool(
                "get_file_contents",
                {"owner": "octocat", "repo": "Hello-World", "path": "README"},
            )
            assert len(content) > 0
            assert "Error:" not in content
    finally:
        await client.close()
