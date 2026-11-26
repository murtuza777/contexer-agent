"""``contexer run``: approve what "done" means, then let Contexer drive the agent to it."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import webbrowser
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from typing import Any, NoReturn

import typer
from rich.console import Console
from rich.markup import escape

from contexer.agents import CodingAgentAdapter, create_agent
from contexer.appserver import AppStartError, open_app
from contexer.checkpoint.lock import RunLocked, run_lock
from contexer.checkpoint.shadow import SnapshotError, unsafe_work_tree
from contexer.cli import term
from contexer.cli.gate_cli import (
    compiler_llm,
    preview_draft,
    print_checklist,
    print_draft_preview,
    print_drafted_by,
    warn_if_weak_draft,
)
from contexer.cli.runview import RunView
from contexer.config.project import (
    CREW_AGENTS,
    AgentSettings,
    ProjectConfig,
    ProjectConfigError,
    load_project_config,
    load_project_env,
)
from contexer.contract import Contract, ContractError, ContractStore
from contexer.contract.store import AUTOMATIC_APPROVAL
from contexer.controller import RunOutcome, RunSettings
from contexer.crew.budget import DEFAULT_MAX_TOKENS, Budget
from contexer.crew.estimate import RunEstimate, estimate_run
from contexer.evidence import RunDir
from contexer.gate import RunResult
from contexer.gate.session import VerificationSession
from contexer.github.api import GitHubClient, GitHubError, github_token
from contexer.github.handoff import Handoff, HandoffError, HandoffPlan, hand_off, plan_handoff
from contexer.github.issues import ISSUE_ORIGIN, visible_text
from contexer.github.issues import issue_goal as shown_issue_goal
from contexer.graph import GraphController, ResumeError
from contexer.graph.context import RunEvent
from contexer.llm import discovery
from contexer.riskscan import scan_project
from contexer.workflow.criteria import GoalAnalyzer


def run(
    goal: str | None = typer.Argument(None, help="What should be true when the work is done."),
    contract_id: str | None = typer.Option(None, "--contract", "-c", help="Run an existing contract instead."),
    project_dir: Path = typer.Option(Path("."), "--dir", "-d", help="Project directory.", file_okay=False),
    url: str | None = typer.Option(None, "--url", "-u", help="Use an app you already run."),
    agent_name: str | None = typer.Option(None, "--agent", help="claude-code (default), codex or opencode."),
    model: str | None = typer.Option(None, "--model", help="Model for the coding agent."),
    rounds: int | None = typer.Option(None, "--rounds", min=0, help="Maximum repair rounds (default 2)."),
    budget: float | None = typer.Option(None, "--budget", help="Stop when the agent has spent this many USD."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Approve the checklist without asking."),
    no_replay: bool = typer.Option(False, "--no-replay", help="Skip re-checking other approved contracts."),
    open_report: bool = typer.Option(False, "--open", help="Open the HTML report when done."),
    json_output: bool = typer.Option(
        False, "--json", help="Print the run as one JSON event per line and nothing else (needs --yes). For CI and other tools."
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Keep every tool call of the coding agent in the output."),
    pr: bool = typer.Option(
        False, "--pr", help="Commit the result to a new branch and open a pull request with the evidence."
    ),
    issue: int | None = typer.Option(
        None, "--issue", min=1, help="Take the goal from this GitHub issue; the pull request closes it."
    ),
    engine: str | None = typer.Option(None, "--engine", hidden=True, help="Removed in 0.5.0: there is one run loop."),
    resume: str | None = typer.Option(
        None, "--resume", metavar="RUN", help="Continue a run that was stopped."
    ),
    max_usd: float | None = typer.Option(
        None,
        "--max-usd",
        min=0.01,
        help="One budget in USD for the coding agent and Contexer's agents together.",
    ),
    no_review: bool = typer.Option(
        False, "--no-review", help="Do not read the diff of a passing run before it ends."
    ),
    no_plan: bool = typer.Option(
        False, "--no-plan", help="Do not read the project for a brief before the first coding turn."
    ),
    correct: str | None = typer.Option(
        None, "--correct", help="With --resume: a correction to what done means, applied first."
    ),
) -> None:
    """Turn a goal into approved checks, have a coding agent build it, prove it, and repair until it passes."""
    if sum((bool(goal), bool(contract_id), issue is not None, bool(resume))) != 1:
        raise typer.BadParameter("give a GOAL, --contract ID, --issue N or --resume RUN")
    one_engine(engine)
    if correct and not resume:
        raise typer.BadParameter("--correct goes with --resume RUN: it corrects a run that was stopped")
    if json_output and not (yes or resume):
        raise typer.BadParameter("--json cannot stop to ask for an approval: add --yes, or approve the contract first")
    console = Console(quiet=True) if json_output else Console()
    project = project_dir.resolve()
    if shutil.which("git") is None:
        raise typer.BadParameter("git is not installed. Contexer snapshots your project with git before an agent touches it.")
    unsafe = unsafe_work_tree(project)
    if unsafe:
        raise typer.BadParameter(f"{unsafe}; run Contexer in your app's folder, or pass --dir")
    for risk in scan_project(project):  # before anything is spent; a warning, never a refusal
        term.note(console, "warn", escape(risk.message))
    pr = pr or issue is not None  # work on an issue ends in a pull request that closes it
    handoff_plan: HandoffPlan | None = None
    if pr:
        try:
            handoff_plan = plan_handoff(project)  # before anything is spent
        except HandoffError as exc:
            console.print(f"[red]Cannot open a pull request:[/] {escape(str(exc))}")
            raise typer.Exit(code=3) from exc
    load_project_env(project)  # model keys for the drafting model and the coding agent
    try:
        config = load_project_config(project)
    except ProjectConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc
    store = ContractStore(project)
    try:
        agent = create_agent(*choose_agent(config.agent, agent_name, model))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    settings = RunSettings(
        max_repair_rounds=rounds if rounds is not None else config.agent.max_repair_rounds,
        budget_usd=budget if budget is not None else config.agent.budget_usd,
        turn_timeout=config.agent.turn_timeout,
        judged_policy=config.gate.judged,
        replay_others=not no_replay,
        review=not no_review,
        plan=not no_plan,
        agent_steps={name: cap for name in CREW_AGENTS if (cap := config.agents.for_agent(name).max_steps)},
    )
    crew_budget = run_budget(config, max_usd)
    model_for_crew = crew_model(
        project,
        on_refused=lambda why: term.note(
            console, "warn", f"{escape(why)} Contexer's own agents are off for this run, and fixed rules decide each next step."
        ),
    )
    try:  # before anything is spent: a model the project names and Contexer cannot build
        models_for_crew = (
            crew_models(project, config, default_provider=config.compiler.provider, agents=RUN_AGENTS)
            if model_for_crew is not None
            else {}
        )
    except AgentSettingError as exc:
        raise typer.BadParameter(str(exc)) from exc
    draft_id: str | None = None
    contract: Contract | None = None
    graph_preview: RunResult | None = None
    graph_analyzer: GoalAnalyzer | None = None
    if issue is not None:
        goal, draft_id = issue_goal(console, handoff_plan, issue, store)
    if contract_id:
        try:
            contract = store.load(contract_id)
        except ContractError as exc:
            raise typer.BadParameter(str(exc)) from exc
    elif goal and model_for_crew is None:
        # No model for the Intent agent: the checks are drafted the 0.4 way, and approved before the run.
        drafting = compiler_llm(project)
        check_free_quota(console, drafting, agent, yes)
        contract, graph_preview, graph_analyzer = _draft(console, project, store, goal, url, drafting, draft_id)
        contract = _from_issue(store, contract, issue)
    if model_for_crew is not None:
        # The estimate's count of model calls, against what is left of a free daily allowance.
        ceiling = _estimate(settings, crew_budget, True, contract is None and not resume).model_calls
        check_free_quota(console, None, agent, yes, crew=model_for_crew, needed=ceiling)
    if contract is not None and contract.status != "approved":
        contract = _approve(console, store, contract, yes, graph_preview, graph_analyzer)
    outcome = execute_graph(
        console,
        project,
        agent,
        store,
        settings,
        url,
        model=model_for_crew,
        models=models_for_crew,
        budget=crew_budget,
        yes=yes,
        contract=contract,
        goal=goal,
        contract_id=draft_id,
        resume=resume,
        correction=correct,
        origin=ISSUE_ORIGIN.format(number=issue) if issue is not None else "",
        json_output=json_output,
        verbose=verbose,
    )
    final = store.load(outcome.contract_id) if outcome.contract_id and store.exists(outcome.contract_id) else None
    _finish(console, outcome, final, handoff_plan, pr, issue, open_report, json_output)


def _finish(
    console: Console,
    outcome: RunOutcome,
    contract: Contract | None,
    handoff_plan: HandoffPlan | None,
    pr: bool,
    issue: int | None,
    open_report: bool,
    json_output: bool = False,
) -> None:
    """Hand the result off if asked, print it, and exit with the outcome's code."""
    handoff: Handoff | None = None
    handoff_error: str | None = None
    if handoff_plan is not None and contract is not None and outcome.terminal not in _NO_HANDOFF:
        with console.status("[dim]Committing the work to a branch and opening a pull request...[/dim]"):
            try:
                handoff = hand_off(handoff_plan, outcome, contract, issue=issue)
            except HandoffError as exc:
                handoff_error = str(exc)
    _render(console, outcome, handoff, handoff_error, pr)
    if json_output:
        emit_json(
            {
                "event": "end",
                "at": round(outcome.duration_seconds, 2),
                "run_id": outcome.run_id,
                "terminal": outcome.terminal,
                "reason": outcome.reason,
                "exit_code": outcome.exit_code,
                "attempts": len(outcome.attempts),
                "best_attempt": outcome.best_attempt,
                "cost_usd": outcome.cost_usd,
                "crew_cost_usd": outcome.crew_cost_usd,
                "review_notes": len(outcome.review),
                "report": str(Path(outcome.run_dir, "report.html")),
                "pull_request": handoff.url if handoff is not None else None,
                "draft": handoff.draft if handoff is not None else None,
                "handoff_note": (handoff.note.strip() if handoff is not None else handoff_error) or None,
            }
        )
    if open_report:
        webbrowser.open(Path(outcome.run_dir, "report.html").resolve().as_uri())
    raise typer.Exit(code=outcome.exit_code)


