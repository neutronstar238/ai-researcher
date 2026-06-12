from datetime import datetime, timezone

from autoresearch.observability import (
    ApprovalQueueSummary,
    FailureStatusSummary,
    ProjectStatusSummary,
    RunStatusSummary,
    SystemMetricSnapshot,
    export_local_dashboard_html,
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


def test_export_local_dashboard_html_renders_operational_sections(tmp_path) -> None:
    metrics = _metrics()
    output_path = tmp_path / "dashboard" / "index.html"

    dashboard = export_local_dashboard_html(
        metrics=metrics,
        output_path=output_path,
        generated_at=datetime(2026, 6, 12, 4, 0, tzinfo=timezone.utc),
        project_states=(
            ProjectStatusSummary(
                project_id="project_1",
                title="Active Benchmark Study",
                status="active",
                active_task_ids=("task_1",),
                open_issue_count=2,
                last_run_id="run_5",
                evidence_coverage=0.75,
            ),
        ),
        runs=(
            RunStatusSummary(
                run_id="run_5",
                project_id="project_1",
                task_id="task_1",
                status="success",
                validation_status="passed",
                cost=3.25,
                evidence_coverage=0.75,
            ),
        ),
        failures=(
            FailureStatusSummary(
                failure_id="failure_citation_1",
                project_id="project_1",
                severity="warning",
                status="open",
                summary="Citation validation needs review.",
                source_ref="autoresearch-vault/projects/project_1/issues/citation",
            ),
        ),
        approval_queue=(
            ApprovalQueueSummary(
                approval_id="approval_gray_release",
                approval_type="strategy_promotion",
                project_id="project_1",
                status="approval_required",
                requested_by="evolution-agent",
                summary="Approve 5 percent gray release.",
                source_ref="autoresearch-vault/exploration/reviews/strategy_v2",
            ),
        ),
    )

    html = output_path.read_text(encoding="utf-8")

    assert dashboard.path == output_path
    assert dashboard.report_format == "html"
    assert "<h1>AI-Researcher Dashboard</h1>" in html
    assert 'data-run-filter type="search"' in html
    assert "Project Status" in html
    assert "Runs" in html
    assert "Failures" in html
    assert "Costs" in html
    assert "Evidence Coverage" in html
    assert "Approval Queue" in html
    assert "run_5" in html
    assert "failure_citation_1" in html
    assert "approval_gray_release" in html
    assert "not a landing page" not in html


def _metrics() -> SystemMetricSnapshot:
    return SystemMetricSnapshot(
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
