"""Executes acceptance checks against a live application in a real browser."""

from __future__ import annotations

import asyncio
import copy
import logging
import os
import re
import time
import weakref
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast
from urllib.parse import urljoin, urlsplit

from contexer.observer.playwright import capture_ui_snapshot, record_console_error
from contexer.verification.checks import (
    DIALOG_ACTIONS,
    RESPONSE_KINDS,
    TEST_SECRET_PREFIX,
    UNANSWERED_DIALOG,
    Check,
    CheckResult,
    Expectation,
    ExpectationOutcome,
    Locator,
    MissingSecretError,
    Step,
    allow_secret_names,
    expand_secrets,
    redact,
    request_parts,
    secret_allowed,
)

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page
    from playwright.async_api import Locator as PWLocator

logger = logging.getLogger(__name__)

_MISSING = "<no matching element>"
_COMPARATOR_KINDS = {"text", "value", "attribute", "css", "url", "title"}
# How much of a response's body a `body` expectation is compared with.
MAX_RESPONSE_CHARS = 100_000
_NO_REQUEST = "<no request was made>"
_VISIBILITY_SCAN_LIMIT = 20

TraceMode = Literal["off", "on", "on-failure"]


class SignInError(Exception):
    """The configured login flow did not reach a signed-in state."""


# How long a ``no_errors`` check waits for the page's own short timers to finish before it counts errors.
QUIET_TIMEOUT_MS = 3000

# Counts the page's pending short timers, so "no errors" is asked once the app has finished starting and
# not after a fixed wait a slow machine can outlast. The app's timers run exactly as before: the same
# callback, delay, arguments and id. A timer longer than LIMIT, and one given as a string, is not counted.
_PENDING_TIMERS_SCRIPT = """
(() => {
  if (window.__contexerPendingTimers) return;
  const LIMIT = 2000;
  const pending = new Set();
  const set = window.setTimeout, clear = window.clearTimeout;
  window.setTimeout = function (fn, delay, ...args) {
    if (typeof fn !== "function" || (Number(delay) || 0) > LIMIT) return set.call(this, fn, delay, ...args);
    const id = set.call(this, function () {
      pending.delete(id);
      return fn.apply(this, arguments);
    }, delay, ...args);
    pending.add(id);
    return id;
  };
  window.clearTimeout = function (id) {
    pending.delete(id);
    return clear.call(this, id);
  };
  Object.defineProperty(window, "__contexerPendingTimers", { value: () => pending.size });
})();
"""


