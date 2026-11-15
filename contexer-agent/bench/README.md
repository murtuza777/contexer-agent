# Contexer benchmark

How often does the gate catch real bugs, and how often does it fail correct
code? This folder answers that with fixture apps and seeded bugs.

```bash
contexer bench               # replay each app's approved, hand-written contract
contexer bench --live        # compile each app's goal with the LLM instead, then score that
contexer bench --app notes   # one app
contexer bench --suite tester --agent stub   # the tester suite (below)
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
| Fails on correct or benign code (also when it was reported on a bug) | **False alarm** | The agent's expectation is wrong, not the app |
| Passes, or cannot run, on the app the agent tested | **Unconfirmed** | Did not reproduce: dropped and counted |

Also reported per app: the agent's steps and its cost when the provider
reports one. An app that does not start is reported and not scored. The
correct app and each benign variant run `--repeats` times (default 1), each
bug once.

`--agent stub` reports nothing, so the suite runs with no model and scores 0
found and 0 false alarms: the floor, and proof that the harness works. The
Tester agent registers here in Phase 1 (`bench/tester.py: TESTER_AGENTS`).
Each run of the whole suite writes `tester-results/<agent>.md`.

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

See [RESULTS.md](RESULTS.md), and [tester-results/](tester-results/) for the tester suite.

## Adding a fixture

1. Write the correct app in `fixtures/<name>/app/`: static HTML/JS, or a
   `package.json` app with a `dev` script and a committed lockfile. Add an
   `[auth]` section to its `contexer.toml` if it needs a signed-in user.
2. Write its contract in `app/.contexer/contracts/<id>.json`, then
   `contexer contract approve <id> --dir fixtures/<name>/app`.
3. Add `bugs/<id>/` overlays, each with a `BUG.md` naming the catching check,
   and `benign/<id>/` overlays with a `CHANGE.md`.
4. Run `contexer bench --app <name>`. The contract must pass on `app/`.
