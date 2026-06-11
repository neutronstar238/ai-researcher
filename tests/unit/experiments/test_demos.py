from pathlib import Path

from autoresearch.experiments import (
    collect_result_bundle,
    create_tabular_baseline_task,
    execute_experiment_task,
    generate_tabular_baseline_demo,
    validate_result_bundle,
)
from autoresearch.schemas import ExecutionStatus, TaskStatus, ValidationStatus, file_hash


def test_create_tabular_baseline_task_defines_local_demo_contract() -> None:
    task = create_tabular_baseline_task(timeout_seconds=12)

    assert task.id == "tabular_baseline"
    assert task.status is TaskStatus.READY
    assert task.timeout_seconds == 12
    assert task.resource_budget["cpu_time_seconds"] == 12
    assert task.resource_budget["gpu_hours"] == 0.0
    assert task.metrics == ["accuracy", "test_rows"]
    assert task.metadata["bench_suite"] == "ScientistBench-Lite"
    assert task.metadata["baseline_metric"] == {"accuracy": 1.0}
    assert task.expected_outputs == [
        "metrics.json",
        "logs/run.log",
        "artifacts/summary.md",
        "artifacts/predictions.csv",
    ]


def test_tabular_baseline_demo_runs_collects_and_validates(tmp_path: Path) -> None:
    experiment_dir, task = generate_tabular_baseline_demo(tmp_path, timeout_seconds=5)

    run = execute_experiment_task(experiment_dir, task, entrypoint="run.py")
    run = run.model_copy(
        update={
            "data_hash": file_hash(experiment_dir / "data" / "tabular_baseline.csv"),
            "cost_json": {"cpu_time_seconds": 0.0, "human_approval_count": 0},
        }
    )
    bundle = collect_result_bundle(experiment_dir, run)
    report = validate_result_bundle(
        experiment_dir,
        run,
        bundle,
        expected_metrics=task.metrics,
        metric_bounds={
            "accuracy": (0.0, 1.0),
            "test_rows": (1.0, None),
        },
        expected_artifacts=[
            "artifacts/summary.md",
            "artifacts/predictions.csv",
        ],
    )

    assert run.status is ExecutionStatus.SUCCESS
    assert run.exit_code == 0
    assert run.limit_violations == []
    assert bundle.metrics == {"accuracy": 1.0, "test_rows": 4.0}
    assert report.status is ValidationStatus.PASSED
    for expected_output in task.expected_outputs:
        assert (experiment_dir / expected_output).exists()