class CheckRunner:
    """Runs each check in a fresh browser context.

    Isolation matters: a check that mutates state (cart, theme, auth) must not
    leak into the next one. Expectations auto-retry until ``expect_timeout`` so
    asynchronous UI updates are not reported as failures.

    With an ``artifacts_dir``, each check leaves a screenshot of the page as it
    was judged, and (per ``trace``) a Playwright trace for the trace viewer.

    A check that fails is replayed once more, after the reset. One that then
    passes is marked ``flaky``: it counts as passed and is named as flaky
    wherever the result is shown. ``replay_failed=False`` turns that off.
    """

    def __init__(
        self,
        headless: bool = True,
        navigation_timeout: float = 15.0,
        action_timeout: float = 3.0,
        expect_timeout: float = 2.0,
        settle_ms: int = 250,
        trace: TraceMode = "off",
        replay_failed: bool = True,
    ) -> None:
        self.replay_failed = replay_failed
        self.headless = headless
        self.navigation_timeout = navigation_timeout
        self.action_timeout = action_timeout
        self.expect_timeout = expect_timeout
        self.settle_ms = settle_ms
        self.trace = trace
        # What the last `request` step of the check on each page was answered with: status and body.
        self._responses: weakref.WeakKeyDictionary[Any, tuple[int, str]] = weakref.WeakKeyDictionary()

    async def run(
        self,
        url: str,
        checks: list[tuple[str, Check]],
        artifacts_dir: Path | None = None,
        storage_state: dict[str, Any] | None = None,
        before_each: Callable[[], Awaitable[str | None]] | None = None,
        timeout_scale: float = 1.0,
    ) -> list[CheckResult]:
        """Execute ``(criterion_id, check)`` pairs in order and return one result each.

        ``storage_state`` is a signed-in session (from :meth:`sign_in`); checks
        run with it unless they say ``"login": false``. ``before_each`` runs
        before every check (the ``[app] reset`` command) and returns why it
        failed, or ``None``; a check whose reset failed cannot run.
        ``timeout_scale`` stretches every wait for this run (a dev server
        compiles each page and API route the first time it is hit).
        """
        if not checks:
            return []
        if timeout_scale != 1.0:
            scaled = copy.copy(self)
            scaled.navigation_timeout *= timeout_scale
            scaled.action_timeout *= timeout_scale
            scaled.expect_timeout *= timeout_scale
            return await scaled.run(url, checks, artifacts_dir, storage_state, before_each)
        from playwright.async_api import async_playwright

        if artifacts_dir is not None:
            artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=self.headless)
                try:
                    results: list[CheckResult] = []
                    for cid, check in checks:
                        problem = await before_each() if before_each is not None else None
                        if problem:
                            results.append(
                                CheckResult(criterion_id=cid, passed=False, failed_step=f"the [app] reset ({problem})")
                            )
                            continue
                        result = await self._run_one(browser, url, cid, check, artifacts_dir, storage_state)
                        # A check that could not start for want of a sign-in fails the same way every time.
                        if not result.passed and self.replay_failed and not (check.login is True and storage_state is None):
                            result = await self._replay(browser, url, cid, check, artifacts_dir, storage_state, before_each, result)
                        results.append(result)
                    return results
                finally:
                    await browser.close()
        except Exception as exc:
            logger.warning("Browser unavailable for check execution: %s", exc)
            return [
                CheckResult(criterion_id=cid, passed=False, failed_step=f"browser launch ({_short(exc)})")
                for cid, _ in checks
            ]

    async def _replay(
        self,
        browser: Browser,
        url: str,
        criterion_id: str,
        check: Check,
        artifacts_dir: Path | None,
        storage_state: dict[str, Any] | None,
        before_each: Callable[[], Awaitable[str | None]] | None,
        first: CheckResult,
    ) -> CheckResult:
        """Run a failed check once more, from a reset app. Passing now makes it flaky, not failed."""
        if before_each is not None and await before_each():
            return first  # the app could not be reset, so a second replay would prove nothing
        second = await self._run_one(browser, url, criterion_id, check, artifacts_dir, storage_state)
        second.duration_seconds += first.duration_seconds
        if second.passed:
            second.flaky = True
            second.first_failure = first.summary()
            second.trace = second.trace or first.trace  # the trace of the replay that failed
        return second

    async def sign_in(
        self,
        base_url: str,
        path: str,
        flow: Check,
        screenshot: Path | None = None,
    ) -> dict[str, Any]:
        """Run the login flow once and return the signed-in browser state.

        The state (cookies, local storage) is kept in memory and handed to each
        check's fresh context; it is never written to disk. Raises
        :class:`SignInError` with the failure report when the flow's
        expectations do not hold.
        """
        allow_secret_names(flow.secrets())  # the sign-in steps come from contexer.toml, which the person wrote
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            try:
                context = await browser.new_context(viewport={"width": 1280, "height": 800}, ignore_https_errors=True)
                try:
                    result, page = await self._exercise(context, urljoin(base_url, path), "sign-in", flow, stay_on_app=False)
                    if not result.passed:
                        problem = [result.summary()]
                        if page is not None:
                            problem.append(f"the browser ended on {page.url}")
                            alerts = await _alert_text(page)
                            if alerts:
                                problem.append(f'the page says "{alerts}"')
                            if screenshot is not None:
                                try:
                                    screenshot.parent.mkdir(parents=True, exist_ok=True)
                                    await page.screenshot(path=str(screenshot), type="jpeg", quality=70, timeout=5000)
                                except Exception as exc:
                                    logger.debug("Sign-in screenshot skipped: %s", exc)
                        raise SignInError(redact("; ".join(problem), _typed_values(flow)))
                    return cast(dict[str, Any], await context.storage_state())
                finally:
                    await context.close()
            finally:
                await browser.close()

    async def _run_one(
        self,
        browser: Browser,
        url: str,
        criterion_id: str,
        check: Check,
        artifacts_dir: Path | None,
        storage_state: dict[str, Any] | None = None,
    ) -> CheckResult:
        if check.login is True and storage_state is None:
            return CheckResult(
                criterion_id=criterion_id,
                passed=False,
                failed_step="sign-in (this check needs a signed-in user, but contexer.toml has no [auth] section)",
            )
        signed_in = storage_state is not None and check.login is not False
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            ignore_https_errors=True,
            storage_state=cast(Any, storage_state) if signed_in else None,
        )
        await context.add_init_script(_PENDING_TIMERS_SCRIPT)
        # A trace records request headers, so a signed-in check's trace holds the session
        # cookie; CI uploads traces as artifacts. Only an explicit --trace on records them.
        tracing = self.trace != "off" and artifacts_dir is not None and (not signed_in or self.trace == "on")
        try:
            if tracing:
                await context.tracing.start(screenshots=True, snapshots=True)
            result, page = await self._exercise(context, url, criterion_id, check)
            if artifacts_dir is not None:
                await self._capture_evidence(context, page, result, artifacts_dir, tracing)
            return result
        finally:
            await context.close()

    async def _capture_evidence(
        self,
        context: BrowserContext,
        page: Page | None,
        result: CheckResult,
        artifacts_dir: Path,
        tracing: bool,
    ) -> None:
        stem = _file_stem(result.criterion_id)
        if page is not None:
            shot = artifacts_dir / f"{stem}.jpg"
            try:
                await page.screenshot(path=str(shot), type="jpeg", quality=70, timeout=5000)
                result.screenshot = str(shot)
            except Exception as exc:
                logger.debug("Screenshot for %s skipped: %s", result.criterion_id, exc)
        if tracing:
            keep = self.trace == "on" or not result.passed
            trace_path = artifacts_dir / f"{stem}.trace.zip"
            try:
                await context.tracing.stop(path=str(trace_path) if keep else None)
                if keep:
                    result.trace = str(trace_path)
            except Exception as exc:
                logger.debug("Trace for %s skipped: %s", result.criterion_id, exc)

    async def _exercise(
        self,
        context: BrowserContext,
        url: str,
        criterion_id: str,
        check: Check,
        stay_on_app: bool = True,
    ) -> tuple[CheckResult, Page | None]:
        started = time.monotonic()
        page_errors: list[str] = []
        console_errors: list[str] = []
        # Expanded ${NAME} values; masked in everything the result records.
        secret_values: list[str] = []
        dialogs: list[str] = []
        armed: list[str] = []  # how to answer the next dialogs, in order

        def finish(
            passed: bool,
            outcomes: list[ExpectationOutcome] | None = None,
            failed_step: str | None = None,
            ui_at_failure: str | None = None,
            blocked: bool | None = None,
        ) -> CheckResult:
            return CheckResult(
                criterion_id=criterion_id,
                passed=passed,
                outcomes=outcomes or [],
                failed_step=failed_step,
                blocked=ui_at_failure is not None if blocked is None else blocked,
                ui_at_failure=ui_at_failure or "",
                page_errors=list(page_errors),
                console_errors=list(console_errors),
                dialogs=list(dialogs),
                duration_seconds=time.monotonic() - started,
            ).redacted(secret_values)

        refused = [name for name in check.secrets() if not secret_allowed(name)]
        if refused:
            return finish(
                False,
                failed_step=f"${{{refused[0]}}} may not be used in a check: only {TEST_SECRET_PREFIX}* and the names in "
                "[auth] of contexer.toml are read from the environment",
            ), None
        missing = [name for name in check.secrets() if name not in os.environ]
        if missing:
            return finish(False, failed_step=f"secret(s) not set: {', '.join(missing)} (set them in the environment or .env)"), None
        secret_values.extend(os.environ[name] for name in check.secrets())

        page: Page | None = None
        try:
            page = await context.new_page()
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.on("console", lambda msg: record_console_error(msg, console_errors))

            async def answer(dialog: Any) -> None:
                # A confirm, alert or prompt. A step of the check may have said how to answer the next one;
                # otherwise it is dismissed, which is what a browser left alone does, and the result says so.
                how = armed.pop(0) if armed else None
                shown = f'{dialog.type} "{dialog.message[:200]}"'
                try:
                    if how == "accept":
                        await dialog.accept()
                    else:
                        await dialog.dismiss()
                except Exception:  # the page closed it first
                    pass
                dialogs.append(f"{shown} ({'accepted' if how == 'accept' else 'dismissed' if how else UNANSWERED_DIALOG})")

            page.on("dialog", answer)

            try:
                await page.goto(url, wait_until="load", timeout=self.navigation_timeout * 1000)
            except Exception as exc:
                return finish(False, failed_step=f"navigation to {url} ({_short(exc)})"), page

            baselines: dict[int, str | None] = {}
            for i, exp in enumerate(check.expect):
                if exp.changed is not None and exp.kind in _COMPARATOR_KINDS:
                    baselines[i] = await self._read_or_none(page, exp)

            for n, step in enumerate(check.steps, 1):
                if step.action in DIALOG_ACTIONS:
                    armed.append(DIALOG_ACTIONS[step.action])
                    continue
                elsewhere = _left_app(page.url, url) if stay_on_app else ""
                if elsewhere:
                    # An earlier step (a link, a redirect) took the page to another site. Nothing is typed or
                    # clicked there: a check proves the app it was started on. The sign-in from contexer.toml
                    # is the person's own and may pass through a login page elsewhere.
                    return finish(False, failed_step=f"step {n} '{step.describe()}' (the page left the app for {elsewhere}; a check stays on the app under test)"), page
                try:
                    await self._perform(page, step, url)
                except Exception as exc:
                    failed = f"step {n} '{step.describe()}' ({_short(exc)})"
                    if step.target is None:
                        return finish(False, failed_step=failed), page
                    ui = await capture_ui_snapshot(page)
                    target = _locate(page, step.target)
                    if not await _any_visible(target, await target.count()):
                        # The target is not on the page: either the feature is
                        # missing or the check named it differently. Inconclusive.
                        return finish(False, failed_step=failed, ui_at_failure=ui), page
                    # The target was there and the action did not take effect
                    # (state did not change, element disabled or covered): that
                    # is observed behaviour, not a lookup problem.
                    actual = await _describe_failed_action(target, step, exc)
                    outcome = ExpectationOutcome(
                        description=f"step {n} '{step.describe()}' takes effect", passed=False, actual=actual
                    )
                    return finish(False, [outcome], ui_at_failure=ui, blocked=False), page

            await page.wait_for_timeout(self.settle_ms)
            if armed:
                # The check said a dialog would open and none did: the app never asked.
                never = ExpectationOutcome(
                    description=f"a dialog opens for the check to {armed[0]}", passed=False, actual="no dialog opened"
                )
                return finish(False, [never]), page

            # Behavioural expectations first (they poll); error accounting last
            # so exceptions thrown asynchronously by the interaction are counted.
            outcomes: dict[int, ExpectationOutcome] = {}
            for i, exp in enumerate(check.expect):
                if exp.kind != "no_errors":
                    outcomes[i] = await self._evaluate(page, exp, baselines.get(i))
            if any(exp.kind == "no_errors" for exp in check.expect):
                await self._wait_for_quiet(page)
            for i, exp in enumerate(check.expect):
                if exp.kind == "no_errors":
                    errors = page_errors + console_errors
                    outcomes[i] = ExpectationOutcome(
                        description=exp.describe(),
                        passed=not errors,
                        actual="; ".join(errors[:3]) if errors else "no errors",
                    )

            ordered = [outcomes[i] for i in range(len(check.expect))]
            return finish(all(o.passed for o in ordered), ordered), page
        except Exception as exc:
            logger.debug("Check %s aborted: %s", criterion_id, exc)
            return finish(False, failed_step=f"check execution ({_short(exc)})"), page

    async def _wait_for_quiet(self, page: Page) -> None:
        """Wait until the page has no short timer pending, at most ``QUIET_TIMEOUT_MS``.

        An app that throws 150 ms after it loads threw after the fixed settle time on a slow machine, and
        the check passed. A page that never goes quiet (a clock, a poller) is not an error: the wait ends.
        """
        try:
            await page.wait_for_function(
                "() => !window.__contexerPendingTimers || window.__contexerPendingTimers() === 0",
                timeout=QUIET_TIMEOUT_MS,
            )
        except Exception:  # noqa: BLE001 - still busy, or the page navigated away: count what there is
            return
        await page.wait_for_timeout(50)  # the error of the last callback reaches us after its timer is gone

    # -- steps ----------------------------------------------------------------

    async def perform(self, page: Page, step: Step, base_url: str) -> None:
        """Perform one step on ``page``. The browser tools act through this, so exploring and replaying agree."""
        await self._perform(page, step, base_url)

    async def evaluate(self, page: Page, exp: Expectation, before: str | None = None) -> ExpectationOutcome:
        """Evaluate one expectation on ``page``, retrying until it holds or the expectation timeout passes."""
        return await self._evaluate(page, exp, before)

    async def _perform(self, page: Page, step: Step, base_url: str) -> None:
        timeout = self.action_timeout * 1000
        value = expand_secrets(step.value or "")
        if step.action in DIALOG_ACTIONS:
            return  # answered where the check's steps are run; there is nothing to do on the page
        if step.action == "wait":
            await page.wait_for_timeout(int(value))
            return
        if step.action == "goto":
            address = _plain_address(base_url, step.value or "")
            if _site(address) != _site(base_url):
                # A check proves the app it was started on. An address elsewhere proves nothing about it, and
                # is how a check written by a steered model would send something out.
                raise ValueError(f"goto would open another site ({_site(address)}); a check stays on the app under test")
            await page.goto(address, wait_until="load", timeout=self.navigation_timeout * 1000)
            return
        if step.action == "request":
            method, path = request_parts(step.value or "")
            address = _plain_address(base_url, path)
            if _site(address) != _site(base_url):
                raise ValueError(f"request would go to another site ({_site(address)}); a check stays on the app under test")
            # The context's own client: it sends the cookies the check's session has, and stores what it is sent.
            # A redirect is reported, not followed: the check is about what this address answers.
            response = await page.context.request.fetch(
                address, method=method, timeout=self.navigation_timeout * 1000, max_redirects=0, fail_on_status_code=False
            )
            try:
                body = (await response.text())[:MAX_RESPONSE_CHARS]
            except Exception:  # not text
                body = ""
            self._responses[page] = (response.status, body)
            return
        if step.target is None:  # validation guarantees this is a target-less "press"
            await page.keyboard.press(value)
            return

        target = await _first_visible(_locate(page, step.target))
        if step.action == "click":
            await target.click(timeout=timeout)
        elif step.action == "fill":
            await target.fill(value, timeout=timeout)
        elif step.action == "press":
            await target.press(value, timeout=timeout)
        elif step.action == "select":
            await target.select_option(value, timeout=timeout)
        elif step.action == "check":
            await target.check(timeout=timeout)
        elif step.action == "uncheck":
            await target.uncheck(timeout=timeout)
        elif step.action == "hover":
            await target.hover(timeout=timeout)

    # -- expectations ---------------------------------------------------------

    async def _evaluate(self, page: Page, exp: Expectation, before: str | None) -> ExpectationOutcome:
        deadline = time.monotonic() + self.expect_timeout
        while True:
            passed, actual = await self._probe(page, exp, before)
            if passed or time.monotonic() >= deadline:
                return ExpectationOutcome(description=exp.describe(), passed=passed, actual=actual)
            await asyncio.sleep(0.1)

    async def _probe(self, page: Page, exp: Expectation, before: str | None) -> tuple[bool, str]:
        try:
            if exp.kind in ("checked", "unchecked"):
                assert exp.target is not None
                loc = _locate(page, exp.target)
                if await loc.count() == 0:
                    return False, _MISSING
                checked = await (await _first_visible(loc)).is_checked(timeout=500)
                return checked == (exp.kind == "checked"), "checked" if checked else "not checked"

            if exp.kind in ("visible", "hidden", "count"):
                assert exp.target is not None
                loc = _locate(page, exp.target)
                count = await loc.count()
                if exp.kind == "count":
                    ok = (exp.min is None or count >= exp.min) and (exp.max is None or count <= exp.max)
                    return ok, f"{count} matching"
                visible = await _any_visible(loc, count)
                if exp.kind == "visible":
                    return visible, "visible" if visible else (_MISSING if count == 0 else "present but not visible")
                return not visible, "hidden" if not visible else "visible"

            if exp.kind in RESPONSE_KINDS:
                answered = self._responses.get(page)
                if answered is None:
                    return False, _NO_REQUEST
                value = str(answered[0]) if exp.kind == "status" else answered[1]
                return exp.compare(value), _show(value, None, exp)
            if exp.target is not None and await _locate(page, exp.target).count() == 0:
                return exp.compare(None, before), _MISSING
            value = await self._read(page, exp)
            return exp.compare(value, before), _show(value, before, exp)
        except Exception as exc:
            return False, f"error: {_short(exc)}"

    async def _read(self, page: Page, exp: Expectation) -> str | None:
        if exp.kind == "url":
            return page.url
        if exp.kind == "title":
            return await page.title()
        assert exp.target is not None
        el = await _first_visible(_locate(page, exp.target))
        timeout = 500
        if exp.kind == "text":
            return await el.inner_text(timeout=timeout)
        if exp.kind == "value":
            return await el.input_value(timeout=timeout)
        if exp.kind == "attribute":
            assert exp.attribute is not None
            return await el.get_attribute(exp.attribute, timeout=timeout)
        if exp.kind == "css":
            return await el.evaluate(
                "(el, prop) => getComputedStyle(el).getPropertyValue(prop)", exp.css_property, timeout=timeout
            )
        raise ValueError(f"'{exp.kind}' has no readable value")

    async def _read_or_none(self, page: Page, exp: Expectation) -> str | None:
        try:
            if exp.target is not None and await _locate(page, exp.target).count() == 0:
                return None
            return await self._read(page, exp)
        except Exception:
            return None


