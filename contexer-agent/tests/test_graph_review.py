"""The Reviewer in the loop (T4.1): a run that passes its checks is read before it is reported.

The review can ask for one more repair when code saw something wrong. It can never undo a pass: the
checks decide whether a run succeeded, with or without a review.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from contexer.controller import RunSettings
from contexer.crew.reviewer import ReviewResult
from contexer.graph import GraphController
from contexer.graph.routing import EDGES, NODES, TARGETS
from tests.fakes import AgentScript, submit
from tests.loop_helpers import BROKEN_JS, GOOD_JS, RecordingAgent, contract, copy_todo, fast_runner

pytestmark = pytest.mark.anyio

LEAK = 'const SERVICE_KEY = "' + "q7Rk2ZpX9vLm" + "4TnB8sWd3Yf6" + '";\n'
LEAKY_JS = LEAK + GOOD_JS
DEBUG_JS = GOOD_JS + '\nconsole.log("render done");\n'


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return copy_todo(tmp_path)


def _graph(project: Path, agent: Any, rounds: int = 2, **kwargs: Any) -> GraphController:
    settings = RunSettings(max_repair_rounds=rounds, **kwargs.pop("settings", {}))
    return GraphController(project, agent, settings, runner=fast_runner(), **kwargs)


def test_review_is_a_node_between_a_pass_and_the_end() -> None:
    assert "review" in NODES and "review" in TARGETS["score"]
    assert set(TARGETS["review"]) == {"coder_turn", "finalize"}
    passed: Any = {"terminal": "succeeded", "n": 1}
    assert EDGES["score"](passed) == "review"
    assert EDGES["score"]({**passed, "reviewed": 1}) == "finalize"  # once per attempt
    for terminal in ("failed_checks", "tampered", "needs_human", "budget_exhausted"):
        assert EDGES["score"]({"terminal": terminal, "n": 1}) == "finalize"  # only a pass is reviewed
    assert EDGES["review"]({"terminal": "succeeded"}) == "finalize"
    assert EDGES["review"]({"terminal": ""}) == "coder_turn"


async def test_a_passing_run_is_reviewed_and_low_notes_do_not_cost_a_turn(project: Path) -> None:
    agent = RecordingAgent([{"app.js": DEBUG_JS}])
    outcome = await _graph(project, agent).run(contract(project))

    assert outcome.terminal == "succeeded" and len(outcome.attempts) == 1
    [note] = outcome.review
    assert (note.file, note.severity, note.category, note.source) == ("app.js", "low", "debug", "scan")
    report = (Path(outcome.run_dir) / "report.html").read_text(encoding="utf-8")
    assert "Review" in report and "app.js" in report and "console.log" in report
    saved = json.loads((Path(outcome.run_dir) / "run.json").read_text(encoding="utf-8"))
    assert saved["review"][0]["category"] == "debug"


async def test_something_code_saw_gets_one_repair_and_the_fix_is_reviewed_again(project: Path) -> None:
    agent = RecordingAgent([{"app.js": LEAKY_JS}, {"app.js": GOOD_JS}])
    events: list[tuple[str, str]] = []
    outcome = await _graph(project, agent, on_event=lambda kind, message: events.append((kind, message))).run(contract(project))

    assert outcome.terminal == "succeeded" and [a.outcome for a in outcome.attempts] == ["pass", "pass"]
    assert outcome.best_attempt == 2 and outcome.review == []  # the second review found nothing
    repair = agent.prompts[1]
    assert "app.js:1" in repair and "looks like a secret" in repair.lower()
    assert "q7Rk2ZpX9vLm" not in repair  # the prompt says where, never what
    assert "every check passed" in repair.lower()  # the agent is told the checks hold and must keep holding
    assert agent.sessions[1] == "scripted-1"  # the session that wrote it fixes it
    assert any(kind == "review" and "1 to fix" in message for kind, message in events)
    assert (project / "app.js").read_text(encoding="utf-8") == GOOD_JS


async def test_a_review_repair_that_breaks_the_checks_is_undone_and_the_pass_stands(project: Path) -> None:
    agent = RecordingAgent([{"app.js": LEAKY_JS}, {"app.js": BROKEN_JS}])
    outcome = await _graph(project, agent).run(contract(project))

    assert outcome.terminal == "succeeded", outcome.reason  # the checks passed on attempt 1; a review cannot take that away
    assert outcome.best_attempt == 1 and len(outcome.attempts) == 2
    assert outcome.attempts[1].reverted_to == 1
    assert (project / "app.js").read_text(encoding="utf-8") == LEAKY_JS
    assert outcome.final is not None and outcome.final.decision.outcome == "pass"
    # The note is still open, and the person is told.
    assert [(n.severity, n.category) for n in outcome.review] == [("high", "security")]
    assert len(agent.prompts) == 2  # and no third turn was spent on it


async def test_a_review_asks_for_a_repair_only_once(project: Path) -> None:
    agent = RecordingAgent([{"app.js": LEAKY_JS}, {"app.js": LEAKY_JS + "// tidied\n"}])
    outcome = await _graph(project, agent).run(contract(project))
    assert outcome.terminal == "succeeded" and len(outcome.attempts) == 2
    assert [(n.severity, n.category) for n in outcome.review] == [("high", "security")]


async def test_no_repair_round_left_means_the_note_is_only_reported(project: Path) -> None:
    agent = RecordingAgent([{"app.js": LEAKY_JS}])
    outcome = await _graph(project, agent, rounds=0).run(contract(project))
    assert outcome.terminal == "succeeded" and len(outcome.attempts) == 1
    assert outcome.review and outcome.review[0].severity == "high"


async def test_a_run_that_does_not_pass_is_not_reviewed(project: Path) -> None:
    outcome = await _graph(project, RecordingAgent([{"app.js": BROKEN_JS}]), rounds=0).run(contract(project))
    assert outcome.terminal == "failed_checks" and outcome.review == []


async def test_the_review_can_be_turned_off(project: Path) -> None:
    agent = RecordingAgent([{"app.js": LEAKY_JS}])
    outcome = await _graph(project, agent, settings={"review": False}).run(contract(project))
    assert outcome.terminal == "succeeded" and outcome.review == [] and len(agent.prompts) == 1


async def test_the_models_notes_are_recorded_and_never_start_a_repair(project: Path) -> None:
    opinion = {"file": "app.js", "line": 3, "severity": "high", "category": "security", "explanation": "innerHTML is fed user text."}
    model = AgentScript(reviewer=[submit(notes=[opinion])])
    # A real change: on a checkout without line-ending conversion GOOD_JS alone is no diff, and nothing is reviewed.
    agent = RecordingAgent([{"app.js": GOOD_JS + "// tidied\n"}])
    outcome = await _graph(project, agent, model=model).run(contract(project))

    assert outcome.terminal == "succeeded" and len(agent.prompts) == 1
    [note] = outcome.review
    assert note.source == "reviewer" and not note.backed and note.explanation == opinion["explanation"]
    assert [a.agent for a in outcome.agents] == ["planner", "reviewer"]  # the brief before the turn, the review after it
    assert (Path(outcome.run_dir) / "agents" / "reviewer.jsonl").is_file()


async def test_a_command_that_writes_files_does_not_change_what_was_proven(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def formatter_ran(diff: str, project_dir: Path, model: Any = None, **_: Any) -> ReviewResult:
        (Path(project_dir) / "app.js").write_text("reformatted, and broken", encoding="utf-8")
        return ReviewResult()

    monkeypatch.setattr("contexer.graph.nodes.review", formatter_ran)
    outcome = await _graph(project, RecordingAgent([{"app.js": GOOD_JS}])).run(contract(project))
    assert outcome.terminal == "succeeded"
    assert (project / "app.js").read_text(encoding="utf-8") == GOOD_JS  # put back to the snapshot that passed
