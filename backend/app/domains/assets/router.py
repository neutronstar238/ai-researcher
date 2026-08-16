"""Asset API routes (spec §18.5)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, SessionDep, require_project_role
from app.db.models import User
from app.domains.assets.schemas import AssetOut, CompleteUploadRequest, InitiateUploadRequest
from app.domains.assets.service import AssetService

router = APIRouter(tags=["assets"])

require_view = require_project_role("view")
require_edit = require_project_role("upload")


@router.post("/projects/{project_id}/assets/uploads:initiate")
async def initiate_upload(
    project_id: uuid.UUID,
    payload: InitiateUploadRequest,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> dict:
    return await AssetService(session).initiate(project_id, payload)


@router.post("/projects/{project_id}/assets/uploads/{upload_id}:complete", response_model=AssetOut, status_code=201)
async def complete_upload(
    project_id: uuid.UUID,
    upload_id: str,
    payload: CompleteUploadRequest,
    user: CurrentUser,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> AssetOut:
    asset = await AssetService(session).complete(project_id, upload_id, payload, user.id)
    return AssetOut.model_validate(asset, from_attributes=True)


@router.get("/projects/{project_id}/assets", response_model=list[AssetOut])
async def list_assets(
    project_id: uuid.UUID,
    session: SessionDep,
    _user: User = Depends(require_view),
) -> list[AssetOut]:
    assets = await AssetService(session).list_assets(project_id)
    return [AssetOut.model_validate(a, from_attributes=True) for a in assets]


@router.get("/projects/{project_id}/assets/{asset_id}/download-url")
async def download_url(
    project_id: uuid.UUID,
    asset_id: uuid.UUID,
    session: SessionDep,
    _user: User = Depends(require_view),
) -> dict:
    service = AssetService(session)
    asset = await service.get_asset(asset_id)
    return {"download_url": service.download_url(asset), "expires_in": 300}
