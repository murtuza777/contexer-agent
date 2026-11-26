"""Per-user settings: the provider, models and keys a person chose with ``contexer setup``.

They live outside every project, so keys never land in a repository::

    ~/.contexer/config.toml        provider, drafting model, coding agent
    ~/.contexer/credentials.toml   API keys (created owner-only on POSIX: mode 600, the folder 700)

On Windows those mode bits do nothing: the file gets the access rules of the folder it is in, which
under a user profile means that user, administrators and the system.

``CONTEXER_HOME`` moves the folder. At startup :func:`apply_user_settings`
copies them into the environment without overriding anything already set, so
an exported variable, a ``.env`` and the project's ``contexer.toml`` all still
win, and the coding agent Contexer starts inherits the same keys.
"""

from __future__ import annotations

import json
import os
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict

CONFIG_FILE = "config.toml"
CREDENTIALS_FILE = "credentials.toml"


class UserSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    agent: str | None = None
    agent_model: str | None = None


def contexer_home() -> Path:
    return Path(os.environ.get("CONTEXER_HOME") or Path.home() / ".contexer")


def _home_dir() -> Path:
    """The settings folder, made for its owner only when it does not exist yet (the mode does nothing on Windows)."""
    home = contexer_home()
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    return home


def _read_toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def load_user_settings() -> UserSettings:
    data = _read_toml(contexer_home() / CONFIG_FILE)
    drafting, agent = data.get("model") or {}, data.get("agent") or {}
    return UserSettings(
        provider=drafting.get("provider"),
        model=drafting.get("model"),
        base_url=drafting.get("base_url"),
        agent=agent.get("name"),
        agent_model=agent.get("model"),
    )


def save_user_settings(settings: UserSettings) -> Path:
    lines = ["# Written by `contexer setup`. Keys are in credentials.toml next to this file.", "", "[model]"]
    lines += _toml_pairs({"provider": settings.provider, "model": settings.model, "base_url": settings.base_url})
    lines += ["", "[agent]"]
    lines += _toml_pairs({"name": settings.agent, "model": settings.agent_model})
    path = _home_dir() / CONFIG_FILE
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def load_credentials() -> dict[str, str]:
    keys = _read_toml(contexer_home() / CREDENTIALS_FILE).get("keys") or {}
    return {str(k): str(v) for k, v in keys.items() if v}


def save_credential(env_name: str, value: str) -> Path:
    """Store one API key under the environment variable name its provider uses."""
    keys = load_credentials()
    keys[env_name] = value
    path = _home_dir() / CREDENTIALS_FILE
    body = ["# API keys saved by `contexer setup`. Never commit this file.", "", "[keys]", *_toml_pairs(keys)]
    # Created owner-only by the same call that creates it: writing first and changing the mode after left a
    # moment in which the file held a key and others could read it. A file that is already there keeps its
    # mode through O_CREAT, so it is closed to others before anything is written.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    if sys.platform != "win32":
        try:
            os.fchmod(fd, 0o600)
        except OSError:
            os.close(fd)
            raise
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(body) + "\n")
    return path


# What apply_user_settings put into the environment, so a project's .env loaded later
# (`--dir` elsewhere) can still take precedence over it, as it does over nothing else.
_APPLIED: dict[str, str] = {}


def apply_user_settings() -> None:
    """Expose saved keys and choices as environment variables, never overriding existing ones."""
    settings = load_user_settings()
    choices = {
        "CONTEXER_LLM_PROVIDER": settings.provider,
        "CONTEXER_LLM_MODEL": settings.model,
        "CONTEXER_LLM_BASE_URL": settings.base_url,
        "CONTEXER_AGENT": settings.agent,
        "CONTEXER_AGENT_MODEL": settings.agent_model,
    }
    for name, value in [*load_credentials().items(), *choices.items()]:
        if value and name not in os.environ:
            os.environ[name] = value
            _APPLIED[name] = value


def from_user_settings(name: str) -> bool:
    """True while ``name`` still holds the value apply_user_settings gave it."""
    return name in _APPLIED and os.environ.get(name) == _APPLIED[name]


def given_by_project(name: str) -> None:
    """A project's ``.env`` set ``name`` itself, so it is no longer only what ``contexer setup`` saved.

    Matters when the file holds the same value setup saved: the app's processes get what the project gave
    (``procutil.child_env``), and comparing values alone could not tell the two apart.
    """
    _APPLIED.pop(name, None)


def mask(secret: str) -> str:
    return f"{secret[:6]}…{secret[-4:]}" if len(secret) > 12 else "••••"


def _toml_pairs(values: Mapping[str, str | None]) -> list[str]:
    # A JSON string is a valid TOML basic string for every value we write.
    return [f"{key} = {json.dumps(value, ensure_ascii=False)}" for key, value in values.items() if value]
