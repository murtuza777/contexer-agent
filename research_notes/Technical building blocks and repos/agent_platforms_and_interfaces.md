# Agent platforms and programmatic interfaces: what Contexer should build on (as of 2026-10-14)

Scope: open-source coding-agent platforms and the programmatic interfaces of Claude Code, Codex, OpenCode and other agent CLIs, judged for Contexer, a Python 3.11+ verification and orchestration layer that sits above existing coding agents. Not covered here: browser-testing tools, sandbox providers, workflow engines.

Method and dating conventions:
- Repo metadata (stars, license, last push, language, archived flag) comes from `gh api repos/OWNER/REPO`, run on 2026-10-14. "Pushed" means the last push to any branch. License `null` or `NOASSERTION` means GitHub found no recognised SPDX license file. It does not mean the code is unlicensed.
- Package versions come from the PyPI JSON API and the npm registry `latest` tag, checked on 2026-10-14.
- "(vendor claim)" marks statements a project or company makes about itself that I did not verify independently.
- Several official doc hosts moved. `developers.openai.com/codex/*` now returns HTTP 308 to `learn.chatgpt.com/docs/*`. Claude Code docs are at `code.claude.com/docs`.

---

## Key question 1: How do you drive Claude Code headlessly? (CLI `-p`, stream-json, resume, permissions, hooks, Agent SDK, claude-code-action, auth, limits and terms)

### Takeaway
Claude Code is the best-instrumented agent to drive from a supervisor. It offers `claude -p --output-format stream-json` (typed NDJSON ending in a `result` message with cost, session ID and permission denials), `--json-schema` structured output, `--resume <id>`, scoped `--allowedTools`, a `dontAsk` mode for locked-down CI, and an official Python Agent SDK (`claude-agent-sdk`, Python ≥3.10) that wraps the same binary. Its hooks fit verification gating well: a `Stop` hook that exits 2, or returns `decision:"block"`, keeps the agent working, and a `PreToolUse` hook can deny edits to protected files. Two limits matter: an 8-consecutive-continuation cap, and the fact that a hook timeout lets Claude stop, so Contexer's outer loop has to stay the authority. The binding constraint is the terms. Products built on Claude Code or the Agent SDK must use API keys or cloud-provider credentials, and must not offer claude.ai login or route requests through users' Pro/Max credentials. An end user signing in to the unmodified `claude` binary with their own subscription is explicitly allowed.

### Cited Findings

#### Repo and package metadata (2026-10-14)
- **anthropics/claude-code**: https://github.com/anthropics/claude-code. 150,793 stars. License `null` (no SPDX license detected). TypeScript. Pushed 2026-10-14. Latest release v2.1.299, 2026-10-14. Backed by Anthropic. — [GitHub API](https://github.com/anthropics/claude-code); [releases](https://github.com/anthropics/claude-code/releases)
- **anthropics/claude-agent-sdk-python**: https://github.com/anthropics/claude-agent-sdk-python. 8,277 stars, MIT, pushed 2026-10-14. PyPI `claude-agent-sdk` 0.2.166, `requires_python >=3.10`. — [GitHub API](https://github.com/anthropics/claude-agent-sdk-python); [PyPI](https://pypi.org/project/claude-agent-sdk/)
- **anthropics/claude-agent-sdk-typescript**: https://github.com/anthropics/claude-agent-sdk-typescript. 1,808 stars, license `null`, pushed 2026-10-14. npm `@anthropic-ai/claude-agent-sdk` 0.3.299. — [GitHub API](https://github.com/anthropics/claude-agent-sdk-typescript); [npm](https://www.npmjs.com/package/@anthropic-ai/claude-agent-sdk)
- **anthropics/claude-code-action**: https://github.com/anthropics/claude-code-action. 9,511 stars, MIT, TypeScript, pushed 2026-10-14. The `v1` release tag is dated 2025-08-26. A mirror, anthropics/claude-code-base-action, has 1,003 stars. — [GitHub API](https://github.com/anthropics/claude-code-action)

