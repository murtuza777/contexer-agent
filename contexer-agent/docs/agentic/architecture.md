# Contexer as an agentic harness

Status: approved plan, 2026-11-13. Nothing here is built yet. This document
replaces the plans in [`docs/multi-agent/`](../multi-agent/) where they differ.

Tickets: [Phase 0](phase-0.md) · [Phase 1](phase-1.md) · [Phase 2](phase-2.md) ·
[Phase 3](phase-3.md) · [Phase 4](phase-4.md) · [Phase 5](phase-5.md)

## 1. The problem

People build apps with coding agents in a loop:

1. prompt the agent;
2. the agent builds;
3. the person clicks through the app;
4. the person explains what they actually meant;
5. the agent fixes; back to 3.

This often takes 10–20 rounds. The person is the tester, the reviewer and the
fix-prompt writer. Contexer takes over those three jobs. It never writes code.

## 2. What changes from 0.4

Contexer 0.4 calls a model in one place: drafting checks. Everything else is a
fixed loop in `controller/run.py`. It cannot explore the app, read the diff,
work out a cause, or talk to the user about intent, and its repair prompts are
templates.

The new version adds five agents that do those jobs. One rule from 0.4 stays.

**The proof rule.** A result is `proven` only when a recorded check ran and
passed. An agent's opinion is never proof. Agents decide what to test, what is
wrong and what to fix; code and the browser decide whether it is done.

## 3. The loop

```text
goal or correction
      │
      ▼
   Intent ──── asks the user when unclear ────► intent spec + draft checks
      │                                                   │
      │                                          user approves
      ▼                                                   ▼
coding agent builds  ◄──── fix prompt ──── Diagnoser ◄── confirmed failures
      │                                                   ▲
      ▼                                                   │
   snapshot ──► Tester explores ──► freeze ──► replay ────┤
                Reviewer reads the diff ──────────────────┤
                                                          │
                                   Triage picks the next move
                                                          │
                                  gate passes ──► done / pull request
```

Contexer is the evaluator side of a generator–evaluator loop. The generator is
the external coding agent (Claude Code, Codex, OpenCode), unchanged.

## 4. The agents

| Agent | Job | Tools | Output |
| --- | --- | --- | --- |
| Intent | Turns the goal and every later correction into a written intent spec. Asks only when something is ambiguous | repo summary, live UI snapshot, ask the user | intent spec, draft checks |
| Tester | Uses the running app like a user: clicks, types, signs in, tries edge cases, reads console and network errors | browser tools, run a check, record a finding | findings with replayable steps |
| Reviewer | Reads the coding agent's diff against the intent: wrong logic, missing cases, secrets, weakened tests | diff, read file, grep, run tests / lint / typecheck | findings with file and line |
| Diagnoser | Works out the likely cause of each confirmed failure and writes the fix prompt | failure evidence, diff, server log, read file | repair prompt |
| Triage | Picks the next move from a fixed menu | none | one validated decision |

Triage's menu: repair in the same session, start a fresh approach, roll back
to the best attempt, ask the user, stop. Code validates the choice and offers
only moves that are legal in the current state.

## 5. Explore → freeze → replay

The Tester's browser tools are the same verbs as the check format in
`verification/checks.py` (`click`, `fill`, `press`, `select`, `goto`, and the
expectation kinds). Every action is recorded as a `Step`. So a finding converts
mechanically into a `Check`, and `CheckRunner` replays it in a fresh browser:

- a reported bug counts only if the replay reproduces it;
- a reported pass counts only if the replay passes;
- every confirmed check is saved, so the regression suite grows by itself and
  replays later with no model.

Findings that do not reproduce are dropped and logged, never shown as proven.

## 6. Intent memory

Corrections from the user ("no, deleting should ask first") are stored in
`.contexer/intent/` and loaded on every later run. The user explains a
behaviour once. The intent spec is plain Markdown the user can edit.

**Project skills.** After a run, Contexer saves what it worked out about the
app as short Markdown files in `.contexer/skills/`: how to sign in, how to
seed data, which flows are slow or fragile. The Tester loads the relevant ones
next time. A skill is advice for the agent; it is never proof.

**Where things are stored.**

| Data | Where | Why |
| --- | --- | --- |
| Intent, skills, contracts | Files in the project's `.contexer/` folder | Versioned with git, readable, shared with a team |
| Run evidence and transcripts | `.contexer/runs/<id>/` | One folder per run |
| Run history and resume state | SQLite in `.contexer/`, from Phase 3 | No server to run |
| Keys and user settings | `~/.contexer/` | Never in the project |

