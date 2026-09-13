"""Tests for GoalAnalyzer ensuring dynamic, goal-specific criteria generation across distinct domains."""

import pytest
from contexer.workflow.criteria import GoalAnalyzer


@pytest.mark.anyio
async def test_three_distinct_goals_produce_different_criteria():
    """GoalAnalyzer must produce distinctly different criteria for unrelated goals."""
    analyzer = GoalAnalyzer()

    # Goal A: E-commerce
    analysis_a = await analyzer.analyze("build an interactive landing page for an e-commerce website")
    crit_a_text = " ".join(c.description.lower() for c in analysis_a.acceptance_criteria)
    assert any(term in crit_a_text for term in ("e-commerce", "product", "cart", "catalog", "pricing"))

    # Goal B: Dark mode
    analysis_b = await analyzer.analyze("add a dark mode toggle to the navigation")
    crit_b_text = " ".join(c.description.lower() for c in analysis_b.acceptance_criteria)
    assert any(term in crit_b_text for term in ("dark mode", "theme", "toggle"))

    # Goal C: Contact form
    analysis_c = await analyzer.analyze("add a contact form with email validation")
    crit_c_text = " ".join(c.description.lower() for c in analysis_c.acceptance_criteria)
    assert any(term in crit_c_text for term in ("form", "contact", "input", "submission"))

    # Crucial assertion: All three must have different descriptions
    assert crit_a_text != crit_b_text
    assert crit_b_text != crit_c_text
    assert crit_a_text != crit_c_text


@pytest.mark.anyio
async def test_no_hardcoded_get_started_assumption():
    """GoalAnalyzer must never insert 'Get Started' unless specifically requested."""
    analyzer = GoalAnalyzer()
    analysis = await analyzer.analyze("create a snake game in javascript")
    crit_text = " ".join(c.description for c in analysis.acceptance_criteria)
    assert "Get Started" not in crit_text
