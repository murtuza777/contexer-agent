"""``contexer run``: approve what "done" means, then let Contexer drive the agent to it."""

from __future__ import annotations

import asyncio
import os
import shutil
import webbrowser
from pathlib import Path
from typing import Any, Callable, Optional

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from contexer.agents import CodingAgentAdapter, create_agent
from contexer.appserver import AppStartError, open_app
from contexer.cli.gate_cli import (
    compiler_llm,
    preview_draft,
    print_draft_preview,
    print_drafted_by,
    warn_if_weak_draft,
)
from contexer.config.project import AgentSettings, ProjectConfigError, load_project_config, load_project_env
from contexer.contract import Contract, ContractError, ContractStore
from contexer.controller import RunController, RunOutcome, RunSettings
from contexer.evidence import RunDir
from contexer.gate import RunResult
from contexer.gate.session import VerificationSession
from contexer.github.api import GitHubClient, GitHubError, github_token
from contexer.github.handoff import Handoff, HandoffError, HandoffPlan, hand_off, plan_handoff
from contexer.llm import discovery
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
    pr: bool = typer.Option(False, "--pr", help="Commit the result to a new branch and open a pull request with the evidence."),
    issue: Optional[int] = typer.Option(None, "--issue", min=1, help="Take the goal from this GitHub issue; the pull request closes it."),
) -> None:
    """Turn a goal into approved checks, have a coding agent build it, prove it, and repair until it passes."""
    if sum((bool(goal), bool(contract_id), issue is not None)) != 1:
        raise typer.BadParameter("give a GOAL, --contract ID or --issue N")
    console = Console()
    project = project_dir.resolve()
    pr = pr or issue is not None  # work on an issue ends in a pull request that closes it
    handoff_plan: Optional[HandoffPlan] = None
    if pr:
        try:
            handoff_plan = plan_handoff(project)  # before anything is spent
        except HandoffError as exc:
            console.print(f"[red]Cannot open a pull request:[/] {escape(str(exc))}")
            raise typer.Exit(code=3) from exc
    load_project_env(project)  # model keys for the drafting model and the coding agent
    try:
        config = load_project_config(project)
    except ProjectConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc
    store = ContractStore(project)
    try:
        agent = create_agent(*choose_agent(config.agent, agent_name, model))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    draft_id: Optional[str] = None
    if issue is not None:
        goal, draft_id = issue_goal(console, handoff_plan, issue, store)
    drafting = compiler_llm(project) if goal else None
    check_free_quota(console, drafting, agent, yes)

    preview: Optional[RunResult] = None
    analyzer: Optional[GoalAnalyzer] = None
    if goal:
        contract, preview, analyzer = _draft(console, project, store, goal, url, drafting, draft_id)
    else:
        try:
            contract = store.load(contract_id or "")
        except ContractError as exc:
            raise typer.BadParameter(str(exc)) from exc

    if contract.status != "approved":
        contract = _approve(console, store, contract, yes, preview, analyzer)

    settings = RunSettings(
        max_repair_rounds=rounds if rounds is not None else config.agent.max_repair_rounds,
        budget_usd=budget if budget is not None else config.agent.budget_usd,
        turn_timeout=config.agent.turn_timeout,
        judged_policy=config.gate.judged,
        replay_others=not no_replay,
    )
    outcome = execute_run(console, project, agent, contract, store, settings, url)
    handoff: Optional[Handoff] = None
    handoff_error: Optional[str] = None
    if handoff_plan is not None and outcome.terminal not in ("tampered", "cancelled"):
        with console.status("[dim]Committing the work to a branch and opening a pull request...[/dim]"):
            try:
                handoff = hand_off(handoff_plan, outcome, contract, issue=issue)
            except HandoffError as exc:
                handoff_error = str(exc)
    _render(console, outcome, handoff, handoff_error, pr)
    if open_report:
        webbrowser.open(Path(outcome.run_dir, "report.html").resolve().as_uri())
    raise typer.Exit(code=outcome.exit_code)


