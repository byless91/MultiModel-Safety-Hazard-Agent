"""M5: authoritative-source checks, no repeated reminders and no automatic publication."""

from uuid import uuid4

import pytest
from app.api import routes
from app.core.db import SessionLocal
from app.core.security import create_access_token
from app.models import KnowledgeDocument, KnowledgeSource, User
from app.services import knowledge_sources
from sqlalchemy import delete, select

URL = "https://example.test/official-law"


@pytest.fixture
def sources():
    ids: list[str] = []
    yield ids
    with SessionLocal() as db:
        if ids:
            db.execute(delete(KnowledgeSource).where(KnowledgeSource.id.in_(ids)))
        db.execute(delete(KnowledgeSource).where(KnowledgeSource.url.like("https://m5-test%")))
        db.commit()


def create(client, sources, url=URL, name="M5 权威来源"):
    response = client.post("/api/v1/knowledge/sources", json={"name": name, "url": url, "industry": "fire"})
    assert response.status_code == 201, response.text
    item = response.json()
    sources.append(item["id"])
    return item


def check(client, item):
    response = client.post(f"/api/v1/knowledge/sources/{item['id']}/check")
    assert response.status_code == 200, response.text
    return response.json()


def test_first_check_is_a_baseline_and_unchanged_checks_do_not_repeat(sources, review_client, monkeypatch):
    monkeypatch.setattr(knowledge_sources, "fetch_content", lambda url: b"law-v1")
    item = create(review_client, sources)
    assert item["pending"] is False and item["last_checked_at"] is None
    first = check(review_client, item)
    assert first["last_status"] == "ok" and first["pending"] is False
    second = check(review_client, item)
    assert second["last_status"] == "ok" and second["pending"] is False
    assert second["last_checked_at"] is not None


def test_changed_source_remains_pending_until_acknowledged_without_publishing(sources, review_client, monkeypatch):
    content = {"body": b"law-v1"}
    monkeypatch.setattr(knowledge_sources, "fetch_content", lambda url: content["body"])
    item = create(review_client, sources)
    check(review_client, item)
    with SessionLocal() as db:
        documents_before = len(db.scalars(select(KnowledgeDocument)).all())
    content["body"] = b"law-v2"
    changed = check(review_client, item)
    assert changed["last_status"] == "changed" and changed["pending"] is True
    assert changed["change_detected_at"] is not None
    again = check(review_client, item)
    assert again["last_status"] == "changed" and again["pending"] is True
    with SessionLocal() as db:
        assert len(db.scalars(select(KnowledgeDocument)).all()) == documents_before

    acknowledged = review_client.post(f"/api/v1/knowledge/sources/{item['id']}/ack")
    assert acknowledged.status_code == 200
    assert acknowledged.json()["pending"] is False and acknowledged.json()["acknowledged_at"] is not None
    assert acknowledged.json()["last_status"] == "ok"
    assert check(review_client, item)["pending"] is False


def test_unreachable_source_is_reported_and_recovers(sources, review_client, monkeypatch):
    def offline(url):
        raise knowledge_sources.SourceError("来源不可达：ConnectError")

    monkeypatch.setattr(knowledge_sources, "fetch_content", offline)
    item = create(review_client, sources)
    failed = check(review_client, item)
    assert failed["last_status"] == "unreachable" and failed["pending"] is False
    assert "不可达" in failed["last_error"]
    monkeypatch.setattr(knowledge_sources, "fetch_content", lambda url: b"law-v1")
    recovered = check(review_client, item)
    assert recovered["last_status"] == "ok" and recovered["last_error"] is None


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "ftp://example.test/law", "https://user:pass@example.test/law", "not-a-url",
])
def test_source_requires_http_url_without_credentials(sources, review_client, url):
    response = review_client.post("/api/v1/knowledge/sources", json={"name": "来源", "url": url})
    assert response.status_code == 422


def test_sources_can_be_deleted_and_are_admin_only(sources, review_client, monkeypatch):
    monkeypatch.setattr(knowledge_sources, "fetch_content", lambda url: b"law-v1")
    item = create(review_client, sources)
    assert review_client.delete(f"/api/v1/knowledge/sources/{item['id']}").status_code == 204
    assert review_client.post(f"/api/v1/knowledge/sources/{item['id']}/check").status_code == 404

    with SessionLocal() as db:
        user = User(username=f"m5-{uuid4().hex}", role="reviewer", password_hash="unused")
        db.add(user)
        db.commit()
        token = create_access_token(user)
    monkeypatch.setattr(routes.settings, "auth_mode", "jwt")
    review_client.headers["Authorization"] = f"Bearer {token}"
    try:
        assert review_client.get("/api/v1/knowledge/sources").status_code == 403
        assert review_client.post("/api/v1/knowledge/sources", json={
            "name": "越权来源", "url": URL,
        }).status_code == 403
    finally:
        review_client.headers.pop("Authorization", None)
