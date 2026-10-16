"""Turning verdicts into a gate outcome.

The rules are deliberately fail-safe:

* only checks executed in a browser (``proven``) can pass or fail the gate;
* anything that could not be decided blocks as ``needs_action``, never as a
  quiet pass;
* a contract that is a draft, or was edited after approval, is not trusted
  until a person approves it;
* LLM-judged criteria are advisory unless the policy says ``block``, because a
  noisy judge in a merge gate gets switched off.
"""

from __future__ import annotations

from typing import Optional

from contexer.gate.models import ContractOutcome, GateDecision, GateOutcome, JudgedPolicy

_SEVERITY: dict[GateOutcome, int] = {"pass": 0, "needs_action": 1, "fail": 2, "error": 3}


def decide(
    outcomes: list[ContractOutcome],
    *,
    require_approval: bool = True,
    judged_policy: JudgedPolicy = "advisory",
    app_error: Optional[str] = None,
) -> GateDecision:
    if app_error:
        return GateDecision(outcome="error", reasons=[app_error])
    if not outcomes:
        return GateDecision(outcome="needs_action", reasons=["No contracts to verify."])

    worst: GateOutcome = "pass"
    reasons: list[str] = []
    counts = {"verified": 0, "refuted": 0, "unverified": 0, "advisory": 0}

    def escalate(level: GateOutcome, reason: str) -> None:
        nonlocal worst
        reasons.append(reason)
        if _SEVERITY[level] > _SEVERITY[worst]:
            worst = level

    for outcome in outcomes:
        cid = outcome.contract.id
        if outcome.error:
            escalate("error", f"[{cid}] {outcome.error}")
            continue
        if require_approval and outcome.status == "draft":
            escalate("needs_action", f"[{cid}] is a draft; approve it with `contexer contract approve {cid}`.")
        elif require_approval and outcome.status == "modified":
            escalate("needs_action", f"[{cid}] changed after it was approved; review and re-approve it.")

        verification = outcome.verification
        if verification is None:
            escalate("error", f"[{cid}] was not verified.")
            continue
        if not verification.criteria_results:
            escalate("error", f"[{cid}] {verification.reason or 'produced no verdicts'}")
            continue

        gating = 0
        for result in verification.criteria_results:
            counts_toward_gate = result.proven or (judged_policy == "block" and result.method == "judgment")
            if not counts_toward_gate:
                counts["advisory"] += 1
                continue
            gating += 1
            verdict = result.verdict
            counts[verdict] += 1
            if verdict == "refuted":
                escalate("fail", f"[{cid}/{result.criterion_id}] {result.description}: {result.evidence}")
            elif verdict == "unverified":
                escalate(
                    "needs_action",
                    f"[{cid}/{result.criterion_id}] could not be checked: {result.evidence}",
                )
        if gating == 0:
            escalate("needs_action", f"[{cid}] has no executable checks, so nothing was proven.")

    return GateDecision(outcome=worst, reasons=reasons, **counts)
