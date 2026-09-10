# -*- coding: utf-8 -*-
"""Run formal offline evaluation against the labeled evaluation set.

The runner loads the versioned dataset through ``app.eval.dataset``, executes
the requested experiment variant as an observer, and writes per-case traces
plus a formal report. Legacy ``run_case/summarize/build_markdown`` helpers are
kept for backward-compatible tests.
"""

import argparse
import json
import os
import sys
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

EVAL_CASES = BACKEND / "data" / "eval_cases" / "cases.jsonl"
EVAL_DIR = BACKEND / "data" / "eval"

from app.eval.dataset import EvalCase, load_dataset
from app.eval.evaluation import (
    build_evaluation_report,
    build_variant_runtime,
    pick_variant,
    run_evaluation_case,
)


def load_cases(path: Path) -> list[dict]:
    """Legacy loader: return dict rows for old helpers/tests."""
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def run_case(case: dict) -> dict:
    """Legacy single-case run used by existing tests (default full system)."""
    started = time.perf_counter()
    eval_case = EvalCase.model_validate(
        {
            **case,
            "id": case["id"],
            "expected_category": case["expected_category"],
            "expected_level": case["expected_level"],
        }
    )
    from app.core.config import get_settings
    settings = get_settings()
    from app.services.providers import build_providers
    from app.services.rag import RAGService
    providers = build_providers(settings)
    rag = RAGService(settings, providers[0])
    trace = run_evaluation_case(
        eval_case,
        pick_variant("full"),
        settings=settings,
        providers=providers,
        rag=rag,
    )
    evidence = trace.get("evidence") or {}
    clause_hit = bool(trace["metric_flags"]["clause_hit"])
    evidence_texts = [str(item.get("text", "")) for item in evidence.get("evidence_items", [])]
    state_status = trace.get("status")
    review_required = trace.get("review_required")
    return {
        "id": case["id"],
        "scenario": case.get("scenario", ""),
        "description": case["description"],
        "expected_category": case["expected_category"],
        "expected_level": case["expected_level"],
        "predicted_category": trace.get("predicted_category"),
        "predicted_level": trace.get("predicted_level"),
        "status": state_status,
        "confidence": trace.get("confidence"),
        "clause_hit": clause_hit,
        "grounded": bool(evidence_texts) and clause_hit,
        "category_match": trace["metric_flags"]["category_match"],
        "level_match": trace["metric_flags"]["level_match"],
        "is_high_risk": case.get("expected_level") == 1,
        "review_required": review_required,
        "auto_passed": trace.get("auto_passed"),
        "unsafe_auto_pass": trace["metric_flags"]["unsafe_auto_pass"],
        "evidence_count": evidence.get("evidence_count", 0),
        "latency_s": trace.get("latency_s"),
    }


def summarize(results: list[dict]) -> dict:
    """Deprecated compatibility layer; new reporting uses ``compute_metrics``."""
    warnings.warn(
        "evaluate.summarize 已弃用，评测指标请使用 app.eval.metrics.compute_metrics",
        DeprecationWarning,
        stacklevel=2,
    )
    return _legacy_summary_from_rows(results)


def build_markdown(results: list[dict], summary: dict) -> str:
    """Deprecated compatibility layer kept for legacy tests."""
    warnings.warn(
        "evaluate.build_markdown 已弃用，报告请使用 app.eval.evaluation.build_evaluation_report",
        DeprecationWarning,
        stacklevel=2,
    )
    return _legacy_markdown(results, summary)


