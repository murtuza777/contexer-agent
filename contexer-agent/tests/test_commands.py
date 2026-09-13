"""Tests for the Contexer slash command system."""

from unittest.mock import patch
from contexer.cli.repl import ContexerApp
from contexer.cli.commands import (
    COMMANDS,
    CommandDef,
    CommandRouter,
    _ALIAS_MAP,
    looks_like_slash_command,
)


class TestLooksLikeSlashCommand:
    """``looks_like_slash_command()`` — distinguish commands from file paths."""

    def test_basic_command(self) -> None:
        assert looks_like_slash_command("/help") is True

    def test_command_with_args(self) -> None:
        assert looks_like_slash_command("/model gpt-4") is True

    def test_file_path(self) -> None:
        assert looks_like_slash_command("/Users/x/file.md") is False

    def test_windows_path(self) -> None:
        # Not a slash command (doesn't start with /)
        assert looks_like_slash_command("C:\\Users\\file") is False

    def test_empty(self) -> None:
        assert looks_like_slash_command("") is False

    def test_no_slash(self) -> None:
        assert looks_like_slash_command("hello") is False

    def test_bare_slash(self) -> None:
        # Just "/" — first word is "/" which has no content after the leading /
        assert looks_like_slash_command("/") is True


class TestCommandRegistry:
    """COMMANDS registry integrity."""

    def test_all_commands_have_names(self) -> None:
        for name, cmd in COMMANDS.items():
            assert cmd.name == name

    def test_all_commands_have_help(self) -> None:
        for cmd in COMMANDS.values():
            assert cmd.help_text, f"{cmd.name} has no help text"

    def test_help_command_exists(self) -> None:
        assert "help" in COMMANDS

    def test_exit_command_exists(self) -> None:
        assert "exit" in COMMANDS

    def test_aliases_registered(self) -> None:
        assert _ALIAS_MAP.get("q") == "exit"
        assert _ALIAS_MAP.get("quit") == "exit"
        assert _ALIAS_MAP.get("h") == "help"
        assert _ALIAS_MAP.get("?") == "help"
        assert _ALIAS_MAP.get("v") == "version"
        assert _ALIAS_MAP.get("cls") == "clear"
        assert _ALIAS_MAP.get("oc") == "opencode"

    def test_opencode_command_exists(self) -> None:
        assert "opencode" in COMMANDS
        assert "oc" in COMMANDS["opencode"].aliases



