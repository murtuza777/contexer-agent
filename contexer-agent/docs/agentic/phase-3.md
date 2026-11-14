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
