"""``contexer runs``: what was verified or built here, newest first, with links to the evidence.

``contexer restore`` puts the files back to a snapshot one of those runs took.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import stat
import statistics
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import typer
from pydantic import BaseModel, Field
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from contexer.checkpoint import ShadowRepo, SnapshotError
from contexer.checkpoint.lock import RunLocked, run_lock
from contexer.cli import term
from contexer.cli.test_cli import is_interactive
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
    "internal_error": "red",
    "tampered": "red",
}


# `contexer runs` lists, as it always did; `contexer runs prune` is its one sub-command.
runs_app = typer.Typer(invoke_without_command=True)


@runs_app.callback()
def runs(
    ctx: typer.Context,
    project_dir: Path = typer.Option(Path("."), "--dir", "-d", help="Project directory.", file_okay=False),
    limit: int = typer.Option(15, "--limit", "-n", min=1, help="How many runs to show."),
    stats: bool = typer.Option(False, "--stats", help="How the agent runs in this project ended, and what they cost."),
) -> None:
    """List recent verifications and agent runs with their outcome and report path."""
    if ctx.invoked_subcommand is not None:
        return
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


# -- prune -------------------------------------------------------------------------------------------

# A run folder is named by `RunDir.create`. Prune removes folders with such a name and no others.
_RUN_ID = re.compile(r"\d{8}-\d{6}-[0-9a-f]{4}")
_JUNCTION = 0xA0000003  # IO_REPARSE_TAG_MOUNT_POINT


@dataclass
class _Plan:
    remove: list[Path] = field(default_factory=list)
    unfinished: list[str] = field(default_factory=list)
    left: list[tuple[str, str]] = field(default_factory=list)
    runs: int = 0


@runs_app.command("prune")
def prune(
    ctx: typer.Context,
    keep: int = typer.Option(20, "--keep", "-k", min=0, help="How many of the newest runs to keep."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Remove without asking."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be removed, and remove nothing."),
    include_unfinished: bool = typer.Option(
        False, "--include-unfinished", help="Also remove older runs that were stopped and can still be resumed."
    ),
    project_dir: Path | None = typer.Option(None, "--dir", "-d", help="Project directory.", file_okay=False),
) -> None:
    """Remove old run folders and their snapshots, keeping the newest. Contracts, intent and your files are not touched."""
    console = Console()
    given = project_dir or (ctx.parent.params.get("project_dir") if ctx.parent else None) or Path(".")
    project = Path(given).resolve()
    root = project / CONTEXER_DIR / RUNS_DIR
    if _is_link(root) or _is_link(root.parent):
        term.note(console, "fail", f"[red]Nothing was removed:[/] {escape(str(root))} is a link, and prune does not follow links.")
        raise typer.Exit(code=1)
    if not root.is_dir():
        console.print("[dim]No runs yet; nothing to remove.[/]")
        return
    # The lock is held from the listing to the last removal, so no run starts in a folder that is being emptied.
    deleting = not dry_run and (yes or is_interactive())
    try:
        with contextlib.ExitStack() as held:
            if deleting:
                held.enter_context(run_lock(project, "contexer runs prune"))
            code = _prune(console, project, root, keep, include_unfinished, dry_run=dry_run, yes=yes)
    except RunLocked as exc:
        term.note(console, "fail", f"[red]Nothing was removed:[/] {escape(str(exc))}")
        raise typer.Exit(code=2) from None
    if code:
        raise typer.Exit(code=code)


def _prune(console: Console, project: Path, root: Path, keep: int, include_unfinished: bool, *, dry_run: bool, yes: bool) -> int:
    shadow = ShadowRepo(project)
    plan = _plan(root, keep, include_unfinished)
    term.header(console, "runs prune", f"keeping the newest {keep} of {plan.runs}")
    rows: list[tuple[str, str]] = []
    sizes = {path: _size(path) for path in plan.remove}
    for path in plan.remove:
        try:
            snapshots = len(shadow.run_refs(path.name))
        except SnapshotError:
            snapshots = 0
        outcome = (_summarise(path) or {}).get("outcome", "")
        rows.append((path.name, " · ".join(filter(None, [_bytes(sizes[path]), _count(snapshots, "snapshot"), escape(outcome)]))))
    if rows:
        term.section(console, "Dry run: would remove" if dry_run else "To remove", _bytes(sum(sizes.values())) + " in run folders")
        term.fields(console, rows)
    for run in plan.unfinished:
        term.note(
            console,
            "warn",
            f"Kept {run}: it was stopped before it ended and can still be continued (`contexer run --resume {run}`). "
            "`--include-unfinished` removes it too.",
        )
    for name, why in plan.left:
        term.note(console, "warn", f"Left {escape(name)}: {why}.")
    if not rows:
        term.note(console, "pass", "Nothing to remove.")
        return 0
    if dry_run:
        console.print("[dim]Dry run: nothing was removed.[/]")
        return 0
    if not yes:
        if not is_interactive():
            term.note(console, "warn", "Nothing was removed: nobody is at the terminal to confirm. Pass --yes to remove these.")
            return 2
        if not typer.confirm(f"Remove {_count(len(rows), 'run')}? This cannot be undone.", default=False):
            console.print("Nothing was removed.")
            return 0

    before = _size(shadow.git_dir)
    removed, folders, failed = 0, 0, 0
    for path in plan.remove:
        try:
            if path.parent != root or _is_link(path):  # it changed since it was listed
                raise OSError("it is no longer a plain folder in the runs folder")
            _remove_tree(path)
            shadow.drop_run(path.name)  # only once the folder is gone: a run that is still listed keeps its snapshots
        except (OSError, SnapshotError) as exc:
            failed += 1
            term.note(console, "fail", f"[red]Could not remove {path.name}:[/] {escape(str(exc))}")
            continue
        removed += 1
        folders += sizes[path]
    if removed:
        try:
            shadow.collect()
        except SnapshotError as exc:
            term.note(console, "warn", f"The snapshots were dropped, but their space was not freed: {escape(str(exc))}")
        snapshots = max(0, before - _size(shadow.git_dir))
        term.note(
            console,
            "pass",
            f"Removed {_count(removed, 'run')}, freed {_bytes(folders + snapshots)} "
            f"[dim](run folders {_bytes(folders)}, snapshots {_bytes(snapshots)})[/]",
        )
    return 1 if failed else 0


def _plan(root: Path, keep: int, include_unfinished: bool) -> _Plan:
    """Which direct children of the runs folder go. Newest first by name, as `contexer runs` lists them."""
    plan = _Plan()
    found: list[Path] = []
    for name in sorted(os.listdir(root), reverse=True):
        path = root / name
        if _is_link(path):
            plan.left.append((name, "it is a link, and prune does not follow links"))
        elif not path.is_dir():
            continue
        elif not _RUN_ID.fullmatch(name):
            plan.left.append((name, "it is not a run folder"))
        else:
            found.append(path)
    plan.runs = len(found)
    for path in found[keep:]:
        if not include_unfinished and _unfinished(path):
            plan.unfinished.append(path.name)
        else:
            plan.remove.append(path)
    return plan


def _unfinished(run_dir: Path) -> bool:
    """Whether a run was cut short: stopped, crashed, or killed before it wrote an outcome.

    Such a run can be continued with `run --resume`, and the work it had not finished exists only in its
    `stopped` snapshot, so it is not removed just for being old.
    """
    from contexer.graph.build import CHECKPOINT_FILE
    from contexer.graph.context import STOPPED_FILE

    run = _load(run_dir / "run.json")
    if (run_dir / STOPPED_FILE).is_file() or (run or {}).get("terminal") in ("cancelled", "internal_error"):
        return True
    return run is None and (run_dir / CHECKPOINT_FILE).is_file()


def _is_link(path: str | Path) -> bool:
    """A symlink or a Windows junction. Other reparse points are ordinary folders (a OneDrive folder is one)."""
    try:
        status = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISLNK(status.st_mode) or getattr(status, "st_reparse_tag", 0) == _JUNCTION


def _size(path: Path) -> int:
    """Bytes of the files under ``path``. A link counts as nothing and is never entered."""
    total = 0
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                if _is_link(entry.path):
                    continue
                total += _size(Path(entry.path)) if entry.is_dir(follow_symlinks=False) else entry.stat(follow_symlinks=False).st_size
    except OSError:
        pass
    return total


def _remove_tree(path: Path) -> None:
    """Remove one run folder. A link inside it is removed as a link; ``shutil.rmtree`` does not enter one.

    On Windows a read-only file cannot be deleted (git writes its objects that way, and a trace can hold
    some), so it is made writable and tried once more; the ``\\\\?\\`` form lifts the 260-character limit.
    """

    def writable(function: Callable[..., Any], target: str, _error: object) -> None:
        os.chmod(target, stat.S_IWRITE)
        function(target)

    target = str(path)
    if sys.platform == "win32" and not target.startswith("\\\\"):
        target = "\\\\?\\" + target
    if sys.version_info >= (3, 12):
        shutil.rmtree(target, onexc=writable)
    else:
        shutil.rmtree(target, onerror=writable)


def _bytes(size: int) -> str:
    amount = float(size)
    for unit in ("B", "KB", "MB"):
        if amount < 1024:
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} GB"


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" + ("" if number == 1 else "s")


def restore(
    run_id: str = typer.Argument(..., help="The run, as `contexer runs` lists it."),
    attempt: int | None = typer.Option(None, "--attempt", "-a", min=0, help="An attempt (0 is the project before the run)."),
    stopped: bool = typer.Option(False, "--stopped", help="The unfinished work of a run you stopped."),
    undo: bool = typer.Option(False, "--undo", help="The files as they were before the last restore from this run."),
    before_resume: bool = typer.Option(False, "--before-resume", help="The files as they were when the run was last resumed."),
    project_dir: Path = typer.Option(Path("."), "--dir", "-d", help="Project directory.", file_okay=False),
) -> None:
    """Put the files back to a snapshot a run took. Ignored files such as .env and node_modules are not touched."""
    if sum((attempt is not None, stopped, undo, before_resume)) != 1:
        raise typer.BadParameter("choose one of --attempt N, --stopped, --before-resume or --undo")
    console = Console()
    name = "stopped" if stopped else "undo" if undo else "before-resume" if before_resume else str(attempt)
    shadow = ShadowRepo(project_dir.resolve())
    commit = shadow.resolve(f"{run_id}/{name}")
    if commit is None:
        console.print(f"[red]No snapshot '{escape(name)}' for run {escape(run_id)}.[/] `contexer runs` lists the runs.")
        raise typer.Exit(code=1)
    shadow.snapshot(f"{run_id}/undo", "before a restore")  # so the restore itself can be undone
    shadow.restore(commit)
    console.print(f"[green]✓[/] Files restored to {escape(run_id)} {escape(name)}. Undo: `contexer restore {escape(run_id)} --undo`")
