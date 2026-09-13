"""Contexer orchestration adapter for coding agents (OpenCode)."""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
import logging
import time
from typing import Optional

from contexer.opencode.client import OpenCodeClient
from contexer.opencode.exceptions import (
    OpenCodeAbortError,
    OpenCodeConnectionError,
    OpenCodeError,
    OpenCodeExecutionError,
    OpenCodeTimeoutError,
)
from contexer.opencode.models import (
    ExecutionStatus,
    OpenCodeDiffItem,
    OpenCodeExecutionResult,
    OpenCodeHealth,
    OpenCodeMessage,
    OpenCodeSession,
)

logger = logging.getLogger(__name__)


class CodingAgent(ABC):
    """Abstract interface representing an external coding execution engine."""

    @abstractmethod
    async def create_session(
        self,
        title: Optional[str] = None,
        directory: Optional[str] = None,
    ) -> OpenCodeSession:
        """Create a new session in the coding engine."""

    @abstractmethod
    async def send_prompt(
        self,
        session_id: str,
        prompt: str,
        wait: bool = True,
        timeout: float = 120.0,
        poll_interval: float = 0.5,
    ) -> OpenCodeExecutionResult:
        """Send a prompt to the engine, optionally waiting for completion."""

    @abstractmethod
    async def wait_for_completion(
        self,
        session_id: str,
        timeout: float = 120.0,
        poll_interval: float = 0.5,
    ) -> OpenCodeExecutionResult:
        """Poll the engine until the session finishes or times out."""

    @abstractmethod
    async def get_messages(
        self,
        session_id: str,
        limit: Optional[int] = None,
    ) -> list[OpenCodeMessage]:
        """Retrieve message history for a session."""

    @abstractmethod
    async def get_diff(self, session_id: str) -> list[OpenCodeDiffItem]:
        """Retrieve Git diffs produced by the session."""

    @abstractmethod
    async def abort(self, session_id: str) -> bool:
        """Abort any ongoing execution in the session."""


