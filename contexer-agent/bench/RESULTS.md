# Benchmark results

All runs below were on Windows 11 with Playwright Chromium, 2026-10-15. CI
re-runs the hand-written benchmark on Linux on every push.

## Hand-written contracts (measures the runner)

`contexer bench --repeats 2`

| App | Seeded bugs | Caught (proven) | Flagged | Missed | False-failing checks on correct and benign code |
| --- | --- | --- | --- | --- | --- |
| todo | 6 | 6 | 0 | 0 | 0 / 56 (8 runs) |
| shop | 6 | 6 | 0 | 0 | 0 / 48 (6 runs) |
| signup | 6 | 6 | 0 | 0 | 0 / 36 (6 runs) |
| notes (held out) | 6 | 6 | 0 | 0 | 0 / 36 (6 runs) |
| **total** | **24** | **24** | 0 | 0 | **0 / 176** (26 runs) |

The benign variants are a full JS refactor, visual restyles, a 600ms deferred
render, a 900ms slow API, a 500ms async submit and a 500ms slow save. All of
them passed every check: auto-retrying expectations absorb timing, and
role-based locators survive restyles and refactors.

**Caveat:** the contracts and the bugs were written by the same author. This
shows the runner is reliable and classifies failures correctly, not that
contracts are good.

## LLM-compiled contracts (measures the compiler)

`contexer bench --live --repeats 2` with `OPENROUTER_MODEL=openrouter/free`, a
router that sends each request to a different free model. That makes this one
noisy sample per app, not a stable measurement. Compiled checks that fail on
the correct app are dropped before scoring, so the false-failure column only
covers checks that survived that filter.

| Compiler prompt | todo | shop | signup | Total (3 tuned apps) | notes (held out) | False-failing checks |
| --- | --- | --- | --- | --- | --- | --- |
| Baseline | 0/6 ¹ | 4/6 | 5/6 | **9/18 (50%)** | — | 0/80 |
| Edge-case guidance ² | 0/6 ³ | 5/6 | 6/6 | **11/18 (61%)** | invalid ³ | 0/112 |

¹ The model returned no parseable JSON on both attempts, so the analyzer fell
back to rule-based checks. The CLI now flags such drafts as weak before
anyone approves them.

² The guidance covers: acting more than once for counts and totals, switching
filters back, removing one of several items, one check per form rule plus the
error clearing, `no_errors` on every interaction, exact values, and up to 10
criteria. The newly caught bugs are shop `total-ignores-quantity` and signup
`stale-error`. Shop `all-keeps-filter` is still missed.

³ The model wrote checks, but most failed on the **correct** app (todo 5 of 7,
notes 6 of 6) and were dropped. Writing wrong checks, not missing checks, is
now the main failure mode; see the diagnosis below.

### What this means for the product

- A one-line goal does not produce a trustworthy contract on its own with free
  models. The approval step is load-bearing: a person reads the checklist, and
  checks that fail on code they know works get fixed before approval.
- When the compiler does produce valid checks, they catch most seeded bugs,
  and every miss so far is an edge case the goal did not spell out.
- Run `contexer bench --live` with your own `OPENROUTER_MODEL` before trusting
  generated contracts.
