"""Per-run evidence directories under ``<project>/.contexer/runs``."""

from __future__ import annotations

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
