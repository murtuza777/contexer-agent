# Contexer product plan

Status: proposal v2, 2026-10-14. This replaces v1, which targeted non-coders
and was built outward from the existing code. v2 is built from two research
reports:

- [Market research](../../reports/AI%20coding%20workflows%20and%20pain%20points.md):
  how professional engineers and vibe coders ship with AI, what breaks for
  them, and what they pay for.
- [Technical landscape](technical-landscape.md): which repos, protocols and
  designs to build on, borrow from or avoid, and who the competitors are.

Engineering detail per milestone stays in [roadmap.md](roadmap.md), which must
be updated to match this plan once it is approved.

---

## 1. What we are building

**Contexer is the AI software engineer that owns "done".** It sits on top of
the coding agents people already use (Claude Code, Codex, OpenCode) and runs
the whole job around them:

1. It turns a ticket or goal into a plain-English checklist plus executable
   checks, and a person approves it.
2. It has the coding agent build the change against that checklist.
3. It starts the app itself and proves every item in a real browser.
4. It repairs failures in a short, bounded loop, and rolls back attempts that
   made things worse.
5. It hands over a pull request marked "ready for review", with evidence
   attached, and blocks the merge if the proof fails.
6. It keeps every approved checklist and replays it on every later change, by
   any agent or human.

The person makes two decisions per task: **approve what "done" means** and
**merge**. Everything between those two is autonomous.

The one-line strategy, from the technical report: **rent the agents, own the
verdict.** Contexer writes only four things itself: the contract compiler, the
verdict, the repair controller and the evidence report. Everything else is an
existing, maintained dependency.

## 2. Why this, and not something else

### The bottleneck moved from writing code to proving it works

- **Teams can't review fast enough.** Agent pull requests wait 4.6–5.3x longer
  for review and are merged 32.7% of the time, against 84.4% for human ones
  (LinearB, vendor data).
