# Contexer technical plan

This is the build plan for [product-plan.md](product-plan.md) v2. It covers
module layout, data formats, the CLI, the order of work, and how each piece is
tested. [technical-landscape.md](technical-landscape.md) holds the research
behind each library choice.

Status legend: **done**, **building**, **next**, **later**.

---

## 1. Principles

1. **Rent the agents, own the verdict.** Contexer writes four things: the
   contract, the verdict, the repair controller and the evidence. Everything
   else is a dependency or an adapter.
2. **The agent's word never counts.** A turn's "success" is recorded but never
   used as a pass. The diff that matters is the one Contexer computes against
   its own snapshot.
3. **Deterministic code owns control flow.** Agents are two nodes, implement
   and repair, inside a state machine that Contexer writes and tests.
4. **Replays need no model.** Once approved, a contract runs with zero LLM
   calls.
5. **Fail safe.** Anything inconclusive blocks; nothing reports a quiet pass.
6. **Measured before claimed.** No accuracy claim without the benchmark.
7. **Few dependencies.** Prefer the stdlib (sqlite3, subprocess, ctypes,
   tomllib) over new packages, and pin whatever is added.

## 2. Architecture

```text
contexer verify | contract | replay | run | bench | report        (Typer subcommands)
   │                                                    REPL (/loop, /verify) stays
   ▼
contract/      Contract model, file store, hashing, approval; compiles goals via
               workflow.criteria.GoalAnalyzer
appserver/     detect start plan → DevServer (spawn, ready, logs, kill tree)
               or StaticAppServer
verification/  check DSL, Playwright runner (+ screenshots, traces), verifier,
               verdicts
agents/        CodingAgentAdapter: claude_code, opencode, scripted (codex next)
checkpoint/    shadow-git snapshots: snapshot / restore / diff
controller/    run state machine: implement → verify → repair, keep-best,
               signatures, budgets
store/         sqlite run store (.contexer/contexer.db)
evidence/      run directory layout + self-contained HTML report
github/        commit status + step summary (check runs come with the App)
bench/         seeded-bug benchmark: catch rate and false-failure rate
```

The existing `workflow/loop.py` (`AutonomousLoop`) keeps serving the REPL until
the controller replaces it (C3). `workflow/criteria.py` remains the goal→check
compiler.

## 3. Data formats

### `.contexer/` inside the target project

```text
.contexer/
  contracts/<slug>.json   approved contracts; commit these alongside the code
  runs/<run-id>/          evidence: report.html, result.json, screenshots,
                          traces, server.log (gitignored)
  shadow.git/             private snapshot repository (gitignored)
  contexer.db             run store (gitignored)
  .gitignore              written by Contexer: everything except contracts/
```

### Contract file

```json
{
  "version": 1,
  "id": "todo-complete",
  "goal": "Users can complete a task and the remaining count updates",
  "summary": "...",
  "criteria": [ { "id": "crit-1", "description": "...", "verification_method": "interactive_test",
                  "check": { "steps": [...], "expect": [...] } } ],
  "source": "llm | user | rules",
  "created_at": "2026-10-15T10:00:00Z",
  "approval": { "by": "murtuza777", "at": "...", "sha256": "..." }
}
```

- `sha256` covers the canonical JSON of `goal` and `criteria`.
- A contract whose current hash differs from its approval hash is **modified**.
  It is never run as approved, and the gate reports it as needing action.
- `approval: null` means the contract is a draft.

### `contexer.toml` (optional, project root)

```toml
[app]
start = "npm run dev"      # default: detected from package.json
port = 5173                # default: a free port
ready_path = "/"
ready_timeout = 120
install = true             # install dependencies when node_modules is missing

[gate]
judged = "advisory"        # or "block"

[agent]
name = "claude-code"       # claude-code | opencode | scripted
max_repair_rounds = 2
budget_usd = 3.0
```

### Verdicts

| Verdict | Meaning | Method labels |
| --- | --- | --- |
| `verified` | All expectations held | `proven` (browser) / `judged` (LLM) / `heuristic` |
| `refuted` | An expectation was observed to fail | same |
| `unverified` | A step couldn't act, or nothing could decide | — |

**Gate conclusion:**

- `pass`: every approved check is `verified` and `proven`.
- `fail`: any proven check is `refuted`.
- `needs_action`: anything `unverified`, a contract that is modified or still a
  draft, or a judged check refuted while `judged = "block"`.

Judged criteria are advisory by default, because noisy judges get removed
(Spotify).

### CLI exit codes

| Code | Meaning |
| --- | --- |
| `0` | pass |
| `1` | fail |
| `2` | needs action |
| `3` | Contexer or environment error, e.g. the app didn't start |

## 4. Milestones, in build order

### C0. Foundations — done

