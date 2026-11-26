"""A capability record per model (MOD-1): what a model can do, and where each fact came from.

No test here reaches a provider. The catalogue rows are written in the shape of OpenRouter's
``/models`` reply; they were not captured from a live call.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from rich.console import Console
from typer.testing import CliRunner

from contexer.cli import app, doctor_cli, setup_cli
from contexer.config.user import contexer_home
from contexer.llm import capabilities
from contexer.llm.capabilities import ModelCapabilities, capabilities_of, model_capabilities, save_measurement
from contexer.llm.chat import ToolCallingError, require_tools, supports_tools
from contexer.llm.discovery import ModelInfo
from tests.fakes import ScriptedChatModel
from tests.loop_helpers import GOOD_JS, copy_todo

# A model that has everything, as OpenRouter lists one.
FULL = {
    "id": "vendor/full",
    "created": 1790000000,
    "context_length": 400000,
    "architecture": {"modality": "text+image->text", "input_modalities": ["text", "image"], "output_modalities": ["text"]},
    "pricing": {"prompt": "0.0000025", "completion": "0.000015", "input_cache_read": "0.00000025", "request": "0"},
    "supported_parameters": ["max_tokens", "parallel_tool_calls", "structured_outputs", "tool_choice", "tools"],
}
# A model with each capability absent: no tools, no strict schema, text only, and no window or price given.
BARE = {
    "id": "vendor/bare",
    "architecture": {"modality": "text->text", "input_modalities": ["text"], "output_modalities": ["text"]},
    "supported_parameters": ["max_tokens", "temperature"],
}
ENDPOINT = "https://gateway.example.test/openai/v1"


def _catalogue(*rows: dict[str, Any], status: int = 200) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(status, json={"data": list(rows)}))


def _sources(record: ModelCapabilities) -> set[str]:
    return {origin.split(":")[0] for _name, _value, origin in record.rows()}


def test_openrouters_catalogue_fills_every_fact_and_each_says_so() -> None:
    record = model_capabilities("openrouter", "vendor/full", transport=_catalogue(FULL, BARE))

    assert (record.context_window.value, record.native_tools.value, record.parallel_tool_calls.value) == (400000, True, True)
    assert (record.strict_schemas.value, record.vision.value) == (True, True)
    assert record.input_usd_per_mtok.value == pytest.approx(2.5)
    assert record.output_usd_per_mtok.value == pytest.approx(15.0)
    assert record.cached_input_usd_per_mtok.value == pytest.approx(0.25)
    assert _sources(record) == {"catalogue"}
    assert all("OpenRouter" in origin for _name, _value, origin in record.rows())


def test_a_model_with_each_capability_absent_is_recorded_as_the_catalogue_states_it() -> None:
    record = model_capabilities("openrouter", "vendor/bare", transport=_catalogue(FULL, BARE))

    assert (record.native_tools.value, record.native_tools.source) == (False, "catalogue")
    assert (record.strict_schemas.value, record.strict_schemas.source) == (False, "catalogue")
    assert (record.vision.value, record.vision.source) == (False, "catalogue")
    # A switch that is not listed is not proof the model sends one call at a time: left as assumed.
    assert (record.parallel_tool_calls.value, record.parallel_tool_calls.source) == (True, "assumed")
    # Nobody gave a window or a price: unknown, and no number is made up.
    for fact in (record.context_window, record.input_usd_per_mtok, record.output_usd_per_mtok, record.cached_input_usd_per_mtok):
        assert (fact.value, fact.source) == (None, "assumed")


def test_a_model_nothing_is_known_about_still_has_a_record_and_every_fact_is_assumed() -> None:
    # An OpenAI-compatible gateway lists the id and nothing else, or cannot be asked at all.
    for transport in (_catalogue({"id": "house-model"}), _catalogue(status=500)):
        record = model_capabilities("custom", "house-model", api_key="k", base_url=ENDPOINT, transport=transport)
        assert _sources(record) == {"assumed"}
        assert record.native_tools.value is True and record.context_window.value is None
        assert supports_tools("custom", "house-model", api_key="k", base_url=ENDPOINT, transport=transport) is None
        require_tools("custom", "house-model", api_key="k", base_url=ENDPOINT, transport=transport)  # not refused


def test_a_model_contexer_has_run_its_agents_on_is_marked_measured_under_any_provider() -> None:
    record = model_capabilities("custom", "gpt-5.4", api_key="k", base_url=ENDPOINT, transport=_catalogue({"id": "gpt-5.4"}))

    assert (record.native_tools.value, record.native_tools.source) == (True, "measured")
    assert "2026-11-17" in record.native_tools.detail
    assert record.context_window.source == "assumed" and record.input_usd_per_mtok.value is None  # not measured, so not claimed


def test_what_one_tool_call_showed_is_kept_and_a_model_that_cannot_call_tools_is_refused_with_the_reason() -> None:
    quiet = _catalogue({"id": "house-model"}, {"id": "other-model"})
    save_measurement("custom", ENDPOINT + "/", "house-model", native_tools=False)
    save_measurement("custom", ENDPOINT, "other-model", native_tools=True)

    record = model_capabilities("custom", "house-model", api_key="k", base_url=ENDPOINT, transport=quiet)
    assert (record.native_tools.value, record.native_tools.source) == (False, "measured")
    assert "contexer setup" in record.native_tools.detail
    with pytest.raises(ToolCallingError, match="custom model 'house-model' cannot call tools"):
        require_tools("custom", "house-model", api_key="k", base_url=ENDPOINT, transport=quiet)
    able = require_tools("custom", "other-model", api_key="k", base_url=ENDPOINT, transport=quiet)
    assert (able.native_tools.value, able.native_tools.source) == (True, "measured")
    # Another endpoint serving a model of the same name was not measured.
    elsewhere = model_capabilities("custom", "house-model", api_key="k", base_url="https://other.example.test/v1", transport=quiet)
    assert elsewhere.native_tools.source == "assumed"
    assert (contexer_home() / "models.json").is_file()


def test_a_caller_that_already_has_the_model_list_does_not_ask_again(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capabilities, "_catalogue_row", lambda *_a, **_k: pytest.fail("asked the provider again"))
    listed = [ModelInfo(id="llama-x", context=131072, tools=True)]
    record = model_capabilities("groq", "llama-x", models=listed)
    assert (record.context_window.value, record.native_tools.source) == (131072, "catalogue")
    assert model_capabilities("groq", "llama-unlisted", models=listed).native_tools.source == "assumed"


def test_every_claude_model_on_anthropics_api_is_known_to_call_tools_without_asking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capabilities, "_catalogue_row", lambda *_a, **_k: pytest.fail("no need to ask"))
    record = model_capabilities("anthropic", "claude-opus-5-5")
    assert (record.native_tools.value, record.native_tools.source) == (True, "catalogue")


# -- the record travels with the model an agent runs on ------------------------------------------------


def test_a_built_model_carries_its_record_and_an_unknown_one_gets_assumptions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from contexer.cli.test_cli import build_model

    monkeypatch.setenv("CONTEXER_CUSTOM_API_KEY", "test-key")
    monkeypatch.setenv("CONTEXER_LLM_PROVIDER", "custom")
    monkeypatch.setenv("CONTEXER_LLM_BASE_URL", ENDPOINT)
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(capabilities, "_catalogue_row", lambda *_a, **_k: None)  # the gateway says nothing

    model = build_model(tmp_path, "custom", "gpt-5.4")
    record = capabilities_of(model)
    assert (record.provider, record.model, record.native_tools.source) == ("custom", "gpt-5.4", "measured")
    assert capabilities_of(model.bind_tools([])).model == "gpt-5.4"  # what an agent holds is the bound model

    unknown = capabilities_of(ScriptedChatModel())
    assert unknown.model == "scripted-model" and _sources(unknown) == {"assumed"}


# -- contexer doctor ------------------------------------------------------------------------------------


def test_doctor_prints_each_capability_of_the_configured_model_and_its_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(capabilities, "_catalogue_row", lambda *_a, **_k: ModelInfo(id="vendor/full", context=400000, tools=True, raw=FULL))
    findings = doctor_cli._model_findings("openrouter", "vendor/full")

    by_area = {f.area: f for f in findings}
    assert set(by_area) == {
        "Tool calling", "Parallel calls", "Strict schemas", "Vision", "Context window", "Input price", "Output price", "Cached input",
    }  # fmt: skip
    assert all(f.status == "ok" and "catalogue" in f.detail for f in findings)
    assert "400,000 tokens" in by_area["Context window"].detail and "$2.50" in by_area["Input price"].detail

    monkeypatch.setattr(capabilities, "_catalogue_row", lambda *_a, **_k: ModelInfo(id="vendor/bare", tools=False, raw=BARE))
    bare = {f.area: f for f in doctor_cli._model_findings("openrouter", "vendor/bare")}
    assert bare["Tool calling"].status == "warn" and "cannot call tools" in bare["Tool calling"].detail
    assert "contexer models" in bare["Tool calling"].fix
    assert "not known" in bare["Context window"].detail and "assumed" in bare["Context window"].detail


def test_doctor_says_when_tool_calling_is_only_assumed_and_how_to_measure_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXER_CUSTOM_API_KEY", "test-key")
    monkeypatch.setenv("CONTEXER_LLM_PROVIDER", "custom")
    monkeypatch.setenv("CONTEXER_LLM_BASE_URL", ENDPOINT)
    tools = next(f for f in doctor_cli._model_findings("custom", "house-model") if f.area == "Tool calling")
    assert tools.status == "ok" and "assumed" in tools.detail and "contexer setup" in tools.detail
    # A provider id outside the catalog is not a crash.
    assert doctor_cli._model_findings("fake", "fake-model")[0].area == "Tool calling"


def test_the_doctor_command_shows_the_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CONTEXER_LLM_PROVIDER", "CONTEXER_LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("OPENROUTER_MODEL", "vendor/full")
    monkeypatch.setattr(capabilities, "_catalogue_row", lambda *_a, **_k: ModelInfo(id="vendor/full", context=400000, tools=True, raw=FULL))
    result = CliRunner().invoke(app, ["doctor", "--dir", str(tmp_path)])
    shown = " ".join(result.output.split())
    assert "Context window" in shown and "400,000 tokens" in shown and "catalogue" in shown, result.output


# -- contexer setup -------------------------------------------------------------------------------------


@pytest.fixture
def offline_setup(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """`contexer setup` against a provider that lists a model and says nothing else about it."""
    state: dict[str, Any] = {"tool_calls": 0, "reply": "The sum is 42."}
    monkeypatch.setattr(setup_cli, "check_key", lambda spec, key, url: None)
    monkeypatch.setattr(setup_cli, "list_models", lambda spec, key, url: [ModelInfo(id="house-model")])

    async def try_model(llm: Any) -> tuple[bool, str, float]:
        return True, "answered by house-model", 0.3

    async def check_tool_calling(model: Any) -> str:
        state["tool_calls"] += 1
        state["model"] = (model.model_name, model.openai_api_base)
        if isinstance(state["reply"], Exception):
            raise state["reply"]
        return state["reply"]

    monkeypatch.setattr(setup_cli, "try_model", try_model)
    monkeypatch.setattr(setup_cli, "check_tool_calling", check_tool_calling)
    monkeypatch.setattr(setup_cli.shutil, "which", lambda name: None)
    monkeypatch.setattr(setup_cli, "ensure_browser", lambda *_a, **_k: True)
    return state


def _setup(*extra: str) -> Any:
    return CliRunner().invoke(
        app, ["setup", "--provider", "custom", "--base-url", ENDPOINT, "--key", "test-key-000111", "--model", "house-model", "--yes", *extra]
    )


def test_setup_measures_tool_calling_with_one_call_when_nobody_says_and_shows_the_record(offline_setup: dict[str, Any]) -> None:
    result = _setup()

    shown = " ".join(result.output.split())
    assert result.exit_code == 0, result.output
    assert offline_setup["tool_calls"] == 1 and offline_setup["model"] == ("house-model", ENDPOINT)
    assert "Tool calling" in shown and "measured" in shown and "Context window" in shown and "not known" in shown
    saved = json.loads((contexer_home() / "models.json").read_text(encoding="utf-8"))
    assert saved[f"custom|{ENDPOINT}|house-model"]["native_tools"] is True
    assert "test-key-000111" not in (contexer_home() / "models.json").read_text(encoding="utf-8")

    _setup()  # measured once: the saved answer is used
    assert offline_setup["tool_calls"] == 1


def test_setup_says_when_the_model_cannot_call_tools_and_what_that_means(offline_setup: dict[str, Any]) -> None:
    offline_setup["reply"] = ToolCallingError("The model 'house-model' cannot call tools, which Contexer's agents need.")
    result = _setup()

    shown = " ".join(result.output.split())
    assert result.exit_code == 0, result.output  # it still drafts checks; the settings are saved
    assert "cannot call tools" in shown and "contexer test" in shown
    saved = json.loads((contexer_home() / "models.json").read_text(encoding="utf-8"))
    assert saved[f"custom|{ENDPOINT}|house-model"]["native_tools"] is False


def test_a_tool_call_that_fails_for_another_reason_is_not_taken_for_an_answer(offline_setup: dict[str, Any]) -> None:
    offline_setup["reply"] = RuntimeError("Error code: 429 - rate limit exceeded")
    result = _setup()

    shown = " ".join(result.output.split())
    assert result.exit_code == 0, result.output
    assert "could not be measured" in shown and "429" in shown
    assert not (contexer_home() / "models.json").exists()

    offline_setup["tool_calls"] = 0
    _setup("--no-test")  # no live request was asked for, so none is made
    assert offline_setup["tool_calls"] == 0


# -- contexer run ---------------------------------------------------------------------------------------


def test_a_run_says_why_its_agents_are_off_when_the_model_cannot_call_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = copy_todo(tmp_path)

    def refuse(*_a: Any, **_k: Any) -> Any:
        raise ToolCallingError("The openrouter model 'vendor/bare' cannot call tools, which Contexer's agents need.")

    monkeypatch.setattr("contexer.cli.test_cli.build_model", refuse)
    turns = tmp_path / "turns.json"
    turns.write_text(json.dumps([{"app.js": GOOD_JS + "// x\n"}]), encoding="utf-8")
    result = CliRunner().invoke(
        app, ["run", "--contract", "todo-basics", "--dir", str(project), "--agent", "scripted", "--model", str(turns), "--yes"]
    )
    shown = " ".join(result.output.split())
    assert result.exit_code == 0, result.output
    assert "vendor/bare" in shown and "cannot call tools" in shown and "fixed rules decide" in shown


def test_the_record_is_printed_the_same_way_everywhere() -> None:
    console = Console(record=True, width=120, force_terminal=False, color_system=None)
    setup_cli.show_capabilities(console, ModelCapabilities(provider="custom", model="house-model"))
    text = console.export_text()
    assert "house-model" in text and text.count("assumed") == 8
