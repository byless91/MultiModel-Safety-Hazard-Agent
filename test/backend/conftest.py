"""Reusable API inputs for review regression tests, isolated by the root plugin."""

import json

import pytest
from app.core.db import SessionLocal
from app.main import app
from app.models import Assessment
from app.services.report import build_report
from fastapi.testclient import TestClient


@pytest.fixture
def review_client():
    with TestClient(app) as client:
        yield client


@pytest.fixture
def assessment_factory(review_client):
    def create(status="awaiting_human_review", **overrides):
        state = {"hazard_category": "占用疏散通道", "risk_level": 1, "confidence": 0.7, "evidence": []}
        report = build_report(state)
        attributes = {
            "description": "楼道堆放纸箱", "status": status,
            "hazard_category": state["hazard_category"], "risk_level": state["risk_level"],
            "confidence": 0.7, "conclusion": report["summary"],
            "report_json": json.dumps(report, ensure_ascii=False),
            "human_review_json": json.dumps({"need_human_review": True, "review_reasons": ["测试待复核"]}),
            "risk_result_json": json.dumps({"risk_score": 90, "risk_level": "high", "operational_level": 1}),
            "confirmed": status == "confirmed", "confirmed_by_name": "原复核员" if status == "confirmed" else None,
        }
        attributes.update(overrides)
        with SessionLocal() as db:
            item = Assessment(**attributes)
            db.add(item)
            db.commit()
            return item.id
    return create
