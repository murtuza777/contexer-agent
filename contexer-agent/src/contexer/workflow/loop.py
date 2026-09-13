"""Dynamic, goal-driven autonomous engineering loop orchestrating OpenCode, Playwright, and Verifier."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Optional
from pydantic import BaseModel, Field
from rich.console import Console
from rich.panel import Panel

from contexer.config.settings import load_config
from contexer.llm.base import LLMProvider
from contexer.llm.factory import create_llm_provider
from contexer.observer.models import BrowserObservation
from contexer.observer.playwright import PlaywrightObserver
from contexer.opencode.adapter import OpenCodeAdapter
from contexer.opencode.models import ExecutionStatus, OpenCodeDiffItem
from contexer.project.manager import ProjectManager
from contexer.project.models import Project
from contexer.repair.repair import RepairEngine
from contexer.verification.models import GoalAnalysis, VerificationResult
from contexer.verification.verifier import Verifier
from contexer.workflow.criteria import GoalAnalyzer
from contexer.workflow.inspector import RepositoryContext, RepositoryInspector
from contexer.workflow.planner import EngineeringPlan, EngineeringPlanner

logger = logging.getLogger(__name__)


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

    Goal -> GoalAnalyzer -> RepoInspector -> Planner -> OpenCode -> Playwright -> Verifier -> Repair
    """

    def __init__(
        self,
        adapter: OpenCodeAdapter,
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
        if llm_provider is None:
            try:
                cfg = load_config()
                if cfg.openrouter_api_key:
                    llm_provider = create_llm_provider(cfg)
            except Exception as e:
                logger.debug("Could not auto-create LLM provider for loop: %s", e)

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
        app_url: str,
        criteria: Optional[GoalAnalysis] = None,
        project: Optional[Project] = None,
        project_dir: Optional[str | Path] = None,
    ) -> AutonomousLoopResult:
        """Run the full dynamic autonomous loop with strict evidence verification."""
        start_time = time.monotonic()

        # 0. Resolve target project workspace
        if project:
            target_proj = project
        elif project_dir:
            target_proj = self.project_manager.set_active_project(project_dir)
        else:
            target_proj = self.project_manager.active_project

        scope_prompt = self.project_manager.format_scope_prompt(target_proj)

        # 1. Header display
        self.console.print()
        header_text = (
            f"[bold bright_cyan]Goal:[/]     {goal}\n"
            f"[bold bright_cyan]Project:[/]  {target_proj.name} ({target_proj.project_type.value}) -> [dim]{target_proj.path}[/dim]\n"
            f"[bold bright_cyan]Target:[/]   {app_url}"
        )
        self.console.print(Panel(header_text, title="Contexer Autonomous Loop", border_style="bright_cyan"))
        self.console.print()

        # 2. Inspect Target Repository
        self.console.print("[bold yellow]● Inspecting Target Repository[/bold yellow]")
        repo_context = self.inspector.inspect(target_proj.path)
        self.console.print(f"  [green]✓[/green] Detected Stack: [bright_cyan]{repo_context.framework}[/]")
        if repo_context.entry_points:
            self.console.print(f"  [green]✓[/green] Entrypoints: {', '.join(repo_context.entry_points)}")
        self.console.print(f"  [green]✓[/green] Existing files: {len(repo_context.key_files)} files")
        self.console.print()

        # 3. Dynamic Goal Understanding & Criteria Generation
        self.console.print("[bold yellow]● Understanding Goal & Deriving Acceptance Criteria[/bold yellow]")
        analysis = criteria
        if not analysis:
            with self.console.status("  [dim]Decomposing goal into verifiable acceptance criteria...[/dim]"):
                analysis = await self.goal_analyzer.analyze(goal, repo_context)

        self.console.print(f"  [green]✓[/green] Derived {len(analysis.acceptance_criteria)} acceptance criteria:")
        for c in analysis.acceptance_criteria:
            self.console.print(f"    [dim]• [{c.id}]:[/dim] {c.description} [dim]({c.verification_method})[/dim]")
        self.console.print()

        # 4. Dynamic Engineering Plan Formulation
        self.console.print("[bold yellow]● Generating Engineering Plan[/bold yellow]")
        with self.console.status("  [dim]Formulating implementation plan...[/dim]"):
            plan = await self.planner.create_plan(goal, repo_context, analysis)
        self.console.print(f"  [green]✓[/green] Strategy: [cyan]{plan.approach}[/]")
        for s in plan.steps:
            target_str = f" [dim]({', '.join(s.target_files)})[/dim]" if s.target_files else ""
            self.console.print(f"    [dim]{s.step_number}.[/dim] {s.title}{target_str}")
        self.console.print()

        # 5. Create OpenCode Session
        session = await self.adapter.create_session(
            title=f"Contexer: {goal[:30]}",
            directory=str(target_proj.path),
        )
        session_id = session.id

        # 6. Dispatch Initial Engineering Task
        self.console.print("[bold yellow]● OpenCode Execution[/bold yellow]")
        self.console.print("  [cyan]›[/cyan] Dispatching engineering plan to OpenCode...")

        criteria_prompt = "\n".join(f"- [{c.id}]: {c.description}" for c in analysis.acceptance_criteria)
        plan_prompt = plan.format_plan()

        initial_prompt = (
            f"{scope_prompt}\n"
            f"You are an expert engineer implementing a task.\n\n"
            f"Original Goal: {goal}\n\n"
            f"Project Context:\n{repo_context.format_summary()}\n\n"
            f"Acceptance Criteria to Satisfy:\n{criteria_prompt}\n\n"
            f"Engineering Plan:\n{plan_prompt}\n\n"
            f"CRITICAL REQUIREMENTS:\n"
            f"1. Implement all necessary code changes to completely satisfy ALL acceptance criteria.\n"
            f"2. All created or modified files MUST be placed inside the target directory.\n"
            f"3. Ensure the code compiles and runs cleanly without syntax or runtime errors.\n"
            f"4. Create any missing files (HTML, CSS, JS, React/Next.js components) required to make the feature work."
        )

        with self.console.status("  [dim]OpenCode is executing the engineering plan...[/dim]"):
            exec_res = await self.adapter.send_prompt(
                session_id=session_id,
                prompt=initial_prompt,
                wait=True,
                timeout=180.0,
            )

        if exec_res.status != ExecutionStatus.COMPLETED:
            err = exec_res.error or "OpenCode execution failed"
            self.console.print(f"  [red]✗[/red] OpenCode error: {err}")
            return AutonomousLoopResult(
                goal=goal,
                app_url=app_url,
                passed=False,
                attempts=1,
                project_name=target_proj.name,
                project_dir=str(target_proj.path),
                session_id=session_id,
                analysis=analysis,
                plan=plan,
                error=err,
                duration_seconds=time.monotonic() - start_time,
            )

        self.console.print(f"  [green]✓[/green] Implementation complete ({exec_res.duration_seconds:.1f}s)")
        if exec_res.diff:
            self.console.print(f"  [dim]Files modified: {len(exec_res.diff)}[/dim]")
        self.console.print()

        # 7. Autonomous Observation & Strict Verification Loop
        attempt = 1
        last_observation: Optional[BrowserObservation] = None
        last_verification: Optional[VerificationResult] = None
        all_diffs = list(exec_res.diff)

        while attempt <= self.max_attempts:
            # Playwright observation
            self.console.print(f"[bold yellow]● Playwright Observation (Attempt {attempt}/{self.max_attempts})[/bold yellow]")
            self.console.print(f"  [cyan]›[/cyan] Navigating to {app_url}...")
            with self.console.status(f"  [dim]Inspecting live application at {app_url}...[/dim]"):
                observation = await self.observer.observe(app_url)
            last_observation = observation

            if not observation.success:
                self.console.print(f"  [red]✗[/red] Application unreachable: {observation.error}")
                self.console.print("    [red]Cannot verify goal because application is offline or unreachable.[/red]")
                self.console.print()
                return AutonomousLoopResult(
                    goal=goal,
                    app_url=app_url,
                    passed=False,
                    attempts=attempt,
                    project_name=target_proj.name,
                    project_dir=str(target_proj.path),
                    session_id=session_id,
                    analysis=analysis,
                    plan=plan,
                    observation=observation,
                    diff=all_diffs,
                    error=observation.error,
                    duration_seconds=time.monotonic() - start_time,
                )

            self.console.print(f"  [green]✓[/green] Application loaded (Title: '{observation.page_title or 'Untitled'}')")
            if observation.headings:
                self.console.print(f"  [green]✓[/green] Observed Headings: {', '.join(observation.headings[:3])}")
            if observation.interactive_elements:
                self.console.print(f"  [green]✓[/green] Interactive Controls: {len(observation.interactive_elements)} detected")
            self.console.print()

            # Dynamic Verification
            self.console.print("[bold yellow]● Dynamic Verification[/bold yellow]")
            with self.console.status("  [dim]Evaluating observed DOM, elements, and text against criteria...[/dim]"):
                verification = await self.verifier.verify(goal, observation, analysis, repo_context)
            last_verification = verification

            # Render individual criteria evaluations
            if verification.criteria_results:
                for cr in verification.criteria_results:
                    mark = "[green]✓[/green]" if cr.passed else "[red]✗[/red]"
                    self.console.print(f"  {mark} [{cr.criterion_id}]: {cr.description}")
                    if cr.evidence:
                        self.console.print(f"    [dim]Evidence: {cr.evidence}[/dim]")
            self.console.print()

            if verification.passed:
                self.console.print(f"  [bold green]✓ Goal Verified![/] (Confidence: {verification.confidence:.2f})")
                for ev in verification.evidence[:3]:
                    self.console.print(f"    [dim]• {ev}[/dim]")
                self.console.print()

                self.console.print(
                    Panel(
                        f"[bold green]Contexer verified all acceptance criteria in {attempt} attempt(s)![/bold green]\n"
                        f"Project: {target_proj.name} ({target_proj.path})\n"
                        f"Target:  {app_url}\n"
                        f"Summary: {verification.summary or 'Outcome confirmed with positive evidence.'}\n"
                        f"Duration: {time.monotonic() - start_time:.1f}s",
                        title="COMPLETE",
                        border_style="green",
                    )
                )
                return AutonomousLoopResult(
                    goal=goal,
                    app_url=app_url,
                    passed=True,
                    attempts=attempt,
                    project_name=target_proj.name,
                    project_dir=str(target_proj.path),
                    session_id=session_id,
                    analysis=analysis,
                    plan=plan,
                    verification=verification,
                    observation=observation,
                    diff=all_diffs,
                    duration_seconds=time.monotonic() - start_time,
                )

            # Verification failed
            self.console.print(f"  [bold red]✗ Verification Failed:[/] {verification.reason}")
            for fail in verification.failures[:3]:
                self.console.print(f"    [red]• {fail}[/red]")
            self.console.print()

            if attempt >= self.max_attempts:
                break

            # 8. Dynamic Diagnosis & Self-Repair Phase
            self.console.print(f"[bold yellow]● Diagnosis & Self-Repair (Attempt {attempt}/{self.max_attempts})[/bold yellow]")
            with self.console.status("  [dim]Diagnosing failures and generating targeted fix instructions...[/dim]"):
                diagnosis = await self.repair_engine.diagnose_failure(
                    goal=goal,
                    observation=observation,
                    result=verification,
                    diffs=all_diffs,
                )
            self.console.print(f"  [cyan]›[/cyan] Diagnosis: {diagnosis}")

            repair_prompt = self.repair_engine.generate_repair_prompt(
                goal=goal,
                observation=observation,
                result=verification,
                analysis=analysis,
                scope_instruction=scope_prompt,
                diagnosis=diagnosis,
            )
            self.console.print("  [cyan]›[/cyan] Sending targeted repair prompt to OpenCode...")

            with self.console.status("  [dim]OpenCode is applying the repair fix...[/dim]"):
                repair_res = await self.adapter.send_prompt(
                    session_id=session_id,
                    prompt=repair_prompt,
                    wait=True,
                    timeout=180.0,
                )

            if repair_res.status != ExecutionStatus.COMPLETED:
                self.console.print(f"  [red]✗[/red] Repair execution failed: {repair_res.error}")
            else:
                self.console.print(f"  [green]✓[/green] Fix applied by OpenCode ({repair_res.duration_seconds:.1f}s)")
                if repair_res.diff:
                    all_diffs.extend(repair_res.diff)
            self.console.print()

            attempt += 1

        # Max attempts reached without satisfying criteria
        self.console.print(
            Panel(
                f"[bold red]Verification failed after {self.max_attempts} attempts.[/bold red]\n"
                f"Project: {target_proj.name} ({target_proj.path})\n"
                f"Reason:  {last_verification.reason if last_verification else 'Acceptance criteria not met'}\n"
                f"Summary: {last_verification.summary if last_verification else 'Missing observable evidence'}",
                title="FAILED",
                border_style="red",
            )
        )
        return AutonomousLoopResult(
            goal=goal,
            app_url=app_url,
            passed=False,
            attempts=self.max_attempts,
            project_name=target_proj.name,
            project_dir=str(target_proj.path),
            session_id=session_id,
            analysis=analysis,
            plan=plan,
            verification=last_verification,
            observation=last_observation,
            diff=all_diffs,
            duration_seconds=time.monotonic() - start_time,
        )
