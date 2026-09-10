"""Unified human-in-the-loop decision across all guard and judge signals."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HumanReviewDecision(BaseModel):
    need_human_review: bool = False
    review_reasons: list[str] = Field(default_factory=list)
    triggers: dict[str, bool] = Field(default_factory=dict)


SAFE_CLAIM_PHRASES = (
    "无安全隐患",
    "没有安全隐患",
    "未发现安全隐患",
    "不存在安全隐患",
    "无安全风险",
    "没有安全风险",
    "现场安全",
    "全部安全",
    "未发现异常",
)

IMAGE_QUALITY_THRESHOLD = 0.55


def _merge_reasons(existing: list[str], new: list[str]) -> None:
    for item in new:
        if item and item not in existing:
            existing.append(item)


def _asserted_safe_phrases(state: dict[str, Any]) -> list[str]:
    parts = [str(state.get("description") or "")]
    ocr_parts = state.get("ocr_texts") or []
    if isinstance(ocr_parts, str):
        ocr_parts = [ocr_parts]
    parts.extend(str(item) for item in ocr_parts)
    joined = " ".join(parts)
    return [phrase for phrase in SAFE_CLAIM_PHRASES if phrase in joined]


def decide_human_review(state: dict[str, Any]) -> HumanReviewDecision:
    reasons: list[str] = []
    triggers: dict[str, bool] = {}

    disagreement = state.get("disagreement") or {}
    if disagreement.get("need_human_review"):
        triggers["disagreement"] = True
        _merge_reasons(
            reasons,
            [str(item) for item in disagreement.get("reasons", [])],
        )

    judge = state.get("ensemble_judge") or {}
    if judge.get("need_human_review"):
        triggers["ensemble_judge"] = True
        _merge_reasons(
            reasons,
            [str(item) for item in judge.get("review_reasons", [])],
        )

    risk = state.get("risk_result") or {}
    if risk.get("review_suggestion"):
        triggers["risk_engine"] = True
        risk_level = str(risk.get("risk_level") or "")
        if risk_level == "high":
            reason = "风险规则引擎判定为高风险，建议人工复核"
        elif risk_level == "medium":
            reason = "风险规则引擎判定为中风险，建议人工复核确认"
        else:
            reason = "风险规则计算存在不确定性（未明确判定为高风险），建议人工复核"
        _merge_reasons(reasons, [reason])

    final_severity = judge.get("final_severity") if isinstance(judge, dict) else None
    risk_level = str((state.get("risk_result") or {}).get("risk_level") or "")
    if final_severity == 3 and risk_level == "low":
        triggers["risk_model_conflict"] = True
        _merge_reasons(reasons, ["模型严重度与风险规则结论严重冲突，需人工复核"])
    elif final_severity == 1 and risk_level == "high":
        triggers["risk_model_conflict"] = True
        _merge_reasons(reasons, ["模型严重度与风险规则结论严重冲突，需人工复核"])

    vision_confidence = state.get("vision_confidence")
    if vision_confidence is not None and float(vision_confidence) < IMAGE_QUALITY_THRESHOLD:
        triggers["image_quality"] = True
        _merge_reasons(
            reasons,
            ["图片质量或视觉信息不足（vision_confidence 偏低），需人工复核"],
        )

    findings = judge.get("final_findings") if isinstance(judge, dict) else []
    if not findings:
        asserted = _asserted_safe_phrases(state)
        if asserted:
            triggers["negated_claim"] = True
            _merge_reasons(
                reasons,
                [
                    "输入/OCR 宣称“"
                    + asserted[0]
                    + "”但模型未检出隐患，禁止自动通过，需人工复核"
                ],
            )

    evidence = state.get("evidence_judge") or {}
    if evidence.get("needs_human_review"):
        triggers["evidence_judge"] = True
        if evidence.get("unsupported_claims"):
            _merge_reasons(reasons, ["法规证据不足：部分结论缺少法规依据，需人工复核"])
        elif evidence.get("findings"):
            _merge_reasons(reasons, ["证据判定存在不确定性，需人工复核"])

    model_guard = state.get("model_guard") or {}
    if any(
        item.get("code") == "unsolicited_safety_verdict"
        for item in (model_guard.get("violations") or [])
    ):
        triggers["model_safety_verdict"] = True
        _merge_reasons(reasons, ["模型输出了绝对化安全结论，需人工复核"])
    if model_guard and model_guard.get("valid") is False:
        triggers["model_guard"] = True
        _merge_reasons(reasons, ["模型输出未通过结构校验，需人工复核"])

    confidence = state.get("confidence")
    if confidence is not None and float(confidence) < 0.8:
        triggers["low_confidence"] = True
        _merge_reasons(
            reasons,
            [f"综合置信度偏低（{float(confidence):.2f}），需人工复核"],
        )

    fallback = bool(state.get("analysis_fallback")) or any(
        item.get("status") == "mock_fallback"
        for item in (state.get("model_results") or [])
    )
    if fallback:
        triggers["fallback"] = True
        _merge_reasons(reasons, ["模型调用降级为 Mock，需人工复核"])

    return HumanReviewDecision(
        need_human_review=bool(reasons),
        review_reasons=reasons,
        triggers=triggers,
    )
