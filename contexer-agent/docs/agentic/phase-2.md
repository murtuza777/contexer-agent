# Phase 2: Intent and fix prompts

Goal: Contexer understands what the user meant, remembers corrections, and
writes the fix prompt. This is the first version people can use day to day,
with any coding tool, because the prompt is pasted by the user. See
[architecture.md](architecture.md) §4 and §6.

Phase is done when: the four tickets pass and one live session on the demo
app goes goal → findings → fix prompt → fixed app → all checks green.

---

## T2.1 Intent agent and intent store

**Goal.** A written, editable statement of what the app should do, built from
the goal and every correction.

**Scope.**
- `src/contexer/intent/store.py`: `.contexer/intent/<feature>.md` plus an
  index; load, append a correction, list.
- `src/contexer/crew/intent.py`: input is the goal, the repo summary
  (`RepositoryInspector`), the UI snapshot and the stored intent. Output is an
  updated intent spec, draft checks, and at most 3 questions.
- Questions are asked only when two readings of the goal lead to different
  checks. `--yes` skips questions and records the assumption taken.
- A correction ("deleting should ask first") updates the spec and regenerates
  only the checks it affects.
- Draft checks go through the existing validation in `workflow/criteria.py`
  (`_parse_check`); that file's drafting prompt is retired.

**Acceptance.**
- A correction given in one run is present in the intent the next run loads.
- An unambiguous goal produces 0 questions.
- Every draft check parses as a `Check`; invalid ones are sent back to the
  agent once, then dropped and reported.
- The intent files are covered by the tamper guard during a coding-agent turn.

**Verify.** `pytest tests/test_intent.py`; a live run with one ambiguous goal.

---

## T2.2 Diagnoser

**Goal.** A fix prompt that names the cause, not a list of failures.

**Scope.** `src/contexer/crew/diagnoser.py`:
- Input: confirmed failures (the existing `CheckResult.failure_report()`),
  the diff when one exists, the server log tail, the intent spec.
- Tools: read file, grep, both confined to the project and read-only.
- Output: `RepairBrief` with likely cause, files involved, the instruction,
  and what must keep working.
- The facts (expected, actual, failed step, errors) are inserted by code,
  word for word; the agent adds the cause and the instruction.

**Acceptance.**
- The prompt always contains the exact expected and actual values from the
  check result.
- Read tools refuse paths outside the project and inside `.contexer/`.
- With the scripted model, a brief with no cause still yields a usable prompt
  from the facts alone.

**Verify.** `pytest tests/test_diagnoser.py`.

---

## T2.3 Fix prompt in `contexer test`

**Goal.** The user's loop becomes: run `contexer test`, paste the prompt,
run it again.

**Scope.**
- `contexer test` prints the fix prompt and saves it as `fix-prompt.md` in the
  run folder; `--copy` puts it on the clipboard.
- `contexer test --again` reruns the saved checks first (no model), then
  explores only if they pass.
- `contexer test --correct "…"` records a correction and reruns.

**Acceptance.**
- On the demo app with its seeded bug: the printed prompt, given to a coding
  agent, leads to a version where `--again` is green. Recorded as a live run.
- `--again` with all saved checks still failing makes no model call.

**Verify.** Live run on the demo app with OpenCode or Claude Code; the
transcript shows 0 model calls for the failing `--again` case.

---

## T2.4 Project skills

**Goal.** Contexer gets better at testing one app the more it tests it.

**Scope.**
- `src/contexer/skills/store.py`: `.contexer/skills/<name>.md` with a one-line
  description each; load, save, list.
- After a `contexer test` run, the Tester proposes at most 3 skills from what
  it learned: how to sign in, how to reach a screen, how to seed or reset
  data, which flows are slow.
- Before a run, the skills whose description matches the intent are added to
  the Tester's prompt.
- A skill is advice. It never changes a verdict, and the user can edit or
  delete the file.
- Secrets are never written into a skill; `${ENV}` names are kept as names.

**Acceptance.**
- A second run on the same app that needs sign-in uses fewer Tester steps
  than the first. Measured on the `members` fixture and recorded.
- A skill containing a value that matches a configured secret is rejected.
- With the skills folder deleted, a run behaves exactly as a first run.

**Verify.** `pytest tests/test_skills.py`; the two-run measurement.

---

## Results, 2026-11-18

Built, with tests written first. Live checks ran on Azure AI Foundry
`gpt-5.4`.

**The phase gate: one live session on the demo app.**

