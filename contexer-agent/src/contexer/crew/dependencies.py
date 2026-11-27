"""The dependency checker: a package a change adds to a manifest is looked up on its registry.

A coding agent sometimes writes the name of a package that does not exist, or one letter away from the
one it meant. Nothing in a browser check sees that. So for every package a change adds to
``package.json``, a ``requirements*.txt`` or ``pyproject.toml``, code asks the public registry (npm or
PyPI) three things: is there a package by that name, when was it first published, how many releases.

No model takes part. The only thing sent is the package's name, in the address of one GET request, and
only to ``registry.npmjs.org`` or ``pypi.org``. A project that sets its own registry is not looked up
at all: its packages may be private, and their names are not the public registry's business.

A lookup that fails says so and proves nothing: it is never read as "the package is fine" and never as
"the package is missing".
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import httpx

Registry = Literal["npm", "pypi"]
FindingKind = Literal["missing", "new", "near", "unchecked"]

NEW_DAYS = 30
# One slow registry must not hold a review up: each request gets this long, and a registry that fails
# once is not asked again in the same review.
LOOKUP_TIMEOUT = 5.0
MAX_LOOKUPS = 20
_MAX_MANIFEST_BYTES = 1_000_000
_LABEL: dict[str, str] = {"npm": "npm", "pypi": "PyPI"}
_NPM_SECTIONS = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")
_NPM_NAME = re.compile(r"(?i)^(?:@[a-z0-9~-][a-z0-9._~-]*/)?[a-z0-9~-][a-z0-9._~-]*$")
_PYPI_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
# A version that says "this comes from the registry": a range, a tag, or nothing. Anything with a
# protocol (file:, git+ssh:, workspace:, https:) or a path (someone/repo) comes from somewhere else.
_NPM_ELSEWHERE = re.compile(r"^[a-z+]+:|/")
_NPM_ALIAS = re.compile(r"^npm:((?:@[^/@]+/)?[^@]+)(?:@.*)?$")
_REQUIREMENT = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(.*)$")
_OWN_INDEX = re.compile(r"^\s*(?:--index-url|--extra-index-url|--find-links|-i|-f)\b")

# Names an agent is likely to mean. They are not looked up (they exist, and have for years), and a
# name one edit away from one of them is what a typo or a squatter looks like.
_MUCH_USED: dict[str, frozenset[str]] = {
    "npm": frozenset(
        """react react-dom preact vue svelte angular next nuxt express fastify koa lodash underscore axios
        node-fetch moment dayjs date-fns chalk commander yargs debug dotenv cross-env typescript webpack vite
        rollup esbuild eslint prettier jest mocha vitest playwright puppeteer cypress jquery bootstrap
        tailwindcss redux zustand mongoose sequelize prisma socket.io uuid nanoid zod yup joi bcrypt
        jsonwebtoken passport cors helmet morgan nodemon body-parser rxjs three d3 classnames immer request
        async bluebird minimist semver glob rimraf fs-extra ws redis pg mysql mysql2 sqlite3 mongodb electron
        tslib core-js react-router react-router-dom styled-components""".split()
    ),
    "pypi": frozenset(
        """requests urllib3 numpy pandas scipy matplotlib django flask fastapi starlette uvicorn gunicorn
        pydantic sqlalchemy alembic celery redis boto3 botocore pytest tox black ruff mypy pylint flake8 isort
        click typer rich jinja2 markupsafe pyyaml toml httpx aiohttp beautifulsoup4 lxml pillow cryptography
        pyjwt python-dotenv python-dateutil six setuptools wheel pip attrs tqdm scikit-learn tensorflow torch
        transformers openai anthropic langchain psycopg2 psycopg2-binary pymongo selenium playwright werkzeug
        certifi idna charset-normalizer packaging colorama openpyxl""".split()
    ),
}
# A short name is one edit from many real packages; only longer ones say something.
_MIN_NEAR_CHARS = 5


@dataclass(frozen=True)
class AddedPackage:
    registry: Registry
    name: str
    file: str
    line: int


@dataclass(frozen=True)
class Published:
    """What a registry says about a name. ``first`` is when its first release was published."""

    exists: bool
    first: datetime | None = None
    releases: int = 0


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    severity: Literal["low", "medium", "high"]
    kind: FindingKind
    explanation: str


class LookupFailed(Exception):
    """The registry could not be asked, or its answer could not be read. Nothing is known about the name."""


Lookup = Callable[[Registry, str], Published]
# A changed file as the review's scan parsed it: its path, the added lines with their numbers, the removed lines.
Change = tuple[str, Sequence[tuple[int, str]], Sequence[str]]


# -- which packages a change adds --------------------------------------------------------------------


def manifest_registry(path: str) -> Registry | None:
    """The registry a manifest's packages come from, or None when ``path`` is not a manifest read here."""
    parts = path.replace("\\", "/").split("/")
    name = parts[-1]
    if "node_modules" in parts or ".venv" in parts or "site-packages" in parts:
        return None
    if name == "package.json":
        return "npm"
    if name == "pyproject.toml" or (name.endswith(".txt") and (name.startswith("requirements") or parts[-2:-1] == ["requirements"])):
        return "pypi"
    return None


