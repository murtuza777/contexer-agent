"""The Tester: explores a running app against the stated intent and reports what it observed.

The Tester is an agent in the :func:`~contexer.crew.base.run_agent` loop with
the browser tools and one more, ``record_finding``. A finding does not carry
the agent's account of what happened. It points at one ``expect`` result, and
code copies the recorded steps and the expectation from the recording
(:mod:`contexer.browser.recorder`). Code also refuses a finding the
observation does not support: a "bug" whose expectation passed, a "works"
whose expectation failed, or one that points at nothing.

Findings are still only claims. :mod:`contexer.browser.freeze` replays each
one in a fresh browser, and only what reproduces is shown to anyone.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from contexer.browser.tools import BrowserSession
from contexer.crew.base import AgentSpec, AgentStatus, run_agent
from contexer.crew.budget import Budget
from contexer.crew.untrusted import untrusted
from contexer.skills.store import MAX_PROPOSED, Skill, skills_text
from contexer.verification.checks import Expectation, Step

DEFAULT_MAX_STEPS = 40
DEFAULT_TIMEOUT = 900.0
_PROMPT = Path(__file__).resolve().parent / "prompts" / "tester.md"

FindingKind = Literal["bug", "works"]
Severity = Literal["high", "medium", "low"]


class Finding(BaseModel):
    """What the Tester observed, as recorded: the steps it took and the expectation it evaluated."""

    kind: FindingKind
    title: str
    description: str = ""
    severity: Severity = "medium"
    steps: list[Step] = Field(default_factory=list)
    expectation: Expectation
    # False when the page was signed out on purpose; None follows the project.
    login: bool | None = None
    # What the page showed when the Tester looked.
    observed: str = ""
    # Messages the app was showing at that moment, when the expectation failed.
    messages: list[str] = Field(default_factory=list)


class TesterSummary(BaseModel):
    """The Tester's closing note. Findings are recorded with `record_finding`, not here."""

    summary: str = Field(description="Two or three sentences: what you covered, and anything you could not test.")
    questions: list[str] = Field(
        default_factory=list,
        description="Behaviour you saw that the intent does not settle, each as one question for the person. Not bugs.",
    )
    skills: list[Skill] = Field(
        default_factory=list,
        description="At most 3 things you learned about operating this app that would save the next tester steps: "
        "how to reach a screen, how to seed or reset data, which flow is slow. Never a credential.",
    )


class _RecordFinding(BaseModel):
    kind: FindingKind = Field(description='"bug": the expect FAILED. "works": the expect PASSED.')
    title: str = Field(description="One line a person can act on, e.g. 'Completing a task does not lower the count'.")
    observation: str = Field(description="The id of the expect result that shows it, e.g. 'e3'.")
    violates: str = Field(
        "",
        description="For a bug: the exact words of the intent it breaks, copied from the intent. "
        "Or the single word 'error' when the app threw an uncaught exception (the observation must be a failed "
        "no_errors).",
    )
    description: str = Field("", description="What you did and what you saw, in a sentence or two.")
    severity: Severity = Field("medium", description="high, medium or low.")


@dataclass
class TesterResult:
    """The Tester's findings and how its run ended. Nothing here is confirmed yet."""

    status: AgentStatus
    findings: list[Finding] = field(default_factory=list)
    summary: str = ""
    # What the Tester saw that the intent does not settle. For the person to answer; never a result.
    questions: list[str] = field(default_factory=list)
    # What the Tester proposes to remember about operating this app. Advice for a later run, never proof.
    skills: list[Skill] = field(default_factory=list)
    steps: int = 0
    tool_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float | None = None
    duration_seconds: float = 0.0
    error: str = ""
    transcript: Path | None = None


def tester_prompt() -> str:
    return _PROMPT.read_text(encoding="utf-8")


