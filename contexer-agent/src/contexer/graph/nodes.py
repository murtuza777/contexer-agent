"""The nodes of the loop. Each does one thing and returns the part of the state it changed.

A node may be run again from its start: when a run is resumed after its
process died, and (for the two that wait for a person) when the answer
arrives. So a node writes to the state only by returning, and the work tree
is reset to the last snapshot before a resumed node runs.

Who decides what:

* ``intent``, ``triage`` and ``diagnose`` ask a model, when one is
  configured. Without one they do nothing, apply the 0.4 rules, or write the
  plain repair prompt, and the loop is the classic one.
* ``guard_snapshot``, ``score`` and ``finalize`` ask nobody. Tampering, the
  score, the revert to the best attempt and the final outcome are code.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from langgraph.types import interrupt

from contexer.agents.base import AgentTurn
from contexer.appserver import AppStartError, open_app
from contexer.contract import Contract
from contexer.controller.models import Attempt, RunOutcome
from contexer.controller.prompts import failure_report, implement_prompt, repair_prompt, restated_prompt
from contexer.controller.shared import (
    DEPENDENCY_FILES,
    check_count,
    score,
    sig_label,
    signatures,
    turn_line,
    write_run_evidence,
)
from contexer.crew.diagnoser import Failure, brief_section, diagnose
from contexer.crew.intent import run_intent
from contexer.crew.reviewer import ReviewNote, review, review_repair_prompt
from contexer.crew.triage import MOVE_LABELS, AttemptView, Situation, TriageDecision, triage
from contexer.crew.untrusted import quoted_goal
from contexer.evidence.test_report import AgentUsage
from contexer.gate.decision import decide
from contexer.gate.models import GateDecision, RunResult
from contexer.gate.session import VerificationSession
from contexer.graph.context import STOPPED_FILE, RunContext
from contexer.graph.routing import settle
from contexer.graph.state import CARRIED_SCORE, UNSCORED, LoopState
from contexer.intent.store import IntentSpec, SavedCheck
from contexer.verification.models import AcceptanceCriterion
from contexer.verification.verifier import Verifier

Node = Callable[[LoopState], Awaitable[dict[str, Any]]]
_DIFF_CHARS = 20_000
_REVIEW_DIFF_CHARS = 200_000
# A review may ask the coding agent for one more turn on work that passed, and no more.
MAX_REVIEW_REPAIRS = 1


def make_nodes(ctx: RunContext) -> dict[str, Node]:
    """The nodes, bound to one run's live objects."""

    # -- intent: what should be true -----------------------------------------------------

    async def intent(state: LoopState) -> dict[str, Any]:
        correction = (state.get("correction") or "").strip()
        contract_id = state.get("contract_id") or ""
        existing = _stored_contract(ctx, contract_id)
        if existing is not None and not correction:
            return {}  # a contract was given; nothing to draft
        if ctx.model is None:
            return {"terminal": "needs_human", "reason": "No model is configured to draft checks from the goal."}

        goal = state.get("goal") or (existing.goal if existing else "")
        intent_id = state.get("intent_id") or ""
        stored = ctx.intents.load(intent_id) if intent_id and ctx.intents.exists(intent_id) else ctx.intents.find(goal)
        spec = stored or IntentSpec(id=ctx.intents.id_for(goal), goal=goal.strip())
        known = _saved_checks(existing) if existing is not None else ctx.intents.load_checks(spec.id)
        ctx.event("phase-quiet", "Redrafting the checks for your correction" if correction else "Drafting checks from the goal")
        result = await run_intent(
            goal,
            ctx.model,
            stored=spec,
            existing_checks=known,
            correction=correction or None,
            repo_summary=ctx.repo.format_summary() if ctx.repo is not None else "",
            ui_snapshot=await _ui_snapshot(ctx),
            assume=True,  # questions are not asked mid-run; assumptions are shown with the checks, and can be corrected
            run_dir=ctx.run.path,
            budget=ctx.budget,
        )
        ctx.intents.save(result.spec)
        ctx.intents.save_checks(result.spec.id, result.checks)
        updates: dict[str, Any] = {
            "intent_id": result.spec.id,
            "correction": "",
            "agents": _used(state, "intent", result.steps, result.tokens_in, result.tokens_out, result.cost_usd),
        }
        if result.status != "ok":
            ctx.event("strategy", f"The Intent agent did not finish ({result.error or result.status}); the checks are as they were.")
        criteria = _criteria(result.checks, existing)
        if existing is None and not any(c.check for c in criteria):
            updates.update(
                guard=ctx.recapture_guard(),
                terminal="needs_human",
                reason="The Intent agent drafted no check that can be executed, so nothing says what done means. "
                "Write the goal more concretely, or write a contract by hand.",
            )
            return updates

        if existing is None:
            contract = Contract(
                id=contract_id or ctx.store.unique_id(goal),
                goal=goal.strip(),
                summary="Drafted by the Intent agent from the goal.",
                criteria=criteria,
                source="llm",
            )
        else:
            contract = existing.model_copy(update={"criteria": criteria})
        if existing is None or contract.content_hash() != existing.content_hash():
            ctx.store.save(contract)  # a changed contract is not approved any more: its hash differs
        elif correction:
            ctx.event("strategy", "The correction changed no check; the approved checks stand.")
        if correction:
            updates["corrections"] = [*state.get("corrections", []), correction]
            updates["restate"] = correction
        updates.update(contract_id=contract.id, guard=ctx.recapture_guard())
        return updates

    # -- approve: a person says these checks are what done means ---------------------------

    async def approve(state: LoopState) -> dict[str, Any]:
        contract = _stored_contract(ctx, state["contract_id"])
        if contract is None:
            return {"terminal": "needs_human", "reason": f"Contract '{state['contract_id']}' is not in the project any more."}
        restate = state.get("restate") or ""
        if contract.status == "approved" and contract.content_hash() == state.get("approved_hash"):
            ctx.contract = contract
            if not restate:
                return {}
            return {"prompt": _job_prompt(ctx, contract, state, restate), "fresh": True, "restate": ""}

        spec = ctx.intents.load(state["intent_id"]) if state.get("intent_id") and ctx.intents.exists(state["intent_id"]) else None
        answer = interrupt(
            {
                "kind": "approve",
                "contract_id": contract.id,
                "goal": contract.goal,
                "checks": contract.describe_lines(),
                "assumptions": list(spec.assumptions) if spec else [],
                "source": contract.source,
                # True when checks that were approved before have changed since.
                "changed": bool(state.get("approved_hash") or state.get("corrections")),
            }
        )
        answer = answer if isinstance(answer, dict) else {}
        typed = str(answer.get("correction") or "").strip()
        if typed:
            return {"correction": typed}
        if answer.get("approve") is not True:
            return {"terminal": "needs_human", "reason": "The checks were not approved, so nothing was built against them."}

        approved = ctx.store.approve(contract.id)
        ctx.contract = approved
        ctx.event("approved", f"Approved {approved.id}")
        updates: dict[str, Any] = {"approved_hash": approved.content_hash(), "guard": ctx.recapture_guard(), "restate": ""}
        updates["prompt"] = _job_prompt(ctx, approved, state, restate)
        if state.get("n", 0) == 0:
            return updates
        # The checks changed after work began. Scores under the old checks say nothing about the new ones:
        # the files that are there stay the fallback, and any attempt that runs under the new checks beats it.
        current = state.get("current")
        held = next((int(n) for n, snap in state.get("snapshots", {}).items() if snap == current and int(n) > 0), None)
        updates.update(
            fresh=True,
            best=held,
            best_score=CARRIED_SCORE if held is not None else UNSCORED,
            last_signatures=[],
        )
        return updates

    # -- coder_turn: the coding agent edits files --------------------------------------------

    async def coder_turn(state: LoopState) -> dict[str, Any]:
        correction = ctx.take_correction()
        if correction:
            return {"correction": correction}
        if ctx.elapsed() > ctx.settings.wall_clock:
            return {"terminal": "timed_out", "reason": "Wall-clock budget used up."}
        cost = state.get("cost_usd", 0.0)
        remaining = None
        if ctx.settings.budget_usd is not None:
            remaining = ctx.settings.budget_usd - cost
            if remaining <= 0:
                return {"terminal": "budget_exhausted", "reason": "Spending budget used up."}

        n = state.get("n", 0) + 1
        fresh = state.get("fresh", True)
        doing = "implementing" if n == 1 else "repairing"
        ctx.event("phase", f"Attempt {n}: {doing}{' (fresh session)' if fresh and n > 1 else ''} with {ctx.agent.describe()}")
        turn = await ctx.agent.run_turn(
            ctx.project,
            state["prompt"],
            session_id=None if fresh else state.get("session_id"),
            timeout=ctx.settings.turn_timeout,
            budget_usd=remaining,
            on_progress=lambda line: ctx.event("agent", line),
        )
        return {
            "n": n,
            "turn": turn.model_dump(mode="json"),
            "session_id": turn.session_id or state.get("session_id"),
            "cost_usd": cost + (turn.cost_usd or 0.0),
        }

    # -- guard_snapshot: keep what the agent did, and check it left "done" alone -----------

    async def guard_snapshot(state: LoopState) -> dict[str, Any]:
        assert ctx.guard is not None
        n = state["n"]
        turn = AgentTurn.model_validate(state.get("turn"))
        tampered = ctx.guard.restore_if_changed()
        snapshot = ctx.shadow.snapshot(f"{ctx.run.run_id}/{n}", f"attempt {n}")
        changed = ctx.shadow.changed_paths(state["current"], snapshot)
        attempt = Attempt(
            n=n,
            kind="implement" if n == 1 else "repair",
            fresh_session=state.get("fresh", True),
            agent=turn,
            snapshot=snapshot,
            changed_files=changed,
            outcome="error",
            score=-(10**6),
        )
        ctx.event("agent-done", turn_line(turn, changed))
        updates: dict[str, Any] = {
            "snapshots": {**state.get("snapshots", {}), str(n): snapshot},
            "current": snapshot,
            "changed": changed,
            "reverted_from": None,
            "elapsed": ctx.elapsed(),
        }
        if tampered:
            attempt.note = f"Agent modified what defines done (contracts, intent or contexer.toml): {', '.join(tampered)} (restored)."
            updates.update(terminal="tampered", reason=attempt.note)
        elif not turn.ok and not changed and state.get("review_passed") is not None:
            # The turn a review asked for did not happen. The work it was asked on had passed, and still stands.
            accepted = state.get("review_passed")
            attempt.note = f"The repair the review asked for did not complete ({turn.error or turn.status}); attempt {accepted} stands."
            ctx.event("strategy", attempt.note)
            updates.update(
                accepted=accepted,
                reviewed=n,
                terminal="succeeded",
                reason=f"Every check proven in the browser (attempt {accepted}).",
            )
        elif not turn.ok and not changed:
            attempt.note = turn.error or turn.status
            updates.update(
                terminal="budget_exhausted" if turn.status == "budget_exceeded" else "agent_error",
                reason=f"The coding agent did not complete: {attempt.note}",
            )
        updates["attempts"] = [*state.get("attempts", []), attempt.model_dump(mode="json")]
        return updates

    # -- ensure_app: the app runs the files as they are now ---------------------------------

    async def ensure_app(state: LoopState) -> dict[str, Any]:
        return {"app_error": _start_app(ctx, state.get("changed", []))}

    # -- test: replay every approved check in a browser ---------------------------------------

    async def test(state: LoopState) -> dict[str, Any]:
        n = state["n"]
        contracts = _contracts(ctx)
        folder = ctx.attempt_dir(n)
        error = state.get("app_error")
        if error is None and ctx.app is not None:
            ctx.event("phase", f"Attempt {n}: proving {check_count(contracts)} checks in Chromium")
            session = VerificationSession(ctx.project, folder, verifier=Verifier(llm_provider=None, runner=ctx.runner))
            result = await session.verify(ctx.app, contracts, judged_policy=ctx.settings.judged_policy)
        else:
            session = VerificationSession(ctx.project, folder)
            decision = GateDecision(outcome="error", reasons=[f"App did not start: {error}"])
            result = session.result(ctx.app, [], decision, error=error)
            if not result.server_log_tail and error:
                result.server_log_tail = error
        ctx.save_result(n, result)
        attempts = _attempts(state)
        attempts[-1].result_dir = str(folder.path)
        return {"attempts": _dump(attempts)}

    # -- score: is it done, is it the best so far, is it worse ---------------------------------

    async def score_attempt(state: LoopState) -> dict[str, Any]:
        n = state["n"]
        contract = _contract(ctx)
        result = ctx.result(n)
        assert result is not None
        attempts = _attempts(state)
        attempt = attempts[-1]
        attempt.outcome = result.decision.outcome
        attempt.verified, attempt.refuted, attempt.unverified = (
            result.decision.verified,
            result.decision.refuted,
            result.decision.unverified,
        )
        attempt.score = score(result, contract.id)
        sigs = signatures(result)
        attempt.signatures = sorted(sigs)
        ctx.event("verdict", f"Attempt {n}: {result.decision.headline()}")
        updates: dict[str, Any] = {"elapsed": ctx.elapsed()}

        if result.decision.outcome == "pass":
            updates.update(attempts=_dump(attempts), best=n, terminal="succeeded", reason="Every check proven in the browser.")
            return updates

        snapshots = state.get("snapshots", {})
        accepted = state.get("review_passed")
        if accepted is not None and str(accepted) in snapshots:
            # This attempt was the repair a review asked for, on work that had already passed. It broke a
            # check, so it is undone: a review can ask for more, it cannot take a pass away.
            ctx.shadow.restore(snapshots[str(accepted)])
            attempt.reverted_to = accepted
            attempt.note = f"The repair the review asked for broke a check; went back to attempt {accepted}, which passed."
            ctx.event("revert", attempt.note)
            _restart_if_dependencies_changed(ctx, snapshots[str(n)], snapshots[str(accepted)])
            updates.update(
                attempts=_dump(attempts),
                best=accepted,
                accepted=accepted,
                reviewed=n,  # what the review found on that attempt still stands; it is not read again
                current=snapshots[str(accepted)],
                reverted_from=accepted,
                terminal="succeeded",
                reason=f"Every check proven in the browser (attempt {accepted}). A repair the review asked for was undone.",
            )
            return updates
        best, best_score = state.get("best"), state.get("best_score", UNSCORED)
        current = state["current"]
        reverted_from: int | None = None
        usable = result.decision.outcome != "error"  # an app that does not start is never kept
        if usable and attempt.score > best_score:
            best, best_score = n, attempt.score
        elif best is not None and attempt.score < best_score:
            ctx.shadow.restore(snapshots[str(best)])
            attempt.reverted_to = best
            reverted_from = best
            attempt.note = f"Scored lower than attempt {best}; reverted to it."
            ctx.event("revert", attempt.note)
            _restart_if_dependencies_changed(ctx, snapshots[str(n)], snapshots[str(best)])
            current = snapshots[str(best)]

        repeated = sorted({sig_label(s) for s in sigs & set(state.get("last_signatures", []))})
        updates.update(
            attempts=_dump(attempts),
            best=best,
            best_score=best_score,
            current=current,
            reverted_from=reverted_from,
            repeats={**state.get("repeats", {}), str(n): repeated},
            last_signatures=sorted(sigs),
        )
        if n > ctx.settings.max_repair_rounds:
            only_unverified = result.decision.refuted == 0 and result.decision.outcome == "needs_action"
            updates.update(
                terminal="needs_human" if only_unverified or state.get("app_error") else "failed_checks",
                reason=f"Not all checks passed after {ctx.settings.max_repair_rounds} repair round(s). "
                + "; ".join(result.decision.reasons[:3]),
            )
        return updates

    # -- review: the diff of a passing attempt is read before the run ends --------------------------

    async def review_node(state: LoopState) -> dict[str, Any]:
        n = state["n"]
        updates: dict[str, Any] = {"reviewed": n}
        if not ctx.settings.review:
            return updates
        snapshots = state["snapshots"]
        passed = snapshots[str(n)]
        contract = _contract(ctx)
        ctx.event("phase-quiet", "Reading the change before it is handed over")
        found = await review(
            ctx.shadow.diff(snapshots["0"], passed, max_chars=_REVIEW_DIFF_CHARS),
            ctx.project,
            ctx.model,
            intent=quoted_goal(contract.goal, contract.origin),
            checks=[c.description for c in contract.criteria],
            run_dir=ctx.run.path,
            budget=ctx.budget,
        )
        # A project command may write files (a formatter, a snapshot test). What passed is the snapshot.
        if ctx.shadow.changed_paths(passed, ctx.shadow.snapshot()):
            ctx.shadow.restore(passed)
        if found.status != "scan_only":
            updates["agents"] = _used(state, "reviewer", found.steps, found.tokens_in, found.tokens_out, found.cost_usd)
            if found.status != "ok":
                ctx.event("strategy", f"The Reviewer did not finish ({found.error or found.status}); the notes are what a program found.")
        updates["review"] = [note.model_dump(mode="json") for note in found.notes]
        to_fix = found.blocking
        if found.notes:
            ctx.event("review", f"Review: {len(found.notes)} note(s), {len(to_fix)} to fix")

        budget_left = ctx.settings.budget_usd is None or ctx.settings.budget_usd - state.get("cost_usd", 0.0) > 0
        if (
            to_fix
            and state.get("review_repairs", 0) < MAX_REVIEW_REPAIRS
            and n <= ctx.settings.max_repair_rounds
            and budget_left
            and ctx.elapsed() < ctx.settings.wall_clock
        ):
            # Not a failure: the pass is set aside for one turn, and comes back if that turn breaks anything.
            updates.update(
                terminal="",
                reason="",
                review_repairs=state.get("review_repairs", 0) + 1,
                review_passed=n,
                prompt=review_repair_prompt(found.notes),
                fresh=not state.get("session_id"),
            )
        return updates

    # -- triage: what next ------------------------------------------------------------------------

    async def triage_node(state: LoopState) -> dict[str, Any]:
        correction = ctx.take_correction()
        if correction:
            return {"correction": correction, "move": ""}
        n = state["n"]
        situation = _situation(ctx, state)
        decision = await triage(situation, ctx.model, run_dir=ctx.run.path, budget=ctx.budget)
        updates: dict[str, Any] = {
            "move": decision.move,
            "decisions": [*state.get("decisions", []), decision.model_dump(mode="json")],
        }
        if decision.source == "model" or decision.rejected:
            updates["agents"] = _used(state, "triage", decision.steps, decision.tokens_in, decision.tokens_out, decision.cost_usd)
        if decision.rejected:
            ctx.event("strategy", decision.rejected)
        if decision.source == "model":
            ctx.event("strategy", f"Triage: {MOVE_LABELS[decision.move]}. {decision.reason}")
        elif decision.move != "repair_same_session":
            ctx.event("strategy", decision.reason)

        if decision.move == "stop":
            result = ctx.result(n)
            only_unverified = result is not None and result.decision.refuted == 0 and result.decision.outcome == "needs_action"
            updates.update(
                terminal="needs_human" if only_unverified or state.get("app_error") else "failed_checks",
                reason=f"Stopped after attempt {n}: {decision.reason}",
            )
        elif decision.move == "rollback_and_retry":
            best = state.get("best")
            snapshots = state.get("snapshots", {})
            if best is not None and str(best) in snapshots:  # legal_moves guarantees it; a missing snapshot must not crash a run
                ctx.shadow.restore(snapshots[str(best)])
                attempts = _attempts(state)
                attempts[-1].reverted_to = best
                attempts[-1].note = f"No better than attempt {best}; Triage went back to it."
                ctx.event("revert", attempts[-1].note)
                _restart_if_dependencies_changed(ctx, snapshots[str(n)], snapshots[str(best)])
                updates.update(attempts=_dump(attempts), current=snapshots[str(best)], reverted_from=best)
        if decision.move in ("fresh_approach", "rollback_and_retry"):
            updates["fresh"] = True
        elif decision.move == "repair_same_session":
            updates["fresh"] = False
        return updates

    # -- ask_user: the run waits for a person ---------------------------------------------------

    async def ask_user(state: LoopState) -> dict[str, Any]:
        n = state["n"]
        decisions = state.get("decisions", [])
        result = ctx.result(n)
        answer = interrupt(
            {
                "kind": "ask",
                "attempt": n,
                "question": decisions[-1]["reason"] if decisions else "",
                "failing": sorted({sig_label(s) for s in signatures(result)}) if result is not None else [],
            }
        )
        answer = answer if isinstance(answer, dict) else {}
        asked = state.get("asked", 0) + 1
        typed = str(answer.get("correction") or "").strip()
        if typed and ctx.model is not None:
            return {"correction": typed, "asked": asked}
        if answer.get("stop"):
            return {"asked": asked, "terminal": "needs_human", "reason": f"Stopped at your request after attempt {n}."}
        # The person answered; how the repair continues is the rules' call (they were just asked once).
        repeated = state.get("repeats", {}).get(str(n), [])
        fresh = bool(repeated) or state.get("reverted_from") is not None or not state.get("session_id")
        return {"asked": asked, "answer": str(answer.get("answer") or typed).strip(), "fresh": fresh}

    # -- diagnose: write the repair prompt ---------------------------------------------------------

    async def diagnose_node(state: LoopState) -> dict[str, Any]:
        n = state["n"]
        contract = _contract(ctx)
        result = ctx.result(n)
        assert result is not None
        best, reverted_from = state.get("best"), state.get("reverted_from")
        # After a revert the files are the best attempt's, so its failures are the ones to fix.
        shown = (ctx.result(best) if reverted_from is not None else None) or result
        app_error = state.get("app_error")
        prompt = repair_prompt(
            contract,
            shown,
            repeated=state.get("repeats", {}).get(str(n), []),
            reverted_from=reverted_from,
            app_error=app_error,
            fresh_session=state.get("fresh", False),
            others=ctx.others,
        )
        updates: dict[str, Any] = {}
        failures = _failures(shown)
        if ctx.model is not None and failures and not app_error and not (ctx.budget is not None and ctx.budget.exhausted()):
            ctx.event("phase-quiet", "Reading the code for the cause")
            found = await diagnose(
                failures,
                ctx.model,
                ctx.project,
                intent=contract.goal,
                diff=ctx.shadow.diff(state["snapshots"]["0"], state["current"], max_chars=_DIFF_CHARS),
                server_log=shown.server_log_tail,
                run_dir=ctx.run.path,
                budget=ctx.budget,
            )
            updates["agents"] = _used(state, "diagnoser", found.steps, found.tokens_in, found.tokens_out, found.cost_usd)
            section = brief_section(found.brief)
            if section:
                prompt += "\n\n" + section
        answer = (state.get("answer") or "").strip()
        if answer:
            prompt += "\n\nThe person you are working for was asked about these failures and answered:\n" + answer
        updates.update(prompt=prompt, answer="")
        return updates

    # -- finalize: leave the best state, and say what happened ------------------------------------

    async def finalize(state: LoopState) -> dict[str, Any]:
        snapshots = state.get("snapshots", {})
        baseline = snapshots["0"]
        attempts = _attempts(state)
        best = state.get("best")
        final_n = attempts[-1].n if attempts else 0
        # The one outcome nobody may assert: it is recomputed from the checks that were replayed.
        # The attempt that must have passed: the last one, or the one that stands after a review's repair was undone.
        accepted = state.get("accepted")
        proven = accepted if accepted is not None and accepted == best else (best if best == final_n else None)
        terminal, reason = settle(state.get("terminal") or "", state.get("reason") or "", _gate(ctx, proven))

        # Leave the project in the best state that was reached, and never worse than it was found.
        if terminal == "tampered":
            ctx.shadow.restore(snapshots[str(best if best is not None else 0)])
        elif terminal != "succeeded" and best is not None and (best != final_n or state.get("current") != snapshots[str(best)]):
            ctx.shadow.restore(snapshots[str(best)])
            if best != final_n:
                ctx.event("revert", f"Restored attempt {best}, the best one reached.")
        elif terminal != "succeeded" and best is None and final_n > 0:
            ctx.shadow.restore(baseline)
            ctx.event("revert", "No attempt produced a working app; restored the project as it was.")
        if ctx.pending_correction:
            ctx.event("strategy", "The run ended before the correction could be applied.")

        end = snapshots.get(str(best), baseline) if best is not None else ctx.shadow.snapshot()
        outcome = _outcome(ctx, state, attempts)
        outcome.terminal, outcome.reason = terminal, reason  # type: ignore[assignment]
        outcome.best_attempt = best
        outcome.final = ctx.result(best) if best is not None else ctx.result(final_n)
        outcome.diff = ctx.shadow.diff(baseline, end)
        outcome.changed_files = ctx.shadow.changed_paths(baseline, end)
        outcome.duration_seconds = ctx.elapsed()
        write_run_evidence(ctx.project, outcome, ctx.run)
        ctx.outcome = outcome
        return {"terminal": terminal, "reason": reason, "elapsed": outcome.duration_seconds}

    nodes: dict[str, Node] = {
        "intent": intent,
        "approve": approve,
        "coder_turn": coder_turn,
        "guard_snapshot": guard_snapshot,
        "ensure_app": ensure_app,
        "test": test,
        "score": score_attempt,
        "review": review_node,
        "triage": triage_node,
        "ask_user": ask_user,
        "diagnose": diagnose_node,
        "finalize": finalize,
    }
    return {name: _mirrored(ctx, node) for name, node in nodes.items()}


