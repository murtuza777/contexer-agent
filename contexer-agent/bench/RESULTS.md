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

## Tester suite (measures an agent that explores)

The Tester gets each app's one-line goal and the running app, never the
contract, and its findings are replayed by code
([method](README.md#the-tester-suite)).

### Azure AI Foundry `gpt-5.4`, 2026-11-17

`contexer bench --suite tester --agent tester`, 40 steps per variant, one run
per variant (40 bugs, 22 runs on correct or benign code):

| App | Seeded bugs | Found | False alarms on correct code | Rejected | Tokens in |
| --- | --- | --- | --- | --- | --- |
| todo | 6 | 5 | 0 / 4 runs | 0 | 2.3M |
| shop | 6 | 5 | 0 / 3 runs | 0 | 2.9M |
| signup | 6 | 2 | 0 / 3 runs | 3 | 1.4M |
| notes | 6 | 5 | 0 / 3 runs | 2 | 2.5M |
| members | 5 | 1 | 0 / 3 runs | 3 | 1.4M |
| budget-react | 6 | 3 | 0 / 3 runs | 1 | 2.3M |
| guestbook-next | 5 | 4 | 0 / 3 runs | 2 | 1.1M |
| **total** | **40** | **25** | **0 / 22 runs** | 11 | **14.0M** |

Per-app detail and the bugs not found: [tester-results/tester.md](tester-results/tester.md).
For comparison, the hand-written contracts catch 40 of 40, and contracts a
free model drafted from the same goals caught 33 of 40 (below).

**What the numbers say.**

- **No false alarm on correct code**, in 22 runs. That is the target the
  product stands on: a person is never told about a bug that is not there.
  It did not hold on an app the prompt had never seen: see the held-out
  result below before quoting this number.
- **25 of 40 found.** An earlier run of six of the apps found 24 of their 35,
  and this one 21 of the same 35: the 21 are a subset of the 24. The three lost
  (`members/no-auth-guard`, `signup/submit-reloads-page`,
  `budget-react/category-ignored`) were reported both times, and the second
  time with a check the correct app fails too. So the prompt changes between
  the runs did not raise the number found; what they bought is the bug-must-
  quote-the-goal rule and the lessons listed below. One run per variant is
  noisy by a few bugs either way; these are not precise rates.
- **11 findings were rejected**: they reproduced on the seeded bug, but the
  correct app fails the same check, so they prove nothing and are not
  counted. Reading them, most are the right bug with a guessed expectation
  (a URL containing "sign-in" where the page is `login.html`, the wording of
  an error the buggy app never shows). A user running `contexer test` has no
  correct app to compare with and would be shown these as confirmed bugs;
  for the seeded bugs that would have been right.
- **Cost.** About 225,000 input tokens per 40-step run, 14.0M for the suite.
  Azure reports no price per call; read the cost in the portal.

**Why bugs were missed.** Each of the 15 was looked up in the kept
transcript of this run:

| What the transcript shows | Bugs | Note |
| --- | --- | --- |
| Seen, and the check was rejected | `members/sign-out-keeps-session`, `members/no-auth-guard`, `signup/submit-reloads-page`, `budget-react/category-ignored` | The Tester reported the failure with an expectation the correct app fails too (above) |
| Seen, and accepted as correct | `members/welcome-shows-email`, `members/count-not-pluralised`, `guestbook-next/name-dropped` | It read "Welcome, demo@example.com" as a welcome by name; it saw "1 projects" and expected exactly that; it expected "Alice: Hello world", saw the name missing, and took its own expectation to be the mistake |
| Seen, and raised as a question | `signup/email-not-validated`, `budget-react/amount-not-cleared` | For the amount field the goal is silent, so a question is the designed outcome. For the email it is a real miss: "not-an-email" was accepted, the goal says invalid input is rejected, and the Tester still asked instead of reporting |
| No failing expectation in the run | `shop/all-keeps-filter`, `budget-react/filter-stuck`, `notes/pin-not-reordered`, `todo/input-not-cleared`, `signup/password-min-wrong`, `signup/stale-error` | It filtered but never went back to "All", or never tried the case. Three of these six runs ended on the 40-step limit; 17 of all 62 did |

Two of these point at a tension in the Tester's instructions, not at the
model. Telling it to expect only what it has seen on the page stops guessed
wording, and also makes it accept what a buggy page shows ("1 projects").
Telling it that anything the goal does not state is a question stops
opinions being reported as bugs, and also made it timid about a goal that
did cover the case. One-line goals leave a lot unsaid; the answers a person
gives to those questions are what Phase 2 stores and tests against.

**What the live runs changed in the code** (each found in a transcript, each
now covered by a test):

- an action that landed but reported a timeout left the recording out of
  step with the page; the recording is now verified or marked unreliable;
- `reset` returns the page, and a behaviour that acts on one item of a list is
  tested with two (todo went from 3 of 6 to 5 of 6);
- behaviour the goal does not mention is a question, and a bug must quote
  the words of the goal it breaks;
- the sign-in email was masked as a secret, which hid a page greeting the
  member by email;
- a console line for a request the server refused (HTTP 400 on empty input)
  was reported as a crash on the correct guestbook app: 3 of 3 clean runs in
  the first attempt at this round. Only an uncaught exception counts now;
  `guestbook-next` was run again after that fix and is the row above;
- a Next.js dev server refused to start when it saw the agent session's
  environment.

**Caveats.** One model, one run per variant, and the Tester's prompt was
changed between the two runs using what the first one showed. The seeded
bugs were not used to write expectations, but the prompt has seen these
apps' failure modes; a held-out app would be the honest next measurement.

### A held-out app, `bookings`, 2026-11-18

The seven apps above are not a fair test of the Tester any more: its prompt
was changed using what its runs on them showed. `bookings` (a slot-booking
app, 6 seeded bugs, 3 benign variants) was written afterwards and no prompt
has been tuned on it. Same model and settings, one run per variant, three
measurements as guards were added:

| Measured with | Found | False alarms on correct code | Tokens in |
| --- | --- | --- | --- |
| The Tester as it was after the seven-app runs | 3 / 6 | **2 in 4 runs** | 2.3M |
| + the Challenger (a second model look at each bug) | 3 / 6 | 1 in 4 runs | 2.7M |
| + "the app said why" (decided by code) | 3 / 6 | **0 in 4 runs** | 2.7M |

**The first row is the honest number for what the seven-app result claimed.**
Zero false alarms on the apps the prompt had seen became two in four on one
it had not. Both were the same mistake: the app clears the name field after
a booking, the Tester clicked a second slot without typing a name again,
the app said "Enter your name", and the Tester reported "booking a second
slot fails". It reproduces every time, so replay confirmed it, and it quotes
the goal, so the quote rule passed.

What was tried, in order:

1. A failed check now tells the Tester what the app is showing ("The page
   is showing: Enter your name"). The Tester recorded the bug anyway.
2. The Challenger, a separate model call that reviews each confirmed bug
   and can only set findings aside, caught it in one run and let it stand
   in another.
3. A rule in code, with no model: a check that failed while the app was
   displaying its own message (`role=alert`) is not asserted as a bug. It is
   listed for the person with that message. This removed the remaining one.

Two model-judgement layers reduced the false alarm and did not remove it;
the rule that removed it is the one that does not ask a model. The
Challenger stays as a filter for other mistakes. On `todo` it cost nothing:
5 of 6 found and no false alarm, as before.

**Caveats, which matter here.**

- `bookings` was held out for the first row only. The Challenger and the
  "app said why" rule were written after seeing it fail, so rows two and
  three show that the fixes work on the case they were built for, not that
  they generalise. Another unseen app is needed for that.
- The rule costs recall where a real bug shows an alert: such a finding is
  listed for the person and not reported as a bug. None of the six bugs in
  `bookings` was lost to it; it has not been run on the other seven apps.
- The same three bugs were missed in all three measurements. In the last
  one's transcripts: for `cancel-wrong-slot` the Tester only ever cancelled
  the earliest booking, which is the one the bug removes anyway; for
  `double-booking` it saw the Book button still there on a booked slot and
  raised it as a question instead of trying to book again; for `stale-name`
  it booked under several names and never checked the name shown for a
  later booking.
- One run per variant; the same author wrote the app, its bugs and the
  guards.

### Stub agent, 2026-11-15

`contexer bench --suite tester --agent stub`: 0 of 40 bugs found, 0 false
alarms, every app started. The stub reports nothing; this is the floor.
[tester-results/stub.md](tester-results/stub.md).

## LLM-compiled contracts (measures the compiler)

### Pinned free model, 2026-10-26

`OPENROUTER_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free contexer bench --live --repeats 1`.
The model drafts each app's contract from its one-line goal, grounded in the
running app's UI. Checks that fail on the correct app are dropped, and the
rest are scored against the seeded bugs.

| App | Drafted checks | Dropped (failed on the correct app) | Bugs caught | Missed | False-failing checks |
| --- | --- | --- | --- | --- | --- |
| todo | 8 | 0 | 4/6 | delete-wrong-task, input-not-cleared | 0/32 |
| shop | 10 | 0 | **6/6** | | 0/30 |
| signup | 7 | 1 | **6/6** | | 0/18 |
| notes | 10 | 1 | 5/6 | pin-not-reordered | 0/27 |
| members (signed in) | 6 | 1 | 4/5 | count-not-pluralised | 0/15 |
| budget-react ⁶ | 10 | 0 | 4/6 | amount-not-cleared, delete-removes-last | 0/30 |
| guestbook-next ⁶ | 6 | 2 | 4/5 | message-not-required | 0/12 |
| **total** | 57 | 5 | **33/40 (82%)** | 7 | **0/164** |

Every draft came from the model, with no rule-based fallback, in 42–142 s
per app. The misses are cases the goal didn't spell out and the model didn't
think of. For example, its delete check removed the *last* item, so a bug that
always deletes the last item went unnoticed. Next.js dropped two checks for a
real reason: the app answers an empty message with HTTP 400, which the
browser logs as a console error, and the model also expected no console
errors.

⁶ In the original run, both dev-server apps came out invalid. An
`npm install`, two OpenCode turns and a cold Vite start were running on the
same machine at the time, and the dev servers' first compiles outlasted
Contexer's waits.
Replaying the *same model-written contracts* on an idle machine, with no new
model calls, kept 10/10 and 4/6 checks, and those are the scores shown. The
waits for dev-server apps were then lengthened (first load 60 s,
expectations 2.5×), because users' machines are busy too.

### Random free model (`openrouter/free`), 2026-10-15 and 16

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
