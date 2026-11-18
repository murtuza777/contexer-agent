"""``contexer bench``: measure catch rate and false-failure rate on seeded bugs.

Three suites share the fixtures: ``gate`` replays each app's approved contract
(the default), ``tester`` lets an agent explore each app from its goal and
replays what it reports, and ``repair`` has a coding agent fix each seeded bug
on each engine of ``contexer run``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from contexer.bench import AppScore, BenchReport, VariantRun, run_bench
from contexer.bench.runner import CompileStats
from contexer.cli import term


def bench(
    fixtures: Path | None = typer.Option(None, "--fixtures", help="Fixtures directory (default: ./bench/fixtures)."),
    repeats: int | None = typer.Option(
        None, "--repeats", "-n", min=1, help="Runs per good/benign variant (default: 3; 1 for the tester suite)."
    ),
    app: list[str] = typer.Option([], "--app", help="Only these fixture apps (repeatable)."),
    out: Path | None = typer.Option(None, "--out", help="Write the full report as JSON."),
    live: bool = typer.Option(False, "--live", help="Score contracts the LLM compiles from each goal instead."),
    suite: str = typer.Option(
        "gate",
        "--suite",
        help="gate: replay each app's contract. tester: an agent explores each app from its goal. "
        "repair: a coding agent fixes each seeded bug on each engine.",
    ),
    agent: str = typer.Option(
        "stub", "--agent", help="tester suite: the agent it measures (stub: reports nothing). repair suite: the coding agent."
    ),
    model: str | None = typer.Option(None, "--model", help="Repair suite: the coding agent's model."),
    engine: list[str] = typer.Option([], "--engine", help="Repair suite: classic and/or graph (default: both)."),
    bug: list[str] = typer.Option([], "--bug", help="Repair suite: only these bugs, as app/bug (repeatable)."),
    limit: int | None = typer.Option(None, "--limit", min=1, help="Repair suite: only the first N bugs."),
    rounds: int = typer.Option(2, "--rounds", min=0, help="Repair suite: repair rounds per bug."),
    repair_only: bool = typer.Option(
        False, "--repair-only", help="Repair suite: the first turn changes nothing, so every fix is a repair."
    ),
    steps: int | None = typer.Option(None, "--steps", min=1, help="Tester suite: the most model calls per app variant."),
) -> None:
    """Run the seeded-bug benchmark against every fixture app."""
    console = Console()
    if suite not in ("gate", "tester", "repair", "reviewer"):
        raise typer.BadParameter(f"unknown suite '{suite}': choose gate, tester, repair or reviewer", param_hint="--suite")
    root = fixtures or _default_fixtures()
    if not root.is_dir():
        raise typer.BadParameter(
            f"no fixtures directory at {root}. The benchmark's apps live in the repository: clone "
            "https://github.com/murtuza777/contexer-agent and run it from contexer-agent/, or pass --fixtures"
        )

    if suite == "reviewer":
        _bench_reviewer(console, root, app, out, agent)
        return
    if suite == "repair":
        _bench_repair(console, root, app, out, agent, model, engine, bug, limit, rounds, repair_only)
        return
    if suite == "tester":
        if live:
            raise typer.BadParameter("--live belongs to the gate suite; the tester suite takes --agent")
        _bench_tester(console, root, repeats or 1, app, out, agent, steps)
        return
    repeats = repeats or 3

    def progress(run: VariantRun) -> None:
        console.print(_run_line(run))

    llm = None
    if live:
        from contexer.cli.gate_cli import compiler_llm

        llm = compiler_llm()
        if llm is None:
            raise typer.BadParameter("--live needs a model: set ANTHROPIC_API_KEY, OPENAI_API_KEY or OPENROUTER_API_KEY")
        console.print(f"[dim]Compiling with {escape(llm.name)} · {escape(llm.model)}[/]")

    def compiled(name: str, stats: CompileStats) -> None:
        dropped = f", dropped {stats.failed_on_good} (failed on the good app)" if stats.failed_on_good else ""
        if stats.fallback:
            dropped += " — the model returned nothing usable; rule-based fallback"
        console.print(
            f"  [cyan]compiled[/] {escape(name)}: {stats.executable}/{stats.criteria} executable"
            f"{escape(dropped)} [dim]{stats.seconds:.0f}s[/]"
        )

    mode = "LLM-compiled contracts" if live else "approved contracts"
    term.header(console, "bench", f"{term.path(root)} · {mode} · {repeats} repeat(s)")
    report = asyncio.run(
        run_bench(root, repeats=repeats, only=app or None, on_run=progress, live_llm=llm, on_compiled=compiled)
    )
    render_bench(console, report)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"[dim]Report written to {escape(str(out))}[/]")
    totals = report.totals()
    invalid = any(not a.valid for a in report.apps)
    raise typer.Exit(code=1 if invalid or totals.missed or totals.false_failure_runs else 0)


def render_bench(console: Console, report: BenchReport) -> None:
    table = Table(title="Seeded-bug benchmark", show_lines=False)
    for column in ("App", "Caught", "Flagged", "Missed", "Catch rate", "False-fail runs", "False-fail checks"):
        table.add_column(column, justify="right" if column != "App" else "left")
    for score in [*report.apps, report.totals()]:
        if not score.valid:
            table.add_row(score.app, "—", "—", "—", "[red]invalid[/]", escape(score.invalid_reason), "")
            continue
        table.add_row(
            f"[bold]{score.app}[/]" if score.app == "total" else score.app,
            str(score.caught),
            str(score.flagged),
            str(score.missed),
            _pct(score.caught, score.bugs),
            f"{score.false_failure_runs}/{score.clean_runs}",
            f"{score.false_failing_checks}/{score.gating_checks_on_clean_runs}",
        )
    console.print()
    console.print(table)
    missed = report.totals().missed_bugs
    if missed:
        console.print(f"[yellow]Missed:[/] {escape(', '.join(missed))}")
    console.print(f"[dim]{report.duration_seconds:.0f}s[/]")


def _bench_tester(
    console: Console, root: Path, repeats: int, only: list[str], out: Path | None, agent: str, steps: int | None
) -> None:
    from contexer.bench.tester import TESTER_AGENTS, TesterRun, results_markdown, run_tester_bench

    if agent not in TESTER_AGENTS:
        raise typer.BadParameter(
            f"no tester agent named '{agent}'. Available: {', '.join(TESTER_AGENTS)}", param_hint="--agent"
        )

    def progress(run: TesterRun) -> None:
        console.print(_tester_line(run))

    term.header(console, "bench", f"{term.path(root)} · tester suite · agent {agent} · {repeats} repeat(s)")
    tester = TESTER_AGENTS[agent]()
    if steps is not None and hasattr(tester, "max_steps"):
        tester.max_steps = steps  # type: ignore[attr-defined]
    if out is not None and hasattr(tester, "keep_dir"):
        # The agent's transcripts, next to the report: they say why a bug was missed.
        tester.keep_dir = out.parent / f"{out.stem}-transcripts"  # type: ignore[attr-defined]
    report = asyncio.run(run_tester_bench(root, tester, repeats=repeats, only=only or None, on_run=progress))

    table = Table(title="Tester benchmark", show_lines=False)
    for column in ("App", "Bugs", "Found", "False alarms", "Rejected", "Unconfirmed", "Steps", "Tokens in/out", "Cost"):
        table.add_column(column, justify="right" if column != "App" else "left")
    totals = report.totals()
    for score in [*report.apps, totals]:
        table.add_row(
            "[bold]total[/]" if score is totals else escape(score.app),
            str(score.bugs),
            str(score.found),
            str(score.false_alarms),
            str(score.rejected),
            str(score.unconfirmed),
            str(score.steps),
            f"{score.tokens_in:,} / {score.tokens_out:,}",
            f"${score.cost_usd:.2f}" if score.cost_usd is not None else "—",
        )
    console.print()
    console.print(table)
    console.print(
        f"{totals.found} of {totals.bugs} seeded bugs found · {totals.false_alarms} false alarms · {totals.rejected} rejected · "
        f"{totals.unconfirmed} unconfirmed · [dim]{report.duration_seconds:.0f}s[/]"
    )
    if totals.errors:
        console.print(f"[red]{totals.errors} run(s) not scored: the app did not start, or the agent failed.[/]")
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"[dim]Report written to {escape(str(out))}[/]")
    # Next to bench/RESULTS.md, when the fixtures are the repository's own.
    if (root.parent / "RESULTS.md").is_file() and not only:
        page = root.parent / "tester-results" / f"{agent}.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(results_markdown(report), encoding="utf-8", newline="\n")
        console.print(f"[dim]Results written to {escape(term.path(page))}[/]")
    # A measurement, not a gate: it fails only when it could not measure.
    raise typer.Exit(code=1 if totals.errors else 0)


def _bench_reviewer(console: Console, root: Path, only: list[str], out: Path | None, agent: str) -> None:
    from contexer.bench.reviewer import CaseRun, results_markdown, run_reviewer_bench
    from contexer.cli import run_cli
    from contexer.config.project import load_project_env
    from contexer.llm.chat import describe_model

    if agent not in ("scan", "reviewer"):
        raise typer.BadParameter("the reviewer suite takes --agent scan (no model) or --agent reviewer", param_hint="--agent")
    cases = root.parent / "reviewer"
    model = None
    if agent == "reviewer":
        load_project_env(Path.cwd())
        model = run_cli.crew_model(Path.cwd())
        if model is None:
            raise typer.BadParameter("--agent reviewer needs a model: run `contexer setup`, or use --agent scan", param_hint="--agent")

    def progress(run: CaseRun) -> None:
        if run.planted:
            mark = f"[green]flagged[/] [dim]by {run.flagged_by}[/]" if run.flagged else "[red]not flagged[/]"
        else:
            mark = f"[red]{run.false_high} false high[/]" if run.false_high else "[green]quiet[/]"
        console.print(f"  {mark} {escape(run.name)} [dim]{len(run.notes)} note(s) {run.seconds:.0f}s[/]")

    term.header(console, "bench", f"{term.path(cases)} · reviewer suite · {agent}")
    try:
        report = asyncio.run(run_reviewer_bench(cases, model, only=only or None, on_case=progress))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    report.model = describe_model(model) if model is not None else ""
    console.print()
    console.print(
        f"Planted issues flagged: [bold]{report.flagged}/{report.planted}[/] · clean diffs with a false high-severity note: "
        f"[bold]{report.clean_with_high}/{report.clean}[/]"
    )
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        out.with_suffix(".md").write_text(results_markdown(report), encoding="utf-8", newline=chr(10))
        console.print(f"[dim]Report written to {escape(str(out))} and {escape(str(out.with_suffix('.md')))}[/]")
    if not only:  # a run of the whole suite is the published result
        page = root.parent / "reviewer-results" / f"{agent}.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(results_markdown(report), encoding="utf-8", newline=chr(10))


def _bench_repair(
    console: Console,
    root: Path,
    only: list[str],
    out: Path | None,
    agent: str,
    model: str | None,
    engines: list[str],
    bugs: list[str],
    limit: int | None,
    rounds: int,
    repair_only: bool,
) -> None:
    from contexer.agents import create_agent
    from contexer.bench.repair import ENGINES, RepairRun, results_markdown, run_repair_bench
    from contexer.cli import run_cli
    from contexer.config.project import load_project_env
    from contexer.llm.chat import describe_model

    if agent == "stub":
        raise typer.BadParameter("the repair suite needs a coding agent: --agent claude-code, codex or opencode", param_hint="--agent")
    try:
        create_agent(agent, model).close()  # refuse a name or a turns file that cannot work before anything runs
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--agent") from exc
    load_project_env(Path.cwd())
    crew = run_cli.crew_model(Path.cwd())

    def progress(run: RepairRun) -> None:
        mark = "[green]fixed[/]" if run.fixed else f"[red]{escape(run.terminal)}[/]"
        cost = f" ${run.cost_usd:.2f}" if run.cost_usd else ""
        moves = f" [dim]({escape(', '.join(run.moves))})[/]" if run.moves else ""
        console.print(
            f"  {mark} {escape(run.app)}/{escape(run.bug)} [dim]on[/] {run.engine} · {run.attempts} attempt(s){moves} "
            f"[dim]{run.duration_seconds:.0f}s{cost}[/]"
        )

    chosen = engines or list(ENGINES)
    mode = "repair only" if repair_only else "from the first turn"
    term.header(console, "bench", f"{term.path(root)} · repair suite · {agent} · {' and '.join(chosen)} · {mode}")
    try:
        report = asyncio.run(
            run_repair_bench(
                root,
                lambda: create_agent(agent, model),
                engines=chosen,
                only=only or None,
                bugs=bugs or None,
                limit=limit,
                rounds=rounds,
                repair_only=repair_only,
                model=crew,
                on_run=progress,
            )
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    report.agent = f"{agent} ({model})" if model else agent
    report.crew_model = describe_model(crew) if crew is not None else ""

    table = Table(title="Repair benchmark", show_lines=False)
    for column in ("Engine", "Bugs", "Fixed", "First try", "After a repair", "Attempts", "Minutes", "Agent cost"):
        table.add_column(column, justify="right" if column != "Engine" else "left")
    for score in report.scores:
        table.add_row(
            score.engine,
            str(score.bugs),
            str(score.fixed),
            str(score.first_try),
            str(score.after_repair),
            str(score.attempts),
            f"{score.seconds / 60:.1f}",
            f"${score.cost_usd:.2f}" if score.cost_usd else "—",
        )
    console.print()
    console.print(table)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        out.with_suffix(".md").write_text(results_markdown(report), encoding="utf-8")
        console.print(f"[dim]Report written to {escape(str(out))} and {escape(str(out.with_suffix('.md')))}[/]")


def _tester_line(run: object) -> str:
    from contexer.bench.tester import TesterRun

    assert isinstance(run, TesterRun)
    label = f"{run.app}/{run.kind}/{run.name}" + (f" #{run.repeat + 1}" if run.kind != "bug" else "")
    from contexer.bench.tester import NOT_SCORED

    if run.error.startswith(NOT_SCORED):
        return f"  [red]error[/] {escape(label)} [dim]{escape(run.error.splitlines()[0])}[/]"
    if run.kind == "bug":
        mark = "[green]found[/]" if run.found else "[yellow]not found[/]"
    else:
        mark = "[red]false alarm[/]" if run.false_alarms else "[green]clean[/]"
    detail = f"{run.findings} finding(s)"
    if run.rejected:
        detail += f", {len(run.rejected)} rejected"
    if run.unconfirmed:
        detail += f", {len(run.unconfirmed)} unconfirmed"
    return f"  {mark} {escape(label)} [dim]{detail} · {run.steps} steps · {run.duration_seconds:.1f}s[/]"


def _run_line(run: VariantRun) -> str:
    label = f"{run.app}/{run.kind}/{run.name}" + (f" #{run.repeat + 1}" if run.kind != "bug" else "")
    if run.kind == "bug":
        style = {"caught": "green", "flagged": "yellow", "missed": "red"}[run.bug_verdict or "missed"]
        detail = f"refuted {run.refuted}" if run.refuted else (f"unverified {run.unverified}" if run.unverified else "")
        if not detail and run.error:
            detail = f"error: {run.error.splitlines()[0]}"
        expected = ""
        if run.expected_catcher and run.bug_verdict == "caught" and not run.caught_by_expected:
            expected = f" [dim](expected {run.expected_catcher})[/]"
        return f"  [{style}]{run.bug_verdict}[/] {escape(label)} [dim]{escape(detail)}[/]{expected} [dim]{run.duration_seconds:.1f}s[/]"
    clean = run.outcome == "pass" and not run.refuted and not run.unverified
    mark = "[green]clean[/]" if clean else "[red]false failure[/]"
    detail = "" if clean else f" refuted {run.refuted} unverified {run.unverified}"
    if run.error:
        detail += f" error: {run.error.splitlines()[0]}"
    return f"  {mark} {escape(label)}[dim]{escape(detail)} {run.duration_seconds:.1f}s[/]"


def _pct(n: int, d: int) -> str:
    return f"{100 * n / d:.0f}%" if d else "—"


def _default_fixtures() -> Path:
    local = Path("bench") / "fixtures"
    if local.is_dir():
        return local
    # Editable install: <repo>/contexer-agent/src/contexer/cli -> <repo>/contexer-agent/bench/fixtures
    return Path(__file__).resolve().parents[3] / "bench" / "fixtures"


__all__ = ["AppScore", "bench", "render_bench"]
