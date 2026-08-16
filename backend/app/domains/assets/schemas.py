"""Asset schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class InitiateUploadRequest(BaseModel):
    original_name: str = Field(min_length=1, max_length=255)
    mime_type: str | None = None
    kind: str = Field(default="other", max_length=20)
    part_count: int = Field(default=1, ge=1, le=10_000)


class UploadPart(BaseModel):
    part_number: int = Field(ge=1, le=10_000)
    etag: str = Field(min_length=1, max_length=255)


class CompleteUploadRequest(BaseModel):
    original_name: str = Field(min_length=1, max_length=255)
    mime_type: str | None = None
    kind: str = Field(default="other", max_length=20)
    object_key: str | None = None
    parts: list[UploadPart] | None = None


class AssetOut(BaseModel):
    id: uuid.UUID
    kind: str
    original_name: str | None
    mime_type: str | None
    size_bytes: int
    sha256: str
    status: str
    scan_status: str = "not_scanned"
    created_at: datetime

    model_config = {"from_attributes": True}