def execute_run(
    console: Console,
    project: Path,
    agent: CodingAgentAdapter,
    contract: Contract,
    store: ContractStore,
    settings: RunSettings,
    url: Optional[str] = None,
    on_progress: Optional[Callable[[str, str], None]] = None,
) -> RunOutcome:
    """Drive the agent to the approved contract, printing progress; Ctrl+C ends in a "cancelled" outcome."""
    others = [c for c in store.list() if c.id != contract.id and c.status == "approved"] if settings.replay_others else []
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
        if on_progress is not None:
            on_progress(kind, message)

    controller = RunController(project, agent, settings, url=url, on_event=on_event)
    try:
        outcome = asyncio.run(controller.run(contract, others))
    except KeyboardInterrupt:
        if controller.last_outcome is None:  # stopped before the first snapshot
            console.print("[yellow]Stopped.[/] Nothing was changed.")
            raise typer.Exit(code=130)
        outcome = controller.last_outcome
    finally:
        agent.close()
    return outcome


def issue_goal(console: Console, plan: Optional[HandoffPlan], number: int, store: ContractStore) -> tuple[str, str]:
    """The goal an issue describes (its title and text), and a contract id that names the issue."""
    token = github_token()
    if plan is None or plan.repo is None or token is None:
        missing = "a GitHub token (GITHUB_TOKEN, or `gh auth login`)" if token is None else "a GitHub remote"
        console.print(f"[red]Cannot read issue #{number}:[/] the project needs {missing}.")
        raise typer.Exit(code=3)
    try:
        with GitHubClient(plan.repo, token) as client:
            found = client.issue(number)
    except GitHubError as exc:
        console.print(f"[red]Cannot read issue #{number}:[/] {escape(str(exc))}")
        raise typer.Exit(code=3) from exc
    if found.get("state") == "closed":
        console.print(f"[yellow]Issue #{number} is closed;[/] working on it anyway.")
    title = str(found.get("title") or "").strip()
    body = str(found.get("body") or "").strip()
    goal = f"{title}\n\n{body[:4000]}".strip()
    console.print(f"[dim]Issue #{number} · {escape(title)} · {escape(str(found.get('html_url', '')))}[/]")
    return goal, store.unique_id(f"issue {number} {title}")


def _draft(
    console: Console,
    project: Path,
    store: ContractStore,
    goal: str,
    url: Optional[str],
    drafting: Any = None,
    contract_id: Optional[str] = None,
) -> tuple[Contract, Optional[RunResult], GoalAnalyzer]:
    analyzer = GoalAnalyzer(llm_provider=drafting)

    async def compile_contract() -> tuple[Contract, Optional[RunResult]]:
        run_dir = RunDir.create(project)
        session = VerificationSession(project, run_dir)
        cid = contract_id or store.unique_id(goal)
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
    return contract, preview, analyzer


def _approve(
    console: Console,
    store: ContractStore,
    contract: Contract,
    yes: bool,
    preview: Optional[RunResult] = None,
    analyzer: Optional[GoalAnalyzer] = None,
) -> Contract:
    console.print()
    console.print(Panel("\n".join(escape(line) for line in contract.describe_lines()), title=f"Definition of done · {contract.id}"))
    print_draft_preview(console, preview)
    if analyzer is not None:
        print_drafted_by(console, analyzer)
    warn_if_weak_draft(console, contract, analyzer.last_error if analyzer else None)
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


