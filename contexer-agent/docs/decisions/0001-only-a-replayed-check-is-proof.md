# 0001: Only a check replayed by code counts as proof

## Status

Accepted. Written down on 2026-11-28; the rule is older than this record.

## Context

Contexer exists because the tool that writes a change also tends to be the
one that says the change works. A model asked whether an app does what was
asked will often say yes. If Contexer's own verdict rested on a model's
reading of a page, it would repeat the problem it is meant to fix.

## Decision

A check passes only when code replayed its steps in a real browser and
every expectation held (`verification/runner.py: CheckRunner`). Models may
draft checks, look for bugs, read a diff and write a repair prompt. No model
output is a verdict:

- A bug the Tester reports is kept only if a replay by code reproduces it
  (`crew/tester.py`, `crew/challenger.py`).
- A criterion a model judged is labelled `LLM-judged` and cannot pass the
  gate on its own (`gate/decision.py: decide`).
- The Reviewer's notes are advice unless a program backs them
  (`crew/reviewer.py: prescan`, `holds_pull_request`).

## Alternatives considered

- **Let a strong model judge screenshots.** Cheaper to build and covers
  things a selector cannot. Rejected: the verdict would change between runs
  and between models, and nobody could say why a run passed.
- **Trust the project's own test suite.** Rejected as the only signal:
  agents have been seen editing tests to make them pass, and a suite proves
  what its author thought to test, not what the person asked for.

## Consequences

- Contexer verifies what a browser can show. Anything that is not a web
  page is out of reach until a check kind for it exists.
- A check can be wrong. It is still the same wrong thing on every run, a
  person approved it, and it can be corrected in one place.
- Every new feature that reports a result has to answer "what replays it?".
