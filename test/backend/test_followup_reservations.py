"""R3/T09: acceptance reserves one slot; each terminal path settles it once."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.api import routes
from app.core.db import SessionLocal
from app.main import app
from app.models import Assessment, AssessmentJob
from app.services import job_runner as jobs
from app.services.followup import finish_followup, recover_abandoned_sync_followups, release_followup, reserve_followup
from fastapi.testclient import TestClient
from sqlalchemy import select

ANSWER = "现场位于一楼楼道，堆放纸箱影响通行"


def make_running(job_id):
    token = str(uuid4())
    with SessionLocal() as db:
        job = db.get(AssessmentJob, job_id)
        job.status, job.attempt_token = "running", token
        job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=30)
        db.commit()
    return token


@pytest.fixture(params=["sync", "async"])
def mode(request, review_client, monkeypatch):
    monkeypatch.setattr(routes.settings, "workflow_mode", request.param)
    monkeypatch.setattr(routes.get_job_runner(), "wake", lambda: None)
    return request.param


def test_five_concurrent_followups_accept_only_one(mode, review_client, assessment_factory, monkeypatch):
    item_id = assessment_factory(status="needs_more_info")
    started, release = threading.Event(), threading.Event()

    def run(**kwargs):
        started.set()
        assert kwargs["followup_used"] == 1
        assert release.wait(5)
        return {"status": "needs_more_info"}

    monkeypatch.setattr(routes, "run_workflow", run)

    def post():
        return review_client.post(f"/api/v1/assessments/{item_id}/followup", json={"answer": ANSWER})

    with ThreadPoolExecutor(max_workers=5) as pool:
        first = pool.submit(post)
        try:
            if mode == "sync":
                assert started.wait(3)
            else:
                assert first.result(timeout=3).status_code == 202
            rest = list(pool.map(lambda _: post(), range(4)))
            assert [result.status_code for result in rest] == [409] * 4
            with SessionLocal() as db:
                item = db.get(Assessment, item_id)
                assert item.followup_used == 1 and item.followup_token
                assert item.status == "pending"
                queued = db.scalars(select(AssessmentJob).where(AssessmentJob.assessment_id == item_id)).all()
                assert len(queued) == (1 if mode == "async" else 0)
        finally:
            release.set()
        assert first.result(timeout=3).status_code == (202 if mode == "async" else 200)


def test_limit_is_reserved_at_acceptance_and_not_incremented_at_completion(
    mode, review_client, assessment_factory, monkeypatch,
):
    item_id = assessment_factory(status="needs_more_info", followup_used=1)
    monkeypatch.setattr(routes, "run_workflow", lambda **kwargs: {"status": "needs_more_info"})
    result = review_client.post(f"/api/v1/assessments/{item_id}/followup", json={"answer": ANSWER})
    assert result.status_code == (202 if mode == "async" else 200)
    if mode == "async":
        job_id = result.json()["id"]
        token = make_running(job_id)
        assert jobs._finish_job(job_id, token, state={"status": "needs_more_info"})
        assert not jobs._finish_job(job_id, token, state={"status": "needs_more_info"})
    with SessionLocal() as db:
        item = db.get(Assessment, item_id)
        assert item.followup_used == 2 and item.followup_token is None
    refused = review_client.post(f"/api/v1/assessments/{item_id}/followup", json={"answer": ANSWER})
    assert refused.status_code == 400 and "上限" in refused.text


def test_failure_releases_slot_retains_result_and_allows_explicit_new_attempt(
    mode, review_client, assessment_factory, monkeypatch,
):
    from app.services import langgraph_flow

    item_id = assessment_factory(status="needs_more_info")
    with SessionLocal() as db:
        original = db.get(Assessment, item_id)
        snapshot = (original.conclusion, original.report_json, original.human_review_json)

    def fail(**kwargs):
        raise RuntimeError("injected model failure")

    monkeypatch.setattr(routes, "run_workflow", fail)
    monkeypatch.setattr(langgraph_flow, "resume_workflow", fail)
    result = review_client.post(f"/api/v1/assessments/{item_id}/followup", json={"answer": ANSWER})
    if mode == "async":
        job_id = result.json()["id"]
        attempt = make_running(job_id)
        jobs.execute_job(job_id, attempt)
        assert not jobs._finish_job(job_id, attempt, error="late duplicate failure")
    else:
        assert result.status_code == 502
    with SessionLocal() as db:
        item = db.get(Assessment, item_id)
        assert item.followup_used == 0 and item.followup_token is None
        assert item.status == "needs_more_info"
        assert (item.conclusion, item.report_json, item.human_review_json) == snapshot
    monkeypatch.setattr(routes, "run_workflow", lambda **kwargs: {"status": "needs_more_info"})
    retried = review_client.post(f"/api/v1/assessments/{item_id}/followup", json={"answer": ANSWER})
    assert retried.status_code == (202 if mode == "async" else 200)
    if mode == "async":
        assert retried.json()["id"] != job_id
    with SessionLocal() as db:
        assert db.get(Assessment, item_id).followup_used == 1


def test_enqueue_failure_rolls_back_reservation(review_client, assessment_factory, monkeypatch):
    item_id = assessment_factory(status="needs_more_info")
    monkeypatch.setattr(routes.settings, "workflow_mode", "async")
    original = routes.enqueue_job

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected enqueue failure")

    monkeypatch.setattr(routes, "enqueue_job", fail)
    with pytest.raises(RuntimeError, match="injected"):
        review_client.post(f"/api/v1/assessments/{item_id}/followup", json={"answer": ANSWER})
    with SessionLocal() as db:
        item = db.get(Assessment, item_id)
        assert item.status == "needs_more_info" and item.followup_used == 0 and not item.followup_token
        assert db.scalars(select(AssessmentJob).where(AssessmentJob.assessment_id == item_id)).first() is None


def test_result_persistence_failure_also_releases_reservation(mode, review_client, assessment_factory, monkeypatch):
    from app.services import langgraph_flow

    item_id = assessment_factory(status="needs_more_info", conclusion="必须保留")
    broken_state = {"status": "completed", "evidence": [object()]}
    monkeypatch.setattr(routes, "run_workflow", lambda **kwargs: broken_state)
    monkeypatch.setattr(langgraph_flow, "resume_workflow", lambda **kwargs: broken_state)
    response = review_client.post(f"/api/v1/assessments/{item_id}/followup", json={"answer": ANSWER})
    if mode == "async":
        job_id = response.json()["id"]
        jobs.execute_job(job_id, make_running(job_id))
        with SessionLocal() as db:
            assert db.get(AssessmentJob, job_id).status == "failed"
    else:
        assert response.status_code == 502
    with SessionLocal() as db:
        item = db.get(Assessment, item_id)
        assert item.status == "needs_more_info" and item.followup_used == 0 and item.followup_token is None
        assert item.conclusion == "必须保留"


def test_expired_followup_releases_exactly_once_and_old_attempt_cannot_change_retry(
    review_client, assessment_factory, monkeypatch,
):
    item_id = assessment_factory(status="needs_more_info")
    monkeypatch.setattr(routes.settings, "workflow_mode", "async")
    response = review_client.post(f"/api/v1/assessments/{item_id}/followup", json={"answer": ANSWER})
    job_id = response.json()["id"]
    attempt = make_running(job_id)
    with SessionLocal() as db:
        reservation = db.get(Assessment, item_id).followup_token
        db.get(AssessmentJob, job_id).lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    assert jobs.recover_stale_jobs() >= 1
    assert jobs.recover_stale_jobs() == 0
    retry = review_client.post(f"/api/v1/assessments/{item_id}/followup", json={"answer": ANSWER})
    assert retry.status_code == 202
    assert not jobs._finish_job(job_id, attempt, state={"status": "completed"})
    with SessionLocal() as db:
        assert not release_followup(db, item_id, reservation)
        assert not finish_followup(db, item_id, reservation, {"status": "completed"})
        db.commit()
        item = db.get(Assessment, item_id)
        assert item.status == "pending" and item.followup_used == 1 and item.followup_token != reservation


def test_atomic_check_rejects_legacy_active_job_even_when_status_needs_info(review_client, assessment_factory):
    item_id = assessment_factory(status="needs_more_info")
    with SessionLocal() as db:
        jobs.enqueue_job(db, item_id, "followup", answer=ANSWER)
        db.commit()
    with SessionLocal() as db:
        with pytest.raises(routes.HTTPException) as exc:
            reserve_followup(db, item_id, 2)
        assert exc.value.status_code == 409


@pytest.mark.parametrize("active_status", ["queued", "running"])
def test_startup_recovery_keeps_async_followup_reservations(review_client, assessment_factory, active_status):
    item_id = assessment_factory(status="needs_more_info")
    with SessionLocal() as db:
        item, token = reserve_followup(db, item_id, 2)
        job = jobs.enqueue_job(db, item_id, "followup", answer=ANSWER, reservation_token=token)
        job.status = active_status
        db.commit()
    recover_abandoned_sync_followups()
    with SessionLocal() as db:
        item = db.get(Assessment, item_id)
        assert item.status == "pending" and item.followup_used == 1 and item.followup_token == token


def test_lifespan_restart_reclaims_abandoned_sync_slot_without_replaying_models(monkeypatch):
    with TestClient(app):
        with SessionLocal() as db:
            item = Assessment(description="楼道堆放纸箱", status="needs_more_info", conclusion="保留原结论",
                              human_review_json='{"history":["原记录"]}')
            db.add(item)
            db.commit()
            item_id = item.id
            _, old_token = reserve_followup(db, item_id, 2)
            db.commit()  # simulate crash after acceptance and before result persistence
    with TestClient(app) as client:
        with SessionLocal() as db:
            item = db.get(Assessment, item_id)
            assert item.status == "needs_more_info" and item.followup_used == 0 and item.followup_token is None
            assert item.conclusion == "保留原结论" and item.human_review_json == '{"history":["原记录"]}'
            assert not finish_followup(db, item_id, old_token, {"status": "completed"})
        monkeypatch.setattr(routes, "run_workflow", lambda **kwargs: {"status": "needs_more_info"})
        result = client.post(f"/api/v1/assessments/{item_id}/followup", json={"answer": ANSWER})
        assert result.status_code == 200 and result.json()["followup_used"] == 1
