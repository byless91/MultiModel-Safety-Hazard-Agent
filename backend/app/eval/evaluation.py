"""Formal evaluation runner: per-case traces, metrics and reports.

The runner is an observer: it never rewrites model output, never forces
human review to lower Unsafe Auto-Pass, and never marks evidence as supported
when the Evidence Judge said otherwise.
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.eval.dataset import EvalCase, EvalDataset, EvalSourceType, load_dataset
from app.eval.metrics import (
    build_error_analysis,
    compute_metrics,
    error_by_dimension,
    error_summary,
)
from app.services.ensemble.categories import canonicalize_hazard_type
from app.services.providers import BaseProvider, build_providers
from app.services.rag import RAGService


__all__ = [
    "build_ablation_markdown",
    "build_error_analysis",
    "build_evaluation_report",
    "build_variant_runtime",
    "build_variant_runtimes",
    "build_variant_settings",
    "check_unsafe_auto_pass",
    "compute_metrics",
    "error_by_dimension",
    "error_summary",
    "evaluation_mode",
    "is_unsafe_auto_pass",
    "pick_variant",
    "run_ablation",
    "run_evaluation_case",
]

DEFAULT_DATASET_VERSION = "v1"

VARIANT_CONFIGS: dict[str, dict[str, Any]] = {
    "qwen": {"id": "A_qwen_only", "label": "Qwen only", "models": "qwen", "risk": False, "rag": False},
    "glm": {"id": "B_glm_only", "label": "GLM only", "models": "glm", "risk": False, "rag": False},
    "ensemble": {"id": "C_ensemble", "label": "Qwen+GLM", "models": "both", "risk": False, "rag": False},
    "plus_risk": {"id": "D_plus_risk", "label": "Qwen+GLM+Risk", "models": "both", "risk": True, "rag": False},
    "plus_rag": {"id": "E_plus_rag", "label": "Qwen+GLM+Risk+RAG", "models": "both", "risk": True, "rag": True},
    "full": {"id": "F_full", "label": "Full system", "models": "both", "risk": True, "rag": True},
}

SINGLE_MODEL_VARIANTS = {"qwen": "qwen", "glm": "glm"}
ENSEMBLE_VARIANTS = {"ensemble", "plus_risk", "plus_rag", "full"}


def build_variant_settings(
    base: Settings,
    variant: dict[str, Any],
    *,
    provider_mode: str,
) -> Settings:
    """Build isolated settings for one experiment variant.

    Single-model variants remove the other provider's API key so the ensemble
    layer cannot hide behind the second model.
    """
    kwargs: dict[str, Any] = {
        "provider_mode": provider_mode,
        "enable_risk_engine": bool(variant["risk"]),
        "enable_evidence_rag": bool(variant["rag"]),
        "refine_with_evidence": bool(variant["rag"]),
        "reranker_enabled": True,
        "_env_file": None,
    }
    if provider_mode == "auto":
        keep_both = variant["models"] == "both"
        kwargs["dashscope_api_key"] = base.dashscope_api_key if keep_both or variant["models"] == "qwen" else ""
        kwargs["zhipu_api_key"] = base.zhipu_api_key if keep_both or variant["models"] == "glm" else ""
    return Settings(**kwargs)


def build_variant_runtime(
    base: Settings,
    variant: dict[str, Any],
    *,
    provider_mode: str,
) -> tuple[Settings, list[BaseProvider], RAGService]:
    """Return (settings, providers, rag) for one experiment variant."""
    settings = build_variant_settings(base, variant, provider_mode=provider_mode)
    providers = build_providers(settings)
    return settings, providers, RAGService(settings, providers[0])


def build_variant_runtimes(
    base: Settings,
    *,
    provider_mode: str,
    variant_names: list[str] | None = None,
) -> dict[str, tuple[Settings, list[BaseProvider], RAGService]]:
    """Build runtimes for every experiment variant at once."""
    names = variant_names or list(VARIANT_CONFIGS)
    return {
        name: build_variant_runtime(base, pick_variant(name), provider_mode=provider_mode)
        for name in names
    }


def pick_variant(name: str) -> dict[str, Any]:
    normalized = (name or "full").strip().lower()
    if normalized not in VARIANT_CONFIGS:
        raise ValueError(f"未知评测变体：{name}，可选：{sorted(VARIANT_CONFIGS)}")
    return dict(VARIANT_CONFIGS[normalized])


def run_ablation(
    dataset: EvalDataset,
    *,
    provider_mode: str,
    runtimes: dict[str, tuple[Settings, list[BaseProvider], RAGService]] | None = None,
    limit: int | None = None,
    variant_names: list[str] | None = None,
) -> dict[str, Any]:
    """Run every variant and return a unified comparison report.

    Each row is a full ``run_evaluation_case`` trace, so comparison tables use
    the exact same metrics as single-variant formal reports.
    """
    if runtimes is None:
        base = get_settings()
        runtimes = build_variant_runtimes(base, provider_mode=provider_mode)
    names = variant_names or sorted(VARIANT_CONFIGS)
    for name in names:
        if name not in runtimes:
            raise KeyError(f"缺少变体 runtime：{name}")
    cases = dataset.cases
    if limit is not None:
        cases = cases[:limit]
    traces: list[dict[str, Any]] = []
    for case in cases:
        for name in names:
            settings, providers, rag = runtimes[name]
            trace = run_evaluation_case(
                case,
                pick_variant(name),
                settings=settings,
                providers=providers,
                rag=rag,
            )
            traces.append(trace)
    per_variant: dict[str, list[dict[str, Any]]] = {
        name: [trace for trace in traces if trace["variant"] == VARIANT_CONFIGS[name]["id"]]
        for name in names
    }
    metrics = {name: compute_metrics(rows) for name, rows in per_variant.items()}
    real_modes = {name: evaluation_mode(runtimes[name][0]) for name in names}
    variant_modes = {
        name: "real" if real_modes[name] == "real" else "mock"
        for name in names
    }
    return {
        "dataset_version": dataset.version,
        "case_count": len(cases),
        "provider_mode": provider_mode,
        "evaluation_mode": evaluation_mode(get_settings()),
        "source_type_counts": dict(dataset.manifest.source_type_counts),
        "partitions": {
            partition: sum(
                1
                for case in cases
                if case.source_type.value == partition
            )
            for partition in dict(dataset.manifest.source_type_counts)
        },
        "variants": {
            name: {
                "label": VARIANT_CONFIGS[name]["label"],
                "metrics": metrics[name],
                "mode": variant_modes[name],
            }
            for name in names
        },
        "results": traces,
    }


def build_ablation_markdown(comparison: dict[str, Any]) -> str:
    """Render the comparison table for the formal ablation report."""
    partitions = comparison.get("partitions") or {}
    partition_text = "、".join(
        f"{key}={value}" for key, value in sorted(partitions.items())
    ) or "未标注来源分类"
    lines = [
        "# 消融评测报告",
        "",
        f"- 数据集版本：{comparison.get('dataset_version', '-')}",
        f"- 案例数：{comparison.get('case_count', 0)}",
        f"- 评测模式：{comparison.get('provider_mode', '-')}",
        f"- 数据来源分布：{partition_text}",
        f"- 实际模型模式：{comparison.get('evaluation_mode', '-')}",
        "",
        "| 变体 | 数据模式 | 类别准确率 | 等级准确率 | MAE | ±1 容差 | 条款命中 | 证据支持 | 无依据结论 | 复核率 | 分歧率 | Unsafe Auto-Pass |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, item in comparison.get("variants", {}).items():
        row = item.get("metrics", {})
        lines.append(
            f"| {item.get('label', name)} | {item.get('mode', comparison.get('evaluation_mode', '-'))} "
            f"| {row.get('category_accuracy', '-')} "
            f"| {row.get('level_accuracy', '-')} "
            f"| {row.get('severity_mae', '-')} "
            f"| {row.get('level_accuracy_tolerance1', '-')} "
            f"| {row.get('clause_hit_rate', '-')} "
            f"| {row.get('evidence_support_rate', '-')} "
            f"| {row.get('unsupported_claim_rate', '-')} "
            f"| {row.get('human_review_rate', '-')} "
            f"| {row.get('model_conflict_rate', '-')} "
            f"| {row.get('unsafe_auto_pass_rate', '-')} |"
        )
    lines.extend(
        [
            "",
            "说明：A/B/C 为模型组合差异；D 加入 Risk Engine；E 加入 Evidence RAG；"
            "F 为完整系统。数据模式列标记本组实际执行方式：real=真实模型调用，"
            "mock=确定性 Mock；synthetic 案例按来源分布单独列出，不混入 curated。",
        ]
    )
    return "\n".join(lines)


def is_unsafe_auto_pass(
    *,
    ground_truth_hazard_present: bool,
    auto_passed: bool,
    review_required: bool,
) -> bool:
    """True only when a real hazard was auto-passed without human review."""
    return bool(ground_truth_hazard_present) and bool(auto_passed) and not bool(review_required)


def check_unsafe_auto_pass(trace: dict[str, Any]) -> tuple[bool, str]:
    """Return (is_unsafe_auto_pass, reason) for one trace."""
    gt_hazard = bool(trace.get("case", {}).get("ground_truth_hazard_present"))
    auto_passed = bool(trace.get("auto_passed"))
    review_required = bool(trace.get("review_required"))
    unsafe = is_unsafe_auto_pass(
        ground_truth_hazard_present=gt_hazard,
        auto_passed=auto_passed,
        review_required=review_required,
    )
    if unsafe:
        reason = "真值存在隐患，但系统自动通过且未进入人工复核"
    else:
        reason = (
            "真值存在隐患但已进入人工复核，不计为 Unsafe Auto-Pass"
            if gt_hazard and review_required
            else "真值无隐患或未自动通过，不计为 Unsafe Auto-Pass"
        )
    return unsafe, reason


def evaluation_mode(settings: Settings) -> str:
    if settings.provider_mode == "mock":
        return "mock"
    if (
        settings.provider_mode == "auto"
        and (settings.dashscope_api_key or settings.zhipu_api_key)
    ):
        return "real"
    return "mock"


def _useful_analysis(run: dict[str, Any]) -> dict[str, Any]:
    analysis = run.get("analysis")
    if not isinstance(analysis, dict):
        return {}
    utilization: dict[str, Any] = {
        "scene_summary": analysis.get("scene_summary", ""),
        "observations": analysis.get("observations", []) or [],
        "hazard_hints": analysis.get("hazard_hints", []) or [],
        "vision_confidence": analysis.get("vision_confidence"),
        "schema_valid": analysis.get("schema_valid"),
        "validation_warnings": analysis.get("validation_warnings", []) or [],
    }
    hazards = analysis.get("hazards") or []
    utilization["hazards"] = hazards
    utilization["hazard_count"] = len(hazards)
    if isinstance(hazards, list) and hazards and isinstance(hazards[0], dict):
        utilization["model_category"] = canonicalize_hazard_type(
            str(hazards[0].get("hazard_type") or "")
        )
        utilization["model_severity"] = hazards[0].get("severity")
    return utilization


def _extract_model_slot(
    results: list[dict[str, Any]],
    family: str,
    fallback_index: int,
) -> dict[str, Any] | None:
    for item in results:
        if str(item.get("family") or item.get("provider") or "").lower() == family:
            return dict(item)
    for item in results:
        if str(item.get("family") or "").lower().startswith(family):
            return dict(item)
    if fallback_index < len(results):
        return dict(results[fallback_index])
    return None


def _model_slot_dict(
    run: dict[str, Any] | None,
    *,
    slot: str,
) -> dict[str, Any]:
    if run is None:
        return {
            "slot": slot,
            "status": "not_configured",
            "family": "",
            "model": "",
            "latency_ms": 0.0,
            "error_type": "",
            "error_message": "",
            "analysis": {},
        }
    payload = {
        "slot": slot,
        "status": run.get("status", "pending"),
        "family": run.get("family", ""),
        "provider": run.get("provider", ""),
        "model": run.get("model", ""),
        "model_version": run.get("model_version", ""),
        "latency_ms": run.get("latency_ms", 0.0),
        "retry_count": run.get("retry_count", 0),
        "error_type": run.get("error_type", ""),
        "error_message": run.get("error_message", ""),
        "analysis": _useful_analysis(run),
    }
    return payload


def _case_to_dict(case: EvalCase) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "scenario": case.scenario,
        "description": case.description,
        "user_text": case.user_text,
        "expected_category": case.category,
        "expected_level": case.severity,
        "expected_clause_terms": list(case.expected_clause_terms),
        "expected_regulation_refs": list(case.expected_regulation_refs),
        "expected_source": case.expected_source,
        "ground_truth_hazard_present": case.ground_truth_hazard_present,
        "expected_hazard": case.expected_hazard,
        "expected_evidence_supported": case.expected_evidence_supported,
        "expected_review_required": case.expected_review_required,
        "source_type": case.source_type.value,
        "dataset_version": case.dataset_version,
        "image_paths": list(case.image_paths),
        "notes": case.notes,
    }


def _predicted_level_from_state(state: dict[str, Any]) -> int | None:
    predicted = state.get("risk_level")
    if isinstance(predicted, int):
        return predicted
    risk = state.get("risk_result") or {}
    if isinstance(risk, dict) and risk.get("operational_level") is not None:
        return int(risk["operational_level"])
    return None


def _predicted_category_from_state(state: dict[str, Any]) -> str | None:
    value = state.get("hazard_category")
    if value:
        return str(value)
    judge = state.get("ensemble_judge") or {}
    findings = judge.get("final_findings") if isinstance(judge, dict) else []
    if findings:
        return str(findings[0].get("category") or "")
    return None


def _evidence_stats(state: dict[str, Any]) -> dict[str, Any]:
    judge = state.get("evidence_judge") or {}
    findings = judge.get("findings") if isinstance(judge, dict) else []
    finding_status = []
    if isinstance(findings, list):
        finding_status = [
            {
                "finding_id": item.get("finding_id", ""),
                "category": item.get("category", ""),
                "supported": bool(item.get("supported")),
                "support_score": item.get("support_score"),
                "needs_human_review": bool(item.get("needs_human_review")),
                "unsupported_claims": item.get("unsupported_claims", []) or [],
            }
            for item in findings
        ]
    evidence = state.get("evidence") or []
    evidence_trace = []
    if isinstance(evidence, list):
        for item in evidence[:5]:
            if isinstance(item, dict):
                evidence_trace.append(
                    {
                        "id": item.get("id", ""),
                        "source": item.get("source", ""),
                        "article": item.get("article", ""),
                        "document": item.get("document", ""),
                        "score": item.get("score"),
                        "text": str(item.get("text") or "")[:200],
                    }
                )
    return {
        "supported": bool((judge or {}).get("supported")),
        "support_score": (judge or {}).get("support_score"),
        "needs_human_review": bool((judge or {}).get("needs_human_review")),
        "visual_evidence_count": (judge or {}).get("visual_evidence_count", 0),
        "retrieval_evidence_count": (judge or {}).get("retrieval_evidence_count", 0),
        "unsupported_claims": list((judge or {}).get("unsupported_claims") or []),
        "evidence_count": len(evidence),
        "evidence_items": evidence_trace,
        "finding_status": finding_status,
    }


def run_evaluation_case(
    case: EvalCase,
    variant: dict[str, Any],
    *,
    provider_mode: str = "mock",
    settings: Settings | None = None,
    providers: list[BaseProvider] | None = None,
    rag: RAGService | None = None,
) -> dict[str, Any]:
    """Run one real/mock evaluation case and collect the full trace."""
    from app.services.workflow import run_workflow

    if settings is None:
        base = get_settings()
        settings, providers, rag = build_variant_runtime(base, variant, provider_mode=provider_mode)
    if providers is None:
        providers = build_providers(settings)
    if rag is None:
        rag = RAGService(settings, providers[0])
    started = time.perf_counter()
    state = run_workflow(
        description=case.description,
        images=[],
        followup_answer=None,
        followup_used=0,
        settings=settings,
        rag=rag,
        providers=providers,
    )
    if state.get("status") == "needs_more_info" and case.user_text:
        state = run_workflow(
            description=case.description,
            images=[],
            followup_answer=case.user_text,
            followup_used=1,
            settings=settings,
            rag=rag,
            providers=providers,
        )
    elapsed = time.perf_counter() - started

    model_results = state.get("model_results") or []
    model_a = _extract_model_slot(model_results, "qwen", 0)
    model_b = _extract_model_slot(model_results, "glm", 1)
    disagreement = state.get("disagreement") or {}
    judge = state.get("ensemble_judge") or {}
    findings = judge.get("final_findings") if isinstance(judge, dict) else []
    predicted_category = _predicted_category_from_state(state)
    predicted_level = _predicted_level_from_state(state)
    expected_level = case.severity
    hazard_present_gt = case.ground_truth_hazard_present
    status = str(state.get("status") or "")
    review_required = status in ("awaiting_human_review", "needs_review")
    auto_passed = status == "completed" and not review_required
    evidence_stats = _evidence_stats(state)
    system_found_hazard = bool(findings)
    predicted_hazard_present = system_found_hazard or review_required
    evidence_status = (
        "supported"
        if evidence_stats["supported"]
        else "insufficient"
        if bool(findings)
        else "not_applicable"
    )

    category_match = predicted_category == case.category
    level_match = predicted_level == expected_level
    tolerance = predicted_level is not None and abs(predicted_level - expected_level) <= 1
    severity_mae = abs(predicted_level - expected_level) if predicted_level is not None else None
    evidence_texts = [str(item.get("text", "")) for item in (state.get("evidence") or [])]
    joined_evidence = " ".join(evidence_texts)
    clause_hit = any(term in joined_evidence for term in case.expected_clause_terms)
    expected_support = case.expected_evidence_supported
    evidence_support = (
        evidence_stats["supported"] if expected_support is not False else None
    )
    finding_statuses = evidence_stats.get("finding_status") or []
    findings_ok = (
        bool(finding_statuses)
        and all(bool(item.get("supported")) for item in finding_statuses)
    )
    if expected_support is False:
        evidence_support = False
    elif expected_support is True:
        evidence_support = bool(finding_statuses) and findings_ok
    else:
        evidence_support = (
            None
            if not finding_statuses
            else findings_ok
        )
    unsupported_claims = bool(evidence_stats["unsupported_claims"]) and bool(system_found_hazard)
    evidence_failure = bool(system_found_hazard) and not evidence_stats["supported"]
    model_conflict = (
        variant["models"] == "both"
        and bool(disagreement.get("need_human_review") or disagreement.get("critical_conflict"))
    )
    conflict_category = bool(model_conflict) and any(
        "类别不一致" in str(reason) or "关键事实冲突" in str(reason)
        for reason in (disagreement.get("reasons") or [])
    )
    unsafe_auto_pass, unsafe_reason = check_unsafe_auto_pass(
        {
            "case": {"ground_truth_hazard_present": hazard_present_gt},
            "auto_passed": auto_passed,
            "review_required": review_required,
        }
    )
    false_negative = bool(hazard_present_gt) and not predicted_hazard_present
    false_positive = (
        bool(not hazard_present_gt)
        and predicted_hazard_present
        and not review_required
    )
    severity_error = category_match and not level_match

    verdict = "completed" if auto_passed else "awaiting_human_review"
    return {
        "case": _case_to_dict(case),
        "variant": variant["id"],
        "label": variant["label"],
        "models": variant["models"],
        "evaluation_timestamp": datetime.now(timezone.utc).isoformat(),
        "latency_s": round(elapsed, 2),
        "provider_mode": evaluation_mode(settings),
        "system_version": "eval-runner-3",
        "ensemble_mode": state.get("multi_model", {}).get("ensemble_mode", ""),
        "model_a_result": model_a if model_a is not None else _model_slot_dict(None, slot="model_a"),
        "model_b_result": model_b if model_b is not None else _model_slot_dict(None, slot="model_b"),
        "model_results": [_model_slot_dict(item, slot=f"model_{index+1}") for index, item in enumerate(model_results)],
        "disagreement": {
            "mode": disagreement.get("mode", ""),
            "agreement_score": disagreement.get("agreement_score"),
            "agreement_available": bool(disagreement.get("agreement_available")),
            "category_agreement": bool(disagreement.get("category_agreement")),
            "severity_difference": disagreement.get("severity_difference"),
            "critical_conflict": bool(disagreement.get("critical_conflict")),
            "need_human_review": bool(disagreement.get("need_human_review")),
            "reasons": list(disagreement.get("reasons") or []),
        },
        "risk_result": state.get("risk_result"),
        "evidence": evidence_stats,
        "evidence_status": evidence_status,
        "human_review": state.get("human_review"),
        "review_reasons": list(state.get("review_reasons") or []),
        "predicted_category": predicted_category,
        "predicted_level": predicted_level,
        "predicted_hazard_present": predicted_hazard_present,
        "status": status,
        "review_required": review_required,
        "auto_passed": auto_passed,
        "confidence": state.get("confidence"),
        "final_decision": verdict,
        "unsafe_reason": unsafe_reason,
        "metric_flags": {
            "category_match": category_match,
            "level_match": level_match,
            "level_tolerance": bool(tolerance),
            "severity_mae": severity_mae,
            "clause_hit": clause_hit,
            "evidence_support": evidence_support,
            "evidence_failure": evidence_failure,
            "unsupported_claims": unsupported_claims,
            "model_conflict": model_conflict,
            "conflict_category": conflict_category,
            "human_review": review_required,
            "unsafe_auto_pass": unsafe_auto_pass,
            "multi_model_configured": variant["models"] == "both",
            "false_positive": false_positive,
            "false_negative": false_negative,
            "severity_error": severity_error,
            "hazard_present_ground_truth": hazard_present_gt,
        },
    }


def _dataset_overview(dataset: EvalDataset) -> dict[str, Any]:
    cases = dataset.cases
    hazards = sum(1 for case in cases if case.ground_truth_hazard_present)
    negatives = len(cases) - hazards
    images = sum(1 for case in cases if case.image_paths)
    evidence_labeled = sum(
        1 for case in cases if case.expected_evidence_supported is not None
    )
    notes: list[str] = []
    if negatives == 0:
        notes.append("当前数据集缺少无隐患负样本，FP 与正确自动通过能力无法完整评估")
    if images == 0:
        notes.append("当前数据集全部为文本场景，尚未验证真实图片输入链路")
    if evidence_labeled == 0:
        notes.append("未标注 expected_evidence_supported，证据支持率按系统 Evidence Judge 结果统计")
    return {
        "case_count": len(cases),
        "dataset_version": dataset.version,
        "source_type_counts": dict(dataset.manifest.source_type_counts),
        "category_counts": dict(dataset.manifest.category_counts),
        "severity_counts": {
            str(key): value for key, value in dataset.manifest.severity_counts.items()
        },
        "scenario_counts": {
            scenario: sum(1 for case in cases if case.scenario == scenario)
            for scenario in sorted({case.scenario for case in cases})
        },
        "hazard_case_count": hazards,
        "safe_negative_case_count": negatives,
        "image_case_count": images,
        "evidence_labeled_count": evidence_labeled,
        "limitation_notes": notes,
    }


def _model_family_performance(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-family stats: only successful real runs are compared to labels."""
    families: dict[str, dict[str, Any]] = {}
    for item in results:
        case = item.get("case") or {}
        observed_families = set()
        for slot in ("model_a_result", "model_b_result"):
            model_result = item.get(slot) or {}
            status = str(model_result.get("status") or "")
            family = str(model_result.get("family") or "")
            analysis = model_result.get("analysis") or {}
            if status != "success" or not analysis:
                continue
            if family in observed_families:
                continue
            observed_families.add(family)
            entry = families.setdefault(
                family,
                {"family": family, "attempts": 0, "category_match": 0, "level_match": 0},
            )
            entry["attempts"] += 1
            predicted_category = analysis.get("model_category")
            predicted_level = analysis.get("model_severity")
            if predicted_category == case.get("expected_category"):
                entry["category_match"] += 1
            if predicted_level is not None and int(predicted_level) == int(
                case.get("expected_level", 0)
            ):
                entry["level_match"] += 1
    rows = []
    for family, entry in sorted(families.items()):
        attempts = max(1, entry["attempts"])
        rows.append(
            {
                "family": family,
                "attempts": entry["attempts"],
                "category_accuracy": round(entry["category_match"] / attempts, 4),
                "level_accuracy": round(entry["level_match"] / attempts, 4),
            }
        )
    return rows


