# Benchmark results

Local runs were on Windows 11 with Playwright Chromium. CI re-runs the
hand-written benchmark on Linux on every push.

## Hand-written contracts (measures the runner)

`contexer bench --repeats 2`, 2026-10-26 (874 s):

| App | What it exercises | Seeded bugs | Caught (proven) | Flagged | Missed | False-failing checks on correct and benign code |
| --- | --- | --- | --- | --- | --- | --- |
| todo | static JS | 6 | 6 | 0 | 0 | 0 / 56 (8 runs) |
| shop | static JS, async data | 6 | 6 | 0 | 0 | 0 / 48 (6 runs) |
| signup | static JS, form validation | 6 | 6 | 0 | 0 | 0 / 36 (6 runs) |
| notes | static JS | 6 | 6 | 0 | 0 | 0 / 36 (6 runs) |
| members | behind a sign-in (`[auth]`), a signed-out guard | 5 | 5 | 0 | 0 | 0 / 36 (6 runs) |
| budget-react | React 19 + Vite 8 through its real dev server | 6 | 6 | 0 | 0 | 0 / 36 (6 runs) |
| guestbook-next | Next.js 16, data kept on the server, `[app] reset` | 5 | 5 | 0 | 0 | 0 / 30 (6 runs) |
| **total** | | **40** | **40** | 0 | 0 | **0 / 278** (44 runs) |

Every bug was caught by the check its `BUG.md` names. The three newest apps
look like real projects:

- `members` signs in once and starts every check signed in; one check runs
  signed out.
- `budget-react` is installed with `npm ci` and started with `vite`, exactly
  as `contexer verify` starts a user's project.
- `guestbook-next` keeps its data in the server process, so checks would see
  each other's entries. Its `[app] reset` clears them before each check;
  without it, the correct app fails 3 of 5 checks.

The 2026-10-15 run of the first four apps scored the same: 24/24 caught, 0/176
false failures.

The benign variants are a full JS refactor, visual restyles, a 600ms deferred
render, a 900ms slow API, a 500ms async submit, a 500ms slow save, a session
moved from local storage to a cookie, a React save behind a 400ms simulated
API call, and a server store rewritten to use a Map. All of them passed every
check: auto-retrying expectations absorb timing, role-based locators survive
restyles and refactors, and the replayed sign-in state carries both cookies
and local storage.

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
| + JSON mode and timeout (todo and notes only) | 4/6 | — | — | — | **6/6** | 0/41 |
| + `checked` expectation, "don't invent behaviour" rule (all four apps) | 3/6 | **6/6** | 5/6 | 14/18 (78%) | 2/6 ⁴ | 0/156 |

| + independent-checks and accessible-name rules, text-matching role locator | 0/6 ⁵ | 2/6 | 0/6 ⁵ | 2/18 | 4/6 | 0/70 |

⁴ Notes stopped being held out once its run-3 diagnosis shaped the prompt
rule. From this row on, its numbers count like the others.

⁵ The router returned replies with 0% executable checks, then no JSON at all,
so only 1–2 checks per app were left. That is a model failure, not a prompt
regression, though a longer prompt may make weak free models worse.

### Conclusion: stop tuning against `openrouter/free`

Across five live runs the catch rate ranged from 25% to 83%, with no stable
trend. The router's choice of model dominates every prompt change, so further
tuning against it would fit noise. What held in **every** run: compiled checks
that pass on the correct app never produced a false failure (0 of 70–156 each
run). The open problem is getting enough good checks, not trusting the ones
that survive.

Next steps for the compiler (see the technical plan):

1. **Pin a capable model for drafting** and measure it with this benchmark
   before recommending it. Free routing is not production-grade for
   compiling contracts. *Partly done:* drafting now runs on Anthropic,
   OpenAI or OpenRouter (`[compiler]` in `contexer.toml`). A live run with a
   paid model has not been measured yet: the development machine has no
   paid key.
2. **Validate drafts against the running app.** *Done:* `contract draft` and
   `run "GOAL"` now try every drafted check on the app before approval and
   list which already pass, which fail (expected vs actual: "bug or wrong
   check?") and which cannot run yet.
3. **Retry when a reply is mostly non-executable**, within the 180-second
   per-attempt cap. *Done:* replies under 50% executable are retried.

Common model mistakes the validity filter caught:

- guessed wording ("1 notes" where the app says "1 note");
- invented controls ("Unpin X" where the button is "Pin X" and shows
  "Unpin");
- assumptions about where text appears (expecting "Dune" gone from the page
  after removing it from the cart, while it is still in the catalog).

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

### Diagnosis: why compiled checks failed on correct code

The third run recorded each dropped check, one per app:

- **todo:** the check asserted `attribute "checked" equals "checked"` after
  ticking a box. The `checked` attribute reflects only the initial markup and
  never changes on a click, so the check could never pass. The format had no
  way to say "is checked". **Fixed:** `checked` and `unchecked` expectations
  were added, and the attribute form is rewritten to them during validation.
- **notes:** the check asserted that unpinning a note "restores the original
  order", meaning oldest first. The app shows newest first and the goal never
  said otherwise, so this was invented behaviour. **Fixed** with a prompt rule:
  assert only what the goal states or the UI shows.

The same run caught 6 of 6 bugs on the held-out notes app and 4 of 6 on todo.
Comparing it with the second run shows how much one model call varies under
`openrouter/free`. Read the rows as directions, not rates.

The fourth run (all four apps, 16 of 24 caught) dropped 9 compiled checks.
Their causes:

- **Checks that depend on each other** (notes 6, probably signup 1). The model
  wrote checks as a sequence: "unpin the note" without creating it, or "3
  notes" assuming earlier checks had run. Every check starts on a freshly
  loaded page. **Fixed** with a prompt rule: each check creates its own state.
- **Visible text vs accessible name** (todo 2). The model clicked button
  "×", but the button's accessible name is its `aria-label`, "Delete Buy
  milk". **Fixed** in two ways:
  - a prompt rule;
  - a role locator now also matches a role element whose visible text
    matches. That only adds what a user can see, so expectations are never
    relaxed.

  The hand-written benchmark is unchanged after this: 24/24 caught, 0/176
  false failures.

### What this means for the product

- A one-line goal does not produce a trustworthy contract on its own with free
  models. The approval step is load-bearing: a person reads the checklist, and
  checks that fail on code they know works get fixed before approval.
- When the compiler does produce valid checks, they catch most seeded bugs,
  and every miss so far is an edge case the goal did not spell out.
- Run `contexer bench --live` with your own `OPENROUTER_MODEL` before trusting
  generated contracts.
