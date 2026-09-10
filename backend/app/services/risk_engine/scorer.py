"""Risk scoring: observed facts and categories become a 0-100 risk score."""

from __future__ import annotations

from typing import Any

from app.services.risk_engine.rules import (
    CATEGORY_BASE_SCORES,
    DEFAULT_BASE_SCORES,
    EXPOSURE_KEYWORDS,
    HIGH_BAND,
    IMMEDIATE_DANGER_KEYWORDS,
    LOW_BAND,
    RULE_VERSION,
)
from app.services.risk_engine.schemas import RiskAssessment


def _clamp_score(value: float) -> int:
    return min(100, max(0, int(round(value))))


def _level_from_score(score: int) -> str:
    if score >= HIGH_BAND:
        return "high"
    if score >= LOW_BAND:
        return "medium"
    return "low"


def _operational_level(score: int) -> int:
    if score >= HIGH_BAND:
        return 1
    if score >= LOW_BAND:
        return 2
    return 3


def _finding_fields(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    return {
        "category": getattr(item, "category", ""),
        "final_severity": getattr(item, "final_severity", None),
        "observed_facts": list(getattr(item, "observed_facts", []) or []),
    }


def _score_one_finding(
    finding: dict[str, Any],
    scene_text: str,
    severity_hint: int | None,
    evidence_joined: str,
) -> tuple[dict[str, int], int, list[str], list[str]]:
    category = str(finding.get("category") or "")
    base = CATEGORY_BASE_SCORES.get(category, DEFAULT_BASE_SCORES)
    values = dict(base)
    severity = finding.get("final_severity")
    if severity is None:
        severity = severity_hint
    severity_factor = 0.0 if severity is None else (int(severity) - 1) * 50.0
    matched_exposure = [
        keyword for keyword in EXPOSURE_KEYWORDS if keyword in scene_text
    ]
    if matched_exposure:
        values["exposure"] = min(100, values["exposure"] + 12)

    facts = [str(item) for item in (finding.get("observed_facts") or [])]
    fact_text = " ".join(facts)
    matched_danger = [
        keyword
        for keyword in IMMEDIATE_DANGER_KEYWORDS
        if keyword in fact_text and keyword in evidence_joined
    ]
    danger_boost = min(25.0, 10.0 * len(matched_danger))
    base_score = (
        0.3 * values["exposure"]
        + 0.25 * values["hazard_source"]
        + 0.2 * values["consequence"]
        + 0.15 * values["violation"]
        + 0.1 * severity_factor
    )
    score = _clamp_score(base_score + danger_boost)
    evidence = []
    if category:
        evidence.append(category)
    evidence.extend(matched_danger)
    triggered: list[str] = []
    if category:
        triggered.append(f"category_base:{category}")
    triggered.extend(f"danger_keyword:{keyword}" for keyword in matched_danger)
    if matched_exposure:
        triggered.append(f"exposure_keyword:{matched_exposure[0]}")
        evidence.append(f"exposure:{matched_exposure[0]}")
    if severity is not None:
        triggered.append(f"severity_hint:{severity}")
    evidence.extend(facts[:2])
    return values, score, evidence, triggered


def score_findings(
    findings: list[Any],
    *,
    scene_text: str = "",
    observations: list[str] | None = None,
    severity_hint: int | None = None,
    evidence_texts: list[str] | None = None,
) -> RiskAssessment:
    """Compute the worst-case risk score across all final findings."""
    if scene_text and observations:
        scene_text = f"{scene_text}\n{' '.join(observations)}"
    evidence_joined = " ".join(evidence_texts or [])
    if not findings:
        return RiskAssessment(
            risk_score=20,
            risk_level="low",
            operational_level=3,
            factor_scores=dict(DEFAULT_BASE_SCORES),
            severity_hint=severity_hint,
            rule_version=RULE_VERSION,
            evidence_used=[],
            triggered_rules=[],
            review_suggestion=True,
        )

    worst_score = 0
    worst_factors = dict(DEFAULT_BASE_SCORES)
    evidence_used: list[str] = []
    triggered_rules: list[str] = []
    unknown_categories: list[str] = []
    missing_severity = False
    for item in findings:
        fields = _finding_fields(item)
        category = str(fields.get("category") or "")
        if category not in CATEGORY_BASE_SCORES:
            unknown_categories.append(category)
        if fields.get("final_severity") is None:
            missing_severity = True
        factors, score, evidence, triggered = _score_one_finding(
            fields,
            scene_text,
            severity_hint,
            evidence_joined,
        )
        evidence_used.extend(evidence)
        triggered_rules.extend(triggered)
        if score > worst_score:
            worst_score = score
            worst_factors = factors

    risk_level = _level_from_score(worst_score)
    needs_care = unknown_categories or missing_severity
    triggered_rules.extend(f"unknown_category:{item}" for item in unknown_categories)
    if missing_severity:
        triggered_rules.append("severity_missing")
    return RiskAssessment(
        risk_score=worst_score,
        risk_level=risk_level,
        operational_level=_operational_level(worst_score),
        factor_scores=worst_factors,
        severity_hint=severity_hint,
        rule_version=RULE_VERSION,
        evidence_used=list(dict.fromkeys(evidence_used))[:5],
        triggered_rules=list(dict.fromkeys(triggered_rules)),
        review_suggestion=worst_score >= HIGH_BAND or bool(needs_care),
    )


def apply_risk_to_judge(judge: Any, risk: RiskAssessment) -> Any:
    """Attach the risk assessment to the ensemble judge result."""
    judge.risk_score = risk.risk_score
    judge.risk_level = risk.risk_level
    judge.rule_version = risk.rule_version
    for finding in judge.final_findings:
        finding.risk_score = risk.risk_score
        finding.risk_level = risk.risk_level
    return judge
