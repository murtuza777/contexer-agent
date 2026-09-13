"""End-to-end test of the autonomous Contexer loop."""

from __future__ import annotations

import functools
import http.server
import socket
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest

from contexer.observer.playwright import PlaywrightObserver
from contexer.opencode.adapter import OpenCodeAdapter
from contexer.opencode.models import ExecutionStatus, OpenCodeDiffItem, OpenCodeExecutionResult, OpenCodeSession
from contexer.verification.verifier import Verifier
from contexer.workflow.loop import AutonomousLoop


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def local_web_app(tmp_path):
    """Spawns a local HTTP server serving a test HTML application."""
    port = _find_free_port()
    html_file = tmp_path / "index.html"
    html_file.write_text(
        "<html><head><title>Test App</title></head><body><h1>Welcome to our App</h1></body></html>",
        encoding="utf-8",
    )

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield f"http://127.0.0.1:{port}", html_file

    server.shutdown()
    server.server_close()


@pytest.mark.anyio
async def test_autonomous_loop_end_to_end(local_web_app):
    """Prove the complete loop: Attempt 1 fails -> Repair prompt dispatched -> Attempt 2 passes."""
    app_url, html_file = local_web_app

    # Mock OpenCode adapter to simulate realistic coding engine behavior
    adapter = MagicMock(spec=OpenCodeAdapter)
    adapter.create_session = AsyncMock(return_value=OpenCodeSession(id="ses_auto_123", title="Test Task"))

    call_count = 0

    async def _send_prompt_side_effect(session_id: str, prompt: str, **kwargs):
        nonlocal call_count
        call_count += 1
        # First call is initial prompt: does NOT fix the button
        if call_count == 1:
            return OpenCodeExecutionResult(
                session_id=session_id,
                status=ExecutionStatus.COMPLETED,
                duration_seconds=1.0,
                response_text="Created initial layout without button.",
                diff=[],
            )

        # Subsequent call is the repair prompt: fixes index.html
        html_file.write_text(
            "<html><head><title>Test App</title></head><body><h1>Welcome</h1><button id='cta'>Get Started</button></body></html>",
            encoding="utf-8",
        )
        return OpenCodeExecutionResult(
            session_id=session_id,
            status=ExecutionStatus.COMPLETED,
            duration_seconds=1.2,
            response_text="Added Get Started button to index.html.",
            diff=[OpenCodeDiffItem(file="index.html", patch="+<button>Get Started</button>", additions=1, deletions=0)],
        )

    adapter.send_prompt = AsyncMock(side_effect=_send_prompt_side_effect)

    observer = PlaywrightObserver(headless=True)
    verifier = Verifier()  # Deterministic criteria verification
    loop = AutonomousLoop(
        adapter=adapter,
        observer=observer,
        verifier=verifier,
        max_attempts=3,
    )

    goal = "Create a landing page with a 'Get Started' button."
    result = await loop.run(goal=goal, app_url=app_url)

    # Verifications:
    # 1. Loop succeeded
    assert result.passed is True
    # 2. Required 2 attempts (1 initial failure + 1 repair)
    assert result.attempts == 2
    # 3. Verification result confirms success
    assert result.verification is not None
    assert result.verification.passed is True
    # 4. Final observation saw the button
    assert result.observation is not None
    assert "Get Started" in result.observation.visible_text
    # 5. OpenCode received both the initial goal and the repair prompt
    assert adapter.send_prompt.await_count == 2
