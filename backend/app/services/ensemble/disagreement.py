"""Deterministic disagreement detection over standardized model results."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from typing import Any

from pydantic import BaseModel, Field

from app.services.ensemble.standardize import (
    StandardizedFinding,
    StandardizedModelResult,
)

NEGATION_PREFIXES = ("未发现", "未见", "没有", "无", "不存在", "无法确认")


class FindingPair(BaseModel):
    category: str
    family_a: str
    family_b: str
    severity_a: int | None = None
    severity_b: int | None = None
    confidence_a: float = 0.0
    confidence_b: float = 0.0
    severity_difference: int | None = None
    category_score: float = 1.0
    severity_score: float = 1.0
    factual_conflict: bool = False


class DisagreementResult(BaseModel):
    mode: str = "single"
    agreement_available: bool = False
    agreement_score: float = 0.0
    category_agreement: bool = False
    severity_difference: int | None = None
    critical_conflict: bool = False
    need_human_review: bool = False
    reasons: list[str] = Field(default_factory=list)
    pairs: list[FindingPair] = Field(default_factory=list)
    model_count: int = 0
    compared_models: list[str] = Field(default_factory=list)


@dataclass
class _PairOutcome:
    pair: FindingPair
    category_score: float
    severity_score: float
    fact_score: float
    max_severity_difference: int | None
    critical: bool


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


def _has_negation(finding: StandardizedFinding) -> bool:
    return any(fact.startswith(NEGATION_PREFIXES) for fact in finding.observed_facts)


def _compare_pair(
    first: StandardizedModelResult,
    second: StandardizedModelResult,
) -> _PairOutcome:
    first_by_category: dict[str, list[StandardizedFinding]] = defaultdict(list)
    for finding in first.findings:
        if finding.canonical_category:
            first_by_category[finding.canonical_category].append(finding)
    second_by_category: dict[str, list[StandardizedFinding]] = defaultdict(list)
    for finding in second.findings:
        if finding.canonical_category:
            second_by_category[finding.canonical_category].append(finding)
    categories = sorted(set(first_by_category) | set(second_by_category))
    matched = len(set(first_by_category) & set(second_by_category))
    category_score = matched / len(categories) if categories else 1.0

    severity_scores: list[float] = []
    severity_diffs: list[int] = []
    factual_conflict = False
    lowest_confidence = 1.0
    for category in categories:
        lefts = first_by_category.get(category, [])
        rights = second_by_category.get(category, [])
        if not lefts or not rights:
            continue
        for left in lefts:
            for right in rights:
                lowest_confidence = min(lowest_confidence, left.confidence, right.confidence)
                if left.severity is not None and right.severity is not None:
                    difference = abs(left.severity - right.severity)
                    severity_diffs.append(difference)
                    severity_scores.append(1.0 - min(2, difference) / 2.0)
                else:
                    severity_scores.append(1.0)
                left_negated = _has_negation(left)
                right_negated = _has_negation(right)
                if left_negated != right_negated:
                    factual_conflict = True

    first_found = bool(first.findings)
    second_found = bool(second.findings)
    critical = first_found != second_found
    severity_difference = max(severity_diffs) if severity_diffs else None
    severity_score = sum(severity_scores) / len(severity_scores) if severity_scores else 1.0
    fact_score = 0.0 if (critical or factual_conflict) else 1.0

    return _PairOutcome(
        pair=FindingPair(
            category="、".join(categories) or "无标准类别",
            family_a=first.family,
            family_b=second.family,
            severity_a=first.findings[0].severity if first.findings else None,
            severity_b=second.findings[0].severity if second.findings else None,
            confidence_a=first.vision_confidence,
            confidence_b=second.vision_confidence,
            severity_difference=severity_difference,
            category_score=round(category_score, 4),
            severity_score=round(severity_score, 4),
            factual_conflict=factual_conflict,
        ),
        category_score=category_score,
        severity_score=severity_score,
        fact_score=fact_score,
        max_severity_difference=severity_difference,
        critical=critical,
    )


def detect_disagreement(
    standardized_results: list[dict[str, Any]] | list[StandardizedModelResult],
    *,
    ensemble_mode: str = "mock",
) -> DisagreementResult:
    models = _as_models(standardized_results)
    configured = [model for model in models if model.status != "mock_fallback"]
    successful = [model for model in models if model.status == "success"]
    model_count = len(models)
    compared_models = [model.family for model in models]

    if any(model.status == "mock_fallback" for model in models) or ensemble_mode == "fallback":
        return DisagreementResult(
            mode="fallback",
            model_count=model_count,
            compared_models=compared_models,
            need_human_review=True,
            reasons=["模型调用降级为 Mock，无法进行交叉验证"],
        )

    if len(configured) <= 1:
        return DisagreementResult(
            mode="single",
            model_count=model_count,
            compared_models=compared_models,
            need_human_review=False,
            reasons=["当前仅配置单个模型，未进行多模型交叉验证"],
        )

    if len(successful) < 2:
        return DisagreementResult(
            mode="partial",
            model_count=model_count,
            compared_models=compared_models,
            need_human_review=True,
            reasons=["双模型配置下仅一个模型成功，无法交叉验证"],
        )

    outcomes = [_compare_pair(first, second) for first, second in combinations(successful, 2)]
    category_scores = [outcome.category_score for outcome in outcomes]
    severity_scores = [outcome.severity_score for outcome in outcomes]
    fact_scores = [outcome.fact_score for outcome in outcomes]
    category_agreement = sum(category_scores) / len(category_scores) >= 1.0
    agreement_score = (
        0.5 * (sum(category_scores) / len(category_scores))
        + 0.3 * (sum(severity_scores) / len(severity_scores))
        + 0.2 * (sum(fact_scores) / len(fact_scores))
    )
    severity_difference = max(
        (outcome.max_severity_difference for outcome in outcomes),
        default=None,
    )
    critical_conflict = any(outcome.critical for outcome in outcomes)
    any_factual_conflict = any(outcome.pair.factual_conflict for outcome in outcomes)

    reasons: list[str] = []
    if critical_conflict:
        reasons.append("关键事实冲突：一个模型检出隐患，另一个模型未检出")
    if any_factual_conflict:
        reasons.append("同一类别存在互相矛盾的关键事实描述")
    if not category_agreement:
        reasons.append("模型隐患类别不一致")
    if severity_difference is not None and severity_difference >= 1:
        if severity_difference == 1:
            reasons.append("模型风险等级存在 1 级分歧，建议人工复核")
        else:
            reasons.append(f"风险等级差异过大（差 {severity_difference} 级）")

    return DisagreementResult(
        mode="pair",
        agreement_available=True,
        agreement_score=round(min(1.0, max(0.0, agreement_score)), 4),
        category_agreement=category_agreement,
        severity_difference=severity_difference,
        critical_conflict=critical_conflict or any_factual_conflict,
        need_human_review=bool(reasons),
        reasons=reasons,
        pairs=[outcome.pair for outcome in outcomes],
        model_count=model_count,
        compared_models=compared_models,
    )
