"""Slash command registry and dispatch for the Contexer CLI.

Design principles:
    - Commands are registered declaratively via ``COMMANDS`` dict.
    - Each command is a ``CommandDef`` with name, aliases, help text,
      and a handler callable.
    - The ``CommandRouter`` resolves input → command → handler.
    - Unknown commands suggest close matches (prefix expansion).
    - New commands can be added without touching the REPL loop.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from contexer.cli.repl import ContexerApp
    from contexer.project.models import Project
    from contexer.workflow.loop import AutonomousLoop

from contexer import __version__


# ---------------------------------------------------------------------------
# Command definition
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommandDef:
    """A registered slash command."""

    name: str
    help_text: str
    aliases: tuple[str, ...] = field(default_factory=tuple)
    hidden: bool = False


# ---------------------------------------------------------------------------
# Built-in command handlers
# ---------------------------------------------------------------------------
# Each handler receives ``(app, args)`` where ``app`` is the ContexerApp
# and ``args`` is the string after the command word (may be empty).
# Returning ``False`` signals the REPL to exit.


def _cmd_help(app: ContexerApp, args: str) -> Optional[bool]:
    """Display available commands."""
    ui = app.ui
    ui.console.print()
    ui.console.print("[ctx.brand]Available Commands[/]")
    ui.print_rule()

    for cmd_def in COMMANDS.values():
        if cmd_def.hidden:
            continue
        alias_str = ""
        if cmd_def.aliases:
            alias_str = f"  [ctx.dim](aliases: {', '.join('/' + a for a in cmd_def.aliases)})[/]"
        ui.console.print(
            f"  [ctx.command]/{cmd_def.name}[/]"
            f"  [ctx.description]{cmd_def.help_text}[/]"
            f"{alias_str}"
        )

    ui.console.print()
    ui.print_dim("Type any message to send it to the agent.")
    ui.console.print()
    return None


def _cmd_exit(app: ContexerApp, args: str) -> Optional[bool]:
    """Exit the Contexer shell."""
    return False


def _cmd_version(app: ContexerApp, args: str) -> Optional[bool]:
    """Show version information."""
    app.ui.print_info(f"contexer v{__version__}")
    return None


def _cmd_clear(app: ContexerApp, args: str) -> Optional[bool]:
    """Clear the terminal screen."""
    os.system("cls" if sys.platform == "win32" else "clear")
    return None


def _cmd_status(app: ContexerApp, args: str) -> Optional[bool]:
    """Show current session status."""
    config = app.config
    ui = app.ui

    agent_status = "Connected" if app.agent else "Not connected"
    key_status = "Configured" if config.openrouter_api_key else "[ctx.warning]Missing (set OPENROUTER_API_KEY)[/]"

    ui.console.print()
    ui.console.print("[ctx.brand]Session Status[/]")
    ui.print_rule()
    ui.console.print(f"  [ctx.accent]Version:[/]   v{__version__}")
    ui.console.print(f"  [ctx.accent]Agent:[/]     {agent_status}")
    active_proj = getattr(getattr(app, "project_manager", None), "active_project", None)
    proj_str = f"{active_proj.name} ({active_proj.project_type.value}) -> {active_proj.path}" if active_proj else "sandbox (scratch)"
    ui.console.print(f"  [ctx.accent]Project:[/]   {proj_str}")
    ui.console.print(f"  [ctx.accent]Provider:[/]  {config.llm_provider}")
    ui.console.print(f"  [ctx.accent]Model:[/]     {config.openrouter_model}")
    ui.console.print(f"  [ctx.accent]API Key:[/]   {key_status}")
    ui.console.print(f"  [ctx.accent]Log Level:[/] {config.log_level}")
    ui.console.print()
    return None


def _cmd_opencode(app: ContexerApp, args: str) -> Optional[bool]:
    """Interact with OpenCode execution engine."""
    import asyncio
    from contexer.opencode.adapter import OpenCodeAdapter
    from contexer.opencode.exceptions import (
        OpenCodeConnectionError,
        OpenCodeError,
        OpenCodeTimeoutError,
    )
    from contexer.opencode.models import ExecutionStatus

    ui = app.ui
    config = app.config
    server_url = getattr(config, "opencode_server_url", "http://127.0.0.1:4096")
    provider = getattr(config, "opencode_model_provider", None) or "opencode"
    model_id = getattr(config, "opencode_model_id", None) or "nemotron-3.5-lightning-free"
    adapter = OpenCodeAdapter(
        base_url=server_url,
        timeout=getattr(config, "opencode_timeout", 120.0),
        model_provider=provider,
        model_id=model_id,
    )

    stripped = args.strip()
    if not stripped or stripped.lower() in ("status", "health"):
        async def _check_health():
            return await adapter.check_health()

        try:
            health = asyncio.run(_check_health())
            ui.console.print()
            ui.print_success("[ctx.brand]OpenCode connected[/]")
            ui.console.print(f"    [ctx.accent]Server:[/]   {server_url}")
            ui.console.print(f"    [ctx.accent]Version:[/]  v{health.version or 'unknown'}")
            ui.console.print(f"    [ctx.accent]Status:[/]   {'Healthy' if health.healthy else 'Degraded'}")
            ui.console.print()
        except OpenCodeConnectionError:
            ui.console.print()
            ui.print_error("OpenCode connection failed")
            ui.console.print(f"    OpenCode server is not reachable at {server_url}")
            ui.console.print()
        except OpenCodeError as exc:
            ui.console.print()
            ui.print_error(f"OpenCode error: {exc}")
            ui.console.print()
        return None

    # Handle prompt execution: e.g. /opencode run <prompt> [--dir <dir>]
    prompt = stripped
    if prompt.lower() == "run":
        ui.print_warning("Usage: /opencode run <prompt> [--dir <path>] or /opencode status")
        return None
    if prompt.lower().startswith("run "):
        prompt = prompt[4:].strip()

    if not prompt:
        ui.print_warning("Usage: /opencode run <prompt> [--dir <path>] or /opencode status")
        return None

    import re
    from contexer.project.manager import ProjectManager

    # Ensure project manager exists on app
    mgr = getattr(app, "project_manager", None)
    if not mgr:
        mgr = ProjectManager()
        app.project_manager = mgr

    # Parse optional --dir or -d argument
    dir_match = re.search(r'(?:--dir|-d)\s+([^\s]+)', prompt)
    if dir_match:
        dir_arg = dir_match.group(1).strip()
        prompt = re.sub(r'(?:--dir|-d)\s+[^\s]+', '', prompt).strip()
        try:
            target_proj = mgr.set_active_project(dir_arg)
        except Exception as exc:
            ui.console.print()
            ui.print_error(f"Invalid target directory: {exc}")
            ui.console.print()
            return None
    else:
        target_proj = mgr.active_project

    scope_prompt = mgr.format_scope_prompt(target_proj)

    async def _execute_task():
        await adapter.check_health()
        session = await adapter.create_session(
            title=f"Contexer Task: {target_proj.name}",
            directory=str(target_proj.path),
        )
        ui.print_dim(f"  Target Project: {target_proj.name} ({target_proj.path})")
        ui.print_dim(f"  Session created: {session.id} ({session.slug or 'default'})")
        ui.console.print("  [ctx.accent]OpenCode working...[/]")

        full_prompt = f"{scope_prompt}\n{prompt}"
        result = await adapter.send_prompt(
            session_id=session.id,
            prompt=full_prompt,
            wait=True,
            timeout=getattr(config, "opencode_timeout", 120.0),
        )
        return session, result

    try:
        session, result = asyncio.run(_execute_task())
        ui.console.print()
        if result.status == ExecutionStatus.COMPLETED:
            ui.print_success(f"[ctx.brand]OpenCode completed in {result.duration_seconds:.1f}s[/]")
        elif result.status == ExecutionStatus.ABORTED:
            ui.print_warning("OpenCode execution was aborted")
        else:
            ui.print_error(f"OpenCode execution failed: {result.error}")

        if result.response_text:
            ui.console.print()
            ui.console.print("[ctx.accent]Summary:[/]")
            ui.console.print(f"  {result.response_text}")

        if result.diff:
            ui.console.print()
            ui.console.print("[ctx.accent]Changed files:[/]")
            for item in result.diff:
                ui.console.print(f"  [ctx.success]+[/] {item.file} (+{item.additions}, -{item.deletions})")
            ui.console.print()
            ui.console.print("[ctx.accent]Diff:[/]")
            for item in result.diff:
                if item.patch:
                    ui.console.print(f"[ctx.dim]{item.patch}[/]")
        else:
            ui.console.print()
            ui.print_dim("No repository files modified.")
        ui.console.print()

    except OpenCodeConnectionError:
        ui.console.print()
        ui.print_error("OpenCode connection failed")
        ui.console.print(f"    OpenCode server is not reachable at {server_url}")
        ui.console.print()
    except OpenCodeTimeoutError as exc:
        ui.console.print()
        ui.print_error(f"OpenCode execution timed out: {exc}")
        ui.console.print()
    except OpenCodeError as exc:
        ui.console.print()
        ui.print_error(f"OpenCode error: {exc}")
        ui.console.print()
    except KeyboardInterrupt:
        ui.console.print()
        ui.print_warning("Interrupted by user.")
        ui.console.print()
    except Exception as exc:
        ui.console.print()
        ui.print_error(f"Unexpected error: {exc}")
        ui.console.print()

    return None


def _cmd_project(app: ContexerApp, args: str) -> Optional[bool]:
    """Manage target project workspace (status, list, set, new, reset)."""
    from rich.table import Table
    from contexer.project.manager import ProjectManager

    ui = app.ui
    mgr = getattr(app, "project_manager", None)
    if not mgr:
        mgr = ProjectManager()
        app.project_manager = mgr

    stripped = args.strip()
    subparts = stripped.split(None, 1)
    subcmd = subparts[0].lower() if subparts else ""
    subarg = subparts[1].strip() if len(subparts) > 1 else ""

    if not stripped or subcmd in ("status", "show"):
        active = mgr.active_project
        ui.console.print()
        ui.console.print("[ctx.brand]Active Target Project[/]")
        ui.print_rule()
        ui.console.print(f"  [ctx.accent]Name:[/]        {active.name}")
        ui.console.print(f"  [ctx.accent]Type:[/]        {active.project_type.value.upper()} ({'Scratch sandbox' if active.is_scratch else 'Existing project'})")
        ui.console.print(f"  [ctx.accent]Path:[/]        {active.path}")
        ui.console.print(f"  [ctx.accent]Files:[/]       {active.count_files()} files")
        ui.console.print(f"  [ctx.accent]Description:[/] {active.description}")
        ui.console.print()
        ui.print_dim("Use '/project list' to see all projects, or '/project set <name>' to switch.")
        ui.console.print()
        return None

    if subcmd == "list":
        projects = mgr.list_projects()
        active = mgr.active_project
        ui.console.print()
        ui.console.print("[ctx.brand]Available Projects[/]")
        ui.print_rule()
        table = Table(box=None, padding=(0, 2))
        table.add_column("", justify="center", style="bold green")
        table.add_column("Name", style="bold bright_cyan")
        table.add_column("Type", style="cyan")
        table.add_column("Files", justify="right", style="dim")
        table.add_column("Path", style="dim")

        for p in projects:
            is_cur = p.path.resolve() == active.path.resolve()
            indicator = "✓" if is_cur else ""
            table.add_row(indicator, p.name, p.project_type.value, str(p.count_files()), str(p.path))

        ui.console.print(table)
        ui.console.print()
        ui.print_dim("Switch project with: /project set <name>")
        ui.console.print()
        return None

    if subcmd == "set":
        if not subarg:
            ui.print_warning("Usage: /project set <name_or_path>")
            return None
        try:
            new_proj = mgr.set_active_project(subarg)
            ui.console.print()
            ui.print_success(f"Switched active project to [bold bright_cyan]{new_proj.name}[/] ({new_proj.project_type.value})")
            ui.console.print(f"    Path: {new_proj.path}")
            ui.console.print()
        except ValueError as exc:
            ui.console.print()
            ui.print_warning(str(exc))
            ui.console.print()
        except Exception as exc:
            ui.console.print()
            ui.print_error(f"Failed to set project: {exc}")
            ui.console.print()
        return None

    if subcmd in ("new", "create"):
        if not subarg:
            ui.print_warning("Usage: /project new <scratch_folder_name>")
            return None
        try:
            new_proj = mgr.create_scratch_project(subarg)
            ui.console.print()
            ui.print_success(f"Created new scratch project [bold bright_cyan]{new_proj.name}[/]")
            ui.console.print(f"    Path: {new_proj.path}")
            ui.console.print()
        except Exception as exc:
            ui.console.print()
            ui.print_error(f"Failed to create project: {exc}")
            ui.console.print()
        return None

    if subcmd == "reset":
        proj = mgr.reset_to_default()
        ui.console.print()
        ui.print_success(f"Reset active project to default [bold bright_cyan]{proj.name}[/]")
        ui.console.print(f"    Path: {proj.path}")
        ui.console.print()
        return None

    # If user provided a direct project name: e.g. /project website
    try:
        new_proj = mgr.set_active_project(stripped)
        ui.console.print()
        ui.print_success(f"Switched active project to [bold bright_cyan]{new_proj.name}[/] ({new_proj.project_type.value})")
        ui.console.print(f"    Path: {new_proj.path}")
        ui.console.print()
    except Exception as exc:
        ui.console.print()
        ui.print_error(f"Unknown project subcommand or directory: {exc}")
        ui.print_dim("Usage: /project [status | list | set <name> | new <name> | reset]")
        ui.console.print()

    return None


def _parse_goal_args(app: ContexerApp, args: str, usage: str) -> Optional[tuple[str, Optional[str], Project]]:
    """Parse ``<goal> [--url <url>] [--dir <path>]``; prints usage/errors and returns None on failure."""
    import re
    from contexer.project.manager import ProjectManager

    ui = app.ui
    mgr = getattr(app, "project_manager", None)
    if not mgr:
        mgr = ProjectManager()
        app.project_manager = mgr

    raw = args.strip()
    if not raw:
        ui.print_warning(f"Usage: {usage}")
        return None

    # Parse optional --url argument
    app_url: Optional[str] = getattr(app.config, "app_url", None)
    goal = raw
    url_match = re.search(r'(?:--url|-u)\s+([^\s]+)', raw)
    if url_match:
        app_url = url_match.group(1).strip()
        goal = re.sub(r'(?:--url|-u)\s+[^\s]+', '', raw).strip()

    # Parse optional --dir or --project argument
    target_proj = mgr.active_project
    dir_match = re.search(r'(?:--dir|-d|--project|-p)\s+([^\s]+)', goal)
    if dir_match:
        dir_arg = dir_match.group(1).strip()
        goal = re.sub(r'(?:--dir|-d|--project|-p)\s+[^\s]+', '', goal).strip()
        try:
            target_proj = mgr.set_active_project(dir_arg)
        except Exception as exc:
            ui.console.print()
            ui.print_error(f"Invalid target directory: {exc}")
            ui.console.print()
            return None

    if not goal:
        ui.print_warning(f"Usage: {usage}")
        return None
    return goal, app_url, target_proj


def _build_loop(app: ContexerApp, with_coding_agent: bool) -> AutonomousLoop:
    from contexer.llm.factory import create_llm_provider
    from contexer.observer.playwright import PlaywrightObserver
    from contexer.opencode.adapter import OpenCodeAdapter
    from contexer.workflow.loop import AutonomousLoop

    config = app.config
    llm_provider = None
    try:
        llm_provider = getattr(app.agent, "llm", None) or create_llm_provider(config)
    except Exception:
        pass

    adapter = None
    if with_coding_agent:
        adapter = OpenCodeAdapter(
            base_url=getattr(config, "opencode_server_url", "http://127.0.0.1:4096"),
            timeout=getattr(config, "opencode_timeout", 120.0),
            model_provider=getattr(config, "opencode_model_provider", None) or "opencode",
            model_id=getattr(config, "opencode_model_id", None) or "nemotron-3.5-lightning-free",
        )
    return AutonomousLoop(
        adapter=adapter,
        observer=PlaywrightObserver(headless=True),
        max_attempts=3,
        console=app.ui.console,
        project_manager=app.project_manager,
        llm_provider=llm_provider,
    )


def _cmd_loop(app: ContexerApp, args: str) -> Optional[bool]:
    """Execute autonomous engineering loop (Goal -> OpenCode -> Playwright -> Verifier -> Repair)."""
    import asyncio

    ui = app.ui
    parsed = _parse_goal_args(app, args, "/loop <goal> [--url <url>] [--dir <path>]")
    if parsed is None:
        return None
    goal, app_url, target_proj = parsed

    loop = _build_loop(app, with_coding_agent=True)
    try:
        asyncio.run(loop.run(goal=goal, app_url=app_url, project=target_proj))
    except KeyboardInterrupt:
        ui.console.print()
        ui.print_warning("Autonomous loop interrupted by user.")
        ui.console.print()
    except Exception as exc:
        ui.console.print()
        ui.print_error(f"Autonomous loop error: {exc}")
        ui.console.print()

    return None


def _cmd_verify(app: ContexerApp, args: str) -> Optional[bool]:
    """Verify the running application against a goal without changing any code."""
    import asyncio

    ui = app.ui
    parsed = _parse_goal_args(app, args, "/verify <goal> [--url <url>] [--dir <path>]")
    if parsed is None:
        return None
    goal, app_url, target_proj = parsed

    loop = _build_loop(app, with_coding_agent=False)
    try:
        asyncio.run(loop.verify_only(goal=goal, app_url=app_url, project=target_proj))
    except KeyboardInterrupt:
        ui.console.print()
        ui.print_warning("Verification interrupted by user.")
        ui.console.print()
    except Exception as exc:
        ui.console.print()
        ui.print_error(f"Verification error: {exc}")
        ui.console.print()

    return None


def _cmd_github(app: ContexerApp, args: str) -> Optional[bool]:
    """Verify GitHub MCP Server connection, read-only status, and discovered tools."""
    import asyncio
    from contexer.cli.ui import _can_encode
    from contexer.mcp.adapter import connect_and_discover_github_mcp
    from contexer.mcp.server import GitHubMCPServerRunner

    ui = app.ui
    config = app.config
    check_char = "✓" if _can_encode("✓") else "+"
    cross_char = "✗" if _can_encode("✗") else "x"
    bullet_char = "•" if _can_encode("•") else "-"

    ui.console.print()
    ui.console.print("[ctx.brand]GitHub MCP Status[/]")
    ui.print_rule()

    runner = GitHubMCPServerRunner(config)
    token = runner.token
    token_status = "[green]Configured[/]" if token else "[yellow]Missing (set GITHUB_PERSONAL_ACCESS_TOKEN)[/]"
    ui.console.print(f"  Token:           {token_status}")
    ui.console.print(f"  Read-only mode:  [green]{check_char} Enforced[/]")
    ui.console.print(f"  Toolsets:        {runner.toolsets}")

    target_ws = getattr(app, "target_workspace", None)
    executable = runner.resolve_executable(target_ws)
    if executable:
        ui.console.print(f"  Server Runner:   [cyan]{executable[0]}[/]")
    else:
        ui.console.print(f"  Server Runner:   [yellow]Not found (github-mcp-server or docker required)[/]")

    if not token:
        ui.console.print()
        ui.print_warning("GitHub Personal Access Token is not set. Set GITHUB_PERSONAL_ACCESS_TOKEN in .env.")
        ui.console.print()
        return None

    if not executable:
        ui.console.print()
        ui.print_warning("Neither 'github-mcp-server' executable nor 'docker' was found.")
        ui.print_dim("To use official GitHub MCP server, download the official binary or ensure Docker is running.")
        ui.console.print()
        return None

    ui.console.print()
    ui.print_info("Connecting to official GitHub MCP Server...")

    async def _check_and_close():
        result = await connect_and_discover_github_mcp(config, target_ws)
        if result.client:
            await result.client.close()
        return result

    try:
        res = asyncio.run(_check_and_close())
        if res.connected:
            ui.console.print(f"  [green]{check_char} Connected[/]")
            ui.console.print(f"  [green]{check_char} Read-only[/]")
            ui.console.print(f"  [green]{check_char} Tools discovered: {len(res.tools)}[/]")
            ui.console.print()
            ui.console.print("  [ctx.dim]Discovered Tools:[/]")
            for t in res.tools:
                desc = t.description.split("\n")[0] if t.description else "No description"
                ui.console.print(f"    - [cyan]{t.name}[/]: {desc}")
        else:
            ui.console.print(f"  [red]{cross_char} Connection failed[/]: {res.error}")
    except Exception as exc:
        ui.console.print(f"  [red]{cross_char} Unexpected error[/]: {exc}")

    ui.console.print()
    return None


# ---------------------------------------------------------------------------
# Command registry
# ---------------------------------------------------------------------------

COMMANDS: dict[str, CommandDef] = {
    "help": CommandDef(name="help", help_text="Show available commands", aliases=("h", "?")),
    "exit": CommandDef(name="exit", help_text="Exit the Contexer shell", aliases=("quit", "q")),
    "version": CommandDef(name="version", help_text="Show version information", aliases=("v",)),
    "clear": CommandDef(name="clear", help_text="Clear the terminal screen", aliases=("cls",)),
    "status": CommandDef(name="status", help_text="Show current session status"),
    "project": CommandDef(
        name="project",
        help_text="Manage target project workspace (status, list, set, new, reset)",
        aliases=("p", "workspace"),
    ),
    "opencode": CommandDef(
        name="opencode",
        help_text="Interact with OpenCode execution engine",
        aliases=("oc",),
    ),
    "loop": CommandDef(
        name="loop",
        help_text="Run autonomous loop (OpenCode + Playwright + Verifier + Repair)",
        aliases=("auto", "build"),
    ),
    "verify": CommandDef(
        name="verify",
        help_text="Verify the running app against a goal with executable browser checks (no code changes)",
        aliases=("check",),
    ),
    "github": CommandDef(
        name="github",
        help_text="Verify GitHub MCP Server connection, read-only status, and tools",
        aliases=("gh", "mcp"),
    ),
}

# Canonical name → handler function
_HANDLERS: dict[str, Callable[..., Optional[bool]]] = {
    "help": _cmd_help,
    "exit": _cmd_exit,
    "version": _cmd_version,
    "clear": _cmd_clear,
    "status": _cmd_status,
    "project": _cmd_project,
    "opencode": _cmd_opencode,
    "loop": _cmd_loop,
    "verify": _cmd_verify,
    "github": _cmd_github,
}

# Build alias → canonical lookup
_ALIAS_MAP: dict[str, str] = {}
for _name, _cmd_def in COMMANDS.items():
    _ALIAS_MAP[_name] = _name
    for _alias in _cmd_def.aliases:
        _ALIAS_MAP[_alias] = _name


# ---------------------------------------------------------------------------
# Command router
# ---------------------------------------------------------------------------


class CommandRouter:
    """Resolves and dispatches slash commands.

    Resolution order:
    1. Exact match (name or alias)
    2. Unique-prefix expansion
    3. Unknown → error with suggestions
    """

    def dispatch(self, app: ContexerApp, raw_input: str) -> Optional[bool]:
        """Parse and execute a slash command.

        Returns:
            ``None`` — continue the REPL.
            ``False`` — exit the REPL.
        """
        stripped = raw_input.strip()
        while stripped.startswith(("❯", ">", "$")):
            stripped = stripped[1:].strip()

        if not stripped.startswith("/"):
            return None

        parts = stripped[1:].split(None, 1)
        if not parts:
            return None

        cmd_word = parts[0].lower()
        cmd_args = parts[1].strip() if len(parts) > 1 else ""

        # 1. Exact match (name or alias)
        canonical = _ALIAS_MAP.get(cmd_word)
        if canonical is not None:
            handler = _HANDLERS.get(canonical)
            if handler is not None:
                return handler(app, cmd_args)

        # 2. Unique-prefix expansion
        matches = [name for name in COMMANDS if name.startswith(cmd_word)]
        if len(matches) == 1:
            handler = _HANDLERS.get(matches[0])
            if handler is not None:
                return handler(app, cmd_args)

        # 3. Unknown command
        if len(matches) > 1:
            app.ui.print_warning(
                f"Ambiguous command: /{cmd_word}\n"
                f"  Did you mean: {', '.join('/' + m for m in sorted(matches))}?"
            )
        else:
            app.ui.print_error(f"Unknown command: /{cmd_word}")
            app.ui.print_dim("Type /help for available commands.")

        return None


def looks_like_slash_command(text: str) -> bool:
    """Determine if input looks like a slash command vs a file path.

    ``/help`` → True, ``/Users/x/file.md`` → False.
    This keeps Unix-style absolute paths from being mistaken for commands.
    """
    stripped = text.strip() if text else ""
    while stripped.startswith(("❯", ">", "$")):
        stripped = stripped[1:].strip()
    if not stripped or not stripped.startswith("/"):
        return False
    first_word = stripped.split()[0]
    # A command's first word has no further `/` after the leading one
    return "/" not in first_word[1:]
