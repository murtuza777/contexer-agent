"""File store for contracts under ``<project>/.contexer/contracts``.

Contracts are meant to be committed next to the code they describe, so a
reviewer sees a change to "done" in the same pull request as the code. The
rest of ``.contexer/`` (runs, snapshots, the run database) stays local; the
store writes a ``.gitignore`` that keeps it that way.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from pydantic import ValidationError

from contexer.contract.models import Contract, slugify

CONTEXER_DIR = ".contexer"
CONTRACTS_DIR = "contracts"

# Ignore everything in .contexer/ except this file and the contracts.
_GITIGNORE = "/*\n!/.gitignore\n!/contracts/\n"


class ContractError(Exception):
    """A contract could not be found, read or written."""


class ContractStore:
    """Loads and saves the contracts of one project."""

    def __init__(self, project_dir: str | Path) -> None:
        self.project_dir = Path(project_dir).resolve()
        self.contexer_dir = self.project_dir / CONTEXER_DIR
        self.root = self.contexer_dir / CONTRACTS_DIR

    def path_for(self, contract_id: str) -> Path:
        return self.root / f"{contract_id}.json"

    def exists(self, contract_id: str) -> bool:
        return self.path_for(contract_id).is_file()

    def list(self) -> list[Contract]:
        if not self.root.is_dir():
            return []
        return [self._read(path) for path in sorted(self.root.glob("*.json"))]

    def load(self, ref: str) -> Contract:
        """Load by id, or by a path to a contract file."""
        candidate = Path(ref)
        if candidate.suffix == ".json" and candidate.is_file():
            return self._read(candidate)
        path = self.path_for(ref)
        if not path.is_file():
            known = ", ".join(c.id for c in self.list()) or "none"
            raise ContractError(f"No contract '{ref}' in {self.root} (known: {known})")
        return self._read(path)

    def save(self, contract: Contract) -> Path:
        ensure_contexer_dir(self.project_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.path_for(contract.id)
        text = json.dumps(contract.to_file_dict(), indent=2, ensure_ascii=False) + "\n"
        path.write_text(text, encoding="utf-8")
        return path

    def unique_id(self, text: str) -> str:
        base = slugify(text)
        candidate, n = base, 2
        while self.exists(candidate):
            candidate, n = f"{base}-{n}", n + 1
        return candidate

    def approve(self, ref: str, by: str | None = None) -> Contract:
        contract = self.load(ref).approved_by(by or current_user(self.project_dir))
        self.save(contract)
        return contract

    def _read(self, path: Path) -> Contract:
        try:
            return Contract.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise ContractError(f"Invalid contract file {path}: {exc}") from exc


def ensure_contexer_dir(project_dir: str | Path) -> Path:
    """Create ``.contexer/`` with its ``.gitignore``; return the directory."""
    root = Path(project_dir).resolve() / CONTEXER_DIR
    root.mkdir(parents=True, exist_ok=True)
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(_GITIGNORE, encoding="utf-8")
    return root


def current_user(project_dir: str | Path | None = None) -> str:
    """The approver's name: git ``user.name``, else the OS user."""
    try:
        out = subprocess.run(
            ["git", "config", "user.name"],
            cwd=str(project_dir) if project_dir else None,
            capture_output=True,
            text=True,
            timeout=5,
        )
        name = out.stdout.strip()
        if name:
            return name
    except (OSError, subprocess.SubprocessError):
        pass
    return os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"
