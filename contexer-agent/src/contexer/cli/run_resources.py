"""What a run works with and what it cost: the coding agent, the models of Contexer's agents, the budget.

``contexer run``, ``contexer test`` and the issue flow all choose these the same way, so the choosing is
here and not in any one command. Nothing in this module starts a run.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from contexer.agents import CodingAgentAdapter
from contexer.config.project import (
    CREW_AGENTS,
    AgentSettings,
    ProjectConfig,
)
from contexer.controller import RunOutcome, RunSettings
from contexer.crew.budget import DEFAULT_MAX_TOKENS, Budget
from contexer.crew.estimate import RunEstimate, estimate_run


def crew_model(project: Path, on_refused: Callable[[str], None] | None = None) -> Any:
    """The model for Contexer's own agents (Intent, Triage, Diagnoser), or None when none is configured or usable.

    A model that is configured and cannot call tools is refused, and ``on_refused`` is told why:
    without that the run went on under rules and nothing said the model had been set aside.
    """
    from contexer.cli.test_cli import build_model
    from contexer.llm.base import LLMError
    from contexer.llm.chat import ToolCallingError

    try:
        return build_model(project)
    except ToolCallingError as exc:
        if on_refused is not None:
            on_refused(str(exc))
        return None
    except (LLMError, ValueError):
        return None


def run_budget(config: ProjectConfig, max_usd: float | None = None) -> Budget:
    """The budget of one run: the token limit, the project's rates, and the one budget in dollars (the flag wins)."""
    return Budget(
        max_tokens=config.limits.tokens or DEFAULT_MAX_TOKENS,
        max_cost_usd=config.limits.cost_usd,
        max_total_usd=max_usd if max_usd is not None else config.agents.max_usd,
        input_usd_per_mtok=config.agents.input_usd_per_mtok,
        output_usd_per_mtok=config.agents.output_usd_per_mtok,
    )


class AgentSettingError(ValueError):
    """A setting under ``[agents.<name>]`` in contexer.toml that cannot be applied."""


def crew_models(
    project: Path,
    config: ProjectConfig,
    *,
    default_provider: str | None = None,
    agents: tuple[str, ...] = CREW_AGENTS,
) -> dict[str, Any]:
    """A model for each of ``agents`` the project names one for; the others use the default.

    A model that cannot be built raises :class:`AgentSettingError`. It used to be a warning and
    the default model: a project that asked for a cheap model was then billed for the other one.
    """
    from contexer.cli import test_cli
    from contexer.llm.base import LLMError

    models: dict[str, Any] = {}
    for name in agents:
        chosen = config.agents.for_agent(name)
        if not chosen.model:
            continue
        try:
            models[name] = test_cli.build_model(project, chosen.provider or default_provider, chosen.model)
        except (LLMError, ValueError) as exc:
            raise AgentSettingError(
                f"[agents.{name}] in contexer.toml names the model '{chosen.model}', which cannot be used: {exc}"
            ) from exc
    return models


def bill_line(outcome: RunOutcome) -> str:
    """What Contexer's own agents used, per agent, and what it cost when that is known. '' when none ran."""
    if not outcome.agents:
        return ""
    parts = [f"{a.agent} {a.tokens_in + a.tokens_out:,} tokens" for a in outcome.agents]
    # An agent that used tokens and has no cost: its model has no known price. It is named, never counted as 0.
    unpriced = [a.agent for a in outcome.agents if a.cost_usd is None and a.tokens_in + a.tokens_out > 0]
    if outcome.crew_cost_usd is None:
        cost = "cost unknown (no price is known for the model; set input_usd_per_mtok and output_usd_per_mtok under [agents] to see it)"
    else:
        cost = f"${outcome.crew_cost_usd:.2f}" + (" estimated from token counts and prices per token" if outcome.crew_cost_estimated else "")
        if unpriced:
            cost += f" · {', '.join(unpriced)}'s cost is unknown and not in that figure"
    return " · ".join(parts) + f" · {cost}"


def coding_cost(outcome: RunOutcome) -> float | None:
    """What the coding agent cost, or None when a turn reported no cost: the figure is then not known, and it is not 0."""
    return None if any(a.agent.cost_usd is None for a in outcome.attempts) else outcome.cost_usd