def _locate(page: Page, loc: Locator) -> PWLocator:
    if loc.role:
        role = cast(Any, loc.role)
        if not loc.name:
            return page.get_by_role(role)
        # The accessible name wins over visible text (aria-label="Delete Buy milk"
        # on a button showing "×"). A check naming what the user *sees* should
        # still find it, so a role element whose visible text matches counts too.
        return page.get_by_role(role, name=loc.name).or_(page.get_by_role(role).filter(has_text=loc.name))
    if loc.text:
        return page.get_by_text(loc.text)
    if loc.label:
        return page.get_by_label(loc.label)
    if loc.placeholder:
        return page.get_by_placeholder(loc.placeholder)
    if loc.test_id:
        return page.get_by_test_id(loc.test_id)
    assert loc.css is not None
    return page.locator(loc.css)


async def _first_visible(loc: PWLocator) -> PWLocator:
    """Prefer the first visible match (responsive layouts often render duplicates).

    Falls back to the first match so Playwright's own auto-wait still applies
    to elements that have not rendered yet.
    """
    count = await loc.count()
    for i in range(min(count, _VISIBILITY_SCAN_LIMIT)):
        candidate = loc.nth(i)
        if await candidate.is_visible():
            return candidate
    return loc.first


async def _any_visible(loc: PWLocator, count: int) -> bool:
    for i in range(min(count, _VISIBILITY_SCAN_LIMIT)):
        if await loc.nth(i).is_visible():
            return True
    return False


