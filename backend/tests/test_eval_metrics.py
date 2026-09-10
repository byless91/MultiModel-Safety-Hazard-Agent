"""Foundational metric edge cases: rates, numerators and safe semantics."""

import pytest

from app.core.config import Settings
from app.eval.evaluation import (
    build_error_analysis,
    build_variant_runtime,
    compute_metrics,
    evaluation_mode,
    pick_variant,
    run_evaluation_case,
)


def _fabricate_trace(
    case_id="eval-metric-001",
    *,
    hazard_gt=True,
    category_match=True,
    level_match=True,
    mae=0,
    tolerance=True,
    clause_hit=True,
    evidence_support=True,
    unsupported=False,
    conflict=False,
    both=True,
    review=True,
    unsafe=False,
    fp=False,
    fn=False,
    severity_error=False,
    status="awaiting_human_review",
    evidence_failure=False,
):
    return {
        "case": {
            "case_id": case_id,
            "scenario": "消防",
            "expected_category": "占用疏散通道",
            "expected_level": 1,
            "ground_truth_hazard_present": hazard_gt,
        },
        "variant": "F_full",
        "label": "Full system",
        "models": "both" if both else "qwen",
        "status": status,
        "ensemble_mode": "pair" if both and not conflict else "mock",
        "model_a_result": {"status": "success", "family": "qwen-vl"},
        "model_b_result": (
            {"status": "success", "family": "glm-v"}
            if both
            else {"status": "not_configured"}
        ),
        "disagreement": {"mode": "pair", "need_human_review": conflict},
        "risk_result": {"risk_score": 75, "operational_level": 1},
        "evidence": {
            "supported": evidence_support,
            "finding_status": (
                [{"finding_id": "占用疏散通道", "supported": evidence_support}]
            ),
            "unsupported_claims": ["缺少法规依据"] if unsupported else [],
            "evidence_items": [{"text": "消防法第二十八条 占用疏散通道"}],
        },
        "human_review": {},
        "predicted_category": "占用疏散通道" if category_match and hazard_gt else "待确认",
        "predicted_level": 1 if level_match else (2 if not unsafe else None),
        "predicted_hazard_present": not fn,
        "review_required": review,
        "auto_passed": not review,
        "latency_s": 0.4,
        "metric_flags": {
            "category_match": category_match,
            "level_match": level_match,
            "level_tolerance": tolerance,
            "severity_mae": mae,
            "clause_hit": clause_hit,
            "evidence_support": evidence_support,
            "evidence_failure": evidence_failure,
            "unsupported_claims": unsupported,
            "model_conflict": conflict,
            "conflict_category": conflict,
            "human_review": review,
            "unsafe_auto_pass": unsafe,
            "multi_model_configured": both,
            "false_positive": fp,
            "false_negative": fn,
            "severity_error": severity_error,
            "hazard_present_ground_truth": hazard_gt,
        },
    }


def test_category_and_level_accuracy_numerator():
    good = _fabricate_trace("good", category_match=True, level_match=True)
    bad = _fabricate_trace(
        "bad-category",
        category_match=False,
        level_match=True,
        severity_error=True,
    )
    metrics = compute_metrics([good, bad])
    assert metrics["category_accuracy"] == 0.5
    assert metrics["level_accuracy"] == 1.0
    assert metrics["severity_error_count"] == 1


def test_severity_mae_and_tolerance():
    close = _fabricate_trace("close", level_match=False, mae=1, tolerance=True)
    far = _fabricate_trace("far", level_match=False, mae=2, tolerance=False)
    metrics = compute_metrics([close, far])
    assert metrics["severity_mae"] == 1.5
    assert metrics["level_accuracy_tolerance1"] == 0.5


def test_missing_level_does_not_crash_mae():
    missing = _fabricate_trace("missing-level")
    missing["predicted_level"] = None
    missing["metric_flags"]["severity_mae"] = None
    ok = _fabricate_trace("ok")
    metrics = compute_metrics([missing, ok])
    assert metrics["severity_mae"] == 0.0
    assert metrics["total"] == 2


