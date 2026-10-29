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
        "evidence_support_rate": "Evidence Judge 系统自评支持率别名，不代表独立正确率",
        "system_evidence_support_rate": "有效证据自评中 supported=True 的比例",
        "independent_evidence_accuracy": "有独立标签且有有效自评的案例中，自评与标签一致的比例；无标签为 N/A",
        "detection_precision": "可用检测中 TP/(TP+FP)，不以人工复核替代发现",
        "detection_recall": "可用检测中 TP/(TP+FN)，缺失另计",
        "end_to_end_hazard_recall": "TP/全部真值隐患案例，缺失和失败不算成功",
        "hazard_interception_rate": "真值隐患案例中未自动通过的比例，包括复核、信息不足及失败",
        "high_risk_review_rate": "真值等级 1 且有隐患的案例中实际转人工的比例",
        "abstention_accuracy": "有独立拒判标签的案例中，实际信息不足状态与标签一致的比例",
        "unsupported_claim_rate": "系统输出结论但缺少可靠法规依据的比例",
        "model_conflict_rate": "多模型配置下检测到模型分歧/关键冲突的比例",
        "human_review_rate": "系统最终进入人工复核的比例",
        "unsafe_auto_pass_rate": "真值存在隐患且系统自动通过、未进入人工复核的比例，越低越好",
    }


def _legacy_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
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


