"""The closed loop as a graph (T3.1): typed state, pure routing, and code that owns "done".

The coding agent and the models are scripted; the snapshots, the app, the browser and the checks are real.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from contexer.controller import RunSettings
from contexer.crew.budget import Budget
from contexer.gate.models import GateDecision
from contexer.graph import GraphController
from contexer.graph.routing import EDGES, NODES, settle
from contexer.graph.state import LoopState
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

TERMINALS = [
    "succeeded",
    "failed_checks",
    "needs_human",
    "budget_exhausted",
    "timed_out",
    "tampered",
    "agent_error",
    "app_error",
    "cancelled",
]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return copy_todo(tmp_path)


def _graph(project: Path, agent: Any, rounds: int = 2, **kwargs: Any) -> GraphController:
    return GraphController(project, agent, RunSettings(max_repair_rounds=rounds), runner=fast_runner(), **kwargs)


# -- routing: every edge is a pure function of the state ---------------------------------


def test_the_graph_has_the_nodes_the_design_names() -> None:
    assert set(NODES) == {
        "intent",
        "approve",
        "plan",
        "coder_turn",
        "guard_snapshot",
        "ensure_app",
        "test",
        "score",
        "review",
        "triage",
        "ask_user",
        "diagnose",
        "finalize",
    }
    assert set(EDGES) == set(NODES) - {"finalize"}  # finalize is the only way out


@pytest.mark.parametrize(
    ("node", "state", "expected"),
    [
        ("intent", {}, "approve"),
        ("approve", {}, "plan"),  # before the first turn
        ("approve", {"n": 1}, "coder_turn"),  # checks approved again after work began: no second brief
        ("approve", {"correction": "Deleting must ask first"}, "intent"),
        ("plan", {}, "coder_turn"),
        ("coder_turn", {}, "guard_snapshot"),
        ("coder_turn", {"correction": "Deleting must ask first"}, "intent"),
        ("guard_snapshot", {}, "ensure_app"),
        ("ensure_app", {}, "test"),
        ("ensure_app", {"app_error": "Module not found"}, "test"),  # the test node records that nothing ran
        ("test", {}, "score"),
        ("score", {}, "triage"),
        ("triage", {"move": "repair_same_session"}, "diagnose"),
        ("triage", {"move": "fresh_approach"}, "diagnose"),
        ("triage", {"move": "rollback_and_retry"}, "diagnose"),
        ("triage", {"move": "ask_user"}, "ask_user"),
        ("triage", {"move": "stop"}, "finalize"),
        ("triage", {"move": "repair_same_session", "correction": "x"}, "intent"),
        ("ask_user", {}, "diagnose"),
        ("ask_user", {"correction": "x"}, "intent"),
        ("diagnose", {}, "coder_turn"),
    ],
)
def test_every_edge(node: str, state: LoopState, expected: str) -> None:
    assert EDGES[node](state) == expected


@pytest.mark.parametrize("terminal", TERMINALS)
@pytest.mark.parametrize("node", sorted(set(NODES) - {"finalize"}))
def test_a_terminal_state_always_leads_to_finalize(node: str, terminal: str) -> None:
    """Whatever else the state says: a correction, a move, an app error."""
    state: LoopState = {"terminal": terminal, "move": "repair_same_session", "correction": "x", "app_error": "y"}  # type: ignore[typeddict-item]
    assert EDGES[node](state) == "finalize"


def test_an_unknown_move_stops_the_run() -> None:
    assert EDGES["triage"]({"move": "succeeded"}) == "finalize"  # type: ignore[typeddict-item]
    assert EDGES["triage"]({}) == "finalize"


# -- the rule: `succeeded` needs the gate's pass ---------------------------------------------


def _decision(outcome: str) -> GateDecision:
    return GateDecision(outcome=outcome)  # type: ignore[arg-type]


@pytest.mark.parametrize("terminal", [t for t in TERMINALS if t != "succeeded"])
def test_settle_keeps_every_other_terminal_state(terminal: str) -> None:
    assert settle(terminal, "why", _decision("pass")) == (terminal, "why")


def test_settle_keeps_succeeded_only_with_a_pass() -> None:
    assert settle("succeeded", "ok", _decision("pass")) == ("succeeded", "ok")
    for outcome in ("fail", "needs_action", "error"):
        terminal, reason = settle("succeeded", "ok", _decision(outcome))
        assert terminal == "failed_checks" and "gate" in reason
    terminal, _reason = settle("succeeded", "ok", None)  # nothing was ever checked
    assert terminal == "failed_checks"


class _ClaimsSuccess(GraphController):
    """A controller whose state says `succeeded` before anything was built or checked."""

    def initial_state(self, *args: Any, **kwargs: Any) -> LoopState:
        state = super().initial_state(*args, **kwargs)
        state["terminal"] = "succeeded"
        state["reason"] = "Trust me."
        return state


async def test_a_state_that_claims_success_without_a_pass_does_not_end_succeeded(project: Path) -> None:
    agent = RecordingAgent([{"app.js": BROKEN_JS}])
    controller = _ClaimsSuccess(project, agent, RunSettings(), runner=fast_runner())
    outcome = await controller.run(contract(project))
    assert outcome.terminal == "failed_checks" and outcome.exit_code == 1


async def test_a_triage_model_cannot_declare_the_run_done(project: Path) -> None:
    model = AgentScript(triage=[submit(move="succeeded", reason="All good now.")] * 4)
    agent = RecordingAgent([{"app.js": COUNT_BUG_JS}, {"app.js": COUNT_BUG_JS + "\n// again\n"}])
    outcome = await _graph(project, agent, rounds=1, model=model).run(contract(project))
    assert outcome.terminal == "failed_checks"
    assert [a.outcome for a in outcome.attempts] == ["fail", "fail"]
    assert outcome.triage[0].source == "rules" and "succeeded" in outcome.triage[0].rejected


# -- the loop ---------------------------------------------------------------------------------------


async def test_a_run_that_needs_one_repair_succeeds_with_two_attempts(project: Path) -> None:
    agent = RecordingAgent([{"app.js": COUNT_BUG_JS}, {"app.js": GOOD_JS}])
    outcome = await _graph(project, agent).run(contract(project))

    assert outcome.terminal == "succeeded", outcome.reason
    assert outcome.engine == "graph"
    assert [(a.n, a.kind, a.outcome) for a in outcome.attempts] == [(1, "implement", "fail"), (2, "repair", "pass")]
    assert outcome.best_attempt == 2 and outcome.exit_code == 0
    assert agent.sessions == [None, "scripted-1"]
    [decision] = outcome.triage
    assert (decision.attempt, decision.move, decision.source) == (1, "repair_same_session", "rules")

    run_dir = Path(outcome.run_dir)
    assert (run_dir / "checkpoint.sqlite").is_file()  # the state is on disk, in the run folder
    saved = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert saved["engine"] == "graph" and saved["triage"][0]["move"] == "repair_same_session"
    report = (run_dir / "report.html").read_text(encoding="utf-8")
    assert "Triage" in report and "repair in the same session" in report.lower()


async def test_many_rounds_do_not_hit_the_graph_step_limit(project: Path) -> None:
    turns = [{"app.js": COUNT_BUG_JS + f"\n// try {n}\n"} for n in range(5)]
    outcome = await _graph(project, RecordingAgent(turns), rounds=4).run(contract(project))
    assert outcome.terminal == "failed_checks" and len(outcome.attempts) == 5


async def test_a_contract_that_is_not_saved_in_the_project_is_used_as_given(project: Path) -> None:
    """Like the classic engine: the caller hands over an approved contract; where it is kept is the caller's business."""
    given = contract(project)
    (project / ".contexer" / "contracts" / f"{CONTRACT_ID}.json").unlink()
    outcome = await _graph(project, RecordingAgent([{"app.js": GOOD_JS}])).run(given)
    assert outcome.terminal == "succeeded", outcome.reason


