"""``contexer run`` on two engines (T3.4): `--engine`, `--resume`, and the questions a run can ask."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from contexer.agents import ScriptedAgent
from contexer.cli import app as cli
from contexer.contract import ContractStore
from contexer.controller import RunSettings
from contexer.graph import GraphController
from tests.fakes import AgentScript, submit
from tests.loop_helpers import (
    CONTRACT_ID,
    COUNT_BUG_JS,
    GOAL,
    GOOD_JS,
    contract,
    contract_checks,
    copy_todo,
    fast_runner,
)


def _plain(text: str) -> str:
    return " ".join(re.sub(r"\x1b\[[0-9;]*m", "", text).split())


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return copy_todo(tmp_path)


@pytest.fixture(autouse=True)
def crew(monkeypatch: pytest.MonkeyPatch) -> Any:
    """No model for Contexer's own agents unless a test installs one: `crew(AgentScript(...))`."""
    monkeypatch.delenv("CONTEXER_ENGINE", raising=False)
    monkeypatch.setattr("contexer.cli.run_cli.compiler_llm", lambda *_a, **_k: None)

    def install(model: Any) -> Any:
        monkeypatch.setattr("contexer.cli.run_cli.crew_model", lambda *_a, **_k: model)
        return model

    install(None)
    return install


def _turns(tmp_path: Path, *turns: dict[str, str]) -> str:
    path = tmp_path / f"turns-{len(list(tmp_path.glob('turns-*.json')))}.json"
    path.write_text(json.dumps(list(turns)), encoding="utf-8")
    return str(path)


def _run(project: Path, *args: str, input: str | None = None) -> Any:
    return CliRunner().invoke(cli, ["run", "--dir", str(project), "--agent", "scripted", *args], input=input)


def _latest(project: Path) -> dict[str, Any]:
    runs = [p for p in (project / ".contexer" / "runs").iterdir() if (p / "run.json").is_file()]
    return json.loads((max(runs, key=lambda p: p.stat().st_mtime_ns) / "run.json").read_text(encoding="utf-8"))


REPAIR = ({"app.js": COUNT_BUG_JS}, {"app.js": GOOD_JS})


# -- choosing the engine ----------------------------------------------------------------------------


def test_the_graph_engine_is_the_default_and_classic_can_be_asked_for(project: Path, tmp_path: Path) -> None:
    result = _run(project, "--contract", CONTRACT_ID, "--model", _turns(tmp_path, *REPAIR))
    assert result.exit_code == 0, result.output
    assert _latest(project)["engine"] == "graph"
    result = _run(project, "--contract", CONTRACT_ID, "--model", _turns(tmp_path, *REPAIR), "--engine", "classic")
    assert result.exit_code == 0, result.output
    assert _latest(project)["engine"] == "classic"


def test_engine_graph_runs_the_same_job_on_the_graph(project: Path, tmp_path: Path) -> None:
    result = _run(project, "--contract", CONTRACT_ID, "--model", _turns(tmp_path, *REPAIR), "--engine", "graph")
    out = _plain(result.output)
    assert result.exit_code == 0, result.output
    run = _latest(project)
    assert run["engine"] == "graph" and run["terminal"] == "succeeded" and len(run["attempts"]) == 2
    assert "fixed rules decide" in out  # no model is configured for triage, and the run says so


