"""Core evaluation metrics and error analysis.

All metrics are computed from already-executed evaluation traces. The runner
never changes model output to improve a metric and never marks evidence as
supported unless the Evidence Judge did.
"""

from __future__ import annotations

from typing import Any


METRIC_ORDER = (
    "category_accuracy",
    "level_accuracy",
    "severity_mae",
    "level_accuracy_tolerance1",
    "clause_hit_rate",
    "evidence_hit_rate",
    "evidence_support_rate",
    "unsupported_claim_rate",
    "model_conflict_rate",
    "human_review_rate",
    "unsafe_auto_pass_rate",
)


def metric_definitions() -> dict[str, str]:
    return {
        "category_accuracy": "预测隐患类别与人工标注类别一致的比例",
        "level_accuracy": "预测风险等级与人工标注等级完全一致的比例",
        "severity_mae": "预测等级与标注等级的平均绝对误差（等级 1-3）",
        "level_accuracy_tolerance1": "预测等级与标注等级相差不超过 1 级的比例",
        "clause_hit_rate": "预期法规条款关键词出现在检索证据中的比例",
        "evidence_hit_rate": "与 clause_hit_rate 相同，保留为法规证据命中率别名",
        "evidence_support_rate": "系统结论被法规证据真正支持（Evidence Judge supported）的比例",
        "unsupported_claim_rate": "系统输出结论但缺少可靠法规依据的比例",
        "model_conflict_rate": "多模型配置下检测到模型分歧/关键冲突的比例",
        "human_review_rate": "系统最终进入人工复核的比例",
        "unsafe_auto_pass_rate": "真值存在隐患且系统自动通过、未进入人工复核的比例，越低越好",
    }


