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


# -- executable checks take precedence over judgment --------------------------------

from contexer.verification.checks import Check, CheckResult, Expectation, ExpectationOutcome, Locator  # noqa: E402
from contexer.verification.runner import CheckRunner  # noqa: E402


class FakeRunner(CheckRunner):
    """Returns scripted pass/fail per criterion instead of driving a browser."""

    def __init__(self, outcomes: dict[str, bool]) -> None:
        super().__init__()
        self.outcomes = outcomes
        self.calls: list[list[str]] = []

    async def run(self, url, checks):  # type: ignore[override]
        self.calls.append([cid for cid, _ in checks])
        results = []
        for cid, check in checks:
            passed = self.outcomes[cid]
            results.append(
                CheckResult(
                    criterion_id=cid,
                    passed=passed,
                    outcomes=[
                        ExpectationOutcome(
                            description=check.expect[0].describe(),
                            passed=passed,
                            actual='"1"' if passed else '"0"',
                        )
                    ],
                )
            )
        return results


LOADED = BrowserObservation(
    url="http://127.0.0.1:8000/",
    success=True,
    status_code=200,
    page_title="Shop",
    visible_text="Shop. Add to cart. Cart 0.",
)


def _checked(cid: str) -> AcceptanceCriterion:
    return AcceptanceCriterion(
        id=cid,
        description=f"{cid} behaviour",
        check=Check(expect=[Expectation(kind="text", target=Locator(test_id="cart-count"), contains="1")]),
    )


@pytest.mark.anyio
async def test_asserted_criteria_never_reach_the_llm(fake_llm) -> None:
    llm = fake_llm()  # no scripted replies: any call is a bug
    runner = FakeRunner({"crit-1": True, "crit-2": True})
    analysis = GoalAnalysis(goal="cart", acceptance_criteria=[_checked("crit-1"), _checked("crit-2")])

    result = await Verifier(llm_provider=llm, runner=runner).verify("cart", LOADED, analysis)

    assert result.passed is True
    assert llm.prompts == []
    assert runner.calls == [["crit-1", "crit-2"]]
    assert [r.method for r in result.criteria_results] == ["assertion", "assertion"]
    assert result.confidence == 1.0
    assert result.summary == "2/2 proven in browser"


@pytest.mark.anyio
async def test_assertion_failure_carries_expected_and_actual() -> None:
    analysis = GoalAnalysis(goal="cart", acceptance_criteria=[_checked("crit-cart")])

    result = await Verifier(runner=FakeRunner({"crit-cart": False})).verify("cart", LOADED, analysis)

    assert result.passed is False
    assert result.confidence == 1.0
    assert result.criteria_results[0].method == "assertion"
    assert result.criteria_results[0].check_result is not None
    assert any('expected: text of [data-testid="cart-count"] contains "1"' in f for f in result.failures)
    assert any('actual:   "0"' in f for f in result.failures)
    assert result.reason.startswith("[crit-cart] expected")


@pytest.mark.anyio
async def test_only_unasserted_criteria_are_judged_by_llm(fake_llm) -> None:
    llm = fake_llm(
        "Here is my verdict:\n```json\n"
        '{"passed": true, "confidence": 0.8, "reason": "looks right",'
        ' "criteria_results": [{"criterion_id": "crit-look", "description": "Modern look",'
        ' "passed": true, "evidence": "Clean layout"}]}\n```'
    )
    analysis = GoalAnalysis(
        goal="cart",
        acceptance_criteria=[
            AcceptanceCriterion(id="crit-look", description="Modern look"),
            _checked("crit-cart"),
        ],
    )

    result = await Verifier(llm_provider=llm, runner=FakeRunner({"crit-cart": True})).verify("cart", LOADED, analysis)

    assert result.passed is True
    assert len(llm.prompts) == 1
    assert "crit-look" in llm.prompts[0] and "crit-cart" not in llm.prompts[0]
    assert [(r.criterion_id, r.method) for r in result.criteria_results] == [
        ("crit-look", "judgment"),
        ("crit-cart", "assertion"),
    ]
    assert result.confidence == 0.8
    assert result.summary == "1/1 proven in browser, 1/1 judged by LLM"


@pytest.mark.anyio
async def test_llm_overall_veto_fails_verification(fake_llm) -> None:
    llm = fake_llm(
        '{"passed": false, "reason": "Page is unrelated to the goal",'
        ' "criteria_results": [{"criterion_id": "crit-look", "passed": true}]}'
    )
    analysis = GoalAnalysis(goal="shop", acceptance_criteria=[AcceptanceCriterion(id="crit-look", description="Shop")])

    result = await Verifier(llm_provider=llm, runner=FakeRunner({})).verify("shop", LOADED, analysis)

    assert result.passed is False
    assert result.reason == "Page is unrelated to the goal"


@pytest.mark.anyio
async def test_unparseable_llm_reply_falls_back_to_labelled_heuristics(fake_llm) -> None:
    llm = fake_llm("I think it is fine!")
    analysis = GoalAnalysis(
        goal="build a shop",
        acceptance_criteria=[AcceptanceCriterion(id="crit-products", description="Product catalog is visible")],
    )

    result = await Verifier(llm_provider=llm, runner=FakeRunner({})).verify("build a shop", LOADED, analysis)

    assert [r.method for r in result.criteria_results] == ["heuristic"]
    assert result.confidence == pytest.approx(0.6)


class BlockingRunner(CheckRunner):
    """crit-blocked cannot perform its steps; crit-broken runs and fails."""

    async def run(self, url, checks):  # type: ignore[override]
        results = []
        for cid, _ in checks:
            if cid == "crit-blocked":
                results.append(CheckResult(criterion_id=cid, passed=False, failed_step="step 1 'click checkbox \"x\"'", blocked=True))
            else:
                results.append(
                    CheckResult(
                        criterion_id=cid,
                        passed=False,
                        outcomes=[ExpectationOutcome(description="count", passed=False, actual='"1"')],
                    )
                )
        return results


@pytest.mark.anyio
async def test_blocked_check_is_inconclusive_not_proof() -> None:
    analysis = GoalAnalysis(goal="todo", acceptance_criteria=[_checked("crit-blocked")])
    result = await Verifier(runner=BlockingRunner()).verify("todo", LOADED, analysis)

    assert result.passed is False
    assert result.confidence == 0.5
    assert result.summary == "0/1 proven in browser (1 blocked)"


@pytest.mark.anyio
async def test_reproduced_failure_outranks_blocked_check() -> None:
    analysis = GoalAnalysis(goal="todo", acceptance_criteria=[_checked("crit-blocked"), _checked("crit-broken")])
    result = await Verifier(runner=BlockingRunner()).verify("todo", LOADED, analysis)

    assert result.confidence == 1.0
    assert result.reason.startswith("[crit-broken]")
