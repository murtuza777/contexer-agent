"""The Intent agent: from the goal and every correction to a written, testable statement of what is meant.

The agent writes three things: the behaviours the goal states, draft checks
for them, and at most three questions, each only where two readings of the
goal would be tested differently. Code keeps the rest in its own hands:

* a correction is written into the intent before the model is called, so it
  is kept whatever the model does;
* a question without two different readings is dropped, and with ``assume``
  no question is asked: the first reading is taken and recorded as an
  assumption;
* every draft check is validated by the check language
  (``workflow/criteria.py: _parse_check``). Invalid ones go back to the agent
  once; what is still invalid is dropped and reported;
* after a correction only the checks the agent names are replaced or
  removed. The others are the same objects as before, and a check a replay
  confirmed cannot be removed by the agent at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field, ValidationError

from contexer.contract.models import slugify
from contexer.crew.base import AgentSpec, AgentStatus, run_agent
from contexer.intent.store import IntentSpec, SavedCheck
from contexer.verification.checks import Check
from contexer.workflow.criteria import CHECK_DSL_GUIDE, _parse_check

MAX_QUESTIONS = 3
_PROMPT = Path(__file__).resolve().parent / "prompts" / "intent.md"
_MAX_STEPS = 4
_TIMEOUT = 300.0
_MAX_OUTPUT_TOKENS = 8000


class Question(BaseModel):
    """Something the goal leaves open, with the two ways to read it."""

    question: str
    reading_a: str = Field("", description="The reading you would take if nobody answers.")
    reading_b: str = Field("", description="The other reading, which would be tested differently.")


class DraftCheck(BaseModel):
    id: str = Field(description="Short kebab-case id, e.g. 'delete-asks-first'.")
    description: str = Field(description="One line: the behaviour this check proves.")
    check: dict[str, Any] = Field(description="The check, in the check language.")


class IntentDraft(BaseModel):
    """The Intent agent's answer."""

    behaviours: list[str] = Field(default_factory=list, description="Each stated behaviour as one checkable sentence.")
    questions: list[Question] = Field(default_factory=list, description="At most 3; only where two readings test differently.")
    assumptions: list[str] = Field(default_factory=list)
    checks: list[DraftCheck] = Field(default_factory=list)
    remove_checks: list[str] = Field(default_factory=list, description="Ids of draft checks a correction makes wrong.")


class _FixedChecks(BaseModel):
    """The checks that were invalid, corrected."""

    checks: list[DraftCheck] = Field(default_factory=list)


@dataclass
class IntentResult:
    spec: IntentSpec
    checks: list[SavedCheck] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    # Draft checks that were still invalid after one correction: (id, why).
    dropped: list[tuple[str, str]] = field(default_factory=list)
    status: AgentStatus = "ok"
    steps: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Optional[float] = None
    error: str = ""


def intent_prompt() -> str:
    return _PROMPT.read_text(encoding="utf-8").replace("{check_language}", CHECK_DSL_GUIDE.rstrip())


async def run_intent(
    goal: str,
    model: BaseChatModel,
    *,
    stored: Optional[IntentSpec] = None,
    existing_checks: Sequence[SavedCheck] = (),
    correction: Optional[str] = None,
    repo_summary: str = "",
    ui_snapshot: str = "",
    assume: bool = False,
    run_dir: Optional[Path] = None,
) -> IntentResult:
    """Write or update the intent for ``goal``.

    With ``correction``, the stored intent is updated and only the checks the
    correction affects change. With ``assume``, nothing is asked.
    """
    spec = stored or IntentSpec(id=slugify(goal), goal=goal.strip())
    if correction and correction.strip():
        spec = spec.with_correction(correction)
    existing = list(existing_checks)
    result = IntentResult(spec=spec, checks=existing)

    agent = AgentSpec(
        name="intent",
        system_prompt=intent_prompt(),
        output_schema=IntentDraft,
        max_steps=_MAX_STEPS,
        timeout=_TIMEOUT,
        max_output_tokens=_MAX_OUTPUT_TOKENS,
    )
    task = _task(spec, existing, repo_summary, ui_snapshot, updating=bool(correction), assume=assume)
    ran = await run_agent(agent, model, [], task, run_dir=run_dir)
    result.status, result.error, result.steps = ran.status, ran.error, ran.steps
    result.tokens_in, result.tokens_out, result.cost_usd = ran.tokens_in, ran.tokens_out, ran.cost_usd
    if not isinstance(ran.output, IntentDraft):
        return result  # the correction is already in the spec; the checks are untouched
    draft = ran.output

    behaviours = [line for line in (" ".join(b.split()) for b in draft.behaviours) if line]
    assumptions = _merged(spec.assumptions, draft.assumptions)
    questions = _real_questions(draft.questions)
    if assume:
        assumptions = _merged(
            assumptions,
            [f"{q.reading_a} (assumed without asking; the other reading was: {q.reading_b})" for q in questions],
        )
        questions = []
    result.spec = spec.model_copy(update={"behaviours": behaviours or spec.behaviours, "assumptions": assumptions})
    result.questions = questions

    valid, invalid = _validated(draft.checks)
    if invalid:
        fixing = AgentSpec(
            name="intent",
            system_prompt=intent_prompt(),
            output_schema=_FixedChecks,
            max_steps=_MAX_STEPS,
            timeout=_TIMEOUT,
            max_output_tokens=_MAX_OUTPUT_TOKENS,
        )
        again = await run_agent(fixing, model, [], _fix_task(invalid), run_dir=run_dir)
        result.steps += again.steps
        result.tokens_in += again.tokens_in
        result.tokens_out += again.tokens_out
        if again.cost_usd is not None:
            result.cost_usd = (result.cost_usd or 0.0) + again.cost_usd
        wanted = {check_id for check_id, _raw, _why in invalid}
        fixed = [c for c in again.output.checks if c.id in wanted] if isinstance(again.output, _FixedChecks) else []
        fixed_valid, still_invalid = _validated(fixed)
        valid += fixed_valid
        answered = {c.id for c in fixed}
        result.dropped = [(check_id, why) for check_id, _raw, why in still_invalid]
        result.dropped += [(check_id, why) for check_id, _raw, why in invalid if check_id not in answered]

    result.checks = _merge(existing, valid, set(draft.remove_checks), updating=bool(correction))
    return result


