"""The state of one run on the graph engine.

Everything here is plain data (strings, numbers, lists, dicts), because it is
written to the checkpoint after every node and read back by a later process.
Live objects (the browser, the dev server, the coding agent, the snapshot
repository) are in the run context (``context.py``), never here.
"""

from __future__ import annotations

from typing import Any, TypedDict

# Below any score an attempt that ran can get, above the score of one where the app did not start. An
# attempt kept across a change of the checks gets it: anything that runs replaces it, and nothing that
# does not run can.
CARRIED_SCORE = -(10**5)
UNSCORED = -(10**9)


class _Always(TypedDict):
    """What every state holds from the first node on."""

    run_id: str
    goal: str
    contract_id: str
    intent_id: str
    n: int
    # Attempt number (as a string: checkpoints are JSON) -> snapshot commit. "0" is the project as found.
    snapshots: dict[str, str]
    # The snapshot the work tree holds, or held when the current turn began.
    current: str
    prompt: str


class LoopState(_Always, total=False):
    started_at: str
    # Where the goal's words came from when the person did not type them ("GitHub issue #7"); "" otherwise.
    goal_origin: str

    # -- what done means ------------------------------------------------------------------
    other_ids: list[str]
    # The content hash the person approved. "" until they have.
    approved_hash: str
    # sha256 of every file that says what done means, as Contexer last wrote or accepted them.
    guard: dict[str, str]
    # A correction from the person, waiting for the Intent agent.
    correction: str
    # Corrections that were applied.
    corrections: list[str]
    # Set when a correction arrived after work began: the next prompt restates the whole job.
    restate: str

    # -- the plan for the first turn ---------------------------------------------------------
    # The approved hash the Planner last ran for, and the brief it gave ("" when it gave none).
    planned: str
    brief: str

    # -- the earlier contracts, before the first turn ---------------------------------------
    # The replay of the other approved contracts on the project as it was found: whether it ran, and the
    # checks ("contract/check") that passed and that failed then. Absent until it was taken; taken once.
    # A check that passed here and fails after an attempt is a regression; one that failed here is stale.
    baseline: dict[str, Any]

    # -- the attempts ---------------------------------------------------------------------
    attempts: list[dict[str, Any]]
    best: int | None
    best_score: int
    session_id: str | None
    fresh: bool
    last_signatures: list[str]
    # Checks that failed in exactly the same way as in the attempt before, per attempt.
    repeats: dict[str, list[str]]
    # The attempt the files were put back to after the latest attempt, if they were.
    reverted_from: int | None
    # The coding agent's last turn, between `coder_turn` and `guard_snapshot`.
    turn: dict[str, Any]
    changed: list[str]
    app_error: str | None

    # -- deciding what is next ------------------------------------------------------------
    move: str
    decisions: list[dict[str, Any]]
    asked: int
    answer: str
    # The Diagnoser's leads so far: the attempt each was written after -> its cause and instruction.
    leads: dict[str, dict[str, str]]

    # -- the review of a passing attempt ---------------------------------------------------
    # The notes of the latest review, and the attempt it read.
    review: list[dict[str, Any]]
    reviewed: int
    # How many repairs a review has asked for (at most one), and the passing attempt it asked on.
    review_repairs: int
    review_passed: int | None
    # The attempt whose pass stands when a later one was undone.
    accepted: int | None

    # -- accounting -------------------------------------------------------------------------
    agents: list[dict[str, Any]]
    cost_usd: float
    elapsed: float

    # -- the end ----------------------------------------------------------------------------
    terminal: str
    reason: str
