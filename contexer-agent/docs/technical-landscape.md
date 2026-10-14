# Rent the agents, own the verdict

Contexer should assemble its acceptance gate from existing parts and write only four things itself: the contract compiler, the verdict, the bounded repair controller and the evidence report. The parts are concrete and all run on Python 3.11. The **Claude Agent SDK** (`claude-agent-sdk` 0.2.166, wrapping Claude Code v2.1.299) is adapter one, OpenAI's Python **Codex SDK** (`openai-codex` 0.162.1) adapter two, **OpenCode's** OpenAPI/SSE server (v1.19.0) driven through `httpx` adapter three, and one **Agent Client Protocol** client (`agent-client-protocol` 0.12.1) covers the long tail. **Playwright Python 1.64** proves behaviour alongside screenshot baselines Contexer stores itself and injected axe-core; plain-git snapshot commits built through a temporary index give per-attempt checkpoints; SQLite with an explicit state enum suffices until a second worker arrives and **DBOS 3.2.0** takes over; `githubkit` 0.16.1 behind a GitHub App produces check runs; and OpenTelemetry GenAI spans fed by Claude Code's own cost telemetry meter spend. The competition is closer than the earlier pain-point research suggested: **Enderfga/claw-orchestrator already ships acceptance contracts its runtime runs itself**, with `verified`/`refuted`/`unverified` verdicts and a rule that editing a contract's tests refutes the run, and millionco/expect, bug0inc/qa-agent and TestSprite all sell real-browser checking of coding-agent output. None of them compiles a ticket into user-approved checks in a closed format a reviewer can read, labels which verdicts a browser proved, replays saved checks without a model, publishes accuracy figures, or blocks a merge as a GitHub check pinned to its own App, and those five properties are where Contexer must win. The traps are documented and specific: Claude Code's Stop hook yields after eight consecutive blocks or a timeout, GitHub counts `neutral` as passing a required check, merge queues test a different SHA from the PR head, `taskkill /T` misses re-parented Windows descendants, Vite silently changes ports and rejects unknown hosts, and Claude Code now ships its own `/verify`. One trap is a policy question rather than an engineering one: Anthropic bars third-party products from routing users' Pro or Max credentials, so the product plan's assumption that "the Claude Code adapter uses the person's own subscription" holds only for starting the unmodified `claude` binary on the user's own machine, and even that needs written confirmation.

## Every layer already exists except an independent verdict

Metadata in this report follows one convention. Stars, license, last push and release come from `gh api`, PyPI and npm as recorded in the research notes on 2026-10-14; "none detected" or `NOASSERTION` means GitHub found no recognised license file, not that the code is unlicensed; statements a project makes about itself are marked **(vendor claim)**.

### Four groups own everything but the verdict

By October 2026 the open-source agent landscape falls into four groups:

| Group | Examples | What they own |
|---|---|---|
| Full background-agent platforms | Open SWE, Open-Inspect, OpenHands | The harness, the sandbox fleet and the PR flow |
| Research agents | SWE-agent, mini-swe-agent, Agentless | Benchmark-oriented agent loops |
| Local orchestration UIs | Orchestrator.inc agent-orchestrator (13,162 stars), Superset, Emdash, the sunsetting Vibe Kanban | Running vendor CLIs in git worktrees |
| Verification-first runtimes | claw-orchestrator (one project) | Running checks that the agent did not write |

