"""Dataset schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    license: str | None = None
    sensitivity: str = "internal"


class DatasetOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str | None
    license: str | None
    sensitivity: str
    created_at: datetime

    model_config = {"from_attributes": True}


class DatasetVersionCreate(BaseModel):
    manifest_sha256: str = Field(min_length=64, max_length=64)
    schema_json: dict | None = None
    statistics: dict | None = None
    row_count: int | None = None
    size_bytes: int | None = None


class DatasetVersionOut(BaseModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    version_no: int
    manifest_sha256: str
    status: str
    row_count: int | None
    size_bytes: int | None
    created_at: datetime

    model_config = {"from_attributes": True}
