"""One verification pass: observe the running app, run each contract, decide."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from contexer import __version__
from contexer.appserver import RunningApp
from contexer.contract.models import Contract, utc_now
from contexer.evidence.rundir import RunDir
from contexer.gate.decision import decide
from contexer.gate.models import ContractOutcome, GateDecision, JudgedPolicy, RunResult
from contexer.observer.models import BrowserObservation
from contexer.observer.playwright import PlaywrightObserver
from contexer.verification.verifier import Verifier
from contexer.workflow.criteria import GoalAnalyzer
from contexer.workflow.inspector import RepositoryContext


class VerificationSession:
    """Verifies a running app against contracts and records the evidence."""

    def __init__(
        self,
        project_dir: str | Path,
        run: RunDir,
        verifier: Optional[Verifier] = None,
        observer: Optional[PlaywrightObserver] = None,
    ) -> None:
        self.project_dir = Path(project_dir).resolve()
        self.run = run
        # No LLM by default: approved contracts replay without a model.
        self.verifier = verifier or Verifier(llm_provider=None)
        self.observer = observer or PlaywrightObserver()
        self._started = time.monotonic()
        self._started_at = utc_now()
        self.load: Optional[BrowserObservation] = None

    async def observe(self, app: RunningApp) -> BrowserObservation:
        """Load the app once: reachability, page errors at load, and the UI vocabulary."""
        self.load = await self.observer.observe(app.url, screenshot=True, screenshot_dir=self.run.path)
        return self.load

    async def compile(
        self,
        goal: str,
        analyzer: GoalAnalyzer,
        contract_id: str,
        repo_context: Optional[RepositoryContext] = None,
    ) -> Contract:
        """Compile a goal into a draft contract grounded in the app's current UI."""
        ui = self.load.ui_snapshot if self.load and self.load.success else ""
        analysis = await analyzer.analyze(goal, repo_context, ui)
        return Contract.from_analysis(analysis, contract_id)

    async def verify(
        self,
        app: RunningApp,
        contracts: list[Contract],
        *,
        require_approval: bool = True,
        judged_policy: JudgedPolicy = "advisory",
    ) -> RunResult:
        load = self.load or await self.observe(app)
        outcomes: list[ContractOutcome] = []
        app_error: Optional[str] = None
        if not load.success:
            app_error = f"Application unreachable at {app.url}: {load.error}"
        else:
            for contract in contracts:
                verification = await self.verifier.verify(
                    contract.goal,
                    load,
                    contract.to_analysis(),
                    app.repo_context,
                    artifacts_dir=self.run.checks_dir(contract.id),
                )
                outcomes.append(ContractOutcome(contract=contract, verification=verification))

        decision = decide(
            outcomes,
            require_approval=require_approval,
            judged_policy=judged_policy,
            app_error=app_error,
        )
        return self.result(app, outcomes, decision, require_approval=require_approval)

    def result(
        self,
        app: Optional[RunningApp],
        outcomes: list[ContractOutcome],
        decision: GateDecision,
        *,
        require_approval: bool = True,
        error: Optional[str] = None,
    ) -> RunResult:
        return RunResult(
            run_id=self.run.run_id,
            project_dir=str(self.project_dir),
            app_url=app.url if app else "",
            started_at=self._started_at,
            duration_seconds=time.monotonic() - self._started,
            require_approval=require_approval,
            contracts=outcomes,
            decision=decision,
            load=self.load,
            server_log_tail=app.log_tail() if app else "",
            contexer_version=__version__,
            run_dir=str(self.run.path),
            error=error,
        )
