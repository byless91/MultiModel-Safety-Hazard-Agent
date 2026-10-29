"""M1: images, failure, human values, roles, idempotency and task persistence."""

import base64
import hashlib
import json
from uuid import uuid4

import httpx
import pytest
from app.api import routes
from app.core.db import SessionLocal
from app.core.security import create_access_token
from app.models import Assessment, AssessmentJob, KnowledgeDocument, LLMCall, User
from app.prompts import CLASSIFICATION_PROMPT_VERSION, PROMPT_VERSION
from app.services import classification, job_runner
from app.services.providers import ImageInput, QwenProvider, ZhipuProvider
from sqlalchemy import select

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jfZkAAAAASUVORK5CYII=")


class Classifier:
    name, vision_model = "fixture", "vision-test"

    def __init__(self):
        self.calls = []
        self.result = {"category": "占用疏散通道", "tags": ["通道受阻"], "risk_level": 1}

    def classify(self, images, text, **kwargs):
        self.calls.append((images, text, kwargs))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class Retrieval:
    def __init__(self, record=None):
        self.record = record

    def search(self, *args, **kwargs):
        if self.record:
            return [self.record]
        return [
            {"id": "article-1", "document": "测试规范", "article": "第1条", "version": "test-1",
             "source": "https://example.test/law", "text": "测试条款"},
            {"id": "demo-1", "document": "演示规范", "article": "第2条", "is_demo": True},
        ]


@pytest.fixture
def client(review_client, monkeypatch):
    provider = Classifier()
    identity = str(uuid4())
    digest = hashlib.sha256("测试条款".encode()).hexdigest()
    with SessionLocal() as db:
        db.add(KnowledgeDocument(id=identity, title="测试规范", version="test-1", content_text="测试条款",
                                 source="https://example.test/law", content_sha256=digest, industry="fire",
                                 applicability="仅测试", series_id=identity, review_status="approved"))
        db.commit()
    record = {"id": f"doc-{identity}-chunk-0", "document_id": identity, "content_sha256": digest,
              "review_status": "approved", "text": "测试条款", "version": "test-1"}
    monkeypatch.setattr(routes.settings, "workflow_mode", "sync")
    monkeypatch.setattr(classification, "get_provider", lambda: provider)
    monkeypatch.setattr(classification, "get_rag", lambda: Retrieval(record))
    yield review_client, provider
    with SessionLocal() as db:
        db.delete(db.get(KnowledgeDocument, identity))
        db.commit()


def create(client, mode="classification", key=None):
    response = client.post("/api/v1/assessments", data={"description": "楼道堆满纸箱影响通行", "mode": mode},
                           files=[("files", ("scene.png", PNG, "image/png"))],
                           headers={"Idempotency-Key": key or f"m1-{uuid4().hex}"})
    assert response.status_code in (200, 201, 202), response.text
    return response.json()


def save(client, item, **changes):
    return client.post(f"/api/v1/assessments/{item['id']}/classification", json={
        "category": "电气线路隐患", "tags": ["线路裸露"], "risk_level": None,
        "revision": item["classification"]["revision"], **changes,
    })


def test_suggestions_do_not_become_final_values_and_images_reach_provider(client):
    http, provider = client
    item = create(http)
    assert item["classification"]["suggested_category"] == "占用疏散通道"
    assert item["hazard_category"] is item["risk_level"] is item["risk_result"] is item["report"] is None
    assert item["classification"]["final_tags"] == [] and not item["confirmed"]
    assert len(item["evidence"]) == 1 and item["evidence"][0]["version"] == "test-1"
    assert provider.calls[0][0][0].path.read_bytes() == PNG
    assert http.post(f"/api/v1/assessments/{item['id']}/confirm", json={}).status_code == 409
    response = save(http, item)
    assert response.status_code == 200
    saved = response.json()
    assert saved["classification"]["suggested_category"] == "占用疏散通道"
    assert saved["hazard_category"] == "电气线路隐患" and saved["risk_level"] is None
    assert not saved["confirmed"]
    response = http.post(f"/api/v1/assessments/{item['id']}/confirm", json={"note": "现场核实"})
    assert response.status_code == 200
    final = response.json()
    assert final["confirmed"] and final["risk_level"] is final["report"] is None
    assert len(final["human_review"]["history"]) == 2
    assert final["human_review"]["ai_original"]["classification"]["suggested_category"] == "占用疏散通道"
    assert save(http, final).status_code == 409
    detail = http.get(f"/api/v1/assessments/{item['id']}").json()
    assert detail["classification"] == final["classification"]
    rows = http.get("/api/v1/assessments", params={"limit": 200}).json()
    listed = next(row for row in rows if row["id"] == item["id"])
    assert listed["classification"] == final["classification"] and listed["risk_level"] is None
    content = http.get(f"/api/v1/assessments/{item['id']}/export").json()["content"]
    assert "未分级" in content and "AI 建议类别：占用疏散通道" in content and "人工类别：电气线路隐患" in content
    assert "隐患整改工单" not in content


