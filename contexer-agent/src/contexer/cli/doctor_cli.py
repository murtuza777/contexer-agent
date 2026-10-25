"""``contexer doctor``: check everything Contexer needs, with the fix for each problem."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import typer
from rich.console import Console
from rich.markup import escape

from contexer import __version__

Status = Literal["ok", "warn", "fail"]
_MARK = {"ok": "[green]✓[/]", "warn": "[yellow]![/]", "fail": "[red]✗[/]"}


@dataclass
class Finding:
    area: str
    status: Status
    detail: str
    fix: str = ""


def doctor(
    project_dir: Path = typer.Option(Path("."), "--dir", "-d", help="Project to check as well.", file_okay=False),
) -> None:
    """Check Python, Chromium, git, Node, a drafting model, coding agents and the project setup."""
    console = Console()
    console.print(f"[bold bright_cyan]Contexer doctor[/] [dim]· contexer {__version__}[/]\n")
    findings = environment_findings() + project_findings(project_dir.resolve())
    for f in findings:
        console.print(f"{_MARK[f.status]} [bold]{escape(f.area)}[/] {escape(f.detail)}")
        if f.fix and f.status != "ok":
            console.print(f"    [dim]fix:[/] {escape(f.fix)}")
    failures = [f for f in findings if f.status == "fail"]
    warnings = [f for f in findings if f.status == "warn"]
    console.print()
    if failures:
        console.print(f"[red]{len(failures)} problem(s) will stop Contexer from working.[/]")
    elif warnings:
        console.print(f"[yellow]Ready, with {len(warnings)} warning(s).[/]")
    else:
        console.print("[green]Everything Contexer needs is in place.[/]")
    raise typer.Exit(code=1 if failures else 0)


def environment_findings() -> list[Finding]:
    from contexer.cli.gate_cli import compiler_llm
    from contexer.config.settings import load_config
    from contexer.observer.browser import chromium_status

    findings: list[Finding] = []
    py = sys.version_info
    findings.append(
        Finding("Python", "ok" if py >= (3, 11) else "fail", f"{py.major}.{py.minor}.{py.micro}", "Use Python 3.11 or newer")
    )

    ok, detail = asyncio.run(chromium_status())
    findings.append(Finding("Browser", "ok" if ok else "fail", detail, "python -m playwright install chromium"))

    git = _version(["git", "--version"])
    findings.append(
        Finding("git", "ok" if git else "fail", git or "not found", "Install git; `contexer run` snapshots attempts with it")
    )

    node = _version(["node", "--version"])
    findings.append(
        Finding(
            "Node.js",
            "ok" if node else "warn",
            node or "not found (only needed for JavaScript apps)",
            "Install Node.js 18+ to verify Vite, Next.js and other JS apps",
        )
    )

    config = load_config()
    llm = compiler_llm(None)
    if llm is not None:
        detail = f"{llm.name} · {llm.model}"
        status: Status = "warn" if llm.name == "openrouter" and llm.model == "openrouter/free" else "ok"
        findings.append(
            Finding(
                "Drafting model",
                status,
                detail + (" (free routing gives inconsistent drafts)" if status == "warn" else ""),
                "Set ANTHROPIC_API_KEY or OPENAI_API_KEY, or pin OPENROUTER_MODEL to a strong model",
            )
        )
    else:
        findings.append(
            Finding(
                "Drafting model",
                "warn",
                "none configured: you can still write contracts by hand and replay them",
                "Set ANTHROPIC_API_KEY, OPENAI_API_KEY or OPENROUTER_API_KEY to draft checks from a goal",
            )
        )

    agents = [name for name in ("claude", "opencode", "codex") if shutil.which(name)]
    findings.append(
        Finding(
            "Coding agents",
            "ok" if agents else "warn",
            ", ".join(agents) if agents else "none found (only `contexer run` needs one)",
            "Install Claude Code (npm i -g @anthropic-ai/claude-code) or OpenCode for `contexer run`",
        )
    )

    token = config.github_token or os.environ.get("GITHUB_TOKEN")
    findings.append(
        Finding(
            "GitHub",
            "ok" if token else "warn",
            "token found" if token else "no token (only needed for `--github` outside Actions)",
            "Set GITHUB_TOKEN to post commit statuses from your machine",
        )
    )
    return findings


def project_findings(project: Path) -> list[Finding]:
    from contexer.appserver.detect import StartPlanError, plan_start
    from contexer.config.project import ProjectConfigError, load_project_config
    from contexer.contract import ContractError, ContractStore
    from contexer.workflow.inspector import RepositoryInspector

    findings: list[Finding] = []
    if not project.is_dir():
        return [Finding("Project", "fail", f"{project} is not a directory")]
    try:
        settings = load_project_config(project)
    except ProjectConfigError as exc:
        return [Finding("contexer.toml", "fail", str(exc), "Fix the file or delete it to use detection")]

    context = RepositoryInspector().inspect(project)
    if context.is_static_site and not settings.app.start:
        findings.append(Finding("App", "ok", f"{project.name}: static site, served by Contexer"))
    else:
        try:
            plan = plan_start(project, settings.app)
            install = " (dependencies will be installed first)" if plan.install_argv else ""
            findings.append(Finding("App", "ok", f"{project.name}: starts with `{plan.display}`{install}"))
        except StartPlanError as exc:
            findings.append(
                Finding("App", "fail", str(exc), 'Add [app] start = "<command with {port}>" to contexer.toml')
            )

    try:
        contracts = ContractStore(project).list()
    except ContractError as exc:
        findings.append(Finding("Contracts", "fail", str(exc), "Fix or remove the invalid contract file"))
        return findings
    if not contracts:
        findings.append(
            Finding("Contracts", "warn", "none yet", 'contexer contract draft "<what must be true>"')
        )
        return findings
    by_status = {s: [c.id for c in contracts if c.status == s] for s in ("approved", "draft", "modified")}
    summary = ", ".join(f"{len(ids)} {status}" for status, ids in by_status.items() if ids)
    pending = by_status["draft"] + by_status["modified"]
    findings.append(
        Finding(
            "Contracts",
            "warn" if pending else "ok",
            summary,
            f"Review and approve: contexer contract approve {pending[0]}" if pending else "",
        )
    )
    return findings


def _version(argv: list[str]) -> str:
    exe = shutil.which(argv[0])
    if exe is None:
        return ""
    try:
        out = subprocess.run([exe, *argv[1:]], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (out.stdout or out.stderr).strip().splitlines()[0] if out.returncode == 0 else ""
