"""Unit tests for GitHub MCP adapter, tool registration, read-only enforcement, and CLI command."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from contexer.cli.commands import CommandRouter
from contexer.cli.repl import ContexerApp
from contexer.cli.ui import UIRenderer
from contexer.config.settings import ContexerConfig
from contexer.mcp.adapter import (
    GitHubMCPConnectionResult,
    register_mcp_tools,
)
from contexer.mcp.client import MCPClient, MCPTool
from contexer.tools.base import ToolKind
from contexer.tools.registry import ToolRegistry


def test_register_mcp_tools_enforces_read_only():
    registry = ToolRegistry()
    mock_client = MagicMock(spec=MCPClient)

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
        ),
        MCPTool(
            name="create_issue",
            description="Create a new issue on GitHub",
            input_schema={"type": "object", "properties": {"title": {"type": "string"}}},
        ),
        MCPTool(
            name="push_files",
            description="Commit and push changes",
            input_schema={"type": "object", "properties": {}},
        ),
        MCPTool(
            name="issue_read",
            description="Get details about an issue",
            input_schema={"type": "object", "properties": {"issue_number": {"type": "integer"}}},
        ),
    ]

    registered = register_mcp_tools(registry, mock_client, tools, read_only=True)

    # create_issue and push_files should have been filtered out!
    registered_names = [t.name for t in registered]
    assert "get_file_contents" in registered_names
    assert "issue_read" in registered_names
    assert "create_issue" not in registered_names
    assert "push_files" not in registered_names

    # Check kind is READ
    for tool in registered:
        assert tool.kind == ToolKind.READ
        assert not tool.is_mutating()


def test_registered_mcp_tool_schema_declaration():
    registry = ToolRegistry()
    mock_client = MagicMock(spec=MCPClient)

    schema = {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "Repository owner"},
            "repo": {"type": "string", "description": "Repository name"},
        },
        "required": ["owner", "repo"],
    }
    tools = [MCPTool(name="get_repo", description="Get repository metadata", input_schema=schema)]
    register_mcp_tools(registry, mock_client, tools, read_only=True)

    tool = registry.get("get_repo")
    assert tool is not None

    declaration = tool.to_tool_declaration()
    assert declaration["type"] == "function"
    assert declaration["function"]["name"] == "get_repo"
    assert declaration["function"]["description"] == "[GitHub] Get repository metadata"
    assert declaration["function"]["parameters"] == schema


@pytest.mark.anyio
async def test_invoke_registered_mcp_tool_executes_client():
    registry = ToolRegistry()
    mock_client = MagicMock(spec=MCPClient)
    mock_client.call_tool = AsyncMock(return_value="# Project README\nWelcome to our project.")

    tools = [
        MCPTool(
            name="get_file_contents",
            description="Read a file",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        )
    ]
    register_mcp_tools(registry, mock_client, tools, read_only=True)

    res = await registry.invoke("get_file_contents", {"path": "README.md"})
    assert res.success is True
    assert "Project README" in res.output
    mock_client.call_tool.assert_awaited_once_with("get_file_contents", {"path": "README.md"})


def test_cli_github_command_missing_token():
    config = ContexerConfig(github_token=None)
    app = MagicMock(spec=ContexerApp)
    app.config = config
    app.ui = UIRenderer()
    app.target_workspace = None

    router = CommandRouter()
    with patch.dict(
        "os.environ",
        {"GITHUB_PERSONAL_ACCESS_TOKEN": "", "GITHUB_TOKEN": "", "GH_TOKEN": ""},
        clear=False,
    ):
        # Should not raise any error
        result = router.dispatch(app, "/github")
        assert result is None


def test_cli_github_command_connected_flow():
    config = ContexerConfig(github_token="ghp_test_mock_token")
    app = MagicMock(spec=ContexerApp)
    app.config = config
    app.ui = UIRenderer()
    app.target_workspace = None

    mock_client = MagicMock(spec=MCPClient)
    mock_client.close = AsyncMock()

    mock_res = GitHubMCPConnectionResult(
        connected=True,
        read_only=True,
        tools=[
            MCPTool(name="get_file_contents", description="Read repo file"),
            MCPTool(name="issue_read", description="Read issue"),
        ],
        client=mock_client,
    )

    router = CommandRouter()
    with patch(
        "contexer.mcp.adapter.connect_and_discover_github_mcp",
        AsyncMock(return_value=mock_res),
    ), patch(
        "contexer.mcp.server.GitHubMCPServerRunner.resolve_executable",
        return_value=("github-mcp-server", ["stdio"]),
    ):
        result = router.dispatch(app, "/github")
        assert result is None
