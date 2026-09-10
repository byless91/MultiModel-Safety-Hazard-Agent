"""Phase 9: complete evaluation report with overview and limitations."""

from pathlib import Path

from app.eval.dataset import EvalCase, load_dataset
from app.eval.evaluation import build_evaluation_report


ROOT = Path(__file__).resolve().parents[2]


def _dataset():
    return load_dataset(
        ROOT / "backend" / "data" / "eval_cases" / "cases.jsonl",
        dataset_version="v1",
    )


def _trace(case_id, *, expected="占用疏散通道", level=1, source_type="curated"):
    return {
        "case": {
            "case_id": case_id,
            "scenario": "消防",
            "expected_category": expected,
            "expected_level": level,
            "ground_truth_hazard_present": True,
            "source_type": source_type,
        },
        "model_a_result": {
            "status": "success",
            "family": "qwen-vl",
            "analysis": {"model_category": expected, "model_severity": level},
        },
        "model_b_result": {
            "status": "success",
            "family": "glm-v",
            "analysis": {"model_category": expected, "model_severity": level},
        },
        "predicted_category": expected,
        "predicted_level": level,
        "status": "awaiting_human_review",
        "review_required": True,
        "auto_passed": False,
        "evidence_status": "supported",
        "risk_result": {"risk_level": "high", "risk_score": 86, "review_suggestion": True},
        "evidence": {
            "supported": True,
            "finding_status": [{"supported": True}],
            "unsupported_claims": [],
        },
        "disagreement": {"reasons": []},
        "latency_s": 0.5,
        "metric_flags": {
            "category_match": True,
            "level_match": True,
            "level_tolerance": True,
            "severity_mae": 0,
            "clause_hit": True,
            "evidence_support": True,
            "evidence_failure": False,
            "unsupported_claims": False,
            "model_conflict": False,
            "conflict_category": False,
            "human_review": True,
            "unsafe_auto_pass": False,
            "multi_model_configured": True,
            "false_positive": False,
            "false_negative": False,
            "severity_error": False,
            "hazard_present_ground_truth": True,
        },
    }


def test_report_contains_overview_performance_and_limitations():
    summary, markdown = build_evaluation_report(
        _dataset(),
        [_trace("ev-001"), _trace("ev-002")],
        provider_mode="mock",
    )
    overview = summary["dataset_overview"]
    assert overview["case_count"] == 30
    assert overview["safe_negative_case_count"] == 0
    assert "缺少无隐患负样本" in overview["limitation_notes"][0]
    assert "模块表现" in markdown
    assert "Dataset Overview" in markdown
    assert "Limitations" in markdown
    assert summary["model_family_performance"][0]["family"] == "glm-v"


def test_report_family_performance_only_counts_successful_runs():
    trace = _trace("ev-a01")
    trace["model_a_result"]["status"] = "failed"
    trace["model_b_result"]["analysis"]["model_category"] = "电气线路隐患"
    summary, _ = build_evaluation_report(
        _dataset(),
        [trace],
        provider_mode="mock",
    )
    families = {row["family"]: row for row in summary["model_family_performance"]}
    assert families["glm-v"]["category_accuracy"] == 0.0


def test_ablation_study_embedded_when_provided():
    ablation = {
        "dataset_version": "v1",
        "variants": {
            "qwen": {
                "label": "Qwen only",
                "metrics": {"category_accuracy": 0.9, "level_accuracy": 0.2, "unsafe_auto_pass_rate": 0.0},
            },
            "full": {
                "label": "Full system",
                "metrics": {"category_accuracy": 1.0, "level_accuracy": 0.7, "unsafe_auto_pass_rate": 0.0},
            },
        },
    }
    _summary, markdown = build_evaluation_report(
        _dataset(),
        [_trace("ev-b01")],
        provider_mode="mock",
        ablation_summary=ablation,
    )
    assert "Ablation Study" in markdown
    assert "Qwen only" in markdown
    assert "Full system" in markdown


def test_eval_case_schema_keeps_synthetic_partition():
    case = EvalCase.model_validate(
        {
            "id": "ev-syn-001",
            "scenario": "消防",
            "description": "合成边界案例描述",
            "expected_category": "占用疏散通道",
            "expected_level": 2,
            "source_type": "synthetic",
        }
    )
    assert case.source_type.value == "synthetic"


def test_docs_readme_uses_evaluation_payload(tmp_path):
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    import build_eval_docs

    readme = build_eval_docs.build_readme(
        dataset_version="v1",
        case_count=30,
        provider_mode="mock",
        variants={},
        partitions={"curated": 30},
        evaluation_payload={
            "dataset_overview": {
                "category_counts": {"占用疏散通道": 9},
                "severity_counts": {"1": 12},
                "hazard_case_count": 30,
                "safe_negative_case_count": 0,
                "image_case_count": 0,
                "limitation_notes": ["缺少无隐患负样本"],
            },
            "limitations": ["未进行真实图片评测"],
        },
        generated_at="2026-09-10T00:00:00+00:00",
    )
    assert "Dataset Overview" in readme
    assert "Limitations" in readme
    assert "缺少无隐患负样本" in readme
    assert "未进行真实图片评测" in readme
