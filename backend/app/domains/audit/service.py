"""Audit logging service (spec §19.6).

审计记录只追加、普通用户不可删除；与业务写入同事务提交（由调用方在同一 session 内调用）。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.observability import AUDIT_EVENTS
from app.db.models import AuditLog


def record_audit(
    session: AsyncSession,
    *,
    action: str,
    actor_type: str = "user",
    actor_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    after_redacted: dict | None = None,
) -> AuditLog:
    entry = AuditLog(
        team_id=team_id,
        project_id=project_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        after_redacted=after_redacted,
    )
    session.add(entry)
    AUDIT_EVENTS.labels(action=action).inc()
    return entry


async def list_audit_logs(session: AsyncSession, project_id: uuid.UUID, limit: int = 100) -> list[AuditLog]:
    result = await session.execute(
        select(AuditLog)
        .where(AuditLog.project_id == project_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
