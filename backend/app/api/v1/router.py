"""Aggregate API v1 router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import system, ws
from app.domains.agents.memory import router as agent_memory_router
from app.domains.agents.router import router as agents_router
from app.domains.approvals.router import router as approvals_router
from app.domains.assets.router import router as assets_router
from app.domains.audit.router import router as audit_router
from app.domains.auth.router import router as auth_router
from app.domains.datasets.router import router as datasets_router
from app.domains.evidence.router import router as evidence_router
from app.domains.experiments.router import router as experiments_router
from app.domains.lifecycle.router import router as lifecycle_router
from app.domains.literature.router import router as literature_router
from app.domains.projects.router import router as projects_router
from app.domains.projects.topics import router as topics_router
from app.domains.teams.router import router as teams_router
from app.domains.vector.router import router as vector_router
from app.domains.writing.reflection import router as reflection_router
from app.domains.writing.router import router as writing_router

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(ws.router)
api_router.include_router(auth_router)
api_router.include_router(teams_router)
api_router.include_router(projects_router)
api_router.include_router(lifecycle_router)
api_router.include_router(topics_router)
api_router.include_router(approvals_router)
api_router.include_router(evidence_router)
api_router.include_router(literature_router)
api_router.include_router(assets_router)
api_router.include_router(vector_router)
api_router.include_router(experiments_router)
api_router.include_router(datasets_router)
api_router.include_router(agents_router)
api_router.include_router(agent_memory_router)
api_router.include_router(writing_router)
api_router.include_router(reflection_router)
api_router.include_router(audit_router)
