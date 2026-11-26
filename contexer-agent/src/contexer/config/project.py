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
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

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


CREW_AGENTS = ("intent", "planner", "tester", "challenger", "triage", "diagnoser", "reviewer")


def _provider_id(value: str | None) -> str | None:
    """The catalog's id for a provider named in ``contexer.toml``; an unknown one is an error that lists them."""
    if value is None:
        return None
    from contexer.llm.catalog import provider_spec

    return provider_spec(value).id


class CrewAgentSettings(BaseModel):
    """One of Contexer's own agents: the model it runs on and how many steps it may take."""

    model_config = ConfigDict(extra="forbid")

    provider: str | None = None
    model: str | None = None
    max_steps: int | None = Field(default=None, gt=0)

    @field_validator("provider")
    @classmethod
    def _known_provider(cls, value: str | None) -> str | None:
        return _provider_id(value)

    @model_validator(mode="after")
    def _provider_needs_a_model(self) -> CrewAgentSettings:
        # Used to be read and dropped: the agent ran on the default provider and nothing said so.
        if self.provider and not self.model:
            raise ValueError(f"provider = \"{self.provider}\" is set with no model: add model = \"...\" beside it, or remove provider")
        return self


class AgentsSettings(BaseModel):
    """Cost controls for a run, and a model per agent.

    ```toml
    [agents]
    max_usd = 5.00              # one budget: the coding agent and Contexer's agents together
    input_usd_per_mtok = 2.50   # prices, for a provider that reports none (Azure, most others)
    output_usd_per_mtok = 15.00

    [agents.triage]             # intent, planner, tester, challenger, triage, diagnoser, reviewer
    model = "gpt-5.4-mini"      # a cheaper model for a small decision

    [agents.reviewer]
    max_steps = 8
    ```

    ``contexer run`` and ``contexer test`` both read it. A model that cannot be built, and a
    provider named with no model, stop the command before it starts.
    """

    model_config = ConfigDict(extra="forbid")

    max_usd: float | None = Field(default=None, gt=0)
    input_usd_per_mtok: float | None = Field(default=None, ge=0)
    output_usd_per_mtok: float | None = Field(default=None, ge=0)
    intent: CrewAgentSettings = Field(default_factory=CrewAgentSettings)
    planner: CrewAgentSettings = Field(default_factory=CrewAgentSettings)
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
        return _provider_id(value)


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


# Names that steer Contexer's own tools (git, the GitHub client, the interpreters it starts, where its requests
# go). A .env file never sets them: the coding agent can write that file, and a repository can carry one.
_ENV_NEVER_FROM_FILE = ("GIT_", "LD_", "DYLD_", "PYTHON", "SSL_CERT_")
_ENV_NAMES_NEVER_FROM_FILE = {
    "PATH", "PATHEXT", "COMSPEC", "SHELL", "NODE_OPTIONS", "NODE_EXTRA_CA_CERTS", "GITHUB_API_URL", "GITHUB_SERVER_URL",
    "GH_HOST", "GH_ENTERPRISE_TOKEN", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "OPENCODE_SERVER_URL",
}  # fmt: skip
_ENV_NEVER_FROM_FILE_SUFFIXES = ("_PROXY",)
# Where a model key is sent. Taken from a file only together with the key it belongs to (see ``_endpoint_key``).
_ENDPOINT_SUFFIXES = ("_BASE_URL", "_ENDPOINT", "_API_BASE")
# Projects whose .env this process has read. It is read once, before any coding agent runs.
_env_loaded: set[str] = set()


def _steers(name: str) -> bool:
    upper = name.upper()
    return upper in _ENV_NAMES_NEVER_FROM_FILE or upper.startswith(_ENV_NEVER_FROM_FILE) or upper.endswith(_ENV_NEVER_FROM_FILE_SUFFIXES)


def _endpoint_key(name: str, values: dict[str, str | None]) -> str | None:
    """The key variable an endpoint variable belongs to, or None when ``name`` is not an endpoint."""
    upper = name.upper()
    if not upper.endswith(_ENDPOINT_SUFFIXES):
        return None
    if upper == "CONTEXER_LLM_BASE_URL":
        from contexer.llm.catalog import provider_spec

        provider = (values.get("CONTEXER_LLM_PROVIDER") or os.environ.get("CONTEXER_LLM_PROVIDER") or "custom").strip().lower()
        try:
            return provider_spec(provider).key_env
        except ValueError:
            return "CONTEXER_CUSTOM_API_KEY"
    stem = upper
    for suffix in _ENDPOINT_SUFFIXES:
        stem = stem.removesuffix(suffix)
    return f"{stem}_API_KEY"


def load_env_file(env_file: str | Path, on_refused: Callable[[str], None] | None = None) -> None:
    """Load one ``.env`` file into the environment. Every place Contexer reads such a file goes through here.

    An exported variable wins over the file; the file wins over what ``contexer setup`` saved. Two kinds of
    name are not taken, and ``on_refused`` is told which:

    * names that steer Contexer's own tools (``_ENV_NEVER_FROM_FILE``);
    * an endpoint (``OPENAI_BASE_URL``, ``AZURE_OPENAI_ENDPOINT``, ``CONTEXER_LLM_BASE_URL``) whose key does not
      come from this same file: a file must not be able to send a key the person exported, or saved with
      ``contexer setup``, to another address.
    """
    path = Path(env_file)
    if not path.is_file():
        return
    from dotenv import dotenv_values

    from contexer.config.user import from_user_settings, given_by_project

    values = dict(dotenv_values(path))

    def taken(name: str) -> bool:
        return values.get(name) is not None and (name not in os.environ or from_user_settings(name))

    takes = {name: taken(name) for name in values}  # decided before anything is set
    for name, value in values.items():
        key = _endpoint_key(name, values)
        if _steers(name) or (key is not None and not takes.get(key, False)):
            if on_refused is not None:
                on_refused(name)
            continue
        if value is not None and takes[name]:
            os.environ[name] = value
            given_by_project(name)


def load_nearest_env() -> None:
    """Load the ``.env`` nearest the working folder (it, or a parent's), filtered as every such file is."""
    from dotenv import find_dotenv

    nearest = find_dotenv(usecwd=True)
    if nearest:
        load_env_file(nearest)


def load_project_env(project_dir: str | Path, on_refused: Callable[[str], None] | None = None) -> None:
    """Load ``<project>/.env`` into the environment, once per process.

    Model and agent keys and ``[auth]`` test credentials can live there, and
    the coding agent Contexer starts inherits them.

    Once, because the coding agent can write ``.env`` and git usually ignores
    it: what appears there after the run began is not configuration. And some
    names are never taken from it at all (see :func:`load_env_file`).
    """
    key = str(Path(project_dir).resolve())
    if key in _env_loaded:
        return
    _env_loaded.add(key)
    load_env_file(Path(project_dir) / ".env", on_refused)


def load_project_config(project_dir: str | Path) -> ProjectConfig:
    path = Path(project_dir) / CONFIG_FILE
    if not path.is_file():
        return ProjectConfig()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        return ProjectConfig.model_validate(data)
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
        raise ProjectConfigError(f"Invalid {path}: {exc}") from exc
