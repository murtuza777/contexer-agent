"""``contexer issue``: take GitHub issues from a checklist people approve to a proven pull request.

``draft`` posts the checks on the issue; ``build`` approves them in the name of
the person who said so and runs the agent; ``event`` does whichever of the two
the triggering GitHub event asks for, so a workflow needs one step.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn

import typer
from rich.console import Console
from rich.markup import escape

from contexer.agents import create_agent
from contexer.appserver import AppStartError, open_app
from contexer.browser.tools import sign_in_secrets
from contexer.cli import run_cli
from contexer.cli.gate_cli import compiler_llm, preview_draft
from contexer.cli.run_cli import (
    _draft,
    _render,
    check_free_quota,
    choose_agent,
    execute_graph,
    one_engine,
)
from contexer.config.project import ProjectConfigError, load_project_config, load_project_env
from contexer.contract import Contract, ContractStore
from contexer.controller import RunOutcome, RunSettings
from contexer.crew.budget import DEFAULT_MAX_TOKENS, Budget
from contexer.crew.intent import IntentResult, run_intent
from contexer.evidence import RunDir
from contexer.gate import RunResult
from contexer.gate.session import VerificationSession
from contexer.github.api import GitHubClient, GitHubError, github_token, repo_of
from contexer.github.handoff import Handoff, HandoffError, hand_off, plan_handoff
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


@issue_app.command("draft")
def draft(
    number: int = typer.Argument(..., help="The issue number."),
    project_dir: Path = DirOption,
    url: str | None = typer.Option(None, "--url", "-u", help="Use an app you already run."),
) -> None:
    """Draft the checks for an issue and post them on it, for someone with write access to approve."""
    console = Console()
    project = project_dir.resolve()
    load_project_env(project)
    with _client(console, project) as client:
        issue = _issue(console, client, number)
        posted = client.comment(number, status_comment("Contexer is drafting the checks for this issue…", [], _run_link()))
        store = ContractStore(project)
        origin = ISSUE_ORIGIN.format(number=number)
        contract_id = store.unique_id(f"issue {number} {issue.get('title', '')}")
        one_engine(None)
        model = run_cli.crew_model(project)
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
            body = draft_comment(
                contract, preview, _model_name(model), note, intent=result.spec, questions=result.questions, answers=answers
            )
        else:
            drafting = compiler_llm(project)
            contract, preview, analyzer = _draft(console, project, store, issue_goal(issue), url, drafting, contract_id)
            contract = contract.model_copy(update={"origin": origin})
            store.save(contract)
            note = ""
            if contract.source == "rules":
                reason = f" ({analyzer.last_error})" if analyzer.last_error else ""
                note = f"The model returned no usable checks{reason}, so these come from simple rules. Edit them, or reply `/contexer draft` later."
            body = draft_comment(contract, preview, analyzer.drafted_by or "", note)
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
            _stop(console, client, number, f"Could not check @{by}'s access: {exc}", 3)
        if role not in WRITE_ROLES:
            _stop(console, client, number, f"@{by}, only people with write access can approve Contexer's checks.", 2)
        try:
            draft_at, contract, edited = find_draft(client.comments(number), own=client.identity())
            if changed_after(draft_at, approved_at):
                raise IssueFlowError(
                    f"The checks changed after @{by} approved them, so that approval does not cover what is here now. "
                    "Read the current draft, then reply `/contexer approve` again."
                )
            plan = plan_handoff(project)
            agent = create_agent(*choose_agent(config.agent, agent_name, model))
        except (IssueFlowError, HandoffError, ValueError) as exc:
            _stop(console, client, number, str(exc), 3)
        check_free_quota(console, None, agent, yes=True)

        store = ContractStore(project)
        # The comment's JSON can be edited; where the goal came from is not for the comment to say.
        contract = contract.model_copy(update={"origin": ISSUE_ORIGIN.format(number=number)})
        store.save(contract)
        contract = store.approve(contract.id, by=by)
        approved = f"approved by @{by}" + (" (checks edited in the comment)" if edited else "")
        console.print(f"[green]✓[/] {escape(contract.id)} {escape(approved)}")
        live = _LiveStatus(client, number, f"Building it with {agent.describe()}, {approved}…")
        settings = RunSettings(
            max_repair_rounds=rounds if rounds is not None else config.agent.max_repair_rounds,
            budget_usd=budget if budget is not None else config.agent.budget_usd,
            turn_timeout=config.agent.turn_timeout,
            judged_policy=config.gate.judged,
        )
        outcome = execute_graph(
            console,
            project,
            agent,
            store,
            settings,
            model=run_cli.crew_model(project),
            budget=Budget(max_tokens=config.limits.tokens or DEFAULT_MAX_TOKENS, max_cost_usd=config.limits.cost_usd),
            yes=True,  # nobody is at a terminal in a workflow: Triage does not stop to ask
            contract=contract,
            on_progress=live.event,
        )
        handoff: Handoff | None = None
        handoff_error: str | None = None
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
) -> None:
    """In GitHub Actions: draft or build for the issue or comment that triggered the workflow."""
    name, path = os.environ.get("GITHUB_EVENT_NAME", ""), os.environ.get("GITHUB_EVENT_PATH", "")
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
    except (OSError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(f"cannot read the GitHub event at {path}: {exc}") from exc
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
        draft(number, project_dir, None)
    else:
        said_at = str((payload.get("comment") or {}).get("created_at") or "") or None
        build(number, who, project_dir, agent_name, model, None, None, None, said_at)


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

    def __init__(self, client: GitHubClient, number: int, headline: str) -> None:
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
        if not force and time.monotonic() - self._last < 5:
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


def _stop(console: Console, client: GitHubClient, number: int, message: str, code: int) -> NoReturn:
    console.print(f"[red]{escape(message)}[/]")
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