Sources: [agent-orchestrator](https://github.com/OrchestratorInc/agent-orchestrator); [Vibe Kanban shutdown](https://vibekanban.com/blog/shutdown); [claw-orchestrator](https://github.com/Enderfga/claw-orchestrator).

Companies that built internal platforms treat the agent loop as a part they can swap. Stripe forked goose ([Stripe](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents)), Ramp picked OpenCode for its server-first design ([Ramp](https://builders.ramp.com/post/why-we-built-our-background-agent)), and Spotify moved to the Claude Agent SDK ([Spotify](https://engineering.atspotify.com/2025/11/context-engineering-background-coding-agents-part-2)). Every incumbent has added browser or computer-use self-testing, from Replit Agent 3 to Cursor's cloud agents, and in each case the agent that wrote the code also grades it ([Replit](https://replit.com/blog/introducing-agent-3-our-most-autonomous-agent-yet); [Cursor](https://cursor.com/changelog/02-24-26)). Claude Code Review goes further: it "always completes with a neutral conclusion so it never blocks merging" ([Claude Code docs](https://code.claude.com/docs/en/code-review)). The gap is therefore not a missing harness, sandbox or browser driver. **The gap is a verdict that the authoring agent can neither produce nor edit, enforced where the merge happens.** Contexer should write only that verdict, the contract it is measured against, the controller that acts on it, and the evidence that explains it.

### Today's prototype keeps its core and gains five missing parts

Contexer today is a Python 3.11+ CLI built on Typer and Rich, with a closed JSON check format run by Playwright Python, a verifier that labels each verdict proven, LLM-judged or heuristic, an OpenCode adapter and an in-process async loop. Nothing in the notes argues for replacing any of these. What is missing sits underneath and around the loop: an adapter interface with Claude Code and Codex behind it, a dev-server lifecycle, checkpoints Contexer owns, explicit persistence and a GitHub reporter. Python support constrains the choices only slightly. Every dependency marked BUILD ON below declares Python ≥3.10 or ≥3.11 on PyPI; the OpenHands SDK is the one candidate that needs ≥3.12, which limits it to a source of ideas, and the ACP Python SDK, Prefect, Arize Phoenix and LiteLLM all cap support below 3.15.

### The target architecture puts a deterministic controller around rented parts

```text
 ticket / goal / PR event / Spec Kit after_implement hook
        |
        v
 CONTRACT COMPILER --> plain-English checklist + closed JSON checks
        |               human approves -> hashed, stored outside the agent's write scope
        v
 BLUEPRINT CONTROLLER (deterministic state machine; owns every push, comment and status)
   +- snapshot ........... temp-index commit -> refs/contexer/<run>/<attempt>
   +- AGENT NODE: implement | repair
   |     AgentAdapter: Claude Agent SDK | Codex SDK or exec --json | OpenCode HTTP+SSE | ACP
   |     inner gate: Stop hook runs fast checks; PreToolUse denies edits to .contexer/**
   +- APP SERVER ......... detect -> free port -> spawn in job object/process group
   |                        -> ready probe -> warm-up GET -> tee logs
   +- VERIFIER ........... Playwright 1.64 assertions, pixel diff, axe (proven)
   |                        -> checklist judge (LLM-judged, labelled) -> heuristic
   +- score, keep best, revert, failure signature, escalate (default <= 2 repair rounds)
   +- replay locked contracts from earlier goals (regression)
        |
        v
 RUN STORE (SQLite now, DBOS later) + EVIDENCE STORE (trace.zip, video, screenshots,
                                                     server logs, diff, cost ledger)
        |
        v
 REPORTERS: HTML report | commit status (CLI) | GitHub App check runs (service)
            | contexer-mcp tools | managed AGENTS.md section
```

| Layer | Contexer writes | Build on (version, 2026-10-14) | Borrow ideas from | Avoid | Plan milestone |
|---|---|---|---|---|---|
| Agent adapters | `AgentAdapter` interface, normalised `AgentEvent`, contract injection, inner-gate hooks | `claude-agent-sdk` 0.2.166 + Claude Code v2.1.299; `openai-codex` 0.162.1 or `codex exec --json`; OpenCode server v1.19.0 via httpx; `agent-client-protocol` 0.12.1; MCP; AGENTS.md | Open-Inspect harness seam; claude-code-action and codex-action auth and gating; Gemini CLI exit codes; goose recipes | Codex app-server used directly; Aider; A2A; coder/agentapi; opencode-sdk-python | M1 |
| Runtime and environment | `AppServer` (detect, start, ready, warm up, log, kill); env and secret injection; test identities | stdlib `subprocess` + psutil 7.2.2 + Windows Job Objects; Supabase CLI v2.120.0; Stripe CLI v1.53.1; Playwright `route`/HAR; optional `e2b` 2.56.0, `docker` 7.2.0 + devcontainers CLI 0.89.0 | Playwright Test `webServer`; `@vercel/frameworks` 3.35.0 data; `@netlify/build-info` 11.3.0; Railpack v0.41.0; ni; Ramp's pre-built images | Daytona; Cloudflare Sandbox; Coder and Ona; Firecracker and gVisor; mirakuru; Nixpacks; stripe-mock; MSW | M2, M5 |
| Verification engine | Check DSL, verdict labels, locator re-location cascade, screenshot baselines, judged-check checklists | `playwright` 1.64.0; pixelmatch-py; axe-core; inspect_ai + StrykerJS + Web-Bench for the M0 benchmark | Browser Use re-matching cascade; Midscene caching rules; Bug0 consensus policy; Playwright Test agents; ArtifactsBench; WebArena Verified | Stagehand as runtime; Skyvern; workflow-use; Lost Pixel; BackstopJS; Shortest, LaVague, Magnitude | M0, M7 |
| Repair and checkpoints | Blueprint state machine, attempt scoring, keep-best, failure signatures, escalation, tamper guard | git snapshot commits built through a temporary index (Codex v2 technique); git worktrees for parallel attempts; Claude SDK `rewind_files` and hooks as a complement | Stripe blueprints and two-round cap; Symphony terminal reasons and backoff; Agentless reproduction tests; OpenHands critic API; jj operation log | Claude Code `/rewind` as the primary mechanism; Codex undo; ccundo; GitButler | M3 |
| Run store and durable state | Schema, state enum, idempotency keys, evidence pointers | stdlib `sqlite3` (WAL) now; DBOS 3.2.0 at the service phase | LangGraph durability modes; Symphony spec; Absurd; 12-factor agents | Temporal (for now); Inngest; Restate; Prefect | M4 |
| GitHub integration | Check-run layout, conclusion mapping, report hosting, approval loop | Commit statuses (CLI phase); GitHub App + Checks API (service phase); `githubkit` 0.16.1 | Probot; Chromatic, Percy and Argos approval flows; CodeRabbit check modes; claude-code-action outputs; Spec Kit hooks | PyGithub for the service; `neutral` conclusions; anything that depends on Agent HQ internals | M6 and later |
| Observability and cost | Span model, per-run cost ledger, budget enforcement | OTel GenAI semconv (pinned); opentelemetry-python-contrib; Claude Code OTel + `total_cost_usd`/`max_budget_usd` | Langfuse, Phoenix and Logfire as optional OTLP sinks; OpenLLMetry instrumentations | LiteLLM as a hard dependency; Phoenix inside a hosted product | M3, M6 |

## Agent adapters: Claude Agent SDK first, Codex SDK second, ACP for the long tail

### Claude Code is the best-instrumented agent to supervise

In command-line mode, `claude -p --output-format stream-json` emits typed NDJSON whose **last line is a `result` message carrying the final text, cost and session metadata**. `--json-schema` puts schema-conforming output in `structured_output`, `--resume <id>` continues a session, `--max-budget-usd` caps spend, and `dontAsk` mode "denies every call that would otherwise prompt", which suits locked-down CI ([Headless docs](https://code.claude.com/docs/en/headless)). The Python SDK wraps the same binary and returns a typed `ResultMessage` whose `subtype` distinguishes `success`, `error_max_turns`, `error_max_budget_usd` and `error_max_structured_output_retries`, alongside `total_cost_usd`, `permission_denials` and `terminal_reason`. `ClaudeSDKClient` adds `interrupt`, `set_permission_mode` and `rewind_files`, and `@tool` plus `create_sdk_mcp_server` register Python functions as in-process MCP tools, so Contexer can hand Claude its own `run_checks` tool without starting another process ([Python SDK reference](https://code.claude.com/docs/en/agent-sdk/python)). The Python SDK (0.2.166) is numbered independently of the CLI (v2.1.299), so every evidence report should record `claude --version` ([PyPI](https://pypi.org/project/claude-agent-sdk/); [releases](https://github.com/anthropics/claude-code/releases)). Five operational details from the [headless docs](https://code.claude.com/docs/en/headless) shape the adapter:

| Behaviour | What to do |
|---|---|
| Without `--bare`, a `-p` session runs the project's hooks and `.mcp.json` servers "even in a folder you've never trusted". The docs call `--bare` "the recommended mode for scripted and SDK calls". | Use `--bare` for scripted runs. |
| `--bare` "never reads OAuth credentials". | It needs an API key or Bedrock, Vertex or Foundry credentials. |
| A run with no explicit permission mode can start in `auto`. | Always pass a mode. |
| SIGTERM leaves the turn unfinished and exits with code 143. | Stop runs with SIGINT or `interrupt()`. |
| A dev server that the agent starts in the background keeps the `-p` run open, up to a 10-minute idle ceiling. | Tell the agent that Contexer owns the dev server. |

### Codex works best through its Python SDK, with exec as the fallback

Codex offers three automation surfaces, and Contexer should use two of them. The Python SDK `openai-codex` 0.162.1 (Python ≥3.10) "controls the local Codex app-server over JSON-RPC", bundles a pinned CLI runtime and exposes threads, turns and sandbox presets ([Codex SDK docs](https://learn.chatgpt.com/docs/codex-sdk)). The fallback, `codex exec --json`, streams JSONL `thread.*`, `turn.*` and `item.*` events with item types such as `command_execution`, `file_change`, `mcp_tool_call` and `agent_message`, and accepts `--output-schema` and session resume ([Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode); [items.ts](https://github.com/openai/codex/blob/main/sdk/typescript/src/items.ts)). Talking to the app-server directly is the surface to skip, because OpenAI recommends the SDK for automation, the WebSocket transport is "not supported for production", and many methods sit behind `experimentalApi` ([App server docs](https://learn.chatgpt.com/docs/app-server)).

The Codex surfaces carry their own traps. `codex exec` defaults to a read-only sandbox, so edits need `--sandbox workspace-write`; `--full-auto` is no longer supported; and `codex mcp-server` has been removed ([Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode); [Codex SDK docs](https://learn.chatgpt.com/docs/codex-sdk)). **`turn.completed` reports token usage but no USD cost**, so Contexer needs its own price table. Codex hooks mirror Claude Code's `Stop` and `PreToolUse` and are on by default, but each hook must be trusted, automation needs `--dangerously-bypass-hook-trust`, and OpenAI itself calls tool hooks "a useful guardrail, not a complete enforcement boundary" ([Codex hooks](https://learn.chatgpt.com/docs/hooks)). The only evidence that hooks run under `codex exec` at all is a `SessionStart` test ([hooks.rs](https://github.com/openai/codex/blob/main/codex-rs/exec/tests/suite/hooks.rs)), so whether a Codex Stop hook can force a continuation in automation remains unverified.

### OpenCode stays, through its server rather than its SDK

`opencode serve` publishes an OpenAPI 3.1 spec at `/doc`, with `POST /session/:id/prompt_async`, an SSE stream at `GET /event`, `GET /session/:id/diff`, and abort and permission endpoints ([OpenCode server docs](https://opencode.ai/docs/server/)). The official Python SDK was last pushed 2026-01-30, about eight months behind the server ([GitHub](https://github.com/anomalyco/opencode-sdk-python)), so Contexer should generate a small `httpx` client from `/doc` and use `opencode run --attach` to reuse one warm server across repair attempts ([OpenCode CLI docs](https://opencode.ai/docs/cli/)). OpenCode lost Claude Pro/Max OAuth access around 2026-01-09 ([VentureBeat](https://venturebeat.com/technology/anthropic-cracks-down-on-unauthorized-claude-usage-by-third-party-harnesses)); it remains Contexer's most provider-flexible backend, but it is no route to a Claude subscription.

### ACP reaches 43 agents; MCP and AGENTS.md carry Contexer outward

**ACP is the only protocol designed for a client to drive a coding agent's turn.** `session/prompt` returns a `stopReason`, `session/update` streams `tool_call` events with a `kind`, a `status` and `diff` content, and permissions arrive through `session/request_permission` ([ACP prompt turn](https://agentclientprotocol.com/protocol/prompt-turn); [ACP tool calls](https://agentclientprotocol.com/protocol/tool-calls)). The agents list shows **43 agents**, including Claude through `claude-agent-acp`, Codex through `codex-acp`, Gemini CLI, Goose, Copilot, Cursor, Kiro and OpenHands ([ACP agents list](https://agentclientprotocol.com/overview/agents)). ACP should cover the long tail rather than replace the native adapters: it carries no USD cost, no schema-validated final output and no hooks, and the Claude and Codex ACP servers are themselves adapters over the same SDK and app-server. ACP also "assumes the user is primarily in their editor" ([ACP introduction](https://agentclientprotocol.com/overview/introduction)), so Contexer should **not advertise the `fs` and `terminal` client capabilities**, or it becomes responsible for the agent's file I/O and terminals.

MCP points the other way. A `contexer-mcp` server exposing `list_checks`, `run_checks` and `get_failure_evidence` lets any agent ask for verification mid-loop, though the verdict that gates still comes from outside the agent. A managed AGENTS.md section that says how to start the app, where the approved checks live, that `.contexer/**` must not be edited, and how to self-verify reaches Codex, OpenCode, Gemini, goose and Copilot through one file ([agents.md](https://agents.md/)). Claude Code (v2.1.277+) reads AGENTS.md only when no CLAUDE.md exists, so repos with a CLAUDE.md need an `@AGENTS.md` import ([Claude Code memory docs](https://code.claude.com/docs/en/memory)). A2A targets opaque remote agents, and no coding CLI in scope speaks it ([A2A](https://github.com/a2aproject/A2A)).

### One event model, and the agent's word never counts as a pass

Open-Inspect's "harness seam" is the pattern to copy: OpenCode and the Claude Agent SDK emit the same normalised session events, and a bridge emits a single `execution_complete` ([HOW_IT_WORKS.md](https://github.com/ColeMurray/background-agents/blob/main/docs/HOW_IT_WORKS.md)). Contexer's equivalent is one `AgentEvent` model covering `run_started`, `tool_call{kind, name, status}`, `file_change`, `command`, `usage{tokens, usd?}` and `run_finished{reason, is_error, session_id}`, with ACP's `ToolKind` names (`read`, `edit`, `execute` and so on) as the neutral vocabulary. An agent's `success` or `end_turn` is never a pass; the self-report is stored next to Contexer's verdict, never instead of it. The authoritative diff comes from `git diff` against Contexer's checkpoint, because edits made through Bash appear as commands rather than file changes.

| Candidate | URL | License | Stars | Last push / release | Python | Verdict | One-line reason |
|---|---|---|---|---|---|---|---|
| Claude Code CLI | https://github.com/anthropics/claude-code | None detected | 150,793 | 2026-10-14 / v2.1.299 | Subprocess (`claude -p`) | **BUILD ON** (via SDK; CLI fallback) | Richest typed stream, Stop/PreToolUse hooks, schema output, budget caps |
| claude-agent-sdk (Python) | https://github.com/anthropics/claude-agent-sdk-python | MIT | 8,277 | 2026-10-14 / PyPI 0.2.166 | ≥3.10 | **BUILD ON** (adapter 1) | Typed `ResultMessage`, callback hooks, in-process MCP tools, `rewind_files` |
| anthropics/claude-code-action | https://github.com/anthropics/claude-code-action | MIT | 9,511 | 2026-10-14 / `v1` tag 2025-08-26 | n/a (Action) | **BORROW IDEAS** / companion | Triggers, OIDC auth, bot gating; creates no check run, so Contexer's gate adds to it rather than competing |
| openai-codex (Python SDK) | https://github.com/openai/codex/tree/main/sdk/python | Apache-2.0 | 129,197 (repo) | 2026-10-14 / PyPI 0.162.1 | ≥3.10 | **BUILD ON** (adapter 2) | Pinned CLI bundled; thread, turn and item events over the app-server |
| `codex exec --json` | https://github.com/openai/codex | Apache-2.0 | 129,197 | 2026-10-14 / rust-v0.162.1 (2026-10-09) | Subprocess | **BUILD ON** (fallback) | Least coupling; `--output-schema`; documented JSONL item types |
| Codex app-server (direct) | https://learn.chatgpt.com/docs/app-server | Apache-2.0 | — | — | JSON-RPC | **AVOID** (for now) | OpenAI steers automation to the SDK; WebSocket transport "not supported for production" |
| openai/codex-action | https://github.com/openai/codex-action | Apache-2.0 | 1,266 | 2026-10-14 | n/a (Action) | **BORROW IDEAS** | Safety strategies, API-key proxy, allow-users; Windows runners need `safety-strategy: unsafe` |
| OpenCode server | https://github.com/anomalyco/opencode | MIT | 213,441 | 2026-10-14 / v1.19.0 | HTTP + SSE via httpx | **BUILD ON** (adapter 3, keep) | OpenAPI 3.1, SSE events, diff endpoint, warm server via `--attach` |
| opencode-sdk-python | https://github.com/anomalyco/opencode-sdk-python | MIT | 286 | 2026-01-30 | Python | **AVOID** | About 8 months behind the server; generate a client from `/doc` instead |
| Agent Client Protocol | https://github.com/agentclientprotocol/agent-client-protocol | Apache-2.0 | 4,441 | 2026-10-14 / schema-v1.25.0 | via SDK | **BUILD ON** (long-tail adapter) | One client reaches the 43 listed agents |
| ACP Python SDK | https://github.com/agentclientprotocol/python-sdk | Apache-2.0 | 335 | PyPI 0.12.1 | ≥3.10, <3.15 | **BUILD ON** | Pydantic models for tool calls, plans, usage and permissions |
| claude-agent-acp | https://github.com/agentclientprotocol/claude-agent-acp | Apache-2.0 | 2,646 | 2026-10-14 / npm 0.90.0 | via ACP | **BORROW IDEAS** (cross-check only) | Adds a moving part over the native SDK; unclear whether subscription use is allowed |
| codex-acp | https://github.com/agentclientprotocol/codex-acp | NOASSERTION | 455 | npm 2.2.2 | via ACP | **BORROW IDEAS** (cross-check only) | Adapter over the app-server; the native SDK is richer |
| Gemini CLI | https://github.com/google-gemini/gemini-cli | Apache-2.0 | 107,353 | 2026-10-14 / v0.64.0 | via ACP | **BORROW IDEAS** | Clean headless contract (exit code 53 = turn limit); consumer users moved to Antigravity CLI on 2026-06-18 |
| goose | https://github.com/aaif-goose/goose | Apache-2.0 | 55,280 | 2026-10-14 / v1.54.0 | via ACP | **AVOID** as primary | General-purpose agent; its recipes are a reference for check bundles |
| Aider | https://github.com/Aider-AI/aider | Apache-2.0 | 49,548 | 2026-05-22 | Unsupported Python API | **AVOID** | No event stream; pushes have stalled |
| MCP | https://github.com/modelcontextprotocol/modelcontextprotocol | Not recorded | 9,449 | Release 2026-07-28 | In-process via Claude SDK | **BUILD ON** (outbound) | Every target agent consumes MCP tools |
| AGENTS.md | https://github.com/agentsmd/agents.md | MIT | 24,919 | 2026-09-10 | n/a | **BUILD ON** | One instruction channel for most agents; "60k+ projects" (vendor claim) |
| A2A | https://github.com/a2aproject/A2A | Apache-2.0 | 26,144 | v1.0.1 (2026-05-28) | SDK exists | **AVOID** | Designed for remote opaque agents; no coding CLI speaks it |
| coder/agentapi | https://github.com/coder/agentapi | MIT | 1,496 | Archived | — | **AVOID** | Deprecated terminal-scraping wrapper |
| mini-swe-agent | https://github.com/SWE-agent/mini-swe-agent | MIT | 8,514 | 2026-10-12 / 2.4.6 | Python | **BORROW IDEAS** (test engine) | Cheap deterministic baseline for Contexer's own tests; ">74% SWE-bench Verified" (vendor claim) |

## Runtime: host processes in a protected checkout, with E2B as the hosted option

### No sandbox by default, because the agent already ran on this host

The default runtime needs no sandbox. Contexer should run the app as plain host processes in the user's checkout, protected by snapshots, or in a per-attempt worktree when attempts run in parallel. That works free on Windows, macOS, Linux and CI, and since the coding agent has already run on the same host, a sandbox adds little security for the user's own repo.

### Contexer must write its own AppServer, modelled on Playwright's webServer

The reference design is Playwright Test's `webServer`, which is Node-only. It treats a server as ready on **2xx, 3xx or 400–403**, probes both `127.0.0.1` and `::1` with backoff at 100, 250, 500 and then 1,000 ms, can instead wait for a stdout regex whose named groups become environment variables, and stops the server with `kill(-pid)` on a POSIX process group or `taskkill /pid N /T /F` on Windows ([playwright.dev](https://playwright.dev/docs/test-webserver); [webServerPlugin.ts](https://github.com/microsoft/playwright/blob/main/packages/playwright/src/plugins/webServerPlugin.ts); [processLauncher.ts](https://github.com/microsoft/playwright/blob/main/packages/utils/processLauncher.ts)). The Python equivalent starts with stdlib `subprocess`, using `start_new_session` on POSIX and `CREATE_NEW_PROCESS_GROUP` on Windows so `CTRL_BREAK_EVENT` can request a graceful stop ([Python docs](https://docs.python.org/3/library/subprocess.html)), and uses psutil for tree kills and for finding which PID holds a port ([psutil recipes](https://psutil.io/recipes/)). On Windows the process also belongs in a Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, so every descendant dies when the last handle closes, even if Contexer crashes ([Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_limit_information)); Codex's Windows sandbox assigns exactly this kind of job before resuming its child ([codex mxc README](https://github.com/openai/codex/blob/main/codex-rs/mxc-sandbox/README.md)). The notes found no maintained Python library that packages spawn, wait, tree-kill and Job Object together, and mirakuru states "Windows support: Frankly, there's none" ([mirakuru](https://github.com/dbfixtures/mirakuru)), so this component is Contexer's to write, as milestone M2.

### Ports and hosts need explicit flags

| Framework | Default behaviour | What Contexer should do |
|---|---|---|
| Vite | Listens on port 5173, but "if the port is already being used, Vite will automatically try the next available port". `server.host` defaults to `localhost`, and only `localhost`, `*.localhost` and IP addresses pass `allowedHosts`. | Pass `--strictPort` and `--host 127.0.0.1`. Allowed hosts become relevant once the app runs in a hosted sandbox ([Vite docs](https://github.com/vitejs/vite/blob/main/docs/config/server-options.md)). |
| Next.js | `next dev` takes `-p` or reads `PORT`, and binds to 0.0.0.0 by default. | Pass the port explicitly ([Next.js CLI](https://github.com/vercel/next.js/blob/canary/docs/01-app/03-api-reference/06-cli/next.mdx)). |

Both frameworks compile routes on first request, so a warm-up GET of the key routes before the checks run reduces flakiness.

### Start detection borrows Vercel's and Netlify's data, and explicit config wins

The best open data on how to start an arbitrary web app comes from two deploy platforms. **Vercel's `frameworks.ts`** holds 75 framework entries, most with a `--port $PORT` dev command, including a `tanstack-start-lovable` entry detected through `@lovable.dev/vite-tanstack-config` ([frameworks.ts](https://github.com/vercel/vercel/blob/main/packages/frameworks/src/frameworks.ts)). **Netlify's `@netlify/build-info`** adds default ports, TCP polling, an accuracy ranking and rules for choosing among `package.json` scripts ([get-commands.ts](https://github.com/netlify/build/blob/main/packages/build-info/src/get-commands.ts)). Contexer should port a curated subset of both into a Python table, with Apache-2.0 attribution for the Vercel data, and let declared intent beat detection: Contexer's own config first, then `devcontainer.json`, then a Procfile `web:` entry, then detection, and a static-site fallback last.

Lovable exports now come in two shapes, the classic Vite SPA and the TanStack Start SSR projects that have been the default for new projects since 2026-05-13 ([Lovable blog](https://lovable.dev/blog/building-apps-using-tanstack-start)). Exports from Lovable and Bolt omit secrets, so Contexer should detect missing environment variables before it starts anything ([BrainGrid](https://www.braingrid.ai/blog/how-to-download-lovable-project)). Package-manager detection is about 30 lines of logic (lockfile, then the `packageManager` field, then `devEngines`, then a walk up the directory tree), and Contexer should reimplement it rather than shell out to `ni`, which Windows PowerShell 5.1 shadows with its built-in `New-Item` alias ([package-manager-detector](https://github.com/antfu-collective/package-manager-detector)).

### Supabase and Stripe test modes supply real backends

**Supabase** is the dependency that matters for the target stack. `supabase start` runs a Docker stack on ports 54321–54324 with a recommended **7 GB of RAM**, `supabase status -o json` exports the keys Contexer needs to inject, and `db reset` re-applies `seed.sql` for deterministic data ([Supabase getting started](https://supabase.com/docs/guides/local-development/cli/getting-started); [CLI reference](https://supabase.com/docs/reference/cli/supabase-start)). The experimental `stack` mode (CLI ≥v2.119.0) gives each git worktree its own stack on auto-assigned ports, but only after fixed ports are removed from `config.toml`, a file Contexer must not edit silently ([multiple projects](https://supabase.com/docs/guides/local-development/running-multiple-local-projects)). The experimental native runtime runs without Docker but is "Not supported" on Windows ([runtimes](https://supabase.com/docs/guides/local-development/docker-and-native-runtimes)). Test users belong in the Auth Admin API with `email_confirm: true`; Contexer logs in once and reuses the session through Playwright `storage_state` ([Supabase Python reference](https://supabase.com/docs/reference/python/auth-admin-createuser); [Playwright auth](https://playwright.dev/python/docs/auth)).

For payments, `stripe listen --forward-to` with `--print-secret` and `stripe trigger` gives real test-mode behaviour, and `stripe sandbox create` provisions an anonymous sandbox with no signup that expires in 7 days ([Stripe sandboxes](https://docs.stripe.com/sandboxes)). Playwright `route` and HAR replay mock calls made from the browser without changing the app, but they do not intercept calls made on the server, which therefore need these real test-mode services ([Playwright mock docs](https://playwright.dev/python/docs/mock)).

### E2B is the hosted option; preview URLs serve the final CI check

E2B is the best optional hosted backend. It runs Firecracker microVMs, exposes any port through `get_host(port)`, snapshots template start commands so a dev server is "already running" when a sandbox starts, ships a self-hostable Apache-2.0 runtime, and offers a one-time $100 credit with 1-hour Hobby sessions ([E2B runtime](https://github.com/e2b-dev/runtime); [start and ready commands](https://docs.e2b.dev/template/start-ready-command.md); [pricing](https://e2b.dev/pricing)). Its public URLs should be treated "like a credential" ([E2B docs](https://docs.e2b.dev/network/public-url.md)). In any hosted sandbox, Vite's host check and Supabase's auth redirect allow-list both reject the sandbox hostname, and the simplest fix is to run Playwright inside the sandbox against `localhost`, as Ramp does ([Modal blog](https://modal.com/blog/how-ramp-built-a-full-context-background-coding-agent-on-modal)). Daytona, once a strong candidate, moved its core development to a private codebase in June 2026 and archived its repo ([Daytona](https://github.com/daytonaio/daytona)).

Preview deployments are a cheap target for the final CI check, but not for the repair loop, because each deploy takes minutes and yields no server logs. A generic `--target-url URL --header K:V` option covers both Vercel's protection-bypass header, available "on all plans", and Cloudflare Access service tokens ([Vercel docs](https://vercel.com/docs/deployment-protection/methods-to-bypass-deployment-protection/protection-bypass-automation); [Cloudflare docs](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/)).

**Process lifecycle and start detection**

| Candidate | URL | License | Stars | Last push / release | Python | Verdict | One-line reason |
|---|---|---|---|---|---|---|---|
| stdlib `subprocess` | https://docs.python.org/3/library/subprocess.html | PSF | — | — | stdlib | **BUILD ON** | Process groups on POSIX; new process group plus CTRL_BREAK on Windows |
| Windows Job Objects (ctypes or pywin32) | https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_limit_information | — | — | — | ctypes | **BUILD ON** | Only reliable way to kill npm → cmd → node → esbuild descendants |
| psutil | https://github.com/giampaolo/psutil | BSD-3-Clause | 11,292 | 2026-10-13 / 7.2.2 | Python | **BUILD ON** | Cross-platform tree kill and port-to-PID lookup |
| Playwright Test `webServer` | https://playwright.dev/docs/test-webserver | Apache-2.0 | 97,700 (playwright) | — | Node-only | **BORROW IDEAS** | Reference contract for readiness and kill |
| start-server-and-test / wait-on | https://github.com/bahmutov/start-server-and-test | MIT | 1,584 / 1,984 | 2026-10-12 / 2026-09-30 | Node CLI | **AVOID** | Hides the PID tree and logs from Python |
| mirakuru | https://github.com/dbfixtures/mirakuru | LGPL-3.0 | 91 | 2026-10-12 / 3.0.4 | Python | **AVOID** | No Windows support |
| port-for / pytest-xprocess | https://github.com/fizyk/port-for | MIT | 32 / 108 | PyPI 1.1.1 | Python | **AVOID** | Binding to port 0 is enough |
| `@vercel/frameworks` | https://github.com/vercel/vercel | Apache-2.0 | 16,394 | 2026-10-14 / npm 3.35.0 | Port the data | **BORROW IDEAS** (vendor a JSON subset) | 75 detectors, `$PORT` dev commands, Lovable entry |
| `@netlify/build-info` | https://github.com/netlify/build | MIT | 260 | 2026-10-13 / npm 11.3.0 | Port the logic | **BORROW IDEAS** | Default ports, TCP polling, accuracy and script ranking |
| Railpack | https://github.com/railwayapp/railpack | MIT | 1,231 | 2026-10-14 / v0.41.0 | Go binary (Windows builds) | **BORROW IDEAS** (optional fallback) | Good package-manager rules, but aimed at production builds |
| Nixpacks | https://github.com/railwayapp/nixpacks | MIT | 3,555 | 2026-10-02 | — | **AVOID** | Maintenance mode |
| Buildpacks `pack` / zbpack | https://github.com/buildpacks/pack | Apache-2.0 / MPL-2.0 | 3,013 / 327 | 2026-10-14 / 2026-08-26 | — | **AVOID** | Production image builders, too slow for dev loops |
| ni / package-manager-detector | https://github.com/antfu-collective/ni | MIT | 8,312 / 171 | 2026-10-09 / 2026-10-05 | Node | **BORROW IDEAS** (reimplement) | About 30 lines of logic; `ni` collides with a PowerShell alias |
| devcontainer.json / Procfile | https://containers.dev/implementors/json_reference/ | CC-BY-4.0 (spec) | 5,767 (spec) | 2026-03-20 | Parse | **BUILD ON** (as overrides) | Declared intent beats detection |
| devcontainers CLI | https://github.com/devcontainers/cli | MIT | 2,985 | 2026-10-08 / npm 0.89.0 | Node CLI | **BUILD ON** (optional `--isolate docker`) | Uses the repo's own config; has no `stop` or `down` |
| docker-py | https://github.com/docker/docker-py | Apache-2.0 | 7,217 | 2026-10-14 / 7.2.0 | Python | **BUILD ON** (optional) | Container control for isolation mode |
| honcho | https://github.com/nickstenning/honcho | MIT | 1,716 | 2025-06-03 / 2.0.0 | Python | **BORROW IDEAS** | Shows Procfile parsing is trivial |

**Backends, test data, isolation and preview targets**

| Candidate | URL | License | Stars | Last push / release | Python | Verdict | One-line reason |
|---|---|---|---|---|---|---|---|
| Supabase CLI | https://github.com/supabase/cli | None detected | 2,436 | 2026-10-14 / v2.120.0 | CLI; `supabase` py 2.32.0 | **BUILD ON** | Default backend for Lovable and Bolt apps; `status -o json`, `db reset` |
| Supabase `stack` mode | https://supabase.com/docs/guides/local-development/running-multiple-local-projects | — | — | CLI ≥v2.119.0 (experimental) | CLI | **BUILD ON** (behind a flag) | One stack per worktree; needs fixed ports removed |
| Supabase native runtime | https://supabase.com/docs/guides/local-development/docker-and-native-runtimes | — | — | Experimental | CLI | **BORROW IDEAS** (Linux CI) | No Docker needed, but not supported on Windows |
| Stripe CLI | https://github.com/stripe/stripe-cli | Apache-2.0 | 2,203 | 2026-10-14 / v1.53.1 | CLI | **BUILD ON** | Real test-mode webhooks; anonymous 7-day sandboxes |
| stripe-mock | https://github.com/stripe/stripe-mock | MIT | 1,656 | — | — | **AVOID** | Stateless and hardcoded |
| Firebase emulators | https://github.com/firebase/firebase-tools | MIT | 4,472 | 2026-10-14 | CLI | **BUILD ON** (only if `firebase.json` exists) | `emulators:exec` fits start, wait and stop |
| Playwright `route` / HAR | https://playwright.dev/python/docs/mock | Apache-2.0 | — | — | Python | **BUILD ON** | Mocks browser-side calls without app changes |
| MSW | https://github.com/mswjs/msw | MIT | 18,288 | 2026-10-10 | JS | **AVOID** (core) | Requires changing the app's code |
| testcontainers-python / WireMock | https://github.com/testcontainers/testcontainers-python | Apache-2.0 | 2,313 / 7,399 | 2026-10-09 / 4.15.0 | ≥3.10 | **AVOID** (for now) | Docker-only backend test tooling |
| E2B SDK + runtime | https://github.com/e2b-dev/E2B | Apache-2.0 | 14,347 / 1,716 | 2026-10-13 / `e2b` 2.56.0 | ≥3.11 | **BUILD ON** (optional hosted) | Port URLs, pre-booted start commands, self-hostable |
| Modal Sandboxes | https://github.com/modal-labs/modal-client | Apache-2.0 | 524 | 2026-10-14 / 1.6.1 | 3.10–3.14 | **BORROW IDEAS** (second hosted option) | Python-native; sandbox CPU costs about 3x Modal Functions |
| Vercel Sandbox | https://github.com/vercel/sandbox | Apache-2.0 | 210 | 2026-10-14 / `vercel` 0.11.6 | ≥3.10 | **BORROW IDEAS** (later) | 45-minute Hobby sessions; tied to Vercel auth |
| microsandbox | https://github.com/superradcompany/microsandbox | Apache-2.0 | 8,679 | 2026-10-14 / 0.7.8 | ≥3.10 | **BORROW IDEAS** (watch) | Only local microVM option with Windows (WHP) support and Python; still beta; "<100 ms boot" (vendor claim) |
| Daytona | https://github.com/daytonaio/daytona | None detected; archived | 71,552 | 2026-07-24 / SDK 0.224.0 | ≥3.10 | **AVOID** | Core development went private in June 2026 |
| Cloudflare Sandbox SDK | https://github.com/cloudflare/sandbox-sdk | NOASSERTION (Apache 2.0 file) | 1,150 | 2026-10-13 | None | **AVOID** | Controlled only from TypeScript inside a Worker |
| Coder / Gitpod (Ona) | https://github.com/coder/coder | AGPL-3.0 | 17,011 / 13,800 | 2026-10-14 | — | **AVOID** | Whole platforms that overlap Contexer's scope |
| Anthropic sandbox-runtime | https://github.com/anthropics/sandbox-runtime | Apache-2.0 | 5,542 | 2026-10-14 | Node | **BORROW IDEAS** (optional hardening) | Egress allow-list for the dev server; beta; dev-server hot reload untested |
| dagger/container-use | https://github.com/dagger/container-use | Apache-2.0 | 4,069 | 2026-09-21 | — | **BORROW IDEAS** | Container plus branch per agent |
| Firecracker / gVisor | https://github.com/firecracker-microvm/firecracker | Apache-2.0 | 37,369 / 19,674 | 2026-10-14 | — | **AVOID** | Building a sandbox fleet is out of scope |
| Vercel bypass header + `repository_dispatch` | https://vercel.com/docs/git/vercel-for-github | — | — | — | Playwright headers | **BUILD ON** (CI mode) | Verify protected preview URLs on any plan |
| wait-for-vercel-preview | https://github.com/patrickedqvist/wait-for-vercel-preview | MIT | 160 | 2026-10-12 | Action | **BORROW IDEAS** | Simple polling of the deployments API |

## Verification engine: Playwright Python 1.64 proves behaviour, Contexer owns everything Python lacks

### Playwright Python already covers nearly every runtime need

Playwright Python 1.64, released 2026-10-13, supplies the primitives a proving engine needs:

| Capability | Since | Source |
|---|---|---|
| ARIA snapshot assertions with partial templates, regex names and `/children` strictness | 1.49 (whole pages since 1.60) | [ARIA snapshots](https://playwright.dev/python/docs/aria-snapshots) |
| `locator.normalize()`, which "converts a locator to follow best practices like test ids and aria roles" | 1.59 | [v1.59.0](https://github.com/microsoft/playwright-python/releases/tag/v1.59.0) |
| A screencast API with chapters, pitched for "agentic video receipts" | 1.59 | [v1.59.0](https://github.com/microsoft/playwright-python/releases/tag/v1.59.0) |
| Tracing that records an ARIA snapshot and a screenshot on every action | 1.63 | [v1.63.0](https://github.com/microsoft/playwright-python/releases/tag/v1.63.0) |
| `page.get_by_ref()`, which resolves refs from the `"ai"` snapshot mode | 1.64 | [v1.64.0](https://github.com/microsoft/playwright-python/releases/tag/v1.64.0) |

Playwright 1.56 added `page.console_messages()`, `page_errors()` and `requests()`, which map directly onto Contexer's `no_errors` expectation ([release notes](https://playwright.dev/python/docs/release-notes)), and the trace viewer "loads the trace entirely in your browser", so a hosted `trace.zip` can serve as linked evidence ([Trace viewer](https://playwright.dev/python/docs/trace-viewer)). Contexer should pin Playwright ≥1.64, noting that release's breaking change that elements inside hidden iframes now count as hidden. It should add an `aria` expectation type built on partial templates with `contain` or `equal` children, which holds up better than CSS selectors, and make a `trace.zip` plus a video with one chapter per check the standard evidence for every check.

### Python lacks screenshot assertions and the test agents, so Contexer owns them

**The Node-only gaps are the main reason Contexer has to own more than a test runner.** On 2026-04-30 a maintainer closed the Python request for `to_have_screenshot` with "No plans to implement this." ([issue #837](https://github.com/microsoft/playwright-python/issues/837)). The Playwright Test agents (planner, generator and healer) have no Python documentation, and that URL returned 404 ([Python test-agents URL](https://playwright.dev/python/docs/test-agents)); the HTML reporter is Node-only too. The healer is worth studying as a warning: it replays failing steps, patches locators, waits or data, and can end with "a skipped test if the healer believes the functionality is broken" ([Test agents](https://playwright.dev/docs/test-agents)). Contexer must treat broken functionality as a failure, never a skip.

### Re-location stays deterministic first, and only the target may move

Browser-agent frameworks help most with re-locating a check after the UI changes, as designs rather than dependencies. **Browser Use** re-matches elements through a cascade that runs from an EXACT full hash, to a STABLE hash with dynamic CSS classes removed, to XPATH, to AX_NAME (same tag and accessible name), to a unique ATTRIBUTE, and logs which level matched ([agent/service.py](https://github.com/browser-use/browser-use/blob/main/browser_use/agent/service.py)). The research behind self-healing locators is thin and mostly preprints:

| Study | Finding |
|---|---|
| ReproBreak | 449 reproducible locator breaks, but no repair results yet ([arXiv](https://arxiv.org/abs/2605.12158)) |
| Zero-cost self-healing preprint | 31 of 31 passes, but on one demo site ([arXiv](https://arxiv.org/abs/2603.20358)) |
| Helsinki thesis | Large models repaired 87.5% of broken locators; Mistral 7B repaired none ([Helda thesis](https://helda.helsinki.fi/server/api/core/bitstreams/631b961a-8642-42ed-9826-3e196eac9cf7/content)) |

The design that follows stores a fingerprint with each check target and re-locates deterministically through that cascade first. Only when the cascade fails does Contexer ask an LLM over `aria_snapshot(mode="ai")`, accepting the answer only above a confidence threshold, as PayPay does ([PayPay](https://blog.paypay.ne.jp/en/ai-driven-self-healing-for-automation-testing-at-paypay/)), then resolving the chosen ref with `get_by_ref()`, converting it to a durable locator with `normalize()`, and re-running the unchanged expectation. Only the target may change, never the comparator or the expected value, and the verdict records the level at which the element matched so a reviewer can audit drift. Midscene supplies the caching rule: cache plans and XPaths, never assertions ("Never cache query results"), and run CI with a read-only cache ([Midscene caching](https://midscenejs.com/caching.html)). Stagehand v4 now caches only on Browserbase, and "with a local browser, the `cache` option has no effect" ([Stagehand v4 caching](https://docs.stagehand.dev/v4/best-practices/caching)), which rules it out as a runtime.

### Pixel diffs prove change; a model only judges acceptability

Visual checks split in two. **pixelmatch-py** (ISC) decides "changed or unchanged", and that result is proven; a vision model is asked only whether a change is acceptable for the goal, and that result is labelled LLM-judged. Baselines should be keyed by git hash, an idea borrowed from reg-suit ([reg-suit](https://github.com/reg-viz/reg-suit)), and Argos can serve as an optional evidence sink because it accepts screenshots from any tool, though its CLI needs Node 22+ ([Argos CLI docs](https://argos-ci.com/docs/argos-cli)). For accessibility, Contexer injects axe-core with `add_script_tag` plus `evaluate`; axe-core is MPL-2.0, so shipping `axe.min.js` unmodified is fine ([axe-core](https://github.com/dequelabs/axe-core)).

Judged verdicts need explicit guardrails, because the evidence on model judges cuts both ways:

| Evidence | Finding |
|---|---|
| ArtifactsBench | Checklist-guided screenshot judging reached over 90% pairwise agreement with human experts ([arXiv](https://arxiv.org/abs/2507.04952)) |
| WebDevJudge (ICLR 2026) | Found "a significant gap" between model judges and human experts on open-ended web-development judgments ([arXiv](https://arxiv.org/abs/2510.18560v1)) |
| Vibe Code Bench | **31.8–93.6% pairwise step-level agreement** between agent evaluators ([arXiv](https://arxiv.org/abs/2603.04601)) |
| PinATA (web agent as tester) | About 60% correct verdicts, with up to 94% specificity ([arXiv](https://arxiv.org/abs/2504.01495)) |
| Spotify | Introduced an LLM judge that vetoed about a quarter of sessions ([Spotify](https://engineering.atspotify.com/2025/12/feedback-loops-background-coding-agents-part-3)), then removed it as "too rigid" ([InfoQ](https://infoq.com/news/2026/03/spotify-honk-rewrite)) |

The pattern in that evidence is that judges work when constrained by a checklist and grounded in screenshots, and fail on open-ended quality calls. Contexer should therefore compile every visual expectation into atomic checklist items, judge the before, after and final screenshots, offer Bug0's `fail-on-disagreement` consensus policy whenever a judged result could pass a gate ([qa-agent](https://github.com/bug0inc/qa-agent)), and never let a judged verdict stand in for a proven one.

**Browser engines, evidence and checks**

| Candidate | URL | License | Stars | Last push / release | Python | Verdict | One-line reason |
|---|---|---|---|---|---|---|---|
| playwright-python | https://github.com/microsoft/playwright-python | Apache-2.0 | 15,041 | 2026-10-13 / 1.64.0 | ≥3.10 | **BUILD ON** (pin ≥1.64) | ARIA snapshots, `get_by_ref`, `normalize()`, per-action traces, screencast |
| pytest-playwright | https://github.com/microsoft/playwright-pytest | Apache-2.0 | 565 | 2026-10-08 | Python | **BORROW IDEAS** | `retain-on-failure` evidence flags as a model |
| Playwright Test agents | https://playwright.dev/docs/test-agents | Apache-2.0 | — | Node 1.56+ | Node-only | **BORROW IDEAS** | Planner, generator and healer split; the healer can skip tests |
| Playwright MCP | https://github.com/microsoft/playwright-mcp | Apache-2.0 | 38,134 | 2026-10-08 / v0.0.83 | Node | **BORROW IDEAS** (tool for the coding agent) | `browser_verify_*` tools mirror Contexer's expectations |
| playwright-cli | https://github.com/microsoft/playwright-cli | Apache-2.0 | 14,169 | 2026-10-14 | Node | **BORROW IDEAS** | Pattern for exposing a CLI to agents as a skill |
| Browser Use | https://github.com/browser-use/browser-use | MIT | 117,955 | 2026-10-09 / 0.13.11 | ≥3.11 | **BORROW IDEAS** | Five-level element re-matching cascade |
| workflow-use | https://github.com/browser-use/workflow-use | AGPL-3.0 | 4,225 | 2026-10-09 | Python | **AVOID** | AGPL; maintainers advise against production use |
| Stagehand | https://github.com/browserbase/stagehand | MIT | 25,665 | 2026-10-14 / v3.7.3 | Python SDK in monorepo | **AVOID** as runtime, **BORROW IDEAS** | v4 uses its own driver; LLM-free replay only on Browserbase |
| Vercel agent-browser | https://github.com/vercel-labs/agent-browser | Apache-2.0 | 43,962 | 2026-10-14 / v0.39.1 | None | **BORROW IDEAS** | Ref snapshots, `diff`, `batch` JSON, embedded axe |
| chrome-devtools-mcp | https://github.com/ChromeDevTools/chrome-devtools-mcp | Apache-2.0 | 53,523 | 2026-10-14 / v1.10.1 | Node | **BORROW IDEAS** (optional evidence) | Lighthouse and performance traces; usage statistics are on by default |
| Midscene.js | https://github.com/web-infra-dev/midscene | MIT | 15,259 | 2026-10-14 / v1.15.4 | Community ports only | **BORROW IDEAS** | Never cache assertions; read-only CI cache |
| Skyvern | https://github.com/Skyvern-AI/skyvern | AGPL-3.0 | 23,195 | 2026-10-14 / v1.0.56 | Python | **AVOID** | AGPL and platform-sized; borrow its progressive script caching |
| Shortest / LaVague / Magnitude browser-agent | https://github.com/antiwork/shortest | MIT / Apache-2.0 / Apache-2.0 | 5,688 / 6,389 / 4,134 | 2026-08-06 / 2025-01-21 / 2026-02-08 | — | **AVOID** | Stalled or pivoted |
| TestZeus Hercules | https://github.com/test-zeus-ai/testzeus-hercules | AGPL-3.0 | 1,185 | 2026-10-14 / 1.0.2 | Python | **AVOID** (borrow its output bundle) | Gherkin-first and AGPL |
| pixelmatch-py | https://github.com/whtsky/pixelmatch-py | ISC | 143 | 2026-10-12 | Python | **BUILD ON** | Deterministic proof that a screenshot changed |
| odiff | https://github.com/dmtrKovalenko/odiff | MIT | 3,248 | 2026-10-13 | Binary | **BORROW IDEAS** (optional) | Faster SIMD pixel diff |
| Argos | https://github.com/argos-ci/argos | MIT | 637 | 2026-10-14 | Node CLI (Node 22+) | **BORROW IDEAS** (optional sink) | Accepts screenshots from any tool; review UI; required status |
| reg-suit | https://github.com/reg-viz/reg-suit | MIT | 1,299 | 2026-10-13 | Node | **BORROW IDEAS** | Git-hash baseline keys; S3/GCS publishing and PR notifier |
| BackstopJS / Lost Pixel | https://github.com/garris/BackstopJS | MIT | 7,187 / 1,681 | 2026-10-10 / archived 2026-04-22 | — | **AVOID** | One is seeking a new maintainer; the other is sunset |
| axe-core | https://github.com/dequelabs/axe-core | MPL-2.0 | 7,647 | 2026-10-14 | Inject JS | **BUILD ON** | Standard accessibility engine; ship it unmodified |
| axe-playwright-python | https://github.com/pamelafox/axe-playwright-python | MIT | 31 | 2026-08-29 | ≥3.10 | **BUILD ON** (pin or vendor) | Thin wrapper; the bundled axe version is not stated |

### The verifier needs its own benchmark before any accuracy claim ships

No competitor publishes accuracy figures, so a measured verifier is both a necessity and a differentiator. StrykerJS's default `command` runner "bases the result on the exit code", which lets Contexer itself serve as the test command; because it runs every check for every mutant, the `mutate` setting should be limited to the lines the goal touched, with `incremental` enabled ([Stryker configuration](https://stryker-mutator.io/docs/stryker-js/configuration/)). LLMorpheus shows that LLM-proposed mutants can resemble real bugs that standard mutators cannot produce ([arXiv](https://arxiv.org/abs/2404.09952)). SWE-Lancer supplies the validity rule that every oracle must pass on fixed code and fail on broken code, and explains why end-to-end grading resists "grader hacking" better than unit tests ([SWE-Lancer](https://arxiv.org/html/2502.12115)). Web-Bench provides an Apache-2.0 dataset of 50 projects with 20 sequential tasks each and one Playwright spec per task ([GitHub](https://github.com/bytedance/web-bench)). Contexer should report two numbers for each verdict label: **catch rate**, the share of seeded bugs at least one check fails on, and **false-failure rate**, the share of checks that fail on known-good builds across repeated runs.

| Candidate | URL | License | Stars | Last push / release | Python | Verdict | One-line reason |
|---|---|---|---|---|---|---|---|
| inspect_ai | https://github.com/UKGovernmentBEIS/inspect_ai | MIT | 3,003 | 2026-10-14 | Python | **BUILD ON** (M0 harness) | Logged, re-scorable runs with `stderr` metrics |
| StrykerJS | https://github.com/stryker-mutator/stryker-js | Apache-2.0 | 3,206 | 2026-10-10 | Node (command runner) | **BUILD ON** (seeded bugs) | Uses Contexer's exit code as the kill signal |
| LLMorpheus | https://github.com/githubnext/llmorpheus | Not recorded | — | — | Node | **BORROW IDEAS** | Realistic LLM-written mutants |
| mutmut | https://github.com/boxed/mutmut | BSD-3-Clause | 1,478 | 2026-09-12 / 3.8.0 | Python (needs `fork`) | **BORROW IDEAS** (limited) | Python backends only; needs WSL on Windows |
| Hypothesis | https://github.com/HypothesisWorks/hypothesis | NOASSERTION (gh) | 9,082 | 2026-10-14 | Python | **BORROW IDEAS** (optional fuzz mode) | Stateful UI fuzzing that shrinks failures to a minimal sequence |
| promptfoo | https://github.com/promptfoo/promptfoo | MIT | 25,996 | 2026-10-14 | Node | **BORROW IDEAS** (optional) | Prompt-regression tests for the check compiler; OpenAI announced its acquisition on 2026-03-09 |
| Web-Bench | https://github.com/bytedance/web-bench | Apache-2.0 | 294 | 2026-04-30 | Playwright specs | **BUILD ON** (dataset) | 1,000 tasks, each with a Playwright oracle |
| WebGen-Bench | https://github.com/mnluzimu/WebGen-Bench | None | 60 | 2026-07-10 | — | **BORROW IDEAS** (measure the compiler) | 647 human-filtered test cases; no license, so no redistribution |
| ReproBreak | https://github.com/rub-sq/ReproBreak | Not recorded | — | — | Scripts | **BUILD ON** (eval; check the license first) | 449 real locator breaks for testing re-location |
| WebArena Verified | https://github.com/ServiceNow/webarena-verified | Apache-2.0 | 62 | 2026-03-08 | Python | **BORROW IDEAS** | Type-aware comparators, confidence intervals |
| ArtifactsBench | https://github.com/Tencent-Hunyuan/ArtifactsBenchmark | Other | 280 | 2025-12-30 | — | **BORROW IDEAS** | Checklist-guided judging of time-sequenced screenshots |
| SWE-Lancer | https://github.com/openai/SWELancer-Benchmark | Archived | — | 2025-07-18 | — | **BORROW IDEAS** | Validity rule for oracles |

## Repair and checkpoints: plain-git snapshots under a two-round blueprint

### Agent-native undo misses too much, so checkpoints live in plain git

Neither vendor's undo is reliable enough to build on. **Claude Code checkpoints do not track files changed by Bash commands**, restore few subagent edits, skip files that pnpm hard-links into place, and are "not a replacement for version control" ([Claude Code checkpointing](https://code.claude.com/docs/en/checkpointing)). **Codex removed its git-based undo** on 2026-04-28 ([PR #19481](https://github.com/openai/codex/pull/19481)). Contexer must therefore checkpoint in plain git, and Codex's earlier "ghost snapshot v2" shows how: build a temporary index from `git status --porcelain=2 -z`, `write-tree`, and `commit-tree` a detached commit without touching any refs ([PR #8055](https://github.com/openai/codex/pull/8055)). In Python, Contexer points `GIT_INDEX_FILE` at a temporary path, runs `git read-tree HEAD` and `git add -A` while skipping large untracked files, and writes the commit under `refs/contexer/<run>/<attempt>`, where it survives garbage collection but never appears on the user's branches. A restore runs `git read-tree -u --reset <tree>` and removes files created after the snapshot, while keeping ignored heavy directories such as `node_modules` and `.next` so the dev server restarts quickly. **Contexer must never run `git clean -fdx`**, which would delete the untracked `.env` files that Lovable and Bolt exports depend on. Git worktrees are reserved for parallel attempts, each with its own port and Supabase `--stack`; Stripe deliberately avoids worktrees at its scale and uses devboxes instead ([Stripe](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents)).

### The controller is a deterministic blueprint with a two-round cap

Stripe's "blueprints" are code-defined workflows in which deterministic nodes ("Run configured linters", "Push changes") wrap agent nodes ("Implement task", "Fix CI failures") ([Stripe Part 2](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2)), and after the second CI round the branch goes to a human ([Stripe Part 1](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents)). OpenAI's Symphony spec contributes run phases, distinct terminal reasons because "retry logic and logs differ", retry backoff of `min(10000·2^(attempt−1), cap)` with a default 5-minute cap, stall detection after 5 minutes without agent events, and a successful run that ends in a handoff state such as `Human Review` rather than `Done` ([SPEC.md](https://github.com/openai/symphony/blob/main/SPEC.md)). 12-factor agents suggests escalating to a human after about three consecutive errors ([factor 9](https://github.com/humanlayer/12-factor-agents/blob/main/content/factor-09-compact-errors.md)), and Claude Code's own guidance is to clear and restart "after two failed corrections" ([best practices](https://code.claude.com/docs/en/best-practices)). Contexer's defaults follow from that consensus: two repair rounds, a failure signature per check that triggers a change of strategy when it survives a repair, and a fresh agent session rather than an ever-growing context.

Each repair receives one compact "self-consistent failure bundle", the phrase TestSprite uses for its own ([TestSprite CLI](https://github.com/TestSprite/testsprite-cli)): the failing check, expected versus observed values, a screenshot path and the relevant log lines, trimmed by regex as Spotify does ([Spotify](https://engineering.atspotify.com/2025/12/feedback-loops-background-coding-agents-part-3)). The bundle goes at the end of a stable, cache-friendly prompt prefix, which matters because Manus reports cached input at $0.30 per million tokens against $3 uncached ([Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)). When Contexer runs best-of-N attempts, Agentless shows how to pick a winner: generate a reproduction test that fails before the fix, then re-rank candidates on regression plus reproduction results ([Agentless](https://github.com/OpenAutoCoder/Agentless)).

### Tamper protection takes three layers

The first layer is a **`PreToolUse` hook that denies `Edit` and `Write`** on `.contexer/**` and the approved check files, relying on the documented precedence "deny > defer > ask > allow" ([Hooks reference](https://code.claude.com/docs/en/hooks)). The second is a content hash of each approved contract. The third is a diff guard that marks the run as tampered if tests or contracts change, matching claw-orchestrator's rule that "editing the tests a contract runs refutes the run" ([claw-orchestrator](https://github.com/Enderfga/claw-orchestrator)). Anthropic's own harness research shows why all three are needed: it kept its feature list in JSON with a `passes` field and still had to tell agents it was "unacceptable to remove or edit tests" ([Anthropic](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)).

| Candidate | URL | License | Stars | Last push / release | Python | Verdict | One-line reason |
|---|---|---|---|---|---|---|---|
| Snapshot commits through a temporary index (Codex v2 technique) | https://github.com/openai/codex/pull/8055 | Technique | — | 2025-12-15 | git via subprocess | **BUILD ON** (reimplement) | Captures Bash edits and untracked files without touching the user's refs |
| git worktree | https://git-scm.com/docs/git-worktree | GPL-2.0 (git) | — | — | git | **BUILD ON** (parallel attempts only) | Isolates caches, ports and Supabase stacks |
| `git stash create` | https://git-scm.com/docs/git-stash | GPL-2.0 (git) | — | — | git | **BORROW IDEAS** | Ref-less commits, but untracked files are not captured |
| Jujutsu | https://github.com/jj-vcs/jj | Apache-2.0 | 32,044 | 2026-10-14 / v0.46.0 | Binary | **AVOID** as a requirement | Its operation log is the model for the attempt ledger |
| Claude Code checkpoints and `/rewind` | https://code.claude.com/docs/en/checkpointing | — | — | — | — | **AVOID** relying on | Misses Bash edits, most subagent edits and pnpm hard links |
| Claude SDK `rewind_files` | https://code.claude.com/docs/en/agent-sdk/python | MIT | — | PyPI 0.2.166 | ≥3.10 | **BUILD ON** (complement) | Rolls back a session's own edits; git remains the source of truth |
| Codex undo | https://github.com/openai/codex/pull/19481 | Apache-2.0 | — | Removed 2026-04-28 | — | **AVOID** | Removed |
| ccundo / GitButler | https://github.com/RonitSachdev/ccundo | — / NOASSERTION | 1,401 / 21,809 | 2025-07-27 / — | — | **AVOID** | Obsolete, or a full git client |
| Stripe Minions blueprints | https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2 | — | — | 2026-02-19 | — | **BORROW IDEAS** | Deterministic nodes around agent nodes; two-round cap |
| OpenAI Symphony | https://github.com/openai/symphony | Apache-2.0 | 27,677 | 2026-09-15 | Elixir | **BORROW IDEAS** | Run phases, terminal reasons, backoff, stall detection |
| OpenHands critic | https://github.com/OpenHands/software-agent-sdk | MIT | 1,254 | 2026-10-14 / 1.54.0 | ≥3.12 | **BORROW IDEAS** | `IterativeRefinementConfig` API shape; needs Python 3.12 or newer |
| Agentless | https://github.com/OpenAutoCoder/Agentless | MIT | 2,124 | 2024-12-22 | Python | **AVOID** (borrow one idea) | Reproduction tests plus re-ranking of candidate patches |

## Run store: SQLite and a state enum now, DBOS when workers multiply

### SQLite with synchronous writes is enough for the CLI phase

**A SQLite store with an explicit run and step state enum is enough for the CLI phase**, provided state is written synchronously before and after every side effect. OpenAI's Symphony goes further and recovers from restarts "without a durable orchestrator DB" at all, using only tracker and filesystem state ([SPEC.md](https://github.com/openai/symphony/blob/main/SPEC.md)). The concrete design uses four tables (`runs`, `steps`, `evidence` with a URI and sha256, and `checks` for locked contracts) in WAL mode, with LangGraph's `"sync"` durability semantics of persisting state before the next step begins ([LangGraph durable execution](https://docs.langchain.com/oss/python/langgraph/durable-execution)). Steps are idempotent, keyed by (run_id, seq, input_hash), so a resumed run reuses saved outputs as DBOS does. Screenshots, traces and logs stay on disk with only pointers in the database. Every agent turn records the agent's session ID and the checkpoint SHA, so a resumed run can continue the conversation and roll back the code, and every run ends in one of seven distinct terminal states: `succeeded`, `failed_checks`, `budget_exhausted`, `timed_out`, `stalled`, `cancelled` or `needs_human`.

### DBOS is the lightest upgrade once workers multiply

**DBOS** fits once there is more than one worker or runs arrive by webhook. It is an MIT library with no orchestration server; on restart it re-invokes pending workflows and returns saved step outputs instead of re-running those steps; and it defaults to `sqlite:///[app].sqlite`, using polling on SQLite, with Postgres recommended for production ([DBOS architecture](https://docs.dbos.dev/architecture); [DBOS configuration](https://docs.dbos.dev/python/reference/configuration)). The costs are one database write per step plus two per workflow, and the constraint that **workflows must be deterministic**, so both the agent subprocess call and the browser run have to be DBOS steps. The heavier engines lose on server overhead, sandbox friction or licensing:

| Engine | Why not now | Source |
|---|---|---|
| Temporal | Needs a server even in development (`start-dev` loses executions on exit unless persisted). Its Python sandbox is "not completely isolated" and creates friction with subprocess-heavy code. Workflow history is capped at 51,200 events or 50 MB. | [Temporal sandbox](https://docs.temporal.io/develop/python/python-sdk-sandbox); [limits](https://docs.temporal.io/workflow-execution/limits); [CLI server](https://docs.temporal.io/cli/server) |
| Inngest | The server is SSPL-licensed | [Inngest](https://github.com/inngest/inngest) |
| Restate | The server is BSL-licensed | [Restate](https://github.com/restatedev/restate) |

Pydantic AI's durability docs make a useful distinction: "durability is not storage". A durable engine keeps a run alive across crashes, but evidence and conversation history still need a separate store ([Pydantic AI](https://pydantic.dev/docs/ai/integrations/durable_execution/overview/)).

| Candidate | URL | License | Stars | Last push / release | Python | Verdict | One-line reason |
|---|---|---|---|---|---|---|---|
| stdlib `sqlite3` + state enum | https://docs.python.org/3/library/sqlite3.html | PSF | — | — | stdlib | **BUILD ON** (now) | No new dependency; WAL; synchronous writes |
| DBOS Transact | https://github.com/dbos-inc/dbos-transact-py | MIT | 1,628 | 2026-10-14 / 3.2.0 | ≥3.10 | **BUILD ON** (service phase) | No server; SQLite default, Postgres for production; ">40K steps/s" (vendor claim) |
| Temporal SDK + server | https://github.com/temporalio/sdk-python | MIT | 1,223 / 23,699 | 2026-10-14 / 1.34.0 | ≥3.10 | **BORROW IDEAS** | Needs a server, sandbox friction, history limits |
| Hatchet | https://github.com/hatchet-dev/hatchet | MIT | 8,113 | 2026-10-14 / v0.110.5; SDK 1.42.1 | ≥3.10 | **BORROW IDEAS** (later option) | Postgres-backed queue with a UI, if one is ever needed |
| Inngest | https://github.com/inngest/inngest | SSPL (server); Apache-2.0 (SDK) | 5,942 / 217 | 2026-10-14; SDK 0.5.19 | ≥3.10 | **AVOID** | SSPL server; HTTP-callback model is awkward for a local CLI |
| Restate | https://github.com/restatedev/restate | BSL 1.1 (server); MIT (SDK) | 4,558 / 82 | 2026-10-14 / v1.8.0 | ≥3.10 | **AVOID** | BSL server; extra process |
| Prefect | https://github.com/PrefectHQ/prefect | Apache-2.0 | 24,018 | 2026-10-13 / 3.8.8 | ≥3.11, <3.15 | **AVOID** | Built for data pipelines and needs a server |
| LangGraph | https://github.com/langchain-ai/langgraph | MIT | 43,261 | 2026-10-14 / 1.2.15 | ≥3.10 | **BORROW IDEAS** (keep deferred) | Checkpoint per step, durability modes, interrupts for human checkpoints |
| Absurd | https://github.com/earendil-works/absurd | Apache-2.0 | 2,490 | 2026-08-10 | Python SDK | **BORROW IDEAS** | Smallest Postgres-only durable-execution design to copy |
| procrastinate | https://github.com/procrastinate-org/procrastinate | MIT | 1,420 | 2026-10-12 | Python | **BORROW IDEAS** (optional queue) | Postgres task queue, if DBOS queues are not used |
| 12-factor agents | https://github.com/humanlayer/12-factor-agents | Apache-2.0 | 26,680 | 2025-09-21 | — | **BORROW IDEAS** | Unify execution and business state; launch, pause and resume |

## GitHub: an App with check runs that never report neutral

### Only a GitHub App can be the gate, but commit statuses work first

**Only GitHub Apps can create check runs**; OAuth apps and users can read them but not create them ([GitHub checks guide](https://docs.github.com/en/rest/guides/using-the-rest-api-to-interact-with-checks)). Only an App receives `check_run.rerequested`, `requested_action` and `merge_group` events, and only an App can be pinned as a required check's **expected source**, so that a status set by anyone else blocks the merge ([protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)). Source pinning is the anti-tamper property behind "gates merges with verified evidence". Contexer can still report before the App exists, because anyone with push access can create a commit status, which is how Argos reports ([Argos GitHub docs](https://argos-ci.com/docs/github)), so `contexer verify --report github` can ship first. `claude-code-action` emits `branch_name`, `session_id` and `conclusion` outputs but creates no check run ([action.yml](https://github.com/anthropics/claude-code-action/blob/main/action.yml)), so a Contexer step can run after it in the same workflow without competing.

### Check runs hold a readable report, but the evidence must live elsewhere

| Field | Limit | Source |
|---|---|---|
| `summary` | 65,535 characters of Markdown | [REST API description](https://github.com/github/rest-api-description/blob/main/descriptions/api.github.com/api.github.com.json) |
| `annotations` | 50 per request | [Check runs](https://docs.github.com/en/rest/checks/runs) |
| `images[]` | Each needs a full `image_url` | [Check runs](https://docs.github.com/en/rest/checks/runs) |
| Action buttons | 3, with labels of up to 20 characters | [Check runs](https://docs.github.com/en/rest/checks/runs) |
| Retention | Check data is archived after 400 days | [GitHub checks guide](https://docs.github.com/en/rest/guides/using-the-rest-api-to-interact-with-checks) |

Because image URLs must stay fetchable and check data expires, the full evidence report must live on long-lived hosting Contexer owns, with the check run pointing to it through `details_url`. The proposed layout uses two checks, `Contexer / acceptance` and `Contexer / regression replay`, so each can be required separately, as Chromatic does with its UI Tests and UI Review checks ([Chromatic](https://www.chromatic.com/docs/mandatory-pr-checks/)). The summary holds a table of criterion, verdict label and evidence link plus attempts and spend, and the three action buttons are "Re-verify", "Approve checks" and "Repair".

### `neutral` passes a required check, so Contexer must never send it

**Conclusion mapping is the single most dangerous detail**, because required checks pass on `successful`, `skipped` or **`neutral`** ([protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)).

| Contexer outcome | Check-run conclusion | Why |
|---|---|---|
| Every locked check has passing proven evidence | `success` | The only green state |
| At least one check disproven | `failure` | Blocks the merge |
| Contract awaiting approval, `needs_human`, or a `blocked`/inconclusive check | `action_required` | `neutral` would silently allow the merge |
| Budget or wall-clock limit reached | `timed_out` | A distinct terminal reason |
| Contexer crashed or the run was cancelled | `cancelled` | Re-runnable via `rerequested` |
| Change provably cannot affect any locked contract | `skipped` (sparingly) | Avoids a check that stays pending forever |
| Anything | never `neutral` | GitHub counts `neutral` as passing |

### Merge queues get replay only, and webhooks get acknowledged before work starts

A merge queue tests a temporary `gh-readonly-queue/{base}` branch whose SHA differs from the PR head, the `merge_group` webhook goes to GitHub Apps only, and a GitHub Actions workflow that does not trigger on `merge_group` never reports its required check ([merge queue docs](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue); [webhook events](https://docs.github.com/en/webhooks/webhook-events-and-payloads)). A full build, verify and repair loop cannot fit inside a queue timeout, so in queue mode Contexer should only replay locked contracts against the merge-group SHA. Every webhook receiver should verify the signature, deduplicate, persist a job row and return 2xx before any work starts, because each sender enforces a short deadline:

| Sender | Deadline | Source |
|---|---|---|
| GitHub | 2xx within 10 seconds; deduplicate on `X-GitHub-Delivery` | [GitHub best practices](https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks) |
| Slack | 2xx within 3 seconds | [Slack Events API](https://docs.slack.dev/apis/events-api/) |
| Linear for Agents | A `thought` activity within 10 seconds | [Linear](https://linear.app/developers/agents) |

### Agent HQ has no verifier slot, so required checks and MCP are the way in

**Agent HQ offers no plug-in slot for third-party verifiers.** Third-party agents' code is scanned with CodeQL, secret scanning and dependency checks before the PR is finalized, and the docs list no extension point for outside validators ([third-party agents](https://docs.github.com/en/copilot/concepts/agents/about-third-party-agents)). The documented entry points are required checks, which apply to every agent's PRs, and custom agents in `.github/agents/*.md`, which can declare MCP servers ([custom agents](https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-custom-agents)). Spec Kit offers a second cheap integration: its `converge` command is LLM reading, not executable checks ([converge.md](https://github.com/github/spec-kit/blob/main/templates/commands/converge.md)), but it runs extension hooks marked `optional: false` automatically ([extensions](https://github.com/github/spec-kit/blob/main/docs/reference/extensions.md)), so a mandatory `after_implement` or `before_converge` hook puts executable evidence where Spec Kit users already work. For rollout, CodeRabbit's per-check `warning` and `error` modes, with per-PR overrides tagged `[IGNORED]` and limitable to requested reviewers, are the ergonomics to copy ([CodeRabbit docs](https://docs.coderabbit.ai/pr-reviews/pre-merge-checks)), along with Percy's and Chromatic's flow in which approving in the report turns the status green.

| Candidate | URL | License | Stars | Last push / release | Python | Verdict | One-line reason |
|---|---|---|---|---|---|---|---|
| GitHub App + Checks API | https://docs.github.com/en/rest/checks/runs | — | — | — | via githubkit | **BUILD ON** (service phase) | The only way to write check runs, receive re-run and action events, and pin the source |
| Commit statuses | https://github.com/github/rest-api-description | — | — | — | via githubkit | **BUILD ON** (CLI phase) | Works with plain push access, before the App exists |
| githubkit | https://github.com/yanyongyu/githubkit | MIT | 354 | 2026-10-07 / v0.16.1 | ≥3.10 | **BUILD ON** | httpx + pydantic, async, App and installation auth, typed webhook parsing, retry and throttling |
| PyGithub | https://github.com/PyGithub/PyGithub | LGPL-3.0 | 7,789 | 2026-10-13 / v2.10.0 | ≥3.10 | **AVOID** (for the service) | Sync-only, separate requests-based HTTP stack, LGPL |
| gidgethub | https://github.com/brettcannon/gidgethub | Apache-2.0 | 424 | 2026-09-25 | ≥3.10 | **BORROW IDEAS** | Small async design; githubkit is more complete |
| Probot | https://github.com/probot/probot | ISC | 9,621 | 2026-10-13 | TypeScript | **BORROW IDEAS** | Webhook → typed handler → per-installation client |
| PR-Agent | https://github.com/The-PR-Agent/pr-agent | MIT | 13,386 | 2026-10-14 | Python | **BORROW IDEAS** | Action and multi-provider packaging; review only, community "legacy" |
| Chromatic / Percy / Argos flows | https://www.chromatic.com/docs/mandatory-pr-checks/ | — | — | — | — | **BORROW IDEAS** | Approve to turn green; split checks; report `skipped` instead of never reporting |
| CodeRabbit pre-merge checks | https://docs.coderabbit.ai/pr-reviews/pre-merge-checks | — | — | — | — | **BORROW IDEAS** | Warning-to-error rollout; audited overrides |
| GitHub custom agents | https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-custom-agents | — | — | — | — | **BUILD ON** (distribution) | `.github/agents/*.md` can declare a Contexer MCP server |
| Spec Kit | https://github.com/github/spec-kit | MIT | 141,251 | v1.2.0 (2026-10-13) | Python CLI | **BUILD ON** (integration hook) | Mandatory `after_implement` or `before_converge` hook |
| Linear for Agents / Slack Events | https://linear.app/developers/agents | — | — | Developer Preview | — | Later | Trigger surfaces with 10-second and 3-second acknowledgement deadlines |

## Observability and cost: OTel GenAI spans and the agent's own cost meter

### Contexer's spans follow the GenAI conventions, pinned

Contexer should emit OpenTelemetry spans named after the GenAI semantic conventions, with `invoke_workflow contexer.run` at the top, `invoke_agent claude-code` for each executor turn and `execute_tool check.<id>` for each check, and custom attributes carrying the run ID, the attempt and the verdict. These conventions are all still in **Development** status and moved to a dedicated repository in 2026, so the version must be pinned ([semantic-conventions-genai](https://github.com/open-telemetry/semantic-conventions-genai)).

### The agent's own telemetry is the cheapest accurate cost meter

Started with `CLAUDE_CODE_ENABLE_TELEMETRY=1`, an OTLP endpoint that Contexer serves, and `OTEL_RESOURCE_ATTRIBUTES=contexer.run_id=<id>` (no spaces allowed), Claude Code exports `claude_code.cost.usage` and per-request `claude_code.api_request` events carrying `cost_usd`, which Contexer can sum per run ([Monitoring usage](https://code.claude.com/docs/en/monitoring-usage)). The SDK's `total_cost_usd` and `max_budget_usd` add a per-run cap, though the docs call these values "client-side estimates", and `system/api_retry` events with `error: rate_limit` reveal throttling ([Headless docs](https://code.claude.com/docs/en/headless)). Codex reports token counts only, so it needs Contexer's price table.

A hard cap that stops spending mid-turn needs a gateway set through `ANTHROPIC_BASE_URL` ([LLM gateway docs](https://code.claude.com/docs/en/llm-gateway)), and Contexer should support "bring your own gateway" rather than bundle one. LiteLLM shows why: its **budgets "require a database"** (Postgres), without which the global budget fails open ([LiteLLM budgets](https://docs.litellm.ai/docs/proxy/users)), and **its PyPI releases 1.82.7 and 1.82.8 were malicious** on 2026-03-24, stealing credentials at interpreter start ([NetSPI](https://www.netspi.com/blog/executive-blog/ai-ml-pentesting/litellm-supply-chain-compromise/)). The default destination for all this data should be local, with spans and cost rows in the run store and shown in the evidence report. Langfuse, Phoenix and Logfire work as optional OTLP destinations, but none belongs in the core: Langfuse self-hosting needs Postgres, ClickHouse, Redis and S3 ([Langfuse self-hosting](https://langfuse.com/self-hosting)), Phoenix is ELv2-licensed, and Logfire's server is closed source.

| Candidate | URL | License | Stars | Last push / release | Python | Verdict | One-line reason |
|---|---|---|---|---|---|---|---|
| OTel GenAI semantic conventions | https://github.com/open-telemetry/semantic-conventions-genai | Apache-2.0 | 439 | 2026-10-14 | n/a | **BUILD ON** (pinned) | Standard span and attribute names for agents and tools |
| opentelemetry-python-contrib | https://github.com/open-telemetry/opentelemetry-python-contrib | Apache-2.0 | 1,113 | 2026-10-14 | Python | **BUILD ON** | httpx and other instrumentations |
| Claude Code OTel telemetry | https://code.claude.com/docs/en/monitoring-usage | — | — | — | Env vars | **BUILD ON** | Per-request `cost_usd`, tagged with a run ID |
| Langfuse | https://github.com/langfuse/langfuse | MIT outside `ee/` | 35,820 / 502 (SDK) | 2026-10-14 / v4.59.0; SDK 5.0.1 | ≥3.11 | **BORROW IDEAS** (optional exporter target) | Self-hosting needs four backing services |
| Arize Phoenix | https://github.com/Arize-ai/phoenix | Elastic License 2.0 | 11,834 | 2026-10-14 / v20.21.3 | ≥3.11, <3.15 | **BORROW IDEAS** (optional local viewer) | ELv2 forbids offering it as a hosted service |
| OpenInference | https://github.com/Arize-ai/openinference | Apache-2.0 | 1,264 | 2026-10-14 | Python | Optional | Framework instrumentations |
| OpenLLMetry | https://github.com/traceloop/openllmetry | Apache-2.0 | 7,494 | 2026-10-13 / traceloop-sdk 0.62.4 | ≥3.10 | **BORROW IDEAS** | Provider instrumentations for Contexer's own LLM calls |
| LiteLLM | https://github.com/BerriAI/litellm | MIT outside `enterprise/` | 61,237 | 2026-10-14 / v1.105.1 | ≥3.10, <3.15 | **BORROW IDEAS** (optional gateway); **AVOID** as a hard dependency | Budgets need Postgres; March 2026 PyPI compromise |
| Pydantic Logfire | https://github.com/pydantic/logfire | SDK MIT; server closed source | 4,512 | 2026-10-14 / v5.2.0 | ≥3.10 | **BORROW IDEAS** | Convenient OTel wrapper, but do not tie Contexer to the closed backend |

## Competitors already promise "verified", but none owns an independent merge gate

### claw-orchestrator already ships most of the thesis

**claw-orchestrator is the nearest competitor and overlaps Contexer's thesis almost exactly.** Its README describes "Acceptance contracts — commands, HTTP probes, screenshots, diff policy, file assertions — that the runtime runs itself", runs that end `verified`, `refuted` or `unverified` and "never 'the agent said so'", and a rule that "editing the tests a contract runs refutes the run". It keeps persistent sessions across Claude Code, Codex, Antigravity, Grok Build and OpenCode, runs a checkpointed run kernel with a per-turn JSONL cost ledger and `maxBudgetUsd`, and exposes MCP and ACP interfaces ([claw-orchestrator](https://github.com/Enderfga/claw-orchestrator)). It is also small, with 591 stars, an MIT license, a Node 22+ requirement and essentially one maintainer, and the notes found no description of compiling contracts from a ticket, a human approval step, or assertions about browser interactions. The lesson cuts two ways: **the core idea is cheap enough for one person to build**, so "we verify" alone is no moat, and Contexer should adopt claw-orchestrator's verdict vocabulary and tamper rule outright rather than invent its own.

### Three browser-verification tools target the same buyer

Three 2026 projects pitch browser verification of coding-agent work directly:

| Project | License and status | How it works |
|---|---|---|
| millionco/expect | FSL; last pushed 2026-05-06 | A skill inside Claude Code, Codex or Cursor that "reads your git changes, generates a test plan, and runs it in a real browser with Playwright". Uses real browser cookies by default ([expect](https://github.com/millionco/expect)). |
| bug0inc/qa-agent | FSL | Runs natural-language steps over ARIA snapshots, caches steps in Redis with AI fallback, and runs Claude and Gemini assertions in parallel with an arbiter ([qa-agent](https://github.com/bug0inc/qa-agent)). |
| TestSprite CLI | Apache-2.0 client for a cloud service | Calls itself "The verification layer for the agentic coding era". Needs an API key and claims "100,000+ teams" (vendor claim) ([TestSprite CLI](https://github.com/TestSprite/testsprite-cli)). TestSprite also reported growing from about 6K to 35K users in about 90 days after shipping an MCP server (vendor claim) ([i-programmer](https://www.i-programmer.info/news/90-tools/18421-testsprite-20-sees-user-growth.html)). |

All three take natural-language specs and rely on LLM-judged assertions, and none publishes a catch rate or false-failure rate. Expect and TestSprite's MCP route share a structural weakness: the coding agent stays in charge and can ignore the result. FSL-1.1 forbids competing commercial use for two years, so **Contexer must not copy code from expect or qa-agent**, and the same holds for ELv2-licensed Explorbot ([explorbot](https://github.com/testomatio/explorbot)).

### Platforms treat verification as one feature among many

| Platform | How it verifies | Why Contexer differs |
|---|---|---|
| Open-Inspect (modelled on Ramp's Inspect) | Playwright visual verification and screenshots stored as artifacts; PRs opened with the user's token. Single-tenant fleet built on Cloudflare plus Modal ([HOW_IT_WORKS.md](https://github.com/ColeMurray/background-agents/blob/main/docs/HOW_IT_WORKS.md)) | It is a hosted fleet, not an independent gate |
| Open SWE | Implements in an isolated sandbox, validates, and reruns only evidence-backed flaky CI jobs. "Not accepting issues or external contributions"; production Agent Server deployments need a license key ([Open SWE](https://github.com/langchain-ai/open-swe)) | Owns its own harness and sandboxes |
| OpenHands SDK | Pairs `ACPAgent` with an experimental critic that "can trigger follow-up prompts" ([critic example](https://github.com/OpenHands/software-agent-sdk/blob/main/examples/01_standalone_sdk/34_critic_example.py)) | Its critic is a model, not executable checks, and the SDK needs Python 3.12 or newer |
| OpenAI's Symphony | Requires "proof of work" (CI status, review feedback, walkthrough videos) before handing off to `Human Review` ([Symphony](https://github.com/openai/symphony)) | It asks for exactly the evidence Contexer produces, which makes it a consumer rather than a rival |

### Incumbents grade their own agents' work

| Product | What it does |
|---|---|
| Claude Code | Ships a `/verify` skill, a Stop-hook gate pattern and `/goal`. Its Code Review never blocks a merge ([best practices](https://code.claude.com/docs/en/best-practices); [Code Review](https://code.claude.com/docs/en/code-review)). |
| Cursor cloud agents | Record their own videos. The forum reports broken mp4 files, which Cursor staff call "a known class of bug" ([Cursor forum](https://forum.cursor.com/t/getting-video-demos-out-of-cloud-agents/157217)). |
| Replit Agent 3 and Lovable | Run browser tests chosen by the same agent that wrote the code ([Replit](https://replit.com/blog/introducing-agent-3-our-most-autonomous-agent-yet); [Lovable](https://docs.lovable.dev/features/browser-testing)). |

### Funding favours "verification layers", but AI testing alone has failed

The commercial signals point the same way. Momentic raised a $15M Series A as a "verification layer for software" ([TechCrunch](https://techcrunch.com/2025/11/24/momentic-raises-15m-to-automate-software-testing)), and Greptile now markets itself as "the independent validation layer for AI-generated code" ([Greptile](https://www.greptile.com/content-library/best-ai-code-review-tools)). Octomind, which sold AI Playwright testing, wound down in mid-2026 for lack of "market validation", according to secondary coverage ([RFP.wiki](https://www.rfp.wiki/vendors/octomind)), a reminder that independence has to come with a gate and measured accuracy, not just generated tests. The two tables below set out each system's overlap and the properties Contexer must ship to stand apart.

| System | Repo / license / stars / last push | What it does | Overlap with Contexer | What Contexer must do differently |
|---|---|---|---|---|
| claw-orchestrator | https://github.com/Enderfga/claw-orchestrator · MIT · 591 · 2026-10-11 (v7.11.0) | Runs acceptance contracts across 5+ engines; verified, refuted or unverified verdicts; tamper rule; budget caps; MCP and ACP; Node 22+ | Independent verdict, tamper rule, budgets, multi-engine | Compile contracts from a ticket with human approval; assert browser behaviour in a closed format; replay checks without an LLM; GitHub check; Python |
| millionco/expect | https://github.com/millionco/expect · FSL-1.1-MIT · 3,562 · 2026-05-06 | Skill inside the agent; turns git changes into a browser test plan; `--flow` replay; `--ci`; GitHub Action | Browser proof of agent diffs; saved flows | Verdict outside the authoring agent; checks a reviewer can inspect; blocking gate; no FSL code |
| bug0inc/qa-agent | https://github.com/bug0inc/qa-agent · FSL-1.1-ALv2 · 1,284 · 2026-09-25 | Natural-language steps over ARIA; Redis step cache; multi-model consensus; video assertions | Step caching, assertion engine | Proven assertions by default; consensus only as a labelled fallback |
| TestSprite CLI | https://github.com/TestSprite/testsprite-cli · Apache-2.0 (client) · 4,622 · 2026-10-12 | Plain-language plan → cloud run → failure bundle → rerun | Positioning and loop shape | Local-first; checks a reviewer can inspect; merge gate; published accuracy |
| Explorbot | https://github.com/testomatio/explorbot · ELv2 · 92 · 2026-10-14 | Exploratory testing crew that saves passing flows as tests | Saved flows | Approved contract rather than exploration |
| Open-Inspect / Ramp Inspect | https://github.com/ColeMurray/background-agents · MIT · 3,358 · 2026-10-14 | Hosted background agent with Playwright visual checks | Harness seam, screenshot evidence | No fleet; independent verdict |
| Open SWE | https://github.com/langchain-ai/open-swe · MIT · 11,016 · 2026-10-14 | Deep Agents and LangGraph software factory; validates; CI babysitting | Validation step | Never own the harness or sandboxes |
| OpenHands critic loop | https://github.com/OpenHands/software-agent-sdk · MIT · 1,254 · 2026-10-14 | `ACPAgent` under an experimental critic | "Agent under a grader" loop | Executable checks, not a critic model; stays on Python 3.11 |
| Playwright Test agents | https://playwright.dev/docs/test-agents · Apache-2.0 | Planner, generator and healer | Plan → checks → heal | Never skip or change data to pass; Python |
| Claude Code built-ins | https://github.com/anthropics/claude-code · none detected · 150,793 · 2026-10-14 | `/verify` skill, Stop hook, `/goal`, Code Review (always `neutral`) | Command name; self-verification | Rename or namespace `/verify`; act as the outer authority |
| GitHub Agent HQ | https://docs.github.com/en/copilot/concepts/agents/about-third-party-agents | Claude and Codex as GitHub agents; CodeQL and secret scans before the PR | Where agent PRs land | Plug in through required checks and MCP in custom agents |
| Spec Kit / Kiro | https://github.com/github/spec-kit · MIT · 141,251 · v1.2.0 | `converge` is LLM-judged; Kiro's property-based tests run only in its IDE ([Kiro](https://kiro.dev/docs/specs/correctness/)) | Requirements → verification | Executable acceptance evidence through a Spec Kit hook; accept EARS-style criteria |
| Chromatic / Percy / Argos; CodeRabbit pre-merge checks | https://argos-ci.com/docs/github | Blocking visual checks with approval; natural-language PR checks in warning or error mode | The gate experience | Borrow the user experience, not the scope |
| QoderAI/better-harness | https://github.com/QoderAI/better-harness · MIT · 2,376 · created 2026-07-21 | Turns agent work-loop evidence into findings with acceptance checks (README only) | Unclear | Watch |
| Orchestration UIs (agent-orchestrator, Superset, Emdash) | https://github.com/OrchestratorInc/agent-orchestrator · Apache-2.0 · 13,162 · 2026-10-14 | Worktree agents with PR and CI views | None directly | Distribution: a Contexer status check appears in their PR views at no extra cost |

| Property | Best existing example | What Contexer must ship |
|---|---|---|
| Verdict outside the authoring agent | claw-orchestrator runs contracts itself | Same, plus the PreToolUse deny, contract hash and diff guard |
| Checks compiled from a ticket, approved by a human, readable by a reviewer | None found; expect, TestSprite and Bug0 use natural-language plans | Closed JSON check format plus a plain-English checklist, approved before the build starts |
| Labels for proven versus judged verdicts | claw-orchestrator's three verdicts; Bug0's consensus | A proven, LLM-judged or heuristic label on every check, shown in the check run |
| Replaying saved checks without an LLM | expect `--flow`; Bug0's Redis step cache | Locked contracts with cached locators; assertions always re-run |
| A blocking GitHub check pinned to its source | Chromatic and Percy for visual changes; Claude Code Review always `neutral` | App check runs, never `neutral`, with expected-source pinning |
| Bounded repair with checkpoints | claw-orchestrator's checkpointed kernel and `maxBudgetUsd` | Snapshot commits, keep-best, a two-round default, distinct terminal reasons |
| Published accuracy | Nobody | Catch rate and false-failure rate for each verdict label (M0) |

## The documented traps cluster around hooks, GitHub's rules and Windows

The published architectures agree on a short list of designs: deterministic code owns control flow with the agent as a bounded node inside it, verification is executable and run by the harness rather than reported by the agent, retries are capped hard with a human handoff, and context stays small and stable. The traps are just as consistent. They sit where an agent's own gate yields (Stop-hook caps and timeouts), where GitHub's semantics surprise (`neutral`, merge-group SHAs, never-reported checks), and where Windows process and path behaviour differs from POSIX. The two tables below are the checklist the team should build against.

### Seventeen patterns worth copying

| Pattern | Source | How Contexer applies it |
|---|---|---|
| Blueprint: deterministic nodes wrap a small number of agent nodes | [Stripe Part 2](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2) | Only deterministic nodes push, comment or set statuses. Agent nodes are "implement" and "repair". |
| Verifier inside the agent as a gate, plus independent re-verification outside it | [Best practices](https://code.claude.com/docs/en/best-practices); [Spotify](https://engineering.atspotify.com/2025/12/feedback-loops-background-coding-agents-part-3) | A Stop hook runs fast checks; Contexer then re-runs everything in its own browser before reporting |
| Contracts the agent cannot edit | [Anthropic harness](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents); [claw-orchestrator](https://github.com/Enderfga/claw-orchestrator) | PreToolUse deny, content hash, diff guard; editing a test refutes the run |
| Hard retry caps with handoff to a human | [Stripe Part 1](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents); [12-factor](https://github.com/humanlayer/12-factor-agents/blob/main/content/factor-09-compact-errors.md) | Two repair rounds by default; a repeated failure signature triggers escalation |
| Distinct terminal reasons, stall detection, backoff | [Symphony SPEC](https://github.com/openai/symphony/blob/main/SPEC.md) | Seven terminal states; kill the agent after 5 minutes with no events |
| Hand off to review instead of declaring "Done" | [Symphony](https://github.com/openai/symphony) | Success ends at "ready for human review", with evidence attached |
| One failure bundle per repair, trimmed by regex | [TestSprite](https://github.com/TestSprite/testsprite-cli); [Spotify](https://engineering.atspotify.com/2025/12/feedback-loops-background-coding-agents-part-3) | Failing check, expected and observed values, screenshot, top log lines |
| Cache-friendly, append-only context | [Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus) | Stable prompt prefix; per-attempt data goes at the end |
| One agent writes code; several verifiers run in parallel | [Cognition](https://cognition.com/blog/dont-build-multi-agents); [Every](https://every.to/chain-of-thought/compound-engineering-how-every-codes-with-agents) | Never run parallel code-writing agents on one change; parallelise read-only checks |
| Check the environment is ready before starting | [Factory](https://factory.com/news/agent-readiness); [Anthropic harness](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) | Score start command, seed data, test login and health URL before the loop starts |
| Policy file kept in the repo | [Symphony](https://github.com/openai/symphony); [CodeRabbit](https://docs.coderabbit.ai/pr-reviews/pre-merge-checks) | `contexer.toml` holds check modes, budgets, start commands and hooks |
| Re-locate deterministically first; use an LLM only above a confidence threshold | [Browser Use](https://github.com/browser-use/browser-use/blob/main/browser_use/agent/service.py); [PayPay](https://blog.paypay.ne.jp/en/ai-driven-self-healing-for-automation-testing-at-paypay/) | The target may change, never the expectation; record the match level |
| Cache actions, never assertions | [Midscene](https://midscenejs.com/caching.html) | Replay runs with no LLM calls and every assertion re-executes |
| Pixel diff proves a change; a vision model judges whether it is acceptable | [ArtifactsBench](https://arxiv.org/abs/2507.04952) | Keep proven and judged results honestly separate |
| Validity rule for oracles: pass on good code, fail on broken code | [SWE-Lancer](https://arxiv.org/html/2502.12115) | Applies to M0 mutants and to compiled checks |
| Harness seam with one completion event | [Open-Inspect](https://github.com/ColeMurray/background-agents/blob/main/docs/HOW_IT_WORKS.md) | `AgentEvent` model; Contexer owns `run_finished` |
| Saved checks feed future work | [Every](https://every.to/chain-of-thought/compound-engineering-how-every-codes-with-agents) | Approved checks become regression contracts; repeated failure types become repo rules |

### Pitfalls the documentation already warns about

| Trap | What the documentation says | Mitigation |
|---|---|---|
| Stop-hook continuation cap | After 8 consecutive Stop-hook continuations, Claude Code overrides the next block. The count resets on each tool call, and `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` raises it ([Hooks](https://code.claude.com/docs/en/hooks)) | Treat the Stop hook as advisory; the outer loop always re-verifies |
| Stop-hook timeout | "A timed-out `command` or `http` hook… On `Stop` that means Claude is allowed to stop". `onFailure: "block"` "has no effect on `Stop`" ([Hooks](https://code.claude.com/docs/en/hooks)) | Run only fast checks in the hook; the full suite runs outside it |
| `-p` without `--bare` | Runs the repo's hooks and `.mcp.json` servers with no trust prompt ([Headless](https://code.claude.com/docs/en/headless)) | Use `--bare` or `setting_sources=[]` plus explicit settings and MCP config |
| Implicit permission mode | A run with no mode set can start in `auto` ([Headless](https://code.claude.com/docs/en/headless)) | Always pass `dontAsk` or `acceptEdits` together with `--allowedTools` |
| Agent starts the dev server | A background dev server started by the agent keeps `-p` open, up to a 10-minute idle ceiling ([Headless](https://code.claude.com/docs/en/headless)) | AGENTS.md and the prompt state that Contexer owns the server |
| Anthropic terms | Products built on the Agent SDK should use API keys. Developers may not "route requests through Free, Pro, or Max plan credentials on behalf of their users". The carve-out lets an end user sign in to "the unmodified Claude Code binary" ([Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)) | Use an API key, Bedrock, Vertex or OIDC on any hosted runner. Locally, start the unmodified `claude` and never read tokens. Get written clarity before marketing "use your Max plan" |
| `/verify` name clash | Claude Code now ships a `/verify` skill that checks a change against the running app ([Best practices](https://code.claude.com/docs/en/best-practices)) | Namespace as `/contexer:verify` in any plugin or skill, and position Contexer as the independent outer check |
| Codex hook trust | Hooks must be trusted; they are "not a complete enforcement boundary"; codex-action needs `unsafe` on Windows runners ([Codex hooks](https://learn.chatgpt.com/docs/hooks); [codex-action](https://github.com/openai/codex-action)) | Treat Codex hooks as best-effort; the outer verdict decides |
| Codex sandbox defaults | `codex exec` defaults to read-only; `--full-auto` is gone ([Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)) | Pass `--sandbox workspace-write` explicitly |
| `neutral` passes | Required checks accept `success`, `skipped` or `neutral` ([Protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)) | Report inconclusive results as `action_required` |
| Merge-queue SHA | The queue tests `gh-readonly-queue/*` commits; `merge_group` is App-only ([Merge queue](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue)) | Replay only, against the merge-group SHA |
| A required check that never reports | If the CI step is skipped, the required check stays pending forever ([Chromatic](https://www.chromatic.com/docs/mandatory-pr-checks/)) | Always report, using `skipped` where it applies |
| Webhook deadlines | GitHub 10 s, Slack 3 s, Linear 10 s ([GitHub](https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks)) | Acknowledge, deduplicate, enqueue |
| Evidence retention | Check data is kept 400 days; `image_url` must be a full URL ([Checks guide](https://docs.github.com/en/rest/guides/using-the-rest-api-to-interact-with-checks)) | Host evidence long-term on storage Contexer owns |
| Events from `GITHUB_TOKEN` | Events it triggers start no new workflow runs, except `workflow_dispatch` and `repository_dispatch` ([GITHUB_TOKEN](https://docs.github.com/en/actions/concepts/security/github_token)) | Chain workflows through dispatch, or use the App's own token |
| Vite port and host | Moves to the next free port; allows only localhost and IP hosts ([Vite](https://github.com/vitejs/vite/blob/main/docs/config/server-options.md)) | `--strictPort --port N --host 127.0.0.1`; in sandboxes, run the browser inside |
| Lazy compilation | Dev servers compile routes on first request | Warm up key routes before the checks run |
| Windows process trees | `taskkill /T` misses re-parented descendants; Playwright's `gracefulShutdown` signals are "ignored on Windows" ([Playwright](https://playwright.dev/docs/test-webserver)) | Kill-on-close Job Object, CTRL_BREAK, psutil |
| PowerShell aliases | `ni` resolves to `New-Item` in Windows PowerShell 5.1 | Reimplement package-manager detection in Python |
| Destructive cleanup | `git clean -fdx` deletes untracked `.env` files; Claude checkpoints miss Bash edits ([Checkpointing](https://code.claude.com/docs/en/checkpointing)) | Snapshot commits; on restore, delete only files created after the snapshot |
| OneDrive and long paths | Worktrees inside OneDrive-synced folders and Windows path limits are risks. The team's own checkout is under OneDrive. | Put worktrees outside synced folders; measure before relying on them |
| Platform gaps | GitHub-hosted Docker needs Linux runners ([GitHub docs](https://docs.github.com/en/actions/tutorials/use-containerized-services/use-docker-service-containers)); Supabase native has no Windows support; mutmut needs WSL | Linux CI for isolation mode; Docker Desktop for Windows developers |
| Mocks that do not reach the server | Playwright `route` does not intercept server-side calls ([Playwright mock](https://playwright.dev/python/docs/mock)) | Use real test-mode services (Supabase, Stripe) for server-side paths |
| Healers that weaken checks | The Playwright healer can make "data fixes" or skip tests ([Test agents](https://playwright.dev/docs/test-agents)) | Only the target may change; broken functionality is a failure |
| Noisy judges | Agent evaluators agree only 31.8–93.6% of the time; Spotify removed its judge ([Vibe Code Bench](https://arxiv.org/abs/2603.04601); [InfoQ](https://infoq.com/news/2026/03/spotify-honk-rewrite)) | Label judged verdicts, use checklist-guided judging, measure agreement in M0 |
| Supply chain | LiteLLM 1.82.7 and 1.82.8 were malicious ([NetSPI](https://www.netspi.com/blog/executive-blog/ai-ml-pentesting/litellm-supply-chain-compromise/)) | Hash-pinned lockfiles for every Python dependency |
| Telemetry defaults | chrome-devtools-mcp sends usage statistics by default and may send trace URLs to CrUX ([chrome-devtools-mcp](https://github.com/ChromeDevTools/chrome-devtools-mcp)) | `--no-usage-statistics --no-performance-crux` |
| Secrets in evidence | `storage_state` files hold "sensitive cookies"; E2B URLs act as credentials ([Playwright auth](https://playwright.dev/python/docs/auth); [E2B](https://docs.e2b.dev/network/public-url.md)) | Gitignore auth state; redact `SERVICE_ROLE_KEY` and `whsec_` values from logs |
| License traps | FSL (expect, qa-agent), ELv2 (Explorbot, Phoenix), AGPL (Skyvern, workflow-use, Hercules, Claude Squad, Coder), SSPL (Inngest), BSL (Restate), LGPL (PyGithub, mirakuru), MPL-2.0 (axe-core) | Copy no code from FSL, ELv2 or AGPL projects; ship axe-core unmodified |
| Unstable conventions | The GenAI semantic conventions are all in Development status | Pin the semconv version and map attribute names in one place |

## Sixteen questions to settle before writing code

The notes leave gaps that would be expensive to discover mid-build. Most can be closed with a fixture repo and a short experiment, and the first one is not technical at all. Each row names the milestone it blocks in the product plan.

| # | Question | Why it matters | How to settle it | Blocks |
|---|---|---|---|---|
| 1 | Does a local CLI that starts the user's logged-in, unmodified `claude` through the Agent SDK count as "offering claude.ai login"? | The product plan's subscription assumption depends on it, and the terms language supports both readings ([Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)) | Written confirmation from Anthropic; default to an API key until then | M1 |
| 2 | Does `setting_sources=[]` without `--bare` suppress the repo's hooks and `.mcp.json` while still allowing OAuth? | Running locally on a subscription cannot use `--bare`, which never reads OAuth | Test with a planted hook and MCP server in a fixture repo | M1 |
| 3 | What is the timeout behaviour of an Agent SDK callback `Stop` hook? | A `PreToolUse` callback that times out blocks the tool call; the docs do not say what a `Stop` callback does | Read the Agent SDK hooks page and test with a slow callback | M1, M3 |
| 4 | Do Codex `Stop` hooks fire and force continuation under `codex exec` and the Python SDK? | Only `SessionStart` is evidenced in exec mode ([hooks.rs](https://github.com/openai/codex/blob/main/codex-rs/exec/tests/suite/hooks.rs)) | Fixture test using `--dangerously-bypass-hook-trust` | M1 |
| 5 | What are OpenCode's SSE event `type` names and its `run --format json` schema? | They are not documented on the SDK or CLI pages | Read `/doc` from a running `opencode serve`, then generate the client | M1 |
| 6 | Can Codex and OpenCode export cost or usage over OTel? | Only Claude Code's telemetry was verified | Check the Codex `[otel]` config and OpenCode's source | M3 |
| 7 | Is an ACP adapter lossy in practice compared with the native APIs? | The gaps in cost, structured output and hooks were inferred from the spec, not tested | Run the same fixture task through native and ACP adapters and diff the events | M1 follow-up |
| 8 | How much does a temporary-index snapshot cost on large JavaScript repos and in OneDrive-synced folders, and why did Codex remove its snapshots? | Snapshots run before every attempt | Benchmark on the M0 apps on Windows, inside and outside OneDrive | M3 |
| 9 | How often does `taskkill /T` orphan npm or pnpm shims, and does the Job Object path close every descendant? | Orphaned dev servers hold ports and corrupt later attempts | Stress-test `npm run dev` start and stop cycles on Windows | M2 |
| 10 | What are cold and warm start times for `vite`, `next dev` and `supabase start` on Windows versus Linux? | They set realistic per-attempt budgets and readiness timeouts | Measure on the M0 apps | M2 |
| 11 | Does Playwright Python 1.64 expose `ariaSnapshotJSON` and the `"ai"` ref grammar? | The re-location design depends on stable refs | Read the 1.64 Python API reference and test | M7 |
| 12 | What licenses do ReproBreak and Supabase CLI carry, and does Web-Bench ship reference solutions? | Dataset redistribution and the "passes on good code" validity rule | Check the LICENSE files; inspect the Web-Bench repo | M0, M2 |
| 13 | Can check runs created with `GITHUB_TOKEN` be written on fork PRs, and which suite do they land in? | Decides whether the gate works before the App exists | Experiment on a test repository with a fork PR | M6 |
| 14 | What are GitHub's default merge-queue timeout and concurrency? | Sets the budget for regression replay in queue mode | Test on a repository with a merge queue enabled | M6 |
| 15 | Is DBOS on SQLite safe when the CLI and a worker run at the same time? | DBOS recommends Postgres for production, with no data on SQLite concurrency | Load test before adopting DBOS | Service phase |
| 16 | Does Orchestrator.inc's daemon expose a hook for external verifiers, and what is Antigravity CLI's headless interface? | Distribution through orchestration UIs and agent coverage after the Gemini CLI transition | Read `docs/architecture.md` and the Antigravity CLI docs | Distribution |

## Conclusion

The line between build and buy has narrowed to four things Contexer writes itself: the contract, the verdict, the repair controller and the report. Every other layer has a maintained, Python-compatible dependency or a documented protocol with a version to pin. Contexer's engineering risk is therefore integration, not invention. The integration risk is concentrated in a few cheap-to-test places: Windows process trees, Vite's host and port behaviour, GitHub's conclusion and merge-queue rules, and Stop-hook semantics. Fixture tests against the open questions above can retire most of that risk before M1 and M2 code is written.

The competitive picture changes what the moat must be. One maintainer has shipped runtime-run contracts with verified and refuted verdicts across five engines, and three source-available or cloud tools already sell browser verification of agent diffs. "We verify in a real browser" is no longer distinctive. What nobody has shipped is a measured verifier with a published catch rate and false-failure rate, joined to a merge gate that only Contexer's App can turn green. The vendors' own documentation supplies the strongest argument for that design: Claude Code's Stop hook gives way after eight blocks or on a timeout, OpenAI calls Codex hooks "not a complete enforcement boundary", and Claude Code Review never blocks. The agent vendors are saying, in writing, that the authoritative verdict has to live outside their agents. What remains unsettled is how Contexer may run Claude Code on a user's behalf. Anthropic's position on subscription credentials decides whether the cheapest path for users is allowed, and it should be confirmed in writing before the first adapter ships.
