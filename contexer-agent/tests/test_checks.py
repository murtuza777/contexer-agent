"""Tests for the executable acceptance-check DSL (validation, comparison, rendering)."""

import pytest
from pydantic import ValidationError

from contexer.verification.checks import Check, CheckResult, Expectation, ExpectationOutcome, Locator, Step


class TestLocator:
    def test_requires_exactly_one_strategy(self) -> None:
        with pytest.raises(ValidationError, match="exactly one"):
            Locator()
        with pytest.raises(ValidationError, match="exactly one"):
            Locator(text="Buy", css=".buy")

    def test_name_only_valid_with_role(self) -> None:
        with pytest.raises(ValidationError, match="only valid together with 'role'"):
            Locator(name="Buy", text="Buy")

    def test_rejects_unknown_role(self) -> None:
        with pytest.raises(ValidationError, match="unknown ARIA role"):
            Locator(role="widget")

    def test_normalizes_tag_names_and_key_aliases_from_models(self) -> None:
        assert Locator.model_validate({"role": "H2"}).role == "heading"
        assert Locator.model_validate({"role": "input", "name": "Email"}).role == "textbox"
        assert Locator.model_validate({"selector": "#cart"}).css == "#cart"
        assert Locator.model_validate({"data-testid": "cart-count"}).test_id == "cart-count"

    def test_describe(self) -> None:
        assert Locator(role="button", name="Add to cart").describe() == 'button "Add to cart"'
        assert Locator(test_id="cart-count").describe() == '[data-testid="cart-count"]'


class TestStep:
    def test_target_and_value_requirements(self) -> None:
        with pytest.raises(ValidationError, match="needs a target"):
            Step(action="click")
        with pytest.raises(ValidationError, match="needs a value"):
            Step(action="fill", target=Locator(label="Email"))
        Step(action="press", value="Enter")  # target is optional for press

    def test_wait_is_bounded_and_numbers_are_coerced(self) -> None:
        assert Step.model_validate({"action": "wait", "value": 300}).value == "300"
        with pytest.raises(ValidationError, match="milliseconds"):
            Step(action="wait", value="60000")
        with pytest.raises(ValidationError, match="milliseconds"):
            Step(action="wait", value="soon")


class TestExpectation:
    def test_kind_specific_requirements(self) -> None:
        with pytest.raises(ValidationError, match="needs a target"):
            Expectation(kind="visible")
        with pytest.raises(ValidationError, match="needs equals, contains, matches, or changed"):
            Expectation(kind="text", target=Locator(text="x"))
        with pytest.raises(ValidationError, match="needs a property"):
            Expectation(kind="css", target=Locator(css="body"), changed=True)
        with pytest.raises(ValidationError, match="needs min or max"):
            Expectation(kind="count", target=Locator(css="li"))
        with pytest.raises(ValidationError, match="min is greater than max"):
            Expectation(kind="count", target=Locator(css="li"), min=3, max=1)
        with pytest.raises(ValidationError, match="invalid regex"):
            Expectation(kind="url", matches="(unclosed")
        Expectation(kind="no_errors")

    def test_css_property_accepts_dsl_key(self) -> None:
        exp = Expectation.model_validate(
            {"kind": "css", "target": {"css": "body"}, "property": "background-color", "changed": True}
        )
        assert exp.css_property == "background-color"

    def test_compare_contains_is_case_and_whitespace_insensitive(self) -> None:
        exp = Expectation(kind="text", target=Locator(text="x"), contains="add  to Cart")
        assert exp.compare("  ADD TO\ncart ")
        assert not exp.compare("Remove")

    def test_compare_combines_comparators_with_and(self) -> None:
        exp = Expectation(kind="text", target=Locator(text="x"), contains="items", matches=r"^\d+ items$")
        assert exp.compare("3 items")
        assert not exp.compare("many items")

    def test_compare_equals_and_numeric_coercion(self) -> None:
        exp = Expectation.model_validate({"kind": "text", "target": {"test_id": "n"}, "equals": 1})
        assert exp.compare(" 1 ")
        assert not exp.compare("10")

    def test_compare_changed_against_baseline(self) -> None:
        exp = Expectation(kind="text", target=Locator(test_id="n"), changed=True)
        assert exp.compare("1", before="0")
        assert not exp.compare("0", before="0")
        assert exp.compare(None, before="0")  # element disappeared: it changed
        assert not exp.compare(None, before=None)

    def test_absent_value_never_satisfies_value_comparators(self) -> None:
        exp = Expectation(kind="attribute", target=Locator(css="html"), attribute="data-theme", equals="dark")
        assert not exp.compare(None)

    def test_describe(self) -> None:
        assert (
            Expectation(kind="text", target=Locator(test_id="cart-count"), contains="1", changed=True).describe()
            == 'text of [data-testid="cart-count"] contains "1" and changes'
        )
        assert Expectation(kind="count", target=Locator(css="li"), min=3).describe() == "at least 3 × css `li`"


class TestCheck:
    def test_needs_at_least_one_expectation(self) -> None:
        with pytest.raises(ValidationError):
            Check(steps=[Step(action="click", target=Locator(text="Go"))], expect=[])

    def test_parses_full_llm_style_payload(self) -> None:
        check = Check.model_validate(
            {
                "steps": [
                    {"action": "fill", "target": {"placeholder": "Add a task"}, "value": "Buy milk"},
                    {"action": "click", "target": {"role": "button", "name": "Add"}},
                ],
                "expect": [{"kind": "visible", "target": {"text": "Buy milk"}}],
                "note": "extra keys from the model are ignored",
            }
        )
        assert check.describe_lines() == [
            'do:     fill field with placeholder "Add a task" with "Buy milk"',
            'do:     click button "Add"',
            'expect: text "Buy milk" is visible',
        ]


def test_check_result_failure_report_shows_expected_and_actual() -> None:
    result = CheckResult(
        criterion_id="crit-2",
        passed=False,
        outcomes=[
            ExpectationOutcome(description="button \"Buy\" is visible", passed=True, actual="visible"),
            ExpectationOutcome(description='text of [data-testid="n"] contains "1"', passed=False, actual='"0"'),
        ],
        page_errors=["TypeError: cart is undefined"],
    )
    report = result.failure_report()
    assert report.splitlines()[0] == "[crit-2] executable check FAILED"
    assert 'expected: text of [data-testid="n"] contains "1"' in report
    assert 'actual:   "0"' in report
    assert "uncaught exception: TypeError: cart is undefined" in report
    assert "Buy" not in report  # passing expectations are not repair noise
    assert result.summary() == 'expected text of [data-testid="n"] contains "1", got "0"'


def test_checked_attribute_is_read_as_live_state() -> None:
    """The `checked` attribute never changes on click; models mean "is it ticked"."""
    ticked = Expectation.model_validate(
        {"kind": "attribute", "target": {"role": "checkbox", "name": "Done"}, "attribute": "checked", "equals": "checked"}
    )
    assert ticked.kind == "checked"
    assert ticked.describe() == 'checkbox "Done" is checked'
    unticked = Expectation.model_validate(
        {"kind": "attribute", "target": {"role": "checkbox", "name": "Done"}, "attribute": "checked", "equals": "false"}
    )
    assert unticked.kind == "unchecked"
    # Other attributes are untouched.
    other = Expectation.model_validate(
        {"kind": "attribute", "target": {"css": "button"}, "attribute": "aria-pressed", "equals": "true"}
    )
    assert other.kind == "attribute"
