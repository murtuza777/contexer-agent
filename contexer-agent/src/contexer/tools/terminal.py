"""Terminal command execution tool using Python subprocess.

Executes commands strictly within the workspace root, captures stdout/stderr,
handles timeouts, truncates oversized output using head+tail retention, strips ANSI
escapes, validates command guardrails, and annotates signals/exit codes.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Optional

from contexer.llm.base import sanitize_sensitive_text

# Maximum output characters returned by command execution
MAX_COMMAND_OUTPUT_CHARS = 20_000

# ANSI escape sequence regex (CSI and OSC sequences)
_ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

# Long-lived foreground server / watcher patterns
_LONG_LIVED_FOREGROUND_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?(?:dev|start|serve|watch)\b",
        r"\bdocker\s+compose\s+up\b",
        r"\bnext\s+dev\b",
        r"\bvite(?:\s|$)",
        r"\bnodemon\b",
        r"\buvicorn\b",
        r"\bgunicorn\b",
        r"\bpython(?:3)?\s+-m\s+http\.server\b",
    )
)

# Shell backgrounding operators
_SHELL_LEVEL_BACKGROUND_RE = re.compile(
    r"(?:^|[;&|]\s*|&&\s*|\|\|\s*|\$\(\s*)(?:nohup|disown|setsid)\b",
    re.IGNORECASE | re.MULTILINE,
)
_INLINE_BACKGROUND_AMP_RE = re.compile(r"\s&\s")
_TRAILING_BACKGROUND_AMP_RE = re.compile(r"\s&\s*(?:#.*)?$")

# Signal-death notes
_SIGNAL_EXIT_NOTES: dict[int, str] = {
    3: "SIGQUIT (quit from keyboard)",
    4: "SIGILL (illegal instruction — corrupt binary or wrong architecture)",
    6: "SIGABRT (abort — assertion failure or fatal runtime error)",
    7: "SIGBUS (bus error — misaligned or unmapped memory access)",
    8: "SIGFPE (fatal arithmetic error, e.g. division by zero)",
    9: "SIGKILL — often the kernel OOM killer on memory exhaustion, or explicit kill -9",
    11: "SIGSEGV (segmentation fault — the program crashed)",
    13: "SIGPIPE (wrote to a closed pipe)",
    15: "SIGTERM (terminated — kill or timeout requested it to stop)",
    24: "SIGXCPU (CPU time limit exceeded)",
    25: "SIGXFSZ (file size limit exceeded)",
}

# Informational non-zero exit codes (not real failures)
_EXIT_CODE_SEMANTICS: dict[str, dict[int, str]] = {
    "grep": {1: "No matches found (informational, not an error)"},
    "egrep": {1: "No matches found (informational, not an error)"},
    "rg": {1: "No matches found (informational, not an error)"},
    "diff": {1: "Files differ (expected, not an error)"},
    "git": {1: "Non-zero exit (often normal — e.g. 'git diff' when changes exist)"},
}


def strip_ansi(text: str) -> str:
    """Remove ANSI color and control escape sequences from output."""
    if not text:
        return ""
    return _ANSI_ESCAPE_RE.sub("", text)


def truncate_head_tail(
    output: str,
    max_chars: int = MAX_COMMAND_OUTPUT_CHARS,
    head_ratio: float = 0.5,
    stream_name: str = "output",
) -> str:
    """Truncate output keeping both head and tail so headers and summaries are preserved."""
    if len(output) <= max_chars:
        return output
    head_len = int(max_chars * head_ratio)
    tail_len = max_chars - head_len
    omitted = len(output) - (head_len + tail_len)
    marker = (
        f"\n... [{stream_name} truncated: output exceeded size limit - "
        f"{omitted:,} characters omitted] ...\n"
    )
    return output[:head_len] + marker + output[-tail_len:]


def _strip_quotes(command: str) -> str:
    """Mask quoted string literals so keywords inside strings aren't falsely matched."""
    result = re.sub(r"'[^']*'", "''", command)
    result = re.sub(r'"(?:[^"\\]|\\.)*"', '""', result)
    return re.sub(r"`[^`]*`", "``", result)


def _looks_like_help_or_version_command(command: str) -> bool:
    """Informational flags that should never be blocked."""
    norm = " ".join(command.lower().split())
    return (
        " --help" in norm
        or norm.endswith(" -h")
        or " --version" in norm
        or norm.endswith(" -v")
    )


