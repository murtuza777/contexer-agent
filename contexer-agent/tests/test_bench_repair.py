"""The repair benchmark: seeded bugs, handed to a coding agent that Contexer drives, and counted.

The coding agent is scripted here; the run loop, the snapshots, the app and the browser checks are real.
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


async def test_every_bug_is_run_once_and_scored(fixtures: Path) -> None:
    seen: list[RepairRun] = []
    report = await _bench(fixtures, _fixes, on_run=seen.append)

    assert [(r.app, r.bug) for r in report.runs] == [("todo", "complete-throws"), ("todo", "count-ignores-done")]
    assert seen == report.runs
    assert all(r.fixed and r.terminal == "succeeded" and r.attempts == 1 for r in report.runs)
    score = report.score
    assert (score.bugs, score.fixed, score.first_try, score.after_repair, score.attempts) == (2, 2, 2, 0, 2)


async def test_each_run_starts_from_the_bug_not_from_the_last_runs_fix(fixtures: Path) -> None:
    found: list[str] = []

    class Looks(ScriptedAgent):
        async def run_turn(self, workdir: Path, prompt: str, **kwargs: Any) -> Any:
            found.append((Path(workdir) / "app.js").read_text(encoding="utf-8"))
            return await super().run_turn(workdir, prompt, **kwargs)

    await _bench(fixtures, lambda: Looks([{"app.js": GOOD_JS}]))
    bugs = [(FIXTURE / "bugs" / name / "app.js").read_text(encoding="utf-8") for name in ("complete-throws", "count-ignores-done")]
    assert found == bugs  # the second run did not inherit the first run's fix


async def test_a_bug_the_agent_never_fixes_is_counted_as_not_fixed(fixtures: Path) -> None:
    report = await _bench(
        fixtures, lambda: ScriptedAgent([{"app.js": BROKEN_JS}] * 3), bugs=["todo/count-ignores-done"], rounds=1
    )
    assert [(r.fixed, r.terminal, r.attempts) for r in report.runs] == [(False, "failed_checks", 2)]
    assert report.score.fixed == 0 and report.score.bugs == 1
    # The project a run leaves is thrown away; the fixture itself is never written to.
    assert (fixtures / "todo" / "app" / "app.js").read_text(encoding="utf-8") == GOOD_JS


async def test_repair_only_makes_every_fix_a_repair_and_opens_a_session_first(fixtures: Path) -> None:
    """What is worth measuring is the repair. A first turn that changes nothing puts every bug there."""
    agents: list[ScriptedAgent] = []

    def make() -> ScriptedAgent:
        agents.append(ScriptedAgent([{}, {"app.js": GOOD_JS}]))
        return agents[-1]

    report = await _bench(fixtures, make, bugs=["todo/count-ignores-done"], repair_only=True)

    assert [(r.fixed, r.attempts, r.moves) for r in report.runs] == [(True, 2, ["repair_same_session"])]
    assert (report.score.first_try, report.score.after_repair) == (0, 1)
    agent = agents[0]
    # The agent is given the whole job and told to change nothing yet
    assert agent.prompts[0].endswith(WARM_UP_PROMPT) and "Acceptance checks" in agent.prompts[0]
    assert agent.sessions == [None, "scripted-1"]  # and the repair continues the session that turn opened
    assert "complete-decrements" in agent.prompts[1]


async def test_bugs_and_a_limit_can_be_chosen(fixtures: Path) -> None:
    report = await _bench(fixtures, _fixes, limit=1)
    assert [r.bug for r in report.runs] == ["complete-throws"]
    with pytest.raises(ValueError, match="no bug"):
        await _bench(fixtures, _fixes, bugs=["todo/does-not-exist"])


async def test_an_agent_that_cannot_run_is_recorded_and_the_benchmark_goes_on(fixtures: Path) -> None:
    report = await _bench(fixtures, lambda: ScriptedAgent([], fail_after=0))
    assert [(r.fixed, r.terminal) for r in report.runs] == [(False, "agent_error")] * 2
    assert "scripted failure" in report.runs[0].error


async def test_the_results_name_the_bugs_that_were_not_fixed(fixtures: Path) -> None:
    turn = {"n": 0}

    def make() -> ScriptedAgent:
        turn["n"] += 1
        # The first run (complete-throws) is never fixed. The other is fixed at once.
        return ScriptedAgent([{"app.js": BROKEN_JS}] * 3) if turn["n"] == 1 else _fixes()

    report = await _bench(fixtures, make, rounds=1)
    report.agent = "scripted"
    text = results_markdown(report)

    assert "| 2 | 1 |" in text and "Engine" not in text
    not_fixed = text.split("Not fixed")[-1]
    assert "todo/complete-throws" in not_fixed and "failed_checks after 2 attempt(s)" in not_fixed
    assert "todo/count-ignores-done" not in not_fixed
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
    assert [(r["bug"], r["fixed"]) for r in data["runs"]] == [("complete-throws", True)]
    assert data["score"]["fixed"] == 1
    assert out.with_suffix(".md").is_file()


async def test_repeats_run_every_bug_again_and_the_results_give_the_rate_its_interval(fixtures: Path) -> None:
    from contexer.bench.stats import Rate

    report = await _bench(fixtures, _fixes, repeats=2)
    assert [(r.bug, r.repeat) for r in report.runs] == [
        ("complete-throws", 0), ("count-ignores-done", 0), ("complete-throws", 1), ("count-ignores-done", 1),
    ]  # fmt: skip
    assert (report.score.bugs, report.score.fixed, report.repeats, report.suite) == (4, 4, 2, "repair")
    assert report.rates() == {"seeded bugs fixed": Rate(4, 4)}

    text = results_markdown(report)
    assert "Each bug ran 2 times" in text
    assert "seeded bugs fixed 4/4, 100% (95% interval 51% to 100%)" in text


def test_the_command_repeats_the_repair_suite_and_compares_it_with_an_earlier_report(
    fixtures: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("contexer.cli.run_cli.crew_model", lambda *_a, **_k: None)
    turns = tmp_path / "turns.json"
    turns.write_text(json.dumps([{"app.js": GOOD_JS}]), encoding="utf-8")
    earlier = tmp_path / "earlier.json"
    earlier.write_text(json.dumps({"suite": "repair", "score": {"bugs": 46, "fixed": 46}}), encoding="utf-8")
    out = tmp_path / "repair.json"
    result = CliRunner().invoke(
        cli,
        ["bench", "--suite", "repair", "--fixtures", str(fixtures), "--agent", "scripted", "--model", str(turns),
         "--limit", "1", "--repeats", "2", "--out", str(out), "--compare", str(earlier)],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    data = json.loads(out.read_text(encoding="utf-8"))
    assert [(r["bug"], r["repeat"], r["fixed"]) for r in data["runs"]] == [("complete-throws", 0, True), ("complete-throws", 1, True)]
    said = " ".join(re.sub(r"\x1b\[[0-9;]*m", "", result.output).split())
    assert "seeded bugs fixed 2/2, 100% (95% interval 34% to 100%)" in said
    # Two of two against 46 of 46: nothing here says the two differ.
    assert "was 46/46, 100% (95% interval 92% to 100%)" in said and "cannot be told apart" in said


def test_the_repair_suite_needs_a_coding_agent(fixtures: Path) -> None:
    result = CliRunner().invoke(cli, ["bench", "--suite", "repair", "--fixtures", str(fixtures)])
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)  # CI colours the usage text
    assert result.exit_code == 2 and "--agent" in plain


def test_the_repair_suite_has_no_engine_to_choose(fixtures: Path, tmp_path: Path) -> None:
    result = CliRunner().invoke(cli, ["bench", "--suite", "repair", "--fixtures", str(fixtures), "--agent", "scripted", "--engine", "classic"])
    assert result.exit_code == 2
