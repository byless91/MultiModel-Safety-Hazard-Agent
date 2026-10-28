"""R1/T04: review history is append-only and stale writers cannot erase it."""

import json

import pytest
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import create_access_token
from app.models import Assessment, User
from app.schemas.assessment import ConfirmIn
from app.services.review import apply_human_review
from fastapi import HTTPException


def stored(assessment_id):
    with SessionLocal() as db:
        item = db.get(Assessment, assessment_id)
        return {column.name: getattr(item, column.name) for column in Assessment.__table__.columns}


def test_reject_then_approve_preserves_both_events_and_ai_snapshot(review_client, assessment_factory):
    assessment_id = assessment_factory()
    initial = stored(assessment_id)
    rejected = review_client.post(f"/api/v1/assessments/{assessment_id}/confirm", json={
        "confirmed": False, "reviewer": "复核甲", "note": "证据需补核", "edits": {"risk_level": 2},
    })
    assert rejected.status_code == 200
    first = rejected.json()["human_review"]
    assert rejected.json()["status"] == "needs_review"
    assert len(first["history"]) == 1
    assert first["history"][0]["before"]["risk_level"] == 1
    assert first["history"][0]["after"]["risk_level"] == 2
    assert first["ai_original"]["risk_level"] == 1
    assert first["ai_original"]["conclusion"] == initial["conclusion"]
    assert first["ai_original"]["report"] == json.loads(initial["report_json"])
    assert first["ai_original"]["risk_result"] == json.loads(initial["risk_result_json"])
    approved = review_client.post(f"/api/v1/assessments/{assessment_id}/confirm", json={
        "confirmed": True, "reviewer": "复核乙", "note": "复查完成", "edits": {"conclusion": "人工最终意见"},
    })
    assert approved.status_code == 200
    review = approved.json()["human_review"]
    assert len(review["history"]) == 2
    assert review["history"][0] == first["history"][0]
    assert review["history"][1]["before"]["risk_level"] == 2
    assert review["ai_original"] == first["ai_original"]
    assert review["resolution"]["reviewer"] == "复核乙"
    assert stored(assessment_id)["risk_result_json"] == initial["risk_result_json"]


@pytest.mark.parametrize("payload", [
    {"confirmed": False}, {"confirmed": False, "note": "  "},
    {"edits": {"confirmed": True}}, {"edits": {"conclusion": []}},
    {"edits": {"conclusion": " "}}, {"edits": {"hazard_category": None}},
    {"edits": {"hazard_category": "x" * 129}}, {"edits": {"conclusion": "x" * 2001}},
])
def test_invalid_review_does_not_mutate_or_create_audit(review_client, assessment_factory, payload):
    assessment_id = assessment_factory()
    before = stored(assessment_id)
    assert review_client.post(f"/api/v1/assessments/{assessment_id}/confirm", json=payload).status_code == 422
    assert stored(assessment_id) == before


def test_repeating_rejection_does_not_append_history(review_client, assessment_factory):
    assessment_id = assessment_factory()
    payload = {"confirmed": False, "note": "无法确认", "reviewer": "复核员"}
    assert review_client.post(f"/api/v1/assessments/{assessment_id}/confirm", json=payload).status_code == 200
    before = stored(assessment_id)
    assert review_client.post(f"/api/v1/assessments/{assessment_id}/confirm", json=payload).status_code == 200
    assert stored(assessment_id) == before


def test_authenticated_identity_overrides_client_name(review_client, assessment_factory, monkeypatch):
    assessment_id = assessment_factory()
    with SessionLocal() as db:
        user = User(username=f"reviewer-{assessment_id}", role="reviewer", password_hash="unused")
        db.add(user)
        db.commit()
        token = create_access_token(user)
        user_id, username = user.id, user.username
    monkeypatch.setattr(get_settings(), "auth_mode", "jwt")
    response = review_client.post(f"/api/v1/assessments/{assessment_id}/confirm",
                                 json={"reviewer": "伪造身份", "note": "已核实"},
                                 headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    event = response.json()["human_review"]["history"][0]
    assert event["reviewer"] == username
    assert event["reviewer_id"] == user_id
    assert event["identity_source"] == "authenticated"
    assert stored(assessment_id)["confirmed_by_id"] == user_id


def test_stale_concurrent_writer_cannot_overwrite_first_review(assessment_factory):
    assessment_id = assessment_factory()
    with SessionLocal() as first, SessionLocal() as stale:
        one, two = first.get(Assessment, assessment_id), stale.get(Assessment, assessment_id)
        apply_human_review(one, first, ConfirmIn(confirmed=False, note="第一意见"), "甲", None)
        with pytest.raises(HTTPException) as caught:
            apply_human_review(two, stale, ConfirmIn(confirmed=False, note="并发意见"), "乙", None)
        assert caught.value.status_code == 409
    review = json.loads(stored(assessment_id)["human_review_json"])
    assert len(review["history"]) == 1
    assert review["resolution"]["note"] == "第一意见"


def test_identical_concurrent_approval_is_read_only(assessment_factory):
    assessment_id = assessment_factory()
    payload = ConfirmIn(note="一致意见")
    with SessionLocal() as first, SessionLocal() as stale:
        one, two = first.get(Assessment, assessment_id), stale.get(Assessment, assessment_id)
        assert apply_human_review(one, first, payload, "甲", None) is True
        assert apply_human_review(two, stale, payload, "甲", None) is False
    assert len(json.loads(stored(assessment_id)["human_review_json"])["history"]) == 1


def test_legacy_resolution_is_preserved_without_inventing_ai_snapshot(review_client, assessment_factory):
    legacy = {"confirmed": False, "reviewer": "旧复核人", "note": "旧意见", "edits": {"risk_level": 2}}
    assessment_id = assessment_factory("needs_review", risk_level=2,
                                       human_review_json=json.dumps({"resolution": legacy}, ensure_ascii=False))
    response = review_client.post(f"/api/v1/assessments/{assessment_id}/confirm", json={"note": "本次已核实"})
    assert response.status_code == 200
    review = response.json()["human_review"]
    assert review["history"][0]["note"] == legacy["note"]
    assert review["history"][0]["legacy"] is True
    assert review["ai_original"]["available"] is False
    assert len(review["history"]) == 2


@pytest.mark.parametrize("raw", ['{"history": {}}', '[]', '{corrupt', '{"history": [1]}', '{"resolution": "bad"}'])
def test_corrupt_audit_is_never_silently_overwritten(review_client, assessment_factory, raw):
    assessment_id = assessment_factory(human_review_json=raw)
    before = stored(assessment_id)
    assert review_client.post(f"/api/v1/assessments/{assessment_id}/confirm", json={}).status_code == 409
    assert stored(assessment_id) == before
