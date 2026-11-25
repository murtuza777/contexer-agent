"""`contexer init --agent NAME`: one command sets a coding agent up to work under Contexer (DX-1).

It registers the MCP server, writes the stop hook where the agent has one, and tells the agent, in the file
that agent reads, when to call Contexer and that it may not edit `.contexer/`. What a person already has in
those files is kept.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from contexer.cli import app
from contexer.integrations.agent_setup import INSTRUCTIONS_MARK
from tests.loop_helpers import copy_todo


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return copy_todo(tmp_path)


def _init(project: Path, agent: str) -> str:
    result = CliRunner().invoke(app, ["init", "--dir", str(project), "--agent", agent])
    assert result.exit_code == 0, result.output
    return " ".join(result.output.split())


def _says_the_rules(text: str) -> None:
    assert "contexer_checks" in text and "contexer_verify" in text
    assert ".contexer/" in text and "approve" in text  # it may not edit the checks or approve them


# -- Claude Code ----------------------------------------------------------------------------------------


def test_claude_code_gets_the_server_the_hook_and_a_skill(project: Path) -> None:
    _init(project, "claude-code")

    servers = json.loads((project / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert servers["contexer"] == {"command": "contexer", "args": ["mcp"]}
    assert "contexer hook stop" in (project / ".claude" / "settings.json").read_text(encoding="utf-8")
    skill = (project / ".claude" / "skills" / "contexer" / "SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\nname: contexer\ndescription: ")
    _says_the_rules(skill)


def test_claude_code_keeps_the_servers_a_person_already_has_and_adds_ours_once(project: Path) -> None:
    mine = {"mcpServers": {"sentry": {"type": "http", "url": "https://mcp.example.test"}}, "other": 1}
    (project / ".mcp.json").write_text(json.dumps(mine), encoding="utf-8")

    _init(project, "claude-code")
    said = _init(project, "claude-code")

    data = json.loads((project / ".mcp.json").read_text(encoding="utf-8"))
    assert data["other"] == 1 and data["mcpServers"]["sentry"] == mine["mcpServers"]["sentry"]
    assert list(data["mcpServers"]) == ["sentry", "contexer"]
    assert "already" in said


def test_a_server_file_that_cannot_be_read_and_a_skill_a_person_wrote_are_left_alone(project: Path) -> None:
    (project / ".mcp.json").write_text("{ not json", encoding="utf-8")
    skill = project / ".claude" / "skills" / "contexer" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("my own notes\n", encoding="utf-8")

    said = _init(project, "claude-code")

    assert (project / ".mcp.json").read_text(encoding="utf-8") == "{ not json"
    assert skill.read_text(encoding="utf-8") == "my own notes\n"
    assert "left unchanged" in said


# -- Codex ----------------------------------------------------------------------------------------------


def test_codex_gets_the_server_the_hook_and_instructions(project: Path) -> None:
    said = _init(project, "codex")

    config = tomllib.loads((project / ".codex" / "config.toml").read_text(encoding="utf-8"))
    assert config["mcp_servers"]["contexer"] == {"command": "contexer", "args": ["mcp"]}
    assert "contexer hook stop" in (project / ".codex" / "hooks.json").read_text(encoding="utf-8")
    _says_the_rules((project / "AGENTS.md").read_text(encoding="utf-8"))
    assert "trust" in said  # Codex reads a project's .codex/ only once the project is trusted


def test_codex_config_and_instructions_a_person_already_has_are_kept(project: Path) -> None:
    config = project / ".codex" / "config.toml"
    config.parent.mkdir()
    config.write_text('model = "gpt-5.4"\n\n[mcp_servers.docs]\ncommand = "npx"\nargs = ["-y", "docs-mcp"]', encoding="utf-8")
    (project / "AGENTS.md").write_text("# House rules\n\nUse tabs.\n", encoding="utf-8")

    _init(project, "codex")
    _init(project, "codex")

    parsed = tomllib.loads(config.read_text(encoding="utf-8"))
    assert parsed["model"] == "gpt-5.4" and parsed["mcp_servers"]["docs"]["command"] == "npx"
    assert parsed["mcp_servers"]["contexer"]["args"] == ["mcp"]
    agents = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith("# House rules\n\nUse tabs.\n")
    assert agents.count(INSTRUCTIONS_MARK) == 1


def test_a_codex_config_that_is_not_toml_is_left_alone(project: Path) -> None:
    config = project / ".codex" / "config.toml"
    config.parent.mkdir()
    config.write_text("this = is = not toml", encoding="utf-8")

    said = _init(project, "codex")

    assert config.read_text(encoding="utf-8") == "this = is = not toml"
    assert "left unchanged" in said


# -- OpenCode -------------------------------------------------------------------------------------------


def test_opencode_gets_instructions_and_is_told_how_to_add_the_server(project: Path) -> None:
    said = _init(project, "opencode")

    _says_the_rules((project / "AGENTS.md").read_text(encoding="utf-8"))
    assert "opencode mcp add" in said  # its config format differs between versions, so its own command writes it
    assert "no hook" in said
    assert not (project / "opencode.json").exists() and not (project / ".opencode").exists()


def test_nothing_is_written_for_an_agent_when_none_is_named(project: Path) -> None:
    result = CliRunner().invoke(app, ["init", "--dir", str(project)])

    assert result.exit_code == 0, result.output
    for name in (".mcp.json", ".claude", ".codex", "AGENTS.md"):
        assert not (project / name).exists()
