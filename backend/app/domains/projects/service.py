"""Project and research-cycle application service (spec §18.4)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import NotFoundError, ValidationAppError
from app.db.models import Project, ProjectMember, ResearchCycle
from app.domains.audit.service import record_audit
from app.domains.lifecycle.service import LifecycleService
from app.domains.projects.schemas import ProjectCreate, ProjectUpdate


class ProjectService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_projects(self, team_id: uuid.UUID) -> list[Project]:
        result = await self.session.execute(
            select(Project).where(Project.team_id == team_id, Project.archived_at.is_(None))
        )
        return list(result.scalars().all())

    async def create_project(self, payload: ProjectCreate, created_by: uuid.UUID) -> Project:
        existing = await self.session.execute(
            select(Project).where(Project.team_id == payload.team_id, Project.slug == payload.slug)
        )
        if existing.scalar_one_or_none() is not None:
            raise ValidationAppError("项目 slug 已在团队内使用", code="PROJECT_SLUG_EXISTS")
        project = Project(
            team_id=payload.team_id,
            name=payload.name,
            slug=payload.slug,
            description=payload.description,
            research_domain=payload.research_domain,
            objective=payload.objective,
            visibility=payload.visibility,
            created_by=created_by,
        )
        self.session.add(project)
        await self.session.flush()
        self.session.add(
            ProjectMember(project_id=project.id, user_id=created_by, role="owner")
        )
        await self.session.commit()
        return project

    async def get_project(self, project_id: uuid.UUID) -> Project:
        project = await self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("项目不存在")
        return project

    async def update_project(self, project_id: uuid.UUID, payload: ProjectUpdate) -> Project:
        project = await self.get_project(project_id)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(project, field, value)
        project.version = Project.version + 1
        await self.session.commit()
        return project

    async def archive_project(self, project_id: uuid.UUID, actor_id: uuid.UUID) -> Project:
        project = await self.get_project(project_id)
        project.status = "archived"
        project.archived_at = datetime.now(UTC)
        record_audit(
            self.session,
            action="project.archived",
            actor_id=actor_id,
            team_id=project.team_id,
            project_id=project.id,
            target_type="project",
            target_id=project.id,
        )
        await self.session.commit()
        return project

    async def restore_project(self, project_id: uuid.UUID, actor_id: uuid.UUID) -> Project:
        project = await self.get_project(project_id)
        project.status = "active"
        project.archived_at = None
        record_audit(
            self.session,
            action="project.restored",
            actor_id=actor_id,
            team_id=project.team_id,
            project_id=project.id,
            target_type="project",
            target_id=project.id,
        )
        await self.session.commit()
        return project

    # -- cycles --------------------------------------------------------

    async def list_cycles(self, project_id: uuid.UUID) -> list[ResearchCycle]:
        result = await self.session.execute(
            select(ResearchCycle)
            .where(ResearchCycle.project_id == project_id)
            .order_by(ResearchCycle.sequence_no)
        )
        return list(result.scalars().all())

    async def create_cycle(
        self, project_id: uuid.UUID, name: str, objective: str | None, created_by: uuid.UUID
    ) -> ResearchCycle:
        await self.get_project(project_id)
        max_seq = await self.session.execute(
            select(func.max(ResearchCycle.sequence_no)).where(ResearchCycle.project_id == project_id)
        )
        sequence_no = (max_seq.scalar() or 0) + 1
        cycle = ResearchCycle(
            project_id=project_id,
            sequence_no=sequence_no,
            name=name,
            objective=objective,
            created_by=created_by,
        )
        self.session.add(cycle)
        await self.session.flush()
        # 每个周期创建时生成 8 条 lifecycle_stages（spec §12.1）
        await LifecycleService(self.session).initialize_cycle(cycle.id)
        await self.session.commit()
        return cycle

    async def activate_cycle(self, project_id: uuid.UUID, cycle_id: uuid.UUID) -> ResearchCycle:
        project = await self.get_project(project_id)
        cycle = await self.session.get(ResearchCycle, cycle_id)
        if cycle is None or cycle.project_id != project_id:
            raise NotFoundError("周期不存在")
        active = (
            await self.session.execute(
                select(ResearchCycle).where(
                    ResearchCycle.project_id == project_id, ResearchCycle.status == "active"
                )
            )
        ).scalars().all()
        for item in active:
            if item.id != cycle_id:
                item.status = "completed"
                item.completed_at = datetime.now(UTC)
        cycle.status = "active"
        if cycle.started_at is None:
            cycle.started_at = datetime.now(UTC)
        project.current_cycle_id = cycle.id
        await self.session.commit()
        return cycle

    async def complete_cycle(self, project_id: uuid.UUID, cycle_id: uuid.UUID) -> ResearchCycle:
        cycle = await self.session.get(ResearchCycle, cycle_id)
        if cycle is None or cycle.project_id != project_id:
            raise NotFoundError("周期不存在")
        cycle.status = "completed"
        cycle.completed_at = datetime.now(UTC)
        await self.session.commit()
        return cycle

    # -- members -------------------------------------------------------

    async def add_member(
        self, project_id: uuid.UUID, user_id: uuid.UUID, role: str, actor_id: uuid.UUID
    ) -> ProjectMember:
        member = ProjectMember(project_id=project_id, user_id=user_id, role=role)
        self.session.add(member)
        record_audit(
            self.session,
            action="project.member.added",
            actor_id=actor_id,
            project_id=project_id,
            target_type="project_member",
            target_id=user_id,
            after_redacted={"role": role},
        )
        await self.session.commit()
        return member

    async def list_members(self, project_id: uuid.UUID) -> list[ProjectMember]:
        result = await self.session.execute(
            select(ProjectMember).where(ProjectMember.project_id == project_id)
        )
        return list(result.scalars().all())

    async def remove_member(self, project_id: uuid.UUID, user_id: uuid.UUID, actor_id: uuid.UUID) -> None:
        member = await self.session.get(ProjectMember, (project_id, user_id))
        if member is None:
            raise NotFoundError("成员不存在")
        await self.session.delete(member)
        record_audit(
            self.session,
            action="project.member.removed",
            actor_id=actor_id,
            project_id=project_id,
            target_type="project_member",
            target_id=user_id,
        )
        await self.session.commit()
