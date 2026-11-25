"""Writing the stop hook into a coding agent's own project settings (``contexer init --agent``).

Claude Code and Codex read the same shape: ``{"hooks": {"Stop": [{"hooks": [{"type": "command", ...}]}]}}``.
OpenCode has no hook that can refuse a stop, so nothing is written for it and the caller says so.
A person's own settings and hooks are kept; a file that cannot be read is left alone.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from contexer.evidence.rundir import write_whole
from contexer.integrations.stop_hook import HOOK_COMMAND, HOOK_TIMEOUT_SECONDS

AGENTS = ("claude-code", "codex", "opencode")

# Where each agent reads project hooks from, relative to the project.
HOOK_FILES = {
    "claude-code": Path(".claude") / "settings.json",
    "codex": Path(".codex") / "hooks.json",
}

NO_STOP_HOOK = {
    "opencode": (
        "OpenCode has no hook that can refuse a stop, so nothing holds it to the checks. "
        "Add the MCP server instead (`contexer mcp`) and ask it to call contexer_verify before it finishes."
    ),
}

AFTER = {
    "codex": "Codex runs a project hook only after you trust it: open Codex in this folder and run /hooks.",
}


@dataclass(frozen=True)
class HookInstall:
    status: Literal["written", "present", "unreadable", "unsupported"]
    path: Path | None = None
    note: str = ""


def install_stop_hook(project_dir: str | Path, agent: str) -> HookInstall:
    """Add ``contexer hook stop`` to the agent's Stop hooks for this project, once."""
    if agent in NO_STOP_HOOK:
        return HookInstall("unsupported", note=NO_STOP_HOOK[agent])
    path = Path(project_dir).resolve() / HOOK_FILES[agent]
    data: dict[str, object] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return HookInstall("unreadable", path)
        if not isinstance(loaded, dict):
            return HookInstall("unreadable", path)
        data = loaded
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        return HookInstall("unreadable", path)
    stop = hooks.setdefault("Stop", [])
    if not isinstance(stop, list):
        return HookInstall("unreadable", path)
    if _has_ours(stop):
        return HookInstall("present", path, AFTER.get(agent, ""))
    stop.append({"hooks": [{"type": "command", "command": HOOK_COMMAND, "timeout": HOOK_TIMEOUT_SECONDS}]})
    path.parent.mkdir(parents=True, exist_ok=True)
    write_whole(path, json.dumps(data, indent=2) + "\n")
    return HookInstall("written", path, AFTER.get(agent, ""))


def _has_ours(stop: list[object]) -> bool:
    for group in stop:
        inner = group.get("hooks") if isinstance(group, dict) else None
        for hook in inner if isinstance(inner, list) else []:
            if isinstance(hook, dict) and str(hook.get("command", "")).strip().startswith(HOOK_COMMAND):
                return True
    return False
