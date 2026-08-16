"""Topic-candidate endpoints (spec §13.6/§6.4)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, SessionDep, require_project_role
from app.api.errors import NotFoundError, ValidationAppError
from app.db.models import ResearchAction, TopicCandidate, User
from app.domains.audit.service import record_audit
from app.domains.lifecycle.service import LifecycleService

router = APIRouter(tags=["topics"])
require_view = require_project_role("view")
require_edit = require_project_role("edit_content")


def _candidate_out(candidate: TopicCandidate) -> dict:
    return {
        "id": str(candidate.id),
        "title": candidate.title,
        "evidence_strength": float(candidate.evidence_strength) if candidate.evidence_strength else None,
        "status": candidate.status,
        "research_question": candidate.research_question,
        "rationale": candidate.rationale,
    }


@router.get("/projects/{project_id}/topic-candidates")
async def list_candidates(
    project_id: uuid.UUID,
    session: SessionDep,
    _user: User = Depends(require_view),
) -> list[dict]:
    result = await session.execute(
        select(TopicCandidate)
        .where(TopicCandidate.project_id == project_id)
        .order_by(TopicCandidate.evidence_strength.desc().nullslast())
    )
    return [_candidate_out(c) for c in result.scalars().all()]


async def _get(session: AsyncSession, candidate_id: uuid.UUID) -> TopicCandidate:
    candidate = await session.get(TopicCandidate, candidate_id)
    if candidate is None:
        raise NotFoundError("候选不存在")
    return candidate


@router.post("/projects/{project_id}/topic-candidates/{candidate_id}:accept")
async def accept_candidate(
    project_id: uuid.UUID,
    candidate_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> dict:
    candidate = await _get(session, candidate_id)
    if candidate.status == "accepted":
        raise ValidationAppError("候选已被采纳", code="CANDIDATE_ALREADY_ACCEPTED")
    candidate.status = "accepted"
    candidate.accepted_by = user.id
    candidate.accepted_at = datetime.now(UTC)
    candidate.version = int(candidate.version) + 1

    # 选题→进化联动（§6.2/§13.6）：采纳后生成下一步文献调研行动 + 落审计
    session.add(
        ResearchAction(
            project_id=project_id,
            cycle_id=candidate.cycle_id,
            stage_key="literature",
            title=f"围绕选题「{candidate.title}」开展文献调研",
            description=f"采纳选题候选：{candidate.title}",
            status="open",
            priority=1,
            source_type="topic",
        )
    )
    record_audit(
        session,
        action="topic.candidate.accepted",
        actor_id=user.id,
        project_id=project_id,
        target_type="topic_candidate",
        target_id=candidate.id,
        after_redacted={"title": candidate.title},
    )

    # 选题→阶段联动（§6.2）：采纳即推进 topic 阶段（ready→running→completed）
    lifecycle = LifecycleService(session)
    stage = await lifecycle.get_stage(candidate.cycle_id, "topic")
    if stage.status == "ready":
        stage = await lifecycle.start_stage(candidate.cycle_id, "topic", user.id, None)
    if stage.status == "running":
        await lifecycle.complete_stage(
            candidate.cycle_id, "topic", user.id, None, f"采纳选题：{candidate.title}", []
        )

    await session.commit()
    return _candidate_out(candidate)


@router.post("/projects/{project_id}/topic-candidates/{candidate_id}:reject")
async def reject_candidate(
    project_id: uuid.UUID,
    candidate_id: uuid.UUID,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> dict:
    candidate = await _get(session, candidate_id)
    candidate.status = "rejected"
    candidate.version = int(candidate.version) + 1
    await session.commit()
    return _candidate_out(candidate)
