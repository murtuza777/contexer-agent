"""Contexer Model Context Protocol (MCP) integration package."""

from contexer.mcp.adapter import (
    GitHubMCPConnectionResult,
    attach_github_mcp_to_registry,
    connect_and_discover_github_mcp,
    register_mcp_tools,
)
from contexer.mcp.client import (
    MCPClient,
    MCPConnectionError,
    MCPError,
    MCPProtocolError,
    MCPTimeoutError,
    MCPTool,
)
from contexer.mcp.server import GitHubMCPServerRunner

__all__ = [
    "MCPClient",
    "MCPTool",
    "MCPError",
    "MCPConnectionError",
    "MCPProtocolError",
    "MCPTimeoutError",
    "GitHubMCPServerRunner",
    "GitHubMCPConnectionResult",
    "register_mcp_tools",
    "connect_and_discover_github_mcp",
    "attach_github_mcp_to_registry",
]
