"""The graph engine: the same job as ``RunController``, able to wait, stop and continue.

``run`` takes an approved contract, like the classic controller. ``run_goal``
starts one step earlier: the Intent agent drafts the checks and the run waits
for a person to approve them. ``resume`` continues a run whose process ended,
from the checkpoint in its run folder.

With no model configured the graph applies the 0.4 rules and writes the 0.4
prompts, so the two engines agree; ``tests/test_controller.py`` runs every
case on both.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.errors import NodeCancelledError
from langgraph.types import Command

from contexer.agents.base import CodingAgentAdapter
from contexer.checkpoint import ShadowRepo
from contexer.contract import Contract, ContractError, ContractStore
from contexer.contract.models import utc_now
from contexer.contract.store import CONTEXER_DIR
from contexer.controller.models import RunOutcome, RunSettings
from contexer.controller.prompts import implement_prompt
from contexer.controller.shared import ContractGuard
from contexer.crew.budget import Budget
from contexer.evidence.rundir import RUNS_DIR, RunDir
from contexer.graph.build import CHECKPOINT_FILE, build_graph, step_limit
from contexer.graph.context import STOPPED_FILE, AskFn, EventFn, RunContext, guard_digest
from contexer.graph.nodes import stopped_outcome
from contexer.graph.state import UNSCORED, LoopState
from contexer.intent.store import IntentStore
from contexer.verification.runner import CheckRunner
from contexer.workflow.inspector import RepositoryInspector


class ResumeError(Exception):
    """A run cannot be continued: it does not exist, has no checkpoint, or what defines done changed."""


class GraphController:
    def __init__(
        self,
        project_dir: str | Path,
        agent: CodingAgentAdapter,
        settings: RunSettings | None = None,
        *,
        url: str | None = None,
        on_event: EventFn | None = None,
        runner: CheckRunner | None = None,
        model: BaseChatModel | None = None,
        ask: AskFn | None = None,
        budget: Budget | None = None,
        corrections: Any = None,
        can_ask: bool | None = None,
        models: dict[str, BaseChatModel] | None = None,
    ) -> None:
        self.project = Path(project_dir).resolve()
        self.agent = agent
        self.settings = settings or RunSettings()
        self.url = url
        self.on_event = on_event or (lambda _kind, _msg: None)
        self.runner = runner or CheckRunner(trace="on-failure")
        # The model for Contexer's own agents (Intent, Triage, Diagnoser). None: the rules decide.
        self.model = model
        self.models = dict(models or {})
        # How a person is asked. None: nobody is there, so nothing is approved and nobody is asked.
        self.ask = ask
        # Whether Triage may stop the run to ask a question. Approvals do not depend on it.
        self.can_ask = (ask is not None) if can_ask is None else (can_ask and ask is not None)
        self.budget = budget
        # Called between attempts; returns a correction the person gave since, or None.
        self.corrections = corrections
        # Set as soon as a run ends, also when it is stopped with an exception.
        self.last_outcome: RunOutcome | None = None

    # -- starting ------------------------------------------------------------------------------

    async def run(self, contract: Contract, others: list[Contract] | None = None) -> RunOutcome:
        """Drive the agent to an approved contract."""
        if contract.status != "approved":
            raise ValueError(f"contract '{contract.id}' must be approved before a run ({contract.status})")
        ctx = self._context(RunDir.create(self.project))
        ctx.contract = contract
        ctx.others = self._others(contract.id, others)
        state = self.initial_state(ctx, goal=contract.goal, contract_id=contract.id)
        state["approved_hash"] = contract.content_hash()
        state["prompt"] = implement_prompt(contract, ctx.repo, ctx.others)
        return await self._drive(ctx, state)

    async def run_goal(
        self,
        goal: str,
        draft: Contract | None = None,
        others: list[Contract] | None = None,
        contract_id: str | None = None,
        origin: str = "",
    ) -> RunOutcome:
        """Start from a goal: draft the checks (or take ``draft``), wait for approval, then build."""
        if draft is None and self.model is None:
            raise ValueError("a goal needs a model to draft its checks, or a draft contract")
        store = ContractStore(self.project)
        if draft is not None:
            store.save(draft)
            contract_id = draft.id
        ctx = self._context(RunDir.create(self.project))
        ctx.others = self._others(contract_id or "", others if others is not None else store.list())
        state = self.initial_state(ctx, goal=goal, contract_id=contract_id or "", origin=origin)
        return await self._drive(ctx, state)

    def initial_state(self, ctx: RunContext, *, goal: str, contract_id: str, origin: str = "") -> LoopState:
        baseline = ctx.shadow.snapshot(f"{ctx.run.run_id}/0", "baseline")
        return LoopState(
            run_id=ctx.run.run_id,
            goal=goal,
            goal_origin=origin,
            started_at=utc_now(),
            contract_id=contract_id,
            other_ids=[c.id for c in ctx.others],
            intent_id="",
            approved_hash="",
            guard=ctx.recapture_guard(),
            correction="",
            corrections=[],
            restate="",
            n=0,
            attempts=[],
            snapshots={"0": baseline},
            current=baseline,
            best=None,
            best_score=UNSCORED,
            session_id=None,
            fresh=True,
            prompt="",
            last_signatures=[],
            repeats={},
            reverted_from=None,
            changed=[],
            app_error=None,
            move="",
            decisions=[],
            asked=0,
            answer="",
            agents=[],
            cost_usd=0.0,
            elapsed=0.0,
            terminal="",
            reason="",
        )

    # -- continuing ------------------------------------------------------------------------------

    async def resume(self, run_id: str, *, correction: str | None = None) -> RunOutcome:
        """Continue a run from its checkpoint: reset the files to the last snapshot, then go on."""
        path = self.project / CONTEXER_DIR / RUNS_DIR / run_id
        if not run_id.strip() or not path.is_dir():
            raise ResumeError(f"There is no run '{run_id}' in this project (looked in {path.parent}).")
        if not (path / CHECKPOINT_FILE).is_file():
            raise ResumeError(f"Run '{run_id}' has no checkpoint. Only runs on the graph engine can be resumed.")
        ctx = self._context(RunDir(run_id=run_id, path=path))
        ctx.pending_correction = (correction or "").strip() or None
        return await self._drive(ctx, None)

    def _prepare_resume(self, ctx: RunContext, values: dict[str, Any], waiting: bool, next_nodes: tuple[str, ...] = ()) -> None:
        """Bring the project and the context back to where the checkpoint says the run was."""
        assert ctx.guard is not None
        now, then = guard_digest(ctx.guard), dict(values.get("guard") or {})
        if now != then:
            touched = sorted(name for name in set(now) | set(then) if now.get(name) != then.get(name))
            raise ResumeError(
                f"What defines done changed while run '{ctx.run.run_id}' was stopped ({', '.join(touched)}). "
                "Nobody approved that inside this run, so it is not continued. Start a new run."
            )
        store = ContractStore(self.project)
        contract_id = values.get("contract_id") or ""
        try:
            contract = store.load(contract_id) if contract_id and store.exists(contract_id) else None
            ctx.others = [store.load(cid) for cid in values.get("other_ids", []) if store.exists(cid)]
        except ContractError as exc:
            raise ResumeError(f"Run '{ctx.run.run_id}' cannot be continued: {exc}") from exc
        if contract is not None and contract.status == "approved" and contract.content_hash() == values.get("approved_hash"):
            ctx.contract = contract
        elif not waiting and values.get("n", 0) > 0 and not values.get("restate"):
            raise ResumeError(f"Run '{ctx.run.run_id}' cannot be continued: its contract is no longer approved.")
        ctx.base_elapsed = float(values.get("elapsed") or 0.0)
        ctx.mirror = dict(values)
        if ctx.budget is not None:
            # A new process builds a new budget. What the run's agents had spent is in the state.
            for row in values.get("agents") or []:
                ctx.budget.spend(int(row.get("tokens_in") or 0), int(row.get("tokens_out") or 0), row.get("cost_usd"))
            ctx.budget.other_usd = float(values.get("cost_usd") or 0.0)
        marker = ctx.run.path / STOPPED_FILE
        stopped_work = marker.read_text(encoding="utf-8").strip() if marker.is_file() else ""
        marker.unlink(missing_ok=True)
        current = values.get("current")
        if not current:
            return
        found = ctx.shadow.snapshot(f"{ctx.run.run_id}/before-resume", "the files as they were when the run was resumed")
        if "guard_snapshot" in next_nodes:
            # The coding agent's turn had returned and only its snapshot was missing. That work is what the
            # next node must see: after an orderly stop it is in the `stopped` snapshot, after a kill it is
            # still in the project.
            if stopped_work:
                ctx.shadow.restore(stopped_work)
            return
        # Whatever a cut-off turn left behind was kept above; the files go back to the state the next node expects.
        put_back = ctx.shadow.changed_paths(found, current)
        ctx.shadow.restore(current)
        if put_back:
            # It may be what a cut-off turn left, or what the person changed since. Code cannot tell which, so it
            # says what it did and where the files are.
            listed = ", ".join(put_back[:8]) + (f" and {len(put_back) - 8} more" if len(put_back) > 8 else "")
            ctx.event(
                "revert",
                f"Resuming put {len(put_back)} file(s) back to where the run left off: {listed}. What was there is "
                f"kept: `contexer restore {ctx.run.run_id} --before-resume`.",
            )

    # -- the loop ----------------------------------------------------------------------------------

    async def _drive(self, ctx: RunContext, state: LoopState | None) -> RunOutcome:
        config: dict[str, Any] = {
            "configurable": {"thread_id": ctx.run.run_id},
            "recursion_limit": step_limit(self.settings.max_repair_rounds),
        }
        resuming = state is None
        if not resuming:
            ctx.mirror = dict(state or {})
        try:
            async with AsyncSqliteSaver.from_conn_string(str(ctx.run.path / CHECKPOINT_FILE)) as saver:
                graph = build_graph(ctx, saver)
                send: Any = state
                first_question: Any = None
                if resuming:
                    snapshot = await graph.aget_state(config)
                    if not snapshot.values:
                        raise ResumeError(f"Run '{ctx.run.run_id}' has an empty checkpoint; it ended before it began.")
                    if not snapshot.next:
                        return self._finished(ctx)
                    waiting = [i for task in snapshot.tasks for i in task.interrupts]
                    self._prepare_resume(ctx, dict(snapshot.values), bool(waiting), tuple(snapshot.next))
                    send = None
                    first_question = waiting[0].value if waiting else None
                try:
                    if first_question is not None:
                        send = Command(resume=self._answer(ctx, first_question))
                    while True:
                        # "sync": the checkpoint is on disk before the next node starts, so a killed process loses
                        # at most the node it was in.
                        result = await graph.ainvoke(send, config, durability="sync")
                        waiting_for = result.get("__interrupt__") if isinstance(result, dict) else None
                        if not waiting_for:
                            break
                        send = Command(resume=self._answer(ctx, waiting_for[0].value))
                except BaseException as exc:
                    # LangGraph reports a cancel raised from inside a node (an adapter's own timeout scope,
                    # say) as NodeCancelledError. To the run it is the same thing: it was stopped.
                    stopped = isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, NodeCancelledError))
                    if stopped or getattr(exc, "stops_run", False):
                        # Ctrl+C, or the person walked away from a question. The app stops first, then the
                        # agent, then the files go back to a state that was proven or found.
                        ctx.close_app()
                        self.agent.stop()
                        self.last_outcome = stopped_outcome(ctx)
                    if isinstance(exc, NodeCancelledError):
                        raise asyncio.CancelledError from exc
                    raise
        finally:
            ctx.close_app()
        if ctx.outcome is None:  # the graph ended without finalize; routing makes this unreachable
            raise RuntimeError("the run ended without an outcome")
        self.last_outcome = ctx.outcome
        return ctx.outcome

    def _answer(self, ctx: RunContext, request: Any) -> dict[str, Any]:
        """Put a question to the person. With nobody there, the answer is the one that changes nothing."""
        request = request if isinstance(request, dict) else {}
        if request.get("kind") == "approve" and ctx.pending_correction:
            correction, ctx.pending_correction = ctx.pending_correction, None
            if self.model is not None:
                return {"correction": correction}
        if self.ask is None:
            return {"approve": False} if request.get("kind") == "approve" else {"answer": ""}
        try:
            answer = self.ask(request)
        except BaseException as exc:
            # Whatever a person does to leave a prompt (Ctrl+C, closing the terminal) stops the run in order.
            try:
                exc.stops_run = True  # type: ignore[attr-defined]
            except AttributeError:
                pass
            raise
        return answer if isinstance(answer, dict) else {}

    def _finished(self, ctx: RunContext) -> RunOutcome:
        path = ctx.run.path / "run.json"
        if not path.is_file():
            raise ResumeError(f"Run '{ctx.run.run_id}' finished, but its run.json is missing.")
        outcome = RunOutcome.model_validate_json(path.read_text(encoding="utf-8"))
        self.on_event("app", f"Run {ctx.run.run_id} had already finished ({outcome.terminal}); nothing was run.")
        self.last_outcome = outcome
        return outcome

    # -- pieces ----------------------------------------------------------------------------------------

    def _context(self, run: RunDir) -> RunContext:
        ctx = RunContext(
            project=self.project,
            agent=self.agent,
            settings=self.settings,
            run=run,
            shadow=ShadowRepo(self.project),
            store=ContractStore(self.project),
            intents=IntentStore(self.project),
            runner=self.runner,
            on_event=self.on_event,
            repo=RepositoryInspector().inspect(self.project),
            url=self.url,
            model=self.model,
            models=self.models,
            budget=self.budget,
            can_ask=self.can_ask,
            corrections=self.corrections,
        )
        ctx.guard = ContractGuard(self.project)
        return ctx

    def _others(self, contract_id: str, others: list[Contract] | None) -> list[Contract]:
        if not self.settings.replay_others:
            return []
        return [c for c in (others or []) if c.id != contract_id and c.status == "approved"]
