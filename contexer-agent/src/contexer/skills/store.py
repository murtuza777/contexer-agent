"""Project skills: what Contexer learned about testing one app, kept for the next run.

A skill is a short Markdown file in ``<project>/.contexer/skills/``: a name,
a one-line description, and a body of advice (how to reach a screen, how to
seed or reset data, which flow is slow). Before a run, the skills whose
description matches the intent are added to the Tester's task.

A skill is advice. It is never evidence and never changes a verdict: what the
Tester reports is still replayed by code. A person can edit or delete any of
them, and with the folder gone a run is exactly a first run.

No secret is written into a skill. A proposed skill containing a configured
secret value, or anything shaped like an API key, is rejected; the name of an
environment variable (``${APP_PASSWORD}``) is fine.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

from pydantic import BaseModel

from contexer.contract.store import ensure_contexer_dir
from contexer.llm.base import sanitize_sensitive_text
from contexer.verification.checks import redact

SKILLS_DIR = "skills"
# The most skills one run may add, and the most one run is given.
MAX_PROPOSED = 3
MAX_LOADED = 5

_WORD = re.compile(r"[a-z0-9]+")
# Words that say nothing about what a skill or an intent is about.
_STOP_WORDS = frozenset(
    "a an and are as at be by can do does for from how in into is it its of on or that the their them then this "
    "to use used using when where which who with will app page user users see".split()
)


class SkillError(Exception):
    """A skill could not be read or saved."""


class Skill(BaseModel):
    name: str
    description: str
    body: str = ""

    def to_markdown(self) -> str:
        return f"# {self.name}\n\n> {self.description}\n\n{self.body.strip()}\n"

    @classmethod
    def from_markdown(cls, name: str, text: str) -> Skill:
        """Read a file a person may have edited: the first quoted line is the description, the rest the body."""
        description, body, seen_description = "", [], False
        for line in text.splitlines():
            if line.startswith("# ") and not seen_description and not body:
                continue
            if line.startswith(">") and not seen_description:
                description, seen_description = line.lstrip("> ").strip(), True
                continue
            body.append(line)
        return cls(name=name, description=description, body="\n".join(body).strip())


class SkillStore:
    """Loads and saves the skills of one project."""

    def __init__(self, project_dir: str | Path) -> None:
        self.project_dir = Path(project_dir).resolve()
        self.root = self.project_dir / ".contexer" / SKILLS_DIR

    def path_for(self, name: str) -> Path:
        return self.root / f"{name}.md"

    def list(self) -> list[Skill]:
        if not self.root.is_dir():
            return []
        return [Skill.from_markdown(path.stem, path.read_text(encoding="utf-8")) for path in sorted(self.root.glob("*.md"))]

    def load(self, name: str) -> Skill:
        path = self.path_for(name)
        if not path.is_file():
            raise SkillError(f"No skill '{name}' in {self.root}")
        return Skill.from_markdown(name, path.read_text(encoding="utf-8"))

    def save(self, skill: Skill, secrets: Sequence[str] = ()) -> Path:
        """Write the skill. Raises :class:`SkillError` for a skill with no name, no description or a secret in it."""
        name = "-".join(_WORD.findall(skill.name.lower()))[:60].strip("-")
        description = " ".join(skill.description.split())
        if not name:
            raise SkillError("a skill needs a name")
        if not description:
            raise SkillError(f"the skill '{name}' needs a one-line description")
        clean = Skill(name=name, description=description, body=skill.body.strip())
        text = clean.to_markdown()
        if redact(text, [s for s in secrets if s]) != text or sanitize_sensitive_text(text) != text:
            raise SkillError(
                f"the skill '{name}' contains a secret. Refer to it by the name of its environment variable instead."
            )
        ensure_contexer_dir(self.project_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.path_for(name)
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def delete(self, name: str) -> None:
        self.path_for(name).unlink(missing_ok=True)

    def matching(self, intent: str, limit: int = MAX_LOADED) -> list[Skill]:
        """The skills whose description shares a meaningful word with the intent: the best ``limit``, by name."""
        wanted = _keywords(intent)
        scored = [(len(wanted & _keywords(f"{skill.name} {skill.description}")), skill) for skill in self.list()]
        best = sorted((item for item in scored if item[0] > 0), key=lambda item: (-item[0], item[1].name))[: max(0, limit)]
        return sorted((skill for _score, skill in best), key=lambda skill: skill.name)


def skills_text(skills: Sequence[Skill]) -> str:
    """Skills as the Tester reads them."""
    parts: list[str] = []
    for skill in skills:
        parts += [f"### {skill.name}: {skill.description}", skill.body.strip(), ""]
    return "\n".join(parts).strip()


def _keywords(text: str) -> set[str]:
    words = set()
    for word in _WORD.findall(text.lower()):
        if word in _STOP_WORDS or len(word) < 3:
            continue
        words.add(word[:-1] if word.endswith("s") and len(word) > 3 else word)  # "members" and "member" are one word
    return words
