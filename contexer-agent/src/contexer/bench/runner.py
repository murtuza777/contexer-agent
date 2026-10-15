"""Seeded-bug benchmark: how often the gate catches real bugs, and how often it
fails good code.

Fixture layout::

    <fixtures>/<app>/app/                         the good version, with
                     app/.contexer/contracts/*.json approved contracts
    <fixtures>/<app>/bugs/<id>/   file overlays introducing one bug (+ BUG.md)
    <fixtures>/<app>/benign/<id>/ overlays that change code but not behaviour

Each variant is materialised in a temporary directory, served, and verified
with the app's approved contracts and no LLM. Scoring:

* good and benign runs: any gating verdict other than ``verified`` is a false
  failure (refuted is a false alarm, unverified is noise that blocks a merge);
* bug runs: **caught** when a proven check is refuted, **flagged** when a check
  is only unverified, **missed** when everything verifies.

Validity rule (from SWE-Lancer): a contract that does not pass on the good app
is broken, and its app is reported as invalid instead of being scored.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal, Optional

from pydantic import BaseModel, Field

from contexer.appserver import RunningApp
from contexer.contract import Contract, ContractStore
from contexer.evidence.rundir import RunDir
from contexer.gate.models import RunResult
from contexer.gate.session import VerificationSession
from contexer.llm.base import LLMProvider
from contexer.verification.runner import CheckRunner
from contexer.verification.verifier import Verifier
from contexer.workflow.app_server import StaticAppServer
from contexer.workflow.criteria import GoalAnalyzer
from contexer.workflow.inspector import RepositoryInspector

VariantKind = Literal["good", "benign", "bug"]
BugVerdict = Literal["caught", "flagged", "missed"]

_IGNORED = shutil.ignore_patterns(".contexer", "node_modules", ".git")


@dataclass(frozen=True)
class Variant:
    app: str
    kind: VariantKind
    name: str
    overlay: Optional[Path] = None
    expected_catcher: Optional[str] = None


@dataclass
class FixtureApp:
    name: str
    root: Path
    contracts: list[Contract]
    bugs: list[Variant] = field(default_factory=list)
    benign: list[Variant] = field(default_factory=list)

    @property
    def app_dir(self) -> Path:
        return self.root / "app"


class VariantRun(BaseModel):
    app: str
    kind: VariantKind
    name: str
    repeat: int = 0
    outcome: str
    verified: int = 0
    refuted: list[str] = Field(default_factory=list)
    unverified: list[str] = Field(default_factory=list)
    bug_verdict: Optional[BugVerdict] = None
    expected_catcher: Optional[str] = None
    caught_by_expected: Optional[bool] = None
    duration_seconds: float = 0.0


class CompileStats(BaseModel):
    """How a model-compiled contract fared before scoring (live mode)."""

    criteria: int = 0
    executable: int = 0
    failed_on_good: list[str] = Field(default_factory=list)
    seconds: float = 0.0


class AppScore(BaseModel):
    app: str
    valid: bool = True
    invalid_reason: str = ""
    compiled: Optional[CompileStats] = None
    clean_runs: int = 0
    false_failure_runs: int = 0
    gating_checks_on_clean_runs: int = 0
    false_failing_checks: int = 0
    bugs: int = 0
    caught: int = 0
    flagged: int = 0
    missed: int = 0
    missed_bugs: list[str] = Field(default_factory=list)


class BenchReport(BaseModel):
    started_at: str
    duration_seconds: float = 0.0
    repeats: int
    apps: list[AppScore] = Field(default_factory=list)
    runs: list[VariantRun] = Field(default_factory=list)

    def totals(self) -> AppScore:
        total = AppScore(app="total")
        for a in self.apps:
            if not a.valid:
                continue
            for key in (
                "clean_runs",
                "false_failure_runs",
                "gating_checks_on_clean_runs",
                "false_failing_checks",
                "bugs",
                "caught",
                "flagged",
                "missed",
            ):
                setattr(total, key, getattr(total, key) + getattr(a, key))
            total.missed_bugs.extend(f"{a.app}/{b}" for b in a.missed_bugs)
        return total


def discover(fixtures_root: Path, only: Optional[list[str]] = None) -> list[FixtureApp]:
    apps: list[FixtureApp] = []
    for root in sorted(p for p in fixtures_root.iterdir() if (p / "app").is_dir()):
        if only and root.name not in only:
            continue
        contracts = [c for c in ContractStore(root / "app").list()]
        app = FixtureApp(name=root.name, root=root, contracts=contracts)
        for kind, folder in (("bug", "bugs"), ("benign", "benign")):
            base = root / folder
            if not base.is_dir():
                continue
            for d in sorted(p for p in base.iterdir() if p.is_dir()):
                catcher = _expected_catcher(d / "BUG.md") if kind == "bug" else None
                variant = Variant(app=root.name, kind=kind, name=d.name, overlay=d, expected_catcher=catcher)  # type: ignore[arg-type]
                (app.bugs if kind == "bug" else app.benign).append(variant)
        apps.append(app)
    return apps


async def run_bench(
    fixtures_root: Path,
    *,
    repeats: int = 3,
    only: Optional[list[str]] = None,
    on_run: Optional[Callable[[VariantRun], None]] = None,
    live_llm: Optional[LLMProvider] = None,
    on_compiled: Optional[Callable[[str, CompileStats], None]] = None,
) -> BenchReport:
    """Score every fixture app.

    With ``live_llm``, each app's contract is replaced by one the model
    compiles from the same one-line goal, grounded in the good app's UI.
    Compiled checks that fail on the good app are dropped and counted (a
    reviewer would reject them), and the rest are scored like hand-written
    contracts. This measures the compiler, not just the runner.
    """
    from contexer.contract.models import utc_now

    started = time.monotonic()
    report = BenchReport(started_at=utc_now(), repeats=repeats)
    for app in discover(fixtures_root, only):
        score = AppScore(app=app.name if live_llm is None else f"{app.name} (compiled)")
        report.apps.append(score)
        unapproved = [c.id for c in app.contracts if c.status != "approved"]
        if not app.contracts or unapproved:
            score.valid = False
            score.invalid_reason = "no approved contracts" if not app.contracts else f"not approved: {unapproved}"
            continue
        if live_llm is not None:
            compiled, stats = await _compile_live(app, live_llm)
            score.compiled = stats
            if on_compiled:
                on_compiled(app.name, stats)
            if compiled is None:
                score.valid = False
                score.invalid_reason = "no compiled check passed on the good app"
                continue
            app = FixtureApp(name=app.name, root=app.root, contracts=[compiled], bugs=app.bugs, benign=app.benign)

        good = Variant(app=app.name, kind="good", name="good")
        plan: list[tuple[Variant, int]] = [(good, r) for r in range(repeats)]
        plan += [(v, r) for v in app.benign for r in range(repeats)]
        plan += [(v, 0) for v in app.bugs]

        for variant, repeat in plan:
            run = await _run_variant(app, variant, repeat)
            report.runs.append(run)
            if on_run:
                on_run(run)
            if variant.kind == "good" and repeat == 0 and run.outcome != "pass":
                score.valid = False
                score.invalid_reason = (
                    f"contract fails on the good app (refuted: {run.refuted}, unverified: {run.unverified})"
                )
                break
            _score(score, run)

    report.duration_seconds = time.monotonic() - started
    return report


async def _compile_live(app: FixtureApp, llm: LLMProvider) -> tuple[Optional[Contract], CompileStats]:
    """Compile the app's goal with the model, then keep only checks that pass on the good app."""
    started = time.monotonic()
    goal = app.contracts[0].goal
    stats = CompileStats()
    with tempfile.TemporaryDirectory(prefix=f"contexer-compile-{app.name}-") as tmp:
        work = Path(tmp) / "app"
        shutil.copytree(app.app_dir, work, ignore=_IGNORED)
        run_dir = RunDir.create(work)
        session = VerificationSession(work, run_dir, verifier=Verifier(llm_provider=None, runner=CheckRunner()))
        context = RepositoryInspector().inspect(work)
        with StaticAppServer(work) as server:
            running = RunningApp(url=server.url, kind="static", repo_context=context)
            await session.observe(running)
            drafted = await session.compile(goal, GoalAnalyzer(llm_provider=llm), f"{app.name}-compiled", context)
            stats.criteria = len(drafted.criteria)
            executable = [c for c in drafted.criteria if c.check is not None]
            stats.executable = len(executable)
            candidate = drafted.model_copy(update={"criteria": executable}).approved_by("bench-live")
            result = await session.verify(running, [candidate])
    passing: set[str] = set()
    for outcome in result.contracts:
        for r in outcome.verification.criteria_results if outcome.verification else []:
            if r.proven and r.verdict == "verified":
                passing.add(r.criterion_id)
            elif r.proven:
                stats.failed_on_good.append(r.criterion_id)
    stats.seconds = time.monotonic() - started
    kept = [c for c in executable if c.id in passing]
    if not kept:
        return None, stats
    pruned = drafted.model_copy(update={"criteria": kept}).approved_by("bench-live")
    return pruned, stats


