"""Unit tests for terminal command execution tool."""

from pathlib import Path
import sys
from unittest.mock import patch

import pytest

from contexer.tools.terminal import execute_command


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "term_workspace"
    ws.mkdir()
    (ws / "indicator.txt").write_text("workspace_indicator", encoding="utf-8")
    return ws


class TestTerminalTool:
    """execute_command execution, exit codes, limits, and sanitization."""

    def test_successful_command(self, workspace: Path) -> None:
        cmd = f'"{sys.executable}" -c "print(\'terminal_test_success\')"'
        result = execute_command(workspace, cmd)
        assert "Exit code: 0" in result
        assert "STDOUT:" in result
        assert "terminal_test_success" in result

    def test_failed_command_returns_nonzero_exit_code(self, workspace: Path) -> None:
        cmd = f'"{sys.executable}" -c "import sys; sys.exit(42)"'
        result = execute_command(workspace, cmd)
        assert "Exit code: 42" in result

    def test_empty_command(self, workspace: Path) -> None:
        result = execute_command(workspace, "   ")
        assert "Error: Command cannot be empty." in result

    def test_timeout_command(self, workspace: Path) -> None:
        cmd = f'"{sys.executable}" -c "import time; time.sleep(5)"'
        result = execute_command(workspace, cmd, timeout=1)
        assert "timed out after 1 seconds" in result

    def test_execution_from_workspace_root(self, workspace: Path) -> None:
        # Check that os.getcwd() matches the workspace directory
        cmd = f'"{sys.executable}" -c "from pathlib import Path; print(Path(\'indicator.txt\').exists())"'
        result = execute_command(workspace, cmd)
        assert "Exit code: 0" in result
        assert "True" in result

    def test_command_output_sanitization(self, workspace: Path) -> None:
        # Output contains a fake Google API key
        fake_key = "AIzaSyD9xK31415926535897932384626433832"
        cmd = f'"{sys.executable}" -c "print(\'{fake_key}\')"'
        result = execute_command(workspace, cmd)
        assert fake_key not in result
        assert "AIza...[MASKED]" in result

    def test_oversized_output_truncated(self, workspace: Path) -> None:
        # Generate 30,000 characters
        cmd = f'"{sys.executable}" -c "print(\'A\' * 30000)"'
        result = execute_command(workspace, cmd)
        assert "stdout truncated: output exceeded size limit" in result
        # Check head and tail are present
        assert result.startswith("Exit code: 0")

    def test_long_lived_server_blocked(self, workspace: Path) -> None:
        cmd = "npm run dev"
        result = execute_command(workspace, cmd)
        assert "Blocked:" in result
        assert "persistent server" in result

    def test_background_operator_blocked(self, workspace: Path) -> None:
        cmd = "pytest &"
        result = execute_command(workspace, cmd)
        assert "Blocked:" in result
        assert "background operators" in result

    def test_help_or_version_not_blocked(self, workspace: Path) -> None:
        cmd = f'"{sys.executable}" --version'
        result = execute_command(workspace, cmd)
        assert "Exit code: 0" in result
        assert "Python" in result

    def test_ansi_escape_stripped(self, workspace: Path) -> None:
        cmd = f'"{sys.executable}" -c "print(\'\\033[32mCOLOR_GREEN\\033[0m\')"'
        result = execute_command(workspace, cmd)
        assert "\033[32m" not in result
        assert "COLOR_GREEN" in result

    def test_exit_code_informational_diff_note(self, workspace: Path) -> None:
        # diff returning exit code 1
        with patch("contexer.tools.terminal.subprocess.run") as mock_run:
            from unittest.mock import MagicMock
            mock_proc = MagicMock(returncode=1, stdout="--- a\n+++ b", stderr="")
            mock_run.return_value = mock_proc
            result = execute_command(workspace, "diff file1 file2")
            assert "Note: Files differ (expected, not an error)" in result

    def test_exit_code_signal_note(self, workspace: Path) -> None:
        # 137 (128 + 9) SIGKILL OOM killer note
        with patch("contexer.tools.terminal.subprocess.run") as mock_run:
            from unittest.mock import MagicMock
            mock_proc = MagicMock(returncode=137, stdout="", stderr="Killed")
            mock_run.return_value = mock_proc
            result = execute_command(workspace, "my_binary")
            assert "SIGKILL" in result
