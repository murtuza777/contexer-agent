"""Signed-in checks: [auth] in contexer.toml, ${SECRET} values, and signed-out checks."""

import json
import os
import shutil
from pathlib import Path
from typing import Iterator

import pytest
from typer.testing import CliRunner

from contexer.agents import ScriptedAgent
from contexer.cli import app
from contexer.config.project import ProjectConfigError, load_project_config
from contexer.contract import ContractStore
from contexer.controller import RunController, RunSettings
from contexer.gate.models import RunResult
from contexer.verification.checks import Check, MissingSecretError, expand_secrets
from contexer.verification.runner import CheckRunner
from contexer.workflow.app_server import StaticAppServer

pytestmark = pytest.mark.anyio

FIXTURE = Path(__file__).resolve().parents[1] / "bench" / "fixtures" / "members"
SECRETS = ("MEMBERS_EMAIL", "MEMBERS_PASSWORD")

AUTH_WITH_SECRETS = """\
[auth]
url = "/login.html"
steps = [
  { action = "fill", target = { label = "Email" }, value = "${MEMBERS_EMAIL}" },
  { action = "fill", target = { label = "Password" }, value = "${MEMBERS_PASSWORD}" },
  { action = "click", target = { role = "button", name = "Sign in" } },
]
expect = [{ kind = "visible", target = { role = "heading", name = "Dashboard" } }]
"""


@pytest.fixture
def members_app(tmp_path: Path) -> Iterator[Path]:
    target = tmp_path / "members"
    shutil.copytree(FIXTURE / "app", target, ignore=shutil.ignore_patterns("runs"))
    (target / "contexer.toml").write_text(AUTH_WITH_SECRETS, encoding="utf-8")
    yield target
    for name in SECRETS:  # a project .env is loaded into this process
        os.environ.pop(name, None)


def _verify(project: Path) -> tuple[int, RunResult]:
    result = CliRunner().invoke(app, ["replay", "--dir", str(project), "--trace", "off"])
    run = sorted((project / ".contexer" / "runs").iterdir())[-1]
    return result.exit_code, RunResult.model_validate_json((run / "result.json").read_text(encoding="utf-8"))


def test_auth_section_parses_into_a_signed_out_flow(members_app: Path) -> None:
    auth = load_project_config(members_app).auth
    assert auth is not None and auth.url == "/login.html"
    flow = auth.as_check()
    assert flow.login is False
    assert flow.secrets() == ["MEMBERS_EMAIL", "MEMBERS_PASSWORD"]


def test_auth_section_without_steps_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "contexer.toml").write_text('[auth]\nurl = "/login"\nsteps = []\nexpect = []\n', encoding="utf-8")
    with pytest.raises(ProjectConfigError):
        load_project_config(tmp_path)


def test_secrets_expand_from_the_environment_only_at_run_time() -> None:
    assert expand_secrets("${USER_A}:${USER_A}", {"USER_A": "x"}) == "x:x"
    assert expand_secrets("no placeholders", {}) == "no placeholders"
    with pytest.raises(MissingSecretError, match="MISSING_ONE"):
        expand_secrets("${MISSING_ONE}", {})


def test_login_flag_is_part_of_the_approved_content() -> None:
    store_free = Check.model_validate({"expect": [{"kind": "url", "contains": "/"}]})
    signed_out = Check.model_validate({"login": False, "expect": [{"kind": "url", "contains": "/"}]})
    # None (follow the project) is omitted on disk, so existing approvals keep their hash.
    assert "login" not in store_free.model_dump(mode="json", exclude_none=True)
    assert signed_out.model_dump(mode="json", exclude_none=True)["login"] is False
    assert signed_out.describe_lines()[0] == "as:     signed-out visitor"


