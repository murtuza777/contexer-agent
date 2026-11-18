"""The repair benchmark: the same seeded bugs, fixed by a coding agent on each engine, compared.

The coding agent is scripted here; the engines, the snapshots, the app and the browser checks are real.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from contexer.agents import ScriptedAgent
from contexer.bench.repair import WARM_UP_PROMPT, RepairRun, results_markdown, run_repair_bench
from contexer.cli import app as cli
from tests.loop_helpers import BROKEN_JS, FIXTURE, GOOD_JS, fast_runner

pytestmark = pytest.mark.anyio


@pytest.fixture
def fixtures(tmp_path: Path) -> Path:
    """A fixtures folder with one app (todo) and two of its bugs."""
    root = tmp_path / "fixtures"
    shutil.copytree(FIXTURE / "app", root / "todo" / "app", ignore=shutil.ignore_patterns("runs"))
    for bug in ("count-ignores-done", "complete-throws"):
        shutil.copytree(FIXTURE / "bugs" / bug, root / "todo" / "bugs" / bug)
    return root


def _fixes() -> ScriptedAgent:
    return ScriptedAgent([{"app.js": GOOD_JS}])


async def _bench(fixtures: Path, make_agent: Any, **kwargs: Any) -> Any:
    return await run_repair_bench(fixtures, make_agent, runner=fast_runner(), **kwargs)


async def test_every_bug_is_run_on_both_engines_and_scored_per_engine(fixtures: Path) -> None:
    seen: list[RepairRun] = []
    report = await _bench(fixtures, _fixes, on_run=seen.append)

    assert [(r.app, r.bug, r.engine) for r in report.runs] == [
        ("todo", "complete-throws", "classic"),
        ("todo", "complete-throws", "graph"),
        ("todo", "count-ignores-done", "classic"),
        ("todo", "count-ignores-done", "graph"),
    ]
    assert seen == report.runs
    assert all(r.fixed and r.terminal == "succeeded" and r.attempts == 1 for r in report.runs)
    assert [(s.engine, s.bugs, s.fixed, s.first_try, s.attempts) for s in report.scores] == [
        ("classic", 2, 2, 2, 2),
        ("graph", 2, 2, 2, 2),
    ]


async def test_each_run_starts_from_the_bug_not_from_the_last_runs_fix(fixtures: Path) -> None:
    found: list[str] = []

    class Looks(ScriptedAgent):
        async def run_turn(self, workdir: Path, prompt: str, **kwargs: Any) -> Any:
            found.append((Path(workdir) / "app.js").read_text(encoding="utf-8"))
            return await super().run_turn(workdir, prompt, **kwargs)

    await _bench(fixtures, lambda: Looks([{"app.js": GOOD_JS}]), bugs=["todo/count-ignores-done"])
    bug = (FIXTURE / "bugs" / "count-ignores-done" / "app.js").read_text(encoding="utf-8")
    assert found == [bug, bug]  # once per engine, and the graph run did not inherit the classic run's fix


async def test_a_bug_the_agent_never_fixes_is_counted_as_not_fixed(fixtures: Path) -> None:
    report = await _bench(
        fixtures, lambda: ScriptedAgent([{"app.js": BROKEN_JS}] * 3), bugs=["todo/count-ignores-done"], rounds=1
    )
    assert [(r.fixed, r.terminal, r.attempts) for r in report.runs] == [(False, "failed_checks", 2)] * 2
    assert all(s.fixed == 0 and s.bugs == 1 for s in report.scores)
    # The project a run leaves is thrown away; the fixture itself is never written to.
    assert (fixtures / "todo" / "app" / "app.js").read_text(encoding="utf-8") == GOOD_JS


async def test_repair_only_makes_every_fix_a_repair_and_opens_a_session_first(fixtures: Path) -> None:
    """Where the engines differ is the repair. A first turn that changes nothing puts every bug there."""
    agents: list[ScriptedAgent] = []

    def make() -> ScriptedAgent:
        agents.append(ScriptedAgent([{}, {"app.js": GOOD_JS}]))
        return agents[-1]

    report = await _bench(fixtures, make, bugs=["todo/count-ignores-done"], repair_only=True)

    assert [(r.engine, r.fixed, r.attempts) for r in report.runs] == [("classic", True, 2), ("graph", True, 2)]
    assert [(s.first_try, s.after_repair) for s in report.scores] == [(0, 1), (0, 1)]
    for agent in agents:
        # The agent is given the whole job and told to change nothing yet, so both engines start level
        assert agent.prompts[0].endswith(WARM_UP_PROMPT) and "Acceptance checks" in agent.prompts[0]
        assert agent.sessions == [None, "scripted-1"]  # and the repair continues the session that turn opened
        assert "complete-decrements" in agent.prompts[1]


async def test_engines_bugs_and_a_limit_can_be_chosen(fixtures: Path) -> None:
    report = await _bench(fixtures, _fixes, engines=["graph"], limit=1)
    assert [(r.bug, r.engine) for r in report.runs] == [("complete-throws", "graph")]
    with pytest.raises(ValueError, match="engine"):
        await _bench(fixtures, _fixes, engines=["langgraph"])
    with pytest.raises(ValueError, match="no bug"):
        await _bench(fixtures, _fixes, bugs=["todo/does-not-exist"])


async def test_an_agent_that_cannot_run_is_recorded_and_the_benchmark_goes_on(fixtures: Path) -> None:
    report = await _bench(fixtures, lambda: ScriptedAgent([], fail_after=0), engines=["classic"])
    assert [(r.fixed, r.terminal) for r in report.runs] == [(False, "agent_error")] * 2
    assert "scripted failure" in report.runs[0].error


async def test_the_results_say_who_fixed_what_and_where_the_engines_differ(fixtures: Path) -> None:
    turn = {"n": 0}

    def make() -> ScriptedAgent:
        turn["n"] += 1
        # Run 1 is classic on complete-throws: it never fixes it. Every other run fixes at once.
        return ScriptedAgent([{"app.js": BROKEN_JS}] * 3) if turn["n"] == 1 else _fixes()

    report = await _bench(fixtures, make, rounds=1)
    report.agent = "scripted"
    text = results_markdown(report)

    assert "| classic | 2 | 1 |" in text and "| graph | 2 | 2 |" in text
    assert "todo/complete-throws" in text and "only graph" in text.lower()
    assert "todo/count-ignores-done" not in text.split("differ")[-1]  # bugs both engines fixed are not listed there
    assert "scripted" in text


def test_the_command_runs_the_repair_suite_and_writes_the_report(fixtures: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("contexer.cli.run_cli.crew_model", lambda *_a, **_k: None)
    turns = tmp_path / "turns.json"
    turns.write_text(json.dumps([{"app.js": GOOD_JS}]), encoding="utf-8")
    out = tmp_path / "repair.json"
    result = CliRunner().invoke(
        cli,
        ["bench", "--suite", "repair", "--fixtures", str(fixtures), "--agent", "scripted", "--model", str(turns),
         "--limit", "1", "--out", str(out)],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    data = json.loads(out.read_text(encoding="utf-8"))
    assert [(r["engine"], r["fixed"]) for r in data["runs"]] == [("classic", True), ("graph", True)]
    assert out.with_suffix(".md").is_file()


def test_the_repair_suite_needs_a_coding_agent(fixtures: Path) -> None:
    result = CliRunner().invoke(cli, ["bench", "--suite", "repair", "--fixtures", str(fixtures)])
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)  # CI colours the usage text
    assert result.exit_code == 2 and "--agent" in plain
