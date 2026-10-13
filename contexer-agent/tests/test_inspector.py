"""Tests for RepositoryInspector."""

from pathlib import Path
from contexer.workflow.inspector import RepositoryInspector


def test_inspector_detects_vanilla_web(tmp_path: Path):
    """Inspector detects static HTML/JS/CSS project."""
    (tmp_path / "index.html").write_text("<!DOCTYPE html><html><body>Test</body></html>")
    (tmp_path / "script.js").write_text("console.log('test')")

    inspector = RepositoryInspector()
    ctx = inspector.inspect(tmp_path)

    assert "HTML" in ctx.framework
    assert "index.html" in ctx.entry_points
    assert "index.html" in ctx.key_files
    assert "script.js" in ctx.key_files


def test_inspector_detects_nextjs(tmp_path: Path):
    """Inspector detects Next.js project from package.json or config."""
    (tmp_path / "package.json").write_text('{"dependencies": {"next": "15.0.0", "react": "19.0.0"}}')
    app_dir = tmp_path / "src" / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "page.tsx").write_text("export default function Page() { return <h1>Next</h1>; }")

    inspector = RepositoryInspector()
    ctx = inspector.inspect(tmp_path)

    assert ctx.framework == "Next.js"
    assert any("page.tsx" in ep for ep in ctx.entry_points)


def test_source_excerpt_prioritises_entry_points_within_budget(tmp_path):
    from contexer.workflow.inspector import SOURCE_EXCERPT_MAX_CHARS

    (tmp_path / "index.html").write_text("<button>Add task</button>", encoding="utf-8")
    (tmp_path / "app.js").write_text("x" * (SOURCE_EXCERPT_MAX_CHARS * 2), encoding="utf-8")
    (tmp_path / "notes.md").write_text("not front-end source", encoding="utf-8")

    ctx = RepositoryInspector().inspect(tmp_path)

    assert ctx.source_excerpt.startswith("--- index.html ---\n<button>Add task</button>")
    assert "--- app.js ---" in ctx.source_excerpt and "(truncated)" in ctx.source_excerpt
    assert "notes.md" not in ctx.source_excerpt
    assert len(ctx.source_excerpt) < SOURCE_EXCERPT_MAX_CHARS + 200
    assert ctx.is_static_site is True
