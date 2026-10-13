"""Repository and project context inspector for Contexer."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class RepositoryContext(BaseModel):
    """Detailed structural understanding of a target project."""

    project_name: str
    project_path: str
    framework: str = "Unknown"
    entry_points: list[str] = Field(default_factory=list)
    key_files: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    scripts: dict[str, str] = Field(default_factory=dict)
    summary: str = ""
    # True when the project has no server-side runtime (no package.json or
    # Python project files) and can be served as plain files.
    is_static_site: bool = False
    # Bounded excerpt of front-end entry points, so acceptance checks can
    # locate elements an existing app creates dynamically.
    source_excerpt: str = ""

    def format_summary(self) -> str:
        """Format context into concise summary string for LLM prompts."""
        files_str = ", ".join(self.key_files[:10]) if self.key_files else "Empty project"
        entry_str = ", ".join(self.entry_points) if self.entry_points else "None detected"
        deps_str = ", ".join(self.dependencies[:8]) if self.dependencies else "None"
        return (
            f"Project: {self.project_name}\n"
            f"Framework: {self.framework}\n"
            f"Key Entrypoints: {entry_str}\n"
            f"Files: {files_str}\n"
            f"Dependencies: {deps_str}"
        )


class RepositoryInspector:
    """Inspects target workspace to understand framework, layout, and entrypoints."""

    def inspect(self, project_path: str | Path) -> RepositoryContext:
        """Analyze a project directory and return structured context."""
        path = Path(project_path).resolve()
        name = path.name

        framework = "Vanilla Web (HTML/CSS/JS)"
        entry_points: list[str] = []
        key_files: list[str] = []
        dependencies: list[str] = []
        scripts: dict[str, str] = {}

        if not path.exists() or not path.is_dir():
            return RepositoryContext(
                project_name=name,
                project_path=str(path),
                framework="New Empty Project",
                summary="Empty directory ready for new project initialization.",
                is_static_site=True,
            )

        # 1. Check Node.js / JavaScript projects
        pkg_json = path / "package.json"
        if pkg_json.exists():
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8"))
                deps = list(data.get("dependencies", {}).keys())
                dev_deps = list(data.get("devDependencies", {}).keys())
                all_deps = deps + dev_deps
                dependencies = all_deps[:15]
                scripts = {k: str(v) for k, v in data.get("scripts", {}).items()}

                if "next" in all_deps or (path / "next.config.js").exists() or (path / "next.config.mjs").exists() or (path / "next.config.ts").exists():
                    framework = "Next.js"
                elif "vite" in all_deps:
                    framework = "Vite"
                elif "react" in all_deps:
                    framework = "React"
                elif "vue" in all_deps:
                    framework = "Vue.js"
                elif "svelte" in all_deps or "@sveltejs/kit" in all_deps:
                    framework = "Svelte"
                else:
                    framework = "Node.js"
            except Exception as e:
                logger.debug("Failed to parse package.json: %e", e)

        # 2. Check Python projects
        pyproject = path / "pyproject.toml"
        reqs = path / "requirements.txt"
        is_static_site = not (pkg_json.exists() or pyproject.exists() or reqs.exists() or (path / "manage.py").exists())
        if pyproject.exists() or reqs.exists():
            text = ""
            if pyproject.exists():
                try:
                    text += pyproject.read_text(encoding="utf-8").lower()
                except Exception:
                    pass
            if reqs.exists():
                try:
                    text += reqs.read_text(encoding="utf-8").lower()
                except Exception:
                    pass

            if "fastapi" in text:
                framework = "FastAPI (Python)"
            elif "flask" in text:
                framework = "Flask (Python)"
            elif "django" in text:
                framework = "Django (Python)"
            elif not pkg_json.exists():
                framework = "Python"

        # 3. Detect Entrypoints
        candidate_entries = [
            "src/app/page.tsx",
            "src/app/page.js",
            "app/page.tsx",
            "pages/index.tsx",
            "pages/index.js",
            "src/App.tsx",
            "src/App.jsx",
            "src/main.tsx",
            "src/main.js",
            "index.html",
            "main.py",
            "app.py",
            "server.py",
        ]
        for candidate in candidate_entries:
            if (path / candidate).exists():
                entry_points.append(candidate)

        # 4. Enumerate key files
        ignored = {".git", ".venv", "node_modules", ".next", "__pycache__", "build", "dist"}
        for item in sorted(path.rglob("*")):
            if item.is_file() and not any(p in ignored for p in item.parts):
                try:
                    rel = str(item.relative_to(path)).replace("\\", "/")
                    key_files.append(rel)
                except Exception:
                    pass
            if len(key_files) >= 50:
                break

        summary = (
            f"{framework} project at {path.name} with {len(key_files)} files. "
            f"Entrypoints: {', '.join(entry_points) if entry_points else 'None'}."
        )

        return RepositoryContext(
            project_name=name,
            project_path=str(path),
            framework=framework,
            entry_points=entry_points,
            key_files=key_files,
            dependencies=dependencies,
            scripts=scripts,
            summary=summary,
            is_static_site=is_static_site,
            source_excerpt=_source_excerpt(path, entry_points, key_files),
        )


SOURCE_EXCERPT_MAX_CHARS = 8000
_FRONTEND_SUFFIXES = {".html", ".js", ".mjs", ".jsx", ".ts", ".tsx", ".vue", ".svelte"}


def _source_excerpt(root: Path, entry_points: list[str], key_files: list[str]) -> str:
    """Entry points first, then other front-end files, within a fixed character budget."""
    candidates = entry_points + [
        f for f in key_files if not f.endswith(".d.ts") and ".config." not in Path(f).name
    ]
    parts: list[str] = []
    used = 0
    for rel in dict.fromkeys(candidates):
        if Path(rel).suffix not in _FRONTEND_SUFFIXES:
            continue
        budget = SOURCE_EXCERPT_MAX_CHARS - used
        if budget < 200:
            break
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        chunk = text if len(text) <= budget else text[:budget] + "\n... (truncated)"
        parts.append(f"--- {rel} ---\n{chunk}")
        used += len(chunk)
    return "\n".join(parts)
