"""Executes acceptance checks in real Chromium against a fixture app served over HTTP."""

from pathlib import Path

import pytest

from contexer.verification.checks import Check
from contexer.verification.runner import CheckRunner
from contexer.workflow.app_server import StaticAppServer

FIXTURE_APP = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Shop Fixture</title>
  <style>
    body { background: rgb(255, 255, 255); }
    body.dark { background: rgb(17, 17, 17); }
    .mobile-only { display: none; }
  </style>
</head>
<body>
  <nav><a class="mobile-only" href="#">Menu</a><a href="#">Menu</a></nav>
  <h1>Shop Fixture</h1>
  <button id="add">Add to cart</button>
  <span data-testid="cart-count">0</span>
  <button id="theme" aria-label="Toggle dark mode">Theme</button>
  <form id="newsletter">
    <input id="email" placeholder="Email">
    <button type="submit">Subscribe</button>
  </form>
  <p id="thanks" hidden>Thanks for subscribing!</p>
  <button id="checkout">Checkout</button>
  <div id="late"></div>
  <script>
    let count = 0;
    document.getElementById("add").addEventListener("click", () => {
      count += 1;
      document.querySelector('[data-testid="cart-count"]').textContent = String(count);
    });
    document.getElementById("theme").addEventListener("click", () => document.body.classList.toggle("dark"));
    document.getElementById("newsletter").addEventListener("submit", (event) => {
      event.preventDefault();
      document.getElementById("thanks").hidden = false;
    });
    document.getElementById("checkout").addEventListener("click", () => {
      setTimeout(() => { undefinedCheckoutHandler(); }, 50);
    });
    setTimeout(() => { document.getElementById("late").textContent = "Recommendations loaded"; }, 400);
  </script>
