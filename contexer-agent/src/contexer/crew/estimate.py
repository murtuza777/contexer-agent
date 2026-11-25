"""What a run can use at most, said before it starts.

The numbers are ceilings, not predictions. The count of model calls follows
from the step caps in code. The tokens are that count times what a call of
each agent used in our live runs on small apps; a large project uses more
per call. A run that passes at the first attempt uses a small part of it.
"""

from __future__ import annotations

from pydantic import BaseModel

# Model calls one use of each agent may make (its step cap), and the tokens one call typically carries.
_INTENT_CALLS, _INTENT_TOKENS = 8, (4_000, 600)  # the draft, and one round of fixing invalid checks
_TRIAGE_CALLS, _TRIAGE_TOKENS = 1, (2_500, 100)
_PLANNER_CALLS, _PLANNER_TOKENS = 12, (6_000, 300)  # once, before the first coding turn; not measured live yet
_DIAGNOSER_CALLS, _DIAGNOSER_TOKENS = 15, (6_000, 250)
_REVIEWER_CALLS, _REVIEWER_TOKENS = 12, (5_000, 200)


class RunEstimate(BaseModel):
    coding_turns: int
    model_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float | None = None

    @property
    def tokens(self) -> int:
        return self.tokens_in + self.tokens_out

    def describe(self) -> str:
        turns = f"at most {self.coding_turns} coding-agent turn(s)"
        if not self.model_calls:
            return turns
        cost = f", about ${self.cost_usd:.2f}" if self.cost_usd is not None else ""
        return f"{turns}; Contexer's agents at most {self.model_calls} model call(s) (about {self.tokens:,} tokens if all are used{cost})"


def estimate_run(
    *,
    rounds: int,
    has_model: bool,
    drafts_checks: bool,
    review: bool,
    plan: bool = True,
    planner_steps: int = _PLANNER_CALLS,
    diagnoser_steps: int = _DIAGNOSER_CALLS,
    reviewer_steps: int = _REVIEWER_CALLS,
    input_usd_per_mtok: float | None = None,
    output_usd_per_mtok: float | None = None,
) -> RunEstimate:
    """The ceiling for a run on the graph engine with ``rounds`` repair rounds."""
    estimate = RunEstimate(coding_turns=rounds + 1)  # a repair the review asks for uses one of the rounds
    if not has_model:
        return estimate
    uses: list[tuple[int, tuple[int, int]]] = []
    if drafts_checks:
        uses.append((_INTENT_CALLS, _INTENT_TOKENS))
    if plan:
        uses.append((planner_steps, _PLANNER_TOKENS))
    for _ in range(rounds):  # after each attempt that does not pass
        uses.append((_TRIAGE_CALLS, _TRIAGE_TOKENS))
        uses.append((diagnoser_steps, _DIAGNOSER_TOKENS))
    if review:
        for _ in range(2 if rounds else 1):  # the pass, and the pass after the one repair a review may ask for
            uses.append((reviewer_steps, _REVIEWER_TOKENS))
    for calls, (tokens_in, tokens_out) in uses:
        estimate.model_calls += calls
        estimate.tokens_in += calls * tokens_in
        estimate.tokens_out += calls * tokens_out
    if input_usd_per_mtok is not None or output_usd_per_mtok is not None:
        estimate.cost_usd = (estimate.tokens_in * (input_usd_per_mtok or 0.0) + estimate.tokens_out * (output_usd_per_mtok or 0.0)) / 1_000_000
    return estimate
