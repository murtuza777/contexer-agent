# Tester benchmark: `stub`

`contexer bench --suite tester --agent stub`, 2026-11-15 (272 s). Written by the command; do not edit.

The agent gets each app's goal in words and the running app, never the contract. A bug is **found** only when
the agent's finding fails on the buggy app and passes on the correct one, both replayed by code. A **false
alarm** is a finding that fails on correct code. **Unconfirmed** findings did not reproduce and were dropped.
Method: [README.md](../README.md#the-tester-suite).

| App | Seeded bugs | Found | False alarms | Clean runs with a false alarm | Unconfirmed | Steps | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| budget-react | 6 | 0 | 0 | 0 / 3 | 0 | 0 | not reported |
| guestbook-next | 5 | 0 | 0 | 0 / 3 | 0 | 0 | not reported |
| members | 5 | 0 | 0 | 0 / 3 | 0 | 0 | not reported |
| notes | 6 | 0 | 0 | 0 / 3 | 0 | 0 | not reported |
| shop | 6 | 0 | 0 | 0 / 3 | 0 | 0 | not reported |
| signup | 6 | 0 | 0 | 0 / 3 | 0 | 0 | not reported |
| todo | 6 | 0 | 0 | 0 / 4 | 0 | 0 | not reported |
| **total** | 40 | 0 | 0 | 0 / 22 | 0 | 0 | not reported |

The stub agent reports nothing, so this is the floor: every app started, every variant ran, nothing was
found and nothing was wrongly flagged. The hand-written contracts catch 40 of 40 with 0 of 278 false
failures ([RESULTS.md](../RESULTS.md)); that is the number the Tester is measured against.
