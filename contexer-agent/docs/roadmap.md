# Contexer engineering roadmap

Contexer's claim is that the agent that writes the code should not be the one
that decides whether it works. Each phase below is judged by how much it
strengthens that claim, or how much it widens where the claim applies.

| Phase | Status | Recommendation |
| --- | --- | --- |
| 1. Housekeeping | Done | — |
| 4. Structured assertion verifier | **Done** | See below |
| 3. Coding-agent abstraction | Next | Do now: the loop depends on a single, currently flaky executor |
| — Dev-server lifecycle (new) | After 3 | Needed before the loop can run on Node/Python apps unattended |
| 5. Run persistence | After that | Pair it with replaying saved checks as regression tests |
| 2. Domain realignment | Fold in | Move code when a phase touches it; no standalone reshuffle |
| 6. LangGraph state machine | Defer | Revisit only on the triggers listed below |

Sizes: **S** ≈ under a day, **M** ≈ 1–3 days, **L** ≈ a week.

---

## Phase 4 — Executable acceptance checks (done)

**Problem.** Verification never interacted with the app. An LLM read about
3,500 characters of HTML and gave an opinion. Without an LLM, keyword matching
passed "add to cart updates the counter" whenever a `$` appeared on the page.
The product's central promise was not actually being kept.

**What shipped**

- `verification/checks.py`: a small, closed DSL. A criterion's `check` has
  `steps` (click, fill, press, select, check, hover, goto, wait) and
  `expect`ations (visible, hidden, count, text, value, attribute, css, url,
  title, no_errors) with `equals` / `contains` / `matches` / `changed`
  comparators. Locators prefer role + accessible name, then text, label,
  placeholder, `data-testid`, and CSS last. Invalid model output is rejected
  per criterion rather than half-executed.
- `verification/runner.py`: runs each check in a fresh Chromium context.
  Expectations auto-retry. Error accounting is evaluated last, so exceptions
  thrown asynchronously by an interaction are counted. When elements are
  duplicated for responsive layouts, the visible one is used.
- `verification/verifier.py`: checks decide the criteria they cover. Only
  criteria without a check go to the LLM judge, or to heuristics when no LLM
  is configured. Each `CriterionResult.method` is `assertion`, `judgment` or
  `heuristic`.
  - Confidence is 1.0 only for a *reproduced* failure.
  - A check whose step could not find its target is `blocked`: inconclusive,
    confidence 0.5. It records the page's locator vocabulary at that moment.
- `workflow/criteria.py`: the LLM compiles the goal into checks. For existing
  apps, the prompt includes the live ARIA snapshot plus a bounded excerpt of
  the entry-point source, used **only** to locate elements. Expected behaviour
  must come from the goal.
  - The analyzer retries once when fewer than half the criteria are
    executable.
  - A `no_errors` runtime check is always present.
- Contract-first loop: the coding agent receives the checks verbatim. Repair
  prompts restate the failing checks with expected vs. actual values.
- `workflow/app_server.py`: static projects are served over HTTP instead of
  `file://`, which broke ES modules and `fetch`.
- `/verify <goal>`: the same verification, without a coding agent.
- Fixes found along the way:
  - Console warnings were counted as errors.
  - Every screenshot was saved as `observation_15.png`.
  - Rich swallowed `[crit-1]` and `[data-testid=…]` as markup.
  - `Verifier()` silently created an LLM client from `.env`, which made the
    "deterministic" tests call OpenRouter. The 271 pre-existing tests went
    from 79 s to 38 s.

**Measured with the live `openrouter/free` model.** These are small samples
and should be treated as indicative only.

- Every reply that came from an instruction-following model produced 100%
  schema-valid checks: 4 of 4 replies across two probes.
- The failures were routing failures. The router sometimes picks a model that
  answers `"User Safety: safe"` (a safety classifier) or wraps JSON in prose
  that itself contains braces. The second case is fixed by the parser. The
  first is mitigated by one retry, and pinning a specific model avoids it
  entirely.
- On a todo app whose "Complete" button throws `refesh is not defined`: the
  correct version passed 4/4 proven, and the buggy version failed with
  `expected "0", actual "1"` plus the uncaught exception. Nothing is wrong at
  page load, so snapshot-based verification could not have seen this bug.

**Known limitations**

- Elements created only after an interaction are located from source,
  so locators guessed for apps with no readable front-end source can be
  `blocked`.
- Criteria such as "looks modern" still rely on LLM judgment of a text
  snapshot.

## Phase 3 — Coding-agent abstraction (next, M)

**Why now.** The loop only works when OpenCode is running and its free model
behaves. In this environment `test_live_opencode_e2e` fails for that reason.
A second executor de-risks every demo and every future phase.

**Design**