| Step | What happened |
| --- | --- |
| `contexer test "Users can add tasks and complete them, and the remaining count stays correct" --yes` | 3 confirmed bugs, 3 confirmed working behaviours, 0 unconfirmed, 2 questions (persistence after a reload, duplicate names) raised instead of reported as bugs. 23 Tester steps, about 150,000 input tokens for the three agents |
| The fix prompt | Named the cause: the checkbox handler in `app.js` line 19 calls the undefined `refesh()`. The facts under it are the replay's |
| Pasted into a coding agent (Claude Code, through Contexer's adapter) | One line changed: `refesh()` became `render()` |
| `contexer test --again` | "6 saved checks pass", then 18 more Tester steps found nothing new. Exit 0 |

`--again` with the bug put back and every model key removed from the
environment: "4 of 9 saved checks still failing", exit 1, a fix prompt
rebuilt from the replay, and no `agents/` folder in the run: no model was
built or called.

OpenCode on the free OpenRouter model was tried first for the coding-agent
step and failed twice on a request timeout before editing anything.

**T2.1, questions.** Two clear goals ("Users can add a task and it appears
in the list", "Users can delete tasks and clear the finished ones") got 0
questions. Two goals that can be read two ways ("Users can archive tasks
they are done with", "Tasks can be reordered and the order is remembered")
got 1 question each, with two readings that would be tested differently.
No draft check was invalid in these runs.

**T2.4, the two-run measurement on `members`: not met.** The ticket expects
the second run to use fewer Tester steps. Measured: 28 steps both times;
tool calls went from 52 to 41 and input tokens from 202,000 to 197,000. The
second run was given two saved skills (how `reset` reaches the signed-in and
signed-out states, where the project count is). One pair of runs, and this
fixture signs in before the Tester starts, so there is little for a skill to
save. The mechanism works; the benefit is not shown.

**T2.4, measured again on 2026-11-21: still not met, and now with enough
runs to say why.** The first measurement compared a first run with a
second one that also had ten saved checks to skip, so it could not tell
skills from saved checks. This one changes only the skills: twelve runs of
`contexer test` on fresh copies of `members`, the same intent, Azure
`gpt-5.4`. Six had `--no-skills`; six started with the three skills an
earlier run saved.

| | Tester steps, each run | Median | Tool calls, median | Tester input tokens, median |
| --- | --- | --- | --- | --- |
| No skills | 13, 16, 17, 17, 19, 23 | 17 | 28.5 | 105,000 |
| Three saved skills | 8, 15, 18, 19, 22, 25 | 18.5 | 33.5 | 124,000 |

- Skills did not lower the step count. Identical runs differ by ten steps
  or more, which is far more than any difference between the two groups.
- There was nothing for a skill to save here. In all twelve runs the
  Tester made five calls that came back as an error or a failed
  expectation, out of 373. The fixture signs in before the Tester starts
  and shows one screen, so it never has to find its way.
- What the step count follows is how many edge cases the Tester decides
  to try, not how long it takes to find a control. "Fewer steps on the
  second run" was the wrong thing to expect from advice about operating
  an app.
- Not measured: an app where the way in is not obvious (a consent screen,
  a control whose label differs from what the goal calls it). That is
  where the live runs on HealthCare.Ai lost time, and it was `contexer
  run` that lost it, which does not read skills at all.

The other two acceptance points hold and have tests: a skill with a
configured secret in it is refused, and with the folder deleted a run is
a first run (`tests/test_skills.py`, `tests/test_test_cli.py`). Cost of
this measurement: 1.39 million input tokens.

**Where the build differs from the tickets.**

- `workflow/criteria.py`'s drafting prompt is not retired. `contexer verify
  "GOAL"` and the classic `contexer run` still draft with it; it goes when
  the new engine replaces them in Phase 3. The Intent agent validates its
  checks with that file's `_parse_check`, as the ticket says.
- A feature's checks are kept next to its intent, in
  `.contexer/intent/<feature>.checks.json`: the Intent agent's drafts and
  the ones a replay confirmed. `--again` replays the confirmed ones only; a
  draft has never run and proves nothing yet.
- With nobody at the terminal (CI, a pipe), questions are not asked and the
  first reading is recorded as an assumption, exactly as with `--yes`.
- A question is asked once per run. If the answers raise a new question, it
  is left for `--correct`.
- The read tools also refuse `.git/`, dependencies and `.env` files, not
  only paths outside the project and `.contexer/`.
- When a saved check that failed passes on `--again`, it is shown and kept
  as "Fixed: ...".

