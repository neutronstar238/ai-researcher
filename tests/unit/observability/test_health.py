from datetime import datetime, timedelta, timezone

from autoresearch.observability import (
    QueueLatencySample,
    SchedulerHealthInput,
    ServiceHealthStatus,
    ValidatorLatencySample,
    build_service_health_report,
    export_service_health_report,
    render_service_health_markdown,
)
from autoresearch.schemas import ExecutionRun, ExecutionStatus


def test_service_health_report_includes_required_sla_metrics(tmp_path) -> None:
    now = datetime(2026, 6, 12, 6, 0, tzinfo=timezone.utc)
    dashboard_path = tmp_path / "dashboard.html"
    dashboard_path.write_text("<html>ok</html>", encoding="utf-8")

    report = build_service_health_report(
        queue_samples=(
            QueueLatencySample(
                task_id="task-1",
                queued_at=now - timedelta(seconds=180),
                started_at=now - timedelta(seconds=60),
            ),
        ),
        runs=(
            ExecutionRun(
                project_id="project-001",
                task_id="task-1",
                status=ExecutionStatus.SUCCESS,
            ),
            ExecutionRun(
                project_id="project-001",
                task_id="task-2",
                status=ExecutionStatus.FAILED,
            ),
            ExecutionRun(
                project_id="project-001",
                task_id="task-3",
                status=ExecutionStatus.SUCCESS,
            ),
        ),
        validator_samples=(
            ValidatorLatencySample(
                run_id="run-1",
                started_at=now - timedelta(seconds=45),
                completed_at=now - timedelta(seconds=15),
            ),
        ),
        dashboard_path=dashboard_path,
        dashboard_generated_at=now - timedelta(seconds=30),
        scheduler=SchedulerHealthInput(
            active=True,
            last_run_at=now - timedelta(seconds=90),
        ),
        generated_at=now,
    )

    metrics = {metric.key: metric for metric in report.metrics}
    assert set(metrics) == {
        "queue_latency_seconds",
        "run_failure_rate",
        "validator_latency_seconds",
        "dashboard_health",
        "scheduler_health",
    }
    assert report.status is ServiceHealthStatus.WARNING
    assert metrics["queue_latency_seconds"].value == 120.0
    assert metrics["run_failure_rate"].status is ServiceHealthStatus.WARNING
    assert metrics["run_failure_rate"].value == 0.333333
    assert metrics["validator_latency_seconds"].value == 30.0
    assert metrics["dashboard_health"].status is ServiceHealthStatus.HEALTHY
    assert metrics["scheduler_health"].status is ServiceHealthStatus.HEALTHY

    markdown = render_service_health_markdown(report)
    assert "Queue latency" in markdown
    assert "Run failure rate" in markdown
    assert "Validator latency" in markdown
    assert "Dashboard health" in markdown
    assert "Scheduler health" in markdown

    artifact = export_service_health_report(report, tmp_path / "health.md")
    assert artifact.path.read_text(encoding="utf-8") == markdown


def test_service_health_report_marks_missing_dashboard_and_scheduler_critical() -> None:
    now = datetime(2026, 6, 12, 6, 0, tzinfo=timezone.utc)

    report = build_service_health_report(generated_at=now)

    metrics = {metric.key: metric for metric in report.metrics}
    assert report.status is ServiceHealthStatus.CRITICAL
    assert metrics["dashboard_health"].status is ServiceHealthStatus.CRITICAL
    assert metrics["dashboard_health"].value is None
    assert metrics["scheduler_health"].status is ServiceHealthStatus.CRITICAL
    assert metrics["scheduler_health"].value is None
    assert report.to_dict()["status"] == "critical"
