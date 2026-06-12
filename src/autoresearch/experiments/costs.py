"""Project-level cost management for experiment runs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from autoresearch.schemas import CostRecord, ExecutionRun

BYTES_PER_GIB = 1024**3


class CostAlertStatus(str, Enum):
    """Severity for project cost budget evaluation."""

    OK = "ok"
    ALERT = "alert"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class CostUnitPrices:
    """Unit prices used when a run does not provide explicit cost totals."""

    input_token_usd_per_1k: float = 0.0
    output_token_usd_per_1k: float = 0.0
    gpu_hour_usd: float = 0.0
    storage_gib_usd: float = 0.0


@dataclass(frozen=True)
class ProjectBudget:
    """Project-level limits for cost monitoring."""

    project_id: str
    max_total_cost_usd: float
    max_gpu_hours: float = 0.0
    max_api_token_cost_usd: float = 0.0
    max_storage_cost_usd: float = 0.0
    alert_threshold: float = 0.8
    hard_limit: float = 1.0


@dataclass(frozen=True)
class ProjectCostUsage:
    """Aggregated cost usage for one project."""

    project_id: str
    run_count: int
    total_cost_usd: float
    api_token_cost_usd: float
    gpu_cost_usd: float
    gpu_hours: float
    storage_cost_usd: float
    storage_artifact_bytes: int
    token_input: int
    token_output: int
    other_cost_usd: float = 0.0


@dataclass(frozen=True)
class CostAlert:
    """A budget threshold crossing for one cost metric."""

    metric: str
    status: CostAlertStatus
    ratio: float
    usage: float
    limit: float
    message: str


@dataclass(frozen=True)
class ProjectCostReport:
    """Cost usage and threshold alerts for one project."""

    project_id: str
    status: CostAlertStatus
    usage: ProjectCostUsage
    alerts: tuple[CostAlert, ...]


def evaluate_project_costs(
    runs: Iterable[ExecutionRun],
    budget: ProjectBudget,
    *,
    prices: CostUnitPrices = CostUnitPrices(),
) -> ProjectCostReport:
    """Aggregate run costs and emit project budget alerts."""

    _validate_budget(budget)
    usage = _aggregate_usage(runs, budget.project_id, prices)
    alerts = _cost_alerts(usage, budget)
    return ProjectCostReport(
        project_id=budget.project_id,
        status=_overall_status(alerts),
        usage=usage,
        alerts=alerts,
    )


def _validate_budget(budget: ProjectBudget) -> None:
    if budget.max_total_cost_usd < 0:
        msg = "max_total_cost_usd must be non-negative"
        raise ValueError(msg)
    if budget.max_gpu_hours < 0:
        msg = "max_gpu_hours must be non-negative"
        raise ValueError(msg)
    if budget.max_api_token_cost_usd < 0:
        msg = "max_api_token_cost_usd must be non-negative"
        raise ValueError(msg)
    if budget.max_storage_cost_usd < 0:
        msg = "max_storage_cost_usd must be non-negative"
        raise ValueError(msg)
    if not 0.0 <= budget.alert_threshold <= budget.hard_limit:
        msg = "alert_threshold must be between 0 and hard_limit"
        raise ValueError(msg)


def _aggregate_usage(
    runs: Iterable[ExecutionRun],
    project_id: str,
    prices: CostUnitPrices,
) -> ProjectCostUsage:
    usage = _MutableCostUsage(project_id=project_id)
    for run in runs:
        if run.project_id != project_id:
            continue
        usage.add(_run_usage(run, prices))
    return usage.freeze()


@dataclass
class _MutableCostUsage:
    project_id: str
    run_count: int = 0
    total_cost_usd: float = 0.0
    api_token_cost_usd: float = 0.0
    gpu_cost_usd: float = 0.0
    gpu_hours: float = 0.0
    storage_cost_usd: float = 0.0
    storage_artifact_bytes: int = 0
    token_input: int = 0
    token_output: int = 0
    other_cost_usd: float = 0.0

    def add(self, usage: ProjectCostUsage) -> None:
        self.run_count += usage.run_count
        self.total_cost_usd += usage.total_cost_usd
        self.api_token_cost_usd += usage.api_token_cost_usd
        self.gpu_cost_usd += usage.gpu_cost_usd
        self.gpu_hours += usage.gpu_hours
        self.storage_cost_usd += usage.storage_cost_usd
        self.storage_artifact_bytes += usage.storage_artifact_bytes
        self.token_input += usage.token_input
        self.token_output += usage.token_output
        self.other_cost_usd += usage.other_cost_usd

    def freeze(self) -> ProjectCostUsage:
        return ProjectCostUsage(
            project_id=self.project_id,
            run_count=self.run_count,
            total_cost_usd=round(self.total_cost_usd, 6),
            api_token_cost_usd=round(self.api_token_cost_usd, 6),
            gpu_cost_usd=round(self.gpu_cost_usd, 6),
            gpu_hours=round(self.gpu_hours, 6),
            storage_cost_usd=round(self.storage_cost_usd, 6),
            storage_artifact_bytes=self.storage_artifact_bytes,
            token_input=self.token_input,
            token_output=self.token_output,
            other_cost_usd=round(self.other_cost_usd, 6),
        )


def _run_usage(run: ExecutionRun, prices: CostUnitPrices) -> ProjectCostUsage:
    cost_json = _numeric_mapping(run.cost_json)
    cost_record = run.cost_record
    token_input = _int_cost_value(
        cost_json,
        ("token_input", "input_tokens", "prompt_tokens"),
        _record_value(cost_record, "token_input"),
    )
    token_output = _int_cost_value(
        cost_json,
        ("token_output", "output_tokens", "completion_tokens"),
        _record_value(cost_record, "token_output"),
    )
    api_token_cost = _first_cost_value(
        cost_json,
        ("api_token_cost_usd", "token_cost_usd", "llm_cost_usd"),
    )
    if api_token_cost is None:
        api_token_cost = (
            (token_input / 1000.0 * prices.input_token_usd_per_1k)
            + (token_output / 1000.0 * prices.output_token_usd_per_1k)
        )

    gpu_hours = _first_cost_value(cost_json, ("gpu_hours",))
    if gpu_hours is None:
        gpu_hours = _record_value(cost_record, "gpu_hours")
    gpu_cost = _first_cost_value(cost_json, ("gpu_cost_usd",))
    if gpu_cost is None:
        gpu_cost = gpu_hours * prices.gpu_hour_usd

    storage_bytes = _int_cost_value(
        cost_json,
        ("storage_artifact_bytes", "artifact_storage_bytes"),
        _record_value(cost_record, "storage_artifact_bytes"),
    )
    storage_cost = _first_cost_value(cost_json, ("storage_cost_usd",))
    if storage_cost is None:
        storage_cost = (storage_bytes / BYTES_PER_GIB) * prices.storage_gib_usd

    other_cost = _first_cost_value(cost_json, ("other_cost_usd", "network_cost_usd"))
    if other_cost is None:
        other_cost = _record_value(cost_record, "network_cost_usd_placeholder")

    explicit_total = _first_cost_value(
        cost_json,
        ("total_cost_usd", "total_cost", "cost_usd"),
    )
    total_cost = explicit_total
    if total_cost is None:
        total_cost = api_token_cost + gpu_cost + storage_cost + other_cost

    return ProjectCostUsage(
        project_id=run.project_id,
        run_count=1,
        total_cost_usd=round(total_cost, 6),
        api_token_cost_usd=round(api_token_cost, 6),
        gpu_cost_usd=round(gpu_cost, 6),
        gpu_hours=round(gpu_hours, 6),
        storage_cost_usd=round(storage_cost, 6),
        storage_artifact_bytes=storage_bytes,
        token_input=token_input,
        token_output=token_output,
        other_cost_usd=round(other_cost, 6),
    )


def _cost_alerts(
    usage: ProjectCostUsage,
    budget: ProjectBudget,
) -> tuple[CostAlert, ...]:
    checks = {
        "total_cost_usd": (usage.total_cost_usd, budget.max_total_cost_usd),
        "gpu_hours": (usage.gpu_hours, budget.max_gpu_hours),
        "api_token_cost_usd": (
            usage.api_token_cost_usd,
            budget.max_api_token_cost_usd,
        ),
        "storage_cost_usd": (usage.storage_cost_usd, budget.max_storage_cost_usd),
    }
    alerts: list[CostAlert] = []
    for metric, (current_usage, limit) in checks.items():
        if limit <= 0:
            continue
        ratio = current_usage / limit
        status = _status_for_ratio(ratio, budget)
        if status is CostAlertStatus.OK:
            continue
        alerts.append(
            CostAlert(
                metric=metric,
                status=status,
                ratio=round(ratio, 6),
                usage=round(current_usage, 6),
                limit=limit,
                message=f"{metric} reached {ratio:.0%} of budget",
            )
        )
    return tuple(alerts)


def _status_for_ratio(ratio: float, budget: ProjectBudget) -> CostAlertStatus:
    if ratio >= budget.hard_limit:
        return CostAlertStatus.BLOCKED
    if ratio >= budget.alert_threshold:
        return CostAlertStatus.ALERT
    return CostAlertStatus.OK


def _overall_status(alerts: tuple[CostAlert, ...]) -> CostAlertStatus:
    if any(alert.status is CostAlertStatus.BLOCKED for alert in alerts):
        return CostAlertStatus.BLOCKED
    if any(alert.status is CostAlertStatus.ALERT for alert in alerts):
        return CostAlertStatus.ALERT
    return CostAlertStatus.OK


def _numeric_mapping(values: Mapping[str, Any]) -> dict[str, float]:
    numeric: dict[str, float] = {}
    for key, value in values.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            numeric[key] = float(value)
    return numeric


def _first_cost_value(
    values: Mapping[str, float],
    keys: tuple[str, ...],
) -> float | None:
    for key in keys:
        if key in values:
            return values[key]
    return None


def _int_cost_value(
    values: Mapping[str, float],
    keys: tuple[str, ...],
    fallback: float,
) -> int:
    value = _first_cost_value(values, keys)
    if value is None:
        value = fallback
    return int(value)


def _record_value(cost_record: CostRecord | None, attr: str) -> float:
    if cost_record is None:
        return 0.0
    value = getattr(cost_record, attr)
    return float(value)
