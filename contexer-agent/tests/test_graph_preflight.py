"""Before anything is spent: can Contexer sign in, and has it looked at the page the goal is about?

Both come from the first run on a real app behind a sign-in. The sign-in steps stopped at a consent
screen, three coding-agent turns were paid for before anyone was told, and the checks had been drafted
from the public landing page, so they named a field the signed-in page did not have.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import HumanMessage

from contexer.contract import ContractStore
from contexer.controller import RunSettings
from contexer.graph import GraphController
from contexer.graph.nodes import pages_in_goal
from tests.fakes import AgentScript, submit
from tests.loop_helpers import RecordingAgent, fast_runner

pytestmark = pytest.mark.anyio

MEMBERS = Path(__file__).resolve().parents[1] / "bench" / "fixtures" / "members" / "app"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    target = tmp_path / "members"
    shutil.copytree(MEMBERS, target, ignore=shutil.ignore_patterns("runs"))
    return target


def _graph(project: Path, agent: Any, **kwargs: Any) -> GraphController:
    return GraphController(project, agent, RunSettings(max_repair_rounds=1), runner=fast_runner(), **kwargs)


def _break_sign_in(project: Path) -> None:
    toml = project / "contexer.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace("correct-horse", "wrong-password"), encoding="utf-8")


async def test_a_sign_in_that_does_not_work_ends_the_run_before_the_coding_agent_is_paid(project: Path) -> None:
    _break_sign_in(project)
    agent = RecordingAgent([{"app.js": (project / "app.js").read_text(encoding="utf-8") + "// x\n"}])
    events: list[tuple[str, str]] = []
    outcome = await _graph(project, agent, on_event=lambda k, m: events.append((k, m))).run(ContractStore(project).load("members-basics"))

    assert outcome.terminal == "needs_human", outcome.reason
    assert "sign in" in outcome.reason.lower() and "[auth]" in outcome.reason
    assert "nothing was" in outcome.reason.lower()  # and it says that nothing was spent or changed
    assert agent.prompts == [] and outcome.attempts == [] and outcome.cost_usd == 0.0
    assert (Path(outcome.run_dir) / "sign-in.jpg").is_file()  # what the browser showed, for the person to look at


async def test_a_sign_in_that_works_lets_the_run_go_on(project: Path) -> None:
    agent = RecordingAgent([{"app.js": (project / "app.js").read_text(encoding="utf-8") + "// x\n"}])
    outcome = await _graph(project, agent).run(ContractStore(project).load("members-basics"))
    assert len(agent.prompts) == 1 and outcome.terminal == "succeeded", outcome.reason


async def test_a_goal_is_not_drafted_when_contexer_cannot_sign_in(project: Path) -> None:
    _break_sign_in(project)
    model = AgentScript()  # any Intent call would be answered; none should be made
    agent = RecordingAgent([{}])
    outcome = await _graph(project, agent, model=model, ask=lambda _request: {"approve": True}).run_goal("Members can archive a project")
    assert outcome.terminal == "needs_human" and "sign in" in outcome.reason.lower()
    assert model.seen == {} and agent.prompts == []


def test_the_pages_a_goal_names_are_found() -> None:
    goal = "On the Symptoms page of the signed-in app (/app/symptoms), show a count. See also /reports.html and http://x.test/elsewhere."
    assert pages_in_goal(goal) == ["/app/symptoms", "/reports.html"]
    assert pages_in_goal("Users can add/remove tasks, 3/4 of them, and/or delete them") == []
    assert pages_in_goal("/a /b /c /d /e") == ["/a", "/b", "/c"]  # no more than three pages are opened


async def test_checks_are_drafted_from_the_signed_in_page_the_goal_names(project: Path) -> None:
    (project / "reports.html").write_text(
        "<!doctype html><title>Reports</title><h1>Reports</h1>"
        '<label for="q">Quarter filter</label><select id="q"><option>Q1</option></select>',
        encoding="utf-8",
    )
    model = AgentScript(intent=[submit(behaviours=["Reports can be filtered by quarter."], checks=[])])
    await _graph(project, RecordingAgent([{}]), model=model, ask=lambda _request: {"approve": True}).run_goal(
        "On the reports page (/reports.html), members can filter reports by quarter"
    )
    task = next(m for m in model.seen["intent"][0] if isinstance(m, HumanMessage)).text
    assert "Dashboard" in task  # the page after sign-in, not the sign-in form
    assert "/reports.html" in task and "Quarter filter" in task  # and the page the goal is about, with its real names
    marker = task.rfind("<untrusted", 0, task.index("Quarter filter"))
    assert marker > task.rfind("</untrusted>", 0, task.index("Quarter filter"))  # as data
