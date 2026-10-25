"""Non-interactive commands: verify, replay and contract management.

These are what CI and scripts call. Exit codes are part of the interface:
0 pass, 1 fail, 2 needs action, 3 error.
"""

from __future__ import annotations

import asyncio
import sys
import webbrowser
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel

from contexer.appserver import AppStartError, RunningApp, open_app
from contexer.contract import Contract, ContractError, ContractStore
from contexer.evidence import RunDir, write_evidence
from contexer.evidence.report import result_json
from contexer.gate import GateDecision, RunResult
from contexer.gate.session import VerificationSession
from contexer.llm.base import LLMProvider
from contexer.verification.runner import CheckRunner
from contexer.verification.verifier import Verifier
from contexer.workflow.criteria import GoalAnalyzer

contract_app = typer.Typer(help="Create, review and approve acceptance contracts.", no_args_is_help=True)

_ICONS = {"verified": "[green]✓[/]", "refuted": "[red]✗[/]", "unverified": "[yellow]?[/]"}
_METHODS = {"assertion": "[green]proven[/]", "judgment": "[yellow]LLM-judged[/]", "heuristic": "[yellow]heuristic[/]"}
_OUTCOME_STYLE = {"pass": "green", "fail": "red", "needs_action": "yellow", "error": "red"}

DirOption = typer.Option(Path("."), "--dir", "-d", help="Project directory.", file_okay=False)
UrlOption = typer.Option(None, "--url", "-u", help="Use an app you already run instead of starting one.")


def register(app: typer.Typer) -> None:
    from contexer.cli.bench_cli import bench
    from contexer.cli.run_cli import run
    from contexer.cli.runs_cli import runs
    from contexer.cli.demo_cli import demo
    from contexer.cli.init_cli import init
    from contexer.cli.doctor_cli import doctor

    app.command("run")(run)
    app.command("verify")(verify)
    app.command("replay")(replay)
    app.add_typer(contract_app, name="contract")
    app.command("bench")(bench)
    app.command("runs")(runs)
    app.command("demo")(demo)
    app.command("init")(init)
    app.command("doctor")(doctor)


# -- verify / replay -----------------------------------------------------------


def verify(
    goal: Optional[str] = typer.Argument(None, help="Compile this goal into a draft contract and verify it."),
    contract: list[str] = typer.Option([], "--contract", "-c", help="Contract id or file to verify (repeatable)."),
    all_contracts: bool = typer.Option(False, "--all", "-a", help="Verify every contract in the project."),
    project_dir: Path = DirOption,
    url: Optional[str] = UrlOption,
    judged: str = typer.Option("advisory", "--judged", help="LLM-judged criteria: advisory or block."),
    trace: str = typer.Option("off", "--trace", help="Playwright traces: off, on-failure or on."),
    json_output: bool = typer.Option(False, "--json", help="Print result.json to stdout."),
    open_report: bool = typer.Option(False, "--open", help="Open the HTML report when done."),
    github: bool = typer.Option(False, "--github", help="Post a contexer/acceptance commit status (needs GITHUB_TOKEN)."),
) -> None:
    """Prove the running app against contracts; exit 0 pass, 1 fail, 2 needs action, 3 error."""
    if not goal and not contract and not all_contracts:
        raise typer.BadParameter("give a GOAL, --contract ID, or --all")
    if judged not in ("advisory", "block"):
        raise typer.BadParameter("--judged must be 'advisory' or 'block'")
    if trace not in ("off", "on", "on-failure"):
        raise typer.BadParameter("--trace must be 'off', 'on' or 'on-failure'")
    console = Console(stderr=json_output)
    result = asyncio.run(
        run_verification(
            project_dir,
            goal=goal,
            contract_refs=contract,
            all_contracts=all_contracts,
            url=url,
            judged=judged,  # type: ignore[arg-type]
            trace=trace,  # type: ignore[arg-type]
            console=console,
        )
    )
    _report_to_github(result, console, project_dir, post=github)
    _finish(result, console, json_output, open_report)


def replay(
    project_dir: Path = DirOption,
    url: Optional[str] = UrlOption,
    judged: str = typer.Option("advisory", "--judged", help="LLM-judged criteria: advisory or block."),
    trace: str = typer.Option("on-failure", "--trace", help="Playwright traces: off, on-failure or on."),
    json_output: bool = typer.Option(False, "--json", help="Print result.json to stdout."),
    open_report: bool = typer.Option(False, "--open", help="Open the HTML report when done."),
    github: bool = typer.Option(False, "--github", help="Post a contexer/acceptance commit status (needs GITHUB_TOKEN)."),
) -> None:
    """Replay every approved contract with no LLM calls (the CI gate)."""
    verify(
        goal=None,
        contract=[],
        all_contracts=True,
        project_dir=project_dir,
        url=url,
        judged=judged,
        trace=trace,
        json_output=json_output,
        open_report=open_report,
        github=github,
    )


