"""``contexer test``: understand what is meant, test the app like a user, and write the fix prompt.

No coding agent is involved and no application code is changed. One run:

1. the Intent agent turns the goal and every earlier correction into a
   written intent (``.contexer/intent/``), asking only when the goal can be
   read two ways;
2. the Tester uses the app in a real browser against that intent;
3. every finding is replayed by code in a fresh browser, and only the ones
   that reproduce are shown;
4. for confirmed bugs the Diagnoser looks for the cause, and the fix prompt
   is printed and saved for the person to paste into any coding agent.

``--again`` replays the checks saved by the last run first, with no model,
and explores further only when they all pass. ``--correct "..."`` records
what the person meant and tests again.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import shutil
import subprocess
import sys
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlparse

import typer
from rich.console import Console
from rich.markup import escape

from contexer import __version__
from contexer.appserver import AppStartError, RunningApp, open_app
from contexer.browser.freeze import Confirmed, ReplayReport, draft_contract, freeze, replay_findings, write_unconfirmed
from contexer.browser.tools import BrowserSession, credential_secrets
from contexer.checkpoint.lock import RunLocked, run_lock
from contexer.cli import term
from contexer.cli.gate_cli import DirOption, UrlOption
from contexer.contract import ContractStore
from contexer.contract.models import utc_now
from contexer.crew import challenger as challenger_agent
from contexer.crew import diagnoser as diagnoser_agent
from contexer.crew import intent as intent_agent
from contexer.crew.budget import DEFAULT_MAX_TOKENS, Budget, unenforceable
from contexer.crew.challenger import challenge
from contexer.crew.diagnoser import Failure, diagnose, fix_prompt
from contexer.crew.intent import Question, run_intent
from contexer.crew.tester import DEFAULT_MAX_STEPS, run_tester
from contexer.crew.transcript import environment_secrets
from contexer.evidence import RunDir
from contexer.evidence.test_report import (
    AgentUsage,
    ConfirmedFinding,
    Explained,
    ExplorationResult,
    SetAside,
    write_test_evidence,
)
from contexer.gate.session import DEV_SERVER_TIMEOUT_SCALE, VerificationSession
from contexer.intent.store import IntentSpec, IntentStore, SavedCheck
from contexer.llm.base import LLMError
from contexer.skills.store import SkillError, SkillStore
from contexer.verification.runner import CheckRunner
from contexer.verification.verifier import Verifier

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

DRAFT_FILE = "draft-contract.json"
FIX_PROMPT_FILE = "fix-prompt.md"
_FIXED = "Fixed: "
_FIRST_RUN = 'Run `contexer test "what the app should do"` first.'
_STOPPED_EARLY = {
    "step_limit": "stopped at the step limit",
    "timeout": "stopped at the time limit",
    "invalid_output": "ended without a usable summary",
    "budget_exhausted": "stopped at the token budget",
}

Mode = Literal["explore", "again"]
ModelFactory = Callable[[], "BaseChatModel"]
# The agents `contexer test` runs. `[agents.<name>]` in contexer.toml gives each its model and step cap.
TEST_AGENTS = ("intent", "tester", "challenger", "diagnoser")
_OWN_STEPS = {
    "intent": intent_agent.DEFAULT_MAX_STEPS,
    "tester": DEFAULT_MAX_STEPS,
    "challenger": challenger_agent.DEFAULT_MAX_STEPS,
    "diagnoser": diagnoser_agent.DEFAULT_MAX_STEPS,
}


class NoModelError(LLMError):
    """No model is configured for the agents."""


def build_model(project: Path, provider: str | None = None, model: str | None = None) -> BaseChatModel:
    """The chat model the agents run on: ``--provider``/``--model``, else the project's and the user's choice.

    The choice follows the drafting model (``[compiler]`` in contexer.toml,
    then ``contexer setup``, then the first key found). A model known to be
    unable to call tools (the provider lists it so, or ``contexer setup``
    measured it) is refused here, before anything starts.
    """
    from contexer.cli.gate_cli import compiler_llm
    from contexer.config.settings import load_config
    from contexer.llm.capabilities import remember
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
    record = require_tools(choice.spec.id, choice.model, api_key=choice.api_key, base_url=choice.base_url)
    remember(record, choice.base_url)  # `capabilities_of(model)` gives it back to whoever runs an agent on the model
    return chat_model(provider, choice.model, config=config)


def on_app_started(running: RunningApp) -> None:
    """Called once the app is up. A seam for callers that need the running app (tests use it)."""


def is_interactive() -> bool:
    """Whether a person is there to answer a question."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def ask_user(question: str) -> str:
    """Ask one question on the terminal; an empty answer means "you decide"."""
    return str(typer.prompt(question, default="", show_default=False)).strip()