# -- triage with a model -----------------------------------------------------------------------------


async def test_the_model_can_choose_a_fresh_approach(project: Path) -> None:
    model = AgentScript(triage=[submit(move="fresh_approach", reason="The first idea was a dead end.")])
    agent = RecordingAgent([{"app.js": COUNT_BUG_JS}, {"app.js": GOOD_JS}])
    outcome = await _graph(project, agent, model=model).run(contract(project))

    assert outcome.terminal == "succeeded"
    assert agent.sessions == [None, None]
    assert "Acceptance checks" in agent.prompts[1]  # a fresh session gets the whole job restated
    assert (outcome.triage[0].source, outcome.triage[0].reason) == ("model", "The first idea was a dead end.")
    assert outcome.attempts[1].fresh_session


async def test_the_model_can_roll_back_to_the_best_attempt_and_retry(project: Path) -> None:
    """Attempt 2 is no better than attempt 1. Triage goes back to attempt 1 before the next turn."""
    tweaked = COUNT_BUG_JS + "\n// a tweak that changes nothing\n"
    model = AgentScript(
        triage=[
            submit(move="repair_same_session", reason="A first failure."),
            submit(move="rollback_and_retry", reason="The second attempt added noise and fixed nothing."),
        ]
    )
    agent = RecordingAgent([{"app.js": COUNT_BUG_JS}, {"app.js": tweaked}, {"app.js": GOOD_JS}])
    outcome = await _graph(project, agent, model=model).run(contract(project))

    assert outcome.terminal == "succeeded"
    assert agent.found == [GOOD_JS, COUNT_BUG_JS, COUNT_BUG_JS]  # turn 3 began from attempt 1, not from the tweak
    assert agent.sessions[2] is None
    assert outcome.attempts[1].reverted_to == 1
    assert [d.move for d in outcome.triage] == ["repair_same_session", "rollback_and_retry"]


