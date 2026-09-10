"""Model output guard: validate structured fields before they enter the flow."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.services.guardrail.schemas import GuardViolation


class ModelGuardResult(BaseModel):
    provider: str = ""
    model: str = ""
    valid: bool = True
    error_count: int = 0
    warning_count: int = 0
    violations: list[GuardViolation] = Field(default_factory=list)


ABSOLUTE_SAFE_PHRASES = (
    "无安全隐患",
    "没有安全隐患",
    "未发现安全隐患",
    "不存在安全隐患",
    "无任何安全隐患",
    "确认安全",
    "判定为安全",
    "可以判定为安全",
    "现场安全",
    "全部安全",
)


def validate_model_analysis(
    analysis: dict[str, Any] | None,
    *,
    provider: str = "",
    model: str = "",
) -> ModelGuardResult:
    violations: list[GuardViolation] = []
    if not isinstance(analysis, dict) or not analysis:
        violations.append(
            GuardViolation(
                code="empty_model_output",
                severity="error",
                message="模型未返回任何结构化输出",
                source="model_output",
            )
        )
    else:
        vision_confidence = analysis.get("vision_confidence")
        if vision_confidence is None or not isinstance(vision_confidence, (int, float)):
            violations.append(
                GuardViolation(
                    code="vision_confidence_missing",
                    severity="error",
                    message="缺少有效的 vision_confidence",
                    source="model_output",
                )
            )
        elif not 0 <= float(vision_confidence) <= 1:
            violations.append(
                GuardViolation(
                    code="confidence_out_of_range",
                    severity="error",
                    message="vision_confidence 超出 0-1 范围",
                    source="model_output",
                )
            )
        hazards = analysis.get("hazards") or []
        hints = analysis.get("hazard_hints") or []
        if not hazards and not hints:
            sample = " ".join(
                [
                    str(analysis.get("scene_summary") or ""),
                    *[str(item) for item in analysis.get("observations") or []],
                ]
            )
            matched = next(
                (phrase for phrase in ABSOLUTE_SAFE_PHRASES if phrase in sample),
                "",
            )
            if matched:
                violations.append(
                    GuardViolation(
                        code="unsolicited_safety_verdict",
                        severity="warning",
                        message=f"模型在本应输出隐患证据的位置给出了绝对化安全表述：{matched}，需人工复核",
                        source="model_output",
                    )
                )
            violations.append(
                GuardViolation(
                    code="empty_finding_output",
                    severity="warning",
                    message="模型未输出任何隐患项或隐患线索",
                    source="model_output",
                )
            )
        for index, item in enumerate(hazards):
            if not isinstance(item, dict):
                violations.append(
                    GuardViolation(
                        code="hazard_not_object",
                        severity="error",
                        message=f"hazards[{index}] 不是对象",
                        source="model_output",
                    )
                )
                continue
            if not str(item.get("hazard_type") or "").strip():
                violations.append(
                    GuardViolation(
                        code="hazard_type_missing",
                        severity="error",
                        message=f"hazards[{index}] 缺少 hazard_type",
                        source="model_output",
                    )
                )
            severity = item.get("severity")
            if severity is not None and (
                not isinstance(severity, (int, float)) or not 1 <= int(severity) <= 3
            ):
                violations.append(
                    GuardViolation(
                        code="severity_out_of_range",
                        severity="error",
                        message=f"hazards[{index}].severity 超出 1-3",
                        source="model_output",
                    )
                )
            confidence = item.get("confidence")
            if confidence is not None and (
                not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1
            ):
                violations.append(
                    GuardViolation(
                        code="finding_confidence_out_of_range",
                        severity="error",
                        message=f"hazards[{index}].confidence 超出 0-1",
                        source="model_output",
                    )
                )
        if analysis.get("schema_valid") is False:
            violations.append(
                GuardViolation(
                    code="normalized_output_corrected",
                    severity="warning",
                    message="模型输出被标准化修正过，请关注 validation_warnings",
                    source="model_output",
                )
            )
    error_count = sum(1 for item in violations if item.severity == "error")
    warning_count = len(violations) - error_count
    return ModelGuardResult(
        provider=provider,
        model=model,
        valid=error_count == 0,
        error_count=error_count,
        warning_count=warning_count,
        violations=violations,
    )
