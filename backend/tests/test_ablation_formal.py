"""Phase 8: formal ablation comparison and docs generation."""

import json
import sys
from pathlib import Path

from app.core.config import Settings
from app.eval.dataset import EvalCase, load_dataset
from app.eval.evaluation import (
    build_ablation_markdown,
    build_variant_runtimes,
    run_ablation,
)


ROOT = Path(__file__).resolve().parents[2]


def _dataset():
    return load_dataset(
        ROOT / "backend" / "data" / "eval_cases" / "cases.jsonl",
        dataset_version="v1",
    )


def _comparison(limit=1):
    base = Settings(provider_mode="mock", _env_file=None)
    runtimes = build_variant_runtimes(base, provider_mode="mock")
    return run_ablation(
        _dataset(),
        provider_mode="mock",
        runtimes=runtimes,
        limit=limit,
    )


def test_comparison_marks_each_variant_mode():
    comparison = _comparison()
    for name, item in comparison["variants"].items():
        assert item["mode"] == "mock"
        assert "metrics" in item


def test_comparison_tracks_dataset_partition_and_version():
    comparison = _comparison()
    assert comparison["dataset_version"] == "v1"
    assert comparison["case_count"] == 1
    assert comparison["provider_mode"] == "mock"
    assert comparison["evaluation_mode"] in ("mock", "real")
    assert comparison["source_type_counts"].get("curated", 0) >= 1
    assert "partitions" in comparison


def test_ablation_markdown_contains_mode_and_partition_columns():
    markdown = build_ablation_markdown(_comparison())
    assert "数据模式" in markdown
    assert "curated" in markdown
    assert "Unsafe Auto-Pass" in markdown
    assert "real" in markdown or "mock" in markdown


def test_docs_generator_writes_expected_layout(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_eval_docs

    eval_dir = tmp_path / "eval"
    eval_dir.mkdir()
    cases_dir = eval_dir.parent / "eval_cases"
    cases_dir.mkdir(parents=True)
    (cases_dir / "cases.jsonl").write_text(
        "{\"id\":\"doc-001\",\"scenario\":\"消防\",\"description\":\"楼道堆物\","
        "\"expected_category\":\"占用疏散通道\",\"expected_level\":1}\n",
        encoding="utf-8",
    )
    (cases_dir / "dataset_meta.json").write_text(
        json.dumps({"title": "测试数据集", "created_at": "2026-09-10"}),
        encoding="utf-8",
    )
    report = {
        "dataset_version": "v1",
        "case_count": 1,
        "provider_mode": "mock",
        "source_type_counts": {"curated": 1},
        "variants": {
            "full": {
                "label": "Full system",
                "mode": "mock",
                "metrics": {"category_accuracy": 1.0},
            }
        },
    }
    (eval_dir / "ablation_report.json").write_text(
        json.dumps(report, ensure_ascii=False),
        encoding="utf-8",
    )
    (eval_dir / "ablation_report.md").write_text("# 消融评测报告\n", encoding="utf-8")
    (eval_dir / "ablation_results.jsonl").write_text("{}\n", encoding="utf-8")
    (eval_dir / "report.md").write_text("# 正式评测报告\n", encoding="utf-8")
    (eval_dir / "report.json").write_text("{}", encoding="utf-8")
    (eval_dir / "results.jsonl").write_text("{}\n", encoding="utf-8")

    docs_dir = tmp_path / "docs"
    old_argv = sys.argv
    old_eval_dir = build_eval_docs.EVAL_DIR
    old_docs_dir = build_eval_docs.DOCS_DIR
    build_eval_docs.EVAL_DIR = eval_dir
    build_eval_docs.DOCS_DIR = docs_dir
    sys.argv = ["build_eval_docs", "--eval-dir", str(eval_dir), "--docs-dir", str(docs_dir)]
    try:
        build_eval_docs.main()
    finally:
        build_eval_docs.EVAL_DIR = old_eval_dir
        build_eval_docs.DOCS_DIR = old_docs_dir
        sys.argv = old_argv
    assert (docs_dir / "README.md").exists()
    assert (docs_dir / "reports" / "ablation_report.md").exists()
    assert (docs_dir / "results" / "ablation_results.jsonl").exists()
    assert (docs_dir / "dataset" / "dataset_meta.json").exists()
    readme = (docs_dir / "README.md").read_text(encoding="utf-8")
    assert "消融对比表" in readme
    assert "curated" in readme


def test_eval_case_sources_remain_explicit_in_traces():
    comparison = _comparison()
    trace = comparison["results"][0]
    assert trace["case"]["source_type"] in ("curated", "donated", "official", "synthetic")
    assert trace["provider_mode"] in ("mock", "real")
    _ = EvalCase  # keep import used for schema-level expectations
