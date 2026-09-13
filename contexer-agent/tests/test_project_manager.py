"""Tests for Contexer ProjectManager and workspace isolation."""

import pytest
from pathlib import Path
from contexer.project.manager import ProjectManager
from contexer.project.models import Project, ProjectType


def test_project_manager_default_sandbox(tmp_path: Path):
    """ProjectManager should initialize a default sandbox directory."""
    mgr = ProjectManager(workspace_root=tmp_path)
    active = mgr.active_project
    assert active.name == "sandbox"
    assert active.project_type == ProjectType.SCRATCH
    assert active.path == tmp_path / "sandbox"
    assert active.path.exists()
    assert active.is_scratch is True


def test_project_manager_protects_contexer_agent(tmp_path: Path):
    """ProjectManager must refuse to target the Contexer agent itself."""
    agent_dir = tmp_path / "contexer-agent"
    (agent_dir / "src" / "contexer").mkdir(parents=True)
    mgr = ProjectManager(workspace_root=tmp_path)

    with pytest.raises(ValueError, match="Protected Contexer agent repository"):
        mgr.set_active_project(agent_dir)


def test_project_manager_list_projects(tmp_path: Path):
    """ProjectManager should discover existing applications and sandboxes."""
    # Create website folder
    web_dir = tmp_path / "website"
    web_dir.mkdir()
    (web_dir / "package.json").write_text('{"name": "test-web"}')

    mgr = ProjectManager(workspace_root=tmp_path)
    projects = mgr.list_projects()
    names = [p.name for p in projects]

    assert "sandbox" in names
    assert "website" in names


def test_project_manager_set_active_project(tmp_path: Path):
    """ProjectManager switches active project by name or path."""
    app_dir = tmp_path / "my_app"
    app_dir.mkdir()

    mgr = ProjectManager(workspace_root=tmp_path)
    proj = mgr.set_active_project("my_app")

    assert proj.name == "my_app"
    assert proj.path == app_dir
    assert mgr.active_project == proj


def test_project_manager_create_scratch(tmp_path: Path):
    """ProjectManager can create a new scratch sandbox."""
    mgr = ProjectManager(workspace_root=tmp_path)
    proj = mgr.create_scratch_project("demo_box")

    assert proj.name == "demo_box"
    assert proj.project_type == ProjectType.SCRATCH
    assert proj.path.exists()
    assert mgr.active_project.name == "demo_box"


def test_project_manager_reset_to_default(tmp_path: Path):
    """ProjectManager can reset back to default sandbox."""
    mgr = ProjectManager(workspace_root=tmp_path)
    mgr.create_scratch_project("demo_box")
    assert mgr.active_project.name == "demo_box"

    reset_proj = mgr.reset_to_default()
    assert reset_proj.name == "sandbox"
    assert mgr.active_project.name == "sandbox"


def test_project_manager_format_scope_prompt(tmp_path: Path):
    """ProjectManager generates workspace boundary instructions for OpenCode."""
    mgr = ProjectManager(workspace_root=tmp_path)
    prompt = mgr.format_scope_prompt()

    assert "TARGET PROJECT WORKSPACE" in prompt
    assert "sandbox" in prompt
    assert "CRITICAL WORKSPACE ISOLATION RULES" in prompt
