"""Phase 7: formal error analysis classification and report sections."""

from app.eval.evaluation import build_evaluation_report
from app.eval.metrics import (
    error_by_dimension,
    error_summary,
    failure_cases,
    failure_case_reason,
)


def _trace(
    case_id,
    *,
    category="占用疏散通道",
    scenario="消防",
    level=1,
    flags=None,
    status="awaiting_human_review",
    evidence_status="insufficient",
    disagreement_reasons=None,
    unsafe_reason=None,
    predicted="占用疏散通道/1",
):
    base_flags = {
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
        "human_review": True,
        "unsafe_auto_pass": False,
        "multi_model_configured": True,
        "false_positive": False,
        "false_negative": False,
        "severity_error": False,
        "hazard_present_ground_truth": True,
    }
    if flags:
        base_flags.update(flags)
    return {
        "case": {
            "case_id": case_id,
            "scenario": scenario,
            "expected_category": category,
            "expected_level": level,
        },
        "predicted_category": predicted.split("/")[0],
        "predicted_level": int(predicted.split("/")[1]) if "/" in predicted else None,
        "status": status,
        "evidence": {
            "supported": bool(base_flags.get("evidence_support")),
            "unsupported_claims": ["法条未覆盖该类隐患"] if base_flags.get("evidence_failure") else [],
        },
        "evidence_status": evidence_status,
        "disagreement": {
            "reasons": disagreement_reasons or ["模型隐患类别不一致"],
        },
        "unsafe_reason": unsafe_reason,
        "review_required": bool(base_flags.get("human_review")),
        "auto_passed": not bool(base_flags.get("human_review")),
        "metric_flags": base_flags,
    }


def test_classify_false_positive_and_negative():
    fp = _trace(
        "fp-001",
        flags={
            "false_positive": True,
            "hazard_present_ground_truth": False,
            "evidence_support": None,
        },
    )
    fn = _trace(
        "fn-001",
        flags={
            "false_negative": True,
            "predicted_category": None,
            "predicted_level": None,
        },
    )
    rows = failure_cases([fp, fn])
    by_id = {row["case_id"]: row for row in rows}
    assert "false_positive" in by_id["fp-001"]["flags"]
    assert "false_negative" in by_id["fn-001"]["flags"]
    assert "unsafe_auto_pass" not in by_id["fp-001"]["flags"]


def test_unsafe_not_double_counted_as_false_negative():
    unsafe = _trace(
        "unsafe-001",
        status="completed",
        flags={
            "unsafe_auto_pass": True,
            "false_negative": True,
            "human_review": False,
            "auto_passed": True,
            "predicted_category": None,
            "predicted_level": None,
        },
        unsafe_reason="真值存在隐患，但系统自动通过且未进入人工复核",
    )
    summary = error_summary([unsafe])
    assert summary["counts"]["unsafe_auto_pass"] == 1
    assert summary["counts"]["false_negative"] == 0
    rows = failure_cases([unsafe])
    assert "unsafe_auto_pass" in rows[0]["flags"]
    assert "false_negative" not in rows[0]["flags"]
    assert rows[0]["reasons"][0]["type"] == "unsafe_auto_pass"


def test_model_conflict_reason_comes_from_disagreement():
    trace = _trace(
        "conflict-001",
        flags={"model_conflict": True, "conflict_category": True},
        disagreement_reasons=["模型隐患类别不一致", "风险等级存在 1 级分歧"],
    )
    rows = failure_cases([trace])
    reason = failure_case_reason(trace, "model_conflict")
    assert "类别不一致" in reason
    assert rows[0]["flags"] == ["model_conflict"]


def test_evidence_failure_and_severity_error_combine():
    trace = _trace(
        "evidence-001",
        flags={
            "evidence_failure": True,
            "severity_error": True,
            "level_match": False,
            "level_tolerance": True,
        },
    )
    rows = failure_cases([trace])
    assert rows[0]["flags"] == ["evidence_failure", "severity_error"]
    assert "结论缺少法规证据支持" in rows[0]["reasons"][0]["reason"]
    assert "等级偏差" in rows[0]["reasons"][1]["reason"]


def test_error_summary_counts_multi_error_cases_once_per_type():
    a = _trace(
        "a-001",
        flags={"evidence_failure": True},
    )
    b = _trace(
        "b-001",
        flags={"evidence_failure": True, "severity_error": True, "level_match": False},
    )
    summary = error_summary([a, b])
    assert summary["counts"]["evidence_failure"] == 2
    assert summary["counts"]["severity_error"] == 1
    assert summary["total_error_occurrences"] == 3
    assert summary["cases_with_error"] == 2


def test_error_by_dimension_aggregates_category_and_scenario():
    a = _trace("a-001", category="消防器材失效", scenario="社区", flags={"evidence_failure": True})
    b = _trace("b-001", category="消防器材失效", scenario="社区", flags={})
    c = _trace("c-001", category="电气线路隐患", scenario="消防", flags={"severity_error": True, "level_match": False})
    by_category = error_by_dimension([a, b, c], dimension="expected_category")
    by_scenario = error_by_dimension([a, b, c], dimension="scenario")
    assert by_category["消防器材失效"]["total"] == 2
    assert by_category["消防器材失效"]["evidence_failure"] == 1
    assert by_category["电气线路隐患"]["severity_error"] == 1
    assert by_scenario["社区"]["evidence_failure"] == 1
    assert by_scenario["消防"]["severity_error"] == 1


def test_report_contains_error_sections_and_failure_list():
    from pathlib import Path

    from app.eval.dataset import load_dataset

    dataset = load_dataset(
        Path(__file__).resolve().parents[1] / "data" / "eval_cases" / "cases.jsonl",
        dataset_version="v1",
    )
    results = [
        _trace(
            "run-er-001",
            flags={"evidence_failure": True},
            evidence_status="insufficient",
        ),
        _trace("run-er-002", flags={}),
    ]
    summary, markdown = build_evaluation_report(dataset, results, provider_mode="mock")
    assert "error_summary" in summary
    assert "error_by_category" in summary
    assert summary["error_analysis_count"] == 1
    assert "## 错误分析汇总" in markdown
    assert "## 错误分类粒度" in markdown
    assert "## 失败案例清单" in markdown
    assert "run-er-001" in markdown
