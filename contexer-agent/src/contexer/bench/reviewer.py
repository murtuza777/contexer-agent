"""The reviewer benchmark: does the review flag an issue planted in a diff, and is it quiet on a clean one?

``bench/reviewer/<case>/`` holds ``before/`` and ``after/`` (a few small
files each) and ``case.json`` with the goal of the change. Ten cases have one
planted issue: its file, the categories a note about it may carry, and
whether a scan by code can see it. Ten are clean changes, some of them
written to look suspicious (a key read from the environment, a placeholder
in a README, an error that is logged).

Two numbers are published:

* **flagged**: planted cases with a note on the planted file in one of its
  categories. Where a note points is checked; whether its words are right is
  not, so this is an upper bound.
* **false high-severity notes** on clean diffs. A high note is what turns a
  pull request into a draft, so these are the ones that cost a person time.

With no model only the scan runs (``--agent scan``). It costs nothing and is
the floor: what the model adds is the difference.
"""

from __future__ import annotations

import difflib
import json
import time
from collections.abc import Callable
from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field

from contexer.bench.stats import Rate, sentence
from contexer.crew.reviewer import ReviewNote, review


class Planted(BaseModel):
    file: str
    categories: list[str]
    # True when the scan (no model) is expected to find it.
    scan: bool = False


class ReviewCase(BaseModel):
    name: str
    goal: str = ""
    planted: Planted | None = None
    path: Path


class CaseRun(BaseModel):
    name: str
    repeat: int = 0
    planted: bool
    flagged: bool = False
    # Which source's note flagged it: "scan", "command", "reviewer" or "".
    flagged_by: str = ""
    false_high: int = 0
    notes: list[ReviewNote] = Field(default_factory=list)
    status: str = ""
    seconds: float = 0.0


class ReviewerBenchReport(BaseModel):
    suite: str = "reviewer"
    agent: str = "scan"
    model: str = ""
    # Reviews of each case. The counts below are of reviews.
    repeats: int = 1
    runs: list[CaseRun] = Field(default_factory=list)
    planted: int = 0
    flagged: int = 0
    clean: int = 0
    clean_with_high: int = 0
    false_high_notes: int = 0
    notes_on_clean: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float | None = None
    duration_seconds: float = 0.0

    def rates(self) -> dict[str, Rate]:
        return {
            "planted issues flagged": Rate(self.flagged, self.planted),
            "clean diffs with a false high": Rate(self.clean_with_high, self.clean),
        }


def discover_cases(root: Path, only: list[str] | None = None) -> list[ReviewCase]:
    cases: list[ReviewCase] = []
    for folder in sorted(p for p in Path(root).iterdir() if (p / "case.json").is_file()) if Path(root).is_dir() else []:
        meta = json.loads((folder / "case.json").read_text(encoding="utf-8"))
        cases.append(ReviewCase(name=folder.name, goal=meta.get("goal", ""), planted=meta.get("planted"), path=folder))
    if only:
        known = {c.name for c in cases}
        missing = [name for name in only if name not in known]
        if missing:
            raise ValueError(f"no case named '{missing[0]}' in {root}")
        cases = [c for c in cases if c.name in only]
    return cases


def case_diff(case: ReviewCase) -> str:
    """The change from ``before/`` to ``after/`` as a unified diff, in the shape git writes."""
    before, after = case.path / "before", case.path / "after"
    names = sorted({p.relative_to(side).as_posix() for side in (before, after) for p in side.rglob("*") if p.is_file()})
    parts: list[str] = []
    for name in names:
        old = (before / name).read_text(encoding="utf-8").splitlines() if (before / name).is_file() else None
        new = (after / name).read_text(encoding="utf-8").splitlines() if (after / name).is_file() else None
        if old == new:
            continue
        lines = list(
            difflib.unified_diff(
                old or [],
                new or [],
                fromfile=f"a/{name}" if old is not None else "/dev/null",
                tofile=f"b/{name}" if new is not None else "/dev/null",
                lineterm="",
            )
        )
        parts += [f"diff --git a/{name} b/{name}", *lines]
    return "\n".join(parts) + ("\n" if parts else "")


