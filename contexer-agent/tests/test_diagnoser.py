"""The Diagnoser: a fix prompt that names the cause, with the facts inserted by code, word for word."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Optional

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from contexer.appserver import open_app
from contexer.browser.freeze import replay_findings
from contexer.crew.diagnoser import Failure, RepairBrief, diagnose, fix_prompt, project_tools
from contexer.crew.tester import Finding
from tests.fakes import ScriptedChatModel, calls, submit

pytestmark = pytest.mark.anyio

FIXTURES = Path(__file__).resolve().parents[1] / "bench" / "fixtures"
INTENT = "Users can add, complete and delete tasks, and the remaining count stays correct"

_COMPLETE = [
    {"action": "fill", "target": {"placeholder": "What needs doing?"}, "value": "Buy milk"},
    {"action": "click", "target": {"role": "button", "name": "Add"}},
    {"action": "check", "target": {"role": "checkbox", "name": "Complete Buy milk"}},
]
COUNT_BUG = Finding.model_validate(
    {
        "kind": "bug",
        "title": "Completing a task does not lower the count",
        "description": "The count stays at 1 left.",
        "severity": "high",
        "steps": _COMPLETE,
        "expectation": {"kind": "text", "target": {"test_id": "remaining-count"}, "equals": "0 left"},
    }
)
THROWS = Finding.model_validate(
    {"kind": "bug", "title": "Completing a task throws", "steps": _COMPLETE, "expectation": {"kind": "no_errors"}}
)


def _project(tmp_path: Path, bug: str) -> Path:
    work = tmp_path / "todo"
    shutil.copytree(FIXTURES / "todo" / "app", work, ignore=shutil.ignore_patterns("runs"))
    shutil.copytree(FIXTURES / "todo" / "bugs" / bug, work, dirs_exist_ok=True)
    return work


async def _failures(project: Path, *findings: Finding) -> list[Failure]:
    """Real failures: the findings replayed in Chromium, as `contexer test` confirms them."""
    with open_app(project) as running:
        report = await replay_findings(list(findings), running.url, repeats=1)
    assert len(report.bugs) == len(findings), report.unconfirmed
    return [Failure.from_confirmed(item) for item in report.bugs]


# -- the prompt ------------------------------------------------------------------


async def test_the_prompt_contains_the_exact_expected_and_actual_values_of_the_check_result(tmp_path: Path) -> None:
    [failure] = await _failures(_project(tmp_path, "count-ignores-done"), COUNT_BUG)
    [outcome] = [o for o in failure.result.outcomes if not o.passed]

    prompt = fix_prompt([failure], intent=INTENT)

    # Word for word from the check result, not retold.
    assert outcome.description in prompt and outcome.actual in prompt
    assert 'text of [data-testid="remaining-count"] equals "0 left"' in prompt and '"1 left"' in prompt
    for line in failure.check.describe_lines():
        assert line in prompt
    assert "Completing a task does not lower the count" in prompt and INTENT in prompt


async def test_an_uncaught_exception_is_quoted_in_the_prompt(tmp_path: Path) -> None:
    [failure] = await _failures(_project(tmp_path, "complete-throws"), THROWS)
    assert failure.result.page_errors

    prompt = fix_prompt([failure], intent=INTENT)

    assert failure.result.page_errors[0] in prompt
    assert "uncaught exception" in prompt.lower()


async def test_with_no_brief_or_an_empty_one_the_facts_alone_make_a_usable_prompt(tmp_path: Path) -> None:
    [failure] = await _failures(_project(tmp_path, "count-ignores-done"), COUNT_BUG)

    for brief in (None, RepairBrief()):
        prompt = fix_prompt([failure], brief, intent=INTENT, working=["Adding a task shows it in the list"])
        assert "Likely cause" not in prompt and "Files to look at" not in prompt
        assert '"1 left"' in prompt
        assert "## What to do" in prompt and "make every expectation above hold" in prompt.lower()
        assert "Adding a task shows it in the list" in prompt  # what must keep working
        assert "contexer test --again" in prompt
        assert ".contexer" in prompt  # the rule not to touch Contexer's files


async def test_the_brief_adds_the_cause_and_the_instruction_and_cannot_change_the_facts(tmp_path: Path) -> None:
    [failure] = await _failures(_project(tmp_path, "count-ignores-done"), COUNT_BUG)
    brief = RepairBrief(
        cause="updateCount() counts every task instead of the ones that are not done.",
        files=["app.js"],
        instruction="Count only tasks whose done flag is false in updateCount().",
        keep_working=["Deleting a task still lowers the count"],
    )
    facts_only = fix_prompt([failure], intent=INTENT)
    prompt = fix_prompt([failure], brief, intent=INTENT, working=["Adding a task shows it in the list"])

    assert "## Likely cause" in prompt and brief.cause in prompt
    assert "a hypothesis" in prompt.lower()  # the cause is the agent's opinion and says so
    assert "- `app.js`" in prompt and brief.instruction in prompt
    assert "Deleting a task still lowers the count" in prompt and "Adding a task shows it in the list" in prompt
    # The section with the facts is identical with and without the brief.
    start, end = "## What is wrong", "## What to do"
    assert prompt[prompt.index(start) : prompt.index("## Likely cause")] == facts_only[facts_only.index(start) : facts_only.index(end)]


def test_no_failures_means_no_prompt() -> None:
    assert fix_prompt([], intent=INTENT) == ""


# -- the agent -------------------------------------------------------------------


async def test_the_diagnoser_reads_the_code_and_returns_a_brief(tmp_path: Path) -> None:
    project = _project(tmp_path, "count-ignores-done")
    [failure] = await _failures(project, COUNT_BUG)
    model = ScriptedChatModel(
        calls(("grep", {"pattern": "remaining-count"}), ("read_file", {"path": "app.js"})),
        submit(
            cause="The count is computed from all tasks.",
            files=["app.js"],
            instruction="Filter out completed tasks when computing the count.",
            keep_working=["Adding a task raises the count"],
        ),
    )

    result = await diagnose(
        [failure],
        model,
        project,
        intent=INTENT,
        diff="--- a/app.js\n+++ b/app.js\n+  count = tasks.length;",
        server_log="GET /app.js 200",
        run_dir=tmp_path / "run",
    )

    assert result.status == "ok" and result.brief is not None
    assert result.brief.cause == "The count is computed from all tasks." and result.brief.files == ["app.js"]
    assert model.bound_tools == ["read_file", "grep", "submit"]  # read-only, nothing else
    task = model.seen[0][1]
    assert isinstance(task, HumanMessage)
    for given in (INTENT, failure.result.failure_report(), "count = tasks.length;", "GET /app.js 200"):
        assert given in task.content
    found, read = [m.content for m in model.seen[1] if isinstance(m, ToolMessage)]
    assert "index.html:" in found and "remaining-count" in found
    assert "1: " in read  # numbered lines of the real file
    assert (tmp_path / "run" / "agents" / "diagnoser.jsonl").is_file()


async def test_a_model_error_gives_no_brief_and_the_prompt_is_still_written_from_the_facts(tmp_path: Path) -> None:
    project = _project(tmp_path, "count-ignores-done")
    [failure] = await _failures(project, COUNT_BUG)
    model = ScriptedChatModel(RuntimeError("Error code: 429 - rate limit exceeded"))

    result = await diagnose([failure], model, project, intent=INTENT, run_dir=tmp_path / "run")

    assert result.status == "model_error" and result.brief is None and "429" in result.error
    assert '"1 left"' in fix_prompt([failure], result.brief, intent=INTENT)


# -- the read tools ----------------------------------------------------------------


async def _call(project: Path, name: str, **args: Any) -> str:
    tool = next(t for t in project_tools(project) if t.name == name)
    return str(await tool.ainvoke(args))


async def test_the_read_tools_are_confined_to_the_project_and_keep_out_of_contexer_and_secrets(tmp_path: Path) -> None:
    project = _project(tmp_path, "count-ignores-done")
    (tmp_path / "outside.txt").write_text("not yours", encoding="utf-8")
    (project / ".env").write_text("API_KEY=sk-live-secret-value-1234567890", encoding="utf-8")
    (project / ".git").mkdir()
    (project / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    (project / "node_modules" / "lib").mkdir(parents=True)
    (project / "node_modules" / "lib" / "index.js").write_text("remaining-count", encoding="utf-8")

    assert [t.name for t in project_tools(project)] == ["read_file", "grep"]
    refused: list[Optional[str]] = [
        await _call(project, "read_file", path="../outside.txt"),
        await _call(project, "read_file", path=str(tmp_path / "outside.txt")),
        await _call(project, "read_file", path=".contexer/contracts/todo-basics.json"),
        await _call(project, "read_file", path=".env"),
        await _call(project, "read_file", path=".git/config"),
        await _call(project, "grep", pattern="yours", path=".."),
        await _call(project, "grep", pattern="goal", path=".contexer"),
    ]
    assert all(r is not None and r.startswith("Error:") for r in refused), refused
    assert "outside the project" in str(refused[0]) and ".contexer" in str(refused[2])

    assert (await _call(project, "read_file", path="missing.js")).startswith("Error:")
    read = await _call(project, "read_file", path="app.js", start=1, lines=3)
    assert read.splitlines()[0].startswith("1: ") and len([line for line in read.splitlines() if ": " in line]) >= 3
    # A search of the whole project skips Contexer's files, dependencies and secrets.
    everywhere = await _call(project, "grep", pattern="remaining-count|API_KEY|goal")
    assert "index.html:" in everywhere
    for hidden in ("node_modules", ".contexer", ".env", "sk-live"):
        assert hidden not in everywhere
    assert (await _call(project, "grep", pattern="no-such-text-anywhere")).startswith("No match")
    assert (await _call(project, "grep", pattern="(unclosed")).startswith("Error:")
