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

import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from contexer.verification.checks import Check, Expectation, Step

CONFIG_FILE = "contexer.toml"


class AppSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    start: str | None = None
    port: int | None = None
    ready_path: str = "/"
    ready_timeout: float = 120.0
    install: bool = True
    env: dict[str, str] = Field(default_factory=dict)
    # Run before every check to put server-side data back (checks share the
    # app's database), e.g. "npm run db:reset". {url} and {port} are filled in.
    reset: str | None = None


class GateSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    judged: Literal["advisory", "block"] = "advisory"


class LimitSettings(BaseModel):
    """What one run of Contexer's own agents may spend.

    ```toml
    [limits]
    tokens = 800000     # in and out together; default 1,500,000
    cost_usd = 2.50     # only where the provider reports prices
    ```
    """

    model_config = ConfigDict(extra="ignore")

    tokens: int | None = Field(default=None, gt=0)
    cost_usd: float | None = Field(default=None, gt=0)


CREW_AGENTS = ("intent", "tester", "challenger", "triage", "diagnoser", "reviewer")


class CrewAgentSettings(BaseModel):
    """One of Contexer's own agents: the model it runs on and how many steps it may take."""

    model_config = ConfigDict(extra="forbid")

    provider: str | None = None
    model: str | None = None
    max_steps: int | None = Field(default=None, gt=0)


class AgentsSettings(BaseModel):
    """Cost controls for a run, and a model per agent.

    ```toml
    [agents]
    max_usd = 5.00              # one budget: the coding agent and Contexer's agents together
    input_usd_per_mtok = 2.50   # prices, for a provider that reports none (Azure, most others)
    output_usd_per_mtok = 15.00

    [agents.triage]             # intent, tester, challenger, triage, diagnoser, reviewer
    model = "gpt-5.4-mini"      # a cheaper model for a small decision

    [agents.reviewer]
    max_steps = 8
    ```
    """

    model_config = ConfigDict(extra="forbid")

    max_usd: float | None = Field(default=None, gt=0)
    input_usd_per_mtok: float | None = Field(default=None, ge=0)
    output_usd_per_mtok: float | None = Field(default=None, ge=0)
    intent: CrewAgentSettings = Field(default_factory=CrewAgentSettings)
    tester: CrewAgentSettings = Field(default_factory=CrewAgentSettings)
    challenger: CrewAgentSettings = Field(default_factory=CrewAgentSettings)
    triage: CrewAgentSettings = Field(default_factory=CrewAgentSettings)
    diagnoser: CrewAgentSettings = Field(default_factory=CrewAgentSettings)
    reviewer: CrewAgentSettings = Field(default_factory=CrewAgentSettings)

    def for_agent(self, name: str) -> CrewAgentSettings:
        if name not in CREW_AGENTS:
            raise KeyError(f"there is no agent named '{name}'")
        return getattr(self, name)


class AgentSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = "claude-code"
    model: str | None = None
    max_repair_rounds: int = 2
    budget_usd: float | None = None
    turn_timeout: float = 900.0


class AuthSettings(BaseModel):
    """How to sign in before checks run. Values may use ``${ENV_VAR}`` secrets.

    ```toml
    [auth]
    url = "/login"
    steps = [
      { action = "fill", target = { label = "Email" }, value = "${CONTEXER_TEST_EMAIL}" },
      { action = "fill", target = { label = "Password" }, value = "${CONTEXER_TEST_PASSWORD}" },
      { action = "click", target = { role = "button", name = "Sign in" } },
    ]
    expect = [{ kind = "url", contains = "/dashboard" }]
    ```
    """

    model_config = ConfigDict(extra="ignore")

    url: str = "/"
    steps: list[Step] = Field(min_length=1)
    expect: list[Expectation] = Field(min_length=1)

    def as_check(self) -> Check:
        return Check(steps=list(self.steps), expect=list(self.expect), login=False)


class CompilerSettings(BaseModel):
    """Which model compiles goals into checks (draft quality depends on it)."""

    model_config = ConfigDict(extra="ignore")

    provider: str | None = None  # any id from contexer.llm.catalog (`contexer models --providers`)
    model: str | None = None

    @field_validator("provider")
    @classmethod
    def _known_provider(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from contexer.llm.catalog import provider_spec

        return provider_spec(value).id  # ValueError names the providers that exist


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    app: AppSettings = Field(default_factory=AppSettings)
    auth: AuthSettings | None = None
    compiler: CompilerSettings = Field(default_factory=CompilerSettings)
    gate: GateSettings = Field(default_factory=GateSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    agents: AgentsSettings = Field(default_factory=AgentsSettings)
    limits: LimitSettings = Field(default_factory=LimitSettings)


class ProjectConfigError(Exception):
    """``contexer.toml`` exists but cannot be used."""


def load_project_env(project_dir: str | Path) -> None:
    """Load ``<project>/.env`` into the environment.

    Model and agent keys and ``[auth]`` test credentials can live there, and
    the coding agent Contexer starts inherits them. An exported variable wins
    over the file; the file wins over what ``contexer setup`` saved.
    """
    env_file = Path(project_dir) / ".env"
    if env_file.is_file():
        from dotenv import dotenv_values

        from contexer.config.user import from_user_settings

        for name, value in dotenv_values(env_file).items():
            if value is not None and (name not in os.environ or from_user_settings(name)):
                os.environ[name] = value


def load_project_config(project_dir: str | Path) -> ProjectConfig:
    path = Path(project_dir) / CONFIG_FILE
    if not path.is_file():
        return ProjectConfig()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        return ProjectConfig.model_validate(data)
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
        raise ProjectConfigError(f"Invalid {path}: {exc}") from exc