async def _run_variant(app: FixtureApp, variant: Variant, repeat: int) -> VariantRun:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix=f"contexer-bench-{app.name}-") as tmp:
        work = Path(tmp) / "app"
        shutil.copytree(app.app_dir, work, ignore=_IGNORED)
        if variant.overlay is not None:
            for src in variant.overlay.rglob("*"):
                if src.is_file() and src.name not in ("BUG.md", "CHANGE.md"):
                    dest = work / src.relative_to(variant.overlay)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dest)
        run_dir = RunDir.create(work)
        session = VerificationSession(work, run_dir, verifier=Verifier(llm_provider=None, runner=CheckRunner()))
        with StaticAppServer(work) as server:
            result = await session.verify(RunningApp(url=server.url, kind="static"), app.contracts)
    return _summarise(variant, repeat, result, time.monotonic() - started)


def _summarise(variant: Variant, repeat: int, result: RunResult, duration: float) -> VariantRun:
    refuted: list[str] = []
    unverified: list[str] = []
    verified = 0
    for outcome in result.contracts:
        for r in (outcome.verification.criteria_results if outcome.verification else []):
            if not r.proven:
                continue
            if r.verdict == "verified":
                verified += 1
            elif r.verdict == "refuted":
                refuted.append(r.criterion_id)
            else:
                unverified.append(r.criterion_id)

    run = VariantRun(
        app=variant.app,
        kind=variant.kind,
        name=variant.name,
        repeat=repeat,
        outcome=result.decision.outcome,
        verified=verified,
        refuted=refuted,
        unverified=unverified,
        expected_catcher=variant.expected_catcher,
        duration_seconds=duration,
    )
    if variant.kind == "bug":
        run.bug_verdict = "caught" if refuted else ("flagged" if unverified else "missed")
        if variant.expected_catcher:
            run.caught_by_expected = variant.expected_catcher in refuted
    return run


def _score(score: AppScore, run: VariantRun) -> None:
    if run.kind in ("good", "benign"):
        score.clean_runs += 1
        checks = run.verified + len(run.refuted) + len(run.unverified)
        score.gating_checks_on_clean_runs += checks
        bad = len(run.refuted) + len(run.unverified)
        score.false_failing_checks += bad
        if bad:
            score.false_failure_runs += 1
        return
    score.bugs += 1
    if run.bug_verdict == "caught":
        score.caught += 1
    elif run.bug_verdict == "flagged":
        score.flagged += 1
    else:
        score.missed += 1
        score.missed_bugs.append(run.name)


_CATCHER = re.compile(r"caught by:\s*`([^`]+)`", re.IGNORECASE)


def _expected_catcher(bug_md: Path) -> Optional[str]:
    try:
        match = _CATCHER.search(bug_md.read_text(encoding="utf-8"))
    except OSError:
        return None
    return match.group(1) if match else None