class TestCommandRouter:
    """CommandRouter dispatch logic."""

    def _make_app(self) -> ContexerApp:
        return ContexerApp()

    def test_dispatch_exact_command(self) -> None:
        app = self._make_app()
        router = CommandRouter()
        # /version should return None (continue REPL)
        result = router.dispatch(app, "/version")
        assert result is None

    def test_dispatch_alias(self) -> None:
        app = self._make_app()
        router = CommandRouter()
        # /q should resolve to /exit and return False (exit REPL)
        result = router.dispatch(app, "/q")
        assert result is False

    def test_dispatch_exit(self) -> None:
        app = self._make_app()
        router = CommandRouter()
        result = router.dispatch(app, "/exit")
        assert result is False

    def test_dispatch_quit(self) -> None:
        app = self._make_app()
        router = CommandRouter()
        result = router.dispatch(app, "/quit")
        assert result is False

    def test_dispatch_unknown(self) -> None:
        app = self._make_app()
        router = CommandRouter()
        result = router.dispatch(app, "/nonexistent")
        assert result is None  # continues REPL

    def test_dispatch_prefix_expansion(self) -> None:
        app = self._make_app()
        router = CommandRouter()
        # /ver should uniquely expand to /version
        result = router.dispatch(app, "/ver")
        assert result is None  # version prints but continues

    def test_dispatch_non_slash_ignored(self) -> None:
        app = self._make_app()
        router = CommandRouter()
        result = router.dispatch(app, "hello world")
        assert result is None

    def test_dispatch_with_args(self) -> None:
        app = self._make_app()
        router = CommandRouter()
        # /help with trailing args should still work
        result = router.dispatch(app, "/help commands")
        assert result is None

    def test_dispatch_status(self) -> None:
        app = self._make_app()
        router = CommandRouter()
        result = router.dispatch(app, "/status")
        assert result is None

    def test_dispatch_opencode_health(self, monkeypatch) -> None:
        from contexer.opencode.adapter import OpenCodeAdapter
        from contexer.opencode.models import OpenCodeHealth

        async def fake_health(self):
            return OpenCodeHealth(healthy=True, version="1.4.3")

        monkeypatch.setattr(OpenCodeAdapter, "check_health", fake_health)
        app = self._make_app()
        router = CommandRouter()
        result = router.dispatch(app, "/opencode status")
        assert result is None

    def test_dispatch_opencode_connection_error(self, monkeypatch) -> None:
        from contexer.opencode.adapter import OpenCodeAdapter
        from contexer.opencode.exceptions import OpenCodeConnectionError

        async def fake_health(self):
            raise OpenCodeConnectionError("Connection refused", "http://127.0.0.1:4096")

        monkeypatch.setattr(OpenCodeAdapter, "check_health", fake_health)
        app = self._make_app()
        router = CommandRouter()
        result = router.dispatch(app, "/opencode health")
        assert result is None

    def test_dispatch_opencode_run_success(self, monkeypatch) -> None:
        from contexer.opencode.adapter import OpenCodeAdapter
        from contexer.opencode.models import (
            ExecutionStatus,
            OpenCodeDiffItem,
            OpenCodeExecutionResult,
            OpenCodeHealth,
            OpenCodeSession,
        )

        async def fake_health(self):
            return OpenCodeHealth(healthy=True, version="1.4.3")

        async def fake_create_session(self, title=None, directory=None):
            return OpenCodeSession(id="ses_test", slug="test-slug")

        async def fake_send_prompt(self, session_id, prompt, wait=True, timeout=120.0):
            return OpenCodeExecutionResult(
                session_id=session_id,
                status=ExecutionStatus.COMPLETED,
                diff=[OpenCodeDiffItem(file="contexer_test.txt", patch="+Hello", additions=1, deletions=0)],
                response_text="Created file.",
                duration_seconds=1.2,
            )

        monkeypatch.setattr(OpenCodeAdapter, "check_health", fake_health)
        monkeypatch.setattr(OpenCodeAdapter, "create_session", fake_create_session)
        monkeypatch.setattr(OpenCodeAdapter, "send_prompt", fake_send_prompt)

        app = self._make_app()
        router = CommandRouter()
        result = router.dispatch(app, "/opencode run create test file")
        assert result is None

    def test_loop_command_registered(self) -> None:
        assert "loop" in COMMANDS
        assert "auto" in COMMANDS["loop"].aliases
        assert "build" in COMMANDS["loop"].aliases

    def test_loop_command_empty_args(self) -> None:
        app = self._make_app()
        router = CommandRouter()
        result = router.dispatch(app, "/loop")
        assert result is None

    @patch("contexer.workflow.loop.AutonomousLoop.run")
    def test_loop_command_dispatches(self, mock_run) -> None:
        from contexer.workflow.loop import AutonomousLoopResult
        mock_run.return_value = AutonomousLoopResult(
            goal="Add button",
            app_url="http://localhost:3000",
            passed=True,
            attempts=1,
        )
        app = self._make_app()
        router = CommandRouter()
        result = router.dispatch(app, "/loop Add button --url http://localhost:4000")
        assert result is None
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["goal"] == "Add button"
        assert call_kwargs["app_url"] == "http://localhost:4000"

    @patch("contexer.workflow.loop.AutonomousLoop.run")
    def test_loop_command_with_dir(self, mock_run) -> None:
        from contexer.workflow.loop import AutonomousLoopResult
        mock_run.return_value = AutonomousLoopResult(
            goal="Add button",
            app_url="http://localhost:3000",
            passed=True,
            attempts=1,
        )
        app = self._make_app()
        router = CommandRouter()
        result = router.dispatch(app, "/loop Add button --dir sandbox --url http://localhost:3000")
        assert result is None
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["goal"] == "Add button"
        assert call_kwargs["project"].name == "sandbox"

    def test_project_command_registered(self) -> None:
        assert "project" in COMMANDS
        assert "p" in COMMANDS["project"].aliases
        assert "workspace" in COMMANDS["project"].aliases

    def test_project_command_status(self) -> None:
        app = self._make_app()
        router = CommandRouter()
        result = router.dispatch(app, "/project")
        assert result is None

    def test_project_command_list(self) -> None:
        app = self._make_app()
        router = CommandRouter()
        result = router.dispatch(app, "/project list")
        assert result is None

    def test_project_command_new_and_reset(self) -> None:
        app = self._make_app()
        router = CommandRouter()
        result = router.dispatch(app, "/project new temp_box")
        assert result is None
        assert app.project_manager.active_project.name == "temp_box"

        result2 = router.dispatch(app, "/project reset")
        assert result2 is None
        assert app.project_manager.active_project.name == "sandbox"