async def _describe_failed_action(target: PWLocator, step: Step, exc: BaseException) -> str:
    """What the page did instead of honouring a step whose target was present."""
    element = await _first_visible(target)
    if step.action in ("check", "uncheck"):
        try:
            checked = await element.is_checked(timeout=500)
            state = "checked" if checked else "unchecked"
            return f"clicked it, but it stayed {state}"
        except Exception:
            pass
    try:
        if not await element.is_enabled(timeout=500):
            return "the element is disabled"
    except Exception:
        pass
    return f"the action did not complete: {_short(exc)}"


# Public names for what the browser tools share with this module.
locate = _locate
any_visible = _any_visible
describe_failed_action = _describe_failed_action


def _typed_values(flow: Check) -> list[str]:
    """Everything a sign-in flow types is a credential, whether literal or ``${NAME}``."""
    values: list[str] = []
    for step in flow.steps:
        if step.action == "fill" and step.value:
            try:
                values.append(expand_secrets(step.value))
            except MissingSecretError:
                continue  # never typed, so it cannot appear anywhere
    return values


async def _alert_text(page: Page) -> str:
    """Visible role="alert" messages, such as "Invalid email or password"."""
    try:
        texts = await page.get_by_role("alert").all_inner_texts()
    except Exception:
        return ""
    return " / ".join(t.strip() for t in texts if t.strip())[:200]


