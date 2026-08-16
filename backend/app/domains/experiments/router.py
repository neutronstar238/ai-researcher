"""Experiment API routes (spec §15.6)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, SessionDep, require_project_role
from app.db.models import User
from app.domains.experiments.schemas import (
    BindArtifactRequest,
    BindDatasetRequest,
    ExperimentCreate,
    ExperimentOut,
    MetricOut,
    MetricRecord,
    RunCreate,
    RunOut,
)
from app.domains.experiments.service import ExperimentService

router = APIRouter(tags=["experiments"])

require_view = require_project_role("view")
require_edit = require_project_role("run_experiment")


@router.get("/projects/{project_id}/experiments", response_model=list[ExperimentOut])
async def list_experiments(
    project_id: uuid.UUID,
    session: SessionDep,
    _user: User = Depends(require_view),
) -> list[ExperimentOut]:
    experiments = await ExperimentService(session).list_experiments(project_id)
    return [ExperimentOut.model_validate(e, from_attributes=True) for e in experiments]


@router.post("/projects/{project_id}/experiments", response_model=ExperimentOut, status_code=201)
async def create_experiment(
    project_id: uuid.UUID,
    payload: ExperimentCreate,
    user: CurrentUser,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> ExperimentOut:
    experiment = await ExperimentService(session).create_experiment(project_id, payload, user.id)
    return ExperimentOut.model_validate(experiment, from_attributes=True)


@router.get("/projects/{project_id}/experiments/{experiment_id}", response_model=ExperimentOut)
async def get_experiment(
    project_id: uuid.UUID,
    experiment_id: uuid.UUID,
    session: SessionDep,
    _user: User = Depends(require_view),
) -> ExperimentOut:
    experiment = await ExperimentService(session).get_experiment(experiment_id)
    return ExperimentOut.model_validate(experiment, from_attributes=True)


@router.post(
    "/projects/{project_id}/experiments/{experiment_id}/runs", response_model=RunOut, status_code=201
)
async def create_run(
    project_id: uuid.UUID,
    experiment_id: uuid.UUID,
    payload: RunCreate,
    user: CurrentUser,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> RunOut:
    run = await ExperimentService(session).create_run(experiment_id, payload, user.id)
    return RunOut.model_validate(run, from_attributes=True)


@router.get("/projects/{project_id}/experiment-runs/{run_id}", response_model=RunOut)
async def get_run(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    session: SessionDep,
    _user: User = Depends(require_view),
) -> RunOut:
    run = await ExperimentService(session).get_run(run_id)
    return RunOut.model_validate(run, from_attributes=True)


@router.post("/projects/{project_id}/experiment-runs/{run_id}:cancel", response_model=RunOut)
async def cancel_run(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> RunOut:
    run = await ExperimentService(session).cancel_run(run_id)
    return RunOut.model_validate(run, from_attributes=True)


@router.post("/projects/{project_id}/experiment-runs/{run_id}/metrics", response_model=list[MetricOut], status_code=201)
async def record_metrics(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    payload: list[MetricRecord],
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> list[MetricOut]:
    metrics = await ExperimentService(session).record_metrics(run_id, payload)
    return [MetricOut.model_validate(m, from_attributes=True) for m in metrics]


@router.get("/projects/{project_id}/experiment-runs/{run_id}/metrics", response_model=list[MetricOut])
async def list_metrics(
    project_id: uuid.UUID, run_id: uuid.UUID, session: SessionDep, _user: User = Depends(require_view)
) -> list[MetricOut]:
    metrics = await ExperimentService(session).list_metrics(run_id)
    return [MetricOut.model_validate(m, from_attributes=True) for m in metrics]


@router.get("/projects/{project_id}/experiment-runs/{run_id}/reproducibility")
async def reproducibility(
    project_id: uuid.UUID, run_id: uuid.UUID, session: SessionDep, _user: User = Depends(require_view)
) -> dict:
    return await ExperimentService(session).reproducibility(run_id)


@router.post("/projects/{project_id}/experiment-runs/{run_id}/datasets", status_code=201)
async def bind_dataset(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    payload: BindDatasetRequest,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> dict:
    binding = await ExperimentService(session).bind_dataset(
        run_id, payload.dataset_version_id, payload.mount_path, payload.access_mode
    )
    return {
        "run_id": str(binding.run_id),
        "dataset_version_id": str(binding.dataset_version_id),
        "mount_path": binding.mount_path,
        "access_mode": binding.access_mode,
    }


@router.post("/projects/{project_id}/experiment-runs/{run_id}/artifacts", status_code=201)
async def bind_artifact(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    payload: BindArtifactRequest,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> dict:
    binding = await ExperimentService(session).bind_artifact(
        run_id, payload.asset_id, payload.role, payload.name
    )
    return {"run_id": str(binding.run_id), "asset_id": str(binding.asset_id), "name": binding.name}
