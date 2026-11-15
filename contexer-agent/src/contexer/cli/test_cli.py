"""``contexer test``: explore a running app like a user and report only what replays.

No coding agent is involved and nothing in the project is changed. The Tester
agent uses the app in a real browser against the stated intent; every finding
it records is then replayed by code in a fresh browser, and only the ones that
reproduce are shown.
"""

from __future__ import annotations

import asyncio
import sys
import time
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import typer
from rich.console import Console
from rich.markup import escape

from contexer import __version__
from contexer.appserver import AppStartError, RunningApp, open_app
from contexer.browser.freeze import Confirmed, draft_contract, freeze, replay_findings, write_unconfirmed
from contexer.browser.tools import BrowserSession
from contexer.cli import term
from contexer.cli.gate_cli import DirOption, UrlOption
from contexer.contract import ContractStore
from contexer.contract.models import utc_now
from contexer.crew.tester import DEFAULT_MAX_STEPS, run_tester
from contexer.evidence import RunDir
from contexer.evidence.test_report import ConfirmedFinding, ExplorationResult, write_test_evidence
from contexer.gate.session import DEV_SERVER_TIMEOUT_SCALE, VerificationSession
from contexer.llm.base import LLMError
from contexer.verification.runner import CheckRunner, _typed_values
from contexer.verification.verifier import Verifier

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

DRAFT_FILE = "draft-contract.json"
_STOPPED_EARLY = {
    "step_limit": "stopped at the step limit",
    "timeout": "stopped at the time limit",
    "invalid_output": "ended without a usable summary",
}


class NoModelError(LLMError):
    """No model is configured for the agents."""


def build_model(project: Path, provider: Optional[str] = None, model: Optional[str] = None) -> BaseChatModel:
    """The chat model the Tester runs on: ``--provider``/``--model``, else the project's and the user's choice.

    The choice follows the drafting model (``[compiler]`` in contexer.toml,
    then ``contexer setup``, then the first key found). A model the provider
    lists as unable to call tools is refused here, before anything starts.
    """
    from contexer.cli.gate_cli import compiler_llm
    from contexer.config.settings import load_config
    from contexer.llm.chat import chat_model, require_tools, resolve_model

    config = load_config()
    if not provider:
        chosen = compiler_llm(project)
        if chosen is None:
            raise NoModelError(
                "No model is configured. Run `contexer setup` to bring your own key, or set "
                "ANTHROPIC_API_KEY, OPENAI_API_KEY or OPENROUTER_API_KEY."
            )
        provider, model = chosen.name, model or chosen.model
    choice = resolve_model(provider, model, config)
    require_tools(choice.spec.id, choice.model, api_key=choice.api_key, base_url=choice.base_url)
    return chat_model(provider, choice.model, config=config)


def on_app_started(running: RunningApp) -> None:
    """Called once the app is up. A seam for callers that need the running app (tests use it)."""


def test(
    intent: str = typer.Argument(..., help="What the app should do, in your words."),
    project_dir: Path = DirOption,
    url: Optional[str] = UrlOption,
    steps: int = typer.Option(DEFAULT_MAX_STEPS, "--steps", min=1, help="The most model calls the tester may make."),
    model: Optional[str] = typer.Option(None, "--model", help="Model id for the tester (default: your drafting model)."),
    provider: Optional[str] = typer.Option(None, "--provider", help="Provider for --model, e.g. anthropic, openrouter."),
    save: bool = typer.Option(False, "--save", help="Save the confirmed checks as a draft contract in the project."),
    json_output: bool = typer.Option(False, "--json", help="Print result.json to stdout."),
    open_report: bool = typer.Option(False, "--open", help="Open the HTML report when done."),
) -> None:
    """Test the running app like a user; exit 0 no confirmed bugs, 1 confirmed bugs, 2 could not test, 3 error."""
    from contexer.config.project import load_project_env

    console = Console(stderr=json_output)
    project = project_dir.resolve()
    load_project_env(project)
    term.header(console, "test", intent)
    try:
        chat = build_model(project, provider, model)
    except (LLMError, ValueError) as exc:
        term.note(console, "fail", f"[red]Could not test:[/] {escape(str(exc))}")
        raise typer.Exit(code=2) from None

    try:
        result = asyncio.run(run_test(project, intent, chat, url=url, steps=steps, save=save, console=console))
    except KeyboardInterrupt:
        _quiet_interrupted_shutdown()
        console.print()
        term.note(console, "warn", "Stopped. The browser and the app were closed; nothing in the project was changed.")
        raise typer.Exit(code=130) from None

    render_test_result(console, result)
    if json_output:
        sys.stdout.write(result.model_dump_json(indent=2) + "\n")
    if open_report and result.run_dir:
        webbrowser.open(Path(result.run_dir, "report.html").resolve().as_uri())
    raise typer.Exit(code=result.exit_code)