async def test_the_model_can_stop_and_the_reason_is_shown(project: Path) -> None:
    model = AgentScript(triage=[submit(move="stop", reason="The check contradicts the goal; a person must decide.")])
    agent = RecordingAgent([{"app.js": COUNT_BUG_JS}, {"app.js": GOOD_JS}])
    outcome = await _graph(project, agent, model=model).run(contract(project))

    assert outcome.terminal == "failed_checks" and len(agent.prompts) == 1
    assert "The check contradicts the goal" in outcome.reason
    assert (project / "app.js").read_text(encoding="utf-8") == COUNT_BUG_JS  # the best attempt reached is kept


async def test_asking_the_user_puts_the_answer_into_the_next_prompt(project: Path) -> None:
    asked: list[dict[str, Any]] = []

    def ask(request: dict[str, Any]) -> dict[str, Any]:
        asked.append(request)
        return {"answer": "Completed tasks must not be counted as remaining."}

    model = AgentScript(triage=[submit(move="ask_user", reason="Is a completed task still 'left'?")])
    agent = RecordingAgent([{"app.js": COUNT_BUG_JS}, {"app.js": GOOD_JS}])
    outcome = await _graph(project, agent, model=model, ask=ask).run(contract(project))

    assert outcome.terminal == "succeeded"
    [request] = asked
    assert request["kind"] == "ask" and request["question"] == "Is a completed task still 'left'?"
    assert "Completed tasks must not be counted as remaining." in agent.prompts[1]


async def test_the_user_can_stop_the_run_when_asked(project: Path) -> None:
    model = AgentScript(triage=[submit(move="ask_user", reason="Unclear.")])
    agent = RecordingAgent([{"app.js": COUNT_BUG_JS}, {"app.js": GOOD_JS}])
    outcome = await _graph(project, agent, model=model, ask=lambda _request: {"stop": True}).run(contract(project))
    assert outcome.terminal == "needs_human" and len(agent.prompts) == 1


async def test_nobody_is_asked_when_nobody_is_there(project: Path) -> None:
    """Without an `ask` function the move is not legal, so the rules decide and the run goes on."""
    model = AgentScript(triage=[submit(move="ask_user", reason="Unclear.")])
    agent = RecordingAgent([{"app.js": COUNT_BUG_JS}, {"app.js": GOOD_JS}])
    outcome = await _graph(project, agent, model=model).run(contract(project))
    assert outcome.terminal == "succeeded" and "ask_user" in outcome.triage[0].rejected


# -- the Diagnoser in the loop ---------------------------------------------------------------------


