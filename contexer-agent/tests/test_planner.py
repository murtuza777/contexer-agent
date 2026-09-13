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
