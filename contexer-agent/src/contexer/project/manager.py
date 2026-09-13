"""Project workspace manager for Contexer."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from contexer.project.models import Project, ProjectType

logger = logging.getLogger(__name__)

# Directory names that should never be targeted as user application projects
PROTECTED_DIR_NAMES = {"contexer-agent", "src", "tests", ".git", ".venv", ".agents"}


class ProjectManager:
    """Manages user target projects and scratch sandboxes."""

    def __init__(
        self,
        workspace_root: Optional[Path] = None,
        default_sandbox_name: str = "sandbox",
    ) -> None:
        if workspace_root is None:
            # If current working directory is inside contexer-agent, step up to workspace root
            cwd = Path.cwd().resolve()
            if cwd.name == "contexer-agent" or (cwd / "src" / "contexer").exists():
                workspace_root = cwd.parent
            else:
                workspace_root = cwd
        self.workspace_root = workspace_root.resolve()
        self.default_sandbox_name = default_sandbox_name

        # Initialize active project to default scratch sandbox
        self._active_project = self._init_default_sandbox()

    @property
    def active_project(self) -> Project:
        """Return the currently active project."""
        return self._active_project

    def _init_default_sandbox(self) -> Project:
        """Ensure default sandbox folder exists and return as active project."""
        sandbox_path = self.workspace_root / self.default_sandbox_name
        sandbox_path.mkdir(parents=True, exist_ok=True)
        return Project(
            name=self.default_sandbox_name,
            path=sandbox_path,
            project_type=ProjectType.SCRATCH,
            description="Default isolated scratch sandbox for rapid prototyping",
        )

    def is_protected(self, path: Path) -> bool:
        """Check if a path is part of the Contexer agent itself."""
        resolved = path.resolve()
        # Direct check for contexer-agent directory or src/contexer
        if resolved.name == "contexer-agent" or (resolved / "src" / "contexer").exists():
            return True
        # Check if resolved path is inside contexer-agent
        for parent in [resolved, *resolved.parents]:
            if parent.name == "contexer-agent" and (parent / "src" / "contexer").exists():
                return True
        return False

    def list_projects(self) -> list[Project]:
        """Scan workspace root for candidate projects."""
        projects: list[Project] = [self.active_project]
        seen_paths = {self.active_project.path.resolve()}

        if not self.workspace_root.exists() or not self.workspace_root.is_dir():
            return projects

        for item in self.workspace_root.iterdir():
            if not item.is_dir():
                continue
            resolved = item.resolve()
            if resolved in seen_paths or self.is_protected(resolved):
                continue
            if item.name.startswith((".", "_")) or item.name in {"node_modules", "dist", "build"}:
                continue

            # Check project type
            is_scratch = item.name == self.default_sandbox_name or item.name.startswith("sandbox")
            ptype = ProjectType.SCRATCH if is_scratch else ProjectType.EXISTING
            desc = "Scratch sandbox" if is_scratch else "Existing application project"

            if (item / "package.json").exists():
                desc = "Node.js / Web application"
            elif (item / "pyproject.toml").exists() or (item / "requirements.txt").exists():
                desc = "Python application"

            projects.append(
                Project(
                    name=item.name,
                    path=resolved,
                    project_type=ptype,
                    description=desc,
                )
            )
            seen_paths.add(resolved)

        return projects

    def set_active_project(self, name_or_path: str | Path) -> Project:
        """Switch the active project by name or path."""
        target: Path
        if isinstance(name_or_path, str):
            # Check if matching known project name
            candidate = self.workspace_root / name_or_path
            if candidate.exists() and candidate.is_dir():
                target = candidate
            else:
                # Try relative to cwd or absolute path
                target = Path(name_or_path).resolve()
        else:
            target = name_or_path.resolve()

        if self.is_protected(target):
            raise ValueError(
                f"Cannot target '{target.name}': Protected Contexer agent repository. "
                "Please choose a scratch project ('sandbox') or an application project (e.g. 'website')."
            )

        if not target.exists() or not target.is_dir():
            raise FileNotFoundError(f"Project directory does not exist: {target}")

        is_scratch = target.name == self.default_sandbox_name or target.name.startswith("sandbox")
        ptype = ProjectType.SCRATCH if is_scratch else ProjectType.EXISTING
        desc = "Scratch sandbox" if is_scratch else "Existing project"

        self._active_project = Project(
            name=target.name,
            path=target,
            project_type=ptype,
            description=desc,
        )
        return self._active_project

    def create_scratch_project(self, name: str) -> Project:
        """Create a new scratch project directory and set it as active."""
        clean_name = name.strip().replace(" ", "_")
        target = (self.workspace_root / clean_name).resolve()

        if self.is_protected(target):
            raise ValueError(f"Cannot create scratch project inside protected directory: {target.name}")

        target.mkdir(parents=True, exist_ok=True)
        self._active_project = Project(
            name=clean_name,
            path=target,
            project_type=ProjectType.SCRATCH,
            description=f"Custom scratch sandbox '{clean_name}'",
        )
        return self._active_project

    def reset_to_default(self) -> Project:
        """Reset active project back to the default sandbox."""
        self._active_project = self._init_default_sandbox()
        return self._active_project

    def format_scope_prompt(self, project: Optional[Project] = None) -> str:
        """Generate authoritative scoping instruction for OpenCode."""
        proj = project or self.active_project
        try:
            rel = proj.path.relative_to(self.workspace_root)
            rel_str = str(rel).replace("\\", "/")
        except ValueError:
            rel_str = str(proj.path).replace("\\", "/")

        return (
            f"=== TARGET PROJECT WORKSPACE ===\n"
            f"Target Directory: {rel_str}\n"
            f"Project Type: {proj.project_type.value.upper()}\n\n"
            f"CRITICAL WORKSPACE ISOLATION RULES:\n"
            f"1. You MUST work exclusively inside '{rel_str}/'.\n"
            f"2. All files created or modified must be placed inside '{rel_str}/' (e.g. '{rel_str}/index.html').\n"
            f"3. DO NOT create or modify any files outside '{rel_str}/' (do not touch root files or other folders).\n"
            f"================================\n"
        )