def _report_to_github(result: RunResult, console: Console, project_dir: Path, *, post: bool) -> None:
    from contexer.github import GitHubReportError, detect_target, post_status, write_step_summary

    summary = write_step_summary(result)
    if summary is not None:
        console.print(f"[dim]Job summary written to {escape(str(summary))}[/]")
    if not post:
        return
    try:
        target = detect_target(project_dir)
        post_status(target, result.decision)
        console.print(f"[green]✓[/] Posted [bold]contexer/acceptance[/] on {escape(target.repo)}@{target.sha[:8]}")
    except GitHubReportError as exc:
        console.print(f"[yellow]![/] GitHub status not posted: {escape(str(exc))}")


async def run_verification(
    project_dir: Path,
    *,
    goal: Optional[str] = None,
    contract_refs: Optional[list[str]] = None,
    all_contracts: bool = False,
    url: Optional[str] = None,
    judged: str = "advisory",
    trace: str = "off",
    console: Optional[Console] = None,
    llm: Optional[LLMProvider] = None,
) -> RunResult:
    """Resolve contracts, start the app, verify, and write the evidence."""
    console = console or Console()
    project = project_dir.resolve()
    store = ContractStore(project)
    contracts = _resolve_contracts(store, contract_refs or [], all_contracts)

    run = RunDir.create(project)
    runner = CheckRunner(trace=trace)  # type: ignore[arg-type]
    session = VerificationSession(project, run, verifier=Verifier(llm_provider=None, runner=runner))
    _print_start(console, project, goal, contracts)

    def status(message: str) -> None:
        console.print(f"[dim]›[/] {escape(message)}")

    try:
        with open_app(project, url, log_path=run.server_log, on_status=status) as app:
            console.print(f"[dim]App:[/] {escape(app.url)} [dim]({app.kind})[/]")
            with console.status("[dim]Loading the app...[/dim]"):
                await session.observe(app)
            if goal:
                analyzer = GoalAnalyzer(llm_provider=llm or compiler_llm(project))
                with console.status("[dim]Compiling the goal into executable checks...[/dim]"):
                    drafted = await session.compile(goal, analyzer, store.unique_id(goal), app.repo_context)
                path = store.save(drafted)
                console.print(f"[dim]Draft contract:[/] {escape(str(path))}")
                warn_if_weak_draft(console, drafted)
                contracts = [drafted, *contracts]
            with console.status(f"[dim]Running {sum(len(c.criteria) for c in contracts)} checks in Chromium...[/dim]"):
                result = await session.verify(
                    app,
                    contracts,
                    require_approval=not goal,
                    judged_policy=judged,  # type: ignore[arg-type]
                )
    except AppStartError as exc:
        decision = GateDecision(outcome="error", reasons=[str(exc)])
        result = session.result(None, [], decision, require_approval=not goal, error=str(exc))
        result.server_log_tail = exc.log_tail

    write_evidence(result, run)
    render_result(console, result)
    return result


def _resolve_contracts(store: ContractStore, refs: list[str], all_contracts: bool) -> list[Contract]:
    try:
        contracts = [store.load(ref) for ref in refs]
        if all_contracts:
            known = {c.id for c in contracts}
            contracts.extend(c for c in store.list() if c.id not in known)
    except ContractError as exc:
        raise typer.BadParameter(str(exc)) from exc
    return contracts


async def preview_draft(session: VerificationSession, app: RunningApp, contract: Contract) -> Optional[RunResult]:
    """Run a draft's checks once on the app as it is now, so its reviewer sees how they fare."""
    if not any(c.check for c in contract.criteria):
        return None
    try:
        return await session.verify(app, [contract], require_approval=False)
    except Exception:  # a preview must never cost the user their draft
        return None