#### Non-interactive CLI (`claude -p`)
- The docs now frame `claude -p` as "the Agent SDK via the CLI". They say: "To drive the same agent loop from a language other than Python or TypeScript, run the CLI as a subprocess with the `-p` flag and `--output-format json`." — [Headless docs](https://code.claude.com/docs/en/headless); [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview)
- Exit status: "Claude Code exits with code 0 on success and a non-zero code when the run fails". When a failure happens inside the run, such as missing auth, "Claude Code prints the failure as the result on stdout." SIGTERM gives exit 143 and leaves the turn unfinished. To end the turn cleanly, send SIGINT or call the SDK's `interrupt()`. — [Headless docs](https://code.claude.com/docs/en/headless)
- **`--bare`** skips auto-discovery of hooks, skills, plugins, MCP servers, auto memory and CLAUDE.md. The docs call it "the recommended mode for scripted and SDK calls, and will become the default for `-p` in a future release." Bare mode "never reads OAuth credentials or the system keychain": it needs `ANTHROPIC_API_KEY`, an `apiKeyHelper`, or Bedrock/Vertex/Foundry credentials. Context is passed explicitly with `--append-system-prompt[-file]`, `--settings`, `--mcp-config`, `--agents` and `--plugin-dir`. — [Headless docs](https://code.claude.com/docs/en/headless)
- Security note: "Without `--bare`, a `-p` session runs the hooks in a project's `.claude/settings.json` and connects the servers in its `.mcp.json`, even in a folder you've never trusted." There is no trust dialog under `-p`. — [Headless docs](https://code.claude.com/docs/en/headless)
- **Output formats**: `text`, `json` and `stream-json`. Adding `--json-schema '<schema>'` to `--output-format json` puts schema-conforming output in `structured_output`. `json` output includes `total_cost_usd` plus a per-model breakdown; the docs call these "client-side estimates". — [Headless docs](https://code.claude.com/docs/en/headless)
- **stream-json events**: the first event is normally `system/init`, carrying model, tools, `mcp_servers`, `mcp_server_errors`, `plugins`, `plugin_errors` and a `capabilities` array for feature detection. `assistant` and `user` messages carry `tool_use` and `tool_result` blocks. Subagent messages are tagged with `parent_tool_use_id`. `system/api_retry` events carry `attempt`, `error_status`, and `error` categories such as `rate_limit`, `billing_error` and `overloaded`. `permission_denied` system messages appear when prompts are suppressed. Partial tokens come as `stream_event` with `--include-partial-messages`. "The last line of the stream is a `result` message with the final response text, cost, and session metadata." — [Headless docs](https://code.claude.com/docs/en/headless)
- **Sessions**: `--continue` resumes the most recent session. `--resume <session_id>` resumes a specific one; the ID is captured with `jq -r '.session_id'`. `--resume` also accepts an absolute path to a session `.jsonl` transcript. Resumed runs report the cumulative cost of the whole conversation. — [Headless docs](https://code.claude.com/docs/en/headless)
- **Permissions**: `--allowedTools` uses permission-rule syntax, for example `Bash(git diff *)`. Modes include `auto` (a classifier reviews actions), `dontAsk` ("denies every call that would otherwise prompt, which is useful for locked-down CI runs") and `acceptEdits`. The docs warn: "A run where nothing sets a permission mode takes the built-in starting permission mode, which can be `auto`, so pass the one you want." `--permission-prompts none` (v2.1.259+) denies anything that would prompt, removes `AskUserQuestion`, and lists denials in the result's `permission_denials`. `--permission-prompt-tool` delegates approvals to an MCP tool. `--max-budget-usd` caps spend. — [Headless docs](https://code.claude.com/docs/en/headless)
- **Background work at exit**: a `-p` run waits for background commands, subagents and Monitor watches. By default it stops after 10 minutes of idle waiting (`CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS`). A dev server started by Claude with a background command keeps the run open until the command exits. — [Headless docs](https://code.claude.com/docs/en/headless)

#### Hooks (blocking completion and tool use)
- **Event list (2026-10)**: SessionStart, SessionEnd, Setup, UserPromptSubmit, UserPromptExpansion, Stop, StopFailure, PreToolUse, PermissionRequest, PermissionDenied, PostToolUse, PostToolUseFailure, PostToolBatch, SubagentStart, SubagentStop, TaskCreated, TaskCompleted, TeammateIdle, PreCompact, PostCompact, InstructionsLoaded, ConfigChange, CwdChanged, DirectoryAdded, FileChanged, WorktreeCreate, WorktreeRemove, PreModelSwitch, PostModelSwitch, Elicitation, ElicitationResult, Notification, MessageDisplay. — [Hooks reference](https://code.claude.com/docs/en/hooks)
- **Hook types**: `command`, `http` (POSTs the same JSON to a URL), `mcp_tool`, `prompt` (single-turn model evaluation) and `agent` (a subagent that can use tools to verify conditions; experimental). Default timeouts are 600 s for command, http and mcp_tool, 30 s for prompt and 60 s for agent. — [Hooks reference](https://code.claude.com/docs/en/hooks)
- **Blocking semantics**: exit 2 is a blocking error and stderr is fed back to Claude ("Exit 2 still blocks even if the hook prints JSON that says allow"). On `Stop`, `decision:"block"` with a `reason` "prevents Claude from stopping". Stop input includes `stop_hook_active`, `last_assistant_message`, `background_tasks` and `session_crons`. — [Hooks reference](https://code.claude.com/docs/en/hooks)
- **Loop cap**: "Claude Code applies an 8-consecutive-continuation cap: after stop hooks have continued the turn eight times in a row, Claude Code overrides the next block and ends the turn. The count of consecutive continuations resets each time Claude calls a tool. To raise the cap, set `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`." — [Hooks reference](https://code.claude.com/docs/en/hooks)
- **Timeout pitfall**: "A timed-out `command` or `http` hook is canceled and renders no decision. On `Stop` that means Claude is allowed to stop." The `onFailure: "block"` option (v2.1.295+) "has no effect on `Stop`". — [Hooks reference](https://code.claude.com/docs/en/hooks)
- **PreToolUse**: returns `hookSpecificOutput.permissionDecision` of `allow`, `deny`, `ask` or `defer`, with precedence `deny > defer > ask > allow`. `updatedInput` rewrites tool arguments. `defer` is honored only in `-p` mode. In the Agent SDK, "a callback hook on `PreToolUse` that exceeds its timeout blocks the tool call". — [Hooks reference](https://code.claude.com/docs/en/hooks)
- Hooks are configured in `~/.claude/settings.json`, `.claude/settings.json`, `.claude/settings.local.json`, managed policy, plugin `hooks/hooks.json`, or skill and subagent frontmatter. — [Hooks reference](https://code.claude.com/docs/en/hooks)

#### Claude Agent SDK (Python and TypeScript)
- The SDK is "a library that runs the Claude Code binary". It exposes built-in tools, hooks, subagents, MCP, permissions, sessions, skills and plugins. — [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview)
- **Python API**: `query()` creates a new session per call. `ClaudeSDKClient` reuses a session and supports `interrupt`, `set_permission_mode`, `set_model`, `rewind_files` and `get_mcp_status`. — [Python SDK reference](https://code.claude.com/docs/en/agent-sdk/python)
- **`ClaudeAgentOptions`** includes `allowed_tools`, `disallowed_tools`, `permission_mode`, `can_use_tool`, `hooks`, `mcp_servers`, `cwd`, `setting_sources`, `max_turns`, `max_budget_usd`, `output_format`, `resume`, `fork_session`, `env`, `cli_path` and `sandbox`. Details:
  - `permission_mode`: `default`, `acceptEdits`, `plan`, `dontAsk`, `bypassPermissions` or `auto`.
  - `can_use_tool` runs only when the flow falls through to a prompt. The docs say: "To gate every tool call, use a `PreToolUse` hook instead."
  - `setting_sources=[]` disables user, project and local settings.
  - `output_format={"type":"json_schema","schema":...}` requests structured output.
  — [Python SDK reference](https://code.claude.com/docs/en/agent-sdk/python)
- **`ResultMessage`** has:
  - `subtype`: `success`, `error_during_execution`, `error_max_turns`, `error_max_budget_usd` or `error_max_structured_output_retries`
  - `is_error`, `total_cost_usd`, `session_id`, `result`, `structured_output`, `permission_denials`
  - `terminal_reason`, such as `completed`, `max_turns` or `api_error`
  - `usage` and `model_usage`
  Other message types include `RateLimitEvent` and `Task*Message`. `include_hook_events` yields `HookEventMessage`. — [Python SDK reference](https://code.claude.com/docs/en/agent-sdk/python)
- **In-process tools**: `@tool(...)` plus `create_sdk_mcp_server(...)` registers Python functions as MCP tools, named `mcp__<server>__<tool>`. — [Python SDK reference](https://code.claude.com/docs/en/agent-sdk/python)
- The Python SDK refers to "the CLI bundled with those SDK versions". `cli_path` overrides the binary, and `CLINotFoundError` is raised when it is missing. — [Python SDK reference](https://code.claude.com/docs/en/agent-sdk/python)
- **Branding**: partners may say "{YourAgentName} Powered by Claude" but not "Claude Code" or "Claude Code Agent". Use is governed by the Commercial Terms. — [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview)
- The docs also list **Managed Agents**, "a hosted agent harness" with sessions in an Anthropic-managed cloud sandbox or a self-hosted sandbox. — [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview)

#### claude-code-action (GitHub)
- Runs on your own GitHub runner. Mode is detected from context: @claude mentions, issue assignment, or automation with an explicit `prompt`. Structured outputs become Action outputs. Progress tracking uses checkbox comments. — [README](https://github.com/anthropics/claude-code-action)
- **Inputs** include:
  - `prompt`, `claude_args`, `settings`, `plugins`, `plugin_marketplaces`, `track_progress`, `use_sticky_comment`
  - `allowed_bots`, `branch_prefix` (default `claude/`), `base_branch`, `use_commit_signing`
  - auth: `anthropic_api_key`, `claude_code_oauth_token` ("Claude Code OAuth token, an alternative to the API key"), workload-identity-federation inputs, `use_bedrock`, `use_vertex`, `use_foundry`
  **Outputs**: `conclusion` (`success` or `failure`), `execution_file`, `branch_name`, `github_token`, `structured_output` (when `--json-schema` is in `claude_args`) and `session_id`. — [action.yml](https://github.com/anthropics/claude-code-action/blob/main/action.yml)
- The action has no input or output that creates a GitHub Check Run or commit status. Reporting is through comments and the step summary (`display_report`). — [action.yml](https://github.com/anthropics/claude-code-action/blob/main/action.yml)

#### Authentication, terms and limits
- **Official policy**: OAuth "is intended exclusively for purchasers of Claude Free, Pro, Max, Team, and Enterprise subscription plans and is designed to support ordinary use of Claude Code and other native Anthropic applications." "Developers building products or services that interact with Claude's capabilities, including those using the Agent SDK, should use API key authentication… Anthropic does not permit third-party developers to offer Claude.ai login into their own applications, or to route requests through Free, Pro, or Max plan credentials on behalf of their users… developers may not collect, store, or intermediate Claude.ai credentials or session tokens." — [Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)
- **The carve-out**: the policy "does not… prevent an end user from signing in to the unmodified Claude Code binary with their own Claude subscription, including where a platform hosts Claude Code". — [Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)
- **Conditions for running Claude Code inside products** (Commercial Terms): "The Claude Code binary must not be modified". Customers may not "remove, disable, or restrict any authentication method built into it". "Customers may not pay for, resell, or intermediate Claude usage on their end users' behalf". — [Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)
- "Advertised usage limits for Pro and Max plans assume ordinary, individual usage of Claude Code and the Agent SDK." — [Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)
- "Unless previously approved, Anthropic does not allow third party developers to offer claude.ai login or rate limits for their products, including agents built on the Claude Agent SDK." — [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview)
- **Enforcement history (secondary sources)**:
  - Server-side checks from about 2026-01-09 blocked third-party tools, including OpenCode, Cline and RooCode, from authenticating to Pro/Max via OAuth. — [VentureBeat](https://venturebeat.com/technology/anthropic-cracks-down-on-unauthorized-claude-usage-by-third-party-harnesses); [falcao.org](https://falcao.org/posts/anthropic-claude-access-crackdown-ecosystem-fallout/)
  - A later cutoff aimed at OpenClaw reportedly took effect 2026-04-04. — [implicator.ai](https://www.implicator.ai/anthropic-cuts-openclaw-from-claude-subscriptions-citing-unsustainable-compute-costs/)
  - These reports are secondary and their dates disagree; the official policy text above is authoritative.
- **Usage limits (unverified secondary)**: blogs report rolling 5-hour windows plus weekly caps for Pro and Max (weekly caps since August 2025), and that `claude -p`, Agent SDK and GitHub Actions usage on a subscription draws from the same pool. A planned June 2026 split of programmatic usage was reportedly paused. Numbers vary between sources. — [redreamality.com](https://redreamality.com/blog/claude-code-usage-limits-cost-2026/); [morphllm.com](https://www.morphllm.com/claude-code-subscription)
- **API retry visibility**: the stream emits `system/api_retry` with `error: rate_limit` and similar categories, so a supervisor can detect throttling. — [Headless docs](https://code.claude.com/docs/en/headless)

### Inferences
- **BUILD ON: Claude Code via `claude-agent-sdk` (Python) as Contexer's primary adapter, with `claude -p --output-format stream-json` as a fallback.**
  - The SDK is native Python (≥3.10, which fits Contexer's 3.11+). It returns typed `ResultMessage` objects with cost, `permission_denials`, `structured_output` and `terminal_reason`.
  - It supports budget caps (`max_budget_usd`), in-process MCP tools, and `rewind_files` (useful next to git checkpoints).
  - Pin both the SDK and the bundled CLI version. The TS SDK's patch number (0.3.299) matches the CLI's (2.1.299). The Python SDK (0.2.166) is numbered independently, so record the CLI version (`claude --version`) in every evidence report.
- **BUILD ON: Claude Code hooks as an inner verification gate, with Contexer's outer loop as the authority.**
  - A `Stop` hook (or SDK `Stop` callback) can run Contexer's fast checks and return `decision:"block"` with the failing evidence.
  - A `PreToolUse` hook can `deny` `Edit`/`Write` on the approved acceptance-check files and on `.contexer/`, so the agent cannot weaken the checks.
  - The outer loop still has to re-verify after the run ends, for three documented reasons: the 8-continuation cap overrides blocks, a timed-out Stop hook lets Claude stop, and `onFailure:"block"` doesn't apply to Stop.
- **Use `--bare` / `setting_sources=[]` plus explicit `--settings` and `--mcp-config` in CI.** This makes runs reproducible and avoids executing untrusted repository hooks. Without `--bare`, `-p` runs a repo's hooks and MCP servers with no trust prompt.
- **Auth posture for Contexer**:
  - Default to `ANTHROPIC_API_KEY`, Bedrock, Vertex or Foundry, and to GitHub OIDC workload identity federation in Actions, which claude-code-action already supports.
  - Locally, support "use the `claude` you already logged in to" by spawning the unmodified binary, never reading or storing tokens. This appears to fall under the end-user carve-out.
  - Never offer a claude.ai login flow inside Contexer.
  - Exposing "use your Max plan" as a headline product feature, especially on a hosted Contexer runner, is the part most likely to conflict with the "ordinary, individual usage" and "no third-party claude.ai login" language. Get written clarity from Anthropic before doing it.
- **BORROW IDEAS (optional BUILD ON) from claude-code-action.** It handles triggers, branches, commit signing and comments, but emits no Check Run. Contexer's status check and evidence report are additive. Contexer can either run after claude-code-action in the same workflow, reading its `branch_name`, `session_id` and `conclusion` outputs, or ship its own Action that calls the SDK directly. Borrow its auth matrix and its `allowed_bots` and `allowed_non_write_users` safety inputs.

### Gaps
- No official, current numeric rate limits for Pro, Max or API tiers specific to `claude -p` or the Agent SDK. Only secondary blogs were found, and they conflict.
- Whether a CLI tool like Contexer that spawns the user's own logged-in `claude` binary through the Agent SDK counts as "offering claude.ai login… for their products" is not stated explicitly. Both readings are possible; this needs confirmation from Anthropic.
- I did not read the full Agent SDK hooks page (list of Python-supported hook events, `HookMatcher` shape). It is referenced at https://code.claude.com/docs/en/agent-sdk/hooks.

---

## Key question 2: How do you drive OpenAI Codex? (`codex exec --json`, Codex SDK, app-server, codex-action, hooks, AGENTS.md)

### Takeaway
Codex offers three supported automation surfaces:
- `codex exec --json`: stable JSONL with `thread.*`, `turn.*` and `item.*` events; `--output-schema`; `codex exec resume`.
- The Codex SDK: TypeScript `@openai/codex-sdk` spawns the CLI. The Python package `openai-codex`, ≥3.10, version 0.162.1, "controls the local Codex app-server over JSON-RPC".
- The app-server JSON-RPC protocol, which OpenAI positions for rich clients. Its WebSocket transport and many methods are experimental.

`codex mcp-server` has been removed. Codex now has Claude-Code-style hooks (`Stop`, `PreToolUse`, …) that are enabled by default but must be trusted. The Python SDK is the natural second adapter for Contexer. `codex exec --json` is the lowest-coupling fallback.

### Cited Findings

#### Metadata (2026-10-14)
- **openai/codex**: https://github.com/openai/codex. 129,197 stars, Apache-2.0, Rust, pushed 2026-10-14. Latest release `rust-v0.162.1`, 2026-10-09. npm `@openai/codex` and `@openai/codex-sdk` are both 0.162.1. PyPI `openai-codex` 0.162.1, `requires_python >=3.10`. Backed by OpenAI. — [GitHub API](https://github.com/openai/codex); [releases](https://github.com/openai/codex/releases); [PyPI](https://pypi.org/project/openai-codex/)
- **openai/codex-action**: https://github.com/openai/codex-action. 1,266 stars, Apache-2.0, JavaScript, pushed 2026-10-14. — [GitHub API](https://github.com/openai/codex-action)
- **openai/codex-plugin-cc**: https://github.com/openai/codex-plugin-cc. "Use Codex from Claude Code to review code or delegate tasks". 34,203 stars, Apache-2.0, created 2026-03-30, pushed 2026-07-08. — [GitHub API](https://github.com/openai/codex-plugin-cc)

#### `codex exec`
- Progress streams to stderr and only the final agent message goes to stdout. `--json` makes stdout a JSON Lines stream. `-o/--output-last-message <path>` writes the final message to a file. `--output-schema <file>` makes the final response conform to a JSON Schema. — [Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
- "By default, `codex exec` runs in a read-only sandbox." Edits need `--sandbox workspace-write`. `danger-full-access` is only for controlled environments. "`--full-auto` is no longer supported"; use `--sandbox workspace-write` or `--approve-for-me`, which routes approvals through automatic review. Other flags: `--ephemeral`, `--ignore-user-config`, `--ignore-rules`, `--skip-git-repo-check`. — [Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
- **Resume**: `codex exec resume --last "<prompt>"` or `codex exec resume <SESSION_ID>`. — [Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
- **Event types** in the TS SDK source: `thread.started`, `turn.started`, `turn.completed` (with `usage`: input, cached, output and reasoning tokens), `turn.failed`, `item.started`, `item.updated`, `item.completed`, `error`. — [events.ts](https://github.com/openai/codex/blob/main/sdk/typescript/src/events.ts); [Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
- **Item types**: `command_execution` (with status), `file_change` (with patch-apply status), `mcp_tool_call` (with status), `agent_message`, `reasoning`, `web_search`, `todo_list` and `error`. — [items.ts](https://github.com/openai/codex/blob/main/sdk/typescript/src/items.ts)
- **CI auth**: `CODEX_API_KEY=<key> codex exec --json "..."`, set inline per invocation. Don't set `OPENAI_API_KEY` or `CODEX_API_KEY` at job level when running repository-controlled code. — [Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
- **ChatGPT-managed auth in CI** is documented but discouraged: "The right way to authenticate automation is with an API key". ChatGPT auth is for trusted private runners only, never public or OSS repos. Keep one `auth.json` per runner; Codex refreshes tokens about every 8 days and writes them back. The page says nothing about usage limits or terms for automated use on ChatGPT plans. — [CI/CD auth](https://learn.chatgpt.com/docs/auth/ci-cd-auth)

#### Codex SDK and app-server
- **TypeScript**: "The TypeScript SDK wraps the `codex` CLI from `@openai/codex`. It spawns the CLI and exchanges JSONL events over stdin/stdout." It provides `startThread()`, `run()`, `runStreamed()` (an async generator of `item.completed` and similar events), `resumeThread(id)`, and `outputSchema` on `run`. — [TS SDK README](https://github.com/openai/codex/blob/main/sdk/typescript/README.md)
- **Python**: package `openai-codex`, Python ≥3.10, "Published builds bundle a pinned Codex CLI runtime". API: `Codex()` as a context manager, `thread_start(model=..., sandbox=...)`, `thread.run(prompt)` → `final_response`, and `AsyncCodex`. Sandbox presets are `read_only`, `workspace_write` and `full_access`. It "controls the local Codex app-server over JSON-RPC." — [Codex SDK docs](https://learn.chatgpt.com/docs/codex-sdk)
- The Python SDK source tree includes `_approval_mode.py`, `_goal.py`, `_login.py`, `retry.py`, and generated `notification_registry.py` and `v2_all.py` (app-server v2 types). — [openai/codex sdk/python](https://github.com/openai/codex/tree/main/sdk/python)
- "The `codex mcp-server` command and standalone `codex-mcp-server` binary have been removed"; existing integrations should move to the app server. — [Codex SDK docs](https://learn.chatgpt.com/docs/codex-sdk)
- **App-server transports**: stdio JSONL (default), `ws://` (experimental, "not supported for production"; non-loopback listeners are unauthenticated by default) and a unix socket. It speaks JSON-RPC 2.0 without the `jsonrpc` header on the wire. — [App server docs](https://learn.chatgpt.com/docs/app-server)
- **App-server methods**: `initialize`/`initialized`, `thread/start`, `thread/resume`, `thread/fork`, `turn/start`, `turn/steer`, `turn/interrupt` and `review/start`. Notifications include `thread/started`, `turn/started`, `turn/completed`, `item/started`, `item/completed` and `item/agentMessage/delta`. Server-initiated requests include `item/permissions/requestApproval` and `mcpServer/elicitation/request`. `codex app-server generate-ts` / `generate-json-schema` emit version-matched schemas. Many methods need `capabilities.experimentalApi = true`. OpenAI recommends the SDK rather than the raw app-server for automation and CI. — [App server docs](https://learn.chatgpt.com/docs/app-server)

#### Hooks
- **Events**: `PreToolUse`, `PermissionRequest`, `PostToolUse`, `PreCompact`, `PostCompact`, `UserPromptSubmit`, `SubagentStop`, `Stop`, `Interrupt`, `SessionStart`, `SubagentStart`, `SessionEnd`. "Hooks are enabled by default" (`[features] hooks = false` turns them off). Hooks live in `hooks.json` or `[hooks]` tables in `config.toml`, at user or repo level. — [Codex hooks](https://learn.chatgpt.com/docs/hooks)
- **Stop**: `"decision":"block"` plus `reason`, or exit 2, "tells Codex to continue and creates a new continuation prompt using `reason`". `stop_hook_active` is provided. — [Codex hooks](https://learn.chatgpt.com/docs/hooks)
- **PreToolUse**: `permissionDecision:"deny"` or exit 2. It covers shell (`Bash`), `exec_command`, `apply_patch` (matched as `apply_patch`, `Edit` or `Write`), MCP tools and local function tools. It does not cover hosted tools like WebSearch. `ask` and `continue:false` are unsupported in PreToolUse. — [Codex hooks](https://learn.chatgpt.com/docs/hooks)
- **Trust**: non-managed hooks must be reviewed and trusted through `/hooks`, and are recorded by hash. `--dangerously-bypass-hook-trust` skips persisted trust for one invocation. Project-local hooks load only when the project `.codex/` layer is trusted. OpenAI calls tool hooks "a useful guardrail, not a complete enforcement boundary"; `prompt` and `agent` handler types are "parsed but skipped". — [Codex hooks](https://learn.chatgpt.com/docs/hooks)
- The Codex repo has an exec-mode test, `exec_hook_trust_bypass_runs_session_start_hook`, that passes `--dangerously-bypass-hook-trust`. So hooks run under `codex exec`, at least `SessionStart`. — [codex-rs/exec/tests/suite/hooks.rs](https://github.com/openai/codex/blob/main/codex-rs/exec/tests/suite/hooks.rs)

#### codex-action
- Installs Codex and routes API calls through a proxy to the Responses API. Inputs:
  - `prompt` / `prompt-file`, `openai-api-key`, `responses-api-endpoint` (Azure)
  - `permission-profile` (beta, CLI ≥0.138.0) or legacy `sandbox`
  - `safety-strategy`: `drop-sudo` (default), `unprivileged-user`, `read-only` or `unsafe`
  - `output-file`, `output-schema[-file]`, `codex-args`, `model`, `effort`, `allow-users`, `allow-bots`
  Output: `final-message`. It "does not create pull requests"; the example posts `final-message` as a PR comment from a separate job. On Windows runners you must use `safety-strategy: unsafe`. — [codex-action README](https://github.com/openai/codex-action)

### Inferences
- **BUILD ON: the Codex Python SDK (`openai-codex`) as Contexer's second adapter.** It is Python-native, bundles a pinned CLI, exposes thread, turn and item semantics, and sits on app-server JSON-RPC. That gives Contexer approvals and streamed items without writing a JSON-RPC client. **Fallback: `codex exec --json --output-schema --sandbox workspace-write`**, parsing the documented JSONL item types. It needs no extra dependency and is the most stable surface.
- **AVOID (for now): talking to the app-server directly.** OpenAI itself steers automation to the SDK, the WebSocket transport is unsupported for production, and much of the protocol sits behind `experimentalApi`.
- **Normalisation is feasible.** Codex's `file_change` / `command_execution` / `mcp_tool_call` / `agent_message` items map cleanly onto Claude Code's `tool_use` blocks (`Edit`/`Write`/`Bash`/`mcp__*`). One internal event model can cover both.
- **Cost reporting**: Codex `turn.completed` reports token usage but, unlike Claude's `total_cost_usd`, no USD cost. Contexer would need its own price table to report cost.
- **Hooks give parity with Claude Code.** Contexer can ship one `.contexer/hooks/stop_gate` script registered in both `.claude/settings.json` and `.codex/hooks.json`. Codex adds trust friction: automation needs `--dangerously-bypass-hook-trust` or managed hooks. Treat Codex hooks as best-effort, since OpenAI says they are not an enforcement boundary.
- **BORROW IDEAS from codex-action**: the safety-strategy model, the API-key proxy, and the `allow-users`/`allow-bots` gating. Note that Windows runners have no sandbox.

### Gaps
- Whether `Stop` hooks fire and can force continuation under `codex exec` and the SDK, specifically, was not confirmed. Only `SessionStart` in exec is evidenced by a test.
- No official statement found on rate limits or terms for automated Codex use on ChatGPT Plus/Pro plans. The CI auth page only covers mechanics.
- I did not read the full app-server item schema (only the first 100k characters of the docs). Exact item type names in app-server v2 (for example `commandExecution`) are therefore not verified here.

---

## Key question 3: Which other agents have headless or server modes? (OpenCode, Gemini CLI, Goose, Aider)

### Takeaway
OpenCode, which Contexer uses today, is the most "server-first" agent:
- `opencode serve` exposes an OpenAPI 3.1 HTTP API with an SSE event stream, session diff, abort and permission endpoints.
- It has a typed JS SDK with JSON-schema structured output, `opencode run --format json`, and `opencode acp`.
- Since January 2026 it cannot use Claude Pro/Max subscriptions.

Gemini CLI has good headless JSON and stream-json, but Google moved consumer and free users to the separate Antigravity CLI on 2026-06-18. Gemini CLI remains for enterprise and API-key users.

Goose (now under the Linux Foundation's AAIF) has `goose run` with json/stream-json and ACP support, but it is a general-purpose agent. Aider has no event stream and an unsupported Python API, and its last push was 2026-05-22.

### Cited Findings

#### OpenCode
- **anomalyco/opencode** (sst/opencode redirects here): https://github.com/anomalyco/opencode. 213,441 stars, MIT, TypeScript, pushed 2026-10-14. Latest v1.19.0, 2026-10-11. npm `@opencode-ai/sdk` 1.19.0. — [GitHub API](https://github.com/anomalyco/opencode); [releases](https://github.com/anomalyco/opencode/releases)
- The official Python SDK, anomalyco/opencode-sdk-python, has 286 stars, MIT, and its last push was 2026-01-30, so it lags the server by about 8 months. — [GitHub API](https://github.com/anomalyco/opencode-sdk-python)
- **`opencode serve`**: `--port` (default 4096), `--hostname` (default 127.0.0.1), `--cors`, `--mdns`. Basic auth turns on when `OPENCODE_SERVER_PASSWORD` is set. The OpenAPI 3.1 spec is at `/doc`. Endpoints:
  - `POST /session`
  - `POST /session/:id/message`, which waits
  - `POST /session/:id/prompt_async`, which returns 204
  - `POST /session/:id/abort`
  - `GET /session/:id/diff`
  - `POST /session/:id/permissions/:permissionID`
  - `GET /event` and `GET /global/event` (SSE)
  - `/find`, `/file`, `/file/content`, and `/tui` endpoints to drive the TUI
  The TUI is itself a client of the server. — [OpenCode server docs](https://opencode.ai/docs/server/)
- **SDK**: `createOpencode()` starts a server and a client; `createOpencodeClient({baseUrl})` attaches to a running server. Methods include `session.create`, `session.prompt` (with `noReply`), `session.abort` and `event.subscribe()`. Structured output uses `format: {type:"json_schema", schema}` through a `StructuredOutput` tool with `retryCount` (default 2). The docs also call this field `outputFormat`, so the naming is inconsistent. — [OpenCode SDK docs](https://opencode.ai/docs/sdk/)
- **CLI**: `opencode run` supports `--format json` ("raw JSON events"; schema undocumented), `--session`, `--continue`, `--fork`, `--attach http://localhost:4096` (avoids MCP cold boot), `--agent`, `--model` and `--auto` ("Auto-approve permissions that are not explicitly denied"). `opencode acp` starts an ACP server over stdio nd-JSON. `opencode github install|run` sets up and runs a GitHub Actions agent. `OPENCODE_PERMISSION` takes inline JSON permissions. — [OpenCode CLI docs](https://opencode.ai/docs/cli/)
- Ramp chose OpenCode for its Inspect agent and says it "strongly recommend[s]" it for its server-first design, typed SDK and plugin system. (Ramp's view.) — [Ramp builders blog](https://builders.ramp.com/post/why-we-built-our-background-agent)
- OpenCode lost Claude Pro/Max OAuth access around 2026-01-09. Secondary reports also mention a legal demand in March 2026. — [VentureBeat](https://venturebeat.com/technology/anthropic-cracks-down-on-unauthorized-claude-usage-by-third-party-harnesses); [falcao.org](https://falcao.org/posts/anthropic-claude-access-crackdown-ecosystem-fallout/)

#### Gemini CLI
- **google-gemini/gemini-cli**: https://github.com/google-gemini/gemini-cli. 107,353 stars, Apache-2.0, TypeScript, pushed 2026-10-14. Latest v0.64.0, 2026-10-13. — [GitHub API](https://github.com/google-gemini/gemini-cli)
- **Headless**: `-p/--prompt`. JSON output is `{response, stats, error?}`. Streaming JSONL events are `init`, `message`, `tool_use`, `tool_result`, `error` and `result` (with aggregated stats). Exit codes: 0 success, 1 error, 42 input error, 53 turn limit exceeded. — [Gemini CLI headless docs](https://geminicli.com/docs/cli/headless/)
- **Transition**: Google announced at I/O on 2026-05-19 that Antigravity CLI (`agy`, written in Go) replaces Gemini CLI. Gemini CLI stopped serving free, Google AI Pro and Ultra individual tiers on 2026-06-18. It remains for Gemini Code Assist Standard/Enterprise and paid API keys. — [Google Developers Blog](https://developers.googleblog.com/en/an-important-update-transitioning-gemini-cli-to-antigravity-cli/); [Virtualization Review](https://virtualizationreview.com/articles/2026/05/19/google-moves-gemini-cli-into-antigravity-cli-as-agent-platform-expands.aspx)
- Third-party coverage disagrees on whether Antigravity CLI is open source; this was not verified here. — [Google Developers Blog](https://developers.googleblog.com/en/an-important-update-transitioning-gemini-cli-to-antigravity-cli/)
- Gemini CLI is listed as an ACP agent. — [ACP agents list](https://agentclientprotocol.com/overview/agents)

#### Goose
- **aaif-goose/goose** (block/goose redirects here): https://github.com/aaif-goose/goose. 55,280 stars, Apache-2.0, Rust, pushed 2026-10-14. Latest v1.54.0, 2026-10-08. It describes itself as a "general-purpose AI agent… Not just for code". It ships as a desktop app, CLI and API. It "works with 15+ providers" and can "use… your existing Claude, ChatGPT, or Gemini subscriptions via ACP" (vendor claim). It is "part of the Agentic AI Foundation (AAIF) at the Linux Foundation". — [goose README](https://github.com/aaif-goose/goose)
- **`goose run`** flags: `-t/--text`, `-i <file|->`, `--recipe <file>`, `--no-session`, `-n`/`-r` (name/resume), `--output-format json|stream-json`, `--provider`/`--model`, and `--with-extension` and related flags. — [goose running tasks docs](https://goose-docs.ai/docs/guides/running-tasks)
- AAIF was announced 2025-12-09 with three founding projects: MCP (Anthropic), goose (Block) and AGENTS.md (OpenAI). Platinum members include AWS, Anthropic, Block, Bloomberg, Cloudflare, Google, Microsoft and OpenAI. — [Linux Foundation press release](https://www.linuxfoundation.org/press/linux-foundation-announces-the-formation-of-the-agentic-ai-foundation)

#### Aider
- **Aider-AI/aider**: https://github.com/Aider-AI/aider. 49,548 stars, Apache-2.0, Python. Last push 2026-05-22, about 5 months before this check. — [GitHub API](https://github.com/Aider-AI/aider)
- **Scripting**: `--message/-m`, `--message-file`, `--yes`, `--auto-commits`/`--no-auto-commits`, `--dry-run`. There is a Python API (`Coder.create(...)`, `coder.run(...)`), but it "is not officially supported or documented, and could change". The docs describe no JSON output or event stream. — [Aider scripting docs](https://aider.chat/docs/scripting.html)

### Inferences
- **BUILD ON: OpenCode (keep it), through its HTTP server rather than the stale Python SDK.**
  - Contexer can generate a small `httpx` client from `/doc` and consume `GET /event` over SSE.
  - `GET /session/:id/diff` gives a free diff artifact for the evidence report.
  - `opencode run --attach` reuses one warm server across repair iterations.
  - OpenCode is also the most provider-flexible backend, which matters for the "use OpenRouter or any model" story.
  - It is not a route to Claude subscriptions. Anthropic models through OpenCode need API keys.
- **BORROW IDEAS / low priority: Gemini CLI.** Its headless contract (typed events plus distinct exit codes such as 53 for turn limit) is a good model for Contexer's own CLI exit codes. The product's consumer base has moved to Antigravity CLI, so Gemini is a weak first-wave target. Reach it through ACP if needed.
- **AVOID as a primary backend, BORROW IDEAS: Goose.** It is general-purpose rather than coding-focused. Its "recipes" are a portable, shareable task-definition format worth studying for Contexer's saved check bundles. Its AAIF governance makes it a stable ACP and MCP reference implementation.
- **AVOID: Aider.** It has no structured event stream, an unsupported Python API, and stalled pushes. At most, reach it as an opaque subprocess (`--message`) via git-diff inspection.

### Gaps
- The `opencode run --format json` event schema is not documented on the CLI page. Event `type` values on `/event` are not listed in the SDK docs; they would need to be read from the OpenAPI spec or source.
- OpenCode plugin and hook events (for example a pre-tool or session-idle hook usable as a completion gate) were not researched.
- Antigravity CLI's programmatic interface (headless flags, ACP support, license) was not researched; the `agy` engine appears in claw-orchestrator's compatibility table.
- `GOOSE_MODE` approval values and the goose server (`goosed`) API were not found on the page fetched.

---

## Key question 4: Which open-source background-agent platforms exist and how are they built? (Open SWE, Open-Inspect, OpenHands and its SDK, SWE-agent/mini, Agentless, PR-Agent, Vibe Kanban, Claude Squad, 2026 orchestrators)

### Takeaway
The 2026 landscape splits into four groups:
1. Full background-agent platforms that own the harness, sandbox fleet, triggers and PR flow: Open SWE (LangGraph/Deep Agents), Open-Inspect (Cloudflare + Modal/Daytona/E2B, with OpenCode or the Claude Agent SDK as harness), and OpenHands (its own SDK plus agent server).
2. Research agents: SWE-agent, mini-swe-agent and Agentless.
3. Local multi-agent UIs and orchestrators that run vendor CLIs in git worktrees: Orchestrator.inc agent-orchestrator (13.2k stars), Superset, Emdash, Vibe Kanban (company shut down 2026-04-10), Claude Squad and Manaflow.
4. Verification-first multi-engine runtimes, most notably Enderfga/claw-orchestrator. Its tagline is "a run only counts as done when checks it didn't write pass", which overlaps Contexer's thesis almost exactly.

None of these exposes a verification-and-evidence layer that Contexer could simply adopt. Their architectures do validate Contexer's design choices: harness-neutral event seams, browser verification, PRs opened as the user, and checks the agent cannot edit.

### Cited Findings

#### LangChain Open SWE
- **langchain-ai/open-swe**: https://github.com/langchain-ai/open-swe. 11,016 stars, MIT, Python, pushed 2026-10-14. Latest `desktop-v0.3.7`, 2026-10-13. Backed by LangChain. — [GitHub API](https://github.com/langchain-ai/open-swe)
- Describes itself as "An open-source software factory built on Deep Agents". It investigates, implements "in an isolated sandbox", validates, delivers a PR, reviews PRs, monitors CI (`/baby-sit`, "rerunning only evidence-backed flaky jobs"), and takes triggers from the dashboard, GitHub issues and PRs, Slack and Linear. — [Open SWE README](https://github.com/langchain-ai/open-swe)
- **Architecture**: Deep Agents provides planning, filesystem, shell, skills and subagents. LangGraph provides durable execution and thread state. Coding runs in "persistent, per-thread Linux sandboxes", with LangSmith as the default sandbox and tracing provider. — [Open SWE README](https://github.com/langchain-ai/open-swe)
- **Caveats**: "Under active development. Expect breaking changes… We're not accepting issues or external contributions". "Production standalone Agent Server deployments require a license key." — [Open SWE README](https://github.com/langchain-ai/open-swe)
- The underlying langchain-ai/deepagents has 30,256 stars and is MIT-licensed. — [GitHub API](https://github.com/langchain-ai/deepagents)

#### Open-Inspect (ColeMurray/background-agents), modelled on Ramp Inspect
- **ColeMurray/background-agents**: https://github.com/ColeMurray/background-agents. 3,358 stars, MIT, TypeScript. User-owned (individual maintainer). Created 2026-01-25, pushed 2026-10-14. — [GitHub API](https://github.com/ColeMurray/background-agents)
- **Architecture**: a control plane on Cloudflare Workers with one Durable Object per session (SQLite, WebSocket hub, event stream, GitHub integration) and D1 for repo-scoped secrets. The data plane is a sandbox (Modal, Daytona, E2B or OpenComputer) running Supervisor → Harness (OpenCode or Claude) → Bridge. Clients are web, Slack, GitHub, Linear and webhooks. Deployment is single-tenant only. — [Open-Inspect README](https://github.com/ColeMurray/background-agents)
- **Harness seam**: "OpenCode (built-in)… runs as a server inside the sandbox; the supervisor owns the `opencode serve` process and the bridge talks to it over HTTP/SSE". The "Claude Agent" harness runs the Claude Agent SDK, which spawns `claude` with one credential and "can use a connected Claude subscription". "Both harnesses emit the same session events (tokens, tool calls, steps, warnings)… The bridge owns turn completion… emits the single `execution_complete` event." — [HOW_IT_WORKS.md](https://github.com/ColeMurray/background-agents/blob/main/docs/HOW_IT_WORKS.md)
- **Verification**: a "Visual verification" capability "Use[s] Playwright to check UI changes", and the sandbox includes "agent-browser CLI + headless Chrome". Screenshots are stored as artifacts (`artifact_created`). The PR is created with the user's GitHub OAuth token, so it "appears as created by you, not a bot". — [HOW_IT_WORKS.md](https://github.com/ColeMurray/background-agents/blob/main/docs/HOW_IT_WORKS.md)
- **Ramp Inspect itself**:
  - Architecture: Modal sandboxes with images prebuilt every 30 minutes, OpenCode harness, Cloudflare Durable Objects.
  - Verification: runs tests, reviews telemetry (Sentry, Datadog, LaunchDarkly), checks frontend changes visually with screenshots and live previews.
  - PRs are opened with the user's token. Claimed adoption: "~30% of all pull requests merged to our frontend and backend repos are written by Inspect" (vendor claim).
  — [Ramp builders blog](https://builders.ramp.com/post/why-we-built-our-background-agent)

#### OpenHands and the OpenHands Software Agent SDK
- **OpenHands/OpenHands**: https://github.com/OpenHands/OpenHands. 90,882 stars, MIT, pushed 2026-10-14. Backed by All Hands AI. — [GitHub API](https://github.com/OpenHands/OpenHands)
- **OpenHands/software-agent-sdk**: https://github.com/OpenHands/software-agent-sdk. 1,254 stars, MIT, Python, pushed 2026-10-14. Latest v1.54.0, 2026-10-09. PyPI `openhands-sdk` 1.54.0 requires **Python ≥3.12**. — [GitHub API](https://github.com/OpenHands/software-agent-sdk); [PyPI](https://pypi.org/project/openhands-sdk/)
- The SDK provides "Python, TypeScript, and REST APIs" and is "the engine behind the OpenHands CLI and OpenHands Cloud". Packages: `openhands-sdk`, `openhands-tools`, `openhands-workspace` (Docker and remote), and `openhands-agent-server` (FastAPI, REST and WebSocket, with OpenAI-compatible `/v1/chat/completions` and `/v1/responses`). — [SDK README](https://github.com/OpenHands/software-agent-sdk); [Architecture docs](https://docs.openhands.dev/sdk/arch/overview)
- **`ACPAgent`** uses "an ACP-compatible server (claude-agent-acp) as the agent backend instead of direct LLM calls". Example: `ACPAgent(acp_command=list(ACP_PROVIDERS["claude-code"].default_command))`. — [40_acp_agent_example.py](https://github.com/OpenHands/software-agent-sdk/blob/main/examples/01_standalone_sdk/40_acp_agent_example.py)
- **Experimental critic**: "a critic model to shepherd an agent… provides feedback that can trigger follow-up prompts when the agent hasn't completed the task successfully". It uses `IterativeRefinementConfig` and custom `CriticBase` subclasses. — [34_critic_example.py](https://github.com/OpenHands/software-agent-sdk/blob/main/examples/01_standalone_sdk/34_critic_example.py)
- The SDK repo contains a hooks system (`examples/01_standalone_sdk/33_hooks` with `require_summary.sh` and `block_dangerous.sh`; `.openhands/hooks/on_stop.sh`). — [OpenHands SDK repo tree](https://github.com/OpenHands/software-agent-sdk/tree/main/examples/01_standalone_sdk/33_hooks)

#### SWE-agent, mini-swe-agent and Agentless
- **SWE-agent/SWE-agent**: https://github.com/SWE-agent/SWE-agent. 20,552 stars, MIT, Python, pushed 2026-10-12. Princeton and Stanford, NeurIPS 2024. — [GitHub API](https://github.com/SWE-agent/SWE-agent)
- **SWE-agent/mini-swe-agent**: https://github.com/SWE-agent/mini-swe-agent. 8,514 stars, MIT, Python, pushed 2026-10-12. PyPI 2.4.6. The agent class is "just some 100 lines of python". It uses no tools other than bash, keeps a "completely linear history", runs actions with `subprocess.run`, and supports local, docker/podman, singularity and bubblewrap environments. It claims ">74% on SWE-bench verified" (vendor claim). The README says "You should consider `mini-swe-agent` your default choice" over SWE-agent and that it "now powers Ramp SWE-Bench". — [mini-swe-agent README](https://github.com/SWE-agent/mini-swe-agent)
- **OpenAutoCoder/Agentless**: https://github.com/OpenAutoCoder/Agentless. 2,124 stars, MIT, Python. **Last push 2024-12-22.** It runs three phases: localization, repair, and patch validation. In validation it "selects the regression tests to run and generates additional reproduction test to reproduce the original error… re-ranks all remaining patches". — [Agentless README](https://github.com/OpenAutoCoder/Agentless)

#### PR-Agent
- **qodo-ai/pr-agent → The-PR-Agent/pr-agent**: https://github.com/The-PR-Agent/pr-agent. 13,386 stars, MIT, Python, pushed 2026-10-14. It is now "a community-maintained legacy project of Qodo… distinct from Qodo's primary AI code review offering". It runs as a GitHub Action (`the-pr-agent/pr-agent@main`) or CLI (`pip install "pr-agent[github]"`). Docker images moved to `pragent/pr-agent` from release 0.34.2. — [PR-Agent README](https://github.com/The-PR-Agent/pr-agent)

#### Vibe Kanban and Claude Squad
- **BloopAI/vibe-kanban**: https://github.com/BloopAI/vibe-kanban. 28,364 stars, Apache-2.0, Rust, last push 2026-09-19. The README banner reads "Vibe Kanban is sunsetting". Features: kanban issues; workspaces giving each agent "a branch, a terminal, and a dev server"; diff review with inline comments; a built-in browser preview; 10+ agents (Claude Code, Codex, Gemini CLI, Copilot, Amp, Cursor, OpenCode, Droid, CCR, Qwen Code); PR creation. — [Vibe Kanban README](https://github.com/BloopAI/vibe-kanban)
- Bloop announced its shutdown on 2026-04-10. The project continues "open source and community maintained". Hosted services were kept for 30 days and then moved to a fully local architecture. — [Vibe Kanban shutdown post](https://vibekanban.com/blog/shutdown)
- **smtg-ai/claude-squad**: https://github.com/smtg-ai/claude-squad. 8,600 stars, **AGPL-3.0**, Go, pushed 2026-08-20. A terminal app built on tmux plus git worktrees that manages Claude Code, Codex, Gemini, Aider and others. `-y/--autoyes` is experimental. It needs tmux and gh. There is no API: the program to run is just a string (`-p "codex"`). — [Claude Squad README](https://github.com/smtg-ai/claude-squad)

#### 2026 orchestrators with traction (metadata 2026-10-14)
- **OrchestratorInc/agent-orchestrator** (ComposioHQ/agent-orchestrator redirects here): https://github.com/OrchestratorInc/agent-orchestrator. 13,162 stars, Apache-2.0, Go. Created 2026-02-13, pushed 2026-10-14, v0.14.0 the same day. It is a desktop app plus local daemon. Each "worker" gets one task, one agent, and its own branch and worktree. A "project orchestrator" plans and delegates. A live Kanban is derived from "session, pull request, CI, and review facts". It includes an "agent-controllable browser" with per-worker isolated profiles and claims 30+ harnesses (Claude Code, Codex, Cursor, opencode, Aider, Copilot, Goose, Gemini CLI…). — [agent-orchestrator README](https://github.com/OrchestratorInc/agent-orchestrator)
- **Enderfga/claw-orchestrator**: https://github.com/Enderfga/claw-orchestrator. 591 stars, MIT, TypeScript. Created 2026-01-30, pushed 2026-10-11, v7.11.0. Features:
  - "Acceptance contracts — commands, HTTP probes, screenshots, diff policy, file assertions — that the runtime runs itself. A run with a contract ends `verified`, `refuted` or `unverified`, never 'the agent said so'. Editing the tests a contract runs refutes the run."
  - Persistent sessions for Claude Code, Codex, Antigravity, Grok Build, OpenCode and custom CLIs.
  - A durable checkpointed run kernel, a per-turn JSONL cost ledger, and `maxBudgetUsd`.
  - An MCP server (`clawo-mcp`), an ACP agent (`clawo acp`), an OpenAI-compatible endpoint, and a TS SDK.
  - Requires Node 22+.
  - Engines tested: `claude` 2.1.296, `codex` 0.162.1, `opencode` 1.19.0.
  — [claw-orchestrator README](https://github.com/Enderfga/claw-orchestrator)
- **generalaction/emdash**: https://github.com/generalaction/emdash. 5,983 stars, Apache-2.0, TypeScript, YC W26, pushed 2026-10-14. A desktop app that runs agents in parallel worktrees, locally or over SSH, and pulls tickets from Linear, GitHub, Jira and others. "For agents with lifecycle-hook support, Emdash installs marker-tagged entries in the agent's user-level config. These hooks let Emdash track status, notifications, and resumable sessions". — [Emdash README](https://github.com/generalaction/emdash)
- **superset-sh/superset**: https://github.com/superset-sh/superset. 15,184 stars, license NOASSERTION, TypeScript. Created 2025-10-21, pushed 2026-10-14. A desktop agentic IDE with worktrees, a diff viewer, an in-app browser with per-workspace port detection, a "Design" mode that sends element context to agents, and PR feedback routed back to agents. macOS first; no Windows build. — [Superset README](https://github.com/superset-sh/superset)
- **manaflow-ai/manaflow**: https://github.com/manaflow-ai/manaflow. 1,115 stars, MIT. Formerly cmux, per commented install lines. Spawns agent CLIs in isolated VS Code workspaces in the cloud or local Docker, with live web preview, PR creation and CI status. — [Manaflow README](https://github.com/manaflow-ai/manaflow)
- **coder/agentapi**: https://github.com/coder/agentapi. 1,496 stars, MIT, Go, **archived**. "AgentAPI is deprecated and no longer maintained." It wrapped agent TUIs behind 4 HTTP endpoints (`/messages`, `/message`, `/status` stable/running, `/events` SSE). — [AgentAPI README](https://github.com/coder/agentapi)
- **coder/xum** (renamed from Mux): https://github.com/coder/xum. 2,054 stars, AGPL-3.0. "Xum has a custom agent loop". — [Xum README](https://github.com/coder/xum)
- **Others found (metadata only, READMEs not reviewed in depth)**:
  - QoderAI/better-harness: 2,376 stars, MIT, created 2026-07-21. Analyses agent work-loop evidence into "prioritized findings with… acceptance checks". — [better-harness README](https://github.com/QoderAI/better-harness)
  - ruvnet/ruflo (formerly claude-flow): 74,641 stars, MIT. — [GitHub API](https://github.com/ruvnet/ruflo)
  - stravu/crystal: 3,129 stars, "now Nimbalyst", last push 2026-02-26. — [GitHub API](https://github.com/stravu/crystal)
  - kbwo/ccmanager: 1,262 stars. — [GitHub API](https://github.com/kbwo/ccmanager)
  - humanlayer/humanlayer: 11,693 stars, last push 2026-06-19. — [GitHub API](https://github.com/humanlayer/humanlayer)
  - ishaan1013/shadow: 1,499 stars, last push 2026-03-19. — [GitHub API](https://github.com/ishaan1013/shadow)
  - rivet-dev/agents (sandbox-agent redirects here): 1,606 stars. — [GitHub API](https://github.com/rivet-dev/agents)

### Inferences
- **Open SWE: BORROW IDEAS, AVOID building on.** It owns exactly what Contexer must not build: the harness (Deep Agents), the sandbox fleet (LangSmith), and the dashboard and Slack UI. It refuses external contributions and needs a license key for production Agent Server deployments. Worth borrowing: `/baby-sit` (CI monitoring that reruns only evidence-backed flaky jobs) and per-thread persistent sandboxes reused across follow-ups.
- **Open-Inspect / Ramp Inspect: BORROW IDEAS (strongly), AVOID building on.** Ideas to take:
  - A "harness seam" where OpenCode and the Claude Agent SDK emit the same normalised events and the bridge owns a single `execution_complete`. This is the internal adapter interface Contexer needs.
  - Playwright visual verification as a first-class capability, with screenshots stored as artifacts.
  - PRs opened with the user's own token, so authors cannot self-approve.
  It is a hosted, single-tenant Cloudflare+Modal fleet, which is exactly what Contexer avoids. Its "connected Claude subscription" harness conflicts with the policy language in Q1.
- **OpenHands SDK: BORROW IDEAS; optional future backend.** `ACPAgent` plus the critic and `IterativeRefinementConfig` is structurally what Contexer does, with an "ACP agent under a critic" pattern. But it brings its own agent runtime, server and event model, and requires Python ≥3.12 (Contexer supports 3.11). Adopting it would invert the architecture, making Contexer a plugin of OpenHands. Borrow the critic and refinement API shape and the hooks design. Support OpenHands as an engine through ACP (it is on the ACP agents list) rather than as a framework.
- **SWE-agent and mini-swe-agent: BORROW IDEAS / use for evaluation, not as a backend.** mini is a good cheap, deterministic baseline engine for Contexer's own test suite and benchmarks, and its linear trajectory format is a good evidence-log model. Contexer's product promise is "use the agent you already pay for", so these are not production engines.
- **Agentless: AVOID (dormant since 2024-12), BORROW ONE IDEA.** Generating a reproduction test that fails before the fix and passes after it, and using regression plus reproduction results to re-rank candidate patches, is directly applicable to Contexer's check compilation and best-of-N repair.
- **PR-Agent: BORROW IDEAS, AVOID.** It is a review bot, now community "legacy". Worth borrowing: its GitHub Action packaging and multi-git-provider reporting. It does not execute or verify behaviour.
- **Vibe Kanban, Claude Squad, Emdash, Superset, Manaflow, Xum, Orchestrator.inc: AVOID as dependencies.** They are the "orchestration UI" layer Contexer has ruled out. Claude Squad and Xum are AGPL. Vibe Kanban's company is gone. AgentAPI shows that terminal-scraping HTTP wrappers lost out to native protocols.
  - **Treat them as distribution surfaces.** Each launches Claude Code or Codex in worktrees and shows PR and CI state, so a Contexer GitHub status check or a Contexer MCP/CLI verify step would surface in all of them for free.
  - **Borrow Emdash's mechanism**: install marker-tagged hook entries in the agent's own config to observe status.
- **claw-orchestrator: the most important competitive signal.** It already ships "acceptance contracts the runtime runs itself", `verified`/`refuted`/`unverified` verdicts, "editing the tests a contract runs refutes the run", multi-engine sessions, cost caps, and MCP and ACP faces. It is small (591 stars), Node-based and single-maintainer. Contexer's differentiation has to be:
  - user-approved, UI-grounded checks compiled from a ticket
  - real-browser behavioural proof
  - replay of saved checks on later changes
  - a GitHub status check plus evidence report
  - Python-native distribution
  Borrow its verdict vocabulary and its "contract files are tamper-evident" rule.

### Gaps
- I did not measure Orchestrator.inc's API or daemon surface (`docs/cli/README.md`, `docs/architecture.md`). Whether it exposes a programmatic hook for external verifiers is unknown.
- No source found for actual production usage numbers of Open SWE, Open-Inspect or claw-orchestrator beyond stars.
- Vibe Kanban's community-edition roadmap after the shutdown was not found.
- ruvnet/ruflo's architecture was not reviewed. Its very high star count (74.6k) was not validated against real usage.

---

## Key question 5: Can one protocol drive many agents? (Agent Client Protocol, MCP, A2A, AGENTS.md)

### Takeaway
ACP is the only protocol in this list designed for a client to drive a coding agent's turn. Its features:
- a `session/prompt` turn that returns a `stopReason`
- streamed `session/update` notifications: `tool_call` (with kind, status, `diff` content and file `locations`), `plan`, `usage_update` and others
- a `session/request_permission` round-trip
- client-provided `fs/*` and `terminal/*`

As of 2026-10, 43 agents are listed. They include Claude Agent (via `claude-agent-acp`), Codex (via `codex-acp`, which drives the Codex app-server), Gemini CLI, OpenCode, Goose, Copilot, Cursor, Cline, Kiro and OpenHands. A Python SDK exists (`agent-client-protocol` 0.12.1, Python ≥3.10).

So yes: one ACP client adapter would let Contexer drive several agents. The trade-off is that ACP is editor-oriented and adapter-mediated. Vendor-specific signals such as USD cost, schema-validated final output, native hooks and session forking are absent or carried only in `_meta` extensions. MCP is the right way to expose Contexer's checks to agents. A2A is not relevant to local coding-agent CLIs today. AGENTS.md is the shared instruction channel; even Claude Code now reads it natively.

### Cited Findings

#### ACP
- **agentclientprotocol/agent-client-protocol** (zed-industries/agent-client-protocol redirects here): https://github.com/agentclientprotocol/agent-client-protocol. 4,441 stars, Apache-2.0, Rust, pushed 2026-10-14. Latest release `schema-v1.25.0`, 2026-10-09. The Python SDK's `PROTOCOL_VERSION = 1`. — [GitHub API](https://github.com/agentclientprotocol/agent-client-protocol); [python-sdk meta.py](https://github.com/agentclientprotocol/python-sdk/blob/main/src/acp/meta.py)
- **Purpose**: ACP "standardizes communication between code editors/IDEs and coding agents", like LSP. Agents run as subprocesses over JSON-RPC on stdio. Remote operation over HTTP/WebSocket is "a work in progress". It "reuses MCP's JSON representations where possible". The design "assumes the user is primarily in their editor". — [ACP introduction](https://agentclientprotocol.com/overview/introduction)
- **Prompt turn**: `session/prompt` responds with a `stopReason` of `end_turn`, `max_tokens`, `max_turn_requests`, `refusal` or `cancelled`. `session/update` variants: `user_message_chunk`, `agent_message_chunk`, `agent_thought_chunk`, `tool_call`, `tool_call_update`, `plan`, `available_commands_update`, `current_mode_update`, `config_option_update`, `session_info_update`, `usage_update`, `notice`, `compaction_update`. `session/cancel` is a notification. — [ACP prompt turn](https://agentclientprotocol.com/protocol/prompt-turn)
- **Tool calls**:
  - `ToolKind`: `read`, `edit`, `delete`, `move`, `search`, `execute`, `think`, `fetch`, `switch_mode`, `other`
  - Status: `pending`, `in_progress`, `completed`, `failed`
  - Content types: `content`, `diff` (`path`, `oldText`, `newText`) and `terminal`
  - `locations`: `{path, line?}`
  - `session/request_permission` options are `allow_once`, `allow_always`, `reject_once` and `reject_always`; the outcome is `selected` or `cancelled`
  — [ACP tool calls](https://agentclientprotocol.com/protocol/tool-calls)
- **Agents list (43)**:
  - Via adapter: Claude Agent (`claude-agent-acp`), Codex CLI (`codex-acp`), Pi, Bub.
  - Listed without an adapter label: Augment Code, Cline, Cursor, Docker cagent, Factory Droid, Gemini CLI, GitHub Copilot (public preview, 2026-01-28 changelog), Goose, Hermes Agent, Junie, Kimi CLI, Kiro CLI, Mistral Vibe, OpenCode, OpenHands, Qoder CLI, Qwen Code, Claw Orchestrator, and others.
  — [ACP agents list](https://agentclientprotocol.com/overview/agents)
- **agentclientprotocol/claude-agent-acp**: https://github.com/agentclientprotocol/claude-agent-acp. 2,646 stars, Apache-2.0, pushed 2026-10-14. npm 0.90.0. It is "an ACP agent by using the official Claude Agent SDK". It supports tool calls with permission requests, edit review, TODO lists, nested subagent transcripts as child sessions, background terminals, slash commands and client MCP servers. Several features are JetBrains-"AIR" `_meta` extensions. — [claude-agent-acp README](https://github.com/agentclientprotocol/claude-agent-acp)
- **agentclientprotocol/codex-acp**: https://github.com/agentclientprotocol/codex-acp. 455 stars, license NOASSERTION, created 2025-12-03, npm 2.2.2. The older zed-industries/codex-acp (871 stars) was last pushed 2026-07-22. codex-acp "starts the Codex App Server, translates ACP requests into Codex operations, and maps Codex events back". It supports ChatGPT, API-key and custom-gateway auth, and shell, file change, permission, MCP, plan, token usage and review events. — [codex-acp README](https://github.com/agentclientprotocol/codex-acp); [GitHub API](https://github.com/zed-industries/codex-acp)
- **ACP Python SDK**: https://github.com/agentclientprotocol/python-sdk. 335 stars, Apache-2.0. PyPI `agent-client-protocol` 0.12.1, `requires_python <3.15,>=3.10`. It exports `Agent`, `Client`, `connect_to_agent`, `run_agent`, `ClientSideConnection` and Pydantic schema models such as `ToolCallStart`, `ToolCallProgress`, `AgentPlanUpdate`, `UsageUpdate` and `RequestPermissionResponse`. Examples include `client.py`, `duet.py`, `gemini.py`, `http_client.py` and `ws_client.py`. — [python-sdk repo](https://github.com/agentclientprotocol/python-sdk); [examples/client.py](https://github.com/agentclientprotocol/python-sdk/blob/main/examples/client.py); [PyPI](https://pypi.org/project/agent-client-protocol/)
- **ACP used for orchestration as well as editors**: OpenHands' `ACPAgent` drives `claude-agent-acp` as a backend. Goose uses ACP to reach "existing Claude, ChatGPT, or Gemini subscriptions". claw-orchestrator exposes `clawo acp`. — [OpenHands ACP example](https://github.com/OpenHands/software-agent-sdk/blob/main/examples/01_standalone_sdk/40_acp_agent_example.py); [goose README](https://github.com/aaif-goose/goose); [claw-orchestrator README](https://github.com/Enderfga/claw-orchestrator)

#### MCP, A2A, AGENTS.md
- **MCP**: the spec repo modelcontextprotocol/modelcontextprotocol has 9,449 stars; its latest release is tagged `2026-07-28`. MCP was contributed to AAIF at the Linux Foundation on 2025-12-09. — [GitHub API/releases](https://github.com/modelcontextprotocol/modelcontextprotocol/releases); [Linux Foundation](https://www.linuxfoundation.org/press/linux-foundation-announces-the-formation-of-the-agentic-ai-foundation)
- The Claude Agent SDK can host in-process MCP tools (`create_sdk_mcp_server`). Codex hooks match MCP tools (`mcp__server__tool`). Both Claude Code and OpenCode accept MCP configs. — [Python SDK reference](https://code.claude.com/docs/en/agent-sdk/python); [Codex hooks](https://learn.chatgpt.com/docs/hooks)
- **A2A**: a2aproject/A2A has 26,144 stars, Apache-2.0. Latest v1.0.1, 2026-05-28. It is a Linux Foundation project contributed by Google: "communication and interoperability between opaque agentic applications". It uses Agent Cards, JSON-RPC 2.0 over HTTP(S), SSE streaming and push notifications. SDKs exist for Python, Go, JS, Java, .NET and Rust. The README does not mention coding agents. — [A2A repo](https://github.com/a2aproject/A2A)
- **AGENTS.md**: agentsmd/agents.md (formerly openai/agents.md) has 24,919 stars, MIT, last push 2026-09-10. "used by over 60k open-source projects" (vendor claim). Supporters include Codex, Jules, Factory, Aider, goose, opencode, Zed, Warp, VS Code, Devin, Junie, Amp, Cursor, Gemini CLI, the GitHub Copilot coding agent and Windsurf. Stewarded by AAIF. The nearest file wins. If it lists test commands, "the agent will attempt to run relevant programmatic checks and fix failures before finishing". — [agents.md](https://agents.md/); [GitHub API](https://github.com/agentsmd/agents.md)
- **Claude Code reads AGENTS.md** "as your project instructions… without adding a `CLAUDE.md`" when no CLAUDE.md exists. If a CLAUDE.md exists, it reads only CLAUDE.md unless that file imports AGENTS.md. This requires v2.1.277+. — [Claude Code memory docs](https://code.claude.com/docs/en/memory)

### Inferences
- **ACP: BUILD ON as Contexer's long-tail adapter**, with one Python ACP client using the `agent-client-protocol` package. The minimal set of adapters is:
  1. native Claude (Agent SDK)
  2. native Codex (Python SDK or `exec --json`)
  3. native OpenCode (HTTP/SSE)
  4. generic ACP, covering Gemini CLI, Goose, Copilot CLI, Cursor, Kiro, Cline, OpenHands, Qwen, and Claude or Codex as a cross-check
- **Why not ACP-only**:
  - **Cost**: ACP exposes `usage_update` but not USD cost. Claude's `total_cost_usd` / `max_budget_usd` and Codex token usage are richer natively.
  - **Structured output**: ACP has no `--json-schema` / `outputSchema` equivalent, and Contexer's goal-to-check compilation relies on schema-validated output.
  - **Hooks**: Stop and PreToolUse gates are configured per vendor, outside ACP.
  - **Coupling**: the Claude and Codex ACP servers are adapters over the same SDK and app-server, so ACP adds a moving part. Recent features arrive as vendor-specific `_meta` "AIR extensions" (JetBrains).
  - **Editor assumptions**: if Contexer advertises `fs`/`terminal` client capabilities, it becomes responsible for implementing file I/O and terminals. It must either implement them faithfully, writing to the real workspace, or not advertise them so the agent uses its own tools.
- **ACP as an outbound face (BORROW from claw-orchestrator)**: Contexer could later expose `contexer acp`, so Zed, JetBrains or any ACP client can run "implement-and-verify" as if Contexer were an agent. This is low priority.
- **MCP: BUILD ON in the "Contexer as a tool" direction.** A `contexer-mcp` server would expose `list_checks`, `run_checks(check_ids)` (returning pass/fail plus evidence paths) and `get_failure_evidence`. Any agent (Claude, Codex, OpenCode, Goose, Cursor) can then call verification mid-loop. For Claude, the same tools can run in-process through `create_sdk_mcp_server`, with no extra process.
- **A2A: AVOID for now.** It targets opaque remote agents exchanging tasks and artifacts over HTTP. No local coding CLI in scope speaks it, so it adds nothing over ACP and MCP for Contexer's loop. Revisit only if Contexer has to accept work from enterprise agent meshes.
- **AGENTS.md: BUILD ON.** Contexer should write or append a managed section to AGENTS.md with how to start the app, where the approved checks live, "do not edit `.contexer/checks/**`", and the command to self-verify. That one file now reaches Codex, OpenCode, Gemini, goose, Copilot and, when no CLAUDE.md exists, Claude Code. For repos with a CLAUDE.md, add an `@AGENTS.md` import.

### Gaps
- No published comparison of what each ACP adapter drops relative to native APIs. The cost, structured-output and hook gaps above are inferred from reading the specs, not from tests.
- ACP remote transport (HTTP/WebSocket) remains a work in progress. The Python SDK includes `http_client.py` and `ws_client.py` examples, but their stability was not assessed.
- Whether Copilot, Cursor and Kiro implement ACP natively or through adapters is not stated on the ACP agents page.
- Whether `claude-agent-acp` used under a subscription login is acceptable under Anthropic's terms is unclear: it is built on the Agent SDK, which the terms steer to API keys.

---

## Key question 6: Which agents expose a structured event stream (tool calls, file edits, final status) that a supervisor can consume?

### Takeaway
Claude Code (stream-json and the SDK), Codex (`exec --json`, SDK and app-server), OpenCode (SSE `/event` plus `/session/:id/diff`), Gemini CLI (stream-json), Goose (stream-json), OpenHands (agent-server WebSocket) and every ACP agent (`session/update`) expose machine-readable streams. Aider does not. Claude Code and Codex are the only ones with documented, typed final-status records that a supervisor can trust: Claude's `result` message with `subtype`, `is_error`, `total_cost_usd` and `permission_denials`, and Codex's `turn.completed`/`turn.failed` with usage. Neither stream is proof of correctness, which is Contexer's whole point. Both supply the provenance a Contexer evidence report needs: what files changed, what commands ran, and why the run ended.

### Cited Findings
| Agent / surface | Transport | Tool calls | File edits | Final status / cost | Schema-validated final output | Resume |
|---|---|---|---|---|---|---|
| Claude Code `claude -p --output-format stream-json` / Agent SDK | NDJSON on stdout, or Python async iterator | `assistant` `tool_use` + `user` `tool_result` blocks; subagents tagged by `parent_tool_use_id` | Edit/Write tool_use inputs; `FileChanged` hook; SDK `rewind_files` | `result` msg: `subtype`, `is_error`, `total_cost_usd`, `session_id`, `permission_denials`, `terminal_reason` | `--json-schema` → `structured_output` | `--resume <id>` / `resume`, `fork_session` |
| Codex `exec --json` / SDK | JSONL (exec); JSON-RPC to app-server (Python SDK) | `item.*` with `command_execution`, `mcp_tool_call`, `web_search` | `file_change` items (patch-apply status) | `turn.completed` (token usage) / `turn.failed` / `error` | `--output-schema` / `outputSchema` | `codex exec resume <id>` / `resumeThread` |
| OpenCode server | HTTP + SSE (`/event`, `/global/event`) | events have `type` + `properties` (types undocumented on SDK page) | `GET /session/:id/diff` | message response, abort endpoint | `format: json_schema` (StructuredOutput tool, retries) | session IDs, `--session`, `--fork` |
| Gemini CLI headless | JSONL | `tool_use`, `tool_result` | (via tool events) | `result` with stats; exit codes 0/1/42/53 | not documented on page | not documented on page |
| Goose `goose run` | json / stream-json | not detailed on page | not detailed | not detailed | not documented | `-r` resume |
| ACP (any listed agent) | JSON-RPC stdio | `tool_call` / `tool_call_update` with `kind`, `status` | `diff` content (`path`, `oldText`, `newText`), `locations` | `stopReason` (`end_turn`, `max_tokens`, `max_turn_requests`, `refusal`, `cancelled`); `usage_update` | none in core protocol | `session/load` |
| OpenHands Agent Server | REST + WebSocket | typed action/observation events | via file-editor tool events | conversation execution status | n/a | conversations persisted |
| Aider | none | — | git commits | process exit | — | — |
| AgentAPI (archived) | SSE | message/status only (terminal-scraped) | — | `stable`/`running` | — | — |

Sources:
- Claude Code: [Headless docs](https://code.claude.com/docs/en/headless); [Python SDK reference](https://code.claude.com/docs/en/agent-sdk/python); [Hooks reference](https://code.claude.com/docs/en/hooks)
- Codex: [Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode); [items.ts](https://github.com/openai/codex/blob/main/sdk/typescript/src/items.ts); [events.ts](https://github.com/openai/codex/blob/main/sdk/typescript/src/events.ts); [App server docs](https://learn.chatgpt.com/docs/app-server)
- OpenCode: [server docs](https://opencode.ai/docs/server/); [SDK docs](https://opencode.ai/docs/sdk/); [CLI docs](https://opencode.ai/docs/cli/)
- Gemini CLI: [headless docs](https://geminicli.com/docs/cli/headless/)
- Goose: [running tasks docs](https://goose-docs.ai/docs/guides/running-tasks)
- ACP: [prompt turn](https://agentclientprotocol.com/protocol/prompt-turn); [tool calls](https://agentclientprotocol.com/protocol/tool-calls)
- OpenHands: [Architecture docs](https://docs.openhands.dev/sdk/arch/overview)
- Aider: [scripting docs](https://aider.chat/docs/scripting.html)
- AgentAPI: [README](https://github.com/coder/agentapi)

### Inferences

#### Event model
- Contexer should define one internal `AgentEvent` model with `run_started`, `message`, `tool_call{kind, name, input, status}`, `file_change{path, diff?}`, `command{cmd, exit_code}`, `usage{tokens, usd?}` and `run_finished{reason, is_error, session_id}`.
- Write one mapper per native surface (Claude SDK, Codex SDK or exec, OpenCode SSE) plus one for ACP. ACP's `ToolKind` enum (`read`, `edit`, `execute`, …) is a good neutral vocabulary to adopt internally.
- Never treat an agent's `success` or `end_turn` as a pass. The verdict always comes from Contexer's own browser and command checks, as claw-orchestrator's "never 'the agent said so'" rule also argues. Record the agent's self-report and Contexer's verdict separately, as claw-orchestrator's ledger does (`ok` vs `verified`).
- Always compute the authoritative diff with `git diff` against Contexer's checkpoint, not from agent events. Event coverage of edits varies: Bash-based edits appear as commands, not file changes.

#### Consolidated verdict matrix (Contexer, as of 2026-10-14)
| Candidate | Verdict | One-line reason |
|---|---|---|
| Claude Code CLI + `claude-agent-sdk` (Python) | **BUILD ON** (adapter #1) | Richest typed stream, structured output, budget caps, Stop/PreToolUse gates; API-key auth for product use |
| Claude Code hooks (Stop, PreToolUse) | **BUILD ON** (inner gate) | Force continuation on failing checks and protect check files; outer loop stays authoritative (8-block cap, timeout lets Claude stop) |
| anthropics/claude-code-action | **BORROW IDEAS** / optional companion | Triggers, branches, OIDC auth; no Check Run output, so Contexer's status check is additive |
| Codex Python SDK (`openai-codex`) / `codex exec --json` | **BUILD ON** (adapter #2) | Python-native, typed thread/turn/item events, output schemas, resume; app-server is the substrate |
| Codex app-server (direct) | **AVOID for now** | OpenAI steers automation to the SDK; WebSocket and many methods experimental |
| openai/codex-action | **BORROW IDEAS** | Safety strategies, API-key proxy, user/bot gating; no PR creation |
| Codex hooks | **BUILD ON (best-effort)** | Same Stop/PreToolUse model as Claude; trust gating; "not a complete enforcement boundary" |
| OpenCode server/SDK | **BUILD ON** (adapter #3, already in use) | OpenAPI HTTP + SSE, diff endpoint, JSON-schema output, `opencode acp`; Python SDK stale, so use httpx; no Claude subscriptions |
| Gemini CLI | **BORROW IDEAS / via ACP only** | Good headless contract, but consumer users moved to Antigravity CLI (2026-06-18) |
| Goose | **AVOID as primary; via ACP** | General-purpose agent; recipes worth studying; AAIF-governed |
| Aider | **AVOID** | No event stream, unsupported Python API, last push 2026-05-22 |
| ACP (+ `agent-client-protocol` Python SDK) | **BUILD ON** (long-tail adapter) | One adapter reaches about 40 agents; lacks cost, structured output and hooks, so keep native adapters for the top 3 |
| MCP | **BUILD ON** (expose Contexer checks as tools) | Every target agent consumes MCP; Claude SDK can host tools in-process |
| A2A | **AVOID** | Remote opaque-agent interop; no coding CLI speaks it |
| AGENTS.md | **BUILD ON** | Single instruction channel read by Codex, OpenCode, Gemini, goose, Copilot and Claude Code (v2.1.277+) |
| Open SWE | **BORROW IDEAS** | Full platform (LangGraph, LangSmith sandboxes, license key); no external contributions |
| Open-Inspect / Ramp Inspect | **BORROW IDEAS** | Harness seam with normalised events, Playwright visual verification, PRs as user; hosted single-tenant fleet |
| OpenHands SDK / OpenHands | **BORROW IDEAS** (engine via ACP) | ACPAgent + critic matches Contexer's shape, but it is its own runtime and needs Python ≥3.12 |
| SWE-agent / mini-swe-agent | **BORROW IDEAS** (eval baseline) | Linear trajectories, cheap deterministic baseline for Contexer's own benchmarks |
| Agentless | **AVOID** (borrow reproduction-test idea) | Dormant since 2024-12; reproduction-test patch validation is relevant |
| PR-Agent | **BORROW IDEAS** | Review-only, community legacy; GitHub Action and report packaging |
| Vibe Kanban | **AVOID** | Company shut down 2026-04-10; it is the orchestration UI Contexer avoids |
| Claude Squad | **AVOID** | AGPL tmux TUI, no API |
| Orchestrator.inc agent-orchestrator, Superset, Emdash, Manaflow, Xum | **AVOID as dependency; partner surface** | Orchestration UIs; Contexer's status check and MCP verify can plug into their PR/CI views; borrow Emdash's hook-based status tracking |
| claw-orchestrator | **BORROW IDEAS; treat as nearest competitor** | Already ships runtime-run acceptance contracts, verified/refuted verdicts, tamper rule, multi-engine, ACP/MCP |
| coder/agentapi | **AVOID** | Archived and deprecated; terminal-scraping approach superseded |

### Gaps
- Exact OpenCode SSE event type names and the `opencode run --format json` schema need to be read from `/doc` (the OpenAPI spec) or the source. They are not on the docs pages fetched.
- Goose's stream-json event schema and the Gemini CLI stream-json flag literal were not shown on the pages fetched.
- I found no third-party benchmark of event-stream completeness or reliability across agents. Production robustness claims, for example how often a `result` or `turn.completed` is missing on crash, are untested here.
