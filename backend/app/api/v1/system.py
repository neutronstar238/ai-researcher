"""System endpoints (Phase 0: real health summary; later: settings/connectors)."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.health import probe_dependencies

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health/summary")
async def health_summary() -> dict:
    """Return dependency availability; UI must not guess health from this."""
    checks = await probe_dependencies()
    return {
        "status": "healthy" if all(c["status"] == "healthy" for c in checks.values()) else "degraded",
        "checks": checks,
        # External providers are not probed in Phase 0; reported as unconfigured.
        "llm_configured": False,
        "embedding_configured": False,
        "experiment_runner_configured": False,
    }
