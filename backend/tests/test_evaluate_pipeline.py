import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate as evaluate_pipeline


def _fabricated_result(
    case_id: str,
    *,
    high_risk: bool = True,
    review_required: bool = True,
    clause_hit: bool = True,
) -> dict:
    return {
        "id": case_id,
        "scenario": "消防",
        "expected_category": "占用疏散通道",
        "predicted_category": "占用疏散通道",
        "expected_level": 1 if high_risk else 2,
        "predicted_level": 1,
        "category_match": True,
        "level_match": True,
        "clause_hit": clause_hit,
        "grounded": clause_hit,
        "confidence": 0.85,
        "is_high_risk": high_risk,
        "review_required": review_required,
        "auto_passed": not review_required,
        "unsafe_auto_pass": high_risk and not review_required,
        "status": "awaiting_human_review" if review_required else "completed",
        "evidence_count": 3,
        "latency_s": 0.1,
    }


def test_run_case_records_review_and_high_risk():
    state = evaluate_pipeline.run_case(
        {
            "id": "eval-test-001",
            "scenario": "消防",
            "description": "小区楼道堆放纸箱杂物，堵塞疏散通道",
            "expected_category": "占用疏散通道",
            "expected_level": 1,
            "expected_clause_terms": ["疏散通道"],
        }
    )
    assert state["id"] == "eval-test-001"
    assert state["is_high_risk"] is True
    assert state["review_required"] is True
    assert state["auto_passed"] is False
    assert state["unsafe_auto_pass"] is False
    assert state["category_match"] is True
    assert "clause_hit" in state
    assert "evidence_count" in state


def test_summarize_reports_high_risk_review_rate():
    results = [
        _fabricated_result("a", review_required=True),
        _fabricated_result("b", review_required=False),
    ]
    summary = evaluate_pipeline.summarize(results)
    assert summary["high_risk_review_rate"] == 0.5
    assert summary["high_risk_case_count"] == 2
    assert summary["unsafe_auto_pass_count"] == 1
    assert summary["unsafe_auto_pass_rate"] == 0.5
    assert "消防" in summary["scenario_breakdown"]
    assert summary["scenario_breakdown"]["消防"]["clause_hit_rate"] == 1.0


def test_build_markdown_contains_metrics_and_rows():
    results = [_fabricated_result("eval-001")]
    summary = evaluate_pipeline.summarize(results)
    text = evaluate_pipeline.build_markdown(results, summary)
    assert "条款命中率" in text
    assert "高风险复核率" in text
    assert "不安全自动通过率" in text
    assert "eval-001" in text
