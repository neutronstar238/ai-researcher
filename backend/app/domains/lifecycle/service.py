"""Lifecycle application service (spec §12).

The 8-stage state machine is server-side: every transition validates the legal
transition table, records a ``stage_transition_events`` row, and bumps the
optimistic-lock ``version``. Completing a stage runs the exit gate and blocks on
missing conditions instead of silently passing.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError, NotFoundError, ValidationAppError, VersionConflictError
from app.core.lifecycle import (
    STAGE_LABELS_ZH,
    STAGE_ORDER,
    gate_missing,
    is_allowed_transition,
    next_stage,
)
from app.db.models import LifecycleStage, Project, ResearchCycle, StageTransitionEvent
from app.domains.audit.service import record_audit


class LifecycleService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- initialization --------------------------------------------------

    async def initialize_cycle(self, cycle_id: uuid.UUID) -> list[LifecycleStage]:
        stages: list[LifecycleStage] = []
        for index, key in enumerate(STAGE_ORDER):
            stage = LifecycleStage(
                cycle_id=cycle_id,
                stage_key=key,
                ordinal=index + 1,
                status="ready" if index == 0 else "pending",
            )
            self.session.add(stage)
            stages.append(stage)
        await self.session.flush()
        return stages

    # -- queries ---------------------------------------------------------

    async def list_stages(self, cycle_id: uuid.UUID) -> list[LifecycleStage]:
        result = await self.session.execute(
            select(LifecycleStage)
            .where(LifecycleStage.cycle_id == cycle_id)
            .order_by(LifecycleStage.ordinal)
        )
        return list(result.scalars().all())

    async def get_stage(self, cycle_id: uuid.UUID, stage_key: str) -> LifecycleStage:
        result = await self.session.execute(
            select(LifecycleStage).where(
                LifecycleStage.cycle_id == cycle_id, LifecycleStage.stage_key == stage_key
            )
        )
        stage = result.scalar_one_or_none()
        if stage is None:
            raise NotFoundError("阶段不存在")
        return stage

    # -- transitions -----------------------------------------------------

    async def start_stage(
        self, cycle_id: uuid.UUID, stage_key: str, actor_id: uuid.UUID, expected_version: int | None
    ) -> LifecycleStage:
        stage = await self.get_stage(cycle_id, stage_key)
        self._check_version(stage, expected_version)
        self._assert_transition(stage, "running")
        stage.status = "running"
        if stage.started_at is None:
            stage.started_at = datetime.now(UTC)
        stage.progress = 0
        await self._commit_transition(stage, "ready", "running", actor_id)
        return stage

    async def complete_stage(
        self,
        cycle_id: uuid.UUID,
        stage_key: str,
        actor_id: uuid.UUID,
        expected_version: int | None,
        completion_note: str | None,
        evidence_node_ids: list[uuid.UUID],
    ) -> LifecycleStage:
        stage = await self.get_stage(cycle_id, stage_key)
        self._check_version(stage, expected_version)
        self._assert_transition(stage, "completed")

        missing = gate_missing(stage_key, stage.evidence_count)
        if missing:
            raise ValidationAppError(
                "阶段尚未满足完成条件",
                code="STAGE_GATE_FAILED",
                details={"missing": missing, "stage_key": stage_key},
            )

        from_status = stage.status
        stage.status = "completed"
        stage.progress = 100
        stage.completed_at = datetime.now(UTC)
        stage.gate_snapshot = {
            "passed": True,
            "completion_note": completion_note,
            "evidence_node_ids": [str(node) for node in evidence_node_ids],
        }
        await self._commit_transition(stage, from_status, "completed", actor_id)
        cycle = await self.session.get(ResearchCycle, cycle_id)
        if cycle is not None:
            project = await self.session.get(Project, cycle.project_id)
            record_audit(
                self.session,
                action="lifecycle.stage.completed",
                actor_id=actor_id,
                project_id=cycle.project_id,
                team_id=project.team_id if project else None,
                target_type="stage",
                target_id=stage.id,
                after_redacted={"stage_key": stage_key},
            )
        await self._unlock_next(cycle_id, stage_key)
        return stage

    async def block_stage(
        self, cycle_id: uuid.UUID, stage_key: str, actor_id: uuid.UUID, reason: str
    ) -> LifecycleStage:
        stage = await self.get_stage(cycle_id, stage_key)
        self._assert_transition(stage, "blocked")
        from_status = stage.status
        stage.status = "blocked"
        stage.blocked_reason = reason
        await self._commit_transition(stage, from_status, "blocked", actor_id, reason)
        return stage

    async def resume_stage(
        self, cycle_id: uuid.UUID, stage_key: str, actor_id: uuid.UUID
    ) -> LifecycleStage:
        stage = await self.get_stage(cycle_id, stage_key)
        self._assert_transition(stage, "running")
        from_status = stage.status
        stage.status = "running"
        stage.blocked_reason = None
        await self._commit_transition(stage, from_status, "running", actor_id)
        return stage

    async def reopen_stage(
        self, cycle_id: uuid.UUID, stage_key: str, actor_id: uuid.UUID, reason: str
    ) -> LifecycleStage:
        stage = await self.get_stage(cycle_id, stage_key)
        self._assert_transition(stage, "running")
        stage.status = "running"
        stage.completed_at = None
        stage.version = int(stage.version) + 1
        await self._commit_transition(stage, "completed", "running", actor_id, reason)
        # 重开使依赖此结果的下游进入 blocked（spec §12.2）
        downstream = next_stage(stage.stage_key)  # type: ignore[arg-type]
        if downstream:
            next_row = await self.get_stage(cycle_id, downstream)
            if next_row.status in {"ready", "running", "completed"}:
                next_row.status = "blocked"
                next_row.blocked_reason = f"上游阶段 {stage_key} 被重开"
        await self.session.commit()
        return stage

    # -- internals -------------------------------------------------------

    def _assert_transition(self, stage: LifecycleStage, target: str) -> None:
        if not is_allowed_transition(stage.status, target):
            raise AppError(
                f"阶段 {stage.stage_key} 不允许从 {stage.status} 转换到 {target}",
                code="ILLEGAL_STAGE_TRANSITION",
                status_code=409,
            )

    @staticmethod
    def _check_version(stage: LifecycleStage, expected_version: int | None) -> None:
        if expected_version is not None and expected_version != int(stage.version):
            raise VersionConflictError("阶段已被其他操作更新", details={"current_version": int(stage.version)})

    async def _commit_transition(
        self,
        stage: LifecycleStage,
        from_status: str,
        to_status: str,
        actor_id: uuid.UUID,
        reason: str | None = None,
    ) -> None:
        self.session.add(
            StageTransitionEvent(
                stage_id=stage.id,
                from_status=from_status,
                to_status=to_status,
                reason=reason,
                actor_user_id=actor_id,
            )
        )
        stage.version = int(stage.version) + 1
        await self.session.flush()

    async def _unlock_next(self, cycle_id: uuid.UUID, stage_key: str) -> None:
        downstream = next_stage(stage_key)  # type: ignore[arg-type]
        if downstream is None:
            return
        next_row = await self.get_stage(cycle_id, downstream)
        if next_row.status == "pending":
            next_row.status = "ready"
        await self.session.commit()


def stage_to_out(stage: LifecycleStage) -> dict:
    return {
        "ordinal": stage.ordinal,
        "stage_key": stage.stage_key,
        "label_zh": STAGE_LABELS_ZH.get(stage.stage_key, stage.stage_key),
        "status": stage.status,
        "progress": float(stage.progress),
        "evidence_count": stage.evidence_count,
        "blocked_reason": stage.blocked_reason,
        "version": int(stage.version),
        "started_at": stage.started_at,
        "completed_at": stage.completed_at,
    }
