"""Alembic 迁移环境：连接串复用应用 Settings，元数据来自 app 模型。

- 未显式指定 sqlalchemy.url 时，从 .env / DATABASE_URL 环境变量解析（与应用一致）
- SQLite 下启用 batch 模式，使 ALTER 类变更可执行
- 不调用 logging.fileConfig：它会整体替换 root handlers，把应用的结构化
  日志配置（或测试的 caplog）清掉——alembic 自身日志经 root 正常输出
"""

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.core.db import Base

# 注册全部模型，保证 Base.metadata 完整（autogenerate 依赖）
import app.models.entities  # noqa: F401

config = context.config

target_metadata = Base.metadata


def _database_url() -> str:
    """显式传入的 sqlalchemy.url 优先（测试/脚本覆盖），否则走应用 Settings。"""
    explicit = config.get_main_option("sqlalchemy.url")
    if explicit:
        return explicit
    return get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
