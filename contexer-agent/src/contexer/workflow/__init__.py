"""Workflow module for autonomous engineering loop.

Exports resolve lazily so that importing a leaf module such as
``contexer.workflow.inspector`` does not pull in the whole loop (and the
app-server layer it depends on).
"""

from __future__ import annotations

from typing import Any

__all__ = ["AutonomousLoop", "AutonomousLoopResult", "extract_acceptance_criteria"]


def __getattr__(name: str) -> Any:
    if name in ("AutonomousLoop", "AutonomousLoopResult"):
        from contexer.workflow import loop

        return getattr(loop, name)
    if name == "extract_acceptance_criteria":
        from contexer.workflow.criteria import extract_acceptance_criteria

        return extract_acceptance_criteria
    raise AttributeError(f"module 'contexer.workflow' has no attribute {name!r}")