def _from_issue(store: ContractStore, contract: Contract, issue: int | None) -> Contract:
    """A contract drafted from an issue says so, so its goal is quoted as data in every prompt."""
    if issue is None:
        return contract
    marked = contract.model_copy(update={"origin": ISSUE_ORIGIN.format(number=issue)})
    store.save(marked)
    return marked


def one_engine(flag: str | None) -> None:
    """Until 0.5.0 ``--engine`` and ``CONTEXER_ENGINE`` chose between two loops. Naming the one that is left still works."""
    for source, name in (("--engine", flag), ("CONTEXER_ENGINE", os.environ.get("CONTEXER_ENGINE"))):
        if name and name.strip().lower() != "graph":
            raise typer.BadParameter(
                f"{source} is '{name.strip()}'. The classic engine was removed in 0.5.0 and there is one run loop now: drop {source}."
            )


def crew_model(project: Path, on_refused: Callable[[str], None] | None = None) -> Any:
    """The model for Contexer's own agents (Intent, Triage, Diagnoser), or None when none is configured or usable.

    A model that is configured and cannot call tools is refused, and ``on_refused`` is told why:
    without that the run went on under rules and nothing said the model had been set aside.
    """
    from contexer.cli.test_cli import build_model
    from contexer.llm.base import LLMError
    from contexer.llm.chat import ToolCallingError

    try:
        return build_model(project)
    except ToolCallingError as exc:
        if on_refused is not None:
            on_refused(str(exc))
        return None
    except (LLMError, ValueError):
        return None


