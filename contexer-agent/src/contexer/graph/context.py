"""What a run needs that cannot be written to a checkpoint.

The browser, the dev server, the coding agent, the snapshot repository and
the models are live objects. They belong to the process, so a resumed run
builds them again; the state (``state.py``) is what survives.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from contexer.agents.base import CodingAgentAdapter
from contexer.appserver import RunningApp
from contexer.browser.tools import sign_in_secrets
from contexer.checkpoint import ShadowRepo
from contexer.config.project import ProjectConfigError, load_project_config
from contexer.contract import Contract, ContractStore
from contexer.controller.models import RunOutcome, RunSettings
from contexer.controller.shared import ContractGuard
from contexer.crew.budget import Budget
from contexer.crew.context_sources import ContextSource, instruction_sources, intent_source, issue_source, sources_read
from contexer.crew.transcript import environment_secrets
from contexer.evidence.rundir import RunDir, write_whole
from contexer.gate.models import RunResult
from contexer.github import issues as github_issues
from contexer.intent.store import IntentError, IntentSpec, IntentStore
from contexer.verification.runner import CheckRunner
from contexer.workflow.inspector import RepositoryContext

EventFn = Callable[[str, str], None]


@dataclass(frozen=True)
class RunEvent:
    """One thing that happened in a run, with the data a watcher needs to draw it.

    ``kind`` and ``message`` are what the words-only stream (``EventFn``) carries. ``data`` is plain
    values only. Kinds that have no words (``checks``, ``attempt-start``, ``end``) are sent here alone.
    """

    kind: str
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    # Seconds since the run began.
    at: float = 0.0

    def as_json(self) -> dict[str, Any]:
        """The event as one flat object: ``event``, ``at``, ``message`` when there is one, then its data."""
        flat: dict[str, Any] = {"event": self.kind, "at": round(self.at, 2)}
        if self.message:
            flat["message"] = self.message
        flat.update(self.data)
        return flat


DetailFn = Callable[[RunEvent], None]
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
    on_detail: DetailFn | None = None
    url: str | None = None
    model: BaseChatModel | None = None
    # A model for one agent by name, where the project chose one; the others use ``model``.
    models: dict[str, BaseChatModel] = field(default_factory=dict)
    budget: Budget | None = None
    can_ask: bool = False
    corrections: Callable[[], str | None] | None = None
    pending_correction: str | None = None
    # Whether this process has already asked if the [auth] sign-in works (it is asked once, before spending).
    signed_in_checked: bool = False
    # The content hash of the contract whose checks were last announced to a view.
    announced: str = ""
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
    # What was read about the task besides its goal, by kind; each kind is read once (``sources``).
    _sources: dict[str, list[ContextSource]] = field(default_factory=dict)

    def model_for(self, agent: str) -> BaseChatModel | None:
        return self.models.get(agent) or self.model

    def secrets(self) -> list[str]:
        """What no agent of this run may be sent: the passwords and codes ``[auth]`` types, and the keys in the environment.

        The same list ``contexer test`` gives its agents. A page, a diff or a log can show the test
        account's password, and only this list tells the masker what it is.
        """
        try:
            typed = sign_in_secrets(load_project_config(self.project).auth)
        except ProjectConfigError:
            typed = []
        return [*typed, *environment_secrets()]

    def sources(self, state: Mapping[str, Any], kinds: Sequence[str] = ("issue", "instructions", "intent")) -> list[ContextSource]:
        """What was written about the task besides its goal (``crew/context_sources.py``), for an agent's task.

        The instruction files come from the snapshot taken before the coding agent's first turn, so
        nothing the agent writes into them is read here. The intent comes from the store, which the
        guard puts back after every turn. The issue is asked for once. Each kind is read the first
        time an agent needs it, and the run says then what was read.
        """
        new: list[ContextSource] = []
        unread = ""
        for kind in kinds:
            if kind in self._sources:
                continue
            found: list[ContextSource] = []
            if kind == "instructions":
                found = instruction_sources(partial(self.shadow.read_file, state["snapshots"]["0"]))
            elif kind == "issue":
                origin = state.get("goal_origin") or (self.contract.origin if self.contract is not None else "")
                number = github_issues.issue_number(origin)
                discussion = github_issues.read_discussion(self.project, number) if number is not None else None
                if discussion is not None:
                    source = issue_source(origin, discussion)
                    found = [source] if source is not None else []
                elif number is not None:
                    unread = f"the comments on {origin.strip()} could not be read"
            elif kind == "intent":
                source = intent_source(self._intent(state.get("intent_id") or ""))
                found = [source] if source is not None else []
            self._sources[kind] = found
            new += found
        if new or unread:
            said = ", ".join(part for part in (sources_read(new), unread) if part)
            self.event("strategy", f"Context read: {said}", sources=[source.name for source in new])
        return [source for kind in kinds for source in self._sources.get(kind, [])]

    def _intent(self, intent_id: str) -> IntentSpec | None:
        try:
            if intent_id:
                return self.intents.load(intent_id) if self.intents.exists(intent_id) else None
            return self.intents.find(self.contract.goal) if self.contract is not None else None
        except (IntentError, OSError, ValueError):
            return None

    def spent(self, coding_usd: float) -> str:
        """Tell the budget what the coding agent has spent; returns why the whole run must stop, or ''.

        Any limit that is reached stops the run, the token limit of Contexer's own agents too: a run
        whose agents may no longer be asked would otherwise go on paying for coding turns under rules.
        """
        if self.budget is None:
            return ""
        self.budget.other_usd = coding_usd
        return self.budget.exhausted()

    def event(self, kind: str, message: str, **data: Any) -> None:
        """Say what happened, in words for a log and with data for a view."""
        self.on_event(kind, message)
        if self.on_detail is not None:
            self.on_detail(RunEvent(kind, message, data, self.elapsed()))

    def detail(self, kind: str, **data: Any) -> None:
        """Something a view needs and a log does not: the list of checks, the start of an attempt, the end."""
        if self.on_detail is not None:
            self.on_detail(RunEvent(kind, "", data, self.elapsed()))

    def elapsed(self) -> float:
        return self.base_elapsed + (time.monotonic() - self.started)

    # -- results: kept on disk too, so a resumed run can still write its repair prompt -----

    def attempt_dir(self, n: int) -> RunDir:
        path = self.run.path / f"attempt-{n}"
        path.mkdir(parents=True, exist_ok=True)
        return RunDir(run_id=f"{self.run.run_id}/a{n}", path=path)

    def save_result(self, n: int, result: RunResult) -> None:
        self._results[n] = result
        write_whole(self.attempt_dir(n).path / _RESULT_FILE, result.model_dump_json())

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
