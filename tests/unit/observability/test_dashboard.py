from datetime import datetime, timezone

from autoresearch.observability import (
    ProjectStatusSummary,
    SystemMetricSnapshot,
    export_local_status_report,
)


def test_export_local_status_report_renders_markdown_without_services(tmp_path) -> None:
    metrics = SystemMetricSnapshot(
        task_success_rate=0.75,
        experiment_reproduction_rate=0.5,
        validator_rejection_rate=0.25,
        avg_cost_per_success=4.5,
        avg_human_interventions=0.5,
        agent_loop_depth=3.0,
        rollback_count=1,
        citation_error_rate=0.1,
        evidence_coverage=0.8,
        total_tasks=4,
        successful_tasks=3,
        total_runs=5,
        reproduction_runs=2,
        successful_reproduction_runs=1,
        validation_report_count=4,
        rejected_validation_report_count=1,
        total_citations=10,
        blocked_citations=1,
        total_claims=5,
        covered_claims=4,
        total_cost=18.0,
        human_intervention_count=2,
    )
    output_path = tmp_path / "status" / "local-status.md"

    report = export_local_status_report(
        metrics=metrics,
        output_path=output_path,
        generated_at=datetime(2026, 6, 12, 4, 0, tzinfo=timezone.utc),
        project_states=(
            ProjectStatusSummary(
                project_id="project_1",
                title="Active Benchmark Study",
                status="active",
                active_task_ids=("task_1", "task_2"),
                open_issue_count=3,
                last_run_id="run_5",
                evidence_coverage=0.75,
            ),
        ),
    )

    markdown = output_path.read_text(encoding="utf-8")

    assert report.path == output_path
    assert report.report_format == "markdown"
    assert "# AI-Researcher Local Status" in markdown
    assert "| Task failure rate | 25.00% |" in markdown
    assert "| Total cost | 18.000000 |" in markdown
    assert "| Evidence coverage | 80.00% |" in markdown
    assert "| project_1 | Active Benchmark Study | active | task_1, task_2 | 3 | run_5 | 75.00% |" in markdown


def test_export_local_status_report_handles_no_active_projects(tmp_path) -> None:
    metrics = SystemMetricSnapshot(
        task_success_rate=0.0,
        experiment_reproduction_rate=0.0,
        validator_rejection_rate=0.0,
        avg_cost_per_success=0.0,
        avg_human_interventions=0.0,
        agent_loop_depth=0.0,
        rollback_count=0,
        citation_error_rate=0.0,
        evidence_coverage=0.0,
        total_tasks=0,
        successful_tasks=0,
        total_runs=0,
        reproduction_runs=0,
        successful_reproduction_runs=0,
        validation_report_count=0,
        rejected_validation_report_count=0,
        total_citations=0,
        blocked_citations=0,
        total_claims=0,
        covered_claims=0,
        total_cost=0.0,
        human_intervention_count=0,
    )
    output_path = tmp_path / "empty-status.md"

    export_local_status_report(metrics=metrics, output_path=output_path)

    assert "- No active projects recorded." in output_path.read_text(encoding="utf-8")
