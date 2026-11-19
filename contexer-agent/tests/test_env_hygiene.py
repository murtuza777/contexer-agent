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
    assert not (set(env) & REPOSITORY_TOKENS) and env["PORT"] == "5173" and env["CI"] == "1"


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
