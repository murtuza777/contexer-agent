"""`contexer init` prepares a project and optionally writes the gate workflow."""

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from contexer.cli import app


def test_init_node_project_with_ci_writes_a_valid_workflow(tmp_path: Path) -> None:
    web = tmp_path / "apps" / "web"
    web.mkdir(parents=True)
    (web / "package.json").write_text(json.dumps({"scripts": {"dev": "vite"}, "devDependencies": {"vite": "6"}}))
    result = CliRunner().invoke(app, ["init", "--dir", str(web), "--ci", "--repo-root", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (web / ".contexer" / ".gitignore").exists()
    assert "vite" in result.output

    workflow = yaml.safe_load((tmp_path / ".github" / "workflows" / "contexer.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["gate"]["steps"]
    assert steps[-1]["uses"] == "murtuza777/contexer-agent@main"
    assert steps[-1]["with"]["working-directory"] == "apps/web"
    assert any(s.get("run") == "npm ci" for s in steps)
    assert workflow["permissions"]["statuses"] == "write"


def test_init_static_site_needs_no_node_setup(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<h1>hi</h1>")
    result = CliRunner().invoke(app, ["init", "--dir", str(tmp_path), "--ci", "--repo-root", str(tmp_path)])
    assert result.exit_code == 0, result.output
    text = (tmp_path / ".github" / "workflows" / "contexer.yml").read_text(encoding="utf-8")
    assert "setup-node" not in text and "working-directory: ." in text


def test_init_unknown_stack_writes_a_config_template(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'api'\n")
    result = CliRunner().invoke(app, ["init", "--dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "[app]" in (tmp_path / "contexer.toml").read_text(encoding="utf-8")


def test_init_writes_the_issue_workflow(tmp_path: Path) -> None:
    import yaml

    project = tmp_path / "apps" / "web"
    project.mkdir(parents=True)
    (project / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
    result = CliRunner().invoke(app, ["init", "--dir", str(project), "--repo-root", str(tmp_path), "--issues"])
    assert result.exit_code == 0, result.output
    workflow = yaml.safe_load((tmp_path / ".github" / "workflows" / "contexer-issues.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["contexer"]
    assert "author_association" in job["if"]  # strangers' comments never start a job
    assert job["steps"][0]["with"]["persist-credentials"] is False  # the agent finds no token in .git/config
    assert job["steps"][1]["with"]["working-directory"] == "apps/web"
    assert workflow["concurrency"]["group"] == "contexer-issue-${{ github.event.issue.number }}"
    assert not (tmp_path / ".github" / "workflows" / "contexer.yml").exists()