async def test_the_diagnosers_brief_is_added_to_the_repair_prompt(project: Path) -> None:
    model = AgentScript(
        diagnoser=[
            submit(
                cause="remaining() counts every task, including the completed ones.",
                files=["app.js", "../../etc/passwd", ".env"],
                instruction="In remaining(), count only tasks that are not done.",
            )
        ]
    )
    agent = RecordingAgent([{"app.js": COUNT_BUG_JS}, {"app.js": GOOD_JS}])
    outcome = await _graph(project, agent, model=model).run(contract(project))

    assert outcome.terminal == "succeeded"
    prompt = agent.prompts[1]
    assert "complete-decrements" in prompt and "expected" in prompt  # the facts from the browser are still there
    assert "remaining() counts every task" in prompt and "count only tasks that are not done" in prompt
    assert "written by a model" in prompt  # and it is marked as a lead, not a fact
    assert "`app.js`" in prompt and "passwd" not in prompt and ".env" not in prompt
    task = str(model.seen["diagnoser"][0][1].content)
    assert "app.js" in task and "<untrusted" in task  # the Diagnoser was shown the agent's diff, marked
    assert {usage.agent for usage in outcome.agents} >= {"triage", "diagnoser"}
    assert (Path(outcome.run_dir) / "agents" / "diagnoser.jsonl").is_file()


async def test_a_diagnoser_that_fails_does_not_stop_the_repair(project: Path) -> None:
    model = AgentScript(diagnoser=[RuntimeError("provider down")])
    agent = RecordingAgent([{"app.js": COUNT_BUG_JS}, {"app.js": GOOD_JS}])
    outcome = await _graph(project, agent, model=model).run(contract(project))
    assert outcome.terminal == "succeeded"
    assert "complete-decrements" in agent.prompts[1] and "Likely cause" not in agent.prompts[1]


async def test_a_spent_budget_runs_the_loop_on_rules_alone(project: Path) -> None:
    budget = Budget(max_tokens=10)
    budget.spend(10, 0, None)
    model = AgentScript()
    agent = RecordingAgent([{"app.js": COUNT_BUG_JS}, {"app.js": GOOD_JS}])
    outcome = await _graph(project, agent, model=model, budget=budget).run(contract(project))
    assert outcome.terminal == "succeeded" and model.total_calls == 0  # no Planner, no Triage, no Diagnoser
    assert outcome.triage[0].source == "rules"


# -- the Planner before the first turn ----------------------------------------------------------------

_PLAN = {
    "change": ["app.js", ".env", ".contexer/contracts/todo-basics.json", "../../etc/passwd"],
    "read_first": ["index.html", "C:/Windows/win.ini"],
    "reuse": ["remaining() already computes the count."],
    "order": ["Render the list, then update the count in the same render."],
    "edge_cases": ["Completing the last open task shows 0 left."],
    "keep": ["The data-testid values in index.html."],
}


async def _template(tmp_path: Path) -> str:
    """The first instruction of a run with no model, on a copy of the project with the same name."""
    plain = copy_todo(tmp_path / "plain")
    agent = RecordingAgent([{"app.js": GOOD_JS}])
    await _graph(plain, agent).run(contract(plain))
    return agent.prompts[0]


async def test_the_planners_brief_follows_the_first_instruction_and_changes_none_of_it(project: Path, tmp_path: Path) -> None:
    model = AgentScript(planner=[submit(**_PLAN)])
    agent = RecordingAgent([{"app.js": COUNT_BUG_JS}, {"app.js": GOOD_JS}])
    outcome = await _graph(project, agent, model=model).run(contract(project))

    assert outcome.terminal == "succeeded"
    template = await _template(tmp_path)
    first = agent.prompts[0]
    assert first.startswith(template) and first != template  # the goal, the checks and the rules as code wrote them
    brief = first[len(template) :]
    assert "written by a model" in brief and "Files to change: `app.js`" in brief and "Read first: `index.html`" in brief
    assert "remaining() already computes the count." in brief and "0 left" in brief
    for hidden in (".env", ".contexer", "passwd", "win.ini"):
        assert hidden not in brief
    assert "remaining() already computes the count." not in agent.prompts[1]  # a repair gets the evidence, not the plan again
    assert len(model.seen["planner"]) == 1  # once, before the first turn
    assert "complete-decrements" in str(model.seen["planner"][0][1].content)  # it was shown the checks
    assert {usage.agent for usage in outcome.agents} >= {"planner", "triage", "diagnoser"}
    planner = next(usage for usage in outcome.agents if usage.agent == "planner")
    assert planner.steps == 1 and (planner.tokens_in, planner.tokens_out) == (10, 5)
    assert (Path(outcome.run_dir) / "agents" / "planner.jsonl").is_file()


