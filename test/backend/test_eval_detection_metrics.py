"""R6/T16: review cannot turn a miss into a detection or erase a false alarm."""

import pytest
from app.core.config import get_settings
from app.eval.dataset import EvalCase
from app.eval.evaluation import compute_metrics, pick_variant, run_evaluation_case
from app.eval.metrics import build_error_analysis
from app.services.providers.mock import MockProvider


def trace_for(monkeypatch, *, hazard=True, found=False, status="awaiting_human_review", support=None,
              expected_support=None, expected_abstention=None, fail=False, schema_valid=True):
    state = {
        "status": status, "hazard_category": "占用疏散通道" if found else None,
        "risk_level": 1 if found else None,
        "ensemble_judge": {"final_findings": [{"category": "占用疏散通道"}] if found else []},
        "model_results": [{"status": "failed" if fail else "success", "family": "mock",
                           "analysis": {"schema_valid": schema_valid, "hazards": []}}],
    }
    if support is not None:
        state["evidence_judge"] = {"supported": support, "findings": [{"supported": support}]}
    monkeypatch.setattr("app.services.workflow.run_workflow", lambda **kwargs: state)
    case = EvalCase(id="metric-case", description="安全出口现场", expected_category="占用疏散通道",
                    expected_level=1, ground_truth_hazard_present=hazard,
                    expected_evidence_supported=expected_support, expected_abstention=expected_abstention)
    return run_evaluation_case(case, pick_variant("full"), settings=get_settings(),
                               providers=[MockProvider()], rag=object())


def test_missed_hazard_stays_false_negative_when_reviewed(monkeypatch):
    trace = trace_for(monkeypatch, hazard=True, found=False)
    metrics = compute_metrics([trace])
    assert trace["predicted_hazard_present"] is False
    assert metrics["false_negative_count"] == 1
    assert metrics["detection_recall"] == 0
    assert metrics["hazard_interception_rate"] == 1
    assert metrics["human_review_rate"] == 1
    assert metrics["unsafe_auto_pass_count"] == 0


def test_false_alarm_stays_false_positive_when_reviewed(monkeypatch):
    trace = trace_for(monkeypatch, hazard=False, found=True)
    metrics = compute_metrics([trace])
    assert metrics["false_positive_count"] == 1
    assert metrics["detection_precision"] == 0
    assert metrics["detection_recall"] is None
    assert metrics["high_risk_review_rate"] is None
    assert metrics["metric_basis"]["detection_precision"]["denominator"] == 1


def test_confusion_matrix_denominators_and_no_review_proxy(monkeypatch):
    traces = [trace_for(monkeypatch, hazard=h, found=f) for h, f in
              [(True, True), (True, False), (False, True), (False, False)]]
    metrics = compute_metrics(traces)
    for name in ("true_positive_count", "true_negative_count", "false_positive_count", "false_negative_count"):
        assert metrics[name] == 1
    assert metrics["detection_precision"] == metrics["detection_recall"] == 0.5
    assert metrics["detection_coverage"] == 1
    assert metrics["metric_basis"]["detection_recall"] == {"numerator": 1, "denominator": 2, "missing": 0}


def test_unsafe_and_missed_are_both_reported(monkeypatch):
    trace = trace_for(monkeypatch, found=False, status="completed")
    errors = build_error_analysis([trace])[0]["flags"]
    assert "unsafe_auto_pass" in errors and "false_negative" in errors


@pytest.mark.parametrize("label,system,accuracy", [(True, True, 1), (False, False, 1), (True, False, 0),
                                                    (False, True, 0), (None, True, None)])
def test_independent_evidence_labels_are_separate_from_self_rating(monkeypatch, label, system, accuracy):
    trace = trace_for(monkeypatch, found=True, support=system, expected_support=label)
    metrics = compute_metrics([trace])
    assert metrics["system_evidence_support_rate"] == int(system)
    assert metrics["independent_evidence_accuracy"] == accuracy
    assert metrics["metric_basis"]["independent_evidence_accuracy"]["denominator"] == (label is not None)


def test_mixed_metric_schemas_rejected(monkeypatch):
    trace = trace_for(monkeypatch)
    with pytest.raises(ValueError, match="mixed"):
        compute_metrics([trace, {"metric_flags": {}}])


def test_original_safe_mock_case_exposes_false_alarm():
    case = EvalCase(id="safe-original", description="小区出入口地面平整，通道无堆放物，通行正常",
                    scenario="消防", expected_category="无隐患", expected_level=3,
                    ground_truth_hazard_present=False, expected_review_required=True)
    trace = run_evaluation_case(case, pick_variant("full"))
    assert trace["review_required"] is True
    assert trace["metric_flags"]["unsafe_auto_pass"] is False
    assert trace["findings"]
    assert trace["metric_flags"]["false_positive"] is True
    assert compute_metrics([trace])["false_positive_count"] == 1
