# Readiness review, 2026-11-19

> A second, wider audit was done on 2026-11-24: [production/audit.md](../production/audit.md).
> It found that two fixes below do not fully hold (the `goto` check and the `.env` filter) and
> lists what is open now.

What stands between the code on this branch and people using it, after
Phase 5. Four parts: what an independent review found and what was fixed,
what is still open, what monitoring exists, and which agents to add next.

The review was done by a separate reader with no part in writing the code.
It read the source and did not run the tests. Its findings were checked
against the code before anything was changed; two it reproduced itself.

---

## 1. Found and fixed

Each has tests that fail without the fix.

| Finding | What could happen | Fix | Tests |
| --- | --- | --- | --- |
| A check step expanded `${NAME}` for any environment variable, and a replayed `goto` could open any address | A check written by a steered model (from an issue, or by the Tester reading a page) types a model key into the page or sends a token to another site | Only `CONTEXER_TEST_*` and the names in `[auth]` are expanded; a `goto` to another site is refused; a draft from an issue is not run before it is approved | `test_secret_scope.py` |
| The dev server, the dependency install and `[app] reset` inherited the repository tokens the coding agent is denied | Code the agent just wrote (a `postinstall`, the `dev` script) reads `GITHUB_TOKEN` in Actions | One `child_env()` without those tokens for all three | `test_env_hygiene.py` |
| The project `.env` was read again on every attempt | The agent writes `GITHUB_API_URL=...` or `GIT_EXTERNAL_DIFF=...` into `.env` and Contexer's own git and GitHub calls follow it | Read once per process, before any agent runs; names that steer git, GitHub or the interpreters are never taken from it | `test_env_hygiene.py` |
| The snapshot repository followed the project's `.gitignore` as it was at each snapshot | The agent edits `.gitignore`; `.env` enters the diff, the prompts and the pull request, and a revert deletes it from disk | Whatever git ignores at a snapshot is frozen out of every later one; env files and local databases are excluded by default | `test_checkpoint.py` |
| The secret scan ran only on runs that passed, and only made the pull request a draft | A failed run with a pasted key is pushed as a draft | `hand_off` scans every outcome; a change that adds a secret is committed locally and not pushed | `test_phase4_handoff.py` |
| Nothing stopped two runs in one project | One run's revert wipes the other agent's work | A lock file with the holder's process id; a dead holder's lock is taken over | `test_run_safety.py` |
| A failed snapshot or a missing git ended in a traceback | A first-time user sees Python internals and no report | A sentence, an exit code, and git is checked before the run | `test_run_safety.py` |
| A pinned port already in use | Checks run against whatever answers there | The port is probed before the app is started | `test_run_safety.py` |
| A contract id was used as a file name unchecked | An edited draft comment writes outside `.contexer/contracts` | The id must be a plain name | `test_run_safety.py` |
| `--yes` recorded the git user as the approver | A pull request says "approved by NAME" for checks nobody read | Recorded as `--yes (not reviewed by a person)`; the pull request says so and is a draft | `test_run_safety.py` |
| A check could not answer a browser dialog | A real run passed by deleting a "Delete this entry?" confirmation | `accept_dialog` / `dismiss_dialog` steps; an unanswered dialog is named in the failure; the scan notes a removed confirmation | `test_dialogs.py` |

One change here can break an existing project: a hand-written contract that
types `${SOME_NAME}` into a field, where `SOME_NAME` is not in `[auth]` and
does not start with `CONTEXER_TEST_`, now fails with a message that says
why. Rename the variable or reference it from `[auth]`.

---

## 2. Still open

Seven of the eleven items first listed here were fixed on 2026-11-20:

