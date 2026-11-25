"""Secrets on their way to a model: what a task carries, and what a run knows to mask.

Each test puts a made-up key or the ``[auth]`` password where an app could put it, and looks at what
the model was sent. (What the app prints is in ``test_devserver.py``; check drafting without tools is
in ``test_goal_analyzer.py``.)
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from contexer.contract import ContractStore
from contexer.controller import RunSettings
from contexer.crew import AgentSpec, run_agent
from contexer.crew.transcript import Masker
from contexer.crew.untrusted import untrusted
from contexer.graph import GraphController
from contexer.verification.checks import MASK
from contexer.workflow.criteria import CHECK_DSL_GUIDE
from tests.fakes import AgentScript, ScriptedChatModel, submit
from tests.loop_helpers import RecordingAgent, fast_runner

pytestmark = pytest.mark.anyio

API_KEY = "sk-or-v1-" + "t3stK3y0" * 5
PASSWORD = "made-up-Passw0rd-417"
EXPORTED_KEY = "made-up-exported-key-0f3a9c"
MEMBERS = Path(__file__).resolve().parents[1] / "bench" / "fixtures" / "members" / "app"
MEMBERS_PASSWORD = "correct-horse"  # the fixture's own [auth] password, written in its contexer.toml


class Report(BaseModel):
    summary: str


SPEC = AgentSpec(name="tester", system_prompt="You test web apps.", output_schema=Report)


def _task(messages: list[Any]) -> str:
    return next(m for m in messages if isinstance(m, HumanMessage)).text


# -- the first message of an agent's prompt -------------------------------------------------------


async def test_a_secret_in_the_task_is_masked_before_the_model_sees_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", EXPORTED_KEY)
    log = f"key {API_KEY}\nadmin password {PASSWORD}\nAuthorization: Bearer {EXPORTED_KEY}"
    task = "## The end of the server log\n" + untrusted("server-log", log)
    model = ScriptedChatModel(submit(summary="ok"))
    await run_agent(SPEC, model, [], task, run_dir=tmp_path, secrets=[PASSWORD])

    sent = _task(model.seen[0])
    assert API_KEY not in sent and PASSWORD not in sent and EXPORTED_KEY not in sent
    assert "admin password " + MASK in sent and "## The end of the server log" in sent
    assert sent.count("<untrusted") == 1 and sent.count("</untrusted>") == 1  # the marking is as it was built


async def test_a_task_with_no_secret_in_it_reaches_the_model_byte_for_byte(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", EXPORTED_KEY)
    task = "\n".join(
        [
            "## The goal",
            "Users can add a task; the count says how many are left (é, ☃, tabs\tand  double spaces).",
            "",
            "## The checks",
            '{"id": "count", "check": {"steps": [{"action": "fill", "target": {"label": "Password"}, "value": "${CONTEXER_TEST_PASSWORD}"}],',
            ' "expect": [{"kind": "text", "target": {"test_id": "remaining-count"}, "equals": "0 left"}]}}',
            "",
            CHECK_DSL_GUIDE,
            untrusted("diff", "+ const key = process.env.API_KEY; // sk- is a prefix, not a key\n- old line\r\n"),
            # Names an app really has: "sk-" in the middle of a word is not the start of a key.
            '{"test_id": "task-remaining-count-label-wide"} .risk-assessment-summary-table-row #desk-booking-calendar-day-view',
            "   trailing spaces and a last line without a newline   ",
        ]
    )
    model = ScriptedChatModel(submit(summary="ok"))
    await run_agent(SPEC, model, [], task, run_dir=None, secrets=[PASSWORD])
    assert _task(model.seen[0]) == task


def test_a_key_is_found_where_a_word_starts_and_a_name_with_sk_in_it_is_left_alone() -> None:
    masker = Masker()
    for before in ("", " ", "=", '"', "'", ":", "(", "\n", "\t", "Bearer ", "KEY=", "x-", "_"):
        assert API_KEY not in masker.text(f"{before}{API_KEY} then more"), repr(before)
    # As JSON text, where a new line is the two characters backslash and n: a tool result, a transcript line.
    as_json = json.dumps({"log": f"started\n{API_KEY}\r\n\t{API_KEY}"})
    assert API_KEY not in masker.text(as_json)
    names = 'task-remaining-count-label-wide risk-assessment-summary-table-row C:\\repo\\task-list-item-checkbox-toggle.js'
    assert masker.text(names) == names


# -- `contexer run`: the agents know the [auth] password ------------------------------------------


@pytest.fixture
def members(tmp_path: Path) -> Path:
    target = tmp_path / "members"
    shutil.copytree(MEMBERS, target, ignore=shutil.ignore_patterns("runs"))
    return target


def _graph(project: Path, agent: Any, **kwargs: Any) -> GraphController:
    return GraphController(project, agent, RunSettings(max_repair_rounds=2), runner=fast_runner(), **kwargs)


async def test_triage_the_diagnoser_and_the_reviewer_of_a_run_never_get_the_sign_in_password(members: Path) -> None:
    good = (members / "app.js").read_text(encoding="utf-8")
    leak = f"// to try it by hand: demo@example.com / {MEMBERS_PASSWORD}\n"
    # The first turn makes the page itself show the password, so the browser's findings carry it too.
    shown = good.replace("`Welcome, ${user.name}`", "`Welcome, ${user.name} (seeded with " + MEMBERS_PASSWORD + ")`")
    assert shown != good
    model = AgentScript()
    agent = RecordingAgent([{"app.js": leak + shown}, {"app.js": leak + good}])
    outcome = await _graph(members, agent, model=model).run(ContractStore(members).load("members-basics"))

    assert outcome.terminal == "succeeded", outcome.reason
    for name, marker in (("triage", "seeded with"), ("diagnoser", "to try it by hand"), ("reviewer", "to try it by hand")):
        task = _task(model.seen[name][0])
        assert marker in task, f"{name} should have been shown what the app said"
        assert MEMBERS_PASSWORD not in task, f"the [auth] password reached {name}"
    assert "demo@example.com" in _task(model.seen["reviewer"][0])  # who signs in is not a secret; an agent may need it


async def test_the_intent_agent_of_a_run_never_gets_the_sign_in_password(members: Path) -> None:
    (members / "reports.html").write_text(
        f"<!doctype html><title>Reports</title><h1>Reports</h1><h2>Seeded account: {MEMBERS_PASSWORD}</h2>",
        encoding="utf-8",
    )
    model = AgentScript(intent=[submit(behaviours=["Reports can be filtered by quarter."], checks=[])])
    await _graph(members, RecordingAgent([{}]), model=model, ask=lambda _request: {"approve": True}).run_goal(
        "On the reports page (/reports.html), members can filter reports by quarter"
    )
    task = _task(model.seen["intent"][0])
    assert "Seeded account" in task, "the page the goal names should have been read"
    assert MEMBERS_PASSWORD not in task
