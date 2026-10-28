"""R4/T11: recover lost responses, reject payload conflicts, never replay calls."""

import asyncio
import importlib.util
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.api import routes
from app.core.db import SessionLocal
from app.main import app
from app.models import Assessment, AssessmentJob, IdempotencyKey

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 48


@pytest.fixture
def submissions(review_client, monkeypatch):
    calls = []

    def run(**kwargs):
        calls.append(kwargs)
        return {"status": "completed", "evidence": []}

    monkeypatch.setattr(routes, "run_workflow", run)
    monkeypatch.setattr(routes.get_job_runner(), "wake", lambda: None)
    return review_client, calls


def post(client, key, *, description="楼道堆放纸箱", answer="", ocr="", files=None):
    return client.post("/api/v1/assessments", headers={"Idempotency-Key": key},
                       data={"description": description, "followup_answer": answer, "ocr_texts": ocr}, files=files)


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_lost_response_retry_has_one_record_and_one_initial_execution(submissions, monkeypatch, mode):
    client, calls = submissions
    monkeypatch.setattr(routes.settings, "workflow_mode", mode)
    key = f"recovery-{uuid4().hex}"
    first = post(client, key)  # Pretend this response never reached the client.
    assert first.status_code == (202 if mode == "async" else 201)
    lookup = client.get(f"/api/v1/assessment-submissions/{key}")
    retry = post(client, key)
    assert lookup.status_code == retry.status_code == (202 if mode == "async" else 200)
    assert lookup.json()["id"] == retry.json()["id"] == first.json()["id"]
    assert retry.headers["Idempotency-Replayed"] == "true"
    item_id = first.json()["assessment_id"] if mode == "async" else first.json()["id"]
    assert retry.headers["Assessment-Id"] == item_id
    assert retry.headers["Location"] == f"/api/v1/assessments/{item_id}"
    with SessionLocal() as db:
        assert db.get(IdempotencyKey, key).assessment_id == item_id
        jobs = db.scalars(sa.select(AssessmentJob).where(AssessmentJob.assessment_id == item_id)).all()
        assert len(jobs) == (1 if mode == "async" else 0)
    assert len(calls) == (0 if mode == "async" else 1)


@pytest.mark.parametrize("changed", ["description", "answer", "ocr", "image_bytes", "image_name", "image_order"])
def test_same_key_changed_payload_returns_conflict_without_calling_model(submissions, changed):
    client, calls = submissions
    key = f"conflict-{uuid4().hex}"
    first_files = [("files", ("first.png", PNG, "image/png")), ("files", ("second.png", PNG + b"x", "image/png"))]
    original = post(client, key, answer="一楼楼道", ocr='["出口"]', files=first_files)
    arguments = {"description": "楼道堆放纸箱", "answer": "一楼楼道", "ocr": '["出口"]', "files": first_files}
    if changed in {"description", "answer", "ocr"}:
        arguments[changed] = '["另一出口"]' if changed == "ocr" else "另一位置"
    elif changed == "image_order":
        arguments["files"] = list(reversed(first_files))
    else:
        arguments["files"] = [
            ("files", ("renamed.png" if changed == "image_name" else "first.png",
                       PNG + b"y" if changed == "image_bytes" else PNG, "image/png")), first_files[1],
        ]
    conflict = post(client, key, **arguments)
    assert conflict.status_code == 409, conflict.text
    assert conflict.headers["Assessment-Id"] == original.json()["id"]
    assert len(calls) == 1


def test_ocr_json_format_and_declared_mime_do_not_change_semantic_payload(submissions):
    client, calls = submissions
    key = f"canonical-{uuid4().hex}"
    first = post(client, key, ocr='["出口"]', files={"files": ("scene.png", PNG, "image/png")})
    replay = post(client, key, ocr='[ "出口" ]', files={"files": ("scene.png", PNG, "application/octet-stream")})
    assert replay.status_code == 200 and replay.json()["id"] == first.json()["id"]
    assert len(calls) == 1


def test_pending_sync_request_can_be_recovered_while_original_is_running(submissions, monkeypatch):
    client, _ = submissions
    started, release = threading.Event(), threading.Event()
    calls = []

    def run(**kwargs):
        calls.append(kwargs)
        started.set()
        assert release.wait(5)
        return {"status": "completed"}

    monkeypatch.setattr(routes, "run_workflow", run)
    key = f"pending-{uuid4().hex}"
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(post, client, key)
        try:
            assert started.wait(3)
            found = client.get(f"/api/v1/assessment-submissions/{key}")
            replay = post(client, key)
            assert found.status_code == replay.status_code == 200
            assert found.json()["status"] == replay.json()["status"] == "pending"
            assert found.json()["id"] == replay.json()["id"]
        finally:
            release.set()
        assert first.result(timeout=3).json()["id"] == found.json()["id"]
    assert len(calls) == 1


