# Contexer

> **Contexer — Autonomous Engineering Agent**

Contexer sits above coding agents and autonomously drives software tasks from intent to implementation, observation, verification, and repair.

```text
INTENT
  ↓
CONTEXT
  ↓
PLAN
  ↓
EXECUTE
  ↓
OBSERVE
  ↓
VERIFY
  ↓
DONE / REPAIR
```

---

## The Problem

Modern AI coding agents excel at writing, editing, and generating code files. However, when an agent executes file edits without errors, it does not guarantee that the application actually works as the user intended.

The critical disconnect in software engineering with AI:

```text
"Code executed successfully"
              ≠
"User's goal was achieved"
```

A coding agent may create a button, write syntactically valid CSS, or install a library, yet:
* The button might not render on screen or might be obscured.
* The script may throw uncaught runtime errors in the browser console.
* The API route may return 500 errors upon actual user interaction.
* The resulting page may completely miss the functional acceptance criteria.

Developers are forced to manually inspect the runtime, test the browser interface, diagnose mistakes, and repeatedly re-prompt the coding agent.

---

## What is Contexer?

Contexer is an orchestration and verification layer that operates *above* coding agents. It does not replace the coding agent; instead, it provides the closed-loop governance needed to guide the coding agent to a verified outcome.

* **Current Execution Layer**: [OpenCode](https://github.com/opencode-ai) via local HTTP API.
* **Current Observation & Verification Layer**: [Playwright](https://playwright.dev/) headless browser runtime + dynamic acceptance criteria verifier.
* **Current Context Layer**: Official [GitHub MCP Server](https://github.com/github/github-mcp-server) in enforced read-only mode.
* **Current Agent & Runtime Infrastructure**: AgentForge-derived async agent harness with streaming tool execution, safety approval policies, and provider support for OpenRouter, Gemini, and OpenAI-compatible models.

---

## How It Works

Contexer closes the feedback loop between code generation and actual application behavior:

```text
User Intent
    ↓
Context
    ↓
Plan
    ↓
OpenCode
    ↓
Application
    ↓
Playwright
    ↓
Verification
    ↓
 ┌──────────────┐
 │              │
PASS           FAIL
 │              │
DONE         Diagnose
                ↓
              Repair
                ↓
             OpenCode
```

1. **User Intent**: The user provides a high-level outcome (e.g., *"Build an interactive product catalog with search, filter, and responsive grid"*).
2. **Context & Inspection**: Contexer inspects the project directory structure, detecting frameworks (Next.js, static HTML/JS), entrypoints, and key files.
3. **Plan & Executable Criteria**: Contexer compiles the intent into acceptance criteria, each with an **executable browser check** (steps such as *click "Add to cart"* followed by expectations such as *the cart count text changes*), plus a multi-step engineering plan. For existing apps, check locators are grounded in the live UI's accessibility tree.
4. **OpenCode Execution**: Contexer creates an isolated OpenCode session and dispatches the task **with the checks as its contract**. OpenCode writes or modifies the files on disk.
5. **Application Runtime**: Static projects are served by Contexer on a local HTTP port; other projects are observed on their dev server (`--url`).
6. **Playwright Observation**: Contexer launches a headless Playwright instance, navigates to the live application URL, captures the DOM tree, detects interactive controls (buttons, links, inputs), tracks console logs, and flags HTTP network errors.
7. **Executable Verification**: Each check runs in a fresh Chromium context: Contexer performs the steps, then evaluates the expectations with auto-retry. Pass/fail comes from the browser, not from a model's opinion. Only criteria that cannot be checked mechanically fall back to LLM judgment, and every verdict is labelled `proven`, `LLM-judged`, or `heuristic`.
8. **Pass or Self-Repair**:
   - If all criteria pass, the task is marked **DONE**.
   - If verification fails, Contexer's **Repair Engine** sends OpenCode the failing checks with *expected vs. actual* values and any uncaught exceptions. The loop repeats until verification passes or max attempts are reached.

---

## Why This Is Different

* **Coding agents execute tasks; Contexer verifies outcomes.** Coding agents report success when file edits finish. Contexer measures whether the user's objective was achieved in the running system.
* **Independent verification from execution.** The entity that writes the code does not evaluate whether the code works. Observation happens externally through a browser engine, inspecting real DOM nodes and console output.
* **Automated closed-loop repair.** Instead of forcing the developer to test, copy errors, and re-prompt, Contexer autonomously extracts runtime discrepancies and drives the repair cycle.

---

## Architecture

The real architecture implemented in this repository:

```text
                 Contexer CLI (Typer + Rich REPL)
                                ↓
                 Agent Runtime (ContexerAgent)
                                ↓
               LLM Provider (OpenRouter / Gemini)
                                ↓
          ┌─────────────────────┴─────────────────────┐
          ↓                                           ↓
   Workspace Tools & MCP                      Autonomous Loop
 (Filesystem, Shell, Git,                            ↓
   Official GitHub MCP)                 Target Project Inspector
                                                     ↓
                                            Goal & Criteria Analyzer
                                                     ↓
                                              Engineering Planner
                                                     ↓
                                          OpenCode HTTP Adapter
                                                     ↓
                                           Target Application
                                                     ↓
                                         Playwright Observer (DOM,
                                          Console, Network, Shot)
                                                     ↓
                                Check Runner + Verifier (executed checks)
                                                     ↓
                                         Repair Engine (Self-Repair)
```

---

## Multi-App Architecture

Contexer functions as an orchestration meta-agent that coordinates multiple specialized external applications and runtimes:

| External Application | Protocol / Interface | What Contexer Sends | What Contexer Receives | Why It Is Needed |
| :--- | :--- | :--- | :--- | :--- |
| **OpenCode** | HTTP REST API (`localhost:4096`) | Task prompts, workspace directory scope, acceptance criteria, repair instructions | Session IDs, execution status, execution duration, git diffs | Acts as the specialized coding worker that directly modifies files in the repository. |
| **Playwright** | Headless Browser Automation (Chromium) | Target application URL (`http://localhost:3000`), navigation timeouts | Page titles, DOM structure, visible headings, interactive elements, console logs, network errors, screenshots | Provides independent, ground-truth observation of how the running application actually behaves. |
| **Official GitHub MCP Server** | Model Context Protocol (stdio / Docker) | Tool execution requests (`list_issues`, `get_file_contents`, etc.) with enforced read-only mode | Structured repository schemas, issue bodies, git tree listings | Supplies external repository context without risking accidental mutations to remote repositories. |

---

## Example Workflow

### User Intent

```text
User: Build an interactive e-commerce landing page.
```

### Execution & Verification Trace

```text
[Contexer Autonomous Loop]
Goal:    Build an interactive e-commerce landing page
Project: sandbox (scratch) -> /workspace/sandbox
Target:  http://127.0.0.1:8080

● Inspecting Target Repository
  ✓ Detected Stack: Static Web (HTML/CSS/JS)
  ✓ Existing files: 0 files

● Deriving Acceptance Criteria & Executable Checks
  ✓ 4 criteria, 4 with executable browser checks:
    • crit-1 Product grid shows at least 6 products with prices (check)
        expect: at least 6 × [data-testid="product-card"]
    • crit-2 Category filter narrows the grid (check)
        do:     click button "Electronics"
        expect: at most 3 × [data-testid="product-card"]
    • crit-3 Add to cart updates the cart counter (check)
        do:     click button "Add to cart"
        expect: text of [data-testid="cart-count"] contains "1" and changes
    • crit-runtime Application loads without uncaught JavaScript exceptions or console errors (check)
        expect: no uncaught exceptions or console errors

● Generating Engineering Plan
  ✓ Strategy: Semantic HTML5 layout, CSS grid, and vanilla JS cart state.
    1. Create index.html with nav, product grid, and cart badge.
    2. Create style.css with card layout.
    3. Create script.js with product data, filtering, and cart counter.

● Coding Agent Execution
  › Dispatching plan and executable acceptance contract...
  ✓ Implementation complete (14.2s)

● Verification (Attempt 1/3)
  ✓ crit-1 Product grid shows at least 6 products with prices · proven
  ✓ crit-2 Category filter narrows the grid · proven
  ✗ crit-3 Add to cart updates the cart counter · proven
        expected: text of [data-testid="cart-count"] contains "1" and changes
        actual:   "0" → "0"
        uncaught exception: cart is not defined
  ✓ crit-runtime Application loads without uncaught JavaScript exceptions or console errors · proven

● Diagnosis & Self-Repair (Attempt 1/3)
  › Sending targeted repair prompt to coding agent...
```

*(Illustrative trace.)* Note what changed from snapshot-based verification: a cart badge that *exists* with count `0` used to satisfy "Add to cart updates the counter". Now the check clicks the button and the browser reports that the count did not change.

### Real output: a bug a page snapshot cannot see

Actual `verify_only` output (live `openrouter/free` model) for a todo app whose "Complete" button strikes the task through but throws `refesh is not defined` and never updates the count. Nothing is wrong at page load. The same contract, derived from the correct version of the app, passes that version 4/4:

```text
● Verification
  ✓ crit-1 User can add a new task and the remaining count updates · proven
  ✗ crit-2 User can mark a task as complete and the remaining count updates · proven
        expected: text of [data-testid="remaining-count"] equals "0"
        actual:   "1"
        uncaught exception: refesh is not defined
  ✗ crit-3 Remaining count reflects number of incomplete tasks · proven
        expected: text of [data-testid="remaining-count"] equals "1"
        actual:   "2"
        uncaught exception: refesh is not defined
  ✓ crit-runtime Application loads without uncaught JavaScript exceptions or console errors · proven
Reason: [crit-2] expected text of [data-testid="remaining-count"] equals "0", got "1"; ...
```

---

## Demo

🎥 Demo video: https://drive.google.com/file/d/1JY83zeOhzG795Fzvxcxr2AD82umNfUXQ/view?usp=drive_link

---

## Quick Start

### Prerequisites

* Python >= 3.11
* Node.js >= 18 (for running target web applications or Playwright browser binaries)
* Git
* (Optional) [OpenCode](https://github.com/opencode-ai) installed and running locally on port 4096: `opencode serve --port 4096`

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/murtuza777/contexer-agent.git
cd contexer-agent

# 2. Navigate to the agent package
cd contexer-agent

# 3. Create and activate a virtual environment
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

# 4. Install dependencies in editable mode
pip install -e ".[dev]"

# 5. Install Playwright browser binaries
playwright install chromium
```

### Environment Configuration

Copy the example environment file and configure your API keys:

```bash
cp .env.example .env
```

Configure keys in `.env`:
* `OPENROUTER_API_KEY`: Required for LLM planning, criteria analysis, and verification.
* `OPENROUTER_MODEL`: Model name (default: `openrouter/free` or any preferred model).
* `GITHUB_PERSONAL_ACCESS_TOKEN`: (Optional) GitHub token for read-only GitHub MCP server integration.

---

## Running Contexer

### Launch Interactive Shell

```bash
contexer
```

Inside the Contexer REPL, the following slash commands are available:

| Command | Aliases | Description |
| :--- | :--- | :--- |
| `/help` | `/h`, `/?` | Display available commands and usage guide. |
| `/status` | — | Show current session status, active project, and provider health. |
| `/project` | `/p`, `/workspace` | Inspect and manage target projects (`/project list`, `/project set <name>`, `/project new <name>`, `/project reset`). |
| `/opencode` | `/oc` | Check OpenCode server health or run targeted prompts (`/opencode status`, `/opencode run <prompt>`). |
| `/loop` | `/auto`, `/build` | Run the complete autonomous loop (`/loop <goal> [--url <url>] [--dir <path>]`). |
| `/verify` | `/check` | Verify the running app against a goal with executable browser checks, without changing code (`/verify <goal> [--url <url>] [--dir <path>]`). |
| `/github` | `/gh`, `/mcp` | Check official GitHub MCP server connection, tool discovery, and read-only enforcement. |
| `/clear` | `/cls` | Clear the terminal screen. |
| `/version` | `/v` | Show version information (`contexer v0.1.0`). |
| `/exit` | `/quit`, `/q` | Exit the Contexer shell. |

### Running an Autonomous Loop Directly

Within the REPL:

```bash
/loop Build an interactive portfolio page with project cards and dark mode toggle --url http://127.0.0.1:3000
```

---

## Current Status

### Working

* **Interactive CLI & REPL**: Typer application with Rich UI, command routing, prefix expansion, and session status tracking.
* **Agent Runtime & Streaming**: Provider abstraction supporting OpenRouter, Gemini, and OpenAI-compatible models with streamed responses and structured function calling.
* **Safety & Tool Execution**: Bounded filesystem tools, read-only git operations, safe command execution, and configurable approval policies (`on-request`, `auto`, `never`).
* **OpenCode Integration**: HTTP client connecting to OpenCode server, session management, prompt dispatch, timeout controls, and diff extraction.
* **Playwright Headless Observer**: Headless browser automation capturing DOM titles, headings, interactive element trees, browser console errors, HTTP failures, and full-page screenshots.
* **Executable Acceptance Checks**: Goals are compiled into browser checks (steps + expectations) that Playwright executes in isolated contexts; failures report expected vs. actual. LLM judgment is used only for criteria without a check, and every verdict is labelled with how it was reached.
* **Self-Repair Engine**: Discrepancy diagnosis between runtime observations and acceptance criteria, producing targeted repair prompts for OpenCode.
* **Autonomous Engineering Loop**: End-to-end orchestration (`Goal → Inspector → Criteria → Planner → OpenCode → Playwright → Verifier → Repair → Complete`).
* **Official GitHub MCP Server**: Read-only integration supporting stdio binary and Docker container execution with tool discovery.
* **Target Project Management**: Project candidate scanning, isolation of user targets from the Contexer agent itself (`is_protected`), and scratch sandboxes.

### In Progress

* Interactive human-in-the-loop intervention during individual repair attempts.
* Persistent cross-session task state using SQLite checkpointing.

### Planned

* Adapters for additional coding agents (Claude Code, Codex, Aider).
* Multi-modal visual regression testing comparing rendered UI against design mockups.
* Automated pull request creation and CI pipeline monitoring via GitHub MCP.

---

## Roadmap

```text
✓ CLI & Interactive REPL
✓ LLM runtime & provider abstraction
✓ Tool runtime & safety approval policies
✓ OpenCode integration & execution adapter
✓ Playwright headless browser observation
✓ Executable acceptance checks (contract-first, browser-proven verdicts, /verify)
✓ Autonomous self-repair loop
✓ Official GitHub MCP server integration (read-only)
→ Coding-agent abstraction + second adapter (Claude Code), independent diffs
→ Dev-server lifecycle for Node/Python projects
→ Run persistence + replaying saved checks as regression tests
→ Interactive human-in-the-loop repair checkpoints
→ Multi-modal visual checks
```

The detailed plan, with sequencing rationale, is in [contexer-agent/docs/roadmap.md](contexer-agent/docs/roadmap.md).

---

## Tech Stack

* **Language**: Python 3.11+
* **Agent Harness & CLI**: Typer, Rich, AgentForge-derived runtime foundation
* **LLM & Inference**: OpenRouter, Google Gemini, OpenAI-compatible API, Pydantic
* **Coding Engine Integration**: OpenCode (HTTP REST client, session & diff APIs)
* **Runtime Observation**: Playwright (Chromium headless browser automation)
* **Model Context Protocol**: MCP (JSON-RPC over stdio) with official GitHub MCP Server
* **Networking & HTTP**: HTTPX (async client with retry and backoff)
* **Testing & Quality**: pytest, pytest-cov, anyio, Pyright
* **Product Website**: Next.js 15 (App Router), TypeScript, Tailwind CSS, Lucide React

---

## License & Attribution

This project is licensed under the [MIT License](contexer-agent/pyproject.toml).

Contexer contains focused adaptations of architectural patterns and selected harness implementation concepts from [AgentForge](https://github.com/MohitGoyal09/AgentForge) (commit `3f513b3`), Copyright (c) 2026 Mohit Goyal, licensed under the MIT License. See [`contexer-agent/THIRD_PARTY_NOTICES.md`](contexer-agent/THIRD_PARTY_NOTICES.md) and [`contexer-agent/docs/agentforge-integration.md`](contexer-agent/docs/agentforge-integration.md) for full notices and module boundary definitions.