- Phase 4 merged into `main` (PRs #1 and #2).
- This plan.

### C1. Contracts, a non-interactive CLI, and evidence — building

**Contract store** (`contract/`):

- the model, canonical hashing, load/save/list
- `approve()` records who approved and the hash
- a modified-contract check

**Subcommands:**

| Command | What it does |
| --- | --- |
| `contexer verify [GOAL] [--contract F...] [--all] [--url U] [--dir D] [--report html,github] [--json]` | With a goal: compile a draft contract, then run it. With `--contract` or `--all`: run saved contracts with no LLM. |
| `contexer contract draft GOAL` / `show` / `approve ID` / `list` | Manage contracts |
| `contexer replay` | `verify --all`, for CI |

The REPL starts only when no subcommand is given.

**Evidence:**

- The runner saves a screenshot per check after its expectations run, and on
  failure.
- Playwright tracing is optional (`--trace on-failure`).
- `evidence/report.py` writes a single self-contained `report.html`:
  - the checklist with a verdict and method per item
  - expected vs actual
  - screenshots inlined as data URIs
  - page errors and the server log tail
  - the run's metadata
- `result.json` holds the machine-readable result.

**Done when:**

- `contexer verify --contract` runs a saved contract against a static app with
  zero LLM calls.
- It exits 0, 1 or 2 correctly.
- The HTML report opens and shows a screenshot for every check.

### C2. App runtime — next

**`appserver/detect.py`** decides how to start the app:

1. `contexer.toml` wins.
2. Otherwise read `package.json` scripts: `dev`, then `start`.
3. The package manager comes from the lockfile: pnpm, yarn, bun, else npm.
4. Port flags come from the framework:
   - Vite: `--port N --strictPort --host 127.0.0.1`
   - Next.js: `-p N -H 127.0.0.1`
   - anything else: the `PORT` environment variable

Static projects keep `StaticAppServer`.

**`appserver/devserver.py`** runs it:

- Spawns the command with a merged log thread writing to `server.log` and a
  ring buffer.
- On Windows, a kill-on-close Job Object (ctypes) so stopping takes down every
  descendant. On POSIX, a new session and `killpg`.
- A readiness probe with Playwright `webServer` semantics: 2xx, 3xx and
  400–403 count as ready. It probes both `127.0.0.1` and `localhost`.
- If the process exits early, it reports the last log lines.
- If the expected port never answers, it falls back to a URL parsed from the
  logs.
- Dependencies are installed automatically when `node_modules` is missing.

**Done when:**

- `contexer verify --dir website` (Next.js) works with nothing started
  beforehand.
- No `node` process is left running afterwards, checked on Windows.

### C3. Benchmark — next

**Layout:**

```text
bench/fixtures/<app>/
  app/                  the good version
  bugs/<id>/            file overlays, one realistic bug each
  bugs/<id>/BUG.md      what the bug is, and which criterion should catch it
  contract.json         approved contract
```

**Runner** (`contexer bench`):

- For each app, run the contract against the good version N times (default 3).
  Any refuted or unverified check there counts as a false failure.
- Run it once against each bug variant. The bug is **caught** when some proven
  check is refuted, and **flagged** when a check is only unverified.
- `--live` also compiles a contract from the app's goal with the LLM and scores
  it the same way. This measures the compiler, not just the runner.

**Validity rule:** every check in a fixture contract must pass on `app/`. The
benchmark refuses to score a contract that fails it.

**Done when:**

- `contexer bench` prints catch rate, flag rate and false-failure rate, per app
  and in total.
- The numbers go in the README.

The first fixtures are static apps, which keeps the benchmark hermetic and
fast. Vite and Next.js fixtures follow C2, and StrykerJS-generated mutants
follow later.

### C4. Agent adapters — next

**`agents/base.py`:**

- `CodingAgentAdapter.start(workdir) -> AgentSession`
- `send(session, prompt, *, timeout, budget_usd) -> AgentTurn`, where
  `AgentTurn` has `status`, `summary`, `cost_usd`, `session_id` and `events`
- `close()`

**`agents/claude_code.py`:**

- Runs `claude -p --output-format stream-json --verbose`, parsing the NDJSON
  `result` line.
- `--permission-mode acceptEdits` with explicit `--allowedTools`.
- `--disallowedTools "Edit(.contexer/**)" "Write(.contexer/**)"` as tamper
  layer 1.
- `--max-budget-usd`, and `--resume` for repair turns.
- Locally it runs the user's own logged-in, unmodified `claude`. Contexer never
  reads tokens; API keys apply in CI.

**Other adapters:**

- `agents/opencode.py` wraps the existing client.
- `agents/scripted.py` applies canned file writes per turn, for hermetic loop
  tests.
- `agents/codex.py` (`codex exec --json --sandbox workspace-write`) comes once
  the Codex CLI is available to test against.

**Done when:**

- The scripted adapter drives the controller tests.
- A live Claude Code turn implements a fixture task.

### C5. Checkpoints and the repair controller — next

**`checkpoint/`** is a shadow git repository at `.contexer/shadow.git`, with
the work tree set to the project:

- It works for directories that aren't git repositories and never touches the
  user's refs.
- `info/exclude` covers `.contexer/`, `node_modules/`, `.next/`, `dist/` and
  `.venv/`.
- `snapshot()` runs `add -A` then `commit-tree`, saving to
  `refs/contexer/<run>/<n>`.
- `restore(sha)` snapshots the current state first, then
  `read-tree -u --reset sha`. Files created since the snapshot are removed, and
  ignored files such as `.env` are never touched.
- `changed_paths(a, b)` lists what changed between two snapshots.

**`controller/run.py`:**

- States: `compiling → awaiting_approval → implementing → verifying →
  repairing(n)`.
- Terminal states: `succeeded`, `failed_checks`, `budget_exhausted`,
  `timed_out`, `stalled`, `cancelled`, `needs_human`, `error`.
- Score each attempt by verified proven checks, counting regressions in other
  locked contracts double. Keep the best attempt; restore it whenever an
  attempt scores lower, and at the end of the run.
- A failure signature per check is a hash of (check id, expectation, actual,
  first page error). When a signature survives a repair, the next round uses a
  fresh agent session focused on that check. After that, escalate as
  `needs_human` with the failure bundle.
- Each repair gets one failure bundle: the failing checks as expected vs
  actual, the first page errors, the screenshot path and the server log tail,
  all trimmed.
- The tamper guard refutes the run if the agent changed `.contexer/**`.
- Defaults: at most 2 repair rounds, a USD budget and a wall-clock budget.

**`contexer run GOAL|--contract ID [--agent claude-code] [--yes]`:**

1. Compile, or load the contract.
2. Approve it, prompting unless `--yes` is given.
3. Snapshot, then implement.
4. Start the app and verify, including regression replay of every other
   approved contract.
5. Repair, then report.

**Done when:**

- With the scripted agent, a run that regresses goes back to its best attempt.
- A repeated signature changes strategy.
- `.env` survives a restore.
- A live Claude Code run fixes a seeded bug in a fixture.

### C6. Run store — later in this pass

- `.contexer/contexer.db` (sqlite3, WAL), with tables `runs`, `attempts` and
  `evidence`.
- `contexer runs` lists runs; `contexer runs show ID` shows one.
- DBOS waits until there is more than one worker.

### C7. GitHub reporting — next after C5

**`github/status.py`:**

- Sets a commit status `contexer/acceptance` through the REST API (httpx,
  `GITHUB_TOKEN`). Statuses have no `neutral`; `needs_action` maps to
  `failure` with a clear description.
- Writes a markdown summary to `$GITHUB_STEP_SUMMARY`.
- The repo and SHA come from the Actions environment or from git.

**A root `action.yml`** (composite action) installs Contexer and Playwright,
runs `contexer replay --report github,html` and uploads `report.html`.

**Done when** a PR on a test repository shows a failing `contexer/acceptance`
status that links to the report.

### Later (product-plan Phases C and D)

- The GitHub App, with check runs that are never `neutral`, an "approve checks"
  button, expected-source pinning and merge-queue replay.
- Ticket-to-PR triggers.
- A `contexer-mcp` server and a Spec Kit hook.
- Visual checks; deterministic re-location of moved targets.
- The founder readiness report.
- Hosted runs on E2B.

## 5. Testing strategy

- **Unit tests:** the DSL, hashing, detection, the conclusion mapping and
  signatures.
- **Hermetic integration:**
  - static fixture apps through the real Playwright runner
  - the scripted agent through the real controller
  - shadow git against a temporary directory
- **Opt-in live tests**, marked `live`:
  - a Claude Code turn
  - OpenRouter compilation
  - a Next.js dev server

  The default run never needs the network.
- **Command:** `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
  --deselect tests/test_opencode_integration.py::test_live_opencode_e2e`
- Every milestone is exercised by running the real CLI on a real app, and its
  output and report are inspected before committing.

## 6. Deferred, with triggers

- **LangGraph and Temporal:** not needed for a bounded, mostly linear state
  machine. Revisit when runs fan out across workers, or must pause for days and
  resume elsewhere.
- **The keyword heuristic verifier:** retire it once the judged path has a
  retry. Until then it stays labelled `heuristic` and can never pass a gate.

---

## Done: Phase 4, executable acceptance checks (2026-10-13)

Verification used to be an LLM opinion of about 3,500 characters of HTML. It is
now a closed check DSL (`verification/checks.py`) executed in fresh Chromium
contexts (`verification/runner.py`):

- Expectations auto-retry, and error accounting runs last.
- Each verdict is labelled with how it was reached
  (`verification/verifier.py`).
- Checks are compiled from the goal and grounded in the live ARIA snapshot
  (`workflow/criteria.py`).
- The coding agent receives the checks verbatim as its contract, and repair
  prompts restate expected vs actual.
- Static projects are served over HTTP; `/verify` runs without a coding agent.

Live findings at the time:

- Every reply from an instruction-following model produced schema-valid checks.
- The failures came from model routing (`openrouter/free`).
- A todo app whose "Complete" button throws `refesh is not defined` passed 4/4
  in its correct version. The buggy version failed with `expected "0", actual
  "1"` plus the exception, a bug no page snapshot could reveal.