@pytest.mark.parametrize("raw,expected", [
    ({"category": "不存在的类别", "tags": ["任意标签"]}, "unknown"),
    ({"parse_failed": True}, "failed"), (RuntimeError("sensitive provider detail"), "failed"),
])
def test_unknown_and_failure_remain_visible_and_allow_manual_entry(client, raw, expected):
    http, provider = client
    provider.result = raw
    item = create(http)
    assert item["classification"]["suggestion_status"] == expected
    assert item["classification"]["warnings"] and item["risk_level"] is None
    assert "sensitive provider detail" not in json.dumps(item)
    assert save(http, item, category="其他隐患").status_code == 200


def test_manual_mode_makes_no_model_or_retrieval_calls(client, monkeypatch):
    http, provider = client
    monkeypatch.setattr(classification, "get_rag", lambda: pytest.fail("manual retrieval must not call embeddings"))
    item = create(http, mode="manual")
    assert item["classification"]["suggestion_status"] == "manual" and not provider.calls
    saved = save(http, item, risk_level=2).json()
    assert saved["risk_level"] == 2
    cleared = save(http, saved).json()
    assert cleared["risk_level"] is None


def test_same_submission_replays_and_changed_mode_conflicts(client):
    http, provider = client
    key = f"m1-idem-{uuid4().hex}"
    item = create(http, key=key)
    assert create(http, key=key)["id"] == item["id"] and len(provider.calls) == 1
    response = http.post("/api/v1/assessments", data={"description": "楼道堆满纸箱影响通行", "mode": "manual"},
                         files=[("files", ("scene.png", PNG, "image/png"))], headers={"Idempotency-Key": key})
    assert response.status_code == 409 and len(provider.calls) == 1


def test_stale_entry_cannot_overwrite_manual_values(client):
    http, _ = client
    item = create(http)
    assert save(http, item).status_code == 200
    assert save(http, item, category="其他隐患").status_code == 409


def test_reject_then_reenter_and_approve_preserves_classification_audit(client):
    http, _ = client
    item = save(http, create(http)).json()
    rejected = http.post(f"/api/v1/assessments/{item['id']}/confirm",
                         json={"confirmed": False, "note": "请现场核实"}).json()
    assert rejected["status"] == "needs_review" and rejected["report"] is None
    revised = save(http, rejected, category="消防器材失效", tags=["设施损坏"], risk_level=2).json()
    assert revised["status"] == "awaiting_human_review"
    final = http.post(f"/api/v1/assessments/{item['id']}/confirm", json={}).json()
    assert final["confirmed"] and final["risk_level"] == 2 and final["report"] is None
    assert len(final["human_review"]["history"]) == 4
    assert final["human_review"]["history"][-1]["after"]["tags"] == ["设施损坏"]
    replay = http.post(f"/api/v1/assessments/{item['id']}/confirm", json={}).json()
    assert replay["human_review"] == final["human_review"]


def test_rejection_before_human_entry_keeps_the_original_classification_snapshot(client):
    http, _ = client
    item = create(http)
    rejected = http.post(f"/api/v1/assessments/{item['id']}/confirm",
                         json={"confirmed": False, "note": "先退回核实"}).json()
    original = rejected["human_review"]["ai_original"]
    assert original["classification"] == item["classification"]
    saved = save(http, rejected).json()
    assert saved["human_review"]["ai_original"] == original


