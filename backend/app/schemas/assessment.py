from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class JobOut(BaseModel):
    """异步研判任务状态（B3/WP1.1，async 模式）。"""

    id: str
    assessment_id: str
    kind: str = "create"
    status: str = "queued"  # queued | running | succeeded | failed
    progress_step: str = "queued"
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class ImageOut(BaseModel):
    id: str
    filename: str
    mime_type: str | None = None
    size_bytes: int
    image_kind: str = "original"
    created_at: datetime
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
    evidence_judge: dict[str, Any] | None = None
    multi_model: dict[str, Any] | None = None
    disagreement: dict[str, Any] | None = None
    findings: list[dict[str, Any]] = Field(default_factory=list)
    report: dict[str, Any] | None = None
    followup_questions: list[str] = Field(default_factory=list)
    followup_used: int = 0
    confirmed: bool = False
    rectification_status: str | None = None
    rectification_note: str | None = None
    rectification_score: float | None = None
    rectification_analysis: dict[str, Any] | None = None
    rectification_meta: dict[str, Any] | None = None
    rectification_next_states: list[str] = Field(default_factory=list)
    rectified_at: datetime | None = None
    review_reasons: list[str] = Field(default_factory=list)
    awaiting_human_review: bool = False
    human_review: dict[str, Any] | None = None
    risk_result: dict[str, Any] | None = None
    risk_score: int | None = None
    risk_label: str | None = None
    risk_operational_level: int | None = None
    risk_rule_version: str | None = None
    risk_factors: dict[str, int] = Field(default_factory=dict)
    risk_evidence_used: list[str] = Field(default_factory=list)
    risk_triggered_rules: list[str] = Field(default_factory=list)
    risk_review_suggestion: bool = False
    created_at: datetime
    updated_at: datetime
    images: list[ImageOut] = Field(default_factory=list)


class ConfirmIn(BaseModel):
    confirmed: bool = True
    edits: dict[str, Any] = Field(default_factory=dict)
    reviewer: str | None = None
    note: str | None = None


class RectificationConfirmIn(BaseModel):
    resolved: bool = True
    note: str | None = None


class RectificationTransitionIn(BaseModel):
    to_status: str
    note: str | None = None
    by: str | None = None


class FollowupIn(BaseModel):
    answer: str = Field(..., min_length=1)


class HealthOut(BaseModel):
    status: str
    provider: str
    rag_loaded: bool
    reranker_enabled: bool = True
    version: str
    auth_required: bool = False


class AuthUserOut(BaseModel):
    id: str
    username: str
    role: str


class TokenOut(BaseModel):
    """POST /api/v1/auth/token 的响应（OAuth2 密码流）。"""

    access_token: str
    token_type: str = "bearer"
    user: AuthUserOut


class UserCreateIn(BaseModel):
    username: str
    password: str
    role: str = "inspector"


class UserAdminOut(BaseModel):
    """用户管理列表项：绝不包含 password_hash。"""

    id: str
    username: str
    role: str
    disabled: bool
    created_at: datetime


class ProviderInfo(BaseModel):
    provider: str
    vision_model: str
    text_model: str
    embedding_model: str
    models: list[dict[str, str]] = Field(default_factory=list)


class DocumentOut(BaseModel):
    id: str
    title: str
    source: str | None = None
    version: str | None = None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
