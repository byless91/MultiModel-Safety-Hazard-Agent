# -*- coding: utf-8 -*-
"""Ablation evaluation over Qwen/GLM/Risk/RAG variants."""

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

VARIANTS = [
    {
        "id": "A_qwen_only",
        "label": "Qwen only",
        "models": "qwen",
        "risk": False,
        "rag": False,
    },
    {
        "id": "B_glm_only",
        "label": "GLM only",
        "models": "glm",
        "risk": False,
        "rag": False,
    },
    {
        "id": "C_ensemble",
        "label": "Qwen+GLM",
        "models": "both",
        "risk": False,
        "rag": False,
    },
    {
        "id": "D_plus_risk",
        "label": "Qwen+GLM+Risk",
        "models": "both",
        "risk": True,
        "rag": False,
    },
    {
        "id": "E_plus_rag",
        "label": "Qwen+GLM+Risk+RAG",
        "models": "both",
        "risk": True,
        "rag": True,
    },
    {
        "id": "F_full",
        "label": "Full system",
        "models": "both",
        "risk": True,
        "rag": True,
    },
]


def load_cases(path: Path) -> list[dict]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            cases.append(json.loads(line))
    return cases


def build_settings(base, variant: dict, provider_mode: str) -> object:
    from app.core.config import Settings

    kwargs = {
        "provider_mode": provider_mode,
        "enable_risk_engine": variant["risk"],
        "enable_evidence_rag": variant["rag"],
        "refine_with_evidence": variant["rag"],
        "reranker_enabled": True,
        "_env_file": None,
    }
    if provider_mode == "auto":
        kwargs["dashscope_api_key"] = (
            base.dashscope_api_key if variant["models"] in ("both", "qwen") else ""
        )
        kwargs["zhipu_api_key"] = (
            base.zhipu_api_key if variant["models"] in ("both", "glm") else ""
        )
    return Settings(**kwargs)


def build_variant_cache(base, provider_mode: str) -> dict[str, tuple]:
    from app.services.providers import build_providers
    from app.services.rag import RAGService

    cache: dict[str, tuple] = {}
    for variant in VARIANTS:
        settings = build_settings(base, variant, provider_mode)
        providers = build_providers(settings)
        cache[variant["id"]] = (
            settings,
            providers[0],
            RAGService(settings, providers[0]),
        )
    return cache


def predicted_level(state: dict) -> int | None:
    risk = state.get("risk_result") or {}
    if risk.get("operational_level"):
        return int(risk["operational_level"])
    final_severity = (state.get("ensemble_judge") or {}).get("final_severity")
    if final_severity:
        return {3: 1, 2: 2, 1: 3}.get(int(final_severity))
    return None


def run_variant(case: dict, variant: dict, entry: tuple) -> dict:
    from app.services.workflow import run_workflow

    settings, _provider, rag = entry
    state = run_workflow(
        description=case["description"],
        images=[],
        followup_answer=None,
        followup_used=0,
        settings=settings,
        rag=rag,
    )
    if state.get("status") == "needs_more_info" and case.get("followup_answer"):
        state = run_workflow(
            description=case["description"],
            images=[],
            followup_answer=case["followup_answer"],
            followup_used=1,
            settings=settings,
            rag=rag,
        )
    terms = case.get("expected_clause_terms", [])
    evidence_texts = [
        str(item.get("text", "")) for item in state.get("evidence", [])
    ]
    joined_evidence = " ".join(evidence_texts)
    pred_category = state.get("hazard_category")
    pred_level = predicted_level(state)
    expected_level = case.get("expected_level")
    review_required = state.get("status") in (
        "awaiting_human_review",
        "needs_review",
    )
    disagreement = state.get("disagreement") or {}
    return {
        "case_id": case["id"],
        "variant": variant["id"],
        "label": variant["label"],
        "expected_level": expected_level,
        "category_match": pred_category == case["expected_category"],
        "level_match": pred_level == expected_level,
        "tolerance": pred_level is not None
        and expected_level is not None
        and abs(pred_level - expected_level) <= 1,
        "clause_hit": any(term in joined_evidence for term in terms),
        "review_required": review_required,
        "high_risk_reviewed": expected_level == 1 and review_required,
        "disagreement": bool(
            disagreement.get("need_human_review")
            or disagreement.get("critical_conflict")
        )
        and variant["models"] == "both",
    }


def summarize_rows(rows: list[dict]) -> dict:
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
    lines.extend(
        [
            "",
            "说明：A/B/C 为真实模型组合差异；D 加入 Risk Engine；E 加入 Evidence RAG；"
            "F 为完整系统（含人工复核路由）。Mock 模式下 A/B/C 使用同一确定性 Mock，"
            "真实模型差异需 `--provider auto` 获得。",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="消融评测")
    parser.add_argument("--provider", default="mock", choices=["mock", "auto"])
    parser.add_argument("--cases", type=Path, default=EVAL_CASES)
    parser.add_argument("--output", type=Path, default=EVAL_DIR)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    os.environ["PROVIDER_MODE"] = args.provider
    from app.core.config import get_settings

    cases = load_cases(args.cases)
    if args.limit is not None:
        cases = cases[: args.limit]
    base = get_settings()
    cache = build_variant_cache(base, args.provider)
    rows: list[dict] = []
    for case in cases:
        for variant in VARIANTS:
            rows.append(run_variant(case, variant, cache[variant["id"]]))
    summary = summarize_rows(rows)

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "ablation_report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (args.output / "ablation_report.md").write_text(
        build_markdown(summary),
        encoding="utf-8",
    )
    with (args.output / "ablation_results.jsonl").open(
        "w", encoding="utf-8"
    ) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print("== 消融评测 ==")
    for key, value in summary.items():
        print(f"{key}: {value['label']} cat={value['category_accuracy']} "
              f"level={value['level_accuracy']} "
              f"tolerance={value['level_tolerance_accuracy']} "
              f"clause={value['clause_hit_rate']} "
              f"review={value['review_rate']} "
              f"disagree={value['disagreement_rate']}")


if __name__ == "__main__":
    main()
