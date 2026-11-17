# Hardening and guardrails

Goal: before the closed loop is built, make what exists safe to put in front
of people. This pulls the parts of [Phase 5](phase-5.md) that cannot wait
(a spending cap, the security pass on the agents that exist) forward, and
adds guardrails that were never planned. See [architecture.md](architecture.md) §7 and §12.

Done when: the tickets pass, the suite is green, lint and type checks run in
CI, and a benchmark app the prompts have never seen is measured.

## The rule

**Assume the model is compromised.** A page, a file or a saved skill can
carry text written to steer the model. Telling the model to ignore it helps
and proves nothing. So every guardrail here is a property of the code: it
holds when the model does exactly what an attacker wants. Each one has a test
in which a scripted model plays that attacker.

What a compromised agent must not be able to do:

| It tries to | Stopped by |
| --- | --- |
| Report a bug that is not there | Replay: a finding that does not reproduce is never shown (Phase 1) |
| Spend without limit | A budget shared by every agent in a run (H1); caps on tool calls (H2) |
| Leave the app under test and act elsewhere | The browser stays on the app's origin (H3) |
| Click and type on a production site | A remote `--url` needs explicit consent (H4) |
| Change the project | No agent has a write tool; enforced by a test (H7) |
| Read secrets or Contexer's files | Read tools are confined (Phase 2); secrets are masked (Phase 0) |
| Steer the coding agent through the fix prompt | The brief is validated and capped; the prompt says what it may not ask (H6) |
| Plant instructions for later runs in a skill or the intent | Size caps, a full store refuses, changes are shown, `--no-skills` (H6) |
| Redefine "done" | The tamper guard covers contracts, the intent and `contexer.toml` (H8) |

---

## H1 A budget for the agents

**Scope.** `crew/budget.py`: `Budget(max_tokens, max_cost_usd)`, shared by
every agent of one run. `run_agent` checks it before each model call and
ends with status `budget_exhausted`. `[limits]` in `contexer.toml`
(`tokens`, `cost_usd`) and `contexer test --max-tokens N`; default 1,500,000
tokens per run. `result.json` lists what each agent used.

**Acceptance.**
- A run that reaches the budget stops making model calls; findings recorded
  so far are still replayed, and the fix prompt is written from the facts.
- The total in the summary equals the sum of the per-agent figures.

## H2 Caps on tool calls

**Scope.** At most 25 tool calls are run from one reply; the rest get an
error result. The same call with the same arguments four times in a row is
not run a fourth time.

**Acceptance.** A model that sends 200 calls in one reply runs 25. A model
that repeats one call forever is told to do something else and the run ends
on its step limit, not sooner or later.

## H3 The browser stays on the app

**Scope.** `goto` to another origin is refused. If an action leaves the
app's origin (a link, a redirect, a form), the page is brought back, nothing
is recorded, and the tool says so. Pop-ups to other origins are closed.

**Acceptance.** No step in any recording points outside the app's origin.

## H4 Consent for a remote target

**Scope.** `contexer test --url` with a host that is not this machine or a
private network stops with an explanation unless `--allow-remote` is given:
the Tester clicks, types and submits for real.

**Acceptance.** `--url https://example.com` exits 2 before a browser starts.

## H5 Untrusted text is marked

**Scope.** Page snapshots, project summaries, diffs, server logs and saved
skills are wrapped in a marker in every task an agent is given; text that
imitates the marker is neutralised. This is the soft layer: it reduces how
often a model is steered, and nothing depends on it.

**Acceptance.** No task contains unmarked page or file text; a closing
marker inside the text cannot end the block.

## H6 What agents write is validated

**Scope.**
- `RepairBrief`: files must exist inside the project and outside closed
  folders, else they are dropped; cause and instruction are capped. The fix
  prompt tells the coding agent that the cause and instruction come from a
  model that read the project's files, and what they may not ask for.
- Skills: description and body are capped, the store holds at most 30, and
  `--no-skills` neither loads nor saves any.
- Intent: the agent cannot change the goal; behaviours are capped in number
  and length; what a run added or changed is printed.

**Acceptance.** A brief naming `../../etc/passwd` or `.env` never reaches the
prompt. A skill of 50,000 characters is cut. A run that changes the intent
says so.

## H7 Tool audit

**Scope.** A table of which agent has which tool in `docs/architecture.md`,
and a test that fails when an agent gains a tool. A test that a full
`contexer test` run leaves every project file outside `.contexer/` byte for
byte unchanged.

## H8 The tamper guard covers `contexer.toml`

**Acceptance.** A coding-agent turn that edits `contexer.toml` ends the run
as `tampered` and the file is restored.

## H9 Engineering

**Scope.** `ruff` and `pyright` run in CI. Modules stop calling each
other's private functions. Work lands through pull requests; branch
protection on `main` is enabled by the owner.

## H10 A held-out benchmark app

**Scope.** One new fixture app with seeded bugs and benign variants, written
without looking at the Tester's transcripts and never used to change a
prompt. Its numbers are quoted apart from the seven apps the prompts have
seen.

**Acceptance.** The gate suite passes on it (every bug caught, no false
failure); the Tester is measured on it once and the result is published.

---

## Not in this pass

Left in Phase 5: the risk scan before a run (`.env` not ignored, committed
credentials), the `.contexer/**` deny rule for the Codex and OpenCode
adapters, a cheaper model per agent, a cost estimate before a run, and a
live injection run against a real model.
