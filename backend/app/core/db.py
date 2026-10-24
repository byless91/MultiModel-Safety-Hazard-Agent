from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings

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


def init_db() -> None:
    """Bootstrap missing tables only; all schema evolution goes through Alembic.

    create_all 只负责为全新空库（开发/测试）补齐缺失的表，不会修改已存在
    的表结构。任何列级变更（新增/修改/删除列）必须通过 Alembic 迁移：
    `uv run alembic revision --autogenerate -m "..."` 后随代码提交，
    部署时执行 `uv run alembic upgrade head`。
    """
    from app.models import entities  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
