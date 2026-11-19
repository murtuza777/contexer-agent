"""``contexer runs``: what was verified or built here, newest first, with links to the evidence.

``contexer restore`` puts the files back to a snapshot one of those runs took.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

import typer
from pydantic import BaseModel, Field
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from contexer.checkpoint import ShadowRepo
from contexer.cli import term
from contexer.contract.store import CONTEXER_DIR
from contexer.evidence.rundir import RUNS_DIR

_STYLE = {
    "pass": "green",
    "succeeded": "green",
    "fail": "red",
    "failed_checks": "red",
    "error": "red",
    "agent_error": "red",
    "app_error": "red",
    "tampered": "red",
}


def runs(
    project_dir: Path = typer.Option(Path("."), "--dir", "-d", help="Project directory.", file_okay=False),
    limit: int = typer.Option(15, "--limit", "-n", min=1, help="How many runs to show."),
    stats: bool = typer.Option(False, "--stats", help="How the agent runs in this project ended, and what they cost."),
) -> None:
    """List recent verifications and agent runs with their outcome and report path."""
    console = Console()
    if stats:
        _print_stats(console, run_stats(project_dir.resolve()))
        return
    root = project_dir.resolve() / CONTEXER_DIR / RUNS_DIR
    rows = [row for row in (_summarise(d) for d in sorted(root.glob("*"), reverse=True) if d.is_dir()) if row]
    if not rows:
        console.print("[dim]No runs yet. Try:[/] contexer verify --all")
        return
    table = Table(box=None, header_style="dim", pad_edge=False)
    for column in ("run", "kind", "outcome", "checks", "detail", "report"):
        table.add_column(column)
    for row in rows[:limit]:
        style = _STYLE.get(row["outcome"], "yellow")
        table.add_row(
            row["run_id"],
            row["kind"],
            f"[{style}]{escape(row['outcome'])}[/]",
            row["checks"],
            escape(row["detail"]),
            escape(row["report"]),
        )
    console.print(table)


class RunStats(BaseModel):
    """What the agent runs kept in a project's ``.contexer/runs`` add up to. Read from files; nothing is sent anywhere."""

    runs: int = 0
    succeeded: int = 0
    first_try: int = 0
    endings: dict[str, int] = Field(default_factory=dict)
    attempts_per_success: float = 0.0
    # The coding agent's spend plus what Contexer's own agents cost, where that is known.
    cost_usd: float = 0.0
    cost_per_success: float | None = None
    spent_without_proof: float = 0.0
    runs_with_high_note: int = 0
    median_seconds: float = 0.0


def run_stats(project: Path) -> RunStats:
    """Outcome numbers for every agent run (``run.json``) in the project. Verifications alone are not counted."""
    found = [data for d in sorted((project / CONTEXER_DIR / RUNS_DIR).glob("*")) if d.is_dir() and (data := _load(d / "run.json"))]
    stats = RunStats(runs=len(found))
    if not found:
        return stats
    proven = [r for r in found if r.get("terminal") == "succeeded"]
    stats.succeeded = len(proven)
    for run in found:
        ending = str(run.get("terminal") or "unknown")
        stats.endings[ending] = stats.endings.get(ending, 0) + 1
    stats.endings = dict(sorted(stats.endings.items(), key=lambda item: (-item[1], item[0])))
    stats.first_try = sum(1 for r in proven if len(r.get("attempts") or []) == 1)
    if proven:
        stats.attempts_per_success = round(sum(len(r.get("attempts") or []) for r in proven) / len(proven), 2)

    def spent(run: dict[str, Any]) -> float:
        return float(run.get("cost_usd") or 0.0) + float(run.get("crew_cost_usd") or 0.0)

    stats.cost_usd = round(sum(spent(r) for r in found), 2)
    stats.cost_per_success = round(stats.cost_usd / len(proven), 2) if proven else None
    stats.spent_without_proof = round(sum(spent(r) for r in found if r.get("terminal") != "succeeded"), 2)
    stats.runs_with_high_note = sum(1 for r in found if any(n.get("severity") == "high" for n in r.get("review") or []))
    stats.median_seconds = float(statistics.median(float(r.get("duration_seconds") or 0.0) for r in found))
    return stats


