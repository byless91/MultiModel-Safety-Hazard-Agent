# -*- coding: utf-8 -*-
"""Compare vector-only vs vector+reranker retrieval on the labeled eval set."""

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


def load_cases(path: Path) -> list[dict]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            cases.append(json.loads(line))
    return cases


def retrieve(rag, query: str, tags: list[str], enabled: bool) -> list[dict]:
    results = (
        rag.search(query, top_k=5, tags=tags, reranker_enabled=enabled)
        if tags
        else []
    )
    if not results:
        results = rag.search(query, top_k=5, reranker_enabled=enabled)
    return results


def _clause_stats(results: list[dict], terms: list[str]) -> dict:
    texts = [str(item.get("text", "")) for item in results]
    hit = any(term in " ".join(texts) for term in terms)
    first_hit = bool(texts) and any(term in texts[0] for term in terms)
    rank = next(
        (
            index + 1
            for index, text in enumerate(texts)
            if any(term in text for term in terms)
        ),
        None,
    )
    return {
        "hit": hit,
        "first_hit": first_hit,
        "match_rank": rank,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Reranker 对比评测")
    parser.add_argument("--cases", type=Path, default=EVAL_CASES)
    parser.add_argument("--output", type=Path, default=EVAL_DIR)
    args = parser.parse_args()

    os.environ["PROVIDER_MODE"] = "mock"
    from app.services.ensemble.categories import rag_tags_for_category
    from app.services.rag import get_rag

    cases = load_cases(args.cases)
    rag = get_rag()
    details = []
    for case in cases:
        query = case["description"]
        tags = rag_tags_for_category(case["expected_category"])
        terms = case.get("expected_clause_terms", [])
        vector_only = retrieve(rag, query, tags, False)
        reranked = retrieve(rag, query, tags, True)
        base_stats = _clause_stats(vector_only, terms)
        rerank_stats = _clause_stats(reranked, terms)
        details.append(
            {
                "id": case["id"],
                "vector_only_hit": base_stats["hit"],
                "reranker_hit": rerank_stats["hit"],
                "vector_only_first_hit": base_stats["first_hit"],
                "reranker_first_hit": rerank_stats["first_hit"],
                "vector_only_match_rank": base_stats["match_rank"],
                "reranker_match_rank": rerank_stats["match_rank"],
                "changed": base_stats["hit"] != rerank_stats["hit"],
            }
        )

    total = len(details)
    base_rate = sum(item["vector_only_hit"] for item in details) / total
    rerank_rate = sum(item["reranker_hit"] for item in details) / total
    base_first_rate = sum(item["vector_only_first_hit"] for item in details) / total
    rerank_first_rate = sum(item["reranker_first_hit"] for item in details) / total
    base_ranks = [item["vector_only_match_rank"] or 6 for item in details]
    rerank_ranks = [item["reranker_match_rank"] or 6 for item in details]
    summary = {
        "total": total,
        "vector_only_clause_hit_rate": round(base_rate, 4),
        "vector_plus_reranker_clause_hit_rate": round(rerank_rate, 4),
        "absolute_delta": round(rerank_rate - base_rate, 4),
        "vector_only_first_hit_rate": round(base_first_rate, 4),
        "vector_plus_reranker_first_hit_rate": round(rerank_first_rate, 4),
        "avg_first_match_rank_vector_only": round(
            sum(base_ranks) / len(base_ranks), 3
        ),
        "avg_first_match_rank_with_reranker": round(
            sum(rerank_ranks) / len(rerank_ranks), 3
        ),
        "improved_cases": sum(
            1 for item in details if item["reranker_hit"] and not item["vector_only_hit"]
        ),
        "regressed_cases": sum(
            1 for item in details if item["vector_only_hit"] and not item["reranker_hit"]
        ),
    }

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "reranker_report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (args.output / "reranker_results.jsonl").open(
        "w", encoding="utf-8"
    ) as handle:
        for item in details:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    print("== Reranker 对比评测 ==")
    for key, value in summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
