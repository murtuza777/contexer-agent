"""Tests for the ContexerApp interactive REPL."""

from io import StringIO
import re
from unittest.mock import patch

from rich.console import Console

from contexer.cli.commands import CommandRouter
from contexer.cli.repl import ContexerApp
from contexer.cli.ui import UIRenderer, _CONTEXER_THEME
from contexer.config.settings import ContexerConfig
from contexer.runtime.agent import ContexerAgent

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class MockStreamingAgent:
    """Mock agent for testing REPL message processing."""

    def __init__(self) -> None:
        self.interrupted = False
        self.shutdown_called = False

    async def stream_message(self, message: str):
        yield f"Agent response to: {message}"

    async def process_message(self, message: str):
        from contexer.runtime.agent import AgentResult, AgentState

        return AgentResult(state=AgentState.COMPLETED, response=f"Agent response to: {message}")

    def interrupt(self) -> None:
        self.interrupted = True

    def shutdown(self) -> None:
        self.shutdown_called = True


def _make_app(agent=None) -> tuple[ContexerApp, StringIO]:
    buf = StringIO()
    console = Console(
        file=buf,
        force_terminal=True,
        color_system="truecolor",
        width=80,
        theme=_CONTEXER_THEME,
    )
    ui = UIRenderer(console=console)
    router = CommandRouter()
    config = ContexerConfig()
    app = ContexerApp(ui=ui, router=router, config=config, agent=agent or MockStreamingAgent())
    return app, buf


class TestContexerApp:
    """ContexerApp lifecycle and REPL flow tests."""

    def test_init_defaults(self) -> None:
        app = ContexerApp()
        assert app.ui is not None
        assert app.router is not None
        assert app.config is not None
        assert app.agent is not None
        assert app._should_exit is False
        assert app._multiline_buffer == []

    def test_startup_renders_banner_and_welcome(self) -> None:
        app, buf = _make_app()
        app._show_startup()
        output = _ANSI_RE.sub("", buf.getvalue())
        assert "CONTEXER" in output
        assert "/help" in output

    def test_handle_user_message_streams_response(self) -> None:
        app, buf = _make_app()
        app._handle_user_message("Build a web app")
        output = buf.getvalue()
        assert "Build a web app" in output
        assert "Agent response to: Build a web app" in output

    def test_shutdown_renders_goodbye_and_calls_agent_shutdown(self) -> None:
        agent = MockStreamingAgent()
        app, buf = _make_app(agent=agent)
        app._shutdown()
        output = buf.getvalue()
        assert "Goodbye" in output
        assert agent.shutdown_called is True

    def test_signal_handler_sets_should_exit(self) -> None:
        app, _ = _make_app()
        assert app._should_exit is False
        app._signal_handler(15, None)
        assert app._should_exit is True

    def test_repl_loop_eof_exits_gracefully(self) -> None:
        app, buf = _make_app()
        with patch("builtins.input", side_effect=EOFError):
            app._repl_loop()
        assert app._should_exit is False  # Loop broke on EOF

    def test_repl_loop_slash_exit_command(self) -> None:
        app, buf = _make_app()
        with patch("builtins.input", side_effect=["/exit"]):
            app._repl_loop()
        assert app._should_exit is True

    def test_repl_loop_empty_input_skipped(self) -> None:
        app, buf = _make_app()
        with patch("builtins.input", side_effect=["   ", "", "/exit"]):
            app._repl_loop()
        assert app._should_exit is True

    def test_repl_loop_multiline_input(self) -> None:
        app, buf = _make_app()
        inputs = ["first line \\", "second line", "/exit"]
        with patch("builtins.input", side_effect=inputs):
            app._repl_loop()
        output = _ANSI_RE.sub("", buf.getvalue())
        assert "first line" in output
        assert "+1 lines" in output

    def test_repl_loop_keyboard_interrupt_clears_buffer(self) -> None:
        app, buf = _make_app()
        inputs = ["line before interrupt \\", KeyboardInterrupt(), "/exit"]
        with patch("builtins.input", side_effect=inputs):
            app._repl_loop()
        output = buf.getvalue()
        assert "Input cancelled." in output

    def test_run_executes_full_flow(self) -> None:
        app, buf = _make_app()
        with patch("builtins.input", side_effect=["/exit"]):
            app.run()
        output = buf.getvalue()
        assert "CONTEXER" in output
        assert "Goodbye" in output