def test_clause_hit_and_evidence_metrics():
    hit = _fabricate_trace("hit", clause_hit=True, evidence_support=True, unsupported=False)
    miss = _fabricate_trace(
        "miss",
        clause_hit=False,
        evidence_support=False,
        unsupported=True,
        evidence_failure=True,
    )
    unknown = _fabricate_trace("unknown-evidence", clause_hit=False)
    unknown["evidence"]["finding_status"] = []
    unknown["metric_flags"]["evidence_support"] = None
    metrics = compute_metrics([hit, miss, unknown])
    assert metrics["clause_hit_rate"] == pytest.approx(0.3333, abs=0.0001)
    assert metrics["evidence_support_rate"] == pytest.approx(0.3333, abs=0.0001)
    assert metrics["unsupported_claim_rate"] == pytest.approx(0.3333, abs=0.0001)
    assert metrics["evidence_failure_count"] == 1


def test_model_conflict_rate_uses_dual_configured_denominator():
    conflict = _fabricate_trace("conflict", conflict=True, both=True)
    agree = _fabricate_trace("agree", conflict=False, both=True)
    single = _fabricate_trace("single", both=False, conflict=False)
    metrics = compute_metrics([conflict, agree, single])
    assert metrics["model_conflict_count"] == 1
    assert metrics["model_conflict_rate"] == 0.5


def test_human_review_rate_and_safe_auto_pass():
    reviewed = _fabricate_trace("reviewed", review=True)
    auto_completed = _fabricate_trace(
        "auto-ok",
        review=False,
        unsafe=False,
        status="completed",
        hazard_gt=False,
        fn=False,
    )
    auto_completed["metric_flags"]["hazard_present_ground_truth"] = False
    auto_completed["metric_flags"]["human_review"] = False
    metrics = compute_metrics([reviewed, auto_completed])
    assert metrics["human_review_rate"] == 0.5
    assert metrics["unsafe_auto_pass_count"] == 0


def test_unsafe_auto_pass_error_analysis_detailed_row():
    unsafe = _fabricate_trace(
        "danger-auto-passed",
        unsafe=True,
        review=False,
        status="completed",
        hazard_gt=True,
        fn=True,
    )
    unsafe["predicted_hazard_present"] = False
    unsafe["predicted_level"] = None
    rows = build_error_analysis([unsafe])
    assert len(rows) == 1
    row = rows[0]
    assert row["case_id"] == "danger-auto-passed"
    assert "unsafe_auto_pass" in row["flags"]
    assert "false_negative" not in row["flags"]
    assert any(item["type"] == "unsafe_auto_pass" for item in row["reasons"])
    assert row["status"] == "completed"


def test_single_model_mode_reported_not_as_conflict():
    run = run_evaluation_case(
        _eval_case(),
        pick_variant("ensemble"),
        provider_mode="mock",
    )
    assert run["ensemble_mode"] == "mock"
    assert run["model_b_result"]["status"] == "not_configured"
    assert run["metric_flags"]["model_conflict"] is False
    assert run["metric_flags"]["multi_model_configured"] is True


def test_evaluation_mode_resolution():
    mock_settings = Settings(provider_mode="mock", _env_file=None)
    assert evaluation_mode(mock_settings) == "mock"
    real_settings = Settings(
        provider_mode="auto",
        dashscope_api_key="sk-demo",
        zhipu_api_key="",
        _env_file=None,
    )
    assert evaluation_mode(real_settings) == "real"
    no_key = Settings(provider_mode="auto", dashscope_api_key="", zhipu_api_key="", _env_file=None)
    assert evaluation_mode(no_key) == "mock"


def _eval_case():
    from app.eval.dataset import EvalCase

    return EvalCase.model_validate(
        {
            "id": "eval-metric-run",
            "scenario": "消防",
            "description": "商场安全出口被货物堵住",
            "expected_category": "占用疏散通道",
            "expected_level": 1,
            "expected_clause_terms": ["安全出口"],
        }
    )
