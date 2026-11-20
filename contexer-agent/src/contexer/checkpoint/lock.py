"""One run at a time in a project.

Two runs in one folder share the snapshot repository and the files. One
run's revert would wipe what the other's coding agent is writing. The lock
is a file with the process id of the run that holds it; a lock whose
process is gone is taken over.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from collections.abc import Iterator
from pathlib import Path

LOCK_FILE = Path(".contexer") / "run.lock"


class RunLocked(Exception):
    """Another run is working in this project."""


@contextlib.contextmanager
def run_lock(project_dir: str | Path, run: str = "") -> Iterator[None]:
    """Hold the project's run lock for the length of the block. Raises :class:`RunLocked` if a live run has it."""
    path = Path(project_dir).resolve() / LOCK_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    holder = _holder(path)
    if holder is not None and _alive(_pid(holder)):
        raise RunLocked(
            f"run {holder.get('run') or '(unnamed)'} is already working in this project (process {_pid(holder)}). "
            "Wait for it, or stop it with Ctrl+C in its terminal."
        )
    path.write_text(json.dumps({"pid": os.getpid(), "run": run}), encoding="utf-8")
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            path.unlink()


def _pid(holder: dict[str, object]) -> int:
    try:
        return int(str(holder.get("pid") or 0))
    except ValueError:
        return 0


def _holder(path: Path) -> dict[str, object] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        # os.kill(pid, 0) would END the process on Windows; ask for its exit code instead.
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
