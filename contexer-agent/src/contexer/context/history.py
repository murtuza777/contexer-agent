"""Provider-neutral conversation history for the generic agent harness.

It is a deliberately small adaptation of AgentForge's context manager: this
milestone needs valid user/assistant/tool ordering and bounded old observations,
not compaction, durable memory, or branchable histories.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConversationContext:
    """Append-only messages for one interactive Contexer session."""

    _messages: list[Any] = field(default_factory=list)

    def add(self, message: Any) -> None:
        self._messages.append(message)

    def messages(self) -> list[Any]:
        """Return a shallow copy suitable for sending to a provider."""
        return list(self._messages)

    def clear(self) -> None:
        self._messages.clear()

    @property
    def size(self) -> int:
        return len(self._messages)