def _task(
    spec: IntentSpec, existing: list[SavedCheck], repo_summary: str, ui_snapshot: str, *, updating: bool, assume: bool
) -> str:
    parts = ["## The goal, in the person's words", spec.goal.strip()]
    if spec.behaviours or spec.corrections or spec.assumptions:
        parts += ["", "## What is already written down about this feature", spec.as_text()]
    if existing:
        parts += ["", "## Checks this feature already has"]
        parts += [f"- {c.id} ({c.source}): {c.description}" for c in existing]
    if repo_summary.strip():
        parts += ["", "## The project", repo_summary.strip()]
    if ui_snapshot.strip():
        parts += ["", "## The app's page right now", ui_snapshot.strip()]
    parts.append("")
    if updating and spec.corrections:
        parts.append(
            f'The person just gave this correction: "{spec.corrections[-1].text}". Update the behaviours to match it, '
            "return only the checks it changes or adds, and list in remove_checks the draft checks it makes wrong."
        )
    else:
        parts.append("Write the behaviours and draft checks for this goal.")
    if assume:
        parts.append("Nobody can answer questions now: still list any real ambiguity as a question, most likely reading first.")
    return "\n".join(parts)


def _fix_task(invalid: list[tuple[str, dict[str, Any], str]]) -> str:
    parts = ["These draft checks are not valid in the check language. Return each one corrected, with the same id:", ""]
    for check_id, raw, why in invalid:
        parts += [f"- {check_id}: {why}", f"  you wrote: {raw!r}"[:1200]]
    parts += ["", "Return only these checks. A check that cannot be made valid may be left out."]
    return "\n".join(parts)


def _real_questions(questions: list[Question]) -> list[Question]:
    """Questions with two different readings, at most ``MAX_QUESTIONS``."""
    kept: list[Question] = []
    for q in questions:
        a, b = " ".join(q.reading_a.split()), " ".join(q.reading_b.split())
        if not q.question.strip() or not a or not b or a.lower() == b.lower():
            continue
        kept.append(Question(question=" ".join(q.question.split()), reading_a=a, reading_b=b))
    return kept[:MAX_QUESTIONS]


def _validated(drafts: list[DraftCheck]) -> tuple[list[SavedCheck], list[tuple[str, dict[str, Any], str]]]:
    valid: list[SavedCheck] = []
    invalid: list[tuple[str, dict[str, Any], str]] = []
    for draft in drafts:
        check_id = slugify(draft.id) if draft.id.strip() else slugify(draft.description)
        check = _parse_check(check_id, draft.check)
        if check is None:
            invalid.append((check_id, draft.check, _why_invalid(draft.check)))
        else:
            valid.append(SavedCheck(id=check_id, description=" ".join(draft.description.split()), check=check))
    return valid, invalid


def _why_invalid(raw: Any) -> str:
    try:
        Check.model_validate(raw)
    except ValidationError as exc:
        parts = []
        for error in exc.errors()[:3]:
            where = ".".join(str(p) for p in error["loc"])
            parts.append(f"{where}: {error['msg'].removeprefix('Value error, ')}" if where else error["msg"])
        return "; ".join(parts)
    return "not a check"


def _merge(existing: list[SavedCheck], new: list[SavedCheck], remove: set[str], *, updating: bool) -> list[SavedCheck]:
    """The feature's checks after this run.

    Confirmed checks always stay. After a correction, a draft stays unless
    the agent replaced or removed it; otherwise the drafts are written anew.
    """
    replaced = {c.id for c in new}
    kept = [
        c
        for c in existing
        if c.source == "confirmed" or (updating and c.id not in replaced and c.id not in remove)
    ]
    taken = {c.id for c in kept}
    merged: list[SavedCheck] = []
    pending = {c.id: c for c in new if c.id not in taken}
    for old in existing:  # a replaced draft keeps its place
        if old in kept:
            merged.append(old)
        elif old.id in pending:
            merged.append(pending.pop(old.id))
    merged += list(pending.values())
    return merged


def _merged(first: list[str], second: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for line in [*first, *second]:
        clean = " ".join(line.split())
        if clean and clean.lower() not in seen:
            seen.add(clean.lower())
            out.append(clean)
    return out
