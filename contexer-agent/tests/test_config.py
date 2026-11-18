"""Tests for Contexer configuration."""

import os
from unittest.mock import patch

from contexer.config.settings import DEFAULT_OPENROUTER_MODEL, ContexerConfig, load_config


class TestContexerConfig:
    """Configuration dataclass and loader tests."""

    def test_default_values(self) -> None:
        config = ContexerConfig()
        assert config.llm_provider == "openrouter"
        assert config.openrouter_model == DEFAULT_OPENROUTER_MODEL
        assert config.openrouter_api_key is None
        assert config.openrouter_site_url is None
        assert config.openrouter_app_name == "Contexer"
        assert config.app_url is None

    def test_custom_values(self) -> None:
        config = ContexerConfig(
            llm_provider="openrouter",
            openrouter_api_key="custom_key",
            openrouter_model="google/gemma-4-31b-it:free",
            openrouter_site_url="https://contexer.dev",
            openrouter_app_name="Contexer CLI",
        )
        assert config.openrouter_api_key == "custom_key"
        assert config.openrouter_model == "google/gemma-4-31b-it:free"
        assert config.openrouter_site_url == "https://contexer.dev"
        assert config.openrouter_app_name == "Contexer CLI"

    def test_load_config_from_environment(self) -> None:
        env_patch = {
            "OPENROUTER_API_KEY": "env_test_key",
            "OPENROUTER_MODEL": "google/gemma-4-31b-it:free",
            "OPENROUTER_SITE_URL": "https://contexer.ai",
            "OPENROUTER_APP_NAME": "ContexerAgent",
        }
        with patch.dict(os.environ, env_patch, clear=False):
            config = load_config()
            assert config.openrouter_api_key == "env_test_key"
            assert config.openrouter_model == "google/gemma-4-31b-it:free"
            assert config.openrouter_site_url == "https://contexer.ai"
            assert config.openrouter_app_name == "ContexerAgent"
