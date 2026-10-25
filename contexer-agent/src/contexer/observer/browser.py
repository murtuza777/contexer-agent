"""Recognising a missing or broken browser, so users get the fix, not a red herring.

When Playwright's Chromium is not installed, every launch fails with a long
message; surfaced naively it reads as "application unreachable".
"""

from __future__ import annotations

from typing import Optional

INSTALL_HINT = "Chromium for Playwright is not installed. Run: python -m playwright install chromium"
LINUX_DEPS_HINT = "Chromium cannot start: system libraries are missing. Run: python -m playwright install-deps chromium"

_MISSING_MARKERS = (
    "executable doesn't exist",
    "looks like playwright was just installed",
    "please run the following command to download new browsers",
)
_DEPS_MARKERS = ("host system is missing dependencies", "error while loading shared libraries")


def browser_problem(error: Optional[str]) -> Optional[str]:
    """A one-line, actionable diagnosis if ``error`` is a browser-install problem."""
    if not error:
        return None
    lowered = error.lower()
    if any(marker in lowered for marker in _MISSING_MARKERS):
        return INSTALL_HINT
    if any(marker in lowered for marker in _DEPS_MARKERS):
        return LINUX_DEPS_HINT
    return None


async def chromium_status() -> tuple[bool, str]:
    """(ok, detail): whether Chromium can actually launch here."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return False, "The playwright package is missing. Run: pip install playwright"
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            version = browser.version
            await browser.close()
            return True, f"Chromium {version}"
    except Exception as exc:
        return False, browser_problem(str(exc)) or f"Chromium failed to start: {str(exc).splitlines()[0][:200]}"
