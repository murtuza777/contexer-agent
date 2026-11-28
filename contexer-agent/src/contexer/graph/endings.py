"""How a run ends when it does not reach its own end: stopped by a person, or an error in Contexer itself.

Either way it still ends as a run: the unfinished work is kept as a snapshot, a state that was proven
or found is put back, and ``run.json`` and the report are written. ``finalize`` in ``nodes.py`` writes the
ending a run reaches on its own; the outcome both start from is built here.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from contexer.controller.models import Attempt, RunOutcome
from contexer.controller.shared import write_run_evidence
from contexer.crew.reviewer import ReviewNote
from contexer.crew.transcript import Masker
from contexer.crew.triage import TriageDecision
from contexer.evidence.rundir import write_whole
from contexer.evidence.test_report import AgentUsage
from contexer.graph.context import STOPPED_FILE, RunContext
from contexer.graph.facts import _attempts, _crew_cost
from contexer.graph.state import LoopState
from contexer.llm.chat import clean_error


def _outcome(ctx: RunContext, state: LoopState, attempts: list[Attempt]) -> RunOutcome:
    return RunOutcome(
        run_id=ctx.run.run_id,
        contract_id=state.get("contract_id") or "",
        agent=ctx.agent.describe(),
        terminal="failed_checks",
        attempts=attempts,
        cost_usd=state.get("cost_usd", 0.0),
        started_at=state.get("started_at", ""),
        run_dir=str(ctx.run.path),
        engine="graph",
        triage=[TriageDecision.model_validate(d) for d in state.get("decisions", [])],
        agents=[AgentUsage.model_validate(row) for row in state.get("agents", [])],
        intent_id=state.get("intent_id") or "",
        corrections=list(state.get("corrections", [])),
        review=[ReviewNote.model_validate(note) for note in state.get("review", [])],
        crew_cost_usd=_crew_cost(state),
        crew_cost_estimated=bool(ctx.budget is not None and ctx.budget.estimated),
        baseline=state.get("baseline"),
    )


# The traceback of a run that ended on an error in Contexer itself, in its run folder.
CRASH_FILE = "crash.txt"


ISSUES_URL = "https://github.com/murtuza777/contexer-agent/issues"


def stopped_outcome(ctx: RunContext) -> RunOutcome:
    """A run that was stopped: keep the unfinished work as a snapshot, put back a state that was proven or found."""
    return _cut_short(
        ctx,
        "cancelled",
        lambda put_back, kept: (
            f"Stopped before the run ended; left {put_back}.{kept} "
            f"`contexer run --resume {ctx.run.run_id}` continues it."
        ),
    )


def crashed_outcome(ctx: RunContext, exc: Exception) -> RunOutcome:
    """A run that ended on an error in Contexer itself. It still ends as a run: files put back, a report written."""
    what = f"{type(exc).__name__}: {clean_error(exc)}"
    trace = ctx.run.path / CRASH_FILE
    try:
        trace.write_text(Masker().text("".join(traceback.format_exception(exc))), encoding="utf-8")
        where = f" The traceback is in {trace}."
    except OSError:
        where = ""
    report = f"{where} Please report it: {ISSUES_URL}."
    again = f"`contexer run --resume {ctx.run.run_id}` tries again from the last step that finished."
    try:
        return _cut_short(
            ctx,
            "internal_error",
            lambda put_back, kept: (
                f"Contexer itself failed ({what}). This is a fault in Contexer, not in the project. "
                f"Left {put_back}.{kept}{report} {again}"
            ),
        )
    except Exception as second:
        # Putting the files back failed too. Say so, and still leave a run.json.
        state: LoopState = ctx.mirror  # type: ignore[assignment]
        outcome = _outcome(ctx, state, _attempts(state))
        outcome.terminal = "internal_error"
        outcome.reason = (
            f"Contexer itself failed ({what}). This is a fault in Contexer, not in the project. The files could not "
            f"be put back ({type(second).__name__}: {clean_error(second)}); they are as the run left them.{report}"
        )
        outcome.duration_seconds = ctx.elapsed()
        try:
            write_run_evidence(ctx.project, outcome, ctx.run)
        except Exception:
            pass
        ctx.outcome = outcome
        return outcome


def _cut_short(ctx: RunContext, terminal: Any, reason: Callable[[str, str], str]) -> RunOutcome:
    """End a run that did not reach its own end: unfinished work kept as a snapshot, a known state put back."""
    state: LoopState = ctx.mirror  # type: ignore[assignment]
    snapshots = state.get("snapshots", {})
    attempts = _attempts(state)
    # An attempt that was snapshotted but never scored is unfinished work, not a result.
    scored = [a for a in attempts if a.outcome != "error" or a.result_dir]
    best = state.get("best")
    unfinished = ctx.shadow.snapshot(f"{ctx.run.run_id}/stopped", "stopped before the run ended")
    target = snapshots[str(best)] if best is not None and str(best) in snapshots else snapshots["0"]
    put_back = "the best attempt reached" if best is not None else "the project as it was"
    kept = ""
    # Where the unfinished work is, for a resume that needs it back (context.py: STOPPED_FILE).
    write_whole(ctx.run.path / STOPPED_FILE, unfinished)
    if ctx.shadow.changed_paths(target, unfinished):
        ctx.shadow.restore(target)
        kept = f" The unfinished work is kept: `contexer restore {ctx.run.run_id} --stopped` brings it back."
    outcome = _outcome(ctx, state, scored)
    outcome.terminal = terminal
    outcome.reason = reason(put_back, kept)
    outcome.best_attempt = best
    outcome.final = ctx.result(best)
    if outcome.final is not None:
        outcome.stale, outcome.regressions = list(outcome.final.decision.stale), dict(outcome.final.decision.regressions)
    outcome.diff = ctx.shadow.diff(snapshots["0"], target)
    outcome.changed_files = ctx.shadow.changed_paths(snapshots["0"], target)
    outcome.duration_seconds = ctx.elapsed()
    write_run_evidence(ctx.project, outcome, ctx.run)
    ctx.outcome = outcome
    return outcome
