"""The tester benchmark: findings count only as far as a replay by code confirms them."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from contexer.appserver import RunningApp
from contexer.bench.tester import (
    TESTER_AGENTS,
    Exploration,
    Finding,
    StubTester,
    results_markdown,
    run_tester_bench,
)
from contexer.cli import app as cli
from contexer.contract import ContractStore
from contexer.verification.checks import Check

pytestmark = pytest.mark.anyio

FIXTURE = Path(__file__).resolve().parents[1] / "bench" / "fixtures" / "todo"
BUG = "count-ignores-done"


def _mini_fixture(root: Path, benign: tuple[str, ...] = ()) -> Path:
    app = root / "todo"
    shutil.copytree(FIXTURE / "app", app / "app", ignore=shutil.ignore_patterns("runs"))
    shutil.copytree(FIXTURE / "bugs" / BUG, app / "bugs" / BUG)
    for name in benign:
        shutil.copytree(FIXTURE / "benign" / name, app / "benign" / name)
    return root


def _contract_check(criterion_id: str) -> Check:
    contract = ContractStore(FIXTURE / "app").load("todo-basics")
    check = next(c.check for c in contract.criteria if c.id == criterion_id)
    assert check is not None
    return check


class ScriptedTester:
    """Reports the same findings on every app, and records what it was given."""

    name = "scripted"

    def __init__(self, *findings: Finding, steps: int = 4, cost_usd: float | None = None) -> None:
        self.findings = list(findings)
        self.steps = steps
        self.cost_usd = cost_usd
        self.goals: list[str] = []
        self.saw_contract: list[bool] = []

    async def explore(self, goal: str, app: RunningApp, project_dir: Path) -> Exploration:
        self.goals.append(goal)
        self.saw_contract.append((project_dir / ".contexer" / "contracts").exists())
        assert app.url.startswith("http")
        return Exploration(findings=self.findings, steps=self.steps, cost_usd=self.cost_usd)


# Completing a task should lower the remaining count: true on the correct app, false with the seeded bug.
REAL = Finding(title="Completing a task does not lower the count", check=_contract_check("complete-decrements"))
# The agent expects something the app was never meant to do.
WRONG = Finding(
    title="The page should say 'All done!'",
    check=Check.model_validate({"expect": [{"kind": "visible", "target": {"text": "All done!"}}]}),
)
# The agent claims a bug, but the behaviour it describes holds everywhere.
HOLDS = Finding(title="Adding a task does not show it", check=_contract_check("add-shows-task"))


async def test_the_stub_agent_completes_with_nothing_found_and_no_false_alarms(tmp_path: Path) -> None:
    report = await run_tester_bench(_mini_fixture(tmp_path, benign=("restyle",)), StubTester())

    [score] = report.apps
    assert report.agent == "stub"
    assert (score.bugs, score.found, score.missed_bugs) == (1, 0, [BUG])
    assert (score.clean_runs, score.false_alarms, score.false_alarm_runs, score.unconfirmed) == (2, 0, 0, 0)
    assert (score.errors, score.steps, score.cost_usd) == (0, 0, None)
    assert [(r.kind, r.name) for r in report.runs] == [("good", "good"), ("benign", "restyle"), ("bug", BUG)]


async def test_a_finding_that_fails_on_the_bug_and_passes_on_the_correct_app_is_a_found_bug(tmp_path: Path) -> None:
    agent = ScriptedTester(REAL, steps=4, cost_usd=0.01)
    report = await run_tester_bench(_mini_fixture(tmp_path), agent)

    [score] = report.apps
    assert (score.bugs, score.found, score.missed_bugs) == (1, 1, [])
    # On the correct app the same claim did not reproduce: it is dropped, not a false alarm.
    assert (score.clean_runs, score.false_alarms, score.unconfirmed) == (1, 0, 1)
    assert score.steps == 8 and score.cost_usd == pytest.approx(0.02)
    bug_run = next(r for r in report.runs if r.kind == "bug")
    assert bug_run.found is True and bug_run.real == [REAL.title]


async def test_the_agent_is_given_the_goal_and_never_the_contract(tmp_path: Path) -> None:
    agent = ScriptedTester()
    await run_tester_bench(_mini_fixture(tmp_path), agent)

    assert set(agent.goals) == {"Users can add, complete and delete tasks, and the remaining count stays correct"}
    assert agent.saw_contract == [False, False]


async def test_a_wrong_expectation_is_a_false_alarm_on_correct_code_and_rejected_on_a_bug(tmp_path: Path) -> None:
    report = await run_tester_bench(_mini_fixture(tmp_path), ScriptedTester(WRONG))

    [score] = report.apps
    # It "reproduces" on the buggy app too, but the correct app fails it as well: the agent is wrong.
    assert (score.bugs, score.found) == (1, 0)
    # On correct code it is a false alarm. On the bug it is rejected: the two are counted apart,
    # because the second is often the right bug described with the wrong words.
    assert (score.false_alarms, score.false_alarm_runs, score.clean_runs, score.rejected) == (1, 1, 1, 1)
    bug_run = next(r for r in report.runs if r.kind == "bug")
    assert bug_run.found is False and bug_run.rejected == [WRONG.title] and bug_run.false_alarms == []


async def test_a_claim_that_does_not_reproduce_is_unconfirmed(tmp_path: Path) -> None:
    report = await run_tester_bench(_mini_fixture(tmp_path), ScriptedTester(HOLDS))

    [score] = report.apps
    assert (score.found, score.false_alarms, score.unconfirmed) == (0, 0, 2)


async def test_an_app_that_does_not_start_is_reported_and_not_scored(tmp_path: Path) -> None:
    root = _mini_fixture(tmp_path)
    (root / "todo" / "bugs" / BUG / "index.html").unlink(missing_ok=True)
    shutil.rmtree(root / "todo" / "app")
    broken = root / "todo" / "app"
    broken.mkdir()
    (broken / "package.json").write_text('{"name": "x", "scripts": {}}', encoding="utf-8")

    report = await run_tester_bench(root, StubTester())

    [score] = report.apps
    assert score.errors == len(report.runs) > 0
    assert (score.bugs, score.clean_runs) == (0, 0)
    assert all(r.error.startswith("the app did not start") for r in report.runs)


async def test_the_results_page_states_the_numbers(tmp_path: Path) -> None:
    report = await run_tester_bench(_mini_fixture(tmp_path), ScriptedTester(REAL, cost_usd=0.01))
    page = results_markdown(report)

    assert "# Tester benchmark: `scripted`" in page
    assert "| todo | 1 | 1 | 0 | 0 / 1 | 0 | 1 | 8 | 0 / 0 | $0.02 |" in page
    assert "| **total** | 1 | 1 | 0 | 0 / 1 | 0 | 1 | 8 | 0 / 0 | $0.02 |" in page


def test_the_command_runs_the_suite_with_the_stub_agent_and_writes_the_results(tmp_path: Path) -> None:
    bench = tmp_path / "bench"
    _mini_fixture(bench / "fixtures")
    (bench / "RESULTS.md").write_text("# Benchmark results\n", encoding="utf-8")
    out = tmp_path / "report.json"

    result = CliRunner().invoke(
        cli, ["bench", "--suite", "tester", "--agent", "stub", "--fixtures", str(bench / "fixtures"), "--out", str(out)]
    )

    assert result.exit_code == 0, result.output
    assert "0 of 1 seeded bugs found" in result.output and "0 false alarms" in result.output
    assert '"agent": "stub"' in out.read_text(encoding="utf-8")
    page = (bench / "tester-results" / "stub.md").read_text(encoding="utf-8")
    assert "| **total** | 1 | 0 | 0 | 0 / 1 | 0 | 0 | 0 | 0 / 0 | not reported |" in page
    assert "Not found: `todo/count-ignores-done`." in page


def test_the_command_refuses_an_agent_it_does_not_have_and_a_mix_of_suites(tmp_path: Path) -> None:
    fixtures = str(_mini_fixture(tmp_path))
    unknown = CliRunner().invoke(cli, ["bench", "--suite", "tester", "--agent", "oracle", "--fixtures", fixtures])
    assert unknown.exit_code == 2 and "stub" in unknown.output

    mixed = CliRunner().invoke(cli, ["bench", "--suite", "tester", "--live", "--fixtures", fixtures])
    assert mixed.exit_code == 2

    wrong_suite = CliRunner().invoke(cli, ["bench", "--suite", "nope", "--fixtures", fixtures])
    assert wrong_suite.exit_code == 2

    assert list(TESTER_AGENTS) == ["stub", "tester"]


async def test_the_tester_agent_is_measured_through_the_same_replays(tmp_path: Path) -> None:
    """The real agent loop and browser tools, on a scripted model: its recorded bug is found, by replay."""
    from contexer.bench.tester import LiveTester
    from tests.fakes import ScriptedChatModel, calls, submit

    def script() -> list:
        return [
            calls(
                ("fill", {"target": {"placeholder": "What needs doing?"}, "value": "Buy milk"}),
                ("click", {"target": {"role": "button", "name": "Add"}}),
                ("check", {"target": {"role": "checkbox", "name": "Complete Buy milk"}}),
                ("expect", {"kind": "text", "target": {"test_id": "remaining-count"}, "equals": "0 left"}),
            ),
            # On the correct app e1 passes, so recording it as a bug is refused and nothing is reported.
            calls(("record_finding", {"kind": "bug", "title": "The count ignores completed tasks", "observation": "e1",
                   "violates": "the remaining count stays correct"})),
            submit(summary="Done."),
        ]

    model = ScriptedChatModel(*script(), *script())  # the correct app, then the bug
    tester = LiveTester(model=model)
    tester.keep_dir = tmp_path / "transcripts"
    report = await run_tester_bench(_mini_fixture(tmp_path / "fixtures"), tester)

    [score] = report.apps
    assert (score.bugs, score.found, score.false_alarms, score.unconfirmed) == (1, 1, 0, 0)
    assert score.steps == 6
    assert (score.tokens_in, score.tokens_out) == (60, 30)
    assert report.model == "model 'scripted-model'"
    bug_run = next(r for r in report.runs if r.kind == "bug")
    assert bug_run.real == ["The count ignores completed tasks"] and bug_run.error == ""
    # The transcripts outlive the working copy, so a miss can be diagnosed.
    kept = sorted(p.name for p in (tmp_path / "transcripts").iterdir())
    assert kept == ["todo-bug-count-ignores-done-1.jsonl", "todo-good-good-1.jsonl"]


async def test_an_agent_that_crashes_on_one_variant_does_not_end_the_suite(tmp_path: Path) -> None:
    """A dropped connection to one app took the whole live benchmark down; one run's failure is one run's."""

    class Crashing:
        name = "crashing"

        def __init__(self) -> None:
            self.calls = 0

        async def explore(self, goal: str, app: RunningApp, project_dir: Path) -> Exploration:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("Page.goto: net::ERR_CONNECTION_REFUSED at http://127.0.0.1:51504/")
            return Exploration(steps=3)

    agent = Crashing()
    report = await run_tester_bench(_mini_fixture(tmp_path), agent)

    assert agent.calls == 2
    [score] = report.apps
    crashed, completed = report.runs
    assert crashed.error.startswith("the tester failed: RuntimeError: Page.goto")
    assert (score.errors, score.clean_runs, score.bugs, score.steps) == (1, 0, 1, 3)
    assert "1 run(s) were not scored" in results_markdown(report)


async def test_the_benchmark_measures_the_tester_together_with_its_challenger(tmp_path: Path) -> None:
    """What `contexer test` would show is what is scored: a finding the Challenger sets aside is not reported."""
    from contexer.bench.tester import LiveTester
    from tests.fakes import AgentScript, calls, submit

    explore = calls(
        ("fill", {"target": {"placeholder": "What needs doing?"}, "value": "Buy milk"}),
        ("click", {"target": {"role": "button", "name": "Add"}}),
        ("check", {"target": {"role": "checkbox", "name": "Complete Buy milk"}}),
        ("expect", {"kind": "text", "target": {"test_id": "remaining-count"}, "equals": "0 left"}),
    )
    report_bug = calls(("record_finding", {"kind": "bug", "title": "The count ignores completed tasks", "observation": "e1",
                                           "violates": "the remaining count stays correct"}))  # fmt: skip
    model = AgentScript(
        tester=[explore, report_bug, submit(summary="x"), explore, report_bug, submit(summary="x")],
        challenger=[submit(verdicts=[{"finding": 1, "verdict": "tester_error", "reason": "Set aside for the test."}])],
    )
    report = await run_tester_bench(_mini_fixture(tmp_path), LiveTester(model=model))

    [score] = report.apps
    # On the correct app the bug is refused when recorded; on the bug variant it is recorded and then set aside.
    assert (score.bugs, score.found, score.false_alarms) == (1, 0, 0)
    assert len(model.seen["challenger"]) == 1
    bug_run = next(r for r in report.runs if r.kind == "bug")
    assert bug_run.findings == 0 and bug_run.set_aside == 1


async def test_a_finding_the_app_explained_is_not_scored_as_a_bug_or_a_false_alarm(tmp_path: Path) -> None:
    from contexer.bench.tester import LiveTester
    from tests.fakes import AgentScript, calls, submit

    fixtures = Path(__file__).resolve().parents[1] / "bench" / "fixtures" / "bookings"
    shutil.copytree(fixtures / "app", tmp_path / "bookings" / "app", ignore=shutil.ignore_patterns("runs"))
    script = [
        calls(
            ("fill", {"target": {"label": "Your name"}, "value": "Bob"}),
            ("click", {"target": {"role": "button", "name": "Book 09:00"}}),
            ("click", {"target": {"role": "button", "name": "Book 10:00"}}),
            ("expect", {"kind": "text", "target": {"test_id": "slot-1000"}, "contains": "Booked by Bob"}),
        ),
        calls(("record_finding", {"kind": "bug", "title": "Booking a second slot fails", "observation": "e1",
                                  "violates": "book a free time slot with their name"})),  # fmt: skip
        submit(summary="x"),
    ]
    model = AgentScript(tester=script)

    report = await run_tester_bench(tmp_path, LiveTester(model=model))

    [score] = report.apps
    [run] = report.runs
    assert (score.clean_runs, score.false_alarms, score.false_alarm_runs) == (1, 0, 0)
    assert (run.findings, run.explained) == (0, 1) and "challenger" not in model.seen
