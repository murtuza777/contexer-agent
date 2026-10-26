"""The interface every coding agent is driven through.

Contexer rents the coding agent: it hands it a prompt and a working
directory, and gets back what the agent *says* happened. That self-report is
recorded but never trusted as a pass — the verdict comes from Contexer's own
checks against the running app, and the diff from Contexer's own snapshots.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Literal, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from contexer.procutil import ProcessTree

TurnStatus = Literal["completed", "failed", "timeout", "budget_exceeded", "cancelled"]

# Progress callback: short human-readable lines ("Editing src/App.tsx").
ProgressFn = Callable[[str], None]


class AgentTurn(BaseModel):
    """What one agent turn reported. Informational; never a verdict."""

    status: TurnStatus
    session_id: Optional[str] = None
    summary: str = ""
    error: Optional[str] = None
    cost_usd: Optional[float] = None
    duration_seconds: float = 0.0
    num_turns: Optional[int] = None
    tool_calls: int = 0
    files_touched: list[str] = Field(default_factory=list)
    permission_denials: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "completed"


class CodingAgentAdapter(ABC):
    """Runs one turn of a coding agent in a project directory."""

    name: str = "agent"
    _in_flight: "Optional[set[ProcessTree]]" = None

    @abstractmethod
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
        """Run ``prompt``; continue ``session_id`` if given, else start fresh."""

    def describe(self) -> str:
        return self.name

    def close(self) -> None:
        """Release anything the adapter started (servers, sessions)."""
        self.stop()

    def stop(self) -> None:
        """Kill any turn still running, so the agent cannot keep editing files after Contexer stops."""
        for tree in list(self._in_flight or ()):
            tree.kill(grace=2)

    def _track(self, tree: "ProcessTree") -> None:
        if self._in_flight is None:
            self._in_flight = set()
        self._in_flight.add(tree)

    def _untrack(self, tree: "ProcessTree") -> None:
        if self._in_flight is not None:
            self._in_flight.discard(tree)
