"""A transcript of everything an agent did, and optional tracing.

Each agent writes ``agents/<name>.jsonl`` in the run folder: one JSON line
per model call and per tool call, with timing and token counts, between a
``start`` and an ``end`` line. It is the record a person reads to see why an
agent did what it did.

The run as a whole has one more file, ``trace.jsonl`` (``Trace``): every run
event, model call and tool call in order, with no content.

No secret reaches either file. Every string is masked with the same redaction
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
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from contexer.evidence.rundir import TRACE_FILE
from contexer.llm.base import sanitize_sensitive_text
from contexer.llm.catalog import PROVIDERS
from contexer.verification.checks import redact

AGENTS_DIR = "agents"
# The OpenTelemetry semantic conventions release whose generative-AI names the trace uses.
SEMCONV_VERSION = "1.40.0"

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


def environment_secrets(env: Mapping[str, str] | None = None) -> list[str]:
    """The provider keys and tokens set in the environment."""
    env = os.environ if env is None else env
    names = [spec.key_env for spec in PROVIDERS] + list(_TOKEN_VARIABLES)
    values = [env.get(name, "").strip() for name in names]
    return [value for value in values if len(value) >= _MIN_SECRET_LENGTH]


class Masker:
    """Replaces secret values in text and in nested data."""

    def __init__(self, secrets: Sequence[str] = (), env: Mapping[str, str] | None = None) -> None:
        # A list is kept, not copied: a secret the caller learns later (a password an agent
        # types) is masked from then on.
        self.secrets: Sequence[str] = secrets if isinstance(secrets, list) else list(secrets)
        self._environment = environment_secrets(env)

    @property
    def values(self) -> list[str]:
        return [*(s for s in self.secrets if s), *self._environment]

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

    def __init__(self, run_dir: Path | None, agent: str, masker: Masker | None = None) -> None:
        self.agent = agent
        self.masker = masker or Masker()
        self.path: Path | None = None
        if run_dir is not None:
            self.path = Path(run_dir) / AGENTS_DIR / f"{_file_stem(agent)}.jsonl"
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: str, **fields: Any) -> None:
        if self.path is None:
            return
        line = {"at": _now(), "agent": self.agent, "event": event, **self.masker.data(fields)}
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")


    def remask(self) -> None:
        """Mask the whole file again, for secrets that became known after a line was written."""
        _remask(self.path, self.masker)


class Trace:
    """Appends masked JSON lines to ``<run_dir>/trace.jsonl``; does nothing without a run folder.

    One file for the whole run: the engine writes each run event as the line ``--json`` prints, and
    every agent writes one line per model call and per tool call. Those two kinds carry a ``time`` and
    are named after OpenTelemetry's generative-AI conventions (``gen_ai.*``; what the conventions have
    no name for is ``contexer.*``). The first line says which version of the conventions.

    The trace holds numbers and names only: no prompt, no reply, no tool argument or result. Those are
    in the agent's own transcript, under the same agent and step.
    """

    def __init__(self, run_dir: Path | None, masker: Masker | None = None) -> None:
        self.masker = masker or Masker()
        self.path: Path | None = None
        if run_dir is not None:
            self.path = Path(run_dir) / TRACE_FILE
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.is_file() or self.path.stat().st_size == 0:
                self.write({"event": "trace", "time": _now(), "format": 1, "semconv": SEMCONV_VERSION})

    def write(self, line: Mapping[str, Any]) -> None:
        if self.path is None:
            return
        # ASCII only and in the given order, so a run event is byte for byte the line `--json` prints.
        text = json.dumps(self.masker.data(line), ensure_ascii=True, default=str)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(text + "\n")

    def call(self, event: str, **fields: Any) -> None:
        """A model call or a tool call: a line with the time it ended."""
        self.write({"event": event, "time": _now(), **fields})

    def remask(self) -> None:
        """Mask the whole file again, for secrets that became known after a line was written."""
        _remask(self.path, self.masker)


def repaired_calls(trace: Path) -> dict[str, int]:
    """How many tool calls each agent repaired, counted from a run's trace. Empty when it cannot be read."""
    counts: dict[str, int] = {}
    try:
        lines = read_transcript(trace)
    except (OSError, ValueError):
        return counts
    for line in lines:
        if line.get("contexer.tool.status") == "repaired":
            agent = str(line.get("gen_ai.agent.name") or "")
            counts[agent] = counts.get(agent, 0) + 1
    return counts


def _remask(path: Path | None, masker: Masker) -> None:
    if path is None or not path.is_file():
        return
    raw = path.read_text(encoding="utf-8")
    # A value inside a JSON string may be escaped; mask that spelling too.
    escaped = [json.dumps(value, ensure_ascii=False)[1:-1] for value in masker.values]
    masked = masker.text(redact(raw, escaped))
    if masked != raw:
        path.write_text(masked, encoding="utf-8", newline="\n")


def read_transcript(path: Path) -> list[dict[str, Any]]:
    """The lines of a transcript or a trace, oldest first."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def tracing_callbacks(env: Mapping[str, str] | None = None) -> list[Any]:
    """LangChain callbacks that send traces to Langfuse, or none when it is not configured.

    Install the optional extra to use it: ``pip install "contexer-agent[tracing]"``.
    """
    env = os.environ if env is None else env
    if not (env.get("LANGFUSE_PUBLIC_KEY", "").strip() and env.get("LANGFUSE_SECRET_KEY", "").strip()):
        return []
    try:
        from langfuse.langchain import CallbackHandler  # pyright: ignore[reportMissingImports]  # optional extra
    except ImportError:
        warnings.warn(
            'LANGFUSE_* is set but the langfuse package is not installed: pip install "contexer-agent[tracing]". '
            "Tracing is off for this run.",
            stacklevel=2,
        )
        return []
    return [CallbackHandler()]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _file_stem(agent: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", agent).strip("-.") or "agent"
