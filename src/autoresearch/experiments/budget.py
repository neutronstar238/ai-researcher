"""Budget-aware execution gates for experiment tasks."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from autoresearch.observability import AuditEvent, AuditEventType, AuditLog
from autoresearch.schemas import CostRecord, ExecutionRun, ExperimentTask


class BudgetGateStatus(str, Enum):
    """Execution decision produced by the budget gate."""

    APPROVED = "approved"
    APPROVAL_REQUIRED = "approval_required"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class BudgetGateConfig:
    """Thresholds for budget-aware execution gating."""

    approval_threshold: float = 0.8
    hard_limit: float = 1.0


@dataclass(frozen=True)
class BudgetGateDecision:
    """Decision returned before continuing or pausing execution."""

    status: BudgetGateStatus
    usage_ratios: dict[str, float]
    reasons: tuple[str, ...]
    approval_required: bool
    pause_required: bool


def evaluate_budget_gate(
    task: ExperimentTask,
    *,
    run: ExecutionRun | None = None,
    usage: Mapping[str, int | float] | None = None,
    config: BudgetGateConfig = BudgetGateConfig(),
    audit_log: AuditLog | None = None,
    actor: str = "budget-gate",
) -> BudgetGateDecision:
    """Evaluate whether an experiment task can continue under its budget."""

    if not 0.0 <= config.approval_threshold <= config.hard_limit:
        msg = "approval_threshold must be between 0 and hard_limit"
        raise ValueError(msg)

    measured_usage = _combined_usage(run, usage)
    ratios = _usage_ratios(task.resource_budget, measured_usage)
    status, reasons = _decision_from_ratios(ratios, config)
    decision = BudgetGateDecision(
        status=status,
        usage_ratios=ratios,
        reasons=reasons,
        approval_required=status is not BudgetGateStatus.APPROVED,
        pause_required=status is not BudgetGateStatus.APPROVED,
    )
    if audit_log is not None:
        audit_log.append(_audit_event(task, decision, config, actor))
    return decision


def _combined_usage(
    run: ExecutionRun | None,
    usage: Mapping[str, int | float] | None,
) -> dict[str, float]:
    combined: dict[str, float] = {}
    if run is not None:
        combined.update(_usage_from_cost_record(run.cost_record))
        combined.update(_numeric_mapping(run.cost_json))
    if usage is not None:
        combined.update(_numeric_mapping(usage))
    return combined


def _usage_from_cost_record(cost: CostRecord | None) -> dict[str, float]:
    if cost is None:
        return {}
    usage = {
        "token_input": cost.token_input,
        "token_output": cost.token_output,
        "cpu_time_seconds": cost.cpu_time_seconds,
        "gpu_hours": cost.gpu_hours,
        "storage_artifact_bytes": cost.storage_artifact_bytes,
        "network_cost_usd_placeholder": cost.network_cost_usd_placeholder,
        "human_approval_count": cost.human_approval_count,
    }
    return _numeric_mapping(usage)


def _numeric_mapping(values: Mapping[str, Any]) -> dict[str, float]:
    numeric: dict[str, float] = {}
    for key, value in values.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            numeric[key] = float(value)
    return numeric


def _usage_ratios(
    budget: Mapping[str, Any],
    usage: Mapping[str, float],
) -> dict[str, float]:
    ratios: dict[str, float] = {}
    for key, limit_value in budget.items():
        if isinstance(limit_value, bool) or not isinstance(limit_value, int | float):
            continue
        limit = float(limit_value)
        if limit <= 0:
            continue
        if key in usage:
            ratios[key] = round(usage[key] / limit, 4)

    if "storage_mb" in budget and "storage_artifact_bytes" in usage:
        storage_limit = budget["storage_mb"]
        if isinstance(storage_limit, int | float) and storage_limit > 0:
            ratios["storage_mb"] = round(
                usage["storage_artifact_bytes"] / (float(storage_limit) * 1024 * 1024),
                4,
            )
    return ratios


def _decision_from_ratios(
    ratios: dict[str, float],
    config: BudgetGateConfig,
) -> tuple[BudgetGateStatus, tuple[str, ...]]:
    if not ratios:
        return BudgetGateStatus.APPROVED, ("no comparable budget usage",)

    blocked = {
        name: ratio
        for name, ratio in ratios.items()
        if ratio >= config.hard_limit
    }
    if blocked:
        return (
            BudgetGateStatus.BLOCKED,
            tuple(f"{name} reached {ratio:.0%} of budget" for name, ratio in sorted(blocked.items())),
        )

    approval = {
        name: ratio
        for name, ratio in ratios.items()
        if ratio >= config.approval_threshold
    }
    if approval:
        return (
            BudgetGateStatus.APPROVAL_REQUIRED,
            tuple(
                f"{name} reached {ratio:.0%} of budget"
                for name, ratio in sorted(approval.items())
            ),
        )

    return BudgetGateStatus.APPROVED, ("budget usage below approval threshold",)


def _audit_event(
    task: ExperimentTask,
    decision: BudgetGateDecision,
    config: BudgetGateConfig,
    actor: str,
) -> AuditEvent:
    return AuditEvent(
        event_type=AuditEventType.APPROVAL_GATE,
        actor=actor,
        action=f"budget gate {decision.status.value}",
        resource=task.name,
        project_id=task.project_id,
        task_id=task.id,
        approved=decision.status is BudgetGateStatus.APPROVED,
        metadata={
            "approval_threshold": config.approval_threshold,
            "hard_limit": config.hard_limit,
            "reasons": list(decision.reasons),
            "usage_ratios": decision.usage_ratios,
        },
    )
