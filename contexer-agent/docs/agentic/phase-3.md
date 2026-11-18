# Phase 3: The closed loop

Goal: `contexer run "goal"` drives the coding agent by itself: intent →
approval → build → test → triage → repair, until the gate passes or a limit is
reached. See [architecture.md](architecture.md) §3 and §7.

Phase is done when: the four tickets pass, the existing controller tests pass
on both engines, and a live run fixes the demo app without the user pasting
anything.

---

## T3.1 The graph

**Goal.** The loop as a graph with typed state, able to pause and resume.

**Scope.** `src/contexer/graph/`:
- Decision first: a one-day spike of the loop on LangGraph (`interrupt`,
  SQLite checkpointer). Adopt it if pause, resume and Ctrl+C all work on
  Windows and Linux; otherwise keep our own loop with a small state file.
  The result is recorded in `docs/agentic/architecture.md` §8. The rest of
  this ticket assumes LangGraph, pinned.
- `state.py`: run id, goal, intent, contract ids, attempts (snapshot ref,
  score, findings), best attempt, cost, terminal state and reason. Live
  objects (browser, dev server, coding agent, shadow repo) live in a run
  context, not in the state.
- `nodes.py`: `intent`, `approve` (interrupt), `coder_turn`, `guard_snapshot`,
  `ensure_app`, `test`, `score`, `triage`, `diagnose`, `finalize`.
- `routing.py`: every edge as a pure function.
- `build.py`: compile with a SQLite checkpointer in the run folder.

**Acceptance.**
- A table test covers every edge and every terminal state.
- With the scripted coding agent and scripted models, a run that needs one
  repair ends `succeeded` with two attempts recorded.
- A run can never reach `succeeded` when `decide()` does not return `pass`;
  a test tries to force it and fails.

**Verify.** `pytest tests/test_graph.py`.

---

## T3.2 Triage

**Goal.** The next move is chosen with judgment, inside limits set by code.

**Scope.** `src/contexer/crew/triage.py`:
- Input: attempt history (scores, failure signatures, reverts), remaining
  budget and rounds, the latest findings.
- Output: one of `repair_same_session`, `fresh_approach`, `rollback_and_retry`,
  `ask_user`, `stop`, with a one-line reason.
- Code builds the list of legal moves first (for example no `repair_*` when no
  round is left) and rejects anything else.
- Fallback when the model fails or picks an illegal move: the 0.4 rules
  (repeat signature or revert → fresh approach; otherwise same session).
- Scoring and best-attempt rollback reuse `_score`, `_signatures` and
  `ShadowRepo`, moved out of `controller/run.py` into shared helpers.

**Acceptance.**
- An illegal choice is replaced by the fallback and logged.
- The project is never left worse than the best attempt; the existing
  rollback tests pass on the new engine.

**Verify.** `pytest tests/test_triage.py`.

---

## T3.3 Interrupts, cancel and resume

**Goal.** The user can step in, stop, and continue.

**Scope.**
- Approval and `ask_user` are graph interrupts rendered by the CLI.
- While a run is waiting or between attempts, the user can type a correction;
  it goes to the Intent agent and the affected checks are redrafted and
  re-approved.
- Ctrl+C: kill process trees, snapshot `stopped`, restore the best attempt,
  write evidence, exit 130 (same behaviour as today).
- `contexer run --resume RUN`: reset the tree to the last snapshot, then
  continue from the checkpoint.

**Acceptance.**
- A killed process resumes and finishes with the same result as an
  uninterrupted scripted run.
- Ctrl+C during a coding-agent turn leaves no process and restores the files.
- A correction mid-run changes the contract hash and requires approval again.

**Verify.** `pytest tests/test_graph_resume.py` on Windows and Linux.

---

## T3.4 `contexer run` on the new engine

**Goal.** One command, two engines, measured against each other.

**Scope.**
- `--engine graph|classic` and `CONTEXER_ENGINE`; `graph` is the default only
  after the gate below.
- `tests/test_controller.py` parametrised over both engines.
- The evidence report gains: intent, agent transcripts, triage decisions.

**Acceptance.**
- Every existing controller test passes on both engines.
- `contexer bench` (hand-written contracts) is unchanged: 40/40, 0 false
  failures.

**Verify.** Full `pytest`; `contexer bench`.

---

## Phase gate

- A live `contexer run` on the demo app reaches `succeeded` with no pasted
  prompt.
- Repair success on the seeded bugs, graph engine against classic, same coding
  agent and model. The graph becomes the default only if it is at least as good.

---

## Results, 2026-11-18

All four tickets are built, tests first. `--engine graph` is opt-in;
`classic` stays the default until the phase gate below is measured.

**T3.1.** LangGraph was adopted after the spike (recorded in
[architecture.md](architecture.md) §8). `graph/`: `state.py` (plain data,
checkpointed after every node), `context.py` (the live objects),
`nodes.py`, `routing.py` (every edge a pure function; a table test covers
each edge and each of the nine terminal states at each node), `build.py`,
and `engine.py` (`GraphController`). Besides the ten nodes in the plan there
is an eleventh, `ask_user`: a node that waits for a person runs again from
its start when the answer arrives, so the wait cannot share a node with the
model call that decided to ask.

`finalize` is the only node that ends a run, and it does not take
`succeeded` from the state: `settle()` keeps it only when the gate's
decision on the last attempt, computed again from the recorded verdicts,
is `pass`. Two tests try to force it (a state that says `succeeded` before
anything ran, a Triage model that answers `succeeded`) and both end
`failed_checks`.

