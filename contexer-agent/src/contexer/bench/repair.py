"""The repair benchmark: can a coding agent, driven by Contexer, fix each seeded bug?

Every bug of every fixture app is laid out with the app's approved contract
and handed to a coding agent. A run counts as fixed only when it ends
``succeeded``, which is the gate's word, not the agent's.

This is how a weaker coding model is measured: same bugs, same checks,
another ``--model``. Until 0.5.0 it also compared two run loops; the result
that settled that (46 of 46 on each) is kept in ``bench/repair-results``.

``repair_only``. A capable model fixes most of these bugs in its first turn,
and a first turn shows nothing of the repair: what Triage chooses, and
whether the Diagnoser's lead is in the prompt. With ``repair_only`` the first
turn gives the agent the whole job and tells it to change nothing yet, so the
checks fail on the seeded bug and every fix is a repair, in the session that
already knows the job.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field

from contexer.agents.base import AgentTurn, CodingAgentAdapter
from contexer.bench.runner import FixtureApp, Variant, Workspace, discover
from contexer.controller import RunOutcome, RunSettings
from contexer.crew.budget import Budget
from contexer.graph import GraphController
from contexer.verification.runner import CheckRunner

WARM_UP_PROMPT = (
    "For this first turn, do not change, create or delete any file. Read the code that the checks above "
    "exercise and reply with one line: where you would look first."
)


class RepairRun(BaseModel):
    app: str
    bug: str
    fixed: bool = False
    terminal: str = ""
    attempts: int = 0
    # How each attempt after the first was started: what Triage (a model, or the fixed rules) chose.
    moves: list[str] = Field(default_factory=list)
    duration_seconds: float = 0.0
    cost_usd: float = 0.0
    error: str = ""


class RepairScore(BaseModel):
    bugs: int = 0
    fixed: int = 0
    first_try: int = 0
    after_repair: int = 0
    attempts: int = 0
    seconds: float = 0.0
    cost_usd: float = 0.0


class RepairReport(BaseModel):
    agent: str = ""
    crew_model: str = ""
    repair_only: bool = False
    rounds: int = 2
    runs: list[RepairRun] = Field(default_factory=list)
    score: RepairScore = Field(default_factory=RepairScore)
    duration_seconds: float = 0.0


async def run_repair_bench(
    fixtures_root: Path,
    make_agent: Callable[[], CodingAgentAdapter],
    *,
    only: list[str] | None = None,
    bugs: list[str] | None = None,
    limit: int | None = None,
    rounds: int = 2,
    repair_only: bool = False,
    model: BaseChatModel | None = None,
    crew_tokens: int | None = None,
    runner: CheckRunner | None = None,
    on_run: Callable[[RepairRun], None] | None = None,
) -> RepairReport:
    """Run every chosen bug. ``make_agent`` is called once per run, for a clean session."""
    apps = discover(Path(fixtures_root), only)
    chosen = [(app, bug) for app in apps for bug in app.bugs]
    if bugs:
        known = {f"{app.name}/{bug.name}" for app, bug in chosen}
        missing = [name for name in bugs if name not in known]
        if missing:
            raise ValueError(f"no bug named '{missing[0]}' in {fixtures_root} (bugs are named app/bug)")
        chosen = [(app, bug) for app, bug in chosen if f"{app.name}/{bug.name}" in bugs]
    if limit is not None:
        chosen = chosen[:limit]

    started = time.monotonic()
    report = RepairReport(repair_only=repair_only, rounds=rounds)
    # No Planner: this suite measures the repair loop, and its published numbers were made without a brief.
    settings = RunSettings(max_repair_rounds=rounds + (1 if repair_only else 0), replay_others=False, plan=False)
    workspaces: dict[str, Workspace] = {}
    try:
        for app, bug in chosen:
            workspace = workspaces.setdefault(app.name, Workspace(app))
            run = await _one(app, bug, workspace, make_agent, settings, repair_only, model, crew_tokens, runner)
            report.runs.append(run)
            if on_run is not None:
                on_run(run)
    finally:
        for workspace in workspaces.values():
            workspace.close()
    report.score = _score(report.runs, repair_only)
    report.duration_seconds = time.monotonic() - started
    return report


async def _one(
    app: FixtureApp,
    bug: Variant,
    workspace: Workspace,
    make_agent: Callable[[], CodingAgentAdapter],
    settings: RunSettings,
    repair_only: bool,
    model: BaseChatModel | None,
    crew_tokens: int | None,
    runner: CheckRunner | None,
) -> RepairRun:
    run = RepairRun(app=app.name, bug=bug.name)
    started = time.monotonic()
    project = workspace.materialise(bug.overlay)  # the good app, the bug on top, and nothing of the last run
    agent: CodingAgentAdapter | None = None
    try:
        agent = make_agent()
        driven: CodingAgentAdapter = _ReadsFirst(agent) if repair_only else agent
        contract = next((c for c in app.contracts if c.status == "approved"), None)
        if contract is None:
            raise ValueError(f"{app.name} has no approved contract")
        budget = Budget(max_tokens=crew_tokens) if crew_tokens else None
        controller = GraphController(project, driven, settings, runner=runner, model=model, budget=budget)
        outcome: RunOutcome = await controller.run(contract)
        run.terminal = outcome.terminal
        run.fixed = outcome.terminal == "succeeded"
        run.attempts = len(outcome.attempts)
        run.cost_usd = outcome.cost_usd
        run.error = outcome.reason if not run.fixed else ""
        run.moves = [d.move for d in outcome.triage]
    except Exception as exc:  # one bug that cannot be run must not end a benchmark of forty
        run.terminal, run.error = "error", f"{type(exc).__name__}: {exc}"
    finally:
        if agent is not None:
            agent.close()
    run.duration_seconds = time.monotonic() - started
    return run


class _ReadsFirst(CodingAgentAdapter):
    """Wraps an agent so that its first turn gets the whole job and is told to change nothing yet."""

    def __init__(self, inner: CodingAgentAdapter) -> None:
        self.inner = inner
        self.name = inner.name
        self._turns = 0

    def describe(self) -> str:
        return self.inner.describe()

    async def run_turn(self, workdir: Path, prompt: str, **kwargs: Any) -> AgentTurn:
        self._turns += 1
        if self._turns == 1:
            prompt = f"{prompt}\n\n{WARM_UP_PROMPT}"
        return await self.inner.run_turn(workdir, prompt, **kwargs)

    def close(self) -> None:
        self.inner.close()

    def stop(self) -> None:
        self.inner.stop()


def _score(mine: list[RepairRun], repair_only: bool) -> RepairScore:
    first = 2 if repair_only else 1  # with repair_only the first turn changes nothing by design
    return RepairScore(
        bugs=len(mine),
        fixed=sum(r.fixed for r in mine),
        first_try=sum(r.fixed and r.attempts <= 1 for r in mine),
        after_repair=sum(r.fixed and r.attempts >= first and r.attempts > 1 for r in mine),
        attempts=sum(r.attempts for r in mine),
        seconds=sum(r.duration_seconds for r in mine),
        cost_usd=sum(r.cost_usd for r in mine),
    )


def results_markdown(report: RepairReport) -> str:
    """The report as a table, and the bugs that were not fixed."""
    lines = [
        f"Coding agent: {report.agent or 'unknown'}. Contexer's own agents: "
        f"{report.crew_model or 'none (the rules decide)'}. Up to {report.rounds} repair round(s) per bug."
    ]
    if report.repair_only:
        lines.append(
            "Repair only: the first turn gave the agent the job and told it to change nothing, so every fix "
            "below is a repair. \"Attempts\" counts that first turn."
        )
    s = report.score
    cost = f"${s.cost_usd:.2f}" if s.cost_usd else "not reported"
    lines += [
        "",
        "| Bugs | Fixed | First try | After a repair | Attempts | Minutes | Agent cost |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        f"| {s.bugs} | {s.fixed} | {s.first_try} | {s.after_repair} | {s.attempts} | {s.seconds / 60:.1f} | {cost} |",
    ]
    unfixed = [r for r in report.runs if not r.fixed]
    lines += ["", "Not fixed:" if unfixed else "Not fixed: none."]
    lines += [f"- `{r.app}/{r.bug}`: {r.terminal} after {r.attempts} attempt(s)" for r in unfixed]
    return "\n".join(lines) + "\n"