def _mirrored(ctx: RunContext, node: Node) -> Node:
    """Keep a copy of the state as each node leaves it: a stopped run is reported from that copy."""

    async def run(state: LoopState) -> dict[str, Any]:
        ctx.mirror = dict(state)
        updates = await node(state)
        ctx.mirror.update(updates)
        return updates

    run.__name__ = node.__name__
    return run


# -- helpers ----------------------------------------------------------------------------------------------


def _start_app(ctx: RunContext, changed: list[str]) -> str | None:
    """Start the app, or refresh it for the files that changed. Returns why it did not start, or None."""
    try:
        if ctx.app is None:
            ctx.app = ctx.stack.enter_context(
                open_app(
                    ctx.project,
                    ctx.url,
                    repo_context=ctx.repo,
                    log_path=ctx.run.server_log,
                    on_status=lambda m: ctx.event("app", m),
                )
            )
        elif ctx.app.server is not None and DEPENDENCY_FILES & {Path(p).name for p in changed}:
            ctx.event("app", "Dependencies changed; reinstalling and restarting the dev server")
            ctx.app.url = ctx.app.server.restart(install=True)
        else:
            ctx.app.ensure_running()
    except AppStartError as exc:
        ctx.event("app", f"The app did not start: {exc}")
        return f"{exc}\n{exc.log_tail}".strip()
    except Exception as exc:  # restart failures (DevServerError) carry the install/server log
        ctx.event("app", f"The app did not restart: {exc}")
        return f"{exc}\n{getattr(exc, 'log_tail', '')}".strip()
    return None


