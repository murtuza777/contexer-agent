"""Shared test doubles."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from contexer.llm.base import LLMProvider, LLMResponse


class FakeLLM(LLMProvider):
    """Scripted provider: returns (or raises) queued replies in order and records every prompt."""

    def __init__(self, *replies: str | Exception) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.kwargs: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return "fake-model"

    async def generate(
        self,
        prompt: str | list[Any],
        system_instruction: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        self.prompts.append(str(prompt))
        self.kwargs.append(dict(kwargs))
        if not self.replies:
            raise AssertionError("FakeLLM received an unexpected call")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return LLMResponse(text=reply)

    def validate_configuration(self) -> tuple[bool, str | None]:
        return True, None


@pytest.fixture
def fake_llm() -> Callable[..., FakeLLM]:
    return FakeLLM


NO_BROWSER_REASON = "needs a browser (--no-browser)"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--no-browser",
        action="store_true",
        default=False,
        help="Skip a test at the moment it starts a browser. For machines with no Chromium installed.",
    )


_wanted_a_browser = pytest.StashKey[bool]()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Any:
    """A browser started in a background task skips that task, and the test then fails waiting for it.

    Such a test asked for a browser under ``--no-browser``, so it is skipped like the others.
    """
    try:
        return (yield)
    except Exception:
        if item.stash.get(_wanted_a_browser, False):
            pytest.skip(NO_BROWSER_REASON)
        raise


@pytest.fixture(autouse=True)
def _no_browser(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """With ``--no-browser``, a test that starts a browser is skipped there; every other test runs whole.

    Which tests need a browser is decided by what they do, not by a list that can fall behind. A
    skip is not an ``Exception``, so code under test that reports a browser that cannot start does
    not take it for one.
    """
    if not request.config.getoption("--no-browser"):
        return
    from playwright.async_api import BrowserType as AsyncBrowserType
    from playwright.sync_api import BrowserType as SyncBrowserType

    def no_launch(*_args: Any, **_kwargs: Any) -> Any:
        request.node.stash[_wanted_a_browser] = True
        pytest.skip(NO_BROWSER_REASON)

    for browser_type in (AsyncBrowserType, SyncBrowserType):
        monkeypatch.setattr(browser_type, "launch", no_launch)
        monkeypatch.setattr(browser_type, "launch_persistent_context", no_launch)


@pytest.fixture(autouse=True)
def _isolated_user_settings(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch):
    """No test reads or writes a real ~/.contexer, and none leaks environment changes into the next."""
    import os

    monkeypatch.setenv("CONTEXER_HOME", str(tmp_path_factory.mktemp("contexer-home")))
    # A developer's own .env may hold an OpenRouter key; asking OpenRouter about it is not hermetic.
    monkeypatch.setattr("contexer.llm.discovery.openrouter_free_quota", lambda *_a, **_k: None)
    # The same for `contexer doctor` asking a provider whether its model can call tools.
    monkeypatch.setattr("contexer.cli.doctor_cli.supports_tools", lambda *_a, **_k: None)
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


@pytest.fixture(autouse=True)
def _forget_allowed_secret_names():
    """What one test let checks read from the environment must not carry over to the next."""
    from contexer.verification import checks

    before = set(checks._allowed_secret_names)
    yield
    checks._allowed_secret_names.clear()
    checks._allowed_secret_names.update(before)
