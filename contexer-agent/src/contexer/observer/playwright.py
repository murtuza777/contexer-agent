"""Headless browser observation using Playwright."""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Optional

from contexer.observer.models import BrowserObservation

logger = logging.getLogger(__name__)


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
    ) -> BrowserObservation:
        """Navigate to URL and capture runtime page state, errors, and DOM."""
        from playwright.async_api import async_playwright, Error as PlaywrightError

        console_errors: list[str] = []
        page_errors: list[str] = []

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=self.headless)
                try:
                    context = await browser.new_context(
                        viewport={"width": 1280, "height": 800},
                        ignore_https_errors=True,
                    )
                    page = await context.new_page()

                    page.on(
                        "console",
                        lambda msg: console_errors.append(f"[{msg.type}] {msg.text}")
                        if msg.type in ("error", "warning")
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
                            file_name = f"observation_{int(timeout)}.png"
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
                        page_errors=page_errors,
                        interactive_elements=interactive_elements,
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
