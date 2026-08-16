"""FastAPI application entrypoint (spec §10).

Request processing order (§10.2):
  request id -> auth -> context resolution -> authorization -> validation
  -> domain service -> transaction + audit + outbox -> response envelope.
Auth/context/authorization are Phase 1/2; Phase 0 establishes the shell,
health checks and the error envelope.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_exception_handlers
from app.api.health import router as health_router
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.observability import setup_metrics, setup_tracing
from app.db.session import dispose_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging()
    settings.validate_for_production()
    try:
        from app.integrations.object_storage.minio import MinioStorage

        MinioStorage().ensure_bucket()
    except Exception:  # noqa: BLE001 - MinIO 未就绪时不阻断启动
        pass
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AI-Researcher API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    register_exception_handlers(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        # 安全头（spec §19.3）
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            response.headers["Content-Security-Policy"] = "default-src 'self'"
        return response

    app.include_router(health_router)
    app.include_router(api_router, prefix="/api/v1")

    # 可观测性（spec §19.7）：Prometheus 指标始终开启，OTel trace 按配置启用。
    setup_metrics(app)
    setup_tracing(app)
    return app


app = create_app()
