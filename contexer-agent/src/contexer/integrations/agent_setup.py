"""Setting a coding agent up to work under Contexer (``contexer init --agent NAME``).

Three things, each in the file that agent itself reads for the project:

* the MCP server (``contexer mcp``), so the agent can read the checks and have them replayed;
* the stop hook (``contexer hook stop``), so it cannot say "done" while one fails, where the agent has a
  hook that can refuse a stop;
* instructions: when to call Contexer, and that it may not edit ``.contexer/`` or approve a check.

What a person already has in those files is kept, each thing is added once, and a file that cannot be read
is left alone. Nothing here starts the agent or talks to it.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from contexer.evidence.rundir import write_whole
from contexer.integrations.stop_hook import HOOK_COMMAND, HOOK_TIMEOUT_SECONDS

AGENTS = ("claude-code", "codex", "opencode")
SERVER_NAME = "contexer"
SERVER_COMMAND, SERVER_ARGS = "contexer", ["mcp"]

# Where each agent reads project hooks from, relative to the project.
HOOK_FILES = {
    "claude-code": Path(".claude") / "settings.json",
    "codex": Path(".codex") / "hooks.json",
}

NO_STOP_HOOK = {
    "opencode": (
        "OpenCode has no hook that can refuse a stop, so nothing holds it to the checks. "
        "It is asked, in AGENTS.md, to call contexer_verify before it finishes."
    ),
}

AFTER_HOOK = {
    "codex": "Codex reads a project's .codex/ folder only once you trust the project, and runs a hook only after you accept it with /hooks.",
}

# The start of the block Contexer adds to a file of instructions a person may also write in.
INSTRUCTIONS_MARK = "<!-- contexer: how to work with the acceptance checks -->"

_RULES = """\
This project uses Contexer. A person approved acceptance checks for it; Contexer replays them in a real
browser, and they decide whether work is done. Your own judgement does not.

- Before you start a task, call the `contexer_checks` tool to read what will be checked.
- When you think you are finished, call `contexer_verify`. Fix what it reports and call it again until
  every check passes. Report its result to the person, in its words.
- Never edit anything under `.contexer/` and never weaken, skip or delete a check. You cannot approve a
  contract: a person does, with `contexer contract approve ID` in a terminal.
- If a check looks wrong or cannot pass, stop and say so to the person. Do not work around it.
"""

SKILL = f"""\
---
name: contexer
description: Use when building, fixing or finishing anything in this project. Contexer holds the approved acceptance checks and replays them in a real browser; call contexer_checks before starting and contexer_verify before saying the work is done.
---

# Working under Contexer

