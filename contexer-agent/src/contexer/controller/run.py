"""The run controller: implement → prove → repair, bounded and reversible.

Deterministic code owns every decision here; the coding agent is called for
exactly two things, implementing and repairing. Per attempt:

1. the agent edits files (its self-report is recorded, never trusted);
2. Contexer snapshots the files and checks the approved contracts were not
   touched (tampering refutes the run and the contracts are put back);
3. Contexer starts or refreshes the app and executes every check — the
   target contract plus all other approved contracts, as regression replay;
4. the attempt is scored; a worse attempt is reverted to the best one;
5. a failure that survives a repair unchanged switches to a fresh agent
   session focused on that failure, instead of retrying the same idea.

The run ends at the first passing attempt, or after ``max_repair_rounds``
with the best attempt restored, or when the budget or wall clock runs out.
"""

from __future__ import annotations

import hashlib
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Callable, Literal, Optional

from pydantic import BaseModel, Field

from contexer import __version__
from contexer.agents.base import AgentTurn, CodingAgentAdapter
from contexer.appserver import AppStartError, RunningApp, open_app
from contexer.checkpoint import ShadowRepo
from contexer.contract import Contract
from contexer.contract.models import utc_now
from contexer.contract.store import CONTEXER_DIR, CONTRACTS_DIR
from contexer.controller.prompts import implement_prompt, repair_prompt
from contexer.evidence.rundir import RunDir
from contexer.evidence.report import write_evidence
from contexer.gate.models import AgentRunSummary, AttemptRow, GateDecision, JudgedPolicy, RunResult
from contexer.gate.session import VerificationSession
from contexer.verification.runner import CheckRunner
from contexer.verification.verifier import Verifier
from contexer.workflow.inspector import RepositoryInspector

TerminalState = Literal[
    "succeeded",
    "failed_checks",
    "needs_human",
    "budget_exhausted",
    "timed_out",
    "tampered",
    "agent_error",
    "app_error",
]

_DEPENDENCY_FILES = {"package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock", "bun.lockb"}

EventFn = Callable[[str, str], None]  # (kind, message)


class RunSettings(BaseModel):
    max_repair_rounds: int = 2
    budget_usd: Optional[float] = None
    turn_timeout: float = 900.0
    wall_clock: float = 3600.0
    judged_policy: JudgedPolicy = "advisory"
    replay_others: bool = True


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
    reverted_to: Optional[int] = None
    note: str = ""
    result_dir: str = ""


class RunOutcome(BaseModel):
    run_id: str
    contract_id: str
    agent: str
    terminal: TerminalState
    reason: str = ""
    attempts: list[Attempt] = Field(default_factory=list)
    best_attempt: Optional[int] = None
    final: Optional[RunResult] = None
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    started_at: str = ""
    diff: str = ""
    run_dir: str = ""
    contexer_version: str = __version__

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
        }[self.terminal]


