"""Drive OpenAI Codex headlessly (``codex exec --json``).

* The prompt goes in on stdin (``-``), as the official TypeScript SDK sends it.
* The JSONL stream is parsed as it arrives. ``thread.started`` carries the
  thread id used to resume the conversation for a repair turn
  (``codex exec ... resume <id> -``); ``item.*`` events become progress lines
  and the list of edited files; ``turn.completed`` / ``turn.failed`` decide
  the outcome. Top-level ``error`` events include retries ("Reconnecting...
  2/5"), so they are kept as context, never treated as the end of a turn.
* Sandbox: ``workspace-write`` with network access (adding a package needs
  it) and approvals ``never``, because a non-interactive run cannot answer a
  prompt. Codex has no per-path deny rule, so protecting ``.contexer/`` rests
  on Contexer's own contract hashing and snapshot diff.
* Codex reports tokens, not cost, so a spending budget cannot be enforced for
  it; the repair-round and wall-clock limits still bound a run.
* Contexer runs the user's own ``codex`` with whatever login it has
  (``codex login`` or ``CODEX_API_KEY``). It never handles credentials.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional

from contexer.agents.base import AgentTurn, CodingAgentAdapter, ProgressFn
from contexer.agents.claude_code import agent_env
from contexer.procutil import ProcessTree, spawn_tree

_CHANGE_VERBS = {"add": "Created", "delete": "Deleted", "update": "Edited"}


class CodexAgent(CodingAgentAdapter):
    name = "codex"

    def __init__(
        self,
        executable: str = "codex",
        model: Optional[str] = None,
        network: bool = True,
        extra_args: Optional[list[str]] = None,
    ) -> None:
        self.executable = shutil.which(executable) or executable
        self.model = model
        self.network = network
        self.extra_args = extra_args or []

    def describe(self) -> str:
        return f"codex{f' ({self.model})' if self.model else ''}"

    def argv(self, workdir: Path, session_id: Optional[str]) -> list[str]:
        args = [
            self.executable,
            "exec",
            "--json",
            "--skip-git-repo-check",
            "--sandbox",
            "workspace-write",
            "--config",
            'approval_policy="never"',
            "--config",
            f"sandbox_workspace_write.network_access={'true' if self.network else 'false'}",
            "--cd",
            str(workdir),
        ]
        if self.model:
            args += ["--model", self.model]
        args += self.extra_args
        if session_id:
            args += ["resume", session_id]
        return args + ["-"]

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
        # budget_usd is accepted for the interface; Codex reports no cost to enforce it with.
        try:
            return await asyncio.to_thread(self._run_blocking, Path(workdir), prompt, session_id, timeout, on_progress)
        except asyncio.CancelledError:
            self.stop()  # Ctrl+C: otherwise the worker thread waits for the agent to finish its turn
            raise

    # -- blocking implementation (runs in a worker thread) ------------------------

    def _run_blocking(
        self,
        workdir: Path,
        prompt: str,
        session_id: Optional[str],
        timeout: float,
        on_progress: Optional[ProgressFn],
    ) -> AgentTurn:
        started = time.monotonic()
        try:
            tree = spawn_tree(self.argv(workdir, session_id), workdir, agent_env(), stdin=subprocess.PIPE)
        except OSError as exc:
            return AgentTurn(status="failed", session_id=session_id, error=f"could not start codex: {exc}")

        state = _CodexStream(workdir, session_id)
        reader = threading.Thread(target=_consume, args=(tree, state, on_progress), daemon=True)
        reader.start()
        try:
            assert tree.proc.stdin is not None
            tree.proc.stdin.write(prompt.encode("utf-8"))
            tree.proc.stdin.close()
        except OSError:
            pass

        self._track(tree)
        try:
            reader.join(timeout)
            timed_out = reader.is_alive()
            if timed_out:
                tree.kill()
                reader.join(5)
            else:
                tree.kill(grace=5)  # reap anything the agent left running
        finally:
            self._untrack(tree)
        return state.to_turn(timed_out=timed_out, duration=time.monotonic() - started, returncode=tree.poll())


class _CodexStream:
    def __init__(self, workdir: Path, session_id: Optional[str]) -> None:
        self.workdir = workdir
        self.session_id = session_id
        self.completed = False
        self.failure: Optional[str] = None
        self.errors: list[str] = []
        self.tool_calls = 0
        self.files: list[str] = []
        self.last_text = ""
        self.noise: list[str] = []

    def handle(self, event: dict[str, Any], on_progress: Optional[ProgressFn]) -> None:
        kind = event.get("type")
        if kind == "thread.started":
            self.session_id = event.get("thread_id") or self.session_id
        elif kind in ("item.started", "item.completed"):
            self._item(kind, event.get("item") or {}, on_progress)
        elif kind == "turn.completed":
            self.completed = True
        elif kind == "turn.failed":
            self.failure = str((event.get("error") or {}).get("message") or "the turn failed")
        elif kind == "error":
            self.errors.append(str(event.get("message") or ""))

    def _item(self, kind: str, item: dict[str, Any], on_progress: Optional[ProgressFn]) -> None:
        item_type = item.get("type")
        progress: Optional[str] = None
        if item_type == "command_execution" and kind == "item.started":
            self.tool_calls += 1
            progress = f"$ {str(item.get('command') or '')[:100]}"
        elif item_type == "file_change" and kind == "item.completed":
            self.tool_calls += 1
            for change in item.get("changes") or []:
                path = self._relative(str(change.get("path") or ""))
                if path:
                    self.files.append(path)
                    if on_progress:
                        on_progress(f"{_CHANGE_VERBS.get(str(change.get('kind')), 'Changed')} {path}")
        elif item_type == "mcp_tool_call" and kind == "item.started":
            self.tool_calls += 1
            progress = f"{item.get('server')}.{item.get('tool')}"
        elif item_type == "web_search" and kind == "item.started":
            progress = f"search {str(item.get('query') or '')[:100]}"
        elif item_type == "agent_message" and kind == "item.completed" and item.get("text"):
            self.last_text = str(item["text"])
        if progress and on_progress:
            on_progress(progress)

    def _relative(self, path: str) -> str:
        try:
            return Path(path).resolve().relative_to(self.workdir.resolve()).as_posix()
        except (ValueError, OSError):
            return path

    def to_turn(self, *, timed_out: bool, duration: float, returncode: Optional[int]) -> AgentTurn:
        base: dict[str, Any] = dict(
            session_id=self.session_id,
            summary=self.last_text[:4000],
            duration_seconds=duration,
            tool_calls=self.tool_calls,
            files_touched=sorted(dict.fromkeys(self.files)),
        )
        if timed_out:
            return AgentTurn(status="timeout", error="the agent turn timed out", **base)
        if self.failure is not None:
            return AgentTurn(status="failed", error=self.failure[:500], **base)
        if self.completed:
            return AgentTurn(status="completed", **base)
        detail = (self.errors or self.noise or [f"exit code {returncode}"])[-1]
        return AgentTurn(status="failed", error=f"no result from codex ({detail[:300]})", **base)


def _consume(tree: ProcessTree, state: _CodexStream, on_progress: Optional[ProgressFn]) -> None:
    stdout = tree.proc.stdout
    assert stdout is not None
    for raw in iter(stdout.readline, b""):
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            state.noise.append(line[:200])  # stderr is merged into stdout: warnings and logs
            continue
        if isinstance(event, dict):
            state.handle(event, on_progress)
