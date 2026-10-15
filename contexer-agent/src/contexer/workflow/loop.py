"""Autonomous engineering loop: goal → criteria → plan → coding agent → browser verification → repair."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel

from contexer.llm.base import LLMProvider
from contexer.observer.models import BrowserObservation
from contexer.observer.playwright import PlaywrightObserver
from contexer.opencode.adapter import CodingAgent
from contexer.opencode.models import ExecutionStatus, OpenCodeDiffItem
from contexer.project.manager import ProjectManager
from contexer.project.models import Project
from contexer.repair.repair import RepairEngine
from contexer.verification.models import GoalAnalysis, VerificationResult, format_contract
from contexer.verification.verifier import Verifier
from contexer.appserver import AppStartError, open_app
from contexer.workflow.criteria import GoalAnalyzer
from contexer.workflow.inspector import RepositoryContext, RepositoryInspector
from contexer.workflow.planner import EngineeringPlan, EngineeringPlanner

logger = logging.getLogger(__name__)

_METHOD_TAGS = {
    "assertion": "[green]proven[/]",
    "judgment": "[yellow]LLM-judged[/]",
    "heuristic": "[yellow]heuristic[/]",
}


class AutonomousLoopResult(BaseModel):
    """Result of an autonomous loop run."""

    goal: str
    app_url: str
    passed: bool
    attempts: int
    project_name: Optional[str] = None
    project_dir: Optional[str] = None
    session_id: Optional[str] = None
    analysis: Optional[GoalAnalysis] = None
    plan: Optional[EngineeringPlan] = None
    verification: Optional[VerificationResult] = None
    observation: Optional[BrowserObservation] = None
    diff: list[OpenCodeDiffItem] = Field(default_factory=list)
    error: Optional[str] = None
    duration_seconds: float = 0.0


class AutonomousLoop:
    """Executes the autonomous engineering loop:

    Inspect -> Criteria (executable checks) -> Plan -> Coding agent -> Observe -> Verify -> Repair
    """

    def __init__(
        self,
        adapter: Optional[CodingAgent] = None,
        observer: Optional[PlaywrightObserver] = None,
        verifier: Optional[Verifier] = None,
        max_attempts: int = 3,
        console: Optional[Console] = None,
        project_manager: Optional[ProjectManager] = None,
        llm_provider: Optional[LLMProvider] = None,
        goal_analyzer: Optional[GoalAnalyzer] = None,
        inspector: Optional[RepositoryInspector] = None,
        planner: Optional[EngineeringPlanner] = None,
        repair_engine: Optional[RepairEngine] = None,
    ) -> None:
        self.llm_provider = llm_provider
        self.adapter = adapter
        self.observer = observer or PlaywrightObserver()
        self.verifier = verifier or Verifier(llm_provider=self.llm_provider)
        self.max_attempts = max_attempts
        self.console = console or Console()
        self.project_manager = project_manager or ProjectManager()
        self.goal_analyzer = goal_analyzer or GoalAnalyzer(llm_provider=self.llm_provider)
        self.inspector = inspector or RepositoryInspector()
        self.planner = planner or EngineeringPlanner(llm_provider=self.llm_provider)
        self.repair_engine = repair_engine or RepairEngine(llm_provider=self.llm_provider)

    async def run(
        self,
        goal: str,
        app_url: Optional[str] = None,
        criteria: Optional[GoalAnalysis] = None,
        project: Optional[Project] = None,
        project_dir: Optional[str | Path] = None,
    ) -> AutonomousLoopResult:
        """Run the full loop. ``app_url=None`` lets Contexer serve or locate the app itself."""
        if self.adapter is None:
            raise ValueError("AutonomousLoop.run requires a coding agent adapter; use verify_only() without one")
        start_time = time.monotonic()
        target_proj = self._resolve_project(project, project_dir)
        repo_context = self.inspector.inspect(target_proj.path)
        try:
            with self._open_app(target_proj, app_url, repo_context) as app:
                return await self._run(goal, app.url, criteria, target_proj, repo_context, start_time)
        except AppStartError as exc:
            return self._app_start_failure(goal, app_url, target_proj, start_time, exc)

    async def verify_only(
        self,
        goal: str,
        app_url: Optional[str] = None,
        criteria: Optional[GoalAnalysis] = None,
        project: Optional[Project] = None,
        project_dir: Optional[str | Path] = None,
    ) -> AutonomousLoopResult:
        """Verify the current state of the application against the goal, without any code changes."""
        start_time = time.monotonic()
        target_proj = self._resolve_project(project, project_dir)
        repo_context = self.inspector.inspect(target_proj.path)
        try:
            with self._open_app(target_proj, app_url, repo_context) as app:
                return await self._verify_only(goal, app.url, criteria, target_proj, repo_context, start_time)
        except AppStartError as exc:
            return self._app_start_failure(goal, app_url, target_proj, start_time, exc)

    async def _verify_only(
        self,
        goal: str,
        resolved_url: str,
        criteria: Optional[GoalAnalysis],
        target_proj: Project,
        repo_context: RepositoryContext,
        start_time: float,
    ) -> AutonomousLoopResult:
        self._print_header("Contexer Verification", goal, target_proj, resolved_url)
        self._print_inspection(repo_context)

        def result(**extra: Any) -> AutonomousLoopResult:
            return AutonomousLoopResult(
                goal=goal,
                app_url=resolved_url,
                attempts=1,
                project_name=target_proj.name,
                project_dir=str(target_proj.path),
                duration_seconds=time.monotonic() - start_time,
                **extra,
            )

        # Observe first: criteria for an existing UI must use the names it actually has.
        observation = await self._observe(resolved_url, "")
        if not observation.success:
            self._print_outcome(False, None, target_proj, resolved_url, start_time, attempts=None)
            return result(passed=False, observation=observation, error=observation.error)

        analysis = await self._derive_criteria(goal, repo_context, criteria, observation.ui_snapshot)
        verification = await self._verify(goal, observation, analysis, repo_context)
        self._print_outcome(verification.passed, verification, target_proj, resolved_url, start_time, attempts=None)
        return result(
            passed=verification.passed,
            analysis=analysis,
            verification=verification,
            observation=observation,
        )

    async def _run(
        self,
        goal: str,
        app_url: str,
        criteria: Optional[GoalAnalysis],
        target_proj: Project,
        repo_context: RepositoryContext,
        start_time: float,
    ) -> AutonomousLoopResult:
        assert self.adapter is not None
        scope_prompt = self.project_manager.format_scope_prompt(target_proj)

        self._print_header("Contexer Autonomous Loop", goal, target_proj, app_url)
        self._print_inspection(repo_context)
        ui_snapshot = await self._capture_current_ui(app_url, repo_context) if criteria is None else ""
        analysis = await self._derive_criteria(goal, repo_context, criteria, ui_snapshot)

        self.console.print("[bold yellow]● Generating Engineering Plan[/bold yellow]")
        with self.console.status("  [dim]Formulating implementation plan...[/dim]"):
            plan = await self.planner.create_plan(goal, repo_context, analysis)
        self.console.print(f"  [green]✓[/green] Strategy: [cyan]{escape(plan.approach)}[/]")
        for s in plan.steps:
            target_str = f" [dim]({escape(', '.join(s.target_files))})[/dim]" if s.target_files else ""
            self.console.print(f"    [dim]{s.step_number}.[/dim] {escape(s.title)}{target_str}")
        self.console.print()

        session = await self.adapter.create_session(
            title=f"Contexer: {goal[:30]}",
            directory=str(target_proj.path),
        )
        session_id = session.id

        def result(passed: bool, attempts: int, **extra: Any) -> AutonomousLoopResult:
            return AutonomousLoopResult(
                goal=goal,
                app_url=app_url,
                passed=passed,
                attempts=attempts,
                project_name=target_proj.name,
                project_dir=str(target_proj.path),
                session_id=session_id,
                analysis=analysis,
                plan=plan,
                duration_seconds=time.monotonic() - start_time,
                **extra,
            )

        self.console.print("[bold yellow]● Coding Agent Execution[/bold yellow]")
        self.console.print("  [cyan]›[/cyan] Dispatching plan and executable acceptance contract...")

        initial_prompt = (
            f"{scope_prompt}\n"
            f"You are an expert engineer implementing a task.\n\n"
            f"Original Goal: {goal}\n\n"
            f"Project Context:\n{repo_context.format_summary()}\n\n"
            f"Acceptance Criteria:\n{format_contract(analysis.acceptance_criteria)}\n\n"
            f"Engineering Plan:\n{plan.format_plan()}\n\n"
            f"CRITICAL REQUIREMENTS:\n"
            f"1. Implement all necessary code changes to completely satisfy ALL acceptance criteria.\n"
            f"2. The 'do:'/'expect:' lines are executed verbatim in a real browser to verify your work. "
            f"Use the exact accessible names, visible texts, labels, placeholders and data-testid values they reference.\n"
            f"3. All created or modified files MUST be placed inside the target directory.\n"
            f"4. The page must load without uncaught exceptions or console errors.\n"
            f"5. Create any missing files (HTML, CSS, JS, components) required to make the feature work."
        )

        with self.console.status("  [dim]Coding agent is executing the engineering plan...[/dim]"):
            exec_res = await self.adapter.send_prompt(
                session_id=session_id,
                prompt=initial_prompt,
                wait=True,
                timeout=180.0,
            )

        if exec_res.status != ExecutionStatus.COMPLETED:
            err = exec_res.error or "Coding agent execution failed"
            self.console.print(f"  [red]✗[/red] Coding agent error: {escape(err)}")
            return result(False, 1, error=err)

        self.console.print(f"  [green]✓[/green] Implementation complete ({exec_res.duration_seconds:.1f}s)")
        if exec_res.diff:
            self.console.print(f"  [dim]Files modified: {len(exec_res.diff)}[/dim]")
        self.console.print()

        attempt = 1
        last_observation: Optional[BrowserObservation] = None
        last_verification: Optional[VerificationResult] = None
        all_diffs = list(exec_res.diff)

        while attempt <= self.max_attempts:
            observation = await self._observe(app_url, f" (Attempt {attempt}/{self.max_attempts})")
            last_observation = observation

            if not observation.success:
                self.console.print("    [red]Cannot verify goal because application is offline or unreachable.[/red]")
                self.console.print()
                return result(False, attempt, observation=observation, diff=all_diffs, error=observation.error)

            verification = await self._verify(goal, observation, analysis, repo_context)
            last_verification = verification
            if verification.passed:
                self._print_outcome(True, verification, target_proj, app_url, start_time, attempts=attempt)
                return result(True, attempt, verification=verification, observation=observation, diff=all_diffs)

            if attempt >= self.max_attempts:
                break

            self.console.print(f"[bold yellow]● Diagnosis & Self-Repair (Attempt {attempt}/{self.max_attempts})[/bold yellow]")
            with self.console.status("  [dim]Diagnosing failures and generating targeted fix instructions...[/dim]"):
                diagnosis = await self.repair_engine.diagnose_failure(
                    goal=goal,
                    observation=observation,
                    result=verification,
                    diffs=all_diffs,
                )
            self.console.print(f"  [cyan]›[/cyan] Diagnosis: {escape(diagnosis)}")

            repair_prompt = self.repair_engine.generate_repair_prompt(
                goal=goal,
                observation=observation,
                result=verification,
                analysis=analysis,
                scope_instruction=scope_prompt,
                diagnosis=diagnosis,
            )
            self.console.print("  [cyan]›[/cyan] Sending targeted repair prompt to coding agent...")

            with self.console.status("  [dim]Coding agent is applying the repair...[/dim]"):
                repair_res = await self.adapter.send_prompt(
                    session_id=session_id,
                    prompt=repair_prompt,
                    wait=True,
                    timeout=180.0,
                )

            if repair_res.status != ExecutionStatus.COMPLETED:
                self.console.print(f"  [red]✗[/red] Repair execution failed: {escape(repair_res.error or '')}")
            else:
                self.console.print(f"  [green]✓[/green] Fix applied ({repair_res.duration_seconds:.1f}s)")
                if repair_res.diff:
                    all_diffs.extend(repair_res.diff)
            self.console.print()

            attempt += 1

        self._print_outcome(False, last_verification, target_proj, app_url, start_time, attempts=self.max_attempts)
        return result(
            False,
            self.max_attempts,
            verification=last_verification,
            observation=last_observation,
            diff=all_diffs,
        )

    # -- target resolution ----------------------------------------------------

    def _resolve_project(self, project: Optional[Project], project_dir: Optional[str | Path]) -> Project:
        if project:
            return project
        if project_dir:
            return self.project_manager.set_active_project(project_dir)
        return self.project_manager.active_project

    def _open_app(self, project: Project, app_url: Optional[str], repo_context: RepositoryContext):
        """An explicit URL wins; static sites are served; otherwise Contexer starts the dev server."""

        def status(message: str) -> None:
            self.console.print(f"  [dim]› {escape(message)}[/dim]")

        return open_app(project.path, app_url, repo_context=repo_context, on_status=status)

    def _app_start_failure(
        self,
        goal: str,
        app_url: Optional[str],
        project: Project,
        start_time: float,
        exc: AppStartError,
    ) -> AutonomousLoopResult:
        self.console.print(f"  [red]✗[/red] Could not start the app: {escape(str(exc))}")
        for line in exc.log_tail.splitlines()[-15:]:
            self.console.print(f"    [dim]{escape(line)}[/dim]")
        return AutonomousLoopResult(
            goal=goal,
            app_url=app_url or "",
            passed=False,
            attempts=0,
            project_name=project.name,
            project_dir=str(project.path),
            error=str(exc),
            duration_seconds=time.monotonic() - start_time,
        )

    # -- phases -----------------------------------------------------------------

    async def _derive_criteria(
        self,
        goal: str,
        repo_context: RepositoryContext,
        criteria: Optional[GoalAnalysis],
        ui_snapshot: str = "",
    ) -> GoalAnalysis:
        self.console.print("[bold yellow]● Deriving Acceptance Criteria & Executable Checks[/bold yellow]")
        analysis = criteria
        if not analysis:
            with self.console.status("  [dim]Compiling goal into executable acceptance checks...[/dim]"):
                analysis = await self.goal_analyzer.analyze(goal, repo_context, ui_snapshot)

        if analysis.generated_by == "rules" and self.llm_provider is not None:
            self.console.print("  [yellow]![/yellow] LLM unavailable; using rule-based criteria")
        checked = sum(1 for c in analysis.acceptance_criteria if c.check)
        grounding = " (locators grounded in the current UI)" if ui_snapshot and analysis.generated_by == "llm" else ""
        self.console.print(
            f"  [green]✓[/green] {len(analysis.acceptance_criteria)} criteria, "
            f"{checked} with executable browser checks{grounding}:"
        )
        for c in analysis.acceptance_criteria:
            kind = "check" if c.check else "judged"
            self.console.print(f"    [dim]•[/dim] [bold]{escape(c.id)}[/bold] {escape(c.description)} [dim]({kind})[/dim]")
            if c.check:
                for line in c.check.describe_lines():
                    self.console.print(f"        [dim]{escape(line)}[/dim]")
        self.console.print()
        return analysis

    async def _capture_current_ui(self, app_url: str, repo_context: RepositoryContext) -> str:
        """Snapshot an existing app's UI so checks reuse its real names; empty for new projects."""
        if not repo_context.key_files:
            return ""
        with self.console.status("  [dim]Capturing current UI to ground check locators...[/dim]"):
            observation = await self.observer.observe(app_url, screenshot=False)
        return observation.ui_snapshot if observation.success else ""

    async def _observe(self, app_url: str, attempt_label: str) -> BrowserObservation:
        self.console.print(f"[bold yellow]● Browser Observation{attempt_label}[/bold yellow]")
        self.console.print(f"  [cyan]›[/cyan] Navigating to {escape(app_url)}...")
        with self.console.status(f"  [dim]Inspecting live application at {escape(app_url)}...[/dim]"):
            observation = await self.observer.observe(app_url)

        if not observation.success:
            self.console.print(f"  [red]✗[/red] Application unreachable: {escape(observation.error or '')}")
            return observation

        self.console.print(f"  [green]✓[/green] Application loaded (Title: '{escape(observation.page_title or 'Untitled')}')")
        if observation.headings:
            self.console.print(f"  [green]✓[/green] Observed Headings: {escape(', '.join(observation.headings[:3]))}")
        if observation.interactive_elements:
            self.console.print(f"  [green]✓[/green] Interactive Controls: {len(observation.interactive_elements)} detected")
        self.console.print()
        return observation

    async def _verify(
        self,
        goal: str,
        observation: BrowserObservation,
        analysis: GoalAnalysis,
        repo_context: RepositoryContext,
    ) -> VerificationResult:
        self.console.print("[bold yellow]● Verification[/bold yellow]")
        with self.console.status("  [dim]Executing acceptance checks in the browser...[/dim]"):
            verification = await self.verifier.verify(goal, observation, analysis, repo_context)

        for cr in verification.criteria_results:
            blocked = cr.check_result is not None and cr.check_result.blocked
            mark = "[green]✓[/green]" if cr.passed else ("[yellow]?[/yellow]" if blocked else "[red]✗[/red]")
            tag = "[yellow]blocked[/]" if blocked else _METHOD_TAGS.get(cr.method, cr.method)
            self.console.print(f"  {mark} [bold]{escape(cr.criterion_id)}[/bold] {escape(cr.description)} [dim]·[/dim] {tag}")
            if cr.check_result and not cr.passed:
                color = "yellow" if blocked else "red"
                for line in cr.check_result.failure_report().splitlines()[1:14]:
                    self.console.print(f"      [{color}]{escape(line.rstrip())}[/{color}]")
            elif cr.evidence:
                self.console.print(f"      [dim]{escape(cr.evidence)}[/dim]")
        self.console.print()
        return verification

    # -- rendering ----------------------------------------------------------------

    def _print_header(self, title: str, goal: str, project: Project, app_url: str) -> None:
        self.console.print()
        header_text = (
            f"[bold bright_cyan]Goal:[/]     {escape(goal)}\n"
            f"[bold bright_cyan]Project:[/]  {escape(project.name)} ({project.project_type.value}) -> [dim]{escape(str(project.path))}[/dim]\n"
            f"[bold bright_cyan]Target:[/]   {escape(app_url)}"
        )
        self.console.print(Panel(header_text, title=title, border_style="bright_cyan"))
        self.console.print()

    def _print_inspection(self, repo_context: RepositoryContext) -> None:
        self.console.print("[bold yellow]● Inspecting Target Repository[/bold yellow]")
        self.console.print(f"  [green]✓[/green] Detected Stack: [bright_cyan]{escape(repo_context.framework)}[/]")
        if repo_context.entry_points:
            self.console.print(f"  [green]✓[/green] Entrypoints: {escape(', '.join(repo_context.entry_points))}")
        self.console.print(f"  [green]✓[/green] Existing files: {len(repo_context.key_files)} files")
        self.console.print()

    def _print_outcome(
        self,
        passed: bool,
        verification: Optional[VerificationResult],
        project: Project,
        app_url: str,
        start_time: float,
        attempts: Optional[int],
    ) -> None:
        duration = time.monotonic() - start_time
        summary = escape(verification.summary) if verification else "No verification result"
        if passed:
            headline = (
                f"Contexer verified all acceptance criteria in {attempts} attempt(s)!"
                if attempts
                else "The application satisfies all acceptance criteria."
            )
            body = f"[bold green]{headline}[/bold green]\n"
            title, style = "COMPLETE", "green"
        else:
            headline = f"Verification failed after {attempts} attempts." if attempts else "The application does not satisfy the goal."
            reason = escape(verification.reason) if verification else "Acceptance criteria not met"
            body = f"[bold red]{headline}[/bold red]\nReason:   {reason}\n"
            title, style = "FAILED", "red"
        confidence = f"{verification.confidence:.2f}" if verification else "n/a"
        body += (
            f"Verdicts: {summary} (confidence {confidence})\n"
            f"Project:  {escape(project.name)} ({escape(str(project.path))})\n"
            f"Target:   {escape(app_url)}\n"
            f"Duration: {duration:.1f}s"
        )
        self.console.print(Panel(body, title=title, border_style=style))