async def _ui_snapshot(ctx: RunContext) -> str:
    """What the app shows now: its roles, labels, placeholders and test ids. Empty when it does not run yet.

    Checks drafted without it invent names, and a coding agent told to make them pass renames the app to
    fit. With it, the checks use the names that are there.
    """
    if _start_app(ctx, []) is not None or ctx.app is None:
        ctx.event("app", "Nothing runs yet, so the checks are drafted from the goal alone.")
        return ""
    try:
        seen = await VerificationSession(ctx.project, ctx.run).observe(ctx.app)
    except Exception as exc:  # a page that will not load must not stop the drafting
        ctx.event("app", f"The app could not be read before drafting: {exc}")
        return ""
    return seen.ui_snapshot


def _stored_contract(ctx: RunContext, contract_id: str) -> Contract | None:
    """The contract as the project has it; or, when it was handed to the run and never saved there, that one.

    The classic engine takes a contract as an object and never reads it back. A caller that keeps its
    contracts elsewhere (the benchmark does) must get the same from this engine.
    """
    if contract_id and ctx.store.exists(contract_id):
        return ctx.store.load(contract_id)
    if ctx.contract is not None and ctx.contract.id == contract_id:
        return ctx.contract
    return None


def _contract(ctx: RunContext) -> Contract:
    if ctx.contract is None:
        raise RuntimeError("the run has no approved contract")  # routing makes this unreachable
    return ctx.contract


