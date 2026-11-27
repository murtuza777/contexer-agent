"""Cost controls (T5.2): one budget for the whole run, a model per agent, an estimate before and the bill after."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from contexer.config.project import ProjectConfigError, load_project_config
from contexer.controller import RunSettings
from contexer.crew.budget import Budget, unenforceable
from contexer.crew.estimate import estimate_run
from contexer.graph import GraphController
from contexer.llm import capabilities
from contexer.llm.capabilities import Fact, ModelCapabilities
from tests.fakes import AgentScript, ScriptedChatModel, calls, submit
from tests.loop_helpers import BROKEN_JS, COUNT_BUG_JS, GOOD_JS, RecordingAgent, contract, copy_todo, fast_runner

pytestmark = pytest.mark.anyio


class PaidAgent(RecordingAgent):
    """A scripted coding agent whose every turn costs money."""

    def __init__(self, turns: list[dict[str, str | None]], cost: float) -> None:
        super().__init__(turns)
        self.cost = cost
        self.budgets: list[float | None] = []

    async def run_turn(self, workdir: Path, prompt: str, **kwargs: Any) -> Any:
        self.budgets.append(kwargs.get("budget_usd"))
        turn = await super().run_turn(workdir, prompt, **kwargs)
        return turn.model_copy(update={"cost_usd": self.cost})


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return copy_todo(tmp_path)


# -- the budget itself ---------------------------------------------------------------------------


def test_a_provider_that_reports_no_price_is_priced_from_the_configured_rates() -> None:
    budget = Budget(max_cost_usd=1.0, input_usd_per_mtok=2.0, output_usd_per_mtok=10.0)
    budget.spend(100_000, 20_000)  # 0.20 + 0.20
    assert budget.cost_usd == pytest.approx(0.40) and budget.estimated
    assert budget.exhausted() == ""
    budget.spend(300_000, 0)  # + 0.60
    assert "cost budget" in budget.exhausted()

    reported = Budget(input_usd_per_mtok=2.0, output_usd_per_mtok=10.0)
    reported.spend(100_000, 20_000, 0.05)  # what the provider says wins over the rates
    assert reported.cost_usd == pytest.approx(0.05) and not reported.estimated

    unknown = Budget()
    unknown.spend(100_000, 20_000)
    assert unknown.cost_usd is None  # no price, no guess


def test_one_budget_covers_the_coding_agent_and_contexers_agents_together() -> None:
    budget = Budget(max_total_usd=1.0, input_usd_per_mtok=2.0, output_usd_per_mtok=10.0)
    budget.spend(100_000, 0)  # 0.20 of Contexer's own
    assert budget.exhausted() == "" and budget.total_left() == pytest.approx(0.80)
    budget.other_usd = 0.85  # what the coding agent has spent
    assert "run budget of $1.00" in budget.exhausted()
    assert budget.total_left() == 0.0
    assert Budget().total_left() is None  # no total, nothing to run out of


def test_a_dollar_limit_that_cannot_be_kept_is_named_with_what_to_set() -> None:
    model = ScriptedChatModel()  # a model nothing is known about: no price
    rates: dict[str, Any] = {"input_usd_per_mtok": 2.0, "output_usd_per_mtok": 10.0}
    assert unenforceable(Budget(max_tokens=10), models=[model], coding_agent="codex") == ""  # no dollar limit, nothing to keep
    assert unenforceable(Budget(max_total_usd=2.0, **rates), models=[model]) == ""

    crew = unenforceable(Budget(max_tokens=1_500_000, max_total_usd=2.0), models=[model])
    assert "run budget of $2.00" in crew and "scripted-model" in crew
    assert "input_usd_per_mtok" in crew and "output_usd_per_mtok" in crew and "[limits] tokens" in crew
    assert "[limits] cost_usd" in unenforceable(Budget(max_cost_usd=2.5), models=[model])

    coding = unenforceable(Budget(max_total_usd=2.0, **rates), coding_agent="codex")
    assert "run budget of $2.00" in coding and "codex reports no cost" in coding and "claude-code" in coding
    # [limits] cost_usd is a limit on Contexer's own agents: the coding agent is not part of it.
    assert unenforceable(Budget(max_cost_usd=2.5, **rates), models=[model], coding_agent="codex") == ""


# -- COST-3: a price per model ---------------------------------------------------------------------


def _listed(monkeypatch: pytest.MonkeyPatch, model: Any, name: str, input_usd: float, output_usd: float, cached_usd: float | None = None) -> Any:
    """``model`` under ``name``, with a record that says what its provider's model list charges."""
    model.model_name = name
    record = ModelCapabilities(
        provider="somewhere",
        model=name,
        input_usd_per_mtok=Fact(input_usd, "catalogue"),
        output_usd_per_mtok=Fact(output_usd, "catalogue"),
        cached_input_usd_per_mtok=Fact(cached_usd, "catalogue" if cached_usd is not None else "assumed"),
    )
    monkeypatch.setitem(capabilities._BUILT, (name, ""), record)
    return model


