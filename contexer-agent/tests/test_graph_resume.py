"""Stopping, resuming and correcting a run on the graph engine (T3.3)."""

import asyncio
import json
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

import pytest

from contexer.agents import ScriptedAgent
from contexer.agents.base import AgentTurn
from contexer.contract import ContractStore
from contexer.controller import RunOutcome, RunSettings
from contexer.graph import GraphController, ResumeError
from contexer.procutil import spawn_tree
from tests.fakes import AgentScript, submit
from tests.loop_helpers import (
    BROKEN_JS,
    CONTRACT_ID,
    COUNT_BUG_JS,
    GOAL,
    GOOD_JS,
    RecordingAgent,
    contract,
    contract_checks,
    copy_todo,
    fast_runner,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return copy_todo(tmp_path)


def _graph(project: Path, agent: Any, rounds: int = 2, **kwargs: Any) -> GraphController:
    return GraphController(project, agent, RunSettings(max_repair_rounds=rounds), runner=fast_runner(), **kwargs)


def _shape(outcome: RunOutcome) -> dict[str, Any]:
    """What must be the same whether or not a run was interrupted on the way."""
    return {
        "terminal": outcome.terminal,
        "best": outcome.best_attempt,
        "attempts": [(a.n, a.kind, a.outcome, a.verified, a.refuted, a.fresh_session) for a in outcome.attempts],
        "changed": outcome.changed_files,
        "triage": [(d.attempt, d.move) for d in outcome.triage],
    }


class _StuckOnTurn(ScriptedAgent):
    """Plays its turns, then on turn ``stuck`` half-writes a file and never returns."""

    def __init__(self, turns: list[dict[str, str | None]], stuck: int) -> None:
        super().__init__(turns)
        self.stuck = stuck
        self.started = asyncio.Event()

    async def run_turn(self, workdir: Path, prompt: str, **kwargs: Any) -> AgentTurn:
        if len(self.prompts) + 1 == self.stuck:
            (Path(workdir) / "app.js").write_text("half-written\n", encoding="utf-8")
            (Path(workdir) / "junk.js").write_text("// unfinished\n", encoding="utf-8")
            self.started.set()
            await asyncio.sleep(3600)
        return await super().run_turn(workdir, prompt, **kwargs)


async def _stop_in_turn(project: Path, turns: list[dict[str, str | None]], stuck: int) -> RunOutcome:
    agent = _StuckOnTurn(turns, stuck)
    controller = _graph(project, agent)
    task = asyncio.create_task(controller.run(contract(project)))
    await asyncio.wait_for(agent.started.wait(), 60)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert controller.last_outcome is not None
    return controller.last_outcome


# -- Ctrl+C, then --resume ---------------------------------------------------------------------


async def test_a_stopped_run_resumes_and_ends_like_an_uninterrupted_one(tmp_path: Path) -> None:
    straight = copy_todo(tmp_path, "straight")
    expected = await _graph(straight, ScriptedAgent([{"app.js": COUNT_BUG_JS}, {"app.js": GOOD_JS}])).run(contract(straight))

    project = copy_todo(tmp_path, "stopped")
    stopped = await _stop_in_turn(project, [{"app.js": COUNT_BUG_JS}], stuck=2)
    assert stopped.terminal == "cancelled" and stopped.exit_code == 130
    assert (project / "app.js").read_text(encoding="utf-8") == COUNT_BUG_JS  # the best attempt, not the half-written file
    assert not (project / "junk.js").exists()

    agent = RecordingAgent([{"app.js": GOOD_JS}])
    resumed = await _graph(project, agent).resume(stopped.run_id)

    assert resumed.run_id == stopped.run_id
    assert _shape(resumed) == _shape(expected)
    assert resumed.terminal == "succeeded"
    assert agent.found == [COUNT_BUG_JS]  # the turn that was cut off started again from attempt 1's files
    assert agent.sessions == ["scripted-1"]  # in the session the first turn opened
    assert (project / "app.js").read_text(encoding="utf-8") == GOOD_JS
    assert json.loads((Path(resumed.run_dir) / "run.json").read_text(encoding="utf-8"))["terminal"] == "succeeded"


async def test_a_run_stopped_in_its_first_turn_resumes_from_the_project_as_it_was(project: Path) -> None:
    stopped = await _stop_in_turn(project, [], stuck=1)
    assert (project / "app.js").read_text(encoding="utf-8") == GOOD_JS

    agent = RecordingAgent([{"app.js": GOOD_JS + "\n// built\n"}])
    resumed = await _graph(project, agent).resume(stopped.run_id)
    assert resumed.terminal == "succeeded" and agent.found == [GOOD_JS]
    assert [a.n for a in resumed.attempts] == [1]


_KILLED_RUN = """
    import asyncio, sys
    from pathlib import Path
    sys.path.insert(0, {root!r})
    from contexer.agents import ScriptedAgent
    from contexer.contract import ContractStore
    from contexer.controller import RunSettings
    from contexer.graph import GraphController
    from contexer.verification.runner import CheckRunner

    project = Path({project!r})

    class Stuck(ScriptedAgent):
        async def run_turn(self, workdir, prompt, **kwargs):
            if len(self.prompts) == 1:
                (Path(workdir) / "app.js").write_text("half-written\\n", encoding="utf-8")
                Path({marker!r}).write_text("stuck", encoding="utf-8")
                await asyncio.sleep(3600)
            return await super().run_turn(workdir, prompt, **kwargs)

    agent = Stuck([{{"app.js": {bug!r}}}])
    controller = GraphController(
        project, agent, RunSettings(max_repair_rounds=2), runner=CheckRunner(action_timeout=1.5, expect_timeout=1.0)
    )
    asyncio.run(controller.run(ContractStore(project).load("todo-basics")))
"""


async def test_a_killed_process_resumes_and_finishes_with_the_same_result(tmp_path: Path) -> None:
    """Not Ctrl+C: the process is killed outright, with no chance to tidy up. The checkpoint is what is left."""
    straight = copy_todo(tmp_path, "straight")
    expected = await _graph(straight, ScriptedAgent([{"app.js": COUNT_BUG_JS}, {"app.js": GOOD_JS}])).run(contract(straight))

    project = copy_todo(tmp_path, "killed")
    marker = tmp_path / "stuck.marker"
    script = tmp_path / "killed_run.py"
    root = str(Path(__file__).resolve().parents[1])
    script.write_text(
        textwrap.dedent(_KILLED_RUN).format(
            root=str(Path(root) / "src"), project=str(project), marker=str(marker), bug=COUNT_BUG_JS
        ),
        encoding="utf-8",
    )
    tree = spawn_tree([sys.executable, str(script)], cwd=root)
    try:
        deadline = time.monotonic() + 120
        while not marker.exists():
            assert tree.poll() is None, "the run ended before its second turn"
            assert time.monotonic() < deadline, "the run never reached its second turn"
            await asyncio.sleep(0.2)
    finally:
        tree.kill(grace=0)

    assert (project / "app.js").read_text(encoding="utf-8") == "half-written\n"  # nothing tidied up
    [run_dir] = [p for p in (project / ".contexer" / "runs").iterdir() if (p / "checkpoint.sqlite").is_file()]
    assert not (run_dir / "run.json").exists()

    agent = RecordingAgent([{"app.js": GOOD_JS}])
    resumed = await _graph(project, agent).resume(run_dir.name)

    assert _shape(resumed) == _shape(expected)
    assert agent.found == [COUNT_BUG_JS]  # the tree was reset to the last snapshot before the turn ran again
    assert (project / "app.js").read_text(encoding="utf-8") == GOOD_JS


async def test_resuming_a_finished_run_reports_it_and_runs_nothing(project: Path) -> None:
    done = await _graph(project, ScriptedAgent([{"app.js": GOOD_JS}])).run(contract(project))
    agent = RecordingAgent([{"app.js": BROKEN_JS}])
    again = await _graph(project, agent).resume(done.run_id)
    assert again.terminal == "succeeded" and again.run_id == done.run_id
    assert agent.prompts == [] and (project / "app.js").read_text(encoding="utf-8") == GOOD_JS


async def test_a_run_that_does_not_exist_cannot_be_resumed(project: Path) -> None:
    with pytest.raises(ResumeError, match="no run"):
        await _graph(project, ScriptedAgent([])).resume("20260101-000000-abcd")


async def test_a_run_folder_without_a_checkpoint_cannot_be_resumed(project: Path) -> None:
    """A run of 0.4, or a `contexer verify`: there is a folder, and nothing to continue from."""
    from contexer.evidence.rundir import RunDir

    old = RunDir.create(project)
    with pytest.raises(ResumeError, match="checkpoint"):
        await _graph(project, ScriptedAgent([])).resume(old.run_id)


async def test_a_run_is_not_resumed_when_what_defines_done_changed_while_it_was_stopped(project: Path) -> None:
    """The checks are not in the snapshots. If they changed while the run was down, nobody approved that."""
    stopped = await _stop_in_turn(project, [{"app.js": COUNT_BUG_JS}], stuck=2)
    path = project / ".contexer" / "contracts" / f"{CONTRACT_ID}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["criteria"] = data["criteria"][:1]
    path.write_text(json.dumps(data), encoding="utf-8")

    agent = RecordingAgent([{"app.js": GOOD_JS}])
    with pytest.raises(ResumeError, match="changed"):
        await _graph(project, agent).resume(stopped.run_id)
    assert agent.prompts == []


# -- Ctrl+C leaves nothing running ------------------------------------------------------------


class _RealProcessAgent(ScriptedAgent):
    """Starts a real child process, as the adapters do, and waits for it without handling a cancel itself."""

    def __init__(self) -> None:
        super().__init__([])
        self.started = asyncio.Event()
        self.tree: Any = None

    async def run_turn(self, workdir: Path, prompt: str, **kwargs: Any) -> AgentTurn:
        (Path(workdir) / "app.js").write_text("half-written\n", encoding="utf-8")
        self.tree = spawn_tree([sys.executable, "-c", "import time; time.sleep(3600)"], cwd=workdir)
        self._track(self.tree)
        self.started.set()
        while self.tree.poll() is None:
            await asyncio.sleep(0.05)
        return AgentTurn(status="completed")


async def test_stopping_during_a_turn_leaves_no_process_and_restores_the_files(project: Path) -> None:
    agent = _RealProcessAgent()
    controller = _graph(project, agent)
    task = asyncio.create_task(controller.run(contract(project)))
    await asyncio.wait_for(agent.started.wait(), 60)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    deadline = time.monotonic() + 15
    while agent.tree.poll() is None and time.monotonic() < deadline:
        await asyncio.sleep(0.1)
    assert agent.tree.poll() is not None, "the agent's process is still running"
    outcome = controller.last_outcome
    assert outcome is not None and outcome.terminal == "cancelled"
    assert (project / "app.js").read_text(encoding="utf-8") == GOOD_JS
    assert (Path(outcome.run_dir) / "report.html").is_file()


# -- corrections --------------------------------------------------------------------------------

CORRECTION = "The heading must say 'My tasks'."
HEADING_CHECK = {
    "id": "heading-says-my-tasks",
    "description": "The page heading says 'My tasks'",
    "check": {"steps": [], "expect": [{"kind": "visible", "target": {"role": "heading", "name": "My tasks"}}]},
}
WITH_HEADING = "document.querySelector('h1').textContent = 'My tasks';\n"


def _once(text: str, after: Any = None) -> Any:
    """A source of corrections that has one to give, once: at once, or only after ``after`` has done a turn."""
    pending = [text]
    return lambda: pending.pop() if pending and (after is None or after.prompts) else None


def _corrected_intent() -> Any:
    return submit(behaviours=["The heading says 'My tasks'"], checks=[HEADING_CHECK])


async def test_a_correction_between_attempts_changes_the_contract_and_needs_approval_again(project: Path) -> None:
    before = contract(project)
    asked: list[dict[str, Any]] = []

    def ask(request: dict[str, Any]) -> dict[str, Any]:
        asked.append(request)
        return {"approve": True}

    model = AgentScript(intent=[_corrected_intent()])
    agent = RecordingAgent([{"app.js": COUNT_BUG_JS}, {"app.js": GOOD_JS + WITH_HEADING}])
    controller = _graph(project, agent, model=model, ask=ask, corrections=_once(CORRECTION, after=agent))
    outcome = await controller.run(before)

    assert outcome.terminal == "succeeded", outcome.reason
    [request] = asked  # the contract came in approved; it was asked about once, after the correction
    assert request["kind"] == "approve" and request["changed"] is True
    assert any("heading-says-my-tasks" in line for line in request["checks"])
    after = ContractStore(project).load(CONTRACT_ID)
    assert after.content_hash() != before.content_hash() and after.status == "approved"
    assert len(after.criteria) == len(before.criteria) + 1
    assert outcome.corrections == [CORRECTION]
    assert CORRECTION in agent.prompts[1] and "heading-says-my-tasks" in agent.prompts[1]
    assert agent.sessions[1] is None  # the job changed: the whole of it is restated in a fresh session
    task = str(model.seen["intent"][0][1].content)
    assert CORRECTION in task and "complete-decrements" in task  # the Intent agent saw the correction and the checks


async def test_a_correction_that_is_not_approved_ends_the_run_on_the_best_attempt(project: Path) -> None:
    model = AgentScript(intent=[_corrected_intent()])
    agent = RecordingAgent([{"app.js": COUNT_BUG_JS}, {"app.js": BROKEN_JS}])
    controller = _graph(project, agent, model=model, ask=lambda _r: {"approve": False}, corrections=_once(CORRECTION, after=agent))
    outcome = await controller.run(contract(project))

    assert outcome.terminal == "needs_human" and len(agent.prompts) == 1
    assert (project / "app.js").read_text(encoding="utf-8") == COUNT_BUG_JS
    assert ContractStore(project).load(CONTRACT_ID).status != "approved"  # the changed checks stay a draft


async def test_a_correction_that_changes_no_check_needs_no_new_approval(project: Path) -> None:
    asked: list[dict[str, Any]] = []
    model = AgentScript(intent=[submit(behaviours=["Tasks can be added"], checks=[])])
    agent = RecordingAgent([{"app.js": COUNT_BUG_JS}, {"app.js": GOOD_JS}])
    controller = _graph(project, agent, model=model, ask=lambda r: asked.append(r) or {"approve": True}, corrections=_once("Keep it simple.", after=agent))
    outcome = await controller.run(contract(project))
    assert outcome.terminal == "succeeded" and asked == []
    assert outcome.corrections == ["Keep it simple."]


async def test_a_correction_without_a_model_is_reported_and_the_run_goes_on(project: Path) -> None:
    events: list[tuple[str, str]] = []
    agent = RecordingAgent([{"app.js": COUNT_BUG_JS}, {"app.js": GOOD_JS}])
    controller = _graph(project, agent, corrections=_once(CORRECTION), on_event=lambda k, m: events.append((k, m)))
    outcome = await controller.run(contract(project))
    assert outcome.terminal == "succeeded" and outcome.corrections == []
    assert any("correction" in message.lower() and "model" in message.lower() for _kind, message in events)


async def test_a_correction_typed_at_the_approval_prompt_redrafts_before_anything_is_built(project: Path) -> None:
    (project / ".contexer" / "contracts" / f"{CONTRACT_ID}.json").unlink()
    answers = [{"correction": CORRECTION}, {"approve": True}]
    asked: list[dict[str, Any]] = []

    def ask(request: dict[str, Any]) -> dict[str, Any]:
        asked.append(request)
        return answers.pop(0)

    model = AgentScript(intent=[submit(behaviours=["Tasks"], checks=contract_checks()), _corrected_intent()])
    agent = RecordingAgent([{"app.js": GOOD_JS + WITH_HEADING}])
    outcome = await _graph(project, agent, model=model, ask=ask).run_goal(GOAL)

    assert outcome.terminal == "succeeded", outcome.reason
    assert [r["kind"] for r in asked] == ["approve", "approve"]
    assert not any("heading-says-my-tasks" in line for line in asked[0]["checks"])
    assert any("heading-says-my-tasks" in line for line in asked[1]["checks"])
    assert len(agent.prompts) == 1 and "heading-says-my-tasks" in agent.prompts[0]


async def test_resuming_with_a_correction_applies_it_before_the_next_turn(project: Path) -> None:
    stopped = await _stop_in_turn(project, [{"app.js": COUNT_BUG_JS}], stuck=2)
    asked: list[dict[str, Any]] = []
    model = AgentScript(intent=[_corrected_intent()])
    agent = RecordingAgent([{"app.js": GOOD_JS + WITH_HEADING}])
    controller = _graph(project, agent, model=model, ask=lambda r: asked.append(r) or {"approve": True})
    outcome = await controller.resume(stopped.run_id, correction=CORRECTION)

    assert outcome.terminal == "succeeded", outcome.reason
    assert [r["kind"] for r in asked] == ["approve"]
    assert CORRECTION in agent.prompts[0] and len(agent.prompts) == 1


# -- waiting for a person survives the process --------------------------------------------------


async def test_a_run_waiting_for_approval_asks_again_when_resumed(project: Path) -> None:
    (project / ".contexer" / "contracts" / f"{CONTRACT_ID}.json").unlink()

    class WalkedAway(Exception):
        pass

    def walks_away(_request: dict[str, Any]) -> dict[str, Any]:
        raise WalkedAway  # Ctrl+C at a prompt reaches the run as an exception from `ask`

    first = _graph(project, RecordingAgent([]), model=AgentScript(intent=[submit(behaviours=["Tasks"], checks=contract_checks())]), ask=walks_away)
    with pytest.raises(WalkedAway):
        await first.run_goal(GOAL)
    assert first.last_outcome is not None and first.last_outcome.terminal == "cancelled"

    asked: list[dict[str, Any]] = []
    model = AgentScript()  # the draft is in the checkpoint: the Intent agent is not asked a second time
    agent = RecordingAgent([{"app.js": GOOD_JS}])
    second = _graph(project, agent, model=model, ask=lambda r: asked.append(r) or {"approve": True})
    outcome = await second.resume(first.last_outcome.run_id)

    assert outcome.terminal == "succeeded", outcome.reason
    assert [r["kind"] for r in asked] == ["approve"] and "intent" not in model.seen


async def test_a_correction_given_before_the_first_turn_is_applied_before_anything_is_built(project: Path) -> None:
    asked: list[dict[str, Any]] = []
    model = AgentScript(intent=[_corrected_intent()])
    agent = RecordingAgent([{"app.js": GOOD_JS + WITH_HEADING}])
    controller = _graph(project, agent, model=model, ask=lambda r: asked.append(r) or {"approve": True}, corrections=_once(CORRECTION))
    outcome = await controller.run(contract(project))

    assert outcome.terminal == "succeeded", outcome.reason
    assert len(asked) == 1 and len(agent.prompts) == 1
    assert "heading-says-my-tasks" in agent.prompts[0] and CORRECTION in agent.prompts[0]


# -- a turn that finished just before the run stopped is not thrown away ------------------------


async def test_a_turn_that_finished_before_the_stop_is_snapshotted_on_resume_not_run_again(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stopped between the coding agent's turn and its snapshot: the work exists, it is just not recorded yet."""
    from contexer.controller.shared import ContractGuard

    checked = {"times": 0}
    real = ContractGuard.restore_if_changed

    def stop_on_second_check(self: ContractGuard) -> list[str]:
        checked["times"] += 1
        if checked["times"] == 2:
            raise asyncio.CancelledError  # Ctrl+C lands here: turn 2 has returned, nothing has been snapshotted
        return real(self)

    monkeypatch.setattr(ContractGuard, "restore_if_changed", stop_on_second_check)
    first = RecordingAgent([{"app.js": COUNT_BUG_JS}, {"app.js": GOOD_JS}])
    controller = _graph(project, first)
    with pytest.raises(asyncio.CancelledError):
        await controller.run(contract(project))
    assert len(first.prompts) == 2
    stopped = controller.last_outcome
    assert stopped is not None and stopped.terminal == "cancelled"
    assert (project / "app.js").read_text(encoding="utf-8") == COUNT_BUG_JS  # put back to the best attempt for now

    monkeypatch.setattr(ContractGuard, "restore_if_changed", real)
    agent = RecordingAgent([{"app.js": "throw new Error('this turn must not run');\n"}])
    resumed = await _graph(project, agent).resume(stopped.run_id)

    assert resumed.terminal == "succeeded", resumed.reason
    assert agent.prompts == []  # turn 2 was already done; it was snapshotted and tested, not repeated
    assert [(a.n, a.outcome, a.changed_files) for a in resumed.attempts] == [(1, "fail", ["app.js"]), (2, "pass", ["app.js"])]
    assert (project / "app.js").read_text(encoding="utf-8") == GOOD_JS


async def test_a_killed_process_whose_turn_had_finished_keeps_that_work_on_resume(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same moment, without the tidy-up of Ctrl+C: the files in the project are the finished turn's."""
    from contexer.controller.shared import ContractGuard

    class Killed(BaseException):  # as when the process dies: no handler of the run's sees it
        pass

    checked = {"times": 0}
    real = ContractGuard.restore_if_changed

    def die_on_second_check(self: ContractGuard) -> list[str]:
        checked["times"] += 1
        if checked["times"] == 2:
            raise Killed  # not a cancel: nothing is restored, nothing is written, as when a process dies
        return real(self)

    monkeypatch.setattr(ContractGuard, "restore_if_changed", die_on_second_check)
    controller = _graph(project, RecordingAgent([{"app.js": COUNT_BUG_JS}, {"app.js": GOOD_JS}]))
    with pytest.raises(Killed):
        await controller.run(contract(project))
    assert (project / "app.js").read_text(encoding="utf-8") == GOOD_JS
    [run_dir] = [p for p in (project / ".contexer" / "runs").iterdir() if (p / "checkpoint.sqlite").is_file()]

    monkeypatch.setattr(ContractGuard, "restore_if_changed", real)
    agent = RecordingAgent([{"app.js": "throw new Error('this turn must not run');\n"}])
    resumed = await _graph(project, agent).resume(run_dir.name)

    assert resumed.terminal == "succeeded" and agent.prompts == []
    assert [(a.n, a.outcome) for a in resumed.attempts] == [(1, "fail"), (2, "pass")]


# -- what a person changed while the run was stopped is said, and kept ----------------------------------


async def test_resuming_says_which_files_it_put_back_and_they_can_be_had_again(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from contexer.cli import app

    project = copy_todo(tmp_path, "edited")
    stopped = await _stop_in_turn(project, [{"app.js": COUNT_BUG_JS}], stuck=2)
    # The person fixes something by hand, and adds a file, before resuming the next day.
    (project / "app.js").write_text(COUNT_BUG_JS + "// my own fix\n", encoding="utf-8")
    (project / "notes.md").write_text("remember this\n", encoding="utf-8")

    events: list[tuple[str, str]] = []
    agent = RecordingAgent([{"app.js": GOOD_JS}])
    resumed = await _graph(project, agent, on_event=lambda kind, message: events.append((kind, message))).resume(stopped.run_id)
    assert resumed.terminal == "succeeded"

    said = " ".join(message for _kind, message in events)
    assert "app.js" in said and "notes.md" in said and "--before-resume" in said  # not silently
    assert not (project / "notes.md").exists()

    result = CliRunner().invoke(app, ["restore", stopped.run_id, "--before-resume", "--dir", str(project)])
    assert result.exit_code == 0, result.output
    assert (project / "app.js").read_text(encoding="utf-8") == COUNT_BUG_JS + "// my own fix\n"
    assert (project / "notes.md").read_text(encoding="utf-8") == "remember this\n"


async def test_a_resume_that_changes_no_file_says_nothing_about_files(tmp_path: Path) -> None:
    project = copy_todo(tmp_path, "untouched")
    stopped = await _stop_in_turn(project, [{"app.js": COUNT_BUG_JS}], stuck=2)
    events: list[tuple[str, str]] = []
    await _graph(project, RecordingAgent([{"app.js": GOOD_JS}]), on_event=lambda k, m: events.append((k, m))).resume(stopped.run_id)
    assert not any("--before-resume" in message for _kind, message in events)


async def test_what_the_agents_spent_before_the_stop_still_counts_after_a_resume(tmp_path: Path) -> None:
    from contexer.crew.budget import Budget

    project = copy_todo(tmp_path, "budget")
    agent = _StuckOnTurn([{"app.js": COUNT_BUG_JS}], stuck=2)
    first = Budget(max_tokens=10_000)
    controller = _graph(project, agent, model=AgentScript(), budget=first)  # Triage and the Diagnoser run before turn 2
    task = asyncio.create_task(controller.run(contract(project)))
    await asyncio.wait_for(agent.started.wait(), 60)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert first.tokens > 0

    second = Budget(max_tokens=10_000)  # a new process builds a new budget
    assert controller.last_outcome is not None
    await _graph(project, RecordingAgent([{"app.js": GOOD_JS}]), model=AgentScript(), budget=second).resume(controller.last_outcome.run_id)
    assert second.tokens >= first.tokens  # it starts from what was already spent, not from zero


async def test_a_pass_under_the_old_checks_does_not_end_a_run_whose_checks_were_corrected(project: Path) -> None:
    # Attempt 1 passes and the review asks for one repair. Before that turn a correction adds a check.
    # No later attempt meets it. The pass was under checks that no longer define done: it must not end the run.
    leaky = 'const SERVICE_KEY = "' + "q7Rk2ZpX9vLm" + "4TnB8sWd3Yf6" + '";\n' + GOOD_JS
    model = AgentScript(intent=[_corrected_intent()])
    agent = RecordingAgent([{"app.js": leaky}, {"app.js": GOOD_JS}, {"app.js": GOOD_JS}])
    controller = _graph(project, agent, model=model, ask=lambda _r: {"approve": True}, corrections=_once(CORRECTION, after=agent))
    outcome = await controller.run(contract(project))

    assert outcome.corrections == [CORRECTION]
    assert outcome.terminal != "succeeded", outcome.reason
    assert outcome.final is None or outcome.final.decision.outcome != "pass"


async def test_a_run_stopped_while_proving_resumes_with_the_app_running(project: Path) -> None:
    # Stopped in the middle of the checks: the resumed process has no app yet. It must start one and
    # prove the attempt, not record "the app did not start" and pay for a repair of nothing.
    replaying = asyncio.Event()

    class _StuckRunner(type(fast_runner())):
        async def run(self, *args: Any, **kwargs: Any) -> Any:
            replaying.set()
            await asyncio.sleep(3600)

    controller = GraphController(project, ScriptedAgent([{"app.js": GOOD_JS}]), RunSettings(max_repair_rounds=2), runner=_StuckRunner(action_timeout=1.5, expect_timeout=1.0))
    task = asyncio.create_task(controller.run(contract(project)))
    await asyncio.wait_for(replaying.wait(), 60)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert controller.last_outcome is not None
    stopped = controller.last_outcome

    agent = RecordingAgent([{"app.js": GOOD_JS}])
    resumed = await _graph(project, agent).resume(stopped.run_id)

    assert resumed.terminal == "succeeded", resumed.reason
    assert [a.outcome for a in resumed.attempts] == ["pass"]
    assert not any("did not start" in (a.note or "") for a in resumed.attempts)


# -- REL-5: a run that crashes still ends as a run ---------------------------------------------


async def test_an_exception_in_a_node_restores_and_reports(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from contexer.controller.shared import ContractGuard

    before = (project / "app.js").read_text(encoding="utf-8")
    key = "sk-or-v1-" + "a1b2c3d4" * 6

    def bug(self: ContractGuard) -> list[str]:
        raise TypeError(f"'NoneType' object is not subscriptable ({key})")

    monkeypatch.setattr(ContractGuard, "restore_if_changed", bug)
    agent = RecordingAgent([{"app.js": GOOD_JS}])
    controller = _graph(project, agent)
    outcome = await controller.run(contract(project))

    assert outcome.terminal == "internal_error"
    assert outcome.exit_code == 3
    assert "TypeError" in outcome.reason and "not subscriptable" in outcome.reason
    assert "report" in outcome.reason.lower()
    assert key not in outcome.reason
    assert controller.last_outcome is outcome
    # The files are as they were before the run; what the agent wrote is kept as a snapshot.
    assert (project / "app.js").read_text(encoding="utf-8") == before
    run_dir = Path(outcome.run_dir)
    saved = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert saved["terminal"] == "internal_error"
    crash = (run_dir / "crash.txt").read_text(encoding="utf-8")
    assert "Traceback" in crash and "TypeError" in crash and key not in crash
    assert (run_dir / "report.html").is_file() or (run_dir / "report.md").is_file()


# -- REL-7: files a resume depends on are written whole ------------------------------------------


async def test_a_truncated_run_file_is_a_resume_error(project: Path) -> None:
    controller = _graph(project, RecordingAgent([{"app.js": GOOD_JS}]))
    outcome = await controller.run(contract(project))
    run_file = Path(outcome.run_dir) / "run.json"
    whole = run_file.read_text(encoding="utf-8")
    run_file.write_text(whole[: len(whole) // 2], encoding="utf-8")  # as a kill in the middle of a write leaves it

    with pytest.raises(ResumeError, match="run.json"):
        await _graph(project, ScriptedAgent([])).resume(outcome.run_id)


def test_a_file_a_resume_depends_on_is_never_seen_half_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from contexer.evidence import rundir

    target = tmp_path / "run.json"
    target.write_text('{"old": true}', encoding="utf-8")

    def dies(_source: Any, _target: Any) -> None:
        raise OSError("killed before the rename")

    monkeypatch.setattr(rundir.os, "replace", dies)
    with pytest.raises(OSError):
        rundir.write_whole(target, '{"new": true}')
    assert target.read_text(encoding="utf-8") == '{"old": true}'  # the old file is still whole
    monkeypatch.undo()
    rundir.write_whole(target, '{"new": true}')
    assert target.read_text(encoding="utf-8") == '{"new": true}'
    assert [p.name for p in tmp_path.iterdir()] == ["run.json"]  # no temporary file is left
