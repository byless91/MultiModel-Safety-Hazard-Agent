from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ImageOut(BaseModel):
    id: str
    filename: str
    mime_type: str | None = None
    size_bytes: int
    image_kind: str = "original"
    url: str | None = None

    model_config = {"from_attributes": True}


class AssessmentOut(BaseModel):
    id: str
    description: str
    status: str
    scene_summary: str | None = None
    hazard_category: str | None = None
    risk_level: int | None = None
    confidence: float | None = None
    conclusion: str | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    report: dict[str, Any] | None = None
    followup_questions: list[str] = Field(default_factory=list)
    followup_used: int = 0
    confirmed: bool = False
    rectification_status: str | None = None
    rectification_note: str | None = None
    rectification_score: float | None = None
    rectification_analysis: dict[str, Any] | None = None
    rectified_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    images: list[ImageOut] = Field(default_factory=list)


class ConfirmIn(BaseModel):
    confirmed: bool = True
    edits: dict[str, Any] = Field(default_factory=dict)


class RectificationConfirmIn(BaseModel):
    resolved: bool = True
    note: str | None = None


class FollowupIn(BaseModel):
    answer: str = Field(..., min_length=1)


class HealthOut(BaseModel):
    status: str
    provider: str
    rag_loaded: bool
    version: str


class ProviderInfo(BaseModel):
    provider: str
    vision_model: str
    text_model: str
    embedding_model: str


class DocumentOut(BaseModel):
    id: str
    title: str
    source: str | None = None
    version: str | None = None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