def _job_prompt(ctx: RunContext, contract: Contract, state: LoopState, correction: str) -> str:
    """The whole job: for a first turn, or restated after a correction changed it in the middle of a run."""
    if state.get("n", 0) > 0:
        return restated_prompt(contract, ctx.others, correction or "The checks changed.")
    prompt = implement_prompt(contract, ctx.repo, ctx.others)
    if correction:
        prompt += f"\n\nA correction from the person you are working for:\n{correction.strip()}"
    return prompt


def _contracts(ctx: RunContext) -> list[Contract]:
    return [_contract(ctx), *ctx.others]


def _attempts(state: LoopState) -> list[Attempt]:
    return [Attempt.model_validate(a) for a in state.get("attempts", [])]


def _dump(attempts: list[Attempt]) -> list[dict[str, Any]]:
    return [a.model_dump(mode="json") for a in attempts]


def _used(state: LoopState, agent: str, steps: int, tokens_in: int, tokens_out: int, cost: float | None) -> list[dict[str, Any]]:
    """The usage list with one agent's call added to its row."""
    rows = [AgentUsage.model_validate(row) for row in state.get("agents", [])]
    row = next((r for r in rows if r.agent == agent), None)
    if row is None:
        row = AgentUsage(agent=agent)
        rows.append(row)
    row.steps += steps
    row.tokens_in += tokens_in
    row.tokens_out += tokens_out
    if cost is not None:
        row.cost_usd = (row.cost_usd or 0.0) + cost
    return [r.model_dump(mode="json") for r in rows]


