"""What a run's state and results say: read-only questions the nodes ask.

Nothing here starts anything, writes anything or asks a model. Each function takes the state (or a
result) and answers from it, so the nodes stay about what happens next and these stay easy to test.
"""

from __future__ import annotations

from typing import Any

from contexer.contract import Contract
from contexer.controller.models import Attempt
from contexer.controller.shared import sig_label, signatures
from contexer.crew.diagnoser import Failure, Tried
from contexer.evidence.test_report import AgentUsage
from contexer.gate.models import RunResult
from contexer.graph.context import RunContext
from contexer.graph.state import LoopState
from contexer.intent.store import SavedCheck
from contexer.verification.models import AcceptanceCriterion


def _attempts(state: LoopState) -> list[Attempt]:
    return [Attempt.model_validate(a) for a in state.get("attempts", [])]


def _dump(attempts: list[Attempt]) -> list[dict[str, Any]]:
    return [a.model_dump(mode="json") for a in attempts]


def _check_rows(result: RunResult, contract_id: str) -> list[dict[str, Any]]:
    """This run's own checks with their verdicts and what the browser saw, in the contract's order."""
    rows: list[dict[str, Any]] = []
    for outcome in result.contracts:
        if outcome.contract.id != contract_id or outcome.verification is None:
            continue
        for r in outcome.verification.criteria_results:
            rows.append({"id": r.criterion_id, "verdict": r.verdict, "evidence": " ".join(r.evidence.split())[:300]})
    return rows


def _others_failing(result: RunResult, contract_id: str) -> int:
    """How many checks of earlier approved contracts did not hold: what this change broke elsewhere.

    A check that was already failing before the run is not among them; the verdict counts those apart.
    """
    stale = set(result.decision.stale)
    return sum(
        1
        for outcome in result.contracts
        if outcome.contract.id != contract_id and outcome.verification is not None
        for r in outcome.verification.criteria_results
        if r.verdict != "verified" and f"{outcome.contract.id}/{r.criterion_id}" not in stale
    )


def _stale(ctx: RunContext, state: LoopState) -> set[str]:
    """The earlier checks that already failed before the first turn. Never a check of the contract being built."""
    own = f"{ctx.contract.id}/" if ctx.contract is not None else ""
    failing = (state.get("baseline") or {}).get("failing", [])
    return {label for label in failing if not (own and label.startswith(own))}


def _regressions(state: LoopState, result: RunResult) -> dict[str, int]:
    """The earlier checks that passed before the first turn and fail in ``result`` -> the attempt that broke each."""
    passed = set((state.get("baseline") or {}).get("passed", []))
    broken = sorted({sig_label(s) for s in signatures(result)} & passed)
    attempts = _attempts(state)
    return {label: _broken_in(label, attempts) for label in broken} if attempts else {}


def _broken_in(label: str, attempts: list[Attempt]) -> int:
    """The attempt that broke a check which fails in the latest one, with the project as found as attempt 0.

    Walks back through the attempts the files came from (the one before, or the one they were put back
    to), as ``_tried`` does, to the first that began from files where the check passed. An attempt
    where no check ran did not show it passing, so the walk goes on through it.
    """
    by_n = {a.n: a for a in attempts}
    n = attempts[-1].n
    while True:
        before = by_n.get(n - 1)
        if before is None:
            return n  # it began from the project as found, where the check passed
        base = by_n.get(before.reverted_to, before) if before.reverted_to is not None else before
        if base.outcome != "error" and label not in {sig_label(s) for s in base.signatures}:
            return n
        n = base.n


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


def _failures(result: RunResult) -> list[Failure]:
    """The checks that were run and did not hold, in the shape the Diagnoser reads."""
    failures: list[Failure] = []
    stale = set(result.decision.stale)  # already failing before the run: not this change's to repair
    for outcome in result.contracts:
        checks = {c.id: c for c in outcome.contract.criteria}
        for r in outcome.verification.criteria_results if outcome.verification else []:
            criterion = checks.get(r.criterion_id)
            if not r.proven or r.verdict == "verified" or r.check_result is None or criterion is None or criterion.check is None:
                continue
            if f"{outcome.contract.id}/{r.criterion_id}" in stale:
                continue
            failures.append(Failure(title=criterion.description, check=criterion.check, result=r.check_result))
    return failures


def _tried(state: LoopState) -> list[Tried]:
    """Each lead the Diagnoser already gave in this run, with what the attempt that worked from it did."""
    attempts = {a.n: a for a in _attempts(state)}
    tried: list[Tried] = []
    for key, lead in sorted(state.get("leads", {}).items(), key=lambda item: int(item[0])):
        before, after = attempts.get(int(key)), attempts.get(int(key) + 1)
        if before is None or after is None:
            continue
        # The attempt began from the files of the one before it, or of the one those were put back to.
        base = attempts.get(before.reverted_to, before) if before.reverted_to is not None else before
        was, now = {sig_label(s) for s in base.signatures}, {sig_label(s) for s in after.signatures}
        tried.append(
            Tried(
                attempt=after.n,
                cause=lead.get("cause", ""),
                instruction=lead.get("instruction", ""),
                changed_files=after.changed_files,
                fixed=sorted(was - now),
                broke=sorted(now - was),
                still_failing=sorted(was & now),
                no_check_ran=after.outcome == "error",
                undone_to=after.reverted_to,
            )
        )
    return tried


def _crew_cost(state: LoopState) -> float | None:
    """The sum of what each of Contexer's agents cost, or None when no call has a known cost."""
    costs = [row.get("cost_usd") for row in state.get("agents", [])]
    known = [c for c in costs if c is not None]
    return sum(known) if known else None
