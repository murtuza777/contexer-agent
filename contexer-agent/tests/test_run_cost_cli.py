"""Cost controls at the command line (T5.2): the estimate before a run, the models per agent, the bill after."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from contexer.cli import app
from contexer.cli.run_cli import bill_line, crew_models, run_budget
from contexer.config.project import load_project_config
from contexer.controller import RunOutcome
from contexer.evidence.test_report import AgentUsage
from tests.loop_helpers import GOOD_JS, copy_todo

TOML = """
[agents]
max_usd = 3.0
input_usd_per_mtok = 2.0
output_usd_per_mtok = 10.0

[agents.triage]
model = "small-model"

[agents.reviewer]
provider = "azure"
model = "small-model"
max_steps = 6
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    target = copy_todo(tmp_path)
    (target / "contexer.toml").write_text(TOML, encoding="utf-8")
    return target


def test_the_budget_is_built_from_the_project_and_the_flag_wins(project: Path) -> None:
    config = load_project_config(project)
    budget = run_budget(config, None)
    assert (budget.max_total_usd, budget.input_usd_per_mtok, budget.output_usd_per_mtok) == (3.0, 2.0, 10.0)
    assert budget.max_tokens  # the token limit keeps its default
    assert run_budget(config, 1.5).max_total_usd == 1.5


def test_only_the_agents_the_project_names_get_their_own_model(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[tuple[str | None, str | None]] = []

    def fake_build(_project: Path, provider: str | None = None, model: str | None = None) -> Any:
        built.append((provider, model))
        return f"model:{provider}:{model}"

    monkeypatch.setattr("contexer.cli.test_cli.build_model", fake_build)
    models = crew_models(project, load_project_config(project), default_provider="azure")
    assert set(models) == {"triage", "reviewer"}
    assert sorted(built) == [("azure", "small-model"), ("azure", "small-model")]  # triage takes the default provider


def test_a_model_that_cannot_be_built_is_said_and_the_default_is_used(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_project: Path, provider: str | None = None, model: str | None = None) -> Any:
        raise ValueError(f"no deployment named {model}")

    monkeypatch.setattr("contexer.cli.test_cli.build_model", broken)
    problems: list[str] = []
    assert crew_models(project, load_project_config(project), default_provider="azure", on_problem=problems.append) == {}
    assert len(problems) == 2 and "small-model" in problems[0] and "triage" in problems[0]


def test_the_bill_names_each_agent_and_says_when_it_is_an_estimate() -> None:
    outcome = RunOutcome(
        run_id="r", contract_id="c", agent="scripted", terminal="succeeded", cost_usd=0.85,
        agents=[
            AgentUsage(agent="intent", steps=1, tokens_in=3346, tokens_out=523, cost_usd=0.0119),
            AgentUsage(agent="reviewer", steps=2, tokens_in=5250, tokens_out=121, cost_usd=0.0117),
        ],
        crew_cost_usd=0.0236, crew_cost_estimated=True,
    )  # fmt: skip
    line = bill_line(outcome)
    assert "intent 3,869 tokens" in line and "reviewer 5,371 tokens" in line
    assert "$0.02" in line and "estimated" in line
    unknown = outcome.model_copy(update={"crew_cost_usd": None, "crew_cost_estimated": False})
    assert "cost unknown" in bill_line(unknown)
    assert bill_line(outcome.model_copy(update={"agents": []})) == ""


def test_a_run_says_what_it_can_use_at_most_before_it_starts(project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("contexer.cli.run_cli.crew_model", lambda *_a, **_k: None)
    turns = tmp_path / "turns.json"
    turns.write_text(json.dumps([{"app.js": GOOD_JS + "// x\n"}]), encoding="utf-8")
    result = CliRunner().invoke(
        app,
        ["run", "--contract", "todo-basics", "--dir", str(project), "--engine", "graph", "--agent", "scripted", "--model", str(turns), "--yes"],
    )
    assert result.exit_code == 0, result.output
    shown = " ".join(result.output.split())
    assert "at most 3 coding-agent turn(s)" in shown  # two repair rounds by default
    assert "one budget of $3.00" in shown


def test_the_summary_says_what_the_review_found_not_only_how_many() -> None:
    from rich.console import Console

    from contexer.cli.run_cli import _render
    from contexer.crew.reviewer import ReviewNote

    notes = [
        ReviewNote(file="src/Symptoms.tsx", line=41, severity="high", category="logic", explanation="The delete button no longer asks for confirmation."),
        ReviewNote(file="app.js", line=3, severity="low", category="debug", explanation="Leftover debug code.", source="scan", backed=True),
    ]
    outcome = RunOutcome(run_id="r", contract_id="c", agent="scripted", terminal="succeeded", engine="graph", review=notes, run_dir=".")
    console = Console(record=True, width=110, force_terminal=False, color_system=None)
    _render(console, outcome)
    text = console.export_text()
    assert "Review" in text and "src/Symptoms.tsx:41" in text and "no longer asks for confirmation" in text
    assert text.index("high") < text.index("low")  # the one that needs a person first
