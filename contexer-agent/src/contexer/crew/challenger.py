"""The Challenger: is a confirmed bug the app's fault, or the tester's?

Replay proves that a finding's steps end with its expectation not holding.
It cannot tell why. On a held-out app the Tester booked a slot, clicked a
second one without typing a name again, was told "Enter your name" by the
app, and reported "booking a second slot fails". That replays every time.

The Challenger looks at each confirmed bug with fresh eyes: the intent, the
exact steps, the expectation, what the page showed and what the app was
saying. It may set a finding aside, with a reason a person can check.

It is a filter and nothing more, and the code keeps it one:

* it can only remove. A verdict about a finding that does not exist, or a
  verdict other than ``tester_error``, changes nothing;
* a finding is set aside only with a reason. When the model fails, says
  nothing, or the budget is spent, every finding stands: a real bug is never
  lost because the second opinion was unavailable;
* what is set aside is not hidden. ``contexer test`` lists it with the
  reason, so a wrong verdict costs a look, not a missed bug.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field

from contexer.browser.freeze import Confirmed
from contexer.crew.base import AgentSpec, AgentStatus, run_agent
from contexer.crew.budget import Budget
from contexer.crew.untrusted import untrusted

_PROMPT = Path(__file__).resolve().parent / "prompts" / "challenger.md"
_MAX_REASON_CHARS = 400
DEFAULT_MAX_STEPS = 3


class Verdict(BaseModel):
    finding: int = Field(description="The number of the finding, as listed.")
    verdict: str = Field(description="'stands' or 'tester_error'.")
    reason: str = Field("", description="For tester_error: one sentence naming the reason and the evidence.")


class Verdicts(BaseModel):
    """The Challenger's answer. A finding left out stands."""

    verdicts: list[Verdict] = Field(default_factory=list)


@dataclass
class ChallengeResult:
    standing: list[Confirmed] = field(default_factory=list)
    # Findings set aside, each with the reason.
    set_aside: list[tuple[Confirmed, str]] = field(default_factory=list)
    status: AgentStatus | Literal["skipped"] = "skipped"
    steps: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float | None = None
    error: str = ""


def challenger_prompt() -> str:
    return _PROMPT.read_text(encoding="utf-8")


async def challenge(
    confirmed: Sequence[Confirmed],
    intent: str,
    model: BaseChatModel,
    *,
    run_dir: Path | None = None,
    budget: Budget | None = None,
    secrets: Sequence[str] = (),
    max_steps: int = DEFAULT_MAX_STEPS,
) -> ChallengeResult:
    """Review ``confirmed`` bugs. Returns the ones that stand and the ones set aside, in their original order.

    ``secrets`` are masked in what the model is sent: the evidence is what the page showed.
    """
    items = list(confirmed)
    result = ChallengeResult(standing=items)
    if not items or (budget is not None and budget.exhausted()):
        return result
    spec = AgentSpec(
        name="challenger", system_prompt=challenger_prompt(), output_schema=Verdicts, max_steps=max_steps, timeout=180.0
    )
    ran = await run_agent(spec, model, [], _task(items, intent), run_dir=run_dir, secrets=list(secrets), budget=budget)
    result.status, result.error, result.steps = ran.status, ran.error, ran.steps
    result.tokens_in, result.tokens_out, result.cost_usd = ran.tokens_in, ran.tokens_out, ran.cost_usd
    if not isinstance(ran.output, Verdicts):
        return result  # no second opinion: every finding stands

    reasons: dict[int, str] = {}
    for verdict in ran.output.verdicts:
        reason = " ".join(verdict.reason.split())
        if verdict.verdict.strip().lower() == "tester_error" and reason and 1 <= verdict.finding <= len(items):
            reasons.setdefault(verdict.finding - 1, reason[:_MAX_REASON_CHARS])
    result.standing = [item for index, item in enumerate(items) if index not in reasons]
    result.set_aside = [(item, reasons[index]) for index, item in enumerate(items) if index in reasons]
    return result


def _task(items: list[Confirmed], intent: str) -> str:
    parts = ["## What the app should do (the intent)", intent.strip(), "", "## Findings, each reproduced by replay"]
    for number, item in enumerate(items, 1):
        finding = item.finding
        seen = item.result.summary() if item.result is not None else f"saw {finding.observed}"
        evidence = [
            f"Title: {finding.title}",
            *([f"The tester's note: {finding.description}"] if finding.description else []),
            "Steps, from a freshly loaded app:",
            *[f"  {line}" for line in item.check.describe_lines()],
            f"What happened: {seen}",
            "The app was showing: " + ("; ".join(finding.messages) if finding.messages else "no message"),
        ]
        parts += ["", f"### Finding {number}", untrusted("finding", "\n".join(evidence))]
    parts += ["", "Give your verdicts."]
    return "\n".join(parts)
