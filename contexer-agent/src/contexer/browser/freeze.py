"""Freeze a finding into a check, and replay it: no finding is shown unless code reproduced it.

A finding is the Tester's claim. ``freeze`` turns its recording into a
:class:`~contexer.verification.checks.Check`, and ``replay_findings`` runs
each check with :class:`CheckRunner` in a fresh browser context, the same way
an approved contract is proven:

* a ``bug`` is confirmed when its check is refuted: the steps ran and the
  expectation was observed to fail;
* a ``works`` finding is confirmed when its check passes;
* anything else is unconfirmed, with the reason: the check gave the other
  answer, a step could not act (which proves nothing about the app), or the
  replays did not agree with each other.

Confirmed checks become a draft contract a person can approve. The checks of
confirmed bugs fail today and pass once the bug is fixed, so they are the
acceptance checks for the fix.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel, Field

from contexer.contract import Contract
from contexer.contract.models import slugify
from contexer.crew.tester import Finding
from contexer.verification.checks import Check, CheckResult
from contexer.verification.models import AcceptanceCriterion
from contexer.verification.runner import CheckRunner

UNCONFIRMED_FILE = "unconfirmed.json"
# Each finding is replayed this many times; all replays must agree.
DEFAULT_REPEATS = 2


class Confirmed(BaseModel):
    """A finding that code reproduced."""

    finding: Finding
    check: Check
    criterion_id: str
    # What the replay saw, in the runner's words.
    evidence: str = ""
    screenshot: Optional[str] = None


class Unconfirmed(BaseModel):
    """A finding that did not reproduce. It is never shown as a result."""

    finding: Finding
    reason: str


class ReplayReport(BaseModel):
    bugs: list[Confirmed] = Field(default_factory=list)
    works: list[Confirmed] = Field(default_factory=list)
    unconfirmed: list[Unconfirmed] = Field(default_factory=list)


def freeze(finding: Finding) -> Check:
    """The finding's recording as a check: its steps, then its one expectation."""
    return Check(steps=list(finding.steps), expect=[finding.expectation], login=finding.login)


async def replay_findings(
    findings: list[Finding],
    url: str,
    *,
    runner: Optional[CheckRunner] = None,
    repeats: int = DEFAULT_REPEATS,
    storage_state: Optional[dict[str, Any]] = None,
    before_each: Optional[Callable[[], Awaitable[Optional[str]]]] = None,
    artifacts_dir: Optional[Path] = None,
    timeout_scale: float = 1.0,
) -> ReplayReport:
    """Replay every finding ``repeats`` times in fresh browser contexts and sort them by what happened."""
    report = ReplayReport()
    if not findings:
        return report
    ids = _criterion_ids(findings)
    checks = [(cid, freeze(finding)) for cid, finding in zip(ids, findings)]
    runner = runner or CheckRunner()
    rounds: list[list[CheckResult]] = []
    for _ in range(max(1, repeats)):
        rounds.append(
            await runner.run(
                url,
                checks,
                artifacts_dir=artifacts_dir,
                storage_state=storage_state,
                before_each=before_each,
                timeout_scale=timeout_scale,
            )
        )
    for index, (finding, (cid, check)) in enumerate(zip(findings, checks)):
        results = [round_[index] for round_ in rounds]
        verdicts = {_verdict(result) for result in results}
        last = results[-1]
        if len(verdicts) > 1:
            seen = ", ".join(_verdict(result) for result in results)
            report.unconfirmed.append(Unconfirmed(finding=finding, reason=f"not every replay agreed ({seen})"))
            continue
        verdict = verdicts.pop()
        confirmed = Confirmed(
            finding=finding, check=check, criterion_id=cid, evidence=last.summary(), screenshot=last.screenshot
        )
        if verdict == "could not run":
            report.unconfirmed.append(Unconfirmed(finding=finding, reason=f"the replay could not run: {last.summary()}"))
        elif finding.kind == "bug" and verdict == "failed":
            report.bugs.append(confirmed)
        elif finding.kind == "works" and verdict == "passed":
            report.works.append(confirmed)
        elif finding.kind == "bug":
            report.unconfirmed.append(
                Unconfirmed(finding=finding, reason="its check passed on replay, so the bug did not reproduce")
            )
        else:
            report.unconfirmed.append(
                Unconfirmed(finding=finding, reason=f"its check failed on replay: {last.summary()}")
            )
    return report


def draft_contract(intent: str, report: ReplayReport, contract_id: Optional[str] = None) -> Optional[Contract]:
    """The confirmed checks as a contract nobody has approved yet; None when nothing was confirmed."""
    confirmed = [*report.bugs, *report.works]
    if not confirmed:
        return None
    criteria = [
        AcceptanceCriterion(
            id=item.criterion_id,
            description=item.finding.title,
            verification_method="interactive_test",
            check=item.check,
        )
        for item in confirmed
    ]
    summary = f"Found by `contexer test`: {len(report.bugs)} failing today (bugs), {len(report.works)} passing."
    return Contract(
        id=contract_id or f"tested-{slugify(intent, max_words=4)}",
        goal=intent,
        summary=summary,
        criteria=criteria,
        source="llm",
    )


def write_unconfirmed(run_dir: Path, report: ReplayReport) -> Path:
    """Write the findings that did not reproduce, each with its reason, to ``unconfirmed.json``."""
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / UNCONFIRMED_FILE
    entries = [
        {
            "kind": item.finding.kind,
            "title": item.finding.title,
            "description": item.finding.description,
            "severity": item.finding.severity,
            "reason": item.reason,
            "check": freeze(item.finding).model_dump(mode="json", by_alias=True, exclude_none=True),
        }
        for item in report.unconfirmed
    ]
    path.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _verdict(result: CheckResult) -> str:
    if result.passed:
        return "passed"
    # A step that could not act, a failed reset or a browser problem observed nothing about the behaviour.
    if result.blocked or result.failed_step:
        return "could not run"
    return "failed"


def _criterion_ids(findings: list[Finding]) -> list[str]:
    ids: list[str] = []
    for finding in findings:
        base = slugify(finding.title)
        if base == "contract":
            base = "finding"
        candidate, n = base, 2
        while candidate in ids:
            candidate, n = f"{base}-{n}", n + 1
        ids.append(candidate)
    return ids
