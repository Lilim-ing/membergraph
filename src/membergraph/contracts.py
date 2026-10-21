"""Typed contracts shared by every agent.

The whole point of this module is that a claim cannot exist without pointing at
evidence. `Claim.evidence_ids` is validated against the ledger before a plan is
allowed to leave the system.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def digest(obj: Any) -> str:
    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


class SubQuestion(BaseModel):
    id: str
    question: str
    metric: str
    dimension: str | None = None
    rationale: str = ""


class Evidence(BaseModel):
    """A single, reproducible fact pulled from the warehouse."""

    id: str
    kind: Literal["metric", "cohort", "segment", "decomposition", "campaign", "power"]
    query: dict[str, Any]
    summary: str
    value: float | None = None
    unit: str = ""
    rows: int = 0
    detail: dict[str, Any] = Field(default_factory=dict)
    digest: str
    created_by: str
    created_at: str = Field(default_factory=now_iso)


class Claim(BaseModel):
    """An assertion that must cite at least one evidence id."""

    id: str
    text: str
    evidence_ids: list[str] = Field(min_length=1)
    kind: Literal["fact", "inference", "recommendation"] = "fact"
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)

    @field_validator("evidence_ids")
    @classmethod
    def _non_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("a claim without evidence is not allowed")
        return v


class Critique(BaseModel):
    id: str
    target_claim_ids: list[str] = Field(default_factory=list)
    failure_code: Literal[
        "insufficient_evidence", "cost_overrun", "logical_gap", "no_action", "unsupported_number"
    ]
    reason: str
    suggestion: str
    round: int = 1


class Action(BaseModel):
    """A concrete operating move. Vague advice is rejected by compliance."""

    id: str
    segment: str
    channel: str
    offer: str
    timing: str
    budget_cny: float = Field(ge=0)
    success_metric: str
    expected_lift: float | None = None
    evidence_ids: list[str] = Field(min_length=1)


class ComplianceIssue(BaseModel):
    code: str
    detail: str
    severity: Literal["block", "warn"] = "block"


class Plan(BaseModel):
    run_id: str
    topic: str
    provider: str
    sub_questions: list[SubQuestion] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    critiques: list[Critique] = Field(default_factory=list)
    compliance: list[ComplianceIssue] = Field(default_factory=list)
    degraded: bool = False
    degrade_reason: str = ""
    budget: dict[str, Any] = Field(default_factory=dict)
    started_at: str = Field(default_factory=now_iso)
    finished_at: str = ""

    @property
    def blocked(self) -> bool:
        return any(i.severity == "block" for i in self.compliance)

    def evidence_index(self) -> dict[str, Evidence]:
        return {e.id: e for e in self.evidence}

    def orphan_claims(self) -> list[str]:
        known = set(self.evidence_index())
        return [c.id for c in self.claims if not set(c.evidence_ids) <= known]
