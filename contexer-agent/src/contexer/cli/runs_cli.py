"""``contexer runs``: what was verified or built here, newest first, with links to the evidence.

``contexer restore`` puts the files back to a snapshot one of those runs took.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from contexer.checkpoint import ShadowRepo
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
) -> None:
    """List recent verifications and agent runs with their outcome and report path."""
    console = Console()
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


def _summarise(run_dir: Path) -> Optional[dict[str, str]]:
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


def _load(path: Path) -> Optional[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def restore(
    run_id: str = typer.Argument(..., help="The run, as `contexer runs` lists it."),
    attempt: Optional[int] = typer.Option(None, "--attempt", "-a", min=0, help="An attempt (0 is the project before the run)."),
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
