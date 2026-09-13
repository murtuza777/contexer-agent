"""Unit tests for OpenCodeAdapter and CodingAgent abstraction."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
import pytest

from contexer.opencode.adapter import CodingAgent, OpenCodeAdapter
from contexer.opencode.client import OpenCodeClient
from contexer.opencode.models import (
    ExecutionStatus,
    OpenCodeDiffItem,
    OpenCodeHealth,
    OpenCodeMessage,
    OpenCodeMessageInfo,
    OpenCodePart,
    OpenCodeSession,
)


@pytest.fixture
def mock_client() -> MagicMock:
    client = MagicMock(spec=OpenCodeClient)
    client.create_session = AsyncMock()
    client.get_session = AsyncMock()
    client.send_prompt_async = AsyncMock()
    client.get_session_status = AsyncMock()
    client.get_messages = AsyncMock()
    client.get_diff = AsyncMock()
    client.abort = AsyncMock()
    client.health = AsyncMock()
    return client


@pytest.mark.anyio
async def test_adapter_is_coding_agent(mock_client: MagicMock):
    adapter = OpenCodeAdapter(client=mock_client)
    assert isinstance(adapter, CodingAgent)


@pytest.mark.anyio
async def test_adapter_check_health(mock_client: MagicMock):
    mock_client.health.return_value = OpenCodeHealth(healthy=True, version="1.4.3")
    adapter = OpenCodeAdapter(client=mock_client)
    res = await adapter.check_health()
    assert res.healthy is True
    assert res.version == "1.4.3"


@pytest.mark.anyio
async def test_adapter_create_session(mock_client: MagicMock):
    mock_client.create_session.return_value = OpenCodeSession(id="ses_abc", title="my-task")
    adapter = OpenCodeAdapter(client=mock_client)
    session = await adapter.create_session(title="my-task")
    assert session.id == "ses_abc"
    mock_client.create_session.assert_awaited_once_with(title="my-task", directory=None)


@pytest.mark.anyio
async def test_adapter_send_prompt_async_no_wait(mock_client: MagicMock):
    adapter = OpenCodeAdapter(client=mock_client)
    result = await adapter.send_prompt(session_id="ses_abc", prompt="create file", wait=False)
    assert result.status == ExecutionStatus.BUSY
    mock_client.send_prompt_async.assert_awaited_once()


@pytest.mark.anyio
async def test_adapter_send_prompt_success(mock_client: MagicMock):
    mock_client.send_prompt.return_value = OpenCodeMessage(
        info=OpenCodeMessageInfo(id="msg_a", role="assistant"),
        parts=[OpenCodePart(type="text", text="File created successfully.")],
    )
    mock_client.get_diff.return_value = [
        OpenCodeDiffItem(file="contexer_test.txt", patch="+Hello", additions=1, deletions=0)
    ]

    adapter = OpenCodeAdapter(client=mock_client)
    result = await adapter.send_prompt(
        session_id="ses_abc",
        prompt="create file",
        wait=True,
    )

    assert result.status == ExecutionStatus.COMPLETED
    assert result.response_text == "File created successfully."
    assert len(result.diff) == 1
    assert result.diff[0].file == "contexer_test.txt"
    assert result.error is None


@pytest.mark.anyio
async def test_adapter_send_prompt_execution_failure(mock_client: MagicMock):
    mock_client.send_prompt.return_value = OpenCodeMessage(
        info=OpenCodeMessageInfo(
            id="msg_a",
            role="assistant",
            error={"name": "RateLimitError", "data": {"message": "Rate limit exceeded"}},
        ),
        parts=[],
    )
    mock_client.get_diff.return_value = []

    adapter = OpenCodeAdapter(client=mock_client)
    result = await adapter.send_prompt(
        session_id="ses_abc",
        prompt="test",
        wait=True,
    )

    assert result.status == ExecutionStatus.FAILED
    assert "RateLimitError" in (result.error or "")


@pytest.mark.anyio
async def test_adapter_send_prompt_aborted(mock_client: MagicMock):
    mock_client.send_prompt.return_value = OpenCodeMessage(
        info=OpenCodeMessageInfo(
            id="msg_a",
            role="assistant",
            error={"name": "MessageAbortedError", "data": {"message": "Aborted"}},
        ),
        parts=[],
    )
    mock_client.get_diff.return_value = []

    adapter = OpenCodeAdapter(client=mock_client)
    result = await adapter.send_prompt(
        session_id="ses_abc",
        prompt="test",
        wait=True,
    )

    assert result.status == ExecutionStatus.ABORTED
    assert "aborted" in (result.error or "").lower()


@pytest.mark.anyio
async def test_adapter_wait_for_completion_success(mock_client: MagicMock):
    mock_client.get_session_status.side_effect = [
        ExecutionStatus.BUSY,
        ExecutionStatus.IDLE,
    ]
    mock_client.get_messages.return_value = [
        OpenCodeMessage(
            info=OpenCodeMessageInfo(id="msg_a", role="assistant"),
            parts=[OpenCodePart(type="text", text="Polled completion.")],
        )
    ]
    mock_client.get_diff.return_value = []

    adapter = OpenCodeAdapter(client=mock_client)
    result = await adapter.wait_for_completion(session_id="ses_abc", poll_interval=0.01)
    assert result.status == ExecutionStatus.COMPLETED
    assert result.response_text == "Polled completion."


@pytest.mark.anyio
async def test_adapter_wait_for_completion_timeout(mock_client: MagicMock):
    mock_client.get_session_status.return_value = ExecutionStatus.BUSY
    mock_client.get_diff.return_value = []

    adapter = OpenCodeAdapter(client=mock_client)
    result = await adapter.wait_for_completion(
        session_id="ses_abc",
        timeout=0.05,
        poll_interval=0.01,
    )

    assert result.status == ExecutionStatus.FAILED
    assert "timed out" in (result.error or "").lower()


@pytest.mark.anyio
async def test_adapter_abort_call(mock_client: MagicMock):
    mock_client.abort.return_value = True
    adapter = OpenCodeAdapter(client=mock_client)
    aborted = await adapter.abort("ses_abc")
    assert aborted is True
    mock_client.abort.assert_awaited_once_with("ses_abc")


@pytest.mark.anyio
async def test_adapter_model_config_passed(mock_client: MagicMock):
    adapter = OpenCodeAdapter(
        client=mock_client,
        model_provider="opencode",
        model_id="big-pickle",
        agent_name="build",
    )
    mock_client.get_session_status.return_value = ExecutionStatus.IDLE
    mock_client.get_messages.return_value = []
    mock_client.get_diff.return_value = []

    await adapter.send_prompt("ses_abc", "prompt", wait=False)
    mock_client.send_prompt_async.assert_awaited_once_with(
        session_id="ses_abc",
        prompt="prompt",
        model={"providerID": "opencode", "modelID": "big-pickle"},
        agent="build",
    )
