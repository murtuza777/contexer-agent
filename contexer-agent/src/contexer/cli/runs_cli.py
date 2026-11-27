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
from rich.padding import Padding
from rich.pager import Pager, SystemPager
from rich.table import Table
from rich.text import Text

from contexer.checkpoint import ShadowRepo, SnapshotError
from contexer.checkpoint.lock import RunLocked, run_lock
from contexer.cli import term
from contexer.cli.test_cli import is_interactive
from contexer.contract.store import CONTEXER_DIR
from contexer.crew.transcript import read_transcript
from contexer.evidence.rundir import RUNS_DIR, TRACE_FILE

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
    by: str | None = typer.Option(None, "--by", help="With --stats: also a row per model Contexer's agents called (`--by model`)."),
    as_json: bool = typer.Option(False, "--json", help="Print JSON and nothing else: the list, or with --stats the numbers."),
) -> None:
    """List recent verifications and agent runs with their outcome and report path."""
    if ctx.invoked_subcommand is not None:
        return
    if by not in (None, "model"):
        raise typer.BadParameter("the one grouping is `model`", param_hint="--by")
    console = Console()
    if stats or by:
        found = run_stats(project_dir.resolve())
        if as_json:
            typer.echo(found.model_dump_json(indent=2))
        else:
            _print_stats(console, found, by_model=by == "model")
        return
    root = project_dir.resolve() / CONTEXER_DIR / RUNS_DIR
    rows = [row for row in (_summarise(d) for d in sorted(root.glob("*"), reverse=True) if d.is_dir()) if row]
    if as_json:
        typer.echo(json.dumps(rows[:limit], indent=2))
        return
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


class ModelStats(BaseModel):
    """What one model did for Contexer's own agents, added up from the runs' ``trace.jsonl``.

    A run counts under every model its agents called. The coding agent's model is not here: the trace
    records Contexer's calls, not the coding agent's.
    """

    provider: str = ""
    model: str = ""
    runs: int = 0
    succeeded: int = 0
    proven_rate: float = 0.0
    attempts_per_success: float | None = None
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    # None: no call of this model has a known cost. Never 0 for "not known".
    cost_usd: float | None = None
    cost_estimated: bool = False
    calls_without_cost: int = 0
    # What the model cost in all its runs, over the runs that were proven.
    cost_per_success: float | None = None
    tool_calls: int = 0
    tool_failed: int = 0
    tool_repaired: int = 0
    tool_error_rate: float | None = None
    tool_repair_rate: float | None = None


class RunStats(BaseModel):
    """What the agent runs kept in a project's ``.contexer/runs`` add up to. Read from files; nothing is sent anywhere."""

    runs: int = 0
    succeeded: int = 0
    first_try: int = 0
    endings: dict[str, int] = Field(default_factory=dict)
    attempts_per_success: float = 0.0
    # The coding agent's spend plus what Contexer's own agents cost, where that is known.
    cost_usd: float = 0.0
    # None when no run was proven, or when a run's cost is not known: the sum is then too low to divide.
    cost_per_success: float | None = None
    spent_without_proof: float = 0.0
    # Runs where the coding agent's cost, or the cost of Contexer's agents, is not known. They add nothing to the sums.
    runs_with_unknown_cost: int = 0
    runs_with_high_note: int = 0
    median_seconds: float = 0.0
    by_model: list[ModelStats] = Field(default_factory=list)
    # Runs with no model call in a trace: from before 2026-11-26, with no model, or with a trace that cannot be read.
    runs_without_model_calls: int = 0


def run_stats(project: Path) -> RunStats:
    """Outcome numbers for every agent run (``run.json``) in the project. Verifications alone are not counted."""
    folders = [(d, data) for d in sorted((project / CONTEXER_DIR / RUNS_DIR).glob("*")) if d.is_dir() and (data := _load(d / "run.json"))]
    found = [data for _, data in folders]
    stats = RunStats(runs=len(found))
    if not found:
        return stats
    stats.by_model, stats.runs_without_model_calls = _by_model(folders)
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
    stats.runs_with_unknown_cost = sum(1 for r in found if _cost_unknown(r))
    stats.cost_per_success = round(stats.cost_usd / len(proven), 2) if proven and not stats.runs_with_unknown_cost else None
    stats.spent_without_proof = round(sum(spent(r) for r in found if r.get("terminal") != "succeeded"), 2)
    stats.runs_with_high_note = sum(1 for r in found if any(n.get("severity") == "high" for n in r.get("review") or []))
    stats.median_seconds = float(statistics.median(float(r.get("duration_seconds") or 0.0) for r in found))
    return stats


