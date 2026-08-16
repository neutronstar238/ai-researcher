"""Agent schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AgentOut(BaseModel):
    id: uuid.UUID
    key: str
    display_name: str
    description: str | None
    status: str
    active_version_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class TaskCreate(BaseModel):
    agent_version_id: uuid.UUID
    task_type: str = Field(min_length=1, max_length=80)
    input: dict | None = None
    budget: dict | None = None


class TaskOut(BaseModel):
    id: uuid.UUID
    agent_version_id: uuid.UUID
    task_type: str
    status: str
    input: dict | None
    output: dict | None
    error: dict | None
    token_usage: dict | None
    attempt: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ToolCallIn(BaseModel):
    tool_name: str = Field(min_length=1, max_length=160)
    arguments: dict | None = None
    step_id: uuid.UUID | None = None


class ToolCallOut(BaseModel):
    id: uuid.UUID
    tool_name: str
    risk_level: str
    status: str
    approval_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class MemoryWrite(BaseModel):
    agent_id: uuid.UUID
    scope: str = "semantic"
    content: str = Field(min_length=1)
    summary: str | None = None
    source_refs: dict | None = None
    importance: float | None = None