def test_the_environment_can_choose_the_engine_and_the_flag_wins(project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXER_ENGINE", "graph")
    assert _run(project, "--contract", CONTRACT_ID, "--model", _turns(tmp_path, {"app.js": GOOD_JS})).exit_code == 0
    assert _latest(project)["engine"] == "graph"
    result = _run(project, "--contract", CONTRACT_ID, "--model", _turns(tmp_path, {"app.js": GOOD_JS}), "--engine", "classic")
    assert result.exit_code == 0 and _latest(project)["engine"] == "classic"


@pytest.mark.parametrize("how", ["flag", "env"])
def test_an_engine_that_does_not_exist_is_refused_before_anything_runs(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    args = ["--contract", CONTRACT_ID, "--model", _turns(tmp_path, {"app.js": GOOD_JS})]
    if how == "flag":
        args += ["--engine", "langgraph"]
    else:
        monkeypatch.setenv("CONTEXER_ENGINE", "langgraph")
    result = _run(project, *args)
    assert result.exit_code == 2 and "graph or classic" in _plain(result.output)
    assert not (project / ".contexer" / "runs").exists()


def test_a_triage_decision_by_a_model_is_printed_with_its_reason(project: Path, tmp_path: Path, crew: Any) -> None:
    crew(AgentScript(triage=[submit(move="fresh_approach", reason="The first idea was a dead end.")]))
    result = _run(project, "--contract", CONTRACT_ID, "--model", _turns(tmp_path, *REPAIR), "--engine", "graph")
    out = _plain(result.output)
    assert result.exit_code == 0, result.output
    assert "fresh approach" in out.lower() and "The first idea was a dead end." in out
    assert "fixed rules decide" not in out


# -- a goal, drafted and approved inside the run -------------------------------------------------


def _goal_run(project: Path, tmp_path: Path, crew: Any, *args: str, input: str | None = None) -> Any:
    (project / ".contexer" / "contracts" / f"{CONTRACT_ID}.json").unlink()
    crew(AgentScript(intent=[submit(behaviours=["Tasks can be added"], checks=contract_checks())]))
    return _run(project, GOAL, "--model", _turns(tmp_path, {"app.js": GOOD_JS}), "--engine", "graph", *args, input=input)


def test_a_goal_is_drafted_shown_and_built_once_approved(project: Path, tmp_path: Path, crew: Any) -> None:
    result = _goal_run(project, tmp_path, crew, input="y\n")
    out = _plain(result.output)
    assert result.exit_code == 0, result.output
    assert "complete-decrements" in out and "Approve" in out
    assert _latest(project)["terminal"] == "succeeded"
    [stored] = ContractStore(project).list()
    assert stored.status == "approved"


def test_a_goal_that_is_not_approved_builds_nothing(project: Path, tmp_path: Path, crew: Any) -> None:
    result = _goal_run(project, tmp_path, crew, input="n\n")
    assert result.exit_code == 2, result.output
    assert (project / "app.js").read_text(encoding="utf-8") == GOOD_JS
    assert _latest(project)["attempts"] == []


def test_yes_approves_without_asking(project: Path, tmp_path: Path, crew: Any) -> None:
    result = _goal_run(project, tmp_path, crew, "--yes")
    assert result.exit_code == 0, result.output
    assert "Approve these checks" not in _plain(result.output)


def test_a_correction_typed_instead_of_yes_redrafts_the_checks(project: Path, tmp_path: Path, crew: Any) -> None:
    (project / ".contexer" / "contracts" / f"{CONTRACT_ID}.json").unlink()
    heading = {
        "id": "heading-says-my-tasks",
        "description": "The page heading says 'My tasks'",
        "check": {"steps": [], "expect": [{"kind": "visible", "target": {"role": "heading", "name": "My tasks"}}]},
    }
    crew(
        AgentScript(
            intent=[
                submit(behaviours=["Tasks can be added"], checks=contract_checks()),
                submit(behaviours=["The heading says 'My tasks'"], checks=[heading]),
            ]
        )
    )
    built = GOOD_JS + "document.querySelector('h1').textContent = 'My tasks';\n"
    result = _run(
        project, GOAL, "--model", _turns(tmp_path, {"app.js": built}), "--engine", "graph",
        input="The heading must say 'My tasks'.\ny\n",
    )  # fmt: skip
    out = _plain(result.output)
    assert result.exit_code == 0, result.output
    assert out.count("Approve") >= 2 and "heading-says-my-tasks" in out
    assert _latest(project)["corrections"] == ["The heading must say 'My tasks'."]


# -- --resume -----------------------------------------------------------------------------------------


class _Stuck(ScriptedAgent):
    def __init__(self, turns: list[dict[str, str | None]]) -> None:
        super().__init__(turns)
        self.started: asyncio.Event | None = None

    async def run_turn(self, workdir: Path, prompt: str, **kwargs: Any) -> Any:
        if len(self.prompts) == 1:
            assert self.started is not None
            self.started.set()
            await asyncio.sleep(3600)
        return await super().run_turn(workdir, prompt, **kwargs)


def _stopped_run(project: Path) -> str:
    async def go() -> str:
        agent = _Stuck([{"app.js": COUNT_BUG_JS}])
        agent.started = asyncio.Event()
        controller = GraphController(project, agent, RunSettings(), runner=fast_runner())
        task = asyncio.create_task(controller.run(contract(project)))
        await asyncio.wait_for(agent.started.wait(), 60)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert controller.last_outcome is not None
        return controller.last_outcome.run_id

    return asyncio.run(go())


def test_resume_continues_a_stopped_run(project: Path, tmp_path: Path) -> None:
    run_id = _stopped_run(project)
    result = _run(project, "--resume", run_id, "--model", _turns(tmp_path, {"app.js": GOOD_JS}))
    out = _plain(result.output)
    assert result.exit_code == 0, result.output
    assert "Resuming" in out and run_id in out
    run = _latest(project)
    assert run["run_id"] == run_id and run["terminal"] == "succeeded" and len(run["attempts"]) == 2


def test_resume_of_a_run_that_does_not_exist_says_so(project: Path, tmp_path: Path) -> None:
    result = _run(project, "--resume", "20260101-000000-abcd", "--model", _turns(tmp_path, {"app.js": GOOD_JS}))
    assert result.exit_code == 2 and "no run" in _plain(result.output).lower()


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--resume", "x", "--contract", CONTRACT_ID], "give a GOAL, --contract ID, --issue N or --resume RUN"),
        (["--resume", "x", "--engine", "classic"], "graph engine"),
        (["--contract", CONTRACT_ID, "--correct", "Make it blue"], "--correct"),
    ],
)
def test_options_that_do_not_go_together_are_refused(project: Path, tmp_path: Path, args: list[str], message: str) -> None:
    result = _run(project, *args, "--model", _turns(tmp_path, {"app.js": GOOD_JS}))
    assert result.exit_code == 2 and message in _plain(result.output)
