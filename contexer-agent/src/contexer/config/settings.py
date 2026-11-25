"""Contexer configuration — settings dataclass and loader.

Loads application configuration from environment variables and .env files,
providing structured, validated settings for the CLI and LLM layer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# OpenRouter's router, which sends each request to a different free model.
OPENROUTER_FREE_ROUTER = "openrouter/free"
# Drafting default: one specific free model, measured with `bench --live` on
# 2026-10-26 at 33/40 seeded bugs caught and 0/164 false failures, where the
# router varied between 25% and 83% per run. Requests fall back to the router
# when it is unavailable (see OpenRouterProvider).
DEFAULT_OPENROUTER_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
DEFAULT_OPENCODE_MODEL_PROVIDER = "opencode"
DEFAULT_OPENCODE_MODEL_ID = "nemotron-3.5-lightning-free"
# OpenCode's own free models refuse programmatic use. With an OpenRouter key,
# OpenCode uses this free model instead: it built a feature that passed every
# check in a live `contexer run` (2026-10-26). Free models come and go on
# OpenRouter; set OPENCODE_MODEL_PROVIDER/OPENCODE_MODEL_ID or --model to pin another.
DEFAULT_OPENROUTER_CODING_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"


@dataclass
class ContexerConfig:
    """Application-level configuration for Contexer."""

    # -- llm & provider ---------------------------------------------------
    llm_provider: str = "openrouter"
    openrouter_api_key: str | None = None
    openrouter_model: str = DEFAULT_OPENROUTER_MODEL
    openrouter_site_url: str | None = None
    openrouter_app_name: str = "Contexer"
    # Direct provider keys, used to compile goals into checks (see llm.factory).
    anthropic_api_key: str | None = None
    anthropic_model: str | None = None
    openai_api_key: str | None = None
    openai_model: str | None = None
    openai_base_url: str | None = None
    # Explicit choice for compiling goals; None means "pick from available keys".
    compiler_provider: str | None = None
    # Model and endpoint for whichever provider drafts (CONTEXER_LLM_MODEL /
    # CONTEXER_LLM_BASE_URL); they win over the provider-specific variables.
    llm_model: str | None = None
    llm_base_url: str | None = None

    # -- opencode ---------------------------------------------------------
    opencode_server_url: str = "http://127.0.0.1:4096"
    opencode_model_provider: str = DEFAULT_OPENCODE_MODEL_PROVIDER
    opencode_model_id: str = DEFAULT_OPENCODE_MODEL_ID
    # None means "not configured": static projects are served locally,
    # others get their dev server started by contexer.appserver.
    app_url: str | None = None

    def __repr__(self) -> str:
        """Safe representation masking sensitive credentials."""
        api_key_preview = "***" if self.openrouter_api_key else "None"
        return (
            f"ContexerConfig(model='{self.openrouter_model}', "
            f"openrouter_api_key={api_key_preview})"
        )


def load_config(env_file: str | Path | None = None) -> ContexerConfig:
    """Load configuration from .env file and environment variables.

    Priority:
        1. Environment variables
        2. .env file in current or parent directories
        3. Built-in defaults
    """
    from contexer.config.project import load_env_file, load_nearest_env  # imports this module

    if env_file:
        load_env_file(env_file)
    else:
        load_nearest_env()

    api_key = os.environ.get("OPENROUTER_API_KEY")
    model = os.environ.get("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL).strip()
    explicit_provider = os.environ.get("CONTEXER_LLM_PROVIDER", "").strip().lower()
    provider = explicit_provider or "openrouter"
    site_url = os.environ.get("OPENROUTER_SITE_URL")
    app_name = os.environ.get("OPENROUTER_APP_NAME", "Contexer").strip()

    opencode_server_url = os.environ.get("OPENCODE_SERVER_URL", "http://127.0.0.1:4096").strip()
    opencode_model_provider = os.environ.get("OPENCODE_MODEL_PROVIDER", DEFAULT_OPENCODE_MODEL_PROVIDER).strip()
    opencode_model_id = os.environ.get("OPENCODE_MODEL_ID", DEFAULT_OPENCODE_MODEL_ID).strip()

    app_url = os.environ.get("CONTEXER_APP_URL", "").strip()

    def _env(name: str) -> str | None:
        value = os.environ.get(name, "").strip()
        return value or None

    return ContexerConfig(
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        anthropic_model=_env("ANTHROPIC_MODEL"),
        openai_api_key=_env("OPENAI_API_KEY"),
        openai_model=_env("OPENAI_MODEL"),
        openai_base_url=_env("OPENAI_BASE_URL"),
        compiler_provider=explicit_provider or None,
        llm_model=_env("CONTEXER_LLM_MODEL"),
        llm_base_url=_env("CONTEXER_LLM_BASE_URL"),
        llm_provider=provider,
        openrouter_api_key=api_key if api_key else None,
        openrouter_model=model if model else DEFAULT_OPENROUTER_MODEL,
        openrouter_site_url=site_url if site_url else None,
        openrouter_app_name=app_name if app_name else "Contexer",
        opencode_server_url=opencode_server_url if opencode_server_url else "http://127.0.0.1:4096",
        opencode_model_provider=opencode_model_provider if opencode_model_provider else DEFAULT_OPENCODE_MODEL_PROVIDER,
        opencode_model_id=opencode_model_id if opencode_model_id else DEFAULT_OPENCODE_MODEL_ID,
        app_url=app_url or None,
    )