def test_a_call_is_priced_from_its_own_models_record_and_the_projects_rates_override_it(monkeypatch: pytest.MonkeyPatch) -> None:
    small = _listed(monkeypatch, ScriptedChatModel(), "small-model", 1.0, 2.0)
    large = _listed(monkeypatch, ScriptedChatModel(), "large-model", 10.0, 20.0)
    budget = Budget()
    assert budget.spend(1_000_000, 100_000, model=small) == pytest.approx(1.2)
    assert budget.spend(1_000_000, 100_000, model=large) == pytest.approx(12.0)
    assert budget.cost_usd == pytest.approx(13.2) and budget.estimated

    override = Budget(input_usd_per_mtok=2.0, output_usd_per_mtok=10.0)
    assert override.spend(1_000_000, 0, model=large) == pytest.approx(2.0)

    unknown = Budget()
    assert unknown.spend(1_000_000, 0, model=ScriptedChatModel()) is None and unknown.cost_usd is None  # no price, no guess

    # A dollar limit can be kept when every model that will be called has a price of its own.
    assert unenforceable(Budget(max_total_usd=2.0), models=[small, large]) == ""
    refused = unenforceable(Budget(max_total_usd=2.0), models=[small, ScriptedChatModel()])
    assert "scripted-model" in refused and "small-model" not in refused


