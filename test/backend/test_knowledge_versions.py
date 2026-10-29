"""M2: version identity, human publication and immutable citations."""

import json
import threading
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest
from app.api import routes
from app.core.db import SessionLocal
from app.core.security import create_access_token
from app.models import Assessment, KnowledgeDocument, User
from app.schemas.knowledge import KnowledgeMetadataIn, KnowledgeReviewIn
from app.services.knowledge_versions import search_approved_knowledge
from app.services.rag import RAGService
from pydantic import ValidationError
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError


def test_approval_requires_explicit_source_check_and_nonblank_note():
    for payload in ({"source_checked": False, "note": "核对了"}, {"source_checked": True, "note": "  "}):
        with pytest.raises(ValidationError):
            KnowledgeReviewIn(decision="approve", revision=0, **payload)


def test_unknown_industry_is_not_silently_classified():
    with pytest.raises(ValidationError):
        KnowledgeMetadataIn(title="文档", industry="unknown-industry")


@pytest.mark.parametrize("duplicate", ["version", "active"])
def test_database_prevents_duplicate_versions_and_two_active_versions(review_client, duplicate):
    series = str(uuid4())
    with SessionLocal() as db:
        db.add_all([
            KnowledgeDocument(title="版本一", series_id=series, version="v1", review_status="approved"),
            KnowledgeDocument(title="版本二", series_id=series, version="v1" if duplicate == "version" else "v2",
                              review_status="unreviewed" if duplicate == "version" else "approved"),
        ])
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


@pytest.fixture
def knowledge_client(review_client):
    created = []

    def upload(*, version="v1", parent=None, body="第一条 测试材料：疏散通道应保持畅通。", **changes):
        data = {"title": "M2_TEST_ONLY_规范", "source": "https://example.test/official-law",
                "version": version, "industry": "fire", "applicability": "测试现场的疏散通道", **changes}
        if parent:
            data["supersedes_id"] = parent["id"]
        response = review_client.post("/api/v1/knowledge/documents", data=data,
                                      files={"file": ("law.txt", body.encode(), "text/plain")})
        assert response.status_code == 201, response.text
        doc = response.json()
        created.append(doc["id"])
        return doc

    yield review_client, upload
    with SessionLocal() as db:
        db.execute(delete(KnowledgeDocument).where(KnowledgeDocument.id.in_(created)))
        db.commit()


def publish(client, doc, **changes):
    return client.post(f"/api/v1/knowledge/documents/{doc['id']}/review", json={
        "decision": "approve", "revision": doc["revision"], "source_checked": True,
        "note": "测试用例人工审核，仅验证工程合同", **changes,
    })


def search(client, industry="fire"):
    result = client.get("/api/v1/knowledge/search", params={"query": "疏散通道", "industry": industry})
    assert result.status_code == 200, result.text
    return result.json()


def test_unreviewed_upload_is_searchable_only_after_explicit_publication(knowledge_client):
    client, upload = knowledge_client
    doc = upload()
    assert doc["review_status"] == "unreviewed" and doc["status"] == "indexed"
    assert search(client)["items"] == []
    response = publish(client, doc)
    assert response.status_code == 200, response.text
    approved = response.json()
    assert approved["review_status"] == "approved"
    assert len(search(client)["items"]) == 1
    row = search(client)["items"][0]
    assert row["document_id"] == doc["id"] and row["content_sha256"] == doc["content_sha256"]
    assert row["version"] == "v1" and row["applicability"] == doc["applicability"]
    assert search(client, "forest")["items"] == []
    assert publish(client, doc).json()["review_history"] == approved["review_history"]
    assert client.delete(f"/api/v1/knowledge/documents/{doc['id']}").status_code == 409


@pytest.mark.parametrize("metadata", [
    {"source": "无法定位的来源"}, {"version": "unversioned"}, {"applicability": ""}, {"is_demo": True},
])
def test_missing_provenance_and_demo_cannot_be_published(knowledge_client, metadata):
    client, upload = knowledge_client
    doc = upload(**metadata)
    assert publish(client, doc).status_code == 422
    assert search(client)["items"] == []


