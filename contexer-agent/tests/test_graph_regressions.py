"""AGT-1: an earlier behaviour this change broke is a regression; one that was already broken is said so.

The earlier approved contracts are replayed once on the project as it was found, before the first
coding turn. That replay is the baseline: a check that passed there and fails after an attempt is a
regression, and one that already failed there is stale. Both come from checks replayed by code.

The coding agent is scripted; the snapshots, the app, the browser and the checks are real.
"""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from contexer.agents import ScriptedAgent
from contexer.agents.base import AgentTurn
from contexer.appserver import AppStartError
from contexer.cli.runview import RunView
from contexer.contract import Contract, ContractStore
from contexer.controller import RunOutcome, RunSettings
from contexer.controller.models import Attempt
from contexer.controller.prompts import failure_report
from contexer.controller.shared import score, sig_label, signatures
from contexer.gate import ContractOutcome, decide
from contexer.gate.models import RunResult
from contexer.github.handoff import pull_request_body
from contexer.graph import GraphController, nodes
from contexer.graph.context import RunEvent
from contexer.graph.routing import EDGES, TARGETS
from contexer.verification.checks import CheckResult
from contexer.verification.models import AcceptanceCriterion, CriterionResult, VerificationResult
from tests.loop_helpers import (
    BROKEN_JS,
    CONTRACT_ID,
    COUNT_BUG_JS,
    GOOD_JS,
    RecordingAgent,
    contract,
    copy_todo,
    fast_runner,
)

pytestmark = pytest.mark.anyio

NEW, EARLIER = "todo-new", "todo-earlier"
COUNT = f"{EARLIER}/complete-decrements"
DELETE = f"{EARLIER}/delete-removes-right-task"
COUNT_TITLE = "Completing a task lowers the remaining count and raises no errors"
BEFORE_FIRST_TURN = "before the first turn"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return copy_todo(tmp_path)


def _split(project: Path) -> tuple[Contract, Contract]:
    """The fixture's contract as two: the one this run builds, and one approved earlier."""
    store = ContractStore(project)
    whole = store.load(CONTRACT_ID)
    by_id = {c.id: c for c in whole.criteria}

    def part(cid: str, goal: str, ids: list[str]) -> Contract:
        made = whole.model_copy(update={"id": cid, "goal": goal, "criteria": [by_id[i] for i in ids], "approval": None})
        made = made.approved_by("tester")
        store.save(made)
        return made

    store.path_for(CONTRACT_ID).unlink()
    new = part(NEW, "The app loads and a task can be added", ["add-shows-task", "loads-clean"])
    earlier = part(EARLIER, "Tasks can be completed and deleted", ["complete-decrements", "delete-removes-right-task"])
    return new, earlier


class _Run:
    """One scripted run with an earlier contract, and what it said while it ran."""

    def __init__(self, project: Path, agent: Any, rounds: int = 2) -> None:
        self.project = project
        self.agent = agent
        self.events: list[tuple[str, str]] = []
        self.details: list[RunEvent] = []
        self.controller = GraphController(
            project,
            agent,
            RunSettings(max_repair_rounds=rounds),
            runner=fast_runner(),
            on_event=lambda kind, message: self.events.append((kind, message)),
            on_detail=self.details.append,
        )

    def said(self, words: str) -> list[str]:
        return [message for _kind, message in self.events if words in message]

    def attempt_result(self, outcome: RunOutcome, n: int) -> RunResult:
        path = Path(outcome.run_dir) / f"attempt-{n}" / "run-result.json"
        return RunResult.model_validate_json(path.read_text(encoding="utf-8"))


def _saved(outcome: RunOutcome) -> dict[str, Any]:
    return json.loads((Path(outcome.run_dir) / "run.json").read_text(encoding="utf-8"))


# -- a regression: passed on the project as found, fails after an attempt ---------------------------


