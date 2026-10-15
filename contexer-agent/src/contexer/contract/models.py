"""Acceptance contracts: the approved definition of "done" for one goal.

A contract is a goal plus its acceptance criteria and their executable checks.
Once a person approves it, its content hash is recorded; any later edit makes
the contract *modified*, and a modified contract is never treated as approved.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from contexer.verification.models import AcceptanceCriterion, GoalAnalysis

CONTRACT_VERSION = 1

ContractStatus = Literal["approved", "draft", "modified"]
ContractSource = Literal["llm", "rules", "user"]


class Approval(BaseModel):
    """Who approved a contract, when, and the content hash they approved."""

    by: str
    at: str
    sha256: str


class Contract(BaseModel):
    """A goal and the acceptance criteria that define it as done."""

    version: int = CONTRACT_VERSION
    id: str
    goal: str
    summary: str = ""
    criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    source: ContractSource = "user"
    created_at: str = Field(default_factory=lambda: utc_now())
    approval: Optional[Approval] = None

    # -- identity -------------------------------------------------------------

    def content_hash(self) -> str:
        """SHA-256 of the canonical goal and criteria; what an approval covers."""
        payload = {
            "goal": self.goal,
            "criteria": [_criterion_payload(c) for c in self.criteria],
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @property
    def status(self) -> ContractStatus:
        if self.approval is None:
            return "draft"
        return "approved" if self.approval.sha256 == self.content_hash() else "modified"

    def approved_by(self, by: str) -> Contract:
        """Return a copy approved by ``by`` at the current content hash."""
        approval = Approval(by=by, at=utc_now(), sha256=self.content_hash())
        return self.model_copy(update={"approval": approval})

    # -- conversion -----------------------------------------------------------

    def to_analysis(self) -> GoalAnalysis:
        return GoalAnalysis(
            goal=self.goal,
            summary=self.summary,
            acceptance_criteria=list(self.criteria),
            generated_by=self.source,
        )

    @classmethod
    def from_analysis(cls, analysis: GoalAnalysis, contract_id: str) -> Contract:
        return cls(
            id=contract_id,
            goal=analysis.goal,
            summary=analysis.summary,
            criteria=list(analysis.acceptance_criteria),
            source=analysis.generated_by,
        )

    def to_file_dict(self) -> dict[str, Any]:
        """JSON-ready dict in the on-disk format (DSL aliases, no nulls inside checks)."""
        data = self.model_dump(mode="json", exclude={"criteria"})
        data["criteria"] = [_criterion_payload(c) for c in self.criteria]
        return data

    def describe_lines(self) -> list[str]:
        """Human-readable checklist, one criterion per line plus its check."""
        lines: list[str] = []
        for c in self.criteria:
            kind = "check" if c.check else "judged"
            lines.append(f"[{c.id}] {c.description} ({kind})")
            if c.check:
                lines.extend(f"    {line}" for line in c.check.describe_lines())
        return lines


def _criterion_payload(criterion: AcceptanceCriterion) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": criterion.id,
        "description": criterion.description,
        "verification_method": criterion.verification_method,
    }
    if criterion.check is not None:
        data["check"] = criterion.check.model_dump(mode="json", by_alias=True, exclude_none=True)
    return data


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


_SLUG_STOP_WORDS = {"a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with", "that", "so", "it"}


def slugify(text: str, max_words: int = 6) -> str:
    """``"Users can complete a task!"`` -> ``"users-can-complete-task"``."""
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _SLUG_STOP_WORDS]
    return "-".join(words[:max_words]) or "contract"
