"""Unit tests for the async MCP client and protocol handling."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any
import pytest

from contexer.mcp.client import (
    MCPClient,
    MCPConnectionError,
    MCPProtocolError,
    MCPTimeoutError,
    MCPTool,
)

# A minimal mock MCP server script that runs via python -c
MOCK_SERVER_SCRIPT = """
import sys
import json

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    req = json.loads(line)
    method = req.get("method")
    req_id = req.get("id")

    if method == "initialize":
        res = {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mock-github-mcp-server", "version": "1.0.0"}
            }
        }
        sys.stdout.write(json.dumps(res) + "\\n")
        sys.stdout.flush()
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        res = {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "get_file_contents",
                        "description": "Get file contents from repository",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "owner": {"type": "string"},
                                "repo": {"type": "string"},
                                "path": {"type": "string"}
                            },
                            "required": ["owner", "repo", "path"]
                        }
                    },
                    {
                        "name": "issue_read",
                        "description": "Read issue details",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "owner": {"type": "string"},
                                "repo": {"type": "string"},
                                "issue_number": {"type": "integer"}
                            },
                            "required": ["owner", "repo", "issue_number"]
                        }
                    }
                ]
            }
        }
        sys.stdout.write(json.dumps(res) + "\\n")
        sys.stdout.flush()
    elif method == "tools/call":
        params = req.get("params", {})
        tool_name = params.get("name")
        args = params.get("arguments", {})

        if tool_name == "get_file_contents":
            path = args.get("path")
            res = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"# Content of {path}"}]
                }
            }
        elif tool_name == "error_tool":
            res = {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32603, "message": "Simulated internal error"}
            }
        elif tool_name == "is_error_tool":
            res = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "isError": True,
                    "content": [{"type": "text", "text": "Repository not found"}]
                }
            }
        else:
            res = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Called {tool_name} with {args}"}]
                }
            }
        sys.stdout.write(json.dumps(res) + "\\n")
        sys.stdout.flush()
"""


@pytest.mark.anyio
async def test_mcp_client_handshake_and_tool_discovery():
    client = MCPClient(
        command=sys.executable,
        args=["-u", "-c", MOCK_SERVER_SCRIPT],
        timeout=5.0,
    )
    async with client:
        assert client.is_connected is True
        assert client.server_info.get("name") == "mock-github-mcp-server"
        assert client.protocol_version == "2024-11-05"

        tools = await client.list_tools()
        assert len(tools) == 2
        tool_names = [t.name for t in tools]
        assert "get_file_contents" in tool_names
        assert "issue_read" in tool_names

        # Check schema structure
        file_tool = next(t for t in tools if t.name == "get_file_contents")
        assert file_tool.input_schema["type"] == "object"
        assert "owner" in file_tool.input_schema["properties"]


@pytest.mark.anyio
async def test_mcp_client_call_tool_success():
    client = MCPClient(
        command=sys.executable,
        args=["-u", "-c", MOCK_SERVER_SCRIPT],
        timeout=5.0,
    )
    async with client:
        result = await client.call_tool(
            "get_file_contents",
            {"owner": "octocat", "repo": "Hello-World", "path": "README.md"},
        )
        assert result == "# Content of README.md"


@pytest.mark.anyio
async def test_mcp_client_call_tool_protocol_error():
    client = MCPClient(
        command=sys.executable,
        args=["-u", "-c", MOCK_SERVER_SCRIPT],
        timeout=5.0,
    )
    async with client:
        with pytest.raises(MCPProtocolError) as exc_info:
            await client.call_tool("error_tool", {})
        assert "Simulated internal error" in str(exc_info.value)


@pytest.mark.anyio
async def test_mcp_client_call_tool_is_error_flag():
    client = MCPClient(
        command=sys.executable,
        args=["-u", "-c", MOCK_SERVER_SCRIPT],
        timeout=5.0,
    )
    async with client:
        output = await client.call_tool("is_error_tool", {})
        assert output.startswith("Error:")
        assert "Repository not found" in output


@pytest.mark.anyio
async def test_mcp_client_connection_error_invalid_command():
    client = MCPClient(
        command="non_existent_binary_xyz_123",
        timeout=1.0,
    )
    with pytest.raises(MCPConnectionError) as exc_info:
        await client.start()
    assert "Failed to start MCP server" in str(exc_info.value)


@pytest.mark.anyio
async def test_mcp_client_timeout():
    # Mock server that sleeps forever on tools/call
    hang_script = """
import sys, time, json
for line in sys.stdin:
    req = json.loads(line)
    if req.get("method") == "initialize":
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": {"protocolVersion": "2024-11-05"}}) + "\\n")
        sys.stdout.flush()
    elif req.get("method") == "tools/call":
        time.sleep(10)
"""
    client = MCPClient(
        command=sys.executable,
        args=["-u", "-c", hang_script],
        timeout=0.5,
    )
    async with client:
        with pytest.raises(MCPTimeoutError):
            await client.call_tool("test", {})
