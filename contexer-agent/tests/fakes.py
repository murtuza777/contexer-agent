"""Test doubles for the agents: a chat model that replays a script, so no test needs a model or a network."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


def calls(*tool_calls: tuple[str, dict[str, Any]], text: str = "", tokens: tuple[int, int] = (10, 5)) -> AIMessage:
    """A model reply that calls tools: ``calls(("click", {"text": "Add"}))``."""
    return AIMessage(
        content=text,
        tool_calls=[{"name": name, "args": args, "id": f"call_{i}_{name}", "type": "tool_call"} for i, (name, args) in enumerate(tool_calls)],
        usage_metadata={"input_tokens": tokens[0], "output_tokens": tokens[1], "total_tokens": sum(tokens)},
    )


def submit(**answer: Any) -> AIMessage:
    """A model reply that hands in the final answer."""
    return calls(("submit", answer))


def says(text: str, tokens: tuple[int, int] = (10, 5)) -> AIMessage:
    """A model reply with text only."""
    return AIMessage(
        content=text,
        usage_metadata={"input_tokens": tokens[0], "output_tokens": tokens[1], "total_tokens": sum(tokens)},
    )


Reply = AIMessage | Exception | Callable[[list[BaseMessage]], AIMessage]


class ScriptedChatModel(BaseChatModel):
    """Returns (or raises) queued replies in order and records what it was sent.

    A reply may be a message, an exception to raise, or a function of the
    messages so far. ``delay`` makes every call take that long, for timeouts.
    """

    replies: list[Any] = Field(default_factory=list)
    delay: float = 0.0
    model_name: str = "scripted-model"
    # What each call received: the messages, and the options (max_tokens...).
    seen: list[list[BaseMessage]] = Field(default_factory=list)
    options: list[dict[str, Any]] = Field(default_factory=list)
    bound_tools: list[str] = Field(default_factory=list)
    # How many callback handlers (tracers) each call carried.
    callbacks_seen: list[int] = Field(default_factory=list)

    def __init__(self, *replies: Reply, **kwargs: Any) -> None:
        super().__init__(replies=list(replies), **kwargs)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Any:
        self.bound_tools = [getattr(tool, "name", str(tool)) for tool in tools]
        return self.bind(**kwargs)

    def _next(self, messages: list[BaseMessage], kwargs: dict[str, Any], run_manager: Any = None) -> ChatResult:
        self.seen.append(list(messages))
        self.callbacks_seen.append(len(getattr(run_manager, "handlers", None) or []))
        self.options.append(dict(kwargs))
        if not self.replies:
            raise AssertionError("ScriptedChatModel received an unexpected call")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if callable(reply):
            reply = reply(list(messages))
        return ChatResult(generations=[ChatGeneration(message=reply)])

    def _generate(self, messages: list[BaseMessage], stop: Optional[list[str]] = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        return self._next(messages, kwargs, run_manager)

    async def _agenerate(self, messages: list[BaseMessage], stop: Optional[list[str]] = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        if self.delay:
            await asyncio.sleep(self.delay)
        return self._next(messages, kwargs, run_manager)