def test_signs_in_with_secrets_from_the_project_env_file(members_app: Path) -> None:
    (members_app / ".env").write_text("MEMBERS_EMAIL=demo@example.com\nMEMBERS_PASSWORD=correct-horse\n", encoding="utf-8")
    code, result = _verify(members_app)

    assert code == 0, result.decision.reasons
    assert result.decision.outcome == "pass"
    verdicts = {
        r.criterion_id: r.verdict
        for o in result.contracts
        for r in (o.verification.criteria_results if o.verification else [])
    }
    # Signed-in checks saw the dashboard; the signed-out one saw the redirect.
    assert verdicts["welcomes-member"] == "verified"
    assert verdicts["anonymous-redirected"] == "verified"
    # The password never reaches the evidence.
    run = sorted((members_app / ".contexer" / "runs").iterdir())[-1]
    assert "correct-horse" not in (run / "result.json").read_text(encoding="utf-8")


def test_wrong_password_is_a_clear_sign_in_error_with_a_screenshot(members_app: Path) -> None:
    (members_app / ".env").write_text("MEMBERS_EMAIL=demo@example.com\nMEMBERS_PASSWORD=wrong\n", encoding="utf-8")
    code, result = _verify(members_app)

    assert code == 3
    assert result.decision.outcome == "error"
    [reason] = result.decision.reasons
    assert reason.startswith("Could not sign in with the [auth] flow in contexer.toml:")
    assert 'heading "Dashboard" is visible' in reason  # the expectation that did not hold
    assert "login.html" in reason  # where the browser ended up
    assert '"Invalid email or password"' in reason  # what the page said
    assert "wrong" not in reason
    run = sorted((members_app / ".contexer" / "runs").iterdir())[-1]
    assert (run / "sign-in.jpg").is_file()


def test_missing_secret_names_the_variable(members_app: Path) -> None:
    code, result = _verify(members_app)

    assert code == 3
    [reason] = result.decision.reasons
    assert "MEMBERS_EMAIL" in reason and "MEMBERS_PASSWORD" in reason and "not set" in reason


async def test_a_check_that_needs_login_without_auth_cannot_pass(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<!doctype html><meta charset='utf-8'><h1>Home</h1>", encoding="utf-8")
    check = Check.model_validate({"login": True, "expect": [{"kind": "visible", "target": {"text": "Home"}}]})
    with StaticAppServer(tmp_path) as server:
        [result] = await CheckRunner().run(server.url, [("needs-login", check)])
    assert not result.passed
    assert result.failed_step is not None and "no [auth] section" in result.failed_step


async def test_an_agent_that_breaks_sign_in_is_told_why_and_not_kept(members_app: Path) -> None:
    (members_app / ".env").write_text("MEMBERS_EMAIL=demo@example.com\nMEMBERS_PASSWORD=correct-horse\n", encoding="utf-8")
    good = (members_app / "auth.js").read_text(encoding="utf-8")
    forgets_session = good.replace("  localStorage.setItem(SESSION_KEY", "  // localStorage.setItem(SESSION_KEY")
    assert forgets_session != good
    agent = ScriptedAgent([{"auth.js": forgets_session}, {"auth.js": good}])
    controller = RunController(
        members_app, agent, RunSettings(max_repair_rounds=1), runner=CheckRunner(action_timeout=1.5, expect_timeout=1.0)
    )
    outcome = await controller.run(ContractStore(members_app).load("members-basics"))

    assert outcome.terminal == "succeeded", outcome.reason
    assert [a.outcome for a in outcome.attempts] == ["error", "pass"]
    assert "No check could run" in agent.prompts[1] and "Could not sign in" in agent.prompts[1]


def test_members_fixture_contract_is_approved() -> None:
    [contract] = ContractStore(FIXTURE / "app").list()
    assert contract.status == "approved"
    data = json.loads((FIXTURE / "app" / ".contexer" / "contracts" / "members-basics.json").read_text("utf-8"))
    assert any(c["check"].get("login") is False for c in data["criteria"])
