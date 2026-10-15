"""``contexer bench``: measure catch rate and false-failure rate on seeded bugs."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from contexer.bench import AppScore, BenchReport, VariantRun, run_bench


def bench(
    fixtures: Optional[Path] = typer.Option(None, "--fixtures", help="Fixtures directory (default: ./bench/fixtures)."),
    repeats: int = typer.Option(3, "--repeats", "-n", min=1, help="Runs per good/benign variant."),
    app: list[str] = typer.Option([], "--app", help="Only these fixture apps (repeatable)."),
    out: Optional[Path] = typer.Option(None, "--out", help="Write the full report as JSON."),
) -> None:
    """Run the seeded-bug benchmark against every fixture app."""
    console = Console()
    root = fixtures or _default_fixtures()
    if not root.is_dir():
        raise typer.BadParameter(f"no fixtures directory at {root}")

    def progress(run: VariantRun) -> None:
        console.print(_run_line(run))

    console.print(f"[bold bright_cyan]Contexer bench[/] [dim]· {escape(str(root))} · {repeats} repeat(s)[/]")
    report = asyncio.run(run_bench(root, repeats=repeats, only=app or None, on_run=progress))
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


def _run_line(run: VariantRun) -> str:
    label = f"{run.app}/{run.kind}/{run.name}" + (f" #{run.repeat + 1}" if run.kind != "bug" else "")
    if run.kind == "bug":
        style = {"caught": "green", "flagged": "yellow", "missed": "red"}[run.bug_verdict or "missed"]
        detail = f"refuted {run.refuted}" if run.refuted else (f"unverified {run.unverified}" if run.unverified else "")
        expected = ""
        if run.expected_catcher and run.bug_verdict == "caught" and not run.caught_by_expected:
            expected = f" [dim](expected {run.expected_catcher})[/]"
        return f"  [{style}]{run.bug_verdict}[/] {escape(label)} [dim]{escape(detail)}[/]{expected} [dim]{run.duration_seconds:.1f}s[/]"
    clean = not run.refuted and not run.unverified
    mark = "[green]clean[/]" if clean else "[red]false failure[/]"
    detail = "" if clean else f" refuted {run.refuted} unverified {run.unverified}"
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
