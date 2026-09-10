"""Phase 6: formal MultiModel comparison and failure-mode semantics."""

from pathlib import Path

from app.core.config import Settings
from app.eval.dataset import EvalCase, load_dataset
from app.eval.evaluation import (
    VARIANT_CONFIGS,
    build_ablation_markdown,
    build_variant_runtimes,
    pick_variant,
    run_ablation,
    run_evaluation_case,
)
from app.services.providers import MockProvider
from app.services.providers.base import BaseProvider
from app.services.providers.base import ModelUnavailableError


def _eval_case(overrides=None):
    payload = {
        "id": "eval-multi-001",
        "scenario": "消防",
        "description": "商场安全出口被货物堵住，出口大门上锁无法开启",
        "expected_category": "占用疏散通道",
        "expected_level": 1,
        "expected_clause_terms": ["安全出口"],
    }
    if overrides:
        payload.update(overrides)
    return EvalCase.model_validate(payload)


class _FailingStub(BaseProvider):
    name = "failing-stub"
    family = "qwen-vl"
    vision_model = "qwen-vl-plus"
    text_model = "qwen-plus"
    embedding_model = "text-embedding-v3"
    last_retry_count = 1

    def analyze(self, images, text, **kwargs):
        raise ModelUnavailableError("phase6-test: qwen unavailable")

    def embed(self, texts):
        raise ModelUnavailableError("phase6-test: embed unavailable")

    def complete(self, system, user):
        raise ModelUnavailableError("phase6-test: complete unavailable")


class _SucceedingStub(BaseProvider):
    name = "succeeding-stub"
    family = "glm-v"
    vision_model = "glm-4v-flash"
    text_model = "glm-4-flash"
    embedding_model = "embedding-2"
    last_retry_count = 0

    def analyze(self, images, text, **kwargs):
        return MockProvider().analyze(images, text, **kwargs)

    def embed(self, texts):
        raise ModelUnavailableError("phase6-test: embed unavailable")

    def complete(self, system, user):
        return {"text": ""}


def test_single_model_variant_reports_one_configured_slot():
    settings = Settings(
        provider_mode="mock",
        _env_file=None,
    )
    providers = [MockProvider()]
    trace = run_evaluation_case(
        _eval_case(),
        pick_variant("qwen"),
        settings=settings,
        providers=providers,
        rag=None,
    )
    assert trace["models"] == "qwen"
    assert len(providers) == 1
    assert trace["ensemble_mode"] == "mock"
    assert trace["model_a_result"]["status"] == "success"
    assert trace["model_b_result"]["status"] == "not_configured"


def test_ablation_runs_and_renders_comparison_table():
    dataset = load_dataset(
        Path(__file__).resolve().parents[1] / "data" / "eval_cases" / "cases.jsonl",
        dataset_version="v1",
    )
    base = Settings(provider_mode="mock", _env_file=None)
    runtimes = build_variant_runtimes(base, provider_mode="mock")
    comparison = run_ablation(dataset, provider_mode="mock", runtimes=runtimes, limit=1)
    assert comparison["case_count"] == 1
    assert set(comparison["variants"]) == set(VARIANT_CONFIGS)
    assert len(comparison["results"]) == len(VARIANT_CONFIGS)
    for name, item in comparison["variants"].items():
        assert "category_accuracy" in item["metrics"]
        assert "evidence_support_rate" in item["metrics"]
        assert "unsafe_auto_pass_rate" in item["metrics"]
        for trace in comparison["results"]:
            if trace["variant"] == VARIANT_CONFIGS[name]["id"]:
                assert trace["models"] in ("qwen", "glm", "both")
    markdown = build_ablation_markdown(comparison)
    assert "消融评测报告" in markdown
    assert "Qwen+GLM" in markdown
    assert "Unsafe Auto-Pass" in markdown


def test_legacy_ablation_cache_still_works():
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "scripts"))
    import ablation as ablation_pipeline

    base = Settings(provider_mode="mock", _env_file=None)
    cache = ablation_pipeline.build_variant_cache(base, "mock")
    case = {
        "id": "ablation-legacy-001",
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
    assert all(row["category_match"] for row in rows)
    assert {row["variant"] for row in rows} == {
        variant["id"] for variant in ablation_pipeline.VARIANTS
    }


def test_partial_ensemble_failure_routes_to_human_review():
    settings = Settings(
        provider_mode="mock",
        dashscope_api_key="",
        zhipu_api_key="",
        _env_file=None,
    )
    providers = [_FailingStub(), _SucceedingStub()]
    trace = run_evaluation_case(
        _eval_case(),
        pick_variant("full"),
        settings=settings,
        providers=providers,
        rag=None,
    )
    assert trace["ensemble_mode"] == "partial"
    assert trace["model_a_result"]["status"] == "failed"
    assert trace["model_b_result"]["status"] == "success"
    assert any(
        item.get("status") == "failed"
        for item in trace.get("model_results", [])
    )
    assert trace["review_required"] is True


def test_both_models_fail_marks_fallback_and_human_review():
    settings = Settings(
        provider_mode="mock",
        dashscope_api_key="",
        zhipu_api_key="",
        _env_file=None,
    )
    providers = [_FailingStub(), _FailingStub()]
    trace = run_evaluation_case(
        _eval_case({"user_text": "现场确认存在明火和可燃物，请继续研判"}),
        pick_variant("full"),
        settings=settings,
        providers=providers,
        rag=None,
    )
    assert trace["ensemble_mode"] == "fallback"
    assert trace["model_a_result"]["status"] == "failed"
    assert trace["model_b_result"]["status"] == "failed"
    assert trace["status"] == "awaiting_human_review"
    assert trace["metric_flags"]["unsafe_auto_pass"] is False
    assert any("Mock" in str(reason) for reason in trace.get("disagreement", {}).get("reasons", []))
