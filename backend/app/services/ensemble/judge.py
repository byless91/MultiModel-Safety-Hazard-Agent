"""Ensemble Judge: deterministic merge of model findings into final conclusions."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.services.ensemble.disagreement import DisagreementResult
from app.services.ensemble.standardize import StandardizedModelResult
from app.services.evidence import judge_evidence


def _merge_unique(target: list[str], source: list[str]) -> None:
    for item in source:
        if item and item not in target:
            target.append(item)


def _as_risk_dict(risk_result: Any) -> dict[str, Any] | None:
    if risk_result is None:
        return None
    if isinstance(risk_result, dict):
        return risk_result
    dump = getattr(risk_result, "model_dump", None)
    if callable(dump):
        return dump()
    return dict(risk_result)


class FinalFinding(BaseModel):
    finding_id: str
    category: str
    description: str = ""
    final_severity: int | None = Field(default=None, ge=1, le=3)
    final_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    observed_facts: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    model_support: list[str] = Field(default_factory=list)
    locations: list[dict[str, Any]] = Field(default_factory=list)
    model_findings: list[dict[str, Any]] = Field(default_factory=list)
    source: str = "single_model"
    risk_score: float | None = None
    risk_level: str | None = None
    evidence_status: str = "pending"
    evidence_ids: list[str] = Field(default_factory=list)
    support_score: float | None = None
    unsupported_claims: list[str] = Field(default_factory=list)


class EnsembleJudgeResult(BaseModel):
    mode: str = "single"
    final_findings: list[FinalFinding] = Field(default_factory=list)
    final_severity: int | None = None
    confidence: float = 0.0
    agreement_score: float = 0.0
    agreement_available: bool = False
    need_human_review: bool = False
    review_reasons: list[str] = Field(default_factory=list)
    decision_summary: str = ""
    risk_score: int | None = None
    risk_level: str | None = None
    rule_version: str | None = None
    version: str = "v1"


def _as_models(
    standardized_results: list[dict[str, Any]] | list[StandardizedModelResult],
) -> list[StandardizedModelResult]:
    models: list[StandardizedModelResult] = []
    for item in standardized_results:
        if isinstance(item, StandardizedModelResult):
            models.append(item)
        elif isinstance(item, dict):
            models.append(StandardizedModelResult.model_validate(item))
    return models


def _location_signature(location: dict[str, Any] | None) -> tuple:
    if not isinstance(location, dict):
        return ()
    bbox = location.get("bbox") if isinstance(location.get("bbox"), list) else ()
    return (
        str(location.get("image_id") or ""),
        tuple(bbox),
        str(location.get("location_text") or ""),
    )


def _aggregate_findings(
    models: list[StandardizedModelResult],
) -> list[FinalFinding]:
    groups: dict[str, dict[str, Any]] = {}
    order: list[Any] = []
    for model in models:
        if model.status not in ("success", "mock_fallback"):
            continue
        for finding in model.findings:
            base_key = finding.canonical_category or finding.raw_hazard_type or finding.finding_id
            key = (base_key, _location_signature(finding.location))
            if key not in groups:
                groups[key] = {
                    "category": base_key,
                    "descriptions": [],
                    "severities": [],
                    "confidences": [],
                    "facts": [],
                    "uncertainties": [],
                    "families": [],
                    "statuses": [],
                    "locations": [],
                    "model_findings": [],
                    "hint_derived": False,
                }
                order.append(key)
            group = groups[key]
            group["descriptions"].append(finding.description)
            if finding.severity is not None:
                group["severities"].append(finding.severity)
            group["confidences"].append(finding.confidence)
            group["facts"].extend(finding.observed_facts)
            group["uncertainties"].extend(finding.uncertainties)
            group["families"].append(model.family)
            group["statuses"].append(model.status)
            if isinstance(finding.location, dict):
                group["locations"].append(finding.location)
            group["model_findings"].append(
                {
                    "family": model.family,
                    "status": model.status,
                    "finding_id": finding.finding_id,
                    "canonical_category": finding.canonical_category,
                    "raw_hazard_type": finding.raw_hazard_type,
                    "description": finding.description,
                    "severity": finding.severity,
                    "confidence": finding.confidence,
                    "observed_facts": list(finding.observed_facts),
                    "uncertainties": list(finding.uncertainties),
                    "location": finding.location,
                    "source": finding.source,
                }
            )
            group["hint_derived"] = group["hint_derived"] or finding.source == "hint_derived"

    results: list[FinalFinding] = []
    for key in order:
        group = groups[key]
        category = group["category"]
        families = list(dict.fromkeys(group["families"]))
        statuses = list(dict.fromkeys(group["statuses"]))
        descriptions = [item for item in group["descriptions"] if item]
        if len(families) >= 2:
            source = "ensemble"
        elif "mock_fallback" in statuses:
            source = "mock_fallback"
        elif group["hint_derived"]:
            source = "hint_derived"
        else:
            source = "single_model"
        results.append(
            FinalFinding(
                finding_id=category,
                category=category,
                description="；".join(descriptions)[:300],
                final_severity=max(group["severities"]) if group["severities"] else None,
                final_confidence=round(max(group["confidences"]), 3),
                observed_facts=list(dict.fromkeys(group["facts"])),
                uncertainties=list(dict.fromkeys(group["uncertainties"])),
                model_support=families,
                locations=group["locations"],
                model_findings=group["model_findings"],
                source=source,
            )
        )
    return results


def _build_summary(
    mode: str,
    findings: list[FinalFinding],
    final_severity: int | None,
    agreement_score: float,
    agreement_available: bool,
) -> str:
    if mode == "fallback":
        return "模型调用降级为 Mock，结果仅作参考，必须人工复核。"
    if not findings:
        return "当前模型未发现明显隐患，建议结合现场人工检查确认。"
    categories = "、".join(item.category for item in findings[:3])
    severity_text = f"，严重度 {final_severity}/3" if final_severity is not None else ""
    agreement_text = (
        f"，模型一致性 {round(agreement_score * 100)}%"
        if agreement_available
        else "，未进行多模型交叉验证"
    )
    return f"综合研判存在“{categories}”类隐患{severity_text}{agreement_text}。"


def judge_ensemble(
    standardized_results: list[dict[str, Any]] | list[StandardizedModelResult],
    disagreement: DisagreementResult | dict[str, Any],
    *,
    risk_result: dict[str, Any] | None = None,
    evidence: list[dict[str, Any]] | None = None,
) -> EnsembleJudgeResult:
    """Merge all available signals into a structured final assessment.

    ``risk_result`` and ``evidence`` are consumed by the judge when provided:
    risk score and review suggestion enter the decision, and evidence support
    is checked per finding before the final assessment is returned.
    """
    models = _as_models(standardized_results)
    disagree = (
        disagreement
        if isinstance(disagreement, DisagreementResult)
        else DisagreementResult.model_validate(disagreement)
    )
    findings = _aggregate_findings(models)
    risk = _as_risk_dict(risk_result)
    evidence_result = (
        judge_evidence([item.model_dump() for item in findings], evidence)
        if evidence is not None
        else None
    )
    if evidence_result:
        status_by_id = {item.finding_id: item for item in evidence_result.findings}
        for finding in findings:
            evidence_item = status_by_id.get(finding.finding_id)
            if evidence_item:
                finding.evidence_status = (
                    "supported"
                    if evidence_item.supported and evidence_item.visual_evidence_ok
                    else "insufficient"
                )
                finding.support_score = evidence_item.support_score
                finding.evidence_ids = evidence_item.evidence_ids
                finding.unsupported_claims = evidence_item.unsupported_claims
    if risk:
        for finding in findings:
            finding.risk_score = risk.get("risk_score")
            finding.risk_level = risk.get("risk_level")
    max_model_confidence = max((item.final_confidence for item in findings), default=0.0)
    if max_model_confidence > 0 and disagree.agreement_available:
        confidence = round(
            min(0.99, max_model_confidence * 0.8 + disagree.agreement_score * 0.2),
            3,
        )
    else:
        confidence = round(max_model_confidence, 3)

    need_review = disagree.need_human_review
    reasons = list(disagree.reasons)
    if risk and risk.get("review_suggestion"):
        need_review = True
        _merge_unique(reasons, ["风险规则引擎判定为高风险，建议人工复核"])
    if evidence_result and evidence_result.needs_human_review:
        need_review = True
        if evidence_result.unsupported_claims:
            _merge_unique(reasons, ["法规证据不足：部分结论缺少法规依据，需人工复核"])
        else:
            _merge_unique(reasons, ["证据判定存在不确定性，需人工复核"])
    final_severity = (
        max(
            (item.final_severity for item in findings if item.final_severity is not None),
            default=None,
        )
        if findings
        else None
    )
    if not findings:
        need_review = True
        if "模型调用降级为 Mock，无法进行交叉验证" not in reasons:
            reasons.append("模型未检出明显隐患，需人工确认后再放行")

    return EnsembleJudgeResult(
        mode=disagree.mode,
        final_findings=findings,
        final_severity=final_severity,
        confidence=confidence,
        agreement_score=disagree.agreement_score,
        agreement_available=disagree.agreement_available,
        need_human_review=need_review,
        review_reasons=reasons if need_review else [],
        risk_score=risk.get("risk_score") if risk else None,
        risk_level=risk.get("risk_level") if risk else None,
        rule_version=risk.get("rule_version") if risk else None,
        decision_summary=_build_summary(
            disagree.mode,
            findings,
            final_severity,
            disagree.agreement_score,
            disagree.agreement_available,
        ),
    )