def added_packages(changes: Iterable[Change], project_dir: Path) -> list[AddedPackage]:
    """The registry packages each changed manifest declares now, whose name is on an added line and on no removed one.

    The manifest is read as it is in ``project_dir`` and parsed, so a name in ``scripts`` or in a comment
    is not a package. A version that changed removes and adds the same name: that package was there before.
    """
    found: dict[tuple[str, str], AddedPackage] = {}
    for path, added, removed in changes:
        registry = manifest_registry(path)
        text = _read(project_dir, path) if registry else None
        if registry is None or text is None:
            continue
        for written, name in _declared(path, text):
            if any(_mentions(line, written, registry) for line in removed):
                continue
            line = next((number for number, line in added if _mentions(line, written, registry)), None)
            if line is not None:
                found.setdefault((registry, _normal(registry, name)), AddedPackage(registry, name, path.replace("\\", "/"), line))
    return list(found.values())


def _read(project_dir: Path, path: str) -> str | None:
    """A manifest's text, when it is a file inside the project and small. The path comes from a diff, so it is checked."""
    root = Path(project_dir).resolve()
    try:
        target = (root / path).resolve()
        if not target.is_relative_to(root) or not target.is_file() or target.stat().st_size > _MAX_MANIFEST_BYTES:
            return None
        return target.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None


def _declared(path: str, text: str) -> list[tuple[str, str]]:
    """Each registry package a manifest declares, as (the name as written in the file, the name to look up)."""
    try:
        if path.endswith("package.json"):
            return _npm_declared(json.loads(text))
        if path.endswith(".toml"):
            return _pyproject_declared(tomllib.loads(text))
    except (ValueError, tomllib.TOMLDecodeError):
        return []
    return [(name, name) for name in (_requirement(line) for line in text.splitlines()) if name]


def _npm_declared(package: Any) -> list[tuple[str, str]]:
    declared: list[tuple[str, str]] = []
    for section in _NPM_SECTIONS:
        entries = package.get(section) if isinstance(package, dict) else None
        for name, spec in (entries.items() if isinstance(entries, dict) else ()):
            if not isinstance(name, str) or not isinstance(spec, str):
                continue
            alias = _NPM_ALIAS.match(spec.strip())
            if alias:
                declared.append((name, alias.group(1)))  # what is installed is the package the alias points at
            elif not _NPM_ELSEWHERE.search(spec.strip()):
                declared.append((name, name))
    return declared


def _pyproject_declared(data: dict[str, Any]) -> list[tuple[str, str]]:
    table = data.get("project")
    project: dict[str, Any] = table if isinstance(table, dict) else {}
    lists: list[Any] = [project.get("dependencies")]
    for table in (project.get("optional-dependencies"), data.get("dependency-groups")):
        lists += list(table.values()) if isinstance(table, dict) else []
    names = [_requirement(item) for items in lists if isinstance(items, list) for item in items if isinstance(item, str)]
    poetry = data.get("tool", {}).get("poetry", {}) if isinstance(data.get("tool"), dict) else {}
    entries = poetry.get("dependencies") if isinstance(poetry, dict) else None
    for name, spec in (entries.items() if isinstance(entries, dict) else ()):
        # A table with a path, a git address or a url is not from the registry; one with only a version is.
        if name != "python" and (isinstance(spec, str) or (isinstance(spec, dict) and not {"path", "git", "url"} & set(spec))):
            names.append(name)
    return [(name, name) for name in names if name]


