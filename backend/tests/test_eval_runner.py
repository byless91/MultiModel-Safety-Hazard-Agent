"""Evaluation runner, trace completeness and metric calculations."""

import json
from pathlib import Path

from app.core.config import get_settings
from app.eval.dataset import EvalCase, load_dataset
from app.eval.evaluation import (
    build_error_analysis,
    build_evaluation_report,
    build_variant_runtime,
    build_variant_settings,
    compute_metrics,
    pick_variant,
    run_evaluation_case,
)


def _case(overrides=None):
    payload = {
        "id": "eval-run-001",
        "scenario": "消防",
        "description": "商场安全出口被货物堵住，出口大门上锁无法开启",
        "expected_category": "占用疏散通道",
        "expected_level": 1,
        "expected_clause_terms": ["安全出口", "疏散通道"],
        "expected_source": "消防法第二十八条",
    }
    if overrides:
        payload.update(overrides)
    return EvalCase.model_validate(payload)


def _trace(case_id, *, hazard_gt=True, unsafe=False, status="awaiting_human_review"):
    """Minimal trace fixture shaped like ``run_evaluation_case`` output."""
    case = _case({"id": case_id})
    evidence = {
        "supported": True,
        "support_score": 0.8,
        "needs_human_review": False,
        "visual_evidence_count": 1,
        "retrieval_evidence_count": 2,
        "unsupported_claims": [],
        "evidence_count": 2,
        "evidence_items": [],
        "finding_status": [{"finding_id": "占用疏散通道", "supported": True}],
    }
    review_required = not unsafe
    return {
        "case": {
            "case_id": case_id,
            "scenario": "消防",
            "description": case.description,
            "expected_category": case.category,
            "expected_level": case.severity,
            "ground_truth_hazard_present": hazard_gt,
            "source_type": "curated",
        },
        "variant": "F_full",
        "label": "Full system",
        "models": "both",
        "status": status,
        "review_required": review_required,
        "auto_passed": unsafe,
        "predicted_category": case.category,
        "predicted_level": case.severity if not unsafe else None,
        "predicted_hazard_present": not unsafe,
        "confidence": 0.9,
        "evidence": evidence,
        "risk_result": {"risk_score": 80, "operational_level": 1},
        "disagreement": {"mode": "pair", "need_human_review": not unsafe},
        "human_review": {},
        "latency_s": 0.5,
        "metric_flags": {
            "category_match": True,
            "level_match": True,
            "level_tolerance": True,
            "severity_mae": 0,
            "clause_hit": True,
            "evidence_support": True,
            "evidence_failure": False,
            "unsupported_claims": False,
            "model_conflict": False,
            "conflict_category": False,
            "human_review": review_required,
            "unsafe_auto_pass": unsafe,
            "multi_model_configured": True,
            "false_positive": False,
            "false_negative": unsafe and hazard_gt,
            "severity_error": False,
            "hazard_present_ground_truth": hazard_gt,
        },
    }


def test_mock_run_records_full_trace():
    variant = pick_variant("full")
    trace = run_evaluation_case(_case(), variant, provider_mode="mock")
    assert trace["case"]["case_id"] == "eval-run-001"
    assert trace["variant"] == "F_full"
    assert trace["provider_mode"] == "mock"
    assert "model_a_result" in trace
    assert "model_b_result" in trace
    assert "disagreement" in trace
    assert "risk_result" in trace
    assert "evidence" in trace
    assert "human_review" in trace
    assert "metric_flags" in trace
    assert trace["metric_flags"]["category_match"] is True
    assert trace["metric_flags"]["human_review"] is True
    assert trace["metric_flags"]["unsafe_auto_pass"] is False


def test_variant_settings_isolate_single_model_keys():
    from app.core.config import Settings

    base = Settings(
        provider_mode="auto",
        dashscope_api_key="dashscope-secret",
        zhipu_api_key="zhipu-secret",
        _env_file=None,
    )
    qwen = build_variant_settings(base, pick_variant("qwen"), provider_mode="auto")
    assert qwen.dashscope_api_key == "dashscope-secret"
    assert qwen.zhipu_api_key == ""
    glm = build_variant_settings(base, pick_variant("glm"), provider_mode="auto")
    assert glm.dashscope_api_key == ""
    assert glm.zhipu_api_key == "zhipu-secret"
    both = build_variant_settings(base, pick_variant("full"), provider_mode="auto")
    assert both.dashscope_api_key == "dashscope-secret"
    assert both.zhipu_api_key == "zhipu-secret"


