"""Typed event streaming hierarchy for Contexer agent harness.

Adapted from AgentForge (MIT License, Copyright (c) 2026 Mohit Goyal).
Decouples agent loop execution from UI rendering, logging, and metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Optional

from contexer.tools.base import ToolResult


class AgentEventType(str, Enum):
    """The type discriminator for agent harness events."""

    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    AGENT_ERROR = "agent_error"

    MESSAGE_START = "message_start"
    MESSAGE_END = "message_end"

    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_COMPLETE = "tool_call_complete"
    TOOL_EXECUTION_UPDATE = "tool_execution_update"

    TEXT_DELTA = "text_delta"
    TEXT_COMPLETE = "text_complete"
    THINKING_DELTA = "thinking_delta"

    RETRY = "retry"
    CIRCUIT_BREAKER = "circuit_breaker"
    COMPACTION = "compaction"
    APPROVAL_DECISION = "approval_decision"
    LOOP_DETECTED = "loop_detected"


class AgentEvent:
    """Base class for all agent-layer events."""

    type: ClassVar[AgentEventType]

    @property
    def data(self) -> dict[str, Any]:
        return {}

    @classmethod
    def agent_start(cls, message: str, run_id: Optional[str] = None) -> AgentStartEvent:
        return AgentStartEvent(message=message, run_id=run_id)

    @classmethod
    def agent_end(
        cls,
        response: Optional[str] = None,
        usage: Optional[dict[str, Any]] = None,
        run_id: Optional[str] = None,
    ) -> AgentEndEvent:
        return AgentEndEvent(response=response, usage=usage, run_id=run_id)

    @classmethod
    def agent_error(cls, error: str, details: Optional[dict[str, Any]] = None) -> AgentErrorEvent:
        return AgentErrorEvent(error=error, details=details or {})

    @classmethod
    def message_start(cls, role: str = "assistant") -> MessageStartEvent:
        return MessageStartEvent(role=role)

    @classmethod
    def message_end(cls, content: str = "", role: str = "assistant") -> MessageEndEvent:
        return MessageEndEvent(content=content, role=role)

    @classmethod
    def text_delta(cls, content: str) -> TextDeltaEvent:
        return TextDeltaEvent(content=content)

    @classmethod
    def text_complete(cls, content: str) -> TextCompleteEvent:
        return TextCompleteEvent(content=content)

    @classmethod
    def thinking_delta(cls, content: str) -> ThinkingDeltaEvent:
        return ThinkingDeltaEvent(content=content)

    @classmethod
    def tool_call_start(cls, call_id: str, name: str, arguments: dict[str, Any]) -> ToolCallStartEvent:
        return ToolCallStartEvent(call_id=call_id, name=name, arguments=arguments)

    @classmethod
    def tool_call_complete(cls, call_id: str, name: str, result: ToolResult) -> ToolCallCompleteEvent:
        return ToolCallCompleteEvent(call_id=call_id, name=name, result=result)

    @classmethod
    def tool_execution_update(cls, call_id: str, name: str, message: str) -> ToolExecutionUpdateEvent:
        return ToolExecutionUpdateEvent(call_id=call_id, name=name, message=message)

    @classmethod
    def retry(cls, model: str, attempt: int, error: str, delay: Optional[float] = None) -> RetryEvent:
        return RetryEvent(model=model, attempt=attempt, error=error, delay=delay)

    @classmethod
    def circuit_breaker(cls, model: str, state: str, message: str = "") -> CircuitBreakerEvent:
        return CircuitBreakerEvent(model=model, state=state, message=message)

    @classmethod
    def compaction(cls, message: str = "", summary_tokens: Optional[int] = None) -> CompactionEvent:
        return CompactionEvent(message=message, summary_tokens=summary_tokens)

    @classmethod
    def approval_decision(cls, tool_name: str, decision: str) -> ApprovalDecisionEvent:
        return ApprovalDecisionEvent(tool_name=tool_name, decision=decision)

    @classmethod
    def loop_detected(cls, message: str) -> LoopDetectedEvent:
        return LoopDetectedEvent(message=message)


@dataclass(frozen=True)
class AgentStartEvent(AgentEvent):
    type: ClassVar[AgentEventType] = AgentEventType.AGENT_START
    message: str
    run_id: Optional[str] = None

    @property
    def data(self) -> dict[str, Any]:
        return {"message": self.message, "run_id": self.run_id}


@dataclass(frozen=True)
class AgentEndEvent(AgentEvent):
    type: ClassVar[AgentEventType] = AgentEventType.AGENT_END
    response: Optional[str] = None
    usage: Optional[dict[str, Any]] = None
    run_id: Optional[str] = None

    @property
    def data(self) -> dict[str, Any]:
        return {
            "response": self.response,
            "usage": self.usage,
            "run_id": self.run_id,
        }


@dataclass(frozen=True)
class AgentErrorEvent(AgentEvent):
    type: ClassVar[AgentEventType] = AgentEventType.AGENT_ERROR
    error: str
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def data(self) -> dict[str, Any]:
        return {"error": self.error, "details": dict(self.details)}


@dataclass(frozen=True)
class MessageStartEvent(AgentEvent):
    type: ClassVar[AgentEventType] = AgentEventType.MESSAGE_START
    role: str = "assistant"

    @property
    def data(self) -> dict[str, Any]:
        return {"role": self.role}


@dataclass(frozen=True)
class MessageEndEvent(AgentEvent):
    type: ClassVar[AgentEventType] = AgentEventType.MESSAGE_END
    content: str = ""
    role: str = "assistant"

    @property
    def data(self) -> dict[str, Any]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class TextDeltaEvent(AgentEvent):
    type: ClassVar[AgentEventType] = AgentEventType.TEXT_DELTA
    content: str

    @property
    def data(self) -> dict[str, Any]:
        return {"content": self.content}


@dataclass(frozen=True)
class TextCompleteEvent(AgentEvent):
    type: ClassVar[AgentEventType] = AgentEventType.TEXT_COMPLETE
    content: str

    @property
    def data(self) -> dict[str, Any]:
        return {"content": self.content}


@dataclass(frozen=True)
class ThinkingDeltaEvent(AgentEvent):
    type: ClassVar[AgentEventType] = AgentEventType.THINKING_DELTA
    content: str

    @property
    def data(self) -> dict[str, Any]:
        return {"content": self.content}


@dataclass(frozen=True)
class ToolCallStartEvent(AgentEvent):
    type: ClassVar[AgentEventType] = AgentEventType.TOOL_CALL_START
    call_id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    @property
    def data(self) -> dict[str, Any]:
        return {"call_id": self.call_id, "name": self.name, "arguments": dict(self.arguments)}


@dataclass(frozen=True)
class ToolCallCompleteEvent(AgentEvent):
    type: ClassVar[AgentEventType] = AgentEventType.TOOL_CALL_COMPLETE
    call_id: str
    name: str
    result: ToolResult

    @property
    def data(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "name": self.name,
            "success": self.result.success,
            "output": self.result.output,
            "error": self.result.error,
            "metadata": self.result.metadata,
            "summary": self.result.summary,
            "diff_text": self.result.diff_text,
            "exit_code": self.result.exit_code,
        }


@dataclass(frozen=True)
class ToolExecutionUpdateEvent(AgentEvent):
    type: ClassVar[AgentEventType] = AgentEventType.TOOL_EXECUTION_UPDATE
    call_id: str
    name: str
    message: str

    @property
    def data(self) -> dict[str, Any]:
        return {"call_id": self.call_id, "name": self.name, "message": self.message}


@dataclass(frozen=True)
class RetryEvent(AgentEvent):
    type: ClassVar[AgentEventType] = AgentEventType.RETRY
    model: str
    attempt: int
    error: str
    delay: Optional[float] = None

    @property
    def data(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "attempt": self.attempt,
            "error": self.error,
            "delay": self.delay,
        }


@dataclass(frozen=True)
class CircuitBreakerEvent(AgentEvent):
    type: ClassVar[AgentEventType] = AgentEventType.CIRCUIT_BREAKER
    model: str
    state: str
    message: str = ""

    @property
    def data(self) -> dict[str, Any]:
        return {"model": self.model, "state": self.state, "message": self.message}


@dataclass(frozen=True)
class CompactionEvent(AgentEvent):
    type: ClassVar[AgentEventType] = AgentEventType.COMPACTION
    message: str = ""
    summary_tokens: Optional[int] = None

    @property
    def data(self) -> dict[str, Any]:
        return {"message": self.message, "summary_tokens": self.summary_tokens}


@dataclass(frozen=True)
class ApprovalDecisionEvent(AgentEvent):
    type: ClassVar[AgentEventType] = AgentEventType.APPROVAL_DECISION
    tool_name: str
    decision: str

    @property
    def data(self) -> dict[str, Any]:
        return {"tool_name": self.tool_name, "decision": self.decision}


@dataclass(frozen=True)
class LoopDetectedEvent(AgentEvent):
    type: ClassVar[AgentEventType] = AgentEventType.LOOP_DETECTED
    message: str

    @property
    def data(self) -> dict[str, Any]:
        return {"message": self.message}
