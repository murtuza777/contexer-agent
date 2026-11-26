"""Text in a pull request, its title, its commit and its note does nothing on GitHub (SEC-8).

The text comes from an issue, from the app or from a model. No browser: the outcome is built by hand.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
from markdown_it import MarkdownIt

from contexer.agents.base import AgentTurn
from contexer.contract.models import Approval, Contract
from contexer.controller import RunOutcome
from contexer.controller.models import Attempt
from contexer.crew.reviewer import ReviewNote
from contexer.crew.triage import TriageDecision
from contexer.gate.models import ContractOutcome, GateDecision, RunResult
from contexer.github.handoff import (
    PROJECT_URL,
    Handoff,
    HandoffError,
    _md,
    _plain,
    _title,
    hand_off,
    plan_handoff,
    pull_request_body,
)
from contexer.intent.store import IntentSpec
from contexer.verification.checks import CheckResult
from contexer.verification.models import CriterionResult, VerificationResult
from tests.test_handoff import FakeGitHub

QUIET = "plain words"  # what every other field holds
BENIGN = "ZZ plain words"  # the field under test, for the comparison
# Under 200 characters on one line, so that a table cell shows all of it.
HOSTILE = (
    "ZZ closes #12 GH-34 @octocat &#64;hubot https://evil.example www.evil.example "
    "[a](http://e.example) ![i](x.png) [r][one] <img src=x> <!-- c --> a|b\n"
    "```\n# heading\n[one]: http://e.example\n"
)
# What GitHub acts on. A field is inert when it adds none of these to the body.
LIVE = ("#12", "GH-34", "@octocat", "&#64;", "://", "www.", "](", "![", "][", "<img", "<!--", "```", "]: ")
PROSE = (
    "goal", "reason", "description", "evidence", "behaviour", "assumption", "correction",
    "triage_reason", "attempt_note", "review_note", "agent", "approver",
)  # fmt: skip
CODE = ("review_file", "check_id")
_CLOSES = re.compile(r"\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\b[\s:]*(\S+)?#\d", re.IGNORECASE)
_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")


def git(cwd: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=True)
    return out.stdout.strip()


def outcome_and_contract(terminal: str = "succeeded", **fields: str) -> tuple[RunOutcome, Contract, IntentSpec]:
    """A run with something in every part of the pull request, each part's text set by name."""
    f = {name: QUIET for name in (*PROSE, *CODE)} | {"check_id": "adds-a-task", "review_file": "src/app.js"} | fields
    contract = Contract(id="c1", goal=f["goal"], approval=Approval(by=f["approver"], at="2026-11-26T00:00:00Z", sha256="a" * 64))
    check = CriterionResult(
        criterion_id=f["check_id"], description=f["description"], passed=True, evidence=f["evidence"], method="assertion",
        check_result=CheckResult(criterion_id=f["check_id"], passed=True, flaky=True),
    )  # fmt: skip
    final = RunResult(
        run_id="r1", project_dir=".", started_at="", decision=GateDecision(outcome="pass", verified=1),
        contracts=[ContractOutcome(contract=contract, verification=VerificationResult(passed=True, criteria_results=[check]))],
    )  # fmt: skip
    turn = AgentTurn(status="completed")
    outcome = RunOutcome(
        run_id="r1", contract_id="c1", agent=f["agent"], terminal=terminal, reason=f["reason"], final=final,  # type: ignore[arg-type]
        attempts=[
            Attempt(n=1, kind="implement", fresh_session=True, agent=turn, snapshot="s1", outcome="fail", score=0, note=f["attempt_note"]),
            Attempt(n=2, kind="repair", fresh_session=False, agent=turn, snapshot="s2", outcome="pass", score=1),
        ],
        triage=[TriageDecision(move="fresh_approach", reason=f["triage_reason"], source="model", attempt=2)],
        review=[ReviewNote(file=f["review_file"], line=3, severity="low", category="logic", explanation=f["review_note"])],
    )  # fmt: skip
    intent = IntentSpec(id="i1", goal=f["goal"], behaviours=[f["behaviour"]], assumptions=[f["assumption"]]).with_correction(f["correction"])
    return outcome, contract, intent