def test_sync_failure_exposes_record_and_retries_never_call_again_even_after_ttl(submissions, monkeypatch):
    client, calls = submissions

    def fail(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("offline ambiguous model failure")

    monkeypatch.setattr(routes, "run_workflow", fail)
    key = f"failed-{uuid4().hex}"
    failed = post(client, key)
    assert failed.status_code == 502
    item_id = failed.headers["Assessment-Id"]
    assert failed.headers["Location"] == f"/api/v1/assessments/{item_id}"
    with SessionLocal() as db:
        db.get(IdempotencyKey, key).created_at = datetime.now(UTC) - timedelta(days=2)
        db.commit()
    found = client.get(f"/api/v1/assessment-submissions/{key}")
    replay = post(client, key)
    assert found.json()["status"] == replay.json()["status"] == "failed"
    assert found.json()["id"] == replay.json()["id"] == item_id
    assert len(calls) == 1


def test_read_only_lookup_preserves_expired_terminal_mapping_and_budget_does_not_block_replay(submissions, monkeypatch):
    client, calls = submissions
    key = f"expired-{uuid4().hex}"
    first = post(client, key)
    with SessionLocal() as db:
        db.get(IdempotencyKey, key).created_at = datetime.now(UTC) - timedelta(days=2)
        db.commit()
    monkeypatch.setattr(routes, "_check_token_budget", lambda: (_ for _ in ()).throw(AssertionError("must not run")))
    found = client.get(f"/api/v1/assessment-submissions/{key}")
    assert found.status_code == 200 and found.json()["id"] == first.json()["id"]
    with SessionLocal() as db:
        assert db.get(IdempotencyKey, key).assessment_id == first.json()["id"]
    assert len(calls) == 1


def test_legacy_key_requires_read_only_recovery_instead_of_guessing_payload(submissions):
    client, calls = submissions
    key = f"legacy-{uuid4().hex}"
    first = post(client, key)
    with SessionLocal() as db:
        db.get(IdempotencyKey, key).request_hash = None
        db.commit()
    assert post(client, key).status_code == 409
    assert client.get(f"/api/v1/assessment-submissions/{key}").json()["id"] == first.json()["id"]
    assert len(calls) == 1


def test_create_replay_never_returns_a_later_followup_job(submissions, monkeypatch):
    client, _ = submissions
    monkeypatch.setattr(routes.settings, "workflow_mode", "async")
    key = f"initial-{uuid4().hex}"
    first = post(client, key).json()
    with SessionLocal() as db:
        db.get(AssessmentJob, first["id"]).status = "succeeded"
        db.get(Assessment, first["assessment_id"]).status = "needs_more_info"
        db.commit()
    followup = client.post(f"/api/v1/assessments/{first['assessment_id']}/followup", json={"answer": "一楼楼道"})
    assert followup.status_code == 202
    replay = post(client, key)
    assert replay.status_code == 200
    assert replay.json()["id"] == first["assessment_id"] and "progress_step" not in replay.json()


def test_replay_follows_original_job_contract_after_mode_change(submissions, monkeypatch):
    client, _ = submissions
    monkeypatch.setattr(routes.settings, "workflow_mode", "async")
    key = f"mode-{uuid4().hex}"
    first = post(client, key)
    monkeypatch.setattr(routes.settings, "workflow_mode", "sync")
    replay = post(client, key)
    assert replay.status_code == 202 and replay.json()["id"] == first.json()["id"]


@pytest.mark.parametrize("different", [False, True])
def test_concurrent_initial_submissions_commit_one_record_and_job(submissions, monkeypatch, different):
    _, calls = submissions
    monkeypatch.setattr(routes.settings, "workflow_mode", "async")
    barrier, local = threading.Barrier(2), threading.local()
    original_replay = routes._idempotent_replay

    def replay(*args, **kwargs):
        result = original_replay(*args, **kwargs)
        if result is None and not getattr(local, "passed", False):
            local.passed = True
            barrier.wait(timeout=4)
        return result

    monkeypatch.setattr(routes, "_idempotent_replay", replay)
    key = f"race-{uuid4().hex}"

    async def send(index):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            return await client.post("/api/v1/assessments", headers={"Idempotency-Key": key}, data={
                "description": f"race-{index}" if different else "同一楼道隐患",
            })

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda index: asyncio.run(send(index)), range(2)))
    assert sorted(response.status_code for response in results) == ([202, 409] if different else [202, 202])
    if not different:
        assert results[0].json()["id"] == results[1].json()["id"]
    with SessionLocal() as db:
        item_id = db.get(IdempotencyKey, key).assessment_id
        assert len(db.scalars(sa.select(AssessmentJob).where(AssessmentJob.assessment_id == item_id)).all()) == 1
    assert not calls


def test_lookup_missing_or_invalid_key_does_not_create_work(submissions):
    client, calls = submissions
    assert client.get("/api/v1/assessment-submissions/unknown-key-123").status_code == 404
    assert client.get("/api/v1/assessment-submissions/bad!key").status_code == 400
    assert not calls


def test_fingerprint_migration_preserves_old_mapping_and_can_reenter(tmp_path, monkeypatch):
    path = (Path(__file__).resolve().parents[2] / "backend/migrations/versions"
            / "20261028_f04b62a9c310_submission_fingerprints.py")
    spec = importlib.util.spec_from_file_location("fingerprint_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE idempotency_keys (key VARCHAR(128) PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO idempotency_keys VALUES ('legacy-key')")
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        migration.upgrade()
        row = connection.exec_driver_sql("SELECT key, request_hash FROM idempotency_keys").one()
        assert row == ("legacy-key", None)
    engine.dispose()
