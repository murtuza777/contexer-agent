# Phase 4: Reviewer and pull requests

Goal: the diff is read before a person sees it, and the goal → PR and issue
flows run on the new engine. See [architecture.md](architecture.md) §4.

Phase is done when: both tickets pass and one real pull request has been
opened by Contexer on a test repository.

---

## T4.1 Reviewer agent

**Goal.** Catch what a browser cannot: wrong logic on paths not exercised,
secrets, weakened tests, leftover debug code.

**Scope.** `src/contexer/crew/reviewer.py`:
- Input: the diff from the baseline snapshot, the intent spec, the check list.
- Tools, all read-only: read file, grep, list changed files, and run the
  project's own commands when they exist (tests, lint, typecheck) with a
  timeout.
- A code-only pre-scan first: secret patterns, `.only`, deleted or loosened
  tests, `console.log` added.
- Output: `list[ReviewNote]` with file, line, severity, explanation.
- A note is **advisory** unless it is backed by a failing command or a check;
  backed notes go to the Diagnoser like any other failure.
- `bench/reviewer/`: 10 diffs with planted issues and 10 clean diffs.

**Acceptance.**
- The Reviewer has no tool that writes files or reaches the network.
- Benchmark: planted issues flagged, and false high-severity notes on clean
  diffs, both published.
- A high-severity security note makes the pull request a draft.

**Verify.** `pytest tests/test_reviewer.py`; `contexer bench --suite reviewer`.

---

## T4.2 Pull request and issue flow on the new engine

**Goal.** `contexer run --pr` and the GitHub issue flow work as today, with
the new evidence.

**Scope.**
- `github/handoff.py`: the PR body adds the intent, checks found by the
  Tester, review notes, and attempts with triage reasons.
- `github/issues.py` and `cli/issue_cli.py`: the draft comment shows intent
  and checks; questions from the Intent agent are posted as a comment and
  answered by reply; approval re-runs the graph up to the approval point.
- Issue text is passed to agents as quoted data with a fixed preamble.

**Acceptance.**
- Existing hand-off and issue tests pass on the new engine.
- An issue body containing "ignore your instructions and …" does not change
  agent behaviour in a scripted test and is shown quoted in the transcript.
- One real PR opened on a test repository, linked in the changelog.

**Verify.** `pytest tests/test_handoff.py tests/test_issues.py`; one live PR.
This needs a test repository on your GitHub account.

---

## Results, 2026-11-19

Both tickets are built, tests first, on the graph engine. One part of the
phase gate is not met: no real pull request has been opened on a test
repository, because there is no test repository Contexer may push to yet.

**What was built.**

- `crew/reviewer.py`: `prescan` (code), `run_commands` (code), the Reviewer
  agent (a model with `read_file`, `grep`, `list_changed_files`), and
  `review()` that puts them together. `ReviewNote` has the file, line,
  severity, category, explanation, where it came from, and `backed`.
- A `review` node on the graph between a pass and `finalize`.
- `contexer bench --suite reviewer` with 10 planted and 10 clean diffs.
- The pull request body, the draft rule, `contexer issue build --engine`,
  Intent-agent drafts on issues with questions and `/contexer answer`, and
  `quoted_goal` for issue text.

**Reviewer benchmark** ([scan](../../bench/reviewer-results/scan.md),
[reviewer](../../bench/reviewer-results/reviewer.md)).

| | Planted flagged | by the scan | by the model | Clean diffs with a false high |
| --- | --- | --- | --- | --- |
| Scan alone, no model | 4 of 10 | 4 | | 0 of 10 |
| Scan and Reviewer, Azure gpt-5.4 | 10 of 10 | 4 | 6 | 1 of 10 |

About 63,000 tokens in and 2,000 out for the 20 diffs, 73 seconds. The one
false high is on `clean-key-from-environment`: the model said that
`process.env` does not exist in browser code. The case does not say whether
the file runs in a browser, so the note is defensible and the case is
ambiguous; it is left as it is rather than rewritten to make the number
zero. It is a logic note, not a security one, so it would not have made a
pull request a draft. Twenty diffs written by the author of the scan are a
smoke test, and "flagged" checks where a note points, not what it says.

**Live run.** A seeded bug on the todo fixture, `contexer run --engine
graph` with Claude Code as the coding agent and Azure gpt-5.4 for
Contexer's agents: fixed in one attempt (23 s, $0.65 for Claude Code), 7 of
7 checks proven, then the Reviewer read the diff in 2 steps (3,464 tokens
in, 41 out) and had no notes.

**Where it differs from the plan above.**

- *The project's commands are run by code, not by the agent.* The plan gave
  the Reviewer a tool to run tests, lint and typecheck. Code now runs them
  once before the agent starts and hands it the results. The agent needs no
  tool that executes anything, a failing command is a fact whether or not
  the model thought to run it, and it works with no model at all.
- *What counts as backed.* The plan: a note is advisory unless a failing
  command or a check backs it. Built: a note is backed when code saw it,
  which is the scan or a failing command. The model cannot back its own
  note by naming a command.
- *Backed notes get one repair turn, not the whole loop.* They do not go
  through Triage and the Diagnoser "like any other failure", because they
  are not failures of a check: the work has passed. One turn is asked for,
  and if it breaks a check it is undone and the pass stands. A review that
  could turn a pass into a failure would give a model's pre-scan patterns
  the say over "done", which the proof rule keeps for the checks.
- *Only npm scripts are run.* Python and other projects get the scan and
  the agent, not their own commands. A command is not run on the baseline,
  so a failure that was already there is reported with that caveat.
- *Approval does not re-run the graph up to the approval point.* The build
  approves the contract from the comment in the approver's name and starts
  the graph there. Drafting again at build time could produce checks that
  differ from the ones the person approved.
- *Checks found by the Tester are not in the pull request.* The Tester does
  not run inside the loop yet.
- *The scripted test for a hostile issue* shows that the text reaches the
  coding agent's prompt and the Intent agent's transcript quoted, with its
  forged closing marker neutralised. It cannot show that a real model
  ignores it; quoting makes steering less likely and nothing relies on it.
  What an issue cannot do is in code: it cannot approve its own checks.

**Not done.**

- **One real pull request on a test repository.** Needs a repository on
  GitHub that Contexer may push to and open pull requests and issues on.
  The hand-off and the issue flow are tested against a fake GitHub and a
  real local git remote.
- `contexer demo` still runs on the classic engine.
- The classic engine has no review.
