"""Milestone 3 end-to-end harness tests using deterministic model tool calls."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, AsyncIterator

import pytest

from contexer.config.settings import ContexerConfig
from contexer.llm.base import LLMChunk, LLMProvider, LLMResponse, ToolCallRequest
from contexer.runtime.agent import AgentState, ContexerAgent


class ScriptedProvider(LLMProvider):
    """A provider that makes one known tool call then sends a final answer."""

    def __init__(self, tool_call: ToolCallRequest, final_answer: str) -> None:
        self._responses = [LLMResponse(tool_calls=[tool_call]), LLMResponse(text=final_answer)]
        self.calls: list[str | list[Any]] = []

    @property
    def name(self) -> str:
        return "scripted"

    @property
    def model(self) -> str:
        return "scripted-model"

    def validate_configuration(self) -> tuple[bool, str | None]:
        return True, None

    async def generate(
        self,
        prompt: str | list[Any],
        system_instruction: str | None = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        self.calls.append(prompt)
        return self._responses.pop(0)

    async def stream(
        self,
        prompt: str | list[Any],
        system_instruction: str | None = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMChunk]:
        response = await self.generate(prompt, system_instruction, tools, **kwargs)
        if response.tool_calls:
            yield LLMChunk(tool_calls=response.tool_calls)
        elif response.text:
            yield LLMChunk(text=response.text)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    path = tmp_path / "engineering-project"
    path.mkdir()
    (path / "README.md").write_text("# Sample Project\n\nA test repository.\n", encoding="utf-8")
    (path / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (path / "test_sample.py").write_text("def test_sample() -> None:\n    assert True\n", encoding="utf-8")
    git = shutil.which("git")
    if git:
        subprocess.run([git, "init", "-b", "main"], cwd=path, capture_output=True, check=False)
        subprocess.run([git, "config", "user.email", "tests@example.com"], cwd=path, capture_output=True, check=False)
        subprocess.run([git, "config", "user.name", "Contexer Tests"], cwd=path, capture_output=True, check=False)
        subprocess.run([git, "add", "."], cwd=path, capture_output=True, check=False)
        subprocess.run([git, "commit", "-m", "initial"], cwd=path, capture_output=True, check=False)
    return path


@pytest.mark.parametrize(
    ("user_message", "tool_call", "final_answer"),
    [
        (
            "list the files in this repository",
            ToolCallRequest(name="list_directory", arguments={"path": "."}, call_id="files"),
            "I listed the repository files.",
        ),
        (
            "read README.md and explain the project",
            ToolCallRequest(name="read_file", arguments={"path": "README.md"}, call_id="readme"),
            "The README describes a sample project.",
        ),
        (
            "check git status",
            ToolCallRequest(name="git_status", arguments={}, call_id="status"),
            "The Git status was inspected.",
        ),
        (
            "run the tests",
            ToolCallRequest(
                name="execute_command",
                arguments={"command": f'"{sys.executable}" -m pytest -q'},
                call_id="tests",
            ),
            "The test command completed.",
        ),
    ],
)
def test_complete_model_tool_model_loop(
    workspace: Path,
    user_message: str,
    tool_call: ToolCallRequest,
    final_answer: str,
) -> None:
    """The acceptance actions complete through the actual runtime loop."""
    provider = ScriptedProvider(tool_call, final_answer)
    agent = ContexerAgent(
        config=ContexerConfig(approval_policy="never"),
        llm=provider,
        repo_path=workspace,
    )

    result = asyncio.run(agent.process_message(user_message))

    assert result.state is AgentState.COMPLETED
    assert result.response == final_answer
    assert result.tool_calls == [tool_call.name]
    assert len(provider.calls) == 2
    assert "<untrusted_content source=" in str(provider.calls[1])
    assert agent.session.context.size >= 4
