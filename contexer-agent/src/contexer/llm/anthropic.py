"""Anthropic Messages API provider (plain httpx; no extra dependency).

Used for compiling goals into checks, where model quality decides how many
bugs a contract catches. Tool calling is not needed there and is not
implemented; ``stream`` yields the complete reply as one chunk.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Optional

import httpx

from contexer.llm.base import (
    LLMAuthenticationError,
    LLMChunk,
    LLMError,
    LLMModelUnavailableError,
    LLMNetworkError,
    LLMProvider,
    LLMRateLimitError,
    LLMResponse,
    sanitize_sensitive_text,
)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"
DEFAULT_MAX_TOKENS = 16_000


class AnthropicProvider(LLMProvider):
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        timeout: float = 300.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self._api_key = api_key
        self._model = model or DEFAULT_ANTHROPIC_MODEL
        self._url = base_url or ANTHROPIC_API_URL
        self._max_tokens = max_tokens
        self._timeout = timeout
        self._transport = transport

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def model(self) -> str:
        return self._model

    def validate_configuration(self) -> tuple[bool, Optional[str]]:
        if not self._api_key or not self._api_key.strip():
            return (
                False,
                "Anthropic API key is missing. Please configure ANTHROPIC_API_KEY in your environment "
                "or in a .env file:\n  ANTHROPIC_API_KEY=your_key_here\n"
                "You can get an API key at https://console.anthropic.com/settings/keys",
            )
        return True, None

    async def generate(
        self,
        prompt: str | list[Any],
        system_instruction: Optional[str] = None,
        tools: Optional[list[Any]] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """One Messages API call. OpenAI-only options (e.g. ``response_format``) are ignored."""
        valid, error = self.validate_configuration()
        if not valid:
            raise LLMAuthenticationError(error or "Missing API key")
        if tools:
            raise LLMError("The Anthropic provider here does not implement tool calling.")

        body: dict[str, Any] = {
            "model": self._model,
            "max_tokens": int(kwargs.get("max_tokens") or self._max_tokens),
            "messages": _messages(prompt),
        }
        if system_instruction:
            body["system"] = system_instruction
        headers = {
            "x-api-key": self._api_key or "",
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                response = await client.post(self._url, headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise LLMNetworkError(f"Network error communicating with Anthropic: {self._clean(str(exc))}", exc) from exc

        if response.status_code >= 400:
            raise self._error_for(response)
        data = response.json()
        text = "".join(
            block.get("text", "") for block in data.get("content") or [] if block.get("type") == "text"
        )
        usage = data.get("usage") or {}
        return LLMResponse(
            text=text,
            model=str(data.get("model") or self._model),
            usage={
                "prompt_tokens": int(usage.get("input_tokens") or 0),
                "completion_tokens": int(usage.get("output_tokens") or 0),
                "total_tokens": int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0),
            },
            metadata={"stop_reason": data.get("stop_reason")},
        )

    async def stream(
        self,
        prompt: str | list[Any],
        system_instruction: Optional[str] = None,
        tools: Optional[list[Any]] = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMChunk]:
        response = await self.generate(prompt, system_instruction, tools, **kwargs)
        yield LLMChunk(text=response.text, finish_reason="stop")

    def _error_for(self, response: httpx.Response) -> LLMError:
        try:
            detail = (response.json().get("error") or {}).get("message") or response.text
        except ValueError:
            detail = response.text
        message = self._clean(f"{response.status_code}: {detail}")
        if response.status_code in (401, 403):
            return LLMAuthenticationError(f"Anthropic authentication failed ({message}). Check ANTHROPIC_API_KEY.")
        if response.status_code in (429, 529):
            return LLMRateLimitError(f"Anthropic rate limit or overload ({message})")
        if response.status_code == 404:
            return LLMModelUnavailableError(f"Anthropic model '{self._model}' is unavailable ({message})")
        return LLMError(f"Anthropic API error ({message})")

    def _clean(self, text: str) -> str:
        return sanitize_sensitive_text(text, sensitive_values=[self._api_key] if self._api_key else None)


def _messages(prompt: str | list[Any]) -> list[dict[str, Any]]:
    if isinstance(prompt, str):
        return [{"role": "user", "content": prompt}]
    messages: list[dict[str, Any]] = []
    for item in prompt:
        if isinstance(item, dict) and item.get("role") in ("user", "assistant"):
            messages.append({"role": item["role"], "content": item.get("content") or ""})
        elif isinstance(item, dict):
            continue  # system/tool messages have no place in this simple call
        else:
            messages.append({"role": "user", "content": str(item)})
    return messages or [{"role": "user", "content": ""}]
