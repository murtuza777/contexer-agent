"""Decide how to start a project's dev server.

Order of precedence: ``[app].start`` in ``contexer.toml``, then the
``dev``/``start`` script in ``package.json`` with port flags for the framework
it runs. Ports are pinned explicitly (and Vite told ``--strictPort``) because a
dev server that silently moves to another port makes every check fail for the
wrong reason.
"""

from __future__ import annotations

import json
import re
import shutil
import socket
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from contexer.config.project import AppSettings

HOST = "127.0.0.1"
_SCRIPT_PREFERENCE = ("dev", "start", "serve", "preview")
_PORT_IN_SCRIPT = re.compile(r"(?:--port[ =]|-p[ =]|PORT=)(\d{2,5})")


class StartPlanError(Exception):
    """No way to start the project could be determined."""


@dataclass
class StartPlan:
    argv: list[str]
    display: str
    port: int
    cwd: Path
    framework: str = "unknown"
    env: dict[str, str] = field(default_factory=dict)
    install_argv: Optional[list[str]] = None
    ready_path: str = "/"
    ready_timeout: float = 120.0

    @property
    def url(self) -> str:
        return f"http://{HOST}:{self.port}/"


def plan_start(project_dir: str | Path, settings: Optional[AppSettings] = None) -> StartPlan:
    project = Path(project_dir).resolve()
    settings = settings or AppSettings()
    pkg = _read_package_json(project)
    manager = package_manager(project, pkg)
    install = _install_argv(manager) if pkg is not None and settings.install and not (project / "node_modules").is_dir() else None

    if settings.start:
        port = settings.port or free_port()
        command = settings.start.replace("{port}", str(port))
        return StartPlan(
            argv=_shell_argv(command),
            display=command,
            port=port,
            cwd=project,
            framework="configured",
            env={"PORT": str(port), **settings.env},
            install_argv=install,
            ready_path=settings.ready_path,
            ready_timeout=settings.ready_timeout,
        )

    if pkg is None:
        raise StartPlanError(
            f"Don't know how to start '{project.name}': no package.json and no [app].start in contexer.toml."
        )
    scripts: dict[str, str] = {k: str(v) for k, v in (pkg.get("scripts") or {}).items()}
    script = next((s for s in _SCRIPT_PREFERENCE if s in scripts), None)
    if script is None:
        raise StartPlanError(
            f"package.json has no {'/'.join(_SCRIPT_PREFERENCE)} script; set [app].start in contexer.toml."
        )

    body = scripts[script]
    framework = detect_framework(body, pkg)
    pinned = _PORT_IN_SCRIPT.search(body)
    port = int(pinned.group(1)) if pinned else (settings.port or free_port())
    extra = [] if pinned else _port_args(framework, port)
    argv = _run_script_argv(manager, script, extra)
    env = {"PORT": str(port), "BROWSER": "none", "HOST": HOST, **settings.env}
    return StartPlan(
        argv=argv,
        display=" ".join([manager, "run", script, *(["--"] if extra and manager == "npm" else []), *extra]),
        port=port,
        cwd=project,
        framework=framework,
        env=env,
        install_argv=install,
        ready_path=settings.ready_path,
        ready_timeout=settings.ready_timeout,
    )


_FRAMEWORK_COMMANDS = (
    (re.compile(r"\bnext\b"), "next"),
    (re.compile(r"\bastro\b"), "astro"),
    (re.compile(r"\bnuxi?\b|\bnuxt\b"), "nuxt"),
    (re.compile(r"\bvite\b"), "vite"),
    (re.compile(r"\breact-scripts\b"), "cra"),
)


def detect_framework(script_body: str, pkg: dict) -> str:
    """The dev server the script actually runs, from the command first, then dependencies."""
    command = script_body.lower()
    for pattern, name in _FRAMEWORK_COMMANDS:
        if pattern.search(command):
            return name
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    if "next" in deps:
        return "next"
    if "vite" in deps or any(d.startswith("@vitejs/") for d in deps):
        return "vite"
    return "unknown"


def _port_args(framework: str, port: int) -> list[str]:
    if framework == "vite":
        return ["--port", str(port), "--strictPort", "--host", HOST]
    if framework == "next":
        return ["-p", str(port), "-H", HOST]
    if framework in ("astro", "nuxt"):
        return ["--port", str(port), "--host", HOST]
    return []  # PORT / HOST environment variables only


def package_manager(project: Path, pkg: Optional[dict]) -> str:
    declared = str((pkg or {}).get("packageManager") or "")
    for name in ("pnpm", "yarn", "bun", "npm"):
        if declared.startswith(name):
            return name
    if (project / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (project / "yarn.lock").exists():
        return "yarn"
    if (project / "bun.lockb").exists() or (project / "bun.lock").exists():
        return "bun"
    return "npm"


def _run_script_argv(manager: str, script: str, extra: list[str]) -> list[str]:
    exe = _resolve(manager)
    if manager == "npm":
        return [exe, "run", script, *(["--", *extra] if extra else [])]
    return [exe, "run", script, *extra]


def _install_argv(manager: str) -> list[str]:
    return [_resolve(manager), "install"]


def _resolve(executable: str) -> str:
    """Full path to an executable (``npm`` is ``npm.cmd`` on Windows)."""
    return shutil.which(executable) or executable


def _shell_argv(command: str) -> list[str]:
    if sys.platform == "win32":
        return ["cmd.exe", "/d", "/s", "/c", command]
    return ["/bin/sh", "-c", command]


def _read_package_json(project: Path) -> Optional[dict]:
    path = project / "package.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StartPlanError(f"Unreadable package.json: {exc}") from exc
    return data if isinstance(data, dict) else None


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        return int(s.getsockname()[1])
