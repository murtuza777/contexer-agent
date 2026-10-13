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


# -- executable checks --------------------------------------------------------------

import json  # noqa: E402

from contexer.workflow.criteria import RUNTIME_CRITERION_ID, _quoted_ui_text  # noqa: E402
from contexer.workflow.inspector import RepositoryInspector  # noqa: E402

LLM_CRITERIA = {
    "summary": "Shopping cart",
    "acceptance_criteria": [
        {
            "id": "crit-add",
            "description": "Adding a product increments the cart badge",
            "verification_method": "interactive_test",
            "check": {
                "steps": [{"action": "click", "target": {"role": "button", "name": "Add to cart"}}],
                "expect": [{"kind": "text", "target": {"test_id": "cart-count"}, "contains": 1, "changed": True}],
            },
        },
        {
            "id": "crit-count",
            "description": "Cart badge starts at zero",
            "check": {"expect": [{"kind": "text", "target": {"test_id": "cart-count"}, "equals": "0"}]},
        },
        {
            "id": "crit-bad",
            "description": "Cart drawer opens",
            "check": {"steps": [], "expect": [{"kind": "visible", "target": {"role": "drawer"}}]},
        },
        {"id": "crit-look", "description": "Layout looks polished"},
        {"description": ""},
    ],
}


@pytest.mark.anyio
async def test_llm_checks_are_validated_per_criterion(fake_llm) -> None:
    reply = "Sure! Here are the criteria:\n```json\n" + json.dumps(LLM_CRITERIA) + "\n```\nLet me know."
    llm = fake_llm(reply)
    analysis = await GoalAnalyzer(llm_provider=llm).analyze("add a shopping cart")

    assert len(llm.prompts) == 1  # 2 of 4 criteria executable meets the coverage bar
    by_id = {c.id: c for c in analysis.acceptance_criteria}
    assert list(by_id) == ["crit-add", "crit-count", "crit-bad", "crit-look", RUNTIME_CRITERION_ID]

    add = by_id["crit-add"].check
    assert add is not None
    assert add.steps[0].target is not None and add.steps[0].target.name == "Add to cart"
    assert add.expect[0].contains == "1"

    assert by_id["crit-bad"].check is None  # unknown role "drawer": dropped, criterion kept for judgment
    assert by_id["crit-look"].check is None
    runtime = by_id[RUNTIME_CRITERION_ID].check
    assert runtime is not None and runtime.expect[0].kind == "no_errors"


@pytest.mark.anyio
async def test_runtime_check_not_duplicated_when_model_provides_one(fake_llm) -> None:
    reply = json.dumps({
        "acceptance_criteria": [
            {"id": "crit-clean", "description": "No errors", "check": {"expect": [{"kind": "no_errors"}]}},
        ]
    })
    analysis = await GoalAnalyzer(llm_provider=fake_llm(reply)).analyze("anything")
    assert [c.id for c in analysis.acceptance_criteria] == ["crit-clean"]


@pytest.mark.anyio
async def test_analysis_prompt_teaches_the_check_dsl(fake_llm) -> None:
    llm = fake_llm(json.dumps(LLM_CRITERIA))
    await GoalAnalyzer(llm_provider=llm).analyze("add a shopping cart")
    assert "add a shopping cart" in llm.prompts[0]
    assert '"kind": "no_errors"' in llm.prompts[0]
    assert "contract" in llm.prompts[0]


@pytest.mark.anyio
async def test_rule_based_analysis_compiles_quoted_ui_text_into_checks() -> None:
    analysis = await GoalAnalyzer().analyze("Create a landing page with a 'Get Started' button and a \"Pricing\" link.")
    by_id = {c.id: c for c in analysis.acceptance_criteria}

    runtime = by_id[RUNTIME_CRITERION_ID].check
    assert runtime is not None and runtime.expect[0].kind == "no_errors"
    button = by_id["crit-text-1"].check
    assert button is not None and button.expect[0].describe() == 'button "Get Started" is visible'
    link = by_id["crit-text-2"].check
    assert link is not None and link.expect[0].describe() == 'link "Pricing" is visible'
    assert analysis.required_text == ["Get Started", "Pricing"]


