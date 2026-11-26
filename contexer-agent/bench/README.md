# Contexer benchmark

How often does the gate catch real bugs, and how often does it fail correct
code? This folder answers that with fixture apps and seeded bugs.

```bash
contexer bench               # replay each app's approved, hand-written contract
contexer bench --live        # compile each app's goal with the LLM instead, then score that
contexer bench --app notes   # one app
contexer bench --suite tester --agent stub   # the tester suite (below)
contexer bench --suite repair --agent opencode   # the repair suite (below)
contexer bench --suite reviewer --agent scan     # the reviewer suite (below)
```

## How it works

Each fixture in `fixtures/<app>/` has:

| Path | What it is |
| --- | --- |
| `app/` | The correct app, with its approved contract in `app/.contexer/contracts/` |
| `bugs/<id>/` | File overlays introducing **one** realistic bug, with a `BUG.md` naming the check expected to catch it |
| `benign/<id>/` | Overlays that change code but not behaviour (refactor, restyle, slow API) |

Every variant is copied to a temporary directory and started the way
`contexer verify` starts a project: static apps are served as files, and an
app with a `package.json` runs its real dev server (`npm ci` once per app, so
the React fixture needs network on its first run). Then it is verified in
Chromium with no LLM. Fixtures with an `[auth]` section in `contexer.toml`
sign in first, exactly as a user's project would. Scoring:

| Variant | Result | Meaning |
| --- | --- | --- |
| Correct and benign | **False failure** | Any check not verified (refuted or unverified), or the app did not start |
| Bug | **Caught** | A proven check is refuted |
| Bug | **Flagged** | The merge is blocked without proof of what broke: a check is only unverified, or the app did not start |
| Bug | **Missed** | Every check passed |

**Validity rule** (from SWE-Lancer): a contract that does not pass on the
correct app is broken, and the app is reported as invalid instead of being
scored.

In `--live` mode, the model compiles a contract from the app's one-line goal,
grounded in the correct app's UI. Compiled checks that fail on the correct app
are dropped and listed, as a reviewer would reject them, and the rest are
scored. If the model returns nothing usable, the report says
`rule-based fallback`.

## The tester suite

`contexer bench --suite tester --agent NAME` measures an agent that explores
an app, on the same fixtures. Nobody hands it a contract: for every variant
it gets the app's goal in words and the running app, and it reports findings.
Each finding states the behaviour the agent expected as a check. Code decides
what a finding is worth by replaying it in a fresh browser, with the
project's sign-in and reset and no model:

| Replay | Result | Meaning |
| --- | --- | --- |
| Fails on the seeded bug, passes on the correct app | **Found** | A real bug, reproduced |
| Reported on correct or benign code, and fails there | **False alarm** | The agent reported a bug in code that has none. The target is 0 |
| Reported on a seeded bug, but the correct app fails the check too | **Rejected** | The expectation is wrong, so it proves nothing and does not count as found. Often the right bug with guessed wording |
| Passes, or cannot run, on the app the agent tested | **Unconfirmed** | Did not reproduce: dropped and counted |

Also reported per app: the agent's steps and its cost when the provider
reports one. An app that does not start is reported and not scored. Every
variant runs `--repeats` times (default 1): the correct app, each benign
variant and each bug.

`--agent stub` reports nothing, so the suite runs with no model and scores 0
found and 0 false alarms: the floor, and proof that the harness works.
`--agent tester` is the Tester agent (`crew/tester.py`) on the model you
configured; it costs model calls for every variant of every app.
Each run of the whole suite writes `tester-results/<agent>.md`.

## The repair suite

`contexer bench --suite repair --agent NAME [--model MODEL]` measures the
whole loop: each seeded bug is laid out with its app's approved contract and
handed to a coding agent that `contexer run`'s loop drives. A bug counts as **fixed** only when the run ends `succeeded`,
which is the gate's word and not the agent's.

```bash
contexer bench --suite repair --agent opencode --model azure/gpt-5.4 --repair-only --out repair.json
contexer bench --suite repair --agent claude-code --bug todo/count-ignores-done
```

- `--repair-only`: the first turn gives the agent the job and tells it to
  change nothing. The checks then fail on the seeded bug and every fix is a
  repair. Use it to measure the repair itself: without it a capable model
  fixes most bugs in its first turn.
- `--bug app/bug`, `--app`, `--limit N`, `--rounds N` narrow the run.
- Contexer's own agents (Triage, Diagnoser) use the model you
  configured; with none, the rules decide.
- It costs a coding-agent session per bug. The full run of 46 bugs on two
  loops (0.4's and the graph, before 0.4's was removed) took 86 minutes on
  gpt-5.4.
- It is also how to measure a weaker coding model: same bugs, same checks,
  another `--model`.

Results are in [repair-results/](repair-results/).

## The reviewer suite

`contexer bench --suite reviewer --agent scan|reviewer` measures the review
of a diff (`crew/reviewer.py`). `reviewer/<case>/` holds `before/`,
`after/` and `case.json`:

- **10 planted cases**, one issue each: a secret in the source, a focused
  test, a deleted test, leftover debug code, a test rewritten to match a
  bug, an off-by-one, user text put into the page as HTML, a removed admin
  check, a value hard-coded for the check, a query built from input.
- **10 clean cases**: refactors, a feature with its tests, a key read from
  the environment, a placeholder in a README, an error that is logged.

