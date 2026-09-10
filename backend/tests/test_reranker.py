import json

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app
from app.services.providers import MockProvider
from app.services.rag import RAGService, rerank_results


def test_rerank_prioritizes_lexical_match_over_raw_vector():
    results = [
        {
            "id": "a",
            "text": "化学品仓库应分类存放并保持通风",
            "score": 0.9,
            "tags": [],
            "article": "",
        },
        {
            "id": "b",
            "text": "不得占用、堵塞、封闭疏散通道、安全出口",
            "score": 0.2,
            "tags": ["消防"],
            "article": "第二十八条",
        },
    ]
    reranked = rerank_results("占用疏散通道", results, top_n=5)
    assert reranked[0]["id"] == "b"
    assert "rerank_score" in reranked[0]
    assert "vector_score" in reranked[0]


def test_rerank_boosts_article_metadata():
    results = [
        {
            "id": "no-article",
            "text": "疏散通道不得被占用",
            "score": 0.5,
            "tags": [],
            "article": "",
        },
        {
            "id": "with-article",
            "text": "疏散通道不得被占用",
            "score": 0.5,
            "tags": [],
            "article": "第二十八条",
        },
    ]
    reranked = rerank_results("疏散通道占用", results, top_n=1)
    assert reranked[0]["id"] == "with-article"


def test_search_respects_reranker_enabled_flag(tmp_path):
    chunks = [
        {
            "id": "c-fire",
            "document": "消防法",
            "article": "第二十八条",
            "source": "官网",
            "version": "v1",
            "tags": ["消防", "疏散通道"],
            "text": "不得占用疏散通道、安全出口",
        },
        {
            "id": "c-forest",
            "document": "森林法",
            "article": "第三条",
            "source": "官网",
            "version": "v1",
            "tags": ["森林防火"],
            "text": "林区防火期内禁止野外用火",
        },
    ]
    (tmp_path / "chunks.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in chunks),
        encoding="utf-8",
    )
    settings = Settings(
        provider_mode="mock",
        knowledge_dir=str(tmp_path),
        reranker_enabled=True,
        _env_file=None,
    )
    rag = RAGService(settings, MockProvider())
    plain = rag.search("疏散通道占用", top_k=5, reranker_enabled=False)
    assert plain
    assert not any("rerank_score" in item for item in plain)
    reranked = rag.search("疏散通道占用", top_k=5, reranker_enabled=True)
    assert reranked
    assert all("rerank_score" in item for item in reranked)
    assert reranked[0]["id"] == "c-fire"


def test_health_exposes_reranker_enabled():
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["reranker_enabled"] in (True, False)
