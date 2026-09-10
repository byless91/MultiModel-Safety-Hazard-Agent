import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import get_settings
from app.core.db import init_db
from app.core.logging import setup_logging

settings = get_settings()
setup_logging()
logger = logging.getLogger("safety_hazard.api")


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "服务内部错误，请稍后重试或联系管理员"},
        )

    @app.middleware("http")
    async def log_requests(request, call_next):
        import time

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
        if token and request.headers.get("Authorization") != f"Bearer {token}":
            return JSONResponse(status_code=401, content={"detail": "未授权"})
        return await call_next(request)

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")

    @app.on_event("startup")
    def startup() -> None:
        init_db()
        from app.services.providers import get_provider
        from app.services.rag import get_rag

        get_provider()
        get_rag()

    return app


app = create_app()
