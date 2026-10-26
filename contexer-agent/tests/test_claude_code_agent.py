"""ClaudeCodeAgent against a fake `claude` that speaks the stream-json protocol."""

import json
import sys
import textwrap
from pathlib import Path

import pytest

from contexer.agents.claude_code import ClaudeCodeAgent, agent_env

pytestmark = pytest.mark.anyio

FAKE = textwrap.dedent(
    r'''
    import json, os, sys, time
    args = sys.argv[1:]
    prompt = sys.stdin.read()
    mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
    session = args[args.index("--resume") + 1] if "--resume" in args else "sess-new"
    def emit(obj): print(json.dumps(obj), flush=True)
    with open("argv.json", "w") as fh: json.dump({"args": args, "prompt": prompt, "env": sorted(os.environ)}, fh)
    emit({"type": "system", "subtype": "init", "session_id": session})
    if mode == "hang":
        time.sleep(60)
    emit({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "Fixing the counter"},
        {"type": "tool_use", "name": "Edit", "input": {"file_path": "app.js", "old_string": "a", "new_string": "b"}}]}})
    with open("app.js", "w") as fh: fh.write("fixed\n")
    if mode == "error":
        emit({"type": "result", "subtype": "success", "is_error": True, "result": "Credit balance is too low",
              "session_id": session, "total_cost_usd": 0, "terminal_reason": "api_error"})
    elif mode == "budget":
        emit({"type": "result", "subtype": "error_max_budget_usd", "is_error": True, "session_id": session,
              "total_cost_usd": 0.5})
    else:
        emit({"type": "result", "subtype": "success", "is_error": False, "result": "Changed app.js",
              "session_id": session, "total_cost_usd": 0.0123, "num_turns": 3,
              "permission_denials": [{"tool_name": "Write", "tool_input": {"file_path": ".contexer/contracts/x.json"}}]})
    '''
)


@pytest.fixture
def fake_claude(tmp_path: Path) -> Path:
    script = tmp_path / "fake_claude.py"
    script.write_text(FAKE, encoding="utf-8")
    if sys.platform == "win32":
        launcher = tmp_path / "claude.cmd"
        launcher.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        launcher = tmp_path / "claude"
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)
    return launcher


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    d = tmp_path / "project"
    d.mkdir()
    (d / "app.js").write_text("broken\n", encoding="utf-8")
    return d


async def test_completed_turn_is_parsed_and_files_change(fake_claude: Path, workdir: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "parent-session")  # a hosting session's plumbing
    progress: list[str] = []
    turn = await ClaudeCodeAgent(executable=str(fake_claude)).run_turn(
        workdir, "Make the counter work", timeout=60, budget_usd=1.5, on_progress=progress.append
    )
    assert turn.status == "completed", turn.error
    assert turn.session_id == "sess-new"
    assert turn.cost_usd == pytest.approx(0.0123)
    assert turn.tool_calls == 1 and turn.files_touched == ["app.js"]
    assert turn.permission_denials == ["Write .contexer/contracts/x.json"]
    assert progress == ["Edit app.js"]
    assert (workdir / "app.js").read_text(encoding="utf-8") == "fixed\n"

    seen = json.loads((workdir / "argv.json").read_text(encoding="utf-8"))
    assert seen["prompt"] == "Make the counter work"  # delivered on stdin
    args = seen["args"]
    assert args[:2] == ["-p", "--output-format"] and "stream-json" in args
    assert args[args.index("--permission-mode") + 1] == "acceptEdits"
    assert "Edit(.contexer/**)" in args[args.index("--disallowedTools") + 1]
    assert args[args.index("--max-budget-usd") + 1] == "1.50"
    assert "CLAUDE_CODE_SESSION_ID" not in seen["env"]  # not inherited by the spawned agent


async def test_resume_passes_the_session_id(fake_claude: Path, workdir: Path) -> None:
    turn = await ClaudeCodeAgent(executable=str(fake_claude)).run_turn(workdir, "again", session_id="sess-7", timeout=60)
    assert turn.session_id == "sess-7"
    args = json.loads((workdir / "argv.json").read_text(encoding="utf-8"))["args"]
    assert args[args.index("--resume") + 1] == "sess-7"


async def test_api_errors_and_budget_are_reported_not_hidden(fake_claude: Path, workdir: Path, monkeypatch) -> None:
    agent = ClaudeCodeAgent(executable=str(fake_claude))
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "error")
    turn = await agent.run_turn(workdir, "x", timeout=60)
    assert turn.status == "failed"
    assert turn.error == "api_error: Credit balance is too low"

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "budget")
    turn = await agent.run_turn(workdir, "x", timeout=60)
    assert turn.status == "budget_exceeded"


async def test_a_hung_agent_times_out_and_is_killed(fake_claude: Path, workdir: Path, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "hang")
    turn = await ClaudeCodeAgent(executable=str(fake_claude)).run_turn(workdir, "x", timeout=3)
    assert turn.status == "timeout"
    assert turn.session_id == "sess-new"  # known from the init line, so a repair can resume it
    assert turn.duration_seconds < 20


async def test_stopping_a_turn_kills_the_agent_at_once(fake_claude: Path, workdir: Path, monkeypatch) -> None:
    """Ctrl+C cancels the turn: the agent must not keep editing files after Contexer stops."""
    import asyncio
    import time

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "hang")
    agent = ClaudeCodeAgent(executable=str(fake_claude))
    task = asyncio.create_task(agent.run_turn(workdir, "x", timeout=120))
    deadline = time.monotonic() + 30
    while not (workdir / "argv.json").exists() or not agent._in_flight:
        assert time.monotonic() < deadline, "the fake agent never started"
        await asyncio.sleep(0.1)
    tree = next(iter(agent._in_flight))
    started = time.monotonic()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert tree.poll() is not None, "the agent process is still running"
    assert time.monotonic() - started < 10
    while agent._in_flight and time.monotonic() - started < 10:
        await asyncio.sleep(0.1)  # the worker thread notices the exit and lets go
    assert not agent._in_flight
    assert (workdir / "app.js").read_text(encoding="utf-8") == "broken\n"  # it never got to edit


def test_agent_env_strips_only_parent_session_plumbing(monkeypatch) -> None:
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_TOKEN", "secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "user-key")
    env = agent_env()
    assert "CLAUDECODE" not in env and "CLAUDE_CODE_MESSAGING_TOKEN" not in env
    assert env["ANTHROPIC_API_KEY"] == "user-key"  # the user's own credentials pass through untouched
