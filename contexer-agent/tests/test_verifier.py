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


@pytest.mark.anyio
async def test_verifier_distinct_goals_evaluated_accurately():
    """Verify distinct user goals produce appropriate rejection/acceptance without hardcoding."""
    verifier = Verifier()

    # Observation of a contact form
    contact_obs = BrowserObservation(
        url="http://localhost:3000",
        success=True,
        status_code=200,
        page_title="Contact Us",
        visible_text="Get in touch with our team. Send message. Contact form.",
        headings=["h1: Contact Us"],
        interactive_elements=['form: "Contact Form"', 'input: "Email"', 'button: "Send Message"'],
        html='<form id="contact-form"><input type="email" placeholder="Email"/><button type="submit">Send Message</button></form>',
    )

    dark_mode_analysis = GoalAnalysis(
        goal="add dark mode toggle to the website",
        acceptance_criteria=[
            AcceptanceCriterion(
                id="crit-darkmode",
                description="Dark mode toggle button exists",
                verification_method="dom_inspection",
            ),
        ],
    )

    # Must FAIL because contact form is not dark mode
    dark_result = await verifier.verify("add dark mode toggle to the website", contact_obs, dark_mode_analysis)
    assert dark_result.passed is False

    contact_analysis = GoalAnalysis(
        goal="add a contact form",
        acceptance_criteria=[
            AcceptanceCriterion(
                id="crit-contact",
                description="Contact form and submit button exist",
                verification_method="dom_inspection",
            ),
        ],
    )

    # Must PASS because contact form satisfies contact criteria
    contact_result = await verifier.verify("add a contact form", contact_obs, contact_analysis)
    assert contact_result.passed is True
