"""What both engines share: scoring an attempt, failure signatures, the tamper guard, the evidence."""

from __future__ import annotations

import hashlib
from pathlib import Path

from contexer import __version__
from contexer.agents.base import AgentTurn
from contexer.config.project import CONFIG_FILE
from contexer.contract import Contract
from contexer.contract.store import CONTEXER_DIR, CONTRACTS_DIR
from contexer.controller.models import RunOutcome
from contexer.evidence.report import write_evidence
from contexer.evidence.rundir import RunDir
from contexer.gate.models import AgentRow, AgentRunSummary, AttemptRow, GateDecision, RunResult, TriageRow
from contexer.intent.store import INTENT_DIR

DEPENDENCY_FILES = {"package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock", "bun.lockb"}


def write_run_evidence(project: Path, outcome: RunOutcome, run: RunDir) -> None:
    """``run.json`` (the whole outcome) and a report for the state the run left behind."""
    summary = AgentRunSummary(
        agent=outcome.agent,
        terminal=outcome.terminal,
        reason=outcome.reason,
        best_attempt=outcome.best_attempt,
        cost_usd=outcome.cost_usd,
        diff=outcome.diff,
        engine=outcome.engine,
        triage=[
            TriageRow(attempt=d.attempt, move=d.move, reason=d.reason, source=d.source, rejected=d.rejected)
            for d in outcome.triage
        ],
        agents=[AgentRow(**usage.model_dump()) for usage in outcome.agents],
        intent_id=outcome.intent_id,
        corrections=list(outcome.corrections),
        attempts=[
            AttemptRow(
                n=a.n,
                kind=a.kind,
                fresh_session=a.fresh_session,
                agent_status=a.agent.status,
                agent_summary=a.agent.summary[:1500],
                agent_error=a.agent.error,
                changed_files=a.changed_files,
                outcome=a.outcome,
                verified=a.verified,
                refuted=a.refuted,
                unverified=a.unverified,
                note=a.note,
                duration_seconds=a.agent.duration_seconds,
                cost_usd=a.agent.cost_usd,
            )
            for a in outcome.attempts
        ],
    )
    if outcome.final is not None:
        report = outcome.final.model_copy(
            update={"run_id": run.run_id, "run_dir": str(run.path), "agent_run": summary}
        )
    else:
        decision = GateDecision(outcome="error", reasons=[outcome.reason or outcome.terminal])
        report = RunResult(
            run_id=run.run_id,
            project_dir=str(project),
            started_at=outcome.started_at,
            decision=decision,
            contracts=[],
            contexer_version=__version__,
            run_dir=str(run.path),
            error=outcome.reason,
            agent_run=summary,
        )
    report.duration_seconds = outcome.duration_seconds
    write_evidence(report, run)
    (run.path / "run.json").write_text(outcome.model_dump_json(indent=2, exclude={"final"}), encoding="utf-8")




class ContractGuard:
    """Keeps the files that say what "done" means, and puts them back if an agent edits them.

    Those are the contracts, the intent (the written goal, its corrections and its checks) and
    ``contexer.toml``. An agent that could rewrite the first two could make any work pass; one that
    could write ``contexer.toml`` could choose the command Contexer runs to start or reset the app.
    """

    def __init__(self, project: Path) -> None:
        self.base = project
        self.saved = self._read()

    def _read(self) -> dict[str, bytes]:
        files: dict[str, bytes] = {}
        for folder, pattern in ((CONTRACTS_DIR, "*.json"), (INTENT_DIR, "*")):
            root = self.base / CONTEXER_DIR / folder
            if root.is_dir():
                files.update(
                    {f"{CONTEXER_DIR}/{folder}/{p.name}": p.read_bytes() for p in sorted(root.glob(pattern)) if p.is_file()}
                )
        config = self.base / CONFIG_FILE
        if config.is_file():
            files[CONFIG_FILE] = config.read_bytes()
        return files

    def restore_if_changed(self) -> list[str]:
        current = self._read()
        touched = sorted(
            name for name in set(current) | set(self.saved) if current.get(name) != self.saved.get(name)
        )
        for name in touched:
            path = self.base / name
            if name in self.saved:
                path.write_bytes(self.saved[name])
            else:
                path.unlink(missing_ok=True)
        return touched


def score(result: RunResult, target_id: str) -> int:
    """Verified target checks, minus double for every broken regression check."""
    if result.decision.outcome == "error":
        return -(10**6)
    total = 0
    for outcome in result.contracts:
        is_target = outcome.contract.id == target_id
        for r in outcome.verification.criteria_results if outcome.verification else []:
            if not r.proven:
                continue
            if r.verdict == "verified":
                total += 1 if is_target else 0
            elif not is_target:
                total -= 2
    return total


def signatures(result: RunResult) -> set[str]:
    sigs: set[str] = set()
    for outcome in result.contracts:
        for r in outcome.verification.criteria_results if outcome.verification else []:
            if not r.proven or r.verdict == "verified":
                continue
            check = r.check_result
            evidence = ""
            if check is not None:
                evidence = "|".join(f"{o.description}={o.actual}" for o in check.outcomes if not o.passed)
                evidence += f"|{check.failed_step or ''}|{(check.page_errors or [''])[0]}"
            digest = hashlib.sha1(f"{r.verdict}|{evidence}".encode()).hexdigest()[:10]
            sigs.add(f"{outcome.contract.id}/{r.criterion_id}#{digest}")
    return sigs


def sig_label(signature: str) -> str:
    return signature.split("#", 1)[0]


def check_count(contracts: list[Contract]) -> int:
    return sum(1 for c in contracts for crit in c.criteria if crit.check)


def turn_line(turn: AgentTurn, changed: list[str]) -> str:
    cost = f", ${turn.cost_usd:.2f}" if turn.cost_usd else ""
    files = f"{len(changed)} file(s) changed" if changed else "no file changes"
    status = "done" if turn.ok else f"{turn.status}: {turn.error or ''}".strip()
    return f"Agent {status} — {files} ({turn.duration_seconds:.0f}s{cost})"
