"""Reflection: deterministic cycle metrics + recommendations (spec §17.5).

复盘报告为不可变 Document（type='reflection'）；建议采纳时创建 research_action。
指标由服务端从真实数据计算，不由 LLM 猜（§28「每一个数字都有查询来源」）。
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, SessionDep, require_project_role
from app.api.errors import NotFoundError, ValidationAppError
from app.db.models import (
    Document,
    DocumentVersion,
    EvidenceNode,
    Experiment,
    ExperimentRun,
    LifecycleStage,
    ResearchAction,
    User,
)

router = APIRouter(tags=["reflection"])
require_view = require_project_role("view")
require_edit = require_project_role("edit_content")


class ReflectionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def compute(self, cycle_id: uuid.UUID) -> dict:
        stages = (
            await self.session.execute(
                select(LifecycleStage).where(LifecycleStage.cycle_id == cycle_id)
            )
        ).scalars().all()
        completed = sum(1 for s in stages if s.status == "completed")
        goal_rate = round(completed / len(stages) * 100, 1) if stages else 0.0

        experiments = (
            await self.session.execute(select(Experiment).where(Experiment.cycle_id == cycle_id))
        ).scalars().all()
        exp_ids = [e.id for e in experiments]
        failed_runs = 0
        if exp_ids:
            runs = (
                await self.session.execute(
                    select(ExperimentRun).where(ExperimentRun.experiment_id.in_(exp_ids))
                )
            ).scalars().all()
            failed_runs = sum(1 for r in runs if r.status == "failed")

        nodes = (
            await self.session.execute(select(EvidenceNode).where(EvidenceNode.cycle_id == cycle_id))
        ).scalars().all()
        contradictions = sum(1 for n in nodes if n.has_unresolved_contradiction)

        return {
            "cycle_id": str(cycle_id),
            "goal_completion_rate": goal_rate,
            "stage_completed": completed,
            "stage_total": len(stages),
            "failed_experiment_runs": failed_runs,
            "evidence_nodes": len(nodes),
            "unresolved_contradictions": contradictions,
            "generated_at": datetime.now(UTC).isoformat(),
        }

    async def recommendations(self, metrics: dict) -> list[dict]:
        recs: list[dict] = []
        if metrics["failed_experiment_runs"] > 0:
            recs.append({"id": "fix-failed-runs", "title": "排查并修复失败实验运行", "reason": f"{metrics['failed_experiment_runs']} 次运行失败"})
        if metrics["unresolved_contradictions"] > 0:
            recs.append({"id": "resolve-contradictions", "title": "处理未解决矛盾证据", "reason": f"{metrics['unresolved_contradictions']} 个未解决矛盾"})
        if metrics["stage_completed"] < metrics["stage_total"]:
            recs.append({"id": "advance-stage", "title": "推进当前生命周期阶段", "reason": "尚有未完成阶段"})
        if not recs:
            recs.append({"id": "next-cycle", "title": "创建下一研究周期", "reason": "当前周期已完成"})
        return recs

    async def run(self, project_id: uuid.UUID, cycle_id: uuid.UUID, created_by: uuid.UUID) -> dict:
        metrics = await self.compute(cycle_id)
        recs = await self.recommendations(metrics)
        markdown = self._render(metrics, recs)
        sha = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        cycle_no = await self._cycle_no(cycle_id)

        document = Document(
            project_id=project_id,
            cycle_id=cycle_id,
            title=f"复盘报告 - 第{cycle_no}周期",
            document_type="reflection",
            created_by=created_by,
        )
        self.session.add(document)
        await self.session.flush()
        version = DocumentVersion(
            document_id=document.id,
            version_no=1,
            content_markdown=markdown,
            structure={"metrics": metrics, "recommendations": recs},
            content_sha256=sha,
            created_by=created_by,
        )
        self.session.add(version)
        await self.session.flush()
        document.current_version_id = version.id
        await self.session.commit()
        return {"document_id": str(document.id), "metrics": metrics, "recommendations": recs}

    async def latest(self, cycle_id: uuid.UUID) -> dict | None:
        doc = (
            await self.session.execute(
                select(Document).where(
                    Document.cycle_id == cycle_id, Document.document_type == "reflection"
                )
            )
        ).scalars().first()
        if doc is None:
            return None
        version = await self.session.get(DocumentVersion, doc.current_version_id)
        return {
            "document_id": str(doc.id),
            "version_id": str(version.id),
            "metrics": (version.structure or {}).get("metrics"),
            "recommendations": (version.structure or {}).get("recommendations", []),
        }

    async def accept_recommendation(
        self, project_id: uuid.UUID, cycle_id: uuid.UUID, rec_id: str, created_by: uuid.UUID
    ) -> dict:
        reflection = await self.latest(cycle_id)
        if reflection is None:
            raise ValidationAppError("尚无复盘报告", code="NO_REFLECTION")
        rec = next((r for r in reflection["recommendations"] if r["id"] == rec_id), None)
        if rec is None:
            raise NotFoundError("建议不存在")
        action = ResearchAction(
            project_id=project_id,
            cycle_id=cycle_id,
            title=rec["title"],
            description=rec["reason"],
            status="open",
            priority=2,
            source_type="reflection",
        )
        self.session.add(action)
        await self.session.commit()
        return {"action_id": str(action.id), "title": action.title}

    async def _cycle_no(self, cycle_id: uuid.UUID) -> int:
        from app.db.models import ResearchCycle

        cycle = await self.session.get(ResearchCycle, cycle_id)
        return cycle.sequence_no if cycle else 0

    @staticmethod
    def _render(metrics: dict, recs: list[dict]) -> str:
        lines = [
            "# 复盘报告",
            "",
            f"- 目标完成率：{metrics['goal_completion_rate']}%",
            f"- 阶段：{metrics['stage_completed']}/{metrics['stage_total']}",
            f"- 失败实验运行：{metrics['failed_experiment_runs']}",
            f"- 证据节点：{metrics['evidence_nodes']}",
            f"- 未解决矛盾：{metrics['unresolved_contradictions']}",
            "",
            "## 建议",
        ]
        for i, rec in enumerate(recs, 1):
            lines.append(f"{i}. {rec['title']}（{rec['reason']}）")
        return "\n".join(lines)


@router.post("/projects/{project_id}/cycles/{cycle_id}/reflection-runs")
async def run_reflection(
    project_id: uuid.UUID,
    cycle_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> dict:
    return await ReflectionService(session).run(project_id, cycle_id, user.id)


@router.get("/projects/{project_id}/cycles/{cycle_id}/reflection")
async def get_reflection(
    project_id: uuid.UUID, cycle_id: uuid.UUID, session: SessionDep, _user: User = Depends(require_view)
) -> dict:
    result = await ReflectionService(session).latest(cycle_id)
    return result if result is not None else {"document_id": None, "metrics": None, "recommendations": []}


@router.post("/projects/{project_id}/cycles/{cycle_id}/reflection/recommendations/{rec_id}:accept")
async def accept_recommendation(
    project_id: uuid.UUID,
    cycle_id: uuid.UUID,
    rec_id: str,
    user: CurrentUser,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> dict:
    return await ReflectionService(session).accept_recommendation(project_id, cycle_id, rec_id, user.id)
