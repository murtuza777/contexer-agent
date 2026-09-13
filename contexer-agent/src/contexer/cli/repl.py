"""Contexer interactive REPL — the main application loop.

The CLI stays deliberately thin over the AgentForge-adapted runtime:

- Rich ``Console`` for output instead of prompt_toolkit's full TUI.
- Python's ``input()`` with Rich prompt styling instead of a TextArea.
- Composition over inheritance (no 16-mixin class).

Design principles:
    - ``ContexerApp`` is the single coordinator for the interactive session.
    - It owns a ``UIRenderer`` (display), ``CommandRouter`` (dispatch),
      ``ContexerConfig`` (settings), and ``ContexerAgent`` (runtime).
    - Signal handling is minimal and clean (Ctrl+C, EOF).
    - The REPL loop is a simple ``while True`` — no threads in Phase 0.
"""

from __future__ import annotations

import signal
import sys
from typing import Any, Optional

from contexer.cli.commands import CommandRouter, looks_like_slash_command
from contexer.cli.ui import UIRenderer
from contexer.config.settings import ContexerConfig, load_config
from contexer.runtime.agent import ContexerAgent


class ContexerApp:
    """The Contexer interactive shell application.

    This is the central coordinator. It owns:
    - ``ui``: UIRenderer — all terminal output
    - ``router``: CommandRouter — slash command dispatch
    - ``config``: ContexerConfig — application settings
    - ``agent``: ContexerAgent — the autonomous runtime
    """

    def __init__(
        self,
        ui: Optional[UIRenderer] = None,
        router: Optional[CommandRouter] = None,
        config: Optional[ContexerConfig] = None,
        agent: Optional[Any] = None,
    ) -> None:

        self.ui = ui or UIRenderer()
        self.router = router or CommandRouter()
        self.config = config or load_config()
        self.agent = agent or ContexerAgent(config=self.config)
        from contexer.project.manager import ProjectManager
        self.project_manager = ProjectManager()
        set_confirmation_callback = getattr(self.agent, "set_confirmation_callback", None)
        if callable(set_confirmation_callback):
            set_confirmation_callback(self.ui.request_tool_confirmation)

        self._should_exit = False
        self._multiline_buffer: list[str] = []


    # -- REPL -------------------------------------------------------------

    def run(self) -> None:
        """Launch the interactive Contexer shell.

        Flow:
            1. Show banner + welcome
            2. Enter input loop
            3. On exit: cleanup + goodbye
        """
        from contexer.cli import _configure_terminal_encoding

        _configure_terminal_encoding()
        self._install_signal_handlers()
        self._show_startup()
        self._repl_loop()
        self._shutdown()

    def _show_startup(self) -> None:
        """Render startup sequence: banner and welcome message."""
        self.ui.render_banner()
        self.ui.render_welcome()
        active = self.project_manager.active_project
        self.ui.print_dim(f"  Target Project: [bright_cyan]{active.name}[/] ({active.project_type.value}) -> {active.path}")
        self.ui.console.print()

    def _repl_loop(self) -> None:
        """Main input loop.

        Handles:
        - Single-line and multiline input (``\\`` continuation)
        - Slash command routing
        - Ctrl+C (interrupt current input, not exit)
        - Ctrl+D / EOF (exit)
        - Empty input (skip)
        """
        prompt = self.ui.render_prompt()

        while not self._should_exit:
            try:
                raw = input(prompt)
            except KeyboardInterrupt:
                # Ctrl+C: clear any multiline buffer and show a new prompt
                if self._multiline_buffer:
                    self._multiline_buffer.clear()
                    self.ui.print_dim("  Input cancelled.")
                else:
                    self.ui.console.print()  # blank line after ^C
                continue
            except EOFError:
                # Ctrl+D: exit
                break

            line = raw.rstrip()

            # -- multiline continuation (backslash at end) ----------------
            if line.endswith("\\"):
                self._multiline_buffer.append(line[:-1])
                prompt = self.ui.render_continuation_prompt()
                continue


            if self._multiline_buffer:
                self._multiline_buffer.append(line)
                full_input = "\n".join(self._multiline_buffer)
                self._multiline_buffer.clear()
                prompt = self.ui.render_prompt()
            else:
                full_input = line

            # -- empty input → skip --------------------------------------
            if not full_input.strip():
                continue

            # -- slash commands -------------------------------------------
            if looks_like_slash_command(full_input.strip()):
                result = self.router.dispatch(self, full_input.strip())
                if result is False:
                    self._should_exit = True
                continue

            # -- regular input ---------------------------------------------
            self._handle_user_message(full_input)

    def _handle_user_message(self, message: str) -> None:
        """Handle a regular (non-command) user message."""
        self.ui.echo_user_input(message)
        self.ui.console.print()

        try:
            import asyncio

            def _loop_exception_handler(
                loop: asyncio.AbstractEventLoop, context: dict[str, Any]
            ) -> None:
                exc = context.get("exception")
                msg = context.get("message", "")
                if (exc and "generator didn't stop after athrow()" in str(exc)) or (
                    "HTTP11ConnectionByteStream" in str(msg)
                ):
                    return
                loop.default_exception_handler(context)

            with asyncio.Runner() as runner:
                runner.get_loop().set_exception_handler(_loop_exception_handler)
                runner.run(self._process_message_async(message))
        except KeyboardInterrupt:
            if self.agent:
                self.agent.interrupt()
            self.ui.print_dim("\n  Operation interrupted.")
            self.ui.console.print()
        except Exception as exc:
            self.ui.print_error(f"Error: {exc}")
            self.ui.console.print()

    async def _process_message_async(self, message: str) -> None:
        """Run asynchronous agent message processing with streaming and tool progress."""
        import inspect

        if self.config.streaming:
            stream_kwargs: dict[str, Any] = {}
            try:
                sig = inspect.signature(self.agent.stream_message)
                params = sig.parameters
                has_var_kwargs = any(
                    p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
                )
                if has_var_kwargs or "on_tool_start" in params:
                    stream_kwargs["on_tool_start"] = self.ui.render_tool_start
                if has_var_kwargs or "on_tool_end" in params:
                    stream_kwargs["on_tool_end"] = self.ui.render_tool_end
                if has_var_kwargs or "on_stream_start" in params:
                    stream_kwargs["on_stream_start"] = self.ui.render_agent_prefix
            except Exception:
                pass

            async for token in self.agent.stream_message(message, **stream_kwargs):
                self.ui.stream_token(token)
            self.ui.end_stream()
        else:
            proc_kwargs: dict[str, Any] = {}
            try:
                sig = inspect.signature(self.agent.process_message)
                params = sig.parameters
                has_var_kwargs = any(
                    p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
                )
                if has_var_kwargs or "on_tool_start" in params:
                    proc_kwargs["on_tool_start"] = self.ui.render_tool_start
                if has_var_kwargs or "on_tool_end" in params:
                    proc_kwargs["on_tool_end"] = self.ui.render_tool_end
            except Exception:
                pass

            result = await self.agent.process_message(message, **proc_kwargs)
            if result.error:
                self.ui.print_error(result.error)
            else:
                self.ui.render_markdown(result.response)

    # -- signal handling --------------------------------------------------

    def _install_signal_handlers(self) -> None:
        """Install signal handlers for graceful shutdown.

        Keeps shutdown coordination intentionally simple on a plain Rich REPL.
        """
        if sys.platform != "win32":
            # SIGTERM → graceful exit
            signal.signal(signal.SIGTERM, self._signal_handler)
            if hasattr(signal, "SIGHUP"):
                signal.signal(signal.SIGHUP, self._signal_handler)

    def _signal_handler(self, signum: int, frame: object) -> None:
        """Handle SIGTERM/SIGHUP by requesting exit."""
        self._should_exit = True

    # -- shutdown ---------------------------------------------------------

    def _shutdown(self) -> None:
        """Clean shutdown sequence."""
        if self.agent:
            self.agent.shutdown()
        self.ui.render_exit()
