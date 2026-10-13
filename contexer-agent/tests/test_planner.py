"""Tests for EngineeringPlanner."""

import pytest
from pathlib import Path
from contexer.workflow.criteria import GoalAnalyzer
from contexer.workflow.inspector import RepositoryInspector
from contexer.workflow.planner import EngineeringPlanner


@pytest.mark.anyio
async def test_planner_creates_structured_plan(tmp_path: Path):
    """Planner must formulate actionable steps for a given goal and repo context."""
    (tmp_path / "index.html").write_text("<html><body></body></html>")

    inspector = RepositoryInspector()
    ctx = inspector.inspect(tmp_path)

    analyzer = GoalAnalyzer()
    analysis = await analyzer.analyze("add a dark mode toggle to the dashboard", ctx)

    planner = EngineeringPlanner()
    plan = await planner.create_plan("add a dark mode toggle to the dashboard", ctx, analysis)

    assert len(plan.steps) >= 2
    assert plan.approach
    assert any("dark mode" in s.title.lower() or "dark mode" in s.description.lower() for s in plan.steps)


@pytest.mark.anyio
async def test_planner_parses_llm_plan_wrapped_in_prose(fake_llm, tmp_path: Path):
    reply = (
        "Here's the plan you asked for:\n"
        '{"approach": "Add a counter", "steps": [{"step_number": 1, "title": "Counter", '
        '"description": "Render it", "target_files": ["index.html"]}]}'
    )
    ctx = RepositoryInspector().inspect(tmp_path)
    analysis = await GoalAnalyzer().analyze("add a counter", ctx)
    plan = await EngineeringPlanner(llm_provider=fake_llm(reply)).create_plan("add a counter", ctx, analysis)
    assert plan.approach == "Add a counter"
    assert [s.target_files for s in plan.steps] == [["index.html"]]
