"""Unit tests for read-only Git tools."""

from pathlib import Path
import shutil
import subprocess
from unittest.mock import patch

import pytest

from contexer.tools.git import git_branch, git_diff, git_log, git_status


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Initialize a real temporary git repository."""
    repo = tmp_path / "repo"
    repo.mkdir()

    git_bin = shutil.which("git")
    if not git_bin:
        pytest.skip("git binary not available in environment")

    # Configure and init repo
    subprocess.run([git_bin, "init", "-b", "main"], cwd=repo, capture_output=True, check=True)
    subprocess.run([git_bin, "config", "user.name", "Test Agent"], cwd=repo, capture_output=True, check=True)
    subprocess.run([git_bin, "config", "user.email", "agent@contexer.ai"], cwd=repo, capture_output=True, check=True)

    # Initial commit
    (repo / "hello.txt").write_text("initial content\n", encoding="utf-8")
    subprocess.run([git_bin, "add", "hello.txt"], cwd=repo, capture_output=True, check=True)
    subprocess.run([git_bin, "commit", "-m", "Initial commit"], cwd=repo, capture_output=True, check=True)

    return repo


class TestGitTools:
    """Read-only Git tools: status, diff, log, branch."""

    def test_git_status_clean(self, git_repo: Path) -> None:
        status = git_status(git_repo)
        assert "main" in status

    def test_git_status_modified(self, git_repo: Path) -> None:
        (git_repo / "hello.txt").write_text("modified content\n", encoding="utf-8")
        status = git_status(git_repo)
        assert "hello.txt" in status
        assert "M" in status

    def test_git_diff_unstaged(self, git_repo: Path) -> None:
        (git_repo / "hello.txt").write_text("new content\n", encoding="utf-8")
        diff = git_diff(git_repo)
        assert "+new content" in diff
        assert "-initial content" in diff

    def test_git_diff_staged(self, git_repo: Path) -> None:
        git_bin = shutil.which("git")
        assert git_bin is not None
        (git_repo / "hello.txt").write_text("staged content\n", encoding="utf-8")
        subprocess.run([git_bin, "add", "hello.txt"], cwd=git_repo, capture_output=True, check=True)

        diff = git_diff(git_repo, cached=True)
        assert "+staged content" in diff

    def test_git_log(self, git_repo: Path) -> None:
        log = git_log(git_repo, max_count=5)
        assert "Initial commit" in log

    def test_git_branch(self, git_repo: Path) -> None:
        branches = git_branch(git_repo)
        assert "main" in branches

    def test_non_git_directory(self, tmp_path: Path) -> None:
        non_git = tmp_path / "not_git"
        non_git.mkdir()
        status = git_status(non_git)
        assert "Git error" in status or "not a git repository" in status

    def test_missing_git_binary(self, git_repo: Path) -> None:
        with patch("shutil.which", return_value=None):
            result = git_status(git_repo)
            assert "executable not found" in result

    def test_git_mutating_command_blocked(self, git_repo: Path) -> None:
        from contexer.tools.git import _run_git_command
        result = _run_git_command(git_repo, ["commit", "-m", "bad commit"])
        assert "Blocked:" in result
        assert "strictly read-only" in result

    def test_git_branch_deletion_blocked(self, git_repo: Path) -> None:
        from contexer.tools.git import _run_git_command
        result = _run_git_command(git_repo, ["branch", "-D", "main"])
        assert "Blocked:" in result