def print_draft_preview(console: Console, result: Optional[RunResult]) -> None:
    """Facts for the person approving a draft: which checks already pass, fail, or cannot run yet."""
    if result is None or result.decision.outcome == "error":
        return
    executed = [
        r
        for o in result.contracts
        for r in (o.verification.criteria_results if o.verification else [])
        if r.check_result is not None
    ]
    if not executed:
        return
    passing = [r for r in executed if r.verdict == "verified"]
    failing = [r for r in executed if r.verdict == "refuted"]
    blocked = [r for r in executed if r.verdict == "unverified"]
    console.print("[bold]Tried on the app as it is now[/] [dim](before any change)[/]")
    if passing:
        console.print(
            f"  [green]✓ {len(passing)} already pass[/] [dim]and will guard that behaviour from now on: "
            f"{escape(', '.join(r.criterion_id for r in passing))}[/]"
        )
    if failing:
        console.print(f"  [red]✗ {len(failing)} fail[/] [dim]: the change must make these pass, or the check is wrong[/]")
        for r in failing:
            detail = r.check_result.summary() if r.check_result else r.evidence
            console.print(f"    [dim]{escape(r.criterion_id)}: {escape(detail[:160])}[/]")
    if blocked:
        console.print(
            f"  [yellow]? {len(blocked)} could not run[/] [dim]: the element is not there yet, "
            "or the check names it differently[/]"
        )
        for r in blocked:
            step = r.check_result.failed_step if r.check_result and r.check_result.failed_step else r.evidence
            console.print(f"    [dim]{escape(r.criterion_id)}: {escape(step[:160])}[/]")
    if passing and not failing and not blocked:
        console.print(
            "  [yellow]Every check already passes.[/] [dim]If the goal asks for new behaviour, "
            "these checks do not test it yet.[/]"
        )
    console.print()


def warn_if_weak_draft(console: Console, contract: Contract) -> None:
    """Say loudly when a draft did not come from the model, before anyone approves it."""
    if contract.source != "rules":
        return
    executable = sum(1 for c in contract.criteria if c.check)
    console.print(
        Panel(
            "The model did not return usable checks, so this draft was built from simple rules and only "
            f"has {executable} executable check(s) — far too few to define done.\n"
            "Retry, use a stronger drafting model (ANTHROPIC_API_KEY or OPENAI_API_KEY, or [compiler] in "
            "contexer.toml), or edit the contract file and add checks before approving it.",
            title="Weak draft",
            border_style="yellow",
        )
    )


def compiler_llm(project_dir: Optional[Path] = None) -> Optional[LLMProvider]:
    """The model that compiles goals into checks: [compiler] in contexer.toml, then env, then any key."""
    from contexer.config.project import ProjectConfigError, load_project_config
    from contexer.config.settings import load_config
    from contexer.llm.factory import compiler_provider

    settings = None
    if project_dir is not None:
        try:
            settings = load_project_config(project_dir).compiler
        except ProjectConfigError:
            settings = None
    try:
        return compiler_provider(load_config(), settings)
    except Exception:
        return None



def _finish(result: RunResult, console: Console, json_output: bool, open_report: bool) -> None:
    if json_output:
        sys.stdout.write(result_json(result) + "\n")
    if open_report and result.run_dir:
        webbrowser.open(Path(result.run_dir, "report.html").resolve().as_uri())
    raise typer.Exit(code=result.decision.exit_code)


# -- rendering -----------------------------------------------------------------


def _print_start(console: Console, project: Path, goal: Optional[str], contracts: list[Contract]) -> None:
    console.print()
    console.print(f"[bold bright_cyan]Contexer verify[/] [dim]·[/] {escape(project.name)}")
    if goal:
        console.print(f"[dim]Goal:[/] {escape(goal)}")
    for c in contracts:
        console.print(f"[dim]Contract:[/] {escape(c.id)} [dim]({c.status})[/]")


def render_result(console: Console, result: RunResult) -> None:
    for outcome in result.contracts:
        contract = outcome.contract
        console.print()
        status = {"approved": "[green]approved[/]", "draft": "[yellow]draft[/]", "modified": "[yellow]modified[/]"}
        console.print(f"[bold]{escape(contract.goal)}[/] [dim]{escape(contract.id)} ·[/] {status[contract.status]}")
        verification = outcome.verification
        if verification is None:
            continue
        for r in verification.criteria_results:
            console.print(
                f"  {_ICONS[r.verdict]} [bold]{escape(r.criterion_id)}[/] {escape(r.description)} "
                f"[dim]·[/] {_METHODS.get(r.method, r.method)}"
            )
            check = r.check_result
            if check is not None and not r.passed:
                for line in check.failure_report().splitlines()[1:10]:
                    console.print(f"      [red]{escape(line.rstrip())}[/]")
            elif check is None and not r.passed and r.evidence:
                console.print(f"      [dim]{escape(r.evidence)}[/]")

    d = result.decision
    style = _OUTCOME_STYLE[d.outcome]
    lines = [f"[bold {style}]{escape(d.headline())}[/]"]
    lines.extend(f"• {escape(reason)}" for reason in d.reasons[:6])
    if len(d.reasons) > 6:
        lines.append(f"[dim]… {len(d.reasons) - 6} more in the report[/]")
    drafts = [o.contract.id for o in result.contracts if o.contract.status != "approved"]
    if drafts and not result.require_approval:
        lines.append(f"[dim]Approve to lock it in:[/] contexer contract approve {escape(drafts[0])}")
    if result.run_dir:
        lines.append(f"[dim]Report:[/] {escape(str(Path(result.run_dir, 'report.html')))}")
    lines.append(f"[dim]{result.duration_seconds:.1f}s[/]")
    console.print()
    console.print(Panel("\n".join(lines), border_style=style, title="Contexer"))