def check_free_quota(console: Console, drafting: Any, agent: CodingAgentAdapter, yes: bool) -> None:
    """Say before the run, not halfway through it, when OpenRouter's free requests are about to run out."""
    users = []
    if drafting is not None and getattr(drafting, "provider_name", "") == "openrouter" and discovery.is_free_model(drafting.model):
        users.append("drafting")
    if getattr(agent, "provider", "") == "openrouter" and discovery.is_free_model(getattr(agent, "model_id", "")):
        users.append("the coding agent")
    key = os.environ.get("OPENROUTER_API_KEY")
    if not users or not key:
        return
    quota = discovery.openrouter_free_quota(key)
    if quota is None or quota.remaining >= discovery.LOW_FREE_REQUESTS:
        return
    detail = (
        f"OpenRouter's free models allow {quota.limit} requests a day and {quota.remaining} are left today "
        f"(the count resets at 00:00 UTC). This run uses them for {' and '.join(users)}; a small change took "
        "about 15 in our runs, a larger one can take 40 or more."
    )
    remedy = "Buying $10 of OpenRouter credit raises the limit to 1,000 a day, or `contexer setup` picks another provider."
    if quota.remaining <= 0:
        console.print(Panel(f"{detail}\n{remedy}", title="No free requests left today", border_style="red"))
        raise typer.Exit(code=3)
    console.print(
        Panel(
            f"{detail}\nIf they run out, the run stops and keeps its best attempt. {remedy}",
            title="Few free requests left",
            border_style="yellow",
        )
    )
    if not yes and not typer.confirm("Start anyway?", default=False):
        raise typer.Exit(code=2)


def choose_agent(project: AgentSettings, flag_name: Optional[str], flag_model: Optional[str]) -> tuple[str, Optional[str]]:
    """Coding agent and model: --agent/--model, then [agent] in contexer.toml, then `contexer setup`, then Claude Code."""
    set_in_project = project.model_fields_set
    name = (
        flag_name
        or (project.name if "name" in set_in_project else None)
        or os.environ.get("CONTEXER_AGENT")
        or project.name
    )
    model = flag_model or project.model
    if model is None and name == os.environ.get("CONTEXER_AGENT"):
        model = os.environ.get("CONTEXER_AGENT_MODEL")  # saved together with that agent
    return name, model


_RATE_LIMITED = ("rate limit", "too many requests", "429")
_ACCOUNT_PROBLEMS = ("credit balance", "credits", "unauthorized", "401", "authentication", "api key", "not logged in", "login")


def agent_hint(outcome: RunOutcome) -> Optional[str]:
    """What to do when the coding agent itself could not run (no credit, not logged in)."""
    reason = " ".join([outcome.reason, *(a.agent.error or "" for a in outcome.attempts)]).lower()
    again = f"`contexer run --contract {outcome.contract_id}`"
    if "free-models-per-day" in reason:
        return (
            "OpenRouter's daily free-model requests ran out (the count resets at 00:00 UTC). Run "
            f"{again} then, buy $10 of credit for 1,000 a day, or `contexer setup` another provider."
        )
    if any(limit in reason for limit in _RATE_LIMITED):
        return f"the model's provider is rate-limiting requests. Wait a minute, then {again} continues from the approved checks."
    if outcome.terminal != "agent_error":
        return None
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


def _render(
    console: Console,
    outcome: RunOutcome,
    handoff: Optional[Handoff] = None,
    handoff_error: Optional[str] = None,
    pr: bool = False,
) -> None:
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
    if handoff is not None:
        if handoff.is_pull_request:
            kind = "Draft pull request" if handoff.draft else "Pull request"
            lines.append(f"[bold]{kind}:[/] {escape(handoff.url or '')}")
        elif handoff.url:
            lines.append(f"[bold]Open the pull request:[/] {escape(handoff.url)}")
        lines.append(f"[dim]Branch:[/] {escape(handoff.branch)} ({handoff.commit[:8]}) — you are on it now")
        if handoff.note:
            lines.append(f"[yellow]{escape(handoff.note.strip())}[/]")
    elif handoff_error:
        lines.append(f"[red]No pull request:[/] {escape(handoff_error)}")
    elif pr and outcome.terminal not in ("tampered", "cancelled"):
        lines.append("[dim]No pull request: the run left no changes.[/]")
    lines.append(f"[dim]Report:[/] {escape(str(Path(outcome.run_dir, 'report.html')))}")
    lines.append(f"[dim]{outcome.duration_seconds:.0f}s[/]")
    console.print()
    console.print(table)
    console.print(Panel("\n".join(lines), border_style=style, title="Contexer"))
