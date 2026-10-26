"""Coding agents Contexer drives (but never trusts for the verdict)."""

from contexer.agents.base import AgentTurn, CodingAgentAdapter, TurnStatus
from contexer.agents.scripted import ScriptedAgent

__all__ = ["AgentTurn", "CodingAgentAdapter", "ScriptedAgent", "TurnStatus", "create_agent"]


def create_agent(name: str, model: str | None = None) -> CodingAgentAdapter:
    """Build an adapter by name: ``claude-code``, ``codex``, ``opencode``, or ``scripted`` (turns from a file)."""
    if name in ("claude-code", "claude"):
        from contexer.agents.claude_code import ClaudeCodeAgent

        return ClaudeCodeAgent(model=model)
    if name == "codex":
        from contexer.agents.codex_agent import CodexAgent

        return CodexAgent(model=model)
    if name == "opencode":
        from contexer.agents.opencode_agent import OpenCodeAgent

        return OpenCodeAgent(model=model)
    if name == "scripted":
        return ScriptedAgent.from_file(model or "")
    raise ValueError(f"Unknown coding agent '{name}' (choose claude-code, codex or opencode)")
