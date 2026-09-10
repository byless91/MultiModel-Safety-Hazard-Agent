"""Evidence guard: shared adapter over the single evidence judge implementation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EvidenceGuardResult(BaseModel):
    supported: bool = False
    support_score: float = 0.0
    evidence_ids: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    needs_human_review: bool = True
    visual_evidence_count: int = 0
    retrieval_evidence_count: int = 0
    finding_status: list[dict[str, Any]] = Field(default_factory=list)


def validate_evidence(
    findings: list[dict[str, Any]] | None,
    evidence: list[dict[str, Any]] | None,
) -> EvidenceGuardResult:
    """Delegate to evidence/judge.py so both entry points share one algorithm."""
    from app.services.evidence import judge_evidence

    result = judge_evidence(findings, evidence)
    return EvidenceGuardResult(
        supported=result.supported,
        support_score=result.support_score,
        evidence_ids=list(dict.fromkeys(result.evidence_ids)),
        unsupported_claims=list(dict.fromkeys(result.unsupported_claims)),
        needs_human_review=result.needs_human_review,
        visual_evidence_count=result.visual_evidence_count,
        retrieval_evidence_count=result.retrieval_evidence_count,
        finding_status=[item.model_dump() for item in result.findings],
    )