- `contexer/agents/base.py`: a protocol covering what the loop actually uses,
  `start(workdir, title) -> AgentSession` and
  `send(session, prompt, timeout) -> AgentResult(status, summary, error, duration)`.
  Neutral types replace `OpenCodeSession` / `OpenCodeExecutionResult` in
  `workflow/`.
- **Contexer computes diffs itself.** Snapshot the workspace with git (a
  temporary index, or `git stash create`) before each `send`, then diff after.
  Don't trust an agent's self-reported diff; this is the same independence
  argument as verification, and it makes every adapter cheaper.
- Adapters:
  - `OpenCodeAgent`: the existing client, moved behind the protocol.
  - `ClaudeCodeAgent`: headless `claude -p --output-format json`, with
    `--resume <session_id>` for repair turns and an edit-only permission mode
    scoped to the target directory.
  - `ScriptedAgent`: applies canned file edits, for hermetic end-to-end
    tests of the full loop.
- Select with `CONTEXER_CODING_AGENT=opencode|claude-code` and `/agent`.

**Done when** `/loop` passes the todo-app scenario end to end with each real
adapter, and the loop test suite runs on `ScriptedAgent` with no network
access.

## Dev-server lifecycle (new, M)

**Why.** Static projects are served automatically. Everything else needs the
user to start a dev server by hand and pass `--url`, so `/loop` cannot run
unattended on the repo's own Next.js `website/`.

**Design.** `workflow/app_server.py` gains a `DevServer` that:

- picks the command from `package.json` scripts (`dev`, then `start`) or the
  Python entrypoint
- assigns a free port through `PORT` and the framework's CLI flag
- waits for HTTP readiness while streaming logs
- terminates the whole process tree on exit (`taskkill /T` on Windows,
  process groups on POSIX)
- restarts between repair attempts if the server died, and surfaces its last
  log lines as evidence, because build errors are the most common failure

**Done when** `/verify "…" --dir website` works with no server running
beforehand.

## Phase 5 — Run store and regression replay (M)

**Design**

- `.contexer/runs.db`, using stdlib `sqlite3` with no new dependency. Tables:
  - `runs`: id, goal, project, url, started, finished, passed, analysis JSON
  - `attempts`: run_id, n, verification JSON, diff, screenshot path
- Pydantic models already serialise everything that needs storing.
- `/runs`: list runs. `/runs show <id>`: replay the transcript.

**The feature that justifies this phase: `/verify --replay <id|all>`.** Every
goal Contexer has completed leaves behind an executable contract. Replaying
those contracts against the current app turns past work into a regression
suite at no extra cost. The same store also gives the repair engine memory of
what was already tried.

**Done when** a completed run can be replayed after a code change and reports
exactly which old checks now fail.

## Phase 2 — Domain realignment (fold in, S each)

The `intent/`, `planner/` and `tasks/` packages are empty placeholders. The
real homes already exist:

- `verification/` holds the contract
- `workflow/` holds orchestration
- Phase 3 adds `agents/`

Moving files to match a target layout is churn: it creates merge conflicts and
delivers nothing to users. Delete the empty packages, and move
`workflow/criteria.py` into `intent/` only when intent handling grows real
behaviour, such as multi-goal decomposition.

## Phase 6 — LangGraph (defer)

The loop is a bounded, mostly linear state machine:
inspect → criteria → plan → execute → (observe → verify → repair) × N.
LangGraph would add a large dependency tree and a second state paradigm, plus
checkpointing that Phase 5's run store already provides for this shape. Pause,
resume and human-in-the-loop interrupts can be built from an explicit
`RunState` enum persisted in `runs.db` in a few hundred lines.

Revisit if any of these become true:

- runs fan out into parallel sub-goals
- several coding agents collaborate on one run
- runs need to wait days for a human and resume elsewhere

## Verifier follow-ups (from Phase 4 findings)

- **Retire the keyword heuristic (S).** In a live run it failed a correct
  criterion because the page did not contain the words "where" and "users". If
  the LLM judge is unavailable, retry it once, and otherwise mark the
  criterion `unverified` (neither passed nor failed) rather than guess. Several
  existing tests encode the heuristic and will need rewriting.
- **Self-healing locators for `blocked` checks (M).** Re-ground a blocked
  check against `ui_at_failure`, the page as it was when the step failed, and
  run it once more. Weakening must be impossible by construction: code
  verifies that only `target` fields changed, and that actions, expectation
  kinds, comparators and values are identical.
- **Visual checks (M).** Add `{"kind": "visual", "describe": "…"}`, judged by
  a vision model against the screenshot and labelled `judgment`. This covers
  "looks modern" style criteria without pretending they are proven.
- **Windows piped output (S, pre-existing).** Rich raises
  `UnicodeEncodeError` on `●` and `✓` when stdout is a cp1252 pipe. Use the
  `_can_encode` fallbacks from `cli/ui.py` in the loop's output too.
