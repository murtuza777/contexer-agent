"""The Diagnoser: a fix prompt that names the cause, not a list of failures.

Two parts, kept apart on purpose:

* ``fix_prompt`` writes the prompt a person pastes into a coding agent. The
  facts in it (the steps, what was expected, what the browser saw, the
  uncaught exceptions) come from the check results and are inserted by code,
  word for word. It needs no model: with no brief it is still a complete
  prompt.
* ``diagnose`` runs the Diagnoser agent, which may read the project (and
  only read it) to find the likely cause. Its ``RepairBrief`` adds the cause,
  the files and the instruction. The cause is labelled as a hypothesis; it
  cannot change a fact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from contexer.crew.base import AgentSpec, AgentStatus, run_agent
from contexer.verification.checks import Check, CheckResult

if TYPE_CHECKING:
    from contexer.browser.freeze import Confirmed

DEFAULT_MAX_STEPS = 15
_TIMEOUT = 300.0
_PROMPT = Path(__file__).resolve().parent / "prompts" / "diagnoser.md"

# What the read tools never open: Contexer's own files, version control, dependencies, secrets.
_CLOSED_DIRS = {".contexer", ".git", "node_modules", ".venv", "venv", "__pycache__", ".next", "dist", "build"}
_MAX_FILE_BYTES = 400_000
_MAX_READ_LINES = 400
_MAX_MATCHES = 60
_MAX_LINE_CHARS = 300
_MAX_DIFF_CHARS = 12_000
_MAX_LOG_CHARS = 4_000


class Failure(BaseModel):
    """One confirmed failure: the check, and what the browser saw when it was replayed."""

    title: str
    description: str = ""
    severity: str = "medium"
    check: Check
    result: CheckResult

    @classmethod
    def from_confirmed(cls, confirmed: Confirmed) -> Failure:
        if confirmed.result is None:
            raise ValueError(f"'{confirmed.finding.title}' has no replay result")
        return cls(
            title=confirmed.finding.title,
            description=confirmed.finding.description,
            severity=confirmed.finding.severity,
            check=confirmed.check,
            result=confirmed.result,
        )


class RepairBrief(BaseModel):
    """What the Diagnoser adds to the facts. Every field may be empty."""

    cause: str = Field("", description="The most likely cause, naming the function or line. Empty if not found.")
    files: list[str] = Field(default_factory=list, description="Paths inside the project the fix most likely touches.")
    instruction: str = Field("", description="What the coding agent should do: the smallest change that fixes it.")
    keep_working: list[str] = Field(default_factory=list, description="Nearby behaviour the fix must not break.")


@dataclass
class DiagnosisResult:
    brief: Optional[RepairBrief]
    status: AgentStatus
    steps: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Optional[float] = None
    error: str = ""


def diagnoser_prompt() -> str:
    return _PROMPT.read_text(encoding="utf-8")


async def diagnose(
    failures: Sequence[Failure],
    model: BaseChatModel,
    project_dir: Path,
    *,
    intent: str = "",
    diff: str = "",
    server_log: str = "",
    run_dir: Optional[Path] = None,
    max_steps: int = DEFAULT_MAX_STEPS,
    secrets: Sequence[str] = (),
) -> DiagnosisResult:
    """Let ``model`` look for the cause of ``failures`` in the project. No brief when it could not finish."""
    spec = AgentSpec(
        name="diagnoser",
        system_prompt=diagnoser_prompt(),
        output_schema=RepairBrief,
        max_steps=max_steps,
        timeout=_TIMEOUT,
    )
    parts = ["## What the app should do", intent.strip() or "(not stated)", "", "## Confirmed failures"]
    for failure in failures:
        parts += [f"### {failure.title}", *failure.check.describe_lines(), "", failure.result.failure_report(), ""]
    if diff.strip():
        parts += ["## The latest diff", diff.strip()[:_MAX_DIFF_CHARS], ""]
    if server_log.strip():
        parts += ["## The end of the server log", server_log.strip()[-_MAX_LOG_CHARS:], ""]
    parts.append("Find the likely cause and hand in the brief.")
    ran = await run_agent(spec, model, project_tools(project_dir), "\n".join(parts), run_dir=run_dir, secrets=list(secrets))
    return DiagnosisResult(
        brief=ran.output if isinstance(ran.output, RepairBrief) else None,
        status=ran.status,
        steps=ran.steps,
        tokens_in=ran.tokens_in,
        tokens_out=ran.tokens_out,
        cost_usd=ran.cost_usd,
        error=ran.error,
    )


def fix_prompt(
    failures: Sequence[Failure],
    brief: Optional[RepairBrief] = None,
    *,
    intent: str = "",
    working: Sequence[str] = (),
) -> str:
    """The prompt to paste into a coding agent. Empty when nothing failed.

    Everything under "What is wrong" is taken from the check results. The
    brief, when there is one, adds the cause, the files and the instruction.
    """
    if not failures:
        return ""
    lines = [
        "# Fix request",
        "",
        "Contexer used the running app in a real browser and replayed what it found. The failures below were "
        "reproduced by a program, in a fresh browser, with no model involved. They are facts about the app as it is now.",
        "",
    ]
    if intent.strip():
        lines += ["## What the app should do", "", intent.strip(), ""]
    lines += ["## What is wrong", ""]
    for number, failure in enumerate(failures, 1):
        lines += [f"### {number}. {failure.title}", ""]
        if failure.description:
            lines += [failure.description, ""]
        lines += ["Steps, from a freshly loaded app:", "", "```text", *failure.check.describe_lines(), "```", ""]
        result = failure.result
        if result.failed_step:
            lines += [f"- Could not perform: {result.failed_step}"]
        for outcome in result.outcomes:
            if not outcome.passed:
                lines += [f"- Expected: {outcome.description}", f"- Actual: {outcome.actual}"]
        for error in result.page_errors[:3]:
            lines += [f"- Uncaught exception: {error}"]
        for error in result.console_errors[:3]:
            lines += [f"- Console: {error}"]
        lines.append("")

    cause = brief.cause.strip() if brief else ""
    files = [f.strip() for f in brief.files if f.strip()] if brief else []
    instruction = brief.instruction.strip() if brief else ""
    if cause:
        lines += [
            "## Likely cause",
            "",
            cause,
            "",
            "This is a hypothesis from reading the code, not a verified fact. Check it before relying on it.",
            "",
        ]
    if files:
        lines += ["## Files to look at", "", *[f"- `{name}`" for name in files], ""]
    lines += ["## What to do", ""]
    if instruction:
        lines += [instruction, ""]
    lines += [
        "Make every expectation above hold, with the smallest change that does it. Do not change what the steps do "
        "or what they expect to make them pass.",
        "",
    ]
    keep = [*working, *(brief.keep_working if brief else [])]
    keep = list(dict.fromkeys(item.strip() for item in keep if item.strip()))
    if keep:
        lines += ["## What must keep working", "", *[f"- {item}" for item in keep], ""]
    lines += [
        "## Rules",
        "",
        "- Do not edit anything in `.contexer/`: it holds the intent and the checks.",
        "- Do not start a dev server, install a browser, or commit.",
        "- When you are done, I will run `contexer test --again`. It replays these exact steps and tells us both "
        "whether they pass.",
    ]
    return "\n".join(lines).rstrip("\n") + "\n"


# -- read tools --------------------------------------------------------------------


class _ReadFile(BaseModel):
    path: str = Field(description="A file path inside the project, e.g. 'src/app.js'.")
    start: int = Field(1, description="The first line to read (1 is the top).")
    lines: int = Field(200, description="How many lines to read.")


class _Grep(BaseModel):
    pattern: str = Field(description="A regular expression.")
    path: str = Field(".", description="A file or folder inside the project to search; the whole project by default.")


def project_tools(project_dir: Path) -> list[BaseTool]:
    """``read_file`` and ``grep``: read-only, confined to the project, closed to Contexer's files and secrets."""
    root = Path(project_dir).resolve()

    def resolve(path: str) -> Path | str:
        raw = path.strip() or "."
        try:
            target = (root / raw).resolve()
        except OSError as exc:
            return f"Error: '{path}' is not a usable path: {exc}"
        if target != root and root not in target.parents:
            return f"Error: '{path}' is outside the project. Only files inside the project can be read."
        closed = _closed(target.relative_to(root))
        if closed:
            return f"Error: '{path}' is not available: {closed}"
        return target

    def read_file(path: str, start: int = 1, lines: int = 200) -> str:
        target = resolve(path)
        if isinstance(target, str):
            return target
        if not target.is_file():
            return f"Error: there is no file '{path}' in the project."
        if target.stat().st_size > _MAX_FILE_BYTES:
            return f"Error: '{path}' is too large to read ({target.stat().st_size:,} bytes). Use grep to find the part you need."
        try:
            content = target.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return f"Error: '{path}' is not a text file."
        first = max(1, start)
        last = min(len(content), first + max(1, min(lines, _MAX_READ_LINES)) - 1)
        if first > len(content):
            return f"Error: '{path}' has {len(content)} lines."
        body = [f"{n}: {content[n - 1][:_MAX_LINE_CHARS]}" for n in range(first, last + 1)]
        more = f"\n... {len(content) - last} more line(s)" if last < len(content) else ""
        return "\n".join(body) + more

    def grep(pattern: str, path: str = ".") -> str:
        target = resolve(path)
        if isinstance(target, str):
            return target
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return f"Error: '{pattern}' is not a valid regular expression: {exc}"
        files = [target] if target.is_file() else sorted(p for p in target.rglob("*") if p.is_file())
        matches: list[str] = []
        for file in files:
            relative = file.relative_to(root)
            if _closed(relative) or file.stat().st_size > _MAX_FILE_BYTES:
                continue
            try:
                text = file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    matches.append(f"{relative.as_posix()}:{number}: {line.strip()[:_MAX_LINE_CHARS]}")
                    if len(matches) >= _MAX_MATCHES:
                        return "\n".join(matches) + f"\n... stopped at {_MAX_MATCHES} matches; narrow the pattern or the path"
        return "\n".join(matches) if matches else f"No match for '{pattern}'."

    return [
        StructuredTool.from_function(
            read_file,
            name="read_file",
            description="Read part of a file in the project, with line numbers.",
            args_schema=_ReadFile,
        ),
        StructuredTool.from_function(
            grep,
            name="grep",
            description="Search the project's files with a regular expression. Returns file:line: text.",
            args_schema=_Grep,
        ),
    ]


def _closed(relative: Path) -> str:
    """Why a path inside the project may not be read, or '' when it may."""
    parts = relative.parts
    for part in parts[:-1] if parts else ():
        if part in _CLOSED_DIRS:
            return f"`{part}/` is closed to this tool."
    if parts and parts[-1] in _CLOSED_DIRS:
        return f"`{parts[-1]}/` is closed to this tool."
    name = parts[-1] if parts else ""
    if name == ".env" or name.startswith(".env."):
        return "environment files hold secrets."
    return ""