def _take_lock(console: Console, activity: Any, agent: CodingAgentAdapter, project: Path, run: str) -> ExitStack:
    """Hold the project's run lock until the returned stack is closed. Exits with a plain sentence if another run has it."""
    stack = ExitStack()
    try:
        stack.enter_context(run_lock(project, run))
    except RunLocked as exc:
        activity.stop()
        agent.close()
        term.note(console, "fail", f"[red]Not started:[/] {escape(str(exc))}")
        raise typer.Exit(code=2) from None
    return stack


def _snapshot_failed(console: Console, activity: Any, exc: Exception) -> NoReturn:
    """Contexer snapshots the project with git. When that fails there is nothing safe to go on with."""
    activity.stop()
    hint = "Install git and run again." if shutil.which("git") is None else "Your files are as the last step left them; `contexer runs` lists what was saved."
    term.note(console, "fail", f"[red]Could not snapshot the project:[/] {escape(str(exc))}")
    console.print(f"  {escape(hint)}")
    raise typer.Exit(code=3) from None


def emit_json(event: dict[str, Any]) -> None:
    """One event as one line on stdout. ASCII only, so no terminal's encoding can break a line."""
    sys.stdout.write(json.dumps(event, ensure_ascii=True, default=str) + "\n")
    sys.stdout.flush()