def test_new_version_keeps_old_document_and_record_citations_unchanged(knowledge_client, monkeypatch):
    client, upload = knowledge_client
    monkeypatch.setattr(routes.settings, "workflow_mode", "sync")
    first = publish(client, upload()).json()
    response = client.post("/api/v1/assessments", data={"description": "疏散通道被纸箱堵塞", "mode": "classification"})
    assert response.status_code == 201, response.text
    record = response.json()
    old_evidence = record["evidence"]
    assert old_evidence and old_evidence[0]["document_id"] == first["id"]
    second = upload(version="v2", parent=first, body="第一条 第二版测试材料：疏散通道应保持畅通，现场核实。")
    assert second["series_id"] == first["series_id"] and second["supersedes_id"] == first["id"]
    assert search(client)["items"][0]["version"] == "v1"
    assert publish(client, second).status_code == 200
    assert search(client)["items"][0]["version"] == "v2"
    old_doc = client.get(f"/api/v1/knowledge/documents/{first['id']}").json()
    assert old_doc["review_status"] == "superseded" and old_doc["content_sha256"] == first["content_sha256"]
    assert old_doc["content"] == "第一条 测试材料：疏散通道应保持畅通。"
    saved = client.get(f"/api/v1/assessments/{record['id']}").json()
    assert saved["evidence"] == old_evidence
    exported = client.get(f"/api/v1/assessments/{record['id']}/export").json()["content"]
    assert first["content_sha256"] in exported and "v1" in exported


def test_stale_index_cannot_return_a_retired_version(knowledge_client, monkeypatch):
    client, upload = knowledge_client
    doc = publish(client, upload()).json()
    assert search(client)["items"]
    def offline(**kwargs):
        raise RuntimeError("index offline")
    monkeypatch.setattr(routes, "rebuild_knowledge", offline)
    response = publish(client, doc, decision="retire", source_checked=False)
    assert response.status_code == 200 and response.json()["status"] == "index_error"
    assert response.json()["review_status"] == "retired"
    assert search(client)["items"] == []


def test_articles_are_complete_paginated_and_keep_their_own_numbers(knowledge_client):
    client, upload = knowledge_client
    doc = upload(body="第一条 通道检查。\n第二条 设备检查。\n第三条 林区检查。")
    url = f"/api/v1/knowledge/documents/{doc['id']}/articles"
    result = client.get(url, params={"offset": 1, "limit": 1}).json()
    assert result["total"] == 3 and len(result["items"]) == 1
    assert result["items"][0]["article"] == "第二条"
    assert result["items"][0]["version"] == "v1"
    assert client.get(url, params={"limit": 101}).status_code == 422


def test_referenced_draft_cannot_be_deleted_and_industry_filters_work(knowledge_client):
    client, upload = knowledge_client
    doc = upload(industry="community")
    with SessionLocal() as db:
        db.add(Assessment(description="测试旧引用", evidence_json=json.dumps([{"id": f"doc-{doc['id']}-chunk-0"}])))
        db.commit()
    assert client.delete(f"/api/v1/knowledge/documents/{doc['id']}").status_code == 409
    rows = client.get("/api/v1/knowledge/documents", params={"industry": "community"}).json()
    assert doc["id"] in {row["id"] for row in rows}
    other = client.get("/api/v1/knowledge/documents", params={"industry": "forest"}).json()
    assert doc["id"] not in {row["id"] for row in other}


@pytest.mark.parametrize("role", ["inspector", "reviewer"])
def test_only_administrators_can_publish_knowledge(knowledge_client, monkeypatch, role):
    client, upload = knowledge_client
    doc = upload()
    with SessionLocal() as db:
        user = User(username=f"m2-{uuid4().hex}", role=role, password_hash="unused")
        db.add(user)
        db.commit()
        token = create_access_token(user)
    monkeypatch.setattr(routes.settings, "auth_mode", "jwt")
    client.headers["Authorization"] = f"Bearer {token}"
    try:
        assert publish(client, doc).status_code == 403
        assert search(client)["items"] == []
    finally:
        client.headers.pop("Authorization", None)


def test_forged_index_text_or_hash_cannot_become_a_citation(knowledge_client):
    client, upload = knowledge_client
    publish(client, upload())
    row = search(client)["items"][0]
    for forged in ({**row, "text": "伪造的条款"}, {**row, "content_sha256": "0" * 64},
                   {**row, "document_id": "missing-document"}):
        rag = SimpleNamespace(search=lambda *args, row=forged, **kwargs: [row])
        assert search_approved_knowledge("疏散通道", rag=rag) == []


def test_many_unreviewed_chunks_cannot_crowd_out_the_approved_industry():
    rag = RAGService.__new__(RAGService)
    rag._lock = threading.RLock()
    rag.settings = SimpleNamespace(reranker_enabled=False)
    rag.texts = ["批准条款"] + ["未审核材料"] * 210
    rag.metas = [{"id": "approved", "document_id": "doc-1", "review_status": "approved", "industry": "forest"}]
    rag.metas += [{"id": str(i), "review_status": "unreviewed", "industry": "fire"} for i in range(210)]
    rag.vectors = np.arange(211, dtype=np.float32).reshape(-1, 1)
    rag._index = None
    rag.embedding_space, rag.embedding_fallback = "test", False
    rag._query_vector = lambda query: np.array([[1]], dtype=np.float32)
    results = rag.search("查询", top_k=1, approved_only=True, industry="forest")
    assert [row["id"] for row in results] == ["approved"]
