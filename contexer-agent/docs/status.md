# Status

What works, what was measured, what is not proven and what comes next. This was the lower half of the
front page until 2026-11-28; the front page now carries a summary.

## What works today

Version 0.7.0. What works today, with about 1,650 tests and CI:

- **`contexer test`**: an agent uses the running app against what you said
  it should do; every finding is replayed by code; a fix prompt names the
  cause in the code. `--again` replays the saved checks with no model.
- **`contexer run`**: what was understood and the checks, for you to
  approve; the coding agent builds; every check is proven in Chromium;
  failures go back with what the browser saw; an attempt that makes things
  worse is undone; the diff of a passing run is read once. It can wait for
  an answer, be stopped with Ctrl+C, and continue with `--resume`.
- **Seven agents of Contexer's own**, on any of 15 providers with your key:
  Intent, Planner, Tester, Challenger, Triage, Diagnoser and Reviewer. None of them decides
  whether the work is done. With no model configured, fixed rules decide
  each next step and the run still works.
- **Limits you set**: repair rounds, one budget in dollars for the coding
  agent and Contexer's agents together, a model and a step cap per agent.
  A run says what it can cost at most before it starts.
- **Coding agents**: Claude Code, Codex and OpenCode.
- **Your app**: static files, Vite, Next.js, or a start command in
  `contexer.toml`; apps behind a login (`[auth]`, secrets masked in all
  evidence); apps that keep data on a server (`[app] reset`).
- **GitHub**: the merge gate, a pull request with the evidence (`--pr`), and
  the issue workflow (label an issue, `/contexer approve`).
- **Safety**: approved checks are hashed and an agent that edits them has
  its run refuted; every attempt is snapshotted and can be restored; text
  from a page, an issue or a model is quoted as data, never followed; a
  change that adds a secret is never pushed.

**Live runs** (2026-11-19, Claude Code, Contexer's agents on Azure
`gpt-5.4`), on [HealthCare.Ai](https://github.com/murtuza777/HealthCare.Ai),
a React and Cloudflare Worker app Contexer had never seen:

| Run | Outcome |
| --- | --- |
| `contexer test` on the public pages | No confirmed bugs, 5 working behaviours confirmed, 1 question |
| `contexer run --pr`, one screen | 1 attempt, 3 of 3 checks, $0.85, 4 minutes |
| `contexer run --pr` behind sign-in, frontend and Worker, first try | **Failed**: the test account stopped at a consent screen, and $6.26 was spent before the run ended |
| The same change, second try | 2 attempts, 4 of 4 checks, $3.35, 7 minutes. The review found that the agent had removed a delete confirmation to make a check pass |

The failed run is why a sign-in is now tried before anything is spent.

**Measured** on the seeded bugs
([results](../bench/RESULTS.md)): replaying hand-written checks
catches 40 of 40 with no false failure. The Tester, from a one-line intent,
finds 25 of 40 on the seven apps it was developed on and 3 of 6 on an app
written afterwards; that app first showed two false alarms in four runs,
and none after a rule in code was added for them. A coding agent driven by
Contexer (OpenCode on `gpt-5.4`) fixed 46 of 46. The Reviewer flagged 10 of
10 planted problems and raised one false high-severity note on 10 clean
diffs.

Honest gaps:

- **Not run with Codex against a real account.** The issue workflow has not
  been run against a real GitHub issue. On macOS the tests that start no
  browser run in CI; the benchmark missed one seeded bug there on
  2026-11-26 and has not been run again since the fix.
- **The checks of the live runs were approved with `--yes`**, not read by a
  person first. The removed confirmation above is what that costs.
- **Web apps only**, in Chromium. No visual-design checks. Sign-in sessions
  kept only in `sessionStorage` are not carried into checks.
- **Project skills show no saving.** Over twelve runs the Tester took as
  many steps with saved skills as without
  ([phase-2](agentic/phase-2.md)).
- **One model was measured** for Contexer's agents (`gpt-5.4`). A cheaper
  model per agent is a setting, and its effect is not measured.
- The budget cannot stop a coding agent in the middle of a turn, so one
  turn can overshoot it.
- The rest is in
  [readiness.md](agentic/readiness.md).

## What is next

In order, and why, in
[launch.md](agentic/launch.md):

| Next | What it is for |
| --- | --- |
| The agent set-up run in Codex and OpenCode | `contexer init --agent` is built (the agent calls Contexer itself and is told what failed); it has been run in Claude Code only |
| A trace in the pull request | Something a reviewer can open without your machine. The screenshots are built (`--pr --screenshots`); a trace is never pushed |
| More agents, each measured before it ships | An access prober. The regression guard, the dependency checker and the scope guard are built |

How 0.5.0 was built, phase by phase with tickets and results:
[0](agentic/phase-0.md),
[1](agentic/phase-1.md),
[2](agentic/phase-2.md),
[3](agentic/phase-3.md),
[4](agentic/phase-4.md),
[5](agentic/phase-5.md). The design is in
[docs/agentic/architecture.md](agentic/architecture.md).

## Benchmark details


- **Fixtures:** todo, a shop (filters, search, cart arithmetic, async data),
  a signup form (validation, error states, a submit that reloads the page), a
  notes app (pinning, search in body text, deletes), a members area behind a
  sign-in (welcome, projects, sign-out, a guard for signed-out visitors), a
  React 19 + Vite 8 budget tracker, and a Next.js 16 guestbook whose entries
  live on the server. The last two start through their own dev servers.
  They live in [`contexer-agent/bench/fixtures`](../bench/fixtures).
  Each bug has a `BUG.md` naming the check expected to catch it, and every
  bug was caught by that check.
- **Validity rule:** a contract that fails on the correct app is not scored.
- **Scoring:**
  - **Caught:** a proven check is refuted.
  - **Flagged:** the merge is blocked without proof (a check is only
    unverified, or the app did not start).
  - **False failure:** any check not verified, or an app that did not start,
    on correct or harmless code.
