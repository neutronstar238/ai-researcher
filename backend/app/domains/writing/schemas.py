"""Writing schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class DocumentCreate(BaseModel):
    cycle_id: uuid.UUID
    title: str = Field(min_length=1)
    document_type: str = "manuscript"


class DocumentOut(BaseModel):
    id: uuid.UUID
    title: str
    document_type: str
    status: str
    current_version_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class VersionCreate(BaseModel):
    content_markdown: str = Field(min_length=1)
    change_summary: str | None = None


class VersionOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    version_no: int
    content_sha256: str
    change_summary: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ClaimLink(BaseModel):
    evidence_node_id: uuid.UUID
    anchor: dict | None = None
    support_status: str = "supports"


class CitationCreate(BaseModel):
    paper_id: uuid.UUID
    citation_key: str = Field(min_length=1, max_length=80)
    style_data: dict | None = None
    anchors: dict | None = None


class CitationOut(BaseModel):
    id: uuid.UUID
    citation_key: str
    paper_id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class SuggestionCreate(BaseModel):
    base_version_id: uuid.UUID
    proposed_markdown: str = Field(min_length=1)
    target_section_key: str | None = Field(default=None, max_length=120)
    agent_task_id: uuid.UUID | None = None


class SuggestionOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    base_version_id: uuid.UUID
    target_section_key: str | None
    status: str
    patch: dict | None
    rendered_preview: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
