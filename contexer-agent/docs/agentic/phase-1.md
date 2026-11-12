# Phase 1: The Tester agent

Goal: `contexer test "what the app should do"` explores a running app like a
user and reports only findings that replay. No coding agent is involved. See
[architecture.md](architecture.md) §5.

Phase is done when: the four tickets pass and the benchmark numbers are
published, with 0 confirmed false alarms on clean apps.

---

## T1.1 Browser tools

**Goal.** A model can operate the app, and every action is recorded.

**Scope.** `src/contexer/browser/tools.py` and `recorder.py`, on one Playwright
page that reuses the project's sign-in state:

| Tool | Does | Recorded as |
| --- | --- | --- |
| `snapshot()` | ARIA tree with test ids and placeholders (existing `capture_ui_snapshot`) | nothing |
| `click`, `fill`, `press`, `select`, `check`, `uncheck`, `hover`, `goto` | The action, with a `Locator` | a `Step` |
| `read_errors()` | Console and page errors, failed network requests | nothing |
| `screenshot()` | Saves a JPEG to the run folder | nothing |
| `expect(...)` | Evaluates one `Expectation` now and returns pass or fail | an `Expectation` |
| `reset()` | Fresh page and, if configured, the `[app] reset` command | starts a new recording |

Locators are validated with the existing `Locator` model, so the model cannot
invent a selector form the runner does not support.

**Acceptance.**
- Each action tool on a fixture app produces the same `Step` the hand-written
  contract uses.
- A locator that matches nothing returns a clear error with the current
  snapshot; it does not raise.
- Password values are masked in snapshots and transcripts.

**Verify.** `pytest tests/test_browser_tools.py` (real Chromium, no model).

---

## T1.2 Tester loop

**Goal.** The agent tests against the stated intent and is hard to satisfy.

**Scope.** `src/contexer/crew/tester.py`, `crew/prompts/tester.md`:
- Input: intent text, the UI snapshot, existing approved checks.
- Prompt: test each stated behaviour, then edge cases (empty input, reload,
  signed out, repeated action); report only what was observed.
- Graded examples in the prompt: a real bug, a non-bug, a finding that was too
  vague to replay.
- Output: `list[Finding]` with `kind` (`bug` or `works`), description, the
  recorded steps, the expectation that failed or passed, severity.
- Limits from `AgentSpec`; default 40 steps.

**Acceptance.**
- With the scripted model, a queued sequence of tool calls yields the expected
  findings.
- Reaching the step limit returns the findings so far with status `step_limit`.

**Verify.** `pytest tests/test_tester.py`.

---

## T1.3 Freeze and replay

**Goal.** No finding is shown unless code reproduced it.

**Scope.** `src/contexer/browser/freeze.py`:
- `freeze(finding) -> Check` from the recorded steps and expectation.
- Replay with `CheckRunner` in a fresh context.
- A `bug` is confirmed when the check fails on replay; a `works` finding is
  confirmed when it passes.
- Confirmed checks are saved as a draft contract; unconfirmed findings go to
  `unconfirmed.json` with the reason.

**Acceptance.**
- A finding whose steps do not reproduce is never listed as confirmed.
- A confirmed `works` check replays green three times in a row on a fixture app.
- Confirmed checks load through `ContractStore` unchanged.

**Verify.** `pytest tests/test_freeze.py`.

---

## T1.4 `contexer test`

**Goal.** One command a person can run on their own app.

**Scope.** `src/contexer/cli/test_cli.py`:
- `contexer test "intent" [--url URL] [--steps N] [--model …]`.
- Starts the app with `open_app`, signs in if `[auth]` exists, runs the Tester,
  freezes and replays, writes `result.json` and `report.html`.
- Terminal output: confirmed bugs, confirmed working behaviours, unconfirmed
  count, steps, cost.
- Exit codes: 0 no confirmed bugs, 1 confirmed bugs, 2 could not test, 3 error.

**Acceptance.**
- On the demo app with its seeded bug, a live run reports that bug as confirmed.
- On the clean demo app, a live run reports 0 confirmed bugs.
- Ctrl+C stops the browser and the dev server and leaves no process behind.

**Verify.** Live runs on the demo app; `pytest tests/test_test_cli.py` with the
scripted model.

---

## Phase gate

`contexer bench --suite tester` on all seven apps with one paid model:

- bugs found and confirmed, out of 40;
- confirmed false alarms on clean and benign variants (target 0);
- cost and steps per app.

Numbers go in `bench/RESULTS.md` and the changelog, whatever they are.
