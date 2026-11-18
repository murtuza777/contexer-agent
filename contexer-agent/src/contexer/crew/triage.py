"""Triage: after an attempt that did not pass, what should happen next?

The 0.4 controller answered with two rules. Triage lets a model answer with
judgment, and keeps the answer inside limits a model cannot move:

* code builds the list of legal moves first (:func:`legal_moves`). No repair
  is legal when no round or money is left; nobody is asked when nobody is
  there. The model is shown only that list;
* an answer outside the list, an answer that is not a move at all, a model
  error and a spent budget all end the same way: the 0.4 rules decide
  (:func:`rule_move`), and what the model said is kept in ``rejected``;
* no move can end a run as ``succeeded``. That is decided by the gate, in
  code, from checks replayed in a browser. Triage is only asked after it
  said no.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, get_args

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field

from contexer.crew.base import AgentSpec, run_agent
from contexer.crew.budget import Budget
from contexer.crew.untrusted import untrusted

Move = Literal["repair_same_session", "fresh_approach", "rollback_and_retry", "ask_user", "stop"]
MOVES: tuple[Move, ...] = get_args(Move)
# How often one run may stop to ask its user what to do.
MAX_ASKS = 1
_MAX_REASON_CHARS = 300
_MAX_FINDINGS_CHARS = 6000
_PROMPT = Path(__file__).resolve().parent / "prompts" / "triage.md"

MOVE_LABELS: dict[str, str] = {
    "repair_same_session": "repair in the same session",
    "fresh_approach": "fresh approach",
    "rollback_and_retry": "roll back to the best attempt and retry",
    "ask_user": "ask the user",
    "stop": "stop",
}
_MOVE_MEANS: dict[str, str] = {
    "repair_same_session": "send the failures back to the session that did the work, which remembers what it tried",
    "fresh_approach": "start a new session that is given the whole job again and the failures, with no memory of the earlier idea",
    "rollback_and_retry": "put the files back to the best attempt so far, then start a new session from there",
    "ask_user": "stop and ask the person one question, when the failures show the goal itself is unclear",
    "stop": "end the run now and keep the best attempt, when another round would not help",
}


class AttemptView(BaseModel):
    """One attempt, as Triage sees it."""

    n: int
    outcome: str
    score: int = 0
    verified: int = 0
    refuted: int = 0
    unverified: int = 0
    # Checks that did not pass, as "contract/criterion".
    failing: list[str] = Field(default_factory=list)
    # Of those, the ones that failed in exactly the same way as in the attempt before.
    repeated: list[str] = Field(default_factory=list)
    # Set when this attempt scored lower than an earlier one and the files were put back to that one.
    reverted_to: int | None = None


class Situation(BaseModel):
    """What Triage decides on. Built by code from the run's state."""

    attempts: list[AttemptView]
    rounds_left: int
    budget_left_usd: float | None = None
    best_attempt: int | None = None
    # Whether the coding agent gave a session that can be continued.
    has_session: bool = True
    # Whether a person is there to answer.
    can_ask: bool = False
    asked: int = 0
    # The latest failures, as text. It quotes the app, so it is untrusted.
    findings: str = ""


class TriageDecision(BaseModel):
    move: Move
    reason: str = ""
    source: Literal["model", "rules"] = "rules"
    # What the model answered when that answer was not used, and why not.
    rejected: str = ""
    attempt: int = 0
    steps: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float | None = None


class _Choice(BaseModel):
    """Triage's answer."""

    move: str = Field(description="One of the moves listed as allowed in the task, spelled exactly.")
    reason: str = Field(description="One line: why this move, naming what in the history shows it.")


def triage_prompt() -> str:
    return _PROMPT.read_text(encoding="utf-8")


def legal_moves(situation: Situation) -> list[Move]:
    """The moves that are allowed now, in a fixed order. Code decides this; the model chooses among them."""
    out_of_money = situation.budget_left_usd is not None and situation.budget_left_usd <= 0
    if situation.rounds_left <= 0 or out_of_money or not situation.attempts:
        return ["stop"]
    latest = situation.attempts[-1]
    moves: list[Move] = []
    # After a revert the session remembers code that is no longer there.
    if situation.has_session and latest.reverted_to is None:
        moves.append("repair_same_session")
    moves.append("fresh_approach")
    best = situation.best_attempt
    if best is not None and best != latest.n and latest.reverted_to is None:
        moves.append("rollback_and_retry")
    if situation.can_ask and situation.asked < MAX_ASKS:
        moves.append("ask_user")
    moves.append("stop")
    return moves


