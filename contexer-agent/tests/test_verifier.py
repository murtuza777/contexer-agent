"""Tests for strict, evidence-based verifier."""

import pytest
from contexer.observer.models import BrowserObservation
from contexer.verification.models import AcceptanceCriterion, GoalAnalysis
from contexer.verification.verifier import Verifier


@pytest.mark.anyio
async def test_verifier_connection_failure():
    verifier = Verifier()
    obs = BrowserObservation(
        url="http://localhost:9999",
        success=False,
        error="Connection refused",
    )
    result = await verifier.verify("Build landing page", obs)
    assert result.passed is False
    assert "offline" in result.reason.lower() or "unreachable" in result.reason.lower()
    assert len(result.failures) >= 1


@pytest.mark.anyio
async def test_verifier_page_errors_failure():
    verifier = Verifier()
    obs = BrowserObservation(
        url="http://localhost:3000",
        success=True,
        page_errors=["TypeError: Cannot read properties of undefined"],
    )
    result = await verifier.verify("Build landing page", obs)
    assert result.passed is False
    assert any("TypeError" in f for f in result.failures)


@pytest.mark.anyio
async def test_verifier_rejects_unrelated_ecommerce_page():
    """Verifier must FAIL if the page is the Contexer landing page instead of an e-commerce page."""
    verifier = Verifier()
    # Simulating what actually happened: localhost:3000 returned Contexer landing page
    obs = BrowserObservation(
        url="http://localhost:3000",
        success=True,
        status_code=200,
        page_title="Contexer | Autonomous Engineering Agent",
        visible_text="Contexer. The autonomous engineering agent that supervises OpenCode.",
        headings=["h1: Contexer", "h2: Architecture"],
        interactive_elements=['button: "Docs"', 'a: "GitHub"'],
    )
    analysis = GoalAnalysis(
        goal="build an interactive landing page for an e-commerce website",
        acceptance_criteria=[
            AcceptanceCriterion(
                id="crit-products",
                description="E-commerce product catalog and pricing are visible",
                verification_method="dom_inspection",
            ),
        ],
    )
    result = await verifier.verify("build an interactive landing page for an e-commerce website", obs, analysis)

    # MUST BE FALSE - Contexer agent page is NOT an e-commerce store!
    assert result.passed is False
    assert len(result.failures) > 0
    assert "e-commerce" in " ".join(result.failures).lower() or "missing" in result.reason.lower()


@pytest.mark.anyio
async def test_verifier_passes_with_real_observable_evidence():
    """Verifier passes when positive observable evidence satisfies the criteria."""
    verifier = Verifier()
    obs = BrowserObservation(
        url="http://localhost:3000",
        success=True,
        status_code=200,
        page_title="TrendyShop | Modern E-Commerce Store",
        visible_text="TrendyShop E-Commerce Storefront. Products on sale. Wireless Headphones $99.",
        headings=["h1: TrendyShop E-Commerce", "h2: Featured Products"],
        interactive_elements=['button: "Add to Cart"', 'button: "Checkout"'],
    )
    analysis = GoalAnalysis(
        goal="build an interactive landing page for an e-commerce website",
        acceptance_criteria=[
            AcceptanceCriterion(
                id="crit-products",
                description="E-commerce product catalog and pricing are visible",
                verification_method="dom_inspection",
            ),
        ],
    )
    result = await verifier.verify("build an interactive landing page for an e-commerce website", obs, analysis)
    assert result.passed is True
    assert len(result.failures) == 0
    assert len(result.evidence) > 0