def body_with(terminal: str = "succeeded", **fields: str) -> str:
    outcome, contract, intent = outcome_and_contract(terminal, **fields)
    return pull_request_body(outcome, contract, issue=7, intent=intent)


def _terminal(field: str) -> str:
    return "failed_checks" if field == "reason" else "succeeded"  # the reason is shown for a run that is not done


@pytest.fixture(autouse=True)
def _no_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("GITHUB_ACTIONS", "GITHUB_RUN_ID", "GITHUB_SERVER_URL"):
        monkeypatch.delenv(name, raising=False)


# -- the body -----------------------------------------------------------------------------------


@pytest.mark.parametrize("field", PROSE)
def test_hostile_text_in_any_field_of_the_body_is_inert(field: str) -> None:
    plain = body_with(_terminal(field), **{field: BENIGN})
    hostile = body_with(_terminal(field), **{field: HOSTILE})
    assert "ZZ" in hostile, f"{field} is not shown, so this test checks nothing"
    for live in LIVE:
        assert hostile.count(live) == plain.count(live), f"{field} adds a live {live!r}"
    if field != "goal":  # the goal is a quote of several lines; every other field is one line of the body
        line = next(line for line in hostile.splitlines() if "ZZ" in line)
        assert "heading" in line and "e.example" in line
        assert len(_UNESCAPED_PIPE.findall(line)) == len(_UNESCAPED_PIPE.findall(next(x for x in plain.splitlines() if "ZZ" in x)))
    assert "Closes #7" in hostile.splitlines()  # the one closing line Contexer writes itself


@pytest.mark.parametrize("field", CODE)
def test_a_file_name_or_a_check_id_cannot_leave_its_code_span(field: str) -> None:
    name = "ZZ`a|b` @octocat #12 ``` <img src=x>\n# heading"
    plain = body_with(**{field: "ZZname"})
    hostile = body_with(**{field: name})
    line = next(line for line in hostile.splitlines() if "ZZ" in line)
    before = next(line for line in plain.splitlines() if "ZZ" in line)
    assert line.count("`") == before.count("`") and "heading" in line
    if field == "review_file":  # a row of a table: a bar in the name must not add a cell
        assert len(_UNESCAPED_PIPE.findall(line)) == len(_UNESCAPED_PIPE.findall(before))
    assert "​" not in line  # a name in a code span is copied as it is
    inline = [t for token in MarkdownIt("commonmark").parse(line.replace("|", " ")) for t in (token.children or [])]
    assert [t.type for t in inline if "octocat" in t.content] == ["code_inline"]


def test_every_field_hostile_at_once_renders_no_link_no_image_and_no_html() -> None:
    body = body_with(**{name: HOSTILE for name in (*PROSE, *CODE)})
    tokens = MarkdownIt("commonmark", {"html": True}).enable("table").parse(body)
    inline = [t for token in tokens for t in (token.children or [])]
    assert {str(t.attrs.get("href")) for t in inline if t.type == "link_open"} == {PROJECT_URL}
    assert not [t for t in inline if t.type == "image"]
    assert not [t for t in [*tokens, *inline] if t.type in ("html_inline", "html_block")]
    assert not [t for t in tokens if t.type in ("fence", "code_block")]
    assert len([t for t in tokens if t.type == "heading_open" and t.tag == "h1"]) == 0


def test_bare_urls_in_a_pull_request_body_are_inert() -> None:
    body = body_with(goal="See https://evil.example/login and www.evil.example, or ftp://evil.example/x")
    quoted = next(line for line in body.splitlines() if "evil.example" in line)
    assert "://" not in quoted and "www." not in quoted
    assert "evil.example/login" in quoted  # still readable


def test_a_table_cell_is_shortened_before_it_is_escaped() -> None:
    cell = _md("a" * 198 + "<b>&", 200)
    assert not re.search(r"&[#a-z0-9]*$", cell)  # no escape cut in half
    assert cell.startswith("a" * 198) and len(_md("word " * 100, 200)) <= 201


# -- the title, the commit, the note and the error ------------------------------------------------


