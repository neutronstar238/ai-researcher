from autoresearch.experiments import (
    CostAlertStatus,
    CostUnitPrices,
    ProjectBudget,
    evaluate_project_costs,
)
from autoresearch.schemas import CostRecord, ExecutionRun


def test_project_cost_report_triggers_alert_at_eighty_percent() -> None:
    run = ExecutionRun(
        project_id="project-001",
        task_id="task-1",
        cost_json={"api_token_cost_usd": 8.0},
    )

    report = evaluate_project_costs(
        (run,),
        ProjectBudget(project_id="project-001", max_total_cost_usd=10.0),
    )

    assert report.status is CostAlertStatus.ALERT
    assert report.usage.total_cost_usd == 8.0
    assert report.usage.api_token_cost_usd == 8.0
    assert report.alerts[0].metric == "total_cost_usd"
    assert report.alerts[0].status is CostAlertStatus.ALERT
    assert report.alerts[0].ratio == 0.8
    assert report.alerts[0].message == "total_cost_usd reached 80% of budget"


def test_project_cost_report_tracks_gpu_token_and_storage_categories() -> None:
    run = ExecutionRun(
        project_id="project-001",
        task_id="task-1",
        cost_record=CostRecord(
            model_name="local-runner",
            token_input=1000,
            token_output=2000,
            gpu_hours=1.5,
            storage_artifact_bytes=2 * 1024**3,
        ),
    )

    report = evaluate_project_costs(
        (run,),
        ProjectBudget(
            project_id="project-001",
            max_total_cost_usd=10.0,
            max_gpu_hours=3.0,
            max_api_token_cost_usd=1.0,
            max_storage_cost_usd=2.0,
        ),
        prices=CostUnitPrices(
            input_token_usd_per_1k=0.1,
            output_token_usd_per_1k=0.2,
            gpu_hour_usd=2.0,
            storage_gib_usd=0.5,
        ),
    )

    assert report.status is CostAlertStatus.OK
    assert report.usage.run_count == 1
    assert report.usage.token_input == 1000
    assert report.usage.token_output == 2000
    assert report.usage.api_token_cost_usd == 0.5
    assert report.usage.gpu_hours == 1.5
    assert report.usage.gpu_cost_usd == 3.0
    assert report.usage.storage_artifact_bytes == 2 * 1024**3
    assert report.usage.storage_cost_usd == 1.0
    assert report.usage.total_cost_usd == 4.5
    assert report.alerts == ()


def test_project_cost_report_blocks_at_hard_limit() -> None:
    run = ExecutionRun(
        project_id="project-001",
        task_id="task-1",
        cost_json={"total_cost_usd": 10.0},
    )

    report = evaluate_project_costs(
        (run,),
        ProjectBudget(project_id="project-001", max_total_cost_usd=10.0),
    )

    assert report.status is CostAlertStatus.BLOCKED
    assert report.alerts[0].metric == "total_cost_usd"
    assert report.alerts[0].status is CostAlertStatus.BLOCKED
    assert report.alerts[0].ratio == 1.0


def test_project_cost_report_filters_other_projects() -> None:
    project_run = ExecutionRun(
        project_id="project-001",
        task_id="task-1",
        cost_json={"total_cost_usd": 1.0},
    )
    other_run = ExecutionRun(
        project_id="project-002",
        task_id="task-2",
        cost_json={"total_cost_usd": 100.0},
    )

    report = evaluate_project_costs(
        (project_run, other_run),
        ProjectBudget(project_id="project-001", max_total_cost_usd=10.0),
    )

    assert report.status is CostAlertStatus.OK
    assert report.usage.run_count == 1
    assert report.usage.total_cost_usd == 1.0
    assert report.alerts == ()