# -- contract subcommands --------------------------------------------------------


@contract_app.command("list")
def contract_list(project_dir: Path = DirOption) -> None:
    """List the project's contracts and their approval status."""
    console = Console()
    contracts = ContractStore(project_dir).list()
    if not contracts:
        console.print("[dim]No contracts yet. Create one with:[/] contexer contract draft \"<goal>\"")
        return
    colors = {"approved": "green", "draft": "yellow", "modified": "red"}
    for c in contracts:
        checks = sum(1 for crit in c.criteria if crit.check)
        console.print(
            f"[{colors[c.status]}]{c.status:<9}[/] [bold]{escape(c.id)}[/] "
            f"[dim]{checks}/{len(c.criteria)} executable ·[/] {escape(c.goal)}"
        )


@contract_app.command("show")
def contract_show(contract_id: str, project_dir: Path = DirOption) -> None:
    """Print a contract as a readable checklist."""
    console = Console()
    contract = _load_or_exit(ContractStore(project_dir), contract_id)
    console.print(f"[bold]{escape(contract.goal)}[/]")
    console.print(f"[dim]{escape(contract.id)} · {contract.status} · source {contract.source}[/]")
    if contract.approval:
        a = contract.approval
        console.print(f"[dim]approved by {escape(a.by)} at {escape(a.at)} · sha256 {a.sha256[:12]}[/]")
    console.print()
    for line in contract.describe_lines():
        console.print(escape(line))


@contract_app.command("approve")
def contract_approve(
    contract_id: str,
    project_dir: Path = DirOption,
    by: Optional[str] = typer.Option(None, "--by", help="Approver name (default: git user.name)."),
) -> None:
    """Approve a contract at its current content; later edits will need re-approval."""
    console = Console()
    store = ContractStore(project_dir)
    _load_or_exit(store, contract_id)
    contract = store.approve(contract_id, by)
    assert contract.approval is not None
    console.print(
        f"[green]✓[/] Approved [bold]{escape(contract.id)}[/] as {escape(contract.approval.by)} "
        f"[dim](sha256 {contract.approval.sha256[:12]})[/]"
    )
    console.print(f"[dim]Commit {escape(str(store.path_for(contract.id)))} so the gate replays it.[/]")


@contract_app.command("draft")
def contract_draft(
    goal: str,
    project_dir: Path = DirOption,
    url: Optional[str] = UrlOption,
    contract_id: Optional[str] = typer.Option(None, "--id", help="Contract id (default: from the goal)."),
) -> None:
    """Compile a goal into a draft contract grounded in the running app's UI."""
    console = Console()
    store = ContractStore(project_dir)
    cid = contract_id or store.unique_id(goal)

    async def _draft() -> tuple[Contract, Optional[RunResult]]:
        run = RunDir.create(project_dir)
        session = VerificationSession(project_dir, run)
        analyzer = GoalAnalyzer(llm_provider=compiler_llm(project_dir))
        try:
            with open_app(project_dir, url) as app:
                await session.observe(app)
                drafted = await session.compile(goal, analyzer, cid, app.repo_context)
                return drafted, await preview_draft(session, app, drafted)
        except AppStartError as exc:
            console.print(f"[yellow]![/] {escape(str(exc))} [dim]Drafting without the live UI.[/]")
            return await session.compile(goal, analyzer, cid), None

    with console.status("[dim]Compiling the goal into checks, then trying them on the app as it is...[/dim]"):
        contract, preview = asyncio.run(_draft())
    path = store.save(contract)
    for line in contract.describe_lines():
        console.print(escape(line))
    console.print()
    print_draft_preview(console, preview)
    warn_if_weak_draft(console, contract)
    console.print(f"[dim]Saved draft:[/] {escape(str(path))}")
    console.print(f"[dim]Review it, then:[/] contexer contract approve {escape(contract.id)}")


def _load_or_exit(store: ContractStore, ref: str) -> Contract:
    try:
        return store.load(ref)
    except ContractError as exc:
        Console(stderr=True).print(f"[red]✗[/] {escape(str(exc))}")
        raise typer.Exit(code=3) from exc
