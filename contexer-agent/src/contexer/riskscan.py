"""A look at the project before a coding agent works in it: what could leak into a commit or a pull request.

A run ends in files a coding agent wrote, and with ``--pr`` in a commit that
is pushed. Two things in a project make that risky, and both can be seen
before anything is spent:

* an environment file (``.env``, ``.env.*``, ``.dev.vars``) that git does not
  ignore, or that is committed already;
* a secret in a committed file.

The scan reports; it never blocks a run and never prints a secret. It needs
git: a folder that is not a repository has nothing that can be committed.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from pydantic import BaseModel

from contexer.crew.reviewer import secret_kind

MAX_RISKS = 20
_MAX_FILES = 3000
_MAX_BYTES = 200_000
_EXAMPLE_ENDINGS = (".example", ".sample", ".template", ".dist", ".defaults")
_SKIP_SUFFIXES = (".lock", ".min.js", ".map", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".pdf")
_SKIP_NAMES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock"}


class Risk(BaseModel):
    kind: str  # env-not-ignored | env-committed | secret-committed
    path: str
    line: int = 0
    message: str


def is_env_file(name: str) -> bool:
    """``.env``, ``.env.local``, ``.dev.vars``: files that hold real values. Their examples do not."""
    if name.endswith(_EXAMPLE_ENDINGS):
        return False
    return name == ".env" or name.startswith(".env.") or name == ".dev.vars" or name.startswith(".dev.vars.")


def scan_project(project_dir: str | Path) -> list[Risk]:
    """The risks in ``project_dir``, the same order every time. Empty when it is not a git repository."""
    project = Path(project_dir).resolve()
    if _git(project, "rev-parse", "--is-inside-work-tree") != "true":
        return []
    tracked = [line for line in (_git(project, "ls-files", "-z") or "").split("\0") if line]
    tracked_set = set(tracked)
    risks: list[Risk] = []

    try:
        here = sorted(p.name for p in project.iterdir() if p.is_file() and is_env_file(p.name))
    except OSError:
        here = []
    for name in here:
        if name in tracked_set:
            risks.append(
                Risk(
                    kind="env-committed",
                    path=name,
                    message=f"{name} is committed. Its values are in the repository's history: move them out, "
                    f"add {name} to .gitignore, and change any that are real.",
                )
            )
        elif _git(project, "check-ignore", "--quiet", name) is None:
            risks.append(
                Risk(
                    kind="env-not-ignored",
                    path=name,
                    message=f"{name} is not ignored by git, so a commit could include it. Add it to .gitignore.",
                )
            )

    for path in tracked[:_MAX_FILES]:
        if len(risks) >= MAX_RISKS:
            break
        name = path.rsplit("/", 1)[-1]
        if is_env_file(name) or name in _SKIP_NAMES or name.endswith(_SKIP_SUFFIXES):
            continue
        file = project / path
        try:
            if not file.is_file() or file.stat().st_size > _MAX_BYTES:
                continue
            lines = file.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for number, text in enumerate(lines, 1):
            found = secret_kind(text)
            if found:
                risks.append(
                    Risk(
                        kind="secret-committed",
                        path=path,
                        line=number,
                        message=f"{path}:{number} holds what looks like a secret ({found}), and it is committed. "
                        "Read it from the environment, and change the value if it is real.",
                    )
                )
                break  # one line per file is enough to send a person there
    return risks[:MAX_RISKS]


def _git(cwd: Path, *args: str) -> str | None:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        out = subprocess.run(
            ["git", *args], cwd=str(cwd), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip("\n") if out.returncode == 0 else None
