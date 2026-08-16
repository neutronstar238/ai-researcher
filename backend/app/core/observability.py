"""Observability wiring (spec §19.7/§22.3).

Two layers:
- Prometheus HTTP + business metrics (``/metrics``, always on).
- OpenTelemetry tracing (FastAPI spans → OTLP exporter), enabled only when
  ``OTEL_EXPORTER_OTLP_ENDPOINT`` is configured; otherwise a no-op so the app
  still starts without a collector.

业务指标必须由真实事件驱动（§28「每一个数字都有查询来源」），不写死、不伪造。
HTTP 指标用路由模板归一化路径，避免把 UUID 展开成高基数标签。
"""

from __future__ import annotations

import logging
import time

from fastapi import FastAPI, Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, Counter, Histogram, generate_latest

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# -- 业务指标 -----------------------------------------------------------
AUDIT_EVENTS = Counter("ar_audit_events_total", "审计事件数", ["action"])
EXPERIMENT_RUNS = Counter("ar_experiment_runs_total", "实验运行数", ["status"])

# -- HTTP 指标 ----------------------------------------------------------
HTTP_REQUESTS = Counter(
    "ar_http_requests_total", "HTTP 请求数", ["method", "path", "status"]
)
HTTP_LATENCY = Histogram(
    "ar_http_request_duration_seconds", "HTTP 请求耗时（秒）", ["method", "path"]
)


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    if route is not None and getattr(route, "path", None):
        return route.path
    return request.url.path


def setup_metrics(app: FastAPI) -> None:
    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        template = _route_template(request)
        HTTP_REQUESTS.labels(
            method=request.method, path=template, status=str(response.status_code)
        ).inc()
        HTTP_LATENCY.labels(method=request.method, path=template).observe(
            time.perf_counter() - start
        )
        return response

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

    logger.info("Prometheus /metrics enabled")


def setup_tracing(app: FastAPI) -> bool:
    endpoint = get_settings().otel_exporter_otlp_endpoint
    if not endpoint:
        logger.info("OTel tracing disabled (OTEL_EXPORTER_OTLP_ENDPOINT not set)")
        return False

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": "ai-researcher-api"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
    logger.info("OTel tracing enabled -> %s", endpoint)
    return True
