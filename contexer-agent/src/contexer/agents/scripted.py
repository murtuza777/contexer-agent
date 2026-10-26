"""A deterministic stand-in for a coding agent, for hermetic tests and demos.

Each turn applies a queued set of file writes (``None`` deletes the file), so
the full controller — snapshots, verification, repair, revert — can be
exercised without a network or a model.

``contexer run --agent scripted --model turns.json`` reads the turns from a
JSON list of ``{"path": "content" | null}`` objects, to try a setup (an
Actions workflow, a pull request hand-off) end to end without a model.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from contexer.agents.base import AgentTurn, CodingAgentAdapter, ProgressFn

FileWrites = dict[str, Optional[str]]


class ScriptedAgent(CodingAgentAdapter):
    name = "scripted"

    def __init__(self, turns: list[FileWrites], fail_after: Optional[int] = None) -> None:
        self.turns = list(turns)
        self.prompts: list[str] = []
        self.sessions: list[Optional[str]] = []
        self._fail_after = fail_after
        self._session_counter = 0

    @classmethod
    def from_file(cls, path: str | Path) -> "ScriptedAgent":
        try:
            turns = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"the scripted agent needs --model turns.json, a JSON list of file writes: {exc}") from exc
        if not isinstance(turns, list) or not all(isinstance(t, dict) for t in turns):
            raise ValueError("the scripted agent's turns file must be a JSON list of {path: content} objects")
        return cls(turns)

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
        started = time.monotonic()
        self.prompts.append(prompt)
        self.sessions.append(session_id)
        if session_id is None:
            self._session_counter += 1
        sid = session_id or f"scripted-{self._session_counter}"
        if self._fail_after is not None and len(self.prompts) > self._fail_after:
            return AgentTurn(status="failed", session_id=sid, error="scripted failure")
        if not self.turns:
            return AgentTurn(status="completed", session_id=sid, summary="nothing left to do")

        writes = self.turns.pop(0)
        for rel, content in writes.items():
            path = Path(workdir) / rel
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8", newline="")  # byte-exact, no CRLF translation
            if on_progress:
                on_progress(f"{'Deleting' if content is None else 'Writing'} {rel}")
        return AgentTurn(
            status="completed",
            session_id=sid,
            summary=f"wrote {len(writes)} file(s)",
            duration_seconds=time.monotonic() - started,
            tool_calls=len(writes),
            files_touched=sorted(writes),
            cost_usd=0.0,
        )
