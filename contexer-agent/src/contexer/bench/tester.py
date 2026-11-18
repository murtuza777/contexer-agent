"""The tester benchmark: does an agent that explores an app find its real bugs?

``contexer bench --suite tester`` uses the same fixture apps and seeded bugs as
the gate benchmark (:mod:`contexer.bench.runner`), but nobody hands the agent
a contract. For every variant of every app the agent gets the app's one-line
goal and the running app, explores it, and reports findings. Each finding
states the behaviour the agent expected as a check. Code then decides what
the findings are worth, by replaying them in a fresh browser:

* a finding **reproduces** when its check is refuted on the app the agent
  tested. Anything else (the check passes, or cannot run) is **unconfirmed**:
  dropped and counted, never treated as a bug;
* on a seeded bug, a reproduced finding is replayed once more on the correct
  app. Only a check that passes there counts: the bug is **found**. A check
  the correct app also fails is **rejected**: the expectation is wrong, so it
  proves nothing. Live runs showed this is usually the right bug described
  with guessed wording (a URL or a message the agent never saw), which is why
  it is counted apart from a false alarm;
* on the correct app and the benign variants, every reproduced finding is a
  **false alarm**: the agent reported a bug in code that has none.

The agent's word is never the score. The stub agent reports nothing, so the
suite runs without a model and must score 0 found, 0 false alarms.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from contexer.appserver import AppStartError, RunningApp, open_app
from contexer.bench.runner import FixtureApp, Variant, VariantKind, Workspace, discover
from contexer.contract import Contract
from contexer.contract.models import utc_now
from contexer.evidence.rundir import RunDir
from contexer.gate.session import VerificationSession
from contexer.verification.checks import Check
from contexer.verification.models import AcceptanceCriterion
from contexer.verification.runner import CheckRunner
from contexer.verification.verifier import Verifier

Replay = Literal["refuted", "verified", "unverified"]
# How the error of a run that could not be scored begins.
NOT_SCORED = ("the app did not start", "the tester failed", "the app could not be opened")


class Finding(BaseModel):
    """Something the agent believes is wrong, stated as the behaviour it expected."""

    title: str
    # Steps a user takes and what should be true afterwards. On a real bug this check fails.
    check: Check
    detail: str = ""


class Exploration(BaseModel):
    """What an agent reports after testing one app."""

    findings: list[Finding] = Field(default_factory=list)
    # Findings not reported because the app was showing its own message when the check failed.
    explained: int = 0
    # Findings the agent's own second look set aside before reporting.
    set_aside: int = 0
    steps: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float | None = None
    # Why the agent stopped early, if it did (a limit, a model error).
    error: str = ""


class TesterAgent(Protocol):
    """Anything that can test a running app from its goal alone."""

    name: str

    async def explore(self, goal: str, app: RunningApp, project_dir: Path) -> Exploration: ...


class StubTester:
    """Reports nothing. It lets the whole suite run with no model, as a baseline of zero."""

    name = "stub"

    async def explore(self, goal: str, app: RunningApp, project_dir: Path) -> Exploration:
        return Exploration()


class LiveTester:
    """The Tester agent (``crew/tester.py``) on the model the user configured.

    It reports the bugs the agent recorded, frozen into checks. Whether they
    are real is decided by this benchmark's replays, not by the agent, and not
    by the replay ``contexer test`` would do: the benchmark also replays on
    the correct app, which a user's project does not have.
    """

    name = "tester"

    def __init__(self, model: object | None = None, max_steps: int | None = None) -> None:
        self.model = model
        self.max_steps = max_steps
        # The model that answered, for the results page.
        self.model_label = ""
        # Where to keep each run's transcript (the working copy is deleted), and what to call it.
        self.keep_dir: Path | None = None
        self.variant_label = ""

    async def explore(self, goal: str, app: RunningApp, project_dir: Path) -> Exploration:
        from contexer.browser.freeze import freeze
        from contexer.browser.tools import BrowserSession, credential_secrets
        from contexer.cli.test_cli import build_model
        from contexer.crew.tester import DEFAULT_MAX_STEPS, run_tester
        from contexer.gate.session import DEV_SERVER_TIMEOUT_SCALE
        from contexer.llm.chat import describe_model

        model = self.model or build_model(project_dir)
        self.model = model  # one model for the whole suite
        self.model_label = describe_model(model)
        run = RunDir.create(project_dir)
        session = VerificationSession(project_dir, run, verifier=Verifier(llm_provider=None, runner=CheckRunner()))
        state = await session.signed_in_state(app)
        if session.sign_in_error is not None:
            return Exploration(error=f"could not sign in: {session.sign_in_error}")
        browser = BrowserSession(
            app.url,
            run_dir=run.path,
            storage_state=state,
            reset=session.reset_before_each(app),
            timeout_scale=DEV_SERVER_TIMEOUT_SCALE if app.kind == "dev" else 1.0,
        )
        try:
            await browser.start()
        except Exception as exc:
            return Exploration(error=f"the app could not be opened in the browser: {str(exc).splitlines()[0]}")
        async with browser:
            tested = await run_tester(
                goal,
                model,  # type: ignore[arg-type]
                browser,
                run_dir=run.path,
                max_steps=self.max_steps or DEFAULT_MAX_STEPS,
                secrets=credential_secrets(session.auth.as_check()) if session.auth is not None else [],
            )
        if self.keep_dir is not None and tested.transcript is not None and tested.transcript.is_file():
            import shutil

            self.keep_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(tested.transcript, self.keep_dir / f"{self.variant_label or run.run_id}.jsonl")
        # The product shows a bug only after its Challenger has looked at it, so that is what is measured.
        from contexer.browser.freeze import Confirmed
        from contexer.crew.challenger import challenge

        candidates = [f for f in tested.findings if f.kind == "bug"]
        explained = [f for f in candidates if f.messages]  # the app said why: not asserted as a bug
        reported = [
            Confirmed(finding=f, check=freeze(f), criterion_id=f"finding-{n}")
            for n, f in enumerate((f for f in candidates if not f.messages), 1)
        ]
        challenged = await challenge(reported, goal, model, run_dir=run.path)  # type: ignore[arg-type]
        bugs = [Finding(title=c.finding.title, check=c.check, detail=c.finding.description) for c in challenged.standing]
        error = "" if tested.status == "ok" else f"the tester ended with {tested.status}: {tested.error}"
        return Exploration(
            findings=bugs,
            steps=tested.steps,
            set_aside=len(challenged.set_aside),
            explained=len(explained),
            tokens_in=tested.tokens_in + challenged.tokens_in,
            tokens_out=tested.tokens_out + challenged.tokens_out,
            cost_usd=tested.cost_usd,
            error=error,
        )


# Agents `--agent` can name.
TESTER_AGENTS: dict[str, Callable[[], TesterAgent]] = {"stub": StubTester, "tester": LiveTester}


class TesterRun(BaseModel):
    """One agent run on one variant, after its findings were replayed."""

    app: str
    kind: VariantKind
    name: str
    repeat: int = 0
    findings: int = 0
    # Findings not reported as bugs: the app said why, or the agent's Challenger set them aside.
    explained: int = 0
    set_aside: int = 0
    # Titles, by what the replay showed.
    real: list[str] = Field(default_factory=list)
    # Correct and benign variants only: a reproduced finding on code that has no bug.
    false_alarms: list[str] = Field(default_factory=list)
    # Bug variants only: reproduced on the bug, but the correct app fails the same check.
    rejected: list[str] = Field(default_factory=list)
    unconfirmed: list[str] = Field(default_factory=list)
    # Bug variants only: a finding reproduced on the bug and passed on the correct app.
    found: bool | None = None
    steps: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float | None = None
    duration_seconds: float = 0.0
    # The app did not start, or the agent stopped early.
    error: str = ""


class TesterScore(BaseModel):
    app: str
    bugs: int = 0
    found: int = 0
    missed_bugs: list[str] = Field(default_factory=list)
    clean_runs: int = 0
    # Reproduced findings on correct or benign code.
    false_alarms: int = 0
    # Findings on a bug variant whose check the correct app fails too.
    rejected: int = 0
    # Runs on correct or benign code with at least one false alarm.
    false_alarm_runs: int = 0
    unconfirmed: int = 0
    # Runs where the app did not start: not scored.
    errors: int = 0
    # Runs where the agent stopped early (a limit or a model error); they are still scored.
    stopped_early: int = 0
    steps: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float | None = None


class TesterBenchReport(BaseModel):
    agent: str
    # The model the agent ran on, when it has one.
    model: str = ""
    started_at: str
    duration_seconds: float = 0.0
    repeats: int
    apps: list[TesterScore] = Field(default_factory=list)
    runs: list[TesterRun] = Field(default_factory=list)

    def totals(self) -> TesterScore:
        total = TesterScore(app="total")
        for score in self.apps:
            for key in ("bugs", "found", "clean_runs", "false_alarms", "false_alarm_runs", "rejected", "unconfirmed", "errors", "steps", "tokens_in", "tokens_out", "stopped_early"):
                setattr(total, key, getattr(total, key) + getattr(score, key))
            total.missed_bugs.extend(f"{score.app}/{bug}" for bug in score.missed_bugs)
            if score.cost_usd is not None:
                total.cost_usd = (total.cost_usd or 0.0) + score.cost_usd
        return total


async def run_tester_bench(
    fixtures_root: Path,
    agent: TesterAgent,
    *,
    repeats: int = 1,
    only: list[str] | None = None,
    on_run: Callable[[TesterRun], None] | None = None,
) -> TesterBenchReport:
    """Run ``agent`` on the correct app and every benign variant ``repeats`` times, and on every bug once."""
    started = time.monotonic()
    report = TesterBenchReport(agent=agent.name, started_at=utc_now(), repeats=repeats)
    for app in discover(fixtures_root, only):
        score = TesterScore(app=app.name)
        report.apps.append(score)
        goal = _goal(app)
        good = Variant(app=app.name, kind="good", name="good")
        plan: list[tuple[Variant, int]] = [(good, r) for r in range(repeats)]
        plan += [(v, r) for v in app.benign for r in range(repeats)]
        plan += [(v, 0) for v in app.bugs]
        with Workspace(app) as workspace:
            for variant, repeat in plan:
                run = await _run_variant(agent, goal, variant, repeat, workspace)
                report.runs.append(run)
                _score(score, run)
                if on_run:
                    on_run(run)
    report.duration_seconds = time.monotonic() - started
    report.model = str(getattr(agent, "model_label", "") or "")
    return report


def _goal(app: FixtureApp) -> str:
    """The app's goal in words. The contract's checks are never shown to the agent."""
    goals = [contract.goal for contract in app.contracts if contract.goal.strip()]
    return " ".join(goals) or f"The {app.name} app works as a user would expect."


async def _run_variant(agent: TesterAgent, goal: str, variant: Variant, repeat: int, workspace: Workspace) -> TesterRun:
    started = time.monotonic()
    run = TesterRun(app=variant.app, kind=variant.kind, name=variant.name, repeat=repeat)
    if variant.kind == "bug":
        run.found = False
    work = workspace.materialise(variant.overlay)
    if hasattr(agent, "variant_label"):
        agent.variant_label = f"{variant.app}-{variant.kind}-{variant.name}-{repeat + 1}"  # type: ignore[attr-defined]
    try:
        with open_app(work, log_path=RunDir.create(work).server_log) as running:
            exploration = await agent.explore(goal, running, work)
            replayed = await _replay(work, running, goal, exploration.findings)
    except AppStartError as exc:
        run.error = f"the app did not start: {exc}\n{exc.log_tail}".strip()[-1500:]
        run.duration_seconds = time.monotonic() - started
        return run
    except Exception as exc:  # one run's failure is one run's: the suite goes on
        first_line = (str(exc).splitlines() or [""])[0]
        run.error = f"the tester failed: {type(exc).__name__}: {first_line}"[:1500]
        run.duration_seconds = time.monotonic() - started
        return run

    run.findings = len(exploration.findings)
    run.set_aside = exploration.set_aside
    run.explained = exploration.explained
    run.steps = exploration.steps
    run.tokens_in, run.tokens_out = exploration.tokens_in, exploration.tokens_out
    run.cost_usd = exploration.cost_usd
    run.error = exploration.error
    if run.error.startswith(NOT_SCORED):
        run.duration_seconds = time.monotonic() - started
        return run
    reproduced = [f for f, verdict in zip(exploration.findings, replayed) if verdict == "refuted"]
    run.unconfirmed = [f.title for f, verdict in zip(exploration.findings, replayed) if verdict != "refuted"]

    if variant.kind != "bug":
        run.false_alarms = [f.title for f in reproduced]
    elif reproduced:
        # Is the app wrong, or the agent's expectation? The correct app decides.
        try:
            on_good = await _replay_on_good(workspace, goal, reproduced)
        except AppStartError as exc:
            run.error = f"the correct app did not start for the second replay: {exc}"[:1500]
            on_good = ["unverified"] * len(reproduced)
        for finding, verdict in zip(reproduced, on_good):
            if verdict == "verified":
                run.real.append(finding.title)
            elif verdict == "refuted":
                run.rejected.append(finding.title)
            else:
                run.unconfirmed.append(finding.title)
        run.found = bool(run.real)
    run.duration_seconds = time.monotonic() - started
    return run


async def _replay_on_good(workspace: Workspace, goal: str, findings: list[Finding]) -> list[Replay]:
    work = workspace.materialise()
    with open_app(work, log_path=RunDir.create(work).server_log) as running:
        return await _replay(work, running, goal, findings)


async def _replay(work: Path, running: RunningApp, goal: str, findings: list[Finding]) -> list[Replay]:
    """Replay each finding's check in a fresh browser, with the project's sign-in and reset, and no model."""
    if not findings:
        return []
    criteria = [
        AcceptanceCriterion(
            id=f"finding-{index + 1}",
            description=finding.title,
            verification_method="interactive_test",
            check=finding.check,
        )
        for index, finding in enumerate(findings)
    ]
    contract = Contract(id="tester-findings", goal=goal, criteria=criteria, source="llm").approved_by("bench-tester")
    session = VerificationSession(work, RunDir.create(work), verifier=Verifier(llm_provider=None, runner=CheckRunner()))
    result = await session.verify(running, [contract])
    verdicts: dict[str, Replay] = {}
    for outcome in result.contracts:
        for r in outcome.verification.criteria_results if outcome.verification else []:
            if r.proven:
                verdicts[r.criterion_id] = r.verdict
    # A check that never ran (the app could not be loaded, sign-in failed) decided nothing.
    return [verdicts.get(criterion.id, "unverified") for criterion in criteria]


def _score(score: TesterScore, run: TesterRun) -> None:
    score.steps += run.steps
    score.tokens_in += run.tokens_in
    score.tokens_out += run.tokens_out
    if run.error.startswith("the tester ended"):
        score.stopped_early += 1
    if run.cost_usd is not None:
        score.cost_usd = (score.cost_usd or 0.0) + run.cost_usd
    if run.error.startswith(NOT_SCORED):
        score.errors += 1
        return
    score.false_alarms += len(run.false_alarms)
    score.rejected += len(run.rejected)
    score.unconfirmed += len(run.unconfirmed)
    if run.kind == "bug":
        score.bugs += 1
        if run.found:
            score.found += 1
        else:
            score.missed_bugs.append(run.name)
    else:
        score.clean_runs += 1
        score.false_alarm_runs += 1 if run.false_alarms else 0


def results_markdown(report: TesterBenchReport) -> str:
    """The report as the Markdown page written next to ``bench/RESULTS.md``."""
    total = report.totals()
    lines = [
        f"# Tester benchmark: `{report.agent}`",
        "",
        f"`contexer bench --suite tester --agent {report.agent}`"
        + (f" --repeats {report.repeats}" if report.repeats != 1 else "")
        + f", {report.started_at[:10]} ({report.duration_seconds:.0f} s)"
        + (f", {report.model}" if report.model else "")
        + ". Written by the command; do not edit.",
        "",
        "The agent gets each app's goal in words and the running app, never the contract. A bug is **found** only when",
        "the agent's finding fails on the buggy app and passes on the correct one, both replayed by code. A **false",
        "alarm** is a finding reported on correct or benign code. **Rejected** is a finding on a seeded bug whose check",
        "the correct app fails too, so it does not count. **Unconfirmed** findings did not reproduce and were dropped.",
        "Method: [README.md](../README.md#the-tester-suite).",
        "",
        "| App | Seeded bugs | Found | False alarms | Clean runs with a false alarm | Rejected | Unconfirmed | Steps | Tokens in / out | Cost |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for score in [*report.apps, total]:
        name = "**total**" if score is total else score.app
        cost = f"${score.cost_usd:.2f}" if score.cost_usd is not None else "not reported"
        lines.append(
            f"| {name} | {score.bugs} | {score.found} | {score.false_alarms} | "
            f"{score.false_alarm_runs} / {score.clean_runs} | {score.rejected} | {score.unconfirmed} | {score.steps} | "
            f"{score.tokens_in:,} / {score.tokens_out:,} | {cost} |"
        )
    if total.missed_bugs:
        lines += ["", "Not found: " + ", ".join(f"`{bug}`" for bug in total.missed_bugs) + "."]
    if total.stopped_early:
        lines += ["", f"In {total.stopped_early} run(s) the agent stopped early (a step or time limit, or a model error); what it had recorded was still scored."]
    if total.errors:
        lines += ["", f"{total.errors} run(s) were not scored: the app did not start, or the agent failed before testing it."]
    if report.agent == "stub":
        lines += [
            "",
            "The stub agent reports nothing, so this is the floor: every app started, every variant ran, nothing was",
            "found and nothing was wrongly flagged. The hand-written contracts catch 40 of 40 with 0 of 278 false",
            "failures ([RESULTS.md](../RESULTS.md)); that is the number the Tester is measured against.",
        ]
    return "\n".join(lines) + "\n"
