"""Dependency probes used by readiness and health-summary endpoints (spec §10.7).

Probes must never raise into the handler; a missing dependency yields a
``degraded`` result, not a 500. Health is never guessed by the frontend.
"""

from __future__ import annotations

import asyncio
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_engine


async def _probe_postgres() -> dict[str, Any]:
    try:
        async with get_engine().connect() as conn:
            await asyncio.wait_for(conn.execute(text("SELECT 1")), timeout=3.0)
        return {"status": "healthy"}
    except Exception as exc:  # noqa: BLE001 - probe must not propagate
        return {"status": "unhealthy", "error": type(exc).__name__}


async def _probe_redis() -> dict[str, Any]:
    try:
        client = Redis.from_url(get_settings().redis_url, socket_connect_timeout=2)
        try:
            await asyncio.wait_for(client.ping(), timeout=3.0)
            return {"status": "healthy"}
        finally:
            await client.aclose()
    except Exception as exc:  # noqa: BLE001
        return {"status": "unhealthy", "error": type(exc).__name__}


async def probe_dependencies() -> dict[str, dict[str, Any]]:
    postgres, redis = await asyncio.gather(_probe_postgres(), _probe_redis())
    return {"postgres": postgres, "redis": redis}


def readiness_ok(checks: dict[str, dict[str, Any]]) -> bool:
    return all(item.get("status") == "healthy" for item in checks.values())
