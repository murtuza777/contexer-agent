"""Adapter bridging GitHub MCP Server tools into Contexer's ToolRegistry.

Provides dynamic discovery, read-only enforcement, and schema adaptation
so that Gemini/OpenRouter can invoke GitHub MCP tools without hardcoded schemas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import BaseModel, ConfigDict

from contexer.config.settings import ContexerConfig
from contexer.mcp.client import MCPClient, MCPTool
from contexer.mcp.server import GitHubMCPServerRunner
from contexer.tools.base import Tool, ToolKind
from contexer.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# Known mutating tool patterns that must be blocked in read-only mode
_MUTATING_TOOL_KEYWORDS = {
    "create", "update", "delete", "write", "push", "merge",
    "fork", "star", "close", "reopen", "lock", "unlock",
    "assign", "label", "comment",
}


class DynamicMCPArgs(BaseModel):
    """Permissive schema container for dynamic MCP tool argument forwarding."""

    model_config = ConfigDict(extra="allow")


@dataclass
class GitHubMCPConnectionResult:
    """Outcome of attempting to connect and discover GitHub MCP tools."""

    connected: bool
    read_only: bool = True
    toolsets: str = "repos,issues"
    tools: list[MCPTool] = field(default_factory=list)
    client: Optional[MCPClient] = None
    runner_command: Optional[str] = None
    error: Optional[str] = None

    def summary(self) -> str:
        """User-friendly summary without exposing sensitive credentials."""
        if not self.connected:
            return f"GitHub MCP: Disconnected ({self.error or 'unknown error'})"
        tool_names = ", ".join(t.name for t in self.tools)
        return (
            f"GitHub MCP: Connected | Read-only: {self.read_only} | "
            f"Tools ({len(self.tools)}): {tool_names}"
        )


def _make_mcp_handler(client: MCPClient, tool_name: str) -> Callable[..., Any]:
    """Factory creating an async callable that forwards invocations to MCP."""

    async def _handler(**kwargs: Any) -> str:
        try:
            return await client.call_tool(tool_name, kwargs)
        except Exception as exc:
            logger.error("Error executing GitHub MCP tool '%s': %s", tool_name, exc)
            return f"Error executing GitHub tool '{tool_name}': {exc}"

    return _handler


def register_mcp_tools(
    registry: ToolRegistry,
    client: MCPClient,
    tools: list[MCPTool],
    *,
    read_only: bool = True,
    prefix: str = "",
) -> list[Tool]:
    """Wrap MCP tools into Contexer Tools and register them into ToolRegistry.

    Guarantees that all tools are registered with ToolKind.READ and that mutating
    operations are blocked.
    """
    registered: list[Tool] = []

    for mcp_tool in tools:
        tool_name = mcp_tool.name
        clean_lower = tool_name.lower()

        # Enforce read-only: skip any mutating tools
        if read_only:
            is_mutating = any(
                keyword in clean_lower.split("_")
                for keyword in _MUTATING_TOOL_KEYWORDS
            )
            if is_mutating:
                logger.warning(
                    "Skipping mutating tool '%s' because read-only mode is active.",
                    tool_name,
                )
                continue

        registered_name = f"{prefix}{tool_name}" if prefix else tool_name
        description = mcp_tool.description or f"GitHub MCP tool: {tool_name}"
        if "[GitHub]" not in description:
            description = f"[GitHub] {description}"

        contexer_tool = Tool(
            name=registered_name,
            description=description,
            args_schema=DynamicMCPArgs,
            handler=_make_mcp_handler(client, tool_name),
            kind=ToolKind.READ,
            parameters_schema=mcp_tool.input_schema,
        )

        registry.register(contexer_tool)
        registered.append(contexer_tool)
        logger.debug("Registered GitHub MCP tool '%s'", registered_name)

    return registered


async def connect_and_discover_github_mcp(
    config: Optional[ContexerConfig] = None,
    workspace_root: Optional[Path | str] = None,
) -> GitHubMCPConnectionResult:
    """Connect to official GitHub MCP Server, complete handshake, and list tools."""
    runner = GitHubMCPServerRunner(config)
    available, reason = runner.check_availability(workspace_root)
    if not available:
        return GitHubMCPConnectionResult(
            connected=False,
            read_only=runner.read_only,
            toolsets=runner.toolsets,
            error=reason,
        )

    client: Optional[MCPClient] = None
    try:
        client = runner.create_client(workspace_root)
        await client.start()
        discovered_tools = await client.list_tools()

        return GitHubMCPConnectionResult(
            connected=True,
            read_only=runner.read_only,
            toolsets=runner.toolsets,
            tools=discovered_tools,
            client=client,
            runner_command=client.command,
        )
    except Exception as exc:
        if client:
            await client.close()
        logger.warning("Failed to connect to GitHub MCP Server: %s", exc)
        return GitHubMCPConnectionResult(
            connected=False,
            read_only=runner.read_only,
            toolsets=runner.toolsets,
            error=f"Connection failed: {exc}",
        )


async def attach_github_mcp_to_registry(
    registry: ToolRegistry,
    config: Optional[ContexerConfig] = None,
    workspace_root: Optional[Path | str] = None,
) -> GitHubMCPConnectionResult:
    """Connect to GitHub MCP server, discover tools, and register them into ToolRegistry."""
    res = await connect_and_discover_github_mcp(config, workspace_root)
    if res.connected and res.client:
        register_mcp_tools(registry, res.client, res.tools, read_only=res.read_only)
    return res
