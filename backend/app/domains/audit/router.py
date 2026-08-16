"""Audit API routes (spec §19.6)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from app.api.deps import SessionDep, require_project_role
from app.db.models import User
from app.domains.audit.service import list_audit_logs

router = APIRouter(tags=["audit"])

require_owner = require_project_role("manage_members")


@router.get("/projects/{project_id}/audit-logs")
async def get_audit_logs(
    project_id: uuid.UUID,
    session: SessionDep,
    limit: int = Query(default=100, ge=1, le=500),
    _owner: User = Depends(require_owner),
) -> list[dict]:
    logs = await list_audit_logs(session, project_id, limit)
    return [
        {
            "id": str(log.id),
            "action": log.action,
            "actor_type": log.actor_type,
            "target_type": log.target_type,
            "created_at": log.created_at.isoformat(),
        }
        for log in logs
    ]
