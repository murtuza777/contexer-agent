"""Tests for PlaywrightObserver."""

import pytest
from contexer.observer.playwright import PlaywrightObserver


@pytest.mark.anyio
async def test_playwright_observe_data_url():
    observer = PlaywrightObserver(headless=True)
    html_content = (
        "data:text/html,<html><head><title>Contexer App</title></head>"
        "<body><h1>Welcome</h1><button id='cta'>Get Started</button></body></html>"
    )
    obs = await observer.observe(html_content, timeout=10.0, screenshot=False)
    assert obs.success is True
    assert obs.page_title == "Contexer App"
    assert "Welcome" in obs.visible_text
    assert "Get Started" in obs.visible_text
    assert obs.status_code is None or obs.status_code == 200
    assert len(obs.console_errors) == 0


@pytest.mark.anyio
async def test_playwright_observe_unreachable_url():
    observer = PlaywrightObserver(headless=True)
    obs = await observer.observe("http://127.0.0.1:59999/nonexistent", timeout=2.0, screenshot=False)
    assert obs.success is False
    assert obs.error is not None
