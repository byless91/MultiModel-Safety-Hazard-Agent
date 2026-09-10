"""Containers for one multi-model analysis run."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ModelRunResult(BaseModel):
    provider: str = ""
    family: str = ""
    model: str = ""
    model_version: str = ""
    status: str = "pending"
    error_type: str = ""
    error_message: str = ""
    latency_ms: float = 0.0
    retry_count: int = 0
    analysis: dict[str, Any] | None = None


class MultiModelResult(BaseModel):
    ensemble_mode: str = "mock"
    results: list[ModelRunResult] = Field(default_factory=list)
    primary: ModelRunResult
    succeeded: int = 0
    failed: int = 0
    total_latency_ms: float = 0.0

    def to_state(self) -> dict[str, Any]:
        return {
            "ensemble_mode": self.ensemble_mode,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "total_latency_ms": self.total_latency_ms,
            "primary": self.primary.model_dump(),
            "results": [item.model_dump() for item in self.results],
        }
