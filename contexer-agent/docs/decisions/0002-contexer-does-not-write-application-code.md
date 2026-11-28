# 0002: Contexer does not write application code

## Status

Accepted on 2026-11-24 by the owner, after an audit asked whether Contexer
should become a coding agent.

## Context

Claude Code, Codex and OpenCode write code well and improve every month.
What they lack is someone independent who says what done means, checks it,
and sends them back with a precise reason when it is not. A second coding
agent would compete with them on their strongest ground and lose the
independence that makes a verdict worth having.

## Decision

Contexer instructs, checks and reports. It does not edit a project's code.

- Its own agents (`crew/`) have read-only tools. A test lists every tool of
  every agent and fails if one can write (`tests/test_guardrails.py`).
- Code changes come from the coding agent Contexer starts
  (`agents/`), or from the agent a person already works in, which reaches
  Contexer through the MCP server and the stop hook (`integrations/`).
- What Contexer writes in a project is under `.contexer/`, plus the files
  `contexer init` is asked for.

## Alternatives considered

- **Add an edit tool to the Diagnoser** so it fixes small things itself.
  Rejected: the one that fixed it would then be the one that checks it.
- **Become a full coding agent with verification built in.** Rejected: see
  Context.

## Consequences

- Contexer is only as good at building as the coding agent under it. Its
  lever is the brief and the repair prompt, so those must be specific.
- A run costs the coding agent's turns plus Contexer's own model calls.
- Contexer works with any coding agent that can be started headless or can
  call an MCP server, including ones that do not exist yet.