</body>
</html>
"""


@pytest.fixture
def app_url(tmp_path: Path):
    (tmp_path / "index.html").write_text(FIXTURE_APP, encoding="utf-8")
    with StaticAppServer(tmp_path) as server:
        yield server.url


@pytest.fixture
def runner() -> CheckRunner:
    return CheckRunner(action_timeout=1.0, expect_timeout=1.0)


def check(payload: dict) -> Check:
    return Check.model_validate(payload)


ADD_TO_CART = {"action": "click", "target": {"role": "button", "name": "Add to cart"}}
CART_COUNT = {"test_id": "cart-count"}


@pytest.mark.anyio
async def test_interaction_changes_state(app_url: str, runner: CheckRunner) -> None:
    [result] = await runner.run(
        app_url,
        [("crit-cart", check({"steps": [ADD_TO_CART], "expect": [
            {"kind": "text", "target": CART_COUNT, "contains": "1", "changed": True},
        ]}))],
    )
    assert result.passed, result.failure_report()
    assert result.outcomes[0].actual == '"0" → "1"'


@pytest.mark.anyio
async def test_failed_expectation_reports_what_the_browser_saw(app_url: str, runner: CheckRunner) -> None:
    [result] = await runner.run(
        app_url,
        [("crit-cart", check({"steps": [ADD_TO_CART], "expect": [
            {"kind": "text", "target": CART_COUNT, "equals": "2"},
        ]}))],
    )
    assert not result.passed
    assert result.outcomes[0].actual == '"1"'
    assert 'expected: text of [data-testid="cart-count"] equals "2"' in result.failure_report()


@pytest.mark.anyio
async def test_theme_toggle_verified_by_computed_style_not_class_names(app_url: str, runner: CheckRunner) -> None:
    [result] = await runner.run(
        app_url,
        [("crit-theme", check({
            "steps": [{"action": "click", "target": {"role": "button", "name": "dark mode"}}],
            "expect": [{"kind": "css", "target": {"css": "body"}, "property": "background-color", "changed": True}],
        }))],
    )
    assert result.passed, result.failure_report()
    assert result.outcomes[0].actual == '"rgb(255, 255, 255)" → "rgb(17, 17, 17)"'


@pytest.mark.anyio
async def test_form_flow(app_url: str, runner: CheckRunner) -> None:
    [result] = await runner.run(
        app_url,
        [("crit-form", check({
            "steps": [
                {"action": "fill", "target": {"placeholder": "Email"}, "value": "a@b.co"},
                {"action": "click", "target": {"role": "button", "name": "Subscribe"}},
            ],
            "expect": [
                {"kind": "visible", "target": {"text": "Thanks for subscribing"}},
                {"kind": "value", "target": {"placeholder": "Email"}, "equals": "a@b.co"},
            ],
        }))],
    )
    assert result.passed, result.failure_report()


@pytest.mark.anyio
async def test_missing_interaction_target_fails_the_step(app_url: str, runner: CheckRunner) -> None:
    [result] = await runner.run(
        app_url,
        [("crit-buy", check({
            "steps": [{"action": "click", "target": {"role": "button", "name": "Buy now"}}],
            "expect": [{"kind": "visible", "target": {"text": "Order placed"}}],
        }))],
    )
    assert not result.passed
    assert result.failed_step is not None
    assert result.failed_step.startswith("step 1 'click button \"Buy now\"'")
    assert result.outcomes == []
    # Not proof the feature is broken: the check is blocked, and records what the page offered.
    assert result.blocked is True
    assert 'button "Add to cart"' in result.ui_at_failure
    assert "executable check BLOCKED" in result.failure_report()
    assert "the page offered instead:" in result.failure_report()


@pytest.mark.anyio
async def test_exception_thrown_asynchronously_by_handler_is_caught(app_url: str, runner: CheckRunner) -> None:
    [result] = await runner.run(
        app_url,
        [("crit-checkout", check({
            "steps": [{"action": "click", "target": {"role": "button", "name": "Checkout"}}],
            "expect": [{"kind": "no_errors"}],
        }))],
    )
    assert not result.passed
    assert "undefinedCheckoutHandler" in result.outcomes[0].actual
    assert any("undefinedCheckoutHandler" in e for e in result.page_errors)


@pytest.mark.anyio
async def test_clean_page_passes_no_errors(app_url: str, runner: CheckRunner) -> None:
    [result] = await runner.run(app_url, [("crit-runtime", check({"expect": [{"kind": "no_errors"}]}))])
    assert result.passed, result.failure_report()
    assert result.console_errors == []


@pytest.mark.anyio
async def test_missing_script_fails_no_errors(tmp_path: Path, runner: CheckRunner) -> None:
    (tmp_path / "index.html").write_text('<html><head><script src="/app.js"></script></head><body>x</body></html>')
    with StaticAppServer(tmp_path) as server:
        [result] = await runner.run(server.url, [("crit-runtime", check({"expect": [{"kind": "no_errors"}]}))])
    assert not result.passed
    assert "404" in result.outcomes[0].actual


class _FakeConsoleMessage:
    def __init__(self, type: str, text: str, url: str = "") -> None:
        self.type = type
        self.text = text
        self.location = {"url": url}


def test_console_filter_keeps_only_genuine_errors() -> None:
    from contexer.observer.playwright import record_console_error

    sink: list[str] = []
    record_console_error(_FakeConsoleMessage("warning", "React DevTools hint"), sink)  # type: ignore[arg-type]
    record_console_error(_FakeConsoleMessage("log", "hello"), sink)  # type: ignore[arg-type]
    record_console_error(
        _FakeConsoleMessage("error", "Failed to load resource: 404", "http://127.0.0.1:5000/favicon.ico"),  # type: ignore[arg-type]
        sink,
    )
    record_console_error(
        _FakeConsoleMessage("error", "Failed to load resource: 404", "http://127.0.0.1:5000/app.js"),  # type: ignore[arg-type]
        sink,
    )
    assert sink == ["[error] Failed to load resource: 404"]


@pytest.mark.anyio
async def test_each_check_runs_in_a_fresh_page(app_url: str, runner: CheckRunner) -> None:
    once = {"steps": [ADD_TO_CART], "expect": [{"kind": "text", "target": CART_COUNT, "equals": "1"}]}
    results = await runner.run(app_url, [("a", check(once)), ("b", check(once))])
    assert [r.passed for r in results] == [True, True]


@pytest.mark.anyio
async def test_expectations_wait_for_late_content(app_url: str, runner: CheckRunner) -> None:
    [result] = await runner.run(
        app_url, [("crit-late", check({"expect": [{"kind": "visible", "target": {"text": "Recommendations loaded"}}]}))]
    )
    assert result.passed, result.failure_report()


@pytest.mark.anyio
async def test_hidden_duplicates_do_not_mask_visible_elements(app_url: str, runner: CheckRunner) -> None:
    [result] = await runner.run(
        app_url,
        [("crit-nav", check({
            "steps": [{"action": "click", "target": {"css": "nav a"}}],
            "expect": [
                {"kind": "visible", "target": {"text": "Menu"}},
                {"kind": "hidden", "target": {"text": "Thanks for subscribing"}},
                {"kind": "count", "target": {"css": "nav a"}, "min": 2, "max": 2},
            ],
        }))],
    )
    assert result.passed, result.failure_report()


@pytest.mark.anyio
async def test_unreachable_app_fails_navigation(runner: CheckRunner) -> None:
    [result] = await runner.run(
        "http://127.0.0.1:9/", [("crit-runtime", check({"expect": [{"kind": "no_errors"}]}))]
    )
    assert not result.passed
    assert result.failed_step is not None and result.failed_step.startswith("navigation to")
    assert result.blocked is False  # an unreachable app is a real failure


@pytest.mark.anyio
async def test_timeout_scale_gives_a_slow_dev_server_time_to_answer(tmp_path: Path) -> None:
    # The text appears 3 s after the click, like a cold API route compiling on first use.
    page = (
        "<!doctype html><meta charset='utf-8'><button onclick=\"setTimeout(() => "
        "document.body.insertAdjacentHTML('beforeend', '<p>Saved</p>'), 3000)\">Save</button>"
    )
    (tmp_path / "index.html").write_text(page, encoding="utf-8")
    check = Check.model_validate(
        {"steps": [{"action": "click", "target": {"role": "button", "name": "Save"}}],
         "expect": [{"kind": "visible", "target": {"text": "Saved"}}]}
    )
    runner = CheckRunner(expect_timeout=2.0)
    with StaticAppServer(tmp_path) as server:
        [strict] = await runner.run(server.url, [("strict", check)])
        [patient] = await runner.run(server.url, [("patient", check)], timeout_scale=2.5)
    assert not strict.passed
    assert patient.passed
    assert runner.expect_timeout == 2.0  # the scale applies to that run only
