"""The small, versioned M1 taxonomy and its human-entry contract."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

TAXONOMY_VERSION = "m1-v1"
CATEGORIES = (
    "占用疏散通道", "消防器材失效", "电气线路隐患", "野外用火风险",
    "危险化学品存储不规范", "公共区域安全隐患", "其他隐患",
)
TAGS = ("通道受阻", "设施缺失", "设施损坏", "线路裸露", "违规用火", "疑似泄漏", "防护缺失", "待现场核实")


class ClassificationData(BaseModel):
    taxonomy_version: str = TAXONOMY_VERSION
    suggestion_status: Literal["pending", "suggested", "unknown", "failed", "manual"] = "pending"
    suggested_category: str | None = None
    suggested_tags: list[str] = Field(default_factory=list)
    final_tags: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    is_demo: bool = False
    provider: str | None = None
    model: str | None = None
    revision: int = 0


class ClassificationSaveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    tags: list[str] = Field(default_factory=list, max_length=8)
    risk_level: int | None = Field(default=None, strict=True, ge=1, le=3)
    note: str = Field(default="", max_length=2000)
    taxonomy_version: Literal["m1-v1"] = TAXONOMY_VERSION
    revision: int = Field(strict=True, ge=0)

    @field_validator("category")
    @classmethod
    def known_category(cls, value: str) -> str:
        if value not in CATEGORIES:
            raise ValueError("请选择分类体系中的类别；无法归类时选择其他隐患")
        return value

    @field_validator("tags")
    @classmethod
    def known_tags(cls, value: list[str]) -> list[str]:
        if any(tag not in TAGS for tag in value):
            raise ValueError("标签不在当前分类体系中")
        return list(dict.fromkeys(value))

    @field_validator("note")
    @classmethod
    def strip_note(cls, value: str) -> str:
        return value.strip()
