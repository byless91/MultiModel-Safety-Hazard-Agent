"""R3/T07: controllable leases, restart recovery and fenced late writers."""

import asyncio
import importlib.util
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.core.db import Base
from app.models import Assessment, AssessmentJob
from app.services import job_runner as jobs
from app.services.worker_lock import WorkerLock
from sqlalchemy.orm import sessionmaker

NOW = datetime(2026, 10, 28, tzinfo=UTC)


@pytest.fixture
def job_db(tmp_path, monkeypatch):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'jobs.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(jobs, "SessionLocal", sessions)
    monkeypatch.setattr(jobs.get_settings(), "langgraph_checkpoint_path", tmp_path / "checkpoint.db")
    yield sessions
    engine.dispose()


def add_job(sessions, *, status="running", lease=None, confirmed=False):
    with sessions() as db:
        item = Assessment(description="原始描述", status="confirmed" if confirmed else "pending",
                          confirmed=confirmed, conclusion="原结论", human_review_json='{"history":["原复核"]}')
        db.add(item)
        db.flush()
        job = AssessmentJob(assessment_id=item.id, kind="create", status=status, worker_id="old",
                            attempt_token="old-attempt", lease_expires_at=lease, updated_at=NOW)
        db.add(job)
        db.commit()
        return item.id, job.id


def test_fast_restart_recovers_fresh_running_but_keeps_old_queue(job_db):
    item_id, running = add_job(job_db, lease=NOW + timedelta(seconds=30))
    _, queued = add_job(job_db, status="queued")
    with job_db() as db:
        db.get(AssessmentJob, queued).updated_at = NOW - timedelta(days=2)
        db.commit()
    assert jobs.recover_stale_jobs(now=NOW + timedelta(seconds=1), startup=True) == 1
    with job_db() as db:
        assert db.get(AssessmentJob, running).status == "failed"
        assert db.get(AssessmentJob, queued).status == "queued"
        item = db.get(Assessment, item_id)
        assert item.status == "failed"
        assert item.conclusion == "原结论"
        assert item.human_review_json == '{"history":["原复核"]}'


def test_expired_lease_and_legacy_running_recovered_without_restart(job_db):
    _, running = add_job(job_db, lease=NOW + timedelta(seconds=30))
    assert jobs.recover_stale_jobs(now=NOW + timedelta(seconds=29)) == 0
    assert jobs.recover_stale_jobs(now=NOW + timedelta(seconds=30)) == 1
    _, legacy = add_job(job_db)
    assert jobs.recover_stale_jobs(now=NOW + timedelta(minutes=11)) == 1
    with job_db() as db:
        assert db.get(AssessmentJob, legacy).status == "failed"


def test_healthy_long_task_renewal_does_not_need_node_progress(job_db):
    _, job_id = add_job(job_db, lease=NOW + timedelta(seconds=30))
    for offset in range(20, 1220, 20):
        now = NOW + timedelta(seconds=offset)
        assert jobs.renew_lease(job_id, "old-attempt", now=now)
        assert jobs.recover_stale_jobs(now=now) == 0
    assert not jobs.renew_lease(job_id, "wrong-attempt", now=now)
    assert jobs.recover_stale_jobs(now=now + timedelta(seconds=31)) == 1
    assert not jobs.renew_lease(job_id, "old-attempt", now=now + timedelta(seconds=32))


@pytest.mark.parametrize("new_attempt", [False, True])
@pytest.mark.parametrize("late_error", [None, "旧线程异常"])
def test_late_attempt_cannot_write_result_or_error(job_db, new_attempt, late_error):
    item_id, job_id = add_job(job_db, lease=datetime.now(UTC) + timedelta(seconds=30))
    jobs.recover_stale_jobs(startup=True)
    if new_attempt:
        with job_db() as db:
            job = db.get(AssessmentJob, job_id)
            job.status, job.attempt_token = "running", "new-attempt"
            db.get(Assessment, item_id).status = "pending"
            db.commit()
    assert not jobs._finish_job(job_id, "old-attempt", state={"status": "completed"}, error=late_error)
    with job_db() as db:
        assert db.get(Assessment, item_id).conclusion == "原结论"
        assert db.get(AssessmentJob, job_id).status == ("running" if new_attempt else "failed")


