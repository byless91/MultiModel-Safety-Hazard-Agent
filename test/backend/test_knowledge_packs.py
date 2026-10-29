"""M6: verified knowledge packs, cloud review import, sync marker and citation preservation."""

import json
from hashlib import sha256
from uuid import uuid4

import pytest
from app.api import routes
from app.core.db import SessionLocal
from app.core.security import create_access_token
from app.models import Assessment, KnowledgeDocument, KnowledgePackImport, User
from app.services.knowledge_packs import PACK_FORMAT, manifest_hash
from sqlalchemy import delete, select

PREFIX = "M6_TEST_ONLY_"


@pytest.fixture
def records():
    ids: list[str] = []
    yield ids
    with SessionLocal() as db:
        if ids:
            db.execute(delete(Assessment).where(Assessment.id.in_(ids)))
        db.execute(delete(KnowledgeDocument).where(KnowledgeDocument.title.like(f"{PREFIX}%")))
        db.execute(delete(KnowledgePackImport).where(KnowledgePackImport.pack_version.like(f"{PREFIX}%")))
        db.commit()


def upload(client, records, *, version="v1", parent=None, body=None, title=None):
    body = body or "第一条 M6 测试材料：疏散通道应保持畅通。"
    data = {
        "title": title or f"{PREFIX}规范", "source": "https://example.test/m6-law",
        "version": version, "industry": "fire", "applicability": "M6 测试场景",
    }
    if parent:
        data["supersedes_id"] = parent["id"]
    response = client.post("/api/v1/knowledge/documents", data=data,
                           files={"file": ("law.txt", body.encode(), "text/plain")})
    assert response.status_code == 201, response.text
    doc = response.json()
    records.append(doc["id"])
    return doc


def approve(client, doc):
    response = client.post(f"/api/v1/knowledge/documents/{doc['id']}/review", json={
        "decision": "approve", "revision": doc["revision"], "source_checked": True,
        "note": "M6_TEST_ONLY 云端审核",
    })
    assert response.status_code == 200, response.text
    return response.json()


def pack_for(series_id, version, body, *, pack_version=f"{PREFIX}PACK-1"):
    digest = sha256(body.encode()).hexdigest()
    document = {
        "title": f"{PREFIX}云端规范", "source": "https://example.test/m6-law", "version": version,
        "industry": "fire", "applicability": "M6 测试场景", "content_text": body,
        "content_sha256": digest, "series_id": series_id, "review_status": "approved",
        "meta_json": json.dumps({"filename": "cloud.txt", "source_format": "txt", "is_demo": False}),
        "review_json": json.dumps({"revision": 1, "history": [{
            "action": "approve", "actor": "cloud-reviewer", "actor_id": "cloud-1",
            "at": "2026-10-30T00:00:00+00:00", "note": "云端已审核", "source_checked": True,
            "content_sha256": digest, "version": version,
        }]}, ensure_ascii=False),
    }
    return {
        "format": PACK_FORMAT, "pack_version": pack_version,
        "created_at": "2026-10-30T00:00:00+00:00", "review_policy": "approved_only",
        "documents": [document],
        "manifest": {"document_count": 1, "documents_sha256": manifest_hash([document])},
    }


def test_export_contains_only_latest_approved_versions_and_verifies_manifest(records, review_client):
    first = upload(review_client, records, version="v1")
    approve(review_client, first)
    second = upload(review_client, records, version="v2", parent=first,
                    body="第一条 M6 测试材料第二版：疏散通道应保持畅通，复核有效。")
    approve(review_client, second)
    pending = upload(review_client, records, version="v3", parent=second)
    assert pending["review_status"] == "unreviewed"

    pack = review_client.get("/api/v1/knowledge/pack/export")
    assert pack.status_code == 200, pack.text
    data = pack.json()
    assert data["format"] == PACK_FORMAT and data["review_policy"] == "approved_only"
    assert len(data["documents"]) == 1
    assert data["documents"][0]["version"] == "v2"
    assert data["manifest"]["documents_sha256"] == manifest_hash(data["documents"])
    assert data["pack_version"].startswith("20")


def test_import_is_idempotent_and_updates_the_local_sync_marker(records, review_client):
    doc = upload(review_client, records, version="v1")
    pack = pack_for(doc["series_id"], "v1", "第一条 M6 测试材料：疏散通道应保持畅通。")
    first = review_client.post("/api/v1/knowledge/pack/import", json=pack)
    assert first.status_code == 200, first.text
    result = first.json()
    assert result["imported"] == 0 and result["skipped"] == 1 and result["failed"] == 0
    assert result["indexed"] is False
    status = review_client.get("/api/v1/knowledge/pack/status").json()
    assert status["last_sync"]["pack_version"] == pack["pack_version"]
    assert status["last_sync"]["manifest_sha256"] == pack["manifest"]["documents_sha256"]
    second = review_client.post("/api/v1/knowledge/pack/import", json=pack).json()
    assert second["imported"] == 0 and second["skipped"] == 1


