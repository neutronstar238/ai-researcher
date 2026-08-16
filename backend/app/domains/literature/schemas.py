"""Literature schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    provider: str = "arxiv"
    max_results: int = Field(default=20, ge=1, le=100)


class SearchRunOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    query: str
    provider: str
    status: str
    result: dict | None
    error: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}


class IngestPdfRequest(BaseModel):
    asset_id: uuid.UUID


class PaperResultOut(BaseModel):
    title: str
    doi: str | None = None
    publication_year: int | None = None
    venue: str | None = None
    abstract: str | None = None
    external_id: str | None = None
    source: str


class SavePaperRequest(BaseModel):
    title: str = Field(min_length=1)
    doi: str | None = None
    publication_year: int | None = None
    venue: str | None = None
    abstract: str | None = None
    external_id: str | None = None
    source: str = "manual"


class PaperOut(BaseModel):
    id: uuid.UUID
    title: str
    doi: str | None
    publication_year: int | None
    venue: str | None
    abstract: str | None
    metadata_source: str | None

    model_config = {"from_attributes": True}