def _legacy_summary_from_rows(results: list[dict]) -> dict:
    """Old flat summary shape; used only by the deprecated compatibility layer."""
    total = len(results)
    if total == 0:
        return {}
    level_diff_ok = sum(
        1
        for r in results
        if r["predicted_level"] is not None
        and abs(r["predicted_level"] - r["expected_level"]) <= 1
    )
    high_risk_cases = [item for item in results if item["is_high_risk"]]
    scenario_map: dict[str, dict[str, int]] = {}
    for item in results:
        scenario = item.get("scenario") or "未知"
        entry = scenario_map.setdefault(
            scenario,
            {
                "total": 0,
                "category_match": 0,
                "level_match": 0,
                "clause_hit": 0,
                "review_required": 0,
            },
        )
        entry["total"] += 1
        entry["category_match"] += int(item["category_match"])
        entry["level_match"] += int(item["level_match"])
        entry["clause_hit"] += int(item["clause_hit"])
        entry["review_required"] += int(item["review_required"])
    scenario_breakdown = {
        key: {
            "total": value["total"],
            "category_accuracy": round(value["category_match"] / value["total"], 4),
            "level_accuracy": round(value["level_match"] / value["total"], 4),
            "clause_hit_rate": round(value["clause_hit"] / value["total"], 4),
            "review_rate": round(value["review_required"] / value["total"], 4),
        }
        for key, value in scenario_map.items()
    }
    return {
        "total": total,
        "category_accuracy": round(sum(r["category_match"] for r in results) / total, 4),
        "level_accuracy": round(sum(r["level_match"] for r in results) / total, 4),
        "level_accuracy_tolerance1": round(level_diff_ok / total, 4),
        "clause_hit_rate": round(sum(r["clause_hit"] for r in results) / total, 4),
        "grounded_rate": round(sum(r["grounded"] for r in results) / total, 4),
        "hallucination_rate": round(1 - sum(r["grounded"] for r in results) / total, 4),
        "avg_confidence": round(sum(r["confidence"] or 0 for r in results) / total, 4),
        "avg_latency_s": round(sum(r["latency_s"] for r in results) / total, 3),
        "needs_review_count": sum(
            1 for r in results if r["status"] in ("needs_review", "awaiting_human_review")
        ),
        "completed_count": sum(1 for r in results if r["status"] == "completed"),
        "high_risk_review_rate": round(
            sum(r["review_required"] for r in high_risk_cases) / max(1, len(high_risk_cases)),
            4,
        ),
        "high_risk_case_count": len(high_risk_cases),
        "unsafe_auto_pass_count": sum(1 for r in results if r["unsafe_auto_pass"]),
        "unsafe_auto_pass_rate": round(
            sum(1 for r in high_risk_cases if r["unsafe_auto_pass"])
            / max(1, len(high_risk_cases)),
            4,
        ),
        "scenario_breakdown": scenario_breakdown,
    }


