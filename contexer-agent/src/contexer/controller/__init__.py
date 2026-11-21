"""What a run is made of: its settings and outcome, the prompts for the coding agent, and the scoring rules.

The loop itself is the graph in ``contexer.graph``.
"""

from contexer.controller.models import Attempt, Engine, RunOutcome, RunSettings, TerminalState

__all__ = ["Attempt", "Engine", "RunOutcome", "RunSettings", "TerminalState"]
