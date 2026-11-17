"""A budget for Contexer's own agents: one per run, shared by every agent in it.

Step limits bound one agent. They do not bound a run: an Intent agent, a
Tester and a Diagnoser each have their own, and a compromised or confused
model can use all of them. The budget counts what the whole run has spent
and ``run_agent`` asks it before every model call.

Tokens are always counted. Cost is counted when the provider reports a price
per call; a cost limit on a provider that reports none never triggers, which
is why the token limit is the one with a default.
"""

from __future__ import annotations

from typing import Optional

# Tokens (in and out together) one run may use unless the project or the command says otherwise.
# A 40-step Tester run on a small app uses about 230,000.
DEFAULT_MAX_TOKENS = 1_500_000


class Budget:
    """What a run may spend, and what it has spent so far."""

    def __init__(self, max_tokens: Optional[int] = None, max_cost_usd: Optional[float] = None) -> None:
        self.max_tokens = max_tokens
        self.max_cost_usd = max_cost_usd
        self.tokens_in = 0
        self.tokens_out = 0
        self.cost_usd: Optional[float] = None

    @property
    def tokens(self) -> int:
        return self.tokens_in + self.tokens_out

    def spend(self, tokens_in: int, tokens_out: int, cost_usd: Optional[float] = None) -> None:
        self.tokens_in += max(0, tokens_in)
        self.tokens_out += max(0, tokens_out)
        if cost_usd is not None:
            self.cost_usd = (self.cost_usd or 0.0) + cost_usd

    def exhausted(self) -> str:
        """Why no further model call may be made, or '' while there is budget left."""
        if self.max_tokens is not None and self.tokens >= self.max_tokens:
            return f"the token budget of {self.max_tokens:,} is used up ({self.tokens:,} tokens spent)"
        if self.max_cost_usd is not None and self.cost_usd is not None and self.cost_usd >= self.max_cost_usd:
            return f"the cost budget of ${self.max_cost_usd:.2f} is used up (${self.cost_usd:.2f} spent)"
        return ""