{_RULES}"""

AGENTS_MD_BLOCK = f"{INSTRUCTIONS_MARK}\n## Contexer\n\n{_RULES}"

Status = Literal["written", "present", "unreadable", "unsupported", "manual"]


@dataclass(frozen=True)
class Done:
    """One thing ``init --agent`` did or could not do. ``what`` is "server", "hook" or "instructions"."""

    what: str
    status: Status
    path: Path | None = None
    note: str = ""


def set_up(project_dir: str | Path, agent: str) -> list[Done]:
    """Register the server, write the hook and the instructions for ``agent``, in that order."""
    project = Path(project_dir).resolve()
    return [install_server(project, agent), install_stop_hook(project, agent), install_instructions(project, agent)]


# -- the MCP server -------------------------------------------------------------------------------------


def install_server(project_dir: str | Path, agent: str) -> Done:
    project = Path(project_dir).resolve()
    if agent == "claude-code":
        return _server_json(project / ".mcp.json")
    if agent == "codex":
        return _server_toml(project / ".codex" / "config.toml")
    # OpenCode's config is JSON with comments, and where servers sit in it changed between versions.
    return Done("server", "manual", note="Add the server with OpenCode's own command: `opencode mcp add` (a local server, command `contexer mcp`).")


def _server_json(path: Path) -> Done:
    data = _read_json(path)
    if data is None:
        return Done("server", "unreadable", path)
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        return Done("server", "unreadable", path)
    if SERVER_NAME in servers:
        return Done("server", "present", path)
    servers[SERVER_NAME] = {"command": SERVER_COMMAND, "args": list(SERVER_ARGS)}
    write_whole(path, json.dumps(data, indent=2) + "\n")
    return Done("server", "written", path, "Claude Code asks you once to allow a server a project brings.")


def _server_toml(path: Path) -> Done:
    """Append one table. The file is a person's: it is parsed to check, and never rewritten."""
    text = ""
    if path.exists():
        try:
            text = path.read_text(encoding="utf-8")
            parsed = tomllib.loads(text)
        except (OSError, ValueError):
            return Done("server", "unreadable", path)
        servers = parsed.get("mcp_servers", {})
        if not isinstance(servers, dict):
            return Done("server", "unreadable", path)
        if SERVER_NAME in servers:
            return Done("server", "present", path)
    table = f'[mcp_servers.{SERVER_NAME}]\ncommand = "{SERVER_COMMAND}"\nargs = {json.dumps(SERVER_ARGS)}\n'
    gap = "" if not text else ("\n" if text.endswith("\n") else "\n\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    write_whole(path, text + gap + table)
    return Done("server", "written", path)


# -- the stop hook --------------------------------------------------------------------------------------


def install_stop_hook(project_dir: str | Path, agent: str) -> Done:
    """Add ``contexer hook stop`` to the agent's Stop hooks for this project, once.

    Claude Code and Codex read the same shape: ``{"hooks": {"Stop": [{"hooks": [{"type": "command", ...}]}]}}``.
    """
    if agent in NO_STOP_HOOK:
        return Done("hook", "unsupported", note=NO_STOP_HOOK[agent])
    path = Path(project_dir).resolve() / HOOK_FILES[agent]
    data = _read_json(path)
    if data is None:
        return Done("hook", "unreadable", path)
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        return Done("hook", "unreadable", path)
    stop = hooks.setdefault("Stop", [])
    if not isinstance(stop, list):
        return Done("hook", "unreadable", path)
    if _has_ours(stop):
        return Done("hook", "present", path, AFTER_HOOK.get(agent, ""))
    stop.append({"hooks": [{"type": "command", "command": HOOK_COMMAND, "timeout": HOOK_TIMEOUT_SECONDS}]})
    path.parent.mkdir(parents=True, exist_ok=True)
    write_whole(path, json.dumps(data, indent=2) + "\n")
    return Done("hook", "written", path, AFTER_HOOK.get(agent, ""))


def _has_ours(stop: list[object]) -> bool:
    for group in stop:
        inner = group.get("hooks") if isinstance(group, dict) else None
        for hook in inner if isinstance(inner, list) else []:
            if isinstance(hook, dict) and str(hook.get("command", "")).strip().startswith(HOOK_COMMAND):
                return True
    return False


# -- the instructions -----------------------------------------------------------------------------------


def install_instructions(project_dir: str | Path, agent: str) -> Done:
    project = Path(project_dir).resolve()
    if agent == "claude-code":
        path = project / ".claude" / "skills" / "contexer" / "SKILL.md"
        if path.exists():
            return Done("instructions", "present", path)  # a skill is one file; a person's own is not touched
        path.parent.mkdir(parents=True, exist_ok=True)
        write_whole(path, SKILL)
        return Done("instructions", "written", path)
    path = project / "AGENTS.md"  # Codex and OpenCode both read it
    try:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
    except (OSError, ValueError):
        return Done("instructions", "unreadable", path)
    if INSTRUCTIONS_MARK in text:
        return Done("instructions", "present", path)
    gap = "" if not text else ("\n" if text.endswith("\n") else "\n\n")
    write_whole(path, text + gap + AGENTS_MD_BLOCK)
    return Done("instructions", "written", path)


def _read_json(path: Path) -> dict[str, object] | None:
    """The file as an object; empty when it does not exist; None when it is not one Contexer can read."""
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None
