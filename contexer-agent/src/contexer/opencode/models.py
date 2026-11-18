"""Data models for OpenCode integration, matching the verified API schemas."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExecutionStatus(str, Enum):
    """Execution state of an OpenCode session."""

    IDLE = "idle"
    BUSY = "busy"
    RETRY = "retry"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"
    UNKNOWN = "unknown"


class OpenCodeSessionTime(BaseModel):
    """Timestamps for an OpenCode session."""

    model_config = ConfigDict(extra="ignore")

    created: int
    updated: int | None = None


class OpenCodeSession(BaseModel):
    """An OpenCode session."""

    model_config = ConfigDict(extra="ignore")

    id: str
    slug: str | None = None
    version: str | None = None
    projectID: str | None = None
    directory: str | None = None
    title: str | None = None
    time: OpenCodeSessionTime | None = None


class OpenCodeSessionStatus(BaseModel):
    """Session status returned by OpenCode /session/status."""

    model_config = ConfigDict(extra="ignore")

    type: ExecutionStatus = ExecutionStatus.UNKNOWN


class OpenCodeDiffItem(BaseModel):
    """Diff entry for a single modified/created/deleted file."""

    model_config = ConfigDict(extra="ignore")

    file: str
    patch: str
    additions: int = 0
    deletions: int = 0
    status: str | None = None


class OpenCodePart(BaseModel):
    """A part of an OpenCode message."""

    model_config = ConfigDict(extra="ignore")

    type: str
    text: str | None = None
    id: str | None = None
    callID: str | None = None
    tool: str | None = None
    time: dict[str, Any] | None = None
    state: dict[str, Any] | None = None


class OpenCodeMessageInfo(BaseModel):
    """Metadata for an OpenCode message."""

    model_config = ConfigDict(extra="ignore")

    id: str
    sessionID: str | None = None
    role: str
    agent: str | None = None
    time: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    finish: str | None = None


class OpenCodeMessage(BaseModel):
    """An OpenCode message object."""

    model_config = ConfigDict(extra="ignore")

    info: OpenCodeMessageInfo
    parts: list[OpenCodePart] = Field(default_factory=list)


class OpenCodeHealth(BaseModel):
    """Health status response from /global/health."""

    model_config = ConfigDict(extra="ignore")

    healthy: bool
    version: str | None = None


class OpenCodeExecutionResult(BaseModel):
    """Structured result of a prompt execution sent to OpenCode."""

    model_config = ConfigDict(extra="ignore")

    session_id: str
    status: ExecutionStatus
    diff: list[OpenCodeDiffItem] = Field(default_factory=list)
    response_text: str = ""
    error: str | None = None
    duration_seconds: float = 0.0
