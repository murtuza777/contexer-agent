# Contexer documentation

## Use it

| Document | Covers |
| --- | --- |
| [Try it yourself](try-it.md) | Install, set up and use Contexer on your app, step by step |
| [Developer guide](../README.md) | Setup, every command, `contexer.toml`, tests |
| [Changelog](../CHANGELOG.md) | What changed in each release |

## How it works today (0.5)

| Document | Covers |
| --- | --- |
| [Architecture](architecture.md) | Every module, data format, algorithm, constant and security measure |
| [Benchmark results](../bench/RESULTS.md) | Seeded-bug catch rate and false failures |

## How it was built

| Document | Covers |
| --- | --- |
| [Agentic harness](agentic/architecture.md) | The design: Intent, Tester, Reviewer, Diagnoser and Triage agents, with code keeping the verdict |
| [Phase 0](agentic/phase-0.md) | Foundations |
| [Phase 1](agentic/phase-1.md) | The Tester agent and `contexer test` |
| [Phase 2](agentic/phase-2.md) | Intent, project skills and fix prompts |
| [Phase 3](agentic/phase-3.md) | The closed loop |
| [Phase 4](agentic/phase-4.md) | Reviewer and pull requests |
| [Phase 5](agentic/phase-5.md) | Security, cost, live runs, release |

Each phase file holds its tickets. The same tickets are GitHub issues, one
milestone per phase.

## Getting to a closed beta

Written on 2026-11-24. Proposals for the owner to read and accept.

| Document | Covers |
| --- | --- |
| [System audit](production/audit.md) | What the code is, what Phase 5 left, what three independent reads found, what was fixed and what is open |
| [Research](production/research.md) | The coding agents, the tools that verify them, the models, what developers report, with sources |
| [Roadmap](production/roadmap.md) | Position, milestones, launch blockers, quality gates, what "ready" means |
| [Tickets](production/tickets.md) | The backlog behind the roadmap |

## Research and history

These explain why Contexer is built the way it is. They are not kept up to
date with the code.

| Document | Covers |
| --- | --- |
| [Market research](product/market-research.md) | Who has the problem and what they pay for (October 2026) |
| [Technical landscape](product/technical-landscape.md) | The projects Contexer builds on, and its competitors (October 2026) |
| [Product plan](product/product-plan.md) | The plan versions 0.1 to 0.4 followed |
| [Technical plan](roadmap.md) | Milestones and formats for 0.1 to 0.4 |
| [Earlier multi-agent plans](archive/multi-agent/design.md) | Archived; superseded by the agentic harness: [design](archive/multi-agent/design.md), [PRD](archive/multi-agent/prd.md), [BRD](archive/multi-agent/brd.md), [build plan](archive/multi-agent/build-plan.md), [LangGraph study](archive/multi-agent/langgraph-port.md) |

## Around the product

| Document | Covers |
| --- | --- |
| [Website](../../website/README.md) | The landing page: run, build, deploy |
| [Launch kit](../../marketing/product-hunt.md) | Product Hunt copy, gallery and the launch video's sources |
