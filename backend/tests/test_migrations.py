"""B2/WP4.1：Alembic 迁移纪律——两条建库路径结构一致、旧库采纳无损。

验收标准（计划书 WP4.1）：
1. 新空库：alembic upgrade head 与 create_all（init_db 路径）产出结构一致；
2. 旧库（含 ensure_columns 时代加过的列）：直接 alembic upgrade head 无损，
   数据保留，且纳入版本管理（后续增量迁移可执行）。
"""

import os
import sqlite3
from pathlib import Path

import pytest

# 本文件验证 SQLite 方言下的迁移语义（PRAGMA/原子写/DROP COLUMN）；
# PostgreSQL 方言由 alembic 本身保证，CI PG 矩阵跳过
if not os.environ.get("DATABASE_URL", "sqlite").startswith("sqlite"):
    pytest.skip("迁移方言测试仅针对 SQLite", allow_module_level=True)

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

import app.models.entities  # noqa: F401  确保 metadata 注册
from app.core.db import Base

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # 测试内显式覆盖目标库，不依赖 .env / 环境变量
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _schema_snapshot(db_path: Path) -> dict[str, list[tuple]]:
    """导出全部表的结构（列名/类型/非空/主键），忽略 alembic 版本表。"""
    conn = sqlite3.connect(db_path)
    try:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'"
            )
        ]
        return {
            table: sorted(
                (col[1], col[2].upper(), col[3], col[5])
                for col in conn.execute(f"PRAGMA table_info({table})")
            )
            for table in sorted(tables)
        }
    finally:
        conn.close()


def test_fresh_db_alembic_matches_create_all(tmp_path: Path):
    alembic_db = tmp_path / "alembic.db"
    create_all_db = tmp_path / "create_all.db"

    command.upgrade(
        _alembic_config(f"sqlite:///{alembic_db.as_posix()}"), "head"
    )
    engine = create_engine(f"sqlite:///{create_all_db.as_posix()}")
    Base.metadata.create_all(engine)
    engine.dispose()

    assert _schema_snapshot(alembic_db) == _schema_snapshot(
        create_all_db
    ), "alembic 建库与 create_all 建库结构不一致，baseline 需要重新生成"


def test_existing_db_upgrade_head_is_lossless(tmp_path: Path):
    """旧库（B2 时代的结构：有业务表、无 assessment_jobs/idempotency_keys、
    无 alembic_version）直接 upgrade head：增量迁移补建新表，存量数据不丢。
    """
    old_db = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{old_db.as_posix()}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        # 模拟 B2 时代结构：删掉 B3/B4 新增的表与列
        conn.execute(text("DROP TABLE IF EXISTS idempotency_keys"))
        conn.execute(text("DROP TABLE IF EXISTS assessment_jobs"))
        conn.execute(text("DROP TABLE IF EXISTS users"))
        conn.execute(text("DROP TABLE IF EXISTS llm_calls"))
        conn.execute(text("DROP INDEX IF EXISTS ix_assessments_confirmed_by_id"))
        conn.execute(text("ALTER TABLE assessments DROP COLUMN confirmed_by_id"))
        conn.execute(text("ALTER TABLE assessments DROP COLUMN confirmed_by_name"))
        conn.execute(
            text(
                "INSERT INTO assessments (id, description, status, followup_used, "
                "confirmed, created_at, updated_at) "
                "VALUES ('legacy-1', '旧库存量研判记录', 'completed', 0, 1, "
                "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )
    engine.dispose()

    command.upgrade(_alembic_config(f"sqlite:///{old_db.as_posix()}"), "head")

    conn = sqlite3.connect(old_db)
    try:
        rows = conn.execute(
            "SELECT id, description FROM assessments"
        ).fetchall()
        versioned = conn.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchall()
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        conn.close()
    assert rows == [("legacy-1", "旧库存量研判记录")]
    assert len(versioned) == 1, "旧库未被纳入 alembic 版本管理"
    assert {"assessment_jobs", "idempotency_keys"} <= tables, "增量迁移未补建新表"


def test_create_all_bootstrap_reconciles_to_head(tmp_path: Path):
    """create_all 半引导的库（有新表、缺新列）经调和后补齐并版本化到 head。"""
    from app.core.db import stamp_if_unversioned, upgrade_to_head

    db_path = tmp_path / "bootstrapped.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    Base.metadata.create_all(engine)

    # 模拟半旧库：create_all 只补表不加列——删列删表后应由迁移守卫补回
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS ix_assessments_confirmed_by_id"))
        conn.execute(text("ALTER TABLE assessments DROP COLUMN confirmed_by_id"))
        conn.execute(text("DROP TABLE llm_calls"))

    assert stamp_if_unversioned(engine) is True
    upgrade_to_head(engine)

    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(assessments)"))}
        tables = {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        }
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert "confirmed_by_id" in cols, "调和流程未补回缺失列"
    assert "llm_calls" in tables, "调和流程未补回缺失表"
    assert version, "调和后必须写入版本号"
    engine.dispose()