@pytest.mark.parametrize(
    "replies",
    [
        [RuntimeError("provider down")],
        [submit(change="app.js")] * 6,  # never the right shape
        [submit()],  # nothing to say
        [submit(change=[".env", ".contexer/contracts/todo-basics.json"], read_first=["../outside.txt"])],  # nothing that may be said
    ],
)
async def test_a_planner_with_no_usable_brief_leaves_the_first_instruction_exactly_as_it_was(project: Path, tmp_path: Path, replies: list[Any]) -> None:
    model = AgentScript(planner=replies)
    agent = RecordingAgent([{"app.js": GOOD_JS}])
    outcome = await _graph(project, agent, model=model).run(contract(project))

    assert outcome.terminal == "succeeded"
    assert agent.prompts[0] == await _template(tmp_path)


async def test_the_planner_can_be_turned_off(project: Path) -> None:
    model = AgentScript(planner=[submit(**_PLAN)])
    agent = RecordingAgent([{"app.js": GOOD_JS}])
    settings = RunSettings(max_repair_rounds=2, plan=False)
    outcome = await GraphController(project, agent, settings, runner=fast_runner(), model=model).run(contract(project))

    assert outcome.terminal == "succeeded" and "planner" not in model.seen
    assert "written by a model" not in agent.prompts[0]


async def test_a_correction_that_changes_no_check_keeps_the_brief_and_pays_for_no_second_one(project: Path) -> None:
    model = AgentScript(intent=[submit(behaviours=["Tasks can be added"], checks=[])], planner=[submit(**_PLAN)])
    agent = RecordingAgent([{"app.js": GOOD_JS}])
    pending = ["Keep it simple."]
    controller = _graph(project, agent, model=model, corrections=lambda: pending.pop() if pending else None)
    outcome = await controller.run(contract(project))

    assert outcome.terminal == "succeeded", outcome.reason
    assert len(model.seen["planner"]) == 1  # the checks did not change, so the brief for them stands
    [first] = agent.prompts
    assert "Keep it simple." in first and first.count("Files to change: `app.js`") == 1


async def test_a_goal_that_is_drafted_and_approved_is_planned_before_it_is_built(project: Path) -> None:
    (project / ".contexer" / "contracts" / f"{CONTRACT_ID}.json").unlink()
    model = AgentScript(intent=[_intent_reply()], planner=[submit(**_PLAN)])
    agent = RecordingAgent([{"app.js": GOOD_JS}])
    outcome = await _graph(project, agent, model=model, ask=lambda _r: {"approve": True}).run_goal(GOAL)

    assert outcome.terminal == "succeeded", outcome.reason
    assert "Files to change: `app.js`" in agent.prompts[0] and agent.prompts[0].index("Rules:") < agent.prompts[0].index("Files to change")
    assert [usage.agent for usage in outcome.agents][:2] == ["intent", "planner"]


# -- intent and approval in the graph ---------------------------------------------------------------


def _intent_reply() -> Any:
    return submit(behaviours=["Adding a task shows it in the list"], checks=contract_checks())


async def test_a_goal_is_drafted_approved_built_and_proven(project: Path) -> None:
    (project / ".contexer" / "contracts" / f"{CONTRACT_ID}.json").unlink()  # nothing says what done means yet
    asked: list[dict[str, Any]] = []

    def ask(request: dict[str, Any]) -> dict[str, Any]:
        asked.append(request)
        return {"approve": True}

    model = AgentScript(intent=[_intent_reply()])
    agent = RecordingAgent([{"app.js": GOOD_JS}])
    outcome = await _graph(project, agent, model=model, ask=ask).run_goal(GOAL)

    assert outcome.terminal == "succeeded", outcome.reason
    [request] = asked
    assert request["kind"] == "approve" and request["goal"] == GOAL
    assert any("complete-decrements" in line for line in request["checks"])
    from contexer.contract import ContractStore

    stored = ContractStore(project).load(outcome.contract_id)
    assert stored.status == "approved" and len(stored.criteria) == 7
    assert outcome.intent_id and (project / ".contexer" / "intent" / f"{outcome.intent_id}.md").is_file()
    assert "complete-decrements" in agent.prompts[0]