def _cost_unknown(run: dict[str, Any]) -> bool:
    """Whether part of what a run cost is not known: the coding agent's turn, or Contexer's agents when any ran."""
    agents = [row for row in run.get("agents") or [] if isinstance(row, dict)]
    if run.get("cost_usd", 0.0) is None or (agents and run.get("crew_cost_usd") is None):
        return True
    # The run's sum leaves out an agent whose cost is null.
    return any("cost_usd" in row and row["cost_usd"] is None for row in agents)


def _by_model(folders: list[tuple[Path, dict[str, Any]]]) -> tuple[list[ModelStats], int]:
    """A row per model, most runs first, and how many runs have no model call in a trace.

    A tool call line names its agent and not a model, so it goes to the model that agent last called.
    """
    rows: dict[tuple[str, str], ModelStats] = {}
    attempts: dict[tuple[str, str], int] = {}
    untraced = 0
    for folder, run in folders:
        try:
            lines = read_transcript(folder / TRACE_FILE)
        except (OSError, ValueError):
            lines = []
        used: set[tuple[str, str]] = set()
        last: dict[str, tuple[str, str]] = {}
        for line in lines:
            if not isinstance(line, dict):
                continue
            agent = str(line.get("gen_ai.agent.name") or "")
            if line.get("event") == "model":
                key = (str(line.get("gen_ai.provider.name") or ""), str(line.get("gen_ai.request.model") or "unknown"))
                row = rows.setdefault(key, ModelStats(provider=key[0], model=key[1]))
                used.add(key)
                last[agent] = key
                row.calls += 1
                row.tokens_in += int(line.get("gen_ai.usage.input_tokens") or 0)
                row.tokens_out += int(line.get("gen_ai.usage.output_tokens") or 0)
                cost = line.get("contexer.cost_usd")
                if isinstance(cost, (int, float)):
                    row.cost_usd = (row.cost_usd or 0.0) + float(cost)
                    row.cost_estimated = row.cost_estimated or bool(line.get("contexer.cost_estimated"))
                else:
                    row.calls_without_cost += 1
            elif line.get("event") == "tool" and agent in last:
                row = rows[last[agent]]
                row.tool_calls += 1
                row.tool_failed += line.get("contexer.tool.status") == "failed"
                row.tool_repaired += line.get("contexer.tool.status") == "repaired"
        untraced += not used
        for key in used:
            rows[key].runs += 1
            if run.get("terminal") == "succeeded":
                rows[key].succeeded += 1
                attempts[key] = attempts.get(key, 0) + len(run.get("attempts") or [])
    for key, row in rows.items():
        row.proven_rate = round(row.succeeded / row.runs, 2) if row.runs else 0.0
        if row.succeeded:
            row.attempts_per_success = round(attempts[key] / row.succeeded, 2)
        if row.cost_usd is not None:
            row.cost_usd = round(row.cost_usd, 4)
            # With a call whose cost is not known the sum is too low to divide.
            if row.succeeded and not row.calls_without_cost:
                row.cost_per_success = round(row.cost_usd / row.succeeded, 4)
        if row.tool_calls:
            row.tool_error_rate = round(row.tool_failed / row.tool_calls, 2)
            row.tool_repair_rate = round(row.tool_repaired / row.tool_calls, 2)
    return sorted(rows.values(), key=lambda r: (-r.runs, r.provider, r.model)), untraced


def _print_stats(console: Console, stats: RunStats, by_model: bool = False) -> None:
    if not stats.runs:
        console.print("[dim]No agent runs in this project yet. Try:[/] contexer run \"what should be true\"")
        return
    console.print(f"[bold]{stats.succeeded} of {stats.runs} runs ended with every check proven[/]")
    rows = [("How runs ended", " · ".join(f"{name} {count}" for name, count in stats.endings.items()))]
    if stats.succeeded:
        rows.append(
            ("When proven", f"{stats.first_try} at the first attempt · {stats.attempts_per_success:g} attempts on average")
        )
    unknown = stats.runs_with_unknown_cost
    cost = f"${stats.cost_usd:.2f} {'known' if unknown else 'in all'}"
    if unknown == stats.runs and not stats.cost_usd:
        cost = "not known"
    if stats.cost_per_success is not None:
        cost += f" · ${stats.cost_per_success:.2f} per proven run"
    if stats.spent_without_proof:
        cost += f" · ${stats.spent_without_proof:.2f} spent on runs that proved nothing"
    if unknown:
        cost += f" · {_count(unknown, 'run')} with a cost that is not known"
    rows.append(("Cost", cost))
    rows.append(("Review", f"{stats.runs_with_high_note} run(s) with a high-severity note"))
    rows.append(("Typical run", term.duration(stats.median_seconds)))
    term.fields(console, rows)
    console.print("[dim]Counted from run.json in .contexer/runs. A cost that is not known adds nothing to the sums.[/]")
    if by_model:
        _print_models(console, stats)


