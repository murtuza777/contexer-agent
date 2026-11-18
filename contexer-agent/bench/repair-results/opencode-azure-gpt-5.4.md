# Repair suite: OpenCode on Azure gpt-5.4, 2026-11-18

`contexer bench --suite repair --agent opencode --model azure/gpt-5.4 --repair-only`, all 7 apps, 46 bugs, 86 minutes.

Coding agent: opencode (azure/gpt-5.4). Contexer's own agents on the graph engine: model 'gpt-5.4'. Up to 2 repair round(s) per bug.
Repair only: the first turn gave the agent the job and told it to change nothing, so every fix below is a repair. "Attempts" counts that first turn.

| Engine | Bugs | Fixed | First try | After a repair | Attempts | Minutes | Agent cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| classic | 46 | 46 | 0 | 46 | 92 | 39.7 | not reported |
| graph | 46 | 46 | 0 | 46 | 92 | 46.6 | not reported |

Bugs on which the engines differ:
none.

Every run took two attempts: the turn that changes nothing, then one repair in the same session
(`repair_same_session` 46 times on each engine). No bug needed a second repair, so Triage never had
to choose between a fresh session, a rollback or a question, and this run says nothing about those.
The agent cost is not reported because the OpenCode adapter does not report one.
