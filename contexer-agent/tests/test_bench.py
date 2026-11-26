"""The benchmark scores bugs and clean runs, and refuses invalid contracts."""

import json
import re
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from contexer.bench import discover, run_bench
from contexer.cli import app as cli
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


def test_a_folder_a_stopped_dev_server_is_still_writing_to_does_not_end_the_benchmark(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seen in CI: Next.js was still writing .next/dev/cache when the next variant was laid out."""
    from contexer.bench import runner

    [app] = discover(_mini_fixture(tmp_path))
    real_rmtree = shutil.rmtree
    attempts: list[str] = []

    def busy_once(path: Path, *args: object, **kwargs: object) -> None:
        attempts.append(Path(path).name)
        if attempts.count(".next") == 1 and Path(path).name == ".next":
            raise OSError(39, "Directory not empty", str(path))
        real_rmtree(path, *args, **kwargs)

    with runner.Workspace(app) as workspace:
        work = workspace.materialise()
        (work / ".next" / "dev" / "cache").mkdir(parents=True)
        (work / ".next" / "dev" / "cache" / "x").write_text("busy", encoding="utf-8")
        monkeypatch.setattr(runner.shutil, "rmtree", busy_once)
        monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)

        workspace.materialise()

        assert attempts.count(".next") == 2  # it was tried again
        assert not (work / ".next").exists() and (work / "index.html").is_file()


async def test_repeats_are_for_correct_and_benign_code_and_each_bug_still_runs_once(tmp_path: Path) -> None:
    """The gate benchmark runs on every push: a repeat must not multiply its bug runs."""
    from contexer.bench.stats import Rate

    report = await run_bench(_mini_fixture(tmp_path), repeats=2)
    assert [(r.kind, r.repeat) for r in report.runs] == [("good", 0), ("good", 1), ("bug", 0)]
    checks = report.totals().gating_checks_on_clean_runs
    assert checks > 0 and report.suite == "gate"
    assert report.rates() == {
        "seeded bugs caught": Rate(1, 1),
        "clean runs with a false failure": Rate(0, 2),
        "false-failing checks": Rate(0, checks),
    }


def _words(output: str) -> str:
    """The output without colour codes, the box an error is drawn in, or the line breaks a narrow terminal adds."""
    return " ".join(re.sub(r"\x1b\[[0-9;]*m|[\u2500-\u257f]", "", output).split())


def test_the_command_gives_each_rate_its_interval_and_a_second_run_cannot_be_told_apart(tmp_path: Path) -> None:
    fixtures = str(_mini_fixture(tmp_path / "fixtures"))
    first = tmp_path / "first.json"
    one = CliRunner().invoke(cli, ["bench", "--fixtures", fixtures, "--repeats", "1", "--out", str(first)])
    assert one.exit_code == 0, one.output
    assert "seeded bugs caught 1/1, 100% (95% interval 21% to 100%)" in _words(one.output)
    assert "clean runs with a false failure 0/1, 0% (95% interval 0% to 79%)" in _words(one.output)
    assert json.loads(first.read_text(encoding="utf-8"))["suite"] == "gate"

    two = CliRunner().invoke(cli, ["bench", "--fixtures", fixtures, "--repeats", "1", "--compare", str(first)])
    assert two.exit_code == 0, two.output
    said = _words(two.output)
    assert "Compared with" in said and "was 1/1, 100% (95% interval 21% to 100%)" in said
    assert said.count("cannot be told apart") == 3
    assert "higher (" not in said and "lower (" not in said


def test_a_report_to_compare_with_is_checked_before_anything_runs(tmp_path: Path) -> None:
    fixtures = str(_mini_fixture(tmp_path / "fixtures"))
    other = tmp_path / "tester.json"
    other.write_text(json.dumps({"suite": "tester", "agent": "stub", "started_at": "x", "repeats": 1}), encoding="utf-8")
    wrong_suite = CliRunner().invoke(cli, ["bench", "--fixtures", fixtures, "--compare", str(other)])
    assert wrong_suite.exit_code == 2 and "tester suite" in _words(wrong_suite.output)

    missing = CliRunner().invoke(cli, ["bench", "--fixtures", fixtures, "--compare", str(tmp_path / "none.json")])
    assert missing.exit_code == 2

    (tmp_path / "junk.json").write_text("{not json", encoding="utf-8")
    junk = CliRunner().invoke(cli, ["bench", "--fixtures", fixtures, "--compare", str(tmp_path / "junk.json")])
    assert junk.exit_code == 2
    for refused in (wrong_suite, missing, junk):
        assert "caught" not in refused.output and "clean" not in refused.output  # no variant ran


def test_the_command_exits_non_zero_when_a_seeded_bug_is_missed(tmp_path: Path) -> None:
    """The release workflow leans on this exit code. A restyle laid out as a bug is one no check can catch."""
    root = _mini_fixture(tmp_path / "fixtures", bugs=())
    shutil.copytree(FIXTURE / "benign" / "restyle", root / "todo" / "bugs" / "not-a-bug")
    result = CliRunner().invoke(cli, ["bench", "--fixtures", str(root), "--repeats", "1"])
    assert result.exit_code == 1, result.output
    assert "Missed: todo/not-a-bug" in _words(result.output)
    assert "seeded bugs caught 0/1, 0% (95% interval 0% to 79%)" in _words(result.output)