| Was open | Now |
| --- | --- |
| `/contexer approve` not tied to the draft that was read | An approval given before the draft last changed is refused (`--approved-at`, set from the comment's time in Actions) |
| The draft was only found when a Bot posted it | The draft is the comment Contexer's own token posted (`GitHubClient.identity`), so a personal token works and another bot's comment is not a draft |
| The CI gate trusted the contract in the pull request | The gate names every contract the pull request changed against the base branch. It warns; it does not fail, because a contract can be changed on purpose |
| `--resume` reverted hand edits without a word | It lists the files it put back, and `contexer restore RUN --before-resume` brings them back |
| Hidden issue text reached the agents | HTML comments and invisible characters are removed, and the draft comment shows the goal exactly as the agents read it |
| Pull request bodies carried live Markdown from the app and from models | Mentions, issue references, links and images in that text are made inert |
| The token budget restarted on `--resume` | It starts from what the run had already spent |
| The model's `grep` took any pattern and walked `node_modules` | Closed folders are never entered; a nested quantifier and an over-long pattern are refused |

Tests: `test_issue_hardening.py`, `test_graph_resume.py`, `test_diagnoser.py`.

Still open:

1. **The issue flow has never been run against a real GitHub issue.** It is
   tested against a fake GitHub and a real local git remote.
2. **Blocking calls on the event loop** (dependency install, the review's
   commands, git) delay Ctrl+C by minutes. On Windows a timed-out install
   leaves `node` running.
3. **In Actions on Linux** a process the agent starts can probably read the
   token from its parent's environment (`/proc`). Not confirmed. The real
   fix is to build in a job with no write token and push from a second job.
4. **Codex has no rule against editing `.contexer/`**; the tamper guard is
   its only layer.
5. **The gate's warning about a changed contract is advice.** Nothing stops
   a reviewer from merging without reading it.
6. **A resume cannot tell a person's edits from what a killed turn left.**
   It keeps both and says so; it does not ask first.

Not measured: macOS (never run), Codex (never run live), a cheaper model
per agent (only one model is deployed), a project that is not a web app
(nothing but a browser can prove a check).

---

## 3. Evals

What is measured today, and what each number can and cannot carry:

| Suite | Question | Latest | Limit |
| --- | --- | --- | --- |
| `bench` (gate) | Does a contract catch a seeded bug? | 46 of 46, 0 false failures in 326 | Contracts and bugs by the same author |
| `bench --suite tester` | Does the exploring agent find it? | 25 of 40, 0 false alarms in 22 clean runs | 15 missed; one model, one run each |
| `bench --suite repair` | Does the loop fix it, per engine? | 46 of 46 on both | Too easy for the model to separate the engines |
| `bench --suite reviewer` | Does the review flag a planted issue? | 10 of 10, 1 false high in 10 | Twenty small diffs by the scan's author |
| `tests/test_security.py` | Does hostile text stay quoted, and does code hold the line when a model is steered? | 12 strings, every channel; live 12 of 12 on one model | Quoting is proven; a model ignoring it is not |
| Real project (HealthCare.Ai) | Does it work on an app nobody tuned it for? | 3 runs that count: public pages, a one-file change, a change behind sign-in | One project, one stack, checks approved with `--yes` |

What the real project taught that no benchmark did: a sign-in that does
not work costs money before anyone is told; checks drafted from the wrong
page are worthless; and a check can be passed by making the app worse. All
three are fixed or guarded now, and all three came from one failed run. The
next evals worth building are therefore not more seeded bugs but:

- **More real projects**, different stacks, with the checks read by a
  person. Three to five would say more than any of the suites above.
- **A weaker coding model** on the repair suite: the only way to learn
  whether Triage and the Diagnoser earn their cost.
- **"Passed for the wrong reason" cases** for the reviewer suite: changes
  that satisfy a check by removing a safeguard, hard-coding a value, or
  weakening validation. The delete-confirmation case is the first.

---

## 4. Monitoring

Contexer has no server, by decision, so there is nothing to watch from
outside. What a user needs is to see their own runs. That exists:

- Every run writes `run.json`, `report.html` and a transcript per agent to
  `.contexer/runs/`.
- `contexer runs` lists them; `contexer runs --stats` reports how runs
  ended, attempts per proven run, cost per proven run, what was spent on
  runs that proved nothing, and runs with a high review note.
- Langfuse tracing is there when the user sets its keys.

On the three HealthCare.Ai runs `--stats` printed: 2 of 3 proven, $10.46 in
all, $5.23 per proven run, $6.26 spent on a run that proved nothing. That
last figure is the one a token dashboard does not have.

Not needed now: a hosted dashboard, alerts, telemetry sent anywhere. Needed
before a team uses it: the same numbers across a team's machines, which
means an export (`runs --stats --json`, or OpenTelemetry) and nothing more.
Usage data from other people's machines would need their consent and is not
built.

---

## 5. Which agents to add

From research into what people report about AI-assisted coding. The figures
come from search summaries of the named sources and were not checked against
the primary reports; several are from vendors who sell a remedy.

| Pain point | Evidence |
| --- | --- |
| "Almost right" code, low trust | 66% name it as a frustration; 46% distrust AI accuracy (Stack Overflow Developer Survey 2025) |
| Review is the bottleneck | Teams with high AI use merge 98% more pull requests with review time up 91% (Faros AI 2025, a vendor) |
| Regressions in code that worked | Most models broke passing behaviour on 75% or more of long maintenance tasks (SWE-CI, 2026, from secondary summaries) |
| Missing access control in AI-built apps | 170 of 1,645 sampled Lovable apps exposed personal data through missing row-level security (reported 2025) |
| Security flaws | About 45% of AI code samples had a vulnerability (Veracode 2025, a vendor) |
| Invented packages | About 20% of generated samples named a package that does not exist (Spracklen et al., USENIX Security 2025) |
| Tests bent to pass | Agents pass tests that contradict the specification (ImpossibleBench, 2025) |
| Unwanted changes | Agent pull requests are accepted less often than human ones, with unwanted features among the reasons (2026 studies) |

The rule for choosing: an agent belongs in Contexer when most of what it
reports can be **proven by code**. One whose output is only a model's
opinion is the kind of tool Contexer exists to replace.

**Build first.**

1. **Regression guard.** Replay every check that was ever approved, on
   every run and on every pull request, and say which earlier behaviour
   broke. Mostly built already (`replay_others`, `contexer replay`). Missing:
   treating a broken earlier check as its own finding with its own repair,
   and telling a check that is stale from one that caught a regression.
   Entirely provable.
2. **Access prober.** Two test accounts; after the checks pass, account B
   asks for account A's records through the app's own API. A read that
   succeeds is a replayable proof of a missing access check. Needs an
   HTTP-level check next to the browser ones, which also ends the
   browser-only limit. The best-documented failure of AI-built apps, and the
   one a browser check on one account can never see.
3. **Dependency checker.** For every package a change adds: does it exist
   in the registry, how old is it, does it have known vulnerabilities. No
   model needed. Cheap, and the evidence is peer-reviewed.
4. **Scope guard.** Extends the review's scan with what code can count:
   files changed outside what the goal named, tests edited or deleted,
   assertions removed, safeguards removed. The delete confirmation is this
   class. Shrinks what a person has to read.

Fold a **flake check** into the runner rather than making it an agent: a
check that fails is run once more, and a check that passes the second time
is reported as flaky, not as refuted. A tool whose proof is "replayed by
code" needs its replays to be trustworthy.

**Not yet.**

- **A test author.** It would make Contexer a writer of code, and invites
  the tampering it polices.
- **A memory or documentation keeper.** The pain is real and nothing about
  it can be proven; the coding agents already have their own files for it.
- **A performance checker.** No good evidence that AI code causes it, and
  timings on a dev server are noise.
- **Accessibility** is worth adding later as a plain check with axe-core,
  not as an agent: it is cheap, and it catches only part of the problem.
