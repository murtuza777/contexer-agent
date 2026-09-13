"""Unit tests for GitHub MCP configuration and credential privacy."""

from __future__ import annotations

import os
from unittest.mock import patch
import pytest

from contexer.config.settings import ContexerConfig, load_config
from contexer.mcp.server import GitHubMCPServerRunner


def test_mcp_config_defaults():
    config = ContexerConfig()
    assert config.github_mcp_enabled is True
    assert config.github_mcp_read_only is True
    assert config.github_mcp_toolsets == "repos,issues"
    assert config.github_token is None
    assert config.github_mcp_command is None


def test_mcp_config_loads_github_personal_access_token():
    with patch.dict(os.environ, {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_secret_test_token_123"}, clear=False):
        config = load_config()
        assert config.github_token == "ghp_secret_test_token_123"


def test_mcp_config_loads_fallback_github_token():
    with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_fallback_token_456"}, clear=False):
        # Ensure GITHUB_PERSONAL_ACCESS_TOKEN is not interfering
        with patch.dict(os.environ, {"GITHUB_PERSONAL_ACCESS_TOKEN": ""}, clear=False):
            config = load_config()
            assert config.github_token == "ghp_fallback_token_456"


def test_mcp_config_loads_custom_toolsets_and_readonly():
    env = {
        "GITHUB_TOOLSETS": "repos,issues,pull_requests",
        "GITHUB_READ_ONLY": "true",
        "CONTEXER_GITHUB_MCP_COMMAND": "github-mcp-server stdio",
    }
    with patch.dict(os.environ, env, clear=False):
        config = load_config()
        assert config.github_mcp_toolsets == "repos,issues,pull_requests"
        assert config.github_mcp_read_only is True
        assert config.github_mcp_command == "github-mcp-server stdio"


def test_mcp_config_masks_sensitive_token_in_repr():
    config = ContexerConfig(
        github_token="ghp_super_secret_should_never_be_printed",
        openrouter_api_key="sk-or-v1-secret",
    )
    repr_str = repr(config)
    assert "ghp_super_secret_should_never_be_printed" not in repr_str
    assert "sk-or-v1-secret" not in repr_str
    assert "github_token=***" in repr_str
    assert "openrouter_api_key=***" in repr_str


def test_github_mcp_server_runner_properties():
    config = ContexerConfig(
        github_token="ghp_test",
        github_mcp_read_only=True,
        github_mcp_toolsets="repos,issues",
    )
    runner = GitHubMCPServerRunner(config)
    assert runner.token == "ghp_test"
    assert runner.read_only is True
    assert runner.toolsets == "repos,issues"


from unittest.mock import PropertyMock, patch


def test_github_mcp_runner_reports_missing_token():
    config = ContexerConfig(github_token=None)
    with patch.object(GitHubMCPServerRunner, "token", new_callable=PropertyMock) as mock_tok:
        mock_tok.return_value = None
        runner = GitHubMCPServerRunner(config)
        available, reason = runner.check_availability()
        assert available is False
        assert "Personal Access Token is missing" in reason
