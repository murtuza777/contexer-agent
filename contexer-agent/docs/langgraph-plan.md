# Contexer on LangGraph: a plan, and how it differs from today

Contexer's run loop is a hand-written state machine in
`src/contexer/controller/run.py` (about 500 lines). This document plans how
the same product would be built on [LangGraph](https://github.com/langchain-ai/langgraph),
maps every part of today's implementation onto it, and ends with a
recommendation.

It is a design study. Nothing here is implemented.

## 1. What has to stay true

Whatever runs the loop, these properties are the product and do not change:

1. **The browser decides.** Pass, fail, repair or roll back is decided by
   Contexer's own Playwright checks and fixed rules, never by a model choosing
   the next step.
2. **Approved contracts are locked.** A sha256 hash at approval; the agent
   cannot edit them (tamper guard).
3. **The project is never left worse.** Every attempt is snapshotted in the
   shadow git repo; a run ends on the best attempt or the baseline, also on
   Ctrl+C.
4. **Bounded.** Repair rounds, wall clock, spend and per-turn timeout.
5. **The coding agent is an external program** (Claude Code, Codex,
   OpenCode), killed with its whole process tree when a run stops.

LangGraph is used for orchestration only. All routing functions are plain
Python; models are called only where they are called today (drafting checks,
LLM-judged checks).

## 2. Today's run loop, step by step

From `RunController.run`:

| Step | Code today |
| --- | --- |
| Setup | `RunDir.create`, `ShadowRepo.snapshot("<run>/0")` (baseline), `_ContractGuard`, `RepositoryInspector().inspect`, `implement_prompt(...)` |
| Budget gate | `wall_clock` → `timed_out`; `budget_usd - cost` ≤ 0 → `budget_exhausted` |
| Agent turn | `agent.run_turn(prompt, session_id=None if fresh else session_id, timeout, budget_usd)` |
| Guard and snapshot | `guard.restore_if_changed()` → `tampered`; `shadow.snapshot("<run>/<n>")`; `changed_paths(current, snapshot)`; agent failed with no change → `agent_error` / `budget_exhausted` |
| App | `open_app(...)` once (entered on the `ExitStack`), restart with install when a dependency file changed, else `ensure_running()`; a start failure becomes an `error` result |
| Prove | `VerificationSession.verify(app, [contract, *others], judged_policy)` |
| Score, keep best | `_score`: +1 per verified target check, −2 per regression, −1e6 when the app did not start; pass → `succeeded`; better → new best; worse → `shadow.restore(best)` and restart if dependencies differ |
| Out of rounds | only unverified or app error → `needs_human`, else `failed_checks` |
| Plan repair | repeated failure signatures or a revert → fresh session; `repair_prompt(...)` |
| Finalize | restore best / baseline per terminal state, diff and changed files from the shadow repo, `_write_evidence` |
| Ctrl+C | `on_exit` on the `ExitStack` → `_stopped`: snapshot `<run>/stopped`, restore best or baseline, write evidence, exit 130 |

## 3. The same loop as a LangGraph graph

```text
START → setup → budget_gate ──over──────────────────────────────┐
                    │ ok                                         │
                    ▼                                            │
               agent_turn → guard_snapshot ──tampered/agent_err──┤
                                  │ ok                           │
                                  ▼                              │
                             ensure_app → prove → score ──pass───┤
                                                   │ rounds left │
                                                   ▼  │ none ────┤
                                             plan_repair         │
                                                   │             ▼
                                                   └→ budget_gate   finalize → END
```

### State

Only serializable values go into graph state, so a checkpointer can save it.
Snapshots are git refs (strings) and results are paths to `result.json`.

```python
from typing import Literal, Optional, TypedDict

class RunState(TypedDict, total=False):
    contract_id: str
    other_ids: list[str]
    run_id: str
    n: int                          # attempt number
    prompt: str
    fresh: bool                     # next turn starts a new agent session
    session_id: Optional[str]
    snapshots: dict[int, str]       # attempt -> shadow commit (0 = baseline)
    current: str                    # tree the agent started this attempt from
    results: dict[int, str]         # attempt -> result.json path
    best: Optional[int]
    best_score: int
    last_signatures: list[str]
    changed: list[str]
    app_error: Optional[str]
    reverted_from: Optional[int]
    cost_usd: float
    started_at: float
    attempts: list[dict]            # Attempt.model_dump()
    terminal: Optional[str]         # TerminalState
    reason: str
```

### Things that cannot live in state

The agent adapter, the running app (a process tree), the `ShadowRepo`, the
`CheckRunner` (one Chromium) and the contracts are live objects. They go into
LangGraph's runtime context, created and closed outside the graph:

```python
from dataclasses import dataclass
from langgraph.runtime import Runtime

@dataclass
class RunContext:
    project: Path
    agent: CodingAgentAdapter
    shadow: ShadowRepo
    guard: _ContractGuard
    runner: CheckRunner
    contracts: dict[str, Contract]
    settings: RunSettings
    apps: "AppHolder"               # opens the app once, restarts it, closes it at the end
    on_event: EventFn
```

### Nodes (each a thin wrapper over today's code)

```python
async def agent_turn(state: RunState, runtime: Runtime[RunContext]) -> dict:
    ctx = runtime.context
    remaining = None if ctx.settings.budget_usd is None else ctx.settings.budget_usd - state["cost_usd"]
    turn = await ctx.agent.run_turn(
        ctx.project, state["prompt"],
        session_id=None if state["fresh"] else state.get("session_id"),
        timeout=ctx.settings.turn_timeout, budget_usd=remaining,
        on_progress=lambda line: ctx.on_event("agent", line),
    )
    return {"session_id": turn.session_id or state.get("session_id"),
            "cost_usd": state["cost_usd"] + (turn.cost_usd or 0.0),
            "last_turn": turn.model_dump()}
```

`guard_snapshot`, `ensure_app`, `prove`, `score`, `plan_repair` and
`finalize` are the matching blocks of `RunController.run`, moved into
functions that read state and return a partial update. `_score`,
`_signatures`, `implement_prompt` and `repair_prompt` are reused unchanged.

### Routing: plain functions, no model

```python
def after_budget(state: RunState) -> Literal["agent_turn", "finalize"]:
    return "finalize" if state.get("terminal") else "agent_turn"

def after_guard(state: RunState) -> Literal["ensure_app", "finalize"]:
    return "finalize" if state.get("terminal") in ("tampered", "agent_error", "budget_exhausted") else "ensure_app"

def after_score(state: RunState) -> Literal["plan_repair", "finalize"]:
    return "finalize" if state.get("terminal") else "plan_repair"
```

`score` sets `terminal` to `succeeded` on a pass, and to `needs_human` or
`failed_checks` when `n > max_repair_rounds`, exactly as today.

### Building and running it

```python
from langgraph.graph import StateGraph, START, END

g = StateGraph(RunState, context_schema=RunContext)
for name, fn in [("setup", setup), ("budget_gate", budget_gate), ("agent_turn", agent_turn),
                 ("guard_snapshot", guard_snapshot), ("ensure_app", ensure_app), ("prove", prove),
                 ("score", score), ("plan_repair", plan_repair), ("finalize", finalize)]:
    g.add_node(name, fn)
g.add_edge(START, "setup")
g.add_edge("setup", "budget_gate")
g.add_conditional_edges("budget_gate", after_budget)
g.add_edge("agent_turn", "guard_snapshot")
g.add_conditional_edges("guard_snapshot", after_guard)
g.add_edge("ensure_app", "prove")
g.add_edge("prove", "score")
g.add_conditional_edges("score", after_score)
g.add_edge("plan_repair", "budget_gate")
g.add_edge("finalize", END)
run_graph = g.compile(checkpointer=checkpointer)

# The recursion limit must allow (max_repair_rounds + 1) laps of 6 nodes, plus setup and finalize.
config = {"configurable": {"thread_id": run_id},
          "recursion_limit": 6 * (settings.max_repair_rounds + 1) + 4}
async with RunContextManager(project, agent, settings) as ctx:   # owns the app, Chromium, kill on exit
    final = await run_graph.ainvoke({"run_id": run_id, "n": 0, "cost_usd": 0.0}, config, context=ctx)
```

### Ctrl+C

Cancelling `ainvoke` cancels the running node. The cleanup that matters
(kill the agent's process tree, snapshot `<run>/stopped`, restore best or
baseline, write evidence) cannot depend on the graph reaching `finalize`, so
it stays in `RunContextManager.__aexit__`, reading the last checkpointed state
through `run_graph.aget_state(config)`. This is the same shape as today's
`on_exit`, one level further out.

## 4. Drafting and approval as a second graph

Approval is a human pause, which is what LangGraph's `interrupt` is for:

```text
START → observe → draft → preview → approve (interrupt) → lock → END
                    ▲                    │ "edit"
                    └────────────────────┘
```

```python
from langgraph.types import interrupt, Command

def approve(state: DraftState) -> dict:
    answer = interrupt({"checks": state["checks"], "preview": state["preview"]})
    if answer["action"] == "edit":
        return {"feedback": answer["text"], "approved": False}
    return {"approved": True}

# The CLI shows the checks, asks, and resumes the same thread:
await draft_graph.ainvoke(Command(resume={"action": "approve"}), config)
```

`observe` wraps `VerificationSession.observe`, `draft` wraps the compiler in
`workflow/criteria.py`, `preview` runs the drafted checks on the current app,
and `lock` hashes and writes the contract (`contract/store.py`).

### The GitHub issue flow

Today the issue flow keeps its state on GitHub itself: a draft comment with
`<!-- contexer:draft id= sha256= -->`, then a separate Actions job when
someone with write access replies `/contexer approve`. With LangGraph the
pause would be an `interrupt` in a graph that lives across two Actions jobs,
hours apart, on different machines. That needs a checkpointer every job can
reach (a hosted Postgres with `langgraph-checkpoint-postgres`), which means a
database, a connection secret in every repository that uses Contexer, and
cleanup of stale threads. The comment marker needs none of that and cannot be
lost. This is the part of the product where LangGraph fits worst.

## 5. Diff against the current implementation

### File by file

| File | Today | With LangGraph |
| --- | --- | --- |
| `controller/run.py` | `RunController.run`: one loop with local variables and an `ExitStack` | Split into `controller/graph.py` (state, routing, `compile`), `controller/nodes.py` (nine nodes), `controller/context.py` (`RunContext`, `RunContextManager`) |
| `controller/prompts.py` | `implement_prompt`, `repair_prompt` | Unchanged |
| `_score`, `_signatures`, `_ContractGuard` | Private helpers in `run.py` | Unchanged, moved to `controller/scoring.py` |
| `cli/run_cli.py` | `await RunController(...).run(contract, others)` | `await run_graph.ainvoke(..., context=ctx)`; progress from `astream(stream_mode="updates")` instead of `on_event` |
| `cli/gate_cli.py` (draft, approve) | Prompt in the CLI, then `ContractStore.approve` | `draft_graph` with `interrupt`, resumed by the CLI |
| `github/issues.py`, `cli/issue_cli.py` | State in issue comments | Unchanged (see §4), or a Postgres checkpointer |
| `checkpoint/shadow.py` | Snapshots and restores the work tree | Unchanged; LangGraph checkpoints state, not files |
| `agents/*`, `procutil.py`, `appserver/*`, `verification/*` | — | Unchanged; called from nodes |
| `pyproject.toml` | 7 runtime dependencies | + `langgraph`, `langgraph-checkpoint-sqlite` (and `langchain-core`, pulled in by LangGraph) |
| `tests/test_controller.py` | Drives `RunController` with scripted agents | Same scenarios against the graph, plus a test per routing function |

### The call site

```diff
-    controller = RunController(project, agent, settings, url=url, on_event=on_event)
-    outcome = await controller.run(contract, others)
+    async with RunContextManager(project, agent, settings, url=url, on_event=on_event,
+                                 contracts=[contract, *others]) as ctx:
+        state = await run_graph.ainvoke(
+            {"run_id": ctx.run_id, "contract_id": contract.id,
+             "other_ids": [c.id for c in others], "n": 0, "cost_usd": 0.0},
+            {"configurable": {"thread_id": ctx.run_id}, "recursion_limit": ctx.recursion_limit},
+            context=ctx,
+        )
+    outcome = RunOutcome.from_state(state)
```

### Behaviour, side by side

| Concern | Today | LangGraph |
| --- | --- | --- |
| Who decides the next step | Plain `if` in one loop | Plain routing functions on conditional edges (same rules) |
| Reading the control flow | One function, top to bottom | A graph plus nine node functions; drawable with `get_graph().draw_mermaid()` |
| State | Local variables, including live objects | A `TypedDict` of serializable values; live objects in runtime context |
| Resume after a crash | Not supported; `contexer restore` brings back any snapshot by hand | Possible from the last checkpoint, but each node must first put the work tree back to `state["current"]`, because files are not in the checkpoint |
| Human approval | CLI prompt; issue comment marker | `interrupt` + `Command(resume=...)` locally; a shared database for the issue flow |
| Ctrl+C cleanup | `ExitStack` callback | Same cleanup, around the graph, reading the last checkpoint |
| Streaming progress | `on_event(kind, message)` | `astream` updates and custom stream events |
| Loop limit | `range(max_repair_rounds + 2)` | `recursion_limit`, which must be kept in step with the round limit |
| Tracing | `result.json`, `report.html`, server log | The same, plus optional LangSmith. It would have to stay off by default: traces would carry prompts, page snapshots and possibly secrets to a third party |
| Dependencies | 7 | 9+, including `langchain-core` |
| Tests | 509, no network | The same suite plus routing tests; the scripted agent still drives it |

## 6. Plan, if we did it

1. **Extract without changing behaviour.** Move `_score`, `_signatures` and
   `_ContractGuard` to `controller/scoring.py`; split the loop body into
   functions that take and return a state dict. Keep `RunController.run` as
   the caller. All tests stay green. (1 day)
2. **Add the graph behind a flag.** `controller/graph.py` with the state,
   nodes and routing above; `CONTEXER_ENGINE=graph` switches `run_cli` to it.
   Run `tests/test_controller.py` against both engines. (2 days)
3. **Cancellation and evidence.** `RunContextManager` owns the app, Chromium
   and the agent's process tree; Ctrl+C restores from the last checkpoint and
   exits 130. Port the stop test. (1 day)
4. **Checkpointer and resume.** `SqliteSaver` in `.contexer/runs/<id>/graph.db`
   (already gitignored); `contexer run --resume RUN` restores
   `snapshots[current]` and continues the thread. New tests for a run killed
   mid-attempt. (2 days)
5. **Drafting graph with `interrupt`.** Replace the approval prompt in
   `gate_cli`; keep the issue flow on comment markers. (1–2 days)
6. **Benchmark and live runs.** `contexer bench` must still catch 40/40 with
   0 false failures; repeat one live OpenCode run with `--pr`. (1 day)
7. **Decide.** Make the graph the default only if `--resume` is wanted by
   users and the benchmark and live runs match; otherwise delete the flag.

About 8–9 working days.

## 7. Recommendation

Do not move the run loop to LangGraph now.

- **What it would add:** resume after a crash, a drawable graph, `interrupt`
  for approval, and a familiar shape for contributors who know LangGraph.
- **What it would cost:** nine files where one reads top to bottom, state
  that must be kept serializable, a recursion limit that must track the round
  limit, cleanup that still has to live outside the graph, and at least two
  more dependencies with frequent API changes.
- **What it would not change:** the outcome of any run. The routing rules are
  the same `if` statements either way, and the files on disk still need the
  shadow repo.

The one feature that would justify it is **resuming a long run after a crash
or a closed laptop**. If users ask for that, follow §6 behind the flag. If
Contexer later runs several agents in parallel on parts of one goal, LangGraph's
fan-out (`Send`) becomes worth a second look too.

CrewAI and similar role-based frameworks fit worse still: they model agents
that talk to each other and decide together, while Contexer's agents are
external programs and its decisions are fixed rules.
