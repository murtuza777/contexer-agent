"""Base tool classes and data contracts for Contexer agent harness.

Adapted from AgentForge (MIT License, Copyright (c) 2026 Mohit Goyal).
Provides schema-first tool execution primitives, result containers, and safety contracts.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
import difflib
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field


class ToolKind(str, Enum):
    """The action classification for tool security boundaries."""

    READ = "read"
    WRITE = "write"
    SHELL = "shell"
    GIT = "git"


@dataclass
class FileDiff:
    """Represents a text difference for file modifications."""

    path: Path
    old_content: str
    new_content: str
    is_new_file: bool = False
    is_deletion: bool = False

    def to_diff(self) -> str:
        old_lines = self.old_content.splitlines(keepends=True)
        new_lines = self.new_content.splitlines(keepends=True)

        if old_lines and not old_lines[-1].endswith("\n"):
            old_lines[-1] = "\n"
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"

        old_name = "/dev/null" if self.is_new_file else str(self.path)
        new_name = "/dev/null" if self.is_deletion else str(self.path)

        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=old_name,
            tofile=new_name,
        )
        return "".join(diff)


class ToolInvocation(BaseModel):
    """Encapsulates a tool invocation with params and working directory."""

    params: dict[str, Any] = Field(default_factory=dict)
    cwd: Path = Field(default_factory=Path.cwd)


@dataclass
class ToolConfirmation:
    """Record passed to ApprovalManager or UI for confirmation."""

    tool_name: str
    description: str
    affected_paths: tuple[Path, ...] = ()
    command: Optional[str] = None
    diff: Optional[FileDiff] = None
    diff_text: Optional[str] = None
    is_dangerous: bool = False

    def get_diff_text(self) -> Optional[str]:
        if self.diff:
            return self.diff.to_diff()
        return self.diff_text


@dataclass(frozen=True)
class ToolResult:
    """Structured outcome returned by tool execution."""

    success: bool
    output: str
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    summary: Optional[str] = None
    diff_text: Optional[str] = None
    exit_code: Optional[int] = None
    recovery_hint: Optional[str] = None

    @classmethod
    def error_result(cls, error: str, output: str = "", **kwargs: Any) -> "ToolResult":
        kwargs.setdefault("summary", error)
        return cls(success=False, output=output, error=error, **kwargs)

    @classmethod
    def success_result(cls, output: str, **kwargs: Any) -> "ToolResult":
        return cls(success=True, output=output, error=None, **kwargs)

    def to_model_output(self) -> str:
        if self.success:
            return self.output
        if self.output and self.error:
            return f"Error: {self.error}\n{self.output}"
        if self.output:
            return self.output
        return f"Error: {self.error or 'Unknown error'}"


@dataclass
class Tool:
    """A schema-first tool in the Contexer agent harness."""

    name: str
    description: str
    args_schema: type[BaseModel]
    handler: Callable[..., Any]
    kind: ToolKind = ToolKind.READ
    parameters_schema: Optional[dict[str, Any]] = None

    def is_mutating(self) -> bool:
        """Return whether this tool can change workspace or process state."""
        return self.kind in {ToolKind.WRITE, ToolKind.SHELL}

    def confirmation(self, args: dict[str, Any]) -> ToolConfirmation:
        """Create a minimal review record without exposing large contents."""
        affected_paths: tuple[Path, ...] = ()
        raw_path = args.get("path")
        if isinstance(raw_path, str) and raw_path.strip():
            affected_paths = (Path(raw_path),)
        command = args.get("command") if self.kind is ToolKind.SHELL else None
        return ToolConfirmation(
            tool_name=self.name,
            description=f"Run {self.name}",
            affected_paths=affected_paths,
            command=command if isinstance(command, str) else None,
        )

    def to_tool_declaration(self) -> dict[str, Any]:
        """Convert this tool into an OpenAI-compatible function tool schema."""
        schema = (
            self.parameters_schema
            if self.parameters_schema is not None
            else self.args_schema.model_json_schema()
        )
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema,
            },
        }

    def to_openai_tool(self) -> dict[str, Any]:
        """Alias for to_tool_declaration."""
        return self.to_tool_declaration()


class BaseTool(abc.ABC):
    """Abstract base class for object-oriented tool implementations if needed."""

    name: str = "base_tool"
    description: str = "Base tool description"
    kind: ToolKind = ToolKind.READ

    @property
    @abc.abstractmethod
    def schema(self) -> type[BaseModel]:
        """Return the Pydantic schema class for tool arguments."""
        ...

    @abc.abstractmethod
    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        """Execute the tool with the given invocation."""
        ...