A planted issue is **flagged** when a note points at its file with a
fitting category. Whether the note's words are right is not judged, so the
number is an upper bound. A **false high** is a high-severity note on a
clean diff; a high-severity security note is what turns a pull request into
a draft.

`--agent scan` runs the code-only scan with no model: the floor. `--agent
reviewer` adds the Reviewer agent on the model you configured. A run of the
whole suite writes `reviewer-results/<agent>.md`.

Twenty small diffs written by the person who wrote the scan are a smoke
test, not a measure of how the review does on real pull requests.

## Repeats and intervals

Every suite takes `--repeats N`, prints each headline count as a rate with
its 95% Wilson interval, and takes `--compare REPORT.json`:

```bash
contexer bench --suite tester --agent tester --app bookings --repeats 5 --out now.json
contexer bench --suite tester --agent tester --app bookings --repeats 5 --compare last-release.json
```

| Suite | What `--repeats N` repeats | Default |
| --- | --- | --- |
| gate | The correct app and each benign variant. Each bug runs once: no model is involved, and the benchmark runs on every push | 3 |
| tester | Every variant, bugs too: a model finds a bug in one run and not in the next | 1 |
| repair | Every bug, one whole pass after another | 1 |
| reviewer | Every case | 1 |

With repeats, the tables count runs, not distinct bugs or cases.

`--compare` reads a report that `--out` wrote earlier for the same suite
(checked before anything runs) and says, for each rate, `higher`, `lower`
or `cannot be told apart`. It uses Newcombe's interval for the difference
of two proportions, built from the two Wilson intervals: when that interval
contains zero, the two results cannot be told apart. Two runs of the same
configuration are reported that way. It changes no exit code.

Where it stops: the intervals treat every run as an independent trial of
one rate. Bugs differ in difficulty and a repeat of a bug is not independent
of the first, so they are a guide to the noise, not an exact error bar. Only
counts are compared; cost, tokens and time are not.

## Release gates

A release is cut only when the gates in
[docs/production/roadmap.md](../docs/production/roadmap.md), section 8, hold
on its commit. `.github/workflows/release.yml` checks what code can check
when a `v*` tag is pushed, and publishes nothing unless it holds:

| Gate | Checked by | How |
| --- | --- | --- |
| Gate benchmark: every seeded bug caught, no false failure | the workflow | `contexer bench --repeats 2` on the tagged commit, on Ubuntu, then `python -m contexer.bench.gates` |
| Tests, lint, types and the clean install on three systems; the hostile suite (`tests/test_security.py`, inside the tests) | the workflow | The latest CI run a push started on the tagged commit must have passed |
| Repair suite: no worse than the last release | a person | `contexer bench --suite repair --agent NAME --repeats 5 --compare LAST.json` |
| Reviewer suite: every planted issue flagged, at most 1 false high in 10 | a person | `contexer bench --suite reviewer --agent reviewer` |
| Tester, held-out app: no more false alarms than the last release | a person | `contexer bench --suite tester --agent tester --app bookings --repeats 5 --compare LAST.json` |
| False success: no run ends `succeeded` without a gate pass | partly the workflow | A missed bug in the gate benchmark is one. The other suites are a person's |

The three gates a person runs need a model key, which the workflow does not
have. Before tagging:

1. Run them, keep each `--out` report for the next release's `--compare`,
   and read "lower" on a rate that should be high (or "higher" on false
   alarms) as a failed gate. "Cannot be told apart" is "no worse".
2. Check that CI has finished and passed on the commit. A tag pushed while
   CI is still running is refused; run the failed `Release gates` job again
   when CI is done.
3. To try the workflow's gates without publishing, run the Release workflow
   by hand on a branch: the gate job runs, the publish jobs do not.

The gate job attaches `bench-results.json` and `release-gates.md` to the
GitHub release. The benchmark in the release workflow runs on Ubuntu only.

## What the numbers mean, and don't

- **Hand-written contracts** measure the runner:
  - Does it execute checks reliably?
  - Does it avoid flakiness on slow or restyled apps?
  - Does it classify failures correctly?

  The contracts and the bugs were written by the same person, so this is
  **not** a measure of how good generated contracts are.
- **`--live`** measures the contract compiler, i.e. what a user gets from a
  one-line goal. It depends heavily on the model. `OPENROUTER_MODEL=openrouter/free`
  routes each request to a random free model, so live results vary between runs.
- **The `notes` app is held out.** It was written after the compiler prompt
  was last tuned on the other three apps, and was never used to tune it.
  Quote its live numbers separately.
- Bugs are hand-seeded. Mutation-generated bugs (StrykerJS) are planned.

## Results

See [RESULTS.md](RESULTS.md), [tester-results/](tester-results/) for the tester suite
[repair-results/](repair-results/) for the repair suite and
[reviewer-results/](reviewer-results/) for the reviewer suite.

## Adding a fixture

1. Write the correct app in `fixtures/<name>/app/`: static HTML/JS, or a
   `package.json` app with a `dev` script and a committed lockfile. Add an
   `[auth]` section to its `contexer.toml` if it needs a signed-in user.
2. Write its contract in `app/.contexer/contracts/<id>.json`, then
   `contexer contract approve <id> --dir fixtures/<name>/app`.
3. Add `bugs/<id>/` overlays, each with a `BUG.md` naming the catching check,
   and `benign/<id>/` overlays with a `CHANGE.md`.
4. Run `contexer bench --app <name>`. The contract must pass on `app/`.
