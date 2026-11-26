"""The release gates that code can check (docs/production/roadmap.md, section 8).

``python -m contexer.bench.gates --bench bench-results.json --ci ci-runs.json``
exits 0 only when every gate it was given holds. The release workflow runs it
on the tagged commit and publishes only after it.

Two gates are decided here:

* the gate benchmark: every seeded bug caught by proof, no run of correct or
  benign code failed, every app scored;
* CI: the latest run of the CI workflow that a push started on the commit has
  passed. That run holds the tests, lint and types on three systems and the
  clean install.

The gates that need a model (the repair, reviewer and tester suites) are not
checked here: a workflow with no key cannot run them. They are listed in the
summary so nobody reads their absence as a pass.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from contexer.bench.runner import BenchReport
from contexer.bench.stats import sentence

NOT_CHECKED = (
    "Not checked by the workflow, because they need a model key: the repair suite, the reviewer suite with a model, "
    "and the tester suite on the held-out app. Run them by hand before tagging (bench/README.md, \"Release gates\")."
)


def benchmark_gate(report: BenchReport) -> list[str]:
    """Why the gate benchmark does not hold. Empty when it does."""
    if report.suite != "gate":
        return [f"the report is from the {report.suite} suite, not the gate benchmark"]
    reasons = [f"{app.app} was not scored: {app.invalid_reason}" for app in report.apps if not app.valid]
    total = report.totals()
    if total.bugs == 0:
        reasons.append("no seeded bug was scored")
    elif total.caught != total.bugs:
        # Flagged (blocked without proof) is not caught: the gate is "every seeded bug caught".
        detail = f"; missed: {', '.join(total.missed_bugs)}" if total.missed_bugs else ""
        detail += f"; {total.flagged} blocked without proof" if total.flagged else ""
        reasons.append(f"{total.caught} of {total.bugs} seeded bugs were caught{detail}")
    if total.clean_runs == 0:
        reasons.append("no run of correct or benign code was scored")
    elif total.false_failure_runs:
        reasons.append(f"{total.false_failure_runs} of {total.clean_runs} runs of correct or benign code failed")
    return reasons


def ci_gate(runs: list[dict[str, Any]]) -> list[str]:
    """Why CI does not hold on the commit. ``runs`` is ``gh run list --workflow ci.yml --commit SHA --json ...``.

    Only runs a push started count: they are the ones with every job, on the commit itself. A scheduled run
    adds the weekly benchmarks on other systems, and a pull request's run is on another commit.
    """
    pushed = [run for run in runs if run.get("event") == "push"]
    if not pushed:
        return ["CI has no run that a push started on this commit: tag a commit that was pushed to main"]
    latest = max(pushed, key=lambda run: str(run.get("createdAt", "")))
    where = f" ({latest['url']})" if latest.get("url") else ""
    if latest.get("status") != "completed":
        return [f"CI has not finished on this commit{where}: run this job again when it has"]
    if latest.get("conclusion") != "success":
        return [f"CI ended with {latest.get('conclusion') or 'no result'} on this commit{where}"]
    return []


def summary_markdown(gates: list[tuple[str, list[str]]], report: BenchReport | None) -> str:
    """What was checked and what it showed, for the release notes."""
    lines = ["## Release gates", "", "| Gate | Result | Why |", "| --- | --- | --- |"]
    lines += [f"| {name} | {'does not hold' if reasons else 'holds'} | {'; '.join(reasons)} |" for name, reasons in gates]
    if report is not None:
        lines += ["", f"Gate benchmark, {report.started_at[:10]}, on the workflow's Ubuntu runner: {sentence(report.rates())}."]
    lines += ["", NOT_CHECKED]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m contexer.bench.gates", description="Exit 0 only when the release gates hold.")
    parser.add_argument("--bench", type=Path, required=True, help="The report `contexer bench --out` wrote.")
    parser.add_argument("--ci", type=Path, help="The CI runs on the commit, as `gh run list --json` wrote them.")
    parser.add_argument("--summary", type=Path, help="Write what was checked as Markdown.")
    args = parser.parse_args(argv)

    report: BenchReport | None = None
    try:
        report = BenchReport.model_validate_json(args.bench.read_text(encoding="utf-8"))
        bench_reasons = benchmark_gate(report)
    except (OSError, ValueError) as exc:  # a benchmark that crashed wrote nothing: that is not a pass
        bench_reasons = [f"no benchmark report could be read from {args.bench}: {type(exc).__name__}"]
    gates = [("Gate benchmark: every seeded bug caught, no false failure", bench_reasons)]
    if args.ci is not None:
        try:
            runs = json.loads(args.ci.read_text(encoding="utf-8"))
            ci_reasons = ci_gate(runs) if isinstance(runs, list) else ["the list of CI runs is not a list"]
        except (OSError, ValueError) as exc:
            ci_reasons = [f"the CI runs could not be read from {args.ci}: {type(exc).__name__}"]
        gates.append(("CI passed on this commit: tests, lint, types and the clean install on three systems", ci_reasons))

    for name, reasons in gates:
        print(f"{'FAILED' if reasons else 'holds '}  {name}")
        for reason in reasons:
            print(f"        {reason}")
    if args.summary is not None:
        args.summary.write_text(summary_markdown(gates, report), encoding="utf-8", newline="\n")
    failed = any(reasons for _, reasons in gates)
    print("The release gates do not hold: nothing is published." if failed else "The release gates hold.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
