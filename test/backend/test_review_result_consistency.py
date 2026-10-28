"""R1/T04: detail, listing, work order, export and original AI remain distinct."""

import json

from app.core.db import SessionLocal
from app.models import Assessment


def test_manual_category_level_and_conclusion_are_consistent_everywhere(review_client, assessment_factory):
    assessment_id = assessment_factory()
    edits = {"hazard_category": "电气线路隐患", "risk_level": 2, "conclusion": "人工复核：线路需整改"}
    response = review_client.post(f"/api/v1/assessments/{assessment_id}/confirm", json={"edits": edits})
    assert response.status_code == 200
    for result in (response.json(), review_client.get(f"/api/v1/assessments/{assessment_id}").json()):
        assert result["hazard_category"] == result["report"]["category"] == result["report"]["work_order"]["category"]
        assert result["risk_level"] == result["report"]["level"] == 2
        assert result["report"]["work_order"]["level"] == "2 级"
        assert result["report"]["work_order"]["deadline"] == "限期整改"
        assert result["conclusion"] == result["report"]["summary"] == edits["conclusion"]
        assert result["report"]["briefing"] == edits["conclusion"]
        assert result["risk_result"]["operational_level"] == 1
        assert result["human_review"]["ai_original"]["risk_level"] == 1
        assert result["report"]["result_source"] == "human_review"
        assert "原始 AI" in result["report"]["disclaimer"]
    rows = review_client.get("/api/v1/assessments", params={"status": "confirmed", "limit": 200}).json()
    listed = next(row for row in rows if row["id"] == assessment_id)
    assert listed["conclusion"] == edits["conclusion"]
    exported = review_client.get(f"/api/v1/assessments/{assessment_id}/export").json()["content"]
    assert edits["conclusion"] in exported
    assert "电气线路隐患隐患整改工单" in exported
    assert "风险等级：2 级" in exported


def test_level_only_edit_replaces_stale_summary_and_deadline(review_client, assessment_factory):
    assessment_id = assessment_factory()
    response = review_client.post(f"/api/v1/assessments/{assessment_id}/confirm", json={"edits": {"risk_level": 3}})
    assert response.status_code == 200
    result = response.json()
    assert "3 级" in result["conclusion"]
    assert result["report"]["summary"] == result["conclusion"]
    assert result["report"]["work_order"]["deadline"] == "列入计划整改"
    assert "1 级" in result["human_review"]["ai_original"]["conclusion"]


def test_legacy_confirmed_edits_render_consistently_without_database_rewrite(review_client, assessment_factory):
    legacy = {"resolution": {"confirmed": True, "reviewer": "旧复核人", "edits": {"risk_level": 2}}}
    assessment_id = assessment_factory("confirmed", risk_level=2, human_review_json=json.dumps(legacy))
    with SessionLocal() as db:
        before = db.get(Assessment, assessment_id).report_json
        old_audit = db.get(Assessment, assessment_id).human_review_json
    result = review_client.get(f"/api/v1/assessments/{assessment_id}").json()
    assert result["report"]["level"] == result["risk_level"] == 2
    assert "2 级" in result["report"]["summary"] == result["conclusion"]
    assert result["human_review"]["ai_original"]["available"] is False
    assert result["human_review"]["history"][0]["legacy"] is True
    exported = review_client.get(f"/api/v1/assessments/{assessment_id}/export").json()["content"]
    assert result["conclusion"] in exported
    with SessionLocal() as db:
        assert db.get(Assessment, assessment_id).report_json == before
        assert db.get(Assessment, assessment_id).human_review_json == old_audit


def test_rejection_remains_unconfirmed_in_report_and_api(review_client, assessment_factory):
    assessment_id = assessment_factory()
    result = review_client.post(f"/api/v1/assessments/{assessment_id}/confirm",
                                json={"confirmed": False, "note": "证据不足"}).json()
    assert result["confirmed"] is False
    assert result["status"] == "needs_review"
    assert result["report"]["review_confirmed"] is False
    assert "待确认" in result["report"]["work_order"]["source_note"]
