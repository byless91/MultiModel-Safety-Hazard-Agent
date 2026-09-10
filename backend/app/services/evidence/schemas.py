"""Output schema of the evidence judge."""

from pydantic import BaseModel, Field


class FindingEvidenceResult(BaseModel):
    finding_id: str
    category: str
    supported: bool = False
    support_score: float = 0.0
    evidence_ids: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    visual_evidence_ok: bool = True
    needs_human_review: bool = True


class EvidenceJudgeResult(BaseModel):
    supported: bool = False
    support_score: float = 0.0
    evidence_ids: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    needs_human_review: bool = True
    visual_evidence_count: int = 0
    retrieval_evidence_count: int = 0
    findings: list[FindingEvidenceResult] = Field(default_factory=list)
    version: str = "v1"
