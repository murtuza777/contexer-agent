"""Ctrl+C during `contexer run`: one press stops the run in order, and a second one cannot cut that short.

The first press stops the agent, keeps the unfinished work and puts the project back (graph/engine.py).
A second press used to raise wherever the program was, which could be in the middle of putting files
back. These tests press for real (`signal.raise_signal`) from inside a scripted agent's turn.
"""

from __future__ import annotations

import asyncio
import json
import re
import signal
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from contexer.agents import ScriptedAgent
from contexer.cli import app as cli
from contexer.cli import run_cli
from contexer.contract import ContractStore
from tests.fakes import AgentScript, submit
from tests.loop_helpers import CONTRACT_ID, COUNT_BUG_JS, GOAL, GOOD_JS, contract_checks, copy_todo

LOCK = Path(".contexer") / "run.lock"


def _plain(text: str) -> str:
    return " ".join(re.sub(r"\x1b\[[0-9;]*m", "", text).split())


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return copy_todo(tmp_path)


@pytest.fixture(autouse=True)
def setup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONTEXER_ENGINE", raising=False)
    monkeypatch.setattr(run_cli, "compiler_llm", lambda *_a, **_k: None)
    monkeypatch.setattr(run_cli, "crew_model", lambda *_a, **_k: None)


class _Pressed(ScriptedAgent):
    """Writes a half-done change, then Ctrl+C is pressed while it works; and again while Contexer stops it."""

    def __init__(self, presses_while_stopping: int) -> None:
        super().__init__([])
        self.presses_while_stopping = presses_while_stopping
        self.stops = 0

    async def run_turn(self, workdir: Path, prompt: str, **kwargs: Any) -> Any:
        (Path(workdir) / "app.js").write_text(COUNT_BUG_JS, encoding="utf-8", newline="")
        signal.raise_signal(signal.SIGINT)
        await asyncio.sleep(3600)

    def stop(self) -> None:
        # The engine calls this at the start of an orderly stop, before the files are put back.
        self.stops += 1
        if self.stops == 1:
            for _ in range(self.presses_while_stopping):
                signal.raise_signal(signal.SIGINT)
        super().stop()


def _lock_file(project: Path) -> Path:
    from contexer.checkpoint import lock

    return project / lock.LOCK_FILE


def _stopped(project: Path, monkeypatch: pytest.MonkeyPatch, presses_while_stopping: int) -> Any:
    before = signal.getsignal(signal.SIGINT)
    with monkeypatch.context() as patch:
        patch.setattr(run_cli, "create_agent", lambda *_a, **_k: _Pressed(presses_while_stopping))
        result = CliRunner().invoke(cli, ["run", "--dir", str(project), "--agent", "scripted", "--contract", CONTRACT_ID])
    assert signal.getsignal(signal.SIGINT) is before  # Ctrl+C is what it was once the run is over
    return result


def _run_json(project: Path) -> dict[str, Any]:
    [run] = [p for p in (project / ".contexer" / "runs").iterdir() if p.is_dir()]
    return json.loads((run / "run.json").read_text(encoding="utf-8"))


def test_one_ctrl_c_stops_the_agent_puts_the_project_back_and_says_how_to_resume(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _stopped(project, monkeypatch, presses_while_stopping=0)
    out = _plain(result.output)
    assert result.exit_code == 130, result.output
    assert (project / "app.js").read_text(encoding="utf-8") == GOOD_JS
    run = _run_json(project)
    assert run["terminal"] == "cancelled"
    assert "Stopping" in out  # said at once, before the files are back
    assert f"contexer run --resume {run['run_id']}" in out and f"contexer restore {run['run_id']} --stopped" in out
    assert not _lock_file(project).exists()


@pytest.mark.parametrize("presses", [1, 3])
def test_a_second_ctrl_c_while_the_project_is_put_back_does_not_cut_that_short(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, presses: int
) -> None:
    result = _stopped(project, monkeypatch, presses_while_stopping=presses)
    out = _plain(result.output)
    assert result.exit_code == 130, result.output
    # The project is whole: as it was, not as the agent left it in the middle of its turn.
    assert (project / "app.js").read_text(encoding="utf-8") == GOOD_JS
    run = _run_json(project)
    assert run["terminal"] == "cancelled"
    assert "Still putting the project back" in out and "Nothing was changed" not in out
    assert not _lock_file(project).exists()

    # The run that was stopped twice is a run like any other: it can be continued.
    turns = tmp_path / "turns.json"
    turns.write_text(json.dumps([{"app.js": GOOD_JS}]), encoding="utf-8")
    again = CliRunner().invoke(
        cli, ["run", "--dir", str(project), "--agent", "scripted", "--model", str(turns), "--resume", run["run_id"]]
    )
    assert again.exit_code == 0, again.output


def test_ctrl_c_at_the_approval_question_leaves_the_question_and_approves_nothing(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / ".contexer" / "contracts" / f"{CONTRACT_ID}.json").unlink()
    model = AgentScript(intent=[submit(behaviours=["Tasks can be added"], checks=contract_checks())])
    monkeypatch.setattr(run_cli, "crew_model", lambda *_a, **_k: model)
    monkeypatch.setattr(run_cli, "is_interactive", lambda: True)

    left: list[bool] = []

    def prompt(*_args: Any, **_kwargs: Any) -> str:
        try:
            signal.raise_signal(signal.SIGINT)
        except KeyboardInterrupt:
            left.append(True)
            raise typer.Abort() from None  # what click does with Ctrl+C at a prompt
        return "y"  # the press did not reach the question: the line that was being typed is taken

    monkeypatch.setattr(run_cli.typer, "prompt", prompt)
    monkeypatch.setattr(run_cli, "create_agent", lambda *_a, **_k: ScriptedAgent([{"app.js": COUNT_BUG_JS}]))
    before = signal.getsignal(signal.SIGINT)
    result = CliRunner().invoke(cli, ["run", "--dir", str(project), "--agent", "scripted", GOAL])
    assert signal.getsignal(signal.SIGINT) is before
    assert result.exit_code == 130, result.output
    assert left  # the press left the question; it was not swallowed while a line was typed
    [stored] = ContractStore(project).list()
    assert stored.status == "draft"
    assert (project / "app.js").read_text(encoding="utf-8") == GOOD_JS
    assert not _lock_file(project).exists()
