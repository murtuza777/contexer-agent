"""Structured exceptions for OpenCode integration."""

from __future__ import annotations

from typing import Optional


class OpenCodeError(Exception):
    """Base exception for all OpenCode operations."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class OpenCodeConnectionError(OpenCodeError):
    """Raised when connecting to OpenCode server fails."""

    def __init__(self, message: str, server_url: str) -> None:
        super().__init__(message)
        self.server_url = server_url


class OpenCodeTimeoutError(OpenCodeError):
    """Raised when an operation or prompt execution times out."""

    def __init__(self, message: str, timeout_seconds: float) -> None:
        super().__init__(message)
        self.timeout_seconds = timeout_seconds


class OpenCodeAPIError(OpenCodeError):
    """Raised when OpenCode server returns an HTTP error."""

    def __init__(self, message: str, status_code: int, response_body: Optional[str] = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class OpenCodeExecutionError(OpenCodeError):
    """Raised when OpenCode execution fails during task execution."""

    def __init__(self, message: str, error_name: Optional[str] = None) -> None:
        super().__init__(message)
        self.error_name = error_name


class OpenCodeAbortError(OpenCodeError):
    """Raised when an execution is aborted."""
