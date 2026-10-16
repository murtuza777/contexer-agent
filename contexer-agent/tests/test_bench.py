"""The benchmark scores bugs and clean runs, and refuses invalid contracts."""

import json
import shutil
from pathlib import Path

import pytest

from contexer.bench import discover, run_bench
from contexer.contract import ContractStore

pytestmark = pytest.mark.anyio

FIXTURE = Path(__file__).resolve().parents[1] / "bench" / "fixtures" / "todo"


def _mini_fixture(root: Path, bugs: tuple[str, ...] = ("count-ignores-done",), benign: tuple[str, ...] = ()) -> Path:
    app = root / "todo"
    shutil.copytree(FIXTURE / "app", app / "app", ignore=shutil.ignore_patterns("runs"))
    for name in bugs:
        shutil.copytree(FIXTURE / "bugs" / name, app / "bugs" / name)
    for name in benign:
        shutil.copytree(FIXTURE / "benign" / name, app / "benign" / name)
    return root


def test_discover_reads_bugs_and_expected_catchers(tmp_path: Path) -> None:
    [app] = discover(_mini_fixture(tmp_path, benign=("restyle",)))
    assert app.name == "todo"
    assert [b.name for b in app.bugs] == ["count-ignores-done"]
    assert app.bugs[0].expected_catcher == "complete-decrements"
    assert [b.name for b in app.benign] == ["restyle"]


async def test_bench_catches_the_bug_with_no_false_failures(tmp_path: Path) -> None:
    report = await run_bench(_mini_fixture(tmp_path), repeats=1)
    [score] = report.apps
    assert score.valid
    assert (score.bugs, score.caught, score.missed) == (1, 1, 0)
    assert score.false_failure_runs == 0
    bug_run = next(r for r in report.runs if r.kind == "bug")
    assert bug_run.caught_by_expected is True


async def test_contract_that_fails_on_the_good_app_is_invalid(tmp_path: Path) -> None:
    root = _mini_fixture(tmp_path)
    good_js = root / "todo" / "app" / "app.js"
    shutil.copyfile(FIXTURE / "bugs" / "input-not-cleared" / "app.js", good_js)
    report = await run_bench(root, repeats=1)
    [score] = report.apps
    assert not score.valid
    assert "fails on the good app" in score.invalid_reason


async def test_live_mode_scores_a_compiled_contract_and_drops_checks_that_fail_on_good_code(
    tmp_path: Path, fake_llm
) -> None:
    complete_check = {
        "steps": [
            {"action": "fill", "target": {"placeholder": "What needs doing?"}, "value": "A"},
            {"action": "click", "target": {"role": "button", "name": "Add"}},
            {"action": "check", "target": {"role": "checkbox", "name": "Complete A"}},
        ],
        "expect": [{"kind": "text", "target": {"test_id": "remaining-count"}, "equals": "0 left"}],
    }
    reply = json.dumps(
        {
            "summary": "todo",
            "acceptance_criteria": [
                {"id": "completes", "description": "Completing lowers the count", "check": complete_check},
                {"id": "bogus", "description": "A widget that does not exist",
                 "check": {"expect": [{"kind": "visible", "target": {"text": "Nonexistent widget"}}]}},
            ],
        }
    )
    llm = fake_llm(reply)
    report = await run_bench(_mini_fixture(tmp_path), repeats=1, live_llm=llm)

    [score] = report.apps
    assert score.app == "todo (compiled)"
    assert score.compiled is not None
    assert score.compiled.failed_on_good == ["bogus"]
    assert (score.caught, score.missed, score.false_failure_runs) == (1, 0, 0)
    assert len(llm.prompts) == 1  # the goal was compiled once, from the contract's goal text
    assert "Users can add, complete and delete tasks" in llm.prompts[0]


async def test_unapproved_contracts_make_the_app_invalid(tmp_path: Path) -> None:
    root = _mini_fixture(tmp_path)
    store = ContractStore(root / "todo" / "app")
    contract = store.load("todo-basics")
    store.save(contract.model_copy(update={"approval": None}))
    report = await run_bench(root, repeats=1)
    assert not report.apps[0].valid
