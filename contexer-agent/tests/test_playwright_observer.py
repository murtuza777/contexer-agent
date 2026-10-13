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


@pytest.mark.anyio
async def test_console_warnings_are_not_errors():
    observer = PlaywrightObserver(headless=True)
    page = (
        "data:text/html,<html><body><h1>Hi</h1><script>"
        "console.warn('deprecated prop');console.error('payment widget failed');"
        "</script></body></html>"
    )
    obs = await observer.observe(page, timeout=10.0, screenshot=False)
    assert obs.console_errors == ["[error] payment widget failed"]
    assert obs.console_warnings == ["[warning] deprecated prop"]


@pytest.mark.anyio
async def test_ui_snapshot_lists_locator_vocabulary():
    observer = PlaywrightObserver(headless=True)
    page = (
        "data:text/html,<html><body><h1>My Tasks</h1>"
        "<input placeholder='What needs doing?'><button aria-label='Add task'>+</button>"
        "<span data-testid='remaining-count'>2</span></body></html>"
    )
    obs = await observer.observe(page, timeout=10.0, screenshot=False)
    assert 'heading "My Tasks"' in obs.ui_snapshot
    assert 'button "Add task"' in obs.ui_snapshot  # accessible name, not the "+" glyph
    assert '[data-testid="remaining-count"] text="2"' in obs.ui_snapshot
    assert 'placeholder="What needs doing?"' in obs.ui_snapshot
