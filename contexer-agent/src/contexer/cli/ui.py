"""Contexer UI rendering — banners, prompts, panels, and status output.

Design principles:
    - All terminal output goes through ``UIRenderer`` — no raw ``print()``.
    - Rich Console handles color, markup, and terminal width detection.
    - The renderer is stateless and can be replaced/mocked for testing.
"""

from __future__ import annotations

import shutil
from typing import Any, Optional, TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme

from contexer import __version__

import sys

if TYPE_CHECKING:
    from contexer.safety import ToolConfirmation

def _can_encode(char: str) -> bool:
    """Check if the current stdout stream can encode the given character."""
    try:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        char.encode(encoding)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

_CONTEXER_THEME = Theme(
    {
        "ctx.brand": "bold bright_cyan",
        "ctx.accent": "bold bright_magenta",
        "ctx.dim": "dim italic",
        "ctx.success": "bold green",
        "ctx.warning": "bold yellow",
        "ctx.error": "bold red",
        "ctx.info": "bold blue",
        "ctx.prompt": "bold bright_cyan",
        "ctx.border": "bright_cyan",
        "ctx.subtitle": "dim cyan",
        "ctx.command": "bold bright_white",
        "ctx.description": "dim",
    }
)

# ---------------------------------------------------------------------------
# UIRenderer
# ---------------------------------------------------------------------------


