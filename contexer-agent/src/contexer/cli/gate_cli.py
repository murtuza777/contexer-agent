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
from contexer.cli import term

contract_app = typer.Typer(help="Create, review and approve acceptance contracts.", no_args_is_help=True)

_VERDICT_MARK = {"verified": "pass", "refuted": "fail", "unverified": "open"}
_METHODS = {"assertion": "[dim]proven[/]", "judgment": "[yellow]LLM-judged[/]", "heuristic": "[yellow]heuristic[/]"}

DirOption = typer.Option(Path("."), "--dir", "-d", help="Project directory.", file_okay=False)
UrlOption = typer.Option(None, "--url", "-u", help="Use an app you already run instead of starting one.")


def register(app: typer.Typer) -> None:
    from contexer.cli.bench_cli import bench
    from contexer.cli.run_cli import run
    from contexer.cli.runs_cli import restore, runs
    from contexer.cli.demo_cli import demo
    from contexer.cli.init_cli import init
    from contexer.cli.doctor_cli import doctor
    from contexer.cli.setup_cli import models, setup
    from contexer.cli.issue_cli import issue_app

    # `contexer --help` lists commands by what a person is doing, in the order they meet them.
    start, build, ci, more = "Get started", "Build and prove", "CI and GitHub", "More"
    app.command("setup", rich_help_panel=start)(setup)
    app.command("demo", rich_help_panel=start)(demo)
    app.command("doctor", rich_help_panel=start)(doctor)
    app.command("init", rich_help_panel=start)(init)
    app.command("run", rich_help_panel=build)(run)
    app.command("verify", rich_help_panel=build)(verify)
    app.add_typer(contract_app, name="contract", rich_help_panel=build)
    app.command("runs", rich_help_panel=build)(runs)
    app.command("restore", rich_help_panel=build)(restore)
    app.command("replay", rich_help_panel=ci)(replay)
    app.add_typer(issue_app, name="issue", rich_help_panel=ci)
    app.command("models", rich_help_panel=more)(models)
    app.command("bench", rich_help_panel=more)(bench)


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
        console.print(f"{term.mark('pass')} Posted [bold]contexer/acceptance[/] on {escape(target.repo)}@{target.sha[:8]}")
    except GitHubReportError as exc:
        term.note(console, "warn", f"GitHub status not posted: {escape(str(exc))}")


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
        console.print(f"  [dim]{escape(message)}[/]")

    try:
        with open_app(project, url, log_path=run.server_log, on_status=status) as app:
            term.fields(console, [("App", f"{escape(app.url)} [dim]({app.kind})[/]")])
            with console.status("[dim]Loading the app...[/dim]"):
                await session.observe(app)
            if goal:
                analyzer = GoalAnalyzer(llm_provider=llm or compiler_llm(project))
                with console.status("[dim]Compiling the goal into executable checks...[/dim]"):
                    drafted = await session.compile(goal, analyzer, store.unique_id(goal), app.repo_context)
                path = store.save(drafted)
                term.fields(console, [("Draft", escape(term.path(path)))])
                print_drafted_by(console, analyzer)
                warn_if_weak_draft(console, drafted, analyzer.last_error)
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
    term.section(console, "Tried on the app as it is now", "before any change")
    if passing:
        console.print(
            f"  {term.mark('pass')} {len(passing)} already pass [dim]· they will guard that behaviour from now on: "
            f"{escape(', '.join(r.criterion_id for r in passing))}[/]"
        )
    if failing:
        console.print(f"  {term.mark('fail')} {len(failing)} fail [dim]· the change must make them pass, or the check is wrong[/]")
        for r in failing:
            detail = r.check_result.summary() if r.check_result else r.evidence
            console.print(f"      [dim]{escape(r.criterion_id)}: {escape(detail[:160])}[/]")
    if blocked:
        console.print(
            f"  {term.mark('open')} {len(blocked)} could not run [dim]· the element is not there yet, "
            "or the check names it differently[/]"
        )
        for r in blocked:
            step = r.check_result.failed_step if r.check_result and r.check_result.failed_step else r.evidence
            console.print(f"      [dim]{escape(r.criterion_id)}: {escape(step[:160])}[/]")
    if passing and not failing and not blocked:
        console.print(
            f"  {term.mark('warn')} Every check already passes. [dim]If the goal asks for new behaviour, "
            "these checks do not test it yet.[/]"
        )