def _print_models(console: Console, stats: RunStats) -> None:
    term.section(console, "By model", "what Contexer's own agents called, from each run's trace.jsonl")
    if not stats.by_model:
        console.print("  [dim]No model call in any trace.[/]")
    else:
        table = Table(box=None, header_style="dim", pad_edge=False)
        for column in ("provider", "model", "proven", "attempts", "calls", "tokens in / out", "cost", "per proven run", "tool errors", "repaired"):
            table.add_column(column)
        for row in stats.by_model:
            table.add_row(
                escape(row.provider),
                escape(row.model),
                f"{row.succeeded} of {row.runs}",
                f"{row.attempts_per_success:g}" if row.attempts_per_success is not None else "",
                str(row.calls),
                f"{row.tokens_in:,} / {row.tokens_out:,}",
                _model_cost(row),
                f"${row.cost_per_success:.2f}" if row.cost_per_success is not None else "",
                _rate(row.tool_failed, row.tool_calls),
                _rate(row.tool_repaired, row.tool_calls),
            )
        console.print(Padding(table, (0, 0, 0, 2), expand=False))
        console.print("[dim]A run counts under every model its agents called. The coding agent's own model is not in the trace.[/]")
    if stats.runs_without_model_calls:
        runs = stats.runs_without_model_calls
        console.print(f"[dim]{_count(runs, 'run')} {'has' if runs == 1 else 'have'} no model call in a trace (older than the trace, or run with no model).[/]")


def _model_cost(row: ModelStats) -> str:
    if row.cost_usd is None:
        return "not known"
    text = f"${row.cost_usd:.2f}" + (" estimated" if row.cost_estimated else "")
    return text + (f", {_count(row.calls_without_cost, 'call')} not known" if row.calls_without_cost else "")


def _rate(part: int, whole: int) -> str:
    return f"{part / whole:.0%} ({part} of {whole})" if whole else ""


