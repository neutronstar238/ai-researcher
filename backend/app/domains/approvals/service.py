"""Approval application service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError, NotFoundError
from app.db.models import Approval, ApprovalDecision
from app.domains.audit.service import record_audit


class ApprovalService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_approvals(self, project_id: uuid.UUID, status: str | None = None) -> list[Approval]:
        query = select(Approval).where(Approval.project_id == project_id).order_by(Approval.created_at.desc())
        if status:
            query = query.where(Approval.status == status)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_approval(self, approval_id: uuid.UUID) -> Approval:
        approval = await self.session.get(Approval, approval_id)
        if approval is None:
            raise NotFoundError("审批不存在")
        return approval

    async def decide(
        self, approval_id: uuid.UUID, user_id: uuid.UUID, decision: str, comment: str | None
    ) -> Approval:
        approval = await self.get_approval(approval_id)
        if approval.status != "pending":
            raise AppError("审批已处理，不可重复决定", code="APPROVAL_ALREADY_DECIDED", status_code=409)
        approval.status = decision
        approval.decided_at = datetime.now(UTC)
        self.session.add(
            ApprovalDecision(
                approval_id=approval.id, decision=decision, comment=comment, decided_by=user_id
            )
        )
        record_audit(
            self.session,
            action=f"approval.{decision}",
            actor_id=user_id,
            project_id=approval.project_id,
            target_type="approval",
            target_id=approval.id,
        )
        await self.session.commit()
        return approval
