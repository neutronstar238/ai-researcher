"""Vector schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class StoreRequest(BaseModel):
    text: str = Field(min_length=1)
    paper_id: str | None = None


class StoreResponse(BaseModel):
    chunk_id: str
    embedding_model: str
    dimension: int


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)


class Hit(BaseModel):
    id: str
    paper_id: str | None
    score: float


class SearchResponse(BaseModel):
    query: str
    hits: list[Hit]
