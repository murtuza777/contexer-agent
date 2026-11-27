"""The errors of `contexer run` have one form: what happened and why, what to do next, and the exit code.

    x Cannot resume: no run '20260101-000000-abcd' ...
      Next: `contexer runs` lists the runs of this project and how each ended.
      Exit code 2.

No box around it, the same in a terminal and in a log, and with `--json` on stderr so stdout stays JSON.
"""

from __future__ import annotations

import io
import json
import os
import re
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console
from typer.testing import CliRunner

from contexer.cli import app as cli
from contexer.cli import run_cli, term
from tests.loop_helpers import CONTRACT_ID, GOOD_JS, copy_todo

BOX = set("│╭╮╰╯─┌┐└┘")


def _plain(text: str) -> str:
    return " ".join(re.sub(r"\x1b\[[0-9;]*m", "", text).split())


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("CONTEXER_ENGINE", raising=False)
    monkeypatch.setattr(run_cli, "compiler_llm", lambda *_a, **_k: None)
    monkeypatch.setattr(run_cli, "crew_model", lambda *_a, **_k: None)
    return copy_todo(tmp_path)


def _run(project: Path, tmp_path: Path, *args: str) -> Any:
    turns = tmp_path / "turns.json"
    turns.write_text(json.dumps([{"app.js": GOOD_JS}]), encoding="utf-8")
    return CliRunner().invoke(cli, ["run", "--dir", str(project), "--agent", "scripted", "--model", str(turns), *args])


def _assert_form(output: str, what: str, code: int) -> str:
    """The error is three parts in order, and nothing is drawn around it. Returns the output on one line."""
    assert not BOX & set(output), output
    out = _plain(output)
    assert re.search(rf"{re.escape(what)}: .+ Next: .+ Exit code {code}\.$", out), out
    return out


def test_the_form_is_what_and_why_then_the_next_step_then_the_exit_code() -> None:
    console = Console(file=io.StringIO(), width=200, force_terminal=False, color_system=None)
    term.error(console, "Cannot resume", "no run 'x' in this project.", "`contexer runs` lists the runs.", 2)
    lines = console.file.getvalue().splitlines()  # type: ignore[attr-defined]
    assert [line[2:] if index == 0 else line for index, line in enumerate(lines)] == [
        "Cannot resume: no run 'x' in this project.",
        "  Next: `contexer runs` lists the runs.",
        "  Exit code 2.",
    ]


@pytest.mark.parametrize(
    ("args", "what", "said"),
    [
        ([], "Not started", "give a GOAL, --contract ID, --issue N or --resume RUN"),
        (["--contract", CONTRACT_ID, "--correct", "Make it blue"], "Not started", "--correct goes with --resume RUN"),
        (["--contract", CONTRACT_ID, "--screenshots"], "Not started", "--screenshots goes with --pr or --issue N"),
        (["--contract", CONTRACT_ID, "--json"], "Not started", "--json cannot stop to ask for an approval"),
        (["--contract", CONTRACT_ID, "--engine", "classic"], "Not started", "was removed in 0.5.0"),
        (["--contract", "no-such-contract"], "Not started", "No contract 'no-such-contract'"),
        (["--resume", "20260101-000000-abcd"], "Cannot resume", "20260101-000000-abcd"),
    ],
)
def test_an_error_before_or_at_the_start_of_a_run_has_the_form_and_exits_2(
    project: Path, tmp_path: Path, args: list[str], what: str, said: str
) -> None:
    result = _run(project, tmp_path, *args)
    assert result.exit_code == 2, result.output
    assert said in _assert_form(result.output, what, 2)


def test_an_agent_that_does_not_exist_is_said_in_the_form(project: Path) -> None:
    result = CliRunner().invoke(cli, ["run", "--dir", str(project), "--agent", "no-such-agent", "--contract", CONTRACT_ID])
    assert result.exit_code == 2, result.output
    assert "no-such-agent" in _assert_form(result.output, "Not started", 2)


def test_a_project_another_run_is_working_in_is_said_in_the_form(project: Path, tmp_path: Path) -> None:
    from contexer.checkpoint import lock

    held = project / lock.LOCK_FILE
    held.parent.mkdir(parents=True, exist_ok=True)
    held.write_text(json.dumps({"pid": os.getpid(), "run": "20260101-000000-abcd"}), encoding="utf-8")
    result = _run(project, tmp_path, "--contract", CONTRACT_ID)
    assert result.exit_code == 2, result.output
    assert "20260101-000000-abcd is already working" in _assert_form(result.output, "Not started", 2)
    assert held.exists()  # the other run's lock is not taken away


def test_a_pull_request_that_cannot_be_opened_is_said_before_anything_runs_and_exits_3(project: Path, tmp_path: Path) -> None:
    result = _run(project, tmp_path, "--contract", CONTRACT_ID, "--pr")  # the fixture is not a git repository
    assert result.exit_code == 3, result.output
    _assert_form(result.output, "Cannot open a pull request", 3)
    assert not (project / ".contexer" / "runs").exists()


def test_with_json_an_error_goes_to_stderr_and_stdout_stays_json(project: Path, tmp_path: Path) -> None:
    result = _run(project, tmp_path, "--resume", "20260101-000000-abcd", "--json")
    assert result.exit_code == 2
    for line in result.stdout.splitlines():
        json.loads(line)
    assert "20260101-000000-abcd" in _assert_form(result.stderr, "Cannot resume", 2)
