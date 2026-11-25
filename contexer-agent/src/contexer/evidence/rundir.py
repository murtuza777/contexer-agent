"""Per-run evidence directories under ``<project>/.contexer/runs``."""

from __future__ import annotations

import contextlib
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from contexer.contract.store import ensure_contexer_dir

RUNS_DIR = "runs"


@dataclass(frozen=True)
class RunDir:
    run_id: str
    path: Path

    @classmethod
    def create(cls, project_dir: str | Path) -> RunDir:
        root = ensure_contexer_dir(project_dir) / RUNS_DIR
        run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"
        path = root / run_id
        path.mkdir(parents=True, exist_ok=False)
        return cls(run_id=run_id, path=path)

    def checks_dir(self, contract_id: str) -> Path:
        return self.path / "checks" / contract_id

    @property
    def report_html(self) -> Path:
        return self.path / "report.html"

    @property
    def result_json(self) -> Path:
        return self.path / "result.json"

    @property
    def server_log(self) -> Path:
        return self.path / "server.log"


def write_whole(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` so that a reader sees the old file or the new one, never half of one.

    A resume reads these files. A process killed in the middle of a plain write leaves a file that cannot
    be read; here the text goes to a temporary name beside it and is renamed over the old file.
    """
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            with contextlib.suppress(OSError):  # not every filesystem can; the rename still holds
                os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            temporary.unlink()
        raise