async def test_a_run_with_two_models_bills_each_agent_at_its_own_models_price(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    default = _listed(monkeypatch, AgentScript(reviewer=[submit(notes=[])]), "large-model", 10.0, 20.0)
    cheap = _listed(monkeypatch, AgentScript(reviewer=[submit(notes=[])]), "small-model", 1.0, 2.0)
    budget = Budget()  # no rates in the project
    agent = RecordingAgent([{"app.js": COUNT_BUG_JS + "// a\n"}, {"app.js": GOOD_JS + "// done\n"}])
    outcome = await GraphController(
        project, agent, RunSettings(max_repair_rounds=2), runner=fast_runner(), model=default,
        models={"triage": cheap, "reviewer": cheap}, budget=budget,
    ).run(contract(project))  # fmt: skip

    prices = {"planner": (10.0, 20.0), "diagnoser": (10.0, 20.0), "triage": (1.0, 2.0), "reviewer": (1.0, 2.0)}
    assert {a.agent for a in outcome.agents} == set(prices)
    for usage in outcome.agents:
        input_usd, output_usd = prices[usage.agent]
        assert usage.cost_usd == pytest.approx((usage.tokens_in * input_usd + usage.tokens_out * output_usd) / 1_000_000)
    assert outcome.crew_cost_usd == pytest.approx(budget.cost_usd) and outcome.crew_cost_estimated


# -- COST-2: cached input ----------------------------------------------------------------------------


def test_the_cached_part_of_the_input_is_priced_at_the_cached_price(monkeypatch: pytest.MonkeyPatch) -> None:
    caching = _listed(monkeypatch, ScriptedChatModel(), "caching-model", 10.0, 20.0, 1.0)
    budget = Budget()
    assert budget.spend(1_000_000, 0, model=caching, cached_in=800_000) == pytest.approx(0.2 * 10.0 + 0.8 * 1.0)
    assert budget.tokens_in == 1_000_000  # cached tokens are part of the input, not on top of it

    plain = _listed(monkeypatch, ScriptedChatModel(), "plain-model", 10.0, 20.0)
    assert Budget().spend(1_000_000, 0, model=plain, cached_in=800_000) == pytest.approx(10.0)  # no cached price known: the full one
    rated = Budget(input_usd_per_mtok=2.0, output_usd_per_mtok=10.0)  # the project's pair has no cached rate
    assert rated.spend(1_000_000, 0, model=caching, cached_in=800_000) == pytest.approx(2.0)


async def test_cached_tokens_reach_the_transcript_the_trace_and_the_bill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import BaseModel

    from contexer.crew import AgentSpec, run_agent
    from contexer.crew.transcript import read_transcript
    from contexer.evidence.rundir import TRACE_FILE

    class Report(BaseModel):
        summary: str

    reply = calls(("submit", {"summary": "fine"}), tokens=(1000, 10))
    reply.usage_metadata["input_token_details"] = {"cache_read": 800}  # type: ignore[index]
    model = _listed(monkeypatch, ScriptedChatModel(reply), "caching-model", 10.0, 20.0, 1.0)
    budget = Budget()
    spec = AgentSpec(name="tester", system_prompt="You test web apps.", output_schema=Report)
    result = await run_agent(spec, model, [], "Test the shop.", run_dir=tmp_path, budget=budget)

    cost = (200 * 10.0 + 800 * 1.0 + 10 * 20.0) / 1_000_000
    assert result.cost_usd == pytest.approx(cost) and budget.cost_usd == pytest.approx(cost)
    [said] = [line for line in read_transcript(tmp_path / "agents" / "tester.jsonl") if line["event"] == "model"]
    assert (said["tokens_in"], said["tokens_cached"]) == (1000, 800)
    [traced] = [line for line in read_transcript(tmp_path / TRACE_FILE) if line["event"] == "model"]
    assert traced["gen_ai.usage.cache_read.input_tokens"] == 800
    assert traced["contexer.cost_usd"] == pytest.approx(cost) and traced["contexer.cost_estimated"] is True


# -- configuration ---------------------------------------------------------------------------------


def _config(tmp_path: Path, text: str) -> Any:
    (tmp_path / "contexer.toml").write_text(text, encoding="utf-8")
    return load_project_config(tmp_path)


def test_agents_can_each_have_a_model_and_a_step_cap(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        """
[agents]
max_usd = 4.0
input_usd_per_mtok = 2.5
output_usd_per_mtok = 15

[agents.triage]
model = "gpt-5.4-mini"

[agents.reviewer]
provider = "azure"
model = "gpt-5.4-mini"
max_steps = 6

[agents.planner]
max_steps = 5
""",
    )
    assert config.agents.for_agent("planner").max_steps == 5
    assert config.agents.max_usd == 4.0 and config.agents.input_usd_per_mtok == 2.5
    assert config.agents.for_agent("triage").model == "gpt-5.4-mini"
    assert config.agents.for_agent("reviewer").max_steps == 6 and config.agents.for_agent("reviewer").provider == "azure"
    assert config.agents.for_agent("diagnoser").model is None  # not named: the default model, the default cap
    assert load_project_config(tmp_path / "nowhere").agents.max_usd is None


@pytest.mark.parametrize(
    "text",
    [
        "[agents]\nmax_usd = -1\n",
        "[agents.reviewer]\nmax_steps = 0\n",
        '[agents.janitor]\nmodel = "x"\n',
        '[agents.tester]\nprovider = "azure"\n',  # a provider and no model: nothing could be built from it
        '[agents.tester]\nprovider = "nowhere"\nmodel = "x"\n',
    ],
)
def test_a_budget_that_makes_no_sense_or_an_agent_that_does_not_exist_is_refused(tmp_path: Path, text: str) -> None:
    with pytest.raises(ProjectConfigError):
        _config(tmp_path, text)


# -- the run -----------------------------------------------------------------------------------------


async def test_the_run_stops_when_the_one_budget_is_reached_and_keeps_the_best_attempt(project: Path) -> None:
    agent = PaidAgent([{"app.js": COUNT_BUG_JS + "// a\n"}, {"app.js": BROKEN_JS}, {"app.js": GOOD_JS}], cost=0.6)
    budget = Budget(max_total_usd=1.0)
    outcome = await GraphController(project, agent, RunSettings(max_repair_rounds=3), runner=fast_runner(), budget=budget).run(contract(project))

    assert outcome.terminal == "budget_exhausted", outcome.reason
    assert "run budget" in outcome.reason
    assert len(agent.prompts) == 2  # 0.6, then 1.2: no third turn was started
    assert agent.budgets[0] == pytest.approx(1.0) and agent.budgets[1] == pytest.approx(0.4)  # each turn is told what is left
    assert outcome.best_attempt == 1
    assert (project / "app.js").read_text(encoding="utf-8") == COUNT_BUG_JS + "// a\n"  # the best state that was reached
    assert outcome.cost_usd == pytest.approx(1.2)


async def test_what_contexers_agents_spend_counts_against_the_same_budget(project: Path) -> None:
    # Each model call is priced at 10 tokens in and 5 out; at these rates one call costs $0.15.
    budget = Budget(max_total_usd=0.5, input_usd_per_mtok=10_000.0, output_usd_per_mtok=10_000.0)
    agent = PaidAgent([{"app.js": COUNT_BUG_JS + "// a\n"}, {"app.js": COUNT_BUG_JS + "// b\n"}, {"app.js": GOOD_JS}], cost=0.1)
    model = AgentScript()  # Triage and the Diagnoser answer with their defaults
    outcome = await GraphController(
        project, agent, RunSettings(max_repair_rounds=3), runner=fast_runner(), model=model, budget=budget
    ).run(contract(project))

    assert outcome.terminal == "budget_exhausted"
    spent_by_crew = sum(a.cost_usd or 0.0 for a in outcome.agents)
    assert spent_by_crew > 0 and outcome.cost_usd + spent_by_crew >= 0.5
    assert len(agent.prompts) < 3  # the fix in the third turn was never asked for


async def test_each_agent_runs_on_the_model_it_was_given(project: Path) -> None:
    default, cheap = AgentScript(), AgentScript()
    agent = RecordingAgent([{"app.js": COUNT_BUG_JS + "// a\n"}, {"app.js": GOOD_JS + "// done\n"}])
    outcome = await GraphController(
        project, agent, RunSettings(max_repair_rounds=2), runner=fast_runner(), model=default,
        models={"triage": cheap, "reviewer": cheap},
    ).run(contract(project))  # fmt: skip

    assert outcome.terminal == "succeeded"
    assert set(cheap.seen) == {"triage", "reviewer"}
    assert set(default.seen) == {"planner", "diagnoser"}


async def test_the_bill_per_agent_adds_up_to_the_transcripts(project: Path) -> None:
    budget = Budget(input_usd_per_mtok=2.0, output_usd_per_mtok=10.0)
    model = AgentScript(reviewer=[submit(notes=[])])
    agent = RecordingAgent([{"app.js": COUNT_BUG_JS + "// a\n"}, {"app.js": GOOD_JS + "// done\n"}])
    outcome = await GraphController(
        project, agent, RunSettings(max_repair_rounds=2), runner=fast_runner(), model=model, budget=budget
    ).run(contract(project))

    assert {a.agent for a in outcome.agents} == {"planner", "triage", "diagnoser", "reviewer"}
    for usage in outcome.agents:
        rows = [json.loads(line) for line in (Path(outcome.run_dir) / "agents" / f"{usage.agent}.jsonl").read_text(encoding="utf-8").splitlines()]
        ends = [r for r in rows if r.get("event") == "end"]
        assert usage.tokens_in == sum(r["tokens_in"] for r in ends) and usage.tokens_out == sum(r["tokens_out"] for r in ends)
        assert usage.cost_usd == pytest.approx((usage.tokens_in * 2.0 + usage.tokens_out * 10.0) / 1_000_000)
    assert budget.tokens_in == sum(a.tokens_in for a in outcome.agents)
    assert budget.cost_usd == pytest.approx(sum(a.cost_usd or 0.0 for a in outcome.agents))
    saved = json.loads((Path(outcome.run_dir) / "run.json").read_text(encoding="utf-8"))
    assert saved["crew_cost_usd"] == pytest.approx(budget.cost_usd) and saved["crew_cost_estimated"] is True


# -- the estimate ------------------------------------------------------------------------------------


def test_the_estimate_says_what_a_run_can_use_at_most_and_grows_with_the_rounds() -> None:
    small = estimate_run(rounds=0, has_model=True, drafts_checks=False, review=True)
    large = estimate_run(rounds=3, has_model=True, drafts_checks=True, review=True)
    assert 0 < small.model_calls < large.model_calls and small.tokens < large.tokens
    assert small.coding_turns == 1 and large.coding_turns == 4  # the first turn and three rounds; a review's repair uses a round
    none = estimate_run(rounds=2, has_model=False, drafts_checks=False, review=True)
    assert none.model_calls == 0 and none.tokens == 0 and none.coding_turns == 3

    priced = estimate_run(rounds=3, has_model=True, drafts_checks=True, review=True, input_usd_per_mtok=2.0, output_usd_per_mtok=10.0)
    assert priced.cost_usd is not None and priced.cost_usd > 0 and large.cost_usd is None
    line = priced.describe()
    assert "at most" in line and "model call" in line and "$" in line

    # The Planner's calls are in the ceiling, at its step cap, and are not when it is turned off.
    unplanned = estimate_run(rounds=0, has_model=True, drafts_checks=False, review=True, plan=False)
    assert small.model_calls - unplanned.model_calls == 12 and small.tokens > unplanned.tokens
    capped = estimate_run(rounds=0, has_model=True, drafts_checks=False, review=True, planner_steps=4)
    assert capped.model_calls - unplanned.model_calls == 4

    # Each agent's share is priced by whoever knows its model's price; one agent without a price leaves the total unknown.
    asked: list[str] = []

    def by_agent(agent: str, tokens_in: int, tokens_out: int) -> float | None:
        asked.append(agent)
        return None if agent == "nobody" else tokens_in * (1.0 if agent == "triage" else 10.0) / 1_000_000

    per_model = estimate_run(rounds=1, has_model=True, drafts_checks=False, review=False, plan=False, price=by_agent)
    assert asked == ["triage", "diagnoser"]
    assert per_model.cost_usd == pytest.approx((2_500 * 1.0 + 15 * 6_000 * 10.0) / 1_000_000)
    no_price = estimate_run(rounds=1, has_model=True, drafts_checks=False, review=False, plan=False, price=lambda *_: None)
    assert no_price.cost_usd is None
