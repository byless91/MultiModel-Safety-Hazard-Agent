"""R6/T16: failed or incomplete execution is not a successful detector."""

import pytest
from app.eval.evaluation import build_evaluation_report, compute_metrics
from test_eval_detection_metrics import trace_for


@pytest.mark.parametrize("status,failed,schema_valid", [("needs_more_info", False, True),
                         ("failed", True, True), ("awaiting_human_review", True, True),
                         ("awaiting_human_review", False, False)])
def test_unavailable_predictions_have_missing_counts(monkeypatch, status, failed, schema_valid):
    trace = trace_for(monkeypatch, found=True, status=status, fail=failed, schema_valid=schema_valid,
                      expected_abstention=True)
    metrics = compute_metrics([trace])
    assert trace["predicted_hazard_present"] is None
    assert trace["final_decision"] == status
    assert metrics["detection_missing_count"] == 1
    assert metrics["detection_precision"] is None
    assert metrics["detection_recall"] is None
    assert metrics["end_to_end_hazard_recall"] == 0
    assert metrics["category_accuracy"] == 0
    assert metrics["metric_basis"]["detection_recall"]["missing"] == 1
    assert metrics["correct_abstention_count"] == (status == "needs_more_info")
    assert metrics["execution_failure_count"] == (status != "needs_more_info")


def test_high_risk_review_is_not_overall_review_proxy(monkeypatch):
    high = trace_for(monkeypatch, found=True, status="completed")
    low = trace_for(monkeypatch, found=True)
    low["case"]["expected_level"] = 3
    metrics = compute_metrics([high, low])
    assert metrics["human_review_rate"] == 0.5
    assert metrics["high_risk_review_rate"] == 0
    assert metrics["metric_basis"]["high_risk_review_rate"]["denominator"] == 1


def test_missing_independent_evidence_and_abstention_show_na(monkeypatch, tmp_path):
    from app.eval.dataset import load_dataset

    path = tmp_path / "cases.jsonl"
    path.write_text("", encoding="utf-8")
    dataset = load_dataset(path)
    trace = trace_for(monkeypatch, found=True, support=True)
    summary, markdown = build_evaluation_report(dataset, [trace], provider_mode="mock")
    assert summary["independent_evidence_accuracy"] is None
    assert "| 独立证据标签正确率 | N/A |" in markdown
    assert summary["abstention_accuracy"] is None


def test_workflow_exception_is_recorded_without_exception_secret(monkeypatch):
    def broken(**kwargs):
        raise RuntimeError("private-api-key")

    from app.core.config import get_settings
    from app.eval.dataset import EvalCase
    from app.eval.evaluation import pick_variant, run_evaluation_case
    from app.services.providers.mock import MockProvider

    monkeypatch.setattr("app.services.workflow.run_workflow", broken)
    trace = run_evaluation_case(EvalCase(id="failed-case", description="现场", expected_category="其他",
                                          expected_level=1), pick_variant("full"), settings=get_settings(),
                               providers=[MockProvider()], rag=object())
    assert trace["status"] == "failed"
    assert trace["evaluation_error"] == "RuntimeError"
    assert "private-api-key" not in str(trace)
    assert compute_metrics([trace])["execution_failure_count"] == 1
