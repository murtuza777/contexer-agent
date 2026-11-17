"""``contexer test``: one command that explores an app and reports only what replays.

The scripted model stands in for a real one; the app, the browser and the replay are real.
"""

from __future__ import annotations

import json
import re
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest
from typer.testing import CliRunner

from contexer.cli import app as cli
from contexer.contract import ContractStore
from contexer.demo import create_demo_project, fixed_app_js
from contexer.llm.chat import ToolCallingError
from tests.fakes import ScriptedChatModel, calls, submit

INTENT = "Users can add and complete tasks, and the remaining count stays correct"
INPUT = {"placeholder": "What needs doing?"}
ADD = {"role": "button", "name": "Add"}

# The demo app's seeded bug: completing a task throws, so the count never changes.
EXPLORE = calls(
    ("fill", {"target": INPUT, "value": "Buy milk"}),
    ("click", {"target": ADD}),
    ("expect", {"kind": "visible", "target": {"text": "Buy milk"}}),
    ("check", {"target": {"role": "checkbox", "name": "Complete Buy milk"}}),
    ("expect", {"kind": "text", "target": {"test_id": "remaining-count"}, "equals": "0 left"}),
)
REPORT_BOTH = calls(
    ("record_finding", {"kind": "works", "title": "Adding a task shows it in the list", "observation": "e1"}),
    ("record_finding", {"kind": "bug", "title": "Completing a task does not lower the count", "observation": "e2",
                        "severity": "high", "description": "The count stays at 1 left."}),
)  # fmt: skip
# On the fixed app the second expectation passes, so the honest report is two working behaviours.
REPORT_WORKING = calls(
    ("record_finding", {"kind": "works", "title": "Adding a task shows it in the list", "observation": "e1"}),
    ("record_finding", {"kind": "works", "title": "Completing a task lowers the count", "observation": "e2"}),
)


def _plain(text: str) -> str:
    return " ".join(re.sub(r"\x1b\[[0-9;]*m", "", text).split())


@pytest.fixture
def demo(tmp_path: Path) -> Path:
    return create_demo_project(tmp_path / "demo")


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch) -> Any:
    """``scripted(*replies)`` makes the command use a scripted model; returns it for inspection."""

    def install(*replies: Any) -> ScriptedChatModel:
        model = ScriptedChatModel(*replies)
        monkeypatch.setattr("contexer.cli.test_cli.build_model", lambda *_a, **_k: model)
        return model

    return install


def _run(*args: str) -> Any:
    return CliRunner().invoke(cli, ["test", *args])


def _run_folder(project: Path) -> Path:
    [folder] = (project / ".contexer" / "runs").iterdir()
    return folder


def test_the_seeded_bug_is_reported_as_confirmed_with_exit_code_1(demo: Path, scripted: Any) -> None:
    scripted(EXPLORE, REPORT_BOTH, submit(summary="Completing is broken.", questions=["Should tasks survive a reload?"]))

    result = _run(INTENT, "--dir", str(demo))

    out = _plain(result.output)
    assert result.exit_code == 1, result.output
    assert "1 confirmed bug" in out
    assert "Completing a task does not lower the count" in out
    assert "1 working behaviour confirmed" in out and "Adding a task shows it in the list" in out
    assert "0 unconfirmed" in out
    assert "3 steps" in out
    # What the intent does not settle is shown as a question, apart from the bugs.
    assert "Not settled by the intent" in out and "Should tasks survive a reload?" in out

    folder = _run_folder(demo)
    data = json.loads((folder / "result.json").read_text(encoding="utf-8"))
    assert data["questions"] == ["Should tasks survive a reload?"]
    assert data["outcome"] == "bugs" and data["intent"] == INTENT
    assert [b["title"] for b in data["bugs"]] == ["Completing a task does not lower the count"]
    assert data["bugs"][0]["severity"] == "high" and data["bugs"][0]["evidence"]
    assert [w["title"] for w in data["works"]] == ["Adding a task shows it in the list"]
    assert (data["unconfirmed"], data["steps"], data["tester_status"]) == (0, 3, "ok")
    html = (folder / "report.html").read_text(encoding="utf-8")
    assert "Completing a task does not lower the count" in html and "confirmed by replay" in html
    assert (folder / "agents" / "tester.jsonl").is_file()
    # The confirmed checks are a draft contract in the run folder, not yet among the project's contracts.
    draft = json.loads((folder / "draft-contract.json").read_text(encoding="utf-8"))
    assert len(draft["criteria"]) == 2 and draft.get("approval") is None
    assert [c.id for c in ContractStore(demo).list()] == ["todo-basics"]


def test_the_clean_app_reports_no_confirmed_bugs_with_exit_code_0(demo: Path, scripted: Any) -> None:
    (demo / "app.js").write_text(fixed_app_js(), encoding="utf-8")
    scripted(EXPLORE, REPORT_WORKING, submit(summary="Both behaviours work."))

    result = _run(INTENT, "--dir", str(demo))

    out = _plain(result.output)
    assert result.exit_code == 0, result.output
    assert "No confirmed bugs" in out and "2 working behaviours confirmed" in out
    assert json.loads((_run_folder(demo) / "result.json").read_text(encoding="utf-8"))["outcome"] == "no_bugs"


