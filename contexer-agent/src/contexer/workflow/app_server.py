"""Local HTTP serving for static target projects.

Static projects are observed over a real HTTP origin rather than ``file://``:
under ``file://`` the browser blocks ES modules, ``fetch()`` of local files and
some storage APIs, so a correct implementation would fail verification.
"""

from __future__ import annotations

import functools
import http.server
import threading
from pathlib import Path
from typing import Any, Optional


class _QuietNoCacheHandler(http.server.SimpleHTTPRequestHandler):
    """Serves files without request logging and without browser caching."""

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - signature fixed by base class
        return


class StaticAppServer:
    """Serves a directory on ``127.0.0.1`` at an OS-assigned port.

    Files are read per request, so files the coding agent creates or repairs
    after the server starts are served immediately.
    """

    def __init__(self, root: str | Path, host: str = "127.0.0.1", port: int = 0) -> None:
        self.root = Path(root).resolve()
        self.host = host
        self.port = port
        self._server: Optional[http.server.ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def url(self) -> str:
        if self._server is None:
            raise RuntimeError("StaticAppServer is not running")
        return f"http://{self.host}:{self._server.server_address[1]}/"

    def start(self) -> str:
        """Start serving in a daemon thread and return the base URL."""
        if self._server is not None:
            return self.url
        self.root.mkdir(parents=True, exist_ok=True)
        handler = functools.partial(_QuietNoCacheHandler, directory=str(self.root))
        self._server = http.server.ThreadingHTTPServer((self.host, self.port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, name="contexer-static-server", daemon=True)
        self._thread.start()
        return self.url

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None

    def __enter__(self) -> StaticAppServer:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
