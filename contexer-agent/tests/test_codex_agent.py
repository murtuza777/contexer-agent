"""CodexAgent against a fake `codex` that speaks the `codex exec --json` protocol.

The event shapes follow @openai/codex-sdk 0.164's ThreadEvent types; the
auth-failure stream was captured from the real codex 0.164.0 binary.
"""

import json
import sys
import textwrap
from pathlib import Path

import pytest

from contexer.agents import create_agent
from contexer.agents.codex_agent import CodexAgent

pytestmark = pytest.mark.anyio

FAKE = textwrap.dedent(
    r'''
    import json, os, sys, time
    args = sys.argv[1:]
    prompt = sys.stdin.read()
    mode = os.environ.get("FAKE_CODEX_MODE", "ok")
    thread = args[args.index("resume") + 1] if "resume" in args else "0199a213-81c0-7800-8aa1-bbab2a035a53"
    cwd = args[args.index("--cd") + 1]
    def emit(obj): print(json.dumps(obj), flush=True)
    with open("argv.json", "w") as fh: json.dump({"args": args, "prompt": prompt}, fh)
    print("WARNING: proceeding, even though we could not create PATH aliases", flush=True)  # stderr is merged
    emit({"type": "thread.started", "thread_id": thread})
    emit({"type": "turn.started"})
    if mode == "hang":
        time.sleep(60)
    if mode == "auth":
        for n in (2, 3):
            emit({"type": "error", "message": f"Reconnecting... {n}/5 (unexpected status 401 Unauthorized)"})
        emit({"type": "item.completed", "item": {"id": "item_0", "type": "error", "message": "Falling back to HTTPS"}})
        emit({"type": "turn.failed", "error": {"message": "unexpected status 401 Unauthorized: Missing bearer or basic authentication in header"}})
        sys.exit(1)
    if mode == "crash":
        sys.exit(2)
    emit({"type": "item.started", "item": {"id": "item_1", "type": "command_execution", "command": "npm test", "aggregated_output": "", "status": "in_progress"}})
    emit({"type": "item.completed", "item": {"id": "item_1", "type": "command_execution", "command": "npm test", "aggregated_output": "ok", "exit_code": 0, "status": "completed"}})
    with open("app.js", "w") as fh: fh.write("fixed\n")
    emit({"type": "item.completed", "item": {"id": "item_2", "type": "file_change", "status": "completed", "changes": [
        {"path": os.path.join(cwd, "app.js"), "kind": "update"}, {"path": os.path.join(cwd, "src", "new.js"), "kind": "add"}]}})
    emit({"type": "item.completed", "item": {"id": "item_3", "type": "agent_message", "text": "Fixed the counter in app.js"}})
    emit({"type": "turn.completed", "usage": {"input_tokens": 1200, "cached_input_tokens": 0, "cache_write_input_tokens": 0, "output_tokens": 300, "reasoning_output_tokens": 50}})
    '''
)


@pytest.fixture
def fake_codex(tmp_path: Path) -> Path:
    script = tmp_path / "fake_codex.py"
    script.write_text(FAKE, encoding="utf-8")
    if sys.platform == "win32":
        launcher = tmp_path / "codex.cmd"
        launcher.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        launcher = tmp_path / "codex"
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)
    return launcher


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    d = tmp_path / "project"
    d.mkdir()
    (d / "app.js").write_text("broken\n", encoding="utf-8")
    return d


def _recorded(workdir: Path) -> dict:
    return json.loads((workdir / "argv.json").read_text(encoding="utf-8"))


async def test_a_turn_reports_the_thread_edits_and_summary(fake_codex: Path, workdir: Path) -> None:
    progress: list[str] = []
    turn = await CodexAgent(executable=str(fake_codex), model="gpt-5-codex").run_turn(
        workdir, "Make the counter work", on_progress=progress.append
    )

    assert turn.status == "completed", turn.error
    assert turn.session_id == "0199a213-81c0-7800-8aa1-bbab2a035a53"
    assert turn.summary == "Fixed the counter in app.js"
    assert turn.files_touched == ["app.js", "src/new.js"]
    assert turn.tool_calls == 2
    assert turn.cost_usd is None  # Codex reports tokens, not cost
    assert progress == ["$ npm test", "Edited app.js", "Created src/new.js"]
    assert (workdir / "app.js").read_text(encoding="utf-8") == "fixed\n"

    recorded = _recorded(workdir)
    assert recorded["prompt"] == "Make the counter work"  # sent on stdin, not argv
    args = recorded["args"]
    assert args[:2] == ["exec", "--json"] and args[-1] == "-"
    assert args[args.index("--sandbox") + 1] == "workspace-write"
    assert 'approval_policy="never"' in args
    assert "sandbox_workspace_write.network_access=true" in args
    assert args[args.index("--model") + 1] == "gpt-5-codex"
    assert "resume" not in args


async def test_a_repair_turn_resumes_the_same_thread(fake_codex: Path, workdir: Path) -> None:
    turn = await CodexAgent(executable=str(fake_codex)).run_turn(workdir, "Fix it", session_id="thread-7")
    assert turn.ok and turn.session_id == "thread-7"
    assert _recorded(workdir)["args"][-3:] == ["resume", "thread-7", "-"]


async def test_auth_failure_is_a_failed_turn_not_retry_noise(
    fake_codex: Path, workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_CODEX_MODE", "auth")
    turn = await CodexAgent(executable=str(fake_codex)).run_turn(workdir, "Fix it")
    assert turn.status == "failed"
    assert turn.error is not None and turn.error.startswith("unexpected status 401")
    assert turn.session_id == "0199a213-81c0-7800-8aa1-bbab2a035a53"


async def test_a_crash_without_a_result_is_reported(
    fake_codex: Path, workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_CODEX_MODE", "crash")
    turn = await CodexAgent(executable=str(fake_codex)).run_turn(workdir, "Fix it")
    assert turn.status == "failed"
    assert turn.error is not None and "no result from codex" in turn.error


async def test_a_hung_turn_times_out_and_is_killed(
    fake_codex: Path, workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_CODEX_MODE", "hang")
    turn = await CodexAgent(executable=str(fake_codex)).run_turn(workdir, "Fix it", timeout=3)
    assert turn.status == "timeout"


async def test_a_missing_binary_is_a_failed_turn(workdir: Path) -> None:
    turn = await CodexAgent(executable=str(workdir / "no-such-codex")).run_turn(workdir, "Fix it")
    assert turn.status == "failed" and "could not start codex" in (turn.error or "")


def test_create_agent_knows_codex() -> None:
    agent = create_agent("codex", "gpt-5-codex")
    assert isinstance(agent, CodexAgent) and agent.describe() == "codex (gpt-5-codex)"
    with pytest.raises(ValueError, match="claude-code, codex or opencode"):
        create_agent("copilot")
