# Roadmap to a closed beta, 2026-11-24

From [audit.md](audit.md) (what the code is and what is open) and
[research.md](research.md) (the market, the models, the users). Tickets
are in [tickets.md](tickets.md); ids such as `SEC-1` point there.

Nothing here is approved. It is a proposal for the owner to read, change
and accept, milestone by milestone, as the earlier phases were.

---

## 1. Position

**Asked for:** "an affordable, model-agnostic autonomous coding harness
that makes smaller and open-source models more capable."

**Recommended:** do not become the coding agent. Keep Contexer above the
agents and make this the claim:

> Proof that the work is done, whichever agent and model did it. Use a
> cheap model: Contexer catches what it gets wrong and sends it back with
> the cause.

Why, in short (the evidence is in [research.md](research.md) §3 and §8):

- The coding-harness position is the most crowded on the map, and three
  funded teams in it ended in 2026.
- The one study with enough runs found the best harness for open models
  is already the largest open project.
- No source shows a harness lifting a small model to a frontier one.
- The verification position is held only in pieces by others.
- The goal behind the request, real work from cheaper models, can be
  served from here, and measured: a weak coding model with Contexer's loop
  against the same model without it (`EVAL-2`).

What would change this recommendation: `EVAL-2` showing that the loop does
not raise a weak model's rate of proven work. Then the cheap-model claim
is dropped, not the product.

**Decided by the owner, 2026-11-24.** Contexer stays above the coding
agents and never writes code. It is the senior engineer over them: it
takes the task, works out what was meant, instructs the agent, watches
the work, tests it as the person intended, reviews it, finds the gaps,
writes the next instruction, and goes on by itself until the task, ticket
or contract is proven. It works with small and large models alike, and it
connects to the agents people already use.

Set against the code, that is three things to build and one to keep:

| The direction | Today | To build |
| --- | --- | --- |
| Instruct like a senior engineer | The first prompt is a template: goal, checks, a file list, rules. Only repairs get a model-written lead | A brief for the first turn: the files that matter, the project's own conventions, the order of work, what not to touch (`BRIEF-1`), measured (`BRIEF-2`) |
| Connect to any coding agent | Contexer starts the agent headless through three adapters. Nothing lets an agent a person is already using call Contexer | An MCP server (`INT-1`), a hook that refuses "done" while a check fails (`INT-2`), the skill that installs both (`DX-1`) |
| Take context | The goal, the page, a file list, the diff, the server log. Corrections are remembered | The ticket and its discussion, the project's instruction files, earlier attempts (`CTX-5`, `CTX-1`) |
| Work until it is finished | Built: the loop, the budget, stop and resume | Keep; make it hold with a weak model (milestone B) |

These move ahead of the model matrix in the order of work: after
milestone A and `REL-3`, `REL-5`, build `INT-1`, `INT-2` and `BRIEF-1`.

**First users.** People who build web apps with a coding agent and are
the tester in the loop. The wedge is one command inside the agent they
already use (`DX-1`), not a new terminal to live in.

---

## 2. Milestones

Effort: S is up to two days, M up to a week, L more than a week, for one
person. Every milestone ends with a stop for review.

### A. Close Phase 5 and the two high findings

- **Objective.** Nothing known can end a run falsely, leak a token in the
  issue flow, or lose a push to an unscanned secret.
- **Current state.** Ten fixes landed on 2026-11-24 ([audit.md](audit.md)
  §4), then `SEC-1` to `SEC-4` the same day. `REL-1` was done on
  2026-11-26 as 0.6.0, on PyPI. Milestone A is complete; the licence
  decision (§7) is open.
- **Required.** `SEC-1`, `SEC-2`, `SEC-3`, `SEC-4`, `REL-1`.
- **Depends on.** Nothing. `REL-1` needs the owner.
- **Accept when.** Each ticket's regression test passes; a hook planted in
  `.git/hooks` does not run during a hand-off; a `.env` cannot set a git
  or GitHub variable for any command; 0.5.1 is tagged.
- **Tests.** The named regression tests; the full suite; the gate benchmark.
- **Risks.** `SEC-1` changes whether a person's own pre-commit hook runs
  on Contexer's commit. That is a decision, stated in the ticket.
- **Effort.** M.
- **Done.** The suite is green on the tagged commit and the readiness
  document lists no high finding.

