"""Standardize per-model outputs into comparable canonical findings."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.services.ensemble.categories import canonicalize_hazard_type


class StandardizedFinding(BaseModel):
    finding_id: str
    canonical_category: str | None = None
    raw_hazard_type: str
    description: str = ""
    severity: int | None = Field(default=None, ge=1, le=3)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    observed_facts: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    location: dict[str, Any] | None = None
    source: str = "model_output"


class StandardizedModelResult(BaseModel):
    provider: str = ""
    family: str = ""
    model: str = ""
    status: str = "failed"
    vision_confidence: float = 0.0
    hazard_hints: list[str] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)
    findings: list[StandardizedFinding] = Field(default_factory=list)


def _as_text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _merge_strings(first: list[str], second: list[str]) -> list[str]:
    result = list(first)
    for item in second:
        if item not in result:
            result.append(item)
    return result


def _dedupe_findings(findings: list[StandardizedFinding]) -> list[StandardizedFinding]:
    unique: dict[tuple, StandardizedFinding] = {}
    order: list[tuple] = []
    for finding in findings:
        location = finding.location or {}
        bbox = location.get("bbox") if isinstance(location.get("bbox"), list) else ()
        key = (
            finding.canonical_category or finding.raw_hazard_type or finding.finding_id,
            str(location.get("image_id") or ""),
            tuple(bbox),
            str(location.get("location_text") or ""),
            tuple(finding.observed_facts),
            tuple(finding.uncertainties),
        )
        if key not in unique:
            unique[key] = finding
            order.append(key)
            continue
        existing = unique[key]
        if finding.description and finding.description not in existing.description:
            existing.description = (
                f"{existing.description}；{finding.description}" if existing.description else finding.description
            )
        if existing.severity is None and finding.severity is not None:
            existing.severity = finding.severity
        existing.confidence = max(existing.confidence, finding.confidence)
    return [unique[key] for key in order]


def _clamp_severity(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return min(3, max(1, int(value)))


def standardize_analysis(
    analysis: dict[str, Any] | None,
    *,
    provider: str,
    family: str,
    model: str,
    status: str,
) -> StandardizedModelResult:
    if not analysis:
        return StandardizedModelResult(
            provider=provider,
            family=family,
            model=model,
            status=status,
        )

    findings: list[StandardizedFinding] = []
    for raw in analysis.get("hazards") or []:
        if not isinstance(raw, dict):
            continue
        raw_type = str(raw.get("hazard_type") or "").strip()
        canonical = canonicalize_hazard_type(raw_type)
        findings.append(
            StandardizedFinding(
                finding_id=canonical or raw_type or "未命名隐患",
                canonical_category=canonical,
                raw_hazard_type=raw_type,
                description=str(raw.get("description") or ""),
                severity=_clamp_severity(raw.get("severity")),
                confidence=float(raw.get("confidence") or 0.0),
                observed_facts=_as_text_list(raw.get("observed_facts")),
                uncertainties=_as_text_list(raw.get("uncertainties")),
                location=raw.get("location") if isinstance(raw.get("location"), dict) else None,
                source="model_output",
            )
        )

    if not findings:
        vision_confidence = float(analysis.get("vision_confidence") or 0.0)
        observations = _as_text_list(analysis.get("observations"))
        for hint in _as_text_list(analysis.get("hazard_hints")):
            canonical = canonicalize_hazard_type(hint)
            findings.append(
                StandardizedFinding(
                    finding_id=canonical or hint or "未命名隐患",
                    canonical_category=canonical,
                    raw_hazard_type=hint,
                    description=f"模型提示可能存在“{hint}”类隐患，但未给出结构化事实",
                    confidence=vision_confidence,
                    observed_facts=observations,
                    uncertainties=["严重度与具体位置未由模型输出"],
                    source="hint_derived",
                )
            )

    return StandardizedModelResult(
        provider=provider,
        family=family,
        model=model,
        status=status,
        vision_confidence=float(analysis.get("vision_confidence") or 0.0),
        hazard_hints=_as_text_list(analysis.get("hazard_hints")),
        validation_warnings=_as_text_list(analysis.get("validation_warnings")),
        findings=_dedupe_findings(findings),
    )


def standardize_model_runs(runs: list[dict[str, Any]]) -> list[StandardizedModelResult]:
    results: list[StandardizedModelResult] = []
    for run in runs:
        results.append(
            standardize_analysis(
                run.get("analysis") if isinstance(run.get("analysis"), dict) else None,
                provider=str(run.get("provider") or ""),
                family=str(run.get("family") or ""),
                model=str(run.get("model") or ""),
                status=str(run.get("status") or "failed"),
            )
        )
    return results
