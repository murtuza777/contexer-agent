"""Per-project settings from ``contexer.toml`` at the project root.

Everything is optional; detection fills the gaps. Example::

    [app]
    start = "npm run dev -- --port {port}"   # {port} is substituted
    port = 5173
    ready_path = "/"
    ready_timeout = 120
    install = true

    [compiler]
    provider = "anthropic"   # or "openai", "openrouter"; default: whichever key is set
    model = "claude-opus-5-5"

    [gate]
    judged = "advisory"

    [agent]
    name = "claude-code"
    max_repair_rounds = 2
    budget_usd = 3.0
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

CONFIG_FILE = "contexer.toml"


class AppSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    start: Optional[str] = None
    port: Optional[int] = None
    ready_path: str = "/"
    ready_timeout: float = 120.0
    install: bool = True
    env: dict[str, str] = Field(default_factory=dict)


class GateSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    judged: Literal["advisory", "block"] = "advisory"


class AgentSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = "claude-code"
    model: Optional[str] = None
    max_repair_rounds: int = 2
    budget_usd: Optional[float] = None
    turn_timeout: float = 900.0


class CompilerSettings(BaseModel):
    """Which model compiles goals into checks (draft quality depends on it)."""

    model_config = ConfigDict(extra="ignore")

    provider: Optional[Literal["anthropic", "openai", "openrouter"]] = None
    model: Optional[str] = None


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    app: AppSettings = Field(default_factory=AppSettings)
    compiler: CompilerSettings = Field(default_factory=CompilerSettings)
    gate: GateSettings = Field(default_factory=GateSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)


class ProjectConfigError(Exception):
    """``contexer.toml`` exists but cannot be used."""


def load_project_config(project_dir: str | Path) -> ProjectConfig:
    path = Path(project_dir) / CONFIG_FILE
    if not path.is_file():
        return ProjectConfig()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        return ProjectConfig.model_validate(data)
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
        raise ProjectConfigError(f"Invalid {path}: {exc}") from exc
