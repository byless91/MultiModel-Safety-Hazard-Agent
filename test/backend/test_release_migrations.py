"""R8/T21: release migration paths preserve records on SQLite and real PG."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from app.core import db as database
from sqlalchemy.schema import CreateSchema, DropSchema

from _support.environment import validate_database_url

BACKEND = Path(__file__).resolve().parents[2] / "backend"
HEAD = "f6a2c91d4e70"
PRE_R3 = "7122c95a212f"
M3_PARENT = "b27e619ac430"
M5_PARENT = "d5e2f7a91c04"
M6_PARENT = "e91c4f7a2d68"
AUDIT = json.dumps({"history": [{"decision": "edit", "reviewer": "release-reviewer"}]})
REPORT = json.dumps({"summary": "人工最终结论", "risk_level": 1}, ensure_ascii=False)


@pytest.fixture(params=["sqlite", "postgres"])
def release_database(request, tmp_path):
    admin = None
    schema = None
    if request.param == "postgres":
        raw = os.environ.get("R8_TEST_POSTGRES_URL")
        if not raw:
            pytest.skip("set R8_TEST_POSTGRES_URL to a dedicated local PG test database")
        validate_database_url(raw)
        admin = sa.create_engine(raw)
        schema = f"r8_migration_{uuid4().hex}"
        with admin.begin() as connection:
            connection.execute(CreateSchema(schema))
        url = sa.engine.make_url(raw).update_query_dict({"options": f"-csearch_path={schema}"})
    else:
        url = sa.engine.make_url(f"sqlite:///{(tmp_path / 'release.db').as_posix()}")
    engine = sa.create_engine(url)
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%"))
    try:
        yield engine, config
    finally:
        engine.dispose()
        if admin is not None:
            with admin.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
            admin.dispose()


def insert_legacy_records(engine):
    metadata = sa.MetaData()
    metadata.reflect(engine)
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(metadata.tables["assessments"].insert().values(
            id="release-assessment", description="保留存量人工确认记录", status="confirmed",
            followup_used=1, confirmed=True, conclusion="人工最终结论", risk_level=1,
            human_review_json=AUDIT, report_json=REPORT, created_at=now, updated_at=now,
        ))
        connection.execute(metadata.tables["assessment_jobs"].insert().values(
            id="release-job", assessment_id="release-assessment", kind="create", status="succeeded",
            progress_step="done", created_at=now, updated_at=now,
        ))
        connection.execute(metadata.tables["idempotency_keys"].insert().values(
            key="release-key", assessment_id="release-assessment", created_at=now,
        ))


def assert_head(engine, *, retained=False):
    inspector = sa.inspect(engine)
    actual = {name: {column["name"] for column in inspector.get_columns(name)}
              for name in inspector.get_table_names() if name != "alembic_version"}
    expected = {name: set(table.columns.keys()) for name, table in database.Base.metadata.tables.items()}
    assert actual == expected
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == HEAD
        if retained:
            query = sa.text("SELECT * FROM assessments WHERE id='release-assessment'")
            row = connection.execute(query).mappings().one()
            assert row["status"] == "confirmed" and row["confirmed"]
            assert row["conclusion"] == "人工最终结论" and row["risk_level"] == 1
            assert row["human_review_json"] == AUDIT and row["report_json"] == REPORT
            assert row["followup_used"] == 1 and row["followup_token"] is None
            assert row["record_mode"] == "assessment" and row["classification_json"] is None
            job = connection.execute(sa.text("SELECT * FROM assessment_jobs WHERE id='release-job'")).mappings().one()
            assert job["status"] == "succeeded" and job["attempt_token"] is None
            key = connection.execute(sa.text("SELECT * FROM idempotency_keys WHERE key='release-key'")).mappings().one()
            assert key["assessment_id"] == "release-assessment" and key["request_hash"] is None


def test_empty_database_upgrades_to_release_head(release_database):
    engine, config = release_database
    command.upgrade(config, "head")
    assert_head(engine)


def test_m1_upgrade_preserves_r8_records_and_is_repeatable(release_database):
    engine, config = release_database
    command.upgrade(config, "f04b62a9c310")
    insert_legacy_records(engine)
    command.upgrade(config, "head")
    assert_head(engine, retained=True)
    command.upgrade(config, "head")
    assert_head(engine, retained=True)


def test_m2_upgrade_preserves_legacy_knowledge_without_approving_it(release_database):
    engine, config = release_database
    command.upgrade(config, "a12f083bcd71")
    with engine.begin() as connection:
        connection.execute(sa.text(
            "INSERT INTO knowledge_documents (id,title,source,version,status,content_text,meta_json,created_at) "
            "VALUES (:id,:title,:source,:version,:status,:body,:meta,:created)"
        ), {"id": "old-law", "title": "原文档", "source": "原来源", "version": "旧版本",
            "status": "indexed", "body": "旧条款原文", "meta": '{"owner":"operator"}', "created": datetime.now(UTC)})
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    with engine.connect() as connection:
        row = connection.execute(sa.text("SELECT * FROM knowledge_documents WHERE id='old-law'")).mappings().one()
        assert row["content_text"] == "旧条款原文" and row["version"] == "旧版本"
        assert row["source"] == "原来源" and row["meta_json"] == '{"owner":"operator"}'
        assert row["review_status"] == "unreviewed" and row["industry"] == "general"
        assert row["content_sha256"] is None and row["series_id"] is None
    assert_head(engine)
    command.upgrade(config, "head")
    assert_head(engine)


def test_m3_upgrade_preserves_legacy_records_without_inventing_location(release_database):
    engine, config = release_database
    command.upgrade(config, M3_PARENT)
    insert_legacy_records(engine)
    command.upgrade(config, "head")
    with engine.connect() as connection:
        row = connection.execute(sa.text(
            "SELECT * FROM assessments WHERE id='release-assessment'")).mappings().one()
        assert row["status"] == "confirmed" and row["conclusion"] == "人工最终结论"
        assert row["human_review_json"] == AUDIT and row["report_json"] == REPORT
        assert row["address"] is None and row["district"] is None and row["facility"] is None
        assert row["latitude"] is None and row["longitude"] is None and row["coordinate_system"] is None
        assert row["data_source"] is None and row["event_time"] is None
        assert row["source_ref"] is None and row["import_batch_id"] is None
    assert_head(engine)
    command.upgrade(config, "head")
    assert_head(engine)


def test_m5_upgrade_adds_source_and_alert_tables_without_touching_records(release_database):
    engine, config = release_database
    command.upgrade(config, M5_PARENT)
    insert_legacy_records(engine)
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT COUNT(*) FROM knowledge_sources")).scalar_one() == 0
        assert connection.execute(sa.text("SELECT COUNT(*) FROM trend_alerts")).scalar_one() == 0
        row = connection.execute(sa.text(
            "SELECT * FROM assessments WHERE id='release-assessment'")).mappings().one()
        assert row["status"] == "confirmed" and row["conclusion"] == "人工最终结论"
    assert_head(engine, retained=True)
    command.upgrade(config, "head")
    assert_head(engine, retained=True)


def test_m6_upgrade_adds_pack_sync_table_without_touching_records(release_database):
    engine, config = release_database
    command.upgrade(config, M6_PARENT)
    insert_legacy_records(engine)
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT COUNT(*) FROM knowledge_pack_imports")).scalar_one() == 0
        row = connection.execute(sa.text(
            "SELECT * FROM assessments WHERE id='release-assessment'")).mappings().one()
        assert row["status"] == "confirmed" and row["conclusion"] == "人工最终结论"
    assert_head(engine, retained=True)
    command.upgrade(config, "head")
    assert_head(engine, retained=True)


def test_pre_r3_upgrade_preserves_business_and_audit(release_database):
    engine, config = release_database
    command.upgrade(config, PRE_R3)
    insert_legacy_records(engine)
    command.upgrade(config, "head")
    assert_head(engine, retained=True)
    command.upgrade(config, "head")
    assert_head(engine, retained=True)


def test_unversioned_old_database_is_adopted_by_startup(release_database, monkeypatch):
    engine, config = release_database
    command.upgrade(config, PRE_R3)
    insert_legacy_records(engine)
    with engine.begin() as connection:
        connection.execute(sa.text("DROP TABLE alembic_version"))
    monkeypatch.setattr(database, "engine", engine)
    database.init_db()
    assert_head(engine, retained=True)
    database.init_db()
    assert_head(engine, retained=True)
