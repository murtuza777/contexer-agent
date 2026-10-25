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


NODE_SERVER_JS = """
const http = require("http");
const fs = require("fs");
const page = fs.readFileSync("page.html", "utf8");
http.createServer((req, res) => {
  res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
  res.end(page);
}).listen(Number(process.env.PORT), "127.0.0.1");
"""


def _node_fixture(root: Path) -> Path:
    """An app with a package.json dev script: the bench must start it like `contexer verify` does."""
    from contexer.contract import Contract
    from contexer.verification.models import AcceptanceCriterion

    app = root / "greeter" / "app"
    app.mkdir(parents=True)
    (app / "package.json").write_text(json.dumps({"name": "greeter", "scripts": {"dev": "node server.js"}}), "utf-8")
    (app / "node_modules").mkdir()
    (app / "server.js").write_text(NODE_SERVER_JS, encoding="utf-8")
    (app / "page.html").write_text("<!doctype html><meta charset=utf-8><h1>Hello</h1>", encoding="utf-8")
    check = {"expect": [{"kind": "visible", "target": {"role": "heading", "name": "Hello"}}]}
    contract = Contract(
        id="greets",
        goal="Greets the visitor",
        criteria=[AcceptanceCriterion(id="hello", description="Says hello", check=check)],
    )
    ContractStore(app).save(contract.approved_by("test"))
    wrong = root / "greeter" / "bugs" / "wrong-greeting"
    wrong.mkdir(parents=True)
    (wrong / "page.html").write_text("<!doctype html><meta charset=utf-8><h1>Goodbye</h1>", encoding="utf-8")
    (wrong / "BUG.md").write_text("Expected to be caught by: `hello`\n", encoding="utf-8")
    crash = root / "greeter" / "bugs" / "server-crashes"
    crash.mkdir(parents=True)
    (crash / "server.js").write_text("process.exit(1);\n", encoding="utf-8")
    return root


@pytest.mark.skipif(shutil.which("node") is None or shutil.which("npm") is None, reason="needs node and npm")
async def test_a_dev_server_app_is_started_for_real_and_a_crash_is_flagged_not_missed(tmp_path: Path) -> None:
    report = await run_bench(_node_fixture(tmp_path), repeats=1)
    [score] = report.apps
    assert score.valid, score.invalid_reason
    runs = {r.name: r for r in report.runs}
    assert runs["wrong-greeting"].bug_verdict == "caught"
    assert runs["server-crashes"].bug_verdict == "flagged"  # the gate blocks it, without a proof
    assert "exited with code 1" in runs["server-crashes"].error
    assert (score.caught, score.flagged, score.missed, score.false_failure_runs) == (1, 1, 0, 0)


def test_a_clean_run_that_errors_counts_as_a_false_failure() -> None:
    from contexer.bench.runner import AppScore, VariantRun, _score

    score = AppScore(app="x")
    _score(score, VariantRun(app="x", kind="benign", name="b", outcome="error", error="app did not start"))
    assert (score.clean_runs, score.false_failure_runs) == (1, 1)
