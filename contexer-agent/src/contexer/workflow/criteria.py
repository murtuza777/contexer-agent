"""Goal analysis: turning a user goal into acceptance criteria with executable checks."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Optional

from pydantic import ValidationError

from contexer.llm.base import LLMProvider
from contexer.llm.structured import parse_json_object
from contexer.verification.checks import Check, Expectation, Locator
from contexer.verification.models import AcceptanceCriterion, GoalAnalysis
from contexer.workflow.inspector import RepositoryContext

logger = logging.getLogger(__name__)

RUNTIME_CRITERION_ID = "crit-runtime"
# One compile attempt may not hang a command for the SDK default (10 minutes).
COMPILE_TIMEOUT_SECONDS = 180.0
MAX_ANALYSIS_ATTEMPTS = 2
# Below this share of executable criteria, a reply is retried: the rest would
# fall back to LLM judgment of a static snapshot, which cannot see behaviour.
MIN_CHECK_COVERAGE = 0.5

CHECK_DSL_GUIDE = """\
Each criterion should carry an executable "check" that a headless browser runs against the live app.
A check is {"steps": [<step>, ...], "expect": [<expectation>, ...]}.

Locators (exactly one key; prefer the first ones because they do not depend on implementation details):
  {"role": "button", "name": "Add to cart"}  ARIA role + accessible name (case-insensitive substring)
  {"text": "Free shipping"}                  visible text
  {"label": "Email"}  or  {"placeholder": "Search"}
  {"test_id": "cart-count"}                  data-testid attribute; use it for state with no visible label
                                             (counters, result lists). The implementer will be told to add it.
  {"css": "body"}                            last resort; never invent class names

Steps:
  {"action": "click" | "hover" | "check" | "uncheck", "target": <locator>}
  {"action": "fill", "target": <locator>, "value": "text"}
  {"action": "select", "target": <locator>, "value": "option label"}
  {"action": "press", "value": "Enter", "target": <locator, optional>}
  {"action": "goto", "value": "/path"}
  {"action": "wait", "value": "300"}         milliseconds; rarely needed, expectations auto-retry

Expectations (all must hold):
  {"kind": "visible", "target": L}     {"kind": "hidden", "target": L}
  {"kind": "checked", "target": L}     {"kind": "unchecked", "target": L}   checkbox / radio / switch state
  {"kind": "count", "target": L, "min": 3}               ("max" also allowed)
  {"kind": "text", "target": L, "contains": "1"}
  {"kind": "value", "target": L, "equals": ""}           value of an input
  {"kind": "attribute", "target": L, "attribute": "aria-pressed", "equals": "true"}
  {"kind": "css", "target": {"css": "body"}, "property": "background-color", "changed": true}
  {"kind": "url", "contains": "/checkout"}    {"kind": "title", "contains": "Shop"}
  {"kind": "no_errors"}                       no uncaught exceptions or console errors
Comparators: "equals", "contains" (case-insensitive), "matches" (regex), "changed" (vs. before the steps ran).

Rules:
- Every check runs alone, in a fresh browser, on the freshly loaded app. Include every step that creates the state it
  checks (add the items, fill the form) — never rely on another check having run first.
- When the project configures a sign-in flow, every check starts already signed in: never add login steps or type
  credentials. For behaviour of signed-out visitors (a redirect to the login page), add "login": false to the check.
- Checks share the app's server. If the app saves data through an API or database, records an earlier check created
  may still be listed: give the items a check creates unique names (include the criterion id) and assert on those
  names, not on an empty list or a total of saved records. Exact counts stay right for state kept in the page.
- A role locator's "name" is the accessible name: an aria-label wins over the visible text.
- Verify behaviour by interacting, not just by presence: click "Add to cart", then expect the cart count text to change.
- One behaviour per check. Keep expectations implementation-agnostic
  (theme toggle: body background-color changed — not a guessed class name).
- Expect exact values ("equals") when the goal implies one, so an off-by-one or a stale value fails.
- Assert only what the goal states or the current UI already shows. Do not invent behaviour the goal leaves open
  (for example the order of items, or wording that appears nowhere in the UI or source).
- Cover the cases a careless implementation gets wrong, not only the happy path:
    counts and totals: act more than once (two different items, and the same item twice) and expect the exact result;
    filters, tabs and toggles: switch to a state and back again, and expect the original state to return;
    removing or editing one of several items: expect the others to stay and any counts or totals to update;
    forms: one check per rule with a value that breaks it, the valid path, and the error clearing after a fix;
    every interaction check also expects no uncaught exceptions or console errors ({"kind": "no_errors"}).
