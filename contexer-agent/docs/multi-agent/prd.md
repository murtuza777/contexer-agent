# PRD: multi-agent Contexer (0.5 → 0.7)

Status: draft, 2026-11-03. Owner: murtuza777.
Design: [design.md](design.md). Business case: [brd.md](brd.md).
Build plan: [build-plan.md](build-plan.md).

## 1. Problem

Contexer 0.4 proves a single change well on apps it can start. It falls short
on the projects people actually have:

1. **Setup is manual.** Multi-service apps (BurryAI: Next.js + a Cloudflare
   Worker + local D1 + Workers AI) need a hand-written `contexer.toml`,
   manual installs and a hand-made sign-in block. Users who fail here never
   reach a first run.
2. **Big goals fail as one turn.** "Recurring expenses that show on the
   timeline" spans a migration, an API route and two screens. One agent turn
   with two repair rounds rarely gets all of it, and the run ends
   `failed_checks` with partial work.
3. **Drafted checks can be weak.** A check that a broken implementation
   would still pass is a false pass waiting to happen. Today only the person
   catches it, at approval, if they read carefully.
4. **Repairs are generic.** The repair prompt is a template of failure
   reports; it does not say *why* (the 500 in the server log, the missing
   column).
5. **Nobody reviews the diff before the person does.** Proven behaviour can
   still ship a leaked key or a disabled auth check.

## 2. Goals

| # | Goal | Measured by |
| --- | --- | --- |
| G1 | A new user on a multi-service repo reaches a first proven run without writing config | Scout writes a working `contexer.toml` for ≥ 8 of 10 test repos |
| G2 | Feature-sized goals finish | On a 10-goal feature set, proven runs rise from the 0.4 baseline by ≥ 30 points |
| G3 | Fewer weak checks | Seeded-bug catch rate of drafted contracts rises with the Critic; false failures stay 0 |
| G4 | Repairs succeed more often | Share of runs that fail attempt 1 and then pass rises vs. the template |
| G5 | Risky diffs are flagged before review | Reviewer flags ≥ 9 of 10 planted security issues, < 1 false high-severity note per run |
| G6 | Small goals cost no more than today | One-slice runs: model requests and wall time within 10% of 0.4 |

## 3. Non-goals

- An LLM deciding pass/fail or when to stop.
- Agents talking to each other freely (chat, swarms, crews).
- Replacing Claude Code, Codex or OpenCode with Contexer's own coding agent.
- Visual design judgement, load testing, mobile viewports (separate work).
- A hosted service (see BRD; CLI and GitHub Action first).

## 4. Users and jobs

| User | Job | What they need from this release |
| --- | --- | --- |
| Solo founder / indie dev | "Build this feature in my real app and tell me honestly if it works" | Zero-config start, feature-sized goals, one PR |
| Engineer on a small team | "Let the agent take tickets, but nothing merges unproven" | Issue flow with plans and slices, reviewer notes, re-proof in CI |
| Tech lead / reviewer | "Review less, trust more" | Per-slice commits, evidence per check, advisory review notes |
| Student / portfolio builder | "Show I can ship with AI agents responsibly" | Readable plans and reports |

## 5. User stories and acceptance criteria

### Scout (0.5)

