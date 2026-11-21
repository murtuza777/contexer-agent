"""A run as a stream of events with data, for the live view, for `--json`, and for anything else that watches a run."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from contexer.cli import app
from contexer.controller import RunSettings
from contexer.graph import GraphController
from contexer.graph.context import RunEvent
from tests.loop_helpers import COUNT_BUG_JS, GOOD_JS, RecordingAgent, contract, copy_todo, fast_runner

pytestmark = pytest.mark.anyio


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return copy_todo(tmp_path)


async def test_a_run_tells_a_watcher_what_it_needs_to_draw_it(project: Path) -> None:
    seen: list[RunEvent] = []
    words: list[tuple[str, str]] = []
    agent = RecordingAgent([{"app.js": COUNT_BUG_JS + "// a\n"}, {"app.js": GOOD_JS + "// b\n"}])
    outcome = await GraphController(
        project, agent, RunSettings(max_repair_rounds=2), runner=fast_runner(), on_detail=seen.append,
        on_event=lambda kind, message: words.append((kind, message)),
    ).run(contract(project))  # fmt: skip
    assert outcome.terminal == "succeeded"

    kinds = [e.kind for e in seen]
    for expected in ("checks", "attempt-start", "agent-done", "verdict", "strategy", "end"):
        assert expected in kinds, kinds
    assert kinds.index("checks") < kinds.index("attempt-start") < kinds.index("verdict") and kinds[-1] == "end"

    checks = next(e for e in seen if e.kind == "checks").data
    assert len(checks["checks"]) == 7 and {"id", "description"} <= set(checks["checks"][0])

    first, second = [e.data for e in seen if e.kind == "verdict"]
    assert (first["n"], first["outcome"], second["n"], second["outcome"]) == (1, "fail", 2, "pass")
    assert first["verified"] + first["refuted"] + first["unverified"] == 7 and second["verified"] == 7
    by_id = {c["id"]: c for c in first["checks"]}
    assert set(by_id) == {c["id"] for c in checks["checks"]}
    failed = [c for c in first["checks"] if c["verdict"] == "refuted"]
    assert failed and failed[0]["evidence"]  # what the browser saw, for the line under the check

    done = next(e for e in seen if e.kind == "agent-done").data
    assert done["n"] == 1 and done["files"] == 1 and "seconds" in done and "cost_usd" in done
    starts = [e.data for e in seen if e.kind == "attempt-start"]
    assert [(s["n"], s["doing"]) for s in starts] == [(1, "implementing"), (2, "repairing")]
    assert next(e for e in seen if e.kind == "strategy").data["move"] == "repair_same_session"

    end = seen[-1].data
    assert end["terminal"] == "succeeded" and end["attempts"] == 2 and end["run_id"] == outcome.run_id

    # Every event is plain data, and the old words-only stream is unchanged for those who read it.
    for event in seen:
        json.dumps(event.as_json())
        assert event.at >= 0
    assert ("verdict", next(m for k, m in words if k == "verdict")) in words
    assert not any(kind in ("checks", "attempt-start", "end") for kind, _ in words)


def test_json_output_is_one_event_per_line_and_nothing_else(project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("contexer.cli.run_cli.crew_model", lambda *_a, **_k: None)
    turns = tmp_path / "turns.json"
    turns.write_text(json.dumps([{"app.js": GOOD_JS + "// x\n"}]), encoding="utf-8")
    result = CliRunner().invoke(
        app,
        ["run", "--contract", "todo-basics", "--dir", str(project), "--agent", "scripted", "--model", str(turns), "--yes", "--json"],
    )
    assert result.exit_code == 0, result.output
    assert not re.search(r"\x1b\[", result.output)  # no colour codes
    events: list[dict[str, Any]] = [json.loads(line) for line in result.output.splitlines() if line.strip()]  # every line parses
    assert events[0]["event"] == "run-start" and events[0]["agent"] == "scripted" and events[0]["engine"] == "graph"
    assert events[-1]["event"] == "end" and events[-1]["terminal"] == "succeeded" and events[-1]["exit_code"] == 0
    assert events[-1]["report"].endswith("report.html")
    assert [e["event"] for e in events].count("verdict") == 1
    assert all("at" in e for e in events)


def test_json_output_of_a_run_that_does_not_pass_ends_with_the_reason_and_the_exit_code(project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("contexer.cli.run_cli.crew_model", lambda *_a, **_k: None)
    turns = tmp_path / "turns.json"
    turns.write_text(json.dumps([{"app.js": COUNT_BUG_JS + "// x\n"}]), encoding="utf-8")
    result = CliRunner().invoke(
        app,
        ["run", "--contract", "todo-basics", "--dir", str(project), "--agent", "scripted", "--model", str(turns), "--yes", "--json", "--rounds", "0"],
    )
    assert result.exit_code == 1
    end = json.loads(result.output.strip().splitlines()[-1])
    assert end["event"] == "end" and end["terminal"] == "failed_checks" and end["exit_code"] == 1 and end["reason"]
