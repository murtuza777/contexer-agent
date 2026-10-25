"""Headless browser observation using Playwright."""

from __future__ import annotations

import base64
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, cast

from contexer.observer.models import BrowserObservation

if TYPE_CHECKING:
    from playwright.async_api import ConsoleMessage, Page

logger = logging.getLogger(__name__)

# Resources whose absence the browser reports as a console error but which say
# nothing about whether the application works.
_IGNORED_RESOURCE_SUFFIXES = ("/favicon.ico",)


def record_console_error(msg: ConsoleMessage, sink: list[str]) -> None:
    """Append genuine console errors to ``sink``; warnings and favicon 404s are not failures."""
    if msg.type != "error":
        return
    location_url = (msg.location or {}).get("url", "")
    if location_url.endswith(_IGNORED_RESOURCE_SUFFIXES):
        return
    sink.append(f"[error] {msg.text}")


UI_SNAPSHOT_MAX_CHARS = 4000

_LOCATOR_EXTRAS_JS = """() => {
    const out = [];
    document.querySelectorAll('[data-testid]').forEach(el => {
        const text = (el.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 40);
        out.push(`[data-testid="${el.getAttribute('data-testid')}"] text="${text}"`);
    });
    document.querySelectorAll('input[placeholder], textarea[placeholder]').forEach(el => {
        out.push(`placeholder="${el.getAttribute('placeholder')}"`);
    });
    return out.slice(0, 60);
}"""


async def capture_ui_snapshot(page: Page) -> str:
    """Locator vocabulary of the rendered page: ARIA tree plus test ids and placeholders.

    The ARIA tree comes from the same accessible-name computation that
    ``get_by_role`` matches against, so names copied from it resolve.
    """
    parts: list[str] = []
    try:
        parts.append(await page.locator("body").aria_snapshot(timeout=3000))
    except Exception as e:
        logger.debug("ARIA snapshot unavailable: %s", e)
    try:
        extras = await page.evaluate(_LOCATOR_EXTRAS_JS)
        if isinstance(extras, list) and extras:
            parts.append("\n".join(f"- {item}" for item in extras))
    except Exception as e:
        logger.debug("Locator extras unavailable: %s", e)
    snapshot = "\n".join(p for p in parts if p).strip()
    snapshot = await _mask_password_values(page, snapshot)
    if len(snapshot) > UI_SNAPSHOT_MAX_CHARS:
        snapshot = snapshot[:UI_SNAPSHOT_MAX_CHARS] + "\n- ... (truncated)"
    return snapshot


_PASSWORD_VALUES_JS = "() => Array.from(document.querySelectorAll('input[type=password]'), i => i.value).filter(Boolean)"


async def _mask_password_values(page: Page, snapshot: str) -> str:
    """The ARIA tree shows what was typed into a password field (``textbox "Password": hunter2``); hide it.

    The snapshot ends up in reports, result.json and prompts to the coding agent's model.
    """
    try:
        values = await page.evaluate(_PASSWORD_VALUES_JS)
    except Exception as e:
        logger.debug("Password fields unavailable: %s", e)
        return snapshot
    if not isinstance(values, list) or not values:
        return snapshot
    suffixes = {f": {v}" for v in values if isinstance(v, str)}
    lines = snapshot.splitlines()
    for i, line in enumerate(lines):
        for suffix in suffixes:
            if line.endswith(suffix):
                lines[i] = line[: -len(suffix)] + ": ••••••"
                break
    return "\n".join(lines)