- **S1.** As a user in a repo without `contexer.toml`, when I run
  `contexer run "GOAL"`, Contexer proposes a config, shows it as a diff, and
  tells me which secrets to add.
  - Writes nothing until the proposed start command reached ready and
    `doctor` passes.
  - Lists external dependencies it could not satisfy (e.g. "Workers AI needs
    `wrangler login`").
  - `contexer init --scout` runs the Scout alone.
- **S2.** As a user, I see the risks the Scout found (committed secrets,
  `.env` not ignored) before anything runs.

### Critic (0.5)

- **C1.** As an approver, I see checks the Critic strengthened, and any
  warnings it could not resolve, next to the checklist.
  - Max 2 Critic rounds; never blocks approval.
  - Uses a second provider when one is configured.
- **C2.** `--no-critic` turns it off.

### Diagnoser (0.5)

- **D1.** As a user watching a failed attempt, I see one line of cause
  ("`POST /expenses` 500: column `is_recurring` missing") before the repair
  starts.
  - The facts in the repair prompt stay verbatim; the diagnosis is added.
  - A missing secret or unreachable external service ends the run
    `needs_human` with the cause, instead of spending repair rounds.

### Planner and parallel builders (0.6)

- **P1.** As a user with a big goal, I approve a plan of slices and their
  checks in one step.
  - 1–6 slices; a one-slice plan skips the Planner's output in the UI.
  - Editing the plan returns to drafting; approval locks all contracts.
- **P2.** Slices in a wave build in parallel, each in its own worktree,
  port and (where possible) database.
  - `[agent] parallel` (default 2).
  - A failed slice does not stop independent slices; dependants are skipped
    and reported.
- **P3.** Ctrl+C stops every builder, restores the project, exits 130.
- **P4.** `contexer run --resume RUN` continues after a crash.

### Integrator (0.6)

- **I1.** After each wave, all approved contracts are re-proven on the merged
  tree. A run is proven only if the integrated tree passes everything.
- **I2.** Merge conflicts get one coding-agent attempt, then `needs_human`
  with both branches kept.

### Reviewer and PR (0.7)

- **R1.** The PR carries advisory review notes with file, line and severity.
  A high-severity security note opens the PR as a draft.
- **R2.** The PR has one commit per slice plus the contracts, and a plan
  table with each slice's checks, attempts and repairs.
- **R3.** The issue flow posts the plan and checks for approval and follows
  the run in one live comment, as today.

## 6. User experience

```text
$ contexer run "Expenses can be recurring; recurring ones show a badge and appear on the Timeline"

Scout        contexer.toml proposed (web :3000, worker :8787, d1 local) · start reached ready in 41 s
             add to .env: BURRY_EMAIL, BURRY_PASSWORD
Plan         4 slices in 3 waves
Checks       14 drafted · Critic strengthened 3 · 1 warning
             ...checklist as today...
Approve these checks? [y/e/n] y

Wave 1       recurring-migration ✓ 2/2 · recurring-api ✓ 3/3 (1 repair: column missing in insert)
Wave 2       recurring-badge-ui ✓ 4/4
Wave 3       timeline-recurring ✓ 5/5
Integrated   23/23 checks proven · 9 existing still pass
Review       2 notes (advisory)
Result       proven · 11 min · $0.84 · PR #57 ready for review
```

Terminal rules stay as today: no boxes, colour only for meaning, aligned
fields, a live activity line.

## 7. Configuration

```toml
[agents]
scout = true            # run when contexer.toml is missing or doctor fails
critic = true
diagnoser = true
reviewer = true
planner = "auto"        # auto: only when the goal looks multi-part; "always" / "never"
parallel = 2            # builders at once
critic_model = ""       # e.g. "anthropic/claude-sonnet-5-5"; empty = drafting model
```

Every agent can be turned off, and with all off Contexer behaves exactly like
0.4.

## 8. Requirements that are not features

| Area | Requirement |
| --- | --- |
| Honesty | No agent output is ever shown as "proven". Verdict labels stay proven / LLM-judged / heuristic |
| Safety | Agents other than builders cannot write source files; builders cannot write `.contexer/**`; no agent gets a GitHub token |
| Bounds | Each agent has a request cap, a time cap and a share of `--budget` |
| Privacy | Prompts carry masked secrets (as today); no tracing to third parties by default |
| Compatibility | Existing contracts, `contexer.toml`, exit codes and the GitHub Action keep working |
| Windows | Worktrees, parallel dev servers and process trees work on Windows as on Linux and macOS |
| Free tier | With OpenRouter free (50 requests a day), a configured one-slice run uses ≤ 3 drafting requests |

## 9. Metrics

- **North star:** proven pull requests merged without changes requested.
- Activation: first proven run within 15 minutes of install, on the user's own repo.
- False-pass rate (proven, but broken): must stay 0 on the benchmark and is
  tracked from user reports.
- Run outcomes by codebase level (basic / hard / extreme).
- Cost and time per proven slice.

## 10. Release plan

| Release | Contents | Gate to ship |
| --- | --- | --- |
| 0.5 | Scout, Critic, Diagnoser on today's single loop | G1, G3, G4 met; benchmark unchanged |
| 0.6 | LangGraph engine, Planner, parallel builders, Integrator, resume | G2 met; Ctrl+C and resume tests pass on Windows and Linux |
| 0.7 | Reviewer, the new PR and issue layout | G5 met; one live PR on a real repo |

## 11. Risks

| Risk | Mitigation |
| --- | --- |
| More agents, more cost, slower small runs | Agents skip themselves when not needed (G6) |
| Parallel builders collide on a shared database | Per-worktree data where possible; otherwise slices run one at a time |
| The Critic makes checks brittle | Benign-change benchmark must stay at 0 false failures |
| Free-tier quotas run out mid-run | Quota checked before start; resume after the limit resets |
| LangGraph API changes | Pin versions; agents and rules stay plain Python behind thin node wrappers |

## 12. Open questions

1. Should the Scout be allowed to run setup commands (installs, migrations),
   or only propose them?
2. Is plan approval one step with check approval, or two?
3. Which second model should the Critic default to on the free tier?
4. Do teams want per-slice PRs instead of one PR per goal?
