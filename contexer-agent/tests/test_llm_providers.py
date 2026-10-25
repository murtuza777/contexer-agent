"""Provider choice for compiling goals, and the Anthropic Messages API client."""

import json
from pathlib import Path

import httpx
import pytest

from contexer.config.project import CompilerSettings, load_project_config
from contexer.config.settings import ContexerConfig
from contexer.llm.anthropic import AnthropicProvider
from contexer.llm.base import LLMAuthenticationError, LLMModelUnavailableError, LLMRateLimitError
from contexer.llm.factory import compiler_provider, create_llm_provider


def _config(**keys: str) -> ContexerConfig:
    return ContexerConfig(**keys)  # type: ignore[arg-type]


def test_no_key_means_no_compiler() -> None:
    assert compiler_provider(_config()) is None


def test_auto_prefers_anthropic_then_openai_then_openrouter() -> None:
    assert compiler_provider(_config(openrouter_api_key="r")).name == "openrouter"  # type: ignore[union-attr]
    assert compiler_provider(_config(openrouter_api_key="r", openai_api_key="o")).name == "openai"  # type: ignore[union-attr]
    both = compiler_provider(_config(openrouter_api_key="r", openai_api_key="o", anthropic_api_key="a"))
    assert both is not None and both.name == "anthropic" and both.model == "claude-opus-5-5"


def test_explicit_choice_wins_and_model_override_applies() -> None:
    config = _config(openrouter_api_key="r", anthropic_api_key="a", compiler_provider="openrouter")
    assert compiler_provider(config).name == "openrouter"  # type: ignore[union-attr]
    project = CompilerSettings(provider="anthropic", model="claude-sonnet-5-5")
    chosen = compiler_provider(config, project)
    assert chosen is not None and (chosen.name, chosen.model) == ("anthropic", "claude-sonnet-5-5")


def test_explicit_provider_without_its_key_is_none_not_a_silent_switch() -> None:
    config = _config(openrouter_api_key="r")
    assert compiler_provider(config, CompilerSettings(provider="anthropic")) is None


def test_openai_provider_uses_base_url_and_names_its_key() -> None:
    provider = create_llm_provider(_config(openai_base_url="http://localhost:1234/v1"), "openai")
    ok, message = provider.validate_configuration()
    assert not ok and message and "OPENAI_API_KEY" in message


def test_compiler_section_is_read_from_contexer_toml(tmp_path: Path) -> None:
    (tmp_path / "contexer.toml").write_text('[compiler]\nprovider = "openai"\nmodel = "gpt-5"\n', encoding="utf-8")
    settings = load_project_config(tmp_path).compiler
    assert (settings.provider, settings.model) == ("openai", "gpt-5")


def _anthropic(handler) -> AnthropicProvider:  # type: ignore[no-untyped-def]
    return AnthropicProvider(api_key="sk-ant-test-0123456789abcdefghij", transport=httpx.MockTransport(handler))


@pytest.mark.anyio
async def test_anthropic_request_shape_and_reply() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "model": "claude-opus-5-5",
                "content": [{"type": "text", "text": '{"acceptance_criteria": []}'}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        )

    reply = await _anthropic(handler).generate(
        "Compile this goal", system_instruction="Return JSON", response_format={"type": "json_object"}
    )
    assert reply.text == '{"acceptance_criteria": []}'
    assert reply.usage["total_tokens"] == 15
    [request] = seen
    body = json.loads(request.content)
    assert request.headers["anthropic-version"] == "2023-06-01"
    assert request.headers["x-api-key"].startswith("sk-ant-")
    assert body["system"] == "Return JSON"
    assert body["messages"] == [{"role": "user", "content": "Compile this goal"}]
    assert "response_format" not in body  # OpenAI-only option is not forwarded


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "error"),
    [(401, LLMAuthenticationError), (429, LLMRateLimitError), (529, LLMRateLimitError), (404, LLMModelUnavailableError)],
)
async def test_anthropic_errors_map_and_never_echo_the_key(status: int, error: type) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": f"bad key sk-ant-test-0123456789abcdefghij"}})

    with pytest.raises(error) as info:
        await _anthropic(handler).generate("x")
    assert "0123456789abcdefghij" not in str(info.value)
