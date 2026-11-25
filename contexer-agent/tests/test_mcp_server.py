"""`contexer mcp`: the server a coding agent talks to, driven by a real MCP client (INT-1).

The agent may read the approved checks, have them replayed, read its brief and the last run. It may not
approve a contract, edit one or change a setting: no tool does that, and the tests below say so.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

import pytest
from mcp import Client, StdioServerParameters

from contexer.contract import ContractStore
from contexer.controller import RunSettings
from contexer.graph import GraphController
from contexer.integrations.mcp_server import TOOL_NAMES, build_server
from tests.loop_helpers import CONTRACT_ID, COUNT_BUG_JS, GOOD_JS, RecordingAgent, copy_todo, fast_runner

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return copy_todo(tmp_path)


def _text(result: Any) -> str:
    return "\n".join(block.text for block in result.content if getattr(block, "type", "") == "text")


def _defines_done(project: Path) -> dict[str, str]:
    """Every file that says what done is, with its hash."""
    files = [*sorted((project / ".contexer" / "contracts").glob("*.json")), project / "contexer.toml"]
    return {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in files if f.is_file()}


async def test_the_server_offers_four_tools_and_none_of_them_decides_what_done_is(project: Path) -> None:
    async with Client(build_server(project, runner=fast_runner())) as client:
        listed = await client.list_tools()

    names = sorted(tool.name for tool in listed.tools)
    assert names == sorted(TOOL_NAMES) == ["contexer_brief", "contexer_checks", "contexer_status", "contexer_verify"]
    for tool in listed.tools:
        assert tool.description and len(tool.description) > 40
        # Flat inputs: at most one optional string, so the weakest model can call them.
        properties = tool.input_schema.get("properties", {})
        assert set(properties) <= {"contract"}
        assert not tool.input_schema.get("required")
    assert not any(word in name for name in names for word in ("approve", "edit", "write", "set"))


async def test_checks_returns_the_approved_contract_as_the_agent_should_read_it(project: Path) -> None:
    async with Client(build_server(project, runner=fast_runner())) as client:
        result = await client.call_tool("contexer_checks", {})

    text = _text(result)
    assert not result.is_error
    contract = ContractStore(project).load(CONTRACT_ID)
    assert CONTRACT_ID in text and contract.goal in text
    for criterion in contract.criteria:
        assert f"[{criterion.id}]" in text
    assert "expect:" in text  # the steps and expectations, not only the titles


async def test_verify_says_what_the_browser_saw_and_then_that_it_passes(project: Path) -> None:
    (project / "app.js").write_text(COUNT_BUG_JS, encoding="utf-8")
    async with Client(build_server(project, runner=fast_runner())) as client:
        broken = await client.call_tool("contexer_verify", {})
        (project / "app.js").write_text(GOOD_JS, encoding="utf-8")
        fixed = await client.call_tool("contexer_verify", {})

    failing = _text(broken)
    assert not broken.is_error  # a failing check is an answer, not a tool error
    assert "FAIL" in failing and "refuted" in failing
    assert "expected" in failing  # what the check expected and what the browser saw
    assert "Not done" in failing
    passing = _text(fixed)
    assert "PASS" in passing and "refuted" not in passing.replace("0 refuted", "")
    assert "Not done" not in passing


async def test_a_call_that_tries_to_approve_is_refused_and_a_draft_is_not_replayed_as_done(project: Path) -> None:
    store = ContractStore(project)
    draft = store.load(CONTRACT_ID).model_copy(update={"status": "draft", "approval": None})
    store.save(draft)
    before = _defines_done(project)

    async with Client(build_server(project, runner=fast_runner())) as client:
        approve = await client.call_tool("contexer_approve", {"contract": CONTRACT_ID})
        checks = await client.call_tool("contexer_checks", {})
        verify = await client.call_tool("contexer_verify", {"contract": CONTRACT_ID})

    assert approve.is_error
    assert "draft" in _text(checks) and "contexer contract approve" in _text(checks)
    assert "cannot approve" in _text(checks)
    assert verify.is_error and "not approved" in _text(verify)
    assert _defines_done(project) == before
    assert store.load(CONTRACT_ID).status == "draft"


async def test_no_tool_changes_what_defines_done(project: Path) -> None:
    before = _defines_done(project)
    source = (project / "app.js").read_text(encoding="utf-8")

    async with Client(build_server(project, runner=fast_runner())) as client:
        for name in TOOL_NAMES:
            await client.call_tool(name, {})
            await client.call_tool(name, {"contract": CONTRACT_ID})
            await client.call_tool(name, {"contract": "../../outside"})

    assert _defines_done(project) == before
    assert (project / "app.js").read_text(encoding="utf-8") == source  # and none writes the project's code


async def test_brief_is_the_instruction_a_run_would_give_for_the_contract(project: Path) -> None:
    async with Client(build_server(project, runner=fast_runner())) as client:
        result = await client.call_tool("contexer_brief", {"contract": CONTRACT_ID})

    text = _text(result)
    assert not result.is_error
    assert "Acceptance checks" in text and ContractStore(project).load(CONTRACT_ID).goal in text


async def test_status_tells_of_the_last_run(project: Path) -> None:
    async with Client(build_server(project, runner=fast_runner())) as client:
        nothing = await client.call_tool("contexer_status", {})
        controller = GraphController(project, RecordingAgent([{"app.js": GOOD_JS}]), RunSettings(max_repair_rounds=0), runner=fast_runner())
        outcome = await controller.run(ContractStore(project).load(CONTRACT_ID))
        after = await client.call_tool("contexer_status", {})

    assert "No run" in _text(nothing)
    text = _text(after)
    assert outcome.run_id in text and "succeeded" in text and "attempt 1" in text


async def test_a_verify_waits_its_turn_while_a_run_works_in_the_project(project: Path) -> None:
    from contexer.checkpoint.lock import run_lock

    async with Client(build_server(project, runner=fast_runner())) as client:
        with run_lock(project, "20261125-000000-busy"):
            result = await client.call_tool("contexer_verify", {})

    assert result.is_error and "20261125-000000-busy" in _text(result)


async def test_the_command_speaks_the_protocol_over_stdio_and_nothing_else_reaches_stdout(project: Path) -> None:
    import os

    source = str(Path(__file__).resolve().parents[1] / "src")  # this checkout, not an installed copy
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "contexer", "mcp", "--dir", str(project)],
        env={**os.environ, "PYTHONPATH": source},
    )
    async with Client(server) as client:
        listed = await client.list_tools()
        checks = await client.call_tool("contexer_checks", {})

    assert sorted(tool.name for tool in listed.tools) == sorted(TOOL_NAMES)
    assert CONTRACT_ID in _text(checks)
