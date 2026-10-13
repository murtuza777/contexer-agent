"""Contexer configuration — settings dataclass and loader.

Loads application configuration from environment variables and .env files,
providing structured, validated settings for the CLI and LLM layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Optional

from dotenv import find_dotenv, load_dotenv

DEFAULT_OPENROUTER_MODEL = "openrouter/free"
DEFAULT_OPENCODE_MODEL_PROVIDER = "opencode"
DEFAULT_OPENCODE_MODEL_ID = "nemotron-3.5-lightning-free"


@dataclass
class ContexerConfig:
    """Application-level configuration for Contexer."""

    # -- general ----------------------------------------------------------
    log_level: str = "INFO"
    verbose: bool = False

    # -- llm & provider ---------------------------------------------------
    llm_provider: str = "openrouter"
    openrouter_api_key: Optional[str] = None
    openrouter_model: str = DEFAULT_OPENROUTER_MODEL
    openrouter_site_url: Optional[str] = None
    openrouter_app_name: str = "Contexer"

    # -- agent & opencode -------------------------------------------------
    max_turns: int = 50
    opencode_path: Optional[str] = None
    opencode_server_url: str = "http://127.0.0.1:4096"
    opencode_model_provider: str = DEFAULT_OPENCODE_MODEL_PROVIDER
    opencode_model_id: str = DEFAULT_OPENCODE_MODEL_ID
    opencode_timeout: float = 120.0
    # None means "not configured": static projects are served locally,
    # others are expected on a dev server (see workflow.loop).
    app_url: Optional[str] = None

    # -- harness safety ---------------------------------------------------
    # AgentForge-inspired policy boundary.  Only the generic harness uses
    # this today; Contexer's engineering workflow will layer on top later.
    approval_policy: str = "on-request"
    redact_tool_output: bool = True
    protect_tool_observations: bool = True
    max_tool_output_chars: int = 20_000

    # -- display ----------------------------------------------------------
    compact: bool = False
    streaming: bool = True

    # -- github mcp -------------------------------------------------------
    github_mcp_enabled: bool = True
    github_token: Optional[str] = None
    github_mcp_read_only: bool = True
    github_mcp_toolsets: str = "repos,issues"
    github_mcp_command: Optional[str] = None

    # -- session ----------------------------------------------------------
    session_dir: Optional[str] = None

    def __repr__(self) -> str:
        """Safe representation masking sensitive credentials."""
        token_preview = "***" if self.github_token else "None"
        api_key_preview = "***" if self.openrouter_api_key else "None"
        return (
            f"ContexerConfig(model='{self.openrouter_model}', "
            f"openrouter_api_key={api_key_preview}, "
            f"github_token={token_preview}, "
            f"github_mcp_enabled={self.github_mcp_enabled}, "
            f"github_mcp_read_only={self.github_mcp_read_only}, "
            f"github_mcp_toolsets='{self.github_mcp_toolsets}')"
        )


def load_config(env_file: Optional[str | Path] = None) -> ContexerConfig:
    """Load configuration from .env file and environment variables.

    Priority:
        1. Environment variables
        2. .env file in current or parent directories
        3. Built-in defaults
    """
    if env_file:
        load_dotenv(dotenv_path=env_file, override=False)
    else:
        dotenv_path = find_dotenv(usecwd=True)
        if dotenv_path:
            load_dotenv(dotenv_path=dotenv_path, override=False)

    api_key = os.environ.get("OPENROUTER_API_KEY")
    model = os.environ.get("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL).strip()
    provider = os.environ.get("CONTEXER_LLM_PROVIDER", "openrouter").strip().lower()
    site_url = os.environ.get("OPENROUTER_SITE_URL")
    app_name = os.environ.get("OPENROUTER_APP_NAME", "Contexer").strip()
    log_level = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
    verbose = os.environ.get("VERBOSE", "false").strip().lower() in ("true", "1", "yes")
    approval_policy = os.environ.get("CONTEXER_APPROVAL_POLICY", "on-request").strip().lower()
    if approval_policy not in {"on-request", "auto", "never"}:
        approval_policy = "on-request"
    redact_tool_output = os.environ.get("CONTEXER_REDACT_TOOL_OUTPUT", "true").strip().lower() not in ("false", "0", "no")
    protect_tool_observations = os.environ.get("CONTEXER_PROTECT_TOOL_OBSERVATIONS", "true").strip().lower() not in ("false", "0", "no")
    try:
        max_tool_output_chars = max(1_000, int(os.environ.get("CONTEXER_MAX_TOOL_OUTPUT_CHARS", "20000")))
    except ValueError:
        max_tool_output_chars = 20_000

    opencode_server_url = os.environ.get("OPENCODE_SERVER_URL", "http://127.0.0.1:4096").strip()
    opencode_model_provider = os.environ.get("OPENCODE_MODEL_PROVIDER", DEFAULT_OPENCODE_MODEL_PROVIDER).strip()
    opencode_model_id = os.environ.get("OPENCODE_MODEL_ID", DEFAULT_OPENCODE_MODEL_ID).strip()
    try:
        opencode_timeout = float(os.environ.get("OPENCODE_TIMEOUT", "120.0"))
    except ValueError:
        opencode_timeout = 120.0

    app_url = os.environ.get("CONTEXER_APP_URL", "").strip()

    raw_gh_token = (
        os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")
        or os.environ.get("GITHUB_TOKEN")
        or os.environ.get("GH_TOKEN")
    )
    github_token = raw_gh_token.strip() if raw_gh_token and raw_gh_token.strip() else None

    github_mcp_enabled = (
        os.environ.get("CONTEXER_GITHUB_MCP_ENABLED", "true").strip().lower()
        not in ("false", "0", "no")
    )
    github_mcp_read_only = (
        os.environ.get("GITHUB_READ_ONLY", os.environ.get("CONTEXER_GITHUB_MCP_READ_ONLY", "true"))
        .strip()
        .lower()
        not in ("false", "0", "no")
    )
    github_mcp_toolsets = os.environ.get(
        "GITHUB_TOOLSETS",
        os.environ.get("CONTEXER_GITHUB_MCP_TOOLSETS", "repos,issues"),
    ).strip()
    raw_gh_cmd = os.environ.get("CONTEXER_GITHUB_MCP_COMMAND")
    github_mcp_command = raw_gh_cmd.strip() if raw_gh_cmd and raw_gh_cmd.strip() else None

    return ContexerConfig(
        log_level=log_level,
        verbose=verbose,
        llm_provider=provider,
        openrouter_api_key=api_key if api_key else None,
        openrouter_model=model if model else DEFAULT_OPENROUTER_MODEL,
        openrouter_site_url=site_url if site_url else None,
        openrouter_app_name=app_name if app_name else "Contexer",
        approval_policy=approval_policy,
        redact_tool_output=redact_tool_output,
        protect_tool_observations=protect_tool_observations,
        max_tool_output_chars=max_tool_output_chars,
        opencode_server_url=opencode_server_url if opencode_server_url else "http://127.0.0.1:4096",
        opencode_model_provider=opencode_model_provider if opencode_model_provider else DEFAULT_OPENCODE_MODEL_PROVIDER,
        opencode_model_id=opencode_model_id if opencode_model_id else DEFAULT_OPENCODE_MODEL_ID,
        opencode_timeout=opencode_timeout,
        app_url=app_url or None,
        github_mcp_enabled=github_mcp_enabled,
        github_token=github_token,
        github_mcp_read_only=github_mcp_read_only,
        github_mcp_toolsets=github_mcp_toolsets if github_mcp_toolsets else "repos,issues",
        github_mcp_command=github_mcp_command,
    )
