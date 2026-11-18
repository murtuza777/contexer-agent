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
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

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


# Variables a hosting agent session sets for its own plumbing, or to tell tools an agent is driving.
# Contexer is often started from a coding agent's terminal; what it starts is not that session.
AGENT_SESSION_PREFIXES = ("CLAUDE_CODE_", "CLAUDE_AGENT_SDK_")
AGENT_SESSION_VARS = frozenset({"CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT", "CLAUDE_PREVIEW_CLASSIFIER_FLOOR", "AI_AGENT"})


def without_agent_session(env: dict[str, str]) -> dict[str, str]:
    """``env`` as a person's own terminal would have it: no markers of a hosting agent session."""
    return {
        name: value
        for name, value in env.items()
        if name not in AGENT_SESSION_VARS and not name.startswith(AGENT_SESSION_PREFIXES)
    }


class ProcessTree:
    """A ``Popen`` plus whatever is needed to stop its descendants."""

    def __init__(self, proc: subprocess.Popen[bytes], job: KillOnCloseJob | None) -> None:
        self.proc = proc
        self._job = job
        self._lock = threading.Lock()  # Ctrl+C may stop a tree while its worker thread is stopping it

    @property
    def pid(self) -> int:
        return self.proc.pid

    def poll(self) -> int | None:
        return self.proc.poll()

    def kill(self, grace: float = 10.0) -> None:
        """Stop the whole tree; safe to call more than once, and from more than one thread."""
        with self._lock:
            self._kill(grace)

    def _kill(self, grace: float) -> None:
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
    env: dict[str, str] | None = None,
    *,
    stdin: Any = subprocess.DEVNULL,
) -> ProcessTree:
    """Start ``argv`` with merged stdout/stderr piped, in its own killable tree."""
    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        # Start suspended: a process created before the job is attached stays outside it
        # forever, and cmd.exe can start its child (node → opencode serve) in that instant.
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW | _CREATE_SUSPENDED
        )
    else:
        kwargs["start_new_session"] = True
    proc: subprocess.Popen[bytes] = subprocess.Popen(  # pyright: ignore[reportAssignmentType]
        popen_args(argv),
        cwd=str(cwd),
        env=env,
        stdin=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        **kwargs,
    )
    job = None
    if sys.platform == "win32":
        try:
            job = _assign_to_job(proc)
        finally:
            _resume(proc)
    return ProcessTree(proc, job)


_CREATE_SUSPENDED = 0x00000004


def _resume(proc: subprocess.Popen[bytes]) -> None:
    """Resume a process created suspended (subprocess keeps only its process handle, not the thread's)."""
    if sys.platform != "win32":  # only Windows starts the process suspended
        return
    import ctypes

    ntdll = ctypes.WinDLL("ntdll")
    ntdll.NtResumeProcess.argtypes = [ctypes.c_void_p]
    status = ntdll.NtResumeProcess(ctypes.c_void_p(int(proc._handle)))  # type: ignore[attr-defined]
    if status != 0:
        proc.kill()
        raise OSError(f"could not resume the child process (NTSTATUS {status:#x})")


def _assign_to_job(proc: subprocess.Popen[bytes]) -> KillOnCloseJob | None:
    try:
        from contexer.appserver.winjob import KillOnCloseJob

        job = KillOnCloseJob()
        job.assign(int(proc._handle))  # type: ignore[attr-defined]
        return job
    except OSError:
        return None  # ProcessTree.kill falls back to taskkill /T


def _signal_group(pid: int, sig: int) -> None:
    if sys.platform == "win32":  # process groups are signalled on POSIX; Windows uses the job object
        return
    try:
        os.killpg(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass
