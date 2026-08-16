"""Project and research-cycle schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    team_id: uuid.UUID
    name: str = Field(min_length=1, max_length=240)
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]+$")
    description: str | None = None
    research_domain: str | None = None
    objective: str | None = None
    visibility: str = "team"


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = None
    research_domain: str | None = None
    objective: str | None = None
    visibility: str | None = None


class ProjectOut(BaseModel):
    id: uuid.UUID
    team_id: uuid.UUID
    name: str
    slug: str
    description: str | None
    research_domain: str | None
    objective: str | None
    status: str
    current_cycle_id: uuid.UUID | None
    visibility: str
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    version: int

    model_config = {"from_attributes": True}


class ProjectMemberIn(BaseModel):
    user_id: uuid.UUID
    role: str = Field(pattern=r"^(owner|researcher|reviewer|guest)$")


class ProjectMemberOut(BaseModel):
    project_id: uuid.UUID
    user_id: uuid.UUID
    role: str

    model_config = {"from_attributes": True}


class CycleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    objective: str | None = None


class CycleOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    sequence_no: int
    name: str
    objective: str | None
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    version: int

    model_config = {"from_attributes": True}
