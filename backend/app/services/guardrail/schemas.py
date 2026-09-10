"""Shared guardrail result types."""

from typing import Literal

from pydantic import BaseModel, Field


class GuardViolation(BaseModel):
    code: str
    severity: Literal["error", "warning"]
    message: str
    source: str = "external"


class GuardHeader(BaseModel):
    allowed: bool = True
    violations: list[GuardViolation] = Field(default_factory=list)

    def error_count(self) -> int:
        return sum(1 for item in self.violations if item.severity == "error")

    def warning_count(self) -> int:
        return sum(1 for item in self.violations if item.severity == "warning")
