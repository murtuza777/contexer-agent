"""Per-user settings: the provider, models and keys a person chose with ``contexer setup``.

They live outside every project, so keys never land in a repository::

    ~/.contexer/config.toml        provider, drafting model, coding agent
    ~/.contexer/credentials.toml   API keys (owner-only permissions on POSIX)

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
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict

CONFIG_FILE = "config.toml"
CREDENTIALS_FILE = "credentials.toml"


class UserSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None
    agent: Optional[str] = None
    agent_model: Optional[str] = None


def contexer_home() -> Path:
    return Path(os.environ.get("CONTEXER_HOME") or Path.home() / ".contexer")


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
    path = contexer_home() / CONFIG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def load_credentials() -> dict[str, str]:
    keys = _read_toml(contexer_home() / CREDENTIALS_FILE).get("keys") or {}
    return {str(k): str(v) for k, v in keys.items() if v}


def save_credential(env_name: str, value: str) -> Path:
    """Store one API key under the environment variable name its provider uses."""
    keys = load_credentials()
    keys[env_name] = value
    path = contexer_home() / CREDENTIALS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    body = ["# API keys saved by `contexer setup`. Never commit this file.", "", "[keys]", *_toml_pairs(keys)]
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    if sys.platform != "win32":
        path.chmod(0o600)
    return path


def apply_user_settings() -> None:
    """Expose saved keys and choices as environment variables, never overriding existing ones."""
    for name, value in load_credentials().items():
        os.environ.setdefault(name, value)
    settings = load_user_settings()
    for env_name, value in (
        ("CONTEXER_LLM_PROVIDER", settings.provider),
        ("CONTEXER_LLM_MODEL", settings.model),
        ("CONTEXER_LLM_BASE_URL", settings.base_url),
        ("CONTEXER_AGENT", settings.agent),
        ("CONTEXER_AGENT_MODEL", settings.agent_model),
    ):
        if value:
            os.environ.setdefault(env_name, value)


def mask(secret: str) -> str:
    return f"{secret[:6]}…{secret[-4:]}" if len(secret) > 12 else "••••"


def _toml_pairs(values: dict[str, Optional[str]]) -> list[str]:
    # A JSON string is a valid TOML basic string for every value we write.
    return [f"{key} = {json.dumps(value, ensure_ascii=False)}" for key, value in values.items() if value]
