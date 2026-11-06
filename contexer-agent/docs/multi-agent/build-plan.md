# Technical build plan: multi-agent Contexer

Status: draft, 2026-11-03. Implements [prd.md](prd.md) following
[design.md](design.md). Estimates are working days for one engineer who knows
the codebase.

## 0. Principles for the build

1. **Each agent ships behind a flag and a benchmark.** It becomes the default
   only when its metric improves and false failures stay at 0.
2. **Agents are plain Python first, LangGraph second.** Each agent is a
   function `async def run(inputs, llm) -> PydanticModel`, tested on its own.
   LangGraph nodes are thin wrappers. This keeps the agents usable from
   today's `RunController` in 0.5, before the graph exists.
3. **Code owns every decision.** Routing, scoring, verdicts and stopping stay
   in tested functions with no model calls.
4. **With every agent off, behaviour equals 0.4.** The existing 509 tests and
   the benchmark run unchanged on every phase.

## 1. New and changed modules

```text
src/contexer/
  agents/                    existing coding-agent adapters (unchanged)
  crew/                      NEW: Contexer's own LLM agents
    base.py                  AgentSpec (name, model, request cap, timeout), call_structured()
    scout.py                 ScoutReport, run_scout(); tools: list/read/grep, try_start
    planner.py               Slice, Plan, run_planner(); normalise_plan() (code)
    critic.py                Finding, run_critic()
    diagnoser.py             RepairBrief, run_diagnoser()
    reviewer.py              ReviewNote, run_reviewer()
    prompts/                 one prompt file per agent
  graph/                     NEW (0.6): the LangGraph engine
    state.py                 GraphState, SliceState, reducers
    context.py               RunContext, RunContextManager (live objects, cleanup)
    nodes.py                 intake, scout, plan, draft, critique, approve, build_slice, integrate, review, finalize
    routing.py               every conditional edge, pure functions
    slice_graph.py           the per-slice implement → prove → diagnose → repair subgraph
    build.py                 compile(), checkpointer setup
  worktree/                  NEW (0.6)
    manager.py               add/remove worktrees, per-slice ports and data dirs
    merge.py                 merge in dependency order, conflict detection
  controller/run.py          0.5: calls Diagnoser; 0.6: becomes the "classic" engine
  controller/prompts.py      repair_prompt() accepts a RepairBrief
  workflow/criteria.py       draft loop accepts Critic findings
  cli/run_cli.py             --resume, --no-critic, engine selection, plan and wave rendering
  cli/init_cli.py            init --scout
  github/handoff.py          per-slice commits, plan table, review notes
  github/issues.py           plan in the draft comment, thread id in the marker
  config/project.py          [agents] section
bench/
  scout/                     NEW: 10 repos with known-good configs
  features/                  NEW: 10 multi-part goals with reference contracts
  critic/                    NEW: weak contracts with the bugs they miss
  reviewer/                  NEW: diffs with planted issues
```

## 2. Phase 0: groundwork (3 days)

| Task | Detail | Done when |
| --- | --- | --- |
| 0.1 `crew/base.py` | `call_structured(model, system, user, schema)` on today's provider clients; request cap, timeout, retries on invalid JSON (max 2); masking of secrets in prompts | Unit tests with a fake provider: valid, invalid-then-valid, cap reached |
| 0.2 `[agents]` config | Parse and validate, defaults all on except `planner = "auto"` | `test_config` covers every key and the all-off case |
| 0.3 Request accounting | Count drafting requests per run, shown in the summary and in `result.json` | Free-tier quota check uses the planned count, not 1 |
| 0.4 Bench harness extensions | `contexer bench --suite scout|features|critic|reviewer` | Each suite runs with a stub agent and reports its metric |

## 3. Phase 1 (0.5): agents on the current loop — 12 days

### 1a. Scout (5 days)

