"""Child processes that are always stopped together with everything they spawn.

Dev servers and coding agents both start process trees (npm → node → workers,
claude → shells → tools). Stopping only the top process leaves the rest
running, holding ports and files. On Windows each tree goes into a
kill-on-close Job Object; on POSIX it gets its own session and is signalled
as a process group.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from contexer.appserver.winjob import KillOnCloseJob


_CMD = ["cmd.exe", "/d", "/s", "/c"]


def popen_args(argv: list[str]) -> list[str] | str:
    """What to hand ``Popen`` for ``argv``.

    ``cmd.exe /c`` parses its own command line, and ``subprocess`` would escape
    quotes inside a shell command as ``\\"``, which cmd does not understand, so
    a command such as ``"C:\\Program Files\\nodejs\\node.exe" server.js`` failed.
    With ``/s`` cmd strips one pair of outer quotes and runs the rest verbatim.
    """
    if sys.platform == "win32" and len(argv) == len(_CMD) + 1 and argv[: len(_CMD)] == _CMD:
        return f'{" ".join(_CMD)} "{argv[-1]}"'
    return argv


class ProcessTree:
    """A ``Popen`` plus whatever is needed to stop its descendants."""

    def __init__(self, proc: subprocess.Popen[bytes], job: Optional[KillOnCloseJob]) -> None:
        self.proc = proc
        self._job = job

    @property
    def pid(self) -> int:
        return self.proc.pid

    def poll(self) -> Optional[int]:
        return self.proc.poll()

    def kill(self, grace: float = 10.0) -> None:
        """Stop the whole tree; safe to call more than once."""
        proc = self.proc
        if proc.poll() is None:
            if sys.platform == "win32":
                if self._job is not None:
                    self._job.terminate()
                else:
                    subprocess.run(
                        ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
            else:
                _signal_group(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                if sys.platform != "win32":
                    _signal_group(proc.pid, signal.SIGKILL)
                proc.kill()
                proc.wait(timeout=5)
        if self._job is not None:
            self._job.close()
            self._job = None


def spawn_tree(
    argv: list[str],
    cwd: str | Path,
    env: Optional[dict[str, str]] = None,
    *,
    stdin: Any = subprocess.DEVNULL,
) -> ProcessTree:
    """Start ``argv`` with merged stdout/stderr piped, in its own killable tree."""
    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        popen_args(argv),
        cwd=str(cwd),
        env=env,
        stdin=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        **kwargs,
    )
    job = _assign_to_job(proc) if sys.platform == "win32" else None
    return ProcessTree(proc, job)


def _assign_to_job(proc: subprocess.Popen[bytes]) -> Optional[KillOnCloseJob]:
    try:
        from contexer.appserver.winjob import KillOnCloseJob

        job = KillOnCloseJob()
        job.assign(int(proc._handle))  # type: ignore[attr-defined]
        return job
    except OSError:
        return None  # ProcessTree.kill falls back to taskkill /T


def _signal_group(pid: int, sig: int) -> None:
    try:
        os.killpg(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass
