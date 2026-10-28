"""R3/T08: request failures never persist a pending record without its job."""

from uuid import uuid4

import pytest
from app.api import routes
from app.core.db import SessionLocal
from app.models import Assessment, AssessmentImage, AssessmentJob, IdempotencyKey
from sqlalchemy import event, select


@pytest.fixture
def queued_client(review_client, monkeypatch):
    monkeypatch.setattr(routes.settings, "workflow_mode", "async")
    # Keep the accepted job queued: this test targets the request transaction.
    monkeypatch.setattr(routes.get_job_runner(), "wake", lambda: None)
    return review_client


@pytest.mark.parametrize("failure", ["enqueue", "commit", "file"])
def test_failure_rolls_back_assessment_key_job_and_uploads(queued_client, monkeypatch, failure):
    description, key = f"atomic-{uuid4().hex}", f"idem-{uuid4().hex}"
    upload_dir = routes.settings.upload_dir
    before = set(upload_dir.glob("**/*"))
    original_enqueue = routes.enqueue_job

    def fail_enqueue(*args, **kwargs):
        original_enqueue(*args, **kwargs)
        raise RuntimeError("injected enqueue failure")

    def fail_commit(session):
        if any(isinstance(obj, AssessmentJob) for obj in session.identity_map.values()):
            raise RuntimeError("injected commit failure")

    original_write = type(upload_dir).write_bytes

    def fail_write(path, data):
        original_write(path, data[:4])
        raise OSError("injected partial file write")

    if failure == "enqueue":
        monkeypatch.setattr(routes, "enqueue_job", fail_enqueue)
    elif failure == "commit":
        event.listen(SessionLocal.class_, "before_commit", fail_commit)
    else:
        monkeypatch.setattr(type(upload_dir), "write_bytes", fail_write)
    try:
        with pytest.raises((RuntimeError, OSError), match="injected"):
            queued_client.post("/api/v1/assessments", data={"description": description},
                               headers={"Idempotency-Key": key},
                               files={"files": ("scene.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 48, "image/png")})
    finally:
        if failure == "commit":
            event.remove(SessionLocal.class_, "before_commit", fail_commit)
    with SessionLocal() as db:
        assert db.scalars(select(Assessment).where(Assessment.description == description)).first() is None
        assert db.get(IdempotencyKey, key) is None
    assert set(upload_dir.glob("**/*")) == before


def test_acceptance_commits_everything_before_worker_wakeup(queued_client, monkeypatch):
    key = f"idem-{uuid4().hex}"
    observed = []

    def wake():
        with SessionLocal() as db:
            idem = db.get(IdempotencyKey, key)
            assert idem is not None
            item = db.get(Assessment, idem.assessment_id)
            job = db.scalars(select(AssessmentJob).where(AssessmentJob.assessment_id == item.id)).one()
            image = db.scalars(select(AssessmentImage).where(AssessmentImage.assessment_id == item.id)).one()
            assert item.status == "pending" and job.status == "queued"
            assert image.size_bytes == 56
            observed.append(job.id)

    monkeypatch.setattr(routes.get_job_runner(), "wake", wake)
    result = queued_client.post("/api/v1/assessments", data={"description": "楼道堆放纸箱"},
                                headers={"Idempotency-Key": key},
                                files={"files": ("scene.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 48, "image/png")})
    assert result.status_code == 202, result.text
    assert observed == [result.json()["id"]]
    replay = queued_client.post("/api/v1/assessments", headers={"Idempotency-Key": key})
    assert replay.status_code == 202
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json()["id"] == observed[0]
