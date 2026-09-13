"""OpenRouter language model provider implementation using OpenAI-compatible SDK."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Optional

from contexer.config.settings import DEFAULT_OPENROUTER_MODEL
from contexer.llm.base import (
    LLMAuthenticationError,
    LLMChunk,
    LLMError,
    LLMModelUnavailableError,
    LLMNetworkError,
    LLMProvider,
    LLMRateLimitError,
    LLMResponse,
    ToolCallRequest,
    sanitize_sensitive_text,
)

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider(LLMProvider):
    """OpenRouter provider utilizing an OpenAI-compatible API interface."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        site_url: Optional[str] = None,
        app_name: Optional[str] = None,
    ) -> None:
        self._api_key = api_key
        self._model = model or DEFAULT_OPENROUTER_MODEL
        self._site_url = site_url
        self._app_name = app_name or "Contexer"
        self._client: Optional[Any] = None

    @property
    def name(self) -> str:
        return "openrouter"

    @property
    def model(self) -> str:
        return self._model

    def validate_configuration(self) -> tuple[bool, Optional[str]]:
        """Verify that the OpenRouter API key is configured."""
        if not self._api_key or not self._api_key.strip():
            return (
                False,
                "OpenRouter API key is missing. Please configure OPENROUTER_API_KEY in your "
                "environment or in a .env file:\n"
                "  OPENROUTER_API_KEY=your_key_here\n"
                "You can get an API key at https://openrouter.ai/keys",
            )
        return True, None

    def _get_client(self) -> Any:
        """Lazily initialize the AsyncOpenAI Client configured for OpenRouter."""
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
                base_url=OPENROUTER_BASE_URL,
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
                f"OpenRouter authentication failed: {clean_msg}. "
                "Please verify your OPENROUTER_API_KEY.",
                original_error=exc,
            )

        if isinstance(exc, openai.RateLimitError) or "429" in lowered or "rate limit" in lowered or "quota" in lowered or "credits" in lowered:
            return LLMRateLimitError(
                f"OpenRouter rate limit or credits exceeded: {clean_msg}",
                original_error=exc,
            )

        if isinstance(exc, openai.NotFoundError) or "404" in lowered or "model not found" in lowered or "no such model" in lowered:
            return LLMModelUnavailableError(
                f"OpenRouter model '{self._model}' is unavailable: {clean_msg}",
                original_error=exc,
            )

        if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)) or "connect" in lowered or "timeout" in lowered:
            return LLMNetworkError(
                f"Network error communicating with OpenRouter API: {clean_msg}",
                original_error=exc,
            )

        return LLMError(f"OpenRouter API error: {clean_msg}", original_error=exc)

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

    # -- Conversation Message Building Helpers ----------------------------

    def build_user_message(self, text: str) -> dict[str, Any]:
        """Create a user message turn."""
        return {"role": "user", "content": text}

    def build_assistant_tool_calls_message(
        self, tool_calls: list[ToolCallRequest], content: Optional[str] = None
    ) -> dict[str, Any]:
        """Create an assistant message recording tool calls."""
        calls_data = []
        for i, call in enumerate(tool_calls):
            call_id = call.call_id or f"call_{call.name}_{i}"
            args_str = (
                json.dumps(call.arguments)
                if isinstance(call.arguments, dict)
                else str(call.arguments or "{}")
            )
            calls_data.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": args_str,
                    },
                }
            )

        msg: dict[str, Any] = {
            "role": "assistant",
            "content": content or None,
            "tool_calls": calls_data,
        }
        return msg

    def build_tool_messages(
        self, tool_results: list[tuple[str, str, Optional[str]]]
    ) -> list[dict[str, Any]]:
        """Create tool response messages returning outputs to the model."""
        messages = []
        for i, (name, output, call_id) in enumerate(tool_results):
            cid = call_id or f"call_{name}_{i}"
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": cid,
                    "name": name,
                    "content": output,
                }
            )
        return messages

    # -- Generation and Streaming -----------------------------------------

    async def generate(
        self,
        prompt: str | list[Any],
        system_instruction: Optional[str] = None,
        tools: Optional[list[Any]] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a full response from OpenRouter, supporting function calling."""
        client = self._get_client()
        messages = self._prepare_messages(prompt, system_instruction)

        api_kwargs: dict[str, Any] = dict(kwargs)
        if tools:
            api_kwargs["tools"] = tools

        try:
            response = await client.chat.completions.create(
                model=self._model,
                messages=messages,
                **api_kwargs,
            )

            choice = response.choices[0]
            message = choice.message
            text = message.content or ""

            tool_calls: list[ToolCallRequest] = []
            if getattr(message, "tool_calls", None):
                for tc in message.tool_calls or []:
                    fn = tc.function
                    args_dict: dict[str, Any] = {}
                    if fn.arguments:
                        try:
                            args_dict = json.loads(fn.arguments)
                        except Exception:
                            args_dict = {"raw": fn.arguments}
                    tool_calls.append(
                        ToolCallRequest(
                            call_id=tc.id,
                            name=fn.name,
                            arguments=args_dict,
                        )
                    )

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

            return LLMResponse(
                text=text,
                tool_calls=tool_calls,
                model=self._model,
                usage=usage_dict,
            )
        except Exception as exc:
            raise self._wrap_error(exc)

    async def stream(
        self,
        prompt: str | list[Any],
        system_instruction: Optional[str] = None,
        tools: Optional[list[Any]] = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMChunk]:
        """Stream response chunks from OpenRouter, yielding tool calls or text tokens."""
        client = self._get_client()
        messages = self._prepare_messages(prompt, system_instruction)

        api_kwargs: dict[str, Any] = dict(kwargs)
        if tools:
            api_kwargs["tools"] = tools

        try:
            stream_response = await client.chat.completions.create(
                model=self._model,
                messages=messages,
                stream=True,
                **api_kwargs,
            )

            # Dictionary to accumulate streaming tool calls across deltas
            # Map index -> {"id": str, "name": str, "arguments": str}
            accumulated_tool_calls: dict[int, dict[str, Any]] = {}

            try:
                async for chunk in stream_response:
                    if not getattr(chunk, "choices", None):
                        continue

                    choice = chunk.choices[0]
                    delta = choice.delta
                    finish_reason = getattr(choice, "finish_reason", None)

                    # Accumulate tool call deltas
                    if getattr(delta, "tool_calls", None):
                        for tc_chunk in delta.tool_calls or []:
                            idx = getattr(tc_chunk, "index", 0)
                            if idx not in accumulated_tool_calls:
                                accumulated_tool_calls[idx] = {
                                    "id": getattr(tc_chunk, "id", "") or "",
                                    "name": "",
                                    "arguments": "",
                                }
                            if getattr(tc_chunk, "id", None):
                                accumulated_tool_calls[idx]["id"] = tc_chunk.id

                            fn = getattr(tc_chunk, "function", None)
                            if fn:
                                if getattr(fn, "name", None):
                                    accumulated_tool_calls[idx]["name"] += fn.name
                                if getattr(fn, "arguments", None):
                                    accumulated_tool_calls[idx]["arguments"] += fn.arguments

                    # Stream text content directly or yield finish chunk
                    text_content = getattr(delta, "content", None)
                    if text_content or finish_reason:
                        yield LLMChunk(text=text_content or "", finish_reason=finish_reason)
            finally:
                try:
                    await stream_response.close()
                except BaseException:
                    pass

            # Once the stream concludes, if tool calls were accumulated, yield them
            if accumulated_tool_calls:
                final_tool_calls: list[ToolCallRequest] = []
                for idx in sorted(accumulated_tool_calls.keys()):
                    call_info = accumulated_tool_calls[idx]
                    args_str = call_info["arguments"]
                    parsed_args: dict[str, Any] = {}
                    if args_str:
                        try:
                            parsed_args = json.loads(args_str)
                        except Exception:
                            parsed_args = {"raw": args_str}

                    final_tool_calls.append(
                        ToolCallRequest(
                            call_id=call_info["id"] or f"call_{call_info['name']}_{idx}",
                            name=call_info["name"],
                            arguments=parsed_args,
                        )
                    )

                yield LLMChunk(tool_calls=final_tool_calls)

        except Exception as exc:
            raise self._wrap_error(exc)
