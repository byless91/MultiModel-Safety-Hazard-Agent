import logging
import re
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.routes import router
from app.core.config import get_settings
from app.core.db import init_db
from app.core.logging import request_id_var, setup_logging

settings = get_settings()
setup_logging()
logger = logging.getLogger("safety_hazard.api")

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    from app.services.providers import get_provider
    from app.services.rag import get_rag

    # 预热含同步 IO（建索引/embedding），放线程池避免阻塞事件循环
    await run_in_threadpool(get_provider)
    await run_in_threadpool(get_rag)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    # HTTP 通用指标（延迟/状态码/QPS）；/metrics 走与业务一致的鉴权中间件，
    # 抓取端需带凭证。B4 认证批次再决定是否对内网放开。
    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "服务内部错误，请稍后重试或联系管理员"},
        )

    @app.middleware("http")
    async def log_requests(request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        logger.info(
            "%s %s -> %s (%.2fs)",
            request.method,
            request.url.path,
            response.status_code,
            time.perf_counter() - started,
        )
        return response

    @app.middleware("http")
    async def require_api_token(request, call_next):
        token = get_settings().api_bearer_token
        if token:
            header = (request.headers.get("Authorization") or "").encode("utf-8")
            expected = f"Bearer {token}".encode()
            # 常量时间比较，防止时序侧信道逐位猜解 token
            if not secrets.compare_digest(header, expected):
                return JSONResponse(status_code=401, content={"detail": "未授权"})
        return await call_next(request)

    @app.middleware("http")
    async def request_id_middleware(request, call_next):
        # 最后注册 = 最外层：此后所有中间件与业务日志都携带同一 request_id
        request_id = (request.headers.get("X-Request-ID") or "").strip()
        if not _REQUEST_ID_RE.match(request_id):
            request_id = uuid4().hex[:16]
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")

    return app


app = create_app()
