"""The link checker: every relative link in the project's Markdown points at something that exists.

Web links are not followed (tests need no network). Run it alone with
``pytest tests/test_docs_links.py``.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

REPO = Path(__file__).resolve().parents[2]
SKIP_DIRS = {".git", ".agents", ".claude", "node_modules", ".venv", "venv", ".next", "out", "dist", ".contexer"}

_FENCE = re.compile(r"^(```|~~~).*?^\1", re.MULTILINE | re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$", re.MULTILINE)


def markdown_files() -> list[Path]:
    found = []
    for path in REPO.rglob("*.md"):
        if not SKIP_DIRS.intersection(path.relative_to(REPO).parts):
            found.append(path)
    return sorted(found)


def _prose(text: str) -> str:
    return _INLINE_CODE.sub("", _FENCE.sub("", text))


def anchors(text: str) -> set[str]:
    """Heading anchors as GitHub makes them: lower case, punctuation dropped, spaces to dashes."""
    seen: dict[str, int] = {}
    result = set()
    for heading in _HEADING.findall(_FENCE.sub("", text)):
        plain = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading).replace("`", "")
        slug = re.sub(r"[^\w\- ]", "", plain.lower()).replace(" ", "-")
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        result.add(slug if count == 0 else f"{slug}-{count}")
    return result


def broken_links(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    problems = []
    for target in _LINK.findall(_prose(text)):
        if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):  # http:, mailto:, ...
            continue
        file_part, _, fragment = target.partition("#")
        file_part = unquote(file_part.split("?", 1)[0])
        if file_part.startswith("/"):
            continue  # a site-absolute path, not a file in the repository
        resolved = (path.parent / file_part).resolve() if file_part else path
        if not resolved.exists():
            problems.append(f"{target} (no such file)")
        elif fragment and resolved.suffix.lower() == ".md" and resolved.is_file():
            if unquote(fragment).lower() not in anchors(resolved.read_text(encoding="utf-8")):
                problems.append(f"{target} (no such heading)")
    return problems


def test_there_are_documents_to_check() -> None:
    names = {path.relative_to(REPO).as_posix() for path in markdown_files()}
    assert "README.md" in names and "contexer-agent/docs/agentic/architecture.md" in names


def test_no_broken_links() -> None:
    problems = {
        path.relative_to(REPO).as_posix(): found for path in markdown_files() if (found := broken_links(path))
    }
    assert problems == {}


def test_the_checker_reports_a_missing_file_and_a_missing_heading(tmp_path: Path) -> None:
    (tmp_path / "other.md").write_text("# Real heading\n", encoding="utf-8")
    page = tmp_path / "page.md"
    page.write_text(
        "[ok](other.md#real-heading) [gone](missing.md) [bad](other.md#nope) "
        "[web](https://example.com/x) `[code](nowhere.md)`\n```\n[fenced](nowhere.md)\n```\n",
        encoding="utf-8",
    )
    assert broken_links(page) == ["missing.md (no such file)", "other.md#nope (no such heading)"]