async def run_reviewer_bench(
    root: Path,
    model: BaseChatModel | None = None,
    *,
    only: list[str] | None = None,
    repeats: int = 1,
    on_case: Callable[[CaseRun], None] | None = None,
) -> ReviewerBenchReport:
    """Review every case, ``repeats`` times over. With no model, only the scan runs."""
    started = time.monotonic()
    report = ReviewerBenchReport(agent="reviewer" if model is not None else "scan", repeats=repeats)
    cases = discover_cases(root, only)
    for repeat, case in ((r, c) for r in range(repeats) for c in cases):
        began = time.monotonic()
        # The cases have no dependencies installed and no scripts: commands are a different question.
        found = await review(case_diff(case), case.path / "after", model, intent=case.goal, run_project_commands=False)
        run = CaseRun(name=case.name, repeat=repeat, planted=case.planted is not None, notes=found.notes, status=found.status)
        if case.planted is not None:
            hits = [n for n in found.notes if n.file == case.planted.file and n.category in case.planted.categories]
            run.flagged = bool(hits)
            run.flagged_by = hits[0].source if hits else ""
        else:
            run.false_high = sum(1 for n in found.notes if n.severity == "high")
        run.seconds = round(time.monotonic() - began, 2)
        report.runs.append(run)
        report.tokens_in += found.tokens_in
        report.tokens_out += found.tokens_out
        if found.cost_usd is not None:
            report.cost_usd = (report.cost_usd or 0.0) + found.cost_usd
        if on_case is not None:
            on_case(run)
    planted = [r for r in report.runs if r.planted]
    clean = [r for r in report.runs if not r.planted]
    report.planted, report.flagged = len(planted), sum(r.flagged for r in planted)
    report.clean = len(clean)
    report.clean_with_high = sum(1 for r in clean if r.false_high)
    report.false_high_notes = sum(r.false_high for r in clean)
    report.notes_on_clean = sum(len(r.notes) for r in clean)
    report.duration_seconds = time.monotonic() - started
    return report


def results_markdown(report: ReviewerBenchReport) -> str:
    by = {"scan": 0, "reviewer": 0, "command": 0}
    for run in report.runs:
        if run.flagged and run.flagged_by in by:
            by[run.flagged_by] += 1
    cost = f"${report.cost_usd:.2f}" if report.cost_usd is not None else "not reported"
    who = f"the scan and the Reviewer agent on {report.model or 'a model'}" if report.agent == "reviewer" else "the scan alone, no model"
    lines = [
        f"# Reviewer benchmark: `{report.agent}`",
        "",
        f"`contexer bench --suite reviewer --agent {report.agent}{f' --repeats {report.repeats}' if report.repeats > 1 else ''}`: {who}. {report.duration_seconds:.0f} s. "
        "Written by the command; do not edit.",
        "",
        "A planted issue is **flagged** when a note points at its file with a fitting category; the note's wording is "
        "not judged. A **false high** is a high-severity note on a clean diff. "
        "Method: [README.md](../README.md#the-reviewer-suite).",
        "",
        "| Planted | Flagged | by the scan | by the model | Clean diffs | Clean diffs with a false high | False high notes | Notes on clean diffs | Tokens in / out | Cost |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        f"| {report.planted} | {report.flagged} | {by['scan']} | {by['reviewer']} | {report.clean} | {report.clean_with_high} | "
        f"{report.false_high_notes} | {report.notes_on_clean} | {report.tokens_in:,} / {report.tokens_out:,} | {cost} |",
        "",
        f"Rates: {sentence(report.rates())}.",
        "",
    ]
    if report.repeats > 1:
        lines += [f"Each case ran {report.repeats} times; the table counts reviews, and a case is named below once.", ""]
    # dict.fromkeys: a case reviewed several times is named once.
    missed = list(dict.fromkeys(r.name for r in report.runs if r.planted and not r.flagged))
    lines.append("Not flagged: " + (", ".join(f"`{name}`" for name in missed) if missed else "none") + ".")
    flagged = list(dict.fromkeys(f"`{r.name}` ({r.flagged_by})" for r in report.runs if r.flagged))
    lines.append("Flagged: " + (", ".join(flagged) if flagged else "none") + ".")
    alarms = list(dict.fromkeys(f"`{r.name}`" for r in report.runs if r.false_high))
    lines.append("Clean diffs with a false high: " + (", ".join(alarms) if alarms else "none") + ".")
    return "\n".join(lines) + "\n"
