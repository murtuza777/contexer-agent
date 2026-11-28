"""OBS-4: a run's trace can be sent to an OpenTelemetry collector, and only when a person asked for it.

The export sends what ``trace.jsonl`` holds about model calls and tool calls: names, counts, times, costs.
It never sends a prompt, a reply or a run event (an event can quote a page), and a project's ``.env``
cannot switch it on.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest

from contexer.config.project import load_env_file
from contexer.evidence.otel import export_trace

ENDPOINT = "http://collector.test:4318"


def _trace(tmp_path: Path) -> Path:
    lines = [
        {"event": "trace", "time": "2026-11-28T10:00:00.000Z", "format": 1, "semconv": "1.40.0"},
        {"event": "strategy", "message": "the page says: made-up page text that must stay home"},
        {
            "event": "model", "time": "2026-11-28T10:00:05.000Z", "gen_ai.operation.name": "chat", "gen_ai.agent.name": "planner",
            "gen_ai.provider.name": "openrouter", "gen_ai.request.model": "some/model", "gen_ai.response.model": "some/model-0728",
            "gen_ai.usage.input_tokens": 1200, "gen_ai.usage.output_tokens": 80, "gen_ai.usage.cache_read.input_tokens": None,
            "gen_ai.response.finish_reasons": ["stop"], "contexer.step": 1, "contexer.seconds": 2.5, "contexer.cost_usd": 0.004,
            "contexer.cost_estimated": True,
        },
        {
            "event": "tool", "time": "2026-11-28T10:00:06.000Z", "gen_ai.operation.name": "execute_tool", "gen_ai.agent.name": "planner",
            "gen_ai.tool.name": "read_file", "contexer.tool.status": "ok", "contexer.step": 1, "contexer.seconds": 0.25,
        },
        {"event": "model", "time": "2026-11-28T10:00:09.000Z", "gen_ai.operation.name": "chat", "gen_ai.agent.name": "reviewer",
         "gen_ai.provider.name": "openrouter", "gen_ai.request.model": "some/model", "gen_ai.usage.input_tokens": 10,
         "gen_ai.usage.output_tokens": 0, "contexer.step": 1, "contexer.seconds": 1.0, "error.type": "RateLimitError"},
    ]  # fmt: skip
    path = tmp_path / "trace.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    return path


class Collector:
    def __init__(self, status: int = 200) -> None:
        self.status, self.requests = status, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json={})


def _attributes(span: dict) -> dict:
    return {a["key"]: next(iter(a["value"].values())) for a in span["attributes"]}


def test_nothing_is_sent_unless_an_endpoint_is_set(tmp_path: Path) -> None:
    collector = Collector()

    note = export_trace(_trace(tmp_path), run_id="20261128-100000-abcd", env={}, transport=httpx.MockTransport(collector))

    assert note == "" and collector.requests == []


def test_a_run_is_sent_as_one_trace_with_a_span_for_each_model_and_tool_call(tmp_path: Path) -> None:
    collector = Collector()
    env = {"OTEL_EXPORTER_OTLP_ENDPOINT": ENDPOINT + "/", "OTEL_EXPORTER_OTLP_HEADERS": "authorization=Basic made-up, x-team = qa"}

    note = export_trace(_trace(tmp_path), run_id="20261128-100000-abcd", terminal="succeeded", env=env, transport=httpx.MockTransport(collector))

    [request] = collector.requests
    assert str(request.url) == ENDPOINT + "/v1/traces" and request.method == "POST"
    assert request.headers["authorization"] == "Basic made-up" and request.headers["x-team"] == "qa"
    assert request.headers["content-type"] == "application/json"
    body = json.loads(request.content)
    [resource] = body["resourceSpans"]
    assert _attributes({"attributes": resource["resource"]["attributes"]})["service.name"] == "contexer"
    spans = resource["scopeSpans"][0]["spans"]
    assert [s["name"] for s in spans] == ["contexer run", "chat some/model", "execute_tool read_file", "chat some/model"]
    root, model, tool, failed = spans
    assert len({s["traceId"] for s in spans}) == 1 and len(root["traceId"]) == 32 and len(root["spanId"]) == 16
    assert all(s["parentSpanId"] == root["spanId"] for s in (model, tool, failed)) and not root.get("parentSpanId")
    assert _attributes(root)["contexer.run.id"] == "20261128-100000-abcd" and _attributes(root)["contexer.run.terminal"] == "succeeded"
    # The call ended at 10:00:05 and took 2.5 seconds.
    assert int(model["endTimeUnixNano"]) - int(model["startTimeUnixNano"]) == 2_500_000_000
    assert int(root["startTimeUnixNano"]) <= int(model["startTimeUnixNano"]) and int(root["endTimeUnixNano"]) >= int(failed["endTimeUnixNano"])
    told = _attributes(model)
    assert told["gen_ai.agent.name"] == "planner" and told["gen_ai.request.model"] == "some/model"
    assert told["gen_ai.usage.input_tokens"] == "1200" and told["contexer.cost_usd"] == 0.004 and told["contexer.cost_estimated"] is True
    assert "gen_ai.usage.cache_read.input_tokens" not in told  # the provider did not say: nothing is made up
    assert _attributes(tool)["contexer.tool.status"] == "ok"
    assert failed["status"]["code"] == 2 and _attributes(failed)["error.type"] == "RateLimitError"
    assert "sent" in note and "collector.test" in note and "made-up" not in note  # where it went, never the header


def test_what_a_run_said_about_a_page_is_not_sent(tmp_path: Path) -> None:
    collector = Collector()

    export_trace(_trace(tmp_path), run_id="r", env={"OTEL_EXPORTER_OTLP_ENDPOINT": ENDPOINT}, transport=httpx.MockTransport(collector))

    assert b"made-up page text" not in collector.requests[0].content and b"strategy" not in collector.requests[0].content


def test_a_collector_that_fails_or_cannot_be_reached_does_not_fail_the_run(tmp_path: Path) -> None:
    env = {"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": ENDPOINT + "/custom/path"}
    refusing = Collector(status=503)

    note = export_trace(_trace(tmp_path), run_id="r", env=env, transport=httpx.MockTransport(refusing))

    assert str(refusing.requests[0].url) == ENDPOINT + "/custom/path"  # the full address, used as given
    assert "503" in note and "not sent" in note

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nobody home")

    assert "not sent" in export_trace(_trace(tmp_path), run_id="r", env=env, transport=httpx.MockTransport(unreachable))
    assert export_trace(tmp_path / "missing.jsonl", run_id="r", env=env, transport=httpx.MockTransport(refusing)) == ""


def test_only_http_with_json_is_spoken_and_another_protocol_is_said_not_guessed(tmp_path: Path) -> None:
    collector = Collector()
    env = {"OTEL_EXPORTER_OTLP_ENDPOINT": ENDPOINT, "OTEL_EXPORTER_OTLP_PROTOCOL": "grpc"}

    note = export_trace(_trace(tmp_path), run_id="r", env=env, transport=httpx.MockTransport(collector))

    assert collector.requests == [] and "http/json" in note


def test_contexer_run_sends_its_trace_when_asked_and_says_where(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from contexer.cli import app, run_cli
    from tests.fakes import AgentScript
    from tests.loop_helpers import CONTRACT_ID, GOOD_JS, copy_todo

    project = copy_todo(tmp_path)
    turns = tmp_path / "turns.json"
    turns.write_text(json.dumps([{"app.js": GOOD_JS + "// tidied\n"}]), encoding="utf-8")
    asked: list[dict] = []

    def recording(trace: Path, **kwargs: object) -> str:
        asked.append({"trace": trace, **kwargs})
        return "Trace sent to collector.test (3 model and tool calls)."

    monkeypatch.setattr(run_cli, "export_trace", recording)
    monkeypatch.setattr(run_cli, "crew_model", lambda *_a, **_k: AgentScript())

    result = CliRunner().invoke(app, ["run", "--contract", CONTRACT_ID, "--dir", str(project), "--agent", "scripted", "--model", str(turns), "--yes", "--plain"])

    assert result.exit_code == 0, result.output
    [call] = asked
    assert call["trace"].name == "trace.jsonl" and call["trace"].is_file() and call["terminal"] == "succeeded"
    assert "Trace sent to collector.test" in " ".join(result.output.split())


def test_a_projects_env_file_cannot_switch_the_export_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_HEADERS", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("OTEL_EXPORTER_OTLP_ENDPOINT=http://elsewhere.test\nOTEL_EXPORTER_OTLP_HEADERS=a=b\n", encoding="utf-8")
    refused: list[str] = []

    load_env_file(env_file, refused.append)

    assert "OTEL_EXPORTER_OTLP_ENDPOINT" not in os.environ and "OTEL_EXPORTER_OTLP_HEADERS" not in os.environ
    assert sorted(refused) == ["OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_HEADERS"]
