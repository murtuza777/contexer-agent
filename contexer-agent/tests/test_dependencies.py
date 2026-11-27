"""The dependency checker (AGT-2): a package a change adds to a manifest is looked up by code.

No test here touches the network: the registry is a function, and the tests pass their own.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from langchain_core.messages import HumanMessage

from contexer.crew import dependencies
from contexer.crew.dependencies import LookupFailed, Published, added_packages, dependency_findings, registry_lookup
from contexer.crew.reviewer import review
from tests.fakes import ScriptedChatModel, submit

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 11, 27, tzinfo=UTC)
OLD = Published(exists=True, first=NOW - timedelta(days=900), releases=40)
MISSING = Published(exists=False)


def _diff(path: str, added: list[str], removed: list[str] | None = None, start: int = 5) -> str:
    removed = removed or []
    return "\n".join(
        [
            f"diff --git a/{path} b/{path}",
            f"--- a/{path}",
            f"+++ b/{path}",
            f"@@ -{start},{len(removed)} +{start},{len(added)} @@",
            *[f"-{line}" for line in removed],
            *[f"+{line}" for line in added],
            "",
        ]
    )


def _change(path: str, added: list[str], removed: list[str] | None = None, start: int = 5) -> tuple[str, list[tuple[int, str]], list[str]]:
    return (path, [(start + i, line) for i, line in enumerate(added)], removed or [])


class Registry:
    """A registry that knows the packages it is given, and records every name it is asked for."""

    def __init__(self, known: dict[str, Published] | None = None, fail: bool = False) -> None:
        self.known = known or {}
        self.fail = fail
        self.asked: list[tuple[str, str]] = []

    def __call__(self, registry: str, name: str) -> Published:
        self.asked.append((registry, name))
        if self.fail:
            raise LookupFailed("the registry did not answer in 5 s")
        return self.known.get(name, MISSING)


def _package(project: Path, dependencies: dict[str, str], dev: dict[str, str] | None = None, scripts: dict[str, str] | None = None) -> None:
    body = {"name": "app", "scripts": scripts or {}, "dependencies": dependencies, "devDependencies": dev or {}}
    (project / "package.json").write_text(json.dumps(body, indent=2), encoding="utf-8")


# -- which packages a change adds --------------------------------------------------------------


def test_a_package_added_to_package_json_is_found_and_a_version_bump_is_not(tmp_path: Path) -> None:
    _package(tmp_path, {"express": "^4.19.0", "fast-csv-parse": "^1.0.0"}, dev={"@acme/lint-rules": "^2.0.0"}, scripts={"build": "tsc"})
    change = _change(
        "package.json",
        ['    "express": "^4.19.0",', '    "fast-csv-parse": "^1.0.0"', '    "@acme/lint-rules": "^2.0.0"', '    "build": "tsc"'],
        removed=['    "express": "^4.18.0"'],
    )
    found = added_packages([change], tmp_path)

    assert [(p.registry, p.name, p.file, p.line) for p in found] == [
        ("npm", "fast-csv-parse", "package.json", 6),
        ("npm", "@acme/lint-rules", "package.json", 7),
    ]  # express was there before; "build" is a script, not a dependency


def test_what_does_not_come_from_the_registry_is_not_looked_up(tmp_path: Path) -> None:
    specs = {"local": "file:../local", "fork": "github:someone/fork", "ws": "workspace:*", "tar": "https://example.com/x.tgz", "alias": "npm:real-name@^1.0.0"}
    _package(tmp_path, specs)
    change = _change("package.json", [f'    "{name}": "{spec}",' for name, spec in specs.items()])

    assert [p.name for p in added_packages([change], tmp_path)] == ["real-name"]  # an alias installs the package it points at


def test_packages_added_to_a_requirements_file_and_to_pyproject_are_found(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text(
        "flask==3.0.0\nreqeusts>=2.0  # http\n-r base.txt\n-e ./local\ngit+https://example.com/x.git\nrich[jupyter]>=13 ; python_version > '3.9'\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "app"\ndependencies = [\n  "httpx>=0.27",\n  "fastjson-utils",\n]\n\n'
        '[project.optional-dependencies]\ndev = ["pytest-quickcheck>=1"]\n',
        encoding="utf-8",
    )
    changes = [
        _change("requirements.txt", ["reqeusts>=2.0  # http", "-r base.txt", "-e ./local", "git+https://example.com/x.git", "rich[jupyter]>=13 ; python_version > '3.9'"], start=2),
        _change("pyproject.toml", ['  "fastjson-utils",', 'dev = ["pytest-quickcheck>=1"]'], start=5),
    ]
    found = added_packages(changes, tmp_path)

    assert [(p.registry, p.name, p.file) for p in found] == [
        ("pypi", "reqeusts", "requirements.txt"),
        ("pypi", "rich", "requirements.txt"),
        ("pypi", "fastjson-utils", "pyproject.toml"),
        ("pypi", "pytest-quickcheck", "pyproject.toml"),
    ]


def test_a_manifest_that_cannot_be_read_and_a_file_that_is_not_a_manifest_add_nothing(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{ not json", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "notes.txt").write_text("left-pad\n", encoding="utf-8")

    assert added_packages([_change("package.json", ['    "left-pad": "1.0.0"']), _change("src/notes.txt", ["left-pad"])], tmp_path) == []
    assert added_packages([_change("node_modules/x/package.json", ['    "left-pad": "1.0.0"'])], tmp_path) == []


# -- what the registry says about them ---------------------------------------------------------


def test_a_package_that_is_not_on_the_registry_is_a_high_finding(tmp_path: Path) -> None:
    _package(tmp_path, {"react-smart-table-pro": "^1.0.0"})
    registry = Registry()
    [finding] = dependency_findings([_change("package.json", ['    "react-smart-table-pro": "^1.0.0"'])], tmp_path, registry, now=NOW)

    assert (finding.file, finding.line, finding.severity) == ("package.json", 5, "high")
    assert "`react-smart-table-pro`" in finding.explanation and "npm" in finding.explanation and "no package" in finding.explanation
    assert registry.asked == [("npm", "react-smart-table-pro")]  # the name and nothing else


def test_a_missing_package_one_edit_from_a_much_used_one_names_it(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("reqeusts\n", encoding="utf-8")
    [finding] = dependency_findings([_change("requirements.txt", ["reqeusts"], start=1)], tmp_path, Registry(), now=NOW)

    assert finding.severity == "high" and "PyPI" in finding.explanation and "`requests`" in finding.explanation


def test_a_package_first_published_in_the_last_30_days_is_a_medium_finding(tmp_path: Path) -> None:
    _package(tmp_path, {"csv-stream-kit": "^0.1.0", "old-and-plain": "^3.0.0"})
    registry = Registry({"csv-stream-kit": Published(True, NOW - timedelta(days=12), 2), "old-and-plain": Published(True, NOW - timedelta(days=31), 9)})
    change = _change("package.json", ['    "csv-stream-kit": "^0.1.0",', '    "old-and-plain": "^3.0.0"'])
    [finding] = dependency_findings([change], tmp_path, registry, now=NOW)

    assert (finding.severity, finding.line) == ("medium", 5)
    assert "12 days ago" in finding.explanation and "2026-11-15" in finding.explanation and "2 releases" in finding.explanation


def test_a_new_package_one_edit_from_a_much_used_one_is_high_and_an_old_one_is_low(tmp_path: Path) -> None:
    _package(tmp_path, {"expresss": "^1.0.0", "crossenv": "^7.0.0"})
    registry = Registry({"expresss": Published(True, NOW - timedelta(days=3), 1), "crossenv": Published(True, NOW - timedelta(days=2000), 4)})
    change = _change("package.json", ['    "expresss": "^1.0.0",', '    "crossenv": "^7.0.0"'])
    new, old = dependency_findings([change], tmp_path, registry, now=NOW)

    assert new.severity == "high" and "`express`" in new.explanation and "3 days ago" in new.explanation
    assert old.severity == "low" and "`cross-env`" in old.explanation


def test_a_much_used_package_is_not_looked_up_and_an_established_one_is_no_finding(tmp_path: Path) -> None:
    _package(tmp_path, {"react": "^18.0.0", "preact": "^10.0.0", "old-and-plain": "^3.0.0"})
    registry = Registry({"old-and-plain": OLD})
    change = _change("package.json", ['    "react": "^18.0.0",', '    "preact": "^10.0.0",', '    "old-and-plain": "^3.0.0"'])

    assert dependency_findings([change], tmp_path, registry, now=NOW) == []
    assert registry.asked == [("npm", "old-and-plain")]


def test_a_lookup_that_fails_is_one_low_finding_that_says_nothing_was_checked(tmp_path: Path) -> None:
    _package(tmp_path, {"made-up-one": "^1.0.0", "made-up-two": "^1.0.0"})
    change = _change("package.json", ['    "made-up-one": "^1.0.0",', '    "made-up-two": "^1.0.0"'])
    [finding] = dependency_findings([change], tmp_path, Registry(fail=True), now=NOW)

    assert finding.severity == "low" and finding.file == "package.json"
    assert "could not be checked" in finding.explanation and "`made-up-one`" in finding.explanation and "`made-up-two`" in finding.explanation
    assert "did not answer" in finding.explanation


def test_a_project_with_its_own_registry_is_not_looked_up_on_the_public_one(tmp_path: Path) -> None:
    _package(tmp_path, {"@acme/billing-core": "^1.0.0"})
    (tmp_path / ".npmrc").write_text("@acme:registry=https://npm.acme.example/\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("--extra-index-url https://pypi.acme.example/simple\nacme-billing\n", encoding="utf-8")
    registry = Registry()
    changes = [_change("package.json", ['    "@acme/billing-core": "^1.0.0"']), _change("requirements.txt", ["acme-billing"], start=2)]
    findings = dependency_findings(changes, tmp_path, registry, now=NOW)

    assert registry.asked == []  # a private package's name is not sent to a public registry
    assert [(f.file, f.severity) for f in findings] == [("package.json", "low"), ("requirements.txt", "low")]
    assert all("its own registry" in f.explanation and "not looked up" in f.explanation for f in findings)


def test_only_so_many_packages_are_looked_up_in_one_review(tmp_path: Path) -> None:
    names = [f"made-up-{i:02d}" for i in range(dependencies.MAX_LOOKUPS + 3)]
    _package(tmp_path, {name: "^1.0.0" for name in names})
    registry = Registry({name: OLD for name in names})
    [finding] = dependency_findings([_change("package.json", [f'    "{name}": "^1.0.0",' for name in names])], tmp_path, registry, now=NOW)

    assert len(registry.asked) == dependencies.MAX_LOOKUPS
    assert finding.severity == "low" and "3 packages" in finding.explanation and "could not be checked" in finding.explanation


# -- the registries, without a network -----------------------------------------------------------


def _answers(monkeypatch: pytest.MonkeyPatch, status: int, body: object, seen: list[httpx.Request]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body)

    real = httpx.Client

    def client(**kwargs: object) -> httpx.Client:
        assert kwargs.get("timeout") == dependencies.LOOKUP_TIMEOUT and not kwargs.get("follow_redirects")
        return real(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(dependencies.httpx, "Client", client)


def test_npm_is_asked_for_the_name_only_and_its_answer_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []
    body = {"time": {"created": "2026-11-20T10:00:00.000Z", "modified": "2026-11-21T10:00:00.000Z", "0.1.0": "2026-11-20T10:00:00.000Z"}, "versions": {"0.1.0": {}}}
    _answers(monkeypatch, 200, body, seen)

    found = registry_lookup("npm", "@acme/csv-kit")

    assert found == Published(True, datetime(2026, 11, 20, 10, tzinfo=UTC), 1)
    [request] = seen
    assert str(request.url) == "https://registry.npmjs.org/@acme%2Fcsv-kit" and request.method == "GET" and not request.content
    assert "authorization" not in request.headers and "cookie" not in request.headers


def test_pypi_is_asked_by_the_normalised_name_and_the_first_upload_is_the_date(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []
    body = {
        "releases": {
            "0.2.0": [{"upload_time_iso_8601": "2025-03-02T08:00:00.000000Z"}],
            "0.1.0": [{"upload_time_iso_8601": "2025-01-05T08:00:00.000000Z"}],
            "0.3.0": [],
        }
    }
    _answers(monkeypatch, 200, body, seen)

    assert registry_lookup("pypi", "Fast_JSON.utils") == Published(True, datetime(2025, 1, 5, 8, tzinfo=UTC), 2)
    assert str(seen[0].url) == "https://pypi.org/pypi/fast-json-utils/json"


def test_a_404_is_a_package_that_does_not_exist_and_anything_else_is_a_failed_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    _answers(monkeypatch, 404, {"error": "Not found"}, [])
    assert registry_lookup("npm", "made-up") == MISSING
    assert registry_lookup("pypi", "made-up") == MISSING

    _answers(monkeypatch, 503, {}, [])
    with pytest.raises(LookupFailed, match="503"):
        registry_lookup("npm", "made-up")

    _answers(monkeypatch, 200, {"time": {"created": "not a date"}, "versions": {"1.0.0": {}}}, [])
    with pytest.raises(LookupFailed):
        registry_lookup("npm", "made-up")

    def down(**_kwargs: object) -> httpx.Client:
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(dependencies.httpx, "Client", down)
    with pytest.raises(LookupFailed):
        registry_lookup("pypi", "made-up")


def test_a_name_no_registry_would_accept_is_never_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []
    _answers(monkeypatch, 200, {}, seen)
    for name in ("../../etc/passwd", "a b", "x?token=1", ""):
        with pytest.raises(LookupFailed):
            registry_lookup("npm", name)
        with pytest.raises(LookupFailed):
            registry_lookup("pypi", name)
    assert seen == []


# -- in the review -------------------------------------------------------------------------------


async def test_the_review_notes_an_invented_package_as_something_code_saw(tmp_path: Path) -> None:
    _package(tmp_path, {"react-smart-table-pro": "^1.0.0"})
    diff = _diff("package.json", ['    "react-smart-table-pro": "^1.0.0"'])
    result = await review(diff, tmp_path, None, run_project_commands=False, lookup=Registry())

    [note] = result.notes
    assert (note.file, note.line, note.severity, note.category, note.source, note.backed) == ("package.json", 5, "high", "security", "scan", True)
    assert result.blocking == [note] and result.holds_pull_request  # a repair is asked for, and the pull request stays a draft


async def test_a_lookup_that_fails_neither_passes_nor_blocks(tmp_path: Path) -> None:
    _package(tmp_path, {"made-up-one": "^1.0.0"})
    diff = _diff("package.json", ['    "made-up-one": "^1.0.0"'])
    result = await review(diff, tmp_path, None, run_project_commands=False, lookup=Registry(fail=True))

    [note] = result.notes
    assert note.severity == "low" and note.category == "other" and "could not be checked" in note.explanation
    assert result.blocking == [] and not result.holds_pull_request


async def test_the_review_can_be_told_not_to_look_anything_up_and_the_model_is_told_what_was_found(tmp_path: Path) -> None:
    _package(tmp_path, {"react-smart-table-pro": "^1.0.0"})
    diff = _diff("package.json", ['    "react-smart-table-pro": "^1.0.0"'])
    assert (await review(diff, tmp_path, None, run_project_commands=False, lookup=None)).notes == []

    model = ScriptedChatModel(submit(notes=[]))
    result = await review(diff, tmp_path, model, run_project_commands=False, lookup=Registry())
    task = next(m for m in model.seen[0] if isinstance(m, HumanMessage)).text
    assert "Already found by a program" in task and "react-smart-table-pro" in task
    assert [n.severity for n in result.notes] == ["high"]


# -- the ticket's evaluation: twenty manifests, ten with a planted name -------------------------

# What the fake registry knows. Everything else does not exist.
KNOWN = {
    "date-fns-tz": OLD, "p-limit": OLD, "nanoid": OLD, "fastify-plugin": OLD, "structlog": OLD, "tenacity": OLD, "orjson": OLD,
    "python-slugify": OLD, "csv-stringify": OLD, "itsdangerous": OLD,
    "reactt": Published(True, NOW - timedelta(days=4), 1),
    "djanga": Published(True, NOW - timedelta(days=9), 1),
    "table-export-kit": Published(True, NOW - timedelta(days=20), 3),
}  # fmt: skip
PLANTED = [
    ("package.json", "react-auto-form-builder", "high"),  # invented
    ("package.json", "node-fetch-retry-pro", "high"),
    ("package.json", "@types/smart-date-utils", "high"),
    ("package.json", "expresss-validator", "high"),
    ("package.json", "reactt", "high"),  # new, and one edit from react
    ("package.json", "table-export-kit", "medium"),  # 20 days old
    ("requirements.txt", "reqeusts", "high"),  # a typo nobody registered
    ("requirements.txt", "fastapi-auth-helpers", "high"),
    ("requirements.txt", "djanga", "high"),
    ("pyproject.toml", "pandas-excel-toolkit", "high"),
]
CLEAN = [
    ("package.json", "date-fns-tz"),
    ("package.json", "p-limit"),
    ("package.json", "nanoid"),
    ("package.json", "fastify-plugin"),
    ("package.json", "csv-stringify"),
    ("package.json", "lodash"),  # much used: not looked up at all
    ("requirements.txt", "structlog"),
    ("requirements.txt", "tenacity"),
    ("requirements.txt", "python-slugify"),
    ("pyproject.toml", "orjson"),
]


def _manifest(project: Path, file: str, name: str) -> tuple[str, list[tuple[int, str]], list[str]]:
    """A small manifest with two packages that were there before, and ``name`` added to it."""
    if file == "package.json":
        _package(project, {"express": "^4.19.0", name: "^1.0.0"}, dev={"vitest": "^2.0.0"})
        return _change(file, [f'    "{name}": "^1.0.0"'])
    if file == "requirements.txt":
        (project / file).write_text(f"flask==3.0.0\npytest>=8\n{name}>=1.0\n", encoding="utf-8")
        return _change(file, [f"{name}>=1.0"], start=3)
    (project / file).write_text(f'[project]\nname = "app"\ndependencies = [\n  "httpx>=0.27",\n  "{name}>=1.0",\n]\n', encoding="utf-8")
    return _change(file, [f'  "{name}>=1.0",'])


@pytest.mark.parametrize(("file", "name", "severity"), PLANTED)
def test_each_planted_name_is_found(tmp_path: Path, file: str, name: str, severity: str) -> None:
    [finding] = dependency_findings([_manifest(tmp_path, file, name)], tmp_path, Registry(KNOWN), now=NOW)
    assert finding.severity == severity and f"`{name}`" in finding.explanation and finding.file == file


@pytest.mark.parametrize(("file", "name"), CLEAN)
def test_each_clean_manifest_is_quiet(tmp_path: Path, file: str, name: str) -> None:
    assert dependency_findings([_manifest(tmp_path, file, name)], tmp_path, Registry(KNOWN), now=NOW) == []
