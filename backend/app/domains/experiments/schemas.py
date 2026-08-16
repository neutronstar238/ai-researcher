"""Experiment schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ExperimentCreate(BaseModel):
    cycle_id: uuid.UUID
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=200)
    objective: str | None = None
    entrypoint: str = Field(min_length=1, max_length=4000)
    container_image: str | None = None


class ExperimentOut(BaseModel):
    id: uuid.UUID
    cycle_id: uuid.UUID
    code: str
    name: str
    objective: str | None
    entrypoint: str
    status: str
    version: int

    model_config = {"from_attributes": True}


class RunCreate(BaseModel):
    parameters: dict | None = None
    random_seed: int | None = None
    resource_request: dict | None = None


class MetricRecord(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    step: int = 0
    value: float


class MetricOut(BaseModel):
    name: str
    step: int
    value: float
    recorded_at: datetime

    model_config = {"from_attributes": True}


class BindDatasetRequest(BaseModel):
    dataset_version_id: uuid.UUID
    mount_path: str = Field(min_length=1, max_length=255)
    access_mode: str = "read_only"


class BindArtifactRequest(BaseModel):
    asset_id: uuid.UUID
    role: str | None = None
    name: str = Field(min_length=1, max_length=160)


class RunOut(BaseModel):
    id: uuid.UUID
    experiment_id: uuid.UUID
    run_no: int
    status: str
    parameters: dict | None
    random_seed: int | None
    exit_code: int | None
    error: dict | None
    log_output: str | None
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    model_config = {"from_attributes": True}
