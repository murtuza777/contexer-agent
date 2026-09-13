"""Filesystem operations restricted to the current workspace root.

Enforces workspace boundary sandboxing, prevents directory traversal attacks,
safeguards sensitive files (.env), and enforces size limits.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Optional

# Maximum file size allowed for read operations (100 KB)
MAX_FILE_SIZE_BYTES = 100 * 1024
# Maximum output characters for search operations
MAX_SEARCH_OUTPUT_CHARS = 20_000
# Directories ignored during default search/listing
IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".next",
    "build",
    "dist",
    ".idea",
    ".vscode",
}


def _canonical_str(p: Path | str) -> str:
    """Return the canonical, real-path string with normalized case."""
    return os.path.normcase(os.path.realpath(os.path.abspath(str(p))))


def _is_binary_file(path: Path) -> bool:
    """Detect if a file contains binary content by scanning the first 1024 bytes."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(1024)
            return b"\x00" in chunk
    except Exception:
        return False


def _resolve_safe_path(workspace_root: Path, user_path: str) -> Path:
    """Resolve user path against workspace root, preventing traversal and secret leakage.

    Enforces:
      - Traversal defense (../../)
      - Symlink resolution escapes (os.path.realpath / normcase)
      - Absolute path breakout
      - Direct access to .env and credentials

    Raises:
        PermissionError: If path escapes workspace or accesses protected files (.env).
    """
    clean_str = user_path.strip()
    if not clean_str:
        clean_str = "."

    root_resolved = Path(os.path.realpath(str(workspace_root.resolve())))
    canonical_root = _canonical_str(root_resolved)

    # Check if absolute path was passed
    candidate = Path(clean_str)
    if candidate.is_absolute():
        target = candidate
    else:
        target = workspace_root / clean_str

    canonical_target = _canonical_str(target)

    # Verify target is strictly within the workspace root using commonpath
    try:
        common = os.path.commonpath([canonical_root, canonical_target])
        if common != canonical_root:
            raise PermissionError(
                f"Access denied: path '{user_path}' resolves outside the workspace root ({workspace_root})."
            )
    except ValueError:
        raise PermissionError(
            f"Access denied: path '{user_path}' resolves outside the workspace root ({workspace_root})."
        )

    # Additional relative_to check using resolved real paths
    resolved_target = Path(os.path.realpath(str(target)))
    try:
        resolved_target.relative_to(root_resolved)
    except ValueError:
        raise PermissionError(
            f"Access denied: path '{user_path}' resolves outside the workspace root ({workspace_root})."
        )

    # Prevent reading/writing .env files directly
    for part in resolved_target.parts:
        if part == ".env" or part.startswith(".env."):
            raise PermissionError(
                "Access denied: accessing or modifying .env files via tools is prohibited."
            )
    for part in Path(clean_str).parts:
        if part == ".env" or part.startswith(".env."):
            raise PermissionError(
                "Access denied: accessing or modifying .env files via tools is prohibited."
            )

    return resolved_target


def list_directory(workspace_root: Path, path: str = ".") -> str:
    """List directory contents within the workspace."""
    try:
        target = _resolve_safe_path(workspace_root, path)
    except PermissionError as err:
        return f"Error: {err}"

    if not target.exists():
        return f"Error: Directory '{path}' does not exist."
    if not target.is_dir():
        return f"Error: '{path}' is a file, not a directory."

    items: list[str] = []
    try:
        for entry in sorted(target.iterdir()):
            if (entry.name in IGNORED_DIRS and path == ".") or entry.name == ".env" or entry.name.startswith(".env."):
                continue
            if entry.is_dir():
                items.append(f"[DIR]  {entry.name}/")
            else:
                size_str = f"{entry.stat().st_size} B"
                items.append(f"[FILE] {entry.name} ({size_str})")
    except Exception as exc:
        return f"Error listing directory '{path}': {exc}"

    if not items:
        return f"Directory '{path}' is empty."

    rel = target.relative_to(workspace_root.resolve())
    header = f"Contents of '{rel if str(rel) != '.' else '.'}':\n"
    return header + "\n".join(items)


