"""Evidence node/edge API routes (spec §7.9)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response

from app.api.deps import CurrentUser, SessionDep, require_project_role
from app.db.models import User
from app.domains.evidence.schemas import (
    EdgeCreate,
    EdgeOut,
    EdgeUpdate,
    NodeCreate,
    NodeOut,
    NodeUpdate,
)
from app.domains.evidence.service import EvidenceService

router = APIRouter(tags=["evidence"])

require_view = require_project_role("view")
require_edit = require_project_role("edit_content")


@router.get("/projects/{project_id}/cycles/{cycle_id}/evidence-graph")
async def evidence_graph(
    project_id: uuid.UUID,
    cycle_id: uuid.UUID,
    session: SessionDep,
    _user: User = Depends(require_view),
) -> dict:
    return await EvidenceService(session).graph(cycle_id)


@router.post("/projects/{project_id}/evidence/nodes", response_model=NodeOut, status_code=201)
async def create_node(
    project_id: uuid.UUID,
    payload: NodeCreate,
    user: CurrentUser,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> NodeOut:
    node = await EvidenceService(session).create_node(project_id, payload, user.id)
    return NodeOut.model_validate(node, from_attributes=True)


@router.get("/projects/{project_id}/evidence/nodes/{node_id}", response_model=NodeOut)
async def get_node(
    project_id: uuid.UUID,
    node_id: uuid.UUID,
    session: SessionDep,
    _user: User = Depends(require_view),
) -> NodeOut:
    node = await EvidenceService(session).get_node(node_id)
    return NodeOut.model_validate(node, from_attributes=True)


@router.patch("/projects/{project_id}/evidence/nodes/{node_id}", response_model=NodeOut)
async def update_node(
    project_id: uuid.UUID,
    node_id: uuid.UUID,
    payload: NodeUpdate,
    user: CurrentUser,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> NodeOut:
    node = await EvidenceService(session).update_node(node_id, payload, user.id)
    return NodeOut.model_validate(node, from_attributes=True)


@router.delete("/projects/{project_id}/evidence/nodes/{node_id}")
async def delete_node(
    project_id: uuid.UUID,
    node_id: uuid.UUID,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> Response:
    await EvidenceService(session).delete_node(node_id)
    return Response(status_code=204)


@router.post("/projects/{project_id}/evidence/edges", response_model=EdgeOut, status_code=201)
async def create_edge(
    project_id: uuid.UUID,
    payload: EdgeCreate,
    user: CurrentUser,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> EdgeOut:
    edge = await EvidenceService(session).create_edge(project_id, payload, user.id)
    return EdgeOut.model_validate(edge, from_attributes=True)


@router.patch("/projects/{project_id}/evidence/edges/{edge_id}", response_model=EdgeOut)
async def update_edge(
    project_id: uuid.UUID,
    edge_id: uuid.UUID,
    payload: EdgeUpdate,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> EdgeOut:
    edge = await EvidenceService(session).update_edge(edge_id, payload)
    return EdgeOut.model_validate(edge, from_attributes=True)


@router.delete("/projects/{project_id}/evidence/edges/{edge_id}")
async def delete_edge(
    project_id: uuid.UUID,
    edge_id: uuid.UUID,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> Response:
    await EvidenceService(session).delete_edge(edge_id)
    return Response(status_code=204)
