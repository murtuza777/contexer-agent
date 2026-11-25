"""Small things that decide whether a first run goes well or ends in a traceback."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from contexer.appserver.devserver import DevServerError, port_in_use
from contexer.checkpoint.lock import RunLocked, run_lock
from contexer.cli import app
from contexer.contract import Contract, ContractStore
from contexer.contract.store import AUTOMATIC_APPROVAL
from contexer.controller import RunOutcome
from contexer.github.handoff import pull_request_body
from contexer.github.issues import IssueFlowError, draft_comment, find_draft
from tests.loop_helpers import GOOD_JS, copy_todo

BOT = {"login": "github-actions[bot]", "type": "Bot"}
FIXTURE = Path(__file__).resolve().parents[1] / "bench" / "fixtures" / "todo" / "app"


# -- one run at a time in a project ----------------------------------------------------------------


def test_a_second_run_in_the_same_project_is_refused_while_the_first_is_alive(tmp_path: Path) -> None:
    with run_lock(tmp_path, "run-a"):
        with pytest.raises(RunLocked, match="run-a"):
            with run_lock(tmp_path, "run-b"):
                pass
    with run_lock(tmp_path, "run-c"):  # released when the first ended
        pass


def test_a_lock_left_by_a_process_that_is_gone_does_not_block(tmp_path: Path) -> None:
    lock = tmp_path / ".contexer" / "run.lock"
    lock.parent.mkdir()
    lock.write_text(json.dumps({"pid": 2_000_000_000, "run": "dead-run"}), encoding="utf-8")  # no such process
    with run_lock(tmp_path, "run-b"):
        assert json.loads(lock.read_text(encoding="utf-8"))["pid"] == os.getpid()
    assert not lock.exists()


def test_the_command_says_which_run_is_working_here(tmp_path: Path) -> None:
    project = copy_todo(tmp_path)
    turns = tmp_path / "turns.json"
    turns.write_text(json.dumps([{"app.js": GOOD_JS + "// x\n"}]), encoding="utf-8")
    with run_lock(project, "20261119-000000-busy"):
        result = CliRunner().invoke(
            app, ["run", "--contract", "todo-basics", "--dir", str(project), "--agent", "scripted", "--model", str(turns), "--yes"]
        )
    assert result.exit_code == 2
    shown = " ".join(result.output.split())
    assert "20261119-000000-busy" in shown and "already" in shown
    assert "Traceback" not in result.output


# -- the port ------------------------------------------------------------------------------------------


def test_a_port_something_else_listens_on_is_seen_before_the_app_is_started() -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        assert port_in_use(port)
    assert not port_in_use(port)
    assert issubclass(DevServerError, Exception)


# -- contract ids are file names -------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["../../.github/workflows/x", "a/b", "..", "C:\\x", "", "x" * 200, ".hidden", "a b"])
def test_a_contract_id_that_is_not_a_plain_name_is_refused(bad: str) -> None:
    with pytest.raises(ValidationError):
        Contract(id=bad, goal="g")


def test_ids_that_exist_today_are_still_accepted() -> None:
    for good in ("todo-basics", "issue-7-remaining-count-ignores-done", "sign-page-pressing-sign-empty-email-2", "a", "v1.2_x"):
        assert Contract(id=good, goal="g").id == good


def test_a_draft_comment_edited_to_escape_the_contracts_folder_is_not_built() -> None:
    contract = ContractStore(FIXTURE).load("todo-basics").model_copy(update={"approval": None})
    body = draft_comment(contract, None).replace('"id": "todo-basics"', '"id": "../../.github/workflows/pwn"')
    with pytest.raises(IssueFlowError, match="not valid"):
        find_draft([{"id": 1, "body": body, "user": BOT}])


# -- an approval nobody gave -------------------------------------------------------------------------


def test_checks_approved_by_yes_are_not_presented_as_read_by_a_person(tmp_path: Path) -> None:
    project = copy_todo(tmp_path)
    store = ContractStore(project)
    contract = store.load("todo-basics").model_copy(update={"approval": None})
    store.save(contract)
    approved = store.approve("todo-basics", by=AUTOMATIC_APPROVAL)
    assert approved.status == "approved" and approved.approval is not None and "--yes" in approved.approval.by

    outcome = RunOutcome(run_id="r", contract_id=approved.id, agent="scripted", terminal="failed_checks", reason="x")
    body = pull_request_body(outcome, approved)
    assert "approved automatically" in body and "nobody read" in body.lower()
    by_a_person = store.approve("todo-basics", by="alice")
    assert "approved automatically" not in pull_request_body(outcome, by_a_person)


# -- REL-7: one lock, taken whole ----------------------------------------------------------------


def test_two_starts_at_once_take_one_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Both starts look before either has written: only one may go on."""
    import threading
    import time

    from contexer.checkpoint import lock

    both_looked = threading.Barrier(2, timeout=5)
    real = lock._holder

    def look_together(path: Path) -> object:
        found = real(path)
        try:
            both_looked.wait()
        except threading.BrokenBarrierError:
            pass
        return found

    release = threading.Event()
    took: list[str] = []
    refused: list[str] = []

    def start(name: str) -> None:
        try:
            with run_lock(tmp_path, name):
                took.append(name)
                release.wait(10)
        except RunLocked:
            refused.append(name)

    monkeypatch.setattr(lock, "_holder", look_together)
    threads = [threading.Thread(target=start, args=(f"run-{i}",)) for i in range(2)]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + 12
    while len(took) + len(refused) < 2 and time.monotonic() < deadline:
        time.sleep(0.05)
    release.set()
    for thread in threads:
        thread.join(10)
    assert len(took) == 1 and len(refused) == 1


def test_a_lock_left_by_a_dead_process_is_taken_over(tmp_path: Path) -> None:
    path = tmp_path / ".contexer" / "run.lock"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"pid": 2**22 + 12345, "run": "gone"}), encoding="utf-8")
    with run_lock(tmp_path, "run-new"):
        assert json.loads(path.read_text(encoding="utf-8"))["run"] == "run-new"
    assert not path.exists()
