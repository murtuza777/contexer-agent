"""`contexer doctor` and the browser-install diagnosis."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from contexer.appserver import RunningApp
from contexer.cli import app
from contexer.contract import Contract
from contexer.evidence import RunDir
from contexer.gate.session import VerificationSession
from contexer.observer.browser import INSTALL_HINT, LINUX_DEPS_HINT, browser_problem
from contexer.observer.models import BrowserObservation

PLAYWRIGHT_MISSING = (
    "BrowserType.launch: Executable doesn't exist at /ms-playwright/chromium-1234/chrome\n"
    "Looks like Playwright was just installed or updated."
)


def test_browser_problem_recognises_install_and_dependency_failures() -> None:
    assert browser_problem(PLAYWRIGHT_MISSING) == INSTALL_HINT
    assert browser_problem("Host system is missing dependencies to run browsers") == LINUX_DEPS_HINT
    assert browser_problem("net::ERR_CONNECTION_REFUSED") is None
    assert browser_problem(None) is None


class _BrokenObserver:
    async def observe(self, url: str, **kwargs: object) -> BrowserObservation:
        return BrowserObservation(url=url, success=False, error=f"Observer error: {PLAYWRIGHT_MISSING}")


@pytest.mark.anyio
async def test_missing_chromium_is_reported_as_the_fix_not_as_an_unreachable_app(tmp_path: Path) -> None:
    session = VerificationSession(tmp_path, RunDir.create(tmp_path), observer=_BrokenObserver())  # type: ignore[arg-type]
    result = await session.verify(RunningApp(url="http://127.0.0.1:1/", kind="external"), [Contract(id="c", goal="g")])
    assert result.decision.outcome == "error"
    assert result.decision.reasons == [INSTALL_HINT]


def test_doctor_passes_on_a_ready_static_project(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
    result = CliRunner().invoke(app, ["doctor", "--dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "Browser" in result.output and "static site" in result.output


def test_doctor_fails_on_a_project_it_cannot_start(tmp_path: Path) -> None:
    (tmp_path / "contexer.toml").write_text("[app\nbroken", encoding="utf-8")
    result = CliRunner().invoke(app, ["doctor", "--dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "contexer.toml" in result.output


SIGN_IN = """\
[auth]
url = "/login"
steps = [
  { action = "fill", target = { label = "Email" }, value = "${DOCTOR_EMAIL}" },
  { action = "fill", target = { label = "Password" }, value = "${DOCTOR_PASSWORD}" },
]
expect = [{ kind = "url", contains = "/home" }]
"""


def test_doctor_names_missing_sign_in_secrets_and_reads_the_env_file(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
    (tmp_path / "contexer.toml").write_text(SIGN_IN, encoding="utf-8")
    missing = CliRunner().invoke(app, ["doctor", "--dir", str(tmp_path)])
    assert missing.exit_code == 1
    assert "DOCTOR_EMAIL, DOCTOR_PASSWORD" in missing.output and "not set" in missing.output

    (tmp_path / ".env").write_text("DOCTOR_EMAIL=a\nDOCTOR_PASSWORD=b\n", encoding="utf-8")
    ready = CliRunner().invoke(app, ["doctor", "--dir", str(tmp_path)])
    assert "signs in at /login with DOCTOR_EMAIL, DOCTOR_PASSWORD" in ready.output


def test_doctor_warns_about_credentials_written_into_contexer_toml(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
    (tmp_path / "contexer.toml").write_text(SIGN_IN.replace("${DOCTOR_EMAIL}", "a@b.co").replace("${DOCTOR_PASSWORD}", "pw"), encoding="utf-8")
    result = CliRunner().invoke(app, ["doctor", "--dir", str(tmp_path)])
    assert "credentials written in contexer.toml" in result.output
