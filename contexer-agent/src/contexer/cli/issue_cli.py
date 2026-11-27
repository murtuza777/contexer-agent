"""``contexer issue``: take GitHub issues from a checklist people approve to a proven pull request.

``draft`` posts the checks on the issue; ``build`` approves them in the name of
the person who said so and runs the agent; ``event`` does whichever of the two
the triggering GitHub event asks for, so a workflow needs one step.

With ``--hand-over DIR`` a draft or a build posts and pushes nothing: it leaves what it would have posted,
and the change as a patch, in DIR. ``publish DIR`` then does the posting and the pushing. That is the issue
workflow in two jobs: the one in which the coding agent runs has a token that cannot write, and the one
with the write token runs nothing of the project and reads who approved what from the issue again.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, NoReturn

import typer
from pydantic import BaseModel, Field
from rich.console import Console
from rich.markup import escape

from contexer.agents import create_agent
from contexer.appserver import AppStartError, open_app
from contexer.browser.tools import sign_in_secrets
from contexer.cli import run_cli
from contexer.cli.gate_cli import compiler_llm, preview_draft
from contexer.cli.run_cli import (
    RUN_AGENTS,
    _draft,
    _render,
    check_free_quota,
    choose_agent,
    crew_models,
    execute_graph,
    one_engine,
    run_budget,
)
from contexer.config.project import ProjectConfigError, load_project_config, load_project_env
from contexer.contract import Contract, ContractStore
from contexer.controller import RunOutcome, RunSettings
from contexer.crew.budget import unenforceable
from contexer.crew.intent import IntentResult, Question, run_intent
from contexer.evidence import RunDir
from contexer.gate import RunResult
from contexer.gate.session import VerificationSession
from contexer.github.api import GitHubClient, GitHubError, github_token, repo_of
from contexer.github.handoff import (
    MAX_PATCH_BYTES,
    Handoff,
    HandoffError,
    _intent,
    _plain,
    hand_off,
    make_patch,
    plan_handoff,
    publish_patch,
)
from contexer.github.issues import (
    DEFAULT_LABEL,
    ISSUE_ORIGIN,
    WRITE_ROLES,
    Answer,
    IssueFlowError,
    command_for,
    draft_comment,
    find_draft,
    issue_answers,
    issue_goal,
    status_comment,
)
from contexer.intent.store import IntentSpec, IntentStore, SavedCheck
from contexer.verification.models import AcceptanceCriterion

issue_app = typer.Typer(
    help="Work on GitHub issues: post the checks for approval, then build a proven pull request.",
    no_args_is_help=True,
)

DirOption = typer.Option(Path("."), "--dir", "-d", help="Project directory.", file_okay=False)
HandOverOption = typer.Option(
    None,
    "--hand-over",
    help="Post and push nothing: leave it in this folder for `contexer issue publish`, which a job with the write token runs.",
    file_okay=False,
)

HANDOVER_FILE = "handover.json"
PATCH_FILE = "change.patch"
MAX_HANDOVER_BYTES = 2_000_000


class Handover(BaseModel):
    """What a draft or a build leaves for the job that publishes. That job checks it and believes none of it."""

    command: Literal["draft", "build"]
    issue: int
    stopped: str = ""  # why nothing was drafted or built, to say on the issue
    # A draft: what the comment is written from.
    contract: Contract | None = None
    preview: RunResult | None = None
    drafted_by: str = ""
    note: str = ""
    intent: IntentSpec | None = None  # for a build, the intent the run wrote
    questions: list[Question] = Field(default_factory=list)
    # A build: the run, the lines of its status comment, and why there is no patch when there is none.
    outcome: RunOutcome | None = None
    lines: list[str] = Field(default_factory=list)
    error: str = ""


@issue_app.command("draft")
def draft(
    number: int = typer.Argument(..., help="The issue number."),
    project_dir: Path = DirOption,
    url: str | None = typer.Option(None, "--url", "-u", help="Use an app you already run."),
    hand_over: Path | None = HandOverOption,
) -> None:
    """Draft the checks for an issue and post them on it, for someone with write access to approve."""
    console = Console()
    project = project_dir.resolve()
    load_project_env(project)
    with _client(console, project) as client:
        issue = _issue(console, client, number)
        one_engine(None)
        model = run_cli.crew_model(project)
        if model is not None:
            try:  # [agents.intent] in contexer.toml names the model that drafts, as it does for `contexer run`
                config = load_project_config(project)
                model = crew_models(project, config, default_provider=config.compiler.provider, agents=("intent",)).get("intent", model)
            except (ProjectConfigError, ValueError) as exc:
                _stop(console, client, number, str(exc), 3, hand_over, "draft")
        posted: dict[str, Any] = {}
        if hand_over is None:
            posted = client.comment(number, status_comment("Contexer is drafting the checks for this issue…", [], _run_link()))
        store = ContractStore(project)
        origin = ISSUE_ORIGIN.format(number=number)
        contract_id = store.unique_id(f"issue {number} {issue.get('title', '')}")
        answers: list[Answer] = []
        if model is not None:
            # The Intent agent writes what it understood, the checks, and its questions.
            answers = _answers(client, number)
            with console.status("[dim]Drafting the checks from the issue, then trying them on the app as it is...[/dim]"):
                contract, preview, result = asyncio.run(
                    _draft_with_intent(project, store, issue_goal(issue), origin, contract_id, url, model, answers)
                )
            note = ""
            if result.status != "ok":
                note = f"The Intent agent did not finish ({result.error or result.status}). Reply `/contexer draft` to try again."
            elif not any(c.check for c in contract.criteria):
                note = "No check could be drafted that a browser can run. Say more concretely what should happen, then reply `/contexer draft`."
            left = Handover(
                command="draft", issue=number, contract=contract, preview=preview, drafted_by=_model_name(model), note=note,
                intent=result.spec, questions=list(result.questions),
            )  # fmt: skip
        else:
            drafting = compiler_llm(project)
            contract, preview, analyzer = _draft(console, project, store, issue_goal(issue), url, drafting, contract_id, origin)
            contract = contract.model_copy(update={"origin": origin})
            store.save(contract)
            note = ""
            if contract.source == "rules":
                reason = f" ({analyzer.last_error})" if analyzer.last_error else ""
                note = f"The model returned no usable checks{reason}, so these come from simple rules. Edit them, or reply `/contexer draft` later."
            left = Handover(command="draft", issue=number, contract=contract, preview=preview, drafted_by=analyzer.drafted_by or "", note=note)
        if hand_over is not None:
            _leave(hand_over, left)
            console.print(f"[green]✓[/] Drafted {len(contract.criteria)} checks for issue #{number}; left in {escape(str(hand_over))} to be posted")
            return
        body = draft_comment(contract, preview, left.drafted_by, left.note, intent=left.intent, questions=left.questions, answers=answers)
        client.edit_comment(int(posted["id"]), body)
    console.print(f"[green]✓[/] Posted {len(contract.criteria)} checks on issue #{number}: {escape(str(posted.get('html_url', '')))}")


@issue_app.command("build")
def build(
    number: int = typer.Argument(..., help="The issue number."),
    by: str = typer.Option(..., "--by", help="The GitHub login approving the checks; needs write access."),
    project_dir: Path = DirOption,
    agent_name: str | None = typer.Option(None, "--agent", help="claude-code, codex or opencode."),
    model: str | None = typer.Option(None, "--model", help="Model for the coding agent."),
    rounds: int | None = typer.Option(None, "--rounds", min=0, help="Maximum repair rounds (default 2)."),
    budget: float | None = typer.Option(None, "--budget", help="Stop when the agent has spent this many USD."),
    engine: str | None = typer.Option(None, "--engine", hidden=True, help="Removed in 0.5.0: there is one run loop."),
    approved_at: str | None = typer.Option(
        None, "--approved-at", help="When the approval was given (ISO time). Checks that changed after it are not built."
    ),
    hand_over: Path | None = HandOverOption,
) -> None:
    """Approve the checks drafted on an issue in BY's name, build them, and open a pull request that closes it."""
    console = Console()
    project = project_dir.resolve()
    one_engine(engine)
    load_project_env(project)
    try:
        config = load_project_config(project)
    except ProjectConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc
    with _client(console, project) as client:
        _issue(console, client, number)
        try:
            role = client.permission(by)
        except GitHubError as exc:
            _stop(console, client, number, f"Could not check @{by}'s access: {exc}", 3, hand_over)
        if role not in WRITE_ROLES:
            _stop(console, client, number, f"@{by}, only people with write access can approve Contexer's checks.", 2, hand_over)
        if hand_over is not None and client.can_push():
            # The point of handing over is that nothing in this job can write. It is checked here, not assumed.
            _stop(
                console, client, number,
                "The job that builds has a token that can push to the repository, so nothing was built. Give that job "
                "`permissions: contents: read` and leave the write permissions to the job that publishes.",
                3, hand_over,
            )  # fmt: skip
        try:
            draft_at, contract, edited = find_draft(client.comments(number), own=client.identity())
            if changed_after(draft_at, approved_at):
                raise IssueFlowError(
                    f"The checks changed after @{by} approved them, so that approval does not cover what is here now. "
                    "Read the current draft, then reply `/contexer approve` again."
                )
            plan = plan_handoff(project)
            agent = create_agent(*choose_agent(config.agent, agent_name, model))
            # Before anything is spent, as `contexer run` does: [agents.<name>] names a model per agent.
            crew = run_cli.crew_model(project)
            models = crew_models(project, config, default_provider=config.compiler.provider, agents=RUN_AGENTS) if crew is not None else {}
        except (IssueFlowError, HandoffError, ValueError) as exc:
            _stop(console, client, number, str(exc), 3, hand_over)
        # Before anything is spent or approved, as `contexer run` does: a dollar limit that would count
        # unknown spend as 0 is refused, and the issue is told why.
        crew_budget = run_budget(config)
        called = [models.get(name) or crew for name in RUN_AGENTS] if crew is not None else []
        cannot_keep = unenforceable(crew_budget, models=called, coding_agent="" if agent.reports_cost else agent.name)
        if cannot_keep:
            _stop(console, client, number, cannot_keep, 2, hand_over)
        check_free_quota(console, None, agent, yes=True)

        store = ContractStore(project)
        # The comment's JSON can be edited; where the goal came from is not for the comment to say.
        contract = contract.model_copy(update={"origin": ISSUE_ORIGIN.format(number=number)})
        store.save(contract)
        contract = store.approve(contract.id, by=by)
        approved = f"approved by @{by}" + (" (checks edited in the comment)" if edited else "")
        console.print(f"[green]✓[/] {escape(contract.id)} {escape(approved)}")
        # With a hand-over nothing is posted while the run goes: its lines are kept for the comment the other job posts.
        live = _LiveStatus(client if hand_over is None else None, number, f"Building it with {agent.describe()}, {approved}…")
        settings = RunSettings(
            max_repair_rounds=rounds if rounds is not None else config.agent.max_repair_rounds,
            budget_usd=budget if budget is not None else config.agent.budget_usd,
            turn_timeout=config.agent.turn_timeout,
            judged_policy=config.gate.judged,
            agent_steps={name: cap for name in RUN_AGENTS if (cap := config.agents.for_agent(name).max_steps)},
        )
        outcome = execute_graph(
            console,
            project,
            agent,
            store,
            settings,
            model=crew,
            models=models,
            budget=crew_budget,
            yes=True,  # nobody is at a terminal in a workflow: Triage does not stop to ask
            contract=contract,
            on_progress=live.event,
        )
        handoff: Handoff | None = None
        handoff_error: str | None = None
        if hand_over is not None:
            patch: bytes | None = None
            if outcome.terminal not in ("tampered", "cancelled"):
                try:
                    patch = make_patch(plan, outcome, contract)
                except HandoffError as exc:
                    handoff_error = str(exc)
            left = Handover(
                command="build", issue=number, outcome=outcome.model_copy(update={"diff": ""}), intent=_intent(project, outcome),
                lines=live.lines[-15:], error=handoff_error or "",
            )  # fmt: skip
            _leave(hand_over, left, patch)
            _render(console, outcome, None, handoff_error, False)
            console.print(f"[dim]Nothing was pushed or posted: the run is in {escape(str(hand_over))} for the job that publishes.[/]")
            raise typer.Exit(code=outcome.exit_code)
        if outcome.terminal not in ("tampered", "cancelled"):
            try:
                handoff = hand_off(plan, outcome, contract, issue=number)
            except HandoffError as exc:
                handoff_error = str(exc)
        live.finish(*_result_headline(outcome, handoff, handoff_error))
    _render(console, outcome, handoff, handoff_error, True)
    raise typer.Exit(code=outcome.exit_code)


