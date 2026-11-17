"""Chat models with tool calling: built for every catalog provider, with no network and no model."""

from __future__ import annotations

import json
import os
import socket
from typing import Any

import httpx
import pytest
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

from contexer.cli.doctor_cli import _tool_calling_finding
from contexer.config.settings import DEFAULT_OPENROUTER_MODEL, ContexerConfig
from contexer.llm.base import LLMAuthenticationError, LLMError
from contexer.llm.catalog import PROVIDERS, provider_spec
from contexer.llm.chat import (
    ToolCallingError,
    chat_model,
    check_tool_calling,
    require_tools,
    supports_tools,
    resolve_model,
    tool_calling_error,
)
from contexer.llm.factory import create_llm_provider
from tests.fakes import ScriptedChatModel, calls, says

pytestmark = pytest.mark.anyio


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_a: Any, **_k: Any) -> None:
        raise AssertionError("a network connection was attempted")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


AZURE_ENDPOINT = "https://my-resource.services.ai.azure.com/openai/v1"


def _config(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> ContexerConfig:
    """Every provider has a key, and Azure has its endpoint."""
    for spec in PROVIDERS:
        monkeypatch.setenv(spec.key_env, f"key-for-{spec.id}")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", AZURE_ENDPOINT)
    return ContexerConfig(
        openrouter_api_key="key-for-openrouter",
        anthropic_api_key="key-for-anthropic",
        openai_api_key="key-for-openai",
        **overrides,
    )


def _custom(provider: str) -> dict[str, Any]:
    """The custom provider has no endpoint of its own: the user names one."""
    if provider != "custom":
        return {}
    return {"compiler_provider": "custom", "llm_base_url": "https://gateway.example/v1"}


@pytest.mark.parametrize("provider", [spec.id for spec in PROVIDERS])
def test_a_model_is_built_for_every_catalog_provider_without_a_network_call(
    provider: str, monkeypatch: pytest.MonkeyPatch, no_network: None
) -> None:
    model = chat_model(provider, "some-model", config=_config(monkeypatch, **_custom(provider)))

    spec = provider_spec(provider)
    if spec.protocol == "anthropic":
        assert isinstance(model, ChatAnthropic)
        assert model.model == "some-model"
        assert model.anthropic_api_key.get_secret_value() == "key-for-anthropic"
    else:
        assert isinstance(model, ChatOpenAI)
        assert model.model_name == "some-model"
        expected = {"custom": "https://gateway.example/v1", "azure": AZURE_ENDPOINT}
        assert model.openai_api_base == (spec.base_url or expected[provider])
        assert model.openai_api_key.get_secret_value() == f"key-for-{provider}"  # type: ignore[union-attr]
    # Tools can be bound to it, which is all an agent needs.
    assert model.bind_tools([_add_numbers_schema()]) is not None


@pytest.mark.parametrize("provider", [spec.id for spec in PROVIDERS])
def test_the_model_and_endpoint_match_what_the_drafting_factory_picks(
    provider: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same keys and precedence rules as llm/factory.py, for an explicit model and for the default."""
    config = _config(monkeypatch, openai_model="gpt-from-env", anthropic_model="claude-from-env", **_custom(provider))
    for explicit in ("explicit-model", None):
        drafting = create_llm_provider(config, provider, explicit)
        if not drafting.model:  # no default model for this provider: the chat model refuses instead of guessing
            with pytest.raises(LLMError, match="No model chosen"):
                resolve_model(provider, explicit, config)
            continue
        choice = resolve_model(provider, explicit, config)
        assert choice.model == drafting.model
        if provider != "anthropic":
            assert choice.base_url == drafting._base_url  # type: ignore[attr-defined]


def test_contexer_llm_model_belongs_only_to_the_provider_chosen_with_it(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(
        monkeypatch, compiler_provider="groq", llm_model="llama-for-groq", llm_base_url="https://groq.proxy/v1"
    )
    assert resolve_model("groq", None, config).model == "llama-for-groq"
    assert resolve_model("groq", None, config).base_url == "https://groq.proxy/v1"
    other = resolve_model("openrouter", None, config)
    assert (other.model, other.base_url) == (DEFAULT_OPENROUTER_MODEL, "https://openrouter.ai/api/v1")


def test_a_missing_key_names_the_variable_to_set() -> None:
    os.environ.pop("GROQ_API_KEY", None)
    with pytest.raises(LLMAuthenticationError, match="GROQ_API_KEY"):
        chat_model("groq", "llama", config=ContexerConfig())
    with pytest.raises(LLMAuthenticationError, match="ANTHROPIC_API_KEY"):
        chat_model("anthropic", config=ContexerConfig())


def test_a_local_ollama_needs_no_key_and_an_unknown_provider_is_refused() -> None:
    os.environ.pop("OLLAMA_API_KEY", None)
    assert isinstance(chat_model("ollama", "llama3.3", config=ContexerConfig()), ChatOpenAI)
    with pytest.raises(ValueError, match="Unknown provider"):
        chat_model("nope", "x", config=ContexerConfig())


# -- the wire: recorded replies through the real client -----------------------

_TOOL_CALL_REPLY = {
    "id": "gen-1",
    "object": "chat.completion",
    "created": 1,
    "model": "vendor/model-served",
    "choices": [
        {
            "index": 0,
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "add_numbers", "arguments": '{"a": 19, "b": 23}'},
                    }
                ],
            },
        }
    ],
    "usage": {"prompt_tokens": 50, "completion_tokens": 12, "total_tokens": 62, "cost": 0.00042},
}
_FINAL_REPLY = {
    "id": "gen-2",
    "object": "chat.completion",
    "created": 2,
    "model": "vendor/model-served",
    "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "The sum is 42."}}],
    "usage": {"prompt_tokens": 70, "completion_tokens": 6, "total_tokens": 76, "cost": 0.0001},
}


def recorded(*replies: httpx.Response) -> tuple[httpx.AsyncClient, list[httpx.Request]]:
    """An HTTP client that answers with ``replies`` in order, and the requests it received."""
    queue, requests = list(replies), []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return queue.pop(0)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), requests


async def test_one_tool_call_and_its_result_over_an_openai_compatible_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, requests = recorded(httpx.Response(200, json=_TOOL_CALL_REPLY), httpx.Response(200, json=_FINAL_REPLY))
    config = _config(monkeypatch, openrouter_site_url="https://example.test")
    model = chat_model("openrouter", "vendor/model", config=config, max_tokens=900, http_async_client=client)

    assert await check_tool_calling(model) == "The sum is 42."

    first, second = (json.loads(r.content) for r in requests)
    assert str(requests[0].url) == "https://openrouter.ai/api/v1/chat/completions"
    assert requests[0].headers["authorization"] == "Bearer key-for-openrouter"
    assert requests[0].headers["x-title"] == "Contexer"
    assert requests[0].headers["http-referer"] == "https://example.test"
    assert first["model"] == "vendor/model"
    assert [t["function"]["name"] for t in first["tools"]] == ["add_numbers"]
    # Other providers still take max_tokens; only OpenAI itself renamed it.
    assert first["max_tokens"] == 900 and "max_completion_tokens" not in first
    assert "models" not in first  # a model the user picked gets no fallback list
    assert [m["role"] for m in second["messages"]] == ["user", "assistant", "tool"]
    assert second["messages"][2]["content"] == "42"


async def test_the_default_openrouter_model_keeps_its_free_fallback_and_openai_uses_its_own_limit_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(monkeypatch)
    client, requests = recorded(httpx.Response(200, json=_FINAL_REPLY))
    await chat_model("openrouter", config=config, http_async_client=client).ainvoke("hello")
    assert json.loads(requests[0].content)["models"] == [DEFAULT_OPENROUTER_MODEL, "openrouter/free"]

    client, requests = recorded(httpx.Response(200, json=_FINAL_REPLY))
    await chat_model("openai", "gpt-5", config=config, max_tokens=300, http_async_client=client).ainvoke("hello")
    body = json.loads(requests[0].content)
    assert str(requests[0].url) == "https://api.openai.com/v1/chat/completions"
    assert body["max_completion_tokens"] == 300 and "max_tokens" not in body


# -- Azure AI Foundry ------------------------------------------------------------


@pytest.mark.parametrize(
    "pasted",
    [
        "https://my-resource.services.ai.azure.com/openai/v1",
        "https://my-resource.services.ai.azure.com/openai/v1/",
        "https://my-resource.services.ai.azure.com/openai/v1/responses",  # the URL the portal shows for one API
        "https://my-resource.services.ai.azure.com/openai/v1/chat/completions",
        "https://my-resource.services.ai.azure.com",
        "https://my-resource.services.ai.azure.com/",
    ],
)
def test_an_azure_endpoint_is_accepted_however_it_was_pasted(pasted: str, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(monkeypatch)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", pasted)
    choice = resolve_model("azure", "gpt-deployment", config)
    assert choice.base_url == AZURE_ENDPOINT
    assert (choice.model, choice.api_key) == ("gpt-deployment", "key-for-azure")


async def test_azure_is_sent_max_completion_tokens_on_chat_completions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Azure's current models refuse max_tokens (seen live on 2026-11-17)."""
    client, requests = recorded(httpx.Response(200, json=_TOOL_CALL_REPLY), httpx.Response(200, json=_FINAL_REPLY))
    model = chat_model("azure", "gpt-deployment", config=_config(monkeypatch), max_tokens=900, http_async_client=client)

    assert await check_tool_calling(model) == "The sum is 42."

    body = json.loads(requests[0].content)
    assert str(requests[0].url) == f"{AZURE_ENDPOINT}/chat/completions"
    assert requests[0].headers["authorization"] == "Bearer key-for-azure"
    assert body["model"] == "gpt-deployment"
    assert body["max_completion_tokens"] == 900 and "max_tokens" not in body


async def test_an_azure_endpoint_given_to_the_custom_provider_is_treated_as_azure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(
        monkeypatch,
        compiler_provider="custom",
        llm_model="gpt-deployment",
        llm_base_url="https://my-resource.services.ai.azure.com/openai/v1/responses",
    )
    client, requests = recorded(httpx.Response(200, json=_FINAL_REPLY))
    await chat_model("custom", config=config, max_tokens=300, http_async_client=client).ainvoke("hello")

    body = json.loads(requests[0].content)
    assert str(requests[0].url) == f"{AZURE_ENDPOINT}/chat/completions"
    assert body["max_completion_tokens"] == 300 and "max_tokens" not in body


def test_azure_without_an_endpoint_names_the_variable_to_set(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(monkeypatch)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT")
    with pytest.raises(ValueError, match="AZURE_OPENAI_ENDPOINT"):
        chat_model("azure", "gpt-deployment", config=config)


def test_the_drafting_client_gets_the_same_azure_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(monkeypatch)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://my-resource.services.ai.azure.com/openai/v1/responses")
    drafting = create_llm_provider(config, "azure", "gpt-deployment")
    assert drafting._base_url == AZURE_ENDPOINT  # type: ignore[attr-defined]
    assert drafting.validate_configuration() == (True, None)


# -- models that cannot call tools --------------------------------------------


async def test_a_provider_that_refuses_tools_gives_an_error_naming_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    refusal = {"error": {"message": "No endpoints found that support tool use. To learn more, see the docs", "code": 404}}
    client, _ = recorded(httpx.Response(404, json=refusal))
    model = chat_model("openrouter", "vendor/no-tools", config=_config(monkeypatch), http_async_client=client)

    with pytest.raises(ToolCallingError) as caught:
        await check_tool_calling(model)
    assert "model 'vendor/no-tools' cannot call tools" in str(caught.value)
    assert "contexer models" in str(caught.value)


async def test_a_model_that_answers_without_calling_the_tool_gives_the_same_error() -> None:
    with pytest.raises(ToolCallingError, match="model 'scripted-model' cannot call tools"):
        await check_tool_calling(ScriptedChatModel(says("19 plus 23 is 42.")))


async def test_the_check_passes_on_a_model_that_calls_the_tool() -> None:
    model = ScriptedChatModel(calls(("add_numbers", {"a": 19, "b": 23})), says("42"))
    assert await check_tool_calling(model) == "42"
    assert model.seen[1][-1].content == "42"  # the tool's result went back to the model


def test_other_errors_are_not_mistaken_for_a_tool_refusal() -> None:
    model = ScriptedChatModel()
    assert tool_calling_error(RuntimeError("Error code: 429 - rate limit exceeded"), model) is None
    assert tool_calling_error(RuntimeError("registry.ollama.ai/library/x does not support tools"), model) is not None


def _models_endpoint(rows: list[dict[str, Any]], status: int = 200) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(status, json={"data": rows}))


def test_the_probe_reads_tool_support_from_the_providers_model_list() -> None:
    transport = _models_endpoint(
        [
            {"id": "vendor/with-tools", "supported_parameters": ["tools", "temperature"]},
            {"id": "vendor/without", "supported_parameters": ["temperature"]},
            {"id": "vendor/silent"},
        ]
    )
    assert supports_tools("openrouter", "vendor/with-tools", transport=transport) is True
    assert supports_tools("openrouter", "vendor/without", transport=transport) is False
    assert supports_tools("openrouter", "vendor/silent", transport=transport) is None
    assert supports_tools("openrouter", "vendor/unlisted", transport=transport) is None


def test_the_probe_knows_claude_and_says_unknown_when_a_provider_cannot_be_asked(no_network: None) -> None:
    assert supports_tools("anthropic", "claude-opus-5-5") is True
    assert supports_tools("groq", "llama", transport=_models_endpoint([], status=500)) is None


def test_require_tools_stops_a_model_the_provider_says_cannot_call_tools() -> None:
    transport = _models_endpoint([{"id": "vendor/without", "supported_parameters": ["temperature"]}])
    with pytest.raises(ToolCallingError, match="openrouter model 'vendor/without' cannot call tools"):
        require_tools("openrouter", "vendor/without", transport=transport)
    require_tools("openrouter", "vendor/unknown", transport=transport)  # unknown is not a refusal


def test_doctor_reports_tool_calling_for_the_model_in_use(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = {"good": True, "bad": False, "quiet": None}
    monkeypatch.setattr("contexer.cli.doctor_cli.supports_tools", lambda _provider, model: answers[model])
    assert _tool_calling_finding("openrouter", "good").status == "ok"
    bad = _tool_calling_finding("openrouter", "bad")
    assert (bad.status, "bad cannot call tools" in bad.detail, "contexer models" in bad.fix) == ("warn", True, True)
    assert _tool_calling_finding("openrouter", "quiet").status == "ok"


# -- live: one real tool call per provider, only when asked for ----------------

_LIVE = [
    ("anthropic", "ANTHROPIC_API_KEY"),
    ("openai", "OPENAI_API_KEY"),
    ("openrouter", "OPENROUTER_API_KEY"),
    ("azure", "AZURE_OPENAI_API_KEY"),
]


@pytest.mark.parametrize("provider,key_env", _LIVE)
async def test_live_one_tool_call_and_its_result(provider: str, key_env: str) -> None:
    """``CONTEXER_LIVE_TESTS=1 pytest tests/test_llm_chat.py -k live`` with the provider's key exported.

    The model is the provider's default, or ``CONTEXER_LIVE_MODEL_<PROVIDER>``.
    """
    if os.environ.get("CONTEXER_LIVE_TESTS") != "1" or not os.environ.get(key_env):
        pytest.skip(f"live check: set CONTEXER_LIVE_TESTS=1 and {key_env}")
    from contexer.config.settings import load_config

    chosen = os.environ.get(f"CONTEXER_LIVE_MODEL_{provider.upper()}")
    model = chat_model(provider, chosen, config=load_config(), max_tokens=2000)
    assert "42" in await check_tool_calling(model)


def _add_numbers_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "add_numbers",
            "description": "Add two whole numbers.",
            "parameters": {
                "type": "object",
                "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                "required": ["a", "b"],
            },
        },
    }
