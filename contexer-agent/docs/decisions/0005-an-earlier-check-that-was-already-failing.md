# 0005: An earlier check that was already failing warns and does not fail a run

## Status

Accepted on 2026-11-27. Chosen by the maintainer's assistant as the option
that is easy to reverse; the owner has not confirmed it.

## Context

A run replays every approved contract, not only the one being built. Before
2026-11-27 a failing check of an earlier contract failed the run whoever
broke it. The coding agent was then sent to repair something its change had
not touched, and a project with one old broken check could not finish any
run.

## Decision

A run replays the other approved contracts once before the coding agent's
first turn (`graph/nodes.py: baseline`).

- A check that passed then and fails after an attempt is a **regression**.
  It fails the run, goes first in the repair prompt, and is reported with
  the attempt that broke it.
- A check that already failed then is **stale**. It does not fail the run
  and is not sent to the coding agent. It is listed as not proven on every
  verdict, in `run.json`, in the report and in the pull request, and the
  last line of the run counts them (`gate/decision.py: decide`).
- `contexer verify`, `contexer replay`, the MCP server and the stop hook
  have no baseline. There a failing approved check fails, as before.

## Alternatives considered

- **Keep failing the run.** Honest and simple. Rejected for a run: it makes
  the agent responsible for a state it did not create.
- **Open the pull request as a draft when a check is stale.** Not chosen,
  and cheap to add: the body already has its own heading for them.

## Consequences

- A run with other approved contracts costs one more replay of their
  checks.
- A run can end as succeeded beside an approved check that does not hold.
  Every place that shows a result has to say so, and a new place that shows
  results has to as well.
- A check that fails at the baseline only because it is flaky stays stale
  for the whole run.
