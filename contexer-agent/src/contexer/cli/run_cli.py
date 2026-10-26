"""``contexer run``: approve what "done" means, then let Contexer drive the agent to it."""

from __future__ import annotations

import asyncio
import os
import shutil
import webbrowser
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from contexer.agents import create_agent
from contexer.appserver import AppStartError, open_app
from contexer.cli.gate_cli import compiler_llm, preview_draft, print_draft_preview, warn_if_weak_draft
from contexer.config.project import ProjectConfigError, load_project_config, load_project_env
from contexer.contract import Contract, ContractError, ContractStore
from contexer.controller import RunController, RunOutcome, RunSettings
from contexer.evidence import RunDir
from contexer.gate import RunResult
from contexer.gate.session import VerificationSession
from contexer.workflow.criteria import GoalAnalyzer

_EVENT_STYLE = {
    "phase": "bold yellow",
    "agent": "dim",
    "agent-done": "cyan",
    "app": "dim",
    "verdict": "bold",
    "revert": "magenta",
    "strategy": "magenta",
}
_TERMINAL_STYLE = {"succeeded": "green", "failed_checks": "red", "tampered": "red", "agent_error": "red", "app_error": "red"}


def run(
    goal: Optional[str] = typer.Argument(None, help="What should be true when the work is done."),
    contract_id: Optional[str] = typer.Option(None, "--contract", "-c", help="Run an existing contract instead."),
    project_dir: Path = typer.Option(Path("."), "--dir", "-d", help="Project directory.", file_okay=False),
    url: Optional[str] = typer.Option(None, "--url", "-u", help="Use an app you already run."),
    agent_name: Optional[str] = typer.Option(None, "--agent", help="claude-code (default), codex or opencode."),
    model: Optional[str] = typer.Option(None, "--model", help="Model for the coding agent."),
    rounds: Optional[int] = typer.Option(None, "--rounds", min=0, help="Maximum repair rounds (default 2)."),
    budget: Optional[float] = typer.Option(None, "--budget", help="Stop when the agent has spent this many USD."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Approve the checklist without asking."),
    no_replay: bool = typer.Option(False, "--no-replay", help="Skip re-checking other approved contracts."),
    open_report: bool = typer.Option(False, "--open", help="Open the HTML report when done."),
) -> None:
    """Turn a goal into approved checks, have a coding agent build it, prove it, and repair until it passes."""
    if bool(goal) == bool(contract_id):
        raise typer.BadParameter("give either a GOAL or --contract ID")
    console = Console()
    project = project_dir.resolve()
    load_project_env(project)  # model keys for the drafting model and the coding agent
    try:
        config = load_project_config(project)
    except ProjectConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc
    store = ContractStore(project)

    preview: Optional[RunResult] = None
    weak_reason: Optional[str] = None
    if goal:
        contract, preview, weak_reason = _draft(console, project, store, goal, url)
    else:
        try:
            contract = store.load(contract_id or "")
        except ContractError as exc:
            raise typer.BadParameter(str(exc)) from exc

    if contract.status != "approved":
        contract = _approve(console, store, contract, yes, preview, weak_reason)

    settings = RunSettings(
        max_repair_rounds=rounds if rounds is not None else config.agent.max_repair_rounds,
        budget_usd=budget if budget is not None else config.agent.budget_usd,
        turn_timeout=config.agent.turn_timeout,
        judged_policy=config.gate.judged,
        replay_others=not no_replay,
    )
    try:
        agent = create_agent(agent_name or config.agent.name, model or config.agent.model)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    others = [c for c in store.list() if c.id != contract.id and c.status == "approved"]

    budget_note = ""
    if settings.budget_usd:
        # Codex reports tokens, not cost: the round and time limits bound its runs instead.
        budget_note = " · no spending limit (Codex reports no cost)" if agent.name == "codex" else f" · budget ${settings.budget_usd:.2f}"
    console.print()
    console.print(f"[bold bright_cyan]Contexer run[/] [dim]·[/] {escape(contract.goal)}")
    console.print(
        f"[dim]{escape(agent.describe())} · up to {settings.max_repair_rounds} repair round(s)"
        f"{budget_note}"
        f"{f' · replaying {len(others)} other contract(s)' if others else ''}[/]"
    )

    def on_event(kind: str, message: str) -> None:
        style = _EVENT_STYLE.get(kind, "")
        prefix = "  " if kind in ("agent", "app") else ""
        console.print(f"{prefix}[{style}]{escape(message)}[/]" if style else f"{prefix}{escape(message)}")

    controller = RunController(project, agent, settings, url=url, on_event=on_event)
    try:
        outcome = asyncio.run(controller.run(contract, others))
    finally:
        agent.close()
    _render(console, outcome)
    if open_report:
        webbrowser.open(Path(outcome.run_dir, "report.html").resolve().as_uri())
    raise typer.Exit(code=outcome.exit_code)


def _draft(
    console: Console, project: Path, store: ContractStore, goal: str, url: Optional[str]
) -> tuple[Contract, Optional[RunResult], Optional[str]]:
    analyzer = GoalAnalyzer(llm_provider=compiler_llm(project))

    async def compile_contract() -> tuple[Contract, Optional[RunResult]]:
        run_dir = RunDir.create(project)
        session = VerificationSession(project, run_dir)
        cid = store.unique_id(goal)
        try:
            with open_app(project, url) as app:
                await session.observe(app)
                drafted = await session.compile(goal, analyzer, cid, app.repo_context)
                return drafted, await preview_draft(session, app, drafted)
        except AppStartError:
            # nothing runs yet: the checks define the contract
            return await session.compile(goal, analyzer, cid), None

    with console.status("[dim]Compiling the goal into checks, then trying them on the app as it is...[/dim]"):
        contract, preview = asyncio.run(compile_contract())
    store.save(contract)
    return contract, preview, analyzer.last_error


def _approve(
    console: Console,
    store: ContractStore,
    contract: Contract,
    yes: bool,
    preview: Optional[RunResult] = None,
    weak_reason: Optional[str] = None,
) -> Contract:
    console.print()
    console.print(Panel("\n".join(escape(line) for line in contract.describe_lines()), title=f"Definition of done · {contract.id}"))
    print_draft_preview(console, preview)
    warn_if_weak_draft(console, contract, weak_reason)
    if yes and contract.source == "rules":
        # Building against a rule-based fallback wastes the agent's budget on a contract nobody chose.
        console.print(
            f"[yellow]Not approved:[/] --yes never approves a weak draft. Review "
            f"{escape(str(store.path_for(contract.id)))}, then `contexer contract approve {escape(contract.id)}`."
        )
        raise typer.Exit(code=2)
    if not yes and not typer.confirm("Approve these checks as the definition of done?", default=False):
        store.save(contract)
        console.print(f"[yellow]Not approved.[/] Edit {escape(str(store.path_for(contract.id)))} and run again.")
        raise typer.Exit(code=2)
    approved = store.approve(contract.id)
    console.print(f"[green]✓[/] Approved [bold]{escape(approved.id)}[/]")
    return approved


_ACCOUNT_PROBLEMS = ("credit balance", "credits", "unauthorized", "401", "authentication", "api key", "not logged in", "login")


def agent_hint(outcome: RunOutcome) -> Optional[str]:
    """What to do when the coding agent itself could not run (no credit, not logged in)."""
    if outcome.terminal != "agent_error":
        return None
    reason = outcome.reason.lower()
    if not any(problem in reason for problem in _ACCOUNT_PROBLEMS):
        return None
    if os.environ.get("OPENROUTER_API_KEY") and shutil.which("opencode"):
        return "the agent's account cannot run it; `--agent opencode` runs it on your OpenRouter key's free models."
    if os.environ.get("OPENROUTER_API_KEY"):
        return (
            "the agent's account cannot run it. Install OpenCode (npm i -g opencode-ai) and use "
            "`--agent opencode` to run it on your OpenRouter key's free models."
        )
    return "the agent's account cannot run it: log in to it, add credit, or choose another with --agent."


def _render(console: Console, outcome: RunOutcome) -> None:
    table = Table(show_header=True, header_style="dim", box=None, pad_edge=False)
    for col in ("#", "turn", "agent", "files", "verdict", "note"):
        table.add_column(col)
    for a in outcome.attempts:
        kept = " ★" if a.n == outcome.best_attempt else ""
        verdict = f"{a.outcome} ({a.verified}✓ {a.refuted}✗ {a.unverified}?)" if a.outcome != "error" else "error"
        table.add_row(
            f"{a.n}{kept}",
            a.kind + (" (fresh)" if a.fresh_session and a.n > 1 else ""),
            a.agent.status,
            str(len(a.changed_files)),
            verdict,
            escape(a.note),
        )
    style = _TERMINAL_STYLE.get(outcome.terminal, "yellow")
    lines = [f"[bold {style}]{escape(outcome.terminal.replace('_', ' ').upper())}[/] — {escape(outcome.reason)}"]
    if outcome.cost_usd:
        lines.append(f"[dim]Agent spend:[/] ${outcome.cost_usd:.2f}")
    hint = agent_hint(outcome)
    if hint:
        lines.append(f"[yellow]Next:[/] {escape(hint)}")
    lines.append(f"[dim]Report:[/] {escape(str(Path(outcome.run_dir, 'report.html')))}")
    lines.append(f"[dim]{outcome.duration_seconds:.0f}s[/]")
    console.print()
    console.print(table)
    console.print(Panel("\n".join(lines), border_style=style, title="Contexer"))
