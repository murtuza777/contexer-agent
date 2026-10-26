"""Bring your own key: the provider catalogue, saved settings, discovery, and `contexer setup`."""

import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from contexer.cli import app
from contexer.config.settings import load_config
from contexer.config.user import (
    UserSettings,
    apply_user_settings,
    contexer_home,
    load_credentials,
    load_user_settings,
    save_credential,
    save_user_settings,
)
from contexer.llm.catalog import PROVIDERS, provider_spec
from contexer.llm.discovery import DiscoveryError, ModelInfo, check_key, list_models
from contexer.llm.factory import compiler_provider, create_llm_provider


def test_every_provider_has_a_key_variable_and_an_endpoint_or_asks_for_one() -> None:
    ids = [p.id for p in PROVIDERS]
    assert len(ids) == len(set(ids))
    for spec in PROVIDERS:
        assert spec.key_env.endswith("_API_KEY")
        assert spec.base_url.startswith("http") or spec.id == "custom"
    assert provider_spec("Groq").id == "groq"
    with pytest.raises(ValueError, match="openrouter"):
        provider_spec("nope")


def test_settings_round_trip_and_never_override_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    save_user_settings(UserSettings(provider="groq", model="llama-x", agent="opencode", agent_model="groq/llama-x"))
    save_credential("GROQ_API_KEY", "gsk_saved_key_123456")
    assert load_user_settings().agent_model == "groq/llama-x"
    assert load_credentials() == {"GROQ_API_KEY": "gsk_saved_key_123456"}
    if sys.platform != "win32":
        assert (contexer_home() / "credentials.toml").stat().st_mode & 0o077 == 0

    for name in ("GROQ_API_KEY", "CONTEXER_LLM_PROVIDER", "CONTEXER_LLM_MODEL", "CONTEXER_AGENT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CONTEXER_AGENT", "claude-code")  # exported by the user: wins
    apply_user_settings()
    assert os.environ["GROQ_API_KEY"] == "gsk_saved_key_123456"
    assert os.environ["CONTEXER_LLM_PROVIDER"] == "groq"
    assert os.environ["CONTEXER_AGENT"] == "claude-code"


def test_any_catalogue_provider_drafts_with_its_endpoint_and_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("CONTEXER_LLM_PROVIDER", "groq")
    monkeypatch.setenv("CONTEXER_LLM_MODEL", "llama-x")
    llm = compiler_provider(load_config())
    assert llm is not None and llm.name == "groq" and llm.model == "llama-x"
    assert llm._base_url == "https://api.groq.com/openai/v1"  # type: ignore[attr-defined]

    # A project that picks another provider must not inherit groq's model id.
    from contexer.config.project import CompilerSettings

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    anthropic = compiler_provider(load_config(), CompilerSettings(provider="anthropic"))
    assert anthropic is not None and anthropic.model == "claude-opus-5-5"


def test_a_local_server_needs_no_key_and_custom_needs_a_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONTEXER_LLM_BASE_URL", raising=False)
    local = create_llm_provider(load_config(), "ollama", "qwen3-coder")
    assert local.validate_configuration()[0]
    with pytest.raises(ValueError, match="base URL"):
        create_llm_provider(load_config(), "custom", "my-model")