def run_budget(config: ProjectConfig, max_usd: float | None = None) -> Budget:
    """The budget of one run: the token limit, the project's rates, and the one budget in dollars (the flag wins)."""
    return Budget(
        max_tokens=config.limits.tokens or DEFAULT_MAX_TOKENS,
        max_cost_usd=config.limits.cost_usd,
        max_total_usd=max_usd if max_usd is not None else config.agents.max_usd,
        input_usd_per_mtok=config.agents.input_usd_per_mtok,
        output_usd_per_mtok=config.agents.output_usd_per_mtok,
    )


# The agents `contexer run` uses. The Tester and the Challenger belong to `contexer test`.
RUN_AGENTS = ("intent", "planner", "triage", "diagnoser", "reviewer")


class AgentSettingError(ValueError):
    """A setting under ``[agents.<name>]`` in contexer.toml that cannot be applied."""


def crew_models(
    project: Path,
    config: ProjectConfig,
    *,
    default_provider: str | None = None,
    agents: tuple[str, ...] = CREW_AGENTS,
) -> dict[str, Any]:
    """A model for each of ``agents`` the project names one for; the others use the default.

    A model that cannot be built raises :class:`AgentSettingError`. It used to be a warning and
    the default model: a project that asked for a cheap model was then billed for the other one.
    """
    from contexer.cli import test_cli
    from contexer.llm.base import LLMError

    models: dict[str, Any] = {}
    for name in agents:
        chosen = config.agents.for_agent(name)
        if not chosen.model:
            continue
        try:
            models[name] = test_cli.build_model(project, chosen.provider or default_provider, chosen.model)
        except (LLMError, ValueError) as exc:
            raise AgentSettingError(
                f"[agents.{name}] in contexer.toml names the model '{chosen.model}', which cannot be used: {exc}"
            ) from exc
    return models


def bill_line(outcome: RunOutcome) -> str:
    """What Contexer's own agents used, per agent, and what it cost when that is known. '' when none ran."""
    if not outcome.agents:
        return ""
    parts = [f"{a.agent} {a.tokens_in + a.tokens_out:,} tokens" for a in outcome.agents]
    if outcome.crew_cost_usd is None:
        cost = "cost unknown (the provider reports none; set prices under [agents] to see it)"
    else:
        cost = f"${outcome.crew_cost_usd:.2f}" + (
            " estimated from the configured rates" if outcome.crew_cost_estimated else ""
        )
    return " · ".join(parts) + f" · {cost}"


def _run_budget_note(budget: Budget | None) -> str:
    if budget is None or budget.max_total_usd is None:
        return ""
    return f" · one budget of ${budget.max_total_usd:.2f} for the coding agent and Contexer's agents"


def _estimate(settings: RunSettings, budget: Budget | None, has_model: bool, drafts_checks: bool) -> RunEstimate:
    return estimate_run(
        rounds=settings.max_repair_rounds,
        has_model=has_model,
        drafts_checks=drafts_checks,
        review=settings.review,
        plan=settings.plan,
        planner_steps=settings.agent_steps.get("planner", 12),
        diagnoser_steps=settings.agent_steps.get("diagnoser", 15),
        reviewer_steps=settings.agent_steps.get("reviewer", 12),
        input_usd_per_mtok=budget.input_usd_per_mtok if budget is not None else None,
        output_usd_per_mtok=budget.output_usd_per_mtok if budget is not None else None,
    )


def _limits_line(agent: CodingAgentAdapter, settings: RunSettings) -> str:
    limits = f"up to {settings.max_repair_rounds} repair round(s)"
    if settings.budget_usd:
        # Codex reports tokens, not cost: the round and time limits bound its runs instead.
        limits += (
            " · no spending limit (Codex reports no cost)"
            if agent.name == "codex"
            else f" · budget ${settings.budget_usd:.2f}"
        )
    return limits