A hosted version would add Postgres. Nothing in Phases 0–5 needs a server.

## 7. What code owns

- Verdicts and the gate (`gate/decision.py`).
- Budgets, step caps, timeouts.
- Snapshots and rollback (`checkpoint/shadow.py`).
- The tamper guard.
- The rule that a run cannot end as `succeeded` unless the gate passes.

## 8. Runtime

| Need | Choice | Reason |
| --- | --- | --- |
| Agent loop (Phases 0–2) | Our own small loop, `run_agent` | One agent with tools needs no graph. OpenClaw and Hermes Agent are built the same way |
| Model calls with tools, any provider | LangChain chat models built from our provider catalog | Our `llm/` layer has no tool calling |
| Pause for the user, resume (Phase 3) | LangGraph, decided in ticket T3.1 | `interrupt` and checkpoints fit a loop that must wait for a person. Not added before it is needed |
| Browser | Playwright in-process, our own tools | Reuses sign-in state and traces; actions can freeze into checks |
| Tracing | JSONL transcript per agent in the run folder; Langfuse optional | Off by default, self-hostable |
| Evals | The seeded-bug benchmark (7 apps, 40 bugs, benign variants) | Measures what the Tester must do |
| Coding agents | The adapters in `agents/` | Unchanged |

Exact package versions are pinned in ticket T0.2 after a working spike.

## 9. What is reused and what is replaced

Reused as it is: `verification/`, `gate/`, `appserver/`, `checkpoint/`,
`contract/`, `evidence/`, `github/`, `agents/`, `observer/`, `bench/`,
`config/`, and `llm/catalog.py`, `discovery.py`, `factory.py`.

Replaced: `controller/run.py` and `controller/prompts.py`. They stay available
as `--engine classic` until the new loop matches them on the benchmark, then
they are deleted. `workflow/criteria.py` folds into the Intent agent.

New packages:

```text
src/contexer/
  llm/chat.py        chat model with tool calling, from the catalog
  crew/              base.py (run_agent), intent, tester, reviewer, diagnoser, triage, prompts/
  browser/           tools.py (browser tools), recorder.py (actions → Steps), freeze.py (finding → Check)
  intent/            store.py (.contexer/intent/)
  skills/            store.py (.contexer/skills/)
  graph/             state.py, nodes.py, routing.py, build.py   (Phase 3)
```

## 10. Rejected

| Option | Reason |
| --- | --- |
| Claude Agent SDK as the base | Claude only; the product must work with any model |
| CrewAI, swarm, group chat | No single place decides "done" |
| A free-form LLM conductor | Unreliable on weaker models; can be tried later and measured |
| Playwright MCP, browser-use, Stagehand for the Tester | Cannot record actions into our check format |
| The agent's judgement as the verdict | LLM evaluators find bugs and then approve the work anyway |

Ideas borrowed without code: Anthropic's "Harness design for long-running
application development" (skeptical evaluator tuned with graded examples; a
contract agreed before building) and claw-orchestrator's verdict vocabulary.

## 11. Users

1. First: people building web apps with coding agents who are stuck in the
   prompt → test → re-prompt loop.
2. Second: small teams that want the merge gate. It exists today and keeps
   working.

## 12. Security

- Page content, issue text and repository files are data, never instructions.
- The Reviewer and Intent agents have read-only tools.
- No agent receives a GitHub token or a provider key.
- Secrets are masked in prompts and transcripts.
- The tamper guard covers contracts, the intent store and `contexer.toml`.

## 13. Phases

| Phase | Result | Stop for review |
| --- | --- | --- |
| 0 Foundations | Chat models with tools, `run_agent`, transcripts, the tester benchmark | yes |
| 1 Tester | `contexer test` explores an app and reports confirmed findings | yes |
| 2 Intent and fix prompts | Clarifying questions, intent memory, project skills, a fix prompt to paste | yes |
| 3 Closed loop | `contexer run` on the graph engine with Triage and resume | yes |
| 4 Reviewer and pull requests | Diff review; PR and issue flow on the new engine | yes |
| 5 Ready for users | Security pass, cost controls, live runs, release | yes |

Later, measured before adopting: a planner with parallel slices, attaching to
a live Claude Code session through hooks, a hosted version.

## 14. How each phase is verified

- Unit tests with a fake model and recorded replies; the existing suite stays
  green.
- `contexer bench --suite tester`: bugs found and confirmed, false alarms on
  clean and benign variants, against the hand-written baseline (40/40, 0/278).
- Phase 3: the existing controller tests run against both engines.
- Live runs on the demo app and then BurryAI, with the report and cost recorded.