def _quiet_interrupted_shutdown() -> None:
    """After Ctrl+C, Playwright's cancelled tasks and closed pipes complain as the interpreter exits.

    The browser is already gone by then; the complaints would only bury the one line that matters.
    """
    import logging

    logging.getLogger("asyncio").setLevel(logging.CRITICAL)
    sys.unraisablehook = lambda _unraisable: None


async def run_test(
    project: Path,
    intent: str,
    chat: BaseChatModel,
    *,
    url: Optional[str] = None,
    steps: int = DEFAULT_MAX_STEPS,
    save: bool = False,
    console: Optional[Console] = None,
) -> ExplorationResult:
    """Start the app, sign in, let the Tester explore, replay what it found, and write the evidence."""
    from contexer.llm.chat import describe_model

    console = console or Console()
    started = time.monotonic()
    run = RunDir.create(project)
    result = ExplorationResult(
        intent=intent,
        outcome="error",
        model=describe_model(chat),
        project_dir=str(project),
        run_id=run.run_id,
        run_dir=str(run.path),
        started_at=utc_now(),
        contexer_version=__version__,
    )
    session = VerificationSession(project, run, verifier=Verifier(llm_provider=None, runner=CheckRunner()))
    store = ContractStore(project)

    def status(message: str) -> None:
        console.print(f"  [dim]{escape(message)}[/]")

    try:
        with open_app(project, url, log_path=run.server_log, on_status=status) as app:
            on_app_started(app)
            result.app_url = app.url
            term.fields(console, [("App", f"{escape(app.url)} [dim]({app.kind})[/]"), ("Model", escape(result.model))])
            state = await session.signed_in_state(app)
            if session.sign_in_error is not None:
                result.error = f"Could not sign in with the [auth] flow in contexer.toml: {session.sign_in_error}"
            else:
                await _explore_and_replay(result, session, app, state, chat, steps, run, store, save, console)
    except AppStartError as exc:
        result.error = str(exc)
    result.duration_seconds = time.monotonic() - started
    write_test_evidence(result, run)
    return result


