"""Records what an agent does in the browser, in the check language.

Every action the agent takes becomes a :class:`~contexer.verification.checks.Step`,
and every expectation it evaluates becomes an :class:`Observation` that keeps
the steps that led to it. An observation is therefore a complete, replayable
check: the agent never has to retell what it did, and cannot misremember it.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from contexer.verification.checks import Expectation, Step


class Observation(BaseModel):
    """One expectation, evaluated on the live page after ``steps``."""

    id: str
    steps: list[Step] = Field(default_factory=list)
    expectation: Expectation
    passed: bool
    # What the page showed, in the runner's words: `"1 left"`, `<no matching element>`.
    actual: str = ""
    # False when the page was signed out on purpose; None follows the project.
    login: Optional[bool] = None
    # False when a step before it failed part-way, so the steps may not be what the page went through.
    reliable: bool = True


class Recorder:
    """The steps since the page was last fresh, and every observation of the session."""

    def __init__(self) -> None:
        self.steps: list[Step] = []
        self.observations: list[Observation] = []
        self.login: Optional[bool] = None
        # Set when an action failed after it may have changed the page; cleared by a fresh page.
        self.tainted = False

    def add_step(self, step: Step) -> None:
        self.steps.append(step)

    def add_observation(self, expectation: Expectation, passed: bool, actual: str) -> Observation:
        observation = Observation(
            id=f"e{len(self.observations) + 1}",
            steps=list(self.steps),
            expectation=expectation,
            passed=passed,
            actual=actual,
            login=self.login,
            reliable=not self.tainted,
        )
        self.observations.append(observation)
        return observation

    def observation(self, observation_id: str) -> Optional[Observation]:
        wanted = observation_id.strip().lower()
        return next((o for o in self.observations if o.id == wanted), None)

    def start_over(self, login: Optional[bool] = None) -> None:
        """A fresh page: later observations start from no steps. Earlier ones keep theirs."""
        self.steps = []
        self.login = login
        self.tainted = False