def _asker(console: Console, activity: Any, yes: bool) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """How a run puts its questions to the person at the terminal."""

    def ask(request: dict[str, Any]) -> dict[str, Any]:
        activity.stop()
        if request.get("kind") == "approve":
            title = "The checks changed" if request.get("changed") else "Checks drafted from the goal"
            term.section(console, title, "what will count as done")
            for line in request.get("checks", []):
                console.print(f"  {escape(str(line))}")
            assumptions = [str(a) for a in request.get("assumptions", [])]
            if assumptions:
                console.print()
                console.print("  [dim]Assumed without asking:[/]")
                term.bullets(console, [escape(a) for a in assumptions], indent=4)
            console.print()
            if yes:
                return {"approve": True, "by": AUTOMATIC_APPROVAL}
            typed = typer.prompt(
                "Approve these checks as the definition of done? [y/n, or type what to change]",
                default="n",
                show_default=False,
            ).strip()
            if typed.lower() in ("y", "yes"):
                return {"approve": True}
            if typed.lower() in ("n", "no", ""):
                return {"approve": False}
            return {"correction": typed}
        attempt = request.get("attempt")
        term.section(console, f"A question after attempt {attempt}", "the run is waiting for you")
        console.print(f"  {escape(str(request.get('question') or 'How should this continue?'))}")
        failing = [str(f) for f in request.get("failing", [])]
        if failing:
            console.print(f"  [dim]Failing: {escape(', '.join(failing))}[/]")
        console.print()
        typed = typer.prompt(
            "Your answer (Enter lets the run decide, `stop` ends it)", default="", show_default=False
        ).strip()
        if typed.lower() == "stop":
            return {"stop": True}
        return {"answer": typed}

    return ask


def execute_graph(
    console: Console,
    project: Path,
    agent: CodingAgentAdapter,
    store: ContractStore,
    settings: RunSettings,
    url: str | None = None,
    *,
    model: Any = None,
    budget: Budget | None = None,
    yes: bool = False,
    contract: Contract | None = None,
    goal: str | None = None,
    contract_id: str | None = None,
    resume: str | None = None,
    correction: str | None = None,
    on_progress: Callable[[str, str], None] | None = None,
    origin: str = "",
    models: dict[str, Any] | None = None,
    json_output: bool = False,
    verbose: bool = False,
) -> RunOutcome:
    """One run: it can wait for an approval or an answer, be stopped, and be resumed."""
    from contexer.cli.test_cli import is_interactive
    from contexer.llm.chat import describe_model

    others = [c for c in store.list() if c.status == "approved"] if settings.replay_others else []
    subject = f"Resuming {resume}" if resume else (contract.goal if contract is not None else goal or "")
    term.header(console, "run", subject.splitlines()[0] if subject else "")
    decides = (
        f"{escape(describe_model(model))} [dim]for Contexer's own agents[/]"
        if model is not None
        else "[dim]none for Contexer's own agents, so fixed rules decide each next step (`contexer setup` adds one)[/]"
    )
    term.fields(
        console,
        [
            ("Agent", escape(agent.describe())),
            ("Model", decides),
            ("Limits", _limits_line(agent, settings) + _run_budget_note(budget)),
            (
                "Estimate",
                escape(_estimate(settings, budget, model is not None, contract is None and not resume).describe()),
            ),
        ],
    )
    # The run is drawn from its events: lines that stay, and in a terminal a block that is redrawn (cli/runview.py).
    # With --json the same events are printed, one object per line, and nothing is drawn.
    activity = RunView(console, verbose=verbose, project=project)

    def on_detail(event: RunEvent) -> None:
        if not json_output:
            activity.handle(event)
        elif event.kind != "end":  # the last line is written when the hand-off is known too
            emit_json(event.as_json())

    if json_output:
        emit_json(
            {
                "event": "run-start",
                "at": 0.0,
                "agent": agent.describe(),
                "engine": "graph",
                "goal": subject,
                "resume": resume,
                "repair_rounds": settings.max_repair_rounds,
                "model": describe_model(model) if model is not None else None,
            }
        )
    controller = GraphController(
        project,
        agent,
        settings,
        url=url,
        on_event=on_progress,
        on_detail=on_detail,
        model=model,
        ask=_asker(console, activity, yes),
        # Triage may stop to ask only when a person is at the terminal; an approval is always asked for.
        can_ask=not yes and is_interactive(),
        budget=budget,
        models=models,
    )
    held = _take_lock(console, activity, agent, project, resume or "")
    try:
        if resume:
            outcome = asyncio.run(controller.resume(resume, correction=correction))
        elif contract is not None:
            outcome = asyncio.run(controller.run(contract, others))
        else:
            outcome = asyncio.run(
                controller.run_goal(goal or "", others=others, contract_id=contract_id, origin=origin)
            )
    except SnapshotError as exc:
        _snapshot_failed(console, activity, exc)
    except ResumeError as exc:
        activity.stop()
        term.note(console, "fail", f"[red]Cannot resume:[/] {escape(str(exc))}")
        raise typer.Exit(code=2) from None
    except (KeyboardInterrupt, typer.Abort, asyncio.CancelledError):
        activity.stop()
        if controller.last_outcome is None:  # stopped before the first snapshot
            term.note(console, "warn", "Stopped. Nothing was changed.")
            raise typer.Exit(code=130) from None
        outcome = controller.last_outcome
    finally:
        activity.stop()
        agent.close()
        held.close()
    return outcome


