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


def test_a_folder_without_a_page_is_not_a_static_site(tmp_path) -> None:
    """A bare main.py is an app Contexer must be told how to start, not files to serve."""
    from contexer.workflow.inspector import RepositoryInspector

    (tmp_path / "main.py").write_text("print('hi')\n", encoding="utf-8")
    assert RepositoryInspector().inspect(tmp_path).is_static_site is False
    (tmp_path / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
    assert RepositoryInspector().inspect(tmp_path).is_static_site is True


def test_the_file_list_is_the_projects_own_files_not_contexers_or_its_dependencies(tmp_path: Path) -> None:
    # After a few runs .contexer/runs holds hundreds of files, and they sort before src/. The list is what the
    # Intent agent and the coding agent are shown as the project's files.
    (tmp_path / "index.html").write_text("<h1>App</h1>", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.js").write_text("let a = 1;", encoding="utf-8")
    for n in range(80):
        run = tmp_path / ".contexer" / "runs" / f"run-{n:03}"
        run.mkdir(parents=True)
        (run / "run.json").write_text("{}", encoding="utf-8")
    deep = tmp_path / "node_modules" / "pkg"
    deep.mkdir(parents=True)
    (deep / "index.js").write_text("", encoding="utf-8")

    files = RepositoryInspector().inspect(tmp_path).key_files
    assert files == ["index.html", "src/app.js"]
