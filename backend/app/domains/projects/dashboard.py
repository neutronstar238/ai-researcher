"""Dashboard aggregation (spec §6.8/§6.3)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Asset,
    CycleCoverageSnapshot,
    Dataset,
    Experiment,
    ExperimentRun,
    Project,
    ResearchAction,
)
from app.domains.lifecycle.service import LifecycleService, stage_to_out
from app.domains.literature.service import LiteratureService


def _current_stage(stages: list) -> dict | None:
    for stage in stages:
        if stage.status in {"running", "waiting_approval", "blocked", "ready"}:
            return stage
    return stages[-1] if stages else None


def _progress_percent(current: dict | None, all_completed: bool) -> float:
    if current is None:
        return 100.0 if all_completed else 0.0
    if current.status == "completed":
        return 100.0
    return float(current.progress)


async def get_dashboard(session: AsyncSession, project_id: uuid.UUID) -> dict:
    project = await session.get(Project, project_id)
    if project is None:
        from app.api.errors import NotFoundError

        raise NotFoundError("项目不存在")

    stages = await LifecycleService(session).list_stages(project.current_cycle_id) if project.current_cycle_id else []
    stage_outs = [stage_to_out(stage) for stage in stages]
    current = _current_stage(stages)
    all_completed = bool(stages) and all(stage.status == "completed" for stage in stages)

    next_action: dict | None = None
    if project.current_cycle_id:
        action = (
            await session.execute(
                select(ResearchAction)
                .where(
                    ResearchAction.cycle_id == project.current_cycle_id,
                    ResearchAction.status == "open",
                )
                .order_by(ResearchAction.priority, ResearchAction.due_at)
                .limit(1)
            )
        ).scalar_one_or_none()
        if action:
            next_action = {"id": str(action.id), "title": action.title, "stage_key": action.stage_key}

    statistics = await _statistics(session, project_id)

    return {
        "project": {
            "id": str(project.id),
            "name": project.name,
            "current_cycle_id": str(project.current_cycle_id) if project.current_cycle_id else None,
            "current_stage": current.stage_key if current else None,
            "progress_percent": _progress_percent(current, all_completed),
            "next_action": next_action,
            "research_domain": project.research_domain,
            "objective": project.objective,
            "status": project.status,
        },
        # 六卡片统计全部来自真实 COUNT（§28「每一个数字都有查询来源」）
        "statistics": statistics,
        "lifecycle": stage_outs,
        "updated_at": datetime.now(UTC).isoformat(),
    }


async def _statistics(session: AsyncSession, project_id: uuid.UUID) -> dict:
    experiment_runs = await session.scalar(
        select(func.count(ExperimentRun.id))
        .join(Experiment, Experiment.id == ExperimentRun.experiment_id)
        .where(Experiment.project_id == project_id)
    )
    datasets = await session.scalar(
        select(func.count(Dataset.id)).where(
            Dataset.project_id == project_id, Dataset.archived_at.is_(None)
        )
    )
    figures = await session.scalar(
        select(func.count(Asset.id)).where(
            Asset.project_id == project_id,
            Asset.kind.in_(["figure", "chart"]),
            Asset.archived_at.is_(None),
        )
    )
    return {
        "papers": await LiteratureService(session).paper_count(project_id),
        "experiment_runs": int(experiment_runs or 0),
        "datasets": int(datasets or 0),
        "figures": int(figures or 0),
    }


async def get_coverage(session: AsyncSession, project_id: uuid.UUID, cycles: int = 6) -> list[dict]:
    """Historical evidence-coverage trend (spec §6.5). 无快照时返回空列表而非 0%。"""
    result = await session.execute(
        select(CycleCoverageSnapshot)
        .where(CycleCoverageSnapshot.project_id == project_id)
        .order_by(CycleCoverageSnapshot.period_index)
        .limit(cycles)
    )
    return [
        {"label": snapshot.label, "coverage": float(snapshot.coverage)}
        for snapshot in result.scalars().all()
    ]
