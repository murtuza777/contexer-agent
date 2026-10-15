"""``contexer init``: set a project up for contracts, and optionally for the CI gate."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape

from contexer.appserver.detect import StartPlanError, plan_start
from contexer.config.project import CONFIG_FILE, AppSettings
from contexer.contract.store import ensure_contexer_dir
from contexer.workflow.inspector import RepositoryInspector

WORKFLOW_PATH = Path(".github") / "workflows" / "contexer.yml"

WORKFLOW = """\
# Contexer acceptance gate: replays every approved contract in .contexer/contracts
# against the pull request and posts a contexer/acceptance commit status.
# Make that status a required check to block merges until behaviour is proven.
name: Contexer acceptance gate

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read
  statuses: write

jobs:
  gate:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v7.0.1
{node_setup}      - uses: murtuza777/contexer-agent@main
        with:
          working-directory: {working_directory}
"""

NODE_SETUP = """\
      - uses: actions/setup-node@v7.0.0
        with:
          node-version: "22"
      - run: npm ci
        working-directory: {working_directory}
"""


def init(
    project_dir: Path = typer.Option(Path("."), "--dir", "-d", help="Project directory.", file_okay=False),
    ci: bool = typer.Option(False, "--ci", help="Also write a GitHub Actions workflow for the gate."),
    repo_root: Path = typer.Option(Path("."), "--repo-root", help="Repository root, for the workflow file."),
) -> None:
    """Detect how the app starts, prepare .contexer/, and (with --ci) add the merge gate workflow."""
    console = Console()
    project = project_dir.resolve()
    context = RepositoryInspector().inspect(project)
    ensure_contexer_dir(project)
    console.print(f"[green]✓[/] Prepared {escape(str(project / '.contexer'))} (commit the contracts/ folder)")

    if context.is_static_site:
        console.print("[green]✓[/] Static site: Contexer will serve the files itself")
    else:
        try:
            plan = plan_start(project, AppSettings())
            console.print(
                f"[green]✓[/] Detected {escape(plan.framework)}: Contexer will run [cyan]{escape(plan.display)}[/]"
            )
        except StartPlanError as exc:
            _write_config_template(project, console)
            console.print(f"[yellow]![/] {escape(str(exc))}")

    if ci:
        root = repo_root.resolve()
        workflow = root / WORKFLOW_PATH
        if workflow.exists():
            console.print(f"[yellow]![/] {escape(str(workflow))} already exists; left unchanged")
        else:
            try:
                working_directory = project.relative_to(root).as_posix() or "."
            except ValueError:
                raise typer.BadParameter(f"{project} is not inside the repository root {root}") from None
            node_setup = "" if context.is_static_site else NODE_SETUP.format(working_directory=working_directory)
            workflow.parent.mkdir(parents=True, exist_ok=True)
            workflow.write_text(
                WORKFLOW.format(node_setup=node_setup, working_directory=working_directory), encoding="utf-8"
            )
            console.print(f"[green]✓[/] Wrote {escape(str(workflow))}")

    console.print()
    console.print("[bold]Next:[/]")
    console.print('  contexer contract draft "<what must be true>"   [dim]# checks grounded in your running app[/]')
    console.print("  contexer contract approve <id>")
    console.print("  contexer verify --all")


def _write_config_template(project: Path, console: Console) -> None:
    path = project / CONFIG_FILE
    if path.exists():
        return
    path.write_text(
        "[app]\n"
        '# How to start the app; {port} is replaced with a free port.\n'
        '# start = "python -m uvicorn app:app --port {port}"\n'
        'ready_path = "/"\n'
        "ready_timeout = 120\n",
        encoding="utf-8",
    )
    console.print(f"[green]✓[/] Wrote {escape(str(path))}; set [app].start there")
