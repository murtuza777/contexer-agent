"""``contexer init``: set a project up for contracts, and optionally for the CI gate and for issues."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape

from contexer.appserver.detect import StartPlanError, plan_start
from contexer.cli import term
from contexer.config.project import CONFIG_FILE, AppSettings
from contexer.contract.store import ensure_contexer_dir
from contexer.workflow.inspector import RepositoryInspector

WORKFLOW_PATH = Path(".github") / "workflows" / "contexer.yml"
ISSUES_WORKFLOW_PATH = Path(".github") / "workflows" / "contexer-issues.yml"

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


ISSUES_WORKFLOW = """\
# Contexer picks up GitHub issues.
#
#  1. Label an issue "contexer": Contexer drafts the checks that define done and posts them on it.
#  2. Someone with write access replies "/contexer approve": a coding agent builds it, Contexer
#     proves every check in a real browser and opens a pull request that closes the issue.
#
# Before the first run:
#  - Add the coding agent's model key as a repository secret. OPENROUTER_API_KEY works with
#    OpenCode and free models; use ANTHROPIC_API_KEY with agent: claude-code, or OPENAI_API_KEY
#    with agent: codex.
#  - Settings > Actions > General: allow GitHub Actions to create pull requests.
#  - Pull requests opened with the default token do not start other workflows. To have your CI
#    and the acceptance gate run on them, pass a personal or app token as github-token.
name: Contexer issues

on:
  issues:
    types: [labeled]
  issue_comment:
    types: [created]

permissions:
  contents: write
  issues: write
  pull-requests: write

concurrency:
  group: contexer-issue-${{{{ github.event.issue.number }}}}

jobs:
  contexer:
    if: >-
      (github.event_name == 'issues' && github.event.label.name == 'contexer') ||
      (github.event_name == 'issue_comment' && !github.event.issue.pull_request &&
       startsWith(github.event.comment.body, '/contexer') &&
       contains(fromJSON('["OWNER", "MEMBER", "COLLABORATOR"]'), github.event.comment.author_association))
    runs-on: ubuntu-latest
    timeout-minutes: 60
    env:
      OPENROUTER_API_KEY: ${{{{ secrets.OPENROUTER_API_KEY }}}}
    steps:
      # No stored credentials: the coding agent edits files; only Contexer pushes.
      - uses: actions/checkout@v7.0.1
        with:
          persist-credentials: false
      - uses: murtuza777/contexer-agent/issue@main
        with:
          agent: opencode
          working-directory: {working_directory}
"""


def init(
    project_dir: Path = typer.Option(Path("."), "--dir", "-d", help="Project directory.", file_okay=False),
    ci: bool = typer.Option(False, "--ci", help="Also write a GitHub Actions workflow for the gate."),
    issues: bool = typer.Option(False, "--issues", help="Also write a workflow that builds labelled issues into pull requests."),
    repo_root: Path = typer.Option(Path("."), "--repo-root", help="Repository root, for the workflow file."),
) -> None:
    """Detect how the app starts, prepare .contexer/, and add the merge gate (--ci) or issue (--issues) workflows."""
    console = Console()
    project = project_dir.resolve()
    context = RepositoryInspector().inspect(project)
    ensure_contexer_dir(project)
    term.header(console, "init", project.name)
    console.print(f"{term.mark('pass')} Prepared {escape(term.path(project / '.contexer'))} [dim](commit its contracts/ folder)[/]")

    startable = True
    if context.is_static_site:
        console.print(f"{term.mark('pass')} Static site: Contexer will serve the files itself")
    else:
        try:
            plan = plan_start(project, AppSettings())
            console.print(f"{term.mark('pass')} Detected {escape(plan.framework)}: Contexer will run [bold]{escape(plan.display)}[/]")
        except StartPlanError as exc:
            startable = False
            term.note(console, "warn", escape(str(exc)))
            _write_config_template(project, console)

    root = repo_root.resolve()
    if ci or issues:
        try:
            working_directory = project.relative_to(root).as_posix() or "."
        except ValueError:
            raise typer.BadParameter(f"{project} is not inside the repository root {root}") from None
        if ci:
            node_setup = "" if context.is_static_site else NODE_SETUP.format(working_directory=working_directory)
            _write_workflow(console, root / WORKFLOW_PATH, WORKFLOW.format(node_setup=node_setup, working_directory=working_directory))
        if issues:
            _write_workflow(console, root / ISSUES_WORKFLOW_PATH, ISSUES_WORKFLOW.format(working_directory=working_directory))
            console.print(
                "  [dim]Add your model key as a repository secret and allow Actions to create pull requests; "
                "the file says how.[/]"
            )

    console.print()
    rows = [] if startable else [("First", f"set {escape('[app]')} start in contexer.toml to the command that starts your app")]
    rows += [
        ("Then", 'contexer run "<what must be true>" [dim]· draft checks, approve them, have your agent build it[/]'),
        ("Later", "contexer verify --all [dim]· replay every approved check, with no model[/]"),
    ]
    term.fields(console, rows, indent=0)


def _write_workflow(console: Console, path: Path, text: str) -> None:
    if path.exists():
        term.note(console, "warn", f"{escape(term.path(path))} already exists; left unchanged")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    console.print(f"{term.mark('pass')} Wrote {escape(term.path(path))}")


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
    console.print(f"{term.mark('pass')} Wrote {escape(term.path(path))}: set {escape('[app]')} start there")