# How a run ended when nothing is committed or pushed: the files were put back, not finished.
_NO_HANDOFF = ("tampered", "cancelled", "internal_error")


def issue_goal(console: Console, plan: HandoffPlan | None, number: int, store: ContractStore) -> tuple[str, str]:
    """The goal an issue describes (its title and text), and a contract id that names the issue."""
    token = github_token()
    if plan is None or plan.repo is None or token is None:
        missing = "a GitHub token (GITHUB_TOKEN, or `gh auth login`)" if token is None else "a GitHub remote"
        console.print(f"[red]Cannot read issue #{number}:[/] the project needs {missing}.")
        raise typer.Exit(code=3)
    try:
        with GitHubClient(plan.repo, token) as client:
            found = client.issue(number)
    except GitHubError as exc:
        console.print(f"[red]Cannot read issue #{number}:[/] {escape(str(exc))}")
        raise typer.Exit(code=3) from exc
    if found.get("state") == "closed":
        console.print(f"[yellow]Issue #{number} is closed;[/] working on it anyway.")
    # The same reading as the Actions path: without what GitHub does not show (HTML comments, invisible
    # characters), so nothing reaches an agent that a person looking at the issue could not see.
    goal = shown_issue_goal(found)
    title = visible_text(str(found.get("title") or ""))
    console.print(f"[dim]Issue #{number} · {escape(title)} · {escape(str(found.get('html_url', '')))}[/]")
    return goal, store.unique_id(f"issue {number} {title}")


def _draft(
    console: Console,
    project: Path,
    store: ContractStore,
    goal: str,
    url: str | None,
    drafting: Any = None,
    contract_id: str | None = None,
) -> tuple[Contract, RunResult | None, GoalAnalyzer]:
    analyzer = GoalAnalyzer(llm_provider=drafting)

    async def compile_contract() -> tuple[Contract, RunResult | None]:
        run_dir = RunDir.create(project)
        session = VerificationSession(project, run_dir)
        cid = contract_id or store.unique_id(goal)
        try:
            with open_app(project, url) as app:
                await session.observe(app)
                drafted = await session.compile(goal, analyzer, cid, app.repo_context)
                return drafted, await preview_draft(session, app, drafted)
        except AppStartError:
            # nothing runs yet: the checks define the contract
            return await session.compile(goal, analyzer, cid), None

    with console.status("[dim]Compiling the goal into checks, then trying them on the app as it is...[/dim]"):
        contract, preview = asyncio.run(compile_contract())
    store.save(contract)
    return contract, preview, analyzer


def _approve(
    console: Console,
    store: ContractStore,
    contract: Contract,
    yes: bool,
    preview: RunResult | None = None,
    analyzer: GoalAnalyzer | None = None,
) -> Contract:
    print_checklist(console, contract)
    print_draft_preview(console, preview)
    if analyzer is not None:
        print_drafted_by(console, analyzer)
    warn_if_weak_draft(console, contract, analyzer.last_error if analyzer else None)
    if yes and contract.source == "rules":
        # Building against a rule-based fallback wastes the agent's budget on a contract nobody chose.
        term.note(
            console,
            "warn",
            f"Not approved: --yes never approves a weak draft. Review {escape(str(store.path_for(contract.id)))}, "
            f"then `contexer contract approve {escape(contract.id)}`.",
        )
        raise typer.Exit(code=2)
    console.print()
    if not yes and not typer.confirm("Approve these checks as the definition of done?", default=False):
        store.save(contract)
        term.note(console, "warn", f"Not approved. Edit {escape(str(store.path_for(contract.id)))} and run again.")
        raise typer.Exit(code=2)
    approved = store.approve(contract.id, by=AUTOMATIC_APPROVAL if yes else None)
    console.print(f"{term.mark('pass')} Approved [bold]{escape(approved.id)}[/]")
    return approved


