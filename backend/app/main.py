import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi.errors import RateLimitExceeded
from starlette.responses import PlainTextResponse

from app.api.routes import public_router, router
from app.core.config import get_settings
from app.core.db import init_db
from app.core.logging import request_id_var, setup_logging
from app.core.rate_limit import limiter
from app.core.security import verify_upload_signature

settings = get_settings()
setup_logging()
logger = logging.getLogger("safety_hazard.api")

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    from app.services.followup import recover_abandoned_sync_followups

    recovered = await run_in_threadpool(recover_abandoned_sync_followups)
    if recovered:
        logger.warning("回收进程遗留的同步追问预留 %d 条；未自动重放模型调用", recovered)
    if settings.auth_mode == "jwt" and settings.auth_jwt_secret == "dev-insecure-secret-change-me":
        logger.warning("AUTH_MODE=jwt 但仍在使用默认开发密钥，生产必须设置 AUTH_JWT_SECRET")
    if settings.auth_mode == "none":
        logger.warning("AUTH_MODE=none：当前无任何鉴权，仅限本地开发使用")
    from app.services.providers import get_provider
    from app.services.rag import get_rag

    # 预热含同步 IO（建索引/embedding），放线程池避免阻塞事件循环
    await run_in_threadpool(get_provider)
    await run_in_threadpool(get_rag)
    if settings.workflow_mode == "async":
        from app.services.job_runner import get_job_runner

        await get_job_runner().start()
    yield
    if settings.workflow_mode == "async":
        from app.services.job_runner import get_job_runner

        await get_job_runner().stop()
    # 释放 provider 持久连接池（B5/WP3.1）
    from app.services.providers import get_providers

    for provider in get_providers():
        close = getattr(provider, "close", None)
        if close is not None:
            close()


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Assessment-Id", "Location", "Idempotency-Replayed"],
    )
    app.include_router(public_router)
    app.include_router(router)

    # HTTP 通用指标（延迟/状态码/QPS）；/metrics 面向内网监控，不做鉴权
    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    # 限流（默认关闭，见 app/core/rate_limit.py）
    app.state.limiter = limiter

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> PlainTextResponse:
        return PlainTextResponse("请求过于频繁，请稍后再试", status_code=429)

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

    @app.get("/uploads/{file_path:path}")
    def serve_upload(file_path: str, exp: str | None = None, sig: str | None = None) -> FileResponse:
        """受保护的静态文件（B4/WP2.3）：auth 模式下走短期签名 URL。

        浏览器 <img> 无法携带 Authorization 头，因此 /api/v1 返回的图片 URL
        均附带 HMAC 签名与过期时间（sign_upload_url），此处校验后流式返回。
        """
        verify_upload_signature(f"/uploads/{file_path}", exp, sig)
        upload_root = settings.upload_dir.resolve()
        target = (settings.upload_dir / file_path).resolve()
        if not target.is_relative_to(upload_root) or not target.is_file():
            raise HTTPException(status_code=404, detail="文件不存在")
        return FileResponse(target)

    return app


app = create_app()
