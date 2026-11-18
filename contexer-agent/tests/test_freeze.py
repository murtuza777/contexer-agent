"""Freeze and replay: no finding is shown unless code reproduced it."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from contexer.appserver import open_app
from contexer.browser.freeze import (
    UNCONFIRMED_FILE,
    draft_contract,
    freeze,
    replay_findings,
    write_unconfirmed,
)
from contexer.contract import ContractStore
from contexer.crew.tester import Finding
from contexer.verification.checks import Check
from contexer.verification.runner import CheckRunner

pytestmark = pytest.mark.anyio

FIXTURES = Path(__file__).resolve().parents[1] / "bench" / "fixtures"
INTENT = "Users can add, complete and delete tasks, and the remaining count stays correct"

_ADD = [
    {"action": "fill", "target": {"placeholder": "What needs doing?"}, "value": "Buy milk"},
    {"action": "click", "target": {"role": "button", "name": "Add"}},
]
_COMPLETE = [*_ADD, {"action": "check", "target": {"role": "checkbox", "name": "Complete Buy milk"}}]
_COUNT = {"test_id": "remaining-count"}


def _finding(kind: str, title: str, steps: list[dict[str, Any]], expectation: dict[str, Any], **extra: Any) -> Finding:
    return Finding.model_validate({"kind": kind, "title": title, "steps": steps, "expectation": expectation, **extra})


# What a tester would report on the app with the count-ignores-done bug.
COUNT_BUG = _finding("bug", "Completing a task does not lower the count", _COMPLETE,
                     {"kind": "text", "target": _COUNT, "equals": "0 left"}, severity="high")  # fmt: skip
ADD_WORKS = _finding("works", "Adding a task shows it", _ADD, {"kind": "visible", "target": {"text": "Buy milk"}})
# Claims that do not hold up.
NOT_A_BUG = _finding("bug", "Adding a task does not show it", _ADD, {"kind": "visible", "target": {"text": "Buy milk"}})
NOT_WORKING = _finding("works", "The count reaches zero", _COMPLETE, {"kind": "text", "target": _COUNT, "equals": "0 left"})
CANNOT_RUN = _finding("bug", "Archive does nothing", [{"action": "click", "target": {"role": "button", "name": "Archive"}}],
                      {"kind": "visible", "target": {"text": "Archived"}})  # fmt: skip


def _app(tmp_path: Path, bug: str | None = None) -> Path:
    work = tmp_path / "todo"
    shutil.copytree(FIXTURES / "todo" / "app", work, ignore=shutil.ignore_patterns("runs", "contracts"))
    if bug:
        shutil.copytree(FIXTURES / "todo" / "bugs" / bug, work, dirs_exist_ok=True)
    return work


def test_freeze_turns_the_recording_into_a_check() -> None:
    check = freeze(COUNT_BUG)
    assert isinstance(check, Check)
    assert check.steps == COUNT_BUG.steps and check.expect == [COUNT_BUG.expectation]
    assert check.login is None
    signed_out = COUNT_BUG.model_copy(update={"login": False})
    assert freeze(signed_out).login is False


async def test_a_bug_is_confirmed_when_its_check_fails_on_replay_and_works_when_it_passes(tmp_path: Path) -> None:
    with open_app(_app(tmp_path, "count-ignores-done")) as running:
        report = await replay_findings([COUNT_BUG, ADD_WORKS], running.url, artifacts_dir=tmp_path / "evidence")

    assert [c.finding.title for c in report.bugs] == [COUNT_BUG.title]
    assert [c.finding.title for c in report.works] == [ADD_WORKS.title]
    assert report.unconfirmed == []
    assert report.bugs[0].check == freeze(COUNT_BUG)
    assert '"1 left"' in report.bugs[0].evidence  # what the replay saw, not what the agent said
    assert list((tmp_path / "evidence").glob("*.jpg"))


async def test_a_finding_that_does_not_reproduce_is_never_listed_as_confirmed(tmp_path: Path) -> None:
    with open_app(_app(tmp_path, "count-ignores-done")) as running:
        report = await replay_findings([NOT_A_BUG, NOT_WORKING, CANNOT_RUN, COUNT_BUG], running.url)

    assert [c.finding.title for c in report.bugs] == [COUNT_BUG.title]
    assert report.works == []
    reasons = {u.finding.title: u.reason for u in report.unconfirmed}
    assert set(reasons) == {NOT_A_BUG.title, NOT_WORKING.title, CANNOT_RUN.title}
    assert "passed on replay" in reasons[NOT_A_BUG.title]
    assert "failed on replay" in reasons[NOT_WORKING.title] and '"1 left"' in reasons[NOT_WORKING.title]
    # A step that could not act proves nothing about the app.
    assert "could not" in reasons[CANNOT_RUN.title].lower()


async def test_on_the_correct_app_the_reported_bug_is_dropped(tmp_path: Path) -> None:
    with open_app(_app(tmp_path)) as running:
        report = await replay_findings([COUNT_BUG], running.url)

    assert report.bugs == [] and len(report.unconfirmed) == 1


async def test_a_confirmed_works_check_replays_green_three_times_in_a_row(tmp_path: Path) -> None:
    with open_app(_app(tmp_path)) as running:
        report = await replay_findings([ADD_WORKS], running.url, repeats=1)
        [confirmed] = report.works
        results = await CheckRunner().run(running.url, [(confirmed.criterion_id, confirmed.check)] * 3)

    assert [r.passed for r in results] == [True, True, True]


async def test_every_replay_must_agree_before_a_finding_is_confirmed(tmp_path: Path) -> None:
    """A check that passes once and fails once is flaky, which confirms nothing."""
    flips = iter([None, "the database was not reset"])

    async def before_each() -> str | None:
        return next(flips, None)

    with open_app(_app(tmp_path)) as running:
        report = await replay_findings([ADD_WORKS], running.url, repeats=2, before_each=before_each)

    assert report.works == []
    assert "not every replay agreed" in report.unconfirmed[0].reason


async def test_confirmed_checks_are_a_draft_contract_that_loads_through_the_store_unchanged(tmp_path: Path) -> None:
    work = _app(tmp_path, "count-ignores-done")
    with open_app(work) as running:
        report = await replay_findings([COUNT_BUG, ADD_WORKS, NOT_A_BUG], running.url)

    contract = draft_contract(INTENT, report)
    assert contract.status == "draft" and contract.source == "llm"
    assert contract.goal == INTENT
    assert [c.id for c in contract.criteria] == ["completing-task-does-not-lower-count", "adding-task-shows"]
    assert [c.check for c in contract.criteria] == [freeze(COUNT_BUG), freeze(ADD_WORKS)]

    store = ContractStore(work)
    store.save(contract)
    loaded = store.load(contract.id)
    assert loaded == contract
    assert loaded.content_hash() == contract.content_hash()


async def test_a_draft_with_nothing_confirmed_is_not_made(tmp_path: Path) -> None:
    with open_app(_app(tmp_path)) as running:
        report = await replay_findings([COUNT_BUG], running.url)
    assert draft_contract(INTENT, report) is None


async def test_unconfirmed_findings_are_written_with_the_reason(tmp_path: Path) -> None:
    with open_app(_app(tmp_path, "count-ignores-done")) as running:
        report = await replay_findings([NOT_A_BUG, COUNT_BUG], running.url)

    path = write_unconfirmed(tmp_path / "run", report)
    assert path == tmp_path / "run" / UNCONFIRMED_FILE == tmp_path / "run" / "unconfirmed.json"
    [entry] = json.loads(path.read_text(encoding="utf-8"))
    assert entry["title"] == NOT_A_BUG.title and entry["kind"] == "bug"
    assert "passed on replay" in entry["reason"]
    assert entry["check"]["steps"][0]["action"] == "fill"


async def test_no_findings_means_no_browser_and_an_empty_report() -> None:
    report = await replay_findings([], "http://127.0.0.1:9")
    assert (report.bugs, report.works, report.unconfirmed) == ([], [], [])
