"""M2 document identity and human publication contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Industry = Literal["general", "fire", "production", "community", "forest"]
INDUSTRIES = {
    "general": "未归类 / 通用", "fire": "消防", "production": "安全生产", "community": "社区", "forest": "林区",
}


class KnowledgeMetadataIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    source: str = Field(default="", max_length=2000)
    version: str = Field(default="unversioned", min_length=1, max_length=64)
    industry: Industry = "general"
    applicability: str = Field(default="", max_length=2000)
    is_demo: bool = False
    supersedes_id: str | None = Field(default=None, max_length=36)

    @field_validator("title", "source", "version", "applicability", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class KnowledgeReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject", "retire"]
    note: str = Field(min_length=1, max_length=2000)
    revision: int = Field(strict=True, ge=0)
    source_checked: bool = Field(default=False, strict=True)

    @field_validator("note", mode="before")
    @classmethod
    def strip_note(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def approval_requires_source_check(self):
        if self.decision == "approve" and not self.source_checked:
            raise ValueError("发布前必须明确确认已核对来源、版本、原文和适用范围")
        return self
