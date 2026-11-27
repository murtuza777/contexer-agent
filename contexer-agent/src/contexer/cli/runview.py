"""What a person sees while ``contexer run`` works.

Two things are drawn from the same events (``graph/context.py: RunEvent``).

**Lines that stay.** One for each attempt, one for what the agent did, one
for the verdict, and under a verdict the checks that did not hold with what
the browser saw. They are printed once and never redrawn, so they read the
same in a terminal, in a CI log and pasted into an issue. The agent's tool
calls are not among them unless ``verbose``: forty lines of "Read file" push
the one line that matters off the screen.

**A block that is redrawn in place**, in a terminal only: the plan of the run
with the step it is at, every check with its state, what is happening now,
and the time and money so far next to their ceilings. It answers what a
person looking up from other work wants to know: is it still going, on what,
how far is it, what has it cost.

The events carry the coding agent's spend and nothing about tokens or how
full a model's context is, so the footer does not show those.

Same rules as the rest of the terminal output (``term.py``): no boxes,
colour for meaning only, one set of marks.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.markup import escape
from rich.padding import Padding
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from contexer.cli import term
from contexer.graph.context import RunEvent

# Checks shown one per line before the rest are counted; the ones that failed always come first.
MAX_CHECK_LINES = 12
# Failed checks listed under a verdict in the lines that stay.
MAX_FAILED_LINES = 6
_STATE_MARK = {"verified": "pass", "refuted": "fail", "unverified": "open"}
_STATE_WORD = {"verified": "", "refuted": "", "unverified": "could not be checked"}
# The plan of a run. The hand-off happens after the last event, when the block is gone.
STEPS = ("draft", "approve", "build", "prove", "review", "hand off")


class RunView:
    """Turns a run's events into the lines that stay and the block that is redrawn."""

    def __init__(
        self,
        console: Console,
        *,
        verbose: bool = False,
        project: Path | None = None,
        drafts: bool = False,
        max_attempts: int | None = None,
        budget_usd: float | None = None,
    ) -> None:
        self.console = console
        self.verbose = verbose
        # A run that drafts its checks begins at the first step; one on approved checks begins at build.
        self.step = "draft" if drafts else "build"
        # The ceilings said before the run: the coding agent's turns, and its budget when one is set.
        self.max_attempts = max_attempts
        self.budget_usd = budget_usd
        # Paths in tool calls are shown from here: `Edit src/app.js`, not the whole way from the drive.
        self._roots = _roots(project)
        self.checks: list[dict[str, Any]] = []
        self.earlier_checks = 0
        # Verdicts of the last attempt that was checked, by check id.
        self.verdicts: dict[str, dict[str, Any]] = {}
        self.attempt = 0
        self.doing = ""
        self.activity = ""
        self.activity_since = 0.0
        self.tool_calls = 0
        self.last_tool = ""
        self.spent_usd = 0.0
        self._started = time.monotonic()
        self._at = 0.0
        self._live: Live | None = None
        # One spinner for the whole run: a new one at every redraw would always show its first frame.
        self._spinner = Spinner("dots", style="dim")

    # -- events ---------------------------------------------------------------------------------

    def handle(self, event: RunEvent) -> None:
        self._at = max(self._at, event.at)
        data = event.data
        kind = event.kind
        if kind == "checks":
            self.checks = list(data.get("checks") or [])
            self.earlier_checks = int(data.get("earlier_checks") or 0)
            self.verdicts = {}
        elif kind == "attempt-start":
            self.attempt = int(data.get("n") or 0)
            self.doing = str(data.get("doing") or "")
            self.step = "build"
            self.tool_calls, self.last_tool = 0, ""
            fresh = " in a fresh session" if data.get("fresh") else ""
            self._line()
            self._line(f"{term.mark('info')} [bold]Attempt {self.attempt}[/] [dim]·[/] {escape(self.doing)}{fresh} with {escape(str(data.get('agent') or 'the agent'))}")
            self._now("Agent working", event.at)
        elif kind == "agent":
            self.tool_calls += 1
            shown = self._local(event.message)
            self.last_tool = shown
            if self.verbose:
                self._line(f"    [dim]{escape(shown)}[/]")
        elif kind == "agent-done":
            cost = data.get("cost_usd")
            self.spent_usd = float(data.get("spent_usd") or 0.0)  # the run's total so far, this turn included
            files = int(data.get("files") or 0)
            parts = [f"{files} file{'' if files == 1 else 's'} changed", term.duration(float(data.get("seconds") or 0.0))]
            if cost:
                parts.append(f"${float(cost):.2f}")
            if data.get("status") not in (None, "completed"):
                parts.insert(0, f"[yellow]{escape(str(data.get('status')))}[/]")
            self._line("  " + " [dim]·[/] ".join(parts))
            self.tool_calls, self.last_tool = 0, ""  # the turn is over; what runs next is not the agent
            self._now("", event.at)
        elif kind == "phase" and data.get("proving"):
            self.step = "prove"
            self._now(f"Proving {data['proving']} checks in Chromium", event.at)
        elif kind == "phase-quiet":
            self._now(event.message, event.at)
            if not self.console.is_terminal:
                self._line(f"  [dim]{escape(event.message)}[/]")
        elif kind == "verdict":
            self._verdict(data)
            if data.get("outcome") == "pass":
                self.step = "review"  # what follows a pass; a repair the review asks for begins a new attempt
            self._now("", event.at)
        elif kind in ("strategy", "revert", "review") and event.message:
            self._line(f"  {term.mark('warn')} {escape(event.message)}")
        elif kind == "approved":
            self.step = "build"
            self._line(f"{term.mark('pass')} {escape(event.message)}")
        elif kind == "app" and event.message:
            self._line(f"  [dim]{escape(event.message)}[/]")
        elif kind == "end":
            self.step = "hand off"
            self.stop()
        self._refresh()

    def _verdict(self, data: dict[str, Any]) -> None:
        rows = list(data.get("checks") or [])
        self.verdicts = {str(row.get("id")): row for row in rows}
        proven = sum(1 for row in rows if row.get("verdict") == "verified")
        failed = sum(1 for row in rows if row.get("verdict") == "refuted")
        unchecked = len(rows) - proven - failed
        passed = data.get("outcome") == "pass"
        parts = [f"{proven} of {len(rows)} checks proven"]
        if failed:
            parts.append(f"{failed} failed")
        if unchecked:
            parts.append(f"{unchecked} could not be checked")
        broke = int(data.get("others_failing") or 0)
        # Earlier checks that failed before the run began: not counted, and said on every verdict, a pass too.
        stale = int(data.get("stale") or 0)
        if broke:
            parts.append(f"[red]{broke} earlier check{'' if broke == 1 else 's'} broke[/]")
        if stale:
            parts.append(f"[yellow]{stale} earlier check{' was' if stale == 1 else 's were'} already failing before this change[/]")
        if not broke and not stale and self.earlier_checks:
            parts.append(f"{self.earlier_checks} earlier checks still pass")
        style = "green" if passed else "red" if (failed or broke) else "yellow"
        self._line(f"  {term.mark('pass' if passed else 'fail' if (failed or broke) else 'open')} [{style}]{parts[0]}[/]" + "".join(f" [dim]·[/] {p}" for p in parts[1:]))
        described = {str(c.get("id")): str(c.get("description") or c.get("id")) for c in self.checks}
        wrong = [row for row in rows if row.get("verdict") != "verified"]
        table = Table.grid()
        table.add_column(width=2, no_wrap=True)
        table.add_column(overflow="fold")
        for row in wrong[:MAX_FAILED_LINES]:
            mark = term.mark(_STATE_MARK.get(str(row.get("verdict")), "open"))
            why = str(row.get("evidence") or "").strip()
            name = escape(described.get(str(row.get("id")), str(row.get("id"))))
            table.add_row(mark, name + (f"\n[dim]{escape(why)}[/]" if why else ""))
        if table.row_count:
            self.console.print(Padding(table, (0, 0, 0, 6), expand=False), highlight=False)
        if len(wrong) > MAX_FAILED_LINES:
            self._line(f"      [dim]and {len(wrong) - MAX_FAILED_LINES} more; all of them are in the report[/]")
        for found in list(data.get("regressions") or [])[:MAX_FAILED_LINES]:
            self._line(f"      {term.mark('fail')} Regression: {escape(str(found.get('check')))}, broken in attempt {found.get('attempt')}")

    def _local(self, text: str) -> str:
        for root in self._roots:
            if root in text:
                # What is left is a path inside the project: written one way on every system.
                text = text.replace(root, "").replace("\\", "/")
        return text

    # -- the lines that stay --------------------------------------------------------------------

    def _line(self, markup: str = "") -> None:
        self.console.print(markup, highlight=False, soft_wrap=False)

    # -- the block that is redrawn ------------------------------------------------------------------

    def _now(self, activity: str, at: float) -> None:
        self.activity, self.activity_since = activity, at

    def start(self) -> None:
        """Begin drawing the live block. Does nothing where there is no terminal (CI, a pipe)."""
        if self._live is None and self.console.is_terminal:
            self._live = Live(_Block(self), console=self.console, refresh_per_second=8, transient=True)
            self._live.start()

    def stop(self) -> None:
        """Take the live block away, for a question to the person or at the end. ``handle`` brings it back."""
        if self._live is not None:
            self._live.stop()
            self._live = None

    def _refresh(self) -> None:
        if self._live is None and self.activity:  # before the first attempt too: drafting and planning take time
            self.start()

    def _elapsed(self) -> float:
        return max(self._at, time.monotonic() - self._started)

    def live_block(self, now: float | None = None) -> RenderableType:
        """The block as it would be drawn ``now`` seconds into the run."""
        now = self._elapsed() if now is None else now
        width = max(30, self.console.width)
        lines: list[RenderableType] = [self._plan_line(width)]
        if self.attempt:
            head = Text(f"Attempt {self.attempt}", style="bold", no_wrap=True, overflow="ellipsis")
            if self.max_attempts:
                head.append(f" of at most {self.max_attempts}", style="dim")
            if self.doing:
                head.append(f" · {self.doing}", style="dim")
            lines.append(head)

        shown, hidden = self._ordered_checks()
        for check in shown:
            lines.append(self._check_line(check, width))
        if hidden:
            lines.append(Text(f"  … and {hidden} more", style="dim", no_wrap=True, overflow="ellipsis"))

        if self.activity:
            since = int(max(0.0, now - self.activity_since))
            status = Text(self.activity)
            status.append(f" · {since // 60}:{since % 60:02d}", style="dim")
            if self.tool_calls:
                status.append(f" · {self.tool_calls} tool call{'' if self.tool_calls == 1 else 's'}", style="dim")
            if self.last_tool:
                status.append(f" · {self.last_tool}", style="dim")
            status.no_wrap, status.overflow = True, "ellipsis"
            status.truncate(width - 4, overflow="ellipsis")
            if self.console.is_terminal:
                self._spinner.update(text=status)
                lines.append(self._spinner)
            else:
                lines.append(Text("  ") + status)

        foot = Text(f"  {term.duration(now)}", style="dim", no_wrap=True, overflow="ellipsis")
        if self.spent_usd:  # never $0.00: an agent that reports no cost has not spent nothing
            foot.append(f" · ${self.spent_usd:.2f}")
            if self.budget_usd:
                foot.append(f" of ${self.budget_usd:.2f}")
        lines.append(foot)
        return Group(*lines)

    def _plan_line(self, width: int) -> Text:
        """``✓ draft  ✓ approve  › build  · prove  · review  · hand off``: done, the step it is at, to come."""
        at = STEPS.index(self.step)
        line = Text(no_wrap=True, overflow="ellipsis")
        for index, step in enumerate(STEPS):
            char, style = term.plain_mark("pass" if index < at else "info" if index == at else "todo")
            line.append("  " if index else "")
            line.append(f"{char} ", style="bold" if index == at else style)
            line.append(step, style="bold" if index == at else "dim")
        line.truncate(width, overflow="ellipsis")
        return line

    def _ordered_checks(self) -> tuple[list[dict[str, Any]], int]:
        """The checks to list, the ones that did not hold first, and how many are left out."""
        order = {"refuted": 0, "unverified": 1}
        ranked = sorted(self.checks, key=lambda c: order.get(str(self.verdicts.get(str(c.get("id")), {}).get("verdict")), 2))
        return ranked[:MAX_CHECK_LINES], max(0, len(ranked) - MAX_CHECK_LINES)

    def _check_line(self, check: dict[str, Any], width: int) -> Text:
        row = self.verdicts.get(str(check.get("id")))
        verdict = str(row.get("verdict")) if row else ""
        char, style = term.plain_mark(_STATE_MARK.get(verdict, "open") if verdict else "todo")
        line = Text(f"  {char} ", style=style)
        why = _short_reason(str(row.get("evidence") or "")) if row and verdict != "verified" else ""
        name = str(check.get("description") or check.get("id"))
        room = max(20, int(width * 0.55)) if why else width  # a failing check keeps room for why it failed
        if len(name) > room:
            name = name[: room - 1].rstrip() + "…"
        line.append(name, style="" if verdict != "verified" else "dim")
        if why:
            line.append(f"  {why}", style="dim")
        line.no_wrap, line.overflow = True, "ellipsis"
        line.truncate(width, overflow="ellipsis")
        return line


class _Block:
    """Asks the view for its block at every refresh, so the clocks move while nothing else happens."""

    def __init__(self, view: RunView) -> None:
        self.view = view

    def __rich__(self) -> RenderableType:
        return self.view.live_block()


def _short_reason(evidence: str) -> str:
    """What the browser saw, short enough to sit next to a check: the part after "got" when there is one."""
    text = " ".join(evidence.split())
    head, found, tail = text.rpartition(", got ")
    return f"got {tail}" if found and tail else text


def _roots(project: Path | None) -> list[str]:
    """The project folder as an agent may write it, with either kind of slash, longest first."""
    if project is None:
        return []
    base = str(project.resolve())
    forms = {base + "\\", base.replace("\\", "/") + "/", base + "/"}
    return sorted(forms, key=len, reverse=True)