class PlaywrightObserver:
    """Observes running web applications using headless Playwright."""

    def __init__(self, headless: bool = True) -> None:
        self.headless = headless

    async def observe(
        self,
        url: str,
        timeout: float = 15.0,
        screenshot: bool = True,
        screenshot_dir: Optional[str | Path] = None,
        storage_state: Optional[dict[str, Any]] = None,
    ) -> BrowserObservation:
        """Navigate to URL and capture runtime page state, errors, and DOM."""
        from playwright.async_api import async_playwright, Error as PlaywrightError

        console_errors: list[str] = []
        console_warnings: list[str] = []
        page_errors: list[str] = []

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=self.headless)
                try:
                    context = await browser.new_context(
                        viewport={"width": 1280, "height": 800},
                        ignore_https_errors=True,
                        storage_state=cast(Any, storage_state),
                    )
                    page = await context.new_page()

                    page.on("console", lambda msg: record_console_error(msg, console_errors))
                    page.on(
                        "console",
                        lambda msg: console_warnings.append(f"[warning] {msg.text}")
                        if msg.type == "warning"
                        else None,
                    )
                    page.on(
                        "pageerror",
                        lambda exc: page_errors.append(str(exc)),
                    )

                    response = await page.goto(
                        url,
                        timeout=int(timeout * 1000),
                        wait_until="domcontentloaded",
                    )
                    # Brief settling wait
                    await page.wait_for_timeout(500)

                    status_code = response.status if response else None
                    page_title = await page.title()

                    # Extract visible text from body
                    try:
                        visible_text = await page.inner_text("body", timeout=2000)
                    except Exception:
                        visible_text = ""

                    # Extract HTML
                    try:
                        html = await page.content()
                    except Exception:
                        html = ""

                    # Extract interactive elements (buttons, links, inputs, forms)
                    interactive_elements: list[str] = []
                    try:
                        extracted_els = await page.evaluate("""() => {
                            const elements = [];
                            document.querySelectorAll('button, a, input, select, textarea, form, [role="button"]').forEach(el => {
                                const text = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim();
                                const tag = el.tagName.toLowerCase();
                                const id = el.id ? `#${el.id}` : '';
                                const type = el.type ? `[type="${el.type}"]` : '';
                                if (text || id || tag === 'input' || tag === 'button') {
                                    elements.push(`${tag}${type}${id}: "${text.slice(0, 60)}"`);
                                }
                            });
                            return elements.slice(0, 40);
                        }""")
                        if isinstance(extracted_els, list):
                            interactive_elements = [str(item) for item in extracted_els]
                    except Exception as e:
                        logger.debug("Failed to extract interactive elements: %s", e)

                    ui_snapshot = await capture_ui_snapshot(page)

                    # Extract headings
                    headings: list[str] = []
                    try:
                        extracted_headings = await page.evaluate("""() => {
                            return Array.from(document.querySelectorAll('h1, h2, h3'))
                                .map(h => `${h.tagName}: ${h.innerText.trim()}`)
                                .filter(h => h.length > 4)
                                .slice(0, 20);
                        }""")
                        if isinstance(extracted_headings, list):
                            headings = [str(item) for item in extracted_headings]
                    except Exception as e:
                        logger.debug("Failed to extract headings: %s", e)

                    # Capture screenshot
                    shot_path_str: Optional[str] = None
                    shot_b64: Optional[str] = None
                    if screenshot:
                        try:
                            shot_bytes = await page.screenshot(type="png")
                            shot_b64 = base64.b64encode(shot_bytes).decode("ascii")

                            out_dir = Path(screenshot_dir) if screenshot_dir else Path(".contexer") / "screenshots"
                            out_dir.mkdir(parents=True, exist_ok=True)
                            file_name = f"observation_{time.strftime('%Y%m%d-%H%M%S')}_{time.monotonic_ns() % 1_000_000:06d}.png"
                            save_path = out_dir / file_name
                            save_path.write_bytes(shot_bytes)
                            shot_path_str = str(save_path.resolve())
                        except Exception as e:
                            logger.debug("Screenshot capture skipped: %s", e)

                    return BrowserObservation(
                        url=url,
                        page_title=page_title,
                        visible_text=visible_text.strip(),
                        html=html,
                        console_errors=console_errors,
                        console_warnings=console_warnings,
                        page_errors=page_errors,
                        interactive_elements=interactive_elements,
                        ui_snapshot=ui_snapshot,
                        headings=headings,
                        status_code=status_code,
                        screenshot_path=shot_path_str,
                        screenshot_base64=shot_b64,
                        success=True,
                    )
                finally:
                    await browser.close()

        except PlaywrightError as exc:
            return BrowserObservation(
                url=url,
                success=False,
                error=f"Playwright navigation failed: {exc}",
                console_errors=console_errors,
                page_errors=page_errors,
            )
        except Exception as exc:
            return BrowserObservation(
                url=url,
                success=False,
                error=f"Observer error: {exc}",
                console_errors=console_errors,
                page_errors=page_errors,
            )
