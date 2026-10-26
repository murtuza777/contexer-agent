"""OpenCodeAgent reports tool calls while a turn runs (the HTTP turn itself is silent until it ends)."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from contexer.agents.opencode_agent import OpenCodeAgent
from contexer.opencode.models import (
    ExecutionStatus,
    OpenCodeExecutionResult,
    OpenCodeMessage,
    OpenCodeMessageInfo,
    OpenCodePart,
)

pytestmark = pytest.mark.anyio


def _tool(part_id: str, tool: str, status: str, **params: str) -> OpenCodePart:
    return OpenCodePart(type="tool", id=part_id, tool=tool, state={"status": status, "input": params})


class _FakeAdapter:
    """A session that gains tool parts while the turn runs, like `opencode serve` (shapes from opencode 1.4.3)."""

    def __init__(self, workdir: Path) -> None:
        self.parts: list[OpenCodePart] = []
        self.workdir = workdir

    async def create_session(self, title: str, directory: str) -> SimpleNamespace:
        return SimpleNamespace(id="ses_1")

    async def get_messages(self, session_id: str) -> list[OpenCodeMessage]:
        info = OpenCodeMessageInfo(id="msg_1", role="assistant")
        return [OpenCodeMessage(info=info, parts=list(self.parts))]

    async def send_prompt(self, session_id: str, prompt: str, wait: bool, timeout: float) -> OpenCodeExecutionResult:
        self.parts.append(OpenCodePart(type="reasoning", text="Let me look"))
        self.parts.append(_tool("p1", "glob", "completed", pattern="**/*"))
        await asyncio.sleep(0.25)
        self.parts.append(_tool("p2", "read", "completed", filePath=str(self.workdir / "app.js")))
        self.parts.append(_tool("p3", "edit", "running", filePath=str(self.workdir / "app.js")))
        await asyncio.sleep(0.25)
        self.parts[-1] = _tool("p3", "edit", "completed", filePath=str(self.workdir / "app.js"))  # same call, finished
        self.parts.append(_tool("p4", "bash", "completed", command="npm test"))  # lands after the last poll
        return OpenCodeExecutionResult(session_id=session_id, status=ExecutionStatus.COMPLETED, response_text="Done")


async def test_tool_calls_are_reported_once_each_while_the_turn_runs(tmp_path: Path) -> None:
    agent = OpenCodeAgent(model="openrouter/some/model:free", start_server=False)
    fake = _FakeAdapter(tmp_path)
    agent._ensure_server = lambda workdir: fake  # type: ignore[method-assign]
    import contexer.agents.opencode_agent as module

    original = module._ToolWatch.__init__

    def fast(self, workdir: Path, interval: float = 0.1) -> None:
        original(self, workdir, interval)

    module._ToolWatch.__init__ = fast  # type: ignore[method-assign]
    try:
        progress: list[str] = []
        turn = await agent.run_turn(tmp_path, "Add delete buttons", on_progress=progress.append)
    finally:
        module._ToolWatch.__init__ = original  # type: ignore[method-assign]

    assert turn.status == "completed" and turn.summary == "Done"
    assert progress[0] == "OpenCode session ses_1 working"
    assert progress[1:] == ["glob **/*", "read app.js", "edit app.js", "bash npm test"]
    assert turn.tool_calls == 4
