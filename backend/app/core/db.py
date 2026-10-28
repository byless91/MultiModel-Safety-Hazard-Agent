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
    """create_all 引导但未版本化的库：stamp 到 base 再由 init_db upgrade 调和。

    create_all 只补表不加列，半新半旧的库不能直接 stamp head（会跳过
    补列迁移），因此 stamp 到 baseline，随后的 upgrade head 借助各迁移的
    存在性守卫把缺口补齐。返回是否执行了 stamp。
    """
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    tables = inspect(db_engine).get_table_names()
    if not tables or "alembic_version" in tables:
        return False
    backend_dir = Path(__file__).resolve().parents[2]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "migrations"))
    # configparser 的 % 是插值语法，Windows 盘符 URL（C%3A）需转义；
    # str(url) 会把密码渲染成 ***，必须用 render_as_string 显式保留
    raw_url = db_engine.url.render_as_string(hide_password=False)
    config.set_main_option("sqlalchemy.url", raw_url.replace("%", "%%"))
    command.stamp(config, "base")
    return True


def upgrade_to_head(db_engine) -> None:
    """把任意状态的库调和到 head（带守卫的迁移可安全重入）。"""
    from alembic import command
    from alembic.config import Config

    backend_dir = Path(__file__).resolve().parents[2]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "migrations"))
    raw_url = db_engine.url.render_as_string(hide_password=False)
    config.set_main_option("sqlalchemy.url", raw_url.replace("%", "%%"))
    command.upgrade(config, "head")


def init_db() -> None:
    """把任意状态的库调和到当前模型：全新/半旧/已版本化三条路径统一。

    - 全新空库：create_all 直接建成当前结构 → stamp base → upgrade（守卫全部空转）
    - 旧库（pre-alembic 或 create_all 半引导）：create_all 补缺失的表 →
      stamp base → upgrade 借助迁移守卫补缺失的列
    - 已版本化：upgrade 直接追平（通常为 no-op）
    列级变更必须通过 Alembic 迁移提交，create_all 永不修改既有表。
    """
    from app.models import entities  # noqa: F401

    Base.metadata.create_all(bind=engine)
    try:
        stamp_if_unversioned(engine)
        upgrade_to_head(engine)
    except Exception:
        logger.error("数据库迁移失败，拒绝继续启动", exc_info=True)
        raise


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