async def test_a_regression_made_by_the_first_attempt_is_named_and_then_fixed(project: Path) -> None:
    new, earlier = _split(project)
    run = _Run(project, RecordingAgent([{"app.js": COUNT_BUG_JS}, {"app.js": GOOD_JS + "\n// fixed\n"}]))
    outcome = await run.controller.run(new, [earlier])

    assert outcome.terminal == "succeeded", outcome.reason
    assert [a.outcome for a in outcome.attempts] == ["fail", "pass"]
    assert len(run.said(BEFORE_FIRST_TURN)) == 1  # the view is told the earlier checks are being replayed
    saved = _saved(outcome)
    assert saved["baseline"]["ran"] is True
    assert sorted(saved["baseline"]["passed"]) == [COUNT, DELETE] and saved["baseline"]["failing"] == []

    first = run.attempt_result(outcome, 1).decision
    assert first.outcome == "fail" and first.regressions == {COUNT: 1} and first.stale == []
    repair = run.agent.prompts[1]
    assert "regression" in repair.lower() and COUNT in repair and "attempt 1" in repair
    verdicts = [e.data for e in run.details if e.kind == "verdict"]
    assert verdicts[0]["regressions"] == [{"check": COUNT, "attempt": 1}] and verdicts[0]["others_failing"] == 1

    # Fixed: the run ends clean, and says nothing about earlier checks.
    assert outcome.regressions == {} and outcome.stale == [] and saved["stale"] == []
    assert "already failing" not in outcome.reason


async def test_a_regression_that_is_not_fixed_is_reported_with_the_attempt_that_broke_it(project: Path) -> None:
    new, earlier = _split(project)
    turns: list[dict[str, str | None]] = [{"app.js": COUNT_BUG_JS}, {"app.js": COUNT_BUG_JS + "\n// again\n"}]
    run = _Run(project, RecordingAgent(turns), rounds=1)
    outcome = await run.controller.run(new, [earlier])

    assert outcome.terminal == "failed_checks"
    # Still broken after attempt 2, and it was attempt 1 that broke it.
    assert outcome.regressions == {COUNT: 1} and _saved(outcome)["regressions"] == {COUNT: 1}
    report = (Path(outcome.run_dir) / "report.html").read_text(encoding="utf-8")
    assert "Regression" in report and "broken in attempt 1" in report and COUNT_TITLE in report
    body = pull_request_body(outcome, new)
    assert "### Regressions" in body and COUNT_TITLE in body and "attempt 1" in body


def test_the_attempt_that_broke_a_check_is_found_through_the_attempts_the_files_came_from() -> None:
    def attempt(n: int, failing: list[str], reverted_to: int | None = None, outcome: str = "fail") -> Attempt:
        return Attempt(
            n=n,
            kind="repair",
            fresh_session=False,
            agent=AgentTurn(status="completed"),
            snapshot=f"s{n}",
            outcome=outcome,
            score=0,
            signatures=[f"{label}#abc" for label in failing],
            reverted_to=reverted_to,
        )

    # Attempt 2 broke b too and was undone back to attempt 1, so attempt 3 began from attempt 1's files.
    attempts = [attempt(1, ["e/a"]), attempt(2, ["e/a", "e/b"], reverted_to=1), attempt(3, ["e/a", "e/b"])]
    assert nodes._broken_in("e/a", attempts) == 1
    assert nodes._broken_in("e/b", attempts) == 3
    # An attempt where nothing ran did not show the check passing: the break is counted from there.
    attempts = [attempt(1, [], outcome="error"), attempt(2, ["e/a"])]
    assert nodes._broken_in("e/a", attempts) == 1


# -- a stale check: it already failed on the project as found -----------------------------------------


async def test_a_check_that_was_already_failing_does_not_fail_the_run_and_is_said_every_time(project: Path) -> None:
    new, earlier = _split(project)
    (project / "app.js").write_text(COUNT_BUG_JS, encoding="utf-8")  # broken before the run began
    run = _Run(project, RecordingAgent([{"app.js": BROKEN_JS}, {"app.js": COUNT_BUG_JS + "\n// done\n"}]))
    outcome = await run.controller.run(new, [earlier])

    saved = _saved(outcome)
    assert saved["baseline"] == {"ran": True, "passed": [DELETE], "failing": [COUNT]}
    assert len(run.said("already failing before this change")) >= 1

    # Attempt 1 broke everything. The stale check is not among what the coding agent, Triage or the
    # Diagnoser are given, and it does not move the score or the signatures; the regression comes first.
    first = run.attempt_result(outcome, 1)
    assert first.decision.stale == [COUNT] and first.decision.regressions == {DELETE: 1}
    assert COUNT not in {sig_label(s) for s in outcome.attempts[0].signatures}
    assert COUNT not in {sig_label(s) for s in signatures(first)} and DELETE in {sig_label(s) for s in signatures(first)}
    assert score(first, NEW) == -2  # one regression; the stale check costs nothing
    repair = run.agent.prompts[1]
    assert "complete-decrements" not in repair
    assert repair.index(DELETE) < repair.index(f"{NEW}/add-shows-task")
    assert "complete-decrements" not in failure_report(first)
    assert COUNT_TITLE not in [f.title for f in nodes._failures(first)]

    # Attempt 2 proves the new contract. The run succeeds, and never reads as fully clean.
    assert outcome.terminal == "succeeded", outcome.reason
    assert len(run.agent.prompts) == 2  # nobody was asked to repair what this change did not break
    assert outcome.final is not None and outcome.final.decision.outcome == "pass"
    assert outcome.final.decision.stale == [COUNT] and outcome.final.decision.verified == 3
    assert outcome.stale == [COUNT] and saved["stale"] == [COUNT]
    assert "1 earlier check was already failing before this change" in outcome.reason
    assert "Every check proven" not in outcome.reason
    assert "already failing" in outcome.final.decision.headline()
    report = (Path(outcome.run_dir) / "report.html").read_text(encoding="utf-8")
    assert "already failing before this change" in report and COUNT_TITLE in report
    body = pull_request_body(outcome, new)
    assert "### Already failing before this change" in body and COUNT_TITLE in body
    assert "1 earlier check was already failing before this change" in body
    assert "**All " not in body  # not "all checks proven"
    verdict = [e.data for e in run.details if e.kind == "verdict"][-1]
    assert verdict["stale"] == 1 and verdict["others_failing"] == 0