@issue_app.command("event")
def event(
    project_dir: Path = DirOption,
    label: str = typer.Option(DEFAULT_LABEL, "--label", help="The label that asks Contexer to draft checks."),
    plan_only: bool = typer.Option(False, "--plan", help="Only print what the event asks for: draft, build or ignore."),
    agent_name: str | None = typer.Option(None, "--agent", help="Coding agent for builds."),
    model: str | None = typer.Option(None, "--model", help="Model for the coding agent."),
    hand_over: Path | None = HandOverOption,
) -> None:
    """In GitHub Actions: draft or build for the issue or comment that triggered the workflow."""
    name, payload = _event()
    command, number, who = command_for(name, payload, label)
    if plan_only:
        typer.echo(command)
        output = os.environ.get("GITHUB_OUTPUT")
        if output:
            with open(output, "a", encoding="utf-8") as fh:
                fh.write(f"command={command}\n")
        return
    if command == "ignore" or number is None:
        typer.echo("Nothing for Contexer in this event.")
        return
    if command == "draft":
        if name == "issue_comment":  # a label needs triage rights on GitHub; anyone can comment
            _writers_only(project_dir.resolve(), number, who, hand_over)
        draft(number, project_dir, None, hand_over)
    else:
        build(number, who, project_dir, agent_name, model, None, None, None, _said_at(payload), hand_over)


