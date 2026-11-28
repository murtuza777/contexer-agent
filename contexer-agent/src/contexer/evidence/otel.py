"""Sending a run's trace to an OpenTelemetry collector, when a person asked for it.

Nothing is sent unless ``OTEL_EXPORTER_OTLP_ENDPOINT`` (or ``..._TRACES_ENDPOINT``) is set in the
environment; a project's ``.env`` cannot set it (``config/project.py: _ENV_NEVER_FROM_FILE``). What is
sent is what ``trace.jsonl`` holds about model calls and tool calls: names, token counts, times, costs.
A run event is not sent, because an event can quote a page. The trace has no prompt and no reply.

It speaks OTLP over HTTP with JSON, through the HTTP client Contexer already has, so there is no new
dependency. An export that fails never fails a run: the caller gets a sentence to print.
"""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from contexer import __version__

EXPORT_TIMEOUT = 5.0
_SPAN_KIND_INTERNAL, _SPAN_KIND_CLIENT = 1, 3
_STATUS_ERROR = 2
# Fields of a trace line that say when and what kind, not something about the call.
_NOT_ATTRIBUTES = {"event", "time"}


def export_trace(
    trace: Path,
    *,
    run_id: str,
    terminal: str = "",
    env: Mapping[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> str:
    """Send the model and tool calls of ``trace``; return a sentence about it, or '' when nothing was asked for."""
    env = os.environ if env is None else env
    address = _address(env)
    if not address:
        return ""
    protocol = (env.get("OTEL_EXPORTER_OTLP_TRACES_PROTOCOL") or env.get("OTEL_EXPORTER_OTLP_PROTOCOL") or "http/json").strip()
    if protocol != "http/json":
        return f"The trace was not sent: Contexer speaks OTLP as http/json only, and the protocol set is {protocol}."
    spans = _spans(trace, run_id, terminal)
    if not spans:
        return ""
    body = {
        "resourceSpans": [
            {
                "resource": {"attributes": _attributes({"service.name": "contexer", "service.version": __version__})},
                "scopeSpans": [{"scope": {"name": "contexer", "version": __version__}, "spans": spans}],
            }
        ]
    }
    host = urlsplit(address).netloc.rsplit("@", 1)[-1]  # never the user name or password of an address
    try:
        with httpx.Client(timeout=EXPORT_TIMEOUT, transport=transport, follow_redirects=False) as client:
            response = client.post(
                address, content=json.dumps(body), headers={**_headers(env), "Content-Type": "application/json"}
            )
    except httpx.HTTPError as error:
        return f"The trace was not sent to {host}: {type(error).__name__}."
    if response.status_code >= 300:
        return f"The trace was not sent: {host} answered {response.status_code}."
    return f"Trace sent to {host} ({len(spans) - 1} model and tool calls)."


def _address(env: Mapping[str, str]) -> str:
    """Where spans go: the traces address as given, or the general endpoint with the standard path."""
    exact = (env.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or "").strip()
    if exact:
        return exact
    base = (env.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip()
    return base.rstrip("/") + "/v1/traces" if base else ""


def _headers(env: Mapping[str, str]) -> dict[str, str]:
    """``OTEL_EXPORTER_OTLP_HEADERS``: ``name=value`` pairs separated by commas. They can hold a key; never printed."""
    raw = env.get("OTEL_EXPORTER_OTLP_TRACES_HEADERS") or env.get("OTEL_EXPORTER_OTLP_HEADERS") or ""
    headers: dict[str, str] = {}
    for pair in raw.split(","):
        name, found, value = pair.partition("=")
        if found and name.strip():
            headers[name.strip()] = value.strip()
    return headers


def _spans(trace: Path, run_id: str, terminal: str) -> list[dict[str, Any]]:
    try:
        raw = trace.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    trace_id, root_id = secrets.token_hex(16), secrets.token_hex(8)
    calls: list[dict[str, Any]] = []
    for text in raw:
        try:
            line = json.loads(text)
        except ValueError:
            continue
        if not isinstance(line, dict) or line.get("event") not in ("model", "tool"):
            continue  # a run event can quote a page, so it stays on the machine
        ended = _nanos(str(line.get("time") or ""))
        if ended is None:
            continue
        seconds = line.get("contexer.seconds")
        started = ended - int(float(seconds) * 1_000_000_000) if isinstance(seconds, (int, float)) else ended
        what = line.get("gen_ai.request.model") if line["event"] == "model" else line.get("gen_ai.tool.name")
        span: dict[str, Any] = {
            "traceId": trace_id,
            "spanId": secrets.token_hex(8),
            "parentSpanId": root_id,
            "name": f"{line.get('gen_ai.operation.name') or line['event']} {what or ''}".strip(),
            "kind": _SPAN_KIND_CLIENT if line["event"] == "model" else _SPAN_KIND_INTERNAL,
            "startTimeUnixNano": str(started),
            "endTimeUnixNano": str(ended),
            "attributes": _attributes({k: v for k, v in line.items() if k not in _NOT_ATTRIBUTES}),
        }
        if line.get("error.type") or line.get("contexer.tool.status") == "failed":
            span["status"] = {"code": _STATUS_ERROR}
        calls.append(span)
    if not calls:
        return []
    root: dict[str, Any] = {
        "traceId": trace_id,
        "spanId": root_id,
        "name": "contexer run",
        "kind": _SPAN_KIND_INTERNAL,
        "startTimeUnixNano": str(min(int(s["startTimeUnixNano"]) for s in calls)),
        "endTimeUnixNano": str(max(int(s["endTimeUnixNano"]) for s in calls)),
        "attributes": _attributes({"contexer.run.id": run_id, "contexer.run.terminal": terminal or None}),
    }
    return [root, *calls]


def _nanos(stamp: str) -> int | None:
    try:
        return int(datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp() * 1_000_000_000)
    except ValueError:
        return None


def _attributes(values: Mapping[str, Any]) -> list[dict[str, Any]]:
    """OTLP's typed attribute list. A value that is not known (None) is left out, not sent as empty."""
    out: list[dict[str, Any]] = []
    for key, value in values.items():
        typed = _typed(value)
        if typed is not None:
            out.append({"key": key, "value": typed})
    return out


def _typed(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}  # OTLP's JSON form writes 64-bit integers as strings
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, (list, tuple)):
        items = [typed for typed in (_typed(item) for item in value) if typed is not None]
        return {"arrayValue": {"values": items}} if items else None
    return {"stringValue": str(value)}