def _review_and_risk_stats(results: list[dict[str, Any]]) -> dict[str, Any]:
    risky = [item for item in results if (item.get("risk_result") or {}).get("risk_level") == "high"]
    risk_suggestions = [
        item for item in results if (item.get("risk_result") or {}).get("review_suggestion")
    ]
    return {
        "high_risk_case_count": len(risky),
        "risk_review_suggestion_count": len(risk_suggestions),
        "risk_review_suggestion_rate": round(
            len(risk_suggestions) / max(1, len(results)), 4
        ),
        "average_risk_score": round(
            sum((item.get("risk_result") or {}).get("risk_score") or 0 for item in results)
            / max(1, len(results)),
            2,
        ),
    }


def _evidence_stats_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    supported = sum(1 for item in results if item.get("evidence_status") == "supported")
    insufficient = sum(
        1 for item in results if item.get("evidence_status") == "insufficient"
    )
    return {
        "supported_count": supported,
        "insufficient_count": insufficient,
        "supported_rate": round(supported / max(1, len(results)), 4),
        "insufficient_rate": round(insufficient / max(1, len(results)), 4),
    }


def build_evaluation_report(
    dataset: EvalDataset,
    results: list[dict[str, Any]],
    *,
    provider_mode: str,
    ablation_summary: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    """Build (summary, markdown) for one variant run."""
    metrics = compute_metrics(results)
    error_rows = build_error_analysis(results)
    error_overview = error_summary(results)
    error_by_category = error_by_dimension(results, dimension="expected_category")
    error_by_scenario = error_by_dimension(results, dimension="scenario")
    overview = _dataset_overview(dataset)
    model_family_performance = _model_family_performance(results)
    review_and_risk = _review_and_risk_stats(results)
    evidence_overview = _evidence_stats_summary(results)
    categories: Counter[str] = Counter()
    severities: Counter[int] = Counter()
    for item in results:
        categories[item["case"]["expected_category"]] += 1
        level = item["case"]["expected_level"]
        severities[level] += 1
    scenario_rows: dict[str, dict[str, float | int]] = {}
    for item in results:
        scenario = item["case"]["scenario"]
        entry = scenario_rows.setdefault(scenario, {"total": 0, "category_accuracy": 0, "level_accuracy": 0, "review_rate": 0, "clause_hit_rate": 0})
        entry["total"] += 1
        entry["category_accuracy"] += int(item["metric_flags"]["category_match"])
        entry["level_accuracy"] += int(item["metric_flags"]["level_match"])
        entry["review_rate"] += int(item["metric_flags"]["human_review"])
        entry["clause_hit_rate"] += int(item["metric_flags"]["clause_hit"])
    for entry in scenario_rows.values():
        total = int(entry["total"])
        for key in ("category_accuracy", "level_accuracy", "review_rate", "clause_hit_rate"):
            entry[key] = round(entry[key] / total, 4)
    summary = {
        "dataset_version": dataset.version,
        "title": dataset.manifest.title,
        "dataset_case_count": dataset.manifest.case_count,
        "source_type_counts": dataset.manifest.source_type_counts,
        "category_counts": dict(categories),
        "severity_counts": dict(severities),
        "scenario_breakdown": scenario_rows,
        "evaluation_mode": provider_mode,
        "evaluation_timestamp": datetime.now(timezone.utc).isoformat(),
        "system_version": "eval-runner-3",
        **metrics,
        "metrics": metrics,
        "dataset_overview": overview,
        "model_family_performance": model_family_performance,
        "review_and_risk_stats": review_and_risk,
        "evidence_stats_summary": evidence_overview,
        "ablation_study": ablation_summary,
        "error_summary": error_overview,
        "error_by_category": error_by_category,
        "error_by_scenario": error_by_scenario,
        "error_analysis_count": len(error_rows),
        "error_analysis": error_rows,
    }
    lines = [
        "# 正式评测报告",
        "",
        f"- 数据集版本：{dataset.version}（{dataset.manifest.title}）",
        f"- 案例数：{dataset.manifest.case_count}；本次运行：{metrics['total']}",
        f"- 评测模式：{provider_mode}",
        f"- 生成时间：{summary['evaluation_timestamp']}",
        "",
        "## Dataset Overview",
        "",
        f"- 案例数：{overview['case_count']}，来源：{json.dumps(overview['source_type_counts'], ensure_ascii=False)}",
        f"- 类别分布：{json.dumps(overview['category_counts'], ensure_ascii=False)}",
        f"- 等级分布：{json.dumps(overview['severity_counts'], ensure_ascii=False)}",
        f"- 场景分布：{json.dumps(overview['scenario_counts'], ensure_ascii=False)}",
        f"- 有隐患样本：{overview['hazard_case_count']}；无隐患负样本：{overview['safe_negative_case_count']}",
        f"- 含图片案例：{overview['image_case_count']}；标注 expected_evidence_supported：{overview['evidence_labeled_count']}",
        "",
        "## 总体指标",
        "",
        "| 指标 | 数值 |",
        "| --- | --- |",
    ]
    metric_labels = [
        ("category_accuracy", "类别准确率"),
        ("level_accuracy", "等级准确率"),
        ("severity_mae", "等级 MAE"),
        ("level_accuracy_tolerance1", "等级容差（±1）"),
        ("clause_hit_rate", "法规证据命中率"),
        ("evidence_support_rate", "证据支持率"),
        ("unsupported_claim_rate", "无依据结论率"),
        ("model_conflict_rate", "模型分歧率"),
        ("human_review_rate", "人工复核率"),
        ("unsafe_auto_pass_rate", "Unsafe Auto-Pass 率"),
        ("unsafe_auto_pass_count", "Unsafe Auto-Pass 数"),
        ("avg_latency_s", "平均耗时（秒）"),
    ]
    for key, label in metric_labels:
        lines.append(f"| {label} | {summary.get(key, '-')} |")
    lines.extend(
        [
            "",
            "## 数据集分布",
            "",
            f"- 类别：{dict(categories)}",
            f"- 等级：{dict(severities)}",
            f"- 来源：{dataset.manifest.source_type_counts}",
            "",
            "## 场景细分",
            "",
            "| 场景 | 案例数 | 类别准确率 | 等级准确率 | 条款命中率 | 复核率 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for scenario, entry in scenario_rows.items():
        lines.append(
            f"| {scenario} | {entry['total']} | {entry['category_accuracy']} "
            f"| {entry['level_accuracy']} | {entry['clause_hit_rate']} | {entry['review_rate']} |"
        )
    error_labels = {
        "false_positive": "误报（无隐患被判有）",
        "false_negative": "漏报（有隐患未检出）",
        "unsafe_auto_pass": "Unsafe Auto-Pass（危险自动通过）",
        "model_conflict": "模型冲突",
        "evidence_failure": "证据不足/证据不支持结论",
        "severity_error": "等级偏差",
    }
    lines.extend(["", "## 错误分析汇总", ""])
    lines.append("| 错误类型 | 数量 |")
    lines.append("| --- | --- |")
    for error_type, label in error_labels.items():
        count = error_overview.get("counts", {}).get(error_type, 0)
        lines.append(f"| {label} | {count} |")
    lines.extend(["", "## 错误分类粒度", ""])
    lines.append("| 类别 | 案例数 | FP | FN | Unsafe | 冲突 | 证据失败 | 等级偏差 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for category, entry in sorted(error_by_category.items()):
        lines.append(
            f"| {category} | {entry['total']} | {entry['false_positive']} "
            f"| {entry['false_negative']} | {entry['unsafe_auto_pass']} "
            f"| {entry['model_conflict']} | {entry['evidence_failure']} "
            f"| {entry['severity_error']} |"
        )
    lines.extend(["", "## 失败案例清单", ""])
    if error_rows:
        lines.append("| 案例 | 场景 | 期望 | 预测 | 状态 | 错误类型 | 原因 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for row in error_rows:
            reason_text = "；".join(
                f"{item['type']}: {item['reason']}" for item in row.get("reasons", [])
            )
            lines.append(
                f"| {row['case_id']} | {row['scenario']} | {row['expected']} "
                f"| {row['predicted']} | {row['status']} "
                f"| {','.join(row['flags'])} | {reason_text} |"
            )
    else:
        lines.append("无错误案例。")
    lines.extend(["", "## 模块表现：模型 / 风险 / 证据", ""])
    if model_family_performance:
        lines.append("| 模型家族 | 有效样本 | 类别准确率 | 等级准确率 |")
        lines.append("| --- | --- | --- | --- |")
        for row in model_family_performance:
            lines.append(
                f"| {row['family']} | {row['attempts']} "
                f"| {row['category_accuracy']} | {row['level_accuracy']} |"
            )
    lines.append(
        f"- Risk Engine：高风险案例 {review_and_risk['high_risk_case_count']} 条，"
        f"建议复核 {review_and_risk['risk_review_suggestion_count']} 条（"
        f"{review_and_risk['risk_review_suggestion_rate']}），平均风险分 "
        f"{review_and_risk['average_risk_score']}"
    )
    lines.append(
        f"- Evidence：支持 {evidence_overview['supported_count']} 条（"
        f"{evidence_overview['supported_rate']}），证据不足 {evidence_overview['insufficient_count']} 条"
    )
    lines.append(
        f"- Human Review：{metrics.get('human_review_count', 0)} 条进入人工复核；"
        f"Unsafe Auto-Pass {metrics.get('unsafe_auto_pass_count', 0)} 条"
    )
    if ablation_summary:
        lines.extend(["", "## Ablation Study（独立消融运行）", ""])
        lines.append("| 变体 | 类别 | 等级 | UA-P |")
        lines.append("| --- | --- | --- | --- |")
        for name, item in ablation_summary.get("variants", {}).items():
            row = item.get("metrics", {})
            lines.append(
                f"| {item.get('label', name)} | {row.get('category_accuracy', '-')} "
                f"| {row.get('level_accuracy', '-')} "
                f"| {row.get('unsafe_auto_pass_rate', '-')} |"
            )
        lines.append(
            "说明：消融结果在独立运行时生成，仅供横向比较，不改变本次单变体结论。"
        )
    lines.extend(["", "## Limitations", ""])
    if overview["limitation_notes"]:
        for note in overview["limitation_notes"]:
            lines.append(f"- {note}")
    lines.append("- 模型输出未经过真实场景图片评测，文本场景仅覆盖当前知识库范围")
    lines.append("- 法规证据支持率以系统 Evidence Judge 为准，存在知识库覆盖不足时结果偏保守")
    lines.append("- 本报告不保证无错误；正式部署前需人工复核高风险与证据不足案例")
    return summary, "\n".join(lines)