def _requirement(line: str) -> str:
    """The package a requirement line names, or '' for an option, a path, a URL or a comment."""
    line = line.split(" #")[0].strip()
    if not line or line[0] in "#-." or "://" in line or line.startswith("git+"):
        return ""
    match = _REQUIREMENT.match(line)
    if match is None or match.group(2).startswith("@"):
        return ""
    return match.group(1)


def _mentions(line: str, name: str, registry: Registry) -> bool:
    if registry == "npm":
        return re.search(rf'"{re.escape(name)}"\s*:', line) is not None
    return re.search(rf"(?i)(?<![\w@/.-]){re.escape(name)}(?![\w/.-])", line) is not None


def _normal(registry: str, name: str) -> str:
    """The name as the registry compares it: PyPI treats ``-``, ``_`` and ``.`` as one, and neither minds case."""
    return re.sub(r"[-_.]+", "-", name).lower() if registry == "pypi" else name.lower()


# -- the registries ------------------------------------------------------------------------------------


def registry_lookup(registry: Registry, name: str) -> Published:
    """Ask npm or PyPI about one name. One GET, the name in its address, nothing else sent."""
    valid = _NPM_NAME if registry == "npm" else _PYPI_NAME
    if not valid.match(name) or len(name) > 214:
        raise LookupFailed("not a name the registry accepts")
    if registry == "npm":
        url = "https://registry.npmjs.org/" + quote(name, safe="@")
    else:
        url = f"https://pypi.org/pypi/{_normal('pypi', name)}/json"
    try:
        with httpx.Client(timeout=LOOKUP_TIMEOUT, follow_redirects=False, headers={"Accept": "application/json", "User-Agent": "contexer"}) as client:
            response = client.get(url)
        if response.status_code == 404:
            return Published(exists=False)
        if response.status_code != 200:
            raise LookupFailed(f"{_LABEL[registry]} answered {response.status_code}")
        body = response.json()
        return _npm_published(body) if registry == "npm" else _pypi_published(body)
    except httpx.TimeoutException as error:
        raise LookupFailed(f"{_LABEL[registry]} did not answer in {LOOKUP_TIMEOUT:.0f} s") from error
    except (httpx.HTTPError, ValueError, TypeError, AttributeError) as error:
        raise LookupFailed(f"{_LABEL[registry]} could not be read ({type(error).__name__})") from error


def _npm_published(body: dict[str, Any]) -> Published:
    versions = body.get("versions") or {}
    if not versions:
        return Published(exists=False)  # every version was unpublished: there is nothing to install
    return Published(True, _when(body["time"]["created"]), len(versions))


def _pypi_published(body: dict[str, Any]) -> Published:
    uploads = [[file["upload_time_iso_8601"] for file in files] for files in (body.get("releases") or {}).values() if files]
    if not uploads:
        return Published(exists=False)
    return Published(True, min(_when(stamp) for release in uploads for stamp in release), len(uploads))


def _when(stamp: str) -> datetime:
    when = datetime.fromisoformat(stamp)
    return when if when.tzinfo else when.replace(tzinfo=UTC)


# -- what is said about them ---------------------------------------------------------------------------


def dependency_findings(
    changes: Iterable[Change], project_dir: Path, lookup: Lookup = registry_lookup, *, now: datetime | None = None
) -> list[Finding]:
    """What the registries say about the packages a change adds. Empty when it adds none, or all are established."""
    now = now or datetime.now(UTC)
    findings: list[Finding] = []
    unchecked: dict[tuple[str, str], list[AddedPackage]] = {}  # (file, why) -> the packages nothing is known about
    down: dict[str, str] = {}  # a registry that failed once, and how
    asked = 0
    for package in added_packages(changes, project_dir):
        label = _LABEL[package.registry]
        if _normal(package.registry, package.name) in _MUCH_USED[package.registry]:
            continue
        own = _own_registry(package, project_dir)
        if own:
            unchecked.setdefault((package.file, f"not looked up on {label}: the project sets its own registry ({own})"), []).append(package)
            continue
        if package.registry in down:
            unchecked.setdefault((package.file, down[package.registry]), []).append(package)
            continue
        if asked >= MAX_LOOKUPS:
            why = f"could not be checked: only {MAX_LOOKUPS} packages are looked up in one review"
            unchecked.setdefault((package.file, why), []).append(package)
            continue
        asked += 1
        try:
            published = lookup(package.registry, package.name)
        except LookupFailed as error:
            down[package.registry] = f"could not be checked on {label} ({error}). A lookup that fails proves nothing either way"
            unchecked.setdefault((package.file, down[package.registry]), []).append(package)
            continue
        finding = _finding(package, published, now)
        if finding is not None:
            findings.append(finding)
    for (file, why), packages in unchecked.items():
        names = ", ".join(f"`{p.name}`" for p in packages[:8]) + (f" and {len(packages) - 8} more" if len(packages) > 8 else "")
        count = "1 package" if len(packages) == 1 else f"{len(packages)} packages"
        verb = "" if why.startswith("could") else "was " if len(packages) == 1 else "were "
        findings.append(Finding(file, packages[0].line, "low", "unchecked", f"{count} this change adds ({names}) {verb}{why}."))
    return findings


