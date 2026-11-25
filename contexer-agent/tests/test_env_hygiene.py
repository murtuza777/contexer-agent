"""What the code a coding agent wrote can see and change in Contexer's own environment.

Contexer runs the app the agent just edited: its install scripts, its dev server, its reset command.
Those get no repository token, as the agent itself gets none. And the project's ``.env`` is read once:
the agent can write that file, and must not be able to set variables for Contexer in the middle of a run.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from contexer.appserver.devserver import DevServer
from contexer.appserver.reset import run_reset
from contexer.config import project as project_config
from contexer.config.project import load_project_env
from contexer.procutil import REPOSITORY_TOKENS, child_env

TOKENS = {"GITHUB_TOKEN": "ghx-repo-token", "GH_TOKEN": "ghx-cli-token", "CONTEXER_GITHUB_TOKEN": "ghx-contexer"}


def test_the_environment_for_the_apps_own_processes_has_no_repository_token(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in TOKENS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("DATABASE_URL", "postgres://local/dev")
    env = child_env()
    assert not (set(env) & REPOSITORY_TOKENS) and set(TOKENS) <= REPOSITORY_TOKENS
    assert env["DATABASE_URL"] == "postgres://local/dev"  # the app's own settings stay
    # What a project sets on purpose in [app] env is the project's choice.
    assert child_env({"GITHUB_TOKEN": "explicit"})["GITHUB_TOKEN"] == "explicit"


def test_the_dev_server_and_the_install_get_that_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in TOKENS.items():
        monkeypatch.setenv(name, value)
    server = DevServer.__new__(DevServer)
    server.plan = SimpleNamespace(env={"PORT": "5173"})  # type: ignore[assignment]
    env = server._env()
    assert not (set(env) & REPOSITORY_TOKENS)
    assert env["PORT"] == "5173" and env["CI"]  # CI is set, to whatever the machine already says (Actions: "true")


def test_the_reset_command_gets_that_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in TOKENS.items():
        monkeypatch.setenv(name, value)
    (tmp_path / "probe.py").write_text(
        "import os, sys\nsys.exit(1 if any(os.environ.get(n) for n in ('GITHUB_TOKEN', 'GH_TOKEN', 'CONTEXER_GITHUB_TOKEN')) else 0)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CONTEXER_TEST_PYTHON", sys.executable)
    command = '"%CONTEXER_TEST_PYTHON%" probe.py' if sys.platform == "win32" else '"$CONTEXER_TEST_PYTHON" probe.py'
    assert run_reset(command, tmp_path) is None  # exit 0: no token was there to see


# -- .env ------------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_env_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(project_config, "_env_loaded", set())


def test_the_project_env_is_read_once_so_a_later_edit_changes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HYGIENE_KEY", raising=False)
    monkeypatch.delenv("HYGIENE_LATER", raising=False)
    (tmp_path / ".env").write_text("HYGIENE_KEY=first\n", encoding="utf-8")
    load_project_env(tmp_path)
    assert os.environ["HYGIENE_KEY"] == "first"

    # The coding agent can write this file. What it adds after the run began is not Contexer's configuration.
    (tmp_path / ".env").write_text("HYGIENE_KEY=changed\nHYGIENE_LATER=injected\n", encoding="utf-8")
    load_project_env(tmp_path)
    assert os.environ["HYGIENE_KEY"] == "first" and "HYGIENE_LATER" not in os.environ
    monkeypatch.delenv("HYGIENE_KEY")


@pytest.mark.parametrize(
    "name",
    ["GIT_EXTERNAL_DIFF", "GIT_SSH_COMMAND", "GITHUB_API_URL", "GITHUB_SERVER_URL", "PATH", "NODE_OPTIONS", "PYTHONPATH", "LD_PRELOAD"],
)
def test_names_that_steer_contexers_own_tools_are_never_taken_from_the_project_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    before = os.environ.get(name)
    (tmp_path / ".env").write_text(f"{name}=https://evil.example/x\nHYGIENE_OK=yes\n", encoding="utf-8")
    monkeypatch.delenv("HYGIENE_OK", raising=False)
    refused: list[str] = []
    load_project_env(tmp_path, on_refused=refused.append)
    assert os.environ.get(name) == before
    assert refused == [name]
    assert os.environ["HYGIENE_OK"] == "yes"  # the rest of the file is read as before
    monkeypatch.delenv("HYGIENE_OK")


# -- the .env nearest the working folder, read when any command starts (SEC-2) ------------------------

STEERING = {
    "GIT_SSH_COMMAND": "evil",
    "GIT_CONFIG_COUNT": "1",
    "GITHUB_API_URL": "https://evil.example",
    "GH_HOST": "evil.example",
    "NODE_OPTIONS": "--require ./x.js",
    "PYTHONSTARTUP": "x.py",
    "HTTPS_PROXY": "http://evil.example:8080",
    "SSL_CERT_FILE": "ca.pem",
    "NODE_EXTRA_CA_CERTS": "ca.pem",
    "OPENCODE_SERVER_URL": "http://evil.example",
}


def _start_cli_in(folder: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from contexer.cli import app

    monkeypatch.chdir(folder)
    result = CliRunner().invoke(app, ["runs", "--dir", str(folder)])
    assert result.exit_code == 0, result.output


def test_no_command_takes_a_steering_name_from_the_nearest_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in STEERING:
        monkeypatch.delenv(name, raising=False)
    lines = [f"{name}={value}" for name, value in STEERING.items()]
    (tmp_path / ".env").write_text("\n".join([*lines, "DATABASE_URL=postgres://local/dev"]) + "\n", encoding="utf-8")
    _start_cli_in(tmp_path, monkeypatch)
    assert not (set(STEERING) & set(os.environ)), sorted(set(STEERING) & set(os.environ))
    assert os.environ["DATABASE_URL"] == "postgres://local/dev"  # ordinary settings are still read


def test_load_config_does_not_take_them_either(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from contexer.config.settings import load_config

    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
    (tmp_path / ".env").write_text("GIT_SSH_COMMAND=evil\nOPENROUTER_MODEL=some/model\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert load_config().openrouter_model == "some/model"
    assert "GIT_SSH_COMMAND" not in os.environ


def test_an_endpoint_from_the_file_is_taken_only_with_its_key_from_the_same_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from contexer.config.project import load_env_file

    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "CONTEXER_LLM_BASE_URL", "CONTEXER_LLM_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    # A key the person exported, and a file that would send it somewhere else.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-exported-by-the-person-0123456789")
    env = tmp_path / ".env"
    env.write_text(
        "OPENAI_BASE_URL=https://evil.example/v1\nCONTEXER_LLM_PROVIDER=openai\nCONTEXER_LLM_BASE_URL=https://evil.example/v1\n"
        "AZURE_OPENAI_API_KEY=key-from-the-file-0123456789\nAZURE_OPENAI_ENDPOINT=https://mine.services.ai.azure.com\n",
        encoding="utf-8",
    )
    refused: list[str] = []
    load_env_file(env, on_refused=refused.append)
    assert "OPENAI_BASE_URL" not in os.environ and "CONTEXER_LLM_BASE_URL" not in os.environ
    assert sorted(refused) == ["CONTEXER_LLM_BASE_URL", "OPENAI_BASE_URL"]
    # A deployment's own key and endpoint, both from the file, are the ordinary case and work.
    assert os.environ["AZURE_OPENAI_ENDPOINT"] == "https://mine.services.ai.azure.com"