def print_drafted_by(console: Console, analyzer: GoalAnalyzer) -> None:
    """Which model wrote the checks, and say so when it is not the one that was asked."""
    asked = analyzer.llm_provider.model if analyzer.llm_provider else None
    served = analyzer.drafted_by
    if not served:
        return
    if asked and served != asked:
        term.note(
            console,
            "warn",
            f"Drafted by {escape(served)} [dim]({escape(asked)} was unavailable, so the provider fell back; "
            "review these checks with extra care or retry later)[/]",
        )
    else:
        console.print(f"[dim]Drafted by {escape(served)}[/]")


def warn_if_weak_draft(console: Console, contract: Contract, reason: Optional[str] = None) -> None:
    """Say loudly when a draft did not come from the model, and why, before anyone approves it."""
    if contract.source != "rules":
        return
    executable = sum(1 for c in contract.criteria if c.check)
    why = f"Why: {reason}\n" if reason else ""
    hint = "Retry"
    if reason and "free-models-per-day" in reason:
        hint = "OpenRouter's daily free-model limit is used up (it resets at 00:00 UTC; credits raise it). Retry later"
    elif reason and ("rate limit" in reason.lower() or "429" in reason):
        hint = "The model is rate-limited. Retry in a minute"
    console.print()
    term.note(console, "warn", "[bold yellow]Weak draft[/]")
    console.print(
        "  The model did not return usable checks, so this draft was built from simple rules and only "
        f"has {executable} executable check(s): far too few to define done."
    )
    if why:
        console.print(f"  [dim]{escape(why.strip())}[/]")
    console.print(
        f"  {escape(hint)}, use a stronger drafting model (ANTHROPIC_API_KEY or OPENAI_API_KEY, or \\[compiler] in "
        "contexer.toml), or edit the contract file and add checks before approving it."
    )


def compiler_llm(project_dir: Optional[Path] = None) -> Optional[LLMProvider]:
    """The model that compiles goals into checks: [compiler] in contexer.toml, then env, then any key."""
    from contexer.config.project import ProjectConfigError, load_project_config, load_project_env
    from contexer.config.settings import load_config
    from contexer.llm.factory import compiler_provider

    settings = None
    if project_dir is not None:
        load_project_env(project_dir)  # a model key kept in the project's .env
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
    term.header(console, "verify", project.name)
    rows = [("Goal", escape(goal))] if goal else []
    rows += [("Contract", f"{escape(c.id)} [dim]· {c.status}[/]") for c in contracts]
    term.fields(console, rows)


_CONTRACT_STATUS = {"approved": "[dim]approved[/]", "draft": "[yellow]draft[/]", "modified": "[yellow]modified since approval[/]"}


def render_result(console: Console, result: RunResult) -> None:
    for outcome in result.contracts:
        contract = outcome.contract
        term.section(console, contract.goal)
        console.print(f"[dim]{escape(contract.id)} ·[/] {_CONTRACT_STATUS[contract.status]}")
        verification = outcome.verification
        if verification is None:
            continue
        for r in verification.criteria_results:
            console.print(
                f"  {term.mark(_VERDICT_MARK[r.verdict])} {escape(r.description)} "
                f"[dim]· {escape(r.criterion_id)} ·[/] {_METHODS.get(r.method, r.method)}"
            )
            check = r.check_result
            if check is not None and not r.passed:
                for line in check.failure_report().splitlines()[1:10]:
                    style = "red" if line.strip().startswith(("actual", "uncaught", "console error")) else "dim"
                    console.print(f"      [{style}]{escape(line.strip())}[/]")
            elif check is None and not r.passed and r.evidence:
                console.print(f"      [dim]{escape(r.evidence)}[/]")
    render_decision(console, result)