def _saved_checks(contract: Contract) -> list[SavedCheck]:
    return [SavedCheck(id=c.id, description=c.description, check=c.check) for c in contract.criteria if c.check is not None]


def _criteria(checks: list[SavedCheck], existing: Contract | None) -> list[AcceptanceCriterion]:
    """The Intent agent's checks as criteria. A criterion that did not change is kept exactly as it was approved."""
    old = {c.id: c for c in existing.criteria} if existing is not None else {}
    criteria: list[AcceptanceCriterion] = []
    for check in checks:
        before = old.get(check.id)
        if before is not None and before.check == check.check and before.description == check.description:
            criteria.append(before)
        else:
            criteria.append(
                AcceptanceCriterion(id=check.id, description=check.description, verification_method="interactive_test", check=check.check)
            )
    # Criteria a person judges have no check, so the Intent agent never saw them: they stay.
    criteria += [c for c in old.values() if c.check is None]
    return criteria


def _situation(ctx: RunContext, state: LoopState) -> Situation:
    n = state["n"]
    repeats = state.get("repeats", {})
    views = [
        AttemptView(
            n=a.n,
            outcome=a.outcome,
            score=a.score,
            verified=a.verified,
            refuted=a.refuted,
            unverified=a.unverified,
            failing=sorted({sig_label(s) for s in a.signatures}),
            repeated=repeats.get(str(a.n), []),
            reverted_to=a.reverted_to,
        )
        for a in _attempts(state)
    ]
    budget = ctx.settings.budget_usd
    result = ctx.result(n)
    findings = (state.get("app_error") or "") or (failure_report(result) if result is not None else "")
    return Situation(
        attempts=views,
        rounds_left=ctx.settings.max_repair_rounds - (n - 1),
        budget_left_usd=None if budget is None else budget - state.get("cost_usd", 0.0),
        best_attempt=state.get("best"),
        has_session=bool(state.get("session_id")),
        can_ask=ctx.can_ask,
        asked=state.get("asked", 0),
        findings=findings,
    )


