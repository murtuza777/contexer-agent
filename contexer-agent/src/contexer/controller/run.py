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
Stopped with Ctrl+C, it kills the agent and puts back the best attempt (or
the project as it was), keeping the unfinished work as a snapshot.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from typing import Literal

from contexer.agents.base import CodingAgentAdapter
from contexer.appserver import AppStartError, RunningApp, open_app
from contexer.checkpoint import ShadowRepo
from contexer.contract import Contract
from contexer.contract.models import utc_now
from contexer.controller.models import Attempt, RunOutcome, RunSettings
from contexer.controller.prompts import implement_prompt, repair_prompt
from contexer.controller.shared import (
    DEPENDENCY_FILES,
    ContractGuard,
    check_count,
    score,
    sig_label,
    signatures,
    turn_line,
    write_run_evidence,
)
from contexer.evidence.rundir import RunDir
from contexer.gate.models import GateDecision, RunResult
from contexer.gate.session import VerificationSession
from contexer.verification.runner import CheckRunner
from contexer.verification.verifier import Verifier
from contexer.workflow.inspector import RepositoryInspector

EventFn = Callable[[str, str], None]  # (kind, message)


class RunController:
    def __init__(
        self,
        project_dir: str | Path,
        agent: CodingAgentAdapter,
        settings: RunSettings | None = None,
        *,
        url: str | None = None,
        on_event: EventFn | None = None,
        runner: CheckRunner | None = None,
    ) -> None:
        self.project = Path(project_dir).resolve()
        self.agent = agent
        self.settings = settings or RunSettings()
        self.url = url
        self.on_event = on_event or (lambda _kind, _msg: None)
        self.runner = runner or CheckRunner(trace="on-failure")
        # Set as soon as a run ends, also when Ctrl+C ends it with an exception.
        self.last_outcome: RunOutcome | None = None

    async def run(self, contract: Contract, others: list[Contract] | None = None) -> RunOutcome:
        if contract.status != "approved":
            raise ValueError(f"contract '{contract.id}' must be approved before a run ({contract.status})")
        others = [c for c in (others or []) if c.id != contract.id and c.status == "approved"]
        if not self.settings.replay_others:
            others = []

        started = time.monotonic()
        run = RunDir.create(self.project)
        shadow = ShadowRepo(self.project)
        baseline = shadow.snapshot(f"{run.run_id}/0", "baseline")
        guard = ContractGuard(self.project)
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
        best: int | None = None
        best_score = -(10**9)
        session_id: str | None = None
        prompt = implement_prompt(contract, repo, others)
        fresh = True
        last_signatures: set[str] = set()
        # What the work tree looked like when the agent started this attempt
        # (after any revert), so "changed files" means the agent's changes.
        current = baseline

        def on_exit(exc_type: type[BaseException] | None, _exc: object, _tb: object) -> bool:
            if exc_type is not None and issubclass(exc_type, (asyncio.CancelledError, KeyboardInterrupt)):
                # Registered first, so it runs after the app has stopped.
                self._stopped(outcome, run, contract, shadow, snapshots, best, results, started)
            return False

        with ExitStack() as stack:
            stack.push(on_exit)
            app: RunningApp | None = None
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
                self.on_event("agent-done", turn_line(turn, changed))

                if tampered:
                    attempt.note = f"Agent modified what defines done (contracts, intent or contexer.toml): {', '.join(tampered)} (restored)."
                    outcome.terminal, outcome.reason = "tampered", attempt.note
                    break
                if not turn.ok and not changed:
                    attempt.note = turn.error or turn.status
                    outcome.terminal = "budget_exhausted" if turn.status == "budget_exceeded" else "agent_error"
                    outcome.reason = f"The coding agent did not complete: {attempt.note}"
                    break

                # -- prove -------------------------------------------------------
                app_error: str | None = None
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
                    elif app.server is not None and DEPENDENCY_FILES & {Path(p).name for p in changed}:
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
                    self.on_event("phase", f"Attempt {n}: proving {check_count([contract, *others])} checks in Chromium")
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
                attempt.score = score(result, contract.id)
                sigs = signatures(result)
                attempt.signatures = sorted(sigs)
                self.on_event("verdict", f"Attempt {n}: {result.decision.headline()}")

                if result.decision.outcome == "pass":
                    best = n
                    outcome.terminal, outcome.reason = "succeeded", "Every check proven in the browser."
                    break

                reverted_from: int | None = None
                usable = result.decision.outcome != "error"  # an app that does not start is never kept
                if usable and attempt.score > best_score:
                    best, best_score = n, attempt.score
                elif best is not None and attempt.score < best_score:
                    shadow.restore(snapshots[best])
                    attempt.reverted_to = best
                    reverted_from = best
                    attempt.note = f"Scored lower than attempt {best}; reverted to it."
                    self.on_event("revert", attempt.note)
                    if app is not None and app.server is not None and DEPENDENCY_FILES & {
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

                repeated_sigs = sigs & last_signatures
                repeated = sorted({sig_label(s) for s in repeated_sigs})
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
                last_signatures = sigs

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
        outcome.changed_files = shadow.changed_paths(baseline, end_snapshot)
        outcome.duration_seconds = time.monotonic() - started
        write_run_evidence(self.project, outcome, run)
        self.last_outcome = outcome
        return outcome

    def _stopped(
        self,
        outcome: RunOutcome,
        run: RunDir,
        contract: Contract,
        shadow: ShadowRepo,
        snapshots: dict[int, str],
        best: int | None,
        results: dict[int, RunResult],
        started: float,
    ) -> None:
        """Ctrl+C: keep the unfinished work as a snapshot, then put back a state that was proven or found."""
        unfinished = shadow.snapshot(f"{run.run_id}/stopped", "stopped before the run ended")
        target = best if best is not None else 0
        put_back = "the best attempt reached" if best is not None else "the project as it was"
        kept = ""
        if shadow.changed_paths(snapshots[target], unfinished):
            shadow.restore(snapshots[target])
            kept = f" The unfinished work is kept: `contexer restore {run.run_id} --stopped` brings it back."
        outcome.terminal = "cancelled"
        outcome.reason = f"Stopped before the run ended; left {put_back}.{kept}"
        outcome.best_attempt = best
        outcome.final = results.get(best) if best is not None else None
        outcome.diff = shadow.diff(snapshots[0], snapshots[target])
        outcome.changed_files = shadow.changed_paths(snapshots[0], snapshots[target])
        outcome.duration_seconds = time.monotonic() - started
        write_run_evidence(self.project, outcome, run)
        self.last_outcome = outcome

