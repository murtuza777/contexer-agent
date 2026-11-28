# Decisions

One file per decision that would be expensive to reverse: what was decided,
why, what else was considered, and what it costs. A record is changed only
by a later record that supersedes it.

Write one when a change picks between approaches that both work, alters
what a pass means, adds a place data is sent, or moves where a kind of code
lives. Copy the headings of an existing record and take the next number.

| Record | Decision |
| --- | --- |
| [0001](0001-only-a-replayed-check-is-proof.md) | Only a check replayed by code counts as proof |
| [0002](0002-contexer-does-not-write-application-code.md) | Contexer does not write application code |
| [0003](0003-what-defines-done-is-out-of-the-agents-reach.md) | What defines done is out of the agent's reach |
| [0004](0004-where-code-lives.md) | Where code lives |
| [0005](0005-an-earlier-check-that-was-already-failing.md) | An earlier check that was already failing warns and does not fail a run |
