"""The run controller end to end: scripted agent, real snapshots, real browser checks."""

import shutil
from pathlib import Path

import pytest

from contexer.agents import ScriptedAgent
from contexer.contract import ContractStore
from contexer.controller import RunController, RunSettings
from contexer.verification.runner import CheckRunner

pytestmark = pytest.mark.anyio

FIXTURE = Path(__file__).resolve().parents[1] / "bench" / "fixtures" / "todo"
GOOD_JS = (FIXTURE / "app" / "app.js").read_text(encoding="utf-8")
COUNT_BUG_JS = (FIXTURE / "bugs" / "count-ignores-done" / "app.js").read_text(encoding="utf-8")
BROKEN_JS = "throw new Error('half-finished refactor');\n"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    target = tmp_path / "todo"
    shutil.copytree(FIXTURE / "app", target, ignore=shutil.ignore_patterns("runs"))
    (target / ".env").write_text("SECRET=keep-me\n", encoding="utf-8")
    return target


def _controller(project: Path, agent: ScriptedAgent, rounds: int = 2) -> RunController:
    fast = CheckRunner(action_timeout=1.5, expect_timeout=1.0)
    return RunController(project, agent, RunSettings(max_repair_rounds=rounds), runner=fast)


def _contract(project: Path):
    return ContractStore(project).load("todo-basics")


async def test_repair_turns_a_failing_attempt_into_a_pass(project: Path) -> None:
    agent = ScriptedAgent([{"app.js": COUNT_BUG_JS}, {"app.js": GOOD_JS}])
    outcome = await _controller(project, agent).run(_contract(project))

    assert outcome.terminal == "succeeded", outcome.reason
    assert [a.outcome for a in outcome.attempts] == ["fail", "pass"]
    assert outcome.best_attempt == 2
    assert outcome.exit_code == 0
    # The repair prompt carried browser evidence, and the session was resumed.
    assert "complete-decrements" in agent.prompts[1] and "expected" in agent.prompts[1]
    assert agent.sessions == [None, "scripted-1"]
    assert (project / ".env").read_text(encoding="utf-8") == "SECRET=keep-me\n"


async def test_worse_attempt_is_reverted_and_the_best_state_is_kept(project: Path) -> None:
    agent = ScriptedAgent([{"app.js": COUNT_BUG_JS}, {"app.js": BROKEN_JS}, {"app.js": BROKEN_JS}])
    outcome = await _controller(project, agent).run(_contract(project))

    assert outcome.terminal == "failed_checks"
    assert outcome.attempts[1].reverted_to == 1
    assert "reverted the files to attempt 1" in agent.prompts[2]
    assert agent.sessions[2] is None  # after a revert the next repair starts fresh
    assert outcome.best_attempt == 1
    # The project is left at attempt 1 (the best one), not at the broken last attempt.
    assert (project / "app.js").read_text(encoding="utf-8") == COUNT_BUG_JS
    assert outcome.exit_code == 1


async def test_same_failure_twice_switches_to_a_fresh_session(project: Path) -> None:
    agent = ScriptedAgent([{"app.js": COUNT_BUG_JS}, {"app.js": COUNT_BUG_JS + "\n// tweak\n"}, {"app.js": GOOD_JS}])
    outcome = await _controller(project, agent).run(_contract(project))

    assert outcome.terminal == "succeeded"
    assert agent.sessions == [None, "scripted-1", None]
    assert "failed in exactly the same way" in agent.prompts[2]
    assert "todo-basics/complete-decrements" in agent.prompts[2]
    # A fresh session gets the whole contract restated.
    assert "Acceptance checks" in agent.prompts[2]


async def test_editing_the_contract_refutes_the_run_and_restores_it(project: Path) -> None:
    contract_path = project / ".contexer" / "contracts" / "todo-basics.json"
    original = contract_path.read_bytes()
    agent = ScriptedAgent([{".contexer/contracts/todo-basics.json": "{}", "app.js": COUNT_BUG_JS}])
    outcome = await _controller(project, agent).run(_contract(project))

    assert outcome.terminal == "tampered"
    assert contract_path.read_bytes() == original
    assert (project / "app.js").read_text(encoding="utf-8") == GOOD_JS  # rolled back to the baseline
    assert outcome.exit_code == 2


async def test_agent_failure_without_changes_stops_cleanly(project: Path) -> None:
    agent = ScriptedAgent([], fail_after=0)
    outcome = await _controller(project, agent).run(_contract(project))
    assert outcome.terminal == "agent_error"
    assert "scripted failure" in outcome.reason
    assert outcome.exit_code == 3


async def test_unapproved_contract_is_rejected(project: Path) -> None:
    contract = _contract(project).model_copy(update={"approval": None})
    with pytest.raises(ValueError, match="approved"):
        await _controller(project, ScriptedAgent([])).run(contract)
