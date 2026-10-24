import logging
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings

logger = logging.getLogger("safety_hazard.db")
settings = get_settings()

_IS_SQLITE = settings.database_url.startswith("sqlite")
connect_args = {"check_same_thread": False} if _IS_SQLITE else {}
engine = create_engine(settings.database_url, connect_args=connect_args)

if _IS_SQLITE:

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        """WAL 允许读写并发；busy_timeout 避免瞬时锁冲突直接抛 database is locked。"""
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def stamp_if_unversioned(db_engine) -> bool:
    """create_all 引导出的库（无 alembic_version）自动 stamp 到 head。

    create_all 产出的必然是当前模型的完整结构，等价于 head；
    不 stamp 的话，后续 `alembic upgrade head` 会重放全部迁移并撞
    "table already exists"。返回是否执行了 stamp。
    """
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    inspector = inspect(db_engine)
    tables = inspector.get_table_names()
    if not tables or "alembic_version" in tables:
        return False
    backend_dir = Path(__file__).resolve().parents[2]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "migrations"))
    # str(url) 会把密码渲染成 ***，必须用 render_as_string 显式保留；
    # configparser 的 % 是插值语法，Windows 盘符 URL（C%3A）需转义
    raw_url = db_engine.url.render_as_string(hide_password=False)
    config.set_main_option("sqlalchemy.url", raw_url.replace("%", "%%"))
    command.stamp(config, "head")
    return True


def init_db() -> None:
    """Bootstrap missing tables only; all schema evolution goes through Alembic.

    create_all 只负责为全新空库（开发/测试）补齐缺失的表，不会修改已存在
    的表结构。任何列级变更（新增/修改/删除列）必须通过 Alembic 迁移：
    `uv run alembic revision --autogenerate -m "..."` 后随代码提交，
    部署时执行 `uv run alembic upgrade head`。
    """
    from app.models import entities  # noqa: F401

    Base.metadata.create_all(bind=engine)
    try:
        stamp_if_unversioned(engine)
    except Exception:
        logger.warning("alembic 版本标记失败（不影响启动，下次将重试）", exc_info=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
