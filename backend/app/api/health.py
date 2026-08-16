"""Liveness and readiness endpoints (spec §10.7)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.health import probe_dependencies, readiness_ok

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def health_live() -> dict[str, str]:
    """Process liveness; never touches external dependencies."""
    return {"status": "alive"}


@router.get("/health/ready")
async def health_ready() -> JSONResponse:
    """Readiness: PostgreSQL and Redis must be reachable."""
    checks = await probe_dependencies()
    if readiness_ok(checks):
        return JSONResponse({"status": "ready", "checks": checks})
    return JSONResponse({"status": "degraded", "checks": checks}, status_code=503)