### B. A run loop that holds with a weak model

- **Objective.** A model that calls tools badly degrades to a clear
  message, never to a silent wrong answer.
- **Current state.** `L1` to `L7` in [audit.md](audit.md) §5.1. `REL-2` to
  `REL-7` were built on 2026-11-25. Milestone B is complete.
- **Required.** `REL-2` (malformed tool calls), `REL-3` (text taken for an
  answer), `REL-4` (corrections per mistake), `REL-5` (a crash still
  writes a report), `REL-6` (flaky checks), `REL-7` (atomic writes and the
  lock).
- **Depends on.** A.
- **Accept when.** A scripted model that sends a cut-off tool call, a tool
  call as text, and three narrated steps ends each agent with the right
  status; a check that fails once and passes on a second replay is
  reported as flaky and starts no repair.
- **Tests.** Scripted-model tests per ticket; the repair suite unchanged.
- **Risks.** `REL-6` doubles the time of every real failure. Measure on
  the gate benchmark before it is the default.
- **Effort.** M.
- **Done.** The scripted "bad model" suite passes and is in CI.

### C. Security that holds in Actions

- **Objective.** The issue flow can be pointed at a public repository.
- **Current state.** Never run against a real issue. `SEC-5` to `SEC-8`
  were built on 2026-11-26, and four of the seven items of `SEC-9` (open:
  a release tag in the workflow templates, Actions pinned by commit,
  Action inputs through `env:`, upper bounds on five dependencies). None
  of it is in a release yet. Not built: `SEC-10`, `REL-8`.
- **Required.** `SEC-5` to `SEC-9`, `SEC-10` (two jobs: build with no
  write token, push from a second), `REL-8` (the issue flow run for real).
- **Depends on.** A.
- **Accept when.** A hostile-issue test set (hidden text, a planted hook,
  a `.env` that steers git, a rewritten contract) ends every case without
  a token read and without a false approval, on a real private repository.
- **Tests.** `tests/test_security.py` grows a "hostile repository" suite
  with a scripted coding agent playing the attacker.
- **Risks.** Needs a sandbox repository, which the owner creates.
- **Effort.** L.
- **Done.** The suite passes, and one real issue went from draft to a
  proven pull request.

### D. Models: a capability record and a measured matrix

- **Objective.** Know which models can drive Contexer's agents and say so
  in the tool, from measurement.
- **Current state.** One model measured. No fallback for a tool call
  printed as text. Built on 2026-11-26: `MOD-1` (the record exists and
  `doctor` and `setup` show it; no agent is built from it yet), `MOD-2`,
  `MOD-5` (open: `max_steps` for Intent and Triage inside `contexer run`),
  `EVAL-3` (no suite has been re-run with repeats). Not built: `MOD-3`,
  `MOD-4`, `EVAL-1`, `EVAL-2`.
- **Required.** `MOD-1` (capability record per model), `MOD-2`
  (validate-and-repair turn), `MOD-3` (tool calls found in text), `MOD-4`
  (strict schemas and `require_parameters`), `MOD-5` (`[agents]` wired
  through `contexer test`), `EVAL-1` (the matrix), `EVAL-2` (weak coding
  model with and without the loop), `EVAL-3` (repeats and intervals).
- **Depends on.** B, because the matrix measures the hardened loop.
- **Accept when.** Six models have a row: tester found and false-alarm
  rates over at least five repeats, tool-call repair rate, cost per run.
  `contexer doctor` and `contexer setup` say what the chosen model was
  measured to do.
- **Tests.** Recorded replies for each failure shape; the matrix itself.
- **Risks.** Cost: a full tester suite is about 14M tokens on one model.
  Use the held-out app and two others for the matrix, not all eight.
- **Effort.** L.
- **Done.** The matrix is published in `bench/RESULTS.md` with its cost.

### E. Cost and observability

- **Objective.** A person sees where a run's money and time went, and can
  compare two models or two versions.
- **Current state.** [audit.md](audit.md) §5.4 and §5.6. Built on
  2026-11-26: `OBS-1` (without `--trace-content` and retries per call) and
  `CTX-1`. Not built: `COST-3` (the record of `MOD-1` has the prices; the
  budget is not told which model a call was for), `COST-1`, `COST-2`,
  `COST-4`, `OBS-2`, `OBS-3`, `OBS-4`, `CTX-2`, `CTX-3`, `CTX-4`.
