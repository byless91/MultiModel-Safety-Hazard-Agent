import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import ablation as ablation_pipeline
from app.core.config import get_settings


def test_ablation_runs_all_variants_in_mock_mode():
    base = get_settings()
    cache = ablation_pipeline.build_variant_cache(base, "mock")
    case = {
        "id": "ablation-test-001",
        "scenario": "消防",
        "description": "小区楼道堆放纸箱杂物，堵塞疏散通道",
        "expected_category": "占用疏散通道",
        "expected_level": 1,
        "expected_clause_terms": ["疏散通道"],
    }
    rows = [
        ablation_pipeline.run_variant(case, variant, cache[variant["id"]])
        for variant in ablation_pipeline.VARIANTS
    ]
    assert len(rows) == 6
    assert {row["variant"] for row in rows} == {
        variant["id"] for variant in ablation_pipeline.VARIANTS
    }
    assert all(row["category_match"] for row in rows)


def test_ablation_summary_reports_full_review_rate():
    base = get_settings()
    cache = ablation_pipeline.build_variant_cache(base, "mock")
    case = {
        "id": "ablation-test-002",
        "scenario": "消防",
        "description": "小区楼道堆放纸箱杂物，堵塞疏散通道",
        "expected_category": "占用疏散通道",
        "expected_level": 1,
        "expected_clause_terms": ["疏散通道"],
    }
    rows = [
        ablation_pipeline.run_variant(case, variant, cache[variant["id"]])
        for variant in ablation_pipeline.VARIANTS
    ]
    summary = ablation_pipeline.summarize_rows(rows)
    full = summary["F_full"]
    assert full["total"] == 1
    assert full["category_accuracy"] == 1.0
    assert full["review_rate"] == 1.0
    assert full["high_risk_review_rate"] == 1.0
    markdown = ablation_pipeline.build_markdown(summary)
    assert "Full system" in markdown
    assert "消融评测报告" in markdown
