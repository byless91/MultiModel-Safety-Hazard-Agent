"""R3/T08: concurrent conditional claims on SQLite and optional real PostgreSQL."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from app.core.db import Base
from app.models import Assessment, AssessmentJob
from app.services import job_runner as jobs
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from _support.environment import validate_database_url


@pytest.fixture(params=["sqlite", "postgres"])
def claim_db(request, tmp_path, monkeypatch):
    admin = None
    if request.param == "postgres":
        url = os.environ.get("R3_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("set R3_TEST_POSTGRES_URL to a local PostgreSQL test database")
        validate_database_url(url)
        schema = f"r3_{uuid4().hex}"
        admin = create_engine(url)
        with admin.begin() as db:
            db.execute(CreateSchema(schema))
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'claims.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(jobs, "SessionLocal", sessions)
    yield sessions
    engine.dispose()
    if admin is not None:
        with admin.begin() as db:
            db.execute(DropSchema(schema, cascade=True))
        admin.dispose()


def queue(sessions, count):
    with sessions() as db:
        item = Assessment(description="认领竞争")
        db.add(item)
        db.flush()
        ids = [jobs.enqueue_job(db, item.id, "create").id for _ in range(count)]
        db.commit()
        return ids


def test_two_claimants_only_one_gets_the_same_job(claim_db):
    for _ in range(10):
        expected = queue(claim_db, 1)
        barrier = threading.Barrier(2)

        def claim(index, barrier=barrier):
            barrier.wait(timeout=5)
            return jobs.claim_next_job(f"worker-{index}")

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, range(2)))
        winners = [result for result in results if result is not None]
        assert [job.id for job in winners] == expected
        assert winners[0].attempt_token and winners[0].lease_expires_at
        assert jobs.claim_next_job() is None


def test_contended_queue_has_unique_owners_and_attempts(claim_db):
    expected = set(queue(claim_db, 20))

    def drain(index):
        claimed = []
        # Losing a PG statement-level race is allowed; the next poll retries.
        for _ in range(25):
            job = jobs.claim_next_job(f"worker-{index}")
            if job:
                claimed.append(job)
        return claimed

    with ThreadPoolExecutor(max_workers=4) as pool:
        claimed = [job for batch in pool.map(drain, range(4)) for job in batch]
    assert len(claimed) == len(expected)
    assert {job.id for job in claimed} == expected
    assert len({job.attempt_token for job in claimed}) == len(expected)
    with claim_db() as db:
        assert all(job.status == "running" for job in db.scalars(select(AssessmentJob)))