def check_free_quota(
    console: Console, drafting: Any, agent: CodingAgentAdapter, yes: bool, *, crew: Any = None, needed: int = 0
) -> None:
    """Say before the run, not halfway through it, when OpenRouter's free requests are about to run out.

    ``crew`` is the model of Contexer's own agents and ``needed`` the most model calls they can make
    in this run (the estimate's ceiling). Fewer requests left than that is said, not asked about:
    a run that passes early uses a small part of the ceiling.
    """
    from contexer.llm.chat import uses_free_requests

    users = []
    crew_is_free = uses_free_requests(crew)
    if crew_is_free:
        users.append("Contexer's own agents")
    if (
        drafting is not None
        and getattr(drafting, "provider_name", "") == "openrouter"
        and discovery.is_free_model(drafting.model)
    ):
        users.append("drafting")
    if getattr(agent, "provider", "") == "openrouter" and discovery.is_free_model(getattr(agent, "model_id", "")):
        users.append("the coding agent")
    key = os.environ.get("OPENROUTER_API_KEY")
    if not users or not key:
        return
    quota = discovery.openrouter_free_quota(key)
    crew_calls = needed if crew_is_free else 0
    if quota is None or quota.remaining >= max(discovery.LOW_FREE_REQUESTS, crew_calls):
        return
    size = (
        f"Contexer's own agents can make up to {crew_calls} model calls in this run"
        if crew_calls
        else "a small change took about 15 in our runs, a larger one can take 40 or more"
    )
    detail = (
        f"OpenRouter's free models allow {quota.limit} requests a day and {quota.remaining} are left today "
        f"(the count resets at 00:00 UTC). This run uses them for {' and '.join(users)}; {size}."
    )
    remedy = (
        "Buying $10 of OpenRouter credit raises the limit to 1,000 a day, or `contexer setup` picks another provider."
    )
    console.print()
    if quota.remaining <= 0:
        term.note(console, "fail", "[bold red]No free requests left today[/]")
        console.print(f"  {escape(detail)}\n  {escape(remedy)}")
        raise typer.Exit(code=3)
    low = quota.remaining < discovery.LOW_FREE_REQUESTS
    term.note(console, "warn", "[bold yellow]Few free requests left[/]" if low else "[yellow]This run can use more free requests than are left[/]")
    console.print(f"  {escape(detail)}\n  If they run out, the run stops and keeps its best attempt. {escape(remedy)}")
    if low and not yes and not typer.confirm("Start anyway?", default=False):
        raise typer.Exit(code=2)


def choose_agent(project: AgentSettings, flag_name: str | None, flag_model: str | None) -> tuple[str, str | None]:
    """Coding agent and model: --agent/--model, then [agent] in contexer.toml, then `contexer setup`, then Claude Code."""
    set_in_project = project.model_fields_set
    name = (
        flag_name
        or (project.name if "name" in set_in_project else None)
        or os.environ.get("CONTEXER_AGENT")
        or project.name
    )
    model = flag_model or project.model
    if model is None and name == os.environ.get("CONTEXER_AGENT"):
        model = os.environ.get("CONTEXER_AGENT_MODEL")  # saved together with that agent
    return name, model


_RATE_LIMITED = ("rate limit", "too many requests", "429")
_ACCOUNT_PROBLEMS = (
    "credit balance",
    "credits",
    "unauthorized",
    "401",
    "authentication",
    "api key",
    "not logged in",
    "login",
)


def agent_hint(outcome: RunOutcome) -> str | None:
    """What to do when the coding agent itself could not run (no credit, not logged in)."""
    reason = " ".join([outcome.reason, *(a.agent.error or "" for a in outcome.attempts)]).lower()
    again = f"`contexer run --contract {outcome.contract_id}`"
    if "free-models-per-day" in reason:
        return (
            "OpenRouter's daily free-model requests ran out (the count resets at 00:00 UTC). Run "
            f"{again} then, buy $10 of credit for 1,000 a day, or `contexer setup` another provider."
        )
    if any(limit in reason for limit in _RATE_LIMITED):
        return f"the model's provider is rate-limiting requests. Wait a minute, then {again} continues from the approved checks."
    if outcome.terminal != "agent_error":
        return None
    if not any(problem in reason for problem in _ACCOUNT_PROBLEMS):
        return None
    if os.environ.get("OPENROUTER_API_KEY") and shutil.which("opencode"):
        return "the agent's account cannot run it; `--agent opencode` runs it on your OpenRouter key's free models."
    if os.environ.get("OPENROUTER_API_KEY"):
        return (
            "the agent's account cannot run it. Install OpenCode (npm i -g opencode-ai) and use "
            "`--agent opencode` to run it on your OpenRouter key's free models."
        )
    return "the agent's account cannot run it: log in to it, add credit, or choose another with --agent."


