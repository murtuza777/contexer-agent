"""How Contexer looks in a terminal: one style for every command.

- No boxes. Output reads the same in a terminal, in a CI log and pasted into an
  issue, and does not break at narrow widths.
- Colour carries meaning only: green is proven, red is refuted or broken, yellow
  needs a person. Headings are bold; anything secondary is dim.
- One set of marks (✓ ✗ ? !), with ASCII stand-ins where the terminal cannot
  encode them.
- Summaries are aligned key–value blocks.
- Long waits show a live line with the elapsed time, so a run never looks stuck.
"""

from __future__ import annotations

import re
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from rich.console import Console, RenderableType
from rich.live import Live
from rich.markup import escape
from rich.padding import Padding
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

OUTCOME_STYLE = {"pass": "green", "fail": "red", "needs_action": "yellow", "error": "red"}
TERMINAL_STYLE = {
    "succeeded": "green",
    "failed_checks": "red",
    "tampered": "red",
    "agent_error": "red",
    "app_error": "red",
    "internal_error": "red",
}

_MARKS = {"pass": ("✓", "+"), "fail": ("✗", "x"), "open": ("?", "?"), "warn": ("!", "!"), "info": ("›", ">"), "todo": ("·", "-")}
_MARK_STYLE = {"pass": "green", "fail": "red", "open": "yellow", "warn": "yellow", "info": "dim", "todo": "dim"}


def _encodable(char: str) -> bool:
    try:
        char.encode(getattr(sys.stdout, "encoding", None) or "utf-8")
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def mark(kind: str) -> str:
    """A styled mark: pass, fail, open, warn or info."""
    fancy, plain = _MARKS[kind]
    return f"[{_MARK_STYLE[kind]}]{fancy if _encodable(fancy) else plain}[/]"


def plain_mark(kind: str) -> tuple[str, str]:
    """The mark's character and its style, for a line that is built as ``Text`` and not as markup."""
    fancy, plain = _MARKS[kind]
    return (fancy if _encodable(fancy) else plain), _MARK_STYLE[kind]


# ``--plain``: what a mark at the start of a line is called, and what the other symbols become.
_PLAIN_MARKS = {"✓": "ok:", "✗": "not ok:", "?": "open:", "!": "warning:", "›": ">", "•": "-"}
_PLAIN_MARK = re.compile(r"(?m)^([ \t]*)([✓✗?!›•]) ")
_PLAIN_CHARS = str.maketrans({"✓": "ok", "✗": "not ok", "›": ">", "•": "-", "·": "-", "…": "...", "–": "-", "—": "-"})
# Wide enough that no line is wrapped: a wrapped path cannot be copied out of a CI log.
_PLAIN_WIDTH = 100_000


class _PlainFile:
    """Writes to ``file`` with marks as words and separators as commas, and no padding at the end of a line."""

    def __init__(self, file: Any) -> None:
        self._file = file
        self.encoding = getattr(file, "encoding", None) or "utf-8"

    def write(self, text: str) -> int:
        plain = _PLAIN_MARK.sub(lambda found: f"{found[1]}{_PLAIN_MARKS[found[2]]} ", text.replace(" · ", ", "))
        self._file.write(re.sub(r"[ \t]+(?=\r?\n)", "", plain.translate(_PLAIN_CHARS)))
        return len(text)

    def flush(self) -> None:
        self._file.flush()

    def isatty(self) -> bool:
        return False


def plain_console(file: Any = None) -> Console:
    """The console of ``--plain``: for a CI log, a pipe and a screen reader.

    No colour, nothing redrawn (it is not a terminal to the code that draws), a mark said as a word
    (``ok:``, ``not ok:``, ``open:``, ``warning:``), ``·`` as a comma, and lines that are not wrapped.
    """
    return Console(
        file=_PlainFile(file if file is not None else sys.stdout),  # type: ignore[arg-type]
        force_terminal=False,
        no_color=True,
        color_system=None,
        width=_PLAIN_WIDTH,
        highlight=False,
        emoji=False,
        legacy_windows=False,
    )


def is_plain(console: Console) -> bool:
    return isinstance(console.file, _PlainFile)


