"""Work picked up from GitHub issues: a checklist posted for approval, then a proven pull request.

1. **Draft.** Labelling an issue ``contexer`` (or commenting ``/contexer draft``)
   drafts the contract from the issue and posts it as a comment: the checks in
   plain words, how each one fares on the app today, and the exact contract
   as JSON. Someone with write access may edit that JSON in the comment.
2. **Approve.** ``/contexer approve`` from someone with write access approves
   the contract in the comment, in that person's name. The coding agent
   builds it, Contexer proves it, and a pull request that closes the issue
   is opened. One status comment follows the run as it goes.

Nothing in an issue or a comment counts as an approval except that command
from a person with write access, checked through the API.

When the Intent agent drafts the checks, the comment also shows what it
understood and any question it has. ``/contexer answer <text>`` answers one:
the checks are drafted again with every answer given by someone with write
access. An answer changes what is drafted, never what is approved.

The issue's own text is data: wherever it goes into a prompt it is quoted,
with a fixed preamble (``crew/untrusted.py: quoted_goal``).
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from pydantic import ValidationError

from contexer.contract import Contract
from contexer.gate.models import RunResult

if TYPE_CHECKING:
    from contexer.crew.intent import Question
    from contexer.intent.store import IntentSpec

Command = Literal["draft", "build", "ignore"]

DEFAULT_LABEL = "contexer"
_DRAFT = re.compile(r"<!-- contexer:draft id=(?P<id>[\w.-]+) sha256=(?P<sha>[0-9a-f]+) -->")
_JSON_BLOCK = re.compile(r"```json\s*\n(?P<json>.*?)\n```", re.DOTALL)
STATUS_MARKER = "<!-- contexer:status -->"
WRITE_ROLES = {"admin", "maintain", "write"}
# What a contract drafted from an issue records as the origin of its goal.
ISSUE_ORIGIN = "GitHub issue #{number}"
_ANSWER = re.compile(r"^\s*/contexer\s+answer\s+(?P<text>.+)", re.IGNORECASE | re.DOTALL)
MAX_ANSWER_CHARS = 1000


@dataclass(frozen=True)
class Answer:
    """What someone replied to the Intent agent's questions with ``/contexer answer``."""

    by: str
    text: str


class IssueFlowError(Exception):
    """The issue flow cannot go on; the message is fit to post on the issue."""


def command_for(event_name: str, event: dict[str, Any], label: str = DEFAULT_LABEL) -> tuple[Command, int | None, str]:
    """What a GitHub event asks Contexer to do: (command, issue number, who asked)."""
    issue = event.get("issue") or {}
    number = issue.get("number")
    if not isinstance(number, int) or issue.get("pull_request"):
        return "ignore", None, ""
    if event_name == "issues" and event.get("action") == "labeled":
        if (event.get("label") or {}).get("name") == label:
            return "draft", number, str((event.get("sender") or {}).get("login", ""))
        return "ignore", number, ""
    if event_name == "issue_comment" and event.get("action") == "created":
        comment = event.get("comment") or {}
        words = str(comment.get("body") or "").strip().split()
        login = str((comment.get("user") or {}).get("login", ""))
        if len(words) >= 2 and words[0].lower() == "/contexer":
            verb = words[1].lower()
            if verb == "draft" or (verb == "answer" and len(words) >= 3):
                return "draft", number, login  # an answer drafts the checks again, with the answer applied
            if verb in ("approve", "build"):
                return "build", number, login
    return "ignore", number, ""


_HTML_COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)
# Zero-width and direction characters: invisible on the page, read by a model.
_INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")


