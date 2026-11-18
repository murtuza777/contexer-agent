"""What the tests of the run loop share: the todo fixture, its seeded bug, and scripted coding agents."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from contexer.agents import ScriptedAgent
from contexer.contract import Contract, ContractStore
from contexer.verification.runner import CheckRunner

FIXTURE = Path(__file__).resolve().parents[1] / "bench" / "fixtures" / "todo"
GOOD_JS = (FIXTURE / "app" / "app.js").read_text(encoding="utf-8")
COUNT_BUG_JS = (FIXTURE / "bugs" / "count-ignores-done" / "app.js").read_text(encoding="utf-8")
BROKEN_JS = "throw new Error('half-finished refactor');\n"
CONTRACT_ID = "todo-basics"
GOAL = "A todo list: add tasks, complete them, delete them, and see how many are left"


def copy_todo(tmp_path: Path, name: str = "todo") -> Path:
    target = tmp_path / name
    shutil.copytree(FIXTURE / "app", target, ignore=shutil.ignore_patterns("runs"))
    (target / ".env").write_text("SECRET=keep-me\n", encoding="utf-8")
    return target


def fast_runner() -> CheckRunner:
    return CheckRunner(action_timeout=1.5, expect_timeout=1.0)


def contract(project: Path) -> Contract:
    return ContractStore(project).load(CONTRACT_ID)


def contract_checks() -> list[dict[str, Any]]:
    """The fixture's checks, in the shape the Intent agent submits them."""
    data = json.loads((FIXTURE / "app" / ".contexer" / "contracts" / f"{CONTRACT_ID}.json").read_text(encoding="utf-8"))
    return [{"id": c["id"], "description": c["description"], "check": c["check"]} for c in data["criteria"]]


class RecordingAgent(ScriptedAgent):
    """A scripted agent that also notes what ``app.js`` held when each turn began."""

    def __init__(self, turns: list[dict[str, str | None]], **kwargs: Any) -> None:
        super().__init__(turns, **kwargs)
        self.found: list[str] = []

    async def run_turn(self, workdir: Path, prompt: str, **kwargs: Any) -> Any:
        self.found.append((Path(workdir) / "app.js").read_text(encoding="utf-8"))
        return await super().run_turn(workdir, prompt, **kwargs)
