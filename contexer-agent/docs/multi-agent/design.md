# Multi-agent Contexer: design

Status: proposal, 2026-11-03. Nothing here is built yet. The current product
(0.4.0) is a single coding agent inside a hand-written loop; see
[architecture.md](../architecture.md). This document describes how Contexer
would work as a multi-agent system on LangGraph, node by node, and which
agentic architecture fits it.

Companion documents: [PRD](prd.md), [BRD](brd.md),
[build plan](build-plan.md), and the single-loop study in
[langgraph-port.md](langgraph-port.md).

## 0. The rule everything else follows

**Agents propose; code and the browser decide.**

Every node below is either an LLM agent that produces a proposal (a config,
a plan, checks, a patch, a repair brief, a review note) or plain code that
decides (prove, score, route, stop, restore). No LLM ever decides that work
is done, that a check passed, or that the loop should continue. The moment an
agent can say "done", Contexer becomes one more tool that grades its own
homework, which is the problem it exists to solve.

```text
Goal or issue → Scout → Planner → Spec writer ⇄ Critic → You approve
   → Builders × N (parallel) → Prover → Rules router ─fail→ Diagnoser → Builders
                                              └pass→ Integrator → Prover (all) → Reviewer → Pull request
```

| Node | Kind | Model | Writes code? | Decides? |
| --- | --- | --- | --- | --- |
| Intake | code | — | no | no |
| Scout | agent | drafting model | `contexer.toml` only | no |
| Planner | agent | drafting model | no | no |
| Spec writer | agent | drafting model | contracts (draft) | no |
| Critic | agent | a different model if available | no | no |
| Approval | person | — | — | yes (what "done" means) |
| Builders | coding agents | Claude Code / Codex / OpenCode | yes, in a worktree | no |
| Prover | code | none | no | yes (verdicts) |
| Rules router | code | none | no | yes (next step) |
| Diagnoser | agent | drafting model | no | no |
| Integrator | code + coding agent for conflicts | coding agent | merge fixes only | no |
| Reviewer | agent | drafting model | no | no (advisory) |
| Pull request | code + person | — | — | person merges |

## 1. How a goal or GitHub issue enters the graph

Three doors, one state shape:

| Door | Today | In the graph |
| --- | --- | --- |
| `contexer run "GOAL"` | goal string | `intake` node with `source="cli"` |
| `contexer run --issue 42` | `issue_goal()` reads title and body | `source="issue"`, `issue=42` |
| Issue labelled `contexer` in Actions | `contexer issue draft` | same, started by the workflow; the run's `thread_id` is written into the draft comment marker |

`intake` is code, not an agent. It:

1. Normalises the goal: title, body, the issue's acceptance criteria if it
   has a checklist, linked issues, and the labels.
2. Treats issue text as **untrusted** (it reaches agent prompts): strips HTML
   comments that imitate Contexer's markers, caps length, and records who
   wrote it.
3. Loads what is already known: `contexer.toml`, approved contracts in
   `.contexer/contracts/`, and the previous run for this issue if one exists.
4. Creates the run: `run_id`, baseline shadow snapshot, `thread_id = run_id`
   for the checkpointer.
5. Routes: no `contexer.toml` or `doctor` failing → **Scout**; config fine →
   **Planner**.

```python
class Goal(TypedDict):
    source: Literal["cli", "issue"]
    text: str
    issue: Optional[int]
    author: Optional[str]
    criteria: list[str]           # checklist items found in the issue body
```

## 2. Scout agent

**Job:** turn an unknown repository into a working `contexer.toml`, so a user
never hand-writes config. This was the slowest part of trying BurryAI.

**Inputs:** the file tree, `package.json` / `pyproject.toml` / lockfiles,
framework configs (`next.config.*`, `vite.config.*`, `wrangler.*`,
`docker-compose.yml`), README, `.env.example`, migrations folders, and the
result of today's `RepositoryInspector`.

**Tools (read-only plus one sandboxed run):** list and read files, grep, and
`try_start(command, port)`, which starts the app with today's `DevServer`,
waits for readiness and returns the log tail. It cannot edit source files.

**Output, validated by Pydantic before use:**

```python
class ScoutReport(BaseModel):
    start: str                    # "npm run dev:all"
    port: Optional[int]           # 3000
    ready_path: str = "/"
    ready_timeout: int = 120
    services: list[str]           # ["next (3000)", "wrangler worker (8787)", "d1 local"]
    setup_steps: list[str]        # ["npm ci --prefix burryai-worker", "npm run d1:migrate:local"]
    auth: Optional[AuthPlan]      # sign-in URL, fields, success signal, secret names
    reset: Optional[str]          # command that puts test data back
    external: list[str]           # ["Workers AI (needs wrangler login)"]
    risks: list[str]              # ["no .env in .gitignore", "auth.json committed"]
```

