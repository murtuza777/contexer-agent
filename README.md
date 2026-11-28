# Contexer

[![PyPI](https://img.shields.io/pypi/v/contexer-agent.svg)](https://pypi.org/project/contexer-agent/)
[![CI](https://github.com/murtuza777/contexer-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/murtuza777/contexer-agent/actions/workflows/ci.yml)
[![Acceptance gate](https://github.com/murtuza777/contexer-agent/actions/workflows/acceptance-gate.yml/badge.svg)](https://github.com/murtuza777/contexer-agent/actions/workflows/acceptance-gate.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)

**The engineer that owns "done" for your coding agent.**

Contexer does not write code. It sits on top of the coding agent you already
use (Claude Code, Codex, OpenCode) and does what a senior engineer does for
a junior one:

1. It turns a goal into checks, and you approve them.
2. It briefs the agent: which files, what to reuse, what must not change.
3. It replays every check in a real browser. Only that counts as proof.
4. It sends the agent back with what the browser saw, until the checks pass
   or a limit you set is reached.
5. It reads the diff for what a check cannot see, and hands you a pull
   request with the evidence.

You make two decisions per task: **what "done" means**, and **whether to
merge**.

```bash
pip install contexer-agent     # or: uv tool install contexer-agent, pipx install contexer-agent
contexer demo                  # no key needed: a todo app with a bug, caught in about ten seconds
```

The package is `contexer-agent`; the command is `contexer`. Python 3.11 or
newer, on Linux, macOS and Windows.

## Two ways to use it

### Inside the coding agent you already work in

One command sets the agent up in a project that has approved checks:

```bash
contexer init --agent claude-code     # or: codex, opencode
```

| It adds | What that does |
| --- | --- |
| An MCP server (`contexer mcp`) | The agent can read the approved checks and have them replayed in a browser |
| A stop hook | The agent cannot end its turn while an approved check fails (Claude Code and Codex; OpenCode has no hook that can refuse a stop) |
| Instructions | When to call Contexer, and that it may not edit the checks |

No tool lets the agent approve, edit or skip a check. Approval stays with
you, in a terminal.

### Let Contexer drive the agent

```bash
contexer setup                 # your own model key, tested with one real request
contexer run "Users can add a task and complete it, and the count updates"
```

Contexer shows what it understood and the checks, and waits for you:
`y` approves, `n` does not, `e` opens the checks in your editor, a sentence
says what to change. Then the agent builds, every check is replayed, and
failures go back with what the browser saw. Add `--pr` to end in a pull
request, or `--issue 42` to take the goal from an issue.

To test what an agent already built, without changing any code:

```bash
contexer test "Users can add tasks and complete them, and the remaining count stays correct"
```

It uses your running app the way a person would, reports only what a replay
by code confirms, and writes the fix prompt to paste into any coding tool.

[Try it yourself](contexer-agent/docs/try-it.md) walks through every step.
[Using Contexer](contexer-agent/docs/usage.md) covers your own key, pull
requests, apps behind a login, the merge gate in CI and the issue workflow.

## What it looks like

A todo app whose "complete" handler throws (the output of `contexer demo`):

```text
$ contexer verify --contract todo-basics

contexer verify · readme-demo
  Contract    todo-basics · approved
  App         http://127.0.0.1:57319/ (static)

Users can add, complete and delete tasks, and the remaining count stays correct
  ✓ Adding a task shows it in the list · add-shows-task · proven
  ✓ The input is cleared after adding a task · add-clears-input · proven
  ✓ Submitting an empty task adds nothing · empty-not-added · proven
  ✓ The remaining count goes up with each task added · count-tracks-adds · proven
  ✗ Completing a task lowers the remaining count and raises no errors · complete-decrements · proven
      expected: text of [data-testid="remaining-count"] equals "1 left"
      actual:   "2 left"
      expected: no uncaught exceptions or console errors
      actual:   refesh is not defined
      uncaught exception: refesh is not defined
  ✓ Deleting a task removes that task and keeps the others · delete-removes-right-task · proven
  ✓ The app loads without uncaught exceptions or console errors · loads-clean · proven

FAIL: 6 verified, 1 refuted, 0 unverified

Report      .contexer/runs/20261028-204055-914e/report.html
Took        9.2s
```

The exit code is 1. Each run also writes a self-contained `report.html`
with the verdict, expected and actual for every refuted check, the
screenshot each check was judged on, and for `contexer run` every attempt
and the final diff. [Using Contexer](contexer-agent/docs/usage.md) shows the
live view of a run.

## Why

Coding agents write code faster than anyone can check it.

- Agent pull requests wait several times longer for review and merge far less
  often than human ones.
- Independent reviewers reject about half of agent changes that pass their
  tests.
- Agents have been caught editing tests to make them pass.

Every agent vendor's own verification is run and graded by the agent that
wrote the code. The research behind this is in
[the market research](contexer-agent/docs/product/market-research.md).

Contexer is the independent half:

- **Proof, not opinion.** Checks are executed in Chromium. Every verdict says
  whether a browser proved it (`proven`) or a model judged it (`LLM-judged`).
  Only proven verdicts can pass the gate.
- **The agent cannot move the goalposts.** Approved checks are hashed. An
  agent that edits one has its run refuted, and the file is put back.
- **Bounded, reversible repair.** Every attempt is snapshotted, an attempt
  that makes things worse is undone, and the run stops after a fixed number
  of rounds or at a budget.
- **Memory that is enforced.** Every approved contract is replayed on every
  later change, with no model involved. A check the change broke is told
  apart from one that was already failing.
- **Fail-safe.** Anything undecided blocks the merge; nothing reports a quiet
  pass.

The reasons behind these rules are written down in
[docs/decisions](contexer-agent/docs/decisions/README.md).

## How accurate is it?

`contexer bench` replays contracts against fixture apps with seeded bugs,
and against harmless variants (refactors, restyles, slow APIs) that must
still pass.

| Contracts | Seeded bugs caught | False-failing checks on correct code |
| --- | --- | --- |
| Hand-written (7 apps, 40 bugs) | **40/40** caught with proof | **0/278** (44 clean runs) |
| Drafted from one-line goals by a pinned free model (`nemotron-3-ultra:free`, 7 apps) | **33/40** (82%) | **0/164** |
| Drafted by `openrouter/free`, which picks a random free model per request | 25–83% per run | 0 in every run |

The hand-written row measures the runner's reliability, since the contracts
and the bugs have the same author. The drafted rows measure what you get
from a one-line goal, which is why a person approves every contract. Zero
false failures in 44 clean runs does not rule out a true rate of up to 8%.
Method, intervals and per-run tables are in
[bench/RESULTS.md](contexer-agent/bench/RESULTS.md).

## Status

Version 0.7.0, with about 1,650 tests and CI on Linux, macOS and Windows.

- **Coding agents:** Claude Code, Codex and OpenCode, started by Contexer or
  calling it through MCP.
- **Contexer's own agents:** Intent, Planner, Tester, Challenger, Triage,
  Diagnoser and Reviewer, on any of 15 model providers with your key. All
  are read-only, and none decides whether the work is done. With no model
  configured, fixed rules decide each next step and a run still works.
- **Your app:** static files, Vite, Next.js, or a start command in
  `contexer.toml`; apps behind a login; apps that keep data on a server.
- **GitHub:** a merge gate, a pull request with the evidence, and a workflow
  that takes a labelled issue to a pull request.
- **Limits you set:** repair rounds, one budget in dollars, a model and a
  step cap per agent. A run says what it can cost at most before it starts.

What is not proven yet:

- **Web apps only**, in Chromium. No visual-design checks.
- **Set up inside an agent was run in Claude Code only**, not in Codex or
  OpenCode.
- **The two-job issue workflow has not been run on GitHub.**
- **One model was measured** for Contexer's agents (`gpt-5.4`). The effect of
  a cheaper model per agent is a setting, and is not measured.
- **The checks of the recorded live runs were approved with `--yes`**, not
  read by a person first.
- The budget cannot stop a coding agent in the middle of a turn, so one turn
  can overshoot it.

Live runs on a real project, the full list of gaps and what comes next are
in [readiness.md](contexer-agent/docs/agentic/readiness.md) and the
[roadmap](contexer-agent/docs/production/roadmap.md).

## Docs

Before you allow it on a repository, read
[what Contexer sends, and what it does not do](contexer-agent/docs/data-and-limits.md).
Contexer calls the model provider you configured with your own key and has no
telemetry. It never edits application code; the coding agent it starts does,
with that agent's own permissions and network access.

| Document | Covers |
| --- | --- |
| [Try it yourself](contexer-agent/docs/try-it.md) | Install, set up and use it on your app, step by step |
| [Using Contexer](contexer-agent/docs/usage.md) | Your own key, pull requests, logins, the CI gate, the issue workflow |
| [Developer guide](contexer-agent/README.md) | Every command, `contexer.toml` and the tests |
| [Architecture](contexer-agent/docs/architecture.md) | Every module, data format, algorithm and security measure |
| [Decisions](contexer-agent/docs/decisions/README.md) | The choices that would be expensive to reverse, with their reasons |
| [What Contexer sends](contexer-agent/docs/data-and-limits.md) | Which command calls which model, what each prompt contains, what stays on disk |
| [Changelog](contexer-agent/CHANGELOG.md) | What changed in each release |

The full index is in [contexer-agent/docs](contexer-agent/docs/README.md).

## Contributing

Bug reports, ideas and pull requests are welcome. [CONTRIBUTING.md](CONTRIBUTING.md)
covers setup, the rules the code must keep and what a pull request needs.
Report a vulnerability privately: see [SECURITY.md](SECURITY.md).

## Licence

MIT. Contexer adapts parts of
[AgentForge](https://github.com/MohitGoyal09/AgentForge) (MIT); see
[THIRD_PARTY_NOTICES](contexer-agent/THIRD_PARTY_NOTICES.md).
