"""Tests for the Contexer CLI entrypoint."""

import re

from typer.testing import CliRunner

from contexer import __version__
from contexer.cli import app

runner = CliRunner()


class TestVersion:
    """``contexer --version`` and ``contexer -V``."""

    def test_version_flag(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert f"contexer v{__version__}" in result.output

    def test_version_short_flag(self) -> None:
        result = runner.invoke(app, ["-V"])
        assert result.exit_code == 0
        assert f"contexer v{__version__}" in result.output


def _plain(text: str) -> str:
    """Help output without ANSI styling (Rich styles it when CI forces a terminal)."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


class TestHelp:
    """``contexer --help``."""

    def test_help_flag(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        output = _plain(result.output)
        assert "Contexer" in output
        assert "owns done" in output
        for command in ("run", "verify", "replay", "contract", "bench"):
            assert command in output

    def test_help_contains_version_option(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert "--version" in _plain(result.output)