- Omit "check" only when a criterion cannot be checked mechanically (e.g. "looks modern").

Illustrative criterion (its names are made up; take real names from the current UI or the goal):
  {"id": "crit-2", "description": "Subscribing shows a confirmation",
   "verification_method": "interactive_test",
   "check": {"steps": [{"action": "fill", "target": {"label": "Email"}, "value": "a@b.co"},
                       {"action": "click", "target": {"role": "button", "name": "Subscribe"}}],
             "expect": [{"kind": "visible", "target": {"text": "Thanks for subscribing"}}]}}
"""


class GoalAnalyzer:
    """Uses LLM to analyze user goals and generate acceptance criteria with executable checks."""

    def __init__(self, llm_provider: Optional[LLMProvider] = None, timeout: float = COMPILE_TIMEOUT_SECONDS) -> None:
        self.llm_provider = llm_provider
        self.timeout = timeout

    async def analyze(
        self,
        goal: str,
        repo_context: Optional[RepositoryContext] = None,
        ui_snapshot: str = "",
    ) -> GoalAnalysis:
        """Derive acceptance criteria with executable checks.

        ``ui_snapshot`` (from ``BrowserObservation.ui_snapshot``) is the running
        app's current locator vocabulary; without it the model can only guess
        names for elements that already exist.
        """
        best: Optional[GoalAnalysis] = None
        for attempt in range(1, MAX_ANALYSIS_ATTEMPTS + 1) if self.llm_provider else ():
            try:
                # First ask for JSON mode (routers drop it for models without support);
                # the retry goes without it in case a provider rejects the parameter.
                candidate = await self._analyze_with_llm(goal, repo_context, ui_snapshot, json_mode=attempt == 1)
            except Exception as exc:
                err_msg = str(exc)
                if "429" in err_msg or "rate limit" in err_msg.lower():
                    logger.info("LLM quota reached; using dynamic rule-based analysis.")
                    break  # retrying a rate-limited API only makes it worse
                logger.warning(
                    "LLM goal analysis attempt %d failed (%s: %s)",
                    attempt,
                    type(exc).__name__,
                    err_msg.splitlines()[0][:200] if err_msg else "",
                )
                continue
            if best is None or _check_coverage(candidate) > _check_coverage(best):
                best = candidate
            if _check_coverage(best) >= MIN_CHECK_COVERAGE:
                break
            # Routers such as openrouter/free pick a model per request; some ignore
            # the format or leave behaviour unchecked. One retry is cheap.
            logger.warning(
                "LLM analysis attempt %d made only %.0f%% of criteria executable",
                attempt,
                _check_coverage(candidate) * 100,
            )

        if best is not None and best.acceptance_criteria:
            return _ensure_runtime_criterion(best)
        return self._dynamic_rule_analysis(goal)

    async def _analyze_with_llm(
        self,
        goal: str,
        repo_context: Optional[RepositoryContext],
        ui_snapshot: str = "",
        json_mode: bool = False,
    ) -> GoalAnalysis:
        assert self.llm_provider is not None
        context_str = repo_context.format_summary() if repo_context else "Target: Web application"
        ui_section = (
            "Current UI of the running application (ARIA roles and accessible names, test ids, placeholders):\n"
            f"{ui_snapshot}\n"
            "Elements that already exist MUST be located exactly as they appear above (same role, name, "
            "placeholder or test id). Only elements the goal adds that are not listed may be named freely; "
            "those names become part of the contract.\n\n"
            if ui_snapshot
            else "The application has no rendered UI yet; every locator you choose becomes part of the contract.\n\n"
        )
        source = repo_context.source_excerpt if repo_context else ""
        source_section = (
            "Existing front-end source. Use it ONLY to learn how to locate elements, including ones created "
            "after an interaction. Derive expected behaviour from the goal, never from this code: the code "
            "may be wrong, and the checks exist to find out.\n"
            f"{source}\n\n"
            if source
            else ""
        )
        prompt = (
            "You are a Senior QA Architect. Turn the user's engineering goal into 4 to 10 specific, "
            "observable acceptance criteria, each with an executable browser check. The checks are given "
            "to the implementing engineer as the contract and then executed against the running app.\n\n"
            f"User Goal: {goal}\n\n"
            f"Project Context:\n{context_str}\n\n"
            f"{ui_section}"
            f"{source_section}"
            f"{CHECK_DSL_GUIDE}\n"
            "Criteria must be tailored to what the user asked for; do not add generic criteria they did not request.\n\n"
            "Respond ONLY with a JSON object:\n"
            '{"summary": "Brief summary of goal intent", "acceptance_criteria": [<criterion>, ...]}'
        )
        extra = {"response_format": {"type": "json_object"}} if json_mode else {}
        try:
            response = await asyncio.wait_for(
                self.llm_provider.generate(
                    prompt=prompt,
                    system_instruction="You are a QA architect. Return ONLY valid JSON.",
                    **extra,
                ),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError as exc:
            raise TimeoutError(f"the model did not answer within {self.timeout:.0f}s") from exc
        data = parse_json_object(response.text, expect_key="acceptance_criteria")

        criteria: list[AcceptanceCriterion] = []
        for i, item in enumerate(data.get("acceptance_criteria", [])):
            if not isinstance(item, dict) or not item.get("description"):
                continue
            criterion_id = str(item.get("id") or f"crit-{i + 1}")
            criteria.append(
                AcceptanceCriterion(
                    id=criterion_id,
                    description=str(item["description"]),
                    verification_method=str(item.get("verification_method") or "dom_inspection"),
                    check=_parse_check(criterion_id, item.get("check")),
                )
            )
        return GoalAnalysis(
            goal=goal,
            summary=str(data.get("summary") or goal),
            acceptance_criteria=criteria,
            generated_by="llm",
        )

    def _dynamic_rule_analysis(self, goal: str) -> GoalAnalysis:
        """Rule-based criteria for when no LLM is available.

        Only what can be derived with certainty gets an executable check: the
        runtime-errors check and explicitly quoted UI text. Everything else is
        left for heuristic judgment.
        """
        criteria: list[AcceptanceCriterion] = [_runtime_criterion()]

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

        quoted = _quoted_ui_text(goal)
        for n, (text, role) in enumerate(quoted, 1):
            locator = Locator(role=role, name=text) if role else Locator(text=text)
            criteria.append(
                AcceptanceCriterion(
                    id=f"crit-text-{n}",
                    description=f"{role.capitalize() if role else 'Text'} \"{text}\" is visible",
                    verification_method="dom_inspection",
                    check=Check(expect=[Expectation(kind="visible", target=locator)]),
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

        return GoalAnalysis(
            goal=goal,
            summary=f"Analysis of: {goal}",
            acceptance_criteria=criteria,
            required_text=[text for text, _ in quoted],
            generated_by="rules",
        )


def _parse_check(criterion_id: str, raw: Any) -> Optional[Check]:
    """Validate an LLM-written check; an invalid one is dropped, not half-executed."""
    if raw is None:
        return None
    try:
        return Check.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ()))
        logger.info("Dropping invalid check for %s (%s: %s)", criterion_id, location, first.get("msg"))
        return None


def _check_coverage(analysis: GoalAnalysis) -> float:
    """Share of criteria with an executable check (0.0 for no criteria)."""
    criteria = analysis.acceptance_criteria
    return sum(1 for c in criteria if c.check is not None) / len(criteria) if criteria else 0.0


def _runtime_criterion() -> AcceptanceCriterion:
    return AcceptanceCriterion(
        id=RUNTIME_CRITERION_ID,
        description="Application loads without uncaught JavaScript exceptions or console errors",
        verification_method="console_check",
        check=Check(expect=[Expectation(kind="no_errors")]),
    )


def _ensure_runtime_criterion(analysis: GoalAnalysis) -> GoalAnalysis:
    """Runtime cleanliness is always verified, whether or not the model asked for it."""
    for criterion in analysis.acceptance_criteria:
        if criterion.check and any(e.kind == "no_errors" for e in criterion.check.expect):
            return analysis
    analysis.acceptance_criteria.append(_runtime_criterion())
    return analysis


# A quote must open at a word boundary so apostrophes ("user's cart") are not
# mistaken for quoted UI text.
_QUOTED = re.compile(r"""(?:^|(?<=[\s(]))(["'])([^"'\n]{1,60})\1(?=[\s.,;:!?)]|$)""")
_ROLE_WORDS = {"button": "button", "link": "link", "heading": "heading", "title": "heading", "tab": "tab"}


def _quoted_ui_text(goal: str) -> list[tuple[str, Optional[str]]]:
    """Quoted strings in a goal, with the ARIA role named right after them, if any.

    ``a 'Get Started' button`` -> ``[("Get Started", "button")]``
    """
    found: list[tuple[str, Optional[str]]] = []
    for match in _QUOTED.finditer(goal):
        text = match.group(2).strip()
        if not text:
            continue
        following = re.match(r"\s+(\w+)", goal[match.end():])
        role = _ROLE_WORDS.get(following.group(1).lower()) if following else None
        found.append((text, role))
    return found
