"""Approval schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ApprovalOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    approval_type: str
    subject_type: str | None
    status: str
    risk_level: str
    request_reason: str | None
    requested_by: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class ApproveRequest(BaseModel):
    comment: str | None = None


class RejectRequest(BaseModel):
    comment: str = Field(min_length=1, max_length=2000)
