"""Executes acceptance checks against a live application in a real browser."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Optional, cast
from urllib.parse import urljoin

from contexer.observer.playwright import capture_ui_snapshot, record_console_error
from contexer.verification.checks import (
    Check,
    CheckResult,
    Expectation,
    ExpectationOutcome,
    Locator,
    MissingSecretError,
    Step,
    expand_secrets,
    redact,
)

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Locator as PWLocator, Page

logger = logging.getLogger(__name__)

_MISSING = "<no matching element>"
_COMPARATOR_KINDS = {"text", "value", "attribute", "css", "url", "title"}
_VISIBILITY_SCAN_LIMIT = 20

TraceMode = Literal["off", "on", "on-failure"]


class SignInError(Exception):
    """The configured login flow did not reach a signed-in state."""


class CheckRunner:
    """Runs each check in a fresh browser context.

    Isolation matters: a check that mutates state (cart, theme, auth) must not
    leak into the next one. Expectations auto-retry until ``expect_timeout`` so
    asynchronous UI updates are not reported as failures.

    With an ``artifacts_dir``, each check leaves a screenshot of the page as it
    was judged, and (per ``trace``) a Playwright trace for the trace viewer.
    """

    def __init__(
        self,
        headless: bool = True,
        navigation_timeout: float = 15.0,
        action_timeout: float = 3.0,
        expect_timeout: float = 2.0,
        settle_ms: int = 250,
        trace: TraceMode = "off",
    ) -> None:
        self.headless = headless
        self.navigation_timeout = navigation_timeout
        self.action_timeout = action_timeout
        self.expect_timeout = expect_timeout
        self.settle_ms = settle_ms
        self.trace = trace

    async def run(
        self,
        url: str,
        checks: list[tuple[str, Check]],
        artifacts_dir: Optional[Path] = None,
        storage_state: Optional[dict[str, Any]] = None,
    ) -> list[CheckResult]:
        """Execute ``(criterion_id, check)`` pairs in order and return one result each.

        ``storage_state`` is a signed-in session (from :meth:`sign_in`); checks
        run with it unless they say ``"login": false``.
        """
        if not checks:
            return []
        from playwright.async_api import async_playwright

        if artifacts_dir is not None:
            artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=self.headless)
                try:
                    return [
                        await self._run_one(browser, url, cid, check, artifacts_dir, storage_state)
                        for cid, check in checks
                    ]
                finally:
                    await browser.close()
        except Exception as exc:
            logger.warning("Browser unavailable for check execution: %s", exc)
            return [
                CheckResult(criterion_id=cid, passed=False, failed_step=f"browser launch ({_short(exc)})")
                for cid, _ in checks
            ]

    async def sign_in(
        self,
        base_url: str,
        path: str,
        flow: Check,
        screenshot: Optional[Path] = None,
    ) -> dict[str, Any]:
        """Run the login flow once and return the signed-in browser state.

        The state (cookies, local storage) is kept in memory and handed to each
        check's fresh context; it is never written to disk. Raises
        :class:`SignInError` with the failure report when the flow's
        expectations do not hold.
        """
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            try:
                context = await browser.new_context(viewport={"width": 1280, "height": 800}, ignore_https_errors=True)
                try:
                    result, page = await self._exercise(context, urljoin(base_url, path), "sign-in", flow)
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
        artifacts_dir: Optional[Path],
        storage_state: Optional[dict[str, Any]] = None,
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
        tracing = self.trace != "off" and artifacts_dir is not None
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
        page: Optional[Page],
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
    ) -> tuple[CheckResult, Optional[Page]]:
        started = time.monotonic()
        page_errors: list[str] = []
        console_errors: list[str] = []
        # Expanded ${NAME} values; masked in everything the result records.
        secret_values: list[str] = []

        def finish(
            passed: bool,
            outcomes: Optional[list[ExpectationOutcome]] = None,
            failed_step: Optional[str] = None,
            ui_at_failure: Optional[str] = None,
            blocked: Optional[bool] = None,
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
                duration_seconds=time.monotonic() - started,
            ).redacted(secret_values)

        missing = [name for name in check.secrets() if name not in os.environ]
        if missing:
            return finish(False, failed_step=f"secret(s) not set: {', '.join(missing)} (set them in the environment or .env)"), None
        secret_values.extend(os.environ[name] for name in check.secrets())

        page: Optional[Page] = None
        try:
            page = await context.new_page()
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.on("console", lambda msg: record_console_error(msg, console_errors))

            try:
                await page.goto(url, wait_until="load", timeout=self.navigation_timeout * 1000)
            except Exception as exc:
                return finish(False, failed_step=f"navigation to {url} ({_short(exc)})"), page

            baselines: dict[int, Optional[str]] = {}
            for i, exp in enumerate(check.expect):
                if exp.changed is not None and exp.kind in _COMPARATOR_KINDS:
                    baselines[i] = await self._read_or_none(page, exp)

            for n, step in enumerate(check.steps, 1):
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

            # Behavioural expectations first (they poll); error accounting last
            # so exceptions thrown asynchronously by the interaction are counted.
            outcomes: dict[int, ExpectationOutcome] = {}
            for i, exp in enumerate(check.expect):
                if exp.kind != "no_errors":
                    outcomes[i] = await self._evaluate(page, exp, baselines.get(i))
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

    # -- steps ----------------------------------------------------------------

    async def _perform(self, page: Page, step: Step, base_url: str) -> None:
        timeout = self.action_timeout * 1000
        value = expand_secrets(step.value or "")
        if step.action == "wait":
            await page.wait_for_timeout(int(value))
            return
        if step.action == "goto":
            await page.goto(urljoin(base_url, value), wait_until="load", timeout=self.navigation_timeout * 1000)
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

    async def _evaluate(self, page: Page, exp: Expectation, before: Optional[str]) -> ExpectationOutcome:
        deadline = time.monotonic() + self.expect_timeout
        while True:
            passed, actual = await self._probe(page, exp, before)
            if passed or time.monotonic() >= deadline:
                return ExpectationOutcome(description=exp.describe(), passed=passed, actual=actual)
            await asyncio.sleep(0.1)

    async def _probe(self, page: Page, exp: Expectation, before: Optional[str]) -> tuple[bool, str]:
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

            if exp.target is not None and await _locate(page, exp.target).count() == 0:
                return exp.compare(None, before), _MISSING
            value = await self._read(page, exp)
            return exp.compare(value, before), _show(value, before, exp)
        except Exception as exc:
            return False, f"error: {_short(exc)}"

    async def _read(self, page: Page, exp: Expectation) -> Optional[str]:
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

    async def _read_or_none(self, page: Page, exp: Expectation) -> Optional[str]:
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


def _show(value: Optional[str], before: Optional[str], exp: Expectation) -> str:
    now = _quote(value)
    if exp.changed is not None:
        return f"{_quote(before)} → {now}"
    return now


def _quote(value: Optional[str]) -> str:
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
