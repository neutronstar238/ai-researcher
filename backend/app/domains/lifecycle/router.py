"""Lifecycle API routes (spec §12.5)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, SessionDep, require_project_role
from app.core.lifecycle import gate_missing
from app.db.models import User
from app.domains.lifecycle.schemas import (
    BlockStageRequest,
    CompleteStageRequest,
    ReopenStageRequest,
    StageOut,
    StartStageRequest,
)
from app.domains.lifecycle.service import LifecycleService, stage_to_out

router = APIRouter(tags=["lifecycle"])

require_view = require_project_role("view")
require_edit = require_project_role("edit_content")


@router.get("/projects/{project_id}/cycles/{cycle_id}/lifecycle", response_model=list[StageOut])
async def list_lifecycle(
    project_id: uuid.UUID,
    cycle_id: uuid.UUID,
    session: SessionDep,
    _user: User = Depends(require_view),
) -> list[StageOut]:
    stages = await LifecycleService(session).list_stages(cycle_id)
    return [StageOut(**stage_to_out(stage)) for stage in stages]


@router.get("/projects/{project_id}/cycles/{cycle_id}/stages/{stage_key}/gate")
async def stage_gate(
    project_id: uuid.UUID,
    cycle_id: uuid.UUID,
    stage_key: str,
    session: SessionDep,
    _user: User = Depends(require_view),
) -> dict:
    stage = await LifecycleService(session).get_stage(cycle_id, stage_key)
    missing = gate_missing(stage_key, stage.evidence_count)
    return {"passed": not missing, "missing": missing, "stage_key": stage_key}


@router.post(
    "/projects/{project_id}/cycles/{cycle_id}/stages/{stage_key}:start", response_model=StageOut
)
async def start_stage(
    project_id: uuid.UUID,
    cycle_id: uuid.UUID,
    stage_key: str,
    payload: StartStageRequest,
    user: CurrentUser,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> StageOut:
    stage = await LifecycleService(session).start_stage(
        cycle_id, stage_key, user.id, payload.expected_version
    )
    return StageOut(**stage_to_out(stage))


@router.post(
    "/projects/{project_id}/cycles/{cycle_id}/stages/{stage_key}:complete", response_model=StageOut
)
async def complete_stage(
    project_id: uuid.UUID,
    cycle_id: uuid.UUID,
    stage_key: str,
    payload: CompleteStageRequest,
    user: CurrentUser,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> StageOut:
    stage = await LifecycleService(session).complete_stage(
        cycle_id,
        stage_key,
        user.id,
        payload.expected_version,
        payload.completion_note,
        payload.evidence_node_ids,
    )
    return StageOut(**stage_to_out(stage))


@router.post(
    "/projects/{project_id}/cycles/{cycle_id}/stages/{stage_key}:block", response_model=StageOut
)
async def block_stage(
    project_id: uuid.UUID,
    cycle_id: uuid.UUID,
    stage_key: str,
    payload: BlockStageRequest,
    user: CurrentUser,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> StageOut:
    stage = await LifecycleService(session).block_stage(cycle_id, stage_key, user.id, payload.reason)
    return StageOut(**stage_to_out(stage))


@router.post(
    "/projects/{project_id}/cycles/{cycle_id}/stages/{stage_key}:resume", response_model=StageOut
)
async def resume_stage(
    project_id: uuid.UUID,
    cycle_id: uuid.UUID,
    stage_key: str,
    user: CurrentUser,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> StageOut:
    stage = await LifecycleService(session).resume_stage(cycle_id, stage_key, user.id)
    return StageOut(**stage_to_out(stage))


@router.post(
    "/projects/{project_id}/cycles/{cycle_id}/stages/{stage_key}:reopen", response_model=StageOut
)
async def reopen_stage(
    project_id: uuid.UUID,
    cycle_id: uuid.UUID,
    stage_key: str,
    payload: ReopenStageRequest,
    user: CurrentUser,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> StageOut:
    stage = await LifecycleService(session).reopen_stage(cycle_id, stage_key, user.id, payload.reason)
    return StageOut(**stage_to_out(stage))
