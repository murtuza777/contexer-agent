"""``[app] reset``: put the app's server-side data back before each check.

Every check gets a fresh browser, but they all talk to the same running app,
so data one check saves on the server (a message, an order, a user) is still
there for the next. A reset command, such as ``npm run db:reset`` or
``curl -X POST {url}/api/test/reset``, makes each check start from the same
data. It must leave the ``[auth]`` test account in place.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from contexer.appserver.detect import shell_argv
from contexer.procutil import popen_args

RESET_TIMEOUT_SECONDS = 120.0


def reset_command(template: str, url: str) -> str:
    """Fill ``{url}`` (no trailing slash) and ``{port}`` from the running app."""
    port = urlparse(url).port
    return template.replace("{url}", url.rstrip("/")).replace("{port}", str(port or ""))


def run_reset(
    command: str,
    cwd: Path,
    env: Optional[dict[str, str]] = None,
    timeout: float = RESET_TIMEOUT_SECONDS,
) -> Optional[str]:
    """Run the reset command; ``None`` when it succeeded, else why it did not."""
    try:
        proc = subprocess.run(
            popen_args(shell_argv(command)),
            cwd=str(cwd),
            env={**os.environ, **(env or {})},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"`{command}` did not finish within {timeout:.0f}s"
    except OSError as exc:
        return f"`{command}` could not start: {exc}"
    if proc.returncode != 0:
        tail = proc.stdout.decode("utf-8", errors="replace").strip()[-300:]
        return f"`{command}` exited with code {proc.returncode}" + (f": {tail}" if tail else "")
    return None