def _transport(routes: dict[str, tuple[int, Any]], seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        status, body = routes[request.url.path]
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


def test_list_models_reads_free_tools_and_context_newest_first() -> None:
    rows = [
        {"id": "old/model", "created": 1, "context_length": 8000, "pricing": {"prompt": "0.000001", "completion": "0.000002"}},
        {"id": "new/model:free", "created": 9, "context_length": 262144, "pricing": {"prompt": "0", "completion": "0"},
         "supported_parameters": ["tools", "temperature"]},
    ]
    seen: list[httpx.Request] = []
    found = list_models(provider_spec("openrouter"), "sk-or-x", transport=_transport({"/api/v1/models": (200, {"data": rows})}, seen))
    assert found == [
        ModelInfo(id="new/model:free", context=262144, free=True, tools=True, created=9),
        ModelInfo(id="old/model", context=8000, free=False, tools=None, created=1),
    ]
    assert seen[0].headers["authorization"] == "Bearer sk-or-x"


def test_a_rejected_key_is_named_and_never_echoed() -> None:
    seen: list[httpx.Request] = []
    transport = _transport({"/v1/models": (401, {"error": "invalid x-api-key"})}, seen)
    with pytest.raises(DiscoveryError, match="rejected the key") as info:
        check_key(provider_spec("anthropic"), "sk-ant-secret-value", transport=transport)
    assert "sk-ant-secret-value" not in str(info.value)
    assert seen[0].headers["x-api-key"] == "sk-ant-secret-value"  # Anthropic's own header, not Bearer
    # OpenRouter's model list is public, so its key is checked against /key.
    ok = _transport({"/api/v1/key": (200, {"data": {"is_free_tier": True}})}, seen)
    check_key(provider_spec("openrouter"), "sk-or-good", transport=ok)
    assert seen[-1].url.path == "/api/v1/key"


@pytest.fixture
def offline_provider(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """`contexer setup` against a provider that exists only in this test."""
    from contexer.cli import setup_cli

    state: dict[str, Any] = {"answers": True, "tried": []}
    monkeypatch.setattr(setup_cli, "check_key", lambda spec, key, url: None)
    monkeypatch.setattr(
        setup_cli, "list_models",
        lambda spec, key, url: [ModelInfo(id="llama-x", context=131072, tools=True), ModelInfo(id="llama-y")],
    )

    async def try_model(llm: Any) -> tuple[bool, str, float]:
        state["tried"].append((llm.name, llm.model))
        return (True, "answered by llama-x", 0.4) if state["answers"] else (False, "model not found", 0.2)

    monkeypatch.setattr(setup_cli, "try_model", try_model)
    monkeypatch.setattr(setup_cli.shutil, "which", lambda name: f"/bin/{name}" if name == "opencode" else None)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    return state


def test_setup_saves_the_key_outside_the_project_and_the_models_it_proved(offline_provider: dict[str, Any]) -> None:
    result = CliRunner().invoke(
        app, ["setup", "--provider", "groq", "--key", "gsk_live_secret_987654", "--model", "llama-x", "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert offline_provider["tried"] == [("groq", "llama-x")]  # one real-shaped request before saving
    assert "gsk_live_secret_987654" not in result.output
    settings = load_user_settings()
    assert (settings.provider, settings.model, settings.agent, settings.agent_model) == (
        "groq", "llama-x", "opencode", "groq/llama-x",
    )
    assert load_credentials() == {"GROQ_API_KEY": "gsk_live_secret_987654"}

    shown = CliRunner().invoke(app, ["setup", "--show"])
    assert "groq · llama-x" in shown.output and "gsk_live_secret_987654" not in shown.output


def test_setup_saves_nothing_when_the_model_does_not_answer(offline_provider: dict[str, Any]) -> None:
    offline_provider["answers"] = False
    result = CliRunner().invoke(app, ["setup", "--provider", "groq", "--key", "gsk_x", "--model", "llama-z", "--yes"])
    assert result.exit_code == 1
    assert "did not answer" in result.output and "Nothing was saved" in result.output
    assert load_user_settings().provider is None and load_credentials() == {}


def test_setup_asks_when_run_interactively(offline_provider: dict[str, Any]) -> None:
    # provider, key (hidden), model (suggested), agent
    result = CliRunner().invoke(app, ["setup"], input="groq\ngsk_typed_key_000111\n\nopencode\n")
    assert result.exit_code == 0, result.output
    assert "llama-x" in result.output and "Paste your Groq API key" in result.output
    assert load_user_settings().model == "llama-x"


def test_run_uses_the_agent_from_setup_unless_the_project_or_a_flag_says_otherwise(monkeypatch: pytest.MonkeyPatch) -> None:
    from contexer.cli.run_cli import choose_agent
    from contexer.config.project import AgentSettings

    monkeypatch.setenv("CONTEXER_AGENT", "opencode")
    monkeypatch.setenv("CONTEXER_AGENT_MODEL", "groq/llama-x")
    assert choose_agent(AgentSettings(), None, None) == ("opencode", "groq/llama-x")
    assert choose_agent(AgentSettings(name="codex"), None, None) == ("codex", None)  # the project's choice
    assert choose_agent(AgentSettings(), "claude-code", None) == ("claude-code", None)  # the flag
    monkeypatch.delenv("CONTEXER_AGENT")
    assert choose_agent(AgentSettings(), None, None)[0] == "claude-code"  # nothing chosen anywhere


def test_models_lists_the_providers_you_can_bring_a_key_for() -> None:
    result = CliRunner().invoke(app, ["models", "--providers"])
    assert result.exit_code == 0
    for label in ("OpenRouter", "Anthropic", "Groq", "DeepSeek", "Ollama"):
        assert label in result.output


def test_a_draft_names_the_model_that_wrote_it_and_flags_a_fallback(fake_llm) -> None:
    import io

    from rich.console import Console

    from contexer.cli.gate_cli import print_drafted_by
    from contexer.workflow.criteria import GoalAnalyzer

    analyzer = GoalAnalyzer(llm_provider=fake_llm())  # asks for "fake-model"
    out = io.StringIO()
    analyzer.drafted_by = "fake-model"
    print_drafted_by(Console(file=out, width=200), analyzer)
    assert "Drafted by fake-model" in out.getvalue() and "fell back" not in out.getvalue()

    out = io.StringIO()
    analyzer.drafted_by = "dots-studio/dots-3-note-preview:free"  # what OpenRouter served when the default was busy
    print_drafted_by(Console(file=out, width=200), analyzer)
    assert "Drafted by dots-studio/dots-3-note-preview:free" in out.getvalue()
    assert "fake-model was unavailable" in out.getvalue()


def test_setup_offers_chromium_only_when_it_is_missing(monkeypatch) -> None:
    from rich.console import Console

    from contexer.cli import setup_cli

    calls: list[list[str]] = []
    states = iter([(False, "Chromium is not installed."), (True, "Chromium 140.0")])

    async def status() -> tuple[bool, str]:
        return next(states)

    monkeypatch.setattr("contexer.observer.browser.chromium_status", status)
    monkeypatch.setattr(setup_cli.subprocess, "call", lambda argv: calls.append(argv) or 0)
    monkeypatch.setattr(setup_cli.typer, "confirm", lambda *_a, **_k: True)
    assert setup_cli.ensure_browser(Console(record=True), ask=True)
    assert calls == [[setup_cli.sys.executable, "-m", "playwright", "install", "chromium"]]

    states = iter([(False, "Chromium is not installed.")])
    console = Console(record=True)
    assert not setup_cli.ensure_browser(console, ask=False)  # --yes never downloads 150 MB unasked
    assert "python -m playwright install chromium" in console.export_text()
    assert len(calls) == 1