def _print_stats(console: Console, stats: RunStats) -> None:
    if not stats.runs:
        console.print("[dim]No agent runs in this project yet. Try:[/] contexer run \"what should be true\"")
        return
    console.print(f"[bold]{stats.succeeded} of {stats.runs} runs ended with every check proven[/]")
    rows = [("How runs ended", " · ".join(f"{name} {count}" for name, count in stats.endings.items()))]
    if stats.succeeded:
        rows.append(
            ("When proven", f"{stats.first_try} at the first attempt · {stats.attempts_per_success:g} attempts on average")
        )
    cost = f"${stats.cost_usd:.2f} in all"
    if stats.cost_per_success is not None:
        cost += f" · ${stats.cost_per_success:.2f} per proven run"
    if stats.spent_without_proof:
        cost += f" · ${stats.spent_without_proof:.2f} spent on runs that proved nothing"
    rows.append(("Cost", cost))
    rows.append(("Review", f"{stats.runs_with_high_note} run(s) with a high-severity note"))
    rows.append(("Typical run", term.duration(stats.median_seconds)))
    term.fields(console, rows)
    console.print("[dim]Counted from run.json in .contexer/runs; a provider that reports no price counts as $0 unless rates are set.[/]")


def _summarise(run_dir: Path) -> dict[str, str] | None:
    result = _load(run_dir / "result.json")
    run = _load(run_dir / "run.json")
    if result is None and run is None:
        return None
    report = run_dir / "report.html"
    decision = (result or {}).get("decision") or {}
    checks = f"{decision.get('verified', 0)}✓ {decision.get('refuted', 0)}✗ {decision.get('unverified', 0)}?"
    if run is not None:
        attempts = len(run.get("attempts") or [])
        cost = run.get("cost_usd") or 0
        detail = f"{run.get('contract_id', '')} · {attempts} attempt(s)" + (f" · ${cost:.2f}" if cost else "")
        return {
            "run_id": run_dir.name,
            "kind": f"run ({run.get('agent', '')})",
            "outcome": str(run.get("terminal", "")),
            "checks": checks,
            "detail": detail,
            "report": str(report) if report.exists() else "",
        }
    contracts = ", ".join(o.get("contract", {}).get("id", "") for o in (result or {}).get("contracts", []))
    return {
        "run_id": run_dir.name,
        "kind": "verify",
        "outcome": str(decision.get("outcome", "")),
        "checks": checks,
        "detail": contracts or ((result or {}).get("error") or ""),
        "report": str(report) if report.exists() else "",
    }


def _load(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def restore(
    run_id: str = typer.Argument(..., help="The run, as `contexer runs` lists it."),
    attempt: int | None = typer.Option(None, "--attempt", "-a", min=0, help="An attempt (0 is the project before the run)."),
    stopped: bool = typer.Option(False, "--stopped", help="The unfinished work of a run you stopped."),
    undo: bool = typer.Option(False, "--undo", help="The files as they were before the last restore from this run."),
    project_dir: Path = typer.Option(Path("."), "--dir", "-d", help="Project directory.", file_okay=False),
) -> None:
    """Put the files back to a snapshot a run took. Ignored files such as .env and node_modules are not touched."""
    if sum((attempt is not None, stopped, undo)) != 1:
        raise typer.BadParameter("choose one of --attempt N, --stopped or --undo")
    console = Console()
    name = "stopped" if stopped else "undo" if undo else str(attempt)
    shadow = ShadowRepo(project_dir.resolve())
    commit = shadow.resolve(f"{run_id}/{name}")
    if commit is None:
        console.print(f"[red]No snapshot '{escape(name)}' for run {escape(run_id)}.[/] `contexer runs` lists the runs.")
        raise typer.Exit(code=1)
    shadow.snapshot(f"{run_id}/undo", "before a restore")  # so the restore itself can be undone
    shadow.restore(commit)
    console.print(f"[green]✓[/] Files restored to {escape(run_id)} {escape(name)}. Undo: `contexer restore {escape(run_id)} --undo`")
