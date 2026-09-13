"""Contexer CLI — thin Typer entrypoint.

This module is the sole entry point for the ``contexer`` command.
It owns argument parsing and top-level routing only; all interactive
behavior lives in ``contexer.cli.app`` and all rendering in
``contexer.cli.ui``.

Architecture principle: the CLI is a thin shell over the agent runtime.

    CLI (this package)
        ↓
    ContexerAgent (runtime/agent.py)
        ↓
    Workflow Engine (workflow/, future)
"""

from __future__ import annotations

import sys
import typer

from contexer import __version__


def _configure_terminal_encoding() -> None:
    """Ensure standard streams use UTF-8 with graceful error replacement."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass



# ---------------------------------------------------------------------------
# Typer application
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="contexer",
    help="Contexer — Autonomous Engineering Agent",
    add_completion=False,
    no_args_is_help=False,
    invoke_without_command=True,
    rich_markup_mode="rich",
)


def _version_callback(value: bool) -> None:
    """Print version and exit when --version is passed."""
    if value:
        typer.echo(f"contexer v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """Contexer — Autonomous Engineering Agent.

    Launch an interactive Contexer shell for autonomous engineering tasks.
    Contexer orchestrates coding agents through an intent → plan → execute
    → verify workflow.
    """
    _configure_terminal_encoding()
    from contexer.cli.repl import ContexerApp

    contexer_app = ContexerApp()
    contexer_app.run()