def _failures(result: RunResult) -> list[Failure]:
    """The checks that were run and did not hold, in the shape the Diagnoser reads."""
    failures: list[Failure] = []
    for outcome in result.contracts:
        checks = {c.id: c for c in outcome.contract.criteria}
        for r in outcome.verification.criteria_results if outcome.verification else []:
            criterion = checks.get(r.criterion_id)
            if not r.proven or r.verdict == "verified" or r.check_result is None or criterion is None or criterion.check is None:
                continue
            failures.append(Failure(title=criterion.description, check=criterion.check, result=r.check_result))
    return failures


def _gate(ctx: RunContext, n: int | None) -> GateDecision | None:
    """The gate's decision on attempt ``n``, computed again from the verdicts that were recorded."""
    result = ctx.result(n)
    if result is None:
        return None
    again = decide(result.contracts, require_approval=result.require_approval, judged_policy=ctx.settings.judged_policy)
    return again if result.decision.outcome == "pass" else result.decision


def _restart_if_dependencies_changed(ctx: RunContext, a: str, b: str) -> None:
    app = ctx.app
    if app is None or app.server is None:
        return
    if DEPENDENCY_FILES & {Path(p).name for p in ctx.shadow.changed_paths(a, b)}:
        try:
            app.url = app.server.restart(install=True)
        except Exception as exc:  # the next attempt restarts it and reports the failure
            ctx.event("app", f"The app did not restart after the revert: {exc}")


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
    )


def stopped_outcome(ctx: RunContext) -> RunOutcome:
    """A run that was stopped: keep the unfinished work as a snapshot, put back a state that was proven or found."""
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
    (ctx.run.path / STOPPED_FILE).write_text(unfinished, encoding="utf-8")
    if ctx.shadow.changed_paths(target, unfinished):
        ctx.shadow.restore(target)
        kept = f" The unfinished work is kept: `contexer restore {ctx.run.run_id} --stopped` brings it back."
    outcome = _outcome(ctx, state, scored)
    outcome.terminal = "cancelled"
    outcome.reason = (
        f"Stopped before the run ended; left {put_back}.{kept} `contexer run --resume {ctx.run.run_id}` continues it."
    )
    outcome.best_attempt = best
    outcome.final = ctx.result(best)
    outcome.diff = ctx.shadow.diff(snapshots["0"], target)
    outcome.changed_files = ctx.shadow.changed_paths(snapshots["0"], target)
    outcome.duration_seconds = ctx.elapsed()
    write_run_evidence(ctx.project, outcome, ctx.run)
    ctx.outcome = outcome
    return outcome
