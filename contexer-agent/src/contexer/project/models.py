"""Data models for Contexer workspace projects."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field


class ProjectType(str, Enum):
    """Type of project workspace."""

    SCRATCH = "scratch"
    EXISTING = "existing"


class Project(BaseModel):
    """A target project workspace for code execution and testing."""

    name: str = Field(..., description="Human-readable project identifier")
    path: Path = Field(..., description="Absolute path to the project directory")
    project_type: ProjectType = Field(
        default=ProjectType.SCRATCH,
        description="Whether this is a scratch sandbox or existing application",
    )
    description: str = Field(default="", description="Optional description of the project")

    @property
    def is_scratch(self) -> bool:
        """Return True if this is a scratch project."""
        return self.project_type == ProjectType.SCRATCH

    def count_files(self) -> int:
        """Count files currently in this project, excluding common ignore patterns."""
        if not self.path.exists() or not self.path.is_dir():
            return 0
        ignored = {".git", ".venv", "node_modules", "__pycache__", ".next", "build", "dist"}
        count = 0
        try:
            for item in self.path.rglob("*"):
                if item.is_file() and not any(part in ignored for part in item.parts):
                    count += 1
        except Exception:
            pass
        return count
