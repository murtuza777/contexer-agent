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
    help=(
        "Proof that your coding agent is done: Contexer turns a goal into checks you approve, has your agent "
        "build it, and proves every check in a real browser. New here? Run `contexer setup`, then `contexer demo`."
    ),
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
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """Contexer — the AI engineer that owns "done".

    With no command, launch the interactive shell. Commands such as
    ``verify``, ``replay`` and ``contract`` run once and exit with a gate
    code: 0 pass, 1 fail, 2 needs action, 3 error.
    """
    _configure_terminal_encoding()
    from dotenv import find_dotenv, load_dotenv

    from contexer.config.user import apply_user_settings

    # Precedence: exported variables, then the nearest .env, then `contexer setup`.
    dotenv_path = find_dotenv(usecwd=True)
    if dotenv_path:
        load_dotenv(dotenv_path, override=False)
    apply_user_settings()
    if ctx.invoked_subcommand is not None:
        return
    from contexer.cli.repl import ContexerApp

    contexer_app = ContexerApp()
    contexer_app.run()


def _register_commands() -> None:
    from contexer.cli.gate_cli import register

    register(app)


_register_commands()


