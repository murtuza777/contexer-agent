"""Approving checks in `contexer run`: the one decision a person makes, so nothing approves by accident.

The checks are a numbered list. One key each: `y` approves, `n` does not, `e` opens the contract in the
editor, and a typed sentence is a correction. A stray key, an empty line, a closed stdin and a run with
no terminal never approve; `--yes` is the only approval without a person and is recorded as such.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from contexer.cli import app as cli
from contexer.cli import run_cli
from contexer.contract import ContractStore
from contexer.contract.store import AUTOMATIC_APPROVAL
from tests.fakes import AgentScript, submit
from tests.loop_helpers import CONTRACT_ID, GOAL, GOOD_JS, contract_checks, copy_todo


def _plain(text: str) -> str:
    return " ".join(re.sub(r"\x1b\[[0-9;]*m", "", text).split())


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return copy_todo(tmp_path)


@pytest.fixture(autouse=True)
def no_editor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONTEXER_ENGINE", raising=False)
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.setattr("contexer.cli.run_cli.compiler_llm", lambda *_a, **_k: None)


@pytest.fixture
def terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """A person is at the terminal: the test's input is what they type."""
    monkeypatch.setattr(run_cli, "is_interactive", lambda: True)


def _turns(tmp_path: Path) -> str:
    path = tmp_path / "turns.json"
    path.write_text(json.dumps([{"app.js": GOOD_JS}]), encoding="utf-8")
    return str(path)


def _goal_run(project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *args: str, input: str | None = None) -> Any:
    """A run from a goal: the Intent agent drafts the fixture's checks, and the run stops to ask."""
    (project / ".contexer" / "contracts" / f"{CONTRACT_ID}.json").unlink()
    model = AgentScript(intent=[submit(behaviours=["Tasks can be added"], checks=contract_checks())] * 3)
    monkeypatch.setattr(run_cli, "crew_model", lambda *_a, **_k: model)
    return CliRunner().invoke(
        cli, ["run", "--dir", str(project), "--agent", "scripted", GOAL, "--model", _turns(tmp_path), *args], input=input
    )


def _only(project: Path) -> Any:
    [stored] = ContractStore(project).list()
    return stored


def _latest(project: Path) -> dict[str, Any]:
    runs = [p for p in (project / ".contexer" / "runs").iterdir() if (p / "run.json").is_file()]
    return json.loads((max(runs, key=lambda p: p.stat().st_mtime_ns) / "run.json").read_text(encoding="utf-8"))


def _editor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> None:
    """Set EDITOR to a script that gets the contract's path as its last argument, like an editor does."""
    script = tmp_path / "editor.py"
    script.write_text("import json, sys\npath = sys.argv[-1]\n" + body, encoding="utf-8")
    monkeypatch.setenv("EDITOR", f'"{sys.executable}" "{script}"')


DROP_LAST = (
    "data = json.loads(open(path, encoding='utf-8').read())\n"
    "data['criteria'] = data['criteria'][:-1]\n"
    "open(path, 'w', encoding='utf-8').write(json.dumps(data))\n"
)


# -- what the prompt shows ---------------------------------------------------------------------------


def test_the_checks_are_a_numbered_list_and_every_key_is_shown(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, terminal: None
) -> None:
    result = _goal_run(project, tmp_path, monkeypatch, input="n\n")
    out = _plain(result.output)
    checks = contract_checks()
    for number, check in enumerate(checks, 1):
        assert f"{number} [{check['id']}]" in out, out
    assert "y approve" in out and "n do not approve" in out and "e edit" in out and "type what to change" in out


# -- what approves, and what does not ----------------------------------------------------------------


def test_y_at_a_terminal_approves_and_names_the_person(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, terminal: None
) -> None:
    result = _goal_run(project, tmp_path, monkeypatch, input="y\n")
    assert result.exit_code == 0, result.output
    stored = _only(project)
    assert stored.status == "approved" and stored.approval.by != AUTOMATIC_APPROVAL


