"""Output schema of the risk engine."""

from pydantic import BaseModel, Field


class RiskAssessment(BaseModel):
    risk_score: int = Field(ge=0, le=100)
    risk_level: str
    operational_level: int = Field(ge=1, le=3)
    factor_scores: dict[str, int] = Field(default_factory=dict)
    severity_hint: int | None = Field(default=None, ge=1, le=3)
    rule_version: str
    evidence_used: list[str] = Field(default_factory=list)
    triggered_rules: list[str] = Field(default_factory=list)
    review_suggestion: bool = False