class RunController:
    def __init__(
        self,
        project_dir: str | Path,
        agent: CodingAgentAdapter,
        settings: Optional[RunSettings] = None,
        *,
        url: Optional[str] = None,
        on_event: Optional[EventFn] = None,
        runner: Optional[CheckRunner] = None,
    ) -> None:
        self.project = Path(project_dir).resolve()
        self.agent = agent
        self.settings = settings or RunSettings()
        self.url = url
        self.on_event = on_event or (lambda _kind, _msg: None)
        self.runner = runner or CheckRunner(trace="on-failure")

    async def run(self, contract: Contract, others: Optional[list[Contract]] = None) -> RunOutcome:
        if contract.status != "approved":
            raise ValueError(f"contract '{contract.id}' must be approved before a run ({contract.status})")
        others = [c for c in (others or []) if c.id != contract.id and c.status == "approved"]
        if not self.settings.replay_others:
            others = []

        started = time.monotonic()
        run = RunDir.create(self.project)
        shadow = ShadowRepo(self.project)
        baseline = shadow.snapshot(f"{run.run_id}/0", "baseline")
        guard = _ContractGuard(self.project)
        repo = RepositoryInspector().inspect(self.project)

        outcome = RunOutcome(
            run_id=run.run_id,
            contract_id=contract.id,
            agent=self.agent.describe(),
            terminal="failed_checks",
            started_at=utc_now(),
            run_dir=str(run.path),
        )
        results: dict[int, RunResult] = {}
        snapshots: dict[int, str] = {0: baseline}
        best: Optional[int] = None
        best_score = -(10**9)
        session_id: Optional[str] = None
        prompt = implement_prompt(contract, repo, others)
        fresh = True
        last_signatures: set[str] = set()
        # What the work tree looked like when the agent started this attempt
        # (after any revert), so "changed files" means the agent's changes.
        current = baseline

        with ExitStack() as stack:
            app: Optional[RunningApp] = None
            for n in range(1, self.settings.max_repair_rounds + 2):
                if time.monotonic() - started > self.settings.wall_clock:
                    outcome.terminal, outcome.reason = "timed_out", "Wall-clock budget used up."
                    break
                remaining = None
                if self.settings.budget_usd is not None:
                    remaining = self.settings.budget_usd - outcome.cost_usd
                    if remaining <= 0:
                        outcome.terminal, outcome.reason = "budget_exhausted", "Spending budget used up."
                        break

                kind: Literal["implement", "repair"] = "implement" if n == 1 else "repair"
                self.on_event("phase", f"Attempt {n}: {'implementing' if kind == 'implement' else 'repairing'}"
                              f"{' (fresh session)' if fresh and n > 1 else ''} with {self.agent.describe()}")
                turn = await self.agent.run_turn(
                    self.project,
                    prompt,
                    session_id=None if fresh else session_id,
                    timeout=self.settings.turn_timeout,
                    budget_usd=remaining,
                    on_progress=lambda line: self.on_event("agent", line),
                )
                session_id = turn.session_id or session_id
                outcome.cost_usd += turn.cost_usd or 0.0

                tampered = guard.restore_if_changed()
                snapshots[n] = shadow.snapshot(f"{run.run_id}/{n}", f"attempt {n}")
                changed = shadow.changed_paths(current, snapshots[n])
                current = snapshots[n]
                attempt = Attempt(
                    n=n,
                    kind=kind,
                    fresh_session=fresh,
                    agent=turn,
                    snapshot=snapshots[n],
                    changed_files=changed,
                    outcome="error",
                    score=-(10**6),
                )
                outcome.attempts.append(attempt)
                self.on_event("agent-done", _turn_line(turn, changed))

                if tampered:
                    attempt.note = f"Agent modified approved contracts: {', '.join(tampered)} (restored)."
                    outcome.terminal, outcome.reason = "tampered", attempt.note
                    break
                if not turn.ok and not changed:
                    attempt.note = turn.error or turn.status
                    outcome.terminal = "budget_exhausted" if turn.status == "budget_exceeded" else "agent_error"
                    outcome.reason = f"The coding agent did not complete: {attempt.note}"
                    break

                # -- prove -------------------------------------------------------
                app_error: Optional[str] = None
                try:
                    if app is None:
                        app = stack.enter_context(
                            open_app(
                                self.project,
                                self.url,
                                repo_context=repo,
                                log_path=run.server_log,
                                on_status=lambda m: self.on_event("app", m),
                            )
                        )
                    elif app.server is not None and _DEPENDENCY_FILES & {Path(p).name for p in changed}:
                        self.on_event("app", "Dependencies changed; reinstalling and restarting the dev server")
                        app.url = app.server.restart(install=True)
                    else:
                        app.ensure_running()
                except AppStartError as exc:
                    app_error = f"{exc}\n{exc.log_tail}".strip()
                    self.on_event("app", f"The app did not start: {exc}")
                except Exception as exc:  # restart failures (DevServerError) carry the install/server log
                    app_error = f"{exc}\n{getattr(exc, 'log_tail', '')}".strip()
                    self.on_event("app", f"The app did not restart: {exc}")

                attempt_dir = RunDir(run_id=f"{run.run_id}/a{n}", path=run.path / f"attempt-{n}")
                attempt_dir.path.mkdir(parents=True, exist_ok=True)
                attempt.result_dir = str(attempt_dir.path)
                if app_error is None and app is not None:
                    self.on_event("phase", f"Attempt {n}: proving {_check_count([contract, *others])} checks in Chromium")
                    session = VerificationSession(
                        self.project, attempt_dir, verifier=Verifier(llm_provider=None, runner=self.runner)
                    )
                    result = await session.verify(app, [contract, *others], judged_policy=self.settings.judged_policy)
                else:
                    session = VerificationSession(self.project, attempt_dir)
                    decision = GateDecision(outcome="error", reasons=[f"App did not start: {app_error}"])
                    result = session.result(app, [], decision, error=app_error)
                    if not result.server_log_tail and app_error:
                        result.server_log_tail = app_error
                results[n] = result

                attempt.outcome = result.decision.outcome
                attempt.verified, attempt.refuted, attempt.unverified = (
                    result.decision.verified,
                    result.decision.refuted,
                    result.decision.unverified,
                )
                attempt.score = _score(result, contract.id)
                signatures = _signatures(result)
                attempt.signatures = sorted(signatures)
                self.on_event("verdict", f"Attempt {n}: {result.decision.headline()}")

                if result.decision.outcome == "pass":
                    best = n
                    outcome.terminal, outcome.reason = "succeeded", "Every check proven in the browser."
                    break

                reverted_from: Optional[int] = None
                usable = result.decision.outcome != "error"  # an app that does not start is never kept
                if usable and attempt.score > best_score:
                    best, best_score = n, attempt.score
                elif best is not None and attempt.score < best_score:
                    shadow.restore(snapshots[best])
                    attempt.reverted_to = best
                    reverted_from = best
                    attempt.note = f"Scored lower than attempt {best}; reverted to it."
                    self.on_event("revert", attempt.note)
                    if app is not None and app.server is not None and _DEPENDENCY_FILES & {
                        Path(p).name for p in shadow.changed_paths(snapshots[n], snapshots[best])
                    }:
                        try:
                            app.url = app.server.restart(install=True)
                        except Exception as exc:  # the next attempt restarts it and reports the failure
                            self.on_event("app", f"The app did not restart after the revert: {exc}")
                    current = snapshots[best]

                if n > self.settings.max_repair_rounds:
                    only_unverified = result.decision.refuted == 0 and result.decision.outcome == "needs_action"
                    outcome.terminal = "needs_human" if only_unverified or app_error else "failed_checks"
                    outcome.reason = (
                        f"Not all checks passed after {self.settings.max_repair_rounds} repair round(s). "
                        + "; ".join(result.decision.reasons[:3])
                    )
                    break

                repeated_sigs = signatures & last_signatures
                repeated = sorted({_sig_label(s) for s in repeated_sigs})
                fresh = bool(repeated_sigs) or reverted_from is not None
                if repeated:
                    self.on_event("strategy", f"Same failure again ({', '.join(repeated)}); next repair starts a fresh session")
                prompt = repair_prompt(
                    contract,
                    results[best] if reverted_from is not None and best is not None else result,
                    repeated=repeated,
                    reverted_from=reverted_from,
                    app_error=app_error,
                    fresh_session=fresh,
                    others=others,
                )
                last_signatures = signatures

        # Leave the project in the best state that was reached — and never in a
        # state worse than the one Contexer found: with no usable attempt, the
        # baseline comes back (each attempt stays in refs/contexer/<run>/<n>).
        final_n = outcome.attempts[-1].n if outcome.attempts else 0
        if outcome.terminal == "tampered":
            target = best if best is not None else 0
            shadow.restore(snapshots[target])
        elif outcome.terminal != "succeeded" and best is not None and best != final_n:
            shadow.restore(snapshots[best])
            self.on_event("revert", f"Restored attempt {best}, the best one reached.")
        elif outcome.terminal != "succeeded" and best is None and final_n > 0:
            shadow.restore(baseline)
            self.on_event("revert", "No attempt produced a working app; restored the project as it was.")
        outcome.best_attempt = best
        outcome.final = results.get(best) if best is not None else (results[final_n] if final_n in results else None)
        end_snapshot = snapshots.get(best, snapshots[0]) if best is not None else shadow.snapshot()
        outcome.diff = shadow.diff(baseline, end_snapshot)
        outcome.duration_seconds = time.monotonic() - started
        self._write_evidence(outcome, run, contract)
        return outcome

    def _write_evidence(self, outcome: RunOutcome, run: RunDir, contract: Contract) -> None:
        """``run.json`` (the whole outcome) and a report for the state the run left behind."""
        summary = AgentRunSummary(
            agent=outcome.agent,
            terminal=outcome.terminal,
            reason=outcome.reason,
            best_attempt=outcome.best_attempt,
            cost_usd=outcome.cost_usd,
            diff=outcome.diff,
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
                project_dir=str(self.project),
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


class _ContractGuard:
    """Hashes approved contract files and puts them back if an agent edits them."""

    def __init__(self, project: Path) -> None:
        self.root = project / CONTEXER_DIR / CONTRACTS_DIR
        self.saved = self._read()

    def _read(self) -> dict[str, bytes]:
        if not self.root.is_dir():
            return {}
        return {p.name: p.read_bytes() for p in sorted(self.root.glob("*.json"))}

    def restore_if_changed(self) -> list[str]:
        current = self._read()
        touched = sorted(
            name for name in set(current) | set(self.saved) if current.get(name) != self.saved.get(name)
        )
        for name in touched:
            path = self.root / name
            if name in self.saved:
                path.write_bytes(self.saved[name])
            else:
                path.unlink(missing_ok=True)
        return touched


def _score(result: RunResult, target_id: str) -> int:
    """Verified target checks, minus double for every broken regression check."""
    if result.decision.outcome == "error":
        return -(10**6)
    score = 0
    for outcome in result.contracts:
        is_target = outcome.contract.id == target_id
        for r in outcome.verification.criteria_results if outcome.verification else []:
            if not r.proven:
                continue
            if r.verdict == "verified":
                score += 1 if is_target else 0
            elif not is_target:
                score -= 2
    return score


def _signatures(result: RunResult) -> set[str]:
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


def _sig_label(signature: str) -> str:
    return signature.split("#", 1)[0]


def _check_count(contracts: list[Contract]) -> int:
    return sum(1 for c in contracts for crit in c.criteria if crit.check)


def _turn_line(turn: AgentTurn, changed: list[str]) -> str:
    cost = f", ${turn.cost_usd:.2f}" if turn.cost_usd else ""
    files = f"{len(changed)} file(s) changed" if changed else "no file changes"
    status = "done" if turn.ok else f"{turn.status}: {turn.error or ''}".strip()
    return f"Agent {status} — {files} ({turn.duration_seconds:.0f}s{cost})"