# -- no baseline ------------------------------------------------------------------------------------


async def test_without_a_baseline_an_earlier_failure_counts_as_it_does_today(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    new, earlier = _split(project)
    (project / "app.js").write_text(COUNT_BUG_JS, encoding="utf-8")
    real, calls = nodes.open_app, []

    def not_at_first(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        if len(calls) == 1:
            raise AppStartError("The dev server did not start")
        return real(*args, **kwargs)

    monkeypatch.setattr(nodes, "open_app", not_at_first)
    run = _Run(project, RecordingAgent([{"app.js": COUNT_BUG_JS + "\n// built\n"}]), rounds=0)
    outcome = await run.controller.run(new, [earlier])

    assert _saved(outcome)["baseline"] == {"ran": False, "passed": [], "failing": []}
    assert run.said("could not be replayed before the first turn")
    # Nothing says the check was broken before, so it blocks; and nothing says this change broke it.
    assert outcome.terminal == "failed_checks"
    assert outcome.stale == [] and outcome.regressions == {}
    assert COUNT in {sig_label(s) for s in outcome.attempts[0].signatures}


async def test_a_run_with_no_other_contract_replays_nothing_before_the_first_turn(project: Path) -> None:
    replayed: list[int] = []

    class _Counting(type(fast_runner())):  # type: ignore[misc]
        async def run(self, *args: Any, **kwargs: Any) -> Any:
            replayed.append(1)
            return await super().run(*args, **kwargs)

    events: list[str] = []
    controller = GraphController(
        project,
        ScriptedAgent([{"app.js": GOOD_JS + "\n// built\n"}]),
        RunSettings(),
        runner=_Counting(action_timeout=1.5, expect_timeout=1.0),
        on_event=lambda _kind, message: events.append(message),
    )
    outcome = await controller.run(contract(project))

    assert outcome.terminal == "succeeded", outcome.reason
    assert not [m for m in events if BEFORE_FIRST_TURN in m]
    assert len(replayed) == 7  # the contract's checks once, and nothing else
    assert _saved(outcome)["baseline"] is None and outcome.stale == [] and outcome.regressions == {}


# -- resume -------------------------------------------------------------------------------------------


class _StuckOnFirstTurn(ScriptedAgent):
    """Never returns from its first turn."""

    def __init__(self) -> None:
        super().__init__([])
        self.started = asyncio.Event()

    async def run_turn(self, workdir: Path, prompt: str, **kwargs: Any) -> AgentTurn:
        self.started.set()
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")


async def test_a_run_stopped_after_the_baseline_keeps_it_and_does_not_replay_it_again(project: Path) -> None:
    new, earlier = _split(project)
    stuck = _StuckOnFirstTurn()
    first = _Run(project, stuck)
    task = asyncio.create_task(first.controller.run(new, [earlier]))
    await asyncio.wait_for(stuck.started.wait(), 60)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    stopped = first.controller.last_outcome
    assert stopped is not None and stopped.terminal == "cancelled"
    assert len(first.said(BEFORE_FIRST_TURN)) == 1

    second = _Run(project, RecordingAgent([{"app.js": COUNT_BUG_JS}]), rounds=0)
    resumed = await second.controller.resume(stopped.run_id)

    assert not second.said(BEFORE_FIRST_TURN)  # not replayed again
    assert resumed.baseline is not None and resumed.baseline["ran"] is True  # and not lost
    assert resumed.terminal == "failed_checks" and resumed.regressions == {COUNT: 1}


# -- the edges ----------------------------------------------------------------------------------------


def test_the_baseline_is_taken_once_and_only_when_there_are_earlier_contracts() -> None:
    assert EDGES["plan"]({"other_ids": ["earlier"]}) == "baseline"  # type: ignore[typeddict-item]
    assert EDGES["plan"]({"other_ids": ["earlier"], "baseline": {"ran": True}}) == "coder_turn"  # type: ignore[typeddict-item]
    assert EDGES["plan"]({"other_ids": []}) == "coder_turn"  # type: ignore[typeddict-item]
    assert EDGES["baseline"]({}) == "coder_turn"  # type: ignore[typeddict-item]
    assert set(TARGETS["baseline"]) == {"coder_turn", "finalize"}


# -- the gate -----------------------------------------------------------------------------------------


def _checked(contract_id: str, results: dict[str, bool]) -> ContractOutcome:
    rows = [
        CriterionResult(
            criterion_id=cid,
            description=cid,
            passed=passed,
            method="assertion",
            check_result=CheckResult(criterion_id=cid, passed=passed),
        )
        for cid, passed in results.items()
    ]
    made = Contract(id=contract_id, goal="g", criteria=[AcceptanceCriterion(id=cid, description="d") for cid in results])
    return ContractOutcome(
        contract=made.approved_by("tester"),
        verification=VerificationResult(passed=all(results.values()), criteria_results=rows),
    )


def test_the_gate_leaves_out_a_stale_check_and_says_which() -> None:
    outcomes = [_checked("new", {"a": True}), _checked("old", {"b": False, "c": True})]
    assert decide(outcomes).outcome == "fail"  # `contexer verify` and the stop hook have no baseline: as today

    decision = decide(outcomes, stale={"old/b"})
    assert decision.outcome == "pass" and decision.stale == ["old/b"]
    assert (decision.verified, decision.refuted) == (2, 0)
    assert "1 already failing before" in decision.headline()


def test_a_contract_whose_checks_are_all_stale_is_not_reported_as_having_no_checks() -> None:
    decision = decide([_checked("new", {"a": True}), _checked("old", {"b": False})], stale={"old/b"})
    assert decision.outcome == "pass" and decision.reasons == []


def test_a_check_that_was_failing_before_and_passes_now_is_counted_as_proven() -> None:
    decision = decide([_checked("new", {"a": True}), _checked("old", {"b": True})], stale={"old/b"})
    assert decision.outcome == "pass" and decision.stale == [] and decision.verified == 2


def test_a_failing_check_of_another_contract_still_fails_when_it_is_not_stale() -> None:
    decision = decide([_checked("new", {"a": True}), _checked("old", {"b": False, "c": False})], stale={"old/b"})
    assert decision.outcome == "fail" and decision.refuted == 1 and decision.stale == ["old/b"]


# -- the run view -------------------------------------------------------------------------------------


def _view() -> tuple[RunView, Console]:
    console = Console(record=True, width=120, force_terminal=False, color_system=None, file=io.StringIO())
    return RunView(console), console


def _verdict(view: RunView, **data: Any) -> None:
    rows = [{"id": "a", "verdict": "verified", "evidence": ""}]
    view.handle(RunEvent("checks", "", {"contract_id": "c", "goal": "g", "checks": [{"id": "a", "description": "A"}], "earlier_checks": 3}))
    view.handle(RunEvent("verdict", "Attempt 1", {"n": 1, "outcome": data.pop("outcome", "pass"), "checks": rows, **data}))


def test_the_view_says_an_earlier_check_was_already_failing_on_a_run_that_passes() -> None:
    view, console = _view()
    _verdict(view, others_failing=0, stale=1)
    text = console.export_text()
    assert "1 earlier check was already failing before this change" in text
    assert "earlier checks still pass" not in text


def test_the_view_names_a_regression_and_the_attempt_that_broke_it() -> None:
    view, console = _view()
    _verdict(view, outcome="fail", others_failing=1, regressions=[{"check": "old/b", "attempt": 1}])
    text = console.export_text()
    assert "1 earlier check broke" in text
    assert "Regression: old/b, broken in attempt 1" in text
