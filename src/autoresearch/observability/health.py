"""Service health and SLA metric reporting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from autoresearch.schemas import ExecutionRun


class ServiceHealthStatus(str, Enum):
    """Overall or per-metric service health state."""

    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class ServiceHealthThresholds:
    """Warning and critical thresholds for SLA-oriented metrics."""

    queue_latency_warning_seconds: float = 300.0
    queue_latency_critical_seconds: float = 900.0
    run_failure_rate_warning: float = 0.2
    run_failure_rate_critical: float = 0.5
    validator_latency_warning_seconds: float = 60.0
    validator_latency_critical_seconds: float = 300.0
    dashboard_age_warning_seconds: float = 300.0
    dashboard_age_critical_seconds: float = 900.0
    scheduler_lag_warning_seconds: float = 300.0
    scheduler_lag_critical_seconds: float = 900.0


@dataclass(frozen=True)
class QueueLatencySample:
    """One queued task latency observation."""

    task_id: str
    queued_at: datetime
    started_at: datetime


@dataclass(frozen=True)
class ValidatorLatencySample:
    """One validator latency observation."""

    run_id: str
    started_at: datetime
    completed_at: datetime


@dataclass(frozen=True)
class SchedulerHealthInput:
    """Observed state for the local scheduler."""

    active: bool
    last_run_at: datetime | None
    failed_run_count: int = 0
    due_task_count: int = 0


@dataclass(frozen=True)
class SlaMetric:
    """One health metric row for reports and machine-readable output."""

    key: str
    label: str
    value: float | None
    unit: str
    status: ServiceHealthStatus
    message: str


@dataclass(frozen=True)
class ServiceHealthReport:
    """Computed health report for operations review."""

    generated_at: datetime
    status: ServiceHealthStatus
    metrics: tuple[SlaMetric, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly health report payload."""

        return {
            "generated_at": self.generated_at.isoformat(),
            "status": self.status.value,
            "metrics": [
                {
                    "key": metric.key,
                    "label": metric.label,
                    "value": metric.value,
                    "unit": metric.unit,
                    "status": metric.status.value,
                    "message": metric.message,
                }
                for metric in self.metrics
            ],
        }


@dataclass(frozen=True)
class ServiceHealthReportArtifact:
    """Written service health report artifact."""

    path: Path
    report_format: str
    report: ServiceHealthReport


def build_service_health_report(
    *,
    queue_samples: tuple[QueueLatencySample, ...] = (),
    runs: tuple[ExecutionRun, ...] = (),
    validator_samples: tuple[ValidatorLatencySample, ...] = (),
    dashboard_path: Path | str | None = None,
    dashboard_generated_at: datetime | None = None,
    scheduler: SchedulerHealthInput | None = None,
    thresholds: ServiceHealthThresholds = ServiceHealthThresholds(),
    generated_at: datetime | None = None,
) -> ServiceHealthReport:
    """Compute queue, run, validator, dashboard, and scheduler health metrics."""

    timestamp = _normalize_datetime(generated_at)
    metrics = (
        _queue_latency_metric(queue_samples, thresholds),
        _run_failure_metric(runs, thresholds),
        _validator_latency_metric(validator_samples, thresholds),
        _dashboard_health_metric(
            dashboard_path,
            dashboard_generated_at,
            thresholds,
            timestamp,
        ),
        _scheduler_health_metric(scheduler, thresholds, timestamp),
    )
    return ServiceHealthReport(
        generated_at=timestamp,
        status=_overall_status(metrics),
        metrics=metrics,
    )


