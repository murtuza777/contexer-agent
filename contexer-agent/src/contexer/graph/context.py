"""What a run needs that cannot be written to a checkpoint.

The browser, the dev server, the coding agent, the snapshot repository and
the models are live objects. They belong to the process, so a resumed run
builds them again; the state (``state.py``) is what survives.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from contexer.agents.base import CodingAgentAdapter
from contexer.appserver import RunningApp
from contexer.checkpoint import ShadowRepo
from contexer.contract import Contract, ContractStore
from contexer.controller.models import RunOutcome, RunSettings
from contexer.controller.shared import ContractGuard
from contexer.crew.budget import Budget
from contexer.evidence.rundir import RunDir
from contexer.gate.models import RunResult
from contexer.intent.store import IntentStore
from contexer.verification.runner import CheckRunner
from contexer.workflow.inspector import RepositoryContext

EventFn = Callable[[str, str], None]
# A question for the person: an approval, or what to do next. Returns their answer.
AskFn = Callable[[dict[str, Any]], dict[str, Any]]
_RESULT_FILE = "run-result.json"
# Written when a run is stopped in order: the snapshot of the work that was unfinished at that moment.
# A resume reads it once and removes it, so a later hard kill is never mistaken for an orderly stop.
STOPPED_FILE = "stopped.ref"


@dataclass
class RunContext:
    project: Path
    agent: CodingAgentAdapter
    settings: RunSettings
    run: RunDir
    shadow: ShadowRepo
    store: ContractStore
    intents: IntentStore
    runner: CheckRunner
    on_event: EventFn
    repo: RepositoryContext | None = None
    url: str | None = None
    model: BaseChatModel | None = None
    budget: Budget | None = None
    can_ask: bool = False
    corrections: Callable[[], str | None] | None = None
    pending_correction: str | None = None
    guard: ContractGuard | None = None
    contract: Contract | None = None
    others: list[Contract] = field(default_factory=list)
    stack: ExitStack = field(default_factory=ExitStack)
    app: RunningApp | None = None
    outcome: RunOutcome | None = None
    # The state as the last finished node left it; what a stopped run is reported from.
    mirror: dict[str, Any] = field(default_factory=dict)
    started: float = field(default_factory=time.monotonic)
    base_elapsed: float = 0.0
    _results: dict[int, RunResult] = field(default_factory=dict)

    def event(self, kind: str, message: str) -> None:
        self.on_event(kind, message)

    def elapsed(self) -> float:
        return self.base_elapsed + (time.monotonic() - self.started)

    # -- results: kept on disk too, so a resumed run can still write its repair prompt -----

    def attempt_dir(self, n: int) -> RunDir:
        path = self.run.path / f"attempt-{n}"
        path.mkdir(parents=True, exist_ok=True)
        return RunDir(run_id=f"{self.run.run_id}/a{n}", path=path)

    def save_result(self, n: int, result: RunResult) -> None:
        self._results[n] = result
        (self.attempt_dir(n).path / _RESULT_FILE).write_text(result.model_dump_json(), encoding="utf-8")

    def result(self, n: int | None) -> RunResult | None:
        if n is None:
            return None
        if n not in self._results:
            path = self.run.path / f"attempt-{n}" / _RESULT_FILE
            if not path.is_file():
                return None
            self._results[n] = RunResult.model_validate_json(path.read_text(encoding="utf-8"))
        return self._results[n]

    # -- corrections -----------------------------------------------------------------------

    def take_correction(self) -> str:
        """A correction the person gave since the last time this was asked, or ''.

        Without a model nothing can redraft the checks, so the correction is reported and dropped
        rather than half-applied.
        """
        text = (self.pending_correction or "").strip()
        self.pending_correction = None
        if not text and self.corrections is not None:
            text = (self.corrections() or "").strip()
        if text and self.model is None:
            self.event(
                "strategy",
                "A correction was given, but no model is configured to redraft the checks, so it was not applied. "
                "Run `contexer setup`, or edit the contract and approve it.",
            )
            return ""
        return text

    # -- what defines done -------------------------------------------------------------------

    def recapture_guard(self) -> dict[str, str]:
        """Accept the files that define done as they are now (Contexer just wrote them); returns their digests."""
        self.guard = ContractGuard(self.project)
        return guard_digest(self.guard)

    def close_app(self) -> None:
        self.stack.close()
        self.app = None


def guard_digest(guard: ContractGuard) -> dict[str, str]:
    return {name: hashlib.sha256(content).hexdigest() for name, content in sorted(guard.saved.items())}
