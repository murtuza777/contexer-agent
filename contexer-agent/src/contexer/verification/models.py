"""Data models for verification, acceptance criteria, and goal analysis."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class AcceptanceCriterion(BaseModel):
    """An individual verifiable condition derived dynamically from a user goal."""

    id: str
    description: str
    verification_method: str = "dom_inspection"  # e.g. "dom_inspection", "visual_check", "interactive_test", "console_check"


class GoalAnalysis(BaseModel):
    """Structured analysis of a user goal and its acceptance criteria."""

    goal: str
    summary: str = ""
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    # Backward-compatible fields
    required_text: list[str] = Field(default_factory=list)
    expected_title: Optional[str] = None
    disallow_console_errors: bool = True


# Backward compatibility alias
AcceptanceCriteria = GoalAnalysis


class CriterionResult(BaseModel):
    """Evaluation result for an individual acceptance criterion."""

    criterion_id: str
    description: str
    passed: bool
    evidence: str = ""


class VerificationResult(BaseModel):
    """Structured result of browser and semantic verification."""

    passed: bool
    confidence: float = 1.0
    criteria_results: list[CriterionResult] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    reason: str = ""
    summary: str = ""
