"""Pydantic schemas and metadata dataclasses for Contexer tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Filesystem Tool Input Schemas
# ---------------------------------------------------------------------------


class ListDirectoryArgs(BaseModel):
    """Arguments for listing directory contents."""

    model_config = ConfigDict(extra="ignore")

    path: str = Field(
        default=".",
        description="Relative path inside the workspace to inspect. Defaults to root ('.').",
    )


class ReadFileArgs(BaseModel):
    """Arguments for reading a file from the workspace."""

    model_config = ConfigDict(extra="ignore")

    path: str = Field(
        ...,
        description="Relative path to the file within the workspace.",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Line number offset to start reading from (0-indexed). Defaults to 0.",
    )
    limit: int = Field(
        default=500,
        ge=1,
        le=5000,
        description="Maximum number of lines to read. Defaults to 500.",
    )


class WriteFileArgs(BaseModel):
    """Arguments for writing content to a file in the workspace."""

    model_config = ConfigDict(extra="ignore")

    path: str = Field(
        ...,
        description="Relative path to the file within the workspace.",
    )
    content: str = Field(
        ...,
        description="Text content to write into the file.",
    )


class SearchFilesArgs(BaseModel):
    """Arguments for searching file contents across the workspace."""

    model_config = ConfigDict(extra="ignore")

    pattern: str = Field(
        ...,
        description="Keyword, substring, or regular expression pattern to search for.",
    )
    path: str = Field(
        default=".",
        description="Relative directory path to search within. Defaults to workspace root ('.').",
    )


class FileExistsArgs(BaseModel):
    """Arguments for checking if a file or directory exists."""

    model_config = ConfigDict(extra="ignore")

    path: str = Field(
        ...,
        description="Relative path to check for existence.",
    )


# ---------------------------------------------------------------------------
# Terminal Tool Input Schemas
# ---------------------------------------------------------------------------


class ExecuteCommandArgs(BaseModel):
    """Arguments for executing a shell command in the repository root."""

    model_config = ConfigDict(extra="ignore")

    command: str = Field(
        ...,
        description="Shell command line to execute from the workspace root.",
    )
    timeout: int = Field(
        default=60,
        ge=1,
        le=300,
        description="Maximum execution time in seconds before terminating. Defaults to 60s.",
    )


# ---------------------------------------------------------------------------
# Git Tool Input Schemas (Read-only)
# ---------------------------------------------------------------------------


class GitStatusArgs(BaseModel):
    """Arguments for retrieving the repository git status."""

    model_config = ConfigDict(extra="ignore")


class GitDiffArgs(BaseModel):
    """Arguments for viewing git diff."""

    model_config = ConfigDict(extra="ignore")

    cached: bool = Field(
        default=False,
        description="If True, shows staged changes (--cached). Otherwise unstaged changes.",
    )
    path: Optional[str] = Field(
        default=None,
        description="Optional relative file path to limit the diff to.",
    )


class GitLogArgs(BaseModel):
    """Arguments for viewing git commit history."""

    model_config = ConfigDict(extra="ignore")

    max_count: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of commits to display. Defaults to 10.",
    )


class GitBranchArgs(BaseModel):
    """Arguments for listing git branches."""

    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Tool contract (imported from contexer.tools.base)
# ---------------------------------------------------------------------------

from contexer.tools.base import (
    BaseTool,
    FileDiff,
    Tool,
    ToolConfirmation,
    ToolInvocation,
    ToolKind,
    ToolResult,
)

__all__ = [
    "ListDirectoryArgs",
    "ReadFileArgs",
    "WriteFileArgs",
    "SearchFilesArgs",
    "FileExistsArgs",
    "ExecuteCommandArgs",
    "GitStatusArgs",
    "GitDiffArgs",
    "GitLogArgs",
    "GitBranchArgs",
    "ToolKind",
    "ToolResult",
    "Tool",
    "ToolConfirmation",
    "ToolInvocation",
    "FileDiff",
    "BaseTool",
]

