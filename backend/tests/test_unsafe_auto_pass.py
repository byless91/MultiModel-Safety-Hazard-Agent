"""Unsafe Auto-Pass semantic tests.

Unsafe Auto-Pass must not be lowered by forcing reviews: the metric only
counts traces where a ground-truth hazard was auto-passed without review, and
real tests exercise the actual workflow paths for evidence insufficiency.
"""

from app.eval.dataset import EvalCase
from app.eval.evaluation import (
    check_unsafe_auto_pass,
    compute_metrics,
    is_unsafe_auto_pass,
    pick_variant,
    run_evaluation_case,
)


def _case(overrides=None):
    payload = {
        "id": "eval-unsafe-001",
        "scenario": "消防",
        "description": "商场安全出口被货物堵住，出口大门上锁无法开启",
        "expected_category": "占用疏散通道",
        "expected_level": 1,
        "expected_clause_terms": ["安全出口"],
    }
    if overrides:
        payload.update(overrides)
    return EvalCase.model_validate(payload)


def test_unsafe_true_only_for_gt_hazard_without_review():
    assert is_unsafe_auto_pass(
        ground_truth_hazard_present=True,
        auto_passed=True,
        review_required=False,
    ) is True
    assert is_unsafe_auto_pass(
        ground_truth_hazard_present=True,
        auto_passed=False,
        review_required=True,
    ) is False
    assert is_unsafe_auto_pass(
        ground_truth_hazard_present=False,
        auto_passed=True,
        review_required=False,
    ) is False


def test_check_unsafe_auto_pass_returns_reason():
    unsafe, reason = check_unsafe_auto_pass(
        {
            "case": {"ground_truth_hazard_present": True},
            "auto_passed": True,
            "review_required": False,
        }
    )
    assert unsafe is True
    assert "真值存在隐患" in reason
    safe, safe_reason = check_unsafe_auto_pass(
        {
            "case": {"ground_truth_hazard_present": True},
            "auto_passed": False,
            "review_required": True,
        }
    )
    assert safe is False
    assert "已进入人工复核" in safe_reason


def test_metric_counts_real_unsafe_branch():
    # This trace deliberately simulates a system that auto-passed a real hazard.
    trace = {
        "case": {
            "case_id": "eval-unsafe-002",
            "scenario": "消防",
            "ground_truth_hazard_present": True,
            "expected_category": "占用疏散通道",
            "expected_level": 1,
        },
        "predict": {
            "predicted_hazard_present": False,
            "predicted_category": None,
            "predicted_level": None,
        },
        "status": "completed",
        "review_required": False,
        "auto_passed": True,
        "unsafe_reason": "真值存在隐患，但系统自动通过且未进入人工复核",
        "latency_s": 0.2,
        "evidence": {
            "supported": False,
            "finding_status": [],
            "unsupported_claims": [],
            "evidence_items": [],
        },
        "metric_flags": {
            "category_match": False,
            "level_match": False,
            "level_tolerance": False,
            "severity_mae": 1,
            "clause_hit": False,
            "evidence_support": None,
            "evidence_failure": False,
            "unsupported_claims": False,
            "model_conflict": False,
            "multi_model_configured": True,
            "human_review": False,
            "unsafe_auto_pass": True,
            "false_positive": False,
            "false_negative": True,
            "severity_error": False,
            "hazard_present_ground_truth": True,
        },
    }
    metrics = compute_metrics([trace])
    assert metrics["unsafe_auto_pass_count"] == 1
    assert metrics["unsafe_auto_pass_rate"] == 1.0


def test_mock_trace_with_review_is_not_unsafe():
    trace = run_evaluation_case(_case(), pick_variant("full"), provider_mode="mock")
    assert trace["review_required"] is True
    assert trace["auto_passed"] is False
    assert trace["metric_flags"]["unsafe_auto_pass"] is False
    assert "已进入人工复核" in trace["unsafe_reason"]


def test_no_legal_evidence_does_not_mean_safe():
    # 知识库没有匹配消防器材/电气条款的案例：模型检出疑似隐患但法规证据不足，
    # 系统必须走人工复核，而不是把“证据不足”当作“无隐患”自动通过。
    trace = run_evaluation_case(
        _case(
            {
                "id": "eval-no-evidence-001",
                "description": "小区配电箱门破损，内部电线裸露",
                "expected_category": "电气线路隐患",
                "expected_level": 2,
                "expected_clause_terms": ["配电箱", "电线"],
            }
        ),
        pick_variant("full"),
        provider_mode="mock",
    )
    assert trace["evidence_status"] in ("supported", "insufficient")
    assert trace["status"] == "awaiting_human_review"
    assert trace["review_required"] is True
    assert trace["metric_flags"]["unsafe_auto_pass"] is False
    assert "法规证据不足" in " ".join(trace["review_reasons"])
