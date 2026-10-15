"""Data models for verification, acceptance criteria, and goal analysis."""

from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field

from contexer.verification.checks import Check, CheckResult

# How a criterion's verdict was reached, strongest first:
#   assertion — an executable check ran in a real browser
#   judgment  — an LLM judged it from a DOM/text snapshot
#   heuristic — keyword evidence only (no LLM available)
VerdictMethod = Literal["assertion", "judgment", "heuristic"]

# What the evidence says about a criterion:
#   verified   — every expectation held
#   refuted    — an expectation was observed to fail
#   unverified — nothing could decide (a step could not act on its target)
Verdict = Literal["verified", "refuted", "unverified"]


class AcceptanceCriterion(BaseModel):
    """An individual verifiable condition derived dynamically from a user goal."""

    id: str
    description: str
    verification_method: str = "dom_inspection"  # e.g. "dom_inspection", "visual_check", "interactive_test", "console_check"
    check: Optional[Check] = None


class GoalAnalysis(BaseModel):
    """Structured analysis of a user goal and its acceptance criteria."""

    goal: str
    summary: str = ""
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    # Who wrote the criteria: the LLM, the rule-based fallback, or the caller.
    generated_by: Literal["llm", "rules", "user"] = "user"
    # Backward-compatible fields
    required_text: list[str] = Field(default_factory=list)
    expected_title: Optional[str] = None
    disallow_console_errors: bool = True


# Backward compatibility alias
AcceptanceCriteria = GoalAnalysis


def format_contract(criteria: list[AcceptanceCriterion]) -> str:
    """Render criteria and their executable checks as the coding agent's contract."""
    lines: list[str] = []
    for c in criteria:
        lines.append(f"- [{c.id}] {c.description}")
        if c.check:
            lines.extend(f"    {line}" for line in c.check.describe_lines())
    return "\n".join(lines)


class CriterionResult(BaseModel):
    """Evaluation result for an individual acceptance criterion."""

    criterion_id: str
    description: str
    passed: bool
    evidence: str = ""
    method: VerdictMethod = "judgment"
    check_result: Optional[CheckResult] = None

    @property
    def verdict(self) -> Verdict:
        if self.passed:
            return "verified"
        # A check that never reached its expectations (step could not act,
        # navigation or the browser failed) observed nothing to refute.
        if self.check_result is not None and (self.check_result.blocked or self.check_result.failed_step):
            return "unverified"
        return "refuted"

    @property
    def proven(self) -> bool:
        """Decided by executing a check in a browser, not by opinion."""
        return self.method == "assertion"


class VerificationResult(BaseModel):
    """Structured result of browser and semantic verification."""

    passed: bool
    confidence: float = 1.0
    criteria_results: list[CriterionResult] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    reason: str = ""
    summary: str = ""