def test_a_finding_the_replay_does_not_reproduce_is_counted_and_never_shown(
    demo: Path, scripted: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The agent says "bug"; the replay disagrees; the replay wins."""
    from contexer.browser.freeze import ReplayReport, Unconfirmed

    async def nothing_reproduces(findings: list[Any], *_a: Any, **_k: Any) -> ReplayReport:
        return ReplayReport(unconfirmed=[Unconfirmed(finding=f, reason="its check passed on replay") for f in findings])

    monkeypatch.setattr("contexer.cli.test_cli.replay_findings", nothing_reproduces)
    scripted(EXPLORE, REPORT_BOTH, submit(summary="Completing is broken."))

    result = _run(INTENT, "--dir", str(demo))

    out = _plain(result.output)
    assert result.exit_code == 0, result.output
    assert "No confirmed bugs" in out and "2 unconfirmed" in out
    assert "Completing a task does not lower the count" not in out
    folder = _run_folder(demo)
    dropped = json.loads((folder / "unconfirmed.json").read_text(encoding="utf-8"))
    assert [d["reason"] for d in dropped] == ["its check passed on replay"] * 2
    assert not (folder / "draft-contract.json").exists()


def test_json_output_is_the_result_and_save_puts_the_draft_among_the_contracts(demo: Path, scripted: Any) -> None:
    scripted(EXPLORE, REPORT_BOTH, submit(summary="Completing is broken."))

    result = _run(INTENT, "--dir", str(demo), "--json", "--save")

    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert data["outcome"] == "bugs" and data["run_dir"].endswith(_run_folder(demo).name)
    drafts = [c for c in ContractStore(demo).list() if c.status == "draft"]
    assert len(drafts) == 1 and len(drafts[0].criteria) == 2
    assert data["contract"] == drafts[0].id


def test_steps_caps_the_tester_and_the_findings_so_far_are_still_replayed(demo: Path, scripted: Any) -> None:
    model = scripted(EXPLORE, REPORT_BOTH, *[calls(("snapshot", {})) for _ in range(5)])

    result = _run(INTENT, "--dir", str(demo), "--steps", "3")

    out = _plain(result.output)
    assert result.exit_code == 1
    assert "1 confirmed bug" in out and "stopped at the step limit" in out
    assert len(model.seen) == 3


def test_without_a_model_the_command_explains_what_to_set_and_exits_2(demo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "CONTEXER_LLM_PROVIDER"):
        monkeypatch.delenv(name, raising=False)

    result = _run(INTENT, "--dir", str(demo))

    assert result.exit_code == 2
    assert "contexer setup" in _plain(result.output)
    assert not (demo / ".contexer" / "runs").exists()  # nothing was started


def test_a_model_that_cannot_call_tools_is_named_and_exits_2(demo: Path, scripted: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    scripted(RuntimeError("Error code: 404 - No endpoints found that support tool use."))

    result = _run(INTENT, "--dir", str(demo))

    out = _plain(result.output)
    assert result.exit_code == 2, result.output
    assert "cannot call tools" in out and "scripted-model" in out
    assert json.loads((_run_folder(demo) / "result.json").read_text(encoding="utf-8"))["outcome"] == "could_not_test"

    def refuse(*_a: Any, **_k: Any) -> Any:
        raise ToolCallingError("The openrouter model 'x/y' cannot call tools, which Contexer's agents need.")

    monkeypatch.setattr("contexer.cli.test_cli.build_model", refuse)
    refused = _run(INTENT, "--dir", str(demo))
    assert refused.exit_code == 2 and "x/y" in _plain(refused.output)


def test_an_app_that_does_not_start_is_an_error_with_exit_code_3(tmp_path: Path, scripted: Any) -> None:
    project = tmp_path / "broken"
    project.mkdir()
    (project / "package.json").write_text('{"name": "broken", "scripts": {}}', encoding="utf-8")
    model = scripted(submit(summary="never asked"))

    result = _run(INTENT, "--dir", str(project))

    assert result.exit_code == 3, result.output
    assert model.seen == []  # no model call was spent on an app that is not running


def test_ctrl_c_stops_the_browser_and_the_app_and_exits_130(
    demo: Path, scripted: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contexer.browser.tools import BrowserSession

    seen_url: list[str] = []
    closed: list[bool] = []
    close = BrowserSession.close

    async def spy(self: BrowserSession) -> None:
        await close(self)
        closed.append(self.closed)

    def interrupt(messages: list[Any]) -> Any:
        raise KeyboardInterrupt

    # The command quiets asyncio on this path; keep that from leaking into the rest of the test session.
    import logging
    import sys

    monkeypatch.setattr(sys, "unraisablehook", sys.unraisablehook)
    monkeypatch.setattr(logging.getLogger("asyncio"), "level", logging.getLogger("asyncio").level)
    monkeypatch.setattr(BrowserSession, "close", spy)
    monkeypatch.setattr("contexer.cli.test_cli.on_app_started", lambda running: seen_url.append(running.url))
    scripted(EXPLORE, interrupt)

    result = _run(INTENT, "--dir", str(demo))

    assert result.exit_code == 130, result.output
    assert "Stopped" in _plain(result.output)
    assert closed == [True]  # the browser was closed
    # The app's server is gone: nothing listens on its port any more.
    port = urlparse(seen_url[0]).port
    with socket.socket() as probe:
        probe.settimeout(1)
        assert probe.connect_ex(("127.0.0.1", port)) != 0


def test_the_url_option_tests_an_app_that_is_already_running(demo: Path, scripted: Any) -> None:
    from contexer.appserver import open_app

    (demo / "app.js").write_text(fixed_app_js(), encoding="utf-8")
    scripted(EXPLORE, REPORT_WORKING, submit(summary="Works."))
    with open_app(demo) as running:
        result = _run(INTENT, "--dir", str(demo), "--url", running.url)

    assert result.exit_code == 0, result.output
    assert "2 working behaviours confirmed" in _plain(result.output)


def test_the_command_is_listed_in_the_help() -> None:
    result = CliRunner().invoke(cli, ["--help"])
    assert re.search(r"\btest\b", _plain(result.output))
    usage = _plain(_run("--help").output)
    for option in ("--url", "--steps", "--model", "--dir"):
        assert option in usage
