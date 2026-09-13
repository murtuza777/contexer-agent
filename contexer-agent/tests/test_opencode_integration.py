"""End-to-end integration test against live OpenCode server.

Runs only when OpenCode is installed on the local system.
Creates a temporary Git repository, executes a real task, verifies Git diff,
file contents on disk, and cleans up.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import time
from typing import Generator
import pytest

import httpx

from contexer.opencode.adapter import OpenCodeAdapter
from contexer.opencode.client import OpenCodeClient
from contexer.opencode.models import ExecutionStatus


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _is_opencode_installed() -> bool:
    return shutil.which("opencode") is not None


@pytest.fixture
def opencode_server(tmp_path) -> Generator[tuple[str, str], None, None]:
    """Ensure an OpenCode server is running in a temporary Git repository."""
    if not _is_opencode_installed():
        pytest.skip("OpenCode binary is not installed on this system.")

    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(repo_dir), check=True, capture_output=True)

    port = _find_free_port()
    server_url = f"http://127.0.0.1:{port}"

    log_file = repo_dir / "opencode_test_server.log"
    log_fp = open(log_file, "w", encoding="utf-8")

    cmd = f"opencode serve --port {port} --hostname 127.0.0.1 --print-logs --log-level DEBUG"
    proc = subprocess.Popen(
        cmd,
        cwd=str(repo_dir),
        stdout=log_fp,
        stderr=log_fp,
        shell=True,
    )

    started = False
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(f"{server_url}/global/health", timeout=1.0)
            if resp.status_code == 200 and resp.json().get("healthy"):
                started = True
                break
        except Exception:
            time.sleep(0.5)

    if not started:
        proc.kill()
        pytest.skip(f"Failed to start OpenCode server on port {port}")

    try:
        yield server_url, str(repo_dir)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5.0)
        except Exception:
            proc.kill()
        try:
            log_fp.close()
        except Exception:
            pass


@pytest.mark.anyio
async def test_live_opencode_e2e(opencode_server: tuple[str, str]):
    """Real end-to-end task execution against OpenCode."""
    server_url, repo_path_str = opencode_server
    from pathlib import Path
    repo_dir = Path(repo_path_str)

    # 1. Connect client and adapter
    async with OpenCodeClient(base_url=server_url, timeout=90.0) as client:
        adapter = OpenCodeAdapter(
            client=client,
            model_provider="opencode",
            model_id="nemotron-3.5-lightning-free",
        )

        # 2. Check server health
        health = await adapter.check_health()
        assert health.healthy is True
        assert health.version is not None

        # 3. Create session inside the test repository directory
        session = await adapter.create_session(
            title="E2E Contexer Verification",
            directory=repo_path_str,
        )
        assert session.id.startswith("ses_")

        # 5. Send engineering task prompt
        prompt = (
            "Create a file called contexer_test.txt in the current repository. "
            "The file must contain exactly: Hello from Contexer"
        )
        result = await adapter.send_prompt(
            session_id=session.id,
            prompt=prompt,
            wait=True,
            timeout=90.0,
            poll_interval=0.5,
        )

        # 6. Verify completion status
        assert result.status == ExecutionStatus.COMPLETED
        assert result.error is None
        assert result.duration_seconds > 0

        # 7. Verify file was created on disk
        created_file = repo_dir / "contexer_test.txt"
        assert created_file.exists(), f"File was not created at {created_file}"
        content = created_file.read_text(encoding="utf-8").strip()
        assert content == "Hello from Contexer"

        # 8. Verify diff retrieval
        assert len(result.diff) >= 1
        diff_files = [item.file for item in result.diff]
        assert "contexer_test.txt" in diff_files
        test_diff = next(item for item in result.diff if item.file == "contexer_test.txt")
        assert test_diff.additions >= 1
        assert "Hello from Contexer" in test_diff.patch

        # 9. Test abort on session
        aborted = await adapter.abort(session.id)
        assert aborted is True