def rule_move(situation: Situation) -> TriageDecision:
    """The 0.4 rules: the same failure again, or a revert, means a fresh session; otherwise the same one."""
    legal = legal_moves(situation)
    attempt = situation.attempts[-1].n if situation.attempts else 0
    if legal == ["stop"]:
        return TriageDecision(move="stop", reason="No repair round or budget is left.", attempt=attempt)
    latest = situation.attempts[-1]
    if latest.repeated:
        reason = f"Same failure again ({', '.join(latest.repeated)}); the next repair starts a fresh session."
        return TriageDecision(move="fresh_approach", reason=reason, attempt=attempt)
    if latest.reverted_to is not None:
        reason = f"Attempt {latest.n} was reverted to attempt {latest.reverted_to}; the next repair starts a fresh session."
        return TriageDecision(move="fresh_approach", reason=reason, attempt=attempt)
    if "repair_same_session" in legal:
        return TriageDecision(move="repair_same_session", reason="A first failure of this kind: repair it in the same session.", attempt=attempt)
    return TriageDecision(move="fresh_approach", reason="There is no session to continue.", attempt=attempt)


async def triage(
    situation: Situation,
    model: BaseChatModel | None,
    *,
    run_dir: Path | None = None,
    budget: Budget | None = None,
) -> TriageDecision:
    """Choose the next move. Never raises; never returns a move that :func:`legal_moves` does not list."""
    fallback = rule_move(situation)
    legal = legal_moves(situation)
    if model is None or (budget is not None and budget.exhausted()):
        return fallback
    spec = AgentSpec(name="triage", system_prompt=triage_prompt(), output_schema=_Choice, max_steps=3, timeout=120.0, max_output_tokens=1000)
    ran = await run_agent(spec, model, [], _task(situation, legal), run_dir=run_dir, budget=budget)
    usage = {"steps": ran.steps, "tokens_in": ran.tokens_in, "tokens_out": ran.tokens_out, "cost_usd": ran.cost_usd}
    if not isinstance(ran.output, _Choice):
        why = f"Triage gave no usable answer ({ran.status}{': ' + ran.error if ran.error else ''}); the rules decided."
        return fallback.model_copy(update={"rejected": why[:_MAX_REASON_CHARS], **usage})
    chosen = ran.output.move.strip()
    if chosen not in legal:
        known = "not allowed now" if chosen in MOVES else "not a move"
        why = f"Triage answered '{chosen[:60]}', which is {known} (allowed: {', '.join(legal)}); the rules decided."
        return fallback.model_copy(update={"rejected": why, **usage})
    reason = " ".join(ran.output.reason.split())[:_MAX_REASON_CHARS]
    return TriageDecision(move=chosen, reason=reason, source="model", attempt=fallback.attempt, **usage)  # type: ignore[arg-type]


def _task(situation: Situation, legal: list[Move]) -> str:
    rounds = situation.rounds_left
    limits = [f"{rounds} repair round{'s' if rounds != 1 else ''} left"]
    if situation.budget_left_usd is not None:
        limits.append(f"${situation.budget_left_usd:.2f} of the coding agent's budget left")
    lines = ["## Attempts so far"]
    for attempt in situation.attempts:
        counts = f"{attempt.verified} verified, {attempt.refuted} refuted, {attempt.unverified} unverified"
        line = f"- Attempt {attempt.n}: {attempt.outcome} ({counts}; score {attempt.score})"
        if attempt.failing:
            line += f"; failing: {', '.join(attempt.failing)}"
        if attempt.repeated:
            line += f"; failed in exactly the same way as the attempt before: {', '.join(attempt.repeated)}"
        if attempt.reverted_to is not None:
            line += f"; scored lower than attempt {attempt.reverted_to}, so the files were put back to attempt {attempt.reverted_to}"
        lines.append(line)
    best = situation.best_attempt
    lines += ["", f"Best attempt so far: {best if best is not None else 'none'}.", f"Limits: {'; '.join(limits)}."]
    if situation.findings.strip():
        lines += ["", "## The latest failures", untrusted("failures", situation.findings.strip()[:_MAX_FINDINGS_CHARS])]
    lines += ["", "## The moves allowed now", *[f"- `{move}`: {_MOVE_MEANS[move]}" for move in legal]]
    lines += ["", "Choose one of these moves."]
    return "\n".join(lines)
