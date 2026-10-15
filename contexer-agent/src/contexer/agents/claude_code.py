"""Drive Claude Code headlessly (``claude -p --output-format stream-json``).

* The prompt goes in on stdin (no command-line length or quoting limits).
* The NDJSON stream is parsed as it arrives: tool calls become progress lines,
  and the final ``result`` line supplies status, cost and the session id used
  to resume the same conversation for a repair turn.
* Permissions: edits are auto-accepted, a short list of shell commands is
  allowed, and edits under ``.contexer/`` (where the approved contract lives)
  are denied. That deny rule is the first of three tamper layers; Contexer's
  own file hashing and snapshot diff are the ones it relies on.
* Contexer runs the user's own, unmodified ``claude`` binary with whatever
  login it already has. It never reads or handles credentials.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional

from contexer.agents.base import AgentTurn, CodingAgentAdapter, ProgressFn
from contexer.procutil import ProcessTree, spawn_tree

DEFAULT_ALLOWED_TOOLS = (
    "Read",
    "Edit",
    "MultiEdit",
    "Write",
    "Glob",
    "Grep",
    "LS",
    "TodoWrite",
    "Bash(npm install:*)",
    "Bash(npm i:*)",
    "Bash(pnpm add:*)",
    "Bash(pnpm install:*)",
    "Bash(yarn add:*)",
    "Bash(npx tsc:*)",
    "Bash(npm run build:*)",
    "Bash(npm run lint:*)",
    "Bash(ls:*)",
    "Bash(git status:*)",
    "Bash(git diff:*)",
)
DENIED_TOOLS = (
    "Edit(.contexer/**)",
    "MultiEdit(.contexer/**)",
    "Write(.contexer/**)",
    "Bash(git commit:*)",
    "Bash(git push:*)",
    "Bash(git reset:*)",
    "Bash(git checkout:*)",
    "Bash(rm -rf:*)",
)

# Variables a hosting Claude Code session sets for its own plumbing. A coding
# agent Contexer starts is a separate session and must not inherit them.
_PARENT_SESSION_PREFIXES = ("CLAUDE_CODE_", "CLAUDE_AGENT_SDK_")
_PARENT_SESSION_VARS = {"CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT", "CLAUDE_PREVIEW_CLASSIFIER_FLOOR"}

_EDIT_TOOLS = {"Edit", "MultiEdit", "Write", "NotebookEdit"}


class ClaudeCodeAgent(CodingAgentAdapter):
    name = "claude-code"

    def __init__(
        self,
        executable: str = "claude",
        model: Optional[str] = None,
        allowed_tools: tuple[str, ...] = DEFAULT_ALLOWED_TOOLS,
        denied_tools: tuple[str, ...] = DENIED_TOOLS,
        extra_args: Optional[list[str]] = None,
    ) -> None:
        self.executable = shutil.which(executable) or executable
        self.model = model
        self.allowed_tools = allowed_tools
        self.denied_tools = denied_tools
        self.extra_args = extra_args or []

    def describe(self) -> str:
        return f"claude-code{f' ({self.model})' if self.model else ''}"

    def argv(self, session_id: Optional[str], budget_usd: Optional[float]) -> list[str]:
        args = [
            self.executable,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            "acceptEdits",
            "--allowedTools",
            ",".join(self.allowed_tools),
            "--disallowedTools",
            ",".join(self.denied_tools),
        ]
        if self.model:
            args += ["--model", self.model]
        if session_id:
            args += ["--resume", session_id]
        if budget_usd is not None:
            args += ["--max-budget-usd", f"{budget_usd:.2f}"]
        return args + self.extra_args

    async def run_turn(
        self,
        workdir: Path,
        prompt: str,
        *,
        session_id: Optional[str] = None,
        timeout: float = 900.0,
        budget_usd: Optional[float] = None,
        on_progress: Optional[ProgressFn] = None,
    ) -> AgentTurn:
        return await asyncio.to_thread(
            self._run_blocking, Path(workdir), prompt, session_id, timeout, budget_usd, on_progress
        )

    # -- blocking implementation (runs in a worker thread) ------------------------

    def _run_blocking(
        self,
        workdir: Path,
        prompt: str,
        session_id: Optional[str],
        timeout: float,
        budget_usd: Optional[float],
        on_progress: Optional[ProgressFn],
    ) -> AgentTurn:
        started = time.monotonic()
        try:
            tree = spawn_tree(self.argv(session_id, budget_usd), workdir, agent_env(), stdin=subprocess.PIPE)
        except OSError as exc:
            return AgentTurn(status="failed", session_id=session_id, error=f"could not start claude: {exc}")

        state = _StreamState(session_id=session_id)
        reader = threading.Thread(target=_consume, args=(tree, state, on_progress), daemon=True)
        reader.start()
        try:
            assert tree.proc.stdin is not None
            tree.proc.stdin.write(prompt.encode("utf-8"))
            tree.proc.stdin.close()
        except OSError:
            pass

        reader.join(timeout)
        timed_out = reader.is_alive()
        if timed_out:
            tree.kill()
            reader.join(5)
        else:
            tree.kill(grace=5)  # reap anything the agent left running
        return state.to_turn(timed_out=timed_out, duration=time.monotonic() - started, returncode=tree.poll())


class _StreamState:
    def __init__(self, session_id: Optional[str]) -> None:
        self.session_id = session_id
        self.result: Optional[dict[str, Any]] = None
        self.tool_calls = 0
        self.files: list[str] = []
        self.last_text = ""
        self.noise: list[str] = []

    def to_turn(self, *, timed_out: bool, duration: float, returncode: Optional[int]) -> AgentTurn:
        r = self.result or {}
        denials = [_denial_text(d) for d in r.get("permission_denials") or []]
        base: dict[str, Any] = dict(
            session_id=r.get("session_id") or self.session_id,
            summary=str(r.get("result") or self.last_text)[:4000],
            cost_usd=_float(r.get("total_cost_usd")),
            duration_seconds=duration,
            num_turns=r.get("num_turns"),
            tool_calls=self.tool_calls,
            files_touched=sorted(dict.fromkeys(self.files)),
            permission_denials=denials,
        )
        if timed_out:
            return AgentTurn(status="timeout", error="the agent turn timed out", **base)
        if not r:
            detail = "; ".join(self.noise[-5:]) or f"exit code {returncode}"
            return AgentTurn(status="failed", error=f"no result from claude ({detail})", **base)
        subtype = str(r.get("subtype") or "")
        if "budget" in subtype:
            return AgentTurn(status="budget_exceeded", error=subtype, **base)
        if r.get("is_error") or subtype.startswith("error"):
            reason = r.get("terminal_reason") or subtype or "error"
            return AgentTurn(status="failed", error=f"{reason}: {str(r.get('result') or '')[:300]}", **base)
        return AgentTurn(status="completed", **base)


def _consume(tree: ProcessTree, state: _StreamState, on_progress: Optional[ProgressFn]) -> None:
    stdout = tree.proc.stdout
    assert stdout is not None
    for raw in iter(stdout.readline, b""):
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            state.noise.append(line[:200])
            continue
        _handle_event(event, state, on_progress)


def _handle_event(event: dict[str, Any], state: _StreamState, on_progress: Optional[ProgressFn]) -> None:
    kind = event.get("type")
    if kind == "system" and event.get("subtype") == "init":
        state.session_id = event.get("session_id") or state.session_id
    elif kind == "assistant":
        for block in (event.get("message") or {}).get("content") or []:
            if block.get("type") == "tool_use":
                state.tool_calls += 1
                name = str(block.get("name") or "tool")
                params = block.get("input") or {}
                target = params.get("file_path") or params.get("path") or params.get("command") or params.get("pattern")
                if name in _EDIT_TOOLS and params.get("file_path"):
                    state.files.append(str(params["file_path"]))
                if on_progress:
                    on_progress(f"{name} {str(target)[:100]}" if target else name)
            elif block.get("type") == "text" and block.get("text"):
                state.last_text = str(block["text"])
    elif kind == "result":
        state.result = event
        state.session_id = event.get("session_id") or state.session_id


def agent_env() -> dict[str, str]:
    """The environment for a spawned agent: the user's, minus a parent agent session's plumbing."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in _PARENT_SESSION_VARS and not k.startswith(_PARENT_SESSION_PREFIXES)
    }
    env.setdefault("CI", "1")
    return env


def _denial_text(denial: Any) -> str:
    if isinstance(denial, dict):
        tool = denial.get("tool_name") or denial.get("tool") or "tool"
        params = denial.get("tool_input") or {}
        target = params.get("file_path") or params.get("command") or ""
        return f"{tool} {target}".strip()
    return str(denial)


def _float(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