def _finding(package: AddedPackage, published: Published, now: datetime) -> Finding | None:
    label = _LABEL[package.registry]
    near = _near(package)
    close = f" The name is one edit from `{near}`." if near else ""
    if not published.exists or published.first is None:
        text = (
            f"`{package.name}` is not on {label}: the registry has no package by that name.{close} An install fails, or "
            "fetches whatever someone publishes under the name later. Use a package that exists, or remove it."
        )
        return Finding(package.file, package.line, "high", "missing", text)
    days = (now - published.first).days
    since = f"{published.first:%Y-%m-%d}"
    releases = "1 release" if published.releases == 1 else f"{published.releases} releases"
    if days < NEW_DAYS:
        ago = "today" if days <= 0 else "1 day ago" if days == 1 else f"{days} days ago"
        text = (
            f"`{package.name}` was first published on {label} {ago} ({since}) and has {releases}.{close} A package this "
            "new is rarely the one that was meant. Check that it is; if it is not, use the one that was."
        )
        return Finding(package.file, package.line, "high" if near else "medium", "new", text)
    if near:
        text = f"`{package.name}` is one edit from `{near}`, a much used package. It has been on {label} since {since} with {releases}; check that it is the one meant."
        return Finding(package.file, package.line, "low", "near", text)
    return None


def _near(package: AddedPackage) -> str:
    """The much used package this name is one edit from, or ''. A scoped npm name belongs to its scope and is left alone."""
    name = _normal(package.registry, package.name)
    if name.startswith("@"):
        return ""
    for known in sorted(_MUCH_USED[package.registry]):
        if len(known) >= _MIN_NEAR_CHARS and name != known and (_one_edit(name, known) or _squashed(name) == _squashed(known)):
            return known
    return ""


def _squashed(name: str) -> str:
    return re.sub(r"[-_.]", "", name)


def _one_edit(a: str, b: str) -> bool:
    """True when ``a`` becomes ``b`` by one letter added, dropped or changed, or two neighbours swapped."""
    if abs(len(a) - len(b)) > 1 or a == b:
        return False
    start = next((i for i, (x, y) in enumerate(zip(a, b, strict=False)) if x != y), min(len(a), len(b)))
    if len(a) == len(b):
        return a[start + 1 :] == b[start + 1 :] or (a[start : start + 2] == b[start : start + 2][::-1] and a[start + 2 :] == b[start + 2 :])
    longer, shorter = (a, b) if len(a) > len(b) else (b, a)
    return longer[start + 1 :] == shorter[start:]


def _own_registry(package: AddedPackage, project_dir: Path) -> str:
    """Where the project says its packages come from, when that is not the public registry; '' otherwise.

    Only files in the project are read: a registry set in the person's home directory is not seen.
    """
    if package.registry == "npm":
        text = _read(project_dir, ".npmrc") or ""
        return ".npmrc" if re.search(r"(?m)^\s*(?:@[^:\s]+:)?registry\s*=", text) else ""
    for name in ("pip.conf", "pip.ini"):
        if _read(project_dir, name) is not None:
            return name
    text = _read(project_dir, package.file) or ""
    if package.file.endswith(".toml"):
        try:
            tool = tomllib.loads(text).get("tool", {})
        except tomllib.TOMLDecodeError:
            return ""
        uv, poetry = tool.get("uv", {}), tool.get("poetry", {})
        return package.file if (isinstance(uv, dict) and uv.get("index")) or (isinstance(poetry, dict) and poetry.get("source")) else ""
    return package.file if any(_OWN_INDEX.match(line) for line in text.splitlines()) else ""