def test_full_runtime_reuses_provider_and_rag_objects():
    base = get_settings()
    settings, providers, rag = build_variant_runtime(base, pick_variant("full"), provider_mode="mock")
    assert settings.provider_mode == "mock"
    assert len(providers) == 1
    assert providers[0].name == "mock"
    assert rag.texts


def test_compute_metrics_counts_unsafe_auto_pass():
    ok = _trace("eval-safe-pass", hazard_gt=False, unsafe=True, status="completed")
    ok["metric_flags"]["unsafe_auto_pass"] = False
    ok["metric_flags"]["false_negative"] = False
    ok["metric_flags"]["human_review"] = False
    ok["metric_flags"]["hazard_present_ground_truth"] = False
    unsafe = _trace("eval-unsafe-pass")
    unsafe["metric_flags"]["unsafe_auto_pass"] = True
    unsafe["metric_flags"]["false_negative"] = True
    unsafe["metric_flags"]["human_review"] = False
    metrics = compute_metrics([ok, unsafe])
    assert metrics["unsafe_auto_pass_count"] == 1
    # Only the ground-truth-hazard case is counted in the denominator.
    assert metrics["unsafe_auto_pass_rate"] == 1.0
    assert metrics["unsafe_hazard_base_count"] == 1
    # The safe positive case did not require review, so review rate is 0.
    assert metrics["human_review_rate"] == 0.0
    assert metrics["category_accuracy"] == 1.0


def test_ground_truth_hazard_auto_pass_is_unsafe():
    trace = _trace("eval-unsafe-001", hazard_gt=True, unsafe=True, status="completed")
    trace["metric_flags"]["unsafe_auto_pass"] = True
    trace["metric_flags"]["false_negative"] = True
    metrics = compute_metrics([trace])
    assert metrics["unsafe_auto_pass_count"] == 1
    assert metrics["unsafe_auto_pass_rate"] == 1.0
    assert metrics["false_negative_count"] == 1


def test_uncertain_review_required_is_not_unsafe():
    trace = _trace("eval-uncertain-001", hazard_gt=True, unsafe=False, status="awaiting_human_review")
    metrics = compute_metrics([trace])
    assert metrics["unsafe_auto_pass_count"] == 0
    assert metrics["human_review_rate"] == 1.0


def test_error_analysis_lists_unsafe_pass_separately():
    unsafe = _trace("eval-error-001", hazard_gt=True, unsafe=True, status="completed")
    unsafe["metric_flags"].update(
        unsafe_auto_pass=True,
        false_negative=True,
        human_review=False,
    )
    rows = build_error_analysis([unsafe])
    assert len(rows) == 1
    assert rows[0]["case_id"] == "eval-error-001"
    assert "unsafe_auto_pass" in rows[0]["flags"]


def test_report_contains_all_formal_metric_sections():
    dataset = load_dataset(
        Path(__file__).resolve().parents[1] / "data" / "eval_cases" / "cases.jsonl",
        dataset_version="v1",
    )
    results = [_trace("eval-fire-101"), _trace("eval-fire-102")]
    summary, markdown = build_evaluation_report(
        dataset,
        results,
        provider_mode="mock",
    )
    assert summary["dataset_version"] == "v1"
    assert summary["evaluation_mode"] == "mock"
    for key in (
        "category_accuracy",
        "level_accuracy",
        "severity_mae",
        "level_accuracy_tolerance1",
        "clause_hit_rate",
        "evidence_support_rate",
        "unsupported_claim_rate",
        "model_conflict_rate",
        "human_review_rate",
        "unsafe_auto_pass_rate",
    ):
        assert key in summary
    for label in (
        "指标",
        "数据",
        "错误分析",
        "Unsafe Auto-Pass 率",
        "模型分歧率",
    ):
        assert label in markdown