def compute_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-case traces into formal metrics.

    ``results`` items are the traces produced by
    ``app.eval.evaluation.run_evaluation_case``; only trace shape is assumed,
    model outputs are never rewritten here.
    """
    total = len(results)
    if not total:
        return {"total": 0}
    flags = [item.get("metric_flags") or {} for item in results]
    severity_mae_values = [
        item["metric_flags"]["severity_mae"]
        for item in results
        if item["metric_flags"].get("severity_mae") is not None
    ]
    unsafe_cases = [item for item in results if item["metric_flags"]["unsafe_auto_pass"]]
    hazardous = [item for item in results if item["metric_flags"]["hazard_present_ground_truth"]]
    review_cases = [item for item in results if item["metric_flags"]["human_review"]]
    configured_both = [item for item in results if item["metric_flags"]["multi_model_configured"]]
    return {
        "total": total,
        "category_accuracy": round(sum(1 for f in flags if f["category_match"]) / total, 4),
        "level_accuracy": round(sum(1 for f in flags if f["level_match"]) / total, 4),
        "severity_mae": round(sum(severity_mae_values) / len(severity_mae_values), 4)
        if severity_mae_values
        else None,
        "level_accuracy_tolerance1": round(
            sum(1 for f in flags if f["level_tolerance"]) / total, 4
        ),
        "clause_hit_rate": round(sum(1 for f in flags if f["clause_hit"]) / total, 4),
        "evidence_hit_rate": round(sum(1 for f in flags if f["clause_hit"]) / total, 4),
        "evidence_support_rate": round(
            sum(1 for f in flags if f["evidence_support"] is True) / total,
            4,
        ),
        "unsupported_claim_rate": round(
            sum(1 for f in flags if f["unsupported_claims"]) / total, 4
        ),
        "model_conflict_rate": round(
            sum(1 for f in flags if f["model_conflict"]) / max(1, len(configured_both)),
            4,
        ),
        "human_review_rate": round(len(review_cases) / total, 4),
        "human_review_count": len(review_cases),
        "unsafe_auto_pass_count": len(unsafe_cases),
        "unsafe_auto_pass_rate": round(len(unsafe_cases) / max(1, len(hazardous)), 4),
        "unsafe_hazard_base_count": len(hazardous),
        "false_positive_count": sum(1 for f in flags if f["false_positive"]),
        "false_negative_count": sum(1 for f in flags if f["false_negative"]),
        "evidence_failure_count": sum(1 for f in flags if f["evidence_failure"]),
        "severity_error_count": sum(1 for f in flags if f["severity_error"]),
        "model_conflict_count": sum(1 for f in flags if f["model_conflict"]),
        "avg_latency_s": round(sum(item.get("latency_s") or 0.0 for item in results) / total, 3),
    }


def _flag(item: dict[str, Any]) -> dict[str, Any]:
    return item.get("metric_flags") or {}


def failure_case_reason(item: dict[str, Any], error_type: str) -> str:
    """Human-readable reason for one classified error on one trace."""
    flags = _flag(item)
    if error_type == "unsafe_auto_pass":
        return item.get("unsafe_reason") or "真值存在隐患但系统自动通过且未进入人工复核"
    if error_type == "false_negative":
        if flags.get("unsafe_auto_pass"):
            return "真值存在隐患，系统未检出且自动通过"
        return "真值存在隐患，系统未检出（已拦截或复核）"
    if error_type == "false_positive":
        return "真值无隐患，但系统给出隐患结论或进入复核"
    if error_type == "model_conflict":
        reasons = (item.get("disagreement") or {}).get("reasons") or []
        return "；".join(str(reason) for reason in reasons[:2]) or "双模型结论分歧"
    if error_type == "evidence_failure":
        claims = (item.get("evidence") or {}).get("unsupported_claims") or []
        detail = "；".join(str(claim) for claim in claims[:2])
        return f"结论缺少法规证据支持（{item.get('evidence_status') or 'insufficient'}）{('：' + detail) if detail else ''}"
    if error_type == "severity_error":
        expected = (item.get("case") or {}).get("expected_level")
        return f"类别正确但等级偏差（期望 {expected}，预测 {item.get('predicted_level')}）"
    return "未知错误"


def _classify_one(item: dict[str, Any]) -> list[str]:
    flags = _flag(item)
    errors: list[str] = []
    if flags.get("unsafe_auto_pass"):
        errors.append("unsafe_auto_pass")
    if flags.get("false_positive"):
        errors.append("false_positive")
    if flags.get("false_negative") and not flags.get("unsafe_auto_pass"):
        errors.append("false_negative")
    if flags.get("model_conflict"):
        errors.append("model_conflict")
    if flags.get("evidence_failure"):
        errors.append("evidence_failure")
    if flags.get("severity_error"):
        errors.append("severity_error")
    return errors


def failure_cases(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build the detailed failure-case list with per-error reasons."""
    rows: list[dict[str, Any]] = []
    for item in results:
        errors = _classify_one(item)
        if not errors:
            continue
        case = item.get("case") or {}
        rows.append(
            {
                "case_id": case.get("case_id", ""),
                "category": case.get("expected_category", ""),
                "scenario": case.get("scenario", ""),
                "expected": f"{case.get('expected_category', '')}/{case.get('expected_level', '')}",
                "predicted": f"{item.get('predicted_category')}/{item.get('predicted_level')}",
                "status": item.get("status", ""),
                "flags": errors,
                "reasons": [
                    {"type": error_type, "reason": failure_case_reason(item, error_type)}
                    for error_type in errors
                ],
            }
        )
    return rows


def build_error_analysis(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Classify every trace into error buckets (backward-compatible rows)."""
    return failure_cases(results)


def error_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Count each error type over the whole run."""
    counts: dict[str, int] = {
        "false_positive": 0,
        "false_negative": 0,
        "unsafe_auto_pass": 0,
        "model_conflict": 0,
        "evidence_failure": 0,
        "severity_error": 0,
    }
    triggered: dict[str, int] = {}
    for item in results:
        errors = _classify_one(item)
        for error_type in errors:
            counts[error_type] = counts.get(error_type, 0) + 1
        for error_type in errors:
            triggered[error_type] = triggered.get(error_type, 0) + 1
    return {
        "counts": counts,
        "total_error_occurrences": sum(counts.values()),
        "cases_with_error": len(failure_cases(results)),
    }


def error_by_dimension(
    results: list[dict[str, Any]],
    *,
    dimension: str,
) -> dict[str, dict[str, Any]]:
    """Aggregate error counts by expected category or scenario."""
    rows: dict[str, dict[str, Any]] = {}
    for item in results:
        case = item.get("case") or {}
        key = str(case.get(dimension) or "未知")
        entry = rows.setdefault(
            key,
            {
                "total": 0,
                "false_positive": 0,
                "false_negative": 0,
                "unsafe_auto_pass": 0,
                "model_conflict": 0,
                "evidence_failure": 0,
                "severity_error": 0,
            },
        )
        entry["total"] += 1
        for error_type in _classify_one(item):
            entry[error_type] = entry.get(error_type, 0) + 1
    return rows