| Task | Detail |
| --- | --- |
| Tools | `list_files(glob)`, `read_file(path, max_bytes)`, `grep(pattern)`, `try_start(command, port)`; read-only, confined to the project |
| Tool loop | At most 12 tool calls; then it must return a `ScoutReport` |
| Validation (code) | `try_start` the proposed start; sign in with `[auth]` if proposed; run `doctor`; only then write `contexer.toml` |
| Risk scan (code) | `.env` not ignored, committed `*.json` with password-like keys, cookies files |
| CLI | `contexer init --scout`; `contexer run` runs it when config is missing or `doctor` fails; shows a diff and asks |
| Bench | `bench/scout/`: 10 repos (static, Node, Python, React/Vite, Next.js, Next.js + API, Django, a monorepo, a two-service app like BurryAI, one with sign-in). Metric: config reaches ready and signs in |

### 1b. Critic (4 days)

| Task | Detail |
| --- | --- |
| Agent | Input: draft contract, UI snapshot, goal; output: `list[Finding]` (kind, check id, severity, suggested check) |
| Loop | Spec writer revises with the findings; max 2 rounds; remaining findings shown at approval |
| Second model | `critic_model`, else a different configured provider, else the drafting model |
| Static checks (code, no model) | Vacuous expectations, checks that already pass on the current app, missing `login: false` case for signed-in features |
| Bench | `bench/critic/`: contracts drafted with and without the Critic for each seeded-bug app; metric: bugs caught, benign changes passing |

### 1c. Diagnoser (3 days)

| Task | Detail |
| --- | --- |
| Agent | Input: failure reports, screenshot path, server log tail, attempt diff, previous signatures; output: `RepairBrief` |
| Prompt | `repair_prompt(..., brief=)` keeps today's facts verbatim and adds cause and instruction |
| Routing (code) | `give_up` plus an external cause (missing secret, sign-in failure, connection refused in the log) → `needs_human` |
| Terminal | One "Cause" line per failed attempt |
| Measure | Re-run the 0.3/0.4 live scenarios and the bench bugs as repair tasks with the scripted agent; compare repair success with and without |

**0.5 release gate:** PRD G1, G3, G4; the full test suite and benchmark
unchanged with agents off; one live run on BurryAI with the Scout.

## 4. Phase 2 (0.6): LangGraph engine and parallel work — 18 days

### 2a. Engine port (6 days)

| Task | Detail |
| --- | --- |
| Dependencies | `langgraph` and `langgraph-checkpoint-sqlite`, pinned; optional extra `contexer-agent[graph]` until it is the default |
| State and context | `graph/state.py`, `graph/context.py` as in design §15 and [langgraph-port.md](langgraph-port.md) §3 |
| Slice subgraph | Today's loop as nodes: budget gate → agent turn → guard and snapshot → ensure app → prove → score → diagnose → plan repair |
| Routing | `graph/routing.py`; table-driven tests for every edge and terminal state |
| Engine flag | `CONTEXER_ENGINE=classic|graph`; `tests/test_controller.py` parametrised over both |
| Cancellation | `RunContextManager.__aexit__` kills all process trees, snapshots `stopped`, restores, writes evidence; exit 130 |

### 2b. Planner and approval (4 days)

| Task | Detail |
| --- | --- |
| Agent | Goal, Scout report, file tree summary, existing contracts → `Plan` |
| `normalise_plan` (code) | Cap 6; remove cycles; compute waves; split slices that share `touches` into different waves; ensure each wave has a visible check |
| `planner = "auto"` | Plan only when the goal has several parts (heuristic first: conjunctions, multiple screens or layers; else one slice) |
| Approval | `interrupt` with plan, contracts, preview, critic findings; CLI renders and resumes; edit loops back to drafting |

### 2c. Worktrees and parallel builders (5 days)

| Task | Detail |
| --- | --- |
| `worktree/manager.py` | `git worktree add` under `.contexer/worktrees/<run>/<slice>`; removal on success; kept on failure for `restore` |
| Ports and data | Free port per slice into `{port}`; `CONTEXER_DATA_DIR` per worktree passed to `[app] env`; documented recipes for SQLite, D1 `--persist-to`, Postgres schemas |
| Fan-out | `Send("build_slice", ...)` per slice in the wave; semaphore from `[agent] parallel` |
| Budget split | Remaining run budget divided across the wave's slices |
| Windows | One Job Object per builder; path length checks for worktrees under OneDrive paths |
| Tests | Two scripted builders editing different files in parallel; one failing slice with a dependant skipped; Ctrl+C during a wave |