def validate_command(command: str) -> Optional[str]:
    """Pre-execution guardrails against long-lived servers and background operators.

    Returns:
        Error message if blocked, or None if permitted.
    """
    if _looks_like_help_or_version_command(command):
        return None

    unquoted = _strip_quotes(command)

    if (
        _SHELL_LEVEL_BACKGROUND_RE.search(unquoted)
        or _INLINE_BACKGROUND_AMP_RE.search(unquoted)
        or _TRAILING_BACKGROUND_AMP_RE.search(unquoted)
    ):
        return (
            "Blocked: Foreground command uses background operators ('&', 'nohup', 'disown'). "
            "Autonomous agents must run bounded foreground commands to inspect their results."
        )

    if any(p.search(unquoted) for p in _LONG_LIVED_FOREGROUND_PATTERNS):
        return (
            "Blocked: Command appears to start a persistent server or watch process "
            "(e.g. dev/serve/watch/http.server). Running long-lived foreground processes will hang "
            "the agent execution turn. Run bounded tasks (builds, tests, linters, checks) instead."
        )

    return None


def _interpret_exit_code(command: str, exit_code: int) -> Optional[str]:
    """Provide explanatory note for non-zero exit codes (signals or informational)."""
    if exit_code == 0:
        return None

    if exit_code < 0:
        signum = -exit_code
        note = _SIGNAL_EXIT_NOTES.get(signum)
        if note:
            return f"Command terminated by signal {signum}: {note}"
        return f"Command terminated by signal {signum}"

    if exit_code > 128:
        signum = exit_code - 128
        note = _SIGNAL_EXIT_NOTES.get(signum)
        if note:
            return f"Exit code {exit_code} (usually signal {signum}: {note})"

    # Extract base command
    parts = command.split()
    if parts:
        base_cmd = parts[0].split("/")[-1].split("\\")[-1].lower()
        return _EXIT_CODE_SEMANTICS.get(base_cmd, {}).get(exit_code)

    return None


def execute_command(
    workspace_root: Path,
    command: str,
    timeout: int = 60,
) -> str:
    """Execute a shell command within the workspace root directory."""
    clean_cmd = command.strip()
    if not clean_cmd:
        return "Error: Command cannot be empty."

    # Validate against command guardrails (dev servers, & backgrounding)
    guard_error = validate_command(clean_cmd)
    if guard_error:
        return f"Error: {guard_error}"

    # Clamp timeout between 1s and 300s
    actual_timeout = max(1, min(timeout, 300))

    try:
        proc = subprocess.run(
            clean_cmd,
            shell=True,
            cwd=str(workspace_root.resolve()),
            capture_output=True,
            text=True,
            timeout=actual_timeout,
            stdin=subprocess.DEVNULL,
        )

        stdout = strip_ansi(proc.stdout or "")
        stderr = strip_ansi(proc.stderr or "")
        exit_code = proc.returncode

        # Sanitize sensitive environment variables and keys from outputs
        stdout = sanitize_sensitive_text(stdout)
        stderr = sanitize_sensitive_text(stderr)

        # Build structured output
        output_parts: list[str] = [f"Exit code: {exit_code}"]

        exit_note = _interpret_exit_code(clean_cmd, exit_code)
        if exit_note:
            output_parts.append(f"Note: {exit_note}")

        if stdout.strip():
            trimmed_stdout = stdout.strip()
            if len(trimmed_stdout) > MAX_COMMAND_OUTPUT_CHARS:
                trimmed_stdout = truncate_head_tail(
                    trimmed_stdout, MAX_COMMAND_OUTPUT_CHARS, stream_name="stdout"
                )
            output_parts.append(f"STDOUT:\n{trimmed_stdout}")

        if stderr.strip():
            trimmed_stderr = stderr.strip()
            if len(trimmed_stderr) > MAX_COMMAND_OUTPUT_CHARS:
                trimmed_stderr = truncate_head_tail(
                    trimmed_stderr, MAX_COMMAND_OUTPUT_CHARS, stream_name="stderr"
                )
            output_parts.append(f"STDERR:\n{trimmed_stderr}")

        if not stdout.strip() and not stderr.strip():
            output_parts.append("(Command produced no output)")

        return "\n\n".join(output_parts)

    except subprocess.TimeoutExpired:
        return (
            f"Error: Command timed out after {actual_timeout} seconds: '{clean_cmd}'"
        )
    except Exception as exc:
        clean_exc = sanitize_sensitive_text(str(exc))
        return f"Error executing command: {clean_exc}"
