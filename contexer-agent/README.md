# Contexer Agent (Python)

> **Status**: Planning & Architecture Placeholder (Intentionally Not Implemented in this Milestone)

Contexer is an autonomous engineering agent that turns developer intent into verified code changes by orchestrating coding agents, inspecting application runtimes, and executing self-repair loops.

## Core Architectural Modules (Upcoming)

When implemented, the Python agent will consist of the following subsystem packages:

- **`intent/`**: Parses high-level engineering outcomes, requirements, and constraints.
- **`context/`**: Repository structural analysis, AST parsing, symbol indexing, dependency graphing, and runtime diagnostics.
- **`planner/`**: Directed Acyclic Graph (DAG) task planner that breaks down intent into ordered, verifiable atomic operations.
- **`runtime/`**: Adapters for code execution and coding agents (e.g., OpenCode, Codex, Claude Code).
- **`verifier/`**: Autonomous verification harness integrating Playwright for headless UI assertions, API testing, and log monitoring.
- **`repair/`**: Error diagnosis and diff generation to resolve mismatches between expected behavior and observed runtime state.

## CLI Experience (Target)

```bash
# Install via uv / pip
uv tool install contexer

# Launch interactive CLI
contexer

# Or run with explicit intent
contexer --intent "Implement token-based auth with refresh tokens"
```

## Milestone Roadmap

- [x] Milestone 1: Public landing page, web architecture, and design system (`website/`)
- [x] Milestone 2: Antigravity project skills (`.agents/skills/`)
- [ ] Milestone 3: Python agent core runtime & OpenCode adapter (`contexer-agent/`)
- [ ] Milestone 4: Verification engine & Playwright headless browser observation
- [ ] Milestone 5: Self-repair loop & multi-agent coordination