- **Required.** `COST-1` (unknown cost is said, not counted as zero),
  `COST-2` (cached tokens and cache markers), `COST-3` (a price per model
  from the provider's catalogue), `COST-4` (the budget covers `contexer
  test`), `OBS-1` (one trace file per run), `OBS-2` (the fix prompt and
  the lead saved per attempt), `OBS-3` (`runs --stats` by model, `--json`),
  `OBS-4` (optional OpenTelemetry export), `CTX-1` (the Diagnoser sees
  earlier attempts), `CTX-2` (diffs ordered by what failed), `CTX-3`
  (old page snapshots dropped from a long conversation).
- **Depends on.** D for `COST-3`; otherwise B.
- **Accept when.** For any run folder, one command prints per agent and
  model: calls, tokens in, out and cached, cost with "estimated" or
  "unknown" said, tool errors, repaired calls, seconds. Nothing leaves the
  machine unless the person set an endpoint.
- **Tests.** A recorded run folder as a fixture; totals equal the
  transcripts.
- **Risks.** OpenTelemetry's conventions are not stable: pin the version
  written in the file.
- **Effort.** M.
- **Done.** The numbers in `bench/RESULTS.md` are produced by this
  command and not by hand.

### F. Where people already are

- **Objective.** A first proven result in five minutes, from inside the
  coding agent.
- **Current state.** Built by 2026-11-26: `INT-1`, `INT-2`, `BRIEF-1`,
  `DX-1`, `DX-2` (off by default; no real pull request opened with it
  yet), `DX-3`, `DX-5`, `DOC-1`. CI installs the package cleanly and runs
  `contexer demo` on Ubuntu, Windows and macOS; the steps of the guide
  that need a model key were followed on Windows only. Not built: `DX-4`,
  `BRIEF-2`, `CTX-5`. The five-minute run by a person has not been timed
  on any system.
- **Required.** `DX-1` (a skill and a command for Claude Code, Codex and
  OpenCode that calls `contexer verify` and reads what failed), `DX-2`
  (screenshots of each check in the pull request), `DX-3` (clean installs
  on macOS and Linux; CI on three systems), `DX-4` (the run view: plan,
  one status line, context and cost), `DX-5` (`contexer runs prune`),
  `DOC-1` (what is sent where; what it does not do).
- **Depends on.** A. `DX-4` is better after E.
- **Accept when.** A person with Claude Code and no Contexer reaches a
  proven check on the sample app in five minutes on each system, timed.
- **Tests.** The install matrix in CI; the skill exercised by a scripted
  agent.
- **Risks.** The agents' plugin formats change; keep the skill a thin
  call to the CLI.
- **Effort.** L.
- **Done.** Three people outside the project did it unaided.

### G. Agents that prove something new

- **Objective.** Add only what code can prove.
- **Current state.** [readiness.md](../agentic/readiness.md) §5 chose four.
  None is built. `AGT-1` was looked at on 2026-11-26 and left: it needs a
  baseline replay before the first turn and a decision by the owner on how
  a stale check is shown ([tickets.md](tickets.md)).
- **Required.** `AGT-1` (regression guard as its own finding), `AGT-2`
  (dependency checker), `AGT-3` (scope guard), `AGT-4` (access prober, and
  with it an HTTP check).
- **Depends on.** B. `AGT-4` after C.
- **Accept when.** Each has a seeded suite: planted cases found, clean
  cases not flagged.
- **Effort.** `AGT-1` to `AGT-3` are S or M each; `AGT-4` is L.
- **Done.** Per ticket.

### H. Closed beta

- **Objective.** Twenty people use it on their own apps and the numbers
  are read weekly.
- **Current state.** `REL-11` was built on 2026-11-26: the release
  workflow checks the gate benchmark and CI on the tagged commit before it
  publishes. It has not been run, and the gates that need a model key are
  a person's step. Not built: `REL-9`, `REL-10`, `DOC-2`.
- **Required.** `REL-9` (three more real projects, checks read by a
  person), `REL-10` (Codex run live), `DOC-2` (troubleshooting from the
  beta's own failures), `REL-11` (release checklist and quality gates).
- **Depends on.** A, B, C, F. D and E can trail by a release.
- **Accept when.** The quality gates in §8 hold on the release commit.
- **Effort.** M, plus the weeks the beta runs.
- **Done.** The definition in §9.

---

## 3. Order and critical path

```text
A ──► B ──► D ──► E
│     │
│     └──► G (1-3)
├──► C ──► G (4)
└──► F ──────────► H
```

The critical path to a closed beta is **A, B, F, H**, with C required
before the issue flow is offered to anyone and switched off in the beta
until then. D and E make the product better and the claims provable; the
beta can start without them if it says "measured on one model".

Recommended order of work: `SEC-1`, `SEC-2`, `SEC-4`, `SEC-3`, `REL-1`;
then `REL-3`, `REL-2`, `REL-4`, `REL-5`; then `DX-3` and `DX-1` in
parallel with `MOD-1` and `MOD-2`; then `EVAL-1` and `EVAL-2`.

---

## 4. Launch blockers, and what is not one

**Blocks a closed beta.**

1. ~~`SEC-1`, `SEC-2`, `SEC-4`~~ and `SEC-3`: fixed on 2026-11-24.
4. ~~`REL-3`~~ and ~~`REL-5`~~: fixed on 2026-11-25.
6. ~~`DX-3`~~: built on 2026-11-26. CI runs on three systems; the browser
   tests run on Ubuntu only, and the macOS benchmark has not been run
   again since the `no_errors` fix.
7. ~~`REL-1`~~: done on 2026-11-26 as 0.6.0.
8. ~~`DOC-1`~~: built on 2026-11-26.

**Blocks the issue flow only** (ship the beta with it off): ~~`SEC-3`~~,
~~`SEC-6`~~ (built on 2026-11-26), `SEC-10`, `REL-8`.

**Not a blocker.** Everything in D, E and G; the run view; OpenTelemetry;
a second coding agent live. They are P1 or P2.

---

## 5. Additional agents

The rule from [readiness.md](../agentic/readiness.md) stands and the
research supports it: an agent belongs in Contexer when most of what it
reports can be proven by code. Of the eleven candidates asked about:

| Candidate | Decision | Why |
| --- | --- | --- |
| Regression guard | Build (`AGT-1`), a capability of the loop | Mostly built; entirely provable. "Fixing one thing breaks another" is the most reported pain after false "done" |
| Dependency checker | Build (`AGT-2`), no model | 205,474 invented package names in one study; a registry lookup proves it |
| Scope guard | Build (`AGT-3`), part of the review's scan | Tests changed or deleted, safeguards removed: countable by code. The delete-confirmation case in Phase 5 is this class |
| Access prober (security) | Build (`AGT-4`), a separate agent with a second account | A read that succeeds is a replayable proof. Needs an HTTP check, which also ends "browser only" |
| Debugging | Exists: the Diagnoser. Improve its context (`CTX-1`, `CTX-2`) | |
| Code review | Exists: the Reviewer. Keep model notes as advice | |
| Repository understanding | Not as an agent. A cached project summary (`CTX-4`) | Nothing about it can be proven; the coding agents have their own |
| Test generation | No | It makes Contexer a writer of code and invites the tampering it polices. Saved checks already grow the suite |
| Documentation | No | Unprovable; the coding agents do it |
| Performance | No | No good evidence AI code causes it; dev-server timings are noise |
| Database and migration | Later, as a check kind | "The migration ran and the old rows still read" is provable; needs the HTTP check first |
| Architecture planning, refactoring | No | The coding agent's job. A refactor is proven by the regression guard |

For each built agent the ticket states the pain, the tools, the model it
needs (none for three of the four) and its seeded suite.

---

## 6. The terminal

Contexer supervises a run and asks few questions. It is not a chat, so it
should not copy one. What the agent CLIs do well, and what their users
complain about ([research.md](research.md) §1): the praised parts are a
status line that stays put, a plan that ticks off, tool output folded to
a line, and a headless mode; the complaints are flicker, lost scrollback
and Windows paste bugs, all from full-screen rendering.

So, in this order (`DX-4`):

1. Keep the output in the terminal's own scrollback. One block redrawn in
   place, as now, with three additions: the plan of the run as a list
   (draft, approve, build, prove, review, hand off) with the current step
   marked; a footer with time, money, tokens and how full the model's
   context is; and the estimate's ceiling next to what was spent.
2. Diffs: `contexer runs show RUN --diff` prints the change of an attempt,
   coloured, paged by the system pager. Not inline in the run.
3. Approval: the checks as a numbered list; `e` opens the contract in the
   editor; a typed sentence is a correction. One key each, shown.
4. Errors: one sentence, what Contexer did about it, the next command.
5. Ctrl+C once stops after the current step and says how to resume; twice
   stops now. Both restore.
6. `--json` stays the contract for tools; `--plain` for CI with no redraw.
7. `contexer watch RUN`, a full-screen view reading the same events, only
   after the above, and never the default.

Accessibility: no meaning carried by colour alone (marks are already
words and symbols), `NO_COLOR` honoured, nothing that needs a mouse.

---

## 7. Open or closed

**Stay fully open source for the tool. Move from MIT to Apache-2.0 before
the first tagged release. Keep the name. Build nothing paid until people
use it.**

- It runs with a person's repository and tokens, and has no brand. Source
  that can be read is the only trust on offer.
- With no users, being unknown is a larger risk than being copied.
- The cases that earned money sold either a model gateway or team
  governance on top of a free tool (Cline's paid tier is single sign-on,
  roles, billing and audit logs). The ones that tried to charge
  individuals for the tool found nothing (Aider, Bloop).
- A source-available licence would stop a hosted clone at the price of
  not being open source to the people whose trust is the point.

What would be paid, later, and is not held back from the tool: shared run
history across a team's machines; a GitHub App that runs the gate and the
issue flow with no workflow file; policy (who may approve, which notes
hold a pull request); single sign-on. Everything a single developer needs
to prove their own work stays free: every command that exists today.

Apache-2.0 over MIT for the patent grant, which companies ask about.
Changing it is easy now and awkward after outside contributions.

**Pricing, when there is something to price.** The nearest public unit is
$1 for one managed web test run, and $24 to $90 a developer a month for
model review of pull requests. A team tier in the range of $20 to $30 a
seat, with the person's own model key, is where comparable tools sit. Do
not sell model tokens: a gateway is a different business.

---

## 8. Quality gates for a release

A release is cut only when all hold on its commit:

| Gate | Threshold | Source |
| --- | --- | --- |
| Tests, lint, types | Green on Linux, macOS, Windows | CI |
| Gate benchmark | Every seeded bug caught; no false failure | `contexer bench` |
| Repair suite | No worse than the last release | `bench --suite repair` |
| Reviewer suite | Every planted issue flagged; at most 1 false high in 10 | `bench --suite reviewer` |
| Tester, held-out app | No more false alarms than the last release, over 5 repeats | `bench --suite tester --app bookings` |
| Hostile suite | Every case ends without a false pass and without a secret read | `tests/test_security.py` |
| False success | 0 runs in any suite end `succeeded` without a gate pass | All suites |
| Clean install | First proven check in 5 minutes on three systems | `DX-3` |

"No worse" means that `--compare` against the last release's report does
not say `lower` for a rate that should be high, or `higher` for false
alarms (`EVAL-3`). The release workflow checks the first two rows by
itself (`REL-11`: the gate benchmark, and the CI run on the same commit);
the rows that need a model key are a person's step before tagging.

---

## 9. What "production ready" means here

Contexer is ready for people who are not the author when:

1. No known way exists for a run to end `succeeded` without the gate
   passing on the checks last approved.
2. No known way exists for text an agent read, or a file an agent wrote,
   to make Contexer read a token, push a secret, or approve a contract.
3. A person can install it and reach a proven check without help on
   Windows, macOS and Linux.
4. Every failure ends in a sentence, an exit code and a report, with the
   project's files as they were or better.
5. Every number in the README was produced by a command in the repository
   and can be reproduced.
6. It says plainly what it does not do: web apps only, never writes code,
   which provider sees what.

Today, after the fixes of 2026-11-25: 1 holds as far as is known; 2 holds
in the code but not in a release (`SEC-1` to `SEC-4` are fixed, not
shipped); 3 holds on Windows only; 4 holds since `REL-5`; 5 holds; 6 is
half written.

On 2026-11-26: for 2, `SEC-1` to `SEC-4` are in the release 0.6.0, and
`SEC-5` to `SEC-9` are on `main` and not released; for 3, CI installs the
package and runs `contexer demo` on three systems, and the steps that
need a model key were followed on Windows only; 6 is written
([data-and-limits.md](../data-and-limits.md)).

---

## 10. Beyond code: a staged path to production engineering

Each stage adds a class of action and the control that makes it safe.
None starts before the one above has run with users.

| Stage | Contexer may | The proof | The control |
| --- | --- | --- | --- |
| 0, today | Read a project, run it locally, replay checks, open a pull request | Browser checks | Snapshots, the tamper guard, one budget |
| 1 | Prove what is not a page: an API, a CLI, a migration | HTTP and command checks (`AGT-4`) | Same |
| 2 | Investigate a failed CI run and propose a fix as a pull request | The failing job passes on the branch | Read-only CI token; the two-job split (`SEC-10`) |
| 3 | Update dependencies and remediate a known vulnerability | Every approved contract replays; the advisory no longer matches | A pull request per change; never a direct push |
| 4 | Verify a preview deployment before release | The contracts replay against the preview URL | Explicit consent per host (`--allow-remote` exists) |
| 5 | Read production signals to explain an incident | A failing check reproduced locally from the report | Read-only, scoped credentials; an audit log; redaction before any model sees a log |
| Never by default | Deploy, migrate production data, change infrastructure | | A named person approves each action; a rollback is rehearsed first |

Before stage 5: an audit log that cannot be edited by the run, a
permission model per action class, redaction that is tested, and a
company behind it that can be held to account. That is not a feature list;
it is a different stage of the business.

---

## 11. The questions the brief ends with

**What already works?** The whole loop on one model and one real project:
checks drafted and approved, an external agent building, replay deciding,
Triage and the Diagnoser repairing, the Reviewer reading the diff, a pull
request with evidence, stop and resume, one budget. Four benchmark suites.

**What is still broken?** The hand-off runs project hooks with the token;
`.env` can steer git; a secret past 200,000 characters of diff is pushed;
a weak model's printed tool call is taken for "nothing to report"; a crash
leaves no report.

**What prevents shipping?** The eight blockers in §4. None is large.

**What to build next?** Milestone A, then B, then the skill that puts
Contexer inside the coding agent (`DX-1`), then the model matrix.

**What to deliberately not build?** A coding agent. A test writer. A
memory or documentation agent. A hosted dashboard. A model gateway. A
full-screen terminal as the default. Planner and router layers before the
matrix says where they would pay.

**How does Contexer become more valuable than the harnesses?** By not
being one: it is the part none of them can be for themselves, a verdict
they cannot bend, that works whichever of them survives.

**How do smaller models perform better?** Not by a better prompt. By a
loop that makes their failures cheap: catch the failure by replay, name
the cause, send it back, and stop when the budget says so. And inside
Contexer's own agents: validate each tool call and send the error back
once, read tool calls a server returned as text, keep schemas flat and
strict, keep the prompt's start stable so it is cached.

**Strongest advantage?** Checks a person approved before the build,
replayed by code the building agent cannot touch. Everything else is easy
to copy.

**Minimum scope for a reliable closed beta?** `contexer test`, `contexer
run`, `contexer verify` and the gate, on web apps, with Claude Code and
OpenCode, one measured model named as such, three operating systems, the
issue flow switched off, and the eight blockers closed.

---

## 12. Test results, 2026-11-24

On the tree with the fixes of that day, Windows 11, Python 3.14.

| Check | Result |
| --- | --- |
| `ruff check src tests` | Passed |
| `pyright src` | 0 errors |
| Tests touched by the fixes | Passed (see [audit.md](audit.md) §4) |
| Full suite (`pytest`, the live OpenCode test deselected) | 1003 passed, 4 skipped, in 37 min 37 s |
| Full suite after `SEC-1` to `SEC-4` | 1014 passed, 4 skipped, in 30 min 46 s |
| Full suite after `REL-2` to `REL-5` (2026-11-25) | 1028 passed, 4 skipped, in 30 min 44 s |
| Full suite after `REL-6` and `REL-7` (2026-11-25) | 1037 passed, 4 skipped, in 37 min 55 s (failing checks are now replayed twice) |
| Gate, tester, repair and reviewer benchmarks | Not re-run that day |
| Live runs with a model | None that day |