**Acceptance (code, not the Scout):** the proposed `start` must reach ready;
the proposed `[auth]` steps must sign in with the user's test secrets;
`contexer doctor` must pass. Only then is `contexer.toml` written, and the
person sees it as a diff. If sign-in fails, the Scout gets the failure once
more, then hands over to the person with what it found.

**Limits:** 2 attempts, 120 s per start try, no network beyond localhost.

## 3. Planner agent

**Job:** split a goal that is too big for one agent turn into slices that can
be built, proven and merged independently.

**Output:**

```python
class Slice(BaseModel):
    id: str                       # "recurring-migration"
    goal: str                     # one sentence a builder can act on
    touches: list[str]            # expected paths or areas: ["workers/migrations", "burryai-worker/src/routes/expenses.ts"]
    depends_on: list[str]         # slice ids that must merge first
    user_visible: bool            # can a browser check prove it on its own?

class Plan(BaseModel):
    slices: list[Slice]           # 1..6
    order: list[list[str]]        # waves: slices in one wave run in parallel
```

**Rules enforced by code:**
- At most 6 slices; a one-slice plan is normal and preferred.
- No cycles in `depends_on`; waves are computed, not trusted.
- Two slices in the same wave must not share files in `touches` (they would
  conflict); the code moves one to the next wave.
- Every slice that is not `user_visible` (a migration, a route) must be
  proven through a later visible slice, so each wave ends with at least one
  check a browser can run.

**Example (BurryAI, "recurring expenses on the timeline"):**
wave 1 `recurring-migration` + `recurring-api`; wave 2 `recurring-badge-ui`;
wave 3 `timeline-recurring`.

## 4. Spec writer agent

**Job:** what `workflow/criteria.py` does today, per slice: turn the goal into
plain-English criteria and executable checks in Contexer's check language,
grounded in the app as it is.

**Inputs:** the slice goal, the UI snapshot from `observe` (ARIA tree,
`data-testid`s, placeholders), existing approved contracts, `[auth]`, and the
Critic's notes on the previous draft.

**Output:** a draft `Contract` per slice (status `draft`), plus a `preview`:
the checks run against the current app, so the person sees which already
pass (a check that passes before any change proves nothing new), which fail,
and which cannot run yet.

**Rules enforced by code:** each check must parse in the DSL; each target
must use a real ARIA role; `${NAME}` secrets must exist; each slice needs at
least one check that fails on the current app (otherwise it proves nothing).

## 5. Critic agent

**Job:** attack the drafted checks before a person spends attention on them.
It looks for checks a broken implementation would still pass.

**What it checks for:**
- **Vacuous checks:** `visible` on text that is already on the page,
  `no_errors` alone, a `count min 0`.
- **Missing negative cases:** invalid input, empty state, permissions
  (signed-out user cannot see it), the error path.
- **Missing persistence:** the item appears, but does it survive a reload?
- **Missing regressions:** existing features the slice touches without an
  existing contract.
- **Over-specification:** exact copy or CSS that will break on a harmless
  restyle (false failures).
- **Untestable criteria:** wording that can only ever be LLM-judged.

**Output:** a list of findings, each with a severity and a suggested check.
The Spec writer revises; the loop is capped at 2 rounds, then whatever is
left is shown to the person as warnings next to the checks.

**Why a separate agent:** the model that wrote the checks is the worst judge
of their gaps. Using a different provider or model for the Critic, when the
user has keys for two, makes the critique less correlated.

**How we know it helps:** the seeded-bug benchmark. A Critic is worth keeping
only if drafted contracts with the Critic catch more seeded bugs than without
it, with no rise in false failures.

## 6. Human approval with LangGraph `interrupt`

Approval stays the one human step before work starts. In LangGraph it is a
node that pauses the graph:

```python
from langgraph.types import interrupt

def approve(state: GraphState) -> dict:
    decision = interrupt({
        "kind": "approve_contracts",
        "plan": state["plan"],
        "contracts": [c.model_dump() for c in state["drafts"]],
        "preview": state["preview"],
        "critic": state["critic_findings"],
        "config_diff": state.get("scout_diff"),
    })
    match decision["action"]:
        case "approve":
            return {"approved": lock(state["drafts"], by=decision["by"])}   # sha256, status approved
        case "edit":
            return {"feedback": decision["text"]}                           # routes back to Spec writer
        case "reject":
            return {"terminal": "cancelled", "reason": "Checks rejected"}
```