def compute_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Schema 2 separates observed detection from operational interception.

    Old hand-authored traces retain their historical contract for read-only
    consumers; new and old schemas cannot be pooled into one metric series.
    """
    versions = {row.get("metrics_schema_version", "1.0") for row in results}
    if len(versions) > 1:
        raise ValueError("Cannot aggregate mixed metric schemas")
    if not results or versions == {"1.0"}:
        return _legacy_metrics(results)
    if versions != {"2.0"}:
        raise ValueError("Unknown metric schema")
    total = len(results)
    flags = [row["metric_flags"] for row in results]
    known = [row for row in results if row["detection_available"]]
    hazards = [row for row in results if row["case"]["ground_truth_hazard_present"]]
    negatives = [row for row in results if not row["case"]["ground_truth_hazard_present"]]
    tp = sum(row["predicted_hazard_present"] is True for row in known if row["case"]["ground_truth_hazard_present"])
    fn = sum(row["predicted_hazard_present"] is False for row in known if row["case"]["ground_truth_hazard_present"])
    fp = sum(row["predicted_hazard_present"] is True for row in known if not row["case"]["ground_truth_hazard_present"])
    tn = sum(row["predicted_hazard_present"] is False
             for row in known if not row["case"]["ground_truth_hazard_present"])
    definitions: dict[str, dict[str, Any]] = {}
    values: dict[str, Any] = {"total": total, "metrics_schema_version": "2.0"}

    def rate(name: str, numerator: int | float, denominator: int, missing: int = 0) -> None:
        values[name] = round(numerator / denominator, 4) if denominator else None
        definitions[name] = {"numerator": numerator, "denominator": denominator, "missing": missing}

    rate("detection_precision", tp, tp + fp, total - len(known))
    rate("detection_recall", tp, tp + fn, len(hazards) - tp - fn)
    rate("detection_specificity", tn, tn + fp, len(negatives) - tn - fp)
    rate("detection_coverage", len(known), total, total - len(known))
    rate("end_to_end_hazard_recall", tp, len(hazards), len(hazards) - tp - fn)
    rate("category_accuracy", sum(r["metric_flags"]["category_match"] for r in hazards), len(hazards))
    rate("level_accuracy", sum(r["metric_flags"]["level_match"] for r in hazards), len(hazards))
    rate("level_accuracy_tolerance1", sum(r["metric_flags"]["level_tolerance"] for r in hazards), len(hazards))
    mae = [r["metric_flags"]["severity_mae"] for r in hazards if r["metric_flags"]["severity_mae"] is not None]
    rate("severity_mae", sum(mae), len(mae), len(hazards) - len(mae))
    rate("clause_hit_rate", sum(f["clause_hit"] for f in flags), total)
    rate("evidence_hit_rate", sum(f["clause_hit"] for f in flags), total)
    self_evidence = [f["evidence_support"] for f in flags if f["evidence_support"] is not None]
    independent = [f["independent_evidence_correct"] for f in flags if f["independent_evidence_correct"] is not None]
    rate("system_evidence_support_rate", sum(self_evidence), len(self_evidence), total - len(self_evidence))
    values["evidence_support_rate"] = values["system_evidence_support_rate"]  # Explicitly a self-assessment alias.
    definitions["evidence_support_rate"] = dict(definitions["system_evidence_support_rate"])
    rate("independent_evidence_accuracy", sum(independent), len(independent), total - len(independent))
    rate("unsupported_claim_rate", sum(f["unsupported_claims"] for f in flags), total)
    dual = sum(f["multi_model_configured"] for f in flags)
    rate("model_conflict_rate", sum(f["model_conflict"] for f in flags), dual)
    review_count = sum(r["review_required"] for r in results)
    rate("human_review_rate", review_count, total)
    high_risk = [r for r in hazards if r["case"]["expected_level"] == 1]
    rate("high_risk_review_rate", sum(r["review_required"] for r in high_risk), len(high_risk))
    rate("hazard_interception_rate", sum(not r["auto_passed"] for r in hazards), len(hazards))
    unsafe = sum(f["unsafe_auto_pass"] for f in flags)
    rate("unsafe_auto_pass_rate", unsafe, len(hazards))
    abstained = sum(f["abstained"] for f in flags)
    rate("information_insufficient_rate", abstained, total)
    abstention_labels = [r for r in results if r["case"].get("expected_abstention") is not None]
    rate("abstention_accuracy", sum(r["metric_flags"]["abstained"] == r["case"]["expected_abstention"]
                                   for r in abstention_labels), len(abstention_labels), total - len(abstention_labels))
    failures = sum(r["status"] in ("failed", "input_failed") or not r["detection_available"]
                   and r["status"] != "needs_more_info" for r in results)
    rate("execution_failure_rate", failures, total)
    values.update(
        true_positive_count=tp, true_negative_count=tn, false_positive_count=fp, false_negative_count=fn,
        detection_missing_count=total - len(known), human_review_count=review_count,
        high_risk_case_count=len(high_risk), unsafe_auto_pass_count=unsafe, unsafe_hazard_base_count=len(hazards),
        information_insufficient_count=abstained, execution_failure_count=failures,
        correct_abstention_count=sum(r["metric_flags"]["abstained"] and r["case"]["expected_abstention"] is True
                                    for r in abstention_labels),
        evidence_failure_count=sum(f["evidence_failure"] for f in flags),
        severity_error_count=sum(f["severity_error"] for f in flags),
        model_conflict_count=sum(f["model_conflict"] for f in flags),
        avg_latency_s=round(sum(r.get("latency_s", 0) for r in results) / total, 3),
        metric_basis=definitions,
    )
    return values


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
        return "真值无隐患，但系统给出隐患 finding；人工复核不消除检测误报"
    if error_type == "model_conflict":
        reasons = (item.get("disagreement") or {}).get("reasons") or []
        return "；".join(str(reason) for reason in reasons[:2]) or "双模型结论分歧"
    if error_type == "evidence_failure":
        claims = (item.get("evidence") or {}).get("unsupported_claims") or []
        detail = "；".join(str(claim) for claim in claims[:2])
        status = item.get("evidence_status") or "insufficient"
        suffix = f"：{detail}" if detail else ""
        return f"结论缺少法规证据支持（{status}）{suffix}"
    if error_type == "severity_error":
        expected = (item.get("case") or {}).get("expected_level")
        return f"类别正确但等级偏差（期望 {expected}，预测 {item.get('predicted_level')}）"
    if error_type == "information_insufficient":
        return "信息不足，未形成可用检测结论；按拒判标签单独评估"
    if error_type == "execution_failure":
        return "输入或模型执行失败，检测结果缺失，不计识别成功"
    return "未知错误"


def _classify_one(item: dict[str, Any]) -> list[str]:
    flags = _flag(item)
    errors: list[str] = []
    if flags.get("unsafe_auto_pass"):
        errors.append("unsafe_auto_pass")
    if flags.get("false_positive"):
        errors.append("false_positive")
    if flags.get("false_negative") and (
        item.get("metrics_schema_version") == "2.0" or not flags.get("unsafe_auto_pass")
    ):
        errors.append("false_negative")
    if item.get("metrics_schema_version") == "2.0" and not item.get("detection_available"):
        errors.append("information_insufficient" if item.get("status") == "needs_more_info" else "execution_failure")
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
