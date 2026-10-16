"""Drive OpenCode through its HTTP server.

If no server answers at the configured URL, the adapter starts
``opencode serve`` itself (in its own process tree) and stops it on
``close()``. Models are named ``provider/model``; the default comes from
``OPENCODE_MODEL_PROVIDER`` / ``OPENCODE_MODEL_ID``.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Optional

import httpx

from contexer.agents.base import AgentTurn, CodingAgentAdapter, ProgressFn
from contexer.opencode.adapter import OpenCodeAdapter
from contexer.opencode.models import ExecutionStatus
from contexer.procutil import ProcessTree, spawn_tree


class OpenCodeAgent(CodingAgentAdapter):
    name = "opencode"

    def __init__(
        self,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        start_server: bool = True,
    ) -> None:
        from contexer.config.settings import load_config

        config = load_config()
        provider, model_id = config.opencode_model_provider, config.opencode_model_id
        if model and "/" in model:
            provider, model_id = model.split("/", 1)
        elif model:
            model_id = model
        self.provider, self.model_id = provider, model_id
        self.base_url = (base_url or config.opencode_server_url).rstrip("/")
        self.start_server = start_server
        self._server: Optional[ProcessTree] = None
        self._adapter: Optional[OpenCodeAdapter] = None

    def describe(self) -> str:
        return f"opencode ({self.provider}/{self.model_id})"

    async def run_turn(
        self,
        workdir: Path,
        prompt: str,
        *,
        session_id: Optional[str] = None,
        timeout: float = 900.0,
        budget_usd: Optional[float] = None,
        on_progress: Optional[ProgressFn] = None,
    ) -> AgentTurn:
        started = time.monotonic()
        try:
            adapter = self._ensure_server(Path(workdir))
            if session_id is None:
                session = await adapter.create_session(title="Contexer run", directory=str(Path(workdir).resolve()))
                session_id = session.id
            if on_progress:
                on_progress(f"OpenCode session {session_id} working")
            result = await adapter.send_prompt(session_id=session_id, prompt=prompt, wait=True, timeout=timeout)
        except Exception as exc:
            return AgentTurn(
                status="failed",
                session_id=session_id,
                error=f"OpenCode unavailable: {exc}",
                duration_seconds=time.monotonic() - started,
            )
        status = {
            ExecutionStatus.COMPLETED: "completed",
            ExecutionStatus.ABORTED: "cancelled",
        }.get(result.status, "failed")
        timed_out = bool(result.error and "timed out" in result.error)
        return AgentTurn(
            status="timeout" if timed_out else status,  # type: ignore[arg-type]
            session_id=session_id,
            summary=result.response_text[:4000],
            error=result.error,
            duration_seconds=time.monotonic() - started,
            files_touched=[d.file for d in result.diff],
        )

    def close(self) -> None:
        if self._server is not None:
            self._server.kill()
            self._server = None

    def _ensure_server(self, workdir: Path) -> OpenCodeAdapter:
        if self._adapter is not None and (self._server is None or self._server.poll() is None):
            return self._adapter
        if not _healthy(self.base_url):
            if not self.start_server:
                raise RuntimeError(f"no OpenCode server at {self.base_url}")
            exe = shutil.which("opencode")
            if exe is None:
                raise RuntimeError("the opencode CLI is not installed")
            port = self.base_url.rsplit(":", 1)[-1]
            self._server = spawn_tree([exe, "serve", "--port", port], workdir)
            deadline = time.monotonic() + 60
            while not _healthy(self.base_url):
                if self._server.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("opencode serve did not become healthy")
                time.sleep(0.5)
        self._adapter = OpenCodeAdapter(base_url=self.base_url, model_provider=self.provider, model_id=self.model_id)
        return self._adapter


def _healthy(base_url: str) -> bool:
    try:
        return httpx.get(f"{base_url}/global/health", timeout=2.0).status_code == 200
    except httpx.HTTPError:
        return False