_LOCAL_SUFFIXES = (".localhost", ".test", ".local", ".internal")


def is_local_target(url: str) -> bool:
    """Whether ``url`` is on this machine or a private network: somewhere a Tester may click freely."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not host:
        return False
    if host == "localhost" or host.endswith(_LOCAL_SUFFIXES):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


def copy_to_clipboard(text: str) -> bool:
    """Put ``text`` on the system clipboard; False when no clipboard tool is there or it failed."""
    if sys.platform == "win32":
        commands, data = [["clip"]], text.encode("utf-16-le")
    elif sys.platform == "darwin":
        commands, data = [["pbcopy"]], text.encode("utf-8")
    else:
        commands = [["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]
        data = text.encode("utf-8")
    for command in commands:
        if shutil.which(command[0]) is None:
            continue
        try:
            subprocess.run(command, input=data, check=True, timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False


def test(
    intent: str | None = typer.Argument(None, help="What the app should do, in your words."),
    project_dir: Path = DirOption,
    url: str | None = UrlOption,
    again: bool = typer.Option(False, "--again", help="Replay the checks the last run saved (no model); explore only if they pass."),
    correct: str | None = typer.Option(None, "--correct", help="Record what you meant, then test again with it."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask questions; take the likeliest reading and record it."),
    copy: bool = typer.Option(False, "--copy", help="Put the fix prompt on the clipboard."),
    max_tokens: int | None = typer.Option(
        None, "--max-tokens", min=1, help="The most tokens the agents may use in this run (default: [limits] tokens, else 1,500,000)."
    ),
    no_skills: bool = typer.Option(False, "--no-skills", help="Neither load nor save project skills in this run."),
    allow_remote: bool = typer.Option(
        False, "--allow-remote", help="Test a --url that is not on this machine or a private network."
    ),
    steps: int | None = typer.Option(
        None, "--steps", min=1, help=f"The most model calls the tester may make (default: [agents.tester] max_steps, else {DEFAULT_MAX_STEPS})."
    ),
    model: str | None = typer.Option(
        None, "--model", help="Model id for every agent in this run (default: [agents.<name>] model, else your drafting model)."
    ),
    provider: str | None = typer.Option(None, "--provider", help="Provider for --model, e.g. anthropic, azure, openrouter."),
    save: bool = typer.Option(False, "--save", help="Save the confirmed checks as a draft contract in the project."),
    json_output: bool = typer.Option(False, "--json", help="Print result.json to stdout."),
    open_report: bool = typer.Option(False, "--open", help="Open the HTML report when done."),
) -> None:
    """Test the running app like a user; exit 0 no confirmed bugs, 1 confirmed bugs, 2 could not test, 3 error."""
    from contexer.config.project import load_project_env

    console = Console(stderr=json_output)
    project = project_dir.resolve()
    load_project_env(project)
    if again and correct is not None:
        raise typer.BadParameter("use --again or --correct, not both")
    if not intent and not again and correct is None:
        raise typer.BadParameter('say what the app should do: contexer test "users can add and complete tasks"')

    if url and not allow_remote and not is_local_target(url):
        term.note(
            console,
            "warn",
            f"{escape(url)} is not on this machine or a private network. The tester clicks, types and submits "
            "for real, so it can change or delete data there. Point it at a local or staging copy, or add "
            "--allow-remote if this is one you may test freely.",
        )
        raise typer.Exit(code=2)
    from contexer.config.project import ProjectConfigError, load_project_config

    try:
        config = load_project_config(project)
    except ProjectConfigError as exc:
        term.note(console, "fail", f"[red]Could not test:[/] {escape(str(exc))}")
        raise typer.Exit(code=2) from None
    from contexer.cli.run_cli import run_budget

    # The same budget `contexer run` builds: the token limit, [agents] max_usd and the rates. The flag wins.
    budget = run_budget(config)
    if max_tokens:
        budget.max_tokens = max_tokens
    agent_steps = {name: cap for name in TEST_AGENTS if (cap := config.agents.for_agent(name).max_steps)}
    if steps is not None:
        agent_steps["tester"] = steps  # the flag wins

    store = IntentStore(project)
    stored = store.find(intent) if intent else store.latest()
    if again or correct is not None:
        if stored is None:
            what = "Nothing to run again" if again else "There is no intent to correct yet"
            term.note(console, "warn", f"{what}: this project has no saved intent. {escape(_FIRST_RUN)}")
            raise typer.Exit(code=2)
        if again and not [c for c in store.load_checks(stored.id) if c.source == "confirmed"]:
            term.note(console, "warn", f"Nothing to run again: no run has saved a confirmed check yet. {escape(_FIRST_RUN)}")
            raise typer.Exit(code=2)
    goal = stored.goal if stored is not None and (again or correct is not None) else str(intent)
    term.header(console, "test", goal)

    cached: list[Any] = []
    named: list[dict[str, Any]] = []

    def model_factory() -> BaseChatModel:
        if not cached:
            cached.append(build_model(project, provider, model))
        return cached[0]

    def agent_models() -> dict[str, BaseChatModel]:
        """The models contexer.toml names per agent. A model named on the command line is for every agent."""
        if not named:
            from contexer.cli.run_cli import crew_models

            flagged = bool(model or provider)
            named.append({} if flagged else crew_models(project, config, default_provider=config.compiler.provider, agents=TEST_AGENTS))
        return named[0]

    dollar_limit = budget.max_total_usd is not None or budget.max_cost_usd is not None
    if not again or dollar_limit:  # --again needs no model unless the saved checks pass; a dollar limit is checked either way
        called: list[Any] = []
        try:
            default, chosen = model_factory(), agent_models()
            called = [chosen.get(name) or default for name in TEST_AGENTS]
        except (LLMError, ValueError) as exc:
            if not again:  # with --again a model that cannot be built is an error only once it is needed
                term.note(console, "fail", f"[red]Could not test:[/] {escape(str(exc))}")
                raise typer.Exit(code=2) from None
        # Before anything is spent: a dollar limit that would count unknown spend as 0 is refused, not ignored.
        cannot_keep = unenforceable(budget, models=called)
        if cannot_keep:
            term.note(console, "fail", escape(cannot_keep))
            raise typer.Exit(code=2)

    try:
        # The tester starts the app and may reset it; a run doing the same in this folder would trip over it.
        with run_lock(project, "contexer test"):
            result = asyncio.run(
                run_test(
                    project,
                    goal,
                    model_factory,
                    url=url,
                    save=save,
                    console=console,
                    mode="again" if again else "explore",
                    correction=correct,
                    assume=yes or not is_interactive(),
                    stored=stored,
                    budget=budget,
                    use_skills=not no_skills,
                    agent_models=agent_models,
                    agent_steps=agent_steps,
                )
            )
    except RunLocked as exc:
        term.note(console, "fail", f"[red]Not started:[/] {escape(str(exc))}")
        raise typer.Exit(code=2) from None
    except KeyboardInterrupt:
        _quiet_interrupted_shutdown()
        console.print()
        term.note(console, "warn", "Stopped. The browser and the app were closed; nothing in the project was changed.")
        raise typer.Exit(code=130) from None

    render_test_result(console, result, cost_estimated=budget.estimated)
    if copy and result.fix_prompt:
        if copy_to_clipboard(Path(result.fix_prompt).read_text(encoding="utf-8")):
            term.note(console, "pass", "The fix prompt was copied to the clipboard.")
        else:
            term.note(console, "warn", f"The fix prompt could not be copied; it is in {escape(term.path(result.fix_prompt))}.")
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
    goal: str,
    model_factory: ModelFactory,
    *,
    url: str | None = None,
    steps: int | None = None,
    save: bool = False,
    console: Console | None = None,
    mode: Mode = "explore",
    correction: str | None = None,
    assume: bool = True,
    stored: IntentSpec | None = None,
    budget: Budget | None = None,
    use_skills: bool = True,
    agent_models: Callable[[], dict[str, BaseChatModel]] | None = None,
    agent_steps: dict[str, int] | None = None,
) -> ExplorationResult:
    """Start the app, sign in, and run one ``contexer test``; the evidence is written whatever happens.

    ``agent_models`` and ``agent_steps`` are what ``[agents.<name>]`` gives an agent by name; an agent
    with neither runs on ``model_factory``'s model with its own step cap. ``steps`` is the Tester's cap.
    """
    caps = dict(agent_steps or {})
    if steps is not None:
        caps["tester"] = steps
    console = console or Console()
    started = time.monotonic()
    run = RunDir.create(project)
    result = ExplorationResult(
        intent=goal,
        outcome="error",
        project_dir=str(project),
        run_id=run.run_id,
        run_dir=str(run.path),
        started_at=utc_now(),
        contexer_version=__version__,
    )
    session = VerificationSession(project, run, verifier=Verifier(llm_provider=None, runner=CheckRunner()))

    def status(message: str) -> None:
        console.print(f"  [dim]{escape(message)}[/]")

    try:
        with open_app(project, url, log_path=run.server_log, on_status=status) as app:
            on_app_started(app)
            result.app_url = app.url
            term.fields(console, [("App", f"{escape(app.url)} [dim]({app.kind})[/]")])
            state = await session.signed_in_state(app)
            if session.sign_in_error is not None:
                result.error = f"Could not sign in with the [auth] flow in contexer.toml: {session.sign_in_error}"
            else:
                job = _Job(project, run, session, app, state, console, result, budget or Budget(DEFAULT_MAX_TOKENS), use_skills)
                job.agent_models, job.agent_steps = agent_models, caps
                await job.run(goal, model_factory, save=save, mode=mode, correction=correction, assume=assume, stored=stored)
    except AppStartError as exc:
        result.error = str(exc)
    result.duration_seconds = time.monotonic() - started
    write_test_evidence(result, run)
    return result


class _Job:
    """One ``contexer test`` on a running, signed-in app."""

    def __init__(
        self,
        project: Path,
        run: RunDir,
        session: VerificationSession,
        app: RunningApp,
        state: dict[str, Any] | None,
        console: Console,
        result: ExplorationResult,
        budget: Budget,
        use_skills: bool = True,
    ) -> None:
        self.project, self.run_dir, self.session, self.app, self.state = project, run, session, app, state
        self.budget, self.use_skills = budget, use_skills
        result.budget_tokens = budget.max_tokens
        self.console, self.result = console, result
        self.scale = DEV_SERVER_TIMEOUT_SCALE if app.kind == "dev" else 1.0
        self.reset = session.reset_before_each(app)
        self.credentials = credential_secrets(session.auth.as_check()) if session.auth is not None else []
        self.intents = IntentStore(project)
        self.contracts = ContractStore(project)
        # What [agents.<name>] gives an agent: its own model (built when first needed) and its step cap.
        self.agent_models: Callable[[], dict[str, BaseChatModel]] | None = None
        self.agent_steps: dict[str, int] = {}
        self.models: dict[str, BaseChatModel] = {}

    def _cap(self, agent: str) -> int:
        """The step cap the project set for an agent, or the agent's own."""
        return self.agent_steps.get(agent) or _OWN_STEPS[agent]

    async def run(
        self,
        goal: str,
        model_factory: ModelFactory,
        *,
        save: bool,
        mode: Mode,
        correction: str | None,
        assume: bool,
        stored: IntentSpec | None,
    ) -> None:
        result = self.result
        spec = stored or IntentSpec(id=self.intents.id_for(goal), goal=goal)
        checks = self.intents.load_checks(spec.id)
        result.intent_id = spec.id

        carried_works: list[ConfirmedFinding] = []
        if mode == "again":
            checks, carried_works, failures = await self._replay_saved(checks)
            self.intents.save_checks(spec.id, checks)
            if failures:
                result.outcome = "bugs"
                self._write_fix_prompt(failures, None, spec, [w.title for w in carried_works])
                return

        try:
            chat = model_factory()
            self.models = self.agent_models() if self.agent_models is not None else {}
        except (LLMError, ValueError) as exc:
            result.works, result.outcome, result.tester_error = carried_works, "could_not_test", str(exc)
            return
        from contexer.llm.chat import describe_model

        models = self.models
        steps = self.agent_steps.get("tester", DEFAULT_MAX_STEPS)
        result.model = describe_model(chat)
        own = [f"{name} on {describe_model(models[name])}" for name in TEST_AGENTS if name in models]
        term.fields(self.console, [("Model", escape(result.model) + (f" [dim]· {escape(', '.join(own))}[/]" if own else ""))])

        browser = BrowserSession(
            self.app.url, run_dir=self.run_dir.path, storage_state=self.state, reset=self.reset, timeout_scale=self.scale
        )
        try:
            await browser.start()
        except Exception as exc:
            from contexer.observer.browser import browser_problem

            result.error = browser_problem(str(exc)) or f"The app could not be opened in Chromium: {str(exc).splitlines()[0]}"
            return
        try:
            if mode == "explore":
                intent_model = models.get("intent") or chat
                spec, checks = await self._understand(spec, checks, intent_model, await browser.snapshot(), correction, assume)
            self.intents.save(spec)
            self.intents.save_checks(spec.id, checks)
            skills = SkillStore(self.project).matching(spec.as_text()) if self.use_skills else []
            existing = [
                criterion.description
                for contract in self.contracts.list()
                if contract.status == "approved"
                for criterion in contract.criteria
            ]
            existing += [c.description for c in checks if c.source == "confirmed"]
            with self.console.status(f"[dim]The tester is using the app (at most {steps} steps)...[/dim]"):
                tested = await run_tester(
                    spec.as_text(),
                    models.get("tester") or chat,
                    browser,
                    run_dir=self.run_dir.path,
                    existing_checks=list(dict.fromkeys(existing)),
                    skills=skills,
                    max_steps=steps,
                    secrets=self.credentials,
                    budget=self.budget,
                )
            secrets = [*self.credentials, *browser.secrets, *environment_secrets()]
        finally:
            await browser.close()

        result.steps, result.tool_calls = tested.steps, tested.tool_calls
        self._spent("tester", tested.steps, tested.tokens_in, tested.tokens_out, tested.cost_usd)
        result.tester_status, result.tester_error, result.summary = tested.status, tested.error, tested.summary
        result.questions = tested.questions

        with self.console.status(f"[dim]Replaying {len(tested.findings)} finding(s) in a fresh browser...[/dim]"):
            report = await replay_findings(
                tested.findings,
                self.app.url,
                storage_state=self.state,
                before_each=self.reset,
                artifacts_dir=self.run_dir.path / "replay",
                timeout_scale=self.scale,
            )
        # Decided by code, with no model: a check that failed while the app was showing its own message is not
        # asserted as a bug. The app most likely refused on purpose and said so; a person sees it with the message.
        result.explained = [
            Explained(title=item.finding.title, messages=item.finding.messages) for item in report.bugs if item.finding.messages
        ]
        report.bugs = [item for item in report.bugs if not item.finding.messages]
        if report.bugs:
            # Replay shows that a bug's steps end badly, not why. A second look sets aside the ones that are the
            # tester's doing; it can only remove, and what it removes is shown with the reason.
            with self.console.status("[dim]Challenging the confirmed bugs...[/dim]"):
                challenged = await challenge(
                    report.bugs,
                    spec.as_text(),
                    models.get("challenger") or chat,
                    run_dir=self.run_dir.path,
                    budget=self.budget,
                    secrets=secrets,
                    max_steps=self._cap("challenger"),
                )
            if challenged.status != "skipped":
                self._spent("challenger", challenged.steps, challenged.tokens_in, challenged.tokens_out, challenged.cost_usd)
            report.bugs = challenged.standing
            result.set_aside = [SetAside(title=item.finding.title, reason=reason) for item, reason in challenged.set_aside]
        result.bugs = [_confirmed(item) for item in report.bugs]
        result.works = [*carried_works, *[_confirmed(item) for item in report.works]]
        result.unconfirmed = len(report.unconfirmed)
        if report.unconfirmed:
            write_unconfirmed(self.run_dir.path, report)
        self.intents.save_checks(spec.id, _with_confirmed(checks, report))
        self._save_draft(spec.goal, report, save)
        if self.use_skills:
            self._save_skills(tested.skills, secrets)

        if result.bugs:
            result.outcome = "bugs"
            failures = [Failure.from_confirmed(item) for item in report.bugs]
            if self.budget.exhausted():  # nothing left for a diagnosis: the facts alone make the prompt
                self._write_fix_prompt(failures, None, spec, [w.title for w in result.works])
                return
            with self.console.status("[dim]Looking for the cause in the code...[/dim]"):
                diagnosis = await diagnose(
                    failures,
                    models.get("diagnoser") or chat,
                    self.project,
                    intent=spec.as_text(),
                    diff=_git_diff(self.project),
                    server_log=self.app.log_tail(),
                    run_dir=self.run_dir.path,
                    secrets=secrets,
                    budget=self.budget,
                    max_steps=self._cap("diagnoser"),
                )
            self._spent("diagnoser", diagnosis.steps, diagnosis.tokens_in, diagnosis.tokens_out, diagnosis.cost_usd)
            self._write_fix_prompt(failures, diagnosis.brief, spec, [w.title for w in result.works])
        elif tested.status == "model_error":
            result.outcome = "could_not_test"  # nothing can be said about an app the tester could not finish testing
        else:
            result.outcome = "no_bugs"

    # -- steps ----------------------------------------------------------------

    async def _replay_saved(
        self, checks: list[SavedCheck]
    ) -> tuple[list[SavedCheck], list[ConfirmedFinding], list[Failure]]:
        """Replay the confirmed checks of the last run. No model is involved."""
        saved = [c for c in checks if c.source == "confirmed"]
        with self.console.status(f"[dim]Replaying {len(saved)} saved check(s) in a fresh browser...[/dim]"):
            results = await CheckRunner().run(
                self.app.url,
                [(c.id, c.check) for c in saved],
                artifacts_dir=self.run_dir.path / "replay",
                storage_state=self.state,
                before_each=self.reset,
                timeout_scale=self.scale,
            )
        by_id = {c.id: r for c, r in zip(saved, results)}
        updated = [_after_replay(c, by_id[c.id].passed) if c.id in by_id else c for c in checks]
        saved = [c for c in updated if c.id in by_id]
        works: list[ConfirmedFinding] = []
        failures: list[Failure] = []
        for check, outcome in zip(saved, results):
            finding = ConfirmedFinding(
                title=check.description,
                criterion_id=check.id,
                check=check.check.describe_lines(),
                evidence=outcome.summary(),
                screenshot=outcome.screenshot,
            )
            if outcome.passed:
                works.append(finding)
            else:
                self.result.bugs.append(finding)
                failures.append(Failure(title=check.description, check=check.check, result=outcome))
        self.result.works = works
        self.result.replayed, self.result.still_failing = len(saved), len(failures)
        return updated, works, failures

    async def _understand(
        self,
        spec: IntentSpec,
        checks: list[SavedCheck],
        chat: BaseChatModel,
        snapshot: str,
        correction: str | None,
        assume: bool,
    ) -> tuple[IntentSpec, list[SavedCheck]]:
        """Run the Intent agent; ask its questions once when a person is there to answer."""
        from contexer.workflow.inspector import RepositoryInspector

        context = self.app.repo_context or RepositoryInspector().inspect(self.project)
        summary = context.format_summary()
        known = set(spec.assumptions)
        written = list(spec.behaviours)
        with self.console.status("[dim]Reading the goal...[/dim]"):
            first = await run_intent(
                spec.goal,
                chat,
                stored=spec,
                existing_checks=checks,
                correction=correction,
                repo_summary=summary,
                ui_snapshot=snapshot,
                assume=assume,
                run_dir=self.run_dir.path,
                budget=self.budget,
                secrets=self.credentials,
                max_steps=self._cap("intent"),
            )
        self._spent("intent", first.steps, first.tokens_in, first.tokens_out, first.cost_usd)
        spec, checks, dropped = first.spec, first.checks, list(first.dropped)
        if first.status != "ok":
            term.note(
                self.console,
                "warn",
                f"The intent could not be refined ({escape(first.error)}); testing against what is written.",
            )
        if first.questions:
            spec = self._ask(spec, first.questions)
            with self.console.status("[dim]Updating the intent with your answers...[/dim]"):
                second = await run_intent(
                    spec.goal,
                    chat,
                    stored=spec,
                    existing_checks=checks,
                    repo_summary=summary,
                    ui_snapshot=snapshot,
                    run_dir=self.run_dir.path,
                    budget=self.budget,
                    secrets=self.credentials,
                    max_steps=self._cap("intent"),
                )
            self._spent("intent", second.steps, second.tokens_in, second.tokens_out, second.cost_usd)
            # Asked once: whatever the agent would ask now is left for `--correct`.
            spec, checks, dropped = second.spec, second.checks, dropped + list(second.dropped)

        changed = [b for b in spec.behaviours if b not in written]
        if changed:
            # Shown every time: the intent decides what gets tested, and a page can try to steer what is written.
            term.section(self.console, "Intent changed", "added or rewritten in this run; edit the file to undo")
            term.bullets(self.console, [escape(b) for b in changed])
        assumed = [a for a in spec.assumptions if a not in known]
        if assumed:
            term.section(self.console, "Assumptions", "taken without asking; correct one with --correct")
            term.bullets(self.console, [escape(a) for a in assumed])
        if dropped:
            term.note(self.console, "warn", f"{len(dropped)} draft check(s) were not valid and were dropped.")
        self.result.dropped_checks = [f"{check_id}: {why}" for check_id, why in dropped]
        return spec, checks

    def _ask(self, spec: IntentSpec, questions: list[Question]) -> IntentSpec:
        term.section(self.console, "Before testing", "the goal can be read two ways")
        for question in questions:
            answer = ask_user(
                f"{question.question}\n  1) {question.reading_a}\n  2) {question.reading_b}\n"
                "Answer in your own words (Enter takes 1)"
            )
            if answer in ("1", ""):
                spec = spec.model_copy(
                    update={
                        "assumptions": [
                            *spec.assumptions,
                            f"{question.reading_a} (assumed without asking; the other reading was: {question.reading_b})"
                            if answer == ""
                            else f"{question.reading_a} (your answer to: {question.question})",
                        ]
                    }
                )
            else:
                spec = spec.with_correction(f"{question.question} {question.reading_b if answer == '2' else answer}")
        return spec

    def _save_draft(self, goal: str, report: ReplayReport, save: bool) -> None:
        draft = draft_contract(goal, report)
        if draft is None:
            return
        if save:
            draft = draft.model_copy(update={"id": self.contracts.unique_id(draft.id)})
            self.contracts.save(draft)
            self.result.contract = draft.id
        (self.run_dir.path / DRAFT_FILE).write_text(
            json.dumps(draft.to_file_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    def _save_skills(self, proposed: list[Any], secrets: list[str]) -> None:
        """Keep what the Tester learned about operating the app. A skill with a secret in it is refused."""
        store = SkillStore(self.project)
        for skill in proposed:
            try:
                store.save(skill, secrets=secrets)
            except SkillError as exc:
                self.result.skills_rejected.append(str(exc))
            else:
                self.result.skills_saved.append(skill.name)

    def _write_fix_prompt(self, failures: list[Failure], brief: Any, spec: IntentSpec, working: list[str]) -> None:
        text = fix_prompt(failures, brief, intent=spec.as_text(), working=working)
        path = self.run_dir.path / FIX_PROMPT_FILE
        path.write_text(text, encoding="utf-8", newline="\n")
        self.result.fix_prompt = str(path)

    def _spent(self, agent: str, steps: int, tokens_in: int, tokens_out: int, cost: float | None) -> None:
        usage = next((a for a in self.result.agents if a.agent == agent), None)
        if usage is None:
            usage = AgentUsage(agent=agent)
            self.result.agents.append(usage)
        usage.steps += steps
        usage.tokens_in += tokens_in
        usage.tokens_out += tokens_out
        if cost is not None:
            usage.cost_usd = (usage.cost_usd or 0.0) + cost
        self.result.tokens_in += tokens_in
        self.result.tokens_out += tokens_out
        if cost is not None:
            self.result.cost_usd = (self.result.cost_usd or 0.0) + cost


def _after_replay(check: SavedCheck, passed: bool) -> SavedCheck:
    """A saved check with its kind brought up to date. One that failed and now passes is titled as fixed."""
    if not passed:
        return check.model_copy(update={"kind": "bug", "description": check.description.removeprefix(_FIXED)})
    description = check.description
    if check.kind == "bug" and not description.startswith(_FIXED):
        description = f"{_FIXED}{description}"
    return check.model_copy(update={"kind": "works", "description": description})


def _with_confirmed(checks: list[SavedCheck], report: ReplayReport) -> list[SavedCheck]:
    """The feature's checks with this run's confirmed ones added; a check with the same id is replaced."""
    def saved(item: Confirmed, kind: Literal["bug", "works"]) -> SavedCheck:
        return SavedCheck(
            id=item.criterion_id, description=item.finding.title, check=item.check, source="confirmed", kind=kind
        )

    confirmed = [*(saved(item, "bug") for item in report.bugs), *(saved(item, "works") for item in report.works)]
    new_ids = {c.id for c in confirmed}
    return [*[c for c in checks if c.id not in new_ids], *confirmed]


def _git_diff(project: Path) -> str:
    """Uncommitted changes to tracked files, when the project is a git checkout; otherwise nothing."""
    if not (project / ".git").exists() or shutil.which("git") is None:
        return ""
    try:
        done = subprocess.run(
            ["git", "diff", "--no-color", "--stat", "--patch", "--", "."],
            cwd=str(project),
            capture_output=True,
            timeout=20,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.decode("utf-8", errors="replace") if done.returncode == 0 else ""


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


def render_test_result(console: Console, result: ExplorationResult, *, cost_estimated: bool = False) -> None:
    if result.outcome == "error":
        console.print()
        term.note(console, "fail", f"[red]Error:[/] {escape(result.error or 'the app could not be tested')}")
        _footer(console, result)
        return

    if result.replayed:
        console.print()
        if result.still_failing:
            term.note(
                console,
                "fail",
                f"[red]{result.still_failing} of {result.replayed} saved check{'s' if result.replayed != 1 else ''} "
                "still failing.[/] Nothing new was explored, and no model was used.",
            )
        else:
            term.note(console, "pass", f"[green]{result.replayed} saved check{'s' if result.replayed != 1 else ''} pass.[/]")

    if result.bugs:
        count = len(result.bugs)
        title = f"{count} confirmed bug{'s' if count != 1 else ''}"
        term.section(console, title, "replayed just now" if result.still_failing else "each reproduced by replay")
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

    if result.explained:
        count = len(result.explained)
        term.section(
            console,
            f"{count} finding{'s' if count != 1 else ''} where the app said why",
            "reproduced, but the app was showing a message; not reported as bugs unless the message is wrong",
        )
        for explained in result.explained:
            console.print(f"  {term.mark('open')} {escape(explained.title)}")
            console.print(f"      [dim]the app showed: {escape('; '.join(explained.messages))}[/]")

    if result.set_aside:
        count = len(result.set_aside)
        term.section(
            console,
            f"{count} finding{'s' if count != 1 else ''} set aside",
            "reproduced, but judged to be the tester's doing; say so if one is a real bug",
        )
        for item in result.set_aside:
            console.print(f"  {term.mark('open')} {escape(item.title)}")
            console.print(f"      [dim]{escape(item.reason)}[/]")

    if result.questions:
        term.section(console, "Not settled by the intent", "questions for you, not bugs; answer one with --correct")
        term.bullets(console, [escape(q) for q in result.questions])

    if result.fix_prompt:
        term.section(console, "Fix prompt", "paste it into your coding agent, then run `contexer test --again`")
        console.print()
        console.print(escape(Path(result.fix_prompt).read_text(encoding="utf-8").rstrip()), soft_wrap=True, highlight=False)

    stopped = _STOPPED_EARLY.get(result.tester_status)
    if result.outcome == "bugs" and result.tester_status == "model_error":
        stopped = f"stopped on a model error ({result.tester_error})"
    if result.tester_status == "budget_exhausted" and "token budget" not in result.tester_error:
        stopped = "stopped at the dollar budget"  # [agents] max_usd or [limits] cost_usd, not the token limit
    if result.cost_usd is None:
        cost = "unknown (the provider reports none, and no price is known for the model)"
    else:
        cost = f"${result.cost_usd:.4f}" + (" estimated from token counts and prices per token" if cost_estimated else "")
    rows = []
    if not result.still_failing:
        unconfirmed = f"{result.unconfirmed} unconfirmed" + (" [dim](did not reproduce; not shown)[/]" if result.unconfirmed else "")
        rows += [
            ("Unconfirmed", unconfirmed),
            ("Tester", f"{result.steps} steps" + (f" [yellow]· {escape(stopped)}[/]" if stopped else "")),
            ("Cost", escape(cost)),
        ]
    skills = []
    if result.skills_saved:
        count = len(result.skills_saved)
        skills.append(f"{count} skill{'s' if count != 1 else ''} saved ({escape(', '.join(result.skills_saved))})")
    if result.skills_rejected:
        count = len(result.skills_rejected)
        skills.append(f"[yellow]{count} skill{'s' if count != 1 else ''} rejected: it contained a secret[/]")
    if skills:
        rows.append(("Skills", " · ".join(skills)))
    if result.intent_id:
        rows.append(("Intent", escape(term.path(IntentStore(result.project_dir).path_for(result.intent_id)))))
    if result.fix_prompt:
        rows.append(("Fix prompt", escape(term.path(result.fix_prompt))))
    if result.contract:
        rows.append(("Contract", f"{escape(result.contract)} [dim](draft: `contexer contract approve {escape(result.contract)}`)[/]"))
    console.print()
    term.fields(console, rows)
    _footer(console, result)


def _footer(console: Console, result: ExplorationResult) -> None:
    if result.run_dir:
        term.fields(console, [("Report", escape(term.path(Path(result.run_dir) / "report.html")))])
