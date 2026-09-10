# -*- coding: utf-8 -*-
"""Ablation evaluation over Qwen/GLM/Risk/RAG variants.

Phase 6: this script is a thin CLI over ``app.eval.evaluation.run_ablation``
so A-F variants and the formal per-case traces share one metric pipeline.
Legacy helper names are kept for the old ablation tests.
"""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

EVAL_CASES = BACKEND / "data" / "eval_cases" / "cases.jsonl"
EVAL_DIR = BACKEND / "data" / "eval"

from app.eval.dataset import load_dataset
from app.eval.evaluation import (
    VARIANT_CONFIGS,
    build_ablation_markdown,
    build_variant_runtimes,
    pick_variant,
    run_ablation,
    run_evaluation_case,
)


VARIANTS = [dict(VARIANT_CONFIGS[name]) for name in sorted(VARIANT_CONFIGS)]


def load_cases(path: Path) -> list[dict]:
    """Legacy loader used by old tests."""
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def build_settings(base, variant: dict, provider_mode: str):
    """Legacy alias; new code uses ``build_variant_settings``."""
    from app.eval.evaluation import build_variant_settings

    return build_variant_settings(base, variant, provider_mode=provider_mode)


def build_variant_cache(base, provider_mode: str) -> dict[str, tuple]:
    """Legacy alias; new code uses ``build_variant_runtimes``."""
    cache: dict[str, tuple] = {}
    for name in sorted(VARIANT_CONFIGS):
        settings, providers, rag = build_variant_runtimes(
            base,
            provider_mode=provider_mode,
            variant_names=[name],
        )[name]
        cache[VARIANT_CONFIGS[name]["id"]] = (settings, providers[0], rag)
    return cache


def predicted_level(state: dict) -> int | None:
    """Legacy helper; new traces carry ``predicted_level`` directly."""
    risk = state.get("risk_result") or {}
    if risk.get("operational_level"):
        return int(risk["operational_level"])
    final_severity = (state.get("ensemble_judge") or {}).get("final_severity")
    if final_severity:
        return {3: 1, 2: 2, 1: 3}.get(int(final_severity))
    return None


def run_variant(case: dict, variant: dict, entry: tuple) -> dict:
    """Legacy single-variant run; new code uses ``run_evaluation_case``."""
    from app.eval.dataset import EvalCase

    eval_case = EvalCase.model_validate(case)
    trace = run_evaluation_case(
        eval_case,
        variant,
        settings=entry[0],
        providers=None,
        rag=entry[2],
    )
    evidence = trace.get("evidence") or {}
    disagreement = trace.get("disagreement") or {}
    return {
        "case_id": case["id"],
        "variant": variant["id"],
        "label": variant["label"],
        "expected_level": case.get("expected_level"),
        "category_match": trace["metric_flags"]["category_match"],
        "level_match": trace["metric_flags"]["level_match"],
        "tolerance": trace["metric_flags"]["level_tolerance"],
        "clause_hit": trace["metric_flags"]["clause_hit"],
        "review_required": trace["metric_flags"]["human_review"],
        "high_risk_reviewed": case.get("expected_level") == 1
        and trace["metric_flags"]["human_review"],
        "disagreement": bool(trace["metric_flags"]["model_conflict"]),
        "unsafe_auto_pass": trace["metric_flags"]["unsafe_auto_pass"],
        "evidence_support": trace["metric_flags"]["evidence_support"],
        "model_a_status": trace.get("model_a_result", {}).get("status"),
        "model_b_status": trace.get("model_b_result", {}).get("status"),
        "ensemble_mode": trace.get("ensemble_mode"),
    }


def summarize_rows(rows: list[dict]) -> dict:
    """Legacy summary over flat rows; new code uses ``compute_metrics``."""
    summary = {}
    for variant in VARIANTS:
        subset = [row for row in rows if row["variant"] == variant["id"]]
        total = len(subset) or 1
        high_risk = [row for row in subset if row["expected_level"] == 1]
        summary[variant["id"]] = {
            "label": variant["label"],
            "total": len(subset),
            "category_accuracy": round(
                sum(row["category_match"] for row in subset) / total, 4
            ),
            "level_accuracy": round(
                sum(row["level_match"] for row in subset) / total, 4
            ),
            "level_tolerance_accuracy": round(
                sum(row["tolerance"] for row in subset) / total, 4
            ),
            "clause_hit_rate": round(
                sum(row["clause_hit"] for row in subset) / total, 4
            ),
            "review_rate": round(
                sum(row["review_required"] for row in subset) / total, 4
            ),
            "high_risk_review_rate": (
                round(
                    sum(row["high_risk_reviewed"] for row in high_risk)
                    / max(1, len(high_risk)),
                    4,
                )
                if high_risk
                else None
            ),
            "disagreement_rate": round(
                sum(row["disagreement"] for row in subset) / total, 4
            ),
        }
    return summary


