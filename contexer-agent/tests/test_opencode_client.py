"""Unit tests for low-level OpenCodeClient using httpx MockTransport."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from contexer.opencode.client import OpenCodeClient
from contexer.opencode.exceptions import (
    OpenCodeAPIError,
    OpenCodeConnectionError,
    OpenCodeError,
    OpenCodeTimeoutError,
)
from contexer.opencode.models import ExecutionStatus


def make_mock_client(handler) -> OpenCodeClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport, base_url="http://mock-opencode:4096")
    return OpenCodeClient(base_url="http://mock-opencode:4096", client=http_client)


@pytest.mark.anyio
async def test_client_health_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/global/health"
        assert request.method == "GET"
        return httpx.Response(200, json={"healthy": True, "version": "1.4.3"})

    client = make_mock_client(handler)
    health = await client.health()
    assert health.healthy is True
    assert health.version == "1.4.3"


@pytest.mark.anyio
async def test_client_health_malformed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    client = make_mock_client(handler)
    with pytest.raises(OpenCodeAPIError) as excinfo:
        await client.health()
    assert "Failed to parse health response" in str(excinfo.value)


@pytest.mark.anyio
async def test_client_create_session():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/session"
        assert request.method == "POST"
        body = json.loads(request.content)
        assert body.get("title") == "test-session"
        return httpx.Response(
            200,
            json={
                "id": "ses_123",
                "slug": "brave-wolf",
                "version": "1.4.3",
                "projectID": "global",
                "directory": "/tmp/test",
                "title": "test-session",
                "time": {"created": 1000, "updated": 2000},
            },
        )

    client = make_mock_client(handler)
    session = await client.create_session(title="test-session")
    assert session.id == "ses_123"
    assert session.title == "test-session"
    assert session.slug == "brave-wolf"


@pytest.mark.anyio
async def test_client_get_session():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/session/ses_123"
        return httpx.Response(200, json={"id": "ses_123", "title": "my-session"})

    client = make_mock_client(handler)
    session = await client.get_session("ses_123")
    assert session.id == "ses_123"
    assert session.title == "my-session"


@pytest.mark.anyio
async def test_client_list_sessions():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/session"
        return httpx.Response(
            200,
            json=[
                {"id": "ses_1", "title": "first"},
                {"id": "ses_2", "title": "second"},
            ],
        )

    client = make_mock_client(handler)
    sessions = await client.list_sessions()
    assert len(sessions) == 2
    assert sessions[0].id == "ses_1"
    assert sessions[1].id == "ses_2"


@pytest.mark.anyio
async def test_client_send_prompt_async():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/session/ses_123/prompt_async"
        assert request.method == "POST"
        captured["body"] = json.loads(request.content)
        return httpx.Response(204)

    client = make_mock_client(handler)
    await client.send_prompt_async(
        "ses_123",
        "create file foo.py",
        model={"providerID": "opencode", "modelID": "big-pickle"},
        agent="build",
    )
    assert captured["body"]["parts"][0]["text"] == "create file foo.py"
    assert captured["body"]["model"]["modelID"] == "big-pickle"
    assert captured["body"]["agent"] == "build"


@pytest.mark.anyio
async def test_client_send_prompt_sync():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/session/ses_123/message"
        assert request.method == "POST"
        return httpx.Response(
            200,
            json={
                "info": {
                    "id": "msg_456",
                    "role": "assistant",
                    "time": {"created": 1000, "completed": 2000},
                },
                "parts": [{"type": "text", "text": "File created"}],
            },
        )

    client = make_mock_client(handler)
    msg = await client.send_prompt("ses_123", "hello")
    assert msg.info.id == "msg_456"
    assert msg.info.role == "assistant"
    assert msg.parts[0].text == "File created"


@pytest.mark.anyio
async def test_client_get_status():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/session/status"
        return httpx.Response(200, json={"ses_123": {"type": "busy"}})

    client = make_mock_client(handler)
    status_map = await client.get_status()
    assert "ses_123" in status_map
    assert status_map["ses_123"].type == ExecutionStatus.BUSY

    session_status = await client.get_session_status("ses_123")
    assert session_status == ExecutionStatus.BUSY

    unknown_status = await client.get_session_status("ses_other")
    assert unknown_status == ExecutionStatus.IDLE


@pytest.mark.anyio
async def test_client_get_messages():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/session/ses_123/message"
        return httpx.Response(
            200,
            json=[
                {
                    "info": {"id": "msg_1", "role": "user"},
                    "parts": [{"type": "text", "text": "task"}],
                },
                {
                    "info": {
                        "id": "msg_2",
                        "role": "assistant",
                        "error": {"name": "TestError", "data": {"message": "failed"}},
                    },
                    "parts": [],
                },
            ],
        )

    client = make_mock_client(handler)
    messages = await client.get_messages("ses_123")
    assert len(messages) == 2
    assert messages[0].info.role == "user"
    assert messages[1].info.role == "assistant"
    assert messages[1].info.error is not None
    assert messages[1].info.error["name"] == "TestError"


@pytest.mark.anyio
async def test_client_get_diff():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/session/ses_123/diff"
        return httpx.Response(
            200,
            json=[
                {
                    "file": "test.txt",
                    "patch": "+hello",
                    "additions": 1,
                    "deletions": 0,
                    "status": "added",
                }
            ],
        )

    client = make_mock_client(handler)
    diff = await client.get_diff("ses_123")
    assert len(diff) == 1
    assert diff[0].file == "test.txt"
    assert diff[0].additions == 1
    assert diff[0].status == "added"


@pytest.mark.anyio
async def test_client_abort():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/session/ses_123/abort"
        assert request.method == "POST"
        return httpx.Response(200, json=True)

    client = make_mock_client(handler)
    res = await client.abort("ses_123")
    assert res is True


@pytest.mark.anyio
async def test_client_connection_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    client = make_mock_client(handler)
    with pytest.raises(OpenCodeConnectionError) as excinfo:
        await client.health()
    assert excinfo.value.server_url == "http://mock-opencode:4096"
    assert "not reachable" in str(excinfo.value)


@pytest.mark.anyio
async def test_client_timeout_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Read timed out")

    client = make_mock_client(handler)
    with pytest.raises(OpenCodeTimeoutError):
        await client.health()


@pytest.mark.anyio
async def test_client_http_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="Session not found")

    client = make_mock_client(handler)
    with pytest.raises(OpenCodeAPIError) as excinfo:
        await client.get_session("ses_missing")
    assert excinfo.value.status_code == 404
    assert "Session not found" in str(excinfo.value.response_body)


@pytest.mark.anyio
async def test_client_context_manager():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"healthy": True})

    transport = httpx.MockTransport(handler)
    async with OpenCodeClient(
        base_url="http://mock:4096",
        client=httpx.AsyncClient(transport=transport, base_url="http://mock:4096"),
    ) as client:
        health = await client.health()
        assert health.healthy is True
