# 0003: What defines done is out of the agent's reach

## Status

Accepted. Written down on 2026-11-28; the rule is older than this record and was widened on 2026-11-26 and 27.

## Context

The coding agent has a shell in the project. The files that say what done
means are in the same project. An agent that cannot make a check pass can
make it go away instead, and has been seen to.

## Decision

A person approves what done means, and nothing a model or a coding agent
does can change it without that showing.

- A contract is approved at its content hash; any later edit needs a new
  approval (`contract/store.py: ContractStore.approve`).
- After every turn of the coding agent, the contracts, the intent, the
  skills and `contexer.toml` are compared byte for byte with what they were
  and put back if they differ; the run ends as tampered
  (`controller/shared.py: ContractGuard`).
- Approval happens at a terminal or on a pull request, never through a tool
  an agent can call: the MCP server has no tool that approves, edits or
  skips a check (`integrations/mcp_server.py`), and a run with no terminal
  approves nothing unless `--yes` is given, which is recorded as not
  reviewed by a person (`cli/run_cli.py`).
- Text that comes from the app, an issue or a project file reaches a model
  marked as data (`crew/untrusted.py`), and code checks what a model claims
  a file says before it is passed on (`crew/context_sources.py`).

## Alternatives considered

- **Keep contracts outside the project.** Rejected: they belong in the
  repository so that a team reviews them and CI replays them.
- **Ask the agent not to edit them.** A rule in a prompt is advice. It is in
  the prompt too, but nothing depends on it.

## Consequences

- A person has to read and approve checks. That step cannot be automated
  away without weakening everything after it.
- Editing a contract by hand during a run ends the run as tampered. That is
  the cost of not being able to tell a person's edit from an agent's.
