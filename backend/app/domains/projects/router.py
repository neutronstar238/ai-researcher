"""Project and cycle API routes (spec §18.4, authorization per §19.1 fail-closed)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import CurrentUser, SessionDep, require_project_role
from app.db.models import User
from app.domains.projects.dashboard import get_coverage, get_dashboard
from app.domains.projects.schemas import (
    CycleCreate,
    CycleOut,
    ProjectCreate,
    ProjectMemberIn,
    ProjectMemberOut,
    ProjectOut,
    ProjectUpdate,
)
from app.domains.projects.service import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])

require_view = require_project_role("view")
require_edit = require_project_role("edit_content")
require_manage = require_project_role("manage_members")
require_archive = require_project_role("archive_delete")


@router.get("", response_model=list[ProjectOut])
async def list_projects(team_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> list[ProjectOut]:
    projects = await ProjectService(session).list_projects(team_id)
    return [ProjectOut.model_validate(p, from_attributes=True) for p in projects]


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(payload: ProjectCreate, user: CurrentUser, session: SessionDep) -> ProjectOut:
    project = await ProjectService(session).create_project(payload, user.id)
    return ProjectOut.model_validate(project, from_attributes=True)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: uuid.UUID,
    session: SessionDep,
    _user: User = Depends(require_view),
) -> ProjectOut:
    project = await ProjectService(session).get_project(project_id)
    return ProjectOut.model_validate(project, from_attributes=True)


@router.get("/{project_id}/dashboard")
async def get_project_dashboard(
    project_id: uuid.UUID,
    session: SessionDep,
    _user: User = Depends(require_view),
) -> dict:
    return await get_dashboard(session, project_id)


@router.get("/{project_id}/evidence-coverage")
async def get_evidence_coverage(
    project_id: uuid.UUID,
    session: SessionDep,
    cycles: int = Query(default=6, ge=1, le=12),
    _user: User = Depends(require_view),
) -> list[dict]:
    return await get_coverage(session, project_id, cycles)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    session: SessionDep,
    _user: User = Depends(require_edit),
) -> ProjectOut:
    project = await ProjectService(session).update_project(project_id, payload)
    return ProjectOut.model_validate(project, from_attributes=True)


@router.post("/{project_id}:archive", response_model=ProjectOut)
async def archive_project(
    project_id: uuid.UUID, session: SessionDep, user: User = Depends(require_archive)
) -> ProjectOut:
    project = await ProjectService(session).archive_project(project_id, user.id)
    return ProjectOut.model_validate(project, from_attributes=True)


@router.post("/{project_id}:restore", response_model=ProjectOut)
async def restore_project(
    project_id: uuid.UUID, session: SessionDep, user: User = Depends(require_archive)
) -> ProjectOut:
    project = await ProjectService(session).restore_project(project_id, user.id)
    return ProjectOut.model_validate(project, from_attributes=True)


# -- members -----------------------------------------------------------

@router.get("/{project_id}/members", response_model=list[ProjectMemberOut])
async def list_members(
    project_id: uuid.UUID, session: SessionDep, _user: User = Depends(require_view)
) -> list[ProjectMemberOut]:
    members = await ProjectService(session).list_members(project_id)
    return [ProjectMemberOut.model_validate(m, from_attributes=True) for m in members]


@router.post("/{project_id}/members", response_model=ProjectMemberOut, status_code=201)
async def add_member(
    project_id: uuid.UUID,
    payload: ProjectMemberIn,
    session: SessionDep,
    user: User = Depends(require_manage),
) -> ProjectMemberOut:
    member = await ProjectService(session).add_member(project_id, payload.user_id, payload.role, user.id)
    return ProjectMemberOut.model_validate(member, from_attributes=True)


@router.delete("/{project_id}/members/{member_user_id}")
async def remove_member(
    project_id: uuid.UUID,
    member_user_id: uuid.UUID,
    session: SessionDep,
    user: User = Depends(require_manage),
) -> Response:
    await ProjectService(session).remove_member(project_id, member_user_id, user.id)
    return Response(status_code=204)


# -- cycles ------------------------------------------------------------

@router.get("/{project_id}/cycles", response_model=list[CycleOut])
async def list_cycles(
    project_id: uuid.UUID, session: SessionDep, _user: User = Depends(require_view)
) -> list[CycleOut]:
    cycles = await ProjectService(session).list_cycles(project_id)
    return [CycleOut.model_validate(c, from_attributes=True) for c in cycles]


@router.post("/{project_id}/cycles", response_model=CycleOut, status_code=201)
async def create_cycle(
    project_id: uuid.UUID,
    payload: CycleCreate,
    user: CurrentUser,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> CycleOut:
    cycle = await ProjectService(session).create_cycle(project_id, payload.name, payload.objective, user.id)
    return CycleOut.model_validate(cycle, from_attributes=True)


@router.post("/{project_id}/cycles/{cycle_id}:activate", response_model=CycleOut)
async def activate_cycle(
    project_id: uuid.UUID, cycle_id: uuid.UUID, session: SessionDep, _user: User = Depends(require_edit)
) -> CycleOut:
    cycle = await ProjectService(session).activate_cycle(project_id, cycle_id)
    return CycleOut.model_validate(cycle, from_attributes=True)


@router.post("/{project_id}/cycles/{cycle_id}:complete", response_model=CycleOut)
async def complete_cycle(
    project_id: uuid.UUID, cycle_id: uuid.UUID, session: SessionDep, _user: User = Depends(require_edit)
) -> CycleOut:
    cycle = await ProjectService(session).complete_cycle(project_id, cycle_id)
    return CycleOut.model_validate(cycle, from_attributes=True)
