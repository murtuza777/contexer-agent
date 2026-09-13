"""Engineering planner synthesizing goal, repository context, and acceptance criteria."""

from __future__ import annotations

import json
import logging
import re
from typing import Optional
from pydantic import BaseModel, Field

from contexer.llm.base import LLMProvider
from contexer.verification.models import GoalAnalysis
from contexer.workflow.inspector import RepositoryContext

logger = logging.getLogger(__name__)


class PlanStep(BaseModel):
    """An individual step in the engineering implementation plan."""

    step_number: int
    title: str
    description: str
    target_files: list[str] = Field(default_factory=list)


class EngineeringPlan(BaseModel):
    """Structured implementation plan generated before OpenCode execution."""

    goal: str
    approach: str
    steps: list[PlanStep] = Field(default_factory=list)

    def format_plan(self) -> str:
        """Format the plan as a clear bulleted string for prompts and terminal display."""
        lines = [f"Approach: {self.approach}", "Steps:"]
        for s in self.steps:
            files_info = f" (target: {', '.join(s.target_files)})" if s.target_files else ""
            lines.append(f"  {s.step_number}. {s.title}: {s.description}{files_info}")
        return "\n".join(lines)


class EngineeringPlanner:
    """Uses LLM to create an engineering plan tailored to the repository and goal."""

    def __init__(self, llm_provider: Optional[LLMProvider] = None) -> None:
        self.llm_provider = llm_provider

    async def create_plan(
        self,
        goal: str,
        repo_context: RepositoryContext,
        analysis: GoalAnalysis,
    ) -> EngineeringPlan:
        """Generate structured engineering plan."""
        if self.llm_provider:
            try:
                criteria_text = "\n".join(
                    f"- [{c.id}] {c.description}" for c in analysis.acceptance_criteria
                )
                prompt = (
                    "You are a Principal Software Architect preparing a precise engineering plan.\n\n"
                    f"User Goal: {goal}\n\n"
                    f"Repository Context:\n{repo_context.format_summary()}\n\n"
                    f"Acceptance Criteria:\n{criteria_text}\n\n"
                    "Create a concrete, minimal, step-by-step engineering plan to satisfy the goal.\n"
                    "Respond ONLY with a JSON object matching this schema:\n"
                    "{\n"
                    '  "approach": "High level strategy",\n'
                    '  "steps": [\n'
                    '    {\n'
                    '      "step_number": 1,\n'
                    '      "title": "Short title",\n'
                    '      "description": "What to change or build",\n'
                    '      "target_files": ["file1.js", "file2.css"]\n'
                    '    }\n'
                    "  ]\n"
                    "}"
                )
                response = await self.llm_provider.generate(
                    prompt=prompt,
                    system_instruction="You are a software architect. Return ONLY valid JSON.",
                )
                raw = response.text.strip()
                if raw.startswith("```"):
                    raw = re.sub(r"^```[a-z]*\n?", "", raw)
                    raw = re.sub(r"\n?```$", "", raw)

                data = json.loads(raw)
                steps = [
                    PlanStep(
                        step_number=item.get("step_number", i + 1),
                        title=item.get("title", f"Step {i + 1}"),
                        description=item.get("description", ""),
                        target_files=item.get("target_files", []),
                    )
                    for i, item in enumerate(data.get("steps", []))
                ]
                return EngineeringPlan(
                    goal=goal,
                    approach=data.get("approach", "Implement requested features."),
                    steps=steps,
                )
            except Exception as e:
                err_msg = str(e)
                if "429" in err_msg or "rate limit" in err_msg.lower():
                    logger.info("LLM quota reached; falling back to dynamic plan.")
                else:
                    logger.warning("LLM plan generation unavailable; falling back to dynamic plan")

        # Fallback dynamic plan
        return EngineeringPlan(
            goal=goal,
            approach=f"Implement feature to satisfy: {goal}",
            steps=[
                PlanStep(
                    step_number=1,
                    title="Implement core feature",
                    description=f"Create or modify components to achieve: {goal}",
                    target_files=repo_context.entry_points[:2],
                ),
                PlanStep(
                    step_number=2,
                    title="Verify styling and interactions",
                    description="Ensure interactive elements respond and layout is clean",
                    target_files=[],
                ),
            ],
        )
