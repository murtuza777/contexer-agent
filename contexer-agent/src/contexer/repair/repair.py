"""Repair prompt generator and failure diagnosis for autonomous self-healing loops."""

from __future__ import annotations

import logging
from typing import Optional

from contexer.llm.base import LLMProvider
from contexer.observer.models import BrowserObservation
from contexer.opencode.models import OpenCodeDiffItem
from contexer.verification.models import GoalAnalysis, VerificationResult, format_contract

logger = logging.getLogger(__name__)


class RepairEngine:
    """Diagnoses failures and constructs targeted, evidence-based repair prompts for OpenCode."""

    def __init__(self, llm_provider: Optional[LLMProvider] = None) -> None:
        self.llm_provider = llm_provider

    async def diagnose_failure(
        self,
        goal: str,
        observation: BrowserObservation,
        result: VerificationResult,
        diffs: list[OpenCodeDiffItem],
    ) -> str:
        """Use LLM to diagnose why the implementation failed and what needs to change."""
        if not self.llm_provider:
            return "Address the failed acceptance criteria by adding the missing components and correcting any runtime issues."

        try:
            diff_summary = "\n".join(
                f"File: {d.file} (+{d.additions}, -{d.deletions})" for d in diffs[:10]
            ) or "No files modified yet."
            failures_str = "\n".join(f"- {f}" for f in result.failures)

            prompt = (
                "You are an expert software diagnostic engineer. Analyze why a web engineering task failed verification.\n\n"
                f"User Goal: {goal}\n\n"
                f"Failed Verification Criteria:\n{failures_str}\n\n"
                f"Recent Code Changes:\n{diff_summary}\n\n"
                f"Observed Page State:\n"
                f"- Page Title: {observation.page_title}\n"
                f"- Interactive Elements: {observation.interactive_elements[:15]}\n"
                f"- Console/Page Errors: {observation.console_errors + observation.page_errors}\n"
                f"- Text Snippet: {observation.visible_text[:800]}\n\n"
                "Provide a concise diagnosis (2-3 bullet points) explaining:\n"
                "1. What is missing or broken\n"
                "2. The exact files or elements that need to be created or modified to fix it\n"
            )
            res = await self.llm_provider.generate(
                prompt=prompt,
                system_instruction="You are a senior debugging engineer. Be direct, concise, and actionable.",
            )
            return res.text.strip()
        except Exception as e:
            logger.debug("LLM diagnosis generation failed: %s", e)
            return "Address the failed acceptance criteria by adding the missing components and correcting any runtime issues."

    @staticmethod
    def generate_repair_prompt(
        goal: str,
        observation: BrowserObservation,
        result: VerificationResult,
        analysis: Optional[GoalAnalysis] = None,
        criteria: Optional[GoalAnalysis] = None,
        scope_instruction: Optional[str] = None,
        diagnosis: Optional[str] = None,
    ) -> str:
        """Generate a structured fix prompt with explicit evidence and instructions."""
        analysis = analysis or criteria
        failures_list = "\n".join(f"- {f}" for f in result.failures) if result.failures else f"- {result.reason}"
        evidence_list = "\n".join(f"- {e}" for e in result.evidence) if result.evidence else "- Page was inspected."

        errors_section = ""
        if observation.console_errors:
            errors_section += "\nConsole Errors:\n" + "\n".join(f"- {err}" for err in observation.console_errors)
        if observation.page_errors:
            errors_section += "\nRuntime Page Errors:\n" + "\n".join(f"- {err}" for err in observation.page_errors)

        diagnosis_section = ""
        if diagnosis:
            diagnosis_section = f"\nDiagnostic Guidance:\n{diagnosis}\n"

        contract_section = ""
        if analysis:
            failed_ids = {r.criterion_id for r in result.criteria_results if not r.passed}
            failed_checks = [c for c in analysis.acceptance_criteria if c.id in failed_ids and c.check]
            if failed_checks:
                contract_section = (
                    "\nChecks That Must Pass (executed verbatim in a real browser; use the exact names, "
                    "texts and data-testid values they reference):\n"
                    f"{format_contract(failed_checks)}\n"
                )

        prefix = f"{scope_instruction}\n\n" if scope_instruction else ""
        return (
            f"{prefix}"
            f"The previous implementation failed automated browser verification.\n\n"
            f"Original Goal:\n{goal}\n\n"
            f"Failed Criteria:\n{failures_list}\n"
            f"{contract_section}"
            f"{diagnosis_section}"
            f"\nObserved Evidence:\n{evidence_list}"
            f"{errors_section}\n\n"
            f"Expected Outcome:\n"
            f"Modify the application code so that the original goal is completely satisfied without runtime errors.\n"
            f"Fix only the missing or broken functionality. Do not modify unrelated parts of the codebase."
        )
