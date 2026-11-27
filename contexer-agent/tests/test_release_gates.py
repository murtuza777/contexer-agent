"""A release is refused unless its gates hold: the decision is code with tests, and the workflow calls it.

The workflow itself cannot be run from a test. What is checked here is the
script it calls, and that the file parses with the job graph that makes a
failed gate stop the publish.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from contexer.bench.gates import benchmark_gate, ci_gate, main
from contexer.bench.runner import AppScore, BenchReport

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"


def _report(**changes: Any) -> BenchReport:
    """A benchmark in which everything held, with ``changes`` applied to its one app."""
    app = AppScore(app="todo", bugs=6, caught=6, clean_runs=8, gating_checks_on_clean_runs=56).model_copy(update=changes)
    return BenchReport(started_at="2026-11-26T00:00:00+00:00", repeats=2, apps=[app])


def _ci(**changes: Any) -> dict[str, Any]:
    run = {"event": "push", "status": "completed", "conclusion": "success", "createdAt": "2026-11-26T10:00:00Z", "url": "https://example.test/runs/1"}
    return {**run, **changes}


def test_the_benchmark_gate_holds_when_every_bug_is_caught_and_no_clean_run_fails() -> None:
    assert benchmark_gate(_report()) == []


@pytest.mark.parametrize(
    ("changes", "says"),
    [
        ({"caught": 5, "missed": 1, "missed_bugs": ["delete-wrong-task"]}, "missed: todo/delete-wrong-task"),
        # Blocked without proof is not caught: the roadmap's gate is "every seeded bug caught".
        ({"caught": 5, "flagged": 1}, "5 of 6 seeded bugs were caught"),
        ({"false_failure_runs": 1, "false_failing_checks": 2}, "1 of 8 runs of correct or benign code failed"),
        ({"valid": False, "invalid_reason": "contract fails on the good app"}, "todo was not scored"),
    ],
)
def test_a_missed_or_flagged_bug_a_false_failure_or_an_app_that_was_not_scored_breaks_it(changes: dict[str, Any], says: str) -> None:
    reasons = benchmark_gate(_report(**changes))
    assert reasons and says in " ".join(reasons)


def test_a_benchmark_that_scored_nothing_does_not_pass() -> None:
    empty = BenchReport(started_at="2026-11-26T00:00:00+00:00", repeats=2)
    assert "no seeded bug was scored" in " ".join(benchmark_gate(empty))
    assert benchmark_gate(_report(clean_runs=0, gating_checks_on_clean_runs=0))
    # Another suite's report is not the gate benchmark, whatever it counts.
    assert "tester suite" in " ".join(benchmark_gate(_report().model_copy(update={"suite": "tester"})))


def test_the_ci_gate_wants_the_latest_run_a_push_started_on_the_commit_to_have_passed() -> None:
    assert ci_gate([_ci()]) == []
    # An older failure that was followed by a pass, and runs other events started, do not decide.
    assert ci_gate([_ci(conclusion="failure", createdAt="2026-11-26T09:00:00Z"), _ci(), _ci(event="schedule", conclusion="failure", createdAt="2026-11-26T11:00:00Z")]) == []

    assert "no run" in " ".join(ci_gate([]))
    assert "no run" in " ".join(ci_gate([_ci(event="pull_request")]))
    assert "failure" in " ".join(ci_gate([_ci(), _ci(conclusion="failure", createdAt="2026-11-26T12:00:00Z")]))
    assert "cancelled" in " ".join(ci_gate([_ci(conclusion="cancelled")]))
    still = ci_gate([_ci(status="in_progress", conclusion="")])
    assert "has not finished" in " ".join(still) and "https://example.test/runs/1" in " ".join(still)


def _files(tmp_path: Path, report: BenchReport, runs: list[dict[str, Any]]) -> tuple[Path, Path]:
    bench, ci = tmp_path / "bench-results.json", tmp_path / "ci-runs.json"
    bench.write_text(report.model_dump_json(), encoding="utf-8")
    ci.write_text(json.dumps(runs), encoding="utf-8")
    return bench, ci


def test_the_script_exits_zero_when_every_gate_holds_and_writes_what_it_checked(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bench, ci = _files(tmp_path, _report(), [_ci()])
    summary = tmp_path / "release-gates.md"

    assert main(["--bench", str(bench), "--ci", str(ci), "--summary", str(summary)]) == 0

    page = summary.read_text(encoding="utf-8")
    assert "seeded bugs caught 6/6, 100% (95% interval 61% to 100%)" in page
    assert "| Gate benchmark" in page and "| holds |" in page and "does not hold" not in page
    assert "Not checked by the workflow" in page and "repair" in page  # the gates that need a model are named
    assert "hold" in capsys.readouterr().out


def test_the_script_exits_non_zero_when_the_benchmark_missed_a_bug(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bench, ci = _files(tmp_path, _report(caught=5, missed=1, missed_bugs=["delete-wrong-task"]), [_ci()])
    summary = tmp_path / "release-gates.md"

    assert main(["--bench", str(bench), "--ci", str(ci), "--summary", str(summary)]) == 1

    assert "todo/delete-wrong-task" in capsys.readouterr().out
    assert "does not hold" in summary.read_text(encoding="utf-8")  # written either way, for the person who looks


def test_the_script_exits_non_zero_when_ci_did_not_pass_or_a_file_is_missing(tmp_path: Path) -> None:
    bench, ci = _files(tmp_path, _report(), [_ci(conclusion="failure")])
    assert main(["--bench", str(bench), "--ci", str(ci)]) == 1
    # A benchmark that crashed wrote no report, and a query that failed wrote no runs: neither is a pass.
    assert main(["--bench", str(tmp_path / "none.json"), "--ci", str(ci)]) == 1
    ci.write_text(json.dumps([_ci()]), encoding="utf-8")
    assert main(["--bench", str(bench), "--ci", str(tmp_path / "none.json")]) == 1
    bench.write_text("{cut off", encoding="utf-8")
    assert main(["--bench", str(bench), "--ci", str(ci)]) == 1


def test_the_workflow_can_run_it_as_a_module(tmp_path: Path) -> None:
    src = str(Path(__file__).resolve().parents[1] / "src")
    env = {**os.environ, "PYTHONPATH": src}

    def run(report: BenchReport) -> int:
        bench, ci = _files(tmp_path, report, [_ci()])
        return subprocess.run([sys.executable, "-m", "contexer.bench.gates", "--bench", str(bench), "--ci", str(ci)], env=env, capture_output=True).returncode

    assert run(_report()) == 0
    assert run(_report(false_failure_runs=1)) == 1


# --- the workflow file -------------------------------------------------------


def _workflow(name: str) -> dict[str, Any]:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _needs(job: dict[str, Any]) -> list[str]:
    needs = job.get("needs", [])
    return [needs] if isinstance(needs, str) else list(needs)


def _commands(job: dict[str, Any]) -> str:
    return "\n".join(str(step.get("run", "")) for step in job["steps"])


def test_publishing_waits_for_the_gate_and_nothing_lets_it_run_after_a_failure() -> None:
    jobs = _workflow("release.yml")["jobs"]
    assert {"build", "gate", "publish", "release"} <= set(jobs)

    assert {"build", "gate"} <= set(_needs(jobs["publish"]))
    assert {"gate", "publish"} <= set(_needs(jobs["release"]))
    for name in ("publish", "release"):
        condition = str(jobs[name].get("if", ""))
        # Without a status function a job is skipped when one it needs failed or was skipped.
        assert "refs/tags/v" in condition, name
        assert not any(word in condition for word in ("always()", "failure()", "cancelled()")), name

    gate = jobs["gate"]
    assert "continue-on-error" not in gate
    assert not any("continue-on-error" in step for step in gate["steps"])
    commands = _commands(gate)
    assert "contexer bench" in commands and "--out bench-results.json" in commands
    assert "python -m contexer.bench.gates" in commands
    assert "|| true" not in commands and "set +e" not in commands


def test_the_gate_runs_for_a_tag_and_the_release_gets_the_benchmark_results() -> None:
    jobs = _workflow("release.yml")["jobs"]
    assert "refs/tags/v" in str(jobs["gate"].get("if", ""))
    uploads = [step for step in jobs["gate"]["steps"] if str(step.get("uses", "")).startswith("actions/upload-artifact@")]
    assert uploads and "bench-results.json" in str(uploads[0]["with"]["path"])
    release = _commands(jobs["release"])
    assert "gh release" in release and "bench-results.json" in release
    assert jobs["release"]["permissions"] == {"contents": "write"}


def test_the_release_stores_no_secret_and_uses_the_action_versions_ci_uses() -> None:
    text = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    assert "secrets." not in text  # PyPI is reached by trusted publishing; the GitHub token is the run's own

    def versions(name: str) -> dict[str, set[str]]:
        found: dict[str, set[str]] = {}
        for job in _workflow(name)["jobs"].values():
            for step in job["steps"]:
                if "uses" in step:
                    action, _, version = step["uses"].partition("@")
                    found.setdefault(action, set()).add(version)
        return found

    ci, release = versions("ci.yml"), versions("release.yml")
    for action, used in release.items():
        assert len(used) == 1, action
        assert action not in ci or used == ci[action], f"{action}: release.yml has {used}, ci.yml has {ci[action]}"
