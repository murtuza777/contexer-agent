"""Replaying approved contracts for an agent that asked, and saying what the browser saw.

Shared by the MCP server and the stop hook. Nothing here prints: both callers own their stdout.
"""

from __future__ import annotations

from pathlib import Path

from contexer.appserver import AppStartError, open_app
from contexer.contract import Contract
from contexer.evidence import RunDir, write_evidence
from contexer.gate import GateDecision, RunResult
from contexer.gate.session import VerificationSession
from contexer.verification.runner import CheckRunner
from contexer.verification.verifier import Verifier


async def replay(project: Path, contracts: list[Contract], runner: CheckRunner) -> RunResult:
    """Start the app, replay ``contracts`` with no model, write the evidence. The caller holds the run lock."""
    run = RunDir.create(project)
    session = VerificationSession(project, run, verifier=Verifier(llm_provider=None, runner=runner))
    try:
        with open_app(project, None, log_path=run.server_log) as app:
            await session.observe(app)
            result = await session.verify(app, contracts, require_approval=True, judged_policy="advisory")
    except AppStartError as exc:
        decision = GateDecision(outcome="error", reasons=[str(exc)])
        result = session.result(None, [], decision, require_approval=True, error=str(exc))
        result.server_log_tail = exc.log_tail
    write_evidence(result, run)
    return result


def verdict(result: RunResult, *, then: str) -> str:
    """What the agent reads: each check, and for a failing one what was expected and what the browser saw.

    ``then`` is what happens after a fix, in the caller's words ("call contexer_verify again").
    """
    decision = result.decision
    lines = [decision.headline()]
    failures: list[str] = []
    for held in result.contracts:
        for item in held.verification.criteria_results if held.verification is not None else []:
            line = f"- [{item.criterion_id}] {item.verdict}: {item.description}"
            if item.check_result is not None and item.check_result.flaky:
                line += " (flaky: it failed on the first replay and passed on the second)"
            lines.append(line)
            if not item.passed:
                failures.append(item.check_result.failure_report() if item.check_result is not None else f"[{item.criterion_id}] {item.evidence}")
        if held.error:
            failures.append(f"[{held.contract.id}] {held.error}")
    if decision.outcome == "pass":
        lines.append("Every approved check passed in the browser.")
    else:
        lines.append(f"Not done: fix what is below. {then} Do not edit the checks.")
        lines.extend(reason for reason in decision.reasons if reason not in lines)
        if failures:
            lines.append("\nWhat the browser saw:")
            lines.extend(failures)
        if result.server_log_tail:
            lines.append("\nThe end of the app's log:\n" + result.server_log_tail[-2000:])
    if result.run_dir:
        lines.append(f"\nEvidence: {Path(result.run_dir) / 'report.html'}")
    return "\n".join(lines)