def header(console: Console, command: str, subject: str = "") -> None:
    """``contexer run · Users can export their data``: the first line of a command's output."""
    console.print()
    tail = f" [dim]·[/] {escape(subject)}" if subject else ""
    console.print(f"[bold]contexer {escape(command)}[/]{tail}")


def section(console: Console, title: str, detail: str = "") -> None:
    console.print()
    console.print(f"[bold]{escape(title)}[/]" + (f" [dim]· {escape(detail)}[/]" if detail else ""))


# Keys share one width across a command's blocks, so values line up from top to bottom.
_KEY_WIDTH = 12


def fields(console: Console, rows: Iterable[tuple[str, str]], indent: int = 2) -> None:
    """Aligned ``key  value`` lines. Values are Rich markup; keys are plain text."""
    rows = [(k, v) for k, v in rows if v]
    if not rows:
        return
    width = max(_KEY_WIDTH, *(len(k) + 2 for k, _ in rows))
    table = Table.grid()
    table.add_column(style="dim", no_wrap=True, width=width)
    table.add_column(overflow="fold")
    for key, value in rows:
        table.add_row(key, value)
    console.print(Padding(table, (0, 0, 0, indent), expand=False))


def bullets(console: Console, items: Iterable[str], indent: int = 2) -> None:
    """``• text`` lines whose wrapped lines stay under the text, not under the bullet."""
    table = Table.grid()
    table.add_column(style="dim", width=2, no_wrap=True)
    table.add_column(overflow="fold")
    for item in items:
        table.add_row("•", item)
    if table.row_count:
        console.print(Padding(table, (0, 0, 0, indent), expand=False))


def path(value: str | Path) -> str:
    """A path as short as it can be: relative to the current folder when it is inside it."""
    target = Path(value)
    try:
        return str(target.resolve().relative_to(Path.cwd().resolve()))
    except (ValueError, OSError):
        return str(target)


def note(console: Console, kind: str, text: str) -> None:
    """``! Weak draft: ...``: a one-off message that needs attention, with its mark."""
    console.print(f"{mark(kind)} {text}")


def error(console: Console, what: str, why: str, next_step: str, code: int) -> None:
    """One form for an error: what happened and why, what to do next, and the exit code.

    ``✗ Cannot resume: no run '20260101-000000-abcd' in this project.``
    ``  Next: `contexer runs` lists the runs that can be continued.``
    ``  Exit code 2.``

    All three texts are plain, not markup. On a console that prints nothing (``--json``) the error goes to
    stderr, so it is still said and stdout stays one JSON object per line.
    """
    out = Console(stderr=True) if console.quiet else console
    out.print(f"{mark('fail')} [red]{escape(what)}:[/] {escape(why)}", highlight=False)
    out.print(f"  Next: {escape(next_step)}", highlight=False)
    out.print(f"  [dim]Exit code {code}.[/]", highlight=False)


def duration(seconds: float) -> str:
    if seconds < 10:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(round(seconds)), 60)
    return f"{minutes}m {secs:02d}s" if minutes else f"{secs}s"


class Activity:
    """A live bottom line, ``⠋ Agent working · 0:42 · 7 tool calls``, while other lines print above it.

    The elapsed time is computed at each refresh, so it keeps moving while nothing
    else is printed. In a non-interactive terminal (CI) nothing is drawn.
    """

    def __init__(self, console: Console) -> None:
        self.console = console
        self.label = ""
        self.detail = ""
        self.started = 0.0
        self._live: Live | None = None

    def start(self, label: str) -> None:
        self.label, self.detail, self.started = label, "", time.monotonic()
        if self._live is None and self.console.is_terminal:
            self._live = Live(self, console=self.console, refresh_per_second=8, transient=True)
            self._live.start()

    def set_detail(self, detail: str) -> None:
        self.detail = detail

    def stop(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None

    def __rich__(self) -> RenderableType:
        elapsed = int(time.monotonic() - self.started)
        text = Text.assemble(
            (self.label, ""),
            (f" · {elapsed // 60}:{elapsed % 60:02d}", "dim"),
            (f" · {self.detail}" if self.detail else "", "dim"),
        )
        return Spinner("dots", text=text, style="dim")

