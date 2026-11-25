"""``contexer hook``: the commands a coding agent's own harness runs. People do not run these by hand."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import typer

hook_app = typer.Typer(help="Commands a coding agent's hooks run (written by `contexer init --agent`).", no_args_is_help=True)


@hook_app.callback()
def _hooks() -> None:
    """Commands a coding agent's hooks run (written by `contexer init --agent`)."""


@hook_app.command("stop")
def stop(
    project_dir: Path | None = typer.Option(None, "--dir", "-d", help="Project directory. Default: where the agent works.", file_okay=False),
    max_blocks: int = typer.Option(3, "--max-blocks", min=0, help="How many times in a row the agent is kept working before the stop goes through."),
) -> None:
    """Replay the approved checks when the agent says it is done; keep it working while one fails.

    Reads the hook's JSON on stdin and answers in JSON on stdout, as Claude Code and Codex expect. It
    always exits 0: a check that fails is an answer, and a hook that breaks must not trap the agent.
    """
    from contexer.integrations import stop_hook

    raw = "" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
    out = stop_hook.main(raw, project_dir, cwd_from_env=os.environ.get("CLAUDE_PROJECT_DIR", ""), max_blocks=max_blocks)
    if out:
        sys.stdout.write(out + "\n")
