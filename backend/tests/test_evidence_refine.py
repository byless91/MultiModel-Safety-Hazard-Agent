from app.core.config import Settings
from app.services.ensemble.schemas import ModelRunResult, MultiModelResult
from app.services.evidence_refine import refine_with_evidence
from app.services.langgraph_flow import get_graph
from app.services.providers.mock import MockProvider


class FakeProvider:
    name = "qwen-vl"
    family = "qwen-vl"


class StubRag:
    texts = ["法规原文"]

    def search(self, query, top_k=5, tags=None, *, include_demo=False):
        return [
            {
                "id": "law-fire-028-chunk-0",
                "source": "国家法律法规数据库；官方公开现行文本",
                "document": "中华人民共和国消防法",
                "article": "第二十八条",
                "version": "2021年修正",
                "tags": ["消防", "疏散通道"],
                "text": "不得占用、堵塞、封闭疏散通道、安全出口。",
                "score": 0.8,
            }
        ]


def _retrieval_state() -> dict:
    return {
        "description": "小区楼道堆放纸箱杂物，堵塞疏散通道",
        "images": [],
        "retrieval": [
            {
                "id": "law-fire-028-chunk-0",
                "document": "中华人民共和国消防法",
                "article": "第二十八条",
                "text": "不得占用、堵塞、封闭疏散通道、安全出口。",
            }
        ],
    }


def _fake_run(**kwargs):
    run = ModelRunResult(
        provider="qwen-vl",
        family="qwen-vl",
        model="qwen-vl-plus",
        status="success",
        analysis={
            "scene_summary": "现场疑似存在占用疏散通道风险",
            "hazard_hints": ["占用疏散通道"],
            "observations": ["疏散通道被纸箱堵塞"],
            "keywords": ["纸箱", "疏散通道"],
            "vision_confidence": 0.9,
            "hazards": [
                {
                    "hazard_type": "占用疏散通道",
                    "description": "疏散通道被纸箱堵塞",
                    "severity": 3,
                    "confidence": 0.9,
                    "observed_facts": ["疏散通道被纸箱堵塞"],
                }
            ],
            "rule": {},
            "rule_score": 0.6,
        },
    )
    return MultiModelResult(
        ensemble_mode="single_real",
        results=[run],
        primary=run,
        succeeded=1,
        failed=0,
        total_latency_ms=1.0,
    )


def test_refine_runs_with_final_evidence(monkeypatch):
    captured = {}

    def fake_run(providers, images, text, *, rag_evidence=None, ocr_texts=None):
        captured["providers"] = providers
        captured["rag_evidence"] = rag_evidence
        captured["ocr_texts"] = ocr_texts
        return _fake_run()

    monkeypatch.setattr(
        "app.services.evidence_refine.run_parallel_analysis",
        fake_run,
    )
    settings = Settings(provider_mode="mock", refine_with_evidence=True, _env_file=None)
    result = refine_with_evidence(
        _retrieval_state(),
        providers=[FakeProvider()],
        settings=settings,
    )
    assert result["refined_with_evidence"] is True
    assert result["evidence_refine_used"] is True
    assert captured["rag_evidence"] == [
        "不得占用、堵塞、封闭疏散通道、安全出口。"
    ]
    assert result["model_results"][0]["status"] == "success"
    assert result["scene_summary"] == "现场疑似存在占用疏散通道风险"


def test_refine_skips_mock_providers(monkeypatch):
    def fail_run(*args, **kwargs):
        raise AssertionError("mock 模式不应触发二次研判")

    monkeypatch.setattr(
        "app.services.evidence_refine.run_parallel_analysis",
        fail_run,
    )
    settings = Settings(provider_mode="mock", refine_with_evidence=True, _env_file=None)
    result = refine_with_evidence(
        _retrieval_state(),
        providers=[MockProvider()],
        settings=settings,
    )
    assert result == {}


def test_refine_skips_when_disabled(monkeypatch):
    def fail_run(*args, **kwargs):
        raise AssertionError("禁用时不应触发二次研判")

    monkeypatch.setattr(
        "app.services.evidence_refine.run_parallel_analysis",
        fail_run,
    )
    settings = Settings(provider_mode="mock", refine_with_evidence=False, _env_file=None)
    result = refine_with_evidence(
        _retrieval_state(),
        providers=[FakeProvider()],
        settings=settings,
    )
    assert result == {}


def test_refine_skips_without_retrieval(monkeypatch):
    def fail_run(*args, **kwargs):
        raise AssertionError("无检索证据时不应触发二次研判")

    monkeypatch.setattr(
        "app.services.evidence_refine.run_parallel_analysis",
        fail_run,
    )
    settings = Settings(provider_mode="mock", refine_with_evidence=True, _env_file=None)
    result = refine_with_evidence(
        {"description": "x", "images": []},
        providers=[FakeProvider()],
        settings=settings,
    )
    assert result == {}


def test_refine_skips_after_already_refined(monkeypatch):
    def fail_run(*args, **kwargs):
        raise AssertionError("已二次研判后不应重复调用")

    monkeypatch.setattr(
        "app.services.evidence_refine.run_parallel_analysis",
        fail_run,
    )
    settings = Settings(provider_mode="mock", refine_with_evidence=True, _env_file=None)
    state = _retrieval_state()
    state["refined_with_evidence"] = True
    result = refine_with_evidence(
        state,
        providers=[FakeProvider()],
        settings=settings,
    )
    assert result == {}


def test_langgraph_workflow_runs_refine_with_real_provider(monkeypatch):
    calls: list[list[str] | None] = []

    def fake_run(providers, images, text, *, rag_evidence=None, ocr_texts=None):
        calls.append(rag_evidence)
        return _fake_run()

    monkeypatch.setattr(
        "app.services.langgraph_flow.run_parallel_analysis",
        fake_run,
    )
    monkeypatch.setattr(
        "app.services.evidence_refine.run_parallel_analysis",
        fake_run,
    )
    settings = Settings(provider_mode="mock", refine_with_evidence=True, _env_file=None)
    initial_state = {
        "description": "小区楼道堆放纸箱杂物，堵塞疏散通道",
        "images": [],
        "settings": settings,
        "provider": FakeProvider(),
        "providers": [FakeProvider()],
        "rag": StubRag(),
    }
    final_state = get_graph().invoke(initial_state)
    assert final_state["refined_with_evidence"] is True
    assert final_state["evidence_refine_used"] is True
    assert len(calls) >= 2
    assert calls[-1] == ["不得占用、堵塞、封闭疏散通道、安全出口。"]