**T3.2.** `crew/triage.py`. Code lists the legal moves; the model is shown
only those; an answer outside the list, a model error or a spent budget
falls back to the 0.4 rules and the rejected answer is kept in the report.
Triage has no tools. With no model configured the rules decide every time,
which is why every controller test passes on both engines unchanged.
Scoring, failure signatures, the tamper guard and the evidence writer moved
from `controller/run.py` to `controller/shared.py`; both engines import
them.

**T3.3.** Approval and Triage's question are interrupts; the CLI renders
them (`y`, `n`, or type what to change). Ctrl+C behaves as on the classic
engine and adds one line: how to resume. `contexer run --resume RUN` resets
the files to the last snapshot (after keeping what was there as
`refs/contexer/<run>/before-resume`) and continues from the checkpoint; a
test kills the process outright in its second turn and the resumed run ends
with the same attempts, outcome and files as an uninterrupted one. A
correction goes to the Intent agent; a changed contract is saved
unapproved, and nothing is built until it is approved again.

**T3.4.** `--engine graph|classic`, `CONTEXER_ENGINE`.
`tests/test_controller.py` runs every case on both engines. The report and
`run.json` gain the intent, each Triage decision with who made it, and what
each of Contexer's agents used, with the path of its transcript.

**Where the build differs from the plan.**

- **A resumed run refuses to continue when what defines done changed while
  it was stopped.** Contracts and the intent are not in the snapshots, so a
  coding agent killed in mid-turn could have edited them and the tamper
  guard would never have seen it. The state keeps a hash of each of those
  files; `--resume` compares and stops with the names of the files that
  differ. This was not in the plan and closes a hole the plan had.
- **Corrections are taken at three points, not at any moment.** At an
  approval prompt, at Triage's question, and with
  `contexer run --resume RUN --correct "..."` after Ctrl+C. The engine also
  polls a `corrections` callable before each turn and after each failed
  attempt, and that is tested, but the CLI does not read the keyboard while
  the coding agent is working: Ctrl+C, then `--resume --correct`, is the
  way to step in between attempts.
- **Questions are not asked in the middle of a run.** The Intent agent
  drafts with `assume`: what it would have asked is listed under "Assumed
  without asking" at the approval prompt, where a correction can be typed.
- **Checks that change in the middle of a run reset the comparison.** A
  score under the old checks says nothing about the new ones. The files
  that are there stay the fallback, with a score that any attempt which
  runs will beat and no attempt whose app does not start can.
- **The test node replays approved checks; it does not explore.** The loop
  drawing in architecture §3 has the Tester exploring inside the loop. That
  is not built: a finding the Tester confirms is not an approved check, and
  how it becomes one inside a run (who approves it, what it costs per
  attempt) is not designed. `contexer test` stays the way to explore.
- With no model for Contexer's own agents and a goal, the checks are
  drafted and approved the 0.4 way before the graph starts.

**Live runs, 2026-11-18** (Azure gpt-5.4 for Contexer's agents).

- *A goal, start to finish, no pasted prompt.* On the demo app with its
  contract removed: `contexer run "Users can add tasks and complete them,
  and the count of tasks left stays correct: completing a task lowers it"
  --engine graph --yes --agent claude-code`. The Intent agent drafted two
  checks, Claude Code fixed the seeded bug in one attempt, both checks
  passed in the browser: `succeeded` in 41 s, $0.69 of agent spend, about
  2,700 tokens for the Intent agent.
- *What the first live run showed, and what was changed.* The first try
  drafted the checks without looking at the app. They named a placeholder
  and a test id the app does not have, and Claude Code renamed both in the
  app to make the checks pass: `succeeded`, with two files changed for no
  reason a user would want. The `intent` node now starts the app and gives
  the Intent agent what the page shows (roles, labels, placeholders, test
  ids), as `contexer test` does. The run above is the second try: the
  checks use the app's own names and one file changed.
- *What it still gets wrong.* The Intent agent sees the page as it loads,
  with no task in the list. So it guessed the label of the checkbox a task
  gets ("the task's title") and the coding agent changed the label from
  "Complete <title>" to fit. Names of things that only exist after an
  action are still invented. Exploring before drafting would fix it; that
  is the Tester in the loop, which is not built.
- *A repair, with a real model deciding.* On the todo fixture with a
  scripted coding agent that leaves the same bug twice: Triage chose
  `repair_same_session` after the first failure and `fresh_approach` after
  the second ("failed in exactly the same way in attempts 1 and 2"), the
  Diagnoser ran before each repair, and the third attempt passed. About
  2,200 tokens for Triage and 7,900 for the Diagnoser.

**Not done: the second half of the phase gate.** Repair success on the
seeded bugs, graph against classic with the same coding agent and model,
has not been measured. It needs a real coding agent on 40 bugs twice,
roughly $50 to $60 of Claude Code spend at the rate above, and a small
sample would say nothing: both engines fix these bugs in the first attempt,
and they differ only when a repair is needed. Until it is measured the
graph is opt-in and `classic` is the default.

**Other things left open.**

- The model budget (`[limits]`) starts again when a run is resumed: the
  spend is in the old process. The coding agent's budget does carry over.
- `contexer issue` and `contexer demo` run on the classic engine.

