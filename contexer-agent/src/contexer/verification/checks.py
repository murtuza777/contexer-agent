"""Executable acceptance checks.

A ``Check`` is the machine-verifiable form of an acceptance criterion: a few
interaction steps followed by expectations about the resulting page. Checks
are written before any code exists, handed to the coding agent as a contract,
and executed by a real browser — so pass/fail comes from the running
application, never from a model's opinion of a DOM dump.

The vocabulary is deliberately small and closed. Anything an LLM produces
outside it fails validation and the criterion falls back to judgment, rather
than being half-executed.
"""

from __future__ import annotations

import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Roles accepted by Playwright's ``get_by_role``.
ARIA_ROLES = frozenset(
    {
        "alert", "alertdialog", "application", "article", "banner", "blockquote",
        "button", "caption", "cell", "checkbox", "code", "columnheader", "combobox",
        "complementary", "contentinfo", "definition", "deletion", "dialog",
        "directory", "document", "emphasis", "feed", "figure", "form", "generic",
        "grid", "gridcell", "group", "heading", "img", "insertion", "link", "list",
        "listbox", "listitem", "log", "main", "marquee", "math", "meter", "menu",
        "menubar", "menuitem", "menuitemcheckbox", "menuitemradio", "navigation",
        "none", "note", "option", "paragraph", "presentation", "progressbar",
        "radio", "radiogroup", "region", "row", "rowgroup", "rowheader",
        "scrollbar", "search", "searchbox", "separator", "slider", "spinbutton",
        "status", "strong", "subscript", "superscript", "switch", "tab", "table",
        "tablist", "tabpanel", "term", "textbox", "time", "timer", "toolbar",
        "tooltip", "tree", "treegrid", "treeitem",
    }
)

# Tag names models commonly write where an ARIA role is meant.
_ROLE_ALIASES = {
    "a": "link",
    "anchor": "link",
    "input": "textbox",
    "textarea": "textbox",
    "select": "combobox",
    "dropdown": "combobox",
    "image": "img",
    "nav": "navigation",
    **{f"h{n}": "heading" for n in range(1, 7)},
}

_LOCATOR_KEY_ALIASES = {
    "selector": "css",
    "testid": "test_id",
    "testId": "test_id",
    "data-testid": "test_id",
    "data_testid": "test_id",
}

LOCATOR_STRATEGIES = ("role", "text", "label", "placeholder", "test_id", "css")
MAX_WAIT_MS = 10_000


