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
