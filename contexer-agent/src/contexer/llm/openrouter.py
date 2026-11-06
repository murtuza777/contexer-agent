"""OpenAI-compatible providers (OpenRouter, OpenAI, gateways) via the OpenAI SDK."""

from __future__ import annotations

import logging
from typing import Any, Optional

from contexer.config.settings import DEFAULT_OPENROUTER_MODEL, OPENROUTER_FREE_ROUTER
from contexer.llm.base import (
    LLMAuthenticationError,
    LLMError,
    LLMModelUnavailableError,
    LLMNetworkError,
    LLMProvider,
    LLMRateLimitError,
    LLMResponse,
    sanitize_sensitive_text,
)

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenAICompatibleProvider(LLMProvider):
    """Any OpenAI-compatible chat completions API (OpenAI, OpenRouter, local gateways)."""

    provider_name = "openai-compatible"
    label = "OpenAI-compatible API"
    key_env = "OPENAI_API_KEY"
    key_help = ""
    default_base_url = "https://api.openai.com/v1"
    default_model = ""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        site_url: Optional[str] = None,
        app_name: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        self._api_key = api_key
        self._model = model or self.default_model
        self._site_url = site_url
        self._app_name = app_name or "Contexer"
        self._base_url = base_url or self.default_base_url
        self._client: Optional[Any] = None

    @property
    def name(self) -> str:
        return self.provider_name

    @property
    def model(self) -> str:
        return self._model

    def validate_configuration(self) -> tuple[bool, Optional[str]]:
        """Verify that the API key (and a model) are configured."""
        if not self._api_key or not self._api_key.strip():
            help_line = f"\nYou can get an API key at {self.key_help}" if self.key_help else ""
            return (
                False,
                f"{self.label} API key is missing. Please configure {self.key_env} in your "
                "environment or in a .env file:\n"
                f"  {self.key_env}=your_key_here{help_line}",
            )
        if not self._model:
            return False, f"No model configured for {self.label}."
        return True, None

    def _request_extras(self) -> dict[str, Any]:
        """Provider-specific request fields; none for a plain OpenAI-compatible API."""
        return {}

    @classmethod
    def for_spec(
        cls, spec: Any, model: Optional[str], base_url: str, api_key: Optional[str] = None
    ) -> OpenAICompatibleProvider:
        """A provider from the BYOK catalogue (Groq, DeepSeek, Gemini, a local Ollama, your own gateway...)."""
        key = api_key or spec.key() or ("local" if spec.local else None)
        provider = cls(api_key=key, model=model, base_url=base_url)
        provider.provider_name = spec.id
        provider.label = spec.label
        provider.key_env = spec.key_env
        provider.key_help = spec.keys_url
        return provider

    def _get_client(self) -> Any:
        """Lazily initialize the AsyncOpenAI client for this endpoint."""
        if self._client is not None:
            return self._client

        valid, error_msg = self.validate_configuration()
        if not valid:
            raise LLMAuthenticationError(error_msg or "Missing API key")

        try:
            from openai import AsyncOpenAI

            headers: dict[str, str] = {}
            if self._site_url:
                headers["HTTP-Referer"] = self._site_url
            if self._app_name:
                headers["X-Title"] = self._app_name

            import asyncio

            current_loop: Optional[asyncio.AbstractEventLoop] = None
            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                pass

            if self._client is not None and getattr(self, "_client_loop", None) is current_loop:
                return self._client

            self._client = AsyncOpenAI(
                base_url=self._base_url,
                api_key=self._api_key,
                default_headers=headers if headers else None,
            )
            self._client_loop = current_loop
            return self._client
        except Exception as exc:
            raise self._wrap_error(exc)

    def _wrap_error(self, exc: Exception) -> LLMError:
        """Map OpenAI SDK errors to sanitized Contexer LLMError subclasses."""
        import openai

        error_str = str(exc)
        clean_msg = sanitize_sensitive_text(
            error_str, sensitive_values=[self._api_key] if self._api_key else None
        )
        lowered = clean_msg.lower()

        if isinstance(exc, openai.AuthenticationError) or "auth" in lowered or "api key" in lowered or "401" in lowered:
            return LLMAuthenticationError(
                f"{self.label} authentication failed: {clean_msg}. "
                f"Please verify your {self.key_env}.",
                original_error=exc,
            )

        if isinstance(exc, openai.RateLimitError) or "429" in lowered or "rate limit" in lowered or "quota" in lowered or "credits" in lowered:
            return LLMRateLimitError(
                f"{self.label} rate limit or credits exceeded: {clean_msg}",
                original_error=exc,
            )

        if isinstance(exc, openai.NotFoundError) or "404" in lowered or "model not found" in lowered or "no such model" in lowered:
            return LLMModelUnavailableError(
                f"{self.label} model '{self._model}' is unavailable: {clean_msg}",
                original_error=exc,
            )

        if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)) or "connect" in lowered or "timeout" in lowered:
            return LLMNetworkError(
                f"Network error communicating with {self.label}: {clean_msg}",
                original_error=exc,
            )

        return LLMError(f"{self.label} API error: {clean_msg}", original_error=exc)

    def _prepare_messages(
        self,
        prompt: str | list[dict[str, Any]],
        system_instruction: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Normalize prompt and system instruction into OpenAI message dicts."""
        messages: list[dict[str, Any]] = []

        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})

        if isinstance(prompt, str):
            messages.append({"role": "user", "content": prompt})
        elif isinstance(prompt, list):
            # If prompt already contains message dicts
            for item in prompt:
                if isinstance(item, dict):
                    # Prevent duplicate system instructions
                    if item.get("role") == "system" and system_instruction:
                        continue
                    messages.append(item)
                elif hasattr(item, "role") and hasattr(item, "content"):
                    messages.append({"role": getattr(item, "role"), "content": getattr(item, "content")})
                else:
                    messages.append({"role": "user", "content": str(item)})

        return messages

    # -- Generation ---------------------------------------------------------

    async def generate(
        self,
        prompt: str | list[Any],
        system_instruction: Optional[str] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a full response."""
        client = self._get_client()
        messages = self._prepare_messages(prompt, system_instruction)

        api_kwargs: dict[str, Any] = {**self._request_extras(), **kwargs}

        try:
            response = await client.chat.completions.create(
                model=self._model,
                messages=messages,
                **api_kwargs,
            )

            choice = response.choices[0]
            message = choice.message
            text = message.content or ""

            usage_dict = {}
            if getattr(response, "usage", None):
                usage_dict = {
                    "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(response.usage, "completion_tokens", 0),
                    "total_tokens": getattr(response.usage, "total_tokens", 0),
                    "prompt_token_count": getattr(response.usage, "prompt_tokens", 0),
                    "candidates_token_count": getattr(response.usage, "completion_tokens", 0),
                    "total_token_count": getattr(response.usage, "total_tokens", 0),
                }

            served = getattr(response, "model", None)
            return LLMResponse(
                text=text,
                # The model that answered: a router or a fallback may differ from the one asked for.
                model=served if isinstance(served, str) and served else self._model,
                usage=usage_dict,
            )
        except Exception as exc:
            raise self._wrap_error(exc)


class OpenRouterProvider(OpenAICompatibleProvider):
    """OpenRouter: one key, many models (including free ones)."""

    provider_name = "openrouter"
    label = "OpenRouter"
    key_env = "OPENROUTER_API_KEY"
    key_help = "https://openrouter.ai/keys"
    default_base_url = OPENROUTER_BASE_URL
    default_model = DEFAULT_OPENROUTER_MODEL

    def _request_extras(self) -> dict[str, Any]:
        # The default is one specific free model; free models come and go, so if it is
        # down, rate-limited or retired, OpenRouter's own fallback list moves on to the
        # free router. A model the user chose is used as given.
        if self._model == DEFAULT_OPENROUTER_MODEL:
            return {"extra_body": {"models": [self._model, OPENROUTER_FREE_ROUTER]}}
        return {}


class OpenAIProvider(OpenAICompatibleProvider):
    """OpenAI, or any compatible gateway reached through OPENAI_BASE_URL."""

    provider_name = "openai"
    label = "OpenAI"
    key_env = "OPENAI_API_KEY"
    key_help = "https://platform.openai.com/api-keys"
    default_model = "gpt-5"
