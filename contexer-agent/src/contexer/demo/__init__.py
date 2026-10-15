"""A self-contained demo: a todo app with a bug an AI agent left in, and its approved contract.

``contexer demo`` needs no API key and no coding agent. It proves the
contract in Chromium (the bug is caught with evidence), and with ``--fix``
shows the repair loop driven by a *simulated* agent that applies a known
fix — clearly labelled, so nobody mistakes it for a real agent run.
"""

from __future__ import annotations

import shutil
from pathlib import Path

DEMO_ROOT = Path(__file__).resolve().parent / "todo"
_APP_FILES = ("index.html", "style.css", "app.js")


def create_demo_project(target: Path) -> Path:
    """Copy the buggy demo app and install its approved contract into ``target``."""
    target = target.resolve()
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"{target} is not empty")
    target.mkdir(parents=True, exist_ok=True)
    for name in _APP_FILES:
        shutil.copyfile(DEMO_ROOT / name, target / name)
    from contexer.contract.store import CONTEXER_DIR, CONTRACTS_DIR, ensure_contexer_dir

    ensure_contexer_dir(target)
    contracts = target / CONTEXER_DIR / CONTRACTS_DIR
    contracts.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DEMO_ROOT / "contract.json", contracts / "todo-basics.json")
    return target


def fixed_app_js() -> str:
    return (DEMO_ROOT / "app.fixed.js").read_text(encoding="utf-8")
