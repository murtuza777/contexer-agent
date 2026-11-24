"""The ``contexer`` command: a Typer app.

It loads the environment (exported variables, then the nearest ``.env``, then
what ``contexer setup`` saved) and routes to the commands registered in
``gate_cli.register``: setup, demo, doctor, init, run, verify, contract, runs,
restore, replay, issue, models and bench. Those render through ``cli/term.py``.
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
    no_args_is_help=True,
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
    """Contexer — the AI engineer that owns "done".

    Commands such as ``verify``, ``replay`` and ``contract`` exit with a
    gate code: 0 pass, 1 fail, 2 needs action, 3 error.
    """
    _configure_terminal_encoding()
    from contexer.config.project import load_nearest_env
    from contexer.config.user import apply_user_settings

    # Precedence: exported variables, then the nearest .env, then `contexer setup`.
    load_nearest_env()
    apply_user_settings()


def _register_commands() -> None:
    from contexer.cli.gate_cli import register

    register(app)


_register_commands()