class OpenCodeAdapter(CodingAgent):
    """Concrete adapter connecting Contexer to an OpenCode server."""

    def __init__(
        self,
        client: Optional[OpenCodeClient] = None,
        base_url: str = "http://127.0.0.1:4096",
        timeout: float = 30.0,
        model_provider: Optional[str] = "opencode",
        model_id: Optional[str] = "nemotron-3.5-lightning-free",
        agent_name: Optional[str] = None,
    ) -> None:
        self.client = client or OpenCodeClient(base_url=base_url, timeout=timeout)
        self.model_provider = model_provider
        self.model_id = model_id
        self.agent_name = agent_name

    def _get_model_config(self) -> Optional[dict[str, str]]:
        if self.model_provider and self.model_id:
            return {"providerID": self.model_provider, "modelID": self.model_id}
        return None

    async def check_health(self) -> OpenCodeHealth:
        """Verify the OpenCode server is reachable and healthy."""
        return await self.client.health()

    async def create_session(
        self,
        title: Optional[str] = None,
        directory: Optional[str] = None,
    ) -> OpenCodeSession:
        """Create a new session in OpenCode."""
        return await self.client.create_session(title=title, directory=directory)

    async def send_prompt(
        self,
        session_id: str,
        prompt: str,
        wait: bool = True,
        timeout: float = 120.0,
        poll_interval: float = 0.5,
    ) -> OpenCodeExecutionResult:
        """Send a prompt to OpenCode.

        If ``wait=True``, dispatches via synchronous message endpoint with timeout.
        If ``wait=False``, dispatches asynchronously and returns BUSY immediately.
        """
        start_time = time.monotonic()
        model_cfg = self._get_model_config()

        if not wait:
            await self.client.send_prompt_async(
                session_id=session_id,
                prompt=prompt,
                model=model_cfg,
                agent=self.agent_name,
            )
            return OpenCodeExecutionResult(
                session_id=session_id,
                status=ExecutionStatus.BUSY,
                response_text="Prompt submitted asynchronously.",
                duration_seconds=time.monotonic() - start_time,
            )

        try:
            assistant_msg = await self.client.send_prompt(
                session_id=session_id,
                prompt=prompt,
                model=model_cfg,
                agent=self.agent_name,
                timeout=timeout,
            )
        except OpenCodeTimeoutError:
            diff = await self._safe_get_diff(session_id)
            return OpenCodeExecutionResult(
                session_id=session_id,
                status=ExecutionStatus.FAILED,
                diff=diff,
                response_text="",
                error=f"Execution timed out after {timeout:.1f} seconds.",
                duration_seconds=time.monotonic() - start_time,
            )

        duration = time.monotonic() - start_time
        status = ExecutionStatus.COMPLETED
        error_msg: Optional[str] = None
        response_text = ""

        text_parts = [
            p.text for p in assistant_msg.parts if p.type == "text" and p.text
        ]
        response_text = "\n".join(text_parts)

        if assistant_msg.info.error:
            err_dict = assistant_msg.info.error
            err_name = err_dict.get("name", "ExecutionError")
            err_data = err_dict.get("data", {})
            detail = err_data.get("message", str(err_dict)) if isinstance(err_data, dict) else str(err_data)
            if err_name == "MessageAbortedError" or "aborted" in detail.lower():
                status = ExecutionStatus.ABORTED
                error_msg = "Execution was aborted."
            else:
                status = ExecutionStatus.FAILED
                error_msg = f"{err_name}: {detail}"

        diff = await self._safe_get_diff(session_id)

        return OpenCodeExecutionResult(
            session_id=session_id,
            status=status,
            diff=diff,
            response_text=response_text,
            error=error_msg,
            duration_seconds=duration,
        )

    async def wait_for_completion(
        self,
        session_id: str,
        timeout: float = 120.0,
        poll_interval: float = 0.5,
        start_time: Optional[float] = None,
    ) -> OpenCodeExecutionResult:
        """Poll the session until terminal state (idle / completed / error / timeout)."""
        if start_time is None:
            start_time = time.monotonic()

        seen_busy = False

        while True:
            elapsed = time.monotonic() - start_time
            if elapsed > timeout:
                logger.warning(f"OpenCode session {session_id} timed out after {elapsed:.1f}s")
                diff = await self._safe_get_diff(session_id)
                return OpenCodeExecutionResult(
                    session_id=session_id,
                    status=ExecutionStatus.FAILED,
                    diff=diff,
                    response_text="",
                    error=f"Execution timed out after {timeout:.1f} seconds.",
                    duration_seconds=elapsed,
                )

            current_status = await self.client.get_session_status(session_id)

            if current_status == ExecutionStatus.BUSY:
                seen_busy = True

            # If we've seen it busy and it's now idle, or if it was never marked busy and is idle
            # after waiting at least one polling cycle to let the server transition:
            if current_status == ExecutionStatus.IDLE:
                if seen_busy or elapsed >= poll_interval:
                    break

            await asyncio.sleep(poll_interval)

        duration = time.monotonic() - start_time

        # Inspect completed messages
        messages = await self.client.get_messages(session_id)
        last_assistant_msg: Optional[OpenCodeMessage] = None
        for msg in reversed(messages):
            if msg.info.role == "assistant":
                last_assistant_msg = msg
                break

        status = ExecutionStatus.COMPLETED
        error_msg: Optional[str] = None
        response_text = ""

        if last_assistant_msg:
            # Extract response text
            text_parts = [
                p.text for p in last_assistant_msg.parts if p.type == "text" and p.text
            ]
            response_text = "\n".join(text_parts)

            # Check for errors
            if last_assistant_msg.info.error:
                err_dict = last_assistant_msg.info.error
                err_name = err_dict.get("name", "ExecutionError")
                err_data = err_dict.get("data", {})
                detail = err_data.get("message", str(err_dict)) if isinstance(err_data, dict) else str(err_data)

                if err_name == "MessageAbortedError" or "aborted" in detail.lower():
                    status = ExecutionStatus.ABORTED
                    error_msg = "Execution was aborted."
                else:
                    status = ExecutionStatus.FAILED
                    error_msg = f"{err_name}: {detail}"

        diff = await self._safe_get_diff(session_id)

        return OpenCodeExecutionResult(
            session_id=session_id,
            status=status,
            diff=diff,
            response_text=response_text,
            error=error_msg,
            duration_seconds=duration,
        )

    async def _safe_get_diff(self, session_id: str) -> list[OpenCodeDiffItem]:
        """Safely fetch diff without crashing on error."""
        try:
            return await self.client.get_diff(session_id)
        except Exception as exc:
            logger.debug(f"Failed to fetch diff for session {session_id}: {exc}")
            return []

    async def get_messages(
        self,
        session_id: str,
        limit: Optional[int] = None,
    ) -> list[OpenCodeMessage]:
        """Retrieve messages from OpenCode."""
        return await self.client.get_messages(session_id, limit=limit)

    async def get_diff(self, session_id: str) -> list[OpenCodeDiffItem]:
        """Retrieve Git diffs from OpenCode."""
        return await self.client.get_diff(session_id)

    async def abort(self, session_id: str) -> bool:
        """Send abort signal to the OpenCode session."""
        return await self.client.abort(session_id)
