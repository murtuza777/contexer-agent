# BRD: multi-agent Contexer

> **Superseded.** This was the plan on 2026-11-03. The current plan is the [agentic harness](../agentic/architecture.md), which keeps the proof rule but replaces this design. Kept for the reasoning and the research it records.

Status: draft, 2026-11-03. Owner: murtuza777.
Product requirements: [prd.md](prd.md). Design: [design.md](design.md).

Figures marked *assumption* are hypotheses to test, not data. The market
reasoning behind Contexer as a whole is in
[product-plan.md](../product/product-plan.md) §2.

## 1. Summary

Contexer is an open-source acceptance gate for AI coding agents: it turns a
goal into checks a person approves, lets Claude Code, Codex or OpenCode build,
proves every check in a real browser, repairs, and hands over a pull request
with the proof. 0.4.0 is prepared as the first PyPI release; it is published when the `v0.4.0` tag is pushed.

This initiative extends it from single changes on simple apps to
feature-sized work on real multi-service codebases, by adding agents that
remove setup work and improve checks and repairs, while keeping the one
thing that differentiates it: **the verdict comes from code and a browser,
never from a model.**

## 2. Business problem

AI coding agents made writing code cheap; checking it did not get cheaper.
Teams and solo builders spend their time on the second half: clicking
through the app, reading diffs, re-running flows after each agent change, and
finding what the agent broke elsewhere. The agents' own reports ("done",
"all tests pass") cannot be trusted as the decision to merge.

Contexer 0.4 addresses this for small, well-configured apps. The users with
the most to gain, people with real products, hit three walls: setup on
multi-service stacks, goals too large for one agent turn, and the cost of
reviewing proven-but-risky diffs.

## 3. Objectives

| # | Objective | Target |
| --- | --- | --- |
| B1 | Activation on real repositories | ≥ 60% of new users reach a first proven run on their own repo (*assumption*: today well below that on multi-service repos) |
| B2 | Credibility | Zero known false passes in public benchmarks and reported issues |
| B3 | Adoption | 1,000 PyPI installs a month and 50 repositories with the GitHub Action, 3 months after 0.7 (*assumption*) |
| B4 | Team pull | 10 teams using the issue flow weekly (*assumption*) |
| B5 | Launch | A Product Hunt and Hacker News launch with a live demo on a real app, not a to-do demo |

## 4. Stakeholders

| Stakeholder | Interest |
| --- | --- |
| Owner (murtuza777) | Product direction, launch, portfolio |
| Users: solo founders, indie devs | Ship features with agents without manual QA |
| Users: small engineering teams | Let agents take tickets, merge only proven work |
| Contributors | Clear architecture, testable parts |
| Agent vendors (Anthropic, OpenAI, OpenCode) | Contexer drives their CLIs; no partnership assumed |
| Model providers (OpenRouter and others) | BYOK traffic; free-tier limits shape the design |

## 5. Scope

**In scope:** Scout, Planner, Spec writer with Critic, parallel builders in
worktrees, Integrator, Diagnoser, Reviewer, a LangGraph engine with resume,
the updated PR and issue flow, documentation, benchmark extensions.

**Out of scope:** a hosted SaaS, a GitHub App with check runs (planned
separately), a proprietary coding agent, billing, enterprise SSO.

## 6. Market and positioning

- **Coding agents** (Claude Code, Codex, Cursor, OpenCode, Devin-style
  agents) build and report on their own work. Contexer rents them and checks
  them.
- **Multi-agent frameworks** (LangGraph, CrewAI, AutoGen) are toolkits, not
  products; Contexer uses LangGraph internally and is not competing with it.
- **AI test generators and QA agents** write or run tests but leave the
  decision with the same model family, or need a separate QA setup.
- **CI and preview platforms** run what you configured; they do not turn a
  goal into checks or drive an agent to pass them.

**Position:** "Many agents may build. Only proof merges." The multi-agent
version must not dilute that: marketing shows agents doing the work and the
browser deciding, with real evidence.

## 7. Business model

Today: MIT open source, bring your own keys, no Contexer server.
Options, in order of preference (*all assumptions to validate*):

1. **Open-source core, stays free:** CLI, GitHub Action, all agents
   described here.
2. **Hosted gate (later):** a GitHub App that runs proof on preview
   deployments, stores evidence and history, and handles approvals; priced
   per repository or per proven PR.
3. **Team features (later):** contract libraries across repos, dashboards
   of false-pass and regression rates, policy (who may approve).

The multi-agent work is a prerequisite for (2) and (3): without zero-config
setup and feature-sized goals, a hosted gate has too little to gate.

## 8. Costs

| Item | Estimate |
| --- | --- |
| Engineering | About 7–9 weeks of one engineer across 0.5–0.7 ([build-plan.md](build-plan.md)) |
| Model spend for development and benchmarks | Free-tier models where possible; *assumption* under $150 for paid runs used in evaluation |
| Infrastructure | None new for 0.5–0.7 (no hosted checkpointer required) |
| Users' cost per run | Their own agent and model keys; the graph adds about 10–20 drafting requests for a multi-slice goal and must add ≤ 10% for one-slice goals |

## 9. Benefits

- Users on real stacks can start without config, which unlocks the users who
  matter commercially.
- Larger goals finish, which turns Contexer from a bug-fix tool into a
  feature tool.
- Fewer weak checks protect the core promise (no false passes).
- A credible "agentic" story for launch, without giving up the deterministic
  verdict, which is the differentiation.

## 10. Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| "Multi-agent" adds cost and latency without better outcomes | Users churn; launch claims ring hollow | Each agent ships only if its benchmark metric improves (PRD §2) |
| A false pass on a public demo | Credibility loss | The Prover stays deterministic; demos run on seeded-bug cases too |
| Agent vendors ship their own verification | Positioning squeezed | Stay agent-neutral and prove across vendors; evidence and contracts are portable |
| Free-tier limits block evaluation by new users | Poor first impression | Small runs stay within 3 requests; clear quota messages (already in 0.4) |
| Framework churn (LangGraph) | Maintenance cost | Thin node wrappers; rules and agents in plain Python |
| Solo maintainer capacity | Slow releases | Phased releases; each one usable alone |

## 11. Assumptions and dependencies

- Claude Code, Codex and OpenCode keep headless interfaces (stream-json,
  `exec --json`, `opencode serve`).
- LangGraph's `StateGraph`, `Send`, `interrupt` and checkpointers remain
  available in the 1.x line.
- Users can provide test credentials and local services for their apps.
- PyPI trusted publishing for `contexer-agent` is set up (done; the first
  release waits on the `v0.4.0` tag).

## 12. Success criteria and decision points

| After | Continue if | Otherwise |
| --- | --- | --- |
| 0.5 | Scout setup success ≥ 8/10 repos; Critic improves catch rate with 0 false failures | Keep the agent that met its bar, drop the rest |
| 0.6 | Feature-set proven runs +30 points; small runs within 10% cost | Ship the Planner off by default; keep the single loop as the default engine |
| 0.7 | One live PR on a real repo merged without changes; Reviewer bar met | Reviewer stays opt-in |

## 13. Approval

| Role | Name | Decision |
| --- | --- | --- |
| Owner | murtuza777 | pending |
