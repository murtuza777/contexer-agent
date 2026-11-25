"""The stop hook: a coding agent may not end its turn while an approved check fails (INT-2).

A rule in a prompt is advice; a hook is code. The hook replays the approved contracts when the agent says it
is done, and hands back what failed. It gives up after a few times in a row and says so, and it never
changes what defines done.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from contexer.checkpoint.lock import run_lock
from contexer.cli import app
from contexer.contract import ContractStore
from contexer.integrations.stop_hook import MAX_BLOCKS, STATE_FILE, answer_stop, claude_code_output
from contexer.verification.runner import CheckRunner
from tests.loop_helpers import CONTRACT_ID, COUNT_BUG_JS, GOOD_JS, copy_todo, fast_runner


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return copy_todo(tmp_path)


def _break(project: Path) -> None:
    (project / "app.js").write_text(COUNT_BUG_JS, encoding="utf-8")


def _runs(project: Path) -> int:
    runs = project / ".contexer" / "runs"
    return len([p for p in runs.iterdir() if p.is_dir()]) if runs.is_dir() else 0


def _defines_done(project: Path) -> dict[str, str]:
    files = [*sorted((project / ".contexer" / "contracts").glob("*.json")), project / "contexer.toml"]
    return {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in files if f.is_file()}


def test_a_failing_check_blocks_the_stop_and_says_what_the_browser_saw(project: Path) -> None:
    _break(project)

    answer = answer_stop(project, {"session_id": "s1"}, make_runner=fast_runner)

    assert answer.block
    assert "FAIL" in answer.message and "expected" in answer.message and "actual" in answer.message
    assert "Do not edit the checks" in answer.message
    assert f"1 of {MAX_BLOCKS}" in answer.message  # the agent is told how many tries are left


def test_a_passing_project_lets_the_agent_stop_and_says_nothing(project: Path) -> None:
    answer = answer_stop(project, {"session_id": "s1"}, make_runner=fast_runner)

    assert not answer.block and answer.message == ""
    assert claude_code_output(answer) == ""


def test_a_fix_between_two_stops_is_seen(project: Path) -> None:
    _break(project)
    first = answer_stop(project, {"session_id": "s1"}, make_runner=fast_runner)
    (project / "app.js").write_text(GOOD_JS, encoding="utf-8")
    second = answer_stop(project, {"session_id": "s1"}, make_runner=fast_runner)

    assert first.block and not second.block


def test_a_check_that_cannot_pass_does_not_loop_for_ever(project: Path) -> None:
    _break(project)

    answers = [answer_stop(project, {"session_id": "s1"}, max_blocks=2, make_runner=fast_runner) for _ in range(3)]

    assert [a.block for a in answers] == [True, True, False]
    gave_up = answers[-1].message
    assert "not proven" in gave_up.lower() and "2" in gave_up  # it stops, and says the work is not proven
    # ... and it does not start again on the next stop while nothing has changed.
    runs = _runs(project)
    again = answer_stop(project, {"session_id": "s1"}, max_blocks=2, make_runner=fast_runner)
    assert not again.block and _runs(project) == runs


def test_a_change_after_giving_up_is_checked_again(project: Path) -> None:
    _break(project)
    for _ in range(2):
        answer_stop(project, {"session_id": "s1"}, max_blocks=1, make_runner=fast_runner)
    (project / "app.js").write_text(COUNT_BUG_JS + "\n// another try\n", encoding="utf-8")

    answer = answer_stop(project, {"session_id": "s1"}, max_blocks=1, make_runner=fast_runner)

    assert answer.block


def test_a_new_session_starts_its_own_count(project: Path) -> None:
    _break(project)
    answer_stop(project, {"session_id": "s1"}, max_blocks=2, make_runner=fast_runner)
    answer_stop(project, {"session_id": "s1"}, max_blocks=2, make_runner=fast_runner)

    other = answer_stop(project, {"session_id": "s2"}, max_blocks=2, make_runner=fast_runner)

    assert other.block and "1 of 2" in other.message


def test_nothing_is_replayed_when_nothing_changed_since_it_passed(project: Path) -> None:
    made: list[CheckRunner] = []

    def counting() -> CheckRunner:
        made.append(fast_runner())
        return made[-1]

    first = answer_stop(project, {"session_id": "s1"}, make_runner=counting)
    second = answer_stop(project, {"session_id": "s1"}, make_runner=counting)  # a turn that only answered a question

    assert not first.block and not second.block
    assert len(made) == 1 and _runs(project) == 1


def test_a_project_with_no_approved_contract_is_left_alone(project: Path) -> None:
    store = ContractStore(project)
    store.save(store.load(CONTRACT_ID).model_copy(update={"status": "draft", "approval": None}))
    _break(project)

    answer = answer_stop(project, {"session_id": "s1"}, make_runner=fast_runner)

    assert not answer.block and answer.message == ""
    assert _runs(project) == 0


def test_a_folder_that_is_not_a_contexer_project_is_left_alone_and_not_written_to(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")

    answer = answer_stop(tmp_path, {"session_id": "s1"}, make_runner=fast_runner)

    assert not answer.block
    assert not (tmp_path / ".contexer").exists()


def test_the_hook_stands_aside_while_a_run_works_in_the_project(project: Path) -> None:
    _break(project)

    with run_lock(project, "20261126-000000-busy"):
        answer = answer_stop(project, {"session_id": "s1"}, make_runner=fast_runner)

    assert not answer.block  # the run has its own verdict; two replays at once would fight over the app
    assert _runs(project) == 0


def test_the_hook_never_changes_what_defines_done_or_the_code(project: Path) -> None:
    _break(project)
    before = _defines_done(project)

    for _ in range(MAX_BLOCKS + 2):
        answer_stop(project, {"session_id": "s1"}, make_runner=fast_runner)

    assert _defines_done(project) == before
    assert (project / "app.js").read_text(encoding="utf-8") == COUNT_BUG_JS
    assert (project / STATE_FILE).is_file()
    assert ".contexer" in Path(STATE_FILE).parts  # its own notes stay in the folder git ignores


def test_what_claude_code_is_told() -> None:
    from contexer.integrations.stop_hook import StopAnswer

    blocked = json.loads(claude_code_output(StopAnswer(block=True, message="fix [count]")))
    assert blocked == {"decision": "block", "reason": "fix [count]"}
    gave_up = json.loads(claude_code_output(StopAnswer(block=False, message="not proven")))
    assert gave_up == {"systemMessage": "not proven"}  # shown to the person; the stop goes ahead


# -- the command the hook runs -----------------------------------------------------------------------


def test_the_command_reads_the_agents_message_and_answers_in_its_format(project: Path) -> None:
    _break(project)
    payload = json.dumps({"session_id": "s1", "hook_event_name": "Stop", "cwd": str(project), "stop_hook_active": False})

    result = CliRunner().invoke(app, ["hook", "stop", "--dir", str(project)], input=payload)

    assert result.exit_code == 0, result.output  # the answer is in the JSON, not the exit code
    answer = json.loads(result.stdout)
    assert answer["decision"] == "block" and "expected" in answer["reason"]


def test_the_command_finds_the_project_from_the_agents_message(project: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    _break(project)

    result = CliRunner().invoke(app, ["hook", "stop"], input=json.dumps({"session_id": "s1", "cwd": str(project)}))

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["decision"] == "block"


def test_the_command_lets_a_stop_through_when_it_cannot_read_its_input(project: Path) -> None:
    result = CliRunner().invoke(app, ["hook", "stop", "--dir", str(project)], input="not json at all")

    # A hook that breaks must not trap the agent: it still replays, for the project it was given.
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == ""


def test_the_command_never_fails_the_agent_when_contexer_itself_breaks(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from contexer.integrations import stop_hook

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("playwright fell over")

    monkeypatch.setattr(stop_hook, "answer_stop", boom)

    result = CliRunner().invoke(app, ["hook", "stop", "--dir", str(project)], input="{}")

    assert result.exit_code == 0
    told = json.loads(result.stdout)
    assert "decision" not in told and "playwright fell over" in told["systemMessage"]


# -- contexer init --agent -----------------------------------------------------------------------------


def _stop_commands(settings: Path) -> list[str]:
    data = json.loads(settings.read_text(encoding="utf-8"))
    return [hook["command"] for group in data["hooks"]["Stop"] for hook in group["hooks"]]


def test_init_writes_the_stop_hook_for_claude_code(project: Path) -> None:
    result = CliRunner().invoke(app, ["init", "--dir", str(project), "--agent", "claude-code"])

    assert result.exit_code == 0, result.output
    settings = project / ".claude" / "settings.json"
    assert _stop_commands(settings) == ["contexer hook stop"]
    hook = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["Stop"][0]["hooks"][0]
    assert hook["type"] == "command" and hook["timeout"] >= 300  # a replay starts an app and a browser


def test_init_keeps_the_settings_and_hooks_a_person_already_has(project: Path) -> None:
    settings = project / ".claude" / "settings.json"
    settings.parent.mkdir()
    mine = {
        "permissions": {"allow": ["Bash(npm test)"]},
        "hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": "say done"}]}],
            "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "guard"}]}],
        },
    }
    settings.write_text(json.dumps(mine), encoding="utf-8")

    for _ in range(2):  # and running it twice adds it once
        result = CliRunner().invoke(app, ["init", "--dir", str(project), "--agent", "claude-code"])
        assert result.exit_code == 0, result.output

    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["permissions"] == mine["permissions"]
    assert data["hooks"]["PreToolUse"] == mine["hooks"]["PreToolUse"]
    assert _stop_commands(settings) == ["say done", "contexer hook stop"]


def test_init_does_not_overwrite_settings_it_cannot_read(project: Path) -> None:
    settings = project / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text("{ not json", encoding="utf-8")

    result = CliRunner().invoke(app, ["init", "--dir", str(project), "--agent", "claude-code"])

    assert result.exit_code == 0, result.output
    assert settings.read_text(encoding="utf-8") == "{ not json"
    assert "left unchanged" in " ".join(result.output.split())


def test_init_refuses_an_agent_it_does_not_know(project: Path) -> None:
    result = CliRunner().invoke(app, ["init", "--dir", str(project), "--agent", "emacs"])

    assert result.exit_code != 0
    assert "claude-code" in result.output


def test_init_writes_the_same_hook_for_codex_and_says_it_must_be_trusted(project: Path) -> None:
    result = CliRunner().invoke(app, ["init", "--dir", str(project), "--agent", "codex"])

    assert result.exit_code == 0, result.output
    assert _stop_commands(project / ".codex" / "hooks.json") == ["contexer hook stop"]
    assert "/hooks" in result.output  # Codex runs a project hook only once a person has trusted it


def test_init_says_plainly_that_opencode_cannot_be_held(project: Path) -> None:
    result = CliRunner().invoke(app, ["init", "--dir", str(project), "--agent", "opencode"])

    assert result.exit_code == 0, result.output
    assert "no hook" in " ".join(result.output.split())
    assert not (project / ".opencode").exists()


def test_a_verify_the_agent_just_passed_is_not_replayed_again_at_the_stop(project: Path) -> None:
    from contexer.integrations.mcp_server import _replay_locked

    approved = [c for c in ContractStore(project).list() if c.status == "approved"]
    result = _replay_locked(project, approved, fast_runner)  # what contexer_verify does
    assert result.decision.outcome == "pass"
    runs = _runs(project)

    answer = answer_stop(project, {"session_id": "s1"}, make_runner=fast_runner)

    assert not answer.block and _runs(project) == runs


def test_a_verify_of_one_contract_out_of_several_does_not_excuse_the_stop(project: Path) -> None:
    from contexer.integrations.mcp_server import _replay_locked

    store = ContractStore(project)
    first = store.load(CONTRACT_ID)
    store.save(first.model_copy(update={"id": "second"}).approved_by("tester"))
    runs_before = _runs(project)
    _replay_locked(project, [store.load(CONTRACT_ID)], fast_runner)

    answer_stop(project, {"session_id": "s1"}, make_runner=fast_runner)

    assert _runs(project) == runs_before + 2  # the hook replayed: only part of what defines done was proven