@issue_app.command("publish")
def publish(
    left_in: Path = typer.Argument(..., help="The folder a draft or a build left with --hand-over.", file_okay=False),
    project_dir: Path = DirOption,
    label: str = typer.Option(DEFAULT_LABEL, "--label", help="The label that asks Contexer to draft checks."),
) -> None:
    """In GitHub Actions, in a job of its own: post or push what a job with no write token left in LEFT_IN.

    Nothing of the project is run and no file of the change is written to the checkout. What was left is
    checked, not believed: the issue, who asked and when come from the event, whether that person may approve
    and which checks were approved are read from GitHub again, and the change is refused when it holds
    anything a run's change may not hold (see ``github/handoff.py: publish_patch``).
    """
    console = Console()
    project = project_dir.resolve()
    name, payload = _event()
    command, number, who = command_for(name, payload, label)
    if command == "ignore" or number is None:
        typer.echo("Nothing for Contexer in this event.")
        return
    if command == "draft" and name == "issue_comment":
        _writers_only(project, number, who)
    with _client(console, project) as client:
        try:
            left = _read_left(left_in, command, number)
        except IssueFlowError as exc:
            _stop(console, client, number, str(exc), 3)
        if left.stopped:  # the other job's words: shown, and one paragraph
            _stop(console, client, number, _plain(" ".join(left.stopped.split())[:1000]), 0)
        if command == "draft":
            if left.contract is None:
                _stop(console, client, number, "The job that drafts left no checks; see the workflow run for why.", 3)
            contract = left.contract.model_copy(update={"origin": ISSUE_ORIGIN.format(number=number), "approval": None})
            body = draft_comment(
                contract, left.preview, _plain(left.drafted_by[:200]), _plain(" ".join(left.note.split())[:600]),
                intent=left.intent, questions=left.questions, answers=_answers(client, number) if left.intent else (),
            )  # fmt: skip
            try:
                posted = client.comment(number, body)
            except GitHubError as exc:
                _stop(console, client, number, f"The checks could not be posted: {exc}", 3)
            console.print(f"[green]✓[/] Posted {len(contract.criteria)} checks on issue #{number}: {escape(str(posted.get('html_url', '')))}")
            return

        try:
            role = client.permission(who)
        except GitHubError as exc:
            _stop(console, client, number, f"Could not check @{who}'s access: {exc}", 3)
        if role not in WRITE_ROLES:
            _stop(console, client, number, f"@{who}, only people with write access can approve Contexer's checks.", 2)
        try:
            draft_at, contract, _edited = find_draft(client.comments(number), own=client.identity())
            if changed_after(draft_at, _said_at(payload)):
                raise IssueFlowError(
                    f"The checks changed after @{who} approved them, so that approval does not cover what is here now. "
                    "Read the current draft, then reply `/contexer approve` again."
                )
            if left.outcome is None:
                raise IssueFlowError("The job that builds left no run to publish; see the workflow run for why.")
        except IssueFlowError as exc:
            _stop(console, client, number, str(exc), 3)
        outcome = left.outcome
        contract = contract.model_copy(update={"origin": ISSUE_ORIGIN.format(number=number)})
        handoff: Handoff | None = None
        error = _plain(" ".join(left.error.split())[:600]) or None
        refused = False
        if error is None and outcome.terminal not in ("tampered", "cancelled"):
            try:
                patch = _read_patch(left_in)
                if patch is not None:
                    handoff = publish_patch(plan_handoff(project), patch, outcome, contract, approved_by=who, issue=number, intent=left.intent)
            except HandoffError as exc:
                error, refused = str(exc), True
        headline, footer = _result_headline(outcome, handoff, error)
        try:
            client.comment(number, status_comment(headline, left.lines, footer))
        except GitHubError as exc:
            console.print(f"[red]The result could not be posted on issue #{number}:[/] {escape(str(exc))}")
    _render(console, outcome, handoff, error, True)
    if refused:
        raise typer.Exit(code=3)