def read_file(
    workspace_root: Path,
    path: str,
    offset: int = 0,
    limit: int = 500,
) -> str:
    """Read a slice of lines from a file in the workspace."""
    try:
        target = _resolve_safe_path(workspace_root, path)
    except PermissionError as err:
        return f"Error: {err}"

    if not target.exists():
        return f"Error: File '{path}' does not exist."
    if not target.is_file():
        return f"Error: '{path}' is a directory, not a file."

    if _is_binary_file(target):
        return f"Error: Cannot read '{path}': file appears to be binary."

    # Size limit check
    file_size = target.stat().st_size
    if file_size > MAX_FILE_SIZE_BYTES and offset == 0 and limit >= 500:
        return (
            f"Error: File '{path}' ({file_size} bytes) exceeds maximum allowable size "
            f"({MAX_FILE_SIZE_BYTES} bytes). Specify offset and limit to read in chunks, or use search_files."
        )

    lines: list[str] = []
    total_lines = 0
    try:
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            for idx, line in enumerate(f):
                total_lines += 1
                if idx >= offset and len(lines) < limit:
                    lines.append(line.rstrip("\r\n"))
    except Exception as exc:
        return f"Error reading file '{path}': {exc}"

    if offset >= total_lines:
        return f"Offset {offset} is beyond end of file ({total_lines} total lines)."

    numbered_lines = [
        f"{offset + idx + 1:4d} | {line}" for idx, line in enumerate(lines)
    ]

    truncated_note = ""
    if offset + limit < total_lines:
        remaining = total_lines - (offset + limit)
        truncated_note = f"\n... [{remaining} more lines remaining]"

    return "\n".join(numbered_lines) + truncated_note


def write_file(workspace_root: Path, path: str, content: str) -> str:
    """Write text content to a file in the workspace."""
    try:
        target = _resolve_safe_path(workspace_root, path)
    except PermissionError as err:
        return f"Error: {err}"

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} characters to '{path}'."
    except Exception as exc:
        return f"Error writing to file '{path}': {exc}"


def search_files(workspace_root: Path, pattern: str, path: str = ".") -> str:
    """Search for pattern in files within the workspace using ripgrep or Python fallback."""
    try:
        target = _resolve_safe_path(workspace_root, path)
    except PermissionError as err:
        return f"Error: {err}"

    if not target.exists():
        return f"Error: Path '{path}' does not exist."

    # 1. Try ripgrep (rg) if installed
    rg_executable = shutil.which("rg")
    if rg_executable:
        try:
            cmd = [
                rg_executable,
                "--line-number",
                "--max-count",
                "50",
                "--max-columns",
                "200",
                "--glob",
                "!{.git,.venv,venv,node_modules,__pycache__}/*",
                "-e",
                pattern,
                str(target),
            ]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15,
                cwd=str(workspace_root),
            )
            output = proc.stdout.strip()
            if output:
                # Replace absolute path prefixes with relative paths
                clean_output = output.replace(str(workspace_root) + os.sep, "")
                if len(clean_output) > MAX_SEARCH_OUTPUT_CHARS:
                    clean_output = clean_output[:MAX_SEARCH_OUTPUT_CHARS] + "\n... [Search results truncated]"
                return clean_output
            if proc.returncode == 1:
                return f"No matches found for pattern '{pattern}' in '{path}'."
        except Exception:
            pass  # Fall through to pure-Python search

    # 2. Pure Python fallback search
    results: list[str] = []
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error:
        # Fallback to literal search if pattern is not valid regex
        regex = re.compile(re.escape(pattern), re.IGNORECASE)

    root_res = workspace_root.resolve()

    def _walk_and_search(dir_path: Path) -> None:
        for root, dirs, files in os.walk(dir_path):
            # Prune ignored directories
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
            for file in files:
                if len(results) >= 50:
                    return
                if (
                    file.startswith(".")
                    or file == ".env"
                    or file.startswith(".env.")
                    or file.endswith((".pyc", ".png", ".jpg", ".ico", ".bin", ".exe", ".dll", ".so"))
                ):
                    continue
                file_path = Path(root) / file
                try:
                    if file_path.stat().st_size > MAX_FILE_SIZE_BYTES or _is_binary_file(file_path):
                        continue
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    for line_idx, line in enumerate(content.splitlines(), start=1):
                        if regex.search(line):
                            rel_file = file_path.relative_to(root_res)
                            results.append(f"{rel_file}:{line_idx}: {line[:200]}")
                            if len(results) >= 50:
                                return
                except Exception:
                    continue

    _walk_and_search(target)

    if not results:
        return f"No matches found for pattern '{pattern}' in '{path}'."

    output = "\n".join(results)
    if len(output) > MAX_SEARCH_OUTPUT_CHARS:
        output = output[:MAX_SEARCH_OUTPUT_CHARS] + "\n... [Search results truncated]"
    return output


def file_exists(workspace_root: Path, path: str) -> str:
    """Check whether a file or directory exists in the workspace."""
    try:
        target = _resolve_safe_path(workspace_root, path)
    except PermissionError as err:
        return f"Error: {err}"

    if not target.exists():
        return f"Path '{path}' does not exist."

    if target.is_dir():
        return f"Directory exists: '{path}'"
    size = target.stat().st_size
    return f"File exists: '{path}' ({size} bytes)"