async def _explore_and_replay(
    result: ExplorationResult,
    session: VerificationSession,
    app: RunningApp,
    state: Optional[dict[str, Any]],
    chat: BaseChatModel,
    steps: int,
    run: RunDir,
    store: ContractStore,
    save: bool,
    console: Console,
) -> None:
    scale = DEV_SERVER_TIMEOUT_SCALE if app.kind == "dev" else 1.0
    reset = session._reset_before_each(app) if session.reset else None
    existing = [
        criterion.description for contract in store.list() if contract.status == "approved" for criterion in contract.criteria
    ]
    credentials = _typed_values(session.auth.as_check()) if session.auth is not None else []

    browser = BrowserSession(app.url, run_dir=run.path, storage_state=state, reset=reset, timeout_scale=scale)
    try:
        await browser.start()
    except Exception as exc:
        from contexer.observer.browser import browser_problem

        result.error = browser_problem(str(exc)) or f"The app could not be opened in Chromium: {str(exc).splitlines()[0]}"
        return
    try:
        with console.status(f"[dim]The tester is using the app (at most {steps} steps)...[/dim]"):
            tested = await run_tester(
                result.intent, chat, browser, run_dir=run.path, existing_checks=existing, max_steps=steps, secrets=credentials
            )
    finally:
        await browser.close()

    result.steps, result.tool_calls = tested.steps, tested.tool_calls
    result.tokens_in, result.tokens_out, result.cost_usd = tested.tokens_in, tested.tokens_out, tested.cost_usd
    result.tester_status, result.tester_error, result.summary = tested.status, tested.error, tested.summary

    with console.status(f"[dim]Replaying {len(tested.findings)} finding(s) in a fresh browser...[/dim]"):
        report = await replay_findings(
            tested.findings,
            app.url,
            storage_state=state,
            before_each=reset,
            artifacts_dir=run.path / "replay",
            timeout_scale=scale,
        )
    result.bugs = [_confirmed(item) for item in report.bugs]
    result.works = [_confirmed(item) for item in report.works]
    result.unconfirmed = len(report.unconfirmed)
    if report.unconfirmed:
        write_unconfirmed(run.path, report)

    draft = draft_contract(result.intent, report)
    if draft is not None:
        if save:
            draft = draft.model_copy(update={"id": store.unique_id(draft.id)})
            store.save(draft)
            result.contract = draft.id
        import json

        (run.path / DRAFT_FILE).write_text(
            json.dumps(draft.to_file_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    if result.bugs:
        result.outcome = "bugs"
    elif tested.status == "model_error":
        result.outcome = "could_not_test"  # nothing can be said about an app the tester could not finish testing
    else:
        result.outcome = "no_bugs"


def _confirmed(item: Confirmed) -> ConfirmedFinding:
    return ConfirmedFinding(
        title=item.finding.title,
        description=item.finding.description,
        severity=item.finding.severity,
        criterion_id=item.criterion_id,
        check=freeze(item.finding).describe_lines(),
        evidence=item.evidence,
        screenshot=item.screenshot,
    )


def render_test_result(console: Console, result: ExplorationResult) -> None:
    if result.outcome == "error":
        console.print()
        term.note(console, "fail", f"[red]Error:[/] {escape(result.error or 'the app could not be tested')}")
        _footer(console, result)
        return

    if result.bugs:
        count = len(result.bugs)
        term.section(console, f"{count} confirmed bug{'s' if count != 1 else ''}", "each reproduced by replay")
        for bug in result.bugs:
            console.print(f"  {term.mark('fail')} {escape(bug.title)} [dim]· {escape(bug.severity)}[/]")
            for line in bug.check:
                console.print(f"      [dim]{escape(line)}[/]")
            console.print(f"      {escape(bug.evidence)}")
    else:
        console.print()
        if result.outcome == "could_not_test":
            term.note(console, "warn", f"[yellow]Could not test:[/] {escape(result.tester_error)}")
        else:
            term.note(console, "pass", "[green]No confirmed bugs.[/]")

    if result.works:
        count = len(result.works)
        term.section(console, f"{count} working behaviour{'s' if count != 1 else ''} confirmed")
        for works in result.works:
            console.print(f"  {term.mark('pass')} {escape(works.title)}")

    stopped = _STOPPED_EARLY.get(result.tester_status)
    if result.outcome == "bugs" and result.tester_status == "model_error":
        stopped = f"stopped on a model error ({result.tester_error})"
    cost = f"${result.cost_usd:.4f}" if result.cost_usd is not None else "not reported by the provider"
    console.print()
    term.fields(
        console,
        [
            ("Unconfirmed", f"{result.unconfirmed} unconfirmed" + (" [dim](did not reproduce; not shown)[/]" if result.unconfirmed else "")),
            ("Tester", f"{result.steps} steps" + (f" [yellow]· {escape(stopped)}[/]" if stopped else "")),
            ("Cost", escape(cost)),
        ],
    )
    if result.contract:
        term.fields(console, [("Contract", f"{escape(result.contract)} [dim](draft: `contexer contract approve {escape(result.contract)}`)[/]")])
    _footer(console, result)


def _footer(console: Console, result: ExplorationResult) -> None:
    if result.run_dir:
        term.fields(console, [("Report", escape(term.path(Path(result.run_dir) / "report.html")))])
