"""One run at a time in a project.

Two runs in one folder share the snapshot repository and the files. One
run's revert would wipe what the other's coding agent is writing. The lock
is a file with the process id of the run that holds it; a lock whose
process is gone is taken over. The file is created with an exclusive open,
so of two runs that start at the same moment exactly one gets it.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import time
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
    _take(path, json.dumps({"pid": os.getpid(), "run": run}))
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            path.unlink()


# A lock file that cannot be read and is younger than this is being written by a run that is starting.
_BEING_WRITTEN_SECONDS = 10.0


def _take(path: Path, body: str) -> None:
    """Create the lock file, or raise :class:`RunLocked`. Creating it is the test: there is no look-then-write."""
    for _ in range(2):
        try:
            handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError:
            holder = _holder(path)
            if holder is not None and _alive(_pid(holder)):
                raise RunLocked(
                    f"run {holder.get('run') or '(unnamed)'} is already working in this project (process {_pid(holder)}). "
                    "Wait for it, or stop it with Ctrl+C in its terminal."
                ) from None
            if holder is None and _young(path):
                raise RunLocked("another run is starting in this project at this moment. Wait for it, or try again.") from None
            # Left by a process that is gone. Remove it only if it is still the file that was judged.
            if _holder(path) == holder:
                with contextlib.suppress(OSError):
                    path.unlink()
            continue
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(body)
        return
    raise RunLocked("another run took this project's lock at the same moment. Wait for it, or try again.")


def _young(path: Path) -> bool:
    try:
        return time.time() - path.stat().st_mtime < _BEING_WRITTEN_SECONDS
    except OSError:
        return False


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
