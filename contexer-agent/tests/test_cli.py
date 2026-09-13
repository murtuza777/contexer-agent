"""Tests for the Contexer CLI entrypoint."""

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


class TestHelp:
    """``contexer --help``."""

    def test_help_flag(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Contexer" in result.output
        assert "Autonomous Engineering Agent" in result.output

    def test_help_contains_version_option(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert "--version" in result.output
