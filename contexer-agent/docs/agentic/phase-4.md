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