def test_y_on_a_pipe_with_no_terminal_does_not_approve(project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = _goal_run(project, tmp_path, monkeypatch, input="y\n")
    out = _plain(result.output)
    assert result.exit_code == 2, result.output
    assert _only(project).status == "draft" and _latest(project)["attempts"] == []
    assert (project / "app.js").read_text(encoding="utf-8") == GOOD_JS
    # It says why, and the two ways on: read and approve, or --yes with what that records.
    assert "not a terminal" in out and "contexer contract approve" in out and "--yes" in out


@pytest.mark.parametrize("typed", ["\n", "x\nn\n", "1\nn\n", "yy\nn\n"])
def test_an_empty_line_or_a_stray_key_does_not_approve_and_is_not_a_correction(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, terminal: None, typed: str
) -> None:
    result = _goal_run(project, tmp_path, monkeypatch, input=typed)
    assert result.exit_code == 2, result.output
    assert _only(project).status == "draft"
    run = _latest(project)
    assert run["attempts"] == [] and run["corrections"] == []
    if typed != "\n":
        assert "is not one of the keys" in _plain(result.output)


def test_after_a_stray_key_the_question_is_asked_again(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, terminal: None
) -> None:
    result = _goal_run(project, tmp_path, monkeypatch, input="q\ny\n")
    assert result.exit_code == 0, result.output
    assert _only(project).status == "approved"


def test_a_closed_stdin_does_not_approve(project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, terminal: None) -> None:
    result = _goal_run(project, tmp_path, monkeypatch, input="")
    assert result.exit_code != 0, result.output
    assert _only(project).status == "draft"
    assert (project / "app.js").read_text(encoding="utf-8") == GOOD_JS


def test_yes_is_recorded_as_not_reviewed_by_a_person(project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = _goal_run(project, tmp_path, monkeypatch, "--yes")
    assert result.exit_code == 0, result.output
    assert _only(project).approval.by == AUTOMATIC_APPROVAL


# -- e: the contract in the editor -------------------------------------------------------------------


def test_e_opens_the_contract_in_the_editor_and_what_comes_back_is_shown_and_asked_about(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, terminal: None
) -> None:
    _editor(tmp_path, monkeypatch, DROP_LAST)
    result = _goal_run(project, tmp_path, monkeypatch, input="e\ny\n")
    out = _plain(result.output)
    assert result.exit_code == 0, result.output
    checks = contract_checks()
    stored = _only(project)
    assert stored.status == "approved" and [c.id for c in stored.criteria] == [c["id"] for c in checks[:-1]]
    # The list is shown again without the check that was removed, and the question is asked a second time.
    assert out.count(f"1 [{checks[0]['id']}]") == 2 and out.count(f"[{checks[-1]['id']}]") == 1
    assert out.count("Approve these checks") == 2


def test_an_edit_alone_approves_nothing(project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, terminal: None) -> None:
    _editor(tmp_path, monkeypatch, DROP_LAST)
    result = _goal_run(project, tmp_path, monkeypatch, input="e\nn\n")
    out = _plain(result.output)
    assert result.exit_code == 2, result.output
    stored = _only(project)
    # Nobody approved the edit, so the contract is as it was drafted, and the run says that and nothing else about it.
    assert stored.status == "draft" and len(stored.criteria) == len(contract_checks())
    assert "back as it was drafted" in out and "changed while the app ran" not in out


@pytest.mark.parametrize(
    ("body", "why"),
    [
        ("open(path, 'w', encoding='utf-8').write('not json at all')\n", "not a valid contract"),
        (
            "data = json.loads(open(path, encoding='utf-8').read())\ndata['id'] = 'another'\n"
            "open(path, 'w', encoding='utf-8').write(json.dumps(data))\n",
            "id",
        ),
        (
            "data = json.loads(open(path, encoding='utf-8').read())\ndata['criteria'] = []\n"
            "open(path, 'w', encoding='utf-8').write(json.dumps(data))\n",
            "no check",
        ),
    ],
)
def test_an_edit_that_is_not_a_contract_is_put_back_and_said(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, terminal: None, body: str, why: str
) -> None:
    _editor(tmp_path, monkeypatch, body)
    result = _goal_run(project, tmp_path, monkeypatch, input="e\nn\n")
    out = _plain(result.output)
    assert result.exit_code == 2, result.output
    assert why in out and "put back" in out
    stored = _only(project)
    assert stored.status == "draft" and len(stored.criteria) == len(contract_checks())


def test_e_without_an_editor_says_how_to_set_one_and_approves_nothing(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, terminal: None
) -> None:
    result = _goal_run(project, tmp_path, monkeypatch, input="e\nn\n")
    out = _plain(result.output)
    assert result.exit_code == 2, result.output
    assert "EDITOR" in out and _only(project).status == "draft"


def test_the_editor_is_started_as_a_program_with_arguments_never_through_a_shell(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, terminal: None
) -> None:
    started: list[Any] = []
    real_run = run_cli.subprocess.run

    def fake_run(argv: Any, *args: Any, **kwargs: Any) -> Any:
        if not isinstance(argv, list) or argv[0] != "my-editor":
            return real_run(argv, *args, **kwargs)  # git, and whatever else the run starts
        started.append((argv, kwargs))
        return None

    monkeypatch.setenv("VISUAL", "my-editor --wait")
    monkeypatch.setenv("EDITOR", "another-editor")
    monkeypatch.setattr(run_cli.subprocess, "run", fake_run)
    result = _goal_run(project, tmp_path, monkeypatch, input="e\nn\n")
    assert result.exit_code == 2, result.output
    [(argv, kwargs)] = started
    contract_file = ContractStore(project).path_for(_only(project).id)
    assert argv == ["my-editor", "--wait", str(contract_file)]  # VISUAL first, and the file as one argument
    assert not kwargs.get("shell")


# -- a contract that is approved before the run (no model for Contexer's own agents) -----------------


def _draft_run(project: Path, tmp_path: Path, *args: str, input: str | None = None) -> Any:
    store = ContractStore(project)
    store.save(store.load(CONTRACT_ID).model_copy(update={"approval": None}))
    monkeypatch_free = ["run", "--dir", str(project), "--agent", "scripted", "--contract", CONTRACT_ID]
    return CliRunner().invoke(cli, [*monkeypatch_free, "--model", _turns(tmp_path), *args], input=input)


@pytest.fixture
def no_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_cli, "crew_model", lambda *_a, **_k: None)


def test_a_draft_contract_is_not_approved_from_a_pipe(project: Path, tmp_path: Path, no_model: None) -> None:
    result = _draft_run(project, tmp_path, input="y\n")
    out = _plain(result.output)
    assert result.exit_code == 2, result.output
    assert ContractStore(project).load(CONTRACT_ID).status == "draft"
    assert "not a terminal" in out and f"contexer contract approve {CONTRACT_ID}" in out
    assert not (project / ".contexer" / "runs").exists() or not any((project / ".contexer" / "runs").iterdir())


def test_a_draft_contract_takes_the_same_keys(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_model: None, terminal: None
) -> None:
    _editor(tmp_path, monkeypatch, DROP_LAST)
    # A stray key, then a sentence (there is no model to redraft with, and it says so), then the editor, then yes.
    result = _draft_run(project, tmp_path, input="x\nMake the heading blue\ne\ny\n")
    out = _plain(result.output)
    assert result.exit_code == 0, result.output
    assert "is not one of the keys" in out and "no model" in out.lower()
    stored = ContractStore(project).load(CONTRACT_ID)
    assert stored.status == "approved" and len(stored.criteria) == len(contract_checks()) - 1
