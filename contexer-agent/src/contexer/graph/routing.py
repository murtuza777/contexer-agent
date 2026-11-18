"""Every edge of the loop, as a pure function of the state.

No edge calls a model, reads a file or looks at the clock, so the whole
shape of a run can be tested as a table. Two rules hold on every edge:

* a state with a terminal outcome goes to ``finalize`` and nowhere else;
* ``finalize`` is the only node that ends a run, and it re-checks the one
  outcome nobody is allowed to assert: ``succeeded`` (:func:`settle`).
"""

from __future__ import annotations

from collections.abc import Callable

from contexer.gate.models import GateDecision
from contexer.graph.state import LoopState

NODES: tuple[str, ...] = (
    "intent",
    "approve",
    "coder_turn",
    "guard_snapshot",
    "ensure_app",
    "test",
    "score",
    "review",
    "triage",
    "ask_user",
    "diagnose",
    "finalize",
)
_REPAIR_MOVES = ("repair_same_session", "fresh_approach", "rollback_and_retry")


def _ended(state: LoopState) -> bool:
    return bool(state.get("terminal"))


def _corrected(state: LoopState) -> bool:
    return bool((state.get("correction") or "").strip())


def after_intent(state: LoopState) -> str:
    return "finalize" if _ended(state) else "approve"


def after_approve(state: LoopState) -> str:
    if _ended(state):
        return "finalize"
    return "intent" if _corrected(state) else "coder_turn"


def after_coder_turn(state: LoopState) -> str:
    if _ended(state):
        return "finalize"
    return "intent" if _corrected(state) else "guard_snapshot"


def after_guard_snapshot(state: LoopState) -> str:
    return "finalize" if _ended(state) else "ensure_app"


def after_ensure_app(state: LoopState) -> str:
    # An app that did not start still goes to `test`, which records that nothing could run.
    return "finalize" if _ended(state) else "test"


def after_test(state: LoopState) -> str:
    return "finalize" if _ended(state) else "score"


def after_score(state: LoopState) -> str:
    # A pass is read by the Reviewer once before the run ends; every other end goes straight to finalize.
    if state.get("terminal") == "succeeded" and state.get("reviewed") != state.get("n"):
        return "review"
    return "finalize" if _ended(state) else "triage"


def after_review(state: LoopState) -> str:
    # The review either leaves the pass as it is, or clears it to ask for one repair.
    return "finalize" if _ended(state) else "coder_turn"


def after_triage(state: LoopState) -> str:
    if _ended(state):
        return "finalize"
    if _corrected(state):
        return "intent"
    move = state.get("move")
    if move == "ask_user":
        return "ask_user"
    return "diagnose" if move in _REPAIR_MOVES else "finalize"  # `stop`, or anything that is not a move


def after_ask_user(state: LoopState) -> str:
    if _ended(state):
        return "finalize"
    return "intent" if _corrected(state) else "diagnose"


def after_diagnose(state: LoopState) -> str:
    return "finalize" if _ended(state) else "coder_turn"


EDGES: dict[str, Callable[[LoopState], str]] = {
    "intent": after_intent,
    "approve": after_approve,
    "coder_turn": after_coder_turn,
    "guard_snapshot": after_guard_snapshot,
    "ensure_app": after_ensure_app,
    "test": after_test,
    "score": after_score,
    "review": after_review,
    "triage": after_triage,
    "ask_user": after_ask_user,
    "diagnose": after_diagnose,
}

# Where each node can lead; the graph is compiled with exactly these.
TARGETS: dict[str, tuple[str, ...]] = {
    "intent": ("approve", "finalize"),
    "approve": ("coder_turn", "intent", "finalize"),
    "coder_turn": ("guard_snapshot", "intent", "finalize"),
    "guard_snapshot": ("ensure_app", "finalize"),
    "ensure_app": ("test", "finalize"),
    "test": ("score", "finalize"),
    "score": ("triage", "review", "finalize"),
    "review": ("coder_turn", "finalize"),
    "triage": ("diagnose", "ask_user", "intent", "finalize"),
    "ask_user": ("diagnose", "intent", "finalize"),
    "diagnose": ("coder_turn", "finalize"),
}


def settle(terminal: str, reason: str, decision: GateDecision | None) -> tuple[str, str]:
    """The outcome a run may end with. ``succeeded`` stands only on a gate decision of ``pass``.

    Every other outcome is kept as it is: nothing is gained by claiming a failure.
    """
    if terminal != "succeeded":
        return terminal or "failed_checks", reason
    if decision is not None and decision.outcome == "pass":
        return terminal, reason
    seen = f"the gate's decision was '{decision.outcome}'" if decision is not None else "no check was ever run"
    return "failed_checks", f"The run was marked as succeeded, but {seen}. Only a pass from the gate ends a run as succeeded."
