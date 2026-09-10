"""Deterministic completion assessment over the provider's rectification compare."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


RULE_VERSION = "rectification-assessment-v1"
RESOLVED_THRESHOLD = 0.8


class RectificationAssessment(BaseModel):
    completion_score: float | None = None
    completion_confidence: float = 0.0
    verdict: str = "insufficient_evidence"
    review_required: bool = True
    triggered_rules: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    provider_ok: bool = False
    rule_version: str = RULE_VERSION


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def _comparison_counts(
    comparison: dict[str, Any] | None,
) -> tuple[int, int, int]:
    if not isinstance(comparison, dict):
        return 0, 0, 0
    original_count = int(comparison.get("original_count") or 0)
    rectification_count = int(comparison.get("rectification_count") or 0)
    pair_count = int(comparison.get("pair_count") or 0)
    return original_count, rectification_count, pair_count


def assess_rectification_completion(
    *,
    provider_result: dict[str, Any] | None = None,
    comparison: dict[str, Any] | None = None,
    provider_failed: bool = False,
) -> RectificationAssessment:
    """Turn raw AI compare output into a conservative, explainable verdict."""
    original_count, rectification_count, pair_count = _comparison_counts(
        comparison
    )
    unmatched = (
        max(0, original_count - pair_count)
        + max(0, rectification_count - pair_count)
    )
    assessment = RectificationAssessment(provider_ok=not provider_failed)

    if provider_failed:
        assessment.triggered_rules.append("provider_failed")
        assessment.reasons.append("AI 前后对比服务不可用，需人工复核")
        return assessment

    if rectification_count == 0:
        assessment.triggered_rules.append("missing_after_photos")
        assessment.reasons.append("缺少整改后照片，无法评估整改完成度")
        return assessment

    raw_score = (
        provider_result.get("completion_score")
        if isinstance(provider_result, dict)
        else None
    )
    try:
        score = _clamp(float(raw_score), 0.0, 1.0)
    except (TypeError, ValueError):
        score = None
    if score is None:
        assessment.triggered_rules.append("missing_score")
        assessment.reasons.append("AI 未返回有效完成度分数，需人工复核")
        return assessment

    assessment.completion_score = round(score, 3)
    issues = [
        str(item).strip()
        for item in (provider_result.get("issues") or [])
        if str(item).strip()
    ]

    confidence = 0.9
    if original_count == 0:
        confidence -= 0.15
        assessment.triggered_rules.append("missing_before_photos")
        assessment.reasons.append("缺少整改前照片，AI 前后对比置信度受限")
        assessment.review_required = True
    if unmatched > 0:
        confidence -= 0.1
        assessment.triggered_rules.append("unmatched_image_counts")
        assessment.reasons.append(
            "整改前/整改后图片数量不一致，部分图片无法成对比对"
        )
        assessment.review_required = True
    if issues:
        confidence -= 0.2
        assessment.triggered_rules.append("unresolved_issues")
        assessment.reasons.append(
            "AI 输出仍包含遗留问题描述，需人工复核"
        )
        assessment.review_required = True

    assessment.completion_confidence = round(
        _clamp(confidence, 0.0, 1.0),
        3,
    )

    if score >= RESOLVED_THRESHOLD:
        assessment.triggered_rules.append("score_above_threshold")
        assessment.verdict = "resolved_recommended"
        assessment.reasons.append(
            "AI 完成度达到阈值且无直接冲突信号，建议人工确认后关闭"
        )
    else:
        assessment.triggered_rules.append("score_below_threshold")
        assessment.verdict = "not_resolved"
        assessment.reasons.append(
            "AI 完成度低于阈值，需继续整改并重新提交"
        )

    if issues and score >= RESOLVED_THRESHOLD:
        assessment.verdict = "needs_review"
        assessment.reasons.insert(
            0,
            "AI 完成度较高但报告了遗留问题，结论冲突，需人工复核",
        )
    if original_count == 0 and assessment.verdict == "resolved_recommended":
        assessment.verdict = "needs_review"
        assessment.reasons.insert(
            0,
            "缺少整改前照片，无法仅凭整改后照片判定完成，需人工复核",
        )
    if unmatched > 0 and assessment.verdict == "resolved_recommended":
        assessment.verdict = "needs_review"
        assessment.reasons.insert(
            0,
            "存在未配对的整改前后照片，无法确认整体完成度，需人工复核",
        )
    if (
        assessment.verdict == "resolved_recommended"
        and "missing_before_photos" not in assessment.triggered_rules
        and "unmatched_image_counts" not in assessment.triggered_rules
        and "unresolved_issues" not in assessment.triggered_rules
    ):
        assessment.review_required = False
    return assessment
