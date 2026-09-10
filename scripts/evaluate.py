# -*- coding: utf-8 -*-
"""Run offline evaluation against the labeled evaluation set."""

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

EVAL_CASES = BACKEND / "data" / "eval_cases" / "cases.jsonl"
EVAL_DIR = BACKEND / "data" / "eval"


def load_cases(path: Path) -> list[dict]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            cases.append(json.loads(line))
    return cases


def run_case(case: dict) -> dict:
    from app.services.workflow import run_workflow

    started = time.perf_counter()
    state = run_workflow(
        description=case["description"],
        images=[],
        followup_answer=None,
        followup_used=0,
    )
    if state.get("status") == "needs_more_info" and case.get("followup_answer"):
        state = run_workflow(
            description=case["description"],
            images=[],
            followup_answer=case["followup_answer"],
            followup_used=1,
        )
    elapsed = time.perf_counter() - started
    evidence_texts = [entry.get("text", "") for entry in state.get("evidence", [])]
    joined_evidence = " ".join(evidence_texts)
    expected_terms = case.get("expected_clause_terms", [])
    clause_hit = any(term in joined_evidence for term in expected_terms)
    grounded = bool(evidence_texts) and clause_hit
    return {
        "id": case["id"],
        "scenario": case.get("scenario", ""),
        "description": case["description"],
        "expected_category": case["expected_category"],
        "expected_level": case["expected_level"],
        "predicted_category": state.get("hazard_category"),
        "predicted_level": state.get("risk_level"),
        "status": state.get("status"),
        "confidence": state.get("confidence"),
        "clause_hit": clause_hit,
        "grounded": grounded,
        "category_match": state.get("hazard_category") == case["expected_category"],
        "level_match": state.get("risk_level") == case["expected_level"],
        "is_high_risk": case.get("expected_level") == 1,
        "review_required": state.get("status")
        in ("awaiting_human_review", "needs_review"),
        "auto_passed": state.get("status") == "completed",
        "unsafe_auto_pass": case.get("expected_level") == 1
        and state.get("status") == "completed",
        "evidence_count": len(evidence_texts),
        "latency_s": round(elapsed, 2),
    }


def summarize(results: list[dict]) -> dict:
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
            "category_accuracy": round(
                value["category_match"] / value["total"], 4
            ),
            "level_accuracy": round(value["level_match"] / value["total"], 4),
            "clause_hit_rate": round(value["clause_hit"] / value["total"], 4),
            "review_rate": round(
                value["review_required"] / value["total"], 4
            ),
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
        "hallucination_rate": round(
            1 - sum(r["grounded"] for r in results) / total, 4
        ),
        "avg_confidence": round(
            sum(r["confidence"] or 0 for r in results) / total, 4
        ),
        "avg_latency_s": round(sum(r["latency_s"] for r in results) / total, 3),
        "needs_review_count": sum(
            1
            for r in results
            if r["status"] in ("needs_review", "awaiting_human_review")
        ),
        "completed_count": sum(1 for r in results if r["status"] == "completed"),
        "high_risk_review_rate": round(
            sum(r["review_required"] for r in high_risk_cases)
            / max(1, len(high_risk_cases)),
            4,
        ),
        "high_risk_case_count": len(high_risk_cases),
        "unsafe_auto_pass_count": sum(
            1 for r in results if r["unsafe_auto_pass"]
        ),
        "unsafe_auto_pass_rate": round(
            sum(1 for r in high_risk_cases if r["unsafe_auto_pass"])
            / max(1, len(high_risk_cases)),
            4,
        ),
        "scenario_breakdown": scenario_breakdown,
    }


def build_markdown(results: list[dict], summary: dict) -> str:
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
    args = parser.parse_args()

    os.environ["PROVIDER_MODE"] = args.provider
    cases = load_cases(args.cases)
    if args.limit is not None:
        cases = cases[: args.limit]
    results = [run_case(case) for case in cases]
    summary = summarize(results)

    from app.services.providers import get_provider

    summary["provider"] = get_provider().name
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output / "report.md").write_text(
        build_markdown(results, summary), encoding="utf-8"
    )
    with (args.output / "results.jsonl").open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")

    print("== 评测摘要 ==")
    for key, value in summary.items():
        print(f"{key}: {value}")

    failed = [r for r in results if not r["category_match"] or not r["level_match"]]
    print(f"\n未完全命中案例：{len(failed)} 条")
    for item in failed[:8]:
        print(
            f"- {item['id']} 预测={item['predicted_category']}/{item['predicted_level']} "
            f"期望={item['expected_category']}/{item['expected_level']}"
        )


if __name__ == "__main__":
    main()
