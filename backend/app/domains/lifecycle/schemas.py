"""Lifecycle request/response schemas (spec §12.5)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class StageOut(BaseModel):
    ordinal: int
    stage_key: str
    label_zh: str
    status: str
    progress: float
    evidence_count: int
    blocked_reason: str | None
    version: int
    started_at: datetime | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class StartStageRequest(BaseModel):
    expected_version: int | None = None


class CompleteStageRequest(BaseModel):
    expected_version: int | None = None
    completion_note: str | None = None
    evidence_node_ids: list[uuid.UUID] = Field(default_factory=list)


class BlockStageRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    expected_version: int | None = None


class ReopenStageRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    expected_version: int | None = None
