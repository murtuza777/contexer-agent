"""The risk scan before a run (T5.1): what a coding agent's commit could leak, found before anything is spent."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from contexer.cli import app
from contexer.riskscan import scan_project

KEY = "q7Rk2ZpX9vLm" + "4TnB8sWd3Yf6"  # in two halves so no scanner takes this file for a leak


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "app"
    root.mkdir()
    (root / "index.html").write_text("<h1>hi</h1>\n", encoding="utf-8")
    git(root, "init", "--quiet", "-b", "main")
    git(root, "config", "user.name", "Dev")
    git(root, "config", "user.email", "dev@example.com")
    git(root, "add", "-A")
    git(root, "commit", "--quiet", "-m", "app")
    return root


def test_a_clean_project_has_no_risks(repo: Path) -> None:
    (repo / ".gitignore").write_text(".env\n.dev.vars\n", encoding="utf-8")
    (repo / ".env").write_text(f"API_KEY={KEY}\n", encoding="utf-8")  # ignored: where a secret belongs
    (repo / ".env.example").write_text("API_KEY=your-key-here\n", encoding="utf-8")
    assert scan_project(repo) == []


def test_an_environment_file_git_does_not_ignore_is_a_risk(repo: Path) -> None:
    (repo / ".env").write_text(f"API_KEY={KEY}\n", encoding="utf-8")
    (repo / ".dev.vars").write_text("SECRET=x\n", encoding="utf-8")
    risks = scan_project(repo)
    assert [(r.kind, r.path) for r in risks] == [("env-not-ignored", ".dev.vars"), ("env-not-ignored", ".env")]
    assert ".gitignore" in risks[0].message
    assert KEY not in " ".join(r.message for r in risks)


def test_an_environment_file_that_is_committed_says_so(repo: Path) -> None:
    (repo / ".env").write_text(f"API_KEY={KEY}\n", encoding="utf-8")
    git(repo, "add", ".env")
    git(repo, "commit", "--quiet", "-m", "oops")
    [risk] = [r for r in scan_project(repo) if r.path == ".env"]
    assert risk.kind == "env-committed" and "history" in risk.message


def test_a_secret_in_a_committed_file_is_found_and_never_repeated(repo: Path) -> None:
    (repo / "config.js").write_text(f'export const base = "/api";\nconst apiKey = "{KEY}";\n', encoding="utf-8")
    (repo / "notes.md").write_text("Use `API_KEY=your-key-here` in `.env`.\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "config")
    [risk] = scan_project(repo)
    assert (risk.kind, risk.path, risk.line) == ("secret-committed", "config.js", 2)
    assert KEY not in risk.message
    # The same line, not yet committed, is the coding agent's diff to be reviewed, not the project's history.
    (repo / "later.js").write_text(f'const token = "{KEY}";\n', encoding="utf-8")
    assert [r.path for r in scan_project(repo)] == ["config.js"]


def test_a_folder_that_is_not_a_repository_is_only_checked_for_what_needs_no_git(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("A=b\n", encoding="utf-8")
    assert scan_project(tmp_path) == []  # nothing can be committed or pushed from here


def test_the_scan_is_bounded(repo: Path) -> None:
    for n in range(40):
        (repo / f"f{n}.js").write_text(f'const apiKey = "{KEY}";\n', encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "many")
    assert len(scan_project(repo)) <= 20


def test_doctor_shows_the_risks(repo: Path) -> None:
    (repo / ".env").write_text("A=b\n", encoding="utf-8")
    result = CliRunner().invoke(app, ["doctor", "--dir", str(repo)])
    shown = "".join(result.output.split())  # the table folds long lines
    assert ".envisnotignoredbygit" in shown
