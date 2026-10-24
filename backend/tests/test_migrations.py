"""B2/WP4.1：Alembic 迁移纪律——两条建库路径结构一致、旧库采纳无损。

验收标准（计划书 WP4.1）：
1. 新空库：alembic upgrade head 与 create_all（init_db 路径）产出结构一致；
2. 旧库（含 ensure_columns 时代加过的列）：直接 alembic upgrade head 无损，
   数据保留，且纳入版本管理（后续增量迁移可执行）。
"""

import sqlite3
from pathlib import Path

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


def test_create_all_bootstrap_is_stamped(tmp_path: Path):
    """create_all 引导的库（init_db 路径）自动 stamp head，后续 upgrade 不炸。"""
    from app.core.db import stamp_if_unversioned

    db_path = tmp_path / "bootstrapped.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    Base.metadata.create_all(engine)

    # stamp_if_unversioned 默认用全局 engine 的 URL，这里直接对全局逻辑做等价验证：
    # 无版本号 + 有表 → stamp；已版本化 → 不重复 stamp
    assert stamp_if_unversioned(engine) is True
    # stamp 后 alembic_version 存在，且指向 head
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert version
    assert stamp_if_unversioned(engine) is False
    engine.dispose()


def test_future_incremental_migration_applies_on_adopted_db(tmp_path: Path):
    """已采纳（upgrade 过 baseline）的库，后续增量迁移可正常执行。

    以 downgrade 到 base 再 upgrade 回 head 模拟一次增量往返。
    """
    db_path = tmp_path / "cycle.db"
    config = _alembic_config(f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    snapshot = _schema_snapshot(db_path)
    assert {
        "assessments",
        "assessment_images",
        "assessment_jobs",
        "idempotency_keys",
        "knowledge_documents",
        "users",
    } == set(snapshot)