class Locator(BaseModel):
    """How to find an element: exactly one strategy (``name`` refines ``role``)."""

    model_config = ConfigDict(extra="ignore", coerce_numbers_to_str=True)

    role: Optional[str] = None
    name: Optional[str] = None
    text: Optional[str] = None
    label: Optional[str] = None
    placeholder: Optional[str] = None
    test_id: Optional[str] = None
    css: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_keys(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = {_LOCATOR_KEY_ALIASES.get(k, k): v for k, v in data.items()}
        role = normalized.get("role")
        if isinstance(role, str):
            role = role.strip().lower()
            normalized["role"] = _ROLE_ALIASES.get(role, role)
        return normalized

    @model_validator(mode="after")
    def _exactly_one_strategy(self) -> Locator:
        chosen = [s for s in LOCATOR_STRATEGIES if getattr(self, s)]
        if len(chosen) != 1:
            raise ValueError(f"locator needs exactly one of {LOCATOR_STRATEGIES}, got {chosen or 'none'}")
        if self.name and not self.role:
            raise ValueError("'name' is only valid together with 'role'")
        if self.role and self.role not in ARIA_ROLES:
            raise ValueError(f"unknown ARIA role '{self.role}'")
        return self

    def describe(self) -> str:
        if self.role:
            return f'{self.role} "{self.name}"' if self.name else f"any {self.role}"
        if self.text:
            return f'text "{self.text}"'
        if self.label:
            return f'field labelled "{self.label}"'
        if self.placeholder:
            return f'field with placeholder "{self.placeholder}"'
        if self.test_id:
            return f'[data-testid="{self.test_id}"]'
        return f"css `{self.css}`"


StepAction = Literal["click", "fill", "press", "select", "check", "uncheck", "hover", "wait", "goto"]

_TARGET_REQUIRED = {"click", "fill", "select", "check", "uncheck", "hover"}
_VALUE_REQUIRED = {"fill", "select", "press", "wait", "goto"}


class Step(BaseModel):
    """A single user interaction performed before expectations are evaluated."""

    model_config = ConfigDict(extra="ignore", coerce_numbers_to_str=True)

    action: StepAction
    target: Optional[Locator] = None
    value: Optional[str] = None

    @model_validator(mode="after")
    def _validate_shape(self) -> Step:
        if self.action in _TARGET_REQUIRED and self.target is None:
            raise ValueError(f"'{self.action}' needs a target")
        if self.action in _VALUE_REQUIRED and self.value is None:
            raise ValueError(f"'{self.action}' needs a value")
        if self.action == "wait":
            assert self.value is not None
            if not self.value.strip().isdigit() or int(self.value) > MAX_WAIT_MS:
                raise ValueError(f"'wait' value must be milliseconds between 0 and {MAX_WAIT_MS}")
        return self

    def describe(self) -> str:
        target = self.target.describe() if self.target else ""
        if self.action == "fill":
            return f'fill {target} with "{self.value}"'
        if self.action == "select":
            return f'select "{self.value}" in {target}'
        if self.action == "press":
            return f"press {self.value}" + (f" in {target}" if target else "")
        if self.action == "wait":
            return f"wait {self.value}ms"
        if self.action == "goto":
            return f"go to {self.value}"
        return f"{self.action} {target}"


ExpectKind = Literal[
    "visible", "hidden", "checked", "unchecked", "count", "text", "value", "attribute", "css", "url", "title",
    "no_errors",
]

_NEEDS_TARGET = {"visible", "hidden", "checked", "unchecked", "count", "text", "value", "attribute", "css"}
_TRUTHY = {"", "true", "checked", "on", "1", "yes"}
_NEEDS_COMPARATOR = {"text", "value", "attribute", "css", "url", "title"}


class Expectation(BaseModel):
    """An assertion about the page after the steps ran.

    Comparators combine with AND. ``contains`` is case-insensitive and
    whitespace-normalised; ``equals`` is exact after whitespace normalisation;
    ``matches`` is a regular expression; ``changed`` compares against the value
    captured before any step ran.
    """

    model_config = ConfigDict(extra="ignore", coerce_numbers_to_str=True, populate_by_name=True)

    kind: ExpectKind
    target: Optional[Locator] = None
    attribute: Optional[str] = None
    css_property: Optional[str] = Field(default=None, alias="property")
    equals: Optional[str] = None
    contains: Optional[str] = None
    matches: Optional[str] = None
    changed: Optional[bool] = None
    min: Optional[int] = None
    max: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def _checked_attribute_means_state(cls, data: Any) -> Any:
        """``attribute "checked"`` only reflects the initial markup, never a user's click.

        Models reach for it to say "the box is ticked"; read it as the live state.
        """
        if (
            isinstance(data, dict)
            and data.get("kind") == "attribute"
            and str(data.get("attribute", "")).lower() == "checked"
            and data.get("changed") is None
            and data.get("contains") is None
            and data.get("matches") is None
        ):
            wanted = str(data.get("equals", "true")).strip().lower()
            return {"kind": "checked" if wanted in _TRUTHY else "unchecked", "target": data.get("target")}
        return data

    @model_validator(mode="after")
    def _validate_shape(self) -> Expectation:
        if self.kind in _NEEDS_TARGET and self.target is None:
            raise ValueError(f"'{self.kind}' expectation needs a target")
        if self.kind == "attribute" and not self.attribute:
            raise ValueError("'attribute' expectation needs an attribute name")
        if self.kind == "css" and not self.css_property:
            raise ValueError("'css' expectation needs a property")
        if self.kind in _NEEDS_COMPARATOR and not self.has_comparator:
            raise ValueError(f"'{self.kind}' expectation needs equals, contains, matches, or changed")
        if self.kind == "count":
            if self.min is None and self.max is None:
                raise ValueError("'count' expectation needs min or max")
            if self.min is not None and self.max is not None and self.min > self.max:
                raise ValueError("'count' min is greater than max")
        if self.matches is not None:
            try:
                re.compile(self.matches)
            except re.error as exc:
                raise ValueError(f"invalid regex {self.matches!r}: {exc}") from exc
        return self

    @property
    def has_comparator(self) -> bool:
        return any(v is not None for v in (self.equals, self.contains, self.matches, self.changed))

    def compare(self, actual: Optional[str], before: Optional[str] = None) -> bool:
        """Apply this expectation's comparators to an observed value."""
        if actual is None:
            # Only "changed" can hold for an absent value (it disappeared).
            return self.changed is True and before is not None and not any(
                v is not None for v in (self.equals, self.contains, self.matches)
            )
        normalized = " ".join(actual.split())
        if self.equals is not None and normalized != " ".join(self.equals.split()):
            return False
        if self.contains is not None and " ".join(self.contains.split()).lower() not in normalized.lower():
            return False
        if self.matches is not None and re.search(self.matches, actual) is None:
            return False
        if self.changed is not None and (actual != before) != self.changed:
            return False
        return True

    def describe(self) -> str:
        target = self.target.describe() if self.target else ""
        if self.kind == "visible":
            return f"{target} is visible"
        if self.kind == "hidden":
            return f"{target} is hidden or absent"
        if self.kind == "checked":
            return f"{target} is checked"
        if self.kind == "unchecked":
            return f"{target} is not checked"
        if self.kind == "no_errors":
            return "no uncaught exceptions or console errors"
        if self.kind == "count":
            if self.min is not None and self.max is not None:
                bound = f"between {self.min} and {self.max}" if self.min != self.max else f"exactly {self.min}"
            elif self.min is not None:
                bound = f"at least {self.min}"
            else:
                bound = f"at most {self.max}"
            return f"{bound} × {target}"
        subject = {
            "text": f"text of {target}",
            "value": f"value of {target}",
            "attribute": f'attribute "{self.attribute}" of {target}',
            "css": f'css "{self.css_property}" of {target}',
            "url": "page URL",
            "title": "page title",
        }[self.kind]
        return f"{subject} {self._describe_comparators()}"

    def _describe_comparators(self) -> str:
        parts: list[str] = []
        if self.equals is not None:
            parts.append(f'equals "{self.equals}"')
        if self.contains is not None:
            parts.append(f'contains "{self.contains}"')
        if self.matches is not None:
            parts.append(f"matches /{self.matches}/")
        if self.changed is not None:
            parts.append("changes" if self.changed else "stays the same")
        return " and ".join(parts)


class Check(BaseModel):
    """Steps to perform, then expectations that must all hold."""

    model_config = ConfigDict(extra="ignore")

    steps: list[Step] = Field(default_factory=list)
    expect: list[Expectation] = Field(min_length=1)

    def describe_lines(self) -> list[str]:
        lines = [f"do:     {s.describe()}" for s in self.steps]
        lines.extend(f"expect: {e.describe()}" for e in self.expect)
        return lines


class ExpectationOutcome(BaseModel):
    """What the browser observed for one expectation."""

    description: str
    passed: bool
    actual: str = ""


class CheckResult(BaseModel):
    """Outcome of executing one check against the live application."""

    criterion_id: str
    passed: bool
    outcomes: list[ExpectationOutcome] = Field(default_factory=list)
    failed_step: Optional[str] = None
    # A step could not act on its target. Either the feature is missing or the
    # check named it differently, so this is not proof of broken behaviour.
    blocked: bool = False
    # Locator vocabulary of the page at the moment a step was blocked.
    ui_at_failure: str = ""
    page_errors: list[str] = Field(default_factory=list)
    console_errors: list[str] = Field(default_factory=list)
    duration_seconds: float = 0.0
    # Evidence files, when the runner was given an artifacts directory.
    screenshot: Optional[str] = None
    trace: Optional[str] = None

    def summary(self) -> str:
        """One-line evidence statement."""
        if self.failed_step:
            return f"Could not perform {self.failed_step}"
        if self.passed:
            return "Executed in browser: " + "; ".join(o.description for o in self.outcomes)
        failed = [o for o in self.outcomes if not o.passed]
        return "; ".join(f"expected {o.description}, got {o.actual}" for o in failed)

    def failure_report(self) -> str:
        """Multi-line expected-vs-actual report used in repair prompts."""
        status = "BLOCKED" if self.blocked else "FAILED"
        lines = [f"[{self.criterion_id}] executable check {status}"]
        if self.failed_step:
            lines.append(f"  could not perform {self.failed_step}")
        if self.ui_at_failure:
            lines.append("  the page offered instead:")
            lines.extend(f"    {line}" for line in self.ui_at_failure.splitlines()[:20])
        for o in self.outcomes:
            if not o.passed:
                lines.append(f"  expected: {o.description}")
                lines.append(f"  actual:   {o.actual}")
        for err in self.page_errors[:3]:
            lines.append(f"  uncaught exception: {err}")
        return "\n".join(lines)
