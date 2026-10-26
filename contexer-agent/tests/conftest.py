"""Shared test doubles."""

from __future__ import annotations

from typing import Any, AsyncIterator, Callable, Optional

import pytest

from contexer.llm.base import LLMChunk, LLMProvider, LLMResponse


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
        system_instruction: Optional[str] = None,
        tools: Optional[list[Any]] = None,
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

    def stream(
        self,
        prompt: str | list[Any],
        system_instruction: Optional[str] = None,
        tools: Optional[list[Any]] = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMChunk]:
        raise NotImplementedError

    def validate_configuration(self) -> tuple[bool, Optional[str]]:
        return True, None


@pytest.fixture
def fake_llm() -> Callable[..., FakeLLM]:
    return FakeLLM


@pytest.fixture(autouse=True)
def _isolated_user_settings(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch):
    """No test reads or writes a real ~/.contexer, and none leaks environment changes into the next."""
    import os

    monkeypatch.setenv("CONTEXER_HOME", str(tmp_path_factory.mktemp("contexer-home")))
    # A developer's own .env may hold an OpenRouter key; asking OpenRouter about it is not hermetic.
    monkeypatch.setattr("contexer.llm.discovery.openrouter_free_quota", lambda *_a, **_k: None)
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)