def test_recovery_preserves_confirmed_assessment(job_db):
    item_id, _ = add_job(job_db, lease=NOW, confirmed=True)
    assert jobs.recover_stale_jobs(now=NOW) == 1
    with job_db() as db:
        item = db.get(Assessment, item_id)
        assert item.status == "confirmed" and item.confirmed
        assert item.human_review_json == '{"history":["原复核"]}'


def test_real_executor_discards_result_after_recovery(job_db, monkeypatch):
    from app.services import workflow

    item_id, job_id = add_job(job_db, status="queued")
    job = jobs.claim_next_job("worker")

    def run(**kwargs):
        assert jobs.recover_stale_jobs(startup=True) == 1
        return {"status": "completed", "conclusion": "迟到结论"}

    monkeypatch.setattr(workflow, "run_workflow", run)
    jobs.execute_job(job_id, job.attempt_token)
    with job_db() as db:
        assert db.get(AssessmentJob, job_id).status == "failed"
        assert db.get(Assessment, item_id).conclusion == "原结论"


def test_monitor_recovers_during_runtime_and_runner_can_restart(job_db, monkeypatch):
    monkeypatch.setattr(jobs.get_settings(), "job_monitor_seconds", 0.02)

    async def exercise():
        runner = jobs.JobRunner()
        await runner.start()
        _, job_id = add_job(job_db, lease=datetime.now(UTC) - timedelta(seconds=1))
        for _ in range(100):
            await asyncio.sleep(0.02)
            with job_db() as db:
                if db.get(AssessmentJob, job_id).status == "failed":
                    break
        else:
            pytest.fail("periodic recovery did not run")
        await runner.stop()
        return runner

    runner = asyncio.run(exercise())

    async def restart():
        await runner.start()
        await asyncio.sleep(0.03)
        await runner.stop()

    asyncio.run(restart())


def test_single_worker_lock_releases_and_excludes_others(tmp_path):
    path = tmp_path / "worker.lock"
    lock = WorkerLock(path)
    with pytest.raises(RuntimeError, match="单实例"):
        WorkerLock(path)
    lock.release()
    WorkerLock(path).release()


def test_monitor_keeps_blocked_execution_alive(job_db, monkeypatch):
    from app.services import workflow

    monkeypatch.setattr(jobs.get_settings(), "job_monitor_seconds", 0.02)
    started, release = threading.Event(), threading.Event()

    def run(**kwargs):
        started.set()
        assert release.wait(3)
        return {"status": "needs_more_info"}

    monkeypatch.setattr(workflow, "run_workflow", run)
    _, job_id = add_job(job_db, status="queued")

    async def exercise():
        runner = jobs.JobRunner()
        await runner.start()
        try:
            assert await asyncio.to_thread(started.wait, 2)
            with job_db() as db:
                before = db.get(AssessmentJob, job_id).lease_expires_at
            await asyncio.sleep(0.08)
            with job_db() as db:
                job = db.get(AssessmentJob, job_id)
                assert job.status == "running"
                assert job.lease_expires_at > before
        finally:
            release.set()
            await runner.stop()

    asyncio.run(exercise())


def test_lease_migration_upgrades_existing_rows_and_is_reentrant(tmp_path, monkeypatch):
    path = (Path(__file__).resolve().parents[2] / "backend/migrations/versions"
            / "20261028_c21a7db8e401_job_execution_leases.py")
    spec = importlib.util.spec_from_file_location("lease_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE assessment_jobs (id VARCHAR(36) PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO assessment_jobs VALUES ('existing')")
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        migration.upgrade()
        assert connection.exec_driver_sql("SELECT id, attempt_token FROM assessment_jobs").one() == ("existing", None)
        assert {c["name"] for c in sa.inspect(connection).get_columns("assessment_jobs")} >= {
            "worker_id", "attempt_token", "lease_expires_at",
        }
    engine.dispose()