async def run_tester(
    intent: str,
    model: BaseChatModel,
    browser: BrowserSession,
    *,
    run_dir: Path | None,
    existing_checks: Sequence[str] = (),
    skills: Sequence[Skill] = (),
    max_steps: int = DEFAULT_MAX_STEPS,
    timeout: float = DEFAULT_TIMEOUT,
    secrets: Sequence[str] = (),
    budget: Budget | None = None,
) -> TesterResult:
    """Let ``model`` test the app in ``browser`` against ``intent``.

    Whatever ends the run (an answer, the step limit, the time limit, a model
    error), the findings recorded so far are returned.
    """
    findings: list[Finding] = []
    reported: dict[str, str] = {}

    def record_finding(
        kind: FindingKind,
        title: str,
        observation: str,
        violates: str = "",
        description: str = "",
        severity: Severity = "medium",
    ) -> str:
        wanted = observation.strip().lower()
        if not wanted:
            return "Error: a finding needs the id of the expect result that shows it (observation). Too vague to replay."
        seen = browser.recorder.observation(wanted)
        if seen is None:
            known = ", ".join(o.id for o in browser.recorder.observations) or "none yet"
            return f"Error: there is no observation {wanted}. Run expect first; the ids so far: {known}."
        if not seen.reliable:
            return (
                f"Error: a step before {seen.id} failed part-way, so its recording may not match what the page went "
                "through and it cannot be replayed. Call reset, repeat the steps, run expect again and record that."
            )
        if kind == "bug" and seen.passed:
            return (
                f"Error: {seen.id} passed, so it does not show a bug. Record it as works, or run an expect that "
                "states the correct behaviour and fails."
            )
        if kind == "bug":
            problem = _not_grounded(violates, intent, seen.crashed)
            if problem:
                return problem
        if kind == "works" and not seen.passed:
            return f"Error: {seen.id} failed, so it does not show that this works. Record it as a bug if the app is wrong."
        if seen.id in reported:
            return f"Error: {seen.id} is already recorded as '{reported[seen.id]}'."
        reported[seen.id] = title
        findings.append(
            Finding(
                kind=kind,
                title=title.strip(),
                description=description.strip(),
                severity=severity,
                steps=list(seen.steps),
                expectation=seen.expectation,
                login=seen.login,
                observed=seen.actual,
                messages=list(seen.messages),
            )
        )
        return f"Recorded {kind} from {seen.id}. It will be replayed in a fresh browser before anyone sees it."

    tools = [
        *browser.tools(),
        StructuredTool.from_function(
            record_finding,
            name="record_finding",
            description="Record a bug or a working behaviour, pointing at the expect result that shows it. "
            "Call it as soon as you have the observation.",
            args_schema=_RecordFinding,
        ),
    ]
    spec = AgentSpec(
        name="tester",
        system_prompt=tester_prompt(),
        output_schema=TesterSummary,
        max_steps=max_steps,
        timeout=timeout,
    )
    # One list, shared: a password the Tester types later is masked from then on, and in the transcript.
    browser.secrets.extend(s for s in secrets if s)
    task = _task(intent, await browser.snapshot(), existing_checks, skills)
    result = await run_agent(spec, model, tools, task, run_dir=run_dir, secrets=browser.secrets, budget=budget)
    summary = result.output.summary if isinstance(result.output, TesterSummary) else ""
    questions = [q.strip() for q in result.output.questions if q.strip()] if isinstance(result.output, TesterSummary) else []
    return TesterResult(
        status=result.status,
        findings=findings,
        summary=summary,
        questions=questions,
        skills=list(result.output.skills[:MAX_PROPOSED]) if isinstance(result.output, TesterSummary) else [],
        steps=result.steps,
        tool_calls=result.tool_calls,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        cost_usd=result.cost_usd,
        duration_seconds=result.duration_seconds,
        error=result.error,
        transcript=result.transcript,
    )


def _words(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _not_grounded(violates: str, intent: str, crashed: bool) -> str:
    """Why a bug is refused, or '' when it rests on the intent or on an outright error.

    A bug is the app not doing what the intent states, or the app throwing. Code checks the first by
    finding the quoted words in the intent, and the second by an uncaught exception behind a failed
    ``no_errors``. A console line alone does not count: a server that answers 400 to invalid input is
    validation working, and the browser logs it all the same.
    """
    quote = _words(violates)
    if not quote:
        return (
            "Error: a bug needs `violates`: the exact words of the intent it breaks, or 'error' when the app "
            "threw an uncaught exception."
        )
    if quote == "error":
        if crashed:
            return ""
        return (
            "Error: violates='error' is for a failed no_errors with an uncaught exception behind it. A console "
            "line about a request the server refused (400, 404, 422) is not a crash: refusing bad input is "
            "often the app working. If the intent says this should succeed, quote the intent; otherwise leave it out."
        )
    if len(quote) >= 6 and quote in _words(intent):
        return ""
    return (
        f"Error: '{violates.strip()}' is not in the intent. Copy the exact words of the intent this breaks. If the "
        "intent does not say it, it is not a bug: leave it out and put it in `questions` when you submit."
    )


def _task(intent: str, snapshot: str, existing_checks: Sequence[str], skills: Sequence[Skill] = ()) -> str:
    parts = [
        "## What the app should do (the intent)",
        intent.strip(),
        "",
        "## The app right now",
        untrusted("page", snapshot) or "(the page could not be read; call snapshot)",
    ]
    if existing_checks:
        parts += ["", "## Checks that already exist (do not repeat them)", *[f"- {line}" for line in existing_checks]]
    parts.append("")
    if skills:
        parts += [
            "## What earlier runs learned about this app (advice: it may be out of date, and it proves nothing)",
            untrusted("saved-skills", skills_text(skills)),
            "",
        ]
    parts.append("Test it. Record findings as you go, then submit a summary.")
    return "\n".join(parts)
