"""Automatic rollback decisions for strategy gray releases."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from autoresearch.observability import AuditEvent, AuditEventType, AuditLog
from autoresearch.schemas import StrategyCard


class StrategyRollbackStatus(str, Enum):
    """Outcome of a strategy rollback check."""

    NO_ACTION = "no_action"
    ROLLBACK_REQUIRED = "rollback_required"


class StrategyRollbackInput(BaseModel):
    """Signals used to decide whether a strategy must roll back."""

    model_config = ConfigDict(extra="forbid")

    strategy: StrategyCard
    recent_rewards: tuple[float, ...] = ()
    safety_incident: bool = False
    required_negative_rewards: int = Field(default=2, ge=1)
    negative_reward_threshold: float = 0.0


class StrategyRollbackDecision(BaseModel):
    """Auditable rollback decision for a strategy family."""

    model_config = ConfigDict(extra="forbid")

    strategy: StrategyCard
    status: StrategyRollbackStatus
    rollback_required: bool
    rollback_target: str | None
    strategy_family_id: str
    family_frozen: bool
    review_required: bool
    reasons: tuple[str, ...]
    recent_rewards: tuple[float, ...]


def evaluate_strategy_rollback(
    rollback: StrategyRollbackInput,
    *,
    audit_log: AuditLog | None = None,
    actor: str = "strategy-rollback",
    run_id: str | None = None,
    project_id: str | None = None,
    task_id: str | None = None,
) -> StrategyRollbackDecision:
    """Require rollback after repeated negative reward or a safety incident."""

    reasons = _rollback_reasons(rollback)
    rollback_required = bool(reasons)
    strategy = (
        rollback.strategy.model_copy(update={"release_status": "rolled_back"})
        if rollback_required
        else rollback.strategy
    )
    decision = StrategyRollbackDecision(
        strategy=strategy,
        status=StrategyRollbackStatus.ROLLBACK_REQUIRED
        if rollback_required
        else StrategyRollbackStatus.NO_ACTION,
        rollback_required=rollback_required,
        rollback_target=rollback.strategy.rollback_target,
        strategy_family_id=_strategy_family_id(rollback.strategy),
        family_frozen=rollback_required,
        review_required=rollback_required,
        reasons=tuple(reasons) if reasons else ("rollback gates clear",),
        recent_rewards=rollback.recent_rewards,
    )
    if audit_log is not None and decision.rollback_required:
        audit_log.append(
            _audit_event(
                rollback,
                decision,
                actor=actor,
                run_id=run_id,
                project_id=project_id,
                task_id=task_id,
            )
        )
    return decision


def _rollback_reasons(rollback: StrategyRollbackInput) -> list[str]:
    reasons: list[str] = []
    if _has_repeated_negative_rewards(rollback):
        reasons.append("repeated negative strategy reward")
    if rollback.safety_incident:
        reasons.append("safety incident")
    return reasons


def _has_repeated_negative_rewards(rollback: StrategyRollbackInput) -> bool:
    required = rollback.required_negative_rewards
    if len(rollback.recent_rewards) < required:
        return False
    recent = rollback.recent_rewards[-required:]
    return all(value < rollback.negative_reward_threshold for value in recent)


def _strategy_family_id(strategy: StrategyCard) -> str:
    return strategy.rollback_target or strategy.parent_strategy_id or strategy.id


def _audit_event(
    rollback: StrategyRollbackInput,
    decision: StrategyRollbackDecision,
    *,
    actor: str,
    run_id: str | None,
    project_id: str | None,
    task_id: str | None,
) -> AuditEvent:
    return AuditEvent(
        event_type=AuditEventType.ROLLBACK,
        actor=actor,
        action=f"rollback strategy {rollback.strategy.id}",
        resource=rollback.strategy.id,
        run_id=run_id,
        project_id=project_id,
        task_id=task_id,
        metadata={
            "rollback": True,
            "rollback_target": decision.rollback_target,
            "strategy_family_id": decision.strategy_family_id,
            "family_frozen": decision.family_frozen,
            "review_required": decision.review_required,
            "reasons": list(decision.reasons),
            "recent_rewards": list(decision.recent_rewards),
            "safety_incident": rollback.safety_incident,
            "required_negative_rewards": rollback.required_negative_rewards,
            "negative_reward_threshold": rollback.negative_reward_threshold,
            "release_status": decision.strategy.release_status,
        },
    )
