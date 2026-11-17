"""``contexer bench``: measure catch rate and false-failure rate on seeded bugs.

Two suites share the fixtures: ``gate`` replays each app's approved contract
(the default), ``tester`` lets an agent explore each app from its goal and
replays what it reports.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from contexer.bench import AppScore, BenchReport, VariantRun, run_bench
from contexer.bench.runner import CompileStats
from contexer.cli import term


def bench(
    fixtures: Optional[Path] = typer.Option(None, "--fixtures", help="Fixtures directory (default: ./bench/fixtures)."),
    repeats: Optional[int] = typer.Option(
        None, "--repeats", "-n", min=1, help="Runs per good/benign variant (default: 3; 1 for the tester suite)."
    ),
    app: list[str] = typer.Option([], "--app", help="Only these fixture apps (repeatable)."),
    out: Optional[Path] = typer.Option(None, "--out", help="Write the full report as JSON."),
    live: bool = typer.Option(False, "--live", help="Score contracts the LLM compiles from each goal instead."),
    suite: str = typer.Option(
        "gate", "--suite", help="gate: replay each app's contract. tester: an agent explores each app from its goal."
    ),
    agent: str = typer.Option("stub", "--agent", help="The agent the tester suite measures (stub: reports nothing)."),
    steps: Optional[int] = typer.Option(None, "--steps", min=1, help="Tester suite: the most model calls per app variant."),
) -> None:
    """Run the seeded-bug benchmark against every fixture app."""
    console = Console()
    if suite not in ("gate", "tester"):
        raise typer.BadParameter(f"unknown suite '{suite}': choose gate or tester", param_hint="--suite")
    root = fixtures or _default_fixtures()
    if not root.is_dir():
        raise typer.BadParameter(
            f"no fixtures directory at {root}. The benchmark's apps live in the repository: clone "
            "https://github.com/murtuza777/contexer-agent and run it from contexer-agent/, or pass --fixtures"
        )

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
    console: Console, root: Path, repeats: int, only: list[str], out: Optional[Path], agent: str, steps: Optional[int]
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
