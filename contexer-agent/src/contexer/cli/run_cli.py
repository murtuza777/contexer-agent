"""``contexer run``: approve what "done" means, then let Contexer drive the agent to it."""

from __future__ import annotations

import asyncio
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
from contexer.cli.gate_cli import compiler_llm, warn_if_weak_draft
from contexer.config.project import ProjectConfigError, load_project_config
from contexer.contract import Contract, ContractError, ContractStore
from contexer.controller import RunController, RunOutcome, RunSettings
from contexer.evidence import RunDir
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
    agent_name: Optional[str] = typer.Option(None, "--agent", help="claude-code (default) or opencode."),
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
    try:
        config = load_project_config(project)
    except ProjectConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc
    store = ContractStore(project)

    if goal:
        contract = _draft(console, project, store, goal, url)
    else:
        try:
            contract = store.load(contract_id or "")
        except ContractError as exc:
            raise typer.BadParameter(str(exc)) from exc

    if contract.status != "approved":
        contract = _approve(console, store, contract, yes)

    settings = RunSettings(
        max_repair_rounds=rounds if rounds is not None else config.agent.max_repair_rounds,
        budget_usd=budget if budget is not None else config.agent.budget_usd,
        turn_timeout=config.agent.turn_timeout,
        judged_policy=config.gate.judged,
        replay_others=not no_replay,
    )
    agent = create_agent(agent_name or config.agent.name, model or config.agent.model)
    others = [c for c in store.list() if c.id != contract.id and c.status == "approved"]

    console.print()
    console.print(f"[bold bright_cyan]Contexer run[/] [dim]·[/] {escape(contract.goal)}")
    console.print(
        f"[dim]{escape(agent.describe())} · up to {settings.max_repair_rounds} repair round(s)"
        f"{f' · budget ${settings.budget_usd:.2f}' if settings.budget_usd else ''}"
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


def _draft(console: Console, project: Path, store: ContractStore, goal: str, url: Optional[str]) -> Contract:
    async def compile_contract() -> Contract:
        run_dir = RunDir.create(project)
        session = VerificationSession(project, run_dir)
        analyzer = GoalAnalyzer(llm_provider=compiler_llm(project))
        cid = store.unique_id(goal)
        try:
            with open_app(project, url) as app:
                await session.observe(app)
                return await session.compile(goal, analyzer, cid, app.repo_context)
        except AppStartError:
            return await session.compile(goal, analyzer, cid)  # nothing runs yet: checks define the contract

    with console.status("[dim]Compiling the goal into executable checks...[/dim]"):
        contract = asyncio.run(compile_contract())
    store.save(contract)
    return contract


def _approve(console: Console, store: ContractStore, contract: Contract, yes: bool) -> Contract:
    console.print()
    console.print(Panel("\n".join(escape(line) for line in contract.describe_lines()), title=f"Definition of done · {contract.id}"))
    warn_if_weak_draft(console, contract)
    if not yes and not typer.confirm("Approve these checks as the definition of done?", default=False):
        store.save(contract)
        console.print(f"[yellow]Not approved.[/] Edit {escape(str(store.path_for(contract.id)))} and run again.")
        raise typer.Exit(code=2)
    approved = store.approve(contract.id)
    console.print(f"[green]✓[/] Approved [bold]{escape(approved.id)}[/]")
    return approved


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
    lines.append(f"[dim]Report:[/] {escape(str(Path(outcome.run_dir, 'report.html')))}")
    lines.append(f"[dim]{outcome.duration_seconds:.0f}s[/]")
    console.print()
    console.print(table)
    console.print(Panel("\n".join(lines), border_style=style, title="Contexer"))
