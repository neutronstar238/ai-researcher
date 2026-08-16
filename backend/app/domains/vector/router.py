"""Vector API routes (spec §13.4)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.api.deps import SessionDep, require_project_role
from app.db.models import User
from app.domains.vector.schemas import (
    Hit,
    SearchRequest,
    SearchResponse,
    StoreRequest,
    StoreResponse,
)
from app.domains.vector.service import VectorService

router = APIRouter(tags=["vector"])

require_view = require_project_role("view")
require_edit = require_project_role("edit_content")


@router.post("/projects/{project_id}/vector/store", response_model=StoreResponse, status_code=201)
async def store_vector(
    project_id: uuid.UUID,
    payload: StoreRequest,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> StoreResponse:
    result = VectorService().store(project_id, payload.text, payload.paper_id)
    return StoreResponse(**result)


@router.post("/projects/{project_id}/vector/search", response_model=SearchResponse)
async def search_vector(
    project_id: uuid.UUID,
    payload: SearchRequest,
    session: SessionDep,
    _user: User = Depends(require_view),
) -> SearchResponse:
    hits = VectorService().search(project_id, payload.query, payload.top_k)
    return SearchResponse(query=payload.query, hits=[Hit(**h) for h in hits])