# -- helpers --------------------------------------------------------------------------------


def changed_after(draft: dict[str, Any], approved_at: str | None) -> bool:
    """Whether the draft comment was created or edited after the approval was given. Unknown times: no."""
    stamp = str(draft.get("updated_at") or draft.get("created_at") or "")
    if not approved_at or not stamp:
        return False
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")) > datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
    except ValueError:
        return False


def _event() -> tuple[str, dict[str, Any]]:
    """The GitHub event that started the workflow: its name and what it carries."""
    name, path = os.environ.get("GITHUB_EVENT_NAME", ""), os.environ.get("GITHUB_EVENT_PATH", "")
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
    except (OSError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(f"cannot read the GitHub event at {path}: {exc}") from exc
    return name, payload if isinstance(payload, dict) else {}


def _said_at(payload: dict[str, Any]) -> str | None:
    """When the comment that asked was written: the time an approval was given."""
    return str((payload.get("comment") or {}).get("created_at") or "") or None


def _leave(folder: Path, left: Handover, patch: bytes | None = None) -> None:
    """Write what the publishing job needs into ``folder``."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / HANDOVER_FILE).write_text(left.model_dump_json(), encoding="utf-8")
    if patch is not None:
        (folder / PATCH_FILE).write_bytes(patch)


def _read_left(folder: Path, command: str, number: int) -> Handover:
    """What the other job left, when it is for this event. Read with a size limit; a link is not followed."""
    file = folder / HANDOVER_FILE
    try:
        if file.is_symlink() or not file.is_file():
            raise IssueFlowError("The job before this one left nothing to publish; see the workflow run for why.")
        if file.stat().st_size > MAX_HANDOVER_BYTES:
            raise IssueFlowError("What the job before this one left is too large to read, so nothing was posted or pushed.")
        left = Handover.model_validate_json(file.read_bytes())
    except (OSError, ValueError) as exc:
        raise IssueFlowError("What the job before this one left cannot be read, so nothing was posted or pushed.") from exc
    if left.command != command or left.issue != number:
        raise IssueFlowError("What the job before this one left is for another issue or another command, so nothing was posted or pushed.")
    return left


def _read_patch(folder: Path) -> bytes | None:
    """The change the other job left, or None when it left none. One byte over the limit is enough to refuse it."""
    file = folder / PATCH_FILE
    try:
        if file.is_symlink() or not file.is_file():
            return None
        with file.open("rb") as fh:
            return fh.read(MAX_PATCH_BYTES + 1)
    except OSError as exc:
        raise HandoffError(f"the change the job before this one left cannot be read: {exc}") from exc


def _writers_only(project: Path, number: int, who: str, hand_over: Path | None = None) -> None:
    """Stop unless ``who`` has write access: a draft spends the model's tokens and posts on the issue."""
    console = Console()
    load_project_env(project)
    with _client(console, project) as client:
        try:
            role = client.permission(who)
        except GitHubError as exc:
            _stop(console, client, number, f"Could not check @{who}'s access: {exc}", 3, hand_over, "draft")
        if role not in WRITE_ROLES:
            _stop(console, client, number, f"@{who}, only people with write access can ask Contexer to draft checks.", 2, hand_over, "draft")


def _answers(client: GitHubClient, number: int) -> list[Answer]:
    """The answers on the issue from people who may decide what done means: those with write access."""
    roles: dict[str, bool] = {}
    kept: list[Answer] = []
    try:
        found = issue_answers(client.comments(number))
    except GitHubError:
        return kept
    for answer in found:
        if answer.by not in roles:
            try:
                roles[answer.by] = client.permission(answer.by) in WRITE_ROLES
            except GitHubError:
                roles[answer.by] = False
        if roles[answer.by]:
            kept.append(answer)
    return kept


async def _draft_with_intent(
    project: Path,
    store: ContractStore,
    goal: str,
    origin: str,
    contract_id: str,
    url: str | None,
    model: Any,
    answers: list[Answer],
) -> tuple[Contract, RunResult | None, IntentResult]:
    """Draft an issue's checks with the Intent agent, on the app as it is when it runs."""
    run_dir = RunDir.create(project)
    session = VerificationSession(project, run_dir)
    intents = IntentStore(project)
    spec = IntentSpec(id=intents.id_for(goal), goal=goal.strip())
    for answer in answers:  # written into the intent by code, so they hold whatever the model does
        spec = spec.with_correction(answer.text)

    async def drafted(ui_snapshot: str, repo_summary: str) -> tuple[Contract, IntentResult]:
        result = await run_intent(
            goal,
            model,
            stored=spec,
            ui_snapshot=ui_snapshot,
            repo_summary=repo_summary,
            run_dir=run_dir.path,
            origin=origin,
            secrets=sign_in_secrets(session.auth),
        )
        contract = Contract(
            id=contract_id,
            goal=goal.strip(),
            summary="Drafted by the Intent agent from the issue.",
            criteria=[_criterion(check) for check in result.checks],
            source="llm",
            origin=origin,
        )
        return contract, result

    try:
        with open_app(project, url) as app:
            seen = await session.observe(app)
            summary = app.repo_context.format_summary() if app.repo_context is not None else ""
            contract, result = await drafted(seen.ui_snapshot, summary)
            preview = await preview_draft(session, app, contract)
    except AppStartError:  # nothing runs yet: the checks are drafted from the issue alone
        contract, result = await drafted("", "")
        preview = None
    store.save(contract)
    return contract, preview, result


def _criterion(check: SavedCheck) -> AcceptanceCriterion:
    return AcceptanceCriterion(
        id=check.id, description=check.description, verification_method="interactive_test", check=check.check
    )


def _model_name(model: Any) -> str:
    from contexer.llm.chat import describe_model

    return describe_model(model)


class _LiveStatus:
    """One comment on the issue that follows the run: attempts, verdicts, reverts."""

    _KINDS = ("phase", "verdict", "revert", "strategy", "agent-done", "review")

    def __init__(self, client: GitHubClient | None, number: int, headline: str) -> None:
        self.client, self.number, self.headline = client, number, headline
        self.lines: list[str] = []
        self.comment_id: int | None = None
        self._last = 0.0
        self._post(force=True)

    def event(self, kind: str, message: str) -> None:
        if kind in self._KINDS:
            self.lines.append(message)
            self._post(force=kind == "verdict")

    def finish(self, headline: str, footer: str) -> None:
        self.headline = headline
        self._post(force=True, footer=footer)

    def _post(self, force: bool = False, footer: str = "") -> None:
        if self.client is None or (not force and time.monotonic() - self._last < 5):
            return
        body = status_comment(self.headline, self.lines, footer or _run_link())
        try:
            if self.comment_id is None:
                self.comment_id = int(self.client.comment(self.number, body)["id"])
            else:
                self.client.edit_comment(self.comment_id, body)
            self._last = time.monotonic()
        except GitHubError:
            pass  # the run matters more than its progress comment


def _result_headline(outcome: RunOutcome, handoff: Handoff | None, error: str | None) -> tuple[str, str]:
    decision = outcome.final.decision if outcome.final is not None else None
    link = ""
    if handoff is not None and handoff.url:
        link = f"{'Draft pull request' if handoff.draft else 'Pull request'}: {handoff.url}" if handoff.is_pull_request else f"Open the pull request: {handoff.url}"
    elif error:
        link = f"No pull request: {error}"
    if outcome.terminal == "succeeded" and decision is not None:
        headline = f"✅ Done: all {decision.verified} checks proven in a real browser"
    elif outcome.terminal == "cancelled":
        headline = "⏹️ Stopped before the run ended"
    else:
        headline = f"⚠️ Not done: {outcome.reason[:200]}"
    footer = "\n\n".join(part for part in (link, handoff.note.strip() if handoff and handoff.note else "", _run_link()) if part)
    return headline, footer


def _client(console: Console, project: Path) -> GitHubClient:
    repo, token = repo_of(project), github_token()
    if repo is None or token is None:
        missing = "a GitHub remote" if repo is None else "a GitHub token (GITHUB_TOKEN, or `gh auth login`)"
        console.print(f"[red]Cannot work on GitHub issues here:[/] the project needs {missing}.")
        raise typer.Exit(code=3)
    return GitHubClient(repo, token)


def _issue(console: Console, client: GitHubClient, number: int) -> dict:
    try:
        return client.issue(number)
    except GitHubError as exc:
        console.print(f"[red]Cannot read issue #{number}:[/] {escape(str(exc))}")
        raise typer.Exit(code=3) from exc


def _stop(
    console: Console,
    client: GitHubClient,
    number: int,
    message: str,
    code: int,
    hand_over: Path | None = None,
    command: Literal["draft", "build"] = "build",
) -> NoReturn:
    """Say why on the issue and exit. With a hand-over the reason is left for the job that can post."""
    console.print(f"[red]{escape(message)}[/]")
    if hand_over is not None:
        _leave(hand_over, Handover(command=command, issue=number, stopped=message))
        raise typer.Exit(code=code)
    try:
        client.comment(number, status_comment("Contexer stopped", [], f"{message}\n\n{_run_link()}".strip()))
    except GitHubError:
        pass
    raise typer.Exit(code=code)


def _run_link() -> str:
    run_id, repo = os.environ.get("GITHUB_RUN_ID"), os.environ.get("GITHUB_REPOSITORY")
    if not (run_id and repo):
        return ""
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    return f"[Workflow run and evidence]({server}/{repo}/actions/runs/{run_id})"