def _render(
    console: Console,
    outcome: RunOutcome,
    handoff: Handoff | None = None,
    handoff_error: str | None = None,
    pr: bool = False,
) -> None:
    style = term.TERMINAL_STYLE.get(outcome.terminal, "yellow")
    mark = "pass" if outcome.terminal == "succeeded" else "fail" if style == "red" else "warn"
    title = outcome.terminal.replace("_", " ").capitalize()
    console.print()
    console.print(f"{term.mark(mark)} [bold {style}]{escape(title)}[/] [dim]·[/] {escape(outcome.reason)}")

    rows: list[tuple[str, str]] = []
    # A graph run has already shown each attempt as it happened; the summary does not say it twice.
    listed = [] if outcome.engine == "graph" else outcome.attempts
    if outcome.engine == "graph" and len(outcome.attempts) > 1:
        kept = f" · attempt {outcome.best_attempt} kept" if outcome.best_attempt else ""
        rows.append(("Attempts", f"{len(outcome.attempts)}{kept}"))
    for a in listed:
        counts = (
            f"{a.verified} verified · {a.refuted} refuted · {a.unverified} unverified"
            if a.outcome != "error"
            else "the app did not run"
        )
        kept = " [dim](kept)[/]" if a.n == outcome.best_attempt and len(outcome.attempts) > 1 else ""
        fresh = " [dim](fresh session)[/]" if a.fresh_session and a.n > 1 else ""
        note = f" [dim]· {escape(a.note)}[/]" if a.note else ""
        rows.append((f"Attempt {a.n}", f"{a.kind}{fresh} · {counts}{kept}{note}"))
    if handoff is not None:
        if handoff.is_pull_request:
            rows.append(
                ("Draft pull request" if handoff.draft else "Pull request", f"[bold]{escape(handoff.url or '')}[/]")
            )
        elif handoff.url:
            rows.append(("Pull request", f"open it at {escape(handoff.url)}"))
        rows.append(("Branch", f"{escape(handoff.branch)} [dim]({handoff.commit[:8]}, you are on it now)[/]"))
        if handoff.note:
            rows.append(("Note", f"[yellow]{escape(handoff.note.strip())}[/]"))
    elif handoff_error:
        rows.append(("Pull request", f"[red]not opened:[/] {escape(handoff_error)}"))
    elif pr and outcome.terminal not in _NO_HANDOFF:
        rows.append(("Pull request", "[dim]none: the run left no changes[/]"))
    # What reading the diff found: the notes themselves, the ones that need a person first.
    order = {"high": 0, "medium": 1, "low": 2}
    for index, note in enumerate(sorted(outcome.review, key=lambda n: order.get(n.severity, 3))[:4]):
        where = f"{note.file}:{note.line}" if note.file and note.line else note.file
        style = "red" if note.severity == "high" else "yellow" if note.severity == "medium" else "dim"
        text = f"[{style}]{note.severity}[/] {escape(where)} [dim]·[/] {escape(note.explanation)}" if where else f"[{style}]{note.severity}[/] {escape(note.explanation)}"
        rows.append(("Review" if index == 0 else " ", text))
    if len(outcome.review) > 4:
        rows.append((" ", f"[dim]and {len(outcome.review) - 4} more in the report[/]"))
    rows.append(("Report", escape(term.path(Path(outcome.run_dir, "report.html")))))
    spend = f" · ${outcome.cost_usd:.2f} agent spend" if outcome.cost_usd else ""
    rows.append(("Took", f"{term.duration(outcome.duration_seconds)}{spend}"))
    bill = bill_line(outcome)
    if bill:
        rows.append(("Contexer's agents", escape(bill)))
    hint = agent_hint(outcome)
    if hint:
        rows.append(("Next", f"[yellow]{escape(hint)}[/]"))
    term.fields(console, rows)
