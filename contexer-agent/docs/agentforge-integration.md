# AgentForge integration boundary

Contexer uses a focused adaptation of AgentForge as its generic agent-harness
foundation. The source basis audited for this milestone is AgentForge commit
`3f513b36b8cd5f7c4c3303506dcbdec949f9e23c` (2026-06-27). Its MIT licence and
attribution are recorded in [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).

The integration is intentionally a harness layer, not a renamed AgentForge
application. Contexer's future intent, planning, task, OpenCode, observation,
verification, and repair packages remain outside this layer.

```text
Contexer CLI → runtime/agent.py → LLM provider
                         ↓              ↑
                   state/session.py     │
                    ↓          ↑        │
              tools/registry.py ─ tool observations
                    ↓
         filesystem / terminal / git tools
```

## Module mapping

| AgentForge module | Contexer module | Decision |
| --- | --- | --- |
| `agent/agent.py` | `runtime/agent.py` | Adapt the async model → tool → observation loop and streaming boundary. Keep Contexer's public API and reserve orchestration states for later. |
| `agent/session.py` | `state/session.py` | Adapt the long-lived ownership boundary for transcript, registry, approval policy, workspace, and session ID. Remove persistence, checkpoints, branching, modes, skills, MCP, and subagents. |
| `context/manager.py` | `context/history.py` | Adapt ordered user/assistant/tool history. Remove token counting, pruning, compaction, memory, and session tree support. |
| `tools/base.py` | `tools/schemas.py` | Adapt schema-first tools, tool kind classification, confirmation metadata, and structured results. Keep the lightweight callable style rather than AgentForge's abstract class hierarchy. |
| `tools/registry.py` | `tools/registry.py` | Adapt centralized lookup → validation → approval → execution → observation processing. Remove hooks, dynamic discovery, MCP, and subagent registration. |
| `tools/builtin/read_file.py`, `list_dir.py`, `shell.py`, `git_diff.py` | `tools/filesystem.py`, `tools/terminal.py`, `tools/git.py` | Adapt the safety/reliability contract while retaining Contexer's already-hardened workspace paths, shell limits, and read-only Git implementation. |
| `safety/approval.py` | `safety/approval.py` | Adapt explicit approval decisions and command safety classification. Narrow to local filesystem and shell actions. |
| `safety/output_hygiene.py`, `prompt_injection.py`, `utils/redaction.py` | `safety/observations.py` | Adapt ANSI/control stripping, output bounds, secret redaction, and untrusted-observation wrapping in one compact module. |
| `client/providers/base.py`, `client/llm_client.py` | `llm/base.py`, `llm/openrouter.py` | Keep Contexer's provider interface and OpenRouter-compatible implementation. AgentForge's multi-provider client, fallbacks, and circuit breaker are not needed yet. |
| `ui/tui.py`, `cli/` | `cli/ui.py`, `cli/repl.py`, `cli/commands.py` | Keep Contexer's Typer + Rich CLI identity. Adapt a Rich approval panel; do not import AgentForge's Click commands or session-management UI. |
| `tools/mcp/`, `skills/`, `hooks/`, `agent/subagent_runner.py`, `agent/persistence.py`, `context/compaction.py` | none | Remove/defer. They are outside Milestone 3 and would prematurely expand the Contexer surface. |

## Milestone 3 runtime contract

1. The CLI sends a user message to `ContexerAgent`.
2. `AgentSession` appends it to conversation context and exposes tool schemas.
3. The configured LLM provider returns streaming text or typed tool calls.
4. `ToolRegistry` validates each call, applies the approval policy, runs the tool, and cleans/redacts the observation.
5. The observation returns to context as untrusted data.
6. The loop repeats until the LLM sends final text.

The only available action tools are workspace filesystem inspection/writes,
bounded shell execution, and read-only Git inspection. OpenCode, planning,
verification, repair, MCP, browser automation, cloud services, and complex
memory are deliberately absent.