**Locally:** `contexer run` streams the graph; on the interrupt it prints the
checklist exactly as today and asks. The answer resumes the same thread:

```python
await graph.ainvoke(Command(resume={"action": "approve", "by": user}), config)
```

**On GitHub:** the interrupt payload is posted as the draft comment (today's
format, with `<!-- contexer:draft id= sha256= thread= -->`). The job ends.
When someone with write access replies `/contexer approve`, a new job
verifies the permission and the sha256 (today's checks), then resumes the
thread. Because the two jobs run on different machines, the checkpoint must
live somewhere both can reach:

| Option | Trade-off |
| --- | --- |
| Re-run the graph up to `approve` from the comment (no checkpointer) | Nothing new to host; drafting runs again but is replaced by the approved contract from the comment, so the result is identical. **Recommended first.** |
| Checkpoint uploaded as an Actions artifact, keyed by `thread_id` | No database; artifacts expire (90 days by default) |
| Postgres checkpointer | Real resume; a database and a secret per repository |

**Invariants that do not change:** approval is hashed; a modified contract
never runs as approved; only the workflow's own comment counts; the approver
must have write access.

## 7. Parallel builders with `Send` and git worktrees

**Fan-out:** after approval, a routing function returns one `Send` per slice
in the current wave:

```python
from langgraph.types import Send

def dispatch_wave(state: GraphState) -> list[Send]:
    wave = state["plan"].order[state["wave"]]
    return [Send("build_slice", {"slice_id": s, "base": state["integrated_ref"]}) for s in wave]
```

`build_slice` is a **subgraph**: today's implement → prove → repair loop,
scoped to one slice, with its own state (attempts, snapshots, best, cost).

**Isolation per builder:**

| Resource | How it is isolated |
| --- | --- |
| Files | `git worktree add .contexer/worktrees/<run>/<slice> <integrated_ref>`; each builder works only there |
| Snapshots | the shared shadow repo, refs `refs/contexer/<run>/<slice>/<n>` |
| App | its own `DevServer` on its own free port (`{port}` in `[app] start`) |
| Data | its own local database where the stack allows (SQLite file, D1 `--persist-to` per worktree, a Postgres schema); otherwise `[app] reset` and the slice runs alone |
| Agent session | one coding-agent session per slice; no shared memory |
| Budget | the run budget is split per slice; a slice that overspends stops alone |
| Process tree | one Job Object / process group per builder, all killed on Ctrl+C |

**Concurrency limit:** default 2 builders at once (`[agent] parallel = 2`).
More parallel agents mostly buy rate-limit errors and merge conflicts.

**Fan-in:** LangGraph waits for every `Send` of the wave, then `integrate`
runs. A slice that ended `failed_checks` or `needs_human` does not block the
others from being reported, but its dependants in later waves are skipped.

## 8. Diagnoser agent

**Job:** turn a failed attempt's evidence into a repair brief the coding
agent can act on. Today `repair_prompt()` is a template; the Diagnoser
replaces the "what went wrong" part, never the facts.

**Inputs:** the failure reports (expected vs actual, what the page offered,
uncaught exceptions), the screenshot, the dev-server log tail, the diff of
the attempt, the failure signatures of earlier attempts, and whether the
router reverted.

**Output:**

```python
class RepairBrief(BaseModel):
    cause: str                    # "POST /expenses returns 500: column is_recurring does not exist"
    evidence: list[str]           # the log line, the check id, the file
    likely_files: list[str]
    instruction: str              # what to change, not the code
    fresh_session: bool           # the same failure twice → recommend a new session
    give_up: bool                 # "needs a person": missing secret, external service down
```

**Rules:** the facts in the repair prompt (which checks failed, expected and
actual) are always inserted by code, verbatim; the Diagnoser only adds the
diagnosis. `give_up` is a recommendation: the router turns it into
`needs_human` only when the evidence shows an external cause (missing
secret, sign-in failure, service unreachable).

## 9. The rules router: pass, repair or stop

Plain Python on a conditional edge; the same rules as today's
`RunController`, per slice:

```python
def route_after_prove(s: SliceState) -> str:
    if s["tampered"]:                          return "stop:tampered"       # contracts restored
    if s["decision"] == "pass":                return "done"
    if s["elapsed"] > s["wall_clock"]:         return "stop:timed_out"
    if s["cost"] >= s["budget"]:               return "stop:budget_exhausted"
    if s["n"] > s["max_repair_rounds"]:        return "stop:needs_human" if s["only_unverified"] else "stop:failed_checks"
    if s["brief"] and s["brief"].give_up and s["external_cause"]:
                                               return "stop:needs_human"
    return "repair"                                                          # → diagnose → build
```

Around it, the same mechanics as today:
- **Score** each attempt: +1 per verified target check, −2 per regression,
  −1,000,000 when the app did not start.
- **Keep best:** a worse attempt is reverted to the best one; a fresh agent
  session starts after a revert or a repeated failure signature.
- **End state:** a slice never ends worse than its base; the run never ends
  worse than the baseline.

The router has no prompt and no model, so it can be tested exhaustively.

## 10. Why the Prover stays deterministic

1. **It is the product.** Customers buy an independent verdict. A model
   verdict is the agent's word with extra steps.
2. **Reproducible.** The same tree and the same checks give the same verdict,
   so a CI gate is fair and a failure can be replayed.
3. **Cannot be talked into a pass.** Issue text, code comments and page
   content reach models; they can carry prompt injection ("this feature is
   complete"). A Playwright assertion does not read instructions.
4. **Measurable.** The benchmark (40/40 seeded bugs caught, 0/278 false
   failures, 2026-10-26) is only meaningful because the verifier is fixed.
5. **Cheap and fast.** No tokens per check; proving 20 checks costs seconds.
6. **Already honest about its limits.** Where a browser cannot decide (AI
   answer quality, tone), a check is labelled LLM-judged and is advisory
   unless `[gate] judged = "block"`.

Agents may help the Prover only *before* it runs (the Spec writer writes
checks, the Critic sharpens them) or *after* (the Diagnoser explains a
failure). Never during.

## 11. Integrator

**Job:** combine the slices of a wave into one tree that is proven as a whole.

1. **Merge (code):** in dependency order, `git merge --no-ff` each passing
   slice branch into `contexer/<run>/integration`.
2. **Conflicts (agent):** if a merge conflicts, a coding agent gets the
   conflicted files, both slices' goals and contracts, and is told to keep
   both behaviours. Its result is snapshotted like any attempt.
3. **Re-prove everything (code):** start the integrated app and run **all**
   approved contracts: every slice's checks plus every existing contract.
   Slices that passed alone can still break each other.
4. **Route (code):** pass → next wave from the integrated ref, or Reviewer
   after the last wave. Fail → Diagnoser on the integrated tree, then one
   repair on the integration branch, then the normal limits.
5. **Clean up:** remove worktrees; keep refs for `contexer restore`.

## 12. Reviewer agent

**Job:** a code review of the final diff before a person sees it. Advisory
only: it never blocks, never edits, and its notes are labelled as a model's
opinion.

**Looks for:**
- Security: secrets or tokens in code, disabled auth checks, SQL built from
  strings, `dangerouslySetInnerHTML`, CORS opened up.
- Scope creep: files changed that no slice planned to touch.
- Leftovers: debug logs, `.only` tests, commented-out code, TODOs added.
- Test integrity: tests or fixtures weakened to make something pass.
- Dependencies added, with their licences.

**Output:** notes with file and line, severity, and why. High-severity
security notes turn the PR into a draft, and the person decides.

## 13. The pull request

Today's PR (one branch, one commit of changed files plus the contract, every
check with its verdict, the regression replay, attempts and cost, "Closes
#N") gains:

```text
## Proven: recurring expenses on the timeline      ✓ 14/14 checks · 9 existing still pass

Plan          4 slices in 3 waves
  ✓ recurring-migration   2 checks   attempt 1
  ✓ recurring-api         3 checks   attempt 2 (repair: column missing in insert)
  ✓ recurring-badge-ui    4 checks   attempt 1
  ✓ timeline-recurring    5 checks   attempt 1
Integration   merged cleanly · all 23 checks re-proven on the merged tree

Checks        (per check: verdict, proven / LLM-judged, evidence link)
Regression    9 existing checks re-run · 0 regressions
Critic        3 weak checks strengthened before approval
Review        2 notes (advisory): …
Cost          $0.84 · 11 min · Claude Code + nemotron (drafting)
Config        contexer.toml written by Scout (diff below)
```

One commit per slice (so a reviewer can read them separately), plus the
approved contracts. Proven runs open ready for review; anything else opens as
a draft that says what still fails. The person still merges.

## 14. Which agentic architecture fits Contexer

| Architecture | What it is | Fit for Contexer |
| --- | --- | --- |
| Single agent with tools (ReAct) | One model loops: think, call a tool, observe | What the coding agents already are. Wrong as the outer system: the model would decide when it is done. |
| Prompt chaining | Fixed sequence of LLM steps | Fits drafting (Scout → Planner → Spec writer). Too rigid alone. |
| Routing | A classifier picks a branch | Useful in intake (needs Scout or not), done in code. |
| Parallelisation | Independent subtasks at once, results combined | Fits builders per slice. |
| **Orchestrator-workers** | An orchestrator splits work, workers do it, results are combined | **Core fit**, with the orchestrator split in two: the Planner (agent) proposes slices, code dispatches and merges them. |
| **Evaluator-optimizer** | One part produces, another evaluates and sends feedback until good enough | **Core fit**, twice: Spec writer ⇄ Critic (LLM evaluator, advisory), and Builder ⇄ Prover (deterministic evaluator, decisive). This is today's repair loop. |
| Plan-and-execute | Plan first, then execute steps, re-plan on failure | Fits the Planner plus waves. Re-planning stays limited: at most one re-plan, and only with the person's approval because it changes the contracts. |
| Reflection / self-critique | The same model critiques itself | Weaker than a separate Critic on a different model. |
| LLM supervisor | A model decides which agent acts next | Rejected: routing is the gate's job and must be code. |
| Hierarchical teams | Supervisors of supervisors | Too much indirection for at most 6 slices. |
| Swarm / handoffs | Agents pass control to each other freely | Rejected: no single place where "done" is decided. |
| Group chat (AutoGen-style) | Agents converse until they agree | Rejected: agreement between models is not proof. |
| Role crews (CrewAI) | Role-played agents collaborate on tasks | Rejected: Contexer's builders are external programs, not roles. |
| Blackboard | Agents read and write a shared store | Partly: graph state is the board, but only code writes verdicts to it. |

**Verdict: a deterministic orchestrator-workers graph with two
evaluator-optimizer loops, where the decisive evaluator is code.** In
LangGraph terms: a `StateGraph` whose conditional edges are plain functions,
`Send` for the parallel builders, a subgraph per slice for the repair loop,
`interrupt` for approval, and a checkpointer for resume. Agents are leaf
nodes that return validated Pydantic objects; none of them chooses an edge.

## 15. Graph state

```python
class GraphState(TypedDict, total=False):
    run_id: str
    goal: Goal
    config: Optional[dict]                 # contexer.toml as approved
    scout_diff: Optional[str]
    plan: Plan
    drafts: list[dict]                     # draft contracts
    preview: dict
    critic_findings: list[dict]
    approved: list[str]                    # contract ids, locked
    wave: int
    integrated_ref: str                    # shadow commit the next wave starts from
    slices: Annotated[dict[str, dict], merge_dicts]   # SliceState per slice, written by parallel branches
    review: list[dict]
    cost_usd: Annotated[float, operator.add]
    terminal: Optional[str]
    reason: str
```

Live objects (agent adapters, dev servers, Chromium, the shadow repo) stay in
the runtime context, as in [langgraph-port.md](langgraph-port.md) §3.

## 16. Failure modes and what happens

| Failure | Handling |
| --- | --- |
| Scout cannot start the app | 2 tries, then `needs_human` with the log and what it tried |
| Planner returns an invalid plan | Code repairs what it can (cycles, overlaps), else one slice = the whole goal |
| Critic and Spec writer disagree forever | 2 rounds, then warnings shown at approval |
| A builder edits a contract | Restored, slice ends `tampered`, the run continues for other slices but is reported tampered |
| Two builders conflict on merge | Integrator agent once, then `needs_human` with both branches kept |
| Rate limit or free quota hit | The slice stops; the run reports which slices finished and the resume command |
| Ctrl+C | Every builder's process tree killed, worktrees kept, project restored to the last integrated ref or baseline, exit 130 |
| Crash or closed laptop | `contexer run --resume RUN`: checkpointed state, worktrees reset to their last snapshot, continue |
| Prompt injection in an issue | Approval of the checks is still human; agents have no GitHub token; only code pushes |

## 17. What it costs

Rough per-run model calls for a 3-slice feature, beyond the coding agents
themselves: Scout 1–3 (only on first use), Planner 1, Spec writer 3–6,
Critic 2–4, Diagnoser 0–6, Reviewer 1. That is about 10–20 drafting-model
requests, against 1–2 today, which matters on OpenRouter's free tier
(50 requests a day). The coding agents dominate cost either way; parallel
builders spend the same tokens sooner, not fewer.

For a one-slice goal on a configured repo the graph must cost no more than
today: Scout and Planner are skipped, the Critic runs once, and there is one
builder.
