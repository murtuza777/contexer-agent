# Contexer Agent (Python)

Contexer is an autonomous engineering CLI that sits above coding agents and coordinates software tasks from intent to implementation, runtime observation, dynamic verification, and self-repair.

The agent harness is a focused adaptation of AgentForge architectural patterns. See [the integration boundary](docs/agentforge-integration.md) and [third-party notices](THIRD_PARTY_NOTICES.md).

## Capabilities

```text
User Intent → Contexer CLI → Autonomous Loop → OpenCode (Coding Agent)
     ↑                                                ↓
     └──── Repair Engine ← Verifier ← Playwright (Observation)
```

1. **Interactive Shell**: Typer + Rich REPL with slash commands (`/help`, `/status`, `/project`, `/opencode`, `/loop`, `/github`, `/exit`).
2. **Provider Abstraction**: OpenRouter, Google Gemini, and OpenAI-compatible streaming LLM completions with structured tool calls.
3. **Workspace Tools & Safety**: File inspection/editing, read-only Git operations, bounded shell execution, and approval policies (`on-request`, `auto`, `never`).
4. **OpenCode Integration**: Async HTTP client and adapter interfacing with local OpenCode server (`http://127.0.0.1:4096`) for session management, prompt execution, and git diffs.
5. **Playwright Observation**: Headless browser automation capturing DOM structure, visible headings, interactive elements, console logs, network errors, and visual screenshots.
6. **Dynamic Verification & Self-Repair**: Decomposes user intent into acceptance criteria, verifies criteria against browser observations, diagnoses runtime failures, and dispatches repair prompts back to OpenCode.
7. **Official GitHub MCP Server**: Enforced read-only integration supporting stdio binary and Docker container execution for safe repository inspection.

## Quick Start

```bash
# 1. Navigate to the agent package
cd contexer-agent

# 2. Create and activate virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# 3. Install in editable mode
pip install -e ".[dev]"

# 4. Install Playwright browser dependencies
playwright install chromium

# 5. Launch Contexer CLI
contexer
```

Configure `OPENROUTER_API_KEY` and optionally `OPENROUTER_MODEL` in `.env` (see `.env.example`).

## CLI Commands

Inside the `contexer` REPL:

* `/loop <goal> [--url <url>] [--dir <path>]` — Run the full autonomous loop (Goal → OpenCode → Playwright → Verifier → Repair).
* `/opencode [status | run <prompt>]` — Interact directly with the local OpenCode execution engine.
* `/github` — Verify official GitHub MCP Server connection, tool discovery, and read-only mode.
* `/project [status | list | set <name> | new <name> | reset]` — Inspect and switch target projects or scratch sandboxes.
* `/status` — View current session status, active project, and provider health.
* `/help` — Display command help.
* `/exit` — Exit the Contexer shell.

## Architecture & Subsystems

- **`cli/`**: Typer entrypoint, Rich REPL shell, command router, and UI components.
- **`runtime/`**: Agent execution loop, streaming events, and tool execution harness.
- **`llm/`**: Provider abstraction, OpenRouter/Gemini client, and prompt templates.
- **`safety/`**: Configurable approval policies, circuit breakers, and observation sanitizers.
- **`tools/`**: Local filesystem tools, read-only git tools, and bounded terminal execution.
- **`project/`**: Workspace manager detecting project stacks and protecting the Contexer agent itself.
- **`opencode/`**: HTTP adapter and async client for OpenCode execution engine.
- **`observer/`**: Playwright headless browser observer.
- **`verification/`**: Evidence-based acceptance criteria verifier.
- **`repair/`**: Failure diagnosis and repair prompt synthesizer.
- **`workflow/`**: Autonomous loop orchestrating inspection, planning, execution, verification, and repair.
- **`mcp/`**: Official GitHub MCP Server runner and client.

## Milestone Status

- [x] Milestone 1: Public landing page, web architecture, and design system (`website/`)
- [x] Milestone 2: Antigravity project skills (`.agents/skills/`)
- [x] Milestone 3: Generic Python agent harness/runtime (`contexer-agent/`)
- [x] Milestone 4: Verification engine & Playwright headless browser observation
- [x] Milestone 5: Self-repair loop & OpenCode integration
- [x] Milestone 6: Official GitHub MCP Server integration (read-only)