def render_decision(console: Console, result: RunResult) -> None:
    """The verdict line, its reasons, and where the evidence is."""
    d = result.decision
    console.print()
    console.print(f"[bold {term.OUTCOME_STYLE[d.outcome]}]{escape(d.headline())}[/]")
    term.bullets(console, [escape(reason) for reason in d.reasons[:6]])
    if len(d.reasons) > 6:
        console.print(f"  [dim]… {len(d.reasons) - 6} more in the report[/]")
    rows: list[tuple[str, str]] = []
    drafts = [o.contract.id for o in result.contracts if o.contract.status != "approved"]
    if drafts and not result.require_approval:
        rows.append(("Approve", f"contexer contract approve {escape(drafts[0])}"))
    if result.run_dir:
        rows.append(("Report", escape(term.path(Path(result.run_dir, "report.html")))))
    rows.append(("Took", term.duration(result.duration_seconds)))
    console.print()
    term.fields(console, rows, indent=0)


def print_checklist(console: Console, contract: Contract, *, steps: bool = True) -> None:
    """A contract as a numbered checklist, each check's steps beneath it."""
    executable = sum(1 for c in contract.criteria if c.check)
    term.section(console, "Definition of done", f"{contract.id} · {executable} of {len(contract.criteria)} checks run in a browser")
    for n, criterion in enumerate(contract.criteria, 1):
        how = "" if criterion.check else " [yellow](judged by a model)[/]"
        console.print(f"  [dim]{n:>2}[/]  {escape(criterion.description)}{how}")
        if steps and criterion.check:
            for line in criterion.check.describe_lines():
                console.print(f"      [dim]{escape(line)}[/]")


# -- contract subcommands --------------------------------------------------------


@contract_app.command("list")
def contract_list(project_dir: Path = DirOption) -> None:
    """List the project's contracts and their approval status."""
    console = Console()
    contracts = ContractStore(project_dir).list()
    if not contracts:
        console.print("[dim]No contracts yet. Create one with:[/] contexer contract draft \"<goal>\"")
        return
    colors = {"approved": "dim", "draft": "yellow", "modified": "red"}
    for c in contracts:
        checks = sum(1 for crit in c.criteria if crit.check)
        console.print(
            f"[{colors[c.status]}]{c.status:<9}[/] [bold]{escape(c.id)}[/] "
            f"[dim]{checks}/{len(c.criteria)} executable ·[/] {escape(c.goal.splitlines()[0] if c.goal else '')}"
        )


@contract_app.command("show")
def contract_show(contract_id: str, project_dir: Path = DirOption) -> None:
    """Print a contract as a readable checklist."""
    console = Console()
    contract = _load_or_exit(ContractStore(project_dir), contract_id)
    console.print()
    console.print(f"[bold]{escape(contract.goal)}[/]")
    rows = [("Status", f"{contract.status} [dim]· drafted from {contract.source}[/]")]
    if contract.approval:
        a = contract.approval
        rows.append(("Approved", f"by {escape(a.by)} at {escape(a.at)} [dim]· sha256 {a.sha256[:12]}[/]"))
    term.fields(console, rows, indent=0)
    print_checklist(console, contract)


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
        f"{term.mark('pass')} Approved [bold]{escape(contract.id)}[/] as {escape(contract.approval.by)} "
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

    analyzer = GoalAnalyzer(llm_provider=compiler_llm(project_dir))

    async def _draft() -> tuple[Contract, Optional[RunResult]]:
        run = RunDir.create(project_dir)
        session = VerificationSession(project_dir, run)
        try:
            with open_app(project_dir, url) as app:
                await session.observe(app)
                drafted = await session.compile(goal, analyzer, cid, app.repo_context)
                return drafted, await preview_draft(session, app, drafted)
        except AppStartError as exc:
            term.note(console, "warn", f"{escape(str(exc))} [dim]Drafting without the live UI.[/]")
            return await session.compile(goal, analyzer, cid), None

    with console.status("[dim]Compiling the goal into checks, then trying them on the app as it is...[/dim]"):
        contract, preview = asyncio.run(_draft())
    path = store.save(contract)
    print_checklist(console, contract)
    print_draft_preview(console, preview)
    print_drafted_by(console, analyzer)
    warn_if_weak_draft(console, contract, analyzer.last_error)
    console.print()
    term.fields(
        console,
        [("Saved", escape(term.path(path))), ("Next", f"review it, then contexer contract approve {escape(contract.id)}")],
        indent=0,
    )


def _load_or_exit(store: ContractStore, ref: str) -> Contract:
    try:
        return store.load(ref)
    except ContractError as exc:
        Console(stderr=True).print(f"[red]✗[/] {escape(str(exc))}")
        raise typer.Exit(code=3) from exc
