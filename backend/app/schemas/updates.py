"""M5 authoritative-source reminders and trend-alert contracts."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.knowledge import Industry


class SourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1, max_length=2000)
    industry: Industry = "general"

    @field_validator("name", "url", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class SourceOut(BaseModel):
    id: str
    name: str
    url: str
    industry: str
    last_status: str | None = None
    last_error: str | None = None
    last_checked_at: datetime | None = None
    change_detected_at: datetime | None = None
    acknowledged_at: datetime | None = None
    pending: bool


class AlertReviewIn(BaseModel):
    status: Literal["acknowledged", "false_positive"]
    note: str = Field(default="", max_length=1000)

    @field_validator("note", mode="before")
    @classmethod
    def strip_note(cls, value):
        return value.strip() if isinstance(value, str) else value


class AlertOut(BaseModel):
    id: str
    rule_version: str
    scope_type: str
    scope_value: str
    month: str
    observed: int
    baseline: float
    ratio_threshold: float
    sample_size: int
    explanation: str
    status: str
    note: str | None = None
    reviewed_by_name: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime


class TrendEvaluationOut(BaseModel):
    category: str
    observed: int
    baseline: float
    sample_size: int
    sufficient: bool
    triggered: bool
    reason: str


class TrendRuleOut(BaseModel):
    version: str
    baseline_months: int
    min_latest: int
    ratio_threshold: float
    min_window_records: int


class TrendBacktestOut(BaseModel):
    months_evaluated: int
    triggered: int
    followed: int
    sample_size: int
    note: str


class TrendSufficiencyOut(BaseModel):
    supported: bool
    reason: str
    categories_sufficient: int
    categories_evaluated: int


class TrendReportOut(BaseModel):
    as_of: str
    rule: TrendRuleOut
    backtest: TrendBacktestOut
    sufficiency: TrendSufficiencyOut
    evaluations: list[TrendEvaluationOut] = Field(default_factory=list)
    alerts: list[AlertOut] = Field(default_factory=list)
    false_positive_count: int
