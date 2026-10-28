"""R5/T13: fail-closed startup and dependency readiness, independent of liveness."""

from types import SimpleNamespace

import numpy as np
import pytest
from app import main
from app.core import db as database
from app.core.config import get_settings
from app.services import rag as rag_module
from app.services import readiness
from app.services.bootstrap import bootstrap_knowledge
from app.services.providers.mock import MockProvider
from fastapi.testclient import TestClient


def fake_rag(*, count=1, demo=False, vectors=None):
    rag = rag_module.RAGService(get_settings(), MockProvider())
    rag.texts, rag.metas = ["测试知识"] * count, [{"is_demo": demo}] * count
    rag.vectors = np.ones((count if vectors is None else vectors, 2))
    rag.embedding_dim, rag._index = 2, None
    return rag


def test_healthy_dependencies_and_public_liveness(review_client):
    assert review_client.get("/api/v1/live").json() == {"status": "alive"}
    result = review_client.get("/api/v1/ready")
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["status"] == "ready" and all(body["checks"].values())
    assert body["knowledge_chunks"] > 0
    assert result.headers["Cache-Control"] == "no-store"


def test_database_failure_is_not_ready_but_liveness_survives_without_credentials_leaking(review_client, monkeypatch):
    def broken():
        raise RuntimeError("postgresql://private-user:private-password@private-db")

    monkeypatch.setattr(readiness, "SessionLocal", broken)
    result = review_client.get("/api/v1/ready")
    assert result.status_code == 503
    assert not result.json()["checks"]["database"]
    assert not result.json()["checks"]["schema"]
    assert "private-password" not in result.text and "private-db" not in result.text
    assert review_client.get("/api/v1/live").status_code == 200


def test_wrong_schema_revision_is_not_ready(review_client, monkeypatch):
    monkeypatch.setattr(readiness, "expected_heads", lambda: {"not-the-current-head"})
    response = review_client.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["database"]
    assert not response.json()["checks"]["schema"]


@pytest.mark.parametrize("case", ["empty", "demo_only", "index_mismatch"])
def test_empty_demo_only_or_inconsistent_knowledge_cannot_pass_readiness(review_client, monkeypatch, case):
    rag = fake_rag(count=0) if case == "empty" else fake_rag(demo=case == "demo_only",
                                                           vectors=0 if case == "index_mismatch" else 1)
    monkeypatch.setattr(readiness, "get_rag", lambda: rag)
    response = review_client.get("/api/v1/ready")
    assert response.status_code == 503 and not response.json()["checks"]["knowledge"]
    assert review_client.get("/api/v1/health").status_code == 200


def test_lost_persistent_corpus_does_not_hide_behind_in_memory_index(review_client, monkeypatch, tmp_path):
    empty = tmp_path / "empty-knowledge"
    empty.mkdir()
    monkeypatch.setattr(get_settings(), "knowledge_dir", empty)
    response = review_client.get("/api/v1/ready")
    assert response.status_code == 503 and not response.json()["checks"]["knowledge"]
    assert review_client.get("/api/v1/health").json()["rag_loaded"]


def test_unwritable_storage_is_reported_by_real_probe(review_client, monkeypatch, tmp_path):
    file = tmp_path / "not-a-directory"
    file.write_bytes(b"operator data")
    monkeypatch.setattr(get_settings(), "upload_dir", file)
    response = review_client.get("/api/v1/ready")
    assert response.status_code == 503 and not response.json()["checks"]["storage"]
    assert file.read_bytes() == b"operator data"


def test_missing_async_worker_is_not_ready(review_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "workflow_mode", "async")
    monkeypatch.setattr(readiness, "get_job_runner", lambda: SimpleNamespace(healthy=False))
    response = review_client.get("/api/v1/ready")
    assert response.status_code == 503 and not response.json()["checks"]["worker"]


def test_init_db_propagates_migration_failure(review_client, monkeypatch):
    def fail(_engine):
        raise RuntimeError("migration failed deliberately")

    monkeypatch.setattr(database, "upgrade_to_head", fail)
    with pytest.raises(RuntimeError, match="migration failed deliberately"):
        database.init_db()


def test_lifespan_never_serves_if_migrations_failed(monkeypatch):
    def fail():
        raise RuntimeError("startup migration failure")

    monkeypatch.setattr(main, "init_db", fail)
    with pytest.raises(RuntimeError, match="startup migration failure"):
        with TestClient(main.app):
            pytest.fail("application startup must not finish")


@pytest.mark.parametrize("faiss_enabled", [False, True])
def test_reloaded_persistent_index_is_ready_without_reembedding(review_client, monkeypatch, tmp_path, faiss_enabled):
    if faiss_enabled and not rag_module.HAS_FAISS:
        pytest.skip("native FAISS unavailable")
    monkeypatch.setattr(rag_module, "HAS_FAISS", faiss_enabled)
    monkeypatch.setattr(get_settings(), "knowledge_dir", tmp_path / "knowledge")
    monkeypatch.setattr(get_settings(), "faiss_index_dir", tmp_path / "faiss")
    bootstrap_knowledge(get_settings())
    first = rag_module.RAGService(get_settings(), MockProvider())
    first.load()

    class CachedOnlyProvider(MockProvider):
        def embed(self, texts):
            pytest.fail("readiness/index reload must not call embedding again")

    restored = rag_module.RAGService(get_settings(), CachedOnlyProvider())
    restored.load()
    if faiss_enabled:
        assert restored.vectors.shape == (0, 0) and restored._index.ntotal > 0
    monkeypatch.setattr(readiness, "get_rag", lambda: restored)
    response = review_client.get("/api/v1/ready")
    assert response.status_code == 200, response.text
    assert response.json()["checks"]["knowledge"]