def render_service_health_markdown(
    report: ServiceHealthReport,
    *,
    title: str = "AI-Researcher Service Health",
) -> str:
    """Render a static Markdown health report."""

    lines = [
        f"# {title}",
        "",
        f"- Generated at: `{report.generated_at.isoformat()}`",
        f"- Overall status: `{report.status.value}`",
        "",
        "## SLA Metrics",
        "",
        "| Metric | Value | Unit | Status | Detail |",
        "|---|---:|---|---|---|",
    ]
    for metric in report.metrics:
        lines.append(
            "| "
            f"{metric.label} | "
            f"{_format_value(metric.value)} | "
            f"{metric.unit} | "
            f"{metric.status.value} | "
            f"{metric.message} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def export_service_health_report(
    report: ServiceHealthReport,
    output_path: Path | str,
) -> ServiceHealthReportArtifact:
    """Write a Markdown service health report."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_service_health_markdown(report), encoding="utf-8")
    return ServiceHealthReportArtifact(
        path=path,
        report_format="markdown",
        report=report,
    )


def _queue_latency_metric(
    samples: tuple[QueueLatencySample, ...],
    thresholds: ServiceHealthThresholds,
) -> SlaMetric:
    latency = max((_latency_seconds(sample.queued_at, sample.started_at) for sample in samples), default=0.0)
    status = _threshold_status(
        latency,
        thresholds.queue_latency_warning_seconds,
        thresholds.queue_latency_critical_seconds,
    )
    return SlaMetric(
        key="queue_latency_seconds",
        label="Queue latency",
        value=round(latency, 6),
        unit="seconds",
        status=status,
        message=f"max queue latency from {len(samples)} sample(s)",
    )


def _run_failure_metric(
    runs: tuple[ExecutionRun, ...],
    thresholds: ServiceHealthThresholds,
) -> SlaMetric:
    failures = sum(_run_status_value(run) in {"failed", "timeout"} for run in runs)
    rate = failures / len(runs) if runs else 0.0
    status = _threshold_status(
        rate,
        thresholds.run_failure_rate_warning,
        thresholds.run_failure_rate_critical,
    )
    return SlaMetric(
        key="run_failure_rate",
        label="Run failure rate",
        value=round(rate, 6),
        unit="ratio",
        status=status,
        message=f"{failures} failed or timed out run(s) from {len(runs)} total",
    )


def _validator_latency_metric(
    samples: tuple[ValidatorLatencySample, ...],
    thresholds: ServiceHealthThresholds,
) -> SlaMetric:
    latency = max(
        (
            _latency_seconds(sample.started_at, sample.completed_at)
            for sample in samples
        ),
        default=0.0,
    )
    status = _threshold_status(
        latency,
        thresholds.validator_latency_warning_seconds,
        thresholds.validator_latency_critical_seconds,
    )
    return SlaMetric(
        key="validator_latency_seconds",
        label="Validator latency",
        value=round(latency, 6),
        unit="seconds",
        status=status,
        message=f"max validator latency from {len(samples)} sample(s)",
    )


def _dashboard_health_metric(
    dashboard_path: Path | str | None,
    dashboard_generated_at: datetime | None,
    thresholds: ServiceHealthThresholds,
    now: datetime,
) -> SlaMetric:
    if dashboard_path is None:
        return _missing_metric(
            key="dashboard_health",
            label="Dashboard health",
            message="dashboard artifact path is not configured",
        )

    path = Path(dashboard_path)
    if not path.exists():
        return _missing_metric(
            key="dashboard_health",
            label="Dashboard health",
            message=f"dashboard artifact does not exist: {path}",
        )
    if dashboard_generated_at is None:
        return _missing_metric(
            key="dashboard_health",
            label="Dashboard health",
            message="dashboard generated timestamp is missing",
        )

    age = _latency_seconds(dashboard_generated_at, now)
    status = _threshold_status(
        age,
        thresholds.dashboard_age_warning_seconds,
        thresholds.dashboard_age_critical_seconds,
    )
    return SlaMetric(
        key="dashboard_health",
        label="Dashboard health",
        value=round(age, 6),
        unit="seconds_since_generation",
        status=status,
        message=f"dashboard artifact is present at {path}",
    )


def _scheduler_health_metric(
    scheduler: SchedulerHealthInput | None,
    thresholds: ServiceHealthThresholds,
    now: datetime,
) -> SlaMetric:
    if scheduler is None:
        return _missing_metric(
            key="scheduler_health",
            label="Scheduler health",
            message="scheduler state is not configured",
        )
    if not scheduler.active:
        return _missing_metric(
            key="scheduler_health",
            label="Scheduler health",
            message="scheduler is inactive",
        )
    if scheduler.last_run_at is None:
        return _missing_metric(
            key="scheduler_health",
            label="Scheduler health",
            message="scheduler last run timestamp is missing",
        )

    lag = _latency_seconds(scheduler.last_run_at, now)
    status = _threshold_status(
        lag,
        thresholds.scheduler_lag_warning_seconds,
        thresholds.scheduler_lag_critical_seconds,
    )
    if scheduler.failed_run_count > 0:
        status = _max_status(status, ServiceHealthStatus.WARNING)
    if scheduler.due_task_count > 0:
        status = _max_status(status, ServiceHealthStatus.WARNING)
    return SlaMetric(
        key="scheduler_health",
        label="Scheduler health",
        value=round(lag, 6),
        unit="seconds_since_last_run",
        status=status,
        message=(
            f"{scheduler.failed_run_count} failed scheduler run(s), "
            f"{scheduler.due_task_count} due task(s)"
        ),
    )


def _missing_metric(key: str, label: str, message: str) -> SlaMetric:
    return SlaMetric(
        key=key,
        label=label,
        value=None,
        unit="n/a",
        status=ServiceHealthStatus.CRITICAL,
        message=message,
    )


def _threshold_status(
    value: float,
    warning_threshold: float,
    critical_threshold: float,
) -> ServiceHealthStatus:
    if value >= critical_threshold:
        return ServiceHealthStatus.CRITICAL
    if value >= warning_threshold:
        return ServiceHealthStatus.WARNING
    return ServiceHealthStatus.HEALTHY


def _overall_status(metrics: tuple[SlaMetric, ...]) -> ServiceHealthStatus:
    status = ServiceHealthStatus.HEALTHY
    for metric in metrics:
        status = _max_status(status, metric.status)
    return status


def _max_status(
    left: ServiceHealthStatus,
    right: ServiceHealthStatus,
) -> ServiceHealthStatus:
    order = {
        ServiceHealthStatus.HEALTHY: 0,
        ServiceHealthStatus.WARNING: 1,
        ServiceHealthStatus.CRITICAL: 2,
    }
    return left if order[left] >= order[right] else right


def _latency_seconds(start: datetime, end: datetime) -> float:
    normalized_start = _normalize_datetime(start)
    normalized_end = _normalize_datetime(end)
    return max((normalized_end - normalized_start).total_seconds(), 0.0)


def _normalize_datetime(value: datetime | None) -> datetime:
    timestamp = value or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _run_status_value(run: ExecutionRun) -> str:
    return str(getattr(run.status, "value", run.status)).casefold()


def _format_value(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.6f}"
