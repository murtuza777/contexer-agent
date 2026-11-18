"""Results of verifying an application against its contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from contexer.contract.models import Contract, ContractStatus
from contexer.observer.models import BrowserObservation
from contexer.verification.models import VerificationResult

GateOutcome = Literal["pass", "fail", "needs_action", "error"]
JudgedPolicy = Literal["advisory", "block"]

EXIT_CODES: dict[GateOutcome, int] = {"pass": 0, "fail": 1, "needs_action": 2, "error": 3}


class ContractOutcome(BaseModel):
    """One contract's verification inside a run."""

    contract: Contract
    verification: VerificationResult | None = None
    error: str | None = None

    @property
    def status(self) -> ContractStatus:
        return self.contract.status


class GateDecision(BaseModel):
    """The verdict a merge gate acts on, with the reasons behind it."""

    outcome: GateOutcome
    reasons: list[str] = Field(default_factory=list)
    verified: int = 0
    refuted: int = 0
    unverified: int = 0
    # Judged or heuristic results that did not count toward the outcome.
    advisory: int = 0

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.outcome]

    def headline(self) -> str:
        label = {
            "pass": "PASS",
            "fail": "FAIL",
            "needs_action": "NEEDS ACTION",
            "error": "ERROR",
        }[self.outcome]
        counts = f"{self.verified} verified, {self.refuted} refuted, {self.unverified} unverified"
        if self.advisory:
            counts += f", {self.advisory} advisory"
        return f"{label}: {counts}"


class AttemptRow(BaseModel):
    """One agent attempt, as shown in the report."""

    n: int
    kind: str
    fresh_session: bool = False
    agent_status: str = ""
    agent_summary: str = ""
    agent_error: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    outcome: str = ""
    verified: int = 0
    refuted: int = 0
    unverified: int = 0
    note: str = ""
    duration_seconds: float = 0.0
    cost_usd: float | None = None


class TriageRow(BaseModel):
    """One decision about what to do after an attempt that did not pass (graph engine)."""

    attempt: int
    move: str
    reason: str = ""
    source: str = "rules"  # "model" or "rules"
    rejected: str = ""  # what a model answered when that answer was not used


class AgentRow(BaseModel):
    """What one of Contexer's own agents used in the run."""

    agent: str
    steps: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float | None = None


class AgentRunSummary(BaseModel):
    """How a coding agent was driven to the state that was verified."""

    agent: str
    terminal: str
    reason: str = ""
    best_attempt: int | None = None
    attempts: list[AttemptRow] = Field(default_factory=list)
    cost_usd: float = 0.0
    diff: str = ""
    engine: str = "classic"
    triage: list[TriageRow] = Field(default_factory=list)
    agents: list[AgentRow] = Field(default_factory=list)
    intent_id: str = ""
    corrections: list[str] = Field(default_factory=list)


class RunResult(BaseModel):
    """Everything a verification run produced; serialised as ``result.json``."""

    run_id: str
    project_dir: str
    app_url: str = ""
    started_at: str
    duration_seconds: float = 0.0
    # Gate mode requires approved contracts; ad-hoc mode (a fresh goal) does not.
    require_approval: bool = True
    contracts: list[ContractOutcome] = Field(default_factory=list)
    decision: GateDecision
    load: BrowserObservation | None = None
    server_log_tail: str = ""
    contexer_version: str = ""
    run_dir: str = ""
    error: str | None = None
    agent_run: AgentRunSummary | None = None
