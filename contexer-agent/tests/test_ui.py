"""Tests for the Contexer UI rendering."""

from io import StringIO

from rich.console import Console

from contexer import __version__
from contexer.cli.ui import UIRenderer, _CONTEXER_THEME

import re

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class TestUIRenderer:
    """UIRenderer output verification."""

    def _make_renderer(self) -> tuple[UIRenderer, StringIO]:
        """Create a renderer that captures output to a StringIO buffer."""
        buf = StringIO()
        console = Console(
            file=buf,
            force_terminal=True,
            color_system="truecolor",
            width=80,
            theme=_CONTEXER_THEME,
        )
        renderer = UIRenderer(console=console)
        return renderer, buf

    def test_render_banner_contains_name(self) -> None:
        renderer, buf = self._make_renderer()
        renderer.render_banner()
        output = buf.getvalue()
        assert "contexer" in output

    def test_render_banner_contains_subtitle(self) -> None:
        renderer, buf = self._make_renderer()
        renderer.render_banner()
        output = buf.getvalue()
        assert "interactive shell" in output and "contexer run" in output

    def test_render_banner_contains_version(self) -> None:
        renderer, buf = self._make_renderer()
        renderer.render_banner()
        output = buf.getvalue()
        assert __version__ in output

    def test_render_prompt(self) -> None:
        renderer, _ = self._make_renderer()
        prompt = renderer.render_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_render_continuation_prompt(self) -> None:
        renderer, _ = self._make_renderer()
        prompt = renderer.render_continuation_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_render_welcome(self) -> None:
        renderer, buf = self._make_renderer()
        renderer.render_welcome()
        output = _ANSI_RE.sub("", buf.getvalue())
        assert "/help" in output


    def test_print_info(self) -> None:
        renderer, buf = self._make_renderer()
        renderer.print_info("test message")
        output = buf.getvalue()
        assert "test message" in output

    def test_print_success(self) -> None:
        renderer, buf = self._make_renderer()
        renderer.print_success("done")
        output = buf.getvalue()
        assert "done" in output

    def test_print_warning(self) -> None:
        renderer, buf = self._make_renderer()
        renderer.print_warning("careful")
        output = buf.getvalue()
        assert "careful" in output

    def test_print_error(self) -> None:
        renderer, buf = self._make_renderer()
        renderer.print_error("oops")
        output = buf.getvalue()
        assert "oops" in output

    def test_print_dim(self) -> None:
        renderer, buf = self._make_renderer()
        renderer.print_dim("faded text")
        output = buf.getvalue()
        assert "faded text" in output

    def test_echo_user_input(self) -> None:
        renderer, buf = self._make_renderer()
        renderer.echo_user_input("hello world")
        output = buf.getvalue()
        assert "hello world" in output

    def test_echo_user_input_multiline(self) -> None:
        renderer, buf = self._make_renderer()
        renderer.echo_user_input("line1\nline2\nline3")
        output = _ANSI_RE.sub("", buf.getvalue())
        assert "line1" in output
        assert "+2 lines" in output

    def test_echo_user_input_empty(self) -> None:
        renderer, buf = self._make_renderer()
        renderer.echo_user_input("")
        output = buf.getvalue()
        assert output.strip() == ""

    def test_render_exit(self) -> None:
        renderer, buf = self._make_renderer()
        renderer.render_exit()
        output = buf.getvalue()
        assert "Goodbye" in output

    def test_terminal_width_fallback(self) -> None:
        renderer, _ = self._make_renderer()
        width = renderer.terminal_width
        assert isinstance(width, int)
        assert width > 0

    def test_render_tool_start_and_end(self) -> None:
        renderer, buf = self._make_renderer()
        renderer.render_tool_start("list_directory")
        renderer.render_tool_end("list_directory", success=True)
        output = buf.getvalue()
        assert "list_directory" in output

    def test_render_tool_end_failure(self) -> None:
        renderer, buf = self._make_renderer()
        renderer.render_tool_end("failing_tool", success=False)
        output = buf.getvalue()
        assert "failing_tool" in output

    def test_render_agent_prefix(self) -> None:
        renderer, buf = self._make_renderer()
        renderer.render_agent_prefix()
        output = buf.getvalue()
        assert "Contexer:" in output

    def test_stream_token_and_end_stream(self) -> None:
        renderer, buf = self._make_renderer()
        renderer.stream_token("Hello ")
        renderer.stream_token("**world**!\n")
        renderer.end_stream()
        output = buf.getvalue()
        assert "Hello" in output
        assert "world" in output

    def test_ensure_newline_flushes_when_not_at_line_start(self) -> None:
        renderer, buf = self._make_renderer()
        renderer._at_line_start = False
        renderer._ensure_newline()
        assert renderer._at_line_start is True
        output = buf.getvalue()
        assert output.endswith("\n")

