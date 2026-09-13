"""Dynamic goal analysis and acceptance criteria generation."""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from contexer.llm.base import LLMProvider
from contexer.verification.models import AcceptanceCriterion, GoalAnalysis
from contexer.workflow.inspector import RepositoryContext

logger = logging.getLogger(__name__)


class GoalAnalyzer:
    """Uses LLM to analyze user goals and generate structured acceptance criteria."""

    def __init__(self, llm_provider: Optional[LLMProvider] = None) -> None:
        self.llm_provider = llm_provider

    async def analyze(
        self,
        goal: str,
        repo_context: Optional[RepositoryContext] = None,
    ) -> GoalAnalysis:
        """Derive structured acceptance criteria tailored specifically to the goal."""
        if self.llm_provider:
            try:
                context_str = repo_context.format_summary() if repo_context else "Target: Web application"
                prompt = (
                    "You are a Senior QA Architect. Analyze the following user engineering goal and generate "
                    "3 to 5 specific, observable acceptance criteria for verifying that the goal was successfully achieved.\n\n"
                    f"User Goal: {goal}\n\n"
                    f"Project Context:\n{context_str}\n\n"
                    "Requirements for Criteria:\n"
                    "- Every criterion must be verifiable by inspecting the browser (DOM elements, visible text, "
                    "buttons/links/inputs, headings, console errors).\n"
                    "- Criteria must be tailored specifically to what the user asked for.\n"
                    "- Do NOT use generic criteria like 'button exists' unless requested.\n\n"
                    "Respond ONLY with a JSON object matching this schema:\n"
                    "{\n"
                    '  "summary": "Brief summary of goal intent",\n'
                    '  "acceptance_criteria": [\n'
                    '    {\n'
                    '      "id": "crit-1",\n'
                    '      "description": "Specific condition that must be present and observable",\n'
                    '      "verification_method": "dom_inspection"\n'
                    '    }\n'
                    "  ]\n"
                    "}"
                )
                response = await self.llm_provider.generate(
                    prompt=prompt,
                    system_instruction="You are a QA architect. Return ONLY valid JSON.",
                )
                raw = response.text.strip()
                if raw.startswith("```"):
                    raw = re.sub(r"^```[a-z]*\n?", "", raw)
                    raw = re.sub(r"\n?```$", "", raw)

                data = json.loads(raw)
                criteria = [
                    AcceptanceCriterion(
                        id=item.get("id", f"crit-{i + 1}"),
                        description=item.get("description", ""),
                        verification_method=item.get("verification_method", "dom_inspection"),
                    )
                    for i, item in enumerate(data.get("acceptance_criteria", []))
                    if item.get("description")
                ]
                if criteria:
                    return GoalAnalysis(
                        goal=goal,
                        summary=data.get("summary", goal),
                        acceptance_criteria=criteria,
                    )
            except Exception as exc:
                logger.warning("LLM goal analysis failed: %s; using dynamic rule-based analysis", exc)

        # Dynamic fallback: decompose goal into structured criteria
        return self._dynamic_rule_analysis(goal)

    def _dynamic_rule_analysis(self, goal: str) -> GoalAnalysis:
        """Dynamically generate criteria based on the intent of the goal."""
        criteria: list[AcceptanceCriterion] = [
            AcceptanceCriterion(
                id="crit-runtime",
                description="Application loads without uncaught JavaScript exceptions or console errors",
                verification_method="console_check",
            ),
        ]

        goal_lower = goal.lower()

        # Check for landing page / home page
        if any(term in goal_lower for term in ("landing page", "home", "storefront", "portal")):
            criteria.append(
                AcceptanceCriterion(
                    id="crit-layout",
                    description=f"Page presents a complete layout corresponding to: '{goal}'",
                    verification_method="dom_inspection",
                )
            )

        # Check for e-commerce / products / shop
        if any(term in goal_lower for term in ("e-commerce", "ecommerce", "shop", "store", "product", "cart")):
            criteria.append(
                AcceptanceCriterion(
                    id="crit-products",
                    description="E-commerce elements (products, catalog, pricing, or cart interactions) are visible and functional",
                    verification_method="dom_inspection",
                )
            )

        # Check for dark mode / theme
        if "dark mode" in goal_lower or "theme" in goal_lower:
            criteria.append(
                AcceptanceCriterion(
                    id="crit-theme",
                    description="Theme toggle control exists and modifies document styling or theme attributes",
                    verification_method="interactive_test",
                )
            )

        # Check for form / contact / login / auth
        if any(term in goal_lower for term in ("form", "contact", "login", "auth", "input")):
            criteria.append(
                AcceptanceCriterion(
                    id="crit-form",
                    description="Form controls, input fields, and submission button are rendered and interactive",
                    verification_method="interactive_test",
                )
            )

        # General goal satisfaction criterion
        criteria.append(
            AcceptanceCriterion(
                id="crit-intent",
                description=f"Core functionality and content for '{goal}' is clearly observable in the UI",
                verification_method="dom_inspection",
            )
        )

        # Extract explicit quoted strings from goal if any
        quoted = re.findall(r'["\']([^"\']+)["\']', goal)

        return GoalAnalysis(
            goal=goal,
            summary=f"Analysis of: {goal}",
            acceptance_criteria=criteria,
            required_text=list(quoted),
        )


def extract_acceptance_criteria(goal: str, llm_provider: Optional[LLMProvider] = None) -> GoalAnalysis:
    """Helper function for backward compatibility."""
    analyzer = GoalAnalyzer(llm_provider=llm_provider)
    return analyzer._dynamic_rule_analysis(goal)
