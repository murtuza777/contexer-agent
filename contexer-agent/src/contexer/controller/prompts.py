"""What the coding agent is told: the contract up front, evidence on failure.

Prompts keep a stable prefix (rules, contract) and put per-attempt evidence
at the end, so a resumed session stays cache-friendly and the agent always
sees the same definition of done.
"""

from __future__ import annotations

from typing import Optional

from contexer.contract import Contract
from contexer.gate.models import RunResult
from contexer.verification.models import CriterionResult, VerificationResult, format_contract
from contexer.workflow.inspector import RepositoryContext

RULES = """\
Rules:
- Make the smallest complete change that satisfies every check. Use exactly the accessible names, visible texts,
  labels, placeholders and data-testid values the checks reference.
- Contexer starts and stops the app. Do not start, stop or restart a dev server yourself.
- Contexer runs the browser checks itself. Do not install Playwright or browsers, and do not write or run
  end-to-end tests for these checks: that only costs time.
- Do not modify anything under .contexer/ — the approved contract lives there and edits to it refute the run.
- Do not commit, push, or rewrite git history.
- The app must load and run without uncaught exceptions or console errors.
- When you are done, reply with a short summary of what you changed and why."""

_MAX_UI_LINES = 25
_MAX_LOG_LINES = 25


def implement_prompt(contract: Contract, repo: Optional[RepositoryContext], others: list[Contract]) -> str:
    parts = [
        "You are implementing a change in this repository. When you finish, Contexer starts the app and executes "
        "the acceptance checks below in a real browser. Those checks — not your own judgement — decide whether the "
        "work is done.",
        f"Goal: {contract.goal}",
        "Acceptance checks (the approved contract; each 'do:' step and 'expect:' line is executed verbatim):\n"
        + format_contract(contract.criteria),
    ]
    if others:
        parts.append(
            "These previously approved behaviours are re-checked too and must keep working:\n"
            + "\n".join(f"- {c.goal}" for c in others)
        )
    if repo is not None:
        parts.append("Project:\n" + repo.format_summary())
    parts.append(RULES)
    return "\n\n".join(parts)


def repair_prompt(
    contract: Contract,
    result: RunResult,
    *,
    repeated: list[str],
    reverted_from: Optional[int],
    app_error: Optional[str] = None,
    fresh_session: bool = False,
    others: Optional[list[Contract]] = None,
) -> str:
    parts: list[str] = []
    if fresh_session:
        # A fresh session has no memory of the earlier turns: restate the job.
        parts.append(implement_prompt(contract, None, others or []))
        parts.append("Earlier attempts did not pass. Here is what Contexer observed on the current code.")
    else:
        parts.append("Contexer started the app and executed the acceptance checks against your changes.")

    if app_error:
        parts.append(f"The app did not start, so no check could run:\n{app_error}")
    elif result.decision.outcome == "error":
        # The app started but nothing could be checked, e.g. the sign-in flow broke.
        parts.append("No check could run:\n" + "\n".join(result.decision.reasons))
    failing = _failing(result)
    if failing:
        parts.append(f"{len(failing)} check(s) did not pass:\n\n" + "\n\n".join(_bundle(cid, r) for cid, r in failing))
    passing = [r.criterion_id for o in result.contracts for r in _results(o.verification) if r.verdict == "verified"]
    if passing:
        parts.append("Already passing (keep them passing): " + ", ".join(passing))

    log = _log_excerpt(result.server_log_tail)
    if log:
        parts.append(f"Dev server log (last lines):\n{log}")
    if reverted_from is not None:
        parts.append(
            f"Your previous attempt made things worse than attempt {reverted_from}, so Contexer reverted the files "
            f"to attempt {reverted_from}. Take a different approach from that last attempt."
        )
    if repeated:
        parts.append(
            "These failed in exactly the same way after your last fix, so that fix did not address the cause: "
            + ", ".join(repeated)
            + ". Find the root cause before editing (read the relevant code and the evidence above)."
        )
    parts.append("Fix the causes. Do not weaken or work around the checks.")
    return "\n\n".join(parts)


def _results(verification: Optional[VerificationResult]) -> list[CriterionResult]:
    return verification.criteria_results if verification is not None else []


def _failing(result: RunResult) -> list[tuple[str, CriterionResult]]:
    out: list[tuple[str, CriterionResult]] = []
    for outcome in result.contracts:
        for r in _results(outcome.verification):
            if r.proven and r.verdict != "verified":
                out.append((outcome.contract.id, r))
    return out


def _bundle(contract_id: str, result: CriterionResult) -> str:
    lines = [f"[{contract_id}/{result.criterion_id}] {result.description} — {result.verdict.upper()}"]
    check = result.check_result
    if check is None:
        lines.append(f"  {result.evidence}")
        return "\n".join(lines)
    if check.failed_step:
        lines.append(f"  could not perform {check.failed_step}")
    for o in check.outcomes:
        if not o.passed:
            lines.append(f"  expected: {o.description}")
            lines.append(f"  actual:   {o.actual}")
    for err in check.page_errors[:3]:
        lines.append(f"  uncaught exception: {err}")
    for err in check.console_errors[:3]:
        lines.append(f"  console: {err}")
    if check.ui_at_failure and check.blocked:
        lines.append("  the page offered instead:")
        lines.extend(f"    {line}" for line in check.ui_at_failure.splitlines()[:_MAX_UI_LINES])
    return "\n".join(lines)


def _log_excerpt(tail: str) -> str:
    lines = [line for line in tail.splitlines() if line.strip()]
    return "\n".join(lines[-_MAX_LOG_LINES:])