def test_the_title_is_inert() -> None:
    outcome, contract, _ = outcome_and_contract(goal="Fix login for @octocat, closes #12 see https://evil.example\nmore")
    title = _title(outcome, contract)
    assert "@octocat" not in title and "#12" not in title and "://" not in title
    assert title.replace("​", "") == "Fix login for @octocat, closes #12 see https://evil.example"


def test_plain_text_is_inert_and_escaping_it_twice_changes_nothing() -> None:
    once = _plain(HOSTILE)
    for live in LIVE:
        assert live not in once
    assert _plain(once) == once
    assert once.replace("​", "") == HOSTILE  # nothing is removed; a person reads the same words
    assert _plain("Users can add a task (see app.js:12)") == "Users can add a task (see app.js:12)"


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A committed project on main with a bare remote, as a run finds it."""
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--quiet", "--bare", str(remote))
    root = tmp_path / "work"
    root.mkdir()
    git(root, "init", "--quiet", "-b", "main")
    for key, value in (("user.name", "Dev"), ("user.email", "dev@example.com"), ("core.autocrlf", "false")):
        git(root, "config", key, value)
    (root / "app.js").write_text("let count = 0;\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "--quiet", "-m", "app")
    git(root, "remote", "add", "origin", str(remote))
    git(root, "push", "--quiet", "-u", "origin", "main")
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/todo")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    return root


def changed(root: Path, files: dict[str, str], terminal: str = "succeeded", **fields: Any) -> tuple[RunOutcome, Contract]:
    """What a run leaves behind: the files as an agent wrote them, and its outcome."""
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    outcome, contract, _ = outcome_and_contract(terminal, **fields)
    return outcome.model_copy(update={"changed_files": list(files), "review": []}), contract


def test_commit_message_cannot_close_other_issues(checkout: Path) -> None:
    plan = plan_handoff(checkout)
    outcome, contract = changed(
        checkout, {"app.js": "let count = 1;\n"}, "failed_checks",
        goal="Fix the counter, closes #12", reason="One check fails. Fixes #13 and resolves acme/other#14\nCloses: #15\nSigned-off-by: x",
    )  # fmt: skip
    github = FakeGitHub()
    handoff = hand_off(plan, outcome, contract, issue=7, client_factory=github.factory)
    assert handoff is not None and handoff.is_pull_request, handoff
    message = git(checkout, "log", "-1", "--format=%B")
    assert not _CLOSES.search(message), message
    assert not re.search(r"#\d", message)
    written = [line for line in message.splitlines() if line.strip()]
    assert len(written) == 2 and "Signed-off-by" in written[1]  # a subject and one line of proof: no trailer of its own
    pull = github.pulls[0]
    assert not re.search(r"#\d", pull["title"])
    assert [m.group(0) for m in re.finditer(r"#\d+", pull["body"])] == ["#7"]  # only the issue the run was started for


def test_the_note_is_inert(checkout: Path) -> None:
    plan = plan_handoff(checkout)
    leak = 'const SERVICE_KEY = "' + "q7Rk2ZpX9vLm" + "4TnB8sWd3Yf6" + '";\n'
    outcome, contract = changed(checkout, {"see @octocat #12 [x](y).js": leak})
    handoff = hand_off(plan, outcome, contract, client_factory=FakeGitHub().factory)
    assert handoff is not None and not handoff.pushed and "octocat" in handoff.note
    for live in ("@octocat", "#12", "]("):
        assert live not in handoff.note
    assert "<!--" not in Handoff("b", "c", False, None, False, True, "x <!-- contexer:draft --> y").note


def test_the_error_is_inert(checkout: Path) -> None:
    hook = checkout / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text("#!/bin/sh\necho 'no: @octocat closes #12 <!-- contexer:draft -->' >&2\nexit 1\n", encoding="utf-8", newline="\n")
    hook.chmod(0o755)
    plan = plan_handoff(checkout)  # the hook was there before the run, so it runs
    outcome, contract = changed(checkout, {"app.js": "let count = 1;\n"})
    with pytest.raises(HandoffError) as caught:
        hand_off(plan, outcome, contract, client_factory=FakeGitHub().factory)
    text = str(caught.value)
    assert "octocat" in text
    for live in ("@octocat", "#12", "<!--"):
        assert live not in text