def _show(value: str | None, before: str | None, exp: Expectation) -> str:
    now = _quote(value)
    if exp.changed is not None:
        return f"{_quote(before)} → {now}"
    return now


def _quote(value: str | None) -> str:
    if value is None:
        return "<absent>"
    flat = " ".join(value.split())
    return f'"{flat[:117]}..."' if len(flat) > 120 else f'"{flat}"'


def _file_stem(criterion_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", criterion_id).strip("._") or "check"


def _short(exc: BaseException) -> str:
    """First line of an exception message; Playwright errors carry long call logs."""
    text = str(exc).strip().splitlines()
    return text[0][:200] if text else type(exc).__name__


short_error = _short


def _plain_address(base_url: str, value: str) -> str:
    """The address a ``goto`` opens, or ValueError when a browser could read it differently from this code.

    Python and a browser do not parse every address alike: a browser treats ``\\`` as ``/`` and drops tabs and
    newlines, so ``http://other\\@app/`` is ``app`` here and ``other`` there. Such an address is refused, as
    is one with a user name in it, and one with ``${NAME}`` in it: a secret is typed into a field, never
    put where it would be sent.
    """
    if "${" in value:
        raise ValueError("a goto address may not contain ${...}; a secret is typed with fill, never put in an address")
    if "\\" in value or any(ord(ch) < 0x20 or ch == "\x7f" for ch in value):
        raise ValueError("a goto address may not contain a backslash or a control character")
    address = urljoin(base_url, value)
    if "@" in urlsplit(address).netloc:
        raise ValueError("a goto address may not contain a user name")
    return address


def _left_app(page_url: str, base_url: str) -> str:
    """The site the page is on when that is not the app's, else ''. A blank page has left nothing."""
    if not page_url.startswith(("http://", "https://")):
        return ""
    return "" if _site(page_url) == _site(base_url) else _site(page_url)


def _site(address: str) -> str:
    """Scheme, host and port of an address; ``localhost`` and ``127.0.0.1`` are the same machine."""
    parts = urlsplit(address)
    host = (parts.hostname or "").lower()
    host = "localhost" if host in ("127.0.0.1", "::1") else host
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return f"{parts.scheme}://{host}:{port}"
