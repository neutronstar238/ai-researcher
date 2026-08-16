"""Team API routes (spec §18.4)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response

from app.api.deps import CurrentUser, SessionDep
from app.domains.teams.schemas import MemberIn, MemberOut, TeamCreate, TeamOut
from app.domains.teams.service import TeamService

router = APIRouter(prefix="/teams", tags=["teams"])


@router.get("", response_model=list[TeamOut])
async def list_teams(user: CurrentUser, session: SessionDep) -> list[TeamOut]:
    teams = await TeamService(session).list_teams(user.id)
    return [TeamOut.model_validate(t, from_attributes=True) for t in teams]


@router.post("", response_model=TeamOut, status_code=201)
async def create_team(payload: TeamCreate, user: CurrentUser, session: SessionDep) -> TeamOut:
    team = await TeamService(session).create_team(payload.name, payload.slug, user.id)
    return TeamOut.model_validate(team, from_attributes=True)


@router.get("/{team_id}/members", response_model=list[MemberOut])
async def list_members(team_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> list[MemberOut]:
    service = TeamService(session)
    await service.require_owner(team_id, user.id)
    members = await service.list_members(team_id)
    return [MemberOut.model_validate(m, from_attributes=True) for m in members]


@router.post("/{team_id}/members", response_model=MemberOut, status_code=201)
async def add_member(
    team_id: uuid.UUID, payload: MemberIn, user: CurrentUser, session: SessionDep
) -> MemberOut:
    service = TeamService(session)
    await service.require_owner(team_id, user.id)
    member = await service.add_member(team_id, payload.user_id, payload.role)
    return MemberOut.model_validate(member, from_attributes=True)


@router.patch("/{team_id}/members/{member_user_id}", response_model=MemberOut)
async def update_member(
    team_id: uuid.UUID, member_user_id: uuid.UUID, payload: MemberIn, user: CurrentUser, session: SessionDep
) -> MemberOut:
    service = TeamService(session)
    await service.require_owner(team_id, user.id)
    await service.update_member(team_id, member_user_id, payload.role)
    member = await service.get_member(team_id, member_user_id)
    return MemberOut.model_validate(member, from_attributes=True)


@router.delete("/{team_id}/members/{member_user_id}")
async def remove_member(
    team_id: uuid.UUID, member_user_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> Response:
    service = TeamService(session)
    await service.require_owner(team_id, user.id)
    await service.remove_member(team_id, member_user_id)
    return Response(status_code=204)
