"""Integration-test isolation: reset the demo seed to a known baseline once per session."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import delete, select, update

from app.db.models import (
    Approval,
    ApprovalDecision,
    AuditLog,
    Citation,
    Document,
    DocumentClaim,
    DocumentVersion,
    EvidenceEdge,
    EvidenceNode,
    Project,
    TopicCandidate,
)
from app.db.session import dispose_engine, get_session_factory
from app.seed import _sid, seed


async def _reset() -> None:
    factory = get_session_factory()
    async with factory() as session:
        project_id = _sid("project:main")

        await session.execute(delete(ApprovalDecision))
        await session.execute(delete(AuditLog).where(AuditLog.project_id == project_id))
        await session.execute(
            update(Approval)
            .where(Approval.project_id == project_id)
            .values(status="pending", decided_at=None)
        )

        candidates = (
            await session.execute(
                select(TopicCandidate).where(TopicCandidate.project_id == project_id)
            )
        ).scalars().all()
        for candidate in candidates:
            strength = float(candidate.evidence_strength or 0)
            candidate.status = "high_priority" if strength >= 90 else "exploring"
            candidate.accepted_at = None
            candidate.accepted_by = None

        # 写作域引用证据节点（RESTRICT），须先删引用再删证据节点
        await session.execute(delete(DocumentClaim))
        await session.execute(delete(Citation))
        await session.execute(delete(DocumentVersion))
        await session.execute(delete(Document))

        await session.execute(delete(EvidenceEdge).where(EvidenceEdge.project_id == project_id))
        await session.execute(delete(EvidenceNode).where(EvidenceNode.project_id == project_id))

        # 清理测试创建的额外项目（按 slug 前缀 isolation-）
        extras = (
            await session.execute(select(Project).where(Project.slug.like("isolation-%")))
        ).scalars().all()
        for extra in extras:
            await session.delete(extra)

        await session.commit()

    # 重新补齐 seed 的 evidence 节点/边（其余幂等跳过）
    async with factory() as session:
        await seed(session)
    await dispose_engine()


@pytest.fixture(scope="session", autouse=True)
def reset_demo_state():
    asyncio.run(_reset())
    yield
