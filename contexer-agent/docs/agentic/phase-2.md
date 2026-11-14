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
