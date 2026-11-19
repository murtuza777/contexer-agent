"""The Reviewer: the diff is read before a person sees it.

A browser check proves what a user can see. It does not see a key pasted into
the source, a test that was switched off, or wrong logic on a path no check
walks. The review looks at the diff for those, from three sources that are
kept apart:

* ``prescan``: code reads the diff for a short list of patterns (a secret, a
  focused or skipped test, a deleted test file, removed assertions, leftover
  debug code). No model.
* ``run_commands``: code runs the project's own ``test``, ``lint`` and
  ``typecheck`` scripts, with a time limit, and notes the ones that fail.
* the Reviewer agent: a model reads the diff and the code around it with
  read-only tools and writes what it thinks is wrong.

What code saw is ``backed``. What the model wrote is advice: it is shown to
the person, and it never starts a repair and never changes a verdict.
Nothing here can make a run pass or fail; the checks do that.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from contexer.crew.base import AgentSpec, run_agent
from contexer.crew.budget import Budget
from contexer.crew.diagnoser import project_tools
from contexer.crew.untrusted import untrusted
from contexer.procutil import spawn_tree, without_agent_session

Severity = Literal["low", "medium", "high"]
Category = Literal["security", "tests", "debug", "logic", "other"]
Source = Literal["scan", "command", "reviewer"]
CommandStatus = Literal["passed", "failed", "timed_out", "not_run"]

MAX_NOTES = 20
MAX_EXPLANATION_CHARS = 500
DEFAULT_COMMAND_TIMEOUT = 180.0
# The package.json scripts that count as the project's own checks, in the order they are run.
COMMAND_SCRIPTS = ("test", "lint", "typecheck", "type-check")
_MAX_STEPS = 12
_TIMEOUT = 300.0
_MAX_DIFF_CHARS = 30_000
_MAX_OUTPUT_TAIL = 1_500
_PROMPT = Path(__file__).resolve().parent / "prompts" / "reviewer.md"
_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


class ReviewNote(BaseModel):
    """One thing the review found. ``backed`` is set by code, never by a model."""

    file: str = ""
    line: int = 0
    severity: Severity = "low"
    category: Category = "other"
    explanation: str
    source: Source = "reviewer"
    backed: bool = False
    # For a failing command: the end of what it printed.
    evidence: str = ""


class ProjectCommand(BaseModel):
    name: str
    argv: list[str]

    @property
    def shown(self) -> str:
        return f"npm run {self.name}"


class CommandRun(BaseModel):
    name: str
    command: str
    status: CommandStatus
    exit_code: int | None = None
    output_tail: str = ""
    seconds: float = 0.0


class ReviewResult(BaseModel):
    notes: list[ReviewNote] = Field(default_factory=list)
    commands: list[CommandRun] = Field(default_factory=list)
    # "scan_only" when no model looked; otherwise how the Reviewer agent ended.
    status: str = "scan_only"
    steps: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float | None = None
    error: str = ""

    @property
    def blocking(self) -> list[ReviewNote]:
        """What a repair is asked to fix: seen by code, and worth a turn."""
        return blocking_notes(self.notes)

    @property
    def holds_pull_request(self) -> bool:
        return holds_pull_request(self.notes)


def blocking_notes(notes: Sequence[ReviewNote]) -> list[ReviewNote]:
    return [n for n in notes if n.backed and n.severity != "low"]


def holds_pull_request(notes: Sequence[ReviewNote]) -> bool:
    """A high-severity security note, from any source, keeps a pull request a draft until a person has looked."""
    return any(n.severity == "high" and n.category == "security" for n in notes)


def reviewer_prompt() -> str:
    return _PROMPT.read_text(encoding="utf-8")


# -- the scan --------------------------------------------------------------------------------------

_TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|specs?|e2e)(/|$)|\.(test|spec)\.[cm]?[jt]sx?$|(^|/)test_[^/]+\.py$|_test\.(py|go)$")
_KNOWN_SECRETS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("an AWS access key", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("an API key (sk-...)", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("a GitHub token", re.compile(r"\b(ghp|gho|ghs|ghu)_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{30,}")),
    ("a Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("a private key", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----")),
)
_ASSIGNED = re.compile(
    r"(?i)\b[\w.-]*(api[_-]?key|[a-z0-9]+[_-]key|secret|token|passwd|password|credential|private[_-]?key)[\w-]*[\"']?\s*[:=]\s*[\"'`]([^\"'`\s]{16,})[\"'`]"
)
_PLACEHOLDER = re.compile(r"(?i)example|placeholder|your[-_ ]|changeme|dummy|sample|test|fake|xxxx|\.\.\.|[<>{}$/\\ ]")
_FOCUSED = re.compile(r"\b(?:it|test|describe|context)\.only\s*\(|\b(?:fit|fdescribe)\s*\(")
_SKIPPED = re.compile(r"\b(?:it|test|describe|context)\.skip\s*\(|\b(?:xit|xdescribe|xtest)\s*\(|@pytest\.mark\.skip|@unittest\.skip")
_ASSERTION = re.compile(r"\bexpect\s*\(|\bassert\b|\bassert[A-Z]\w*\s*\(|\.should\b")
_DEBUG = re.compile(r"\bconsole\.(log|debug|trace)\s*\(|^\s*debugger\s*;?\s*$|\bbreakpoint\(\)|\bpdb\.set_trace\(\)")


def is_test_path(path: str) -> bool:
    return bool(_TEST_PATH.search(path.replace("\\", "/")))


class _FileDiff:
    def __init__(self, path: str) -> None:
        self.path = path
        self.deleted = False
        self.added: list[tuple[int, str]] = []  # (line number in the new file, text)
        self.removed: list[str] = []


def _parse(diff: str) -> list[_FileDiff]:
    files: list[_FileDiff] = []
    current: _FileDiff | None = None
    old_path = ""
    new_line = 0
    for raw in diff.splitlines():
        if raw.startswith("diff --git "):
            current, old_path = None, ""
        elif raw.startswith("--- "):
            old_path = _path(raw[4:])
            current = None
        elif raw.startswith("+++ "):
            new_path = _path(raw[4:])
            current = _FileDiff(new_path or old_path)
            current.deleted = not new_path
            files.append(current)
        elif raw.startswith("@@"):
            match = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", raw)
            new_line = int(match.group(1)) if match else 0
        elif current is None:
            continue
        elif raw.startswith("+"):
            current.added.append((new_line, raw[1:]))
            new_line += 1
        elif raw.startswith("-"):
            current.removed.append(raw[1:])
        elif not raw.startswith("\\"):
            new_line += 1
    return files


def _path(side: str) -> str:
    """``a/src/x.js`` or ``b/src/x.js`` as ``src/x.js``; '' for /dev/null."""
    side = side.split("\t")[0].strip().strip('"')
    if side == "/dev/null":
        return ""
    return side[2:] if side[:2] in ("a/", "b/") else side


def changed_files(diff: str) -> list[str]:
    return list(dict.fromkeys(f.path for f in _parse(diff) if f.path))


def secret_kind(line: str) -> str:
    """What kind of secret ``line`` holds, or ''. The value itself is never returned."""
    for label, pattern in _KNOWN_SECRETS:
        if pattern.search(line):
            return label
    assigned = _ASSIGNED.search(line)
    if assigned is None:
        return ""
    value = assigned.group(2)
    mixed = any(c.isdigit() for c in value) and any(c.islower() for c in value) and any(c.isupper() for c in value)
    if not mixed or _PLACEHOLDER.search(value) or len(set(value)) < 8:
        return ""
    return f"a value assigned to something named like a secret (`{assigned.group(1)}`)"


def prescan(diff: str) -> list[ReviewNote]:
    """What code can see in the diff without a model. Every note is ``backed``: it is a fact about the diff."""
    notes: list[ReviewNote] = []

    def add(file: str, line: int, severity: Severity, category: Category, explanation: str) -> None:
        notes.append(
            ReviewNote(file=file, line=line, severity=severity, category=category, explanation=explanation, source="scan", backed=True)
        )

    for file in _parse(diff):
        tests = is_test_path(file.path)
        if file.deleted:
            if tests:
                add(file.path, 0, "medium", "tests", "A test file was deleted. Tests are removed only when what they test is removed.")
            continue
        name = file.path.rsplit("/", 1)[-1]
        if name == ".env" or name.startswith(".env."):
            if not name.endswith((".example", ".sample", ".template")):
                add(file.path, 0, "high", "security", "An environment file is part of the change. They hold secrets and do not belong in a commit.")
            continue
        for line, text in file.added:
            found = secret_kind(text)
            if found:
                add(
                    file.path, line, "high", "security",
                    f"This line adds what looks like a secret: {found}. Read it from the environment instead, and "
                    "revoke the value if it is real.",
                )  # fmt: skip
                continue
            if tests and _FOCUSED.search(text):
                add(file.path, line, "medium", "tests", "A test is focused with `.only`, so the other tests in this file do not run.")
            elif tests and _SKIPPED.search(text):
                add(file.path, line, "medium", "tests", "A test is switched off with `skip`.")
            elif not tests and _DEBUG.search(text):
                add(file.path, line, "low", "debug", f"Leftover debug code: `{text.strip()[:80]}`.")
        if tests:
            removed = sum(1 for text in file.removed if _ASSERTION.search(text))
            added = sum(1 for _line, text in file.added if _ASSERTION.search(text))
            if removed > added:
                add(
                    file.path, 0, "medium", "tests",
                    f"{removed} assertion(s) were removed from this test file and {added} added. A test that asserts less proves less.",
                )  # fmt: skip
    return notes


# -- the project's own commands ----------------------------------------------------------------------

_NO_TESTS = "no test specified"
_SECRET_NAME = re.compile(r"(?i)key|token|secret|password|passwd|credential|auth")


def project_commands(project_dir: Path) -> list[ProjectCommand]:
    """The ``test``, ``lint`` and ``typecheck`` scripts of the project's package.json. Nothing else is ever run."""
    try:
        package = json.loads((Path(project_dir) / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    scripts = package.get("scripts") if isinstance(package, dict) else None
    if not isinstance(scripts, dict):
        return []
    commands: list[ProjectCommand] = []
    for name in COMMAND_SCRIPTS:
        script = scripts.get(name)
        if not isinstance(script, str) or not script.strip() or _NO_TESTS in script:
            continue
        line = f"npm run {name} --silent"
        argv = ["cmd.exe", "/d", "/s", "/c", line] if sys.platform == "win32" else ["npm", "run", name, "--silent"]
        commands.append(ProjectCommand(name=name, argv=argv))
    return commands


def _needs_install(project_dir: Path) -> bool:
    """True when the project declares dependencies that are not installed: its scripts cannot say anything yet."""
    try:
        package = json.loads((Path(project_dir) / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    declared = any(package.get(key) for key in ("dependencies", "devDependencies")) if isinstance(package, dict) else False
    return bool(declared) and not (Path(project_dir) / "node_modules").is_dir()


def command_env() -> dict[str, str]:
    """The environment a project command gets: the person's own, without anything named like a credential."""
    env = {name: value for name, value in without_agent_session(dict(os.environ)).items() if not _SECRET_NAME.search(name)}
    env["CI"] = "1"  # test runners that watch for changes by default run once instead
    return env


def run_commands(project_dir: Path, commands: Sequence[ProjectCommand], timeout: float = DEFAULT_COMMAND_TIMEOUT) -> list[CommandRun]:
    """Run each command once. A command that cannot run, or does not finish, proves nothing and says so."""
    runs: list[CommandRun] = []
    if not commands:
        return runs
    if shutil.which("npm") is None or _needs_install(Path(project_dir)):
        why = "npm is not installed" if shutil.which("npm") is None else "the project's dependencies are not installed"
        return [CommandRun(name=c.name, command=c.shown, status="not_run", output_tail=why) for c in commands]
    for command in commands:
        started = time.monotonic()
        tree = spawn_tree(command.argv, project_dir, command_env())
        try:
            output, _ = tree.proc.communicate(timeout=timeout)
            status: CommandStatus = "passed" if tree.proc.returncode == 0 else "failed"
            code: int | None = tree.proc.returncode
        except subprocess.TimeoutExpired:
            tree.kill(grace=3)
            try:
                output, _ = tree.proc.communicate(timeout=5)
            except (subprocess.TimeoutExpired, ValueError, OSError):
                output = b""
            status, code = "timed_out", None
        finally:
            tree.kill(grace=1)
        text = (output or b"").decode("utf-8", errors="replace").strip()
        runs.append(
            CommandRun(
                name=command.name,
                command=command.shown,
                status=status,
                exit_code=code,
                output_tail=text[-_MAX_OUTPUT_TAIL:],
                seconds=round(time.monotonic() - started, 2),
            )
        )
    return runs


def _command_notes(runs: Sequence[CommandRun]) -> list[ReviewNote]:
    return [
        ReviewNote(
            severity="medium",
            category="tests" if run.name == "test" else "other",
            explanation=f"`{run.command}` fails (exit {run.exit_code}). It was not run before the change, so it may have failed then too.",
            source="command",
            backed=True,
            evidence=run.output_tail,
        )
        for run in runs
        if run.status == "failed"
    ]


# -- the agent ---------------------------------------------------------------------------------------


class _Note(BaseModel):
    file: str = Field("", description="The changed file the note is about, as a path inside the project.")
    line: int = Field(0, description="The line in the file as it is now; 0 when the note is about the whole file.")
    severity: Severity = Field(description="high: must be looked at before merging. medium: should be fixed. low: tidy-up.")
    category: Category
    explanation: str = Field(description="What is wrong and why it matters, in one or two sentences.")


class Review(BaseModel):
    """The Reviewer's answer."""

    notes: list[_Note] = Field(default_factory=list, description="Empty when nothing is wrong. Do not pad.")


class _NoArgs(BaseModel):
    pass


async def review(
    diff: str,
    project_dir: Path,
    model: BaseChatModel | None = None,
    *,
    intent: str = "",
    checks: Sequence[str] = (),
    run_project_commands: bool = True,
    command_timeout: float = DEFAULT_COMMAND_TIMEOUT,
    run_dir: Path | None = None,
    budget: Budget | None = None,
    secrets: Sequence[str] = (),
) -> ReviewResult:
    """Review ``diff`` (the change from the baseline to the project as it is now in ``project_dir``)."""
    result = ReviewResult()
    if not diff.strip():
        return result
    result.notes = prescan(diff)
    if run_project_commands:
        result.commands = run_commands(project_dir, project_commands(project_dir), command_timeout)
        result.notes += _command_notes(result.commands)
    if model is None or (budget is not None and budget.exhausted()):
        result.notes = _ordered(result.notes)
        return result

    files = _parse(diff)
    touched = [f.path for f in files if f.path]

    def list_changed_files() -> str:
        rows = [f"{f.path}: {'deleted' if f.deleted else f'+{len(f.added)} -{len(f.removed)}'}" for f in files if f.path]
        return "\n".join(rows) or "No file changed."

    tools = [
        *project_tools(project_dir),
        StructuredTool.from_function(
            list_changed_files,
            name="list_changed_files",
            description="The files this change touches, with the number of lines added and removed.",
            args_schema=_NoArgs,
        ),
    ]
    spec = AgentSpec(name="reviewer", system_prompt=reviewer_prompt(), output_schema=Review, max_steps=_MAX_STEPS, timeout=_TIMEOUT)
    ran = await run_agent(
        spec, model, tools, _task(diff, intent, checks, result), run_dir=run_dir, secrets=list(secrets), budget=budget
    )
    result.status = ran.status
    result.steps, result.tokens_in, result.tokens_out = ran.steps, ran.tokens_in, ran.tokens_out
    result.cost_usd, result.error = ran.cost_usd, ran.error
    if isinstance(ran.output, Review):
        result.notes += _accepted(ran.output.notes, touched, result.notes)
    result.notes = _ordered(result.notes)[:MAX_NOTES]
    return result


def _task(diff: str, intent: str, checks: Sequence[str], found: ReviewResult) -> str:
    parts = ["## What the change is for", intent.strip() or "(not stated)", ""]
    if checks:
        parts += ["## The checks that passed in the browser", *[f"- {line}" for line in checks][:40], ""]
    if found.notes:
        parts += ["## Already found by a program (do not repeat these)"]
        parts += [f"- {_where(n) or 'the project'}: {n.explanation}" for n in found.notes]
        parts.append("")
    ran = [c for c in found.commands if c.status != "not_run"]
    if ran:
        parts += ["## The project's own commands, run just now"]
        for command in ran:
            parts.append(f"- `{command.command}`: {command.status.replace('_', ' ')}")
            if command.status == "failed" and command.output_tail:
                parts.append(untrusted("command-output", command.output_tail))
        parts.append("")
    cut = diff.strip()[:_MAX_DIFF_CHARS]
    more = "\n(The diff is longer than this; use the tools to read the rest.)" if len(diff.strip()) > _MAX_DIFF_CHARS else ""
    parts += ["## The diff", untrusted("diff", cut) + more, "", "Review the change and hand in your notes."]
    return "\n".join(parts)


def _accepted(notes: Sequence[_Note], touched: Sequence[str], known: Sequence[ReviewNote]) -> list[ReviewNote]:
    """The model's notes with what code allows: about a file the change touches, capped, and never ``backed``."""
    files = set(touched)
    seen = {(n.file, n.line, n.category) for n in known}
    seen_files = {(n.file, n.category) for n in known if n.category == "debug"}
    accepted: list[ReviewNote] = []
    for note in notes:
        file = note.file.strip().replace("\\", "/")
        explanation = " ".join(note.explanation.split())
        if file not in files or not explanation:
            continue
        line = max(0, note.line)
        key = (file, line, note.category)
        if key in seen or (file, note.category) in seen_files:
            continue
        seen.add(key)
        if len(explanation) > MAX_EXPLANATION_CHARS:
            explanation = explanation[: MAX_EXPLANATION_CHARS - 3].rstrip() + "..."
        accepted.append(
            ReviewNote(file=file, line=line, severity=note.severity, category=note.category, explanation=explanation, source="reviewer")
        )
    return accepted


def _ordered(notes: Sequence[ReviewNote]) -> list[ReviewNote]:
    """Code's notes first, then by severity; the order within each is the order they were found in."""
    return sorted(notes, key=lambda n: (not n.backed, _SEVERITY_ORDER[n.severity]))


def _where(note: ReviewNote) -> str:
    if not note.file:
        return ""
    return f"{note.file}:{note.line}" if note.line else note.file


# -- what a repair is told ---------------------------------------------------------------------------


def review_section(notes: Sequence[ReviewNote]) -> str:
    """What code saw in the change, as a section of a prompt for the coding agent. '' when there is nothing."""
    todo = blocking_notes(notes)
    if not todo:
        return ""
    lines = ["A program read your change and found this. Each point is a fact about the files as they are now:", ""]
    for number, note in enumerate(todo, 1):
        where = _where(note)
        lines.append(f"{number}. {f'`{where}`: ' if where else ''}{note.explanation}")
        if note.evidence.strip():
            lines += ["   The end of what the command printed:", untrusted("command-output", note.evidence.strip())]
    return "\n".join(lines)


def review_repair_prompt(notes: Sequence[ReviewNote]) -> str:
    """The prompt for the one repair a review may ask for. The checks passed, and must still pass after it."""
    return "\n\n".join(
        [
            "Every check passed in the browser. Before the work is handed over, one more thing needs fixing.",
            review_section(notes),
            "Fix these points with the smallest change that does it. Every check passed with the code as it is: "
            "they are run again after this turn, and if any of them fails, this turn is undone. Do not weaken, skip "
            "or delete a test to make a command pass, and do not edit anything under .contexer/.",
            "When you are done, reply with one line saying what you changed.",
        ]
    )
