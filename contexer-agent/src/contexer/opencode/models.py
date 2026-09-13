"""Data models for OpenCode integration, matching the verified API schemas."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

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
    updated: Optional[int] = None


class OpenCodeSession(BaseModel):
    """An OpenCode session."""

    model_config = ConfigDict(extra="ignore")

    id: str
    slug: Optional[str] = None
    version: Optional[str] = None
    projectID: Optional[str] = None
    directory: Optional[str] = None
    title: Optional[str] = None
    time: Optional[OpenCodeSessionTime] = None


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
    status: Optional[str] = None


class OpenCodePart(BaseModel):
    """A part of an OpenCode message."""

    model_config = ConfigDict(extra="ignore")

    type: str
    text: Optional[str] = None
    id: Optional[str] = None
    callID: Optional[str] = None
    tool: Optional[str] = None
    time: Optional[dict[str, Any]] = None
    state: Optional[dict[str, Any]] = None


class OpenCodeMessageInfo(BaseModel):
    """Metadata for an OpenCode message."""

    model_config = ConfigDict(extra="ignore")

    id: str
    sessionID: Optional[str] = None
    role: str
    agent: Optional[str] = None
    time: Optional[dict[str, Any]] = None
    error: Optional[dict[str, Any]] = None
    finish: Optional[str] = None


class OpenCodeMessage(BaseModel):
    """An OpenCode message object."""

    model_config = ConfigDict(extra="ignore")

    info: OpenCodeMessageInfo
    parts: list[OpenCodePart] = Field(default_factory=list)


class OpenCodeHealth(BaseModel):
    """Health status response from /global/health."""

    model_config = ConfigDict(extra="ignore")

    healthy: bool
    version: Optional[str] = None


class OpenCodeExecutionResult(BaseModel):
    """Structured result of a prompt execution sent to OpenCode."""

    model_config = ConfigDict(extra="ignore")

    session_id: str
    status: ExecutionStatus
    diff: list[OpenCodeDiffItem] = Field(default_factory=list)
    response_text: str = ""
    error: Optional[str] = None
    duration_seconds: float = 0.0
