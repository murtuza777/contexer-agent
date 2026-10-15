"""Run a project's dev server for the duration of a verification.

Readiness follows Playwright's ``webServer`` rule: a 2xx, 3xx or 400-403
response means the server is up. Both ``127.0.0.1`` and ``localhost`` are
probed, and if the server announces a different port in its log than the one
it was given, that URL is probed too. If the process exits first, the error
carries the last log lines, because build errors are the most common reason a
dev server never becomes ready.
"""

from __future__ import annotations

import collections
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import IO, Callable, Optional

import httpx

from contexer.appserver.detect import StartPlan
from contexer.procutil import ProcessTree, spawn_tree

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_ANNOUNCED_URL = re.compile(r"https?://(?:localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0):(\d{2,5})")
_READY_STATUSES = set(range(200, 400)) | {400, 401, 402, 403}
_LOG_LINES = 400
_INSTALL_TIMEOUT = 900.0


class DevServerError(Exception):
    def __init__(self, message: str, log_tail: str = "") -> None:
        super().__init__(message)
        self.log_tail = log_tail


class DevServer:
    """Starts, watches and stops one dev-server process tree."""

    def __init__(
        self,
        plan: StartPlan,
        log_path: Optional[Path] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.plan = plan
        self.log_path = log_path
        self.on_status = on_status or (lambda _msg: None)
        self.url: Optional[str] = None
        self._proc: Optional[ProcessTree] = None
        self._lines: collections.deque[str] = collections.deque(maxlen=_LOG_LINES)
        self._lock = threading.Lock()
        self._reader: Optional[threading.Thread] = None
        self._log_file: Optional[IO[str]] = None

    # -- lifecycle -------------------------------------------------------------

    def start(self) -> str:
        """Install dependencies if needed, start the server, and wait until it answers."""
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_file = open(self.log_path, "a", encoding="utf-8")  # noqa: SIM115 - closed in stop()
        if self.plan.install_argv and not (self.plan.cwd / "node_modules").is_dir():
            self._install()
        self.on_status(f"Starting `{self.plan.display}` on port {self.plan.port}")
        self._spawn()
        self.url = self._wait_until_ready()
        return self.url

    def stop(self) -> None:
        if self._proc is not None:
            self._proc.kill()
        if self._reader is not None:
            self._reader.join(timeout=5)
            self._reader = None
        self._proc = None
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None

    def restart(self) -> str:
        self.stop()
        return self.start()

    def ensure_running(self) -> str:
        """Restart the server if it died (an agent edit can crash it)."""
        if self.is_alive() and self.url:
            return self.url
        self.on_status("Dev server is not running; restarting it")
        return self.restart()

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def log_tail(self, lines: int = 80) -> str:
        with self._lock:
            return "\n".join(list(self._lines)[-lines:])

    def __enter__(self) -> DevServer:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    # -- internals ---------------------------------------------------------------

    def _install(self) -> None:
        assert self.plan.install_argv is not None
        display = " ".join([Path(self.plan.install_argv[0]).stem, *self.plan.install_argv[1:]])
        self.on_status(f"Installing dependencies (`{display}`)")
        self._record(f"$ {display}")
        try:
            proc = subprocess.run(
                self.plan.install_argv,
                cwd=self.plan.cwd,
                env=self._env(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=_INSTALL_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DevServerError(f"Dependency install failed: {exc}", self.log_tail()) from exc
        for line in proc.stdout.decode("utf-8", errors="replace").splitlines():
            self._record(line)
        if proc.returncode != 0:
            raise DevServerError(f"`{display}` exited with code {proc.returncode}", self.log_tail())

    def _spawn(self) -> None:
        self._record(f"$ {self.plan.display}")
        try:
            self._proc = spawn_tree(self.plan.argv, self.plan.cwd, self._env())
        except OSError as exc:
            raise DevServerError(f"Could not run `{self.plan.display}`: {exc}") from exc
        self._reader = threading.Thread(target=self._pump, args=(self._proc.proc,), name="contexer-devserver-log", daemon=True)
        self._reader.start()

    def _pump(self, proc: subprocess.Popen[bytes]) -> None:
        assert proc.stdout is not None
        for raw in iter(proc.stdout.readline, b""):
            self._record(_ANSI.sub("", raw.decode("utf-8", errors="replace")).rstrip())

    def _record(self, line: str) -> None:
        with self._lock:
            self._lines.append(line)
            if self._log_file is not None:
                self._log_file.write(line + "\n")
                self._log_file.flush()

    def _wait_until_ready(self) -> str:
        deadline = time.monotonic() + self.plan.ready_timeout
        path = self.plan.ready_path if self.plan.ready_path.startswith("/") else f"/{self.plan.ready_path}"
        with httpx.Client(timeout=10.0, follow_redirects=False) as client:
            while time.monotonic() < deadline:
                proc = self._proc
                code = proc.poll() if proc is not None else "?"
                if code is not None:
                    if self._reader is not None:
                        self._reader.join(timeout=2)  # let the last log lines land
                    raise DevServerError(
                        f"`{self.plan.display}` exited with code {code} before it was ready", self.log_tail()
                    )
                for base in self._candidate_bases():
                    try:
                        response = client.get(base.rstrip("/") + path)
                    except httpx.HTTPError:
                        continue
                    if response.status_code in _READY_STATUSES:
                        return base if base.endswith("/") else base + "/"
                time.sleep(0.5)
        raise DevServerError(
            f"`{self.plan.display}` did not answer on port {self.plan.port} within {self.plan.ready_timeout:.0f}s",
            self.log_tail(),
        )

    def _candidate_bases(self) -> list[str]:
        ports = [self.plan.port]
        announced = _ANNOUNCED_URL.findall(self.log_tail(200))
        ports.extend(int(p) for p in announced if int(p) not in ports)
        bases: list[str] = []
        for port in ports:
            bases.extend([f"http://127.0.0.1:{port}/", f"http://localhost:{port}/"])
        return bases

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update(self.plan.env)
        env.setdefault("FORCE_COLOR", "0")
        env.setdefault("CI", "1")  # no interactive prompts from dev tooling
        return env
