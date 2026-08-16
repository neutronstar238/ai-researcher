"""Evidence node/edge schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class NodeCreate(BaseModel):
    cycle_id: uuid.UUID
    node_type: str
    code: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1)
    description: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=100)
    importance: int = Field(default=1, ge=1, le=5)
    metadata: dict | None = None


class NodeUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=100)
    importance: int | None = Field(default=None, ge=1, le=5)


class NodeOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    cycle_id: uuid.UUID
    node_type: str
    code: str
    title: str
    description: str | None
    status: str
    confidence: float | None
    importance: int
    has_unresolved_contradiction: bool
    version: int
    created_at: datetime

    model_config = {"from_attributes": True}


class EdgeCreate(BaseModel):
    cycle_id: uuid.UUID
    source_node_id: uuid.UUID
    target_node_id: uuid.UUID
    relation: str
    stance: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=100)
    rationale: str | None = None


class EdgeUpdate(BaseModel):
    stance: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=100)
    rationale: str | None = None


class EdgeOut(BaseModel):
    id: uuid.UUID
    cycle_id: uuid.UUID
    source_node_id: uuid.UUID
    target_node_id: uuid.UUID
    relation: str
    stance: str | None
    confidence: float | None
    rationale: str | None
    version: int
    created_at: datetime

    model_config = {"from_attributes": True}
