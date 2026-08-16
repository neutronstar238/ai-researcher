"""Approval API routes (spec §18.6)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, SessionDep, require_project_role
from app.db.models import User
from app.domains.approvals.schemas import ApprovalOut, ApproveRequest, RejectRequest
from app.domains.approvals.service import ApprovalService

router = APIRouter(tags=["approvals"])

require_view = require_project_role("view")
require_approve = require_project_role("approve")


@router.get("/projects/{project_id}/approvals", response_model=list[ApprovalOut])
async def list_approvals(
    project_id: uuid.UUID,
    session: SessionDep,
    status: str | None = Query(default=None),
    _user: User = Depends(require_view),
) -> list[ApprovalOut]:
    approvals = await ApprovalService(session).list_approvals(project_id, status)
    return [ApprovalOut.model_validate(a, from_attributes=True) for a in approvals]


@router.get("/projects/{project_id}/approvals/{approval_id}", response_model=ApprovalOut)
async def get_approval(
    project_id: uuid.UUID,
    approval_id: uuid.UUID,
    session: SessionDep,
    _user: User = Depends(require_view),
) -> ApprovalOut:
    approval = await ApprovalService(session).get_approval(approval_id)
    return ApprovalOut.model_validate(approval, from_attributes=True)


@router.post("/projects/{project_id}/approvals/{approval_id}:approve", response_model=ApprovalOut)
async def approve(
    project_id: uuid.UUID,
    approval_id: uuid.UUID,
    payload: ApproveRequest,
    user: CurrentUser,
    session: SessionDep,
    _owner: User = Depends(require_approve),
) -> ApprovalOut:
    approval = await ApprovalService(session).decide(approval_id, user.id, "approved", payload.comment)
    return ApprovalOut.model_validate(approval, from_attributes=True)


@router.post("/projects/{project_id}/approvals/{approval_id}:reject", response_model=ApprovalOut)
async def reject(
    project_id: uuid.UUID,
    approval_id: uuid.UUID,
    payload: RejectRequest,
    user: CurrentUser,
    session: SessionDep,
    _owner: User = Depends(require_approve),
) -> ApprovalOut:
    approval = await ApprovalService(session).decide(approval_id, user.id, "rejected", payload.comment)
    return ApprovalOut.model_validate(approval, from_attributes=True)