- **Passing tests isn't proof.** METR found that about half of agent PRs that
  pass SWE-bench's tests would still be rejected by maintainers
  ([METR](https://metr.org/notes/2026-03-10-many-swe-bench-passing-prs-would-not-be-merged-into-main/)).
- **Spotify says it directly:** "PR review, not code generation, is now the
  bottleneck."
- **Vibe coders have the same problem in a different form.** They fall into
  fix-break loops that burn credits, and they can't tell whether a fix worked
  or whether something else broke.

### Autonomy follows verifiability

Stripe, Ramp, Spotify and Uber let agents run unattended only where a machine
can check the result: migrations, flaky tests, config changes. The way to make
an AI engineer more autonomous is therefore not a smarter agent loop. It is a
trustworthy oracle for the change in question. That oracle is what Contexer
builds.

### The incumbents grade their own homework, and say so

- Claude Code Review "always completes with a neutral conclusion so it never
  blocks merging" ([docs](https://code.claude.com/docs/en/code-review)).
- A Claude Code Stop hook gives way after 8 consecutive blocks, or when it
  times out.
- OpenAI calls Codex hooks "not a complete enforcement boundary".
- Replit, Lovable and Cursor agents test their own work.

The vendors' own documentation is the argument for putting the authoritative
verdict outside the agent.

### Money exists for checking work, at two specific moments

- **At the merge (teams).** DX found that 85.7% of engineering budget holders
  set aside 2026 money for non-authoring tools, roughly $12–17 per developer
  per month ([DX](https://getdx.com/blog/how-are-engineering-leaders-approaching-2026-ai-tooling-budget/)).
  CodeRabbit ($24–30/dev/month) and Greptile ($30/seat) show that flat seat
  pricing for "check the agent's work" sells.
- **At launch or after an incident (founders).** Rescue agencies advertise
  audits at €450–$3,000 and stabilisation sprints at $2.5k–10k (asking
  prices). Between a $25–100 builder subscription and a $500 audit, nothing
  exists yet.

### What doesn't sell, or gets absorbed

- **Orchestration UIs.** Terragon shut down in February 2026, and Vibe
  Kanban's company in April 2026, because "the vast majority are free users".
- **Review bots.** Every platform now bundles one.
- **Standalone AI testing.** Octomind wound down in mid-2026.
- **Sandbox fleets.** Codex, Claude and Cursor all ship hosted environments.

## 3. Who it is for

**Primary buyer (recommended): small product teams with 2–30 engineers.** They
ship web apps with Claude Code or Codex and have no platform team. Large
companies build their own gates (Stripe, Ramp, Uber), and individual power
users build their own with hooks and scripts. Teams in between buy neutral,
seat-priced tools that attach to the PR. They work on standard web stacks
(Vite/React, Next.js, Supabase), which keeps environment work tractable for a
small team.

**Secondary, as an early revenue test: founders with an AI-built app about to
launch.** That means apps built with Claude Code or Cursor, or exported from
Lovable or Bolt. They pay at a moment (launch, investor demo, first incident)
rather than monthly. The market report warns that people who left app builders
for Claude Code are mostly cost-motivated and not yet earning, so this is a
test, not the foundation.

**Not now:** enterprises with monorepos and custom CI, complete non-coders,
mobile apps.

## 4. What it looks like

### Team flow on GitHub

```text
issue labelled "contexer"  /  "/contexer" comment  /  Spec Kit hook  /  CLI
   │
   ▼
1. CONTRACT     Contexer drafts a plain-English checklist plus executable
                checks, grounded in the live app's UI, and posts it for
                approval                                ◀── human decision 1
   ▼
2. BUILD        snapshot → the team's own Claude Code / Codex implements it
                against the contract (API key; Contexer never resells usage)
   ▼
3. PROVE        Contexer starts the app itself and runs every check in its
                own browser, plus all locked checks from earlier work
   ▼
4. REPAIR       at most 2 rounds: failure bundle → agent → re-prove; keep the
                best attempt, revert regressions, then escalate with a
                specific question
   ▼
5. HAND OFF     PR "ready for review" with two checks, Contexer/acceptance
                and Contexer/regression-replay, linking an evidence report
                (checklist, ✓/✗, screenshots, trace, video, diff, cost)
   ▼
6. MERGE        a human merges; the merge queue replays locked checks only
                                                        ◀── human decision 2
```

Every later PR, from a human or any agent including Copilot, Cursor or Agent
HQ, gets regression replay as a required check.

### Founder flow, local CLI

1. Run `contexer` in the app's repo.
2. Describe what the app must do, or let Contexer draft a checklist from the
   running UI. Approve the checklist.
3. `contexer verify` produces a readiness report: every flow proven or not,
   including login and payments in test mode.
4. `contexer fix` drives the founder's own coding agent through the bounded
   repair loop.
5. The locked checklist replays on every later change. The doom loop stops
   because nothing that used to work can silently break.

### Autonomy levels

| Level | Human does | Contexer does |
| --- | --- | --- |
| **Verify** | Opens a PR or points Contexer at a repo | Proves the change against a checklist and reports, without changing code |
| **Build** | Approves the checklist; merges | Drives the agent, proves, repairs, hands off a ready PR |
| **Pick up work** | Labels issues; approves checklists; merges | Takes labelled tickets end to end, in parallel, within budget |
| **Guard** | Nothing, until a check fails | Replays every locked contract on every PR and in the merge queue |
| **Later, opt-in** | Sets rules for low-risk change classes | Auto-merges where every check is proven and replay is green, *only after measured accuracy supports it* |

## 5. How it is built

The target architecture, with the libraries to use, is in
[technical-landscape.md](technical-landscape.md#the-target-architecture-puts-a-deterministic-controller-around-rented-parts).
In summary:

| Layer | Build on | Contexer writes |
| --- | --- | --- |
| Agent adapters | `claude-agent-sdk` (adapter 1), `openai-codex` SDK with `codex exec --json` as fallback (adapter 2), OpenCode HTTP+SSE (adapter 3), Agent Client Protocol for the long tail | `AgentAdapter` and one `AgentEvent` model; contract injection; inner-gate hooks |
| Running the app | `subprocess` + psutil + Windows Job Objects; Supabase CLI; Stripe CLI test mode; Playwright `storage_state`; E2B optional, later | `AppServer`: detect, start, wait until ready, warm up, keep logs, kill the process tree |
| Proving behaviour | Playwright Python 1.64 (ARIA snapshots, traces, screencast, error capture); pixelmatch; axe-core | The check DSL (exists), verdict labels (exist), deterministic re-location, screenshot baselines |
| Repair and checkpoints | Plain-git snapshot commits through a temporary index, under `refs/contexer/…` | Blueprint state machine, scoring, keep-best, failure signatures, 2-round cap, 7 terminal states |
| Run store | stdlib `sqlite3` (WAL) now; DBOS once there is more than one worker | Schema: runs, steps, evidence, locked checks |
| GitHub | Commit statuses first; then a GitHub App with check runs, via `githubkit` | Check layout, conclusion mapping, hosted evidence report |
| Cost and tracing | OpenTelemetry GenAI conventions; Claude Code's own cost telemetry | Per-run cost ledger and budget enforcement |

The existing code stays: the check DSL, the Playwright runner, the verifier
with proven / LLM-judged / heuristic labels, the criteria compiler and the
static app server. The OpenCode-specific loop in `workflow/loop.py` becomes one
adapter behind the new interface.

### Non-negotiable rules, from the research

- **The agent's word never counts as a pass.** Its self-report is stored next
  to Contexer's verdict, never instead of it. The authoritative diff is
  `git diff` against Contexer's own checkpoint.
- **Three layers of tamper protection.** A `PreToolUse` deny on `.contexer/**`,
  a hash of each approved contract, and a diff guard. Editing a check refutes
  the run, as in claw-orchestrator.
- **Hooks are advisory; the outer loop decides.** A Stop hook runs fast checks
  inside the agent. Contexer always re-verifies outside it.
- **Never report `neutral` to GitHub.** A required check passes on `neutral`,
  so inconclusive results are reported as `action_required`, never as a quiet
  pass.
- **Cache actions, never assertions.** Replays need no LLM, and every
  expectation still re-executes. When re-locating an element, only the target
  may change, never the expected value.
- **Never `git clean -fdx`.** It would delete the untracked `.env` files that
  exported apps depend on.
- **Verdict vocabulary:** `verified` / `refuted` / `unverified`, each labelled
  with how it was reached: `proven`, `LLM-judged` or `heuristic`.

## 6. Competitors, and where we must win

"We verify in a real browser" is no longer distinctive:

- **[claw-orchestrator](https://github.com/Enderfga/claw-orchestrator)** (MIT,
  Node, one maintainer, 591 stars). It already runs acceptance contracts
  itself across five engines, with verified / refuted / unverified verdicts, a
  tamper rule and budget caps.
- **millionco/expect** and **bug0inc/qa-agent** (FSL; do not copy their code)
  and **TestSprite** (cloud). All three sell browser verification of agent
  diffs, using natural-language plans and model-judged assertions.

None of them does these five things, so these are what Contexer must ship and
defend:

1. **Checks compiled from a ticket, approved by a person, readable by a
   reviewer.** A closed check format, not free-form prose.
2. **Honest labels.** Every verdict says whether a browser proved it or a model
   judged it.
3. **Replay without a model.** Locked contracts replay deterministically, and
   failures are never quietly "healed".
4. **Published accuracy.** Catch rate and false-failure rate per verdict label.
   Nobody publishes these.
5. **A merge gate only Contexer can turn green.** GitHub App check runs, with
   the App pinned as the check's expected source.

## 7. Build plan

Sizes: **S** ≈ under a day, **M** ≈ 1–3 days, **L** ≈ a week.

### Phase A — Prove the verifier

**M0. Foundations and de-risking (S–M)**

- Merge `feat/phase4-assertion-verifier` into `main`.
- **Ask Anthropic in writing** whether a local CLI may start the user's
  logged-in, unmodified `claude` through the Agent SDK
  ([terms](https://code.claude.com/docs/en/legal-and-compliance)). Until
  answered, default to API keys.
- Run fixture experiments for the blocking open questions in the technical
  report:
  - Stop-hook timeout behaviour
  - whether Codex hooks fire under `codex exec`
  - OpenCode's event schema
  - Windows process-tree cleanup
  - Vite, Next.js and Supabase start times
- Move git worktree experiments outside the OneDrive-synced folder.
- Add hash-pinned dependency locks.
- Namespace anything shipped as a Claude Code plugin as `/contexer:verify`,
  because Claude Code now has its own `/verify`.

**Done when** each blocking question has an answer, or a recorded default, in
roadmap.md.

**M1. Verifier benchmark (M)**

- Build 6–10 fixture apps: Vite/React, Next.js, a Lovable-style TanStack Start
  app, and one with Supabase login.
- Seed bugs with StrykerJS, limited to the lines the goal touches.
- Add a Web-Bench subset.
- Use inspect_ai as the harness.
- Measure catch rate and false-failure rate per verdict label, across repeated
  runs, using SWE-Lancer's validity rule: every check must pass on good code
  and fail on broken code.
- Run in two modes: saved contracts with no network, and live compilation by
  a model.

**Done when** one command prints the table and the numbers go in the README.
Targets are set after the first measurement, not before.

### Phase B — A loop that works on real apps

**M2. Agent adapters (M)**

- The `AgentAdapter` interface and `AgentEvent` model.
- A Claude Agent SDK adapter:
  - an explicit permission mode plus `allowedTools`
  - `--bare` or `setting_sources=[]` on scripted runs
  - `max_budget_usd`
  - schema-validated output
  - resume
- A Codex SDK adapter with `codex exec --json --sandbox workspace-write` as the
  fallback.
- An OpenCode client generated from its `/doc` OpenAPI spec.
- A `ScriptedAgent` for hermetic tests.
- The three tamper layers.
- A managed AGENTS.md section telling agents that Contexer owns the dev server.

**Done when** M1's tasks run end to end with Claude Code and with Codex, and a
deliberate check edit refutes the run.

**M3. App runtime (M)**

- Start-command detection, in order: `contexer.toml`, then `package.json`
  scripts, then a framework table borrowed from Vercel's data.
- `--strictPort` and explicit host flags.
- Readiness probing with Playwright `webServer` semantics, then route warm-up
  and log capture.
- Kill-on-close Job Objects on Windows; process groups on POSIX.
- Restart between attempts.
- Supabase local with seed data and test users; Stripe CLI test mode;
  `storage_state` for logged-in checks.
- An environment-readiness score before the loop starts.

**Done when** `contexer verify` works with nothing pre-started on the repo's
own Next.js `website/`, on a Vite + Supabase app with login, and on a Lovable
export, on both Windows and Linux.

**M4. Repair controller and checkpoints (M)**

- A blueprint state machine: deterministic steps wrap exactly two agent steps,
  implement and repair.
- Snapshot commits through a temporary index.
- Score every attempt, keep the best, and revert any attempt that scores lower.
- Failure signatures: when one survives a repair, start a fresh session with a
  narrower scope, then escalate with a specific question.
- At most 2 repair rounds by default.
- A trimmed failure bundle for each repair.
- 7 distinct terminal states; stall detection; budget caps.

**Done when** on M1's hard tasks a run never ends worse than its best attempt,
never deletes untracked files, and never retries an identical failure
unchanged.

**M5. Locked contracts and replay (M)**

- A SQLite run store.
- Approval plus a hash on every contract.
- `contexer replay` with zero LLM calls.
- Deterministic element re-location, where only the target may change.

**Done when** a regression in an old feature is caught, and repaired, during
an unrelated new task.

### Phase C — The gate people pay for

**M6a. Report to GitHub without an App (S–M)**

- `contexer verify --report github` sets a commit status.
- A self-contained HTML evidence report, uploaded as a workflow artifact.
- A GitHub Action wrapper that runs after `claude-code-action` or
  `codex-action` in the same workflow.

**Done when** a PR opened by Claude Code in CI gets a failing Contexer status
that links readable evidence.

**M6b. The GitHub App (L)**

- Two check runs, `Contexer / acceptance` and `Contexer / regression replay`.
- Conclusion mapping that never sends `neutral`.
- "Approve checks", "Re-verify" and "Repair" buttons.
- Expected-source pinning on the required check.
- Merge queue: replay only, against the merge-group SHA.
- Webhooks: acknowledge, deduplicate, queue.
- Hosted evidence.
- DBOS once there is more than one worker.

**Done when** on a test repo, only Contexer's App can turn the required check
green, and only with proof.

**M7. Ticket to proven PR (M–L)**

- An issue label or comment starts a run.
- The contract draft is posted for approval.
- An approved run ends in a "ready for review" PR with evidence.
- Distribution:
  - a `contexer-mcp` server so any agent can ask for checks mid-task
  - a mandatory Spec Kit `after_implement` hook
  - a `.github/agents` example
- Linear and Slack triggers come later.

**Done when** a labelled issue becomes a review-ready PR and the human only
approved the checklist and merged.

### Phase D — Expand

- **M8. Founder launch-readiness proof (M).** Functional proof of the key flows
  (sign-up, login, core actions, payments in test mode), presented as one
  report a founder can read. Basic configuration hygiene checks on the
  founder's own project come later. They need their own research pass, which
  this round deliberately left out.
- **M9. Visual checks and locator re-location (M each).** Pixel diffs prove
  that something changed; a vision model judges whether it is acceptable, and
  that verdict is labelled `LLM-judged`.
- **Service phase.** Hosted runs on E2B as an option, and a dashboard showing
  run history: what share of agent work met its contract with no human edits.

### Validation track, in parallel from week 1

Code alone doesn't answer "will they pay". From the start:

- Recruit **5 small product teams and 10 pre-launch founders** as design
  partners. Run Contexer on their real repos as soon as M3 works.
- Watch what they do, not what they say:
  - do they approve the checklists?
  - how often do they edit them?
  - do they complain about false failures?
  - do they keep the check required?
- **Pricing hypotheses to test:**
  - Teams: about $20–30 per developer per month, flat. They bring their own
    agent and API key, and there is no per-run metering, which drew backlash
    when Claude Code Review charged $15–25 per PR.
  - Founders: a per-launch readiness proof, somewhere between a $25–100
    builder subscription and a $500 audit.
- **Packaging hypothesis:** an open-source local CLI for adoption, with the
  paid product being the GitHub App, hosted evidence and run history. This is
  the Argos and Chromatic pattern.

## 8. What we will not build

| Not building | Why |
| --- | --- |
| Our own agent harness | Companies treat agent loops as swappable; we rent them |
| An orchestration UI | Two shutdowns in 2026; vendors bundle it free |
| A sandbox fleet | Codex, Claude and Cursor ship environments; E2B exists |
| A PR review bot | Every platform bundles one |
| An app builder | Lovable and Replit have hundreds of millions in revenue |
| LangGraph or Temporal now | SQLite plus a state enum is enough; DBOS when needed |
| Resold model usage | Users bring their own keys; this also fits Anthropic's terms |

## 9. How we will know it works

| Metric | Why it matters |
| --- | --- |
| Catch rate and false-failure rate per verdict label (M1) | The verifier *is* the product; a noisy gate is worse than none. Spotify removed its LLM judge as "too rigid" |
| Human decisions per task (target: 2, approve and merge) | The definition of "autonomous" |
| Share of runs reaching "ready for review" with no human code edits | Real autonomy, with the denominator nobody publishes |
| Repair rounds and cost per task | The doom-loop and credit-burn pain |
| Locked checks per repo, and regressions caught by replay | Retention: the suite gets more valuable over time |
| Design partners who keep the check *required* after a month | The best early signal of willingness to pay |

## 10. What would kill or reshape this

- GitHub or Anthropic ships a blocking, runtime-verified acceptance gate that
  works across agents. GitHub is the bigger threat: it owns the PR and Agent
  HQ.
- M1 shows a false-failure rate users won't tolerate.
- Design partners won't keep the check required, or founders won't pay before
  an incident (Octomind's lesson).
- Keeping real app stacks runnable costs more than a small team can sustain.
- claw-orchestrator or expect adds human-approved, ticket-compiled checks and a
  GitHub gate first. Speed to M6a matters.

## 11. Decisions for the owner

1. **Primary buyer.** Recommended: small product teams, with founders as a
   revenue test. The alternative is founders first.
2. **Open-source the CLI core.** Recommended: yes. Charge for the App, hosting
   and history.
3. **Write to Anthropic** about running the user's logged-in `claude` from
   Contexer. Only the owner can send this. Until there is an answer, Contexer
   defaults to API keys.
