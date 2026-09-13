"""Tests for Contexer Agent runtime and LLM integration."""

import asyncio
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from contexer.config.settings import ContexerConfig
from contexer.llm.base import LLMChunk, LLMProvider, LLMResponse
from contexer.runtime.agent import AgentResult, AgentState, ContexerAgent


class TestAgentState:
    """Agent lifecycle state enum."""

    def test_state_members(self) -> None:
        expected_names = {
            "IDLE",
            "PLANNING",
            "AWAITING_APPROVAL",
            "EXECUTING",
            "OBSERVING",
            "VERIFYING",
            "DIAGNOSING",
            "REPAIRING",
            "COMPLETED",
            "FAILED",
        }
        actual_names = {state.name for state in AgentState}
        assert expected_names == actual_names


class TestAgentResult:
    """AgentResult dataclass."""

    def test_defaults(self) -> None:
        result = AgentResult()
        assert result.state == AgentState.IDLE
        assert result.response == ""
        assert result.error is None
        assert result.metadata == {}

    def test_custom_values(self) -> None:
        result = AgentResult(
            state=AgentState.COMPLETED,
            response="Task completed",
            error=None,
            metadata={"step_count": 3},
        )
        assert result.state == AgentState.COMPLETED
        assert result.response == "Task completed"
        assert result.metadata["step_count"] == 3


class MockProvider(LLMProvider):
    """Mock LLMProvider for testing agent orchestration."""

    def __init__(self, valid: bool = True, error_msg: str = "") -> None:
        self._valid = valid
        self._error_msg = error_msg

    @property
    def name(self) -> str:
        return "mock"

    @property
    def model(self) -> str:
        return "mock-model"

    def validate_configuration(self) -> tuple[bool, str | None]:
        if not self._valid:
            return False, self._error_msg or "Missing key"
        return True, None

    @staticmethod
    def _extract_prompt_text(prompt: str | list[Any]) -> str:
        if isinstance(prompt, str):
            return prompt
        if isinstance(prompt, list) and len(prompt) > 0:
            first = prompt[0]
            if isinstance(first, dict) and "content" in first:
                return str(first["content"])
            if hasattr(first, "text"):
                return str(getattr(first, "text", ""))
        return str(prompt)

    async def generate(
        self,
        prompt: str | list[Any],
        system_instruction: str | None = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        text = self._extract_prompt_text(prompt)
        return LLMResponse(text=f"Echo: {text}", model="mock-model")

    async def stream(
        self,
        prompt: str | list[Any],
        system_instruction: str | None = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMChunk]:
        text = self._extract_prompt_text(prompt)
        yield LLMChunk(text=f"Echo: {text}")



class TestContexerAgent:
    """ContexerAgent interface tests."""

    def test_init_defaults(self) -> None:
        agent = ContexerAgent()
        assert agent.state == AgentState.IDLE
        assert isinstance(agent.config, ContexerConfig)

    def test_init_custom_config(self) -> None:
        cfg = ContexerConfig(verbose=True)
        agent = ContexerAgent(config=cfg)
        assert agent.config.verbose is True

    def test_gather_repository_context(self) -> None:
        agent = ContexerAgent()
        context = agent.gather_repository_context()
        assert "Project Root:" in context

    def test_process_message_validation_failure(self) -> None:
        # Default config has no OPENROUTER_API_KEY set
        agent = ContexerAgent(llm=MockProvider(valid=False, error_msg="Configure OPENROUTER_API_KEY"))
        result = asyncio.run(agent.process_message("Explain architecture"))
        assert result.state == AgentState.FAILED
        assert "Configure OPENROUTER_API_KEY" in result.response

    def test_process_message_success(self) -> None:
        agent = ContexerAgent(llm=MockProvider(valid=True))
        result = asyncio.run(agent.process_message("Explain architecture"))
        assert result.state == AgentState.COMPLETED
        assert "Echo: Explain architecture" in result.response
        assert result.metadata["model"] == "mock-model"

    def test_stream_message_success(self) -> None:
        agent = ContexerAgent(llm=MockProvider(valid=True))

        async def collect():
            chunks = []
            async for token in agent.stream_message("Hello"):
                chunks.append(token)
            return "".join(chunks)

        text = asyncio.run(collect())
        assert text == "Echo: Hello"
        assert agent.state == AgentState.COMPLETED

    def test_interrupt(self) -> None:
        agent = ContexerAgent()
        agent.state = AgentState.EXECUTING
        agent.interrupt()
        assert agent.state == AgentState.IDLE

    def test_shutdown(self) -> None:
        agent = ContexerAgent()
        agent.state = AgentState.PLANNING
        agent.shutdown()
        assert agent.state == AgentState.IDLE
