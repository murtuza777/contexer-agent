"""Chat models that can call tools, for every provider in the catalog.

The agents (``crew/``) need tool calling, which the drafting providers in this
package do not have. This module builds a LangChain chat model from the same
catalog, keys and precedence rules as :mod:`contexer.llm.factory`:

* OpenAI-compatible providers (OpenRouter, OpenAI, Groq, a local Ollama, your
  own gateway...) all use one class, ``ChatOpenAI``, with the provider's base URL;
* Anthropic uses ``ChatAnthropic``.

LangChain is imported only when a model is built, so commands that never run
an agent do not pay for it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING, Any

from contexer.config.settings import DEFAULT_OPENROUTER_MODEL, OPENROUTER_FREE_ROUTER, ContexerConfig, load_config
from contexer.llm import discovery
from contexer.llm.base import LLMAuthenticationError, LLMError, sanitize_sensitive_text
from contexer.llm.capabilities import ModelCapabilities, model_capabilities
from contexer.llm.catalog import ProviderSpec, is_azure, normalize_endpoint, provider_spec

if TYPE_CHECKING:
    import httpx
    from langchain_core.language_models.chat_models import BaseChatModel

# Seconds one model call may take before the client gives up.
DEFAULT_REQUEST_TIMEOUT = 120.0


class ToolCallingError(LLMError):
    """The chosen model cannot call tools, so it cannot drive an agent."""


@dataclass(frozen=True)
class ModelChoice:
    """A provider and model, resolved the way :func:`contexer.llm.factory.create_llm_provider` resolves them."""

    spec: ProviderSpec
    model: str
    api_key: str | None
    base_url: str

    @property
    def label(self) -> str:
        return f"{self.spec.id} model '{self.model}'"


def resolve_model(provider: str, model: str | None = None, config: ContexerConfig | None = None) -> ModelChoice:
    """Work out the model, key and endpoint for ``provider``.

    Model precedence: ``model``, then ``CONTEXER_LLM_MODEL`` when ``provider``
    is the one named by ``CONTEXER_LLM_PROVIDER`` (a provider never inherits
    another's model or base URL), then the provider's own variable, then the
    catalog default.
    """
    config = config or load_config()
    spec = provider_spec(provider)  # ValueError for an unknown provider
    paired = spec.id == (config.compiler_provider or "").lower()
    chosen = model or (config.llm_model if paired else None)
    base_override = config.llm_base_url if paired else None
    if spec.id == "openrouter":
        api_key, chosen, base_url = config.openrouter_api_key, chosen or config.openrouter_model, spec.base_url
    elif spec.id == "openai":
        api_key = config.openai_api_key
        chosen = chosen or config.openai_model or spec.default_model
        base_url = base_override or config.openai_base_url or spec.base_url
    elif spec.id == "anthropic":
        api_key, chosen, base_url = config.anthropic_api_key, chosen or config.anthropic_model or spec.default_model, spec.base_url
    else:
        api_key = spec.key() or ("local" if spec.local else None)
        chosen = chosen or spec.default_model
        base_url = normalize_endpoint(base_override) if base_override else spec.endpoint()
        if not base_url:
            where = f"{spec.base_url_env} or CONTEXER_LLM_BASE_URL" if spec.base_url_env else "CONTEXER_LLM_BASE_URL"
            raise ValueError(f"The '{spec.id}' provider needs a base URL: set {where} or run `contexer setup`.")
    if not chosen:
        raise LLMError(f"No model chosen for {spec.label}: pass one, or run `contexer setup`.")
    if not api_key or not api_key.strip():
        where = f" You can get one at {spec.keys_url}." if spec.keys_url else ""
        raise LLMAuthenticationError(f"{spec.label} API key is missing: set {spec.key_env}.{where}")
    return ModelChoice(spec=spec, model=chosen, api_key=api_key.strip(), base_url=base_url)


def chat_model(
    provider: str,
    model: str | None = None,
    *,
    config: ContexerConfig | None = None,
    max_tokens: int | None = None,
    timeout: float = DEFAULT_REQUEST_TIMEOUT,
    http_async_client: httpx.AsyncClient | None = None,
) -> BaseChatModel:
    """A tool-calling chat model for ``provider``. Building it makes no network call.

    ``http_async_client`` replaces the HTTP client of an OpenAI-compatible
    model; tests use it to replay recorded replies.
    """
    config = config or load_config()
    choice = resolve_model(provider, model, config)
    return chat_model_from(choice, config=config, max_tokens=max_tokens, timeout=timeout, http_async_client=http_async_client)


def chat_model_from(
    choice: ModelChoice,
    *,
    config: ContexerConfig | None = None,
    max_tokens: int | None = None,
    timeout: float = DEFAULT_REQUEST_TIMEOUT,
    http_async_client: httpx.AsyncClient | None = None,
) -> BaseChatModel:
    """A chat model for exactly this provider, model, key and endpoint (``contexer setup`` has them before they are saved)."""
    config = config or load_config()
    if choice.spec.protocol == "anthropic":
        # `model` and `max_tokens` are the documented names; the class declares them as aliases.
        return _anthropic_class()(
            model=choice.model,  # pyright: ignore[reportCallIssue]
            api_key=choice.api_key,  # type: ignore[arg-type]
            max_tokens=max_tokens or 8192,  # pyright: ignore[reportCallIssue]
            timeout=timeout,
            max_retries=2,
        )

    extras: dict[str, Any] = {}
    if choice.spec.id == "openrouter":
        headers = {"X-Title": config.openrouter_app_name or "Contexer"}
        if config.openrouter_site_url:
            headers["HTTP-Referer"] = config.openrouter_site_url
        extras["default_headers"] = headers
        if choice.model == DEFAULT_OPENROUTER_MODEL:
            # Same fallback as the drafting client: free models come and go.
            extras["extra_body"] = {"models": [choice.model, OPENROUTER_FREE_ROUTER]}
        # One id for every call this model object makes (an agent's run): OpenRouter keeps the calls of a
        # session on the provider that holds their cached prompt.
        extras["extra_body"] = {**extras.get("extra_body", {}), "session_id": uuid.uuid4().hex}
    if http_async_client is not None:
        extras["http_async_client"] = http_async_client
    if max_tokens:
        extras["max_tokens"] = max_tokens
    # OpenAI renamed max_tokens to max_completion_tokens, and Azure's models refuse the old name;
    # the other providers still take max_tokens.
    cls = _openai_class(native=choice.spec.id in ("openai", "azure") or is_azure(choice.base_url))
    return cls(
        model=choice.model,
        api_key=choice.api_key,  # type: ignore[arg-type]
        base_url=choice.base_url,
        timeout=timeout,
        max_retries=2,
        # Every catalog provider speaks Chat Completions; only OpenAI itself has the Responses API.
        use_responses_api=False,
        **extras,
    )


# Anthropic caches a request up to a marker, and only where one is set.
_CACHE_MARKER = {"type": "ephemeral"}


@cache
def _anthropic_class() -> Any:
    from langchain_anthropic import ChatAnthropic

    class CachingChatAnthropic(ChatAnthropic):
        """ChatAnthropic that asks for the tools and the system prompt to be cached.

        An agent sends the same tools and system prompt with every call of its run. Marked, the
        second call on reads them from the cache at the cached price. The conversation after them
        is not marked.
        """

        def _get_request_payload(self, input_: Any, *, stop: list[str] | None = None, **kwargs: Any) -> dict:
            payload = super()._get_request_payload(input_, stop=stop, **kwargs)
            tools = payload.get("tools")
            if isinstance(tools, list) and tools and isinstance(tools[-1], dict):
                payload["tools"] = [*tools[:-1], {**tools[-1], "cache_control": _CACHE_MARKER}]
            system = payload.get("system")
            if isinstance(system, str) and system:
                payload["system"] = [{"type": "text", "text": system, "cache_control": _CACHE_MARKER}]
            elif isinstance(system, list) and system and isinstance(system[-1], dict):
                payload["system"] = [*system[:-1], {**system[-1], "cache_control": _CACHE_MARKER}]
            return payload

    return CachingChatAnthropic


@cache
def _openai_class(native: bool) -> Any:
    from langchain_openai import ChatOpenAI

    if native:
        return ChatOpenAI

    class CompatibleChatOpenAI(ChatOpenAI):
        """ChatOpenAI for another provider's OpenAI-compatible endpoint."""

        def _get_request_payload(self, input_: Any, *, stop: list[str] | None = None, **kwargs: Any) -> dict:
            payload = super()._get_request_payload(input_, stop=stop, **kwargs)
            if "max_completion_tokens" in payload:
                payload["max_tokens"] = payload.pop("max_completion_tokens")
            return payload

    return CompatibleChatOpenAI


def supports_tools(
    provider: str,
    model: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> bool | None:
    """Whether ``model`` can call tools: True, False, or None when the provider does not say.

    A metadata lookup, never a model request. OpenRouter lists each model's
    supported parameters; every Claude model on Anthropic's API accepts tools;
    a model Contexer has run its agents on, or that ``contexer setup`` measured
    with one tool call, is known too. Otherwise the answer is None and the
    first agent run finds out (see :func:`tool_calling_error`).
    """
    known = model_capabilities(provider, model, api_key=api_key, base_url=base_url, transport=transport).native_tools
    return None if known.source == "assumed" else known.value


def require_tools(provider: str, model: str, **probe: Any) -> ModelCapabilities:
    """The model's capability record. Raises :class:`ToolCallingError` when it is known that ``model`` cannot call tools."""
    record = model_capabilities(provider, model, **probe)
    if record.native_tools.source != "assumed" and not record.native_tools.value:
        label = f"{record.provider} model '{model}'"
        raise ToolCallingError(f"{_cannot_call_tools(label)} ({record.native_tools.origin()})")
    return record


_NO_TOOLS_PHRASES = (
    "support tool use",  # OpenRouter: "No endpoints found that support tool use"
    "does not support tools",  # Ollama
    "does not support function calling",
    "tool calling is not supported",
    "tools is not supported",
    "tool use is not supported",
    "`tools` is not supported",
    "tool_choice is not supported",
)


def tool_calling_error(exc: BaseException, model: Any) -> ToolCallingError | None:
    """A :class:`ToolCallingError` naming the model, if ``exc`` is a provider refusing tools; else None."""
    text = str(exc).lower()
    if any(phrase in text for phrase in _NO_TOOLS_PHRASES):
        return ToolCallingError(_cannot_call_tools(describe_model(model)), original_error=exc if isinstance(exc, Exception) else None)
    return None


def describe_model(model: Any) -> str:
    """``model 'id'`` for a chat model (or a runnable wrapping one), for error messages."""
    inner = getattr(model, "bound", model)
    name = getattr(inner, "model_name", None) or getattr(inner, "model", None)
    return f"model '{name}'" if isinstance(name, str) and name else f"model {type(inner).__name__}"


def uses_free_requests(model: Any) -> bool:
    """Whether calls to this chat model count against OpenRouter's daily free-request limit."""
    inner = getattr(model, "bound", model)
    name = getattr(inner, "model_name", None)
    base = str(getattr(inner, "openai_api_base", "") or "")
    return isinstance(name, str) and "openrouter.ai" in base and discovery.is_free_model(name)


def clean_error(exc: BaseException) -> str:
    """One line of ``exc`` with anything that looks like an API key masked."""
    lines = str(exc).strip().splitlines()
    return sanitize_sensitive_text(lines[0] if lines else type(exc).__name__)[:500]


async def check_tool_calling(model: BaseChatModel) -> str:
    """One real tool call and its result, end to end: returns the model's final text.

    Raises :class:`ToolCallingError` naming the model when it answers without
    calling the tool or the provider refuses tools.
    """
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langchain_core.tools import tool

    @tool
    def add_numbers(a: int, b: int) -> int:
        """Add two whole numbers and return the sum."""
        return a + b

    messages: list[Any] = [
        HumanMessage("Use the add_numbers tool to add 19 and 23, then tell me the sum in one short sentence.")
    ]
    bound = model.bind_tools([add_numbers])
    try:
        reply = await bound.ainvoke(messages)
    except Exception as exc:
        raise (tool_calling_error(exc, model) or exc) from exc
    calls = reply.tool_calls if isinstance(reply, AIMessage) else []
    if not calls:
        raise ToolCallingError(_cannot_call_tools(describe_model(model)) + " It answered without calling the tool.")
    messages.append(reply)
    for call in calls:
        result = await add_numbers.ainvoke(call["args"])
        messages.append(ToolMessage(content=str(result), tool_call_id=call["id"] or ""))
    final = await bound.ainvoke(messages)
    return str(final.text)


def _cannot_call_tools(label: str) -> str:
    return (
        f"The {label} cannot call tools, which Contexer's agents need. "
        "Choose a model that supports tool calling (`contexer models` marks them)."
    )
