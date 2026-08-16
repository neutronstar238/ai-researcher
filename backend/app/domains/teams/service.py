"""Team application service."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import NotFoundError, PermissionDeniedError, ValidationAppError
from app.db.models import Team, TeamMember, User


class TeamService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_teams(self, user_id: uuid.UUID) -> list[Team]:
        result = await self.session.execute(
            select(Team)
            .join(TeamMember, TeamMember.team_id == Team.id)
            .where(TeamMember.user_id == user_id)
        )
        return list(result.scalars().unique().all())

    async def create_team(self, name: str, slug: str, owner_user_id: uuid.UUID) -> Team:
        existing = await self.session.execute(select(Team).where(Team.slug == slug))
        if existing.scalar_one_or_none() is not None:
            raise ValidationAppError("团队 slug 已存在", code="TEAM_SLUG_EXISTS")
        team = Team(name=name, slug=slug, owner_user_id=owner_user_id)
        self.session.add(team)
        await self.session.flush()
        self.session.add(TeamMember(team_id=team.id, user_id=owner_user_id, role="owner"))
        await self.session.commit()
        return team

    async def get_team(self, team_id: uuid.UUID) -> Team:
        team = await self.session.get(Team, team_id)
        if team is None:
            raise NotFoundError("团队不存在")
        return team

    async def add_member(self, team_id: uuid.UUID, user_id: uuid.UUID, role: str) -> TeamMember:
        user = await self.session.get(User, user_id)
        if user is None:
            raise NotFoundError("用户不存在")
        member = TeamMember(team_id=team_id, user_id=user_id, role=role)
        self.session.add(member)
        await self.session.commit()
        return member

    async def update_member(self, team_id: uuid.UUID, user_id: uuid.UUID, role: str) -> None:
        member = await self.session.get(TeamMember, (team_id, user_id))
        if member is None:
            raise NotFoundError("成员不存在")
        member.role = role
        await self.session.commit()

    async def remove_member(self, team_id: uuid.UUID, user_id: uuid.UUID) -> None:
        member = await self.session.get(TeamMember, (team_id, user_id))
        if member is None:
            raise NotFoundError("成员不存在")
        await self.session.delete(member)
        await self.session.commit()

    async def require_owner(self, team_id: uuid.UUID, user_id: uuid.UUID) -> None:
        team = await self.get_team(team_id)
        if team.owner_user_id != user_id:
            raise PermissionDeniedError("仅团队 Owner 可管理成员")

    async def list_members(self, team_id: uuid.UUID) -> list[TeamMember]:
        result = await self.session.execute(
            select(TeamMember).where(TeamMember.team_id == team_id)
        )
        return list(result.scalars().all())

    async def get_member(self, team_id: uuid.UUID, user_id: uuid.UUID) -> TeamMember:
        member = await self.session.get(TeamMember, (team_id, user_id))
        if member is None:
            raise NotFoundError("成员不存在")
        return member
