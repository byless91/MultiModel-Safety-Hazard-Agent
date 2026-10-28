"""R1/T03: invalid operations cannot overwrite a final or in-flight result."""

import json

import pytest
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import create_access_token
from app.models import Assessment, AssessmentJob, User


def snapshot(assessment_id):
    with SessionLocal() as db:
        item = db.get(Assessment, assessment_id)
        return {column.name: getattr(item, column.name) for column in Assessment.__table__.columns}


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("status", [
    "pending", "completed", "awaiting_human_review", "needs_review", "confirmed", "failed",
])
def test_followup_rejects_non_waiting_states_unchanged(review_client, assessment_factory, monkeypatch, mode, status):
    assessment_id = assessment_factory(status)
    before = snapshot(assessment_id)
    monkeypatch.setattr(get_settings(), "workflow_mode", mode)
    response = review_client.post(f"/api/v1/assessments/{assessment_id}/followup", json={"answer": "现场已变化"})
    assert response.status_code == 409
    assert snapshot(assessment_id) == before


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("status", ["pending", "needs_more_info", "failed"])
def test_confirmation_rejects_unfinished_or_failed_states(review_client, assessment_factory, monkeypatch, mode, status):
    assessment_id = assessment_factory(status)
    before = snapshot(assessment_id)
    monkeypatch.setattr(get_settings(), "workflow_mode", mode)
    response = review_client.post(f"/api/v1/assessments/{assessment_id}/confirm", json={"confirmed": True})
    assert response.status_code == 409
    assert snapshot(assessment_id) == before


@pytest.mark.parametrize("job_status", ["queued", "running"])
@pytest.mark.parametrize("operation", ["followup", "confirm"])
def test_active_jobs_block_mutation(review_client, assessment_factory, job_status, operation):
    assessment_id = assessment_factory("needs_more_info" if operation == "followup" else "awaiting_human_review")
    with SessionLocal() as db:
        db.add(AssessmentJob(assessment_id=assessment_id, kind="create", status=job_status))
        db.commit()
    before = snapshot(assessment_id)
    payload = {"answer": "补充信息"} if operation == "followup" else {"confirmed": True}
    response = review_client.post(f"/api/v1/assessments/{assessment_id}/{operation}", json=payload)
    assert response.status_code == 409
    assert snapshot(assessment_id) == before


def test_identical_final_approval_is_a_read_only_replay(review_client, assessment_factory):
    assessment_id = assessment_factory()
    payload = {"confirmed": True, "reviewer": "复核员", "note": "已核实", "edits": {}}
    assert review_client.post(f"/api/v1/assessments/{assessment_id}/confirm", json=payload).status_code == 200
    before = snapshot(assessment_id)
    assert review_client.post(f"/api/v1/assessments/{assessment_id}/confirm", json=payload).status_code == 200
    assert snapshot(assessment_id) == before
    changed = review_client.post(f"/api/v1/assessments/{assessment_id}/confirm", json={**payload, "note": "改写原意见"})
    assert changed.status_code == 409
    assert snapshot(assessment_id) == before


def test_inconsistent_confirmed_marker_still_blocks_followup(review_client, assessment_factory):
    assessment_id = assessment_factory("needs_more_info", confirmed=True)
    before = snapshot(assessment_id)
    response = review_client.post(f"/api/v1/assessments/{assessment_id}/followup", json={"answer": "补充说明"})
    assert response.status_code == 409
    assert snapshot(assessment_id) == before


@pytest.mark.parametrize("level", ["abc", 9, 4, True, 1.5])
def test_invalid_risk_edits_are_validation_errors_even_before_completion(review_client, assessment_factory, level):
    assessment_id = assessment_factory("needs_more_info")
    before = snapshot(assessment_id)
    response = review_client.post(f"/api/v1/assessments/{assessment_id}/confirm",
                                 json={"confirmed": True, "edits": {"risk_level": level}})
    assert response.status_code == 422
    assert snapshot(assessment_id) == before


def test_waiting_assessment_can_still_follow_up(review_client, assessment_factory):
    assessment_id = assessment_factory("needs_more_info")
    response = review_client.post(f"/api/v1/assessments/{assessment_id}/followup", json={"answer": "纸箱阻挡通道"})
    assert response.status_code == 200
    assert response.json()["followup_used"] == 1
    assert response.json()["status"] in {"completed", "awaiting_human_review"}


def test_inspector_cannot_rewrite_or_approve_confirmed_result(review_client, assessment_factory, monkeypatch):
    assessment_id = assessment_factory("confirmed", human_review_json=json.dumps({"resolution": {"note": "原意见"}}))
    with SessionLocal() as db:
        user = User(username=f"inspector-{assessment_id}", role="inspector", password_hash="unused")
        db.add(user)
        db.commit()
        token = create_access_token(user)
    monkeypatch.setattr(get_settings(), "auth_mode", "jwt")
    headers = {"Authorization": f"Bearer {token}"}
    before = snapshot(assessment_id)
    assert review_client.post(f"/api/v1/assessments/{assessment_id}/followup", json={"answer": "重写"},
                              headers=headers).status_code == 409
    assert review_client.post(f"/api/v1/assessments/{assessment_id}/confirm", json={"confirmed": True},
                              headers=headers).status_code == 403
    assert snapshot(assessment_id) == before
