"""Session state container for the Contexer Agent.

Adapted from AgentForge (MIT License, Copyright (c) 2026 Mohit Goyal).
Holds active conversation context, safety approval managers, circuit breakers,
and loop detectors for a single execution lifecycle.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import uuid

from contexer.context.loop_detector import LoopDetector
from contexer.context.manager import ContextManager
from contexer.safety.approval import ApprovalManager, ApprovalPolicy
from contexer.safety.circuit_breaker import CircuitBreakerRegistry
from contexer.tools.registry import ToolRegistry


class ContexerSession:
    """State container managing runtime lifecycle components for an active session."""

    def __init__(
        self,
        workspace_root: Optional[Path | str] = None,
        approval_policy: ApprovalPolicy | str = ApprovalPolicy.AUTO,
        approval_manager: Optional[ApprovalManager] = None,
        tool_registry: Optional[ToolRegistry] = None,
        max_context_tokens: int = 200_000,
    ) -> None:
        self.session_id = str(uuid.uuid4())
        self.workspace_root = Path(workspace_root) if workspace_root else Path.cwd()
        self.created_at = datetime.now()
        self.updated_at = datetime.now()

        self.approval_manager = approval_manager or ApprovalManager(
            policy=approval_policy,
            workspace_root=self.workspace_root,
        )
        self.tool_registry = tool_registry
        self.circuit_breaker = CircuitBreakerRegistry()
        self.context_manager = ContextManager(max_context_tokens=max_context_tokens)
        self.loop_detector = LoopDetector()

        self.turn_count = 0
        self._cancel_requested = False
        self._running = False

    @property
    def context(self) -> ContextManager:
        """Alias to context_manager for concise access."""
        return self.context_manager

    @property
    def is_running(self) -> bool:
        """Whether an agent execution turn is actively in progress."""
        return self._running

    @property
    def cancel_requested(self) -> bool:
        """Whether cooperative cancellation was requested by the user or system."""
        return self._cancel_requested

    def request_cancel(self) -> None:
        """Signal cooperative cancellation for the active run."""
        self._cancel_requested = True

    def reset_cancel(self) -> None:
        """Clear cancellation state."""
        self._cancel_requested = False

    def start_turn(self) -> int:
        """Begin a new execution turn."""
        self._running = True
        return self.increment_turn()

    def end_turn(self) -> None:
        """Mark the active turn as finished."""
        self._running = False
        self.updated_at = datetime.now()

    def increment_turn(self) -> int:
        """Advance turn counter."""
        self.turn_count += 1
        self.updated_at = datetime.now()
        return self.turn_count

    def reset(self) -> None:
        """Reset session context and loop detectors for a fresh conversation."""
        self.context_manager.clear()
        self.loop_detector.clear()
        self.turn_count = 0
        self.reset_cancel()
        self._running = False
        self.updated_at = datetime.now()


# Compatibility alias for Contexer Agent runtime
AgentSession = ContexerSession
