"""``contexer demo``: see the gate catch a real bug in about ten seconds, with no keys."""

from __future__ import annotations

import asyncio
import webbrowser
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape

from contexer.agents import ScriptedAgent
from contexer.cli import term
from contexer.cli.gate_cli import run_verification
from contexer.cli.run_cli import _render
from contexer.cli.setup_cli import ensure_browser
from contexer.cli.test_cli import is_interactive
from contexer.contract import ContractStore
from contexer.controller import RunSettings
from contexer.demo import create_demo_project, fixed_app_js
from contexer.graph import GraphController


def demo(
    target: Path = typer.Option(Path("contexer-demo"), "--dir", "-d", help="Where to create the demo app."),
    fix: bool = typer.Option(False, "--fix", help="Then show the repair loop with a simulated agent."),
    open_report: bool = typer.Option(False, "--open", help="Open the HTML report when done."),
) -> None:
    """Create a todo app with a seeded bug, prove its contract, and (with --fix) repair it."""
    console = Console()
    try:
        project = create_demo_project(target)
    except FileExistsError as exc:
        raise typer.BadParameter(f"{exc}; pass --dir to choose another folder") from exc

    term.header(console, "demo", "a todo app an AI agent just \"finished\"")
    console.print(
        "  Its approved contract says what done means: 7 checks covering adding, completing and deleting\n"
        "  tasks and the remaining count. Contexer serves the app and runs every check in Chromium.\n"
        "  [dim]No API key and no model are needed.[/]"
    )
    term.fields(console, [("Created", escape(term.path(project)))])
    _browser_for_a_first_run(console)
    result = asyncio.run(run_verification(project, all_contracts=True, console=console))
    report = Path(result.run_dir, "report.html")

    if not fix:
        console.print()
        term.fields(
            console,
            [
                ("Next", "contexer demo --fix [dim]to watch the repair loop[/]"),
                ("", "contexer test \"<what the app should do>\" [dim]to have it used like a person would (needs `contexer setup`)[/]"),
                ("", "contexer run \"<what must be true>\" [dim]in your own app's folder[/]"),
            ],
            indent=0,
        )
        _maybe_open(report, open_report)
        raise typer.Exit(code=result.decision.exit_code)

    term.section(console, "Repair loop with a SIMULATED agent", "it replays a known fix; `contexer run` drives a real one")
    agent = ScriptedAgent([{"app.js": fixed_app_js()}])
    contract = ContractStore(project).load("todo-basics")

    def on_event(kind: str, message: str) -> None:
        if kind == "verdict":
            passed = ": PASS:" in message
            console.print(f"  {term.mark('pass' if passed else 'fail')} [{'green' if passed else 'red'}]{escape(message)}[/]")
        elif kind in ("phase", "revert", "strategy", "agent-done"):
            console.print(f"  [dim]{escape(message)}[/]")

    # The loop of `contexer run`, with no model: fixed rules decide each next step.
    outcome = asyncio.run(GraphController(project, agent, RunSettings(max_repair_rounds=1), on_event=on_event).run(contract))
    _render(console, outcome)
    _maybe_open(Path(outcome.run_dir, "report.html"), open_report)
    raise typer.Exit(code=outcome.exit_code)


def _browser_for_a_first_run(console: Console) -> None:
    """This is the first command a new user runs, and a new install has no browser yet: offer it, then go on.

    With nobody to ask, nothing is downloaded and the verification says what to run.
    """
    from contexer.observer.browser import chromium_status

    if not is_interactive():
        return
    ok, _detail = asyncio.run(chromium_status())
    if not ok:
        console.print()
        ensure_browser(console, ask=True)


def _maybe_open(report: Path, open_report: bool) -> None:
    if open_report and report.exists():
        webbrowser.open(report.resolve().as_uri())
