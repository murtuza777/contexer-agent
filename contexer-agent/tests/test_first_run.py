"""The first minutes of a new user (T5.3): a clean install has no browser yet.

Found by following `docs/try-it.md` from a wheel in a fresh environment: `contexer demo`, the first command
the help names, ended with "Run: python -m playwright install chromium". With `uv tool install` or `pipx`,
the install the guide recommends, `python` is another Python that has no Playwright, so that command fails.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from contexer.cli import app, setup_cli
from contexer.observer.browser import INSTALL_HINT, LINUX_DEPS_HINT

WORKS_ANYWHERE = "contexer setup --browser"


@pytest.fixture
def chromium(monkeypatch: pytest.MonkeyPatch):
    """Chromium is missing until the install command has run. Returns the install commands that were run."""
    calls: list[list[str]] = []

    async def status() -> tuple[bool, str]:
        return (True, "Chromium 140.0") if calls else (False, INSTALL_HINT)

    monkeypatch.setattr("contexer.observer.browser.chromium_status", status)
    monkeypatch.setattr(setup_cli.subprocess, "call", lambda argv: calls.append(argv) or 0)
    return calls


def test_every_hint_names_a_command_that_works_however_contexer_was_installed() -> None:
    assert WORKS_ANYWHERE in INSTALL_HINT and "python -m playwright install chromium" not in INSTALL_HINT
    # The Linux libraries are installed by Playwright itself: the hint names this install's Python, not "python".
    assert sys.executable in LINUX_DEPS_HINT and "install-deps chromium" in LINUX_DEPS_HINT


def test_setup_browser_installs_chromium_and_asks_for_nothing_else(chromium: list[list[str]]) -> None:
    result = CliRunner().invoke(app, ["setup", "--browser"])  # no input given: a question would end it
    assert result.exit_code == 0, result.output
    assert chromium == [[sys.executable, "-m", "playwright", "install", "chromium"]]
    assert "Chromium 140.0" in result.output and "provider" not in result.output.lower()


def test_setup_browser_says_so_when_chromium_is_already_there(monkeypatch: pytest.MonkeyPatch) -> None:
    async def status() -> tuple[bool, str]:
        return True, "Chromium 140.0"

    monkeypatch.setattr("contexer.observer.browser.chromium_status", status)
    monkeypatch.setattr(setup_cli.subprocess, "call", lambda argv: pytest.fail("nothing to install"))
    result = CliRunner().invoke(app, ["setup", "--browser"])
    assert result.exit_code == 0 and "Chromium 140.0" in result.output


def test_setup_browser_fails_loudly_when_the_download_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    async def status() -> tuple[bool, str]:
        return False, INSTALL_HINT

    monkeypatch.setattr("contexer.observer.browser.chromium_status", status)
    monkeypatch.setattr(setup_cli.subprocess, "call", lambda argv: 1)
    result = CliRunner().invoke(app, ["setup", "--browser"])
    assert result.exit_code == 1 and "did not install" in result.output


def test_declining_the_download_leaves_the_command_that_works(chromium: list[list[str]]) -> None:
    console = Console(record=True, width=120)
    assert not setup_cli.ensure_browser(console, ask=False)  # --yes never downloads 150 MB unasked
    assert WORKS_ANYWHERE in console.export_text() and chromium == []


def test_doctor_names_the_same_command(monkeypatch: pytest.MonkeyPatch) -> None:
    from contexer.cli import doctor_cli

    async def status() -> tuple[bool, str]:
        return False, INSTALL_HINT

    monkeypatch.setattr("contexer.observer.browser.chromium_status", status)
    browser = next(f for f in doctor_cli.environment_findings() if f.area == "Browser")
    assert browser.fix == WORKS_ANYWHERE


def test_the_demo_offers_the_browser_to_a_person_before_it_runs_the_checks(
    chromium: list[list[str]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The demo is the first command a new user runs. With a person there, it installs what it needs and goes on."""
    from contexer.cli import demo_cli

    asked: list[str] = []
    monkeypatch.setattr(demo_cli, "is_interactive", lambda: True)
    monkeypatch.setattr(setup_cli.typer, "confirm", lambda text, **_k: asked.append(text) or True)
    result = CliRunner().invoke(app, ["demo", "--dir", str(tmp_path / "demo")])
    assert len(asked) == 1 and "Chromium" in asked[0]
    assert chromium == [[sys.executable, "-m", "playwright", "install", "chromium"]]
    assert result.exit_code == 1 and "refesh is not defined" in result.output  # and the demo went on to catch the bug


def test_the_demo_asks_nobody_when_nobody_is_there(chromium: list[list[str]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(setup_cli.typer, "confirm", lambda *_a, **_k: pytest.fail("nobody to ask"))
    CliRunner().invoke(app, ["demo", "--dir", str(tmp_path / "demo")])
    assert chromium == []
