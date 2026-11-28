# 0004: Where code lives

## Status

Accepted on 2026-11-28.

## Context

The package grew from a gate into a harness in a few weeks. Two files took
most of the growth: `cli/run_cli.py` (1,156 lines, the most changed file in
the repository) and `graph/nodes.py` (1,332 lines, the second). A change to
either meant reading all of it, and two people could not work in one
without a conflict. There was no written rule for where a new piece goes.

## Decision

The package has seven groups. Code depends downward in this table.

| Group | Packages | What it is |
| --- | --- | --- |
| Commands | `cli/`, `integrations/`, `bench/`, `demo/` | What a person or a coding agent calls. Parses, prints, exits. No rules of its own |
| Reporting | `github/` | Turning a finished run into a status, a comment or a pull request |
| Runs | `graph/`, `controller/` | The loop of one run: its nodes, its state, how it ends |
| Agents | `crew/`, `agents/`, `opencode/` | Contexer's own model-driven agents (read-only), and the adapters that start a coding agent |
| Proof | `verification/`, `gate/`, `browser/`, `observer/`, `appserver/`, `workflow/` | Starting the app, replaying checks in a browser, turning verdicts into a decision |
| Records | `contract/`, `intent/`, `skills/`, `evidence/`, `checkpoint/` | What is kept in a project: contracts, intent, run folders, snapshots |
| Base | `llm/`, `config/`, `procutil.py`, `riskscan.py` | Model providers, settings and helpers |

The table is a direction, not yet a law. Counted on 2026-11-28, eleven
imports go the other way, and each is one of three kinds:

- **Shared data types.** The check language (`verification/checks.py`,
  `verification/models.py`) and the result types (`gate/models.py`) are
  what contracts, intent, skills, evidence and `config/project.py` are made
  of, so those import them. The types belong at the bottom; they sit in
  `verification/` and `gate/` because that is where they began.
- **One helper used from below.** `appserver/devserver.py`,
  `browser/freeze.py` and `workflow/criteria.py` import the masker and the
  untrusted-text wrapper from `crew/`.
- **Reading an issue.** `crew/context_sources.py` and `graph/context.py`
  import the issue reader from `github/issues.py`, a module that both reads
  issues and writes comments.

Rules that follow:

1. **A command holds no rule.** If `contexer run` and the issue flow must
   agree on something (how a budget is built, which model an agent gets),
   it lives below both, in one place (`cli/run_resources.py` holds what a
   run works with).
2. **A node says what happens next; a question about the state is a
   function.** Read-only questions are in `graph/facts.py`, the endings a
   run does not reach on its own in `graph/endings.py`, and `graph/nodes.py`
   keeps the nodes.
3. **One file, one reason to change.** When a file passes about 600 lines
   or shows up in most pull requests, split it along the seam its tests
   already use, moving text without rewriting it.
4. **A name that tests replace stays where they replace it.** Several tests
   swap `run_cli.crew_model` or `nodes.open_app`. A function is moved only
   with every caller that must see the replacement.
5. **Nothing but a command prints.** The MCP server and the stop hook own
   their standard output, so code below the command group returns text.
6. **Do not add an import that goes up the table.** Move the thing that is
   needed down instead.

## Alternatives considered

- **One class per node, one file each.** The nodes share a run's live
  objects through a closure today. Turning them into classes touches 750
  lines that the checkpoint and resume tests depend on, for a gain in
  navigation only. Not done now; rule 3 will get there a piece at a time.
- **A plugin system for agents and check kinds.** There are three coding
  agents and one way to check. One adapter is a guess at a seam; three with
  the same interface is a real one, and `agents/` already is that. Check
  kinds wait until a second way to check exists.
- **Move the shared types and the masker down now.** It would make the
  table a law. It also renames imports in about a hundred files in one
  change. Left for its own pull request.
- **Leave it.** The files worked. Rejected: they were where most conflicts
  between parallel changes happened on 2026-11-26 and 27.

## Consequences

- `cli/run_cli.py` is 979 lines and `graph/nodes.py` 1,082 after the first
  two moves. Both are still over the mark in rule 3 and are the next to
  split: the approval prompt out of `run_cli.py`, the review and triage
  nodes out of `nodes.py`.
- Nothing enforces the direction yet. Once the eleven exceptions are moved,
  an import-linter contract in CI can.
- Moving text keeps history readable with `git log --follow` and
  `git blame -C`.
