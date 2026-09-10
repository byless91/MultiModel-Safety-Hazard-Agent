"""Structured and validated schema for provider model outputs.

Every provider returns a plain dict for backward compatibility with the
existing workflow nodes, but the dict is produced from a validated
``ModelAnalysis`` so that both Mock and real model outputs share one schema.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator


class HazardLocation(BaseModel):
    image_id: str | None = None
    bbox: list[float] | None = None
    location_text: str | None = None

    @field_validator("bbox")
    @classmethod
    def bbox_has_four_numbers(cls, value: list[float] | None) -> list[float] | None:
        if value is None:
            return None
        if len(value) != 4:
            raise ValueError("bbox 必须为 [x1, y1, x2, y2]")
        if any(not isinstance(item, (int, float)) for item in value):
            raise ValueError("bbox 必须为数值")
        return [float(item) for item in value]


class HazardFinding(BaseModel):
    hazard_type: str
    description: str = ""
    severity: int = Field(default=2, ge=1, le=3, description="3 表示最严重")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    observed_facts: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    location: HazardLocation | None = None


class ModelAnalysis(BaseModel):
    provider: str = "unknown"
    family: str = "unknown"
    model: str = "unknown"
    model_version: str = ""
    vision_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    scene_summary: str = ""
    observations: list[str] = Field(default_factory=list)
    hazard_hints: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    hazards: list[HazardFinding] = Field(default_factory=list)
    rule: dict[str, Any] = Field(default_factory=dict)
    rule_score: float = Field(default=0.0, ge=0.0, le=1.0)
    llm_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    validation_warnings: list[str] = Field(default_factory=list)

    def to_workflow_dict(self) -> dict[str, Any]:
        """Legacy-compatible dict consumed by existing workflow nodes."""
        data: dict[str, Any] = {
            "provider": self.provider,
            "family": self.family,
            "model": self.model,
            "model_version": self.model_version,
            "scene_summary": self.scene_summary,
            "observations": self.observations,
            "hazard_hints": self.hazard_hints,
            "keywords": self.keywords,
            "hazards": [item.model_dump() for item in self.hazards],
            "vision_confidence": self.vision_confidence,
            "rule": self.rule,
            "rule_score": self.rule_score,
            "validation_warnings": self.validation_warnings,
            "schema_valid": not self.validation_warnings,
        }
        if self.llm_confidence is not None:
            data["llm_confidence"] = self.llm_confidence
        return data


def _clamp_number(
    value: Any,
    default: float,
    low: float,
    high: float,
    label: str,
    warnings: list[str],
) -> float:
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        warnings.append(f"{label} 非数值，已使用默认值 {default}")
        return default
    if not (low <= number <= high):
        warnings.append(f"{label} 超出 {low}-{high}，已夹紧")
        return min(high, max(low, number))
    return number


def _as_string_list(value: Any, label: str, warnings: list[str]) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    warnings.append(f"{label} 不是字符串数组，已忽略")
    return []


def _sanitize_hazard(item: Any, index: int, warnings: list[str]) -> HazardFinding | None:
    if not isinstance(item, dict):
        warnings.append(f"hazards[{index}] 不是对象，已忽略")
        return None
    hazard_type = str(item.get("hazard_type") or "").strip()
    if not hazard_type:
        hazard_type = "待确认隐患"
        warnings.append(f"hazards[{index}] 缺少 hazard_type，使用占位值")
    severity = int(
        _clamp_number(
            item.get("severity"),
            2.0,
            1.0,
            3.0,
            f"hazards[{index}].severity",
            warnings,
        )
    )
    confidence = _clamp_number(
        item.get("confidence"),
        0.5,
        0.0,
        1.0,
        f"hazards[{index}].confidence",
        warnings,
    )
    location: HazardLocation | None = None
    location_raw = item.get("location")
    if isinstance(location_raw, dict):
        bbox = location_raw.get("bbox")
        if bbox is not None and (not isinstance(bbox, (list, tuple)) or len(bbox) != 4):
            warnings.append(f"hazards[{index}].location.bbox 非法，已忽略")
            location_raw = {key: value for key, value in location_raw.items() if key != "bbox"}
        usable = {key: value for key, value in location_raw.items() if value not in (None, "")}
        if usable:
            try:
                location = HazardLocation(**location_raw)
            except ValidationError as exc:
                warnings.append(f"hazards[{index}].location 校验失败，已忽略：{str(exc)[:100]}")
                location = None
    return HazardFinding(
        hazard_type=hazard_type,
        description=str(item.get("description") or ""),
        severity=severity,
        confidence=confidence,
        observed_facts=_as_string_list(
            item.get("observed_facts"),
            f"hazards[{index}].observed_facts",
            warnings,
        ),
        uncertainties=_as_string_list(
            item.get("uncertainties"),
            f"hazards[{index}].uncertainties",
            warnings,
        ),
        location=location,
    )


def normalize_analysis(
    raw: dict[str, Any],
    *,
    provider: str = "unknown",
    family: str = "unknown",
    model: str = "unknown",
    model_version: str = "",
) -> ModelAnalysis:
    """Sanitize raw provider output into a validated ModelAnalysis."""
    warnings: list[str] = []
    vision_confidence = _clamp_number(
        raw.get("vision_confidence"),
        0.0,
        0.0,
        1.0,
        "vision_confidence",
        warnings,
    )
    llm_raw = raw.get("llm_confidence")
    llm_confidence = (
        None
        if llm_raw is None
        else _clamp_number(llm_raw, 0.0, 0.0, 1.0, "llm_confidence", warnings)
    )
    trust_rule = provider == "mock"
    rule_score_raw = raw.get("rule_score") if trust_rule else 0.0
    rule_score = _clamp_number(rule_score_raw, 0.0, 0.0, 1.0, "rule_score", warnings)

    hazards: list[HazardFinding] = []
    for index, item in enumerate(raw.get("hazards") or []):
        finding = _sanitize_hazard(item, index, warnings)
        if finding is not None:
            hazards.append(finding)

    rule = raw.get("rule") if trust_rule and isinstance(raw.get("rule"), dict) else {}
    return ModelAnalysis(
        provider=provider,
        family=family,
        model=model,
        model_version=model_version,
        vision_confidence=vision_confidence,
        scene_summary=str(raw.get("scene_summary") or ""),
        observations=_as_string_list(raw.get("observations"), "observations", warnings),
        hazard_hints=_as_string_list(raw.get("hazard_hints"), "hazard_hints", warnings),
        keywords=_as_string_list(raw.get("keywords"), "keywords", warnings),
        hazards=hazards,
        rule=rule,
        rule_score=rule_score,
        llm_confidence=llm_confidence,
        validation_warnings=warnings,
    )
