# Contexer

**The AI engineer that owns "done".**

Contexer sits on top of the coding agents you already use: Claude Code, Codex
and OpenCode. It works in four steps:

1. It turns a goal into checks you approve.
2. It has the agent build against them.
3. It proves every check in a real browser.
4. It repairs failures in a bounded loop.

After that, it re-checks everything you ever approved on every later change,
and blocks the merge when behaviour regresses.

You make two decisions per task: **what "done" means**, and **whether to
merge**. Everything between is Contexer's job.

---

## Why

Coding agents write code faster than anyone can check it.

- Agent pull requests wait several times longer for review and merge far less
  often than human ones.
- Independent reviewers reject about half of agent changes that pass their
  tests.
- Agents have been caught editing tests to make them pass.

Every agent vendor's own verification is run and graded by the agent that
wrote the code, and some vendor reviewers are designed never to block a
merge. The research behind this is in
[reports/AI coding workflows and pain points.md](reports/AI%20coding%20workflows%20and%20pain%20points.md).

Contexer is the independent half:

- **Proof, not opinion.** Checks are executed in Chromium. Every verdict says
  whether a browser proved it (`proven`) or a model judged it (`LLM-judged`).
  Only proven verdicts can pass the gate.
- **The agent can't move the goalposts.** Approved contracts are hashed. An
  agent that edits one has its run refuted, and the contract is put back.
- **Bounded, reversible repair.**
  - Every attempt is snapshotted.
  - An attempt that makes things worse is reverted to the best one.
  - A failure that repeats unchanged forces a fresh approach instead of the
    same retry.
  - The run stops after a fixed number of rounds or at a budget.
- **Memory that is enforced.** Every approved contract is replayed on every
  later change, as a regression suite, with no LLM calls.
- **Fail-safe gate.** Anything undecided blocks the merge; nothing reports a
  quiet pass.

## What it looks like

A todo app whose "complete" handler throws:

```text
$ contexer verify --contract todo-basics
  ✓ add-shows-task Adding a task shows it in the list · proven
  ✓ add-clears-input The input is cleared after adding a task · proven
  ✓ empty-not-added Submitting an empty task adds nothing · proven
  ✓ count-tracks-adds The remaining count goes up with each task added · proven
  ✗ complete-decrements Completing a task lowers the remaining count and raises no errors · proven
        expected: text of [data-testid="remaining-count"] equals "1 left"
        actual:   "2 left"
        uncaught exception: refesh is not defined
  ✓ delete-removes-right-task Deleting a task removes that task and keeps the others · proven
  ✓ loads-clean The app loads without uncaught exceptions or console errors · proven

FAIL: 6 verified, 1 refuted, 0 unverified                      (exit code 1)
```

Each run also writes a self-contained `report.html`. It contains:

- the verdict, and the reasons for it, up front;
- expected vs actual for every refuted check;
- the screenshot each check was judged on;
- Playwright traces for failures;
- for `contexer run`, every attempt the agent made and the final diff.

## Quickstart

Contexer isn't on PyPI yet, so install it from GitHub (Python 3.11+):

```bash
pip install "git+https://github.com/murtuza777/contexer-agent.git#subdirectory=contexer-agent"
python -m playwright install chromium
contexer doctor        # checks Chromium, git, Node, model keys and agents, with the fix for each
```

See it catch a real bug in about ten seconds, with no API key and no agent:

```bash
contexer demo          # a todo app with a bug an AI left in, proven against its contract
contexer demo --fix    # then the repair loop, driven by a clearly labelled simulated agent
```

In your app's directory:

```bash
contexer init --ci     # detect how the app starts; add the GitHub merge-gate workflow

# 1. Describe what must be true. Contexer starts your app (static, Vite or Next.js),
#    compiles the goal into checks grounded in the live UI, and tries each check on the
#    app as it is: which already pass, which fail, which can't run yet.
#    Needs ANTHROPIC_API_KEY, OPENAI_API_KEY or OPENROUTER_API_KEY.
contexer contract draft "Users can add a task and complete it, and the count updates"

# 2. Read the checklist and lock it in. Commit .contexer/contracts/.
contexer contract show <id>
contexer contract approve <id>

# 3. Prove it, with no LLM involved.
contexer verify --contract <id>

# 4. Or let a coding agent build or fix it until every check is proven.
contexer run --contract <id> --agent claude-code
```

Or do it all in one step:
`contexer run "Users can add a task and complete it, and the count updates"`.
Contexer shows the checklist and asks you to approve it before any code
changes.

### Apps behind a login

Tell Contexer how to sign in, with a test account, in `contexer.toml`:

```toml
[auth]
url = "/login"
steps = [
  { action = "fill", target = { label = "Email" }, value = "${CONTEXER_TEST_EMAIL}" },
  { action = "fill", target = { label = "Password" }, value = "${CONTEXER_TEST_PASSWORD}" },
  { action = "click", target = { role = "button", name = "Sign in" } },
]
expect = [{ kind = "url", contains = "/dashboard" }]
```

It signs in once per run and starts every check signed in; a check marked
`"login": false` runs as a signed-out visitor. `${NAME}` values come from the
environment (CI secrets) or the project's `.env`. They are never written to
contracts, and typed secrets and password fields are masked in reports and in
what the coding agent sees.

## Gate merges in CI

