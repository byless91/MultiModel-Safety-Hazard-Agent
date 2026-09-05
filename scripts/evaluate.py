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
        "needs_review_count": sum(1 for r in results if r["status"] == "needs_review"),
        "completed_count": sum(1 for r in results if r["status"] == "completed"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="运行离线评测并生成报告")
    parser.add_argument("--provider", default="mock", choices=["mock", "auto"])
    parser.add_argument("--cases", type=Path, default=EVAL_CASES)
    parser.add_argument("--output", type=Path, default=EVAL_DIR)
    args = parser.parse_args()

    os.environ["PROVIDER_MODE"] = args.provider
    cases = load_cases(args.cases)
    results = [run_case(case) for case in cases]
    summary = summarize(results)

    from app.services.providers import get_provider

    summary["provider"] = get_provider().name
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
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
