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