def test_tampered_or_unapproved_pack_is_rejected_without_import(records, review_client):
    doc = upload(review_client, records, version="v1")
    pack = pack_for(doc["series_id"], "v2", "新的测试条款")
    pack["documents"][0]["content_text"] = "被篡改的条款"
    assert review_client.post("/api/v1/knowledge/pack/import", json=pack).status_code == 422

    unapproved = pack_for(doc["series_id"], "v2", "新的测试条款")
    unapproved["documents"][0]["review_status"] = "unreviewed"
    unapproved["manifest"] = {"document_count": 1, "documents_sha256": manifest_hash(unapproved["documents"])}
    assert review_client.post("/api/v1/knowledge/pack/import", json=unapproved).status_code == 422
    with SessionLocal() as db:
        assert db.scalars(select(KnowledgeDocument).where(
            KnowledgeDocument.title.like(f"{PREFIX}云端%"))).all() == []
        assert db.scalars(select(KnowledgePackImport).where(
            KnowledgePackImport.pack_version.like(f"{PREFIX}%"))).all() == []


def test_import_new_version_supersedes_old_and_preserves_existing_citations(records, review_client, monkeypatch):
    monkeypatch.setattr(routes.settings, "workflow_mode", "sync")
    first = upload(review_client, records, version="v1",
                   body="第一条 M6 测试材料：疏散通道应保持畅通。")
    approve(review_client, first)
    response = review_client.post("/api/v1/assessments", data={
        "description": "疏散通道被纸箱堵塞", "mode": "classification",
    })
    assert response.status_code == 201, response.text
    record = response.json()
    records.append(record["id"])
    assert record["evidence"][0]["document_id"] == first["id"]
    old_evidence = record["evidence"]

    pack = pack_for(first["series_id"], "v2", "第一条 M6 测试材料第二版：疏散通道应保持畅通，需现场复核。")
    imported = review_client.post("/api/v1/knowledge/pack/import", json=pack)
    assert imported.status_code == 200, imported.text
    result = imported.json()
    assert result["imported"] == 1 and result["superseded"] == 1 and result["indexed"] is True

    old = review_client.get(f"/api/v1/knowledge/documents/{first['id']}").json()
    assert old["review_status"] == "superseded" and old["content"] == "第一条 M6 测试材料：疏散通道应保持畅通。"
    saved = review_client.get(f"/api/v1/assessments/{record['id']}").json()
    assert saved["evidence"] == old_evidence
    search = review_client.get("/api/v1/knowledge/search", params={"query": "疏散通道", "industry": "fire"}).json()
    assert search["items"][0]["version"] == "v2"
    assert first["content_sha256"] in review_client.get(
        f"/api/v1/assessments/{record['id']}/export").json()["content"]


def test_conflicting_version_is_reported_while_other_documents_import(records, review_client):
    local = upload(review_client, records, version="v1", title=f"{PREFIX}本地规范")
    pack = pack_for(local["series_id"], "v1", "与本地不同内容的同版本条款")
    second = pack_for(str(uuid4()), "v1", "另一系列的新条款", pack_version=f"{PREFIX}PACK-2")
    pack["documents"].append(second["documents"][0])
    pack["manifest"] = {"document_count": 2, "documents_sha256": manifest_hash(pack["documents"])}
    response = review_client.post("/api/v1/knowledge/pack/import", json=pack)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["imported"] == 1 and result["failed"] == 1
    assert result["failures"][0]["index"] == 1


@pytest.mark.parametrize("role", ["inspector", "reviewer"])
def test_pack_operations_are_admin_only(records, review_client, monkeypatch, role):
    with SessionLocal() as db:
        user = User(username=f"m6-{uuid4().hex}", role=role, password_hash="unused")
        db.add(user)
        db.commit()
        token = create_access_token(user)
    monkeypatch.setattr(routes.settings, "auth_mode", "jwt")
    review_client.headers["Authorization"] = f"Bearer {token}"
    try:
        assert review_client.get("/api/v1/knowledge/pack/export").status_code == 403
        assert review_client.get("/api/v1/knowledge/pack/status").status_code == 403
        assert review_client.post("/api/v1/knowledge/pack/import", json={
            "format": PACK_FORMAT, "pack_version": "x",
        }).status_code == 403
    finally:
        review_client.headers.pop("Authorization", None)
