"""Dataset API routes (spec §18.5)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, SessionDep, require_project_role
from app.db.models import User
from app.domains.datasets.schemas import (
    DatasetCreate,
    DatasetOut,
    DatasetVersionCreate,
    DatasetVersionOut,
)
from app.domains.datasets.service import DatasetService

router = APIRouter(tags=["datasets"])

require_view = require_project_role("view")
require_edit = require_project_role("upload")


@router.get("/projects/{project_id}/datasets", response_model=list[DatasetOut])
async def list_datasets(
    project_id: uuid.UUID, session: SessionDep, _user: User = Depends(require_view)
) -> list[DatasetOut]:
    datasets = await DatasetService(session).list_datasets(project_id)
    return [DatasetOut.model_validate(d, from_attributes=True) for d in datasets]


@router.post("/projects/{project_id}/datasets", response_model=DatasetOut, status_code=201)
async def create_dataset(
    project_id: uuid.UUID,
    payload: DatasetCreate,
    user: CurrentUser,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> DatasetOut:
    dataset = await DatasetService(session).create_dataset(project_id, payload, user.id)
    return DatasetOut.model_validate(dataset, from_attributes=True)


@router.get("/projects/{project_id}/datasets/{dataset_id}", response_model=DatasetOut)
async def get_dataset(
    project_id: uuid.UUID, dataset_id: uuid.UUID, session: SessionDep, _user: User = Depends(require_view)
) -> DatasetOut:
    dataset = await DatasetService(session).get_dataset(dataset_id)
    return DatasetOut.model_validate(dataset, from_attributes=True)


@router.post(
    "/projects/{project_id}/datasets/{dataset_id}/versions",
    response_model=DatasetVersionOut,
    status_code=201,
)
async def create_version(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: DatasetVersionCreate,
    user: CurrentUser,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> DatasetVersionOut:
    version = await DatasetService(session).create_version(dataset_id, payload, user.id)
    return DatasetVersionOut.model_validate(version, from_attributes=True)