def test_inspector_can_enter_but_cannot_approve(client, monkeypatch):
    http, _ = client
    item = create(http)
    with SessionLocal() as db:
        user = User(username=f"m1-inspector-{uuid4().hex}", role="inspector", password_hash="unused")
        db.add(user)
        db.commit()
        token, username = create_access_token(user), user.username
    monkeypatch.setattr(routes.settings, "auth_mode", "jwt")
    http.headers["Authorization"] = f"Bearer {token}"
    try:
        response = save(http, item)
        assert response.status_code == 200
        assert response.json()["human_review"]["history"][0]["reviewer"] == username
        assert http.post(f"/api/v1/assessments/{item['id']}/confirm", json={}).status_code == 403
    finally:
        http.headers.pop("Authorization", None)


def test_async_payload_and_worker_keep_classification_mode(client, monkeypatch):
    http, provider = client
    monkeypatch.setattr(routes.settings, "workflow_mode", "async")
    monkeypatch.setattr(routes.get_job_runner(), "wake", lambda: None)
    job = create(http)
    with SessionLocal() as db:
        row = db.get(AssessmentJob, job["id"])
        assert json.loads(row.payload_json)["entry_mode"] == "classification"
    claimed = job_runner.claim_next_job("m1-worker")
    assert claimed is not None and claimed.id == job["id"]
    job_runner.execute_job(claimed.id, claimed.attempt_token)
    detail = http.get(f"/api/v1/assessments/{job['assessment_id']}").json()
    assert detail["status"] == "awaiting_human_review" and detail["risk_level"] is None
    assert detail["classification"]["suggested_category"] == "占用疏散通道" and len(provider.calls) == 1
    with SessionLocal() as db:
        assert db.get(AssessmentJob, job["id"]).status == "succeeded"
        assert db.get(Assessment, detail["id"]).record_mode == "classification"


@pytest.mark.parametrize("provider_type", [QwenProvider, ZhipuProvider])
def test_real_provider_request_contains_actual_image_bytes(review_client, tmp_path, provider_type):
    image = tmp_path / "actual.png"
    image.write_bytes(PNG)
    sent = []

    def transport(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"category":null,"tags":[]}'}}]})

    provider = provider_type(api_key="test-not-real", max_retries=0)
    provider._client.close()
    provider._client = httpx.Client(transport=httpx.MockTransport(transport), base_url="https://example.test")
    try:
        provider.classify([ImageInput("actual.png", image, "image/png")], "查看现场图片")
    finally:
        provider.close()
    content = sent[0]["messages"][1]["content"]
    assert base64.b64decode(content[1]["image_url"]["url"].split(",")[1]) == PNG
    prompt = sent[0]["messages"][0]["content"]
    assert "禁止输出风险等级" in prompt and "severity" not in prompt


@pytest.mark.parametrize("http_status", [200, 503])
def test_classification_prompt_version_and_purpose_are_audited_without_changing_legacy(review_client, http_status):
    model = f"m1-audit-{uuid4().hex}"
    provider = QwenProvider(api_key="test-not-real", max_retries=0, vision_model=model)
    provider._client.close()
    provider._client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
        http_status, json={"choices": [{"message": {"content": '{"category":null,"tags":[]}'}}]},
    )), base_url="https://example.test")
    try:
        result = classification.run_classification("现场情况", [], provider=provider, rag=Retrieval())
    finally:
        provider.close()
    assert result["classification"]["suggestion_status"] == ("unknown" if http_status == 200 else "failed")
    with SessionLocal() as db:
        call = db.scalar(select(LLMCall).where(LLMCall.model == model))
        assert call.prompt_version == CLASSIFICATION_PROMPT_VERSION == "classification-m1-v1"
        assert call.purpose == "classification" and call.status == ("success" if http_status == 200 else "failed")
    assert PROMPT_VERSION == "vision-v2"  # Existing vision prompt and baseline were not changed.