```yaml
# .github/workflows/acceptance.yml
name: Acceptance gate
on: [pull_request]
permissions:
  contents: read
  statuses: write
jobs:
  gate:
    runs-on: ubuntu-latest
    env:                                       # only if contexer.toml has [auth]
      CONTEXER_TEST_EMAIL: ${{ secrets.CONTEXER_TEST_EMAIL }}
      CONTEXER_TEST_PASSWORD: ${{ secrets.CONTEXER_TEST_PASSWORD }}
    steps:
      - uses: actions/checkout@v7.0.1
      - uses: actions/setup-node@v7.0.0        # if your app needs Node
        with: { node-version: "22" }
      - uses: murtuza777/contexer-agent@main
        with:
          working-directory: .
```

The action does four things:

1. Replays every approved contract against the PR's code.
2. Posts a `contexer/acceptance` commit status that links to the evidence.
3. Writes a per-check table into the job summary.
4. Uploads `report.html` as the `contexer-report` artifact.

Make `contexer/acceptance` a required check and nothing merges until the
behaviour is proven. This repository runs the action on its own todo fixture
([`acceptance-gate.yml`](.github/workflows/acceptance-gate.yml)).

## How accurate is it?

`contexer bench` replays contracts against fixture apps with seeded bugs. It
also runs them against harmless variants (refactors, restyles, slow APIs),
which must still pass.

| Contracts | Seeded bugs caught | False-failing checks on correct code |
| --- | --- | --- |
| Hand-written (6 apps, 35 bugs) | **35/35** caught with proof | **0/248** (38 clean runs) |
| Compiled by the LLM from one-line goals (`--live`, free models) | 25–83% per run | 0 in every run |

- **Hand-written row:** the contracts and the bugs were written by the same
  author, so this row measures the runner's reliability, not how good
  generated contracts are.
- **Live row:** this measures generated contracts. It varies a lot from run to
  run with free models. Its misses are edge cases the goal didn't spell out,
  plus checks the model got wrong, which is why a person approves every
  contract.

Full method, per-run tables and the diagnosis of bad compiled checks are in
[bench/RESULTS.md](contexer-agent/bench/RESULTS.md).

<a id="benchmark-details"></a>
<details><summary>Benchmark details</summary>

- **Fixtures:** todo, a shop (filters, search, cart arithmetic, async data),
  a signup form (validation, error states, a submit that reloads the page), a
  notes app (pinning, search in body text, deletes), a members area behind a
  sign-in (welcome, projects, sign-out, a guard for signed-out visitors), and
  a React 19 + Vite 8 budget tracker started through its own dev server.
  They live in [`contexer-agent/bench/fixtures`](contexer-agent/bench/fixtures).
  Each bug has a `BUG.md` naming the check expected to catch it, and every
  bug was caught by that check.
- **Validity rule:** a contract that fails on the correct app is not scored.
- **Scoring:**
  - **Caught:** a proven check is refuted.
  - **Flagged:** the merge is blocked without proof (a check is only
    unverified, or the app did not start).
  - **False failure:** any check not verified, or an app that did not start,
    on correct or harmless code.

</details>

## Status

What works today, with tests (442 passing) and CI on Linux:

- Contracts, approval and hashing; `verify`, `replay`, `contract`, `run`,
  `doctor` and `bench` (including `--live`).
- Drafts that are tried on the running app before approval.
- Starting the project's dev server (static, Vite, Next.js, or a command in
  `contexer.toml`): `npm ci` from the lockfile, a reinstall when an agent
  changes dependencies, and killing the whole process tree on Windows.
- Apps behind a login (`[auth]`), with secrets masked in all evidence.
- Drafting with Anthropic, OpenAI or OpenRouter models.
- The repair controller: snapshots, keep-best, revert, fresh session on a
  repeated failure, tamper guard and regression replay.
- GitHub: the commit status, the job summary, and a reusable action.

Honest gaps:

- **No live coding-agent run yet.** The Claude Code, Codex and OpenCode
  adapters are tested against their real stream protocols with fake binaries,
  and the full loop is tested with a scripted agent. The real Codex CLI
  accepts the exact invocations Contexer uses, up to authentication. A
  complete live run hasn't happened yet: the development machine has no
  Claude API credit or OpenAI key, and OpenCode's free tier refuses
  programmatic use.
- No GitHub App (check runs, approve button) yet; not on PyPI yet.
- No visual-design checks. Sign-in sessions kept only in `sessionStorage`
  are not carried into checks (cookie and local-storage sessions are).
- Draft quality depends on the model. Free OpenRouter models are slow
  (minutes) and vary from run to run (25–83% of seeded bugs caught). A paid
  model has not been benchmarked yet, for lack of a paid key on the
  development machine. Replays never call a model.

## Docs

| Document | Covers |
| --- | --- |
| [Product plan](contexer-agent/docs/product-plan.md) | Who it's for, what it does, and the order of work |
| [Technical plan](contexer-agent/docs/roadmap.md) | Architecture, formats and milestones |
| [Technical landscape](contexer-agent/docs/technical-landscape.md) | The repos and designs Contexer builds on, and its competitors |
| [Developer guide](contexer-agent/README.md) | Setup, commands, `contexer.toml` and tests |

MIT licensed. Contexer adapts parts of
[AgentForge](https://github.com/MohitGoyal09/AgentForge) (MIT); see
[THIRD_PARTY_NOTICES](contexer-agent/THIRD_PARTY_NOTICES.md).
