"""Tests for OpenRouterProvider with mocked API calls and OpenAI SDK client."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from contexer.llm.base import (
    LLMAuthenticationError,
    LLMChunk,
    LLMError,
    LLMModelUnavailableError,
    LLMNetworkError,
    LLMRateLimitError,
    LLMResponse,
)
from contexer.llm.openrouter import OpenRouterProvider, OPENROUTER_BASE_URL


class TestOpenRouterProviderValidation:
    """OpenRouter configuration validation tests."""

    def test_missing_api_key_fails_validation(self) -> None:
        provider = OpenRouterProvider(api_key=None)
        valid, msg = provider.validate_configuration()
        assert valid is False
        assert msg is not None
        assert "OPENROUTER_API_KEY" in msg

    def test_empty_api_key_fails_validation(self) -> None:
        provider = OpenRouterProvider(api_key="   ")
        valid, msg = provider.validate_configuration()
        assert valid is False
        assert msg is not None

    def test_configured_api_key_passes_validation(self) -> None:
        provider = OpenRouterProvider(api_key="sk-or-v1-valid_test_key_123")
        valid, msg = provider.validate_configuration()
        assert valid is True
        assert msg is None

    def test_default_model_assigned(self) -> None:
        provider = OpenRouterProvider(api_key="sk-or-v1-test_key")
        assert provider.model == "openrouter/free"
        assert provider.name == "openrouter"

    def test_custom_model_assigned(self) -> None:
        provider = OpenRouterProvider(
            api_key="sk-or-v1-test_key", model="meta-llama/llama-3.3-70b-instruct:free"
        )
        assert provider.model == "meta-llama/llama-3.3-70b-instruct:free"


class TestOpenRouterClientInitialization:
    """OpenAI-compatible client initialization for OpenRouter."""

    def test_client_headers_and_base_url(self) -> None:
        provider = OpenRouterProvider(
            api_key="sk-or-v1-test_key",
            site_url="https://contexer.dev",
            app_name="Contexer CLI",
        )
        client = provider._get_client()
        assert str(client.base_url).rstrip("/") == OPENROUTER_BASE_URL.rstrip("/")
        assert client.api_key == "sk-or-v1-test_key"
        assert client.default_headers.get("http-referer") == "https://contexer.dev" or client.default_headers.get("HTTP-Referer") == "https://contexer.dev"
        assert client.default_headers.get("x-title") == "Contexer CLI" or client.default_headers.get("X-Title") == "Contexer CLI"

    def test_missing_api_key_raises_auth_error_on_get_client(self) -> None:
        provider = OpenRouterProvider(api_key=None)
        with pytest.raises(LLMAuthenticationError, match="OpenRouter API key is missing"):
            provider._get_client()


class TestOpenRouterErrorWrapping:
    """Error classification and secret sanitization."""

    def test_wrap_auth_error(self) -> None:
        provider = OpenRouterProvider(api_key="sk-or-v1-secret_test_key_12345")
        mock_response = MagicMock(status_code=401, headers={})
        exc = openai.AuthenticationError(
            message="Incorrect API key provided: sk-or-v1-secret_test_key_12345",
            response=mock_response,
            body=None,
        )
        wrapped = provider._wrap_error(exc)
        assert isinstance(wrapped, LLMAuthenticationError)
        assert "sk-or-v1-secret_test_key_12345" not in str(wrapped)
        assert "sk-or-v1-...[MASKED]" in str(wrapped)

    def test_wrap_rate_limit_error(self) -> None:
        provider = OpenRouterProvider(api_key="sk-or-v1-test_key")
        mock_response = MagicMock(status_code=429, headers={})
        exc = openai.RateLimitError(
            message="Rate limit exceeded: free tier credits depleted",
            response=mock_response,
            body=None,
        )
        wrapped = provider._wrap_error(exc)
        assert isinstance(wrapped, LLMRateLimitError)

    def test_wrap_model_unavailable_error(self) -> None:
        provider = OpenRouterProvider(api_key="sk-or-v1-test_key", model="nonexistent/model")
        mock_response = MagicMock(status_code=404, headers={})
        exc = openai.NotFoundError(
            message="Model not found or no endpoints currently online",
            response=mock_response,
            body=None,
        )
        wrapped = provider._wrap_error(exc)
        assert isinstance(wrapped, LLMModelUnavailableError)

    def test_wrap_network_connection_error(self) -> None:
        provider = OpenRouterProvider(api_key="sk-or-v1-test_key")
        exc = openai.APIConnectionError(request=MagicMock())
        wrapped = provider._wrap_error(exc)
        assert isinstance(wrapped, LLMNetworkError)

    def test_wrap_timeout_error(self) -> None:
        provider = OpenRouterProvider(api_key="sk-or-v1-test_key")
        exc = openai.APITimeoutError(request=MagicMock())
        wrapped = provider._wrap_error(exc)
        assert isinstance(wrapped, LLMNetworkError)

    def test_wrap_generic_error(self) -> None:
        provider = OpenRouterProvider(api_key="sk-or-v1-test_key")
        exc = Exception("Unexpected server glitch")
        wrapped = provider._wrap_error(exc)
        assert isinstance(wrapped, LLMError)
        assert not isinstance(wrapped, LLMAuthenticationError)


class TestOpenRouterGenerationMocked:
    """Mocked generate and stream calls."""

    def test_generate_success(self) -> None:
        provider = OpenRouterProvider(api_key="sk-or-v1-test_key")

        mock_choice = MagicMock()
        mock_choice.message.content = "Here is the code solution"
        mock_choice.message.tool_calls = None

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 20
        mock_usage.completion_tokens = 30
        mock_usage.total_tokens = 50

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.model = "google/gemma-4-31b-it:free"
        mock_response.usage = mock_usage

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        response = asyncio.run(provider.generate("Explain algorithms"))
        assert isinstance(response, LLMResponse)
        assert response.text == "Here is the code solution"
        assert response.model == "openrouter/free"
        assert response.usage["total_tokens"] == 50

    def test_stream_success(self) -> None:
        provider = OpenRouterProvider(api_key="sk-or-v1-test_key")

        class MockDelta:
            def __init__(self, content: str | None = None) -> None:
                self.content = content
                self.tool_calls = None

        class MockChunkChoice:
            def __init__(self, content: str | None, finish_reason: str | None = None) -> None:
                self.delta = MockDelta(content)
                self.finish_reason = finish_reason

        class MockChunk:
            def __init__(self, content: str | None, finish_reason: str | None = None) -> None:
                self.choices = [MockChunkChoice(content, finish_reason)]

        async def mock_stream_gen(*args, **kwargs):
            yield MockChunk("Hello")
            yield MockChunk(" OpenRouter")
            yield MockChunk(None, finish_reason="stop")

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_stream_gen())
        provider._client = mock_client

        async def collect_stream():
            chunks = []
            async for chunk in provider.stream("Say hello"):
                chunks.append(chunk)
            return chunks

        chunks = asyncio.run(collect_stream())
        assert len(chunks) == 3
        assert chunks[0].text == "Hello"
        assert chunks[1].text == " OpenRouter"
        assert chunks[2].finish_reason == "stop"

    def test_generate_missing_key_raises_auth_error(self) -> None:
        provider = OpenRouterProvider(api_key=None)
        with pytest.raises(LLMAuthenticationError, match="OpenRouter API key is missing"):
            asyncio.run(provider.generate("test"))
