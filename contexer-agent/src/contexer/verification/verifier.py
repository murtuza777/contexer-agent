"""Strict, evidence-based verification of browser observations against dynamic acceptance criteria."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Optional

from contexer.config.settings import load_config
from contexer.llm.base import LLMProvider
from contexer.llm.factory import create_llm_provider
from contexer.observer.models import BrowserObservation
from contexer.verification.models import (
    CriterionResult,
    GoalAnalysis,
    VerificationResult,
)

if TYPE_CHECKING:
    from contexer.workflow.inspector import RepositoryContext

logger = logging.getLogger(__name__)


class Verifier:
    """Evaluates whether a running web application satisfies a given user goal with verifiable evidence."""

    def __init__(self, llm_provider: Optional[LLMProvider] = None) -> None:
        if llm_provider is None:
            try:
                cfg = load_config()
                if cfg.openrouter_api_key:
                    llm_provider = create_llm_provider(cfg)
            except Exception as e:
                logger.debug("Could not auto-create LLM provider for Verifier: %s", e)
        self.llm_provider = llm_provider

    async def verify(
        self,
        goal: str,
        observation: BrowserObservation,
        analysis: Optional[GoalAnalysis] = None,
        repo_context: Optional[RepositoryContext] = None,
    ) -> VerificationResult:
        """Run strict, evidence-based verification against acceptance criteria."""
        evidence: list[str] = []
        failures: list[str] = []

        # 1. Connectivity & HTTP Status Check
        if not observation.success:
            err = observation.error or "Application was not reachable."
            return VerificationResult(
                passed=False,
                confidence=1.0,
                reason=f"Application offline or unreachable: {err}",
                evidence=[],
                failures=[err],
                summary="Application failed to load in browser.",
            )

        if observation.status_code and observation.status_code >= 400:
            err = f"Server returned HTTP status {observation.status_code}"
            return VerificationResult(
                passed=False,
                confidence=1.0,
                reason=err,
                evidence=[],
                failures=[err],
                summary=f"HTTP error {observation.status_code}",
            )

        evidence.append(f"HTTP Status: {observation.status_code or 200}")
        if observation.page_title:
            evidence.append(f"Page title: '{observation.page_title}'")

        # 2. Uncaught Runtime Errors
        if observation.page_errors:
            for p_err in observation.page_errors:
                failures.append(f"Uncaught runtime error: {p_err}")

        # 3. Dynamic LLM Verification
        if self.llm_provider:
            return await self._verify_with_llm(
                goal=goal,
                observation=observation,
                analysis=analysis,
                repo_context=repo_context,
                pre_evidence=evidence,
                pre_failures=failures,
            )

        # 4. Strict Non-LLM Fallback: NEVER falsely claim success without LLM verification
        return self._strict_fallback(
            goal=goal,
            observation=observation,
            analysis=analysis,
            pre_evidence=evidence,
            pre_failures=failures,
        )

    async def _verify_with_llm(
        self,
        goal: str,
        observation: BrowserObservation,
        analysis: Optional[GoalAnalysis],
        repo_context: Optional[RepositoryContext],
        pre_evidence: list[str],
        pre_failures: list[str],
    ) -> VerificationResult:
        """Query LLM with all observable evidence to evaluate each acceptance criterion."""
        criteria_list = analysis.acceptance_criteria if analysis else []
        criteria_prompt_section = "\n".join(
            f"- [{c.id}] ({c.verification_method}): {c.description}"
            for c in criteria_list
        ) if criteria_list else f"- [crit-main]: Satisfies user goal: '{goal}'"

        interactive_str = (
            "\n".join(f"  • {el}" for el in observation.interactive_elements[:25])
            if observation.interactive_elements
            else "  None detected"
        )
        headings_str = (
            "\n".join(f"  • {h}" for h in observation.headings[:15])
            if observation.headings
            else "  None detected"
        )
        console_str = (
            "\n".join(f"  • {err}" for err in observation.console_errors)
            if observation.console_errors
            else "  None"
        )

        prompt = (
            "You are a rigorous, zero-tolerance automated software QA Verifier evaluating a running web application.\n"
            "Your job is to determine whether the application ACTUALLY satisfies the user's engineering goal based "
            "STRICTLY on the observed evidence.\n\n"
            f"Original User Goal:\n{goal}\n\n"
            f"Acceptance Criteria to Verify:\n{criteria_prompt_section}\n\n"
            "=== OBSERVED BROWSER EVIDENCE ===\n"
            f"URL: {observation.url}\n"
            f"Page Title: {observation.page_title}\n"
            f"HTTP Status: {observation.status_code}\n\n"
            f"Observed Headings:\n{headings_str}\n\n"
            f"Observed Interactive Elements (buttons, inputs, links, forms):\n{interactive_str}\n\n"
            f"Observed Visible Text:\n{observation.visible_text[:2500]}\n\n"
            f"Observed DOM Snippet:\n{observation.html[:3500]}\n\n"
            f"Console Errors:\n{console_str}\n"
            "=================================\n\n"
            "VERIFICATION RULES:\n"
            "1. You must evaluate EACH acceptance criterion independently.\n"
            "2. DO NOT assume or hallucinate features that are not visible in the headings, interactive elements, text, or DOM.\n"
            "3. If the page is completely unrelated to the user goal (e.g. user asked for an e-commerce page, but the page is a generic tool/landing page), "
            "you MUST return passed=false.\n"
            "4. Only mark passed=true if ALL criteria are satisfied with direct observable evidence.\n\n"
            "Respond ONLY with a JSON object matching this schema:\n"
            "{\n"
            '  "passed": false,\n'
            '  "confidence": 0.95,\n'
            '  "summary": "Clear summary of verification findings",\n'
            '  "reason": "Why the goal passed or failed",\n'
            '  "criteria_results": [\n'
            '    {\n'
            '      "criterion_id": "crit-1",\n'
            '      "description": "Criterion description",\n'
            '      "passed": false,\n'
            '      "evidence": "Concrete observation details or why it was missing"\n'
            '    }\n'
            '  ],\n'
            '  "evidence": ["Found product card in DOM", "Found Add to Cart button"],\n'
            '  "failures": ["Missing shopping cart drawer", "No product pricing visible"]\n'
            "}"
        )

        try:
            assert self.llm_provider is not None
            response = await self.llm_provider.generate(
                prompt=prompt,
                system_instruction="You are a strict QA verification engine. Output ONLY valid JSON.",
            )
            raw = response.text.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw)

            data = json.loads(raw)
            c_results: list[CriterionResult] = []
            for item in data.get("criteria_results", []):
                c_results.append(
                    CriterionResult(
                        criterion_id=str(item.get("criterion_id", "")),
                        description=str(item.get("description", "")),
                        passed=bool(item.get("passed", False)),
                        evidence=str(item.get("evidence", "")),
                    )
                )

            # Overall pass requires: data["passed"] == True AND no criteria failed
            any_crit_failed = any(not c.passed for c in c_results)
            overall_passed = bool(data.get("passed", False)) and not any_crit_failed and not pre_failures

            ev_list = pre_evidence + list(data.get("evidence", []))
            fail_list = pre_failures + list(data.get("failures", []))

            # Add failing criteria descriptions to fail_list if not present
            for c in c_results:
                if not c.passed and c.description not in fail_list:
                    fail_list.append(f"Criterion [{c.criterion_id}] not satisfied: {c.description} ({c.evidence})")

            return VerificationResult(
                passed=overall_passed,
                confidence=float(data.get("confidence", 0.9)),
                criteria_results=c_results,
                evidence=ev_list,
                failures=fail_list,
                reason=str(data.get("reason", "Verification complete.")),
                summary=str(data.get("summary", "")),
            )
        except Exception as exc:
            err_msg = str(exc)
            if "429" in err_msg or "rate limit" in err_msg.lower():
                logger.info("LLM quota reached; using strict evidence fallback.")
            else:
                logger.warning("LLM verification evaluation unavailable; using strict fallback")
            return self._strict_fallback(
                goal=goal,
                observation=observation,
                analysis=analysis,
                pre_evidence=pre_evidence,
                pre_failures=pre_failures,
            )

    def _strict_fallback(
        self,
        goal: str,
        observation: BrowserObservation,
        analysis: Optional[GoalAnalysis],
        pre_evidence: list[str],
        pre_failures: list[str],
    ) -> VerificationResult:
        """Strict fallback when LLM is unavailable: evaluates observable evidence per criterion."""
        failures = list(pre_failures)
        evidence = list(pre_evidence)
        criteria_results: list[CriterionResult] = []

        criteria_list = analysis.acceptance_criteria if analysis else []

        text_content = (
            observation.visible_text
            + " " + " ".join(observation.headings)
            + " " + " ".join(observation.interactive_elements)
            + " " + observation.html
        ).lower()

        # Extract explicit required_text if present in analysis
        found_reqs: list[str] = []
        missing_reqs: list[str] = []
        if analysis and analysis.required_text:
            for req in analysis.required_text:
                if req.lower() in text_content:
                    found_reqs.append(f"'{req}'")
                else:
                    missing_reqs.append(f"'{req}'")

        # Goal keywords (excluding common UI/meta-words)
        meta_stop_words = {
            "a", "an", "the", "with", "and", "or", "for", "to", "in", "of",
            "at", "by", "from", "up", "about", "into", "over", "after",
            "build", "create", "make", "add", "implement", "fix", "update",
            "ensure", "simple", "interactive", "page", "landing", "website",
            "webpage", "application", "site", "view", "interface", "using",
            "that", "this", "some", "more", "user", "should", "must", "have",
            "need", "needed", "needs", "app", "work", "works",
            "button", "buttons", "component", "components", "element", "elements",
            "control", "controls", "section", "sections",
        }
        goal_keywords = [
            w.lower() for w in re.findall(r'[a-zA-Z0-9_\-]+', goal)
            if len(w) > 2 and w.lower() not in meta_stop_words
        ]

        found_keywords = [kw for kw in goal_keywords if kw in text_content]
        missing_keywords = [kw for kw in goal_keywords if kw not in text_content]

        # Evaluate each criterion against observed evidence
        for c in criteria_list:
            desc_lower = c.description.lower()
            method_lower = c.verification_method.lower()

            if "console" in method_lower or "console" in desc_lower or "exception" in desc_lower:
                if len(observation.console_errors) == 0 and len(observation.page_errors) == 0:
                    criteria_results.append(
                        CriterionResult(
                            criterion_id=c.id,
                            description=c.description,
                            passed=True,
                            evidence="No console or runtime exceptions observed.",
                        )
                    )
                else:
                    err_msg = f"Console/runtime errors detected: {observation.console_errors + observation.page_errors}"
                    failures.append(err_msg)
                    criteria_results.append(
                        CriterionResult(
                            criterion_id=c.id,
                            description=c.description,
                            passed=False,
                            evidence=err_msg,
                        )
                    )
            elif "e-commerce" in desc_lower or "ecommerce" in desc_lower or "product" in desc_lower or "cart" in desc_lower:
                ecom_signals = {"cart", "product", "price", "shop", "store", "buy", "$", "checkout", "commerce"}
                found_signals = [s for s in ecom_signals if s in text_content]
                if found_signals:
                    ev_text = f"Observed e-commerce indicators: {', '.join(found_signals)}"
                    evidence.append(ev_text)
                    criteria_results.append(
                        CriterionResult(
                            criterion_id=c.id,
                            description=c.description,
                            passed=True,
                            evidence=ev_text,
                        )
                    )
                else:
                    fail_text = "No e-commerce, product, or catalog elements detected in DOM."
                    failures.append(fail_text)
                    criteria_results.append(
                        CriterionResult(
                            criterion_id=c.id,
                            description=c.description,
                            passed=False,
                            evidence=fail_text,
                        )
                    )
            elif "theme" in desc_lower or "dark" in desc_lower:
                theme_signals = {"dark", "theme", "light", "toggle"}
                found_theme = [s for s in theme_signals if s in text_content]
                if any(s in text_content for s in ("dark", "theme-toggle", "dark-mode")):
                    ev_text = f"Observed theme elements: {', '.join(found_theme)}"
                    evidence.append(ev_text)
                    criteria_results.append(
                        CriterionResult(
                            criterion_id=c.id,
                            description=c.description,
                            passed=True,
                            evidence=ev_text,
                        )
                    )
                else:
                    fail_text = "No dark mode toggle or theme styling elements detected."
                    failures.append(fail_text)
                    criteria_results.append(
                        CriterionResult(
                            criterion_id=c.id,
                            description=c.description,
                            passed=False,
                            evidence=fail_text,
                        )
                    )
            elif "form" in desc_lower or "contact" in desc_lower:
                if any(tag in text_content for tag in ("<form", "<input", "textarea", "submit", "contact")):
                    ev_text = "Observed form/input elements in DOM."
                    evidence.append(ev_text)
                    criteria_results.append(
                        CriterionResult(
                            criterion_id=c.id,
                            description=c.description,
                            passed=True,
                            evidence=ev_text,
                        )
                    )
                else:
                    fail_text = "No form, input, or submission elements detected."
                    failures.append(fail_text)
                    criteria_results.append(
                        CriterionResult(
                            criterion_id=c.id,
                            description=c.description,
                            passed=False,
                            evidence=fail_text,
                        )
                    )
            else:
                # Content / DOM / Layout criteria
                if missing_reqs or missing_keywords:
                    missing_str = ", ".join(missing_reqs + [f"'{k}'" for k in missing_keywords])
                    fail_text = f"Missing required observable elements: {missing_str}"
                    failures.append(fail_text)
                    criteria_results.append(
                        CriterionResult(
                            criterion_id=c.id,
                            description=c.description,
                            passed=False,
                            evidence=fail_text,
                        )
                    )
                elif found_reqs or found_keywords:
                    found_str = ", ".join(found_reqs + [f"'{k}'" for k in found_keywords])
                    ev_text = f"Observed required elements: {found_str}"
                    evidence.append(ev_text)
                    criteria_results.append(
                        CriterionResult(
                            criterion_id=c.id,
                            description=c.description,
                            passed=True,
                            evidence=ev_text,
                        )
                    )
                else:
                    fail_text = f"No observable evidence found for: {c.description}"
                    failures.append(fail_text)
                    criteria_results.append(
                        CriterionResult(
                            criterion_id=c.id,
                            description=c.description,
                            passed=False,
                            evidence=fail_text,
                        )
                    )

        # Deduplicate failures and evidence
        unique_failures = list(dict.fromkeys(failures))
        unique_evidence = list(dict.fromkeys(evidence))

        has_substantive_evidence = len(found_reqs) > 0 or len(found_keywords) > 0 or len(unique_evidence) > 0
        all_passed = len(criteria_results) > 0 and all(cr.passed for cr in criteria_results)
        passed = all_passed and len(unique_failures) == 0 and has_substantive_evidence

        return VerificationResult(
            passed=passed,
            confidence=0.85 if passed else 0.95,
            criteria_results=criteria_results,
            evidence=unique_evidence,
            failures=unique_failures,
            reason="All criteria satisfied by observable evidence." if passed else f"Observable evidence missing: {', '.join(unique_failures[:2])}",
            summary="Verification completed via strict observable evidence check.",
        )

