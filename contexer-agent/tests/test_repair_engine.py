"""Tests for repair prompt generation."""

from contexer.observer.models import BrowserObservation
from contexer.repair.repair import RepairEngine
from contexer.verification.models import AcceptanceCriteria, VerificationResult


def test_repair_prompt_contains_evidence_and_failures():
    obs = BrowserObservation(
        url="http://localhost:3000",
        page_title="My Home",
        visible_text="Welcome to the site",
        console_errors=["[error] Failed to load resource"],
        page_errors=["ReferenceError: buttonHandler is not defined"],
    )
    res = VerificationResult(
        passed=False,
        reason="Missing CTA button.",
        evidence=["Page title: 'My Home'"],
        failures=["Missing required element: 'Get Started'"],
    )
    criteria = AcceptanceCriteria(
        goal="Add a Get Started button",
        required_text=["Get Started"],
    )

    prompt = RepairEngine.generate_repair_prompt(
        goal="Add a Get Started button",
        observation=obs,
        result=res,
        criteria=criteria,
    )

    assert "Original Goal:" in prompt
    assert "Add a Get Started button" in prompt
    assert "Missing required element: 'Get Started'" in prompt
    assert "Page title: 'My Home'" in prompt
    assert "Failed to load resource" in prompt
    assert "ReferenceError" in prompt
    assert "Fix only the missing or broken functionality" in prompt


def test_repair_prompt_restates_only_the_failed_checks() -> None:
    from contexer.verification.checks import Check, Expectation, Locator, Step
    from contexer.verification.models import AcceptanceCriterion, CriterionResult, GoalAnalysis

    cart_check = Check(
        steps=[Step(action="click", target=Locator(role="button", name="Add to cart"))],
        expect=[Expectation(kind="text", target=Locator(test_id="cart-count"), contains="1")],
    )
    analysis = GoalAnalysis(
        goal="cart",
        acceptance_criteria=[
            AcceptanceCriterion(id="crit-cart", description="Cart count increments", check=cart_check),
            AcceptanceCriterion(
                id="crit-runtime",
                description="No errors",
                check=Check(expect=[Expectation(kind="no_errors")]),
            ),
        ],
    )
    result = VerificationResult(
        passed=False,
        failures=['[crit-cart] executable check FAILED\n  expected: ...\n  actual:   "0"'],
        criteria_results=[
            CriterionResult(criterion_id="crit-cart", description="Cart count increments", passed=False, method="assertion"),
            CriterionResult(criterion_id="crit-runtime", description="No errors", passed=True, method="assertion"),
        ],
    )

    prompt = RepairEngine.generate_repair_prompt(
        goal="cart",
        observation=BrowserObservation(url="http://127.0.0.1:8000/"),
        result=result,
        analysis=analysis,
    )

    assert "Checks That Must Pass" in prompt
    assert 'do:     click button "Add to cart"' in prompt
    assert 'expect: text of [data-testid="cart-count"] contains "1"' in prompt
    assert 'actual:   "0"' in prompt
    assert "[crit-runtime]" not in prompt
