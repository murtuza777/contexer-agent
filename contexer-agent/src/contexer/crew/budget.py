"""A budget for a run: what Contexer's own agents may spend, and what the whole run may spend.

Step limits bound one agent. They do not bound a run: an Intent agent, a
Tester and a Diagnoser each have their own, and a compromised or confused
model can use all of them. The budget counts what the whole run has spent
and ``run_agent`` asks it before every model call.

Tokens are always counted. Cost is counted when the provider reports a price
per call. A call it did not price is priced from its tokens, and the total
is then marked as an estimate: at the rates the project gives (``[agents]
input_usd_per_mtok`` / ``output_usd_per_mtok``), which apply to every model,
else at the prices in the record of the model that was called
(``llm/capabilities.py``), so two models are each billed at their own. With
none of these, cost stays unknown and a cost limit never triggers, which is
why the token limit is the one with a default, and why a command refuses a
dollar limit it could not keep (``unenforceable``) before it starts.

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

    def _rates(self, model: Any) -> tuple[float, float, float] | None:
        """US dollars per million tokens of input, output and cached input for a call to ``model``; None when nobody says.

        The project's rates are an override and apply to every model. Without them the model's own
        record is asked, and only a record that states both prices counts: half a price is no price.
        Cached input costs what the record says. Where nobody says (the project's pair has no cached
        rate), it is priced as input, so an estimate errs upward.
        """
        if self.input_usd_per_mtok is not None or self.output_usd_per_mtok is not None:
            rate_in = self.input_usd_per_mtok or 0.0
            return rate_in, self.output_usd_per_mtok or 0.0, rate_in
        if model is None:
            return None
        record = capabilities_of(model)
        listed_in, listed_out = record.input_usd_per_mtok.value, record.output_usd_per_mtok.value
        if listed_in is None or listed_out is None:
            return None
        cached = record.cached_input_usd_per_mtok.value
        return listed_in, listed_out, listed_in if cached is None else cached

    def price(self, tokens_in: int, tokens_out: int, model: Any = None, cached_in: int = 0) -> float | None:
        """What these tokens cost at the project's rates, else at the prices of ``model``; None when neither is known.

        ``cached_in`` is the part of ``tokens_in`` the provider read from its cache.
        """
        rates = self._rates(model)
        if rates is None:
            return None
        tokens_in, tokens_out = max(0, tokens_in), max(0, tokens_out)
        cached_in = min(max(0, cached_in), tokens_in)
        return ((tokens_in - cached_in) * rates[0] + tokens_out * rates[1] + cached_in * rates[2]) / 1_000_000

    def cost_of(
        self, tokens_in: int, tokens_out: int, reported: float | None, model: Any = None, cached_in: int = 0
    ) -> float | None:
        """The cost to record for a call: what the provider reported, else its price (``price``)."""
        return reported if reported is not None else self.price(tokens_in, tokens_out, model, cached_in)

    def spend(
        self, tokens_in: int, tokens_out: int, cost_usd: float | None = None, *, model: Any = None, cached_in: int = 0
    ) -> float | None:
        """Count one call to ``model``; returns the cost that was recorded for it, or None when it is not known."""
        self.tokens_in += max(0, tokens_in)
        self.tokens_out += max(0, tokens_out)
        if cost_usd is None:
            cost_usd = self.price(tokens_in, tokens_out, model, cached_in)
            if cost_usd is not None:
                self.estimated = True
        if cost_usd is not None:
            self.cost_usd = (self.cost_usd or 0.0) + cost_usd
        return cost_usd

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
            # `contexer test` runs no coding agent: there the budget is spent by Contexer's agents alone.
            by = "the coding agent and Contexer's agents" if self.other_usd else "Contexer's agents"
            return f"the run budget of ${self.max_total_usd:.2f} is used up (${spent:.2f} spent by {by})"
        return ""

    def priced(self, model: Any) -> bool:
        """Whether a call to ``model`` will have a known cost: there are rates for it, or its provider reports one per call."""
        return self._rates(model) is not None or capabilities_of(model).provider in _REPORTS_COST


def unenforceable(budget: Budget, *, models: Iterable[Any] = (), coding_agent: str = "", flag: str = "--max-usd") -> str:
    """Why a dollar limit of ``budget`` cannot be kept, and what to set; '' when it can be, or there is none.

    ``models`` are the chat models Contexer's agents will call. ``coding_agent`` is the name of the
    coding agent when it reports no cost for its turns. A limit that would count unknown spend as 0
    is not a limit, so the commands refuse it before anything is spent. ``flag`` is the option that sets
    the run budget on the calling command, '' when it has none (``contexer issue build``).
    """
    if budget.max_total_usd is not None:
        where = f"{flag}, or max_usd under [agents]" if flag else "max_usd under [agents] in contexer.toml"
        limit = f"The run budget of ${budget.max_total_usd:.2f} ({where})"
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
        "Set input_usd_per_mtok and output_usd_per_mtok under [agents] in contexer.toml (US dollars per million tokens, used for every model), "
        f"or remove the dollar limit: the token limit ([limits] tokens, {tokens} for this run) still applies."
    )


def _named(model: Any) -> str:
    record = capabilities_of(model)
    return f"{record.model} ({record.provider})" if record.provider else record.model