def visible_text(text: str) -> str:
    """``text`` without what GitHub does not show: HTML comments and invisible characters."""
    cleaned = _INVISIBLE.sub("", _HTML_COMMENT.sub("", text))
    lines = [line.rstrip() for line in cleaned.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def issue_goal(issue: dict[str, Any]) -> str:
    """The goal an issue states: its title and text as a person reading the issue sees them.

    The person who approves the checks reads the rendered issue. Text that does not render there
    would reach the agents without anyone having seen it, so it is removed first.
    """
    title = visible_text(str(issue.get("title") or ""))
    body = visible_text(str(issue.get("body") or ""))
    return f"{title}\n\n{body[:4000]}".strip()


def issue_answers(comments: list[dict[str, Any]]) -> list[Answer]:
    """Every ``/contexer answer`` on the issue, oldest first. Whether its author may answer is the caller's check."""
    answers: list[Answer] = []
    for comment in comments:
        if (comment.get("user") or {}).get("type") == "Bot":
            continue
        match = _ANSWER.match(str(comment.get("body") or ""))
        if match is None:
            continue
        text = " ".join(match.group("text").split())[:MAX_ANSWER_CHARS]
        login = str((comment.get("user") or {}).get("login", ""))
        if text and login:
            answers.append(Answer(by=login, text=text))
    return answers


def draft_comment(
    contract: Contract,
    preview: RunResult | None,
    drafted_by: str = "",
    note: str = "",
    *,
    intent: IntentSpec | None = None,
    questions: Sequence[Question] = (),
    answers: Sequence[Answer] = (),
) -> str:
    lines = [
        f"<!-- contexer:draft id={contract.id} sha256={contract.content_hash()} -->",
        "### Contexer: what \"done\" means for this issue",
        "",
    ]
    if intent is not None and (intent.behaviours or intent.assumptions):
        lines += ["### What Contexer understood", ""]
        lines += [f"- {_md(line)}" for line in intent.behaviours]
        if intent.assumptions:
            lines += ["", "Assumed without asking:", "", *[f"- {_md(line)}" for line in intent.assumptions]]
        lines.append("")
    if answers:
        lines += ["Answers applied: " + "; ".join(f"@{a.by}: {_md(a.text)}" for a in answers), ""]
    if questions:
        lines += ["### Questions", "", "The issue can be read in more than one way. The checks below take the first reading.", ""]
        for number, q in enumerate(questions, 1):
            lines += [
                f"{number}. **{_md(q.question)}**",
                f"   - Taken: {_md(q.reading_a)}",
                f"   - Otherwise: {_md(q.reading_b)}",
            ]
        lines += [
            "",
            "To answer, someone with write access replies `/contexer answer <your answer>`; the checks are drafted again.",
            "",
        ]
    lines += [
        "Contexer drafted these checks from the issue. Each one runs in a real browser against the app.",
        "",
        "The goal, exactly as the agents will read it (anything hidden in the issue was removed):",
        "",
        *[f"> {line}" if line.strip() else ">" for line in contract.goal.strip()[:3000].splitlines()],
        "",
        "| | Check | On the app today |",
        "|---|---|---|",
    ]
    today = _preview_marks(preview)
    for criterion in contract.criteria:
        mark = "🔎" if criterion.check else "📝"
        lines.append(f"| {mark} | {_md(criterion.description)} | {today.get(criterion.id, '—')} |")
    executable = sum(1 for c in contract.criteria if c.check)
    lines += ["", f"{executable} of {len(contract.criteria)} checks are executable in the browser."]
    if note:
        lines += ["", f"> ⚠️ {note}"]
    if drafted_by:
        lines += ["", f"<sub>Drafted by {drafted_by}.</sub>"]
    lines += [
        "",
        "**To build it,** someone with write access replies `/contexer approve`. The coding agent then builds it, "
        "Contexer proves every check, and opens a pull request that closes this issue.",
        "**To change the checks,** edit the JSON below in this comment, then approve. To start over, edit the "
        "issue and reply `/contexer draft`.",
        "",
        "<details><summary>The contract (JSON)</summary>",
        "",
        "```json",
        json.dumps(contract.model_dump(mode="json", exclude={"approval"}), indent=2, ensure_ascii=False),
        "```",
        "",
        "</details>",
    ]
    return "\n".join(lines) + "\n"


def find_draft(comments: list[dict[str, Any]], own: str = "") -> tuple[dict[str, Any], Contract, bool]:
    """The newest Contexer draft on the issue: (comment, contract, edited since drafting).

    ``own`` is the login Contexer's token posts as. Only that account's comment is a draft: with a
    personal token that is a person, in Actions it is ``github-actions[bot]``. When the login is not
    known, a comment by any bot is taken, as before.
    """
    for comment in reversed(comments):
        body = str(comment.get("body") or "")
        marker = _DRAFT.search(body)
        author = comment.get("user") or {}
        ours = (str(author.get("login") or "").lower() == own.lower()) if own else author.get("type") == "Bot"
        if marker is None or not ours:
            continue
        block = _JSON_BLOCK.search(body, marker.end())
        if block is None:
            raise IssueFlowError("The draft comment has no contract JSON any more; reply `/contexer draft` to draft again.")
        try:
            contract = Contract.model_validate(json.loads(block.group("json")))
        except (json.JSONDecodeError, ValidationError) as exc:
            first = str(exc).splitlines()[0][:200]
            raise IssueFlowError(f"The contract JSON in the draft comment is not valid ({first}). Fix it, or reply `/contexer draft`.") from exc
        if not contract.criteria:
            raise IssueFlowError("The contract in the draft comment has no checks.")
        return comment, contract.model_copy(update={"approval": None}), contract.content_hash() != marker.group("sha")
    raise IssueFlowError("There is no Contexer draft on this issue yet. Reply `/contexer draft` first.")


def status_comment(headline: str, lines: list[str], footer: str = "") -> str:
    body = [STATUS_MARKER, f"### {headline}", ""]
    if lines:
        body += ["```text", *lines[-15:], "```", ""]
    if footer:
        body.append(footer)
    return "\n".join(body) + "\n"


def _preview_marks(preview: RunResult | None) -> dict[str, str]:
    marks: dict[str, str] = {}
    if preview is None or preview.decision.outcome == "error":
        return marks
    for outcome in preview.contracts:
        for r in outcome.verification.criteria_results if outcome.verification else []:
            if r.check_result is None:
                continue
            marks[r.criterion_id] = {
                "verified": "✅ already passes",
                "refuted": f"❌ not yet: {_md(r.evidence)[:80]}",
                "unverified": "❔ cannot run yet",
            }[r.verdict]
    return marks


def _md(text: str) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")
