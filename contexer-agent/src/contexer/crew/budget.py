"""A budget for a run: what Contexer's own agents may spend, and what the whole run may spend.

Step limits bound one agent. They do not bound a run: an Intent agent, a
Tester and a Diagnoser each have their own, and a compromised or confused
model can use all of them. The budget counts what the whole run has spent
and ``run_agent`` asks it before every model call.

Tokens are always counted. Cost is counted when the provider reports a price
per call, or when the project gives the rates (``[agents]
input_usd_per_mtok`` / ``output_usd_per_mtok``): then a call the provider
did not price is priced from its tokens, and the total is marked as an
estimate. With neither, cost stays unknown and a cost limit never triggers,
which is why the token limit is the one with a default, and why a command
refuses a dollar limit it could not keep (``unenforceable``) before it starts.

``max_total_usd`` is one budget for everything: Contexer's agents and the
coding agent. The engine tells the budget what the coding agent has spent
(``other_usd``); the budget cannot see that by itself.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from contexer.llm.capabilities import capabilities_of

# Tokens (in and out together) one run may use unless the project or the command says otherwise.
# A 40-step Tester run on a small app uses about 230,000.
DEFAULT_MAX_TOKENS = 1_500_000
# Providers that say what each call cost in its reply (``crew/base.py: reported_cost``).
_REPORTS_COST = frozenset({"openrouter"})


class Budget:
    """What a run may spend, and what it has spent so far."""

    def __init__(
        self,
        max_tokens: int | None = None,
        max_cost_usd: float | None = None,
        *,
        max_total_usd: float | None = None,
        input_usd_per_mtok: float | None = None,
        output_usd_per_mtok: float | None = None,
    ) -> None:
        self.max_tokens = max_tokens
        self.max_cost_usd = max_cost_usd
        self.max_total_usd = max_total_usd
        self.input_usd_per_mtok = input_usd_per_mtok
        self.output_usd_per_mtok = output_usd_per_mtok
        self.tokens_in = 0
        self.tokens_out = 0
        self.cost_usd: float | None = None
        # True once any part of ``cost_usd`` was worked out from tokens and rates, not reported.
        self.estimated = False
        # What the coding agent has spent in this run; set by the engine.
        self.other_usd = 0.0

    @property
    def tokens(self) -> int:
        return self.tokens_in + self.tokens_out

    def price(self, tokens_in: int, tokens_out: int) -> float | None:
        """What these tokens cost at the configured rates, or None when no rates are configured."""
        if self.input_usd_per_mtok is None and self.output_usd_per_mtok is None:
            return None
        return (max(0, tokens_in) * (self.input_usd_per_mtok or 0.0) + max(0, tokens_out) * (self.output_usd_per_mtok or 0.0)) / 1_000_000

    def cost_of(self, tokens_in: int, tokens_out: int, reported: float | None) -> float | None:
        """The cost to record for a call: what the provider reported, else the price at the configured rates."""
        return reported if reported is not None else self.price(tokens_in, tokens_out)

    def spend(self, tokens_in: int, tokens_out: int, cost_usd: float | None = None) -> None:
        self.tokens_in += max(0, tokens_in)
        self.tokens_out += max(0, tokens_out)
        if cost_usd is None:
            cost_usd = self.price(tokens_in, tokens_out)
            if cost_usd is not None:
                self.estimated = True
        if cost_usd is not None:
            self.cost_usd = (self.cost_usd or 0.0) + cost_usd

    def total_left(self) -> float | None:
        """What is left of the one budget for the whole run, never below 0. None when there is no such budget."""
        if self.max_total_usd is None:
            return None
        return max(0.0, self.max_total_usd - (self.cost_usd or 0.0) - self.other_usd)

    def exhausted(self) -> str:
        """Why no further model call may be made, or '' while there is budget left."""
        if self.max_tokens is not None and self.tokens >= self.max_tokens:
            return f"the token budget of {self.max_tokens:,} is used up ({self.tokens:,} tokens spent)"
        if self.max_cost_usd is not None and self.cost_usd is not None and self.cost_usd >= self.max_cost_usd:
            return f"the cost budget of ${self.max_cost_usd:.2f} is used up (${self.cost_usd:.2f} spent)"
        if self.max_total_usd is not None and self.total_left() == 0.0:
            spent = (self.cost_usd or 0.0) + self.other_usd
            return f"the run budget of ${self.max_total_usd:.2f} is used up (${spent:.2f} spent by the coding agent and Contexer's agents)"
        return ""

    def priced(self, model: Any) -> bool:
        """Whether a call to ``model`` will have a known cost: the project gives rates, or the provider reports one per call."""
        return self.price(0, 0) is not None or capabilities_of(model).provider in _REPORTS_COST


def unenforceable(budget: Budget, *, models: Iterable[Any] = (), coding_agent: str = "") -> str:
    """Why a dollar limit of ``budget`` cannot be kept, and what to set; '' when it can be, or there is none.

    ``models`` are the chat models Contexer's agents will call. ``coding_agent`` is the name of the
    coding agent when it reports no cost for its turns. A limit that would count unknown spend as 0
    is not a limit, so the commands refuse it before anything is spent.
    """
    if budget.max_total_usd is not None:
        limit = f"The run budget of ${budget.max_total_usd:.2f} (--max-usd, or max_usd under [agents])"
        if coding_agent:
            return (
                f"{limit} cannot be enforced: {coding_agent} reports no cost for its turns. "
                "Use a coding agent that reports cost (claude-code), or remove the budget: "
                "--rounds and the time limits still bound the run."
            )
    elif budget.max_cost_usd is not None:
        limit = f"The cost limit of ${budget.max_cost_usd:.2f} ([limits] cost_usd)"
    else:
        return ""
    unknown = sorted({_named(model) for model in models if not budget.priced(model)})
    if not unknown:
        return ""
    tokens = f"{budget.max_tokens:,}" if budget.max_tokens is not None else "not set"
    return (
        f"{limit} cannot be enforced: no price is known for {', '.join(unknown)}, which Contexer's agents will call. "
        "Set input_usd_per_mtok and output_usd_per_mtok under [agents] in contexer.toml (US dollars per million tokens), "
        f"or remove the dollar limit: the token limit ([limits] tokens, {tokens} for this run) still applies."
    )


def _named(model: Any) -> str:
    record = capabilities_of(model)
    return f"{record.model} ({record.provider})" if record.provider else record.model