def coding_spend(outcome: RunOutcome) -> str:
    """What the coding agent spent, for the summary. A turn that reported no cost is said, never shown as $0.00."""
    silent = sum(1 for a in outcome.attempts if a.agent.cost_usd is None)
    if not silent:
        return f"${outcome.cost_usd:.2f} agent spend" if outcome.cost_usd else ""
    if silent == len(outcome.attempts):
        return "coding agent cost unknown (no turn reported one)"
    return f"${outcome.cost_usd:.2f} agent spend · {silent} turn{'s' if silent != 1 else ''} with no cost reported"


def _run_budget_note(budget: Budget | None) -> str:
    if budget is None or budget.max_total_usd is None:
        return ""
    return f" · one budget of ${budget.max_total_usd:.2f} for the coding agent and Contexer's agents"


def _estimate(
    settings: RunSettings,
    budget: Budget | None,
    has_model: bool,
    drafts_checks: bool,
    model: Any = None,
    models: dict[str, Any] | None = None,
) -> RunEstimate:
    """The ceiling for this run. Each agent's share is priced as its calls will be: on the model it runs on."""

    def price(agent: str, tokens_in: int, tokens_out: int) -> float | None:
        return budget.price(tokens_in, tokens_out, (models or {}).get(agent) or model) if budget is not None else None

    return estimate_run(
        rounds=settings.max_repair_rounds,
        has_model=has_model,
        drafts_checks=drafts_checks,
        review=settings.review,
        plan=settings.plan,
        planner_steps=settings.agent_steps.get("planner", 12),
        diagnoser_steps=settings.agent_steps.get("diagnoser", 15),
        reviewer_steps=settings.agent_steps.get("reviewer", 12),
        price=price,
    )


def _limits_line(agent: CodingAgentAdapter, settings: RunSettings) -> str:
    limits = f"up to {settings.max_repair_rounds} repair round(s)"
    if settings.budget_usd:
        # Codex and OpenCode report no cost: the round and time limits bound their runs instead.
        limits += (
            f" · no spending limit ({agent.name} reports no cost)"
            if not agent.reports_cost
            else f" · budget ${settings.budget_usd:.2f}"
        )
    return limits


def choose_agent(project: AgentSettings, flag_name: str | None, flag_model: str | None) -> tuple[str, str | None]:
    """Coding agent and model: --agent/--model, then [agent] in contexer.toml, then `contexer setup`, then Claude Code."""
    set_in_project = project.model_fields_set
    name = (
        flag_name
        or (project.name if "name" in set_in_project else None)
        or os.environ.get("CONTEXER_AGENT")
        or project.name
    )
    model = flag_model or project.model
    if model is None and name == os.environ.get("CONTEXER_AGENT"):
        model = os.environ.get("CONTEXER_AGENT_MODEL")  # saved together with that agent
    return name, model


_RATE_LIMITED = ("rate limit", "too many requests", "429")


_ACCOUNT_PROBLEMS = (
    "credit balance",
    "credits",
    "unauthorized",
    "401",
    "authentication",
    "api key",
    "not logged in",
    "login",
)


def agent_hint(outcome: RunOutcome) -> str | None:
    """What to do when the coding agent itself could not run (no credit, not logged in)."""
    reason = " ".join([outcome.reason, *(a.agent.error or "" for a in outcome.attempts)]).lower()
    again = f"`contexer run --contract {outcome.contract_id}`"
    if "free-models-per-day" in reason:
        return (
            "OpenRouter's daily free-model requests ran out (the count resets at 00:00 UTC). Run "
            f"{again} then, buy $10 of credit for 1,000 a day, or `contexer setup` another provider."
        )
    if any(limit in reason for limit in _RATE_LIMITED):
        return f"the model's provider is rate-limiting requests. Wait a minute, then {again} continues from the approved checks."
    if outcome.terminal != "agent_error":
        return None
    if not any(problem in reason for problem in _ACCOUNT_PROBLEMS):
        return None
    if os.environ.get("OPENROUTER_API_KEY") and shutil.which("opencode"):
        return "the agent's account cannot run it; `--agent opencode` runs it on your OpenRouter key's free models."
    if os.environ.get("OPENROUTER_API_KEY"):
        return (
            "the agent's account cannot run it. Install OpenCode (npm i -g opencode-ai) and use "
            "`--agent opencode` to run it on your OpenRouter key's free models."
        )
    return "the agent's account cannot run it: log in to it, add credit, or choose another with --agent."
