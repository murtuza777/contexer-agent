"""Read-only Git operations executed via the Git CLI.

Provides status, diff, log, and branch information without modifying
repository state. Destructive operations (commit, push, checkout, reset)
are strictly excluded.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from typing import Optional

from contexer.llm.base import sanitize_sensitive_text
from contexer.tools.terminal import strip_ansi, truncate_head_tail

MAX_GIT_OUTPUT_CHARS = 20_000

# Strict read-only whitelist of allowed top-level git commands
_ALLOWED_READONLY_GIT_COMMANDS = frozenset({
    "status",
    "diff",
    "log",
    "branch",
    "show",
    "rev-parse",
    "describe",
})


def _is_safe_read_only_git(args: list[str]) -> bool:
    """Verify that git arguments represent an allowed read-only inspection command."""
    if not args:
        return False
    primary = args[0].lower()
    if primary not in _ALLOWED_READONLY_GIT_COMMANDS:
        return False
    # If branch, ensure no mutating flags like -d, -D, -m, -M
    if primary == "branch":
        mutating_branch_flags = {"-d", "-D", "-m", "-M", "--delete", "--move"}
        if any(flag in args for flag in mutating_branch_flags):
            return False
    return True


def _run_git_command(workspace_root: Path, args: list[str]) -> str:
    """Execute a read-only git command in the workspace root."""
    if not _is_safe_read_only_git(args):
        first_cmd = args[0] if args else "empty"
        return (
            f"Blocked: Git operation 'git {first_cmd}' is mutating or disallowed. "
            "Contexer git tools are strictly read-only."
        )

    git_bin = shutil.which("git")
    if not git_bin:
        return "Error: 'git' executable not found on system PATH."

    try:
        proc = subprocess.run(
            [git_bin] + args,
            cwd=str(workspace_root.resolve()),
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
        )

        stdout = strip_ansi(sanitize_sensitive_text(proc.stdout or "")).strip()
        stderr = strip_ansi(sanitize_sensitive_text(proc.stderr or "")).strip()

        if proc.returncode != 0:
            return f"Git error (exit code {proc.returncode}):\n{stderr or stdout}"

        output = stdout if stdout else "(No output from git)"
        if len(output) > MAX_GIT_OUTPUT_CHARS:
            output = truncate_head_tail(output, MAX_GIT_OUTPUT_CHARS, stream_name="git output")
        return output

    except subprocess.TimeoutExpired:
        return f"Error: Git command timed out: git {' '.join(args)}"
    except Exception as exc:
        return f"Error executing git command: {exc}"


def git_status(workspace_root: Path) -> str:
    """Get the current working tree status."""
    return _run_git_command(workspace_root, ["status", "--short", "--branch"])


def git_diff(
    workspace_root: Path,
    cached: bool = False,
    path: Optional[str] = None,
) -> str:
    """Get unstaged or staged git diff, optionally restricted to a path."""
    args = ["diff"]
    if cached:
        args.append("--cached")
    if path:
        args.extend(["--", path.strip()])
    return _run_git_command(workspace_root, args)


def git_log(workspace_root: Path, max_count: int = 10) -> str:
    """Get recent commit history in oneline format."""
    count = max(1, min(max_count, 50))
    return _run_git_command(
        workspace_root,
        ["log", f"-n{count}", "--pretty=format:%h %ad | %s%d [%an]", "--date=short"],
    )


def git_branch(workspace_root: Path) -> str:
    """List local and remote branches."""
    return _run_git_command(workspace_root, ["branch", "-a"])