class UIRenderer:
    """Centralized terminal rendering for the Contexer CLI.

    Every visible output the CLI produces passes through this class.
    Swapping or mocking it replaces all UI without touching business logic.
    """

    def __init__(self, console: Optional[Console] = None) -> None:
        self.console = console or Console(theme=_CONTEXER_THEME, highlight=False)
        self._at_line_start: bool = True
        self._stream_buffer: list[str] = []
        self._live: Optional[Any] = None
        self._active_tool: Optional[str] = None

    # -- helpers ----------------------------------------------------------

    @property
    def terminal_width(self) -> int:
        """Current terminal width, with a sane fallback."""
        try:
            return shutil.get_terminal_size((80, 24)).columns
        except Exception:
            return 80

    # -- banner -----------------------------------------------------------

    def render_banner(self) -> None:
        """Render the startup banner.

        Uses a Rich panel for automatic width and border handling.
        """
        width = min(self.terminal_width - 4, 60)

        title_text = Text("CONTEXER", style="bold bright_cyan")
        subtitle = Text("Autonomous Engineering Agent", style="dim cyan")
        version_text = Text(f"v{__version__}", style="dim")

        content = Text()
        content.append_text(title_text)
        content.append("\n")
        content.append_text(subtitle)
        content.append("\n")
        content.append_text(version_text)

        panel = Panel(
            content,
            border_style="bright_cyan",
            width=width,
            padding=(1, 2),
        )
        self.console.print()
        self.console.print(panel)

    # -- prompt -----------------------------------------------------------

    def render_prompt(self) -> str:
        """Return the prompt string for input. Does NOT print it."""
        return "❯ " if _can_encode("❯") else "> "

    def render_continuation_prompt(self) -> str:
        """Return the continuation prompt string for multiline input."""
        return "… " if _can_encode("…") else "... "



    def render_welcome(self) -> None:
        """Print the post-banner welcome hint."""
        self.console.print(
            "[ctx.dim]Type a message to begin, or [/][ctx.command]/help[/]"
            "[ctx.dim] for commands.[/]"
        )
        self.console.print()

    # -- status output ----------------------------------------------------

    def print_info(self, message: str) -> None:
        """Informational message (blue prefix)."""
        char = "ℹ" if _can_encode("ℹ") else "i"
        self.console.print(f"[ctx.info]{char}[/] {message}")

    def print_success(self, message: str) -> None:
        """Success message (green prefix)."""
        char = "✓" if _can_encode("✓") else "+"
        self.console.print(f"[ctx.success]{char}[/] {message}")

    def print_warning(self, message: str) -> None:
        """Warning message (yellow prefix)."""
        char = "⚠" if _can_encode("⚠") else "!"
        self.console.print(f"[ctx.warning]{char}[/] {message}")

    def print_error(self, message: str) -> None:
        """Error message (red prefix)."""
        char = "✗" if _can_encode("✗") else "x"
        self.console.print(f"[ctx.error]{char}[/] {message}")

    def print_dim(self, message: str) -> None:
        """Dim/muted message."""
        self.console.print(f"[ctx.dim]{message}[/]")

    def print_rule(self, title: str = "") -> None:
        """Horizontal rule, optionally titled."""
        characters = "─" if _can_encode("─") else "-"
        self.console.rule(title, style="ctx.border", characters=characters)

    # -- echo (user input feedback) ---------------------------------------

    def echo_user_input(self, text: str) -> None:
        """Echo the user's input back for confirmation/scrollback."""
        preview = text.strip()
        if not preview:
            return
        # Truncate long inputs to first line
        lines = preview.splitlines()
        if len(lines) > 1:
            display = f"{lines[0]}  [ctx.dim](+{len(lines) - 1} lines)[/]"
        else:
            display = preview
        marker = "▸" if _can_encode("▸") else ">"
        self.console.print(f"[ctx.dim]  {marker} {display}[/]")

    # -- line safety and live display helpers ----------------------------

    def _ensure_newline(self) -> None:
        """Ensure the console cursor is on a new line before printing block elements."""
        if not self._at_line_start:
            self.console.print()
            self._at_line_start = True

    def _stop_live(self) -> None:
        """Safely conclude and close the Live display if active."""
        if self._live is not None:
            try:
                from rich.markdown import Markdown

                full_text = "".join(self._stream_buffer)
                if full_text.strip():
                    self._live.update(Markdown(full_text))
                self._live.stop()
            except Exception:
                pass
            finally:
                self._live = None
                self._stream_buffer.clear()

    # -- tool execution indicators ----------------------------------------

    def render_tool_start(self, tool_name: str) -> None:
        """Render a compact tool execution start indicator."""
        self._ensure_newline()
        self._stop_live()
        self._active_tool = tool_name
        if self.console.is_terminal:
            arrow = "›" if _can_encode("›") else ">"
            self.console.print(f"[ctx.dim]  {arrow} {tool_name}...[/]", end="\r")

    def render_tool_end(self, tool_name: str, success: bool = True) -> None:
        """Render a clean, compact single-line tool completion indicator."""
        self._ensure_newline()
        self._stop_live()
        pad = "          " if self.console.is_terminal else ""
        if success:
            mark = "✓" if _can_encode("✓") else "[OK]"
            self.console.print(f"  [ctx.success]{mark}[/] [ctx.dim]{tool_name}[/]{pad}")
        else:
            mark = "✗" if _can_encode("✗") else "[FAIL]"
            self.console.print(f"  [ctx.error]{mark} {tool_name} (failed)[/]{pad}")
        self._at_line_start = True
        self._active_tool = None

    def request_tool_confirmation(self, confirmation: "ToolConfirmation") -> bool:
        """Render an AgentForge-inspired approval gate in the Contexer UI."""
        from rich.prompt import Prompt

        lines = [f"[ctx.command]{confirmation.tool_name}[/]", confirmation.description]
        if confirmation.command:
            lines.append(f"[ctx.warning]$ {confirmation.command}[/]")
        for path in confirmation.affected_paths:
            lines.append(f"[ctx.dim]Path: {path}[/]")
        if confirmation.is_dangerous:
            lines.append("[ctx.error]This operation was classified as dangerous.[/]")
        self.console.print()
        self.console.print(
            Panel(
                "\n".join(lines),
                title="Approval required",
                border_style="yellow",
                padding=(1, 2),
            )
        )
        answer = Prompt.ask("Approve?", choices=["y", "n", "yes", "no"], default="n")
        return answer.lower() in {"y", "yes"}

    def render_agent_prefix(self) -> None:
        """Render the 'Contexer:' label before final answer streaming."""
        self._ensure_newline()
        self._stop_live()
        self.console.print()
        self.console.print("[ctx.brand]Contexer:[/]")
        self.console.print()
        self._at_line_start = True

    # -- streaming output -------------------------------------------------

    def stream_token(self, token: str) -> None:
        """Output a single token chunk with Rich Markdown formatting."""
        if not token:
            return

        self._at_line_start = token.endswith("\n")
        self._stream_buffer.append(token)

        from rich.markdown import Markdown

        full_text = "".join(self._stream_buffer)
        if self._live is None:
            from rich.live import Live

            self._live = Live(
                Markdown(full_text),
                console=self.console,
                refresh_per_second=10,
                vertical_overflow="visible",
            )
            self._live.start()
        else:
            self._live.update(Markdown(full_text))

    def end_stream(self) -> None:
        """End a streaming generation session and flush spacing."""
        self._stop_live()
        self.console.print()
        self._at_line_start = True

    def render_markdown(self, markdown_text: str) -> None:
        """Render a full markdown block with styling."""
        self._ensure_newline()
        self._stop_live()
        from rich.markdown import Markdown

        self.console.print(Markdown(markdown_text))
        self.console.print()
        self._at_line_start = True

    def render_agent_event(self, event: Any) -> None:
        """Render a typed AgentEvent from the runtime harness."""
        from contexer.runtime.events import AgentEventType

        event_type = getattr(event, "type", None)
        if event_type == AgentEventType.TOOL_CALL_START:
            self.render_tool_start(event.data.get("name", ""))
        elif event_type == AgentEventType.TOOL_CALL_COMPLETE:
            self.render_tool_end(
                event.data.get("name", ""),
                event.data.get("success", True),
            )
        elif event_type == AgentEventType.TEXT_DELTA:
            self.stream_token(event.data.get("content", ""))
        elif event_type == AgentEventType.LOOP_DETECTED:
            self.console.print(f"[ctx.warning]⚠ Loop warning: {event.data.get('message')}[/]")
        elif event_type == AgentEventType.CIRCUIT_BREAKER:
            self.console.print(f"[ctx.error]⚡ Circuit breaker: {event.data.get('message')}[/]")
        elif event_type == AgentEventType.AGENT_ERROR:
            self.print_error(f"Error: {event.data.get('error')}")


    # -- exit summary -----------------------------------------------------

    def render_exit(self) -> None:
        """Print the exit message."""
        self.console.print()
        self.console.print("[ctx.dim]Goodbye.[/]")