async def test_checks_that_are_not_approved_are_never_built_against(project: Path) -> None:
    (project / ".contexer" / "contracts" / f"{CONTRACT_ID}.json").unlink()
    model = AgentScript(intent=[_intent_reply()])
    agent = RecordingAgent([{"app.js": BROKEN_JS}])
    outcome = await _graph(project, agent, model=model, ask=lambda _r: {"approve": False}).run_goal(GOAL)

    assert outcome.terminal == "needs_human" and outcome.exit_code == 2
    assert agent.prompts == [] and (project / "app.js").read_text(encoding="utf-8") == GOOD_JS


async def test_with_nobody_to_approve_nothing_is_approved(project: Path) -> None:
    (project / ".contexer" / "contracts" / f"{CONTRACT_ID}.json").unlink()
    agent = RecordingAgent([{"app.js": BROKEN_JS}])
    outcome = await _graph(project, agent, model=AgentScript(intent=[_intent_reply()])).run_goal(GOAL)
    assert outcome.terminal == "needs_human" and agent.prompts == []


async def test_a_goal_no_check_was_drafted_for_ends_before_any_build(project: Path) -> None:
    (project / ".contexer" / "contracts" / f"{CONTRACT_ID}.json").unlink()
    agent = RecordingAgent([{"app.js": BROKEN_JS}])
    model = AgentScript(intent=[submit(behaviours=["It works"], checks=[])])
    outcome = await _graph(project, agent, model=model, ask=lambda _r: {"approve": True}).run_goal(GOAL)
    assert outcome.terminal == "needs_human" and "no check" in outcome.reason.lower() and agent.prompts == []


async def test_a_goal_needs_a_model_or_a_draft(project: Path) -> None:
    with pytest.raises(ValueError, match="model"):
        await _graph(project, RecordingAgent([])).run_goal(GOAL)


async def test_a_draft_from_elsewhere_waits_for_approval_in_the_graph(project: Path) -> None:
    draft = contract(project).model_copy(update={"approval": None})
    kinds: list[str] = []

    def ask(request: dict[str, Any]) -> dict[str, Any]:
        kinds.append(request["kind"])
        return {"approve": True}

    agent = RecordingAgent([{"app.js": GOOD_JS}])
    outcome = await _graph(project, agent, ask=ask).run_goal(draft.goal, draft=draft)
    assert outcome.terminal == "succeeded" and kinds == ["approve"]


async def test_the_intent_agent_is_shown_the_app_as_it_is_before_it_drafts_checks(project: Path) -> None:
    """Checks drafted blind invent names; the coding agent then renames the app to fit them (seen in a live run)."""
    (project / ".contexer" / "contracts" / f"{CONTRACT_ID}.json").unlink()
    model = AgentScript(intent=[_intent_reply()])
    agent = RecordingAgent([{"app.js": GOOD_JS}])
    outcome = await _graph(project, agent, model=model, ask=lambda _r: {"approve": True}).run_goal(GOAL)

    assert outcome.terminal == "succeeded", outcome.reason
    task = str(model.seen["intent"][0][1].content)
    assert "What needs doing?" in task and "remaining-count" in task  # the placeholder and test id the app really has
    assert task.index("<untrusted") < task.index("What needs doing?")  # and they are marked as coming from the app


async def test_a_goal_for_an_app_that_does_not_start_yet_is_drafted_from_the_goal_alone(tmp_path: Path) -> None:
    project = tmp_path / "empty"
    project.mkdir()
    (project / "notes.txt").write_text("nothing to serve yet\n", encoding="utf-8")
    events: list[str] = []
    model = AgentScript(intent=[_intent_reply()])
    controller = GraphController(
        project, RecordingAgent([]), RunSettings(), runner=fast_runner(), model=model,
        ask=lambda _r: {"approve": False}, on_event=lambda _k, m: events.append(m),
    )  # fmt: skip
    outcome = await controller.run_goal(GOAL)
    assert outcome.terminal == "needs_human"  # not approved; the point is that drafting did not need a running app
    assert len(model.seen["intent"]) == 1
