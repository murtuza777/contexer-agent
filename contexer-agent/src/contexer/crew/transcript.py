"""A transcript of everything an agent did, and optional tracing.

Each agent writes ``agents/<name>.jsonl`` in the run folder: one JSON line
per model call and per tool call, with timing and token counts, between a
``start`` and an ``end`` line. It is the record a person reads to see why an
agent did what it did.

No secret reaches the file. Every string is masked with the same redaction
the checks use (``verification/checks.py``), for the values the caller names
plus every provider key and token in the environment, and anything shaped
like an API key.

Langfuse tracing is off unless ``LANGFUSE_PUBLIC_KEY`` and
``LANGFUSE_SECRET_KEY`` are set. With them unset the ``langfuse`` package is
never imported and nothing leaves the machine.
"""

from __future__ import annotations

import json
import os
import re
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from contexer.llm.base import sanitize_sensitive_text
from contexer.llm.catalog import PROVIDERS
from contexer.verification.checks import redact

AGENTS_DIR = "agents"

_TOKEN_VARIABLES = (
    "CONTEXER_GITHUB_TOKEN",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "CODEX_API_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_PUBLIC_KEY",
)
# A credential worth masking is longer than this; shorter values would blank ordinary words.
_MIN_SECRET_LENGTH = 6


def environment_secrets(env: Optional[Mapping[str, str]] = None) -> list[str]:
    """The provider keys and tokens set in the environment."""
    env = os.environ if env is None else env
    names = [spec.key_env for spec in PROVIDERS] + list(_TOKEN_VARIABLES)
    values = [env.get(name, "").strip() for name in names]
    return [value for value in values if len(value) >= _MIN_SECRET_LENGTH]


class Masker:
    """Replaces secret values in text and in nested data."""

    def __init__(self, secrets: Sequence[str] = (), env: Optional[Mapping[str, str]] = None) -> None:
        self.values = [*(s for s in secrets if s), *environment_secrets(env)]

    def text(self, text: str) -> str:
        return sanitize_sensitive_text(redact(text, self.values))

    def data(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, Mapping):
            return {self.text(str(key)): self.data(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.data(item) for item in value]
        return value


class Transcript:
    """Appends masked JSON lines to ``<run_dir>/agents/<agent>.jsonl``; does nothing without a run folder."""

    def __init__(self, run_dir: Optional[Path], agent: str, masker: Optional[Masker] = None) -> None:
        self.agent = agent
        self.masker = masker or Masker()
        self.path: Optional[Path] = None
        if run_dir is not None:
            self.path = Path(run_dir) / AGENTS_DIR / f"{_file_stem(agent)}.jsonl"
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: str, **fields: Any) -> None:
        if self.path is None:
            return
        line = {"at": _now(), "agent": self.agent, "event": event, **self.masker.data(fields)}
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")


def read_transcript(path: Path) -> list[dict[str, Any]]:
    """The lines of a transcript, oldest first."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def tracing_callbacks(env: Optional[Mapping[str, str]] = None) -> list[Any]:
    """LangChain callbacks that send traces to Langfuse, or none when it is not configured.

    Install the optional extra to use it: ``pip install "contexer-agent[tracing]"``.
    """
    env = os.environ if env is None else env
    if not (env.get("LANGFUSE_PUBLIC_KEY", "").strip() and env.get("LANGFUSE_SECRET_KEY", "").strip()):
        return []
    try:
        from langfuse.langchain import CallbackHandler
    except ImportError:
        warnings.warn(
            'LANGFUSE_* is set but the langfuse package is not installed: pip install "contexer-agent[tracing]". '
            "Tracing is off for this run.",
            stacklevel=2,
        )
        return []
    return [CallbackHandler()]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _file_stem(agent: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", agent).strip("-.") or "agent"
