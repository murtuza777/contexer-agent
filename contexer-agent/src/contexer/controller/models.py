"""What a run is configured with and what it reports. Shared by both engines."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from contexer import __version__
from contexer.agents.base import AgentTurn
from contexer.crew.reviewer import ReviewNote
from contexer.crew.triage import TriageDecision
from contexer.evidence.test_report import AgentUsage
from contexer.gate.models import JudgedPolicy, RunResult

TerminalState = Literal[
    "succeeded",
    "failed_checks",
    "needs_human",
    "budget_exhausted",
    "timed_out",
    "tampered",
    "agent_error",
    "app_error",
    "cancelled",
]

Engine = Literal["classic", "graph"]


class RunSettings(BaseModel):
    max_repair_rounds: int = 2
    budget_usd: float | None = None
    turn_timeout: float = 900.0
    wall_clock: float = 3600.0
    judged_policy: JudgedPolicy = "advisory"
    replay_others: bool = True
    # Read the diff of a passing attempt before the run ends (crew/reviewer.py).
    review: bool = True
    # Step caps for Contexer's own agents, by name ("diagnoser", "reviewer"); the agent's default when absent.
    agent_steps: dict[str, int] = Field(default_factory=dict)


class Attempt(BaseModel):
    n: int
    kind: Literal["implement", "repair"]
    fresh_session: bool
    agent: AgentTurn
    snapshot: str
    changed_files: list[str] = Field(default_factory=list)
    outcome: str
    verified: int = 0
    refuted: int = 0
    unverified: int = 0
    score: int
    signatures: list[str] = Field(default_factory=list)
    reverted_to: int | None = None
    note: str = ""
    result_dir: str = ""


class RunOutcome(BaseModel):
    run_id: str
    contract_id: str
    agent: str
    terminal: TerminalState
    reason: str = ""
    attempts: list[Attempt] = Field(default_factory=list)
    best_attempt: int | None = None
    final: RunResult | None = None
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    started_at: str = ""
    diff: str = ""
    changed_files: list[str] = Field(default_factory=list)  # project-relative, baseline → what was left
    run_dir: str = ""
    contexer_version: str = __version__
    # Which loop drove the run. "classic" is what a run.json written before 0.5.0 holds (and what one without
    # the field means); every run since is "graph". The fields below are the graph's.
    engine: Engine = "classic"
    triage: list[TriageDecision] = Field(default_factory=list)
    agents: list[AgentUsage] = Field(default_factory=list)  # Contexer's own agents: Intent, Triage, Diagnoser
    intent_id: str = ""
    corrections: list[str] = Field(default_factory=list)
    # What the review of the final state found. Advice and facts about the diff; never part of the verdict.
    review: list[ReviewNote] = Field(default_factory=list)
    # What Contexer's own agents cost in this run. None: the provider reports no price and no rates are configured.
    crew_cost_usd: float | None = None
    # True when any of it was worked out from tokens and the configured rates.
    crew_cost_estimated: bool = False

    @property
    def exit_code(self) -> int:
        return {
            "succeeded": 0,
            "failed_checks": 1,
            "needs_human": 2,
            "tampered": 2,
            "budget_exhausted": 2,
            "timed_out": 2,
            "agent_error": 3,
            "app_error": 3,
            "cancelled": 130,  # the shell's code for Ctrl+C
        }[self.terminal]
