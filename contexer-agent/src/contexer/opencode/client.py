"""Low-level asynchronous HTTP client for the OpenCode Server."""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from contexer.opencode.exceptions import (
    OpenCodeAPIError,
    OpenCodeConnectionError,
    OpenCodeError,
    OpenCodeTimeoutError,
)
from contexer.opencode.models import (
    ExecutionStatus,
    OpenCodeDiffItem,
    OpenCodeHealth,
    OpenCodeMessage,
    OpenCodeSession,
    OpenCodeSessionStatus,
)

logger = logging.getLogger(__name__)

DEFAULT_OPENCODE_URL = "http://127.0.0.1:4096"
DEFAULT_REQUEST_TIMEOUT = 30.0


class OpenCodeClient:
    """HTTP client communicating with a running OpenCode server."""

    def __init__(
        self,
        base_url: str = DEFAULT_OPENCODE_URL,
        timeout: float = DEFAULT_REQUEST_TIMEOUT,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._external_client = client is not None
        self._client = client or httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    async def __aenter__(self) -> OpenCodeClient:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client if created internally."""
        if not self._external_client:
            await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> httpx.Response:
        """Execute an HTTP request with structured error handling."""
        req_timeout = timeout if timeout is not None else self.timeout
        try:
            response = await self._client.request(
                method,
                path,
                params=params,
                json=json_body,
                timeout=req_timeout,
            )
            response.raise_for_status()
            return response
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise OpenCodeConnectionError(
                f"OpenCode server is not reachable at {self.base_url}: {exc}",
                server_url=self.base_url,
            ) from exc
        except httpx.TimeoutException as exc:
            raise OpenCodeTimeoutError(
                f"Request to OpenCode timed out after {req_timeout}s: {exc}",
                timeout_seconds=req_timeout,
            ) from exc
        except httpx.HTTPStatusError as exc:
            text = exc.response.text if exc.response is not None else ""
            status = exc.response.status_code if exc.response is not None else 500
            raise OpenCodeAPIError(
                f"OpenCode API error ({status}): {text}",
                status_code=status,
                response_body=text,
            ) from exc
        except httpx.RequestError as exc:
            raise OpenCodeError(f"HTTP request to OpenCode failed: {exc}") from exc

    async def health(self) -> OpenCodeHealth:
        """Check OpenCode server health.

        Endpoint: GET /global/health
        """
        response = await self._request("GET", "/global/health")
        try:
            data = response.json()
            return OpenCodeHealth.model_validate(data)
        except Exception as exc:
            raise OpenCodeAPIError(
                f"Failed to parse health response: {exc}",
                status_code=response.status_code,
                response_body=response.text,
            ) from exc

    async def create_session(
        self,
        title: Optional[str] = None,
        directory: Optional[str] = None,
    ) -> OpenCodeSession:
        """Create a new OpenCode session.

        Endpoint: POST /session
        """
        params: dict[str, Any] = {}
        if directory:
            params["directory"] = directory

        body: dict[str, Any] = {}
        if title:
            body["title"] = title

        response = await self._request(
            "POST",
            "/session",
            params=params if params else None,
            json_body=body if body else None,
        )
        try:
            data = response.json()
            return OpenCodeSession.model_validate(data)
        except Exception as exc:
            raise OpenCodeAPIError(
                f"Failed to parse session creation response: {exc}",
                status_code=response.status_code,
                response_body=response.text,
            ) from exc

    async def get_session(self, session_id: str) -> OpenCodeSession:
        """Retrieve details of an existing session.

        Endpoint: GET /session/{sessionID}
        """
        response = await self._request("GET", f"/session/{session_id}")
        try:
            return OpenCodeSession.model_validate(response.json())
        except Exception as exc:
            raise OpenCodeAPIError(
                f"Failed to parse session response: {exc}",
                status_code=response.status_code,
                response_body=response.text,
            ) from exc

    async def list_sessions(self, directory: Optional[str] = None) -> list[OpenCodeSession]:
        """List sessions from OpenCode.

        Endpoint: GET /session
        """
        params = {"directory": directory} if directory else None
        response = await self._request("GET", "/session", params=params)
        try:
            data = response.json()
            items = data if isinstance(data, list) else data.get("value", [])
            return [OpenCodeSession.model_validate(item) for item in items]
        except Exception as exc:
            raise OpenCodeAPIError(
                f"Failed to parse session list: {exc}",
                status_code=response.status_code,
                response_body=response.text,
            ) from exc

    async def send_prompt_async(
        self,
        session_id: str,
        prompt: str,
        model: Optional[dict[str, str]] = None,
        agent: Optional[str] = None,
    ) -> None:
        """Send a prompt asynchronously to OpenCode.

        Endpoint: POST /session/{sessionID}/prompt_async
        """
        body: dict[str, Any] = {
            "parts": [{"type": "text", "text": prompt}],
        }
        if model:
            body["model"] = model
        if agent:
            body["agent"] = agent

        await self._request("POST", f"/session/{session_id}/prompt_async", json_body=body)

    async def send_prompt(
        self,
        session_id: str,
        prompt: str,
        model: Optional[dict[str, str]] = None,
        agent: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> OpenCodeMessage:
        """Send a prompt synchronously, waiting for completion.

        Endpoint: POST /session/{sessionID}/message
        """
        body: dict[str, Any] = {
            "parts": [{"type": "text", "text": prompt}],
        }
        if model:
            body["model"] = model
        if agent:
            body["agent"] = agent

        response = await self._request(
            "POST",
            f"/session/{session_id}/message",
            json_body=body,
            timeout=timeout,
        )
        try:
            return OpenCodeMessage.model_validate(response.json())
        except Exception as exc:
            raise OpenCodeAPIError(
                f"Failed to parse prompt response: {exc}",
                status_code=response.status_code,
                response_body=response.text,
            ) from exc

    async def get_status(self) -> dict[str, OpenCodeSessionStatus]:
        """Get the execution status of all sessions.

        Endpoint: GET /session/status
        Response mapping: { "<sessionID>": { "type": "busy" | "idle" | ... } }
        """
        response = await self._request("GET", "/session/status")
        try:
            data = response.json()
            if not isinstance(data, dict):
                return {}
            result: dict[str, OpenCodeSessionStatus] = {}
            for sid, val in data.items():
                if isinstance(val, dict):
                    result[sid] = OpenCodeSessionStatus.model_validate(val)
                else:
                    result[sid] = OpenCodeSessionStatus(type=ExecutionStatus(str(val)))
            return result
        except Exception as exc:
            raise OpenCodeAPIError(
                f"Failed to parse session status: {exc}",
                status_code=response.status_code,
                response_body=response.text,
            ) from exc

    async def get_session_status(self, session_id: str) -> ExecutionStatus:
        """Helper to get execution status for a specific session."""
        status_map = await self.get_status()
        session_status = status_map.get(session_id)
        if session_status is not None:
            return session_status.type
        return ExecutionStatus.IDLE

    async def get_messages(self, session_id: str, limit: Optional[int] = None) -> list[OpenCodeMessage]:
        """Retrieve message history for a session.

        Endpoint: GET /session/{sessionID}/message
        """
        params = {"limit": limit} if limit is not None else None
        response = await self._request("GET", f"/session/{session_id}/message", params=params)
        try:
            data = response.json()
            items = data if isinstance(data, list) else data.get("value", [])
            return [OpenCodeMessage.model_validate(item) for item in items]
        except Exception as exc:
            raise OpenCodeAPIError(
                f"Failed to parse messages response: {exc}",
                status_code=response.status_code,
                response_body=response.text,
            ) from exc

    async def get_diff(self, session_id: str) -> list[OpenCodeDiffItem]:
        """Retrieve Git diff items resulting from session execution.

        Endpoint: GET /session/{sessionID}/diff
        """
        response = await self._request("GET", f"/session/{session_id}/diff")
        try:
            data = response.json()
            items = data if isinstance(data, list) else data.get("value", [])
            return [OpenCodeDiffItem.model_validate(item) for item in items]
        except Exception as exc:
            raise OpenCodeAPIError(
                f"Failed to parse diff response: {exc}",
                status_code=response.status_code,
                response_body=response.text,
            ) from exc

    async def abort(self, session_id: str) -> bool:
        """Abort an in-progress execution for a session.

        Endpoint: POST /session/{sessionID}/abort
        """
        response = await self._request("POST", f"/session/{session_id}/abort")
        try:
            val = response.json()
            return bool(val)
        except Exception:
            return response.is_success
