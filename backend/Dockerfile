# 后端镜像：uv 锁定依赖 + 启动时执行 Alembic 迁移
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# 先装依赖（利用层缓存：pyproject/uv.lock 不变则跳过）
COPY pyproject.toml uv.lock alembic.ini ./
COPY migrations ./migrations
RUN uv sync --frozen --no-dev --no-install-project --extra faiss --extra pg

COPY app ./app
COPY resources/knowledge_seed ./resources/knowledge_seed
RUN chmod -R a-w /app/resources/knowledge_seed

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PROVIDER_MODE=mock

EXPOSE 8001

# 启动即迁移（旧库自动 stamp/增量；全新库完整建表）
# 当前仅支持单实例、单 worker；PG 也不解除 checkpoint/文件/索引约束。
CMD ["sh", "-c", "python -m alembic upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --workers 1"]