### 2d. Integrator and resume (3 days)

| Task | Detail |
| --- | --- |
| Merge | `worktree/merge.py`: merge passing slices in dependency order into `contexer/<run>/integration` |
| Conflicts | One coding-agent turn with the conflicted files and both slices' contracts; snapshot; then re-prove |
| Re-prove | All approved contracts on the integrated tree; failures go to the Diagnoser and one integration repair |
| Resume | SQLite checkpointer in `.contexer/runs/<id>/graph.db`; `contexer run --resume RUN` resets each worktree to its last snapshot, then continues |
| Tests | A forced merge conflict; a slice pair that passes alone and fails together; resume after a killed process |

**0.6 release gate:** PRD G2 and G6 on `bench/features/`; Ctrl+C and resume
tests green on Windows and Linux; one live multi-slice run on BurryAI.

## 5. Phase 3 (0.7): review and hand-off — 8 days

| Task | Days | Detail |
| --- | --- | --- |
| Reviewer agent | 3 | Final diff plus plan → `list[ReviewNote]`; deterministic pre-scan for secrets (regex), `.only`, `console.log`, weakened tests |
| PR layout | 2 | One commit per slice plus contracts; plan table; review notes; high-severity security note → draft PR |
| Issue flow | 2 | Plan and checks in the draft comment; `thread=` in the marker; live status per wave; approval re-runs up to `approve` from the comment (design §6) |
| Bench | 1 | `bench/reviewer/`: 10 diffs with planted issues and 10 clean ones |

**0.7 release gate:** PRD G5; one live PR on a real GitHub repository, opened
by the issue flow and merged without changes requested.

## 6. Testing strategy

| Layer | How |
| --- | --- |
| Agents | Fake provider returning recorded JSON; invalid output, caps, timeouts, masking |
| Routing | Exhaustive table tests of every conditional edge; property test: no path ends worse than the baseline |
| Graph | Scripted coding agents (existing `ScriptedAgent`) for builders; fake agents for crew members; real Chromium for proving, as today |
| Concurrency | Parallel scripted builders, forced conflicts, Ctrl+C mid-wave, resume after kill |
| Benchmarks | Existing seeded-bug suite (must not regress) plus the four new suites |
| Live | Free-tier OpenCode runs on the bench apps; BurryAI at each release |
| CI | Existing workflows; graph tests in a separate job with the `graph` extra |

## 7. Schedule

| Week | Work |
| --- | --- |
| 1 | Phase 0; Scout tools and loop |
| 2 | Scout validation and bench; Critic |
| 3 | Critic bench; Diagnoser; **0.5** |
| 4 | Engine port |
| 5 | Planner, approval, worktrees |
| 6 | Parallel builders, Integrator, resume; **0.6** |
| 7 | Reviewer, PR and issue layout |
| 8 | Reviewer bench, live PR, docs; **0.7** |

About 41 working days including the benchmarks, with buffer in weeks 6 and 8.

## 8. Documentation to update per release

- `docs/architecture.md`: new modules, state, routing, limits.
- `README.md` and `contexer-agent/README.md`: `[agents]`, `--resume`, the
  new run output.
- `docs/try-it.md`: zero-config first run with the Scout.
- `CHANGELOG.md`: each release, with live-run results.
- `docs/multi-agent/*`: mark what shipped, move measured numbers in.

## 9. Definition of done for the whole initiative

- With every agent off, 0.7 behaves like 0.4 and passes its tests.
- No agent output is ever labelled proven; the benchmark false-pass count is 0.
- Each shipped agent met its PRD metric, measured and written in the
  changelog.
- A multi-slice feature on BurryAI went from goal to a merged PR with the
  evidence attached.
