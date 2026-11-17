"""The intent store: what the app should do, written down once and kept.

Each feature has a Markdown file in ``<project>/.contexer/intent/``. It holds
the goal as the person stated it, the behaviours Contexer derived from it,
every correction the person gave ("no, deleting should ask first") and the
assumptions taken without asking. A person can read it, edit it and commit
it; whatever is in the file is what the next run tests against.

Next to it, ``<feature>.checks.json`` holds the feature's checks: drafts from
the Intent agent, and the ones a ``contexer test`` run confirmed by replay.

An ``index.md`` lists the features. Like contracts, intent files say what
"done" means, so the tamper guard covers them while a coding agent works.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from contexer.contract.models import slugify
from contexer.contract.store import ensure_contexer_dir
from contexer.verification.checks import Check

INTENT_DIR = "intent"
INDEX_FILE = "index.md"
_CHECKS_SUFFIX = ".checks.json"

_SECTION = re.compile(r"^##\s+(.+?)\s*$")
_BULLET = re.compile(r"^\s*[-*]\s+(.*)$")
_DATED = re.compile(r"^(\d{4}-\d{2}-\d{2}):\s*(.*)$")
_MARKER = re.compile(r"<!--\s*contexer:intent\b.*?-->", re.DOTALL)


class IntentError(Exception):
    """An intent could not be found, read or written."""


class Correction(BaseModel):
    """Something the person said after seeing the app: the intent as they meant it."""

    on: str = ""
    text: str


class IntentSpec(BaseModel):
    """What one feature should do."""

    id: str
    goal: str
    behaviours: list[str] = Field(default_factory=list)
    corrections: list[Correction] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    def with_correction(self, text: str, on: Optional[str] = None) -> IntentSpec:
        """A copy with one more correction, dated today unless ``on`` says otherwise."""
        correction = Correction(on=date.today().isoformat() if on is None else on, text=" ".join(text.split()))
        return self.model_copy(update={"corrections": [*self.corrections, correction]})

    def as_text(self) -> str:
        """The intent as the agents read it: the goal, then what refines it. Corrections win over the rest."""
        parts = [self.goal.strip()]
        if self.behaviours:
            parts += ["", "Behaviours:", *[f"- {line}" for line in self.behaviours]]
        if self.corrections:
            parts += ["", "Corrections from the person (these override anything above):"]
            parts += [f"- {c.text}" for c in self.corrections]
        if self.assumptions:
            parts += ["", "Assumptions taken without asking:", *[f"- {line}" for line in self.assumptions]]
        return "\n".join(parts)

    def to_markdown(self) -> str:
        title = self.goal.strip().splitlines()[0][:80] if self.goal.strip() else self.id
        lines = [
            f"# {title}",
            "",
            f"<!-- contexer:intent id={self.id} -->",
            "",
            "What this feature should do. Edit it freely: Contexer tests against what is written here.",
            "",
            "## Goal",
            "",
            self.goal.strip(),
            "",
            "## Behaviours",
            "",
            *[f"- {line}" for line in self.behaviours],
            "",
            "## Corrections",
            "",
            *[f"- {c.on}: {c.text}" if c.on else f"- {c.text}" for c in self.corrections],
            "",
            "## Assumptions",
            "",
            *[f"- {line}" for line in self.assumptions],
        ]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).rstrip("\n") + "\n"

    @classmethod
    def from_markdown(cls, intent_id: str, text: str) -> IntentSpec:
        """Read a file a person may have edited: sections by heading, one item per bullet."""
        sections: dict[str, list[str]] = {}
        title, current = "", None
        for raw in _MARKER.sub("", text).splitlines():
            heading = _SECTION.match(raw)
            if heading:
                current = heading.group(1).strip().lower()
                sections.setdefault(current, [])
            elif current is not None:
                sections[current].append(raw)
            elif raw.startswith("# ") and not title:
                title = raw[2:].strip()
        goal = " ".join(" ".join(sections.get("goal", [])).split()) or title
        corrections = []
        for item in _bullets(sections.get("corrections", [])):
            dated = _DATED.match(item)
            corrections.append(Correction(on=dated.group(1), text=dated.group(2)) if dated else Correction(text=item))
        return cls(
            id=intent_id,
            goal=goal,
            behaviours=_bullets(sections.get("behaviours", [])),
            corrections=corrections,
            assumptions=_bullets(sections.get("assumptions", [])),
        )


class SavedCheck(BaseModel):
    """One check of a feature: a draft from the Intent agent, or one a replay confirmed."""

    id: str
    description: str
    check: Check
    source: Literal["draft", "confirmed"] = "draft"
    # For a confirmed check: whether it failed (a bug to fix) or passed (behaviour to keep) when last replayed.
    kind: Optional[Literal["bug", "works"]] = None


class IntentStore:
    """Loads and saves the intent of one project."""

    def __init__(self, project_dir: str | Path) -> None:
        self.project_dir = Path(project_dir).resolve()
        self.root = self.project_dir / ".contexer" / INTENT_DIR

    def id_for(self, goal: str) -> str:
        return slugify(goal)

    def path_for(self, intent_id: str) -> Path:
        return self.root / f"{intent_id}.md"

    def checks_path(self, intent_id: str) -> Path:
        return self.root / f"{intent_id}{_CHECKS_SUFFIX}"

    def exists(self, intent_id: str) -> bool:
        return self.path_for(intent_id).is_file()

    def _files(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        return sorted(p for p in self.root.glob("*.md") if p.name != INDEX_FILE)

    def list(self) -> list[IntentSpec]:
        return [self._read(path) for path in self._files()]

    def load(self, intent_id: str) -> IntentSpec:
        path = self.path_for(intent_id)
        if not path.is_file():
            known = ", ".join(p.stem for p in self._files()) or "none"
            raise IntentError(f"No intent '{intent_id}' in {self.root} (known: {known})")
        return self._read(path)

    def find(self, goal: str) -> Optional[IntentSpec]:
        """The stored intent for this goal, if a run already wrote one."""
        intent_id = self.id_for(goal)
        return self.load(intent_id) if self.exists(intent_id) else None

    def latest(self) -> Optional[IntentSpec]:
        """The intent that was saved last: what ``--again`` and ``--correct`` refer to."""
        files = self._files()
        return self._read(max(files, key=lambda p: p.stat().st_mtime_ns)) if files else None

    def save(self, spec: IntentSpec) -> Path:
        ensure_contexer_dir(self.project_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.path_for(spec.id)
        path.write_text(spec.to_markdown(), encoding="utf-8", newline="\n")
        self._write_index()
        return path

    def append_correction(self, intent_id: str, text: str, on: Optional[str] = None) -> IntentSpec:
        spec = self.load(intent_id).with_correction(text, on)
        self.save(spec)
        return spec

    def load_checks(self, intent_id: str) -> list[SavedCheck]:
        path = self.checks_path(intent_id)
        if not path.is_file():
            return []
        try:
            return [SavedCheck.model_validate(item) for item in json.loads(path.read_text(encoding="utf-8"))]
        except (ValueError, ValidationError) as exc:
            raise IntentError(f"{path} is not a list of checks: {exc}") from exc

    def save_checks(self, intent_id: str, checks: list[SavedCheck]) -> Path:
        ensure_contexer_dir(self.project_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.checks_path(intent_id)
        data = [c.model_dump(mode="json", by_alias=True, exclude_none=True) for c in checks]
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        return path

    def _read(self, path: Path) -> IntentSpec:
        try:
            return IntentSpec.from_markdown(path.stem, path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as exc:
            raise IntentError(f"{path} could not be read as an intent: {exc}") from exc

    def _write_index(self) -> None:
        lines = ["# Intent", "", "What each feature of this project should do. Written by Contexer, edited by you.", ""]
        for spec in self.list():
            goal = " ".join(spec.goal.split())
            lines.append(f"- [{spec.id}]({spec.id}.md): {goal}")
        (self.root / INDEX_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _bullets(lines: list[str]) -> list[str]:
    """Bullet items, each with its wrapped continuation lines joined."""
    items: list[str] = []
    for raw in lines:
        bullet = _BULLET.match(raw)
        if bullet:
            items.append(bullet.group(1).strip())
        elif raw.strip() and items and raw.startswith((" ", "\t")):
            items[-1] = f"{items[-1]} {raw.strip()}"
    return [item for item in items if item]
