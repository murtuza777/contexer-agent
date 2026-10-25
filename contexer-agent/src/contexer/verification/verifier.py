"""Evidence-based verification of a running application against acceptance criteria."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional

from contexer.llm.base import LLMProvider
from contexer.llm.structured import parse_json_object
from contexer.observer.models import BrowserObservation
from contexer.verification.models import (
    AcceptanceCriterion,
    CriterionResult,
    GoalAnalysis,
    VerificationResult,
)
from contexer.verification.runner import CheckRunner

if TYPE_CHECKING:
    from contexer.workflow.inspector import RepositoryContext

logger = logging.getLogger(__name__)

HEURISTIC_CONFIDENCE = 0.6
# A check that could not perform its steps says the expected UI was not found,
# not that the behaviour is broken.
BLOCKED_CONFIDENCE = 0.5


@dataclass
class _Judgment:
    """Verdicts for criteria that had no executable check."""

    criteria_results: list[CriterionResult]
    evidence: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    confidence: float = 1.0
    overall_ok: bool = True
    reason: str = ""


class Verifier:
    """Decides whether a running application satisfies the goal's acceptance criteria.

    Criteria with an executable check are decided by running it in a browser —
    that verdict is final. Only criteria without a check fall back to LLM
    judgment of a page snapshot, or to keyword heuristics when no LLM is
    configured. Every criterion result records which method decided it, so
    callers can tell proof from opinion.
    """

    def __init__(
        self,
        llm_provider: Optional[LLMProvider] = None,
        runner: Optional[CheckRunner] = None,
    ) -> None:
        self.llm_provider = llm_provider
        self.runner = runner or CheckRunner()

    async def verify(
        self,
        goal: str,
        observation: BrowserObservation,
        analysis: Optional[GoalAnalysis] = None,
        repo_context: Optional[RepositoryContext] = None,
        artifacts_dir: Optional[Path] = None,
        storage_state: Optional[dict[str, Any]] = None,
        before_each: Optional[Callable[[], Awaitable[Optional[str]]]] = None,
    ) -> VerificationResult:
        """Verify the application at ``observation.url`` against ``analysis``.

        ``artifacts_dir`` receives per-check screenshots (and traces, if the
        runner records them). ``storage_state`` and ``before_each`` are passed
        to the runner (signed-in state; the ``[app] reset`` before each check).
        """
        if not observation.success:
            err = observation.error or "Application was not reachable."
            return VerificationResult(
                passed=False,
                confidence=1.0,
                reason=f"Application offline or unreachable: {err}",
                failures=[err],
                summary="Application failed to load in browser.",
            )

        if observation.status_code and observation.status_code >= 400:
            err = f"Server returned HTTP status {observation.status_code}"
            return VerificationResult(
                passed=False,
                confidence=1.0,
                reason=err,
                failures=[err],
                summary=f"HTTP error {observation.status_code}",
            )

        evidence: list[str] = [f"HTTP Status: {observation.status_code or 200}"]
        if observation.page_title:
            evidence.append(f"Page title: '{observation.page_title}'")
        runtime_failures = [f"Uncaught runtime error: {err}" for err in observation.page_errors]
        failures: list[str] = list(runtime_failures)

        criteria = analysis.acceptance_criteria if analysis else []
        asserted = [c for c in criteria if c.check is not None]
        unasserted = [c for c in criteria if c.check is None]

        results: list[CriterionResult] = []
        confidences: list[float] = []
        judgment: Optional[_Judgment] = None

        if asserted:
            pairs = [(c.id, c.check) for c in asserted if c.check is not None]
            extra: dict[str, Any] = {}
            if artifacts_dir is not None:
                extra["artifacts_dir"] = artifacts_dir
            if storage_state is not None:
                extra["storage_state"] = storage_state
            if before_each is not None:
                extra["before_each"] = before_each
            check_results = await self.runner.run(observation.url, pairs, **extra)
            for criterion, outcome in zip(asserted, check_results):
                results.append(
                    CriterionResult(
                        criterion_id=criterion.id,
                        description=criterion.description,
                        passed=outcome.passed,
                        evidence=outcome.summary(),
                        method="assertion",
                        check_result=outcome,
                    )
                )
                if outcome.passed:
                    evidence.append(f"[{criterion.id}] {outcome.summary()}")
                else:
                    failures.append(outcome.failure_report())
            confidences.append(1.0)

        if unasserted or not criteria:
            subset = analysis.model_copy(update={"acceptance_criteria": unasserted}) if analysis else None
            if self.llm_provider:
                judgment = await self._judge_with_llm(goal, observation, subset)
            if judgment is None:
                judgment = self._judge_heuristically(goal, observation, subset)
            results.extend(judgment.criteria_results)
            evidence.extend(judgment.evidence)
            failures.extend(judgment.failures)
            confidences.append(judgment.confidence)

        order = {c.id: i for i, c in enumerate(criteria)}
        results.sort(key=lambda r: order.get(r.criterion_id, len(order)))

        # Reproduced behavioural failures first: they are the most actionable.
        failed = sorted((r for r in results if not r.passed), key=_is_blocked)
        judgment_ok = judgment.overall_ok if judgment else True
        passed = bool(results) and not failed and not runtime_failures and judgment_ok

        if any(r.method == "assertion" and not _is_blocked(r) for r in failed):
            confidence = 1.0  # a reproduced failure is not a matter of opinion
        else:
            if any(_is_blocked(r) for r in failed):
                confidences.append(BLOCKED_CONFIDENCE)
            confidence = min(confidences) if confidences else 0.0

        if passed:
            reason = "All acceptance criteria satisfied."
        elif runtime_failures:
            reason = runtime_failures[0]
        elif failed:
            reason = "; ".join(f"[{r.criterion_id}] {r.evidence}" for r in failed[:2])
        else:
            reason = (judgment.reason if judgment else "") or "Acceptance criteria not met."

        return VerificationResult(
            passed=passed,
            confidence=confidence,
            criteria_results=results,
            evidence=list(dict.fromkeys(evidence)),
            failures=list(dict.fromkeys(failures)),
            reason=reason,
            summary=_method_summary(results),
        )

    async def _judge_with_llm(
        self,
        goal: str,
        observation: BrowserObservation,
        analysis: Optional[GoalAnalysis],
    ) -> Optional[_Judgment]:
        """Ask the LLM to judge criteria from a page snapshot; ``None`` if unavailable."""
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
            data = parse_json_object(response.text, expect_key="criteria_results")
        except Exception as exc:
            err_msg = str(exc)
            if "429" in err_msg or "rate limit" in err_msg.lower():
                logger.info("LLM quota reached; using heuristic verification for unasserted criteria.")
            else:
                logger.warning("LLM verification unavailable; using heuristic verification for unasserted criteria")
            return None

        c_results = [
            CriterionResult(
                criterion_id=str(item.get("criterion_id", "")),
                description=str(item.get("description", "")),
                passed=bool(item.get("passed", False)),
                evidence=str(item.get("evidence", "")),
                method="judgment",
            )
            for item in data.get("criteria_results", [])
            if isinstance(item, dict)
        ]
        failures = [str(f) for f in data.get("failures", [])]
        for c in c_results:
            if not c.passed:
                failures.append(f"Criterion [{c.criterion_id}] not satisfied: {c.description} ({c.evidence})")

        try:
            confidence = float(data.get("confidence", 0.9))
        except (TypeError, ValueError):
            confidence = 0.9

        return _Judgment(
            criteria_results=c_results,
            evidence=[str(e) for e in data.get("evidence", [])],
            failures=failures,
            confidence=confidence,
            overall_ok=bool(data.get("passed", False)),
            reason=str(data.get("reason", "")),
        )

    def _judge_heuristically(
        self,
        goal: str,
        observation: BrowserObservation,
        analysis: Optional[GoalAnalysis],
    ) -> _Judgment:
        """Keyword evidence check used when no LLM is available.

        Weak by construction — results are labelled ``heuristic`` and capped at
        ``HEURISTIC_CONFIDENCE`` so they are never mistaken for proof.
        """
        failures: list[str] = []
        evidence: list[str] = []
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

        def record(c: AcceptanceCriterion, passed: bool, text: str) -> None:
            (evidence if passed else failures).append(text)
            criteria_results.append(
                CriterionResult(
                    criterion_id=c.id,
                    description=c.description,
                    passed=passed,
                    evidence=text,
                    method="heuristic",
                )
            )

        for c in criteria_list:
            desc_lower = c.description.lower()
            method_lower = c.verification_method.lower()

            if "console" in method_lower or "console" in desc_lower or "exception" in desc_lower:
                errors = observation.console_errors + observation.page_errors
                if not errors:
                    criteria_results.append(
                        CriterionResult(
                            criterion_id=c.id,
                            description=c.description,
                            passed=True,
                            evidence="No console or runtime exceptions observed.",
                            method="heuristic",
                        )
                    )
                else:
                    record(c, False, f"Console/runtime errors detected: {errors}")
            elif "e-commerce" in desc_lower or "ecommerce" in desc_lower or "product" in desc_lower or "cart" in desc_lower:
                ecom_signals = {"cart", "product", "price", "shop", "store", "buy", "$", "checkout", "commerce"}
                found_signals = [s for s in ecom_signals if s in text_content]
                if found_signals:
                    record(c, True, f"Observed e-commerce indicators: {', '.join(found_signals)}")
                else:
                    record(c, False, "No e-commerce, product, or catalog elements detected in DOM.")
            elif "theme" in desc_lower or "dark" in desc_lower:
                theme_signals = {"dark", "theme", "light", "toggle"}
                found_theme = [s for s in theme_signals if s in text_content]
                if any(s in text_content for s in ("dark", "theme-toggle", "dark-mode")):
                    record(c, True, f"Observed theme elements: {', '.join(found_theme)}")
                else:
                    record(c, False, "No dark mode toggle or theme styling elements detected.")
            elif "form" in desc_lower or "contact" in desc_lower:
                if any(tag in text_content for tag in ("<form", "<input", "textarea", "submit", "contact")):
                    record(c, True, "Observed form/input elements in DOM.")
                else:
                    record(c, False, "No form, input, or submission elements detected.")
            else:
                # Content / DOM / Layout criteria
                if missing_reqs or missing_keywords:
                    missing_str = ", ".join(missing_reqs + [f"'{k}'" for k in missing_keywords])
                    record(c, False, f"Missing required observable elements: {missing_str}")
                elif found_reqs or found_keywords:
                    found_str = ", ".join(found_reqs + [f"'{k}'" for k in found_keywords])
                    record(c, True, f"Observed required elements: {found_str}")
                else:
                    record(c, False, f"No observable evidence found for: {c.description}")

        unique_failures = list(dict.fromkeys(failures))
        unique_evidence = list(dict.fromkeys(evidence))
        has_substantive_evidence = bool(found_reqs or found_keywords or unique_evidence)

        return _Judgment(
            criteria_results=criteria_results,
            evidence=unique_evidence,
            failures=unique_failures,
            confidence=HEURISTIC_CONFIDENCE,
            overall_ok=has_substantive_evidence,
            reason=f"Observable evidence missing: {', '.join(unique_failures[:2])}" if unique_failures else "",
        )


def _is_blocked(result: CriterionResult) -> bool:
    return result.check_result is not None and result.check_result.blocked


def _method_summary(results: list[CriterionResult]) -> str:
    """e.g. '3/4 proven in browser (1 blocked), 1/2 judged by LLM'."""
    labels = {
        "assertion": "proven in browser",
        "judgment": "judged by LLM",
        "heuristic": "matched by keyword heuristics",
    }
    parts = []
    for method, label in labels.items():
        group = [r for r in results if r.method == method]
        if group:
            part = f"{sum(r.passed for r in group)}/{len(group)} {label}"
            blocked = sum(_is_blocked(r) for r in group)
            parts.append(f"{part} ({blocked} blocked)" if blocked else part)
    return ", ".join(parts) or "No criteria evaluated."
