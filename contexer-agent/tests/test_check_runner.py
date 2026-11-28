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


# -- REL-6: a check that fails is replayed once more ---------------------------------------------


@pytest.fixture
def slow_first_load():
    """An app whose first page load shows "Loading" and every later one "Ready"."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    loads = {"n": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path != "/":
                self.send_error(404)
                return
            loads["n"] += 1
            word = "Loading" if loads["n"] == 1 else "Ready"
            body = f"<!doctype html><title>t</title><h1>{word}</h1>".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/", loads
    finally:
        server.shutdown()
        server.server_close()


READY = {"steps": [], "expect": [{"kind": "text", "target": {"role": "heading"}, "equals": "Ready"}]}


@pytest.mark.anyio
async def test_a_check_that_passes_on_the_second_replay_is_flaky(slow_first_load, runner: CheckRunner) -> None:
    url, loads = slow_first_load
    resets: list[int] = []

    async def reset() -> None:
        resets.append(loads["n"])

    [result] = await runner.run(url, [("crit-ready", check(READY))], before_each=reset)

    assert result.passed
    assert result.flaky
    assert '"Loading"' in result.first_failure
    assert "flaky" in result.summary()
    assert resets == [0, 1]  # the app was reset again before the second replay


@pytest.mark.anyio
async def test_a_check_that_fails_twice_is_failed_and_not_flaky(app_url: str, runner: CheckRunner) -> None:
    [result] = await runner.run(
        app_url,
        [("crit-cart", check({"steps": [ADD_TO_CART], "expect": [{"kind": "text", "target": CART_COUNT, "equals": "2"}]}))],
    )
    assert not result.passed and not result.flaky and result.first_failure == ""


@pytest.mark.anyio
async def test_the_second_replay_can_be_turned_off(slow_first_load) -> None:
    url, loads = slow_first_load
    once = CheckRunner(action_timeout=1.0, expect_timeout=1.0, replay_failed=False)
    [result] = await once.run(url, [("crit-ready", check(READY))])
    assert not result.passed and loads["n"] == 1


# -- no_errors waits for the page to go quiet ---------------------------------------------------------

LATE = """<!doctype html><html><body><h1>Late</h1><p id="out"></p><script>
%s
</script></body></html>
"""


async def _no_errors(tmp_path: Path, script: str) -> tuple[object, float]:
    import time

    (tmp_path / "index.html").write_text(LATE % script, encoding="utf-8")
    with StaticAppServer(tmp_path) as server:
        began = time.monotonic()
        [result] = await CheckRunner(action_timeout=1.0, expect_timeout=1.0).run(
            server.url, [("loads-clean", check({"expect": [{"kind": "no_errors"}]}))]
        )
    return result, time.monotonic() - began


@pytest.mark.anyio
async def test_an_error_thrown_after_the_settle_time_is_still_counted(tmp_path: Path) -> None:
    # A slow machine stretches an app's own start-up past any fixed wait; the check must not pass then.
    result, _ = await _no_errors(
        tmp_path,
        'new Promise((done) => setTimeout(done, 700)).then(() => { lateAnalytics.track("loaded"); });',
    )

    assert not result.passed
    assert "lateAnalytics" in result.outcomes[0].actual


@pytest.mark.anyio
async def test_an_error_thrown_by_a_timer_a_timer_started_is_counted(tmp_path: Path) -> None:
    result, _ = await _no_errors(tmp_path, "setTimeout(() => setTimeout(() => { secondStage(); }, 300), 300);")

    assert not result.passed and "secondStage" in result.outcomes[0].actual


@pytest.mark.anyio
async def test_a_page_that_never_goes_quiet_is_not_waited_for_for_ever(tmp_path: Path) -> None:
    result, seconds = await _no_errors(
        tmp_path,
        'let n = 0; function tick() { n += 1; document.getElementById("out").textContent = n; setTimeout(tick, 100); } tick();',
    )

    assert result.passed, result.failure_report()
    assert seconds < 8  # a bounded wait: a clock or a poller is not an error


@pytest.mark.anyio
async def test_a_timer_far_in_the_future_is_not_waited_for(tmp_path: Path) -> None:
    result, seconds = await _no_errors(tmp_path, "setTimeout(() => { sessionTimeout(); }, 60000);")

    assert result.passed and seconds < 6  # stated limit: what happens a minute later is outside a check


@pytest.mark.anyio
async def test_the_apps_timers_behave_as_before(tmp_path: Path) -> None:
    script = (
        'const cancelled = setTimeout(() => { document.getElementById("out").textContent = "wrong"; }, 50);'
        "clearTimeout(cancelled);"
        'setTimeout((a, b) => { document.getElementById("out").textContent = a + b; }, 80, "ar", "gs");'
        'setTimeout("window.fromString = 1", 10);'
    )
    (tmp_path / "index.html").write_text(LATE % script, encoding="utf-8")
    with StaticAppServer(tmp_path) as server:
        [result] = await CheckRunner(action_timeout=1.0, expect_timeout=1.0).run(
            server.url,
            [("timers", check({"expect": [{"kind": "text", "target": {"css": "#out"}, "equals": "args"}, {"kind": "no_errors"}]}))],
        )

    assert result.passed, result.failure_report()


# -- AGT-4: one HTTP request to the app, with the check's session -------------------------------------


@pytest.fixture
def api_app():
    """An app with one API route that answers 200 with data to the session `sid=alice`, and 401 to anyone else."""
    import http.server
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - the name the standard library calls
            if self.path == "/api/notes":
                signed_in = "sid=alice" in (self.headers.get("Cookie") or "")
                body = b'{"notes": ["buy milk"], "owner": "alice"}' if signed_in else b'{"error": "sign in first"}'
                self.send_response(200 if signed_in else 401)
                self.send_header("Content-Type", "application/json")
            elif self.path == "/old":
                body = b""
                self.send_response(302)
                self.send_header("Location", "/api/notes")
            else:
                body = b"<!doctype html><html><body><h1>Notes</h1></body></html>" if self.path == "/" else b"not here"
                self.send_response(200 if self.path == "/" else 404)
                self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()
        server.server_close()


def _alice(url: str) -> dict:
    return {"cookies": [{"name": "sid", "value": "alice", "url": url}], "origins": []}


@pytest.mark.anyio
async def test_a_request_step_is_answered_with_the_checks_own_session(api_app: str, runner: CheckRunner) -> None:
    signed_in = check({
        "steps": [{"action": "request", "value": "GET /api/notes"}],
        "expect": [{"kind": "status", "equals": "200"}, {"kind": "body", "contains": "buy milk"}],
    })
    visitor = check({
        "login": False,
        "steps": [{"action": "request", "value": "GET /api/notes"}],
        "expect": [{"kind": "status", "equals": "401"}, {"kind": "body", "contains": "sign in first"}],
    })
    results = await runner.run(api_app, [("reads-own-notes", signed_in), ("visitor-is-refused", visitor)], storage_state=_alice(api_app))

    assert [r.passed for r in results] == [True, True], [r.failure_report() for r in results]


@pytest.mark.anyio
async def test_a_request_that_gets_another_status_fails_and_says_which(api_app: str, runner: CheckRunner) -> None:
    [result] = await runner.run(
        api_app,
        [("open-to-anyone", check({"login": False, "steps": [{"action": "request", "value": "GET /api/notes"}], "expect": [{"kind": "status", "equals": "200"}]}))],
        storage_state=_alice(api_app),
    )

    assert not result.passed
    assert "status of the response" in result.outcomes[0].description and "401" in result.outcomes[0].actual


@pytest.mark.anyio
async def test_a_redirect_is_reported_and_not_followed(api_app: str, runner: CheckRunner) -> None:
    [result] = await runner.run(
        api_app, [("moved", check({"steps": [{"action": "request", "value": "GET /old"}], "expect": [{"kind": "status", "equals": "302"}]}))]
    )

    assert result.passed, result.failure_report()  # what the app answered, not what the next address answers


@pytest.mark.anyio
async def test_a_status_with_no_request_before_it_fails(api_app: str, runner: CheckRunner) -> None:
    [result] = await runner.run(api_app, [("nothing-asked", check({"expect": [{"kind": "status", "equals": "200"}]}))])

    assert not result.passed and "no request" in result.outcomes[0].actual


def test_a_request_names_a_method_and_a_path_of_the_app_and_nothing_else() -> None:
    from pydantic import ValidationError

    assert check({"steps": [{"action": "request", "value": "delete /api/notes/3"}], "expect": [{"kind": "status", "equals": "204"}]}).steps[0].describe() == "request DELETE /api/notes/3"
    for value in ["/api/notes", "FETCH /api/notes", "GET api/notes", "GET //other.example/x", "GET https://other.example/x", "GET /a b", "GET /api/${TOKEN}"]:
        with pytest.raises(ValidationError):
            check({"steps": [{"action": "request", "value": value}], "expect": [{"kind": "status", "equals": "200"}]})
    with pytest.raises(ValidationError):  # the response has no "before": there is nothing for it to change from
        check({"steps": [{"action": "request", "value": "GET /"}], "expect": [{"kind": "status", "changed": True}]})
    with pytest.raises(ValidationError):
        check({"steps": [{"action": "request", "value": "GET /"}], "expect": [{"kind": "body"}]})