def _legacy_markdown(results: list[dict], summary: dict) -> str:
    """Old report shape; used only by the deprecated compatibility layer."""
    metric_labels = [
        ("total", "案例数"),
        ("provider", "模型模式"),
        ("category_accuracy", "类别准确率"),
        ("level_accuracy", "等级准确率"),
        ("level_accuracy_tolerance1", "等级容差准确率（±1）"),
        ("clause_hit_rate", "条款命中率"),
        ("grounded_rate", "可追溯率"),
        ("hallucination_rate", "幻觉率（无依据输出代理）"),
        ("high_risk_review_rate", "高风险复核率"),
        ("unsafe_auto_pass_rate", "不安全自动通过率（Unsafe Auto-Pass Rate）"),
        ("unsafe_auto_pass_count", "不安全自动通过案例数"),
        ("needs_review_count", "需人工复核数"),
        ("completed_count", "自动完成数"),
        ("avg_confidence", "平均置信度"),
        ("avg_latency_s", "平均耗时（秒）"),
    ]
    lines = [
        "# 离线评测报告",
        "",
        "## 总体指标",
        "",
        "| 指标 | 数值 |",
        "| --- | --- |",
    ]
    for key, label in metric_labels:
        if key in summary:
            lines.append(f"| {label} | {summary[key]} |")
    lines.extend(
        ["", "## 场景细分", "", "| 场景 | 案例数 | 类别准确率 | 等级准确率 | 条款命中率 | 复核率 |", "| --- | --- | --- | --- | --- | --- |"]
    )
    for scenario, value in summary.get("scenario_breakdown", {}).items():
        lines.append(
            f"| {scenario} | {value['total']} | {value['category_accuracy']} "
            f"| {value['level_accuracy']} | {value['clause_hit_rate']} "
            f"| {value['review_rate']} |"
        )
    lines.extend(
        [
            "",
            "## 逐条结果",
            "",
            "| 案例 | 场景 | 期望类别 | 预测类别 | 期望等级 | 预测等级 | 条款命中 | 需复核 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in results:
        lines.append(
            f"| {item['id']} | {item.get('scenario', '')} "
            f"| {item['expected_category']} | {item['predicted_category']} "
            f"| {item['expected_level']} | {item['predicted_level']} "
            f"| {'是' if item['clause_hit'] else '否'} "
            f"| {'是' if item['review_required'] else '否'} |"
        )
    return "\n".join(lines)
    metric_labels = [
        ("total", "案例数"),
        ("provider", "模型模式"),
        ("category_accuracy", "类别准确率"),
        ("level_accuracy", "等级准确率"),
        ("level_accuracy_tolerance1", "等级容差准确率（±1）"),
        ("clause_hit_rate", "条款命中率"),
        ("grounded_rate", "可追溯率"),
        ("hallucination_rate", "幻觉率（无依据输出代理）"),
        ("high_risk_review_rate", "高风险复核率"),
        ("unsafe_auto_pass_rate", "不安全自动通过率（Unsafe Auto-Pass Rate）"),
        ("unsafe_auto_pass_count", "不安全自动通过案例数"),
        ("needs_review_count", "需人工复核数"),
        ("completed_count", "自动完成数"),
        ("avg_confidence", "平均置信度"),
        ("avg_latency_s", "平均耗时（秒）"),
    ]
    lines = [
        "# 离线评测报告",
        "",
        "## 总体指标",
        "",
        "| 指标 | 数值 |",
        "| --- | --- |",
    ]
    for key, label in metric_labels:
        if key in summary:
            lines.append(f"| {label} | {summary[key]} |")
    lines.extend(["", "## 场景细分", "", "| 场景 | 案例数 | 类别准确率 | 等级准确率 | 条款命中率 | 复核率 |", "| --- | --- | --- | --- | --- | --- |"])
    for scenario, value in summary.get("scenario_breakdown", {}).items():
        lines.append(
            f"| {scenario} | {value['total']} | {value['category_accuracy']} "
            f"| {value['level_accuracy']} | {value['clause_hit_rate']} "
            f"| {value['review_rate']} |"
        )
    lines.extend(
        [
            "",
            "## 逐条结果",
            "",
            "| 案例 | 场景 | 期望类别 | 预测类别 | 期望等级 | 预测等级 | 条款命中 | 需复核 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in results:
        lines.append(
            f"| {item['id']} | {item.get('scenario', '')} "
            f"| {item['expected_category']} | {item['predicted_category']} "
            f"| {item['expected_level']} | {item['predicted_level']} "
            f"| {'是' if item['clause_hit'] else '否'} "
            f"| {'是' if item['review_required'] else '否'} |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="运行离线评测并生成报告")
    parser.add_argument("--provider", default="mock", choices=["mock", "auto"])
    parser.add_argument("--cases", type=Path, default=EVAL_CASES)
    parser.add_argument("--output", type=Path, default=EVAL_DIR)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--variant",
        default="full",
        help="评测变体：qwen/glm/ensemble/plus_risk/plus_rag/full",
    )
    parser.add_argument("--dataset-version", default="v1")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="只校验数据集，不调用模型",
    )
    args = parser.parse_args()

    os.environ["PROVIDER_MODE"] = args.provider
    from app.services.providers import get_provider

    dataset = load_dataset(
        args.cases,
        dataset_version=args.dataset_version,
        fail_on_issues=True,
    )
    cases = dataset.cases
    if args.limit is not None:
        cases = cases[: args.limit]
    if args.validate_only:
        print(f"== 数据集校验通过 == {dataset.version} 共 {len(dataset.cases)} 条")
        print(json.dumps(dataset.manifest.model_dump(), ensure_ascii=False, indent=2))
        return

    variant = pick_variant(args.variant)
    from app.core.config import get_settings
    base_settings = get_settings()
    settings, providers, rag = build_variant_runtime(
        base_settings, variant, provider_mode=args.provider
    )
    results = [
        run_evaluation_case(
            case,
            variant,
            settings=settings,
            providers=providers,
            rag=rag,
        )
        for case in cases
    ]
    ablation_summary = None
    ablation_report_path = args.output / "ablation_report.json"
    if ablation_report_path.exists():
        try:
            ablation_summary = json.loads(ablation_report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            ablation_summary = None
    summary, markdown = build_evaluation_report(
        dataset,
        results,
        provider_mode=args.provider,
        ablation_summary=ablation_summary,
    )
    try:
        summary["provider"] = get_provider().name
    except Exception:
        summary["provider"] = settings.provider_mode
    summary["variant"] = variant["id"]
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output / "report.md").write_text(markdown, encoding="utf-8")
    with (args.output / "results.jsonl").open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")

    print("== 评测摘要 ==")
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
        "avg_latency_s",
    ):
        print(f"{key}: {summary.get(key)}")
    failed = [item for item in results if not item["metric_flags"]["category_match"]]
    print(f"\n错误分析：{len(summary['error_analysis'])} 条")
    for row in summary["error_analysis"][:8]:
        print(f"- {row['case_id']} {row['expected']} → {row['predicted']} {','.join(row['flags'])}")


if __name__ == "__main__":
    main()
