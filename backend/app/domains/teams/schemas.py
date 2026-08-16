"""Team schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]+$")


class TeamOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    owner_user_id: uuid.UUID
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MemberIn(BaseModel):
    user_id: uuid.UUID
    role: str = Field(pattern=r"^(owner|admin|member)$")


class MemberOut(BaseModel):
    team_id: uuid.UUID
    user_id: uuid.UUID
    role: str
