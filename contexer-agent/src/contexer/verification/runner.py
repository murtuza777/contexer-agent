"""Executes acceptance checks against a live application in a real browser."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, Optional, cast
from urllib.parse import urljoin

from contexer.observer.playwright import capture_ui_snapshot, record_console_error
from contexer.verification.checks import Check, CheckResult, Expectation, ExpectationOutcome, Locator, Step

if TYPE_CHECKING:
    from playwright.async_api import Browser, Locator as PWLocator, Page

logger = logging.getLogger(__name__)

_MISSING = "<no matching element>"
_COMPARATOR_KINDS = {"text", "value", "attribute", "css", "url", "title"}
_VISIBILITY_SCAN_LIMIT = 20


class CheckRunner:
    """Runs each check in a fresh browser context.

    Isolation matters: a check that mutates state (cart, theme, auth) must not
    leak into the next one. Expectations auto-retry until ``expect_timeout`` so
    asynchronous UI updates are not reported as failures.
    """

    def __init__(
        self,
        headless: bool = True,
        navigation_timeout: float = 15.0,
        action_timeout: float = 3.0,
        expect_timeout: float = 2.0,
        settle_ms: int = 250,
    ) -> None:
        self.headless = headless
        self.navigation_timeout = navigation_timeout
        self.action_timeout = action_timeout
        self.expect_timeout = expect_timeout
        self.settle_ms = settle_ms

    async def run(self, url: str, checks: list[tuple[str, Check]]) -> list[CheckResult]:
        """Execute ``(criterion_id, check)`` pairs in order and return one result each."""
        if not checks:
            return []
        from playwright.async_api import async_playwright

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=self.headless)
                try:
                    return [await self._run_one(browser, url, cid, check) for cid, check in checks]
                finally:
                    await browser.close()
        except Exception as exc:
            logger.warning("Browser unavailable for check execution: %s", exc)
            return [
                CheckResult(criterion_id=cid, passed=False, failed_step=f"browser launch ({_short(exc)})")
                for cid, _ in checks
            ]

    async def _run_one(self, browser: Browser, url: str, criterion_id: str, check: Check) -> CheckResult:
        started = time.monotonic()
        page_errors: list[str] = []
        console_errors: list[str] = []

        def finish(
            passed: bool,
            outcomes: Optional[list[ExpectationOutcome]] = None,
            failed_step: Optional[str] = None,
            ui_at_failure: Optional[str] = None,
        ) -> CheckResult:
            return CheckResult(
                criterion_id=criterion_id,
                passed=passed,
                outcomes=outcomes or [],
                failed_step=failed_step,
                blocked=ui_at_failure is not None,
                ui_at_failure=ui_at_failure or "",
                page_errors=list(page_errors),
                console_errors=list(console_errors),
                duration_seconds=time.monotonic() - started,
            )

        context = await browser.new_context(viewport={"width": 1280, "height": 800}, ignore_https_errors=True)
        try:
            page = await context.new_page()
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.on("console", lambda msg: record_console_error(msg, console_errors))

            try:
                await page.goto(url, wait_until="load", timeout=self.navigation_timeout * 1000)
            except Exception as exc:
                return finish(False, failed_step=f"navigation to {url} ({_short(exc)})")

            baselines: dict[int, Optional[str]] = {}
            for i, exp in enumerate(check.expect):
                if exp.changed is not None and exp.kind in _COMPARATOR_KINDS:
                    baselines[i] = await self._read_or_none(page, exp)

            for n, step in enumerate(check.steps, 1):
                try:
                    await self._perform(page, step, url)
                except Exception as exc:
                    # A step that cannot act on its target is inconclusive; record
                    # what the page offered so repair (or a human) can tell why.
                    ui = await capture_ui_snapshot(page) if step.target is not None else None
                    return finish(False, failed_step=f"step {n} '{step.describe()}' ({_short(exc)})", ui_at_failure=ui)

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
            return finish(all(o.passed for o in ordered), ordered)
        except Exception as exc:
            logger.debug("Check %s aborted: %s", criterion_id, exc)
            return finish(False, failed_step=f"check execution ({_short(exc)})")
        finally:
            await context.close()

    # -- steps ----------------------------------------------------------------

    async def _perform(self, page: Page, step: Step, base_url: str) -> None:
        timeout = self.action_timeout * 1000
        value = step.value or ""
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
        return page.get_by_role(role, name=loc.name) if loc.name else page.get_by_role(role)
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


def _short(exc: BaseException) -> str:
    """First line of an exception message; Playwright errors carry long call logs."""
    text = str(exc).strip().splitlines()
    return text[0][:200] if text else type(exc).__name__
