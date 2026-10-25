"""One verification pass: observe the running app, run each contract, decide."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional, Union

from contexer import __version__
from contexer.appserver import RunningApp
from contexer.config.project import AuthSettings, ProjectConfigError, load_project_config
from contexer.contract.models import Contract, utc_now
from contexer.evidence.rundir import RunDir
from contexer.gate.decision import decide
from contexer.gate.models import ContractOutcome, GateDecision, JudgedPolicy, RunResult
from contexer.observer.browser import browser_problem
from contexer.observer.models import BrowserObservation
from contexer.observer.playwright import PlaywrightObserver
from contexer.verification.runner import SignInError
from contexer.verification.verifier import Verifier
from contexer.workflow.criteria import GoalAnalyzer
from contexer.workflow.inspector import RepositoryContext


class _FromProject:
    """Sentinel: read [auth] from the project's contexer.toml."""


FROM_PROJECT = _FromProject()


class VerificationSession:
    """Verifies a running app against contracts and records the evidence.

    If the project configures ``[auth]``, the session signs in once (lazily)
    and every observation and check runs with that signed-in browser state,
    unless a check says ``"login": false``. Secrets referenced as ``${NAME}``
    come from the environment or the project's ``.env``.
    """

    def __init__(
        self,
        project_dir: str | Path,
        run: RunDir,
        verifier: Optional[Verifier] = None,
        observer: Optional[PlaywrightObserver] = None,
        auth: Union[Optional[AuthSettings], _FromProject] = FROM_PROJECT,
    ) -> None:
        self.project_dir = Path(project_dir).resolve()
        self.run = run
        # No LLM by default: approved contracts replay without a model.
        self.verifier = verifier or Verifier(llm_provider=None)
        self.observer = observer or PlaywrightObserver()
        self.auth: Optional[AuthSettings] = _project_auth(self.project_dir) if isinstance(auth, _FromProject) else auth
        _load_project_env(self.project_dir)
        self._started = time.monotonic()
        self._started_at = utc_now()
        self.load: Optional[BrowserObservation] = None
        self.sign_in_error: Optional[str] = None
        self._signed_in_state: Optional[dict[str, Any]] = None

    async def signed_in_state(self, app: RunningApp) -> Optional[dict[str, Any]]:
        """Sign in once per session; None when there is no [auth] or it failed."""
        if self.auth is None or self.sign_in_error is not None:
            return None
        if self._signed_in_state is None:
            try:
                self._signed_in_state = await self.verifier.runner.sign_in(
                    app.url, self.auth.url, self.auth.as_check(), screenshot=self.run.path / "sign-in.jpg"
                )
            except SignInError as exc:
                self.sign_in_error = str(exc)
                return None
        return self._signed_in_state

    async def observe(self, app: RunningApp) -> BrowserObservation:
        """Load the app once (signed in, if configured): reachability, page errors, UI vocabulary."""
        state = await self.signed_in_state(app)
        kwargs: dict[str, Any] = {"screenshot": True, "screenshot_dir": self.run.path}
        if state is not None:
            kwargs["storage_state"] = state
        self.load = await self.observer.observe(app.url, **kwargs)
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
            app_error = browser_problem(load.error) or f"Application unreachable at {app.url}: {load.error}"
        elif self.sign_in_error is not None:
            app_error = (
                f"Could not sign in with the [auth] flow in contexer.toml: {self.sign_in_error}. "
                "Check the test credentials and the [auth] steps"
            )
            if (self.run.path / "sign-in.jpg").is_file():
                app_error += " (screenshot: sign-in.jpg in the run folder)"
            app_error += "."
        else:
            state = await self.signed_in_state(app)
            for contract in contracts:
                extra: dict[str, Any] = {"artifacts_dir": self.run.checks_dir(contract.id)}
                if state is not None:
                    extra["storage_state"] = state
                verification = await self.verifier.verify(
                    contract.goal,
                    load,
                    contract.to_analysis(),
                    app.repo_context,
                    **extra,
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


def _project_auth(project_dir: Path) -> Optional[AuthSettings]:
    try:
        return load_project_config(project_dir).auth
    except ProjectConfigError:
        return None  # the app runner reports an invalid contexer.toml


def _load_project_env(project_dir: Path) -> None:
    """Make the project's .env (test credentials) visible to ${NAME} placeholders."""
    env_file = project_dir / ".env"
    if env_file.is_file():
        from dotenv import load_dotenv

        load_dotenv(env_file, override=False)