def _summarise(run_dir: Path) -> dict[str, Any] | None:
    result = _load(run_dir / "result.json")
    run = _load(run_dir / "run.json")
    if result is None and run is None:
        return None
    report = run_dir / "report.html"
    decision = (result or {}).get("decision") or {}
    checks = f"{decision.get('verified', 0)}✓ {decision.get('refuted', 0)}✗ {decision.get('unverified', 0)}?"
    if run is not None:
        attempts = len(run.get("attempts") or [])
        cost = run.get("cost_usd", 0)
        spent = " · cost not known" if cost is None else f" · ${cost:.2f}" if cost else ""
        detail = f"{run.get('contract_id', '')} · {attempts} attempt(s){spent}"
        return {
            "attempts": attempts,
            "cost_usd": cost,
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


# -- show: the attempts of one run, and what they changed ---------------------------------------------


@runs_app.command("show")
def show(
    ctx: typer.Context,
    run: str = typer.Argument(..., help="The run, as `contexer runs` lists it."),
    diff: bool = typer.Option(False, "--diff", help="Print what the run changed, as a diff."),
    attempt: int | None = typer.Option(None, "--attempt", "-a", min=1, help="With --diff: the change of this attempt alone."),
    project_dir: Path | None = typer.Option(None, "--dir", "-d", help="Project directory.", file_okay=False),
) -> None:
    """The attempts of one agent run. With --diff, the change of the run or of one attempt, paged in a terminal."""
    console = Console()
    given = project_dir or (ctx.parent.params.get("project_dir") if ctx.parent else None) or Path(".")
    project = Path(given).resolve()
    # The name is checked before it is joined to a path: a run is never named by a path.
    data = _load(project / CONTEXER_DIR / RUNS_DIR / run / "run.json") if _RUN_ID.fullmatch(run) else None
    if data is None:
        _stop(console, f"No agent run named {escape(run)} in this project. `contexer runs` lists them.")
    assert data is not None
    attempts = [row for row in data.get("attempts") or [] if isinstance(row, dict)]
    if not diff:
        if attempt is not None:
            _stop(console, f"`--attempt` goes with `--diff`: `contexer runs show {run} --diff --attempt {attempt}`.")
        term.header(console, "runs show", f"{run} · {data.get('terminal', '')}")
        if not attempts:
            console.print("  [dim]The run made no attempt.[/]")
            return
        term.fields(console, [(str(row.get("n", "")), escape(_attempt_line(row))) for row in attempts])
        console.print(f"[dim]`contexer runs show {run} --diff` prints the change of the run; add `--attempt N` for one attempt.[/]")
        return
    if attempt is None:
        text = str(data.get("diff") or "")
    else:
        text = _attempt_diff(console, project, run, attempts, attempt)
    if not text.strip():
        console.print("[dim]" + ("This attempt changed no file." if attempt is not None else "This run changed no file.") + "[/]")
        return
    _print_diff(console, text)


def _stop(console: Console, sentence: str) -> None:
    term.note(console, "fail", sentence)
    raise typer.Exit(code=2)


def _attempt_line(row: dict[str, Any]) -> str:
    """``repair · 2 of 3 checks proven · 1 file changed``, and where the files went when the attempt was undone."""
    counts = [int(row.get(key) or 0) for key in ("verified", "refuted", "unverified")]
    parts = [str(row.get("kind") or ""), f"{counts[0]} of {sum(counts)} checks proven", _count(len(row.get("changed_files") or []), "file") + " changed"]
    back = row.get("reverted_to")
    if back is not None:
        parts.append(f"undone, back to {'attempt ' + str(back) if back else 'the files as they were found'}")
    return " · ".join(part for part in parts if part)


def _attempt_diff(console: Console, project: Path, run: str, attempts: list[dict[str, Any]], n: int) -> str:
    """What attempt ``n`` changed: from the files it began with (the attempt before, or the one that was put back) to its snapshot."""
    numbers = [int(row.get("n") or 0) for row in attempts]
    if n not in numbers:
        had = f"attempts 1 to {max(numbers)}" if len(numbers) > 1 else "one attempt" if numbers else "no attempt"
        _stop(console, f"Run {run} has {had}. `contexer runs show {run}` lists them.")
    before = attempts[numbers.index(n) - 1] if numbers.index(n) else None
    began = 0 if before is None else before.get("reverted_to") if before.get("reverted_to") is not None else before.get("n")
    shadow = ShadowRepo(project)
    try:
        old, new = shadow.resolve(f"{run}/{began}"), shadow.resolve(f"{run}/{n}")
        if old and new:
            return shadow.diff(old, new)
    except SnapshotError:
        pass
    _stop(
        console,
        f"The snapshots of run {run} are not in this project any more, so the change of one attempt cannot be shown. "
        f"`contexer runs show {run} --diff` prints the change of the whole run.",
    )
    return ""


def _print_diff(console: Console, text: str, pager: Pager | None = None, colour: bool | None = None) -> None:
    """A diff: as it is into a pipe or a file, coloured and through the system pager in a terminal.

    Lines are never wrapped or cut, so what is printed can be applied as a patch.
    """
    if not console.is_terminal:
        console.out(text.rstrip("\n"), highlight=False)
        return
    if colour is None:
        # git's own default for `less`: quit when it fits a screen, show colour, leave the text on the screen.
        os.environ.setdefault("LESS", "FRX")
        # Without a PAGER, Windows pages with `more`, which prints colour codes as text.
        colour = os.name != "nt" or bool(os.environ.get("PAGER"))
    if not colour:
        (pager or SystemPager()).show(text)
        return
    shown = Text(no_wrap=True)
    for line in text.splitlines():
        shown.append(line + "\n", style=_diff_style(line))
    with console.pager(pager, styles=True):
        console.print(shown, soft_wrap=True, highlight=False, end="")


def _diff_style(line: str) -> str:
    if line.startswith(("diff --git", "--- ", "+++ ", "index ")):
        return "bold"
    if line.startswith("@@"):
        return "cyan"
    if line.startswith("+"):
        return "green"
    if line.startswith("-"):
        return "red"
    return ""


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
