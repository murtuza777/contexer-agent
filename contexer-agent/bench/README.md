# Contexer benchmark

How often does the gate catch real bugs, and how often does it fail correct
code? This folder answers that with fixture apps and seeded bugs.

```bash
contexer bench               # replay each app's approved, hand-written contract
contexer bench --live        # compile each app's goal with the LLM instead, then score that
contexer bench --app notes   # one app
```

## How it works

Each fixture in `fixtures/<app>/` has:

| Path | What it is |
| --- | --- |
| `app/` | The correct app, with its approved contract in `app/.contexer/contracts/` |
| `bugs/<id>/` | File overlays introducing **one** realistic bug, with a `BUG.md` naming the check expected to catch it |
| `benign/<id>/` | Overlays that change code but not behaviour (refactor, restyle, slow API) |

Every variant is copied to a temporary directory, served, and verified in
Chromium with no LLM. Scoring:

| Variant | Result | Meaning |
| --- | --- | --- |
| Correct and benign | **False failure** | Any check not verified (refuted or unverified) |
| Bug | **Caught** | A proven check is refuted |
| Bug | **Flagged** | A check is only unverified, so the merge is blocked without proof of what broke |
| Bug | **Missed** | Every check passed |

**Validity rule** (from SWE-Lancer): a contract that does not pass on the
correct app is broken, and the app is reported as invalid instead of being
scored.

In `--live` mode, the model compiles a contract from the app's one-line goal,
grounded in the correct app's UI. Compiled checks that fail on the correct app
are dropped and listed, as a reviewer would reject them, and the rest are
scored. If the model returns nothing usable, the report says
`rule-based fallback`.

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

See [RESULTS.md](RESULTS.md).

## Adding a fixture

1. Write the correct app in `fixtures/<name>/app/` (static HTML/JS, so it is
   served without a build).
2. Write its contract in `app/.contexer/contracts/<id>.json`, then
   `contexer contract approve <id> --dir fixtures/<name>/app`.
3. Add `bugs/<id>/` overlays, each with a `BUG.md` naming the catching check,
   and `benign/<id>/` overlays with a `CHANGE.md`.
4. Run `contexer bench --app <name>`. The contract must pass on `app/`.
