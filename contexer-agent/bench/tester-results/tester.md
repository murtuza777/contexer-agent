# Tester benchmark: `tester`

`contexer bench --suite tester --agent tester --app <app>`, run once per app on 2026-11-17 with Azure AI Foundry
`gpt-5.4` (40 steps per variant) and merged. Six apps are from one run; `guestbook-next` was run again after a fix
(see [RESULTS.md](../RESULTS.md#tester-suite-measures-an-agent-that-explores)). One run per variant: expect a few bugs either way on a repeat.

The agent gets each app's goal in words and the running app, never the contract. A bug is **found** only when
the agent's finding fails on the buggy app and passes on the correct one, both replayed by code. A **false
alarm** is a finding reported on correct or benign code. **Rejected** is a finding on a seeded bug whose check
the correct app fails too, so it does not count. **Unconfirmed** findings did not reproduce and were dropped.
Method: [README.md](../README.md#the-tester-suite).

| App | Seeded bugs | Found | False alarms | Clean runs with a false alarm | Rejected | Unconfirmed | Steps | Tokens in / out | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| todo | 6 | 5 | 0 | 0 / 4 | 0 | 0 | 341 | 2,307,066 / 17,480 | not reported |
| shop | 6 | 5 | 0 | 0 / 3 | 0 | 0 | 341 | 2,922,471 / 15,489 | not reported |
| signup | 6 | 2 | 0 | 0 / 3 | 3 | 0 | 225 | 1,421,853 / 13,816 | not reported |
| notes | 6 | 5 | 0 | 0 / 3 | 2 | 0 | 348 | 2,522,365 / 17,807 | not reported |
| members | 5 | 1 | 0 | 0 / 3 | 3 | 0 | 209 | 1,402,152 / 12,875 | not reported |
| budget-react | 6 | 3 | 0 | 0 / 3 | 1 | 0 | 295 | 2,318,568 / 20,132 | not reported |
| guestbook-next | 5 | 4 | 0 | 0 / 3 | 2 | 0 | 174 | 1,107,872 / 12,272 | not reported |
| **total** | 40 | 25 | 0 | 0 / 22 | 11 | 0 | 1933 | 14,002,347 / 109,871 | not reported |

Not found: `todo/input-not-cleared`, `shop/all-keeps-filter`, `signup/email-not-validated`, `signup/password-min-wrong`, `signup/stale-error`, `signup/submit-reloads-page`, `notes/pin-not-reordered`, `members/count-not-pluralised`, `members/no-auth-guard`, `members/sign-out-keeps-session`, `members/welcome-shows-email`, `budget-react/amount-not-cleared`, `budget-react/category-ignored`, `budget-react/filter-stuck`, `guestbook-next/name-dropped`.

In 17 run(s) the agent stopped early (a step or time limit, or a model error); what it had recorded was still scored.
