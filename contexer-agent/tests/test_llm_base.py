"""Tests for LLM base classes, error sanitization, and factory."""

import pytest

from contexer.config.settings import ContexerConfig
from contexer.llm.base import (
    LLMAuthenticationError,
    LLMChunk,
    LLMError,
    LLMModelUnavailableError,
    LLMNetworkError,
    LLMRateLimitError,
    LLMResponse,
    sanitize_sensitive_text,
)
from contexer.llm.factory import create_llm_provider
from contexer.llm.openrouter import OpenRouterProvider


class TestSanitizeSensitiveText:
    """Secret masking tests."""

    def test_masks_openrouter_api_key_pattern(self) -> None:
        raw = "Error calling endpoint with key sk-or-v1-abcdef1234567890abcdef1234567890"
        sanitized = sanitize_sensitive_text(raw)
        assert "sk-or-v1-abcdef1234567890abcdef1234567890" not in sanitized
        assert "sk-or-v1-...[MASKED]" in sanitized

    def test_masks_standard_openai_style_key_pattern(self) -> None:
        raw = "Error calling endpoint with key sk-abcdef1234567890abcdef12345678901234"
        sanitized = sanitize_sensitive_text(raw)
        assert "sk-abcdef1234567890abcdef12345678901234" not in sanitized
        assert "sk-...[MASKED]" in sanitized

    def test_masks_explicit_sensitive_values(self) -> None:
        raw = "Failed connection for secret_token_123456"
        sanitized = sanitize_sensitive_text(raw, sensitive_values=["secret_token_123456"])
        assert "secret_token_123456" not in sanitized
        assert "sec...[MASKED]" in sanitized

    def test_handles_empty_or_none(self) -> None:
        assert sanitize_sensitive_text("") == ""


class TestLLMErrors:
    """Sanitized LLM exception hierarchy."""

    def test_llm_error_sanitizes_message(self) -> None:
        err = LLMError("Failure with key sk-or-v1-abcdef1234567890abcdef1234567890")
        assert "sk-or-v1-abcdef1234567890abcdef1234567890" not in str(err)
        assert "sk-or-v1-...[MASKED]" in str(err)

    def test_subclasses_inherit_llm_error(self) -> None:
        assert issubclass(LLMAuthenticationError, LLMError)
        assert issubclass(LLMRateLimitError, LLMError)
        assert issubclass(LLMNetworkError, LLMError)
        assert issubclass(LLMModelUnavailableError, LLMError)


class TestDataModels:
    """LLMResponse and LLMChunk models."""

    def test_chunk_defaults(self) -> None:
        chunk = LLMChunk(text="hello")
        assert chunk.text == "hello"
        assert chunk.finish_reason is None

    def test_response_defaults(self) -> None:
        resp = LLMResponse(text="output", model="google/gemma-4-31b-it:free", usage={"total": 10})
        assert resp.text == "output"
        assert resp.model == "google/gemma-4-31b-it:free"
        assert resp.usage["total"] == 10


class TestLLMFactory:
    """create_llm_provider routing."""

    def test_creates_openrouter_provider(self) -> None:
        cfg = ContexerConfig(
            llm_provider="openrouter",
            openrouter_api_key="test_key",
            openrouter_model="google/gemma-4-31b-it:free",
        )
        provider = create_llm_provider(cfg)
        assert isinstance(provider, OpenRouterProvider)
        assert provider.name == "openrouter"
        assert provider.model == "google/gemma-4-31b-it:free"

    def test_unsupported_provider_raises_value_error(self) -> None:
        cfg = ContexerConfig(llm_provider="unsupported_vendor")
        with pytest.raises(ValueError, match="Unsupported LLM provider"):
            create_llm_provider(cfg)
