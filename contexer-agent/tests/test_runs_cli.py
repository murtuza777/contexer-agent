"""`contexer runs` lists verifications and agent runs from their evidence files."""

import json
import re
from pathlib import Path

from typer.testing import CliRunner

from contexer.cli import app


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_lists_newest_first_with_outcomes(tmp_path: Path) -> None:
    runs = tmp_path / ".contexer" / "runs"
    _write(
        runs / "20261015-100000-aaaa" / "result.json",
        {"decision": {"outcome": "fail", "verified": 6, "refuted": 1, "unverified": 0},
         "contracts": [{"contract": {"id": "todo-basics"}}]},
    )
    _write(
        runs / "20261015-110000-bbbb" / "run.json",
        {"terminal": "succeeded", "agent": "claude-code", "contract_id": "todo-basics",
         "attempts": [{}, {}], "cost_usd": 0.42},
    )
    (runs / "20261015-110000-bbbb" / "report.html").write_text("<html>", encoding="utf-8")
    (runs / "not-a-run").mkdir()

    result = CliRunner().invoke(app, ["runs", "--dir", str(tmp_path)], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    out = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    lines = [line for line in out.splitlines() if line.startswith("2026")]
    assert lines[0].startswith("20261015-110000-bbbb") and "succeeded" in lines[0] and "$0.42" in lines[0]
    assert lines[1].startswith("20261015-100000-aaaa") and "fail" in lines[1] and "6✓ 1✗ 0?" in lines[1]
    assert len(lines) == 2


def test_no_runs_says_how_to_start(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["runs", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "No runs yet" in result.output


def test_stats_say_how_runs_ended_and_what_a_proven_run_cost(tmp_path: Path) -> None:
    from contexer.cli.runs_cli import run_stats

    runs = tmp_path / ".contexer" / "runs"
    note = {"severity": "high", "category": "logic", "backed": False}
    _write(runs / "20261101-100000-aaaa" / "run.json", {"terminal": "succeeded", "attempts": [{}], "cost_usd": 1.0, "crew_cost_usd": 0.1,
                                                        "duration_seconds": 100, "review": [], "engine": "graph"})
    _write(runs / "20261101-110000-bbbb" / "run.json", {"terminal": "succeeded", "attempts": [{}, {}, {}], "cost_usd": 3.0, "crew_cost_usd": None,
                                                        "duration_seconds": 300, "review": [note, {**note, "severity": "low"}], "engine": "graph"})
    _write(runs / "20261101-120000-cccc" / "run.json", {"terminal": "failed_checks", "attempts": [{}, {}, {}], "cost_usd": 6.0,
                                                        "duration_seconds": 400, "engine": "graph"})
    _write(runs / "20261101-130000-dddd" / "run.json", {"terminal": "needs_human", "attempts": [], "cost_usd": 0.0, "duration_seconds": 5})
    _write(runs / "20261101-140000-eeee" / "result.json", {"decision": {"outcome": "pass"}})  # a verification, not an agent run
    (runs / "20261101-150000-ffff").mkdir()
    (runs / "20261101-150000-ffff" / "run.json").write_text("{not json", encoding="utf-8")

    stats = run_stats(tmp_path)
    assert (stats.runs, stats.succeeded) == (4, 2)
    assert stats.endings == {"succeeded": 2, "failed_checks": 1, "needs_human": 1}
    assert stats.first_try == 1 and stats.attempts_per_success == 2.0
    assert stats.cost_usd == 10.1 and stats.cost_per_success == 5.05  # everything spent, over what was proven
    assert stats.spent_without_proof == 6.0
    assert stats.runs_with_high_note == 1 and stats.median_seconds == 200

    result = CliRunner().invoke(app, ["runs", "--stats", "--dir", str(tmp_path)], env={"COLUMNS": "200"})
    out = " ".join(re.sub(r"\x1b\[[0-9;]*m", "", result.output).split())
    assert result.exit_code == 0, result.output
    assert "2 of 4 runs ended with every check proven" in out and "$5.05 per proven run" in out
    assert "failed_checks 1" in out and "$6.00 spent on runs that proved nothing" in out


def test_stats_with_no_runs_say_so(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["runs", "--stats", "--dir", str(tmp_path)])
    assert result.exit_code == 0 and "No agent runs" in result.output


# -- by model, and as JSON (OBS-3) -------------------------------------------------------------------


def _model_call(agent: str, model: str, cost: float | None, tokens: tuple[int, int] = (1000, 100), estimated: bool = False) -> dict:
    return {
        "event": "model", "time": "2026-11-26T10:00:00.000Z", "gen_ai.operation.name": "chat", "gen_ai.agent.name": agent,
        "gen_ai.provider.name": "azure", "gen_ai.request.model": model, "gen_ai.usage.input_tokens": tokens[0],
        "gen_ai.usage.output_tokens": tokens[1], "contexer.cost_usd": cost, "contexer.cost_estimated": estimated,
    }  # fmt: skip


def _tool_call(agent: str, status: str) -> dict:
    return {"event": "tool", "gen_ai.operation.name": "execute_tool", "gen_ai.agent.name": agent, "gen_ai.tool.name": "read_file",
            "contexer.tool.status": status}  # fmt: skip


def _trace(folder: Path, lines: list[dict]) -> None:
    head = {"event": "trace", "format": 1, "semconv": "1.40.0"}
    (folder / "trace.jsonl").write_text("\n".join(json.dumps(line) for line in [head, *lines]) + "\n", encoding="utf-8")


def _runs_with_traces(tmp_path: Path) -> None:
    runs = tmp_path / ".contexer" / "runs"
    # Proven at the first attempt, on gpt-a alone: one call in four tool calls failed, one was repaired.
    _write(runs / "20261126-100000-aaaa" / "run.json", {"terminal": "succeeded", "attempts": [{}], "cost_usd": 1.0, "crew_cost_usd": 0.3})
    _trace(runs / "20261126-100000-aaaa", [
        {"event": "attempt-start", "at": 1.0, "n": 1},
        _model_call("planner", "gpt-a", 0.1), _tool_call("planner", "ok"), _tool_call("planner", "failed"),
        _model_call("diagnoser", "gpt-a", 0.2, estimated=True), _tool_call("diagnoser", "repaired"), _tool_call("diagnoser", "ok"),
    ])  # fmt: skip
    # Not proven after two attempts; the Planner on gpt-a, the Diagnoser on gpt-b, which has no known price.
    _write(runs / "20261126-110000-bbbb" / "run.json", {"terminal": "failed_checks", "attempts": [{}, {}], "cost_usd": 2.0, "crew_cost_usd": 0.1,
                                                        "agents": [{"agent": "planner"}, {"agent": "diagnoser"}]})  # fmt: skip
    _trace(runs / "20261126-110000-bbbb", [
        _model_call("planner", "gpt-a", 0.1),
        _model_call("diagnoser", "gpt-b", None), _tool_call("diagnoser", "ok"), _tool_call("diagnoser", "ok"),
    ])  # fmt: skip
    # A run from before there was a trace, and one whose trace cannot be read.
    _write(runs / "20261101-100000-cccc" / "run.json", {"terminal": "succeeded", "attempts": [{}, {}, {}], "cost_usd": 3.0})
    _write(runs / "20261126-120000-dddd" / "run.json", {"terminal": "needs_human", "attempts": [], "cost_usd": 0.0})
    (runs / "20261126-120000-dddd" / "trace.jsonl").write_text("{not json\n", encoding="utf-8")


def test_stats_by_model_are_counted_from_each_runs_trace(tmp_path: Path) -> None:
    from contexer.cli.runs_cli import run_stats

    _runs_with_traces(tmp_path)
    stats = run_stats(tmp_path)
    assert stats.runs == 4 and stats.runs_without_model_calls == 2
    a, b = stats.by_model  # the model with the most runs first
    assert (a.provider, a.model, a.runs, a.succeeded, a.proven_rate) == ("azure", "gpt-a", 2, 1, 0.5)
    assert a.attempts_per_success == 1.0  # of the runs it proved
    assert (a.calls, a.tokens_in, a.tokens_out) == (3, 3000, 300)
    assert a.cost_usd == 0.4 and a.cost_estimated and a.calls_without_cost == 0
    assert a.cost_per_success == 0.4  # what this model cost in every run, over the runs that were proven
    assert (a.tool_calls, a.tool_failed, a.tool_repaired) == (4, 1, 1)
    assert a.tool_error_rate == 0.25 and a.tool_repair_rate == 0.25
    assert (b.model, b.runs, b.succeeded, b.proven_rate, b.attempts_per_success) == ("gpt-b", 1, 0, 0.0, None)
    assert b.cost_usd is None and b.calls_without_cost == 1 and b.cost_per_success is None  # not known is not 0
    assert (b.tool_calls, b.tool_error_rate, b.tool_repair_rate) == (2, 0.0, 0.0)


def test_stats_by_model_print_a_row_per_model_and_never_a_cost_that_is_not_known(tmp_path: Path) -> None:
    _runs_with_traces(tmp_path)
    result = CliRunner().invoke(app, ["runs", "--stats", "--by", "model", "--dir", str(tmp_path)], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    lines = [" ".join(line.split()) for line in re.sub(r"\x1b\[[0-9;]*m", "", result.output).splitlines()]
    out = " ".join(lines)
    assert "2 of 4 runs ended with every check proven" in out  # the overall block is still there
    gpt_a = next(line for line in lines if line.startswith("azure gpt-a"))
    assert "1 of 2" in gpt_a and "$0.40" in gpt_a and "25%" in gpt_a
    gpt_b = next(line for line in lines if line.startswith("azure gpt-b"))
    assert "0 of 1" in gpt_b and "not known" in gpt_b and "$0.00" not in gpt_b
    assert "2 runs have no model call in a trace" in out

    plain = CliRunner().invoke(app, ["runs", "--stats", "--dir", str(tmp_path)], env={"COLUMNS": "200"})
    assert "gpt-a" not in plain.output  # only when asked for

    wrong = CliRunner().invoke(app, ["runs", "--stats", "--by", "agent", "--dir", str(tmp_path)])
    assert wrong.exit_code == 2 and "model" in wrong.output


def test_stats_as_json_are_one_object_with_the_models(tmp_path: Path) -> None:
    _runs_with_traces(tmp_path)
    result = CliRunner().invoke(app, ["runs", "--stats", "--json", "--dir", str(tmp_path)], env={"COLUMNS": "40"})
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)  # nothing but JSON, and not wrapped to the terminal's width
    assert data["runs"] == 4 and data["succeeded"] == 2 and data["endings"]["succeeded"] == 2
    assert [row["model"] for row in data["by_model"]] == ["gpt-a", "gpt-b"]
    assert data["by_model"][1]["cost_usd"] is None and data["by_model"][0]["tool_repair_rate"] == 0.25

    empty = CliRunner().invoke(app, ["runs", "--stats", "--json", "--dir", str(tmp_path / "nothing")])
    assert json.loads(empty.output)["runs"] == 0


def test_the_list_as_json(tmp_path: Path) -> None:
    _runs_with_traces(tmp_path)
    result = CliRunner().invoke(app, ["runs", "--json", "--limit", "2", "--dir", str(tmp_path)], env={"COLUMNS": "40"})
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert [row["run_id"] for row in rows] == ["20261126-120000-dddd", "20261126-110000-bbbb"]
    assert rows[1]["outcome"] == "failed_checks" and rows[1]["attempts"] == 2 and rows[1]["cost_usd"] == 2.0
    assert json.loads(CliRunner().invoke(app, ["runs", "--json", "--dir", str(tmp_path / "nothing")]).output) == []


def test_a_run_whose_cost_is_not_known_is_not_counted_as_free(tmp_path: Path) -> None:
    from contexer.cli.runs_cli import run_stats

    runs = tmp_path / ".contexer" / "runs"
    _write(runs / "20261126-100000-aaaa" / "run.json", {"terminal": "succeeded", "agent": "opencode", "attempts": [{}], "cost_usd": None})
    _write(runs / "20261126-110000-bbbb" / "run.json", {"terminal": "succeeded", "attempts": [{}], "cost_usd": 2.0, "crew_cost_usd": None,
                                                        "agents": [{"agent": "planner", "cost_usd": None}]})  # fmt: skip
    _write(runs / "20261126-120000-cccc" / "run.json", {"terminal": "succeeded", "attempts": [{}], "cost_usd": 1.0, "crew_cost_usd": 0.5})

    stats = run_stats(tmp_path)
    assert stats.cost_usd == 3.5 and stats.runs_with_unknown_cost == 2
    assert stats.cost_per_success is None  # two of the three proven runs cost an amount nobody knows

    out = " ".join(re.sub(r"\x1b\[[0-9;]*m", "", CliRunner().invoke(app, ["runs", "--stats", "--dir", str(tmp_path)], env={"COLUMNS": "200"}).output).split())
    assert "$3.50 known" in out and "2 runs with a cost that is not known" in out and "per proven run" not in out

    listed = re.sub(r"\x1b\[[0-9;]*m", "", CliRunner().invoke(app, ["runs", "--dir", str(tmp_path)], env={"COLUMNS": "200"}).output)
    unknown = next(line for line in listed.splitlines() if line.startswith("20261126-100000-aaaa"))
    assert "cost not known" in unknown and "$0.00" not in unknown


def test_a_run_with_one_agent_of_unknown_cost_is_counted_as_not_fully_known(tmp_path: Path) -> None:
    from contexer.cli.runs_cli import run_stats

    agents = [{"agent": "planner", "cost_usd": 0.2}, {"agent": "diagnoser", "cost_usd": None}]
    run = {"terminal": "succeeded", "attempts": [{}], "cost_usd": 1.0, "crew_cost_usd": 0.2, "agents": agents}
    _write(tmp_path / ".contexer" / "runs" / "20261126-100000-aaaa" / "run.json", run)
    stats = run_stats(tmp_path)
    assert stats.cost_usd == 1.2 and stats.runs_with_unknown_cost == 1 and stats.cost_per_success is None
