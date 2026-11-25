"""``contexer mcp``: serve this project's checks to a coding agent over the Model Context Protocol."""

from __future__ import annotations

from pathlib import Path

import typer

from contexer.cli.gate_cli import DirOption


def mcp(project_dir: Path = DirOption) -> None:
    """Serve the approved checks to a coding agent (Claude Code, Codex, OpenCode, Cursor) over MCP, on stdio.

    The agent can read the checks, have them replayed in a browser, and read how the last run ended.
    It cannot approve or edit a check. Add it to an agent with, for Claude Code:
    `claude mcp add contexer -- contexer mcp`.
    """
    # stdout carries the protocol and nothing else, so this command prints nothing itself.
    from contexer.integrations.mcp_server import serve

    try:
        serve(project_dir)
    except KeyboardInterrupt:
        raise typer.Exit(code=130) from None