def build_markdown(summary: dict) -> str:
    """Legacy markdown for old tests; new reports use ``build_ablation_markdown``."""
    lines = [
        "# 消融评测报告",
        "",
        "| 变体 | 类别准确率 | 等级准确率 | ±1 容差 | 条款命中率 | 复核率 | 高风险复核率 | 分歧率 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for variant in VARIANTS:
        item = summary.get(variant["id"], {})
        high_risk = (
            item.get("high_risk_review_rate")
            if item.get("high_risk_review_rate") is not None
            else "-"
        )
        lines.append(
            f"| {item.get('label', variant['label'])} "
            f"| {item.get('category_accuracy', '-')} "
            f"| {item.get('level_accuracy', '-')} "
            f"| {item.get('level_tolerance_accuracy', '-')} "
            f"| {item.get('clause_hit_rate', '-')} "
            f"| {item.get('review_rate', '-')} "
            f"| {high_risk} "
            f"| {item.get('disagreement_rate', '-')} |"
        )
    lines.append("")
    lines.append("说明：A/B/C 为真实模型组合差异；D 加入 Risk Engine；E 加入 Evidence RAG；F 为完整系统。")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="消融评测（A-F 六变体）")
    parser.add_argument("--provider", default="mock", choices=["mock", "auto"])
    parser.add_argument("--cases", type=Path, default=EVAL_CASES)
    parser.add_argument("--output", type=Path, default=EVAL_DIR)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--variants",
        default="qwen,glm,ensemble,plus_risk,plus_rag,full",
        help="逗号分隔的变体名",
    )
    args = parser.parse_args()

    os.environ["PROVIDER_MODE"] = args.provider
    variant_names = [name.strip() for name in args.variants.split(",") if name.strip()]
    for name in variant_names:
        pick_variant(name)
    dataset = load_dataset(args.cases, dataset_version="v1", fail_on_issues=True)
    from app.core.config import get_settings

    base = get_settings()
    runtimes = build_variant_runtimes(
        base,
        provider_mode=args.provider,
        variant_names=variant_names,
    )
    comparison = run_ablation(
        dataset,
        provider_mode=args.provider,
        runtimes=runtimes,
        limit=args.limit,
        variant_names=variant_names,
    )
    markdown = build_ablation_markdown(comparison)
    args.output.mkdir(parents=True, exist_ok=True)
    summary_payload = {
        "dataset_version": comparison["dataset_version"],
        "case_count": comparison["case_count"],
        "provider_mode": comparison["provider_mode"],
        "evaluation_mode": comparison.get("evaluation_mode", comparison["provider_mode"]),
        "source_type_counts": comparison.get("source_type_counts", {}),
        "partitions": comparison.get("partitions", {}),
        "variants": {
            name: {
                "label": item["label"],
                "metrics": item["metrics"],
                "mode": item.get("mode", comparison.get("evaluation_mode", "mock")),
            }
            for name, item in comparison["variants"].items()
        },
    }
    (args.output / "ablation_report.json").write_text(
        json.dumps(summary_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (args.output / "ablation_report.md").write_text(markdown, encoding="utf-8")
    with (args.output / "ablation_results.jsonl").open("w", encoding="utf-8") as handle:
        for row in comparison["results"]:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print("== 消融评测 ==")
    for name, item in comparison["variants"].items():
        metrics = item["metrics"]
        print(
            f"{name}: {item['label']} cat={metrics.get('category_accuracy', '-')} "
            f"level={metrics.get('level_accuracy', '-')} "
            f"clause={metrics.get('clause_hit_rate', '-')} "
            f"review={metrics.get('human_review_rate', '-')} "
            f"conflict={metrics.get('model_conflict_rate', '-')} "
            f"unsafe={metrics.get('unsafe_auto_pass_rate', '-')}"
        )


if __name__ == "__main__":
    main()