def test_apostrophes_are_not_quoted_ui_text() -> None:
    assert _quoted_ui_text("Don't break the user's cart") == []
    assert _quoted_ui_text("show 'Sold out' when stock is 0") == [("Sold out", None)]


@pytest.mark.anyio
async def test_existing_ui_grounds_the_prompt(fake_llm) -> None:
    llm = fake_llm(json.dumps(LLM_CRITERIA), json.dumps(LLM_CRITERIA))
    snapshot = '- button "Add task"\n- [data-testid="remaining-count"] text="0"'

    grounded = await GoalAnalyzer(llm_provider=llm).analyze("track remaining tasks", ui_snapshot=snapshot)
    await GoalAnalyzer(llm_provider=llm).analyze("track remaining tasks")

    assert snapshot in llm.prompts[0]
    assert "MUST be located exactly" in llm.prompts[0]
    assert "no rendered UI yet" in llm.prompts[1]
    assert grounded.generated_by == "llm"
    assert (await GoalAnalyzer().analyze("anything")).generated_by == "rules"


@pytest.mark.anyio
async def test_source_excerpt_is_offered_for_locators_only(fake_llm, tmp_path) -> None:
    (tmp_path / "index.html").write_text("<script>btn.setAttribute('aria-label','Complete '+v)</script>")
    llm = fake_llm(json.dumps(LLM_CRITERIA))
    await GoalAnalyzer(llm_provider=llm).analyze("mark tasks complete", RepositoryInspector().inspect(tmp_path))
    assert "aria-label','Complete '+v" in llm.prompts[0]
    assert "never from this code" in llm.prompts[0]


NO_CHECKS = json.dumps({"acceptance_criteria": [{"id": "crit-1", "description": "Tasks can be added"}]})


@pytest.mark.anyio
async def test_retries_once_when_router_picks_a_model_that_ignores_the_format(fake_llm) -> None:
    llm = fake_llm("User Safety: safe", json.dumps(LLM_CRITERIA))  # observed from openrouter/free
    analysis = await GoalAnalyzer(llm_provider=llm).analyze("add a shopping cart")
    assert len(llm.prompts) == 2
    assert analysis.generated_by == "llm"
    assert analysis.acceptance_criteria[0].id == "crit-add"


@pytest.mark.anyio
async def test_retries_when_reply_has_no_executable_checks_and_keeps_the_better_one(fake_llm) -> None:
    llm = fake_llm(NO_CHECKS, json.dumps(LLM_CRITERIA))
    analysis = await GoalAnalyzer(llm_provider=llm).analyze("add a shopping cart")
    assert len(llm.prompts) == 2
    assert analysis.acceptance_criteria[0].check is not None

    llm = fake_llm(NO_CHECKS, "User Safety: safe")
    analysis = await GoalAnalyzer(llm_provider=llm).analyze("add tasks")
    assert analysis.generated_by == "llm"  # judged criteria beat rule-based guesses
    assert [c.id for c in analysis.acceptance_criteria] == ["crit-1", RUNTIME_CRITERION_ID]


@pytest.mark.anyio
async def test_does_not_retry_a_rate_limited_api(fake_llm) -> None:
    llm = fake_llm(RuntimeError("Error code: 429 - rate limit exceeded"), json.dumps(LLM_CRITERIA))
    analysis = await GoalAnalyzer(llm_provider=llm).analyze("add a shopping cart")
    assert len(llm.prompts) == 1
    assert analysis.generated_by == "rules"


@pytest.mark.anyio
async def test_retries_when_only_trivial_criteria_are_executable(fake_llm) -> None:
    mostly_judged = json.dumps({
        "acceptance_criteria": [
            {"id": "crit-1", "description": "Tasks can be added"},
            {"id": "crit-2", "description": "Tasks can be completed"},
            {"id": "crit-3", "description": "Remaining count updates"},
            {"id": "crit-4", "description": "Starts empty",
             "check": {"expect": [{"kind": "text", "target": {"test_id": "remaining-count"}, "contains": "0"}]}},
        ]
    })
    llm = fake_llm(mostly_judged, json.dumps(LLM_CRITERIA))
    analysis = await GoalAnalyzer(llm_provider=llm).analyze("todo list")
    assert len(llm.prompts) == 2
    assert analysis.acceptance_criteria[0].id == "crit-add"
