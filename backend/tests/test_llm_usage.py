"""B5/WP3.2：LLM 台账端到端验收——研判产生台账行、预算熔断、admin 聚合视图。"""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.main import app
from app.models import LLMCall, User
from app.services import llm_ledger
from app.services.providers.http import OpenAICompatibleProvider
from app.services.rag import get_rag
from app.services.workflow import run_functional


@pytest.fixture(autouse=True)
def _ensure_tables():
    """本文件直接调 run_functional/台账，不经过 TestClient 生命周期，先建表。"""
    from app.core.db import init_db

    init_db()
    yield


VALID_ANALYSIS = {
    "scene_summary": "楼道堆放纸箱",
    "hazard_hints": ["占用疏散通道"],
    "vision_confidence": 0.8,
    "hazards": [
        {
            "hazard_type": "占用疏散通道",
            "severity": 3,
            "confidence": 0.8,
            "observed_facts": ["楼道堆放纸箱"],
        }
    ],
}

import json as _json


def _mock_transport_provider(name: str) -> OpenAICompatibleProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": _json.dumps(VALID_ANALYSIS, ensure_ascii=False)}}
                ],
                "usage": {"prompt_tokens": 50, "completion_tokens": 20},
            },
        )

    return OpenAICompatibleProvider(
        base_url="http://fake",
        api_key="sk-test",
        vision_model="vision-model",
        text_model="text-model",
        embedding_model="embedding-model",
        name=name,
        family="test",
        timeout=1.0,
        max_retries=0,
        retry_backoff=0,
        transport=httpx.MockTransport(handler),
    )


def _rows(provider_name: str) -> list[LLMCall]:
    db = SessionLocal()
    try:
        return list(db.query(LLMCall).filter(LLMCall.provider == provider_name).all())
    finally:
        db.close()


def test_assessment_run_creates_ledger_rows_with_context():
    """完整研判管线：analyze + refine 两次调用均落台账，携带 assessment 与 purpose。"""
    provider = _mock_transport_provider("e2e-ledger-provider")
    ctx_token = llm_ledger.current_assessment_id.set("ledger-e2e-assessment")
    try:
        run_functional(
            "小区楼道堆放纸箱杂物，堵塞疏散通道",
            [],
            providers=[provider],
            rag=get_rag(),
        )
    finally:
        llm_ledger.current_assessment_id.reset(ctx_token)
    provider.close()

    rows = _rows("e2e-ledger-provider")
    purposes = {row.purpose for row in rows}
    assert "analyze" in purposes, "首轮分析必须落台账"
    assert "refine" in purposes, "证据二次研判（真实 provider）必须落台账"
    for row in rows:
        assert row.assessment_id == "ledger-e2e-assessment"
        assert row.tokens_in == 50 and row.tokens_out == 20
        assert row.status == "success"


def test_budget_exceeded_blocks_new_assessment(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "daily_token_budget", 10)
    # 预置今日已超预算的台账
    llm_ledger.record_call(
        provider="budget-seed",
        model="m",
        status="success",
        latency_ms=1.0,
        tokens_in=100,
        tokens_out=10,
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/assessments", data={"description": "楼道堆物堵塞疏散通道"}
        )
    assert response.status_code == 429
    assert "预算" in response.json()["detail"]


def test_admin_llm_usage_endpoint(monkeypatch):
    from app.core.security import hash_password

    settings = get_settings()
    monkeypatch.setattr(settings, "auth_mode", "jwt")
    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == "ledger-admin").first() is None:
            db.add(
                User(
                    username="ledger-admin",
                    password_hash=hash_password("password-123"),
                    role="admin",
                )
            )
            db.commit()
    finally:
        db.close()

    llm_ledger.record_call(
        provider="usage-view-provider",
        model="m",
        status="success",
        latency_ms=12.5,
        tokens_in=7,
        tokens_out=3,
    )
    with TestClient(app) as client:
        token = client.post(
            "/api/v1/auth/token",
            data={"username": "ledger-admin", "password": "password-123"},
        ).json()["access_token"]
        response = client.get(
            "/api/v1/admin/llm-usage",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    body = response.json()
    assert "tokens_used_today" in body and "items" in body
    assert any(item["provider"] == "usage-view-provider" for item in body["items"])
