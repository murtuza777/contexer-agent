"""Context and conversation history manager for Contexer Agent.

Adapted from AgentForge (MIT License, Copyright (c) 2026 Mohit Goyal).
Maintains coherent multi-turn message history, OpenAI-compatible role serialization,
token budget estimations, and old tool output pruning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class MessageItem:
    """Individual turn message representation in conversation context."""

    role: str
    content: str = ""
    tool_call_id: Optional[str] = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to OpenAI-compatible message dictionary format."""
        result: dict[str, Any] = {"role": self.role}

        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id

        if self.tool_calls:
            result["tool_calls"] = self.tool_calls

        if self.content or not self.tool_calls:
            result["content"] = self.content

        return result


class ContextManager:
    """Manages the agent's message transcript, budgeting, and tool output pruning."""

    def __init__(
        self,
        system_prompt: str = "",
        max_context_tokens: int = 200_000,
        max_tool_output_chars: int = 20_000,
    ) -> None:
        self.system_prompt = system_prompt
        self.max_context_tokens = max_context_tokens
        self.max_tool_output_chars = max_tool_output_chars
        self._messages: list[MessageItem] = []

    @property
    def size(self) -> int:
        """Number of messages currently tracked in context."""
        return len(self._messages)

    def __len__(self) -> int:
        return len(self._messages)

    def set_system_prompt(self, prompt: str) -> None:
        """Update system instruction."""
        self.system_prompt = prompt

    def add_user_message(self, content: str) -> None:
        """Append a user message to the context transcript."""
        self._messages.append(MessageItem(role="user", content=content))

    def add_assistant_message(
        self,
        content: Optional[str] = None,
        tool_calls: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        """Append an assistant response with optional tool calls."""
        self._messages.append(
            MessageItem(
                role="assistant",
                content=content or "",
                tool_calls=tool_calls or [],
            )
        )

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        """Append a tool result turn matching a prior assistant tool call."""
        self._messages.append(
            MessageItem(
                role="tool",
                content=content,
                tool_call_id=tool_call_id,
            )
        )

    def add(self, message: Any) -> None:
        """Add a dict or list of message dicts to context."""
        if isinstance(message, dict):
            self._messages.append(
                MessageItem(
                    role=message.get("role", "user"),
                    content=message.get("content") or "",
                    tool_call_id=message.get("tool_call_id"),
                    tool_calls=message.get("tool_calls") or [],
                )
            )
        elif isinstance(message, list):
            for m in message:
                self.add(m)

    def messages(self) -> list[dict[str, Any]]:
        """Return the complete message history in standard provider dict format."""
        return self.get_messages()

    def get_messages(self) -> list[dict[str, Any]]:
        """Return the complete message history in standard provider dict format."""
        return [msg.to_dict() for msg in self._messages]

    def estimate_tokens(self) -> int:
        """Estimate context size based on heuristic ~4 chars per token."""
        total_chars = sum(len(m.content) for m in self._messages)
        return total_chars // 4

    def prune_tool_outputs(self, keep_recent_tool_results: int = 4) -> int:
        """Truncate older tool outputs in long conversations to reclaim context space.

        Returns:
            Number of tool result messages pruned.
        """
        tool_indices = [
            i for i, m in enumerate(self._messages) if m.role == "tool"
        ]
        if len(tool_indices) <= keep_recent_tool_results:
            return 0

        prune_targets = tool_indices[:-keep_recent_tool_results]
        pruned_count = 0

        for idx in prune_targets:
            item = self._messages[idx]
            if len(item.content) > 500:
                first_line = item.content.splitlines()[0] if item.content else ""
                item.content = f"{first_line}\n... [prior tool result pruned to conserve context]"
                pruned_count += 1

        return pruned_count

    def clear(self) -> None:
        """Reset conversation transcript."""
        self._messages.clear()
