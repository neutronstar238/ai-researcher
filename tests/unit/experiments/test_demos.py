import json
from pathlib import Path

from autoresearch.experiments import (
    StatisticalCheck,
    collect_result_bundle,
    create_pendigits_centroid_baseline_task,
    create_pendigits_prototype_shrinkage_task,
    create_tabular_baseline_task,
    create_text_classifier_stub_task,
    execute_experiment_task,
    generate_pendigits_centroid_baseline_demo,
    generate_pendigits_prototype_shrinkage_demo,
    generate_tabular_baseline_demo,
    generate_text_classifier_stub_demo,
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


def test_create_text_classifier_stub_task_defines_local_demo_contract() -> None:
    task = create_text_classifier_stub_task(timeout_seconds=12)

    assert task.id == "text_classifier_stub"
    assert task.status is TaskStatus.READY
    assert task.timeout_seconds == 12
    assert task.resource_budget["cpu_time_seconds"] == 12
    assert task.resource_budget["gpu_hours"] == 0.0
    assert task.metrics == ["accuracy", "test_rows", "vocabulary_size"]
    assert task.metadata["bench_suite"] == "ScientistBench-Lite"
    assert task.metadata["baseline_metric"] == {"accuracy": 1.0}
    assert task.expected_outputs == [
        "metrics.json",
        "logs/run.log",
        "artifacts/summary.md",
        "artifacts/predictions.csv",
        "artifacts/vocabulary.txt",
    ]


def test_text_classifier_stub_demo_runs_collects_and_validates(tmp_path: Path) -> None:
    experiment_dir, task = generate_text_classifier_stub_demo(
        tmp_path,
        timeout_seconds=5,
    )

    run = execute_experiment_task(experiment_dir, task, entrypoint="run.py")
    run = run.model_copy(
        update={
            "data_hash": file_hash(experiment_dir / "data" / "text_classifier_stub.csv"),
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
            "vocabulary_size": (1.0, None),
        },
        expected_artifacts=[
            "artifacts/summary.md",
            "artifacts/predictions.csv",
            "artifacts/vocabulary.txt",
        ],
    )

    assert run.status is ExecutionStatus.SUCCESS
    assert run.exit_code == 0
    assert run.limit_violations == []
    assert bundle.metrics == {
        "accuracy": 1.0,
        "test_rows": 4.0,
        "vocabulary_size": 13.0,
    }
    assert report.status is ValidationStatus.PASSED
    for expected_output in task.expected_outputs:
        assert (experiment_dir / expected_output).exists()


def test_create_pendigits_centroid_baseline_task_defines_real_benchmark_contract() -> None:
    task = create_pendigits_centroid_baseline_task(timeout_seconds=30)

    assert task.id == "pendigits_centroid_baseline"
    assert task.status is TaskStatus.READY
    assert task.resource_budget["gpu_hours"] == 0.0
    assert task.metadata["real_dataset"] is True
    assert task.metadata["dataset_realism"] == "real_public_benchmark"
    assert task.metadata["dataset_license"] == "CC BY 4.0"
    assert "ablation" in task.metadata
    assert "accuracy_standard_error" in task.metrics
    assert task.expected_outputs == [
        "metrics.json",
        "logs/run.log",
        "artifacts/summary.md",
        "artifacts/predictions.csv",
        "artifacts/ablation.csv",
        "artifacts/dataset_sources.json",
    ]


def test_pendigits_centroid_baseline_uses_cached_real_format_data(
    tmp_path: Path,
) -> None:
    experiment_dir, task = generate_pendigits_centroid_baseline_demo(
        tmp_path,
        timeout_seconds=20,
    )
    _write_cached_pendigits_file(experiment_dir / "data" / "pendigits.tra", rows_per_label=120)
    _write_cached_pendigits_file(experiment_dir / "data" / "pendigits.tes", rows_per_label=110)

    run = execute_experiment_task(experiment_dir, task, entrypoint="run.py")
    run = run.model_copy(
        update={
            "data_hash": file_hash(
                experiment_dir / "data" / "pendigits_centroid_baseline.csv"
            ),
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
            "macro_f1": (0.0, 1.0),
            "test_rows": (1000.0, None),
            "train_rows": (1000.0, None),
            "dataset_rows": (1000.0, None),
            "accuracy_standard_error": (0.0, 1.0),
        },
        expected_artifacts=[
            "artifacts/summary.md",
            "artifacts/predictions.csv",
            "artifacts/ablation.csv",
            "artifacts/dataset_sources.json",
        ],
        statistical_checks=[
            StatisticalCheck(
                metric_name="accuracy",
                sample_size=int(bundle.metrics["test_rows"]),
                mean=bundle.metrics["accuracy"],
                standard_error=bundle.metrics["accuracy_standard_error"],
                baseline_mean=bundle.metrics["ablation_accuracy_first8"],
                comparison_mean=bundle.metrics["accuracy"],
                min_sample_size=1000,
            )
        ],
    )

    assert run.status is ExecutionStatus.SUCCESS
    assert run.exit_code == 0
    assert run.limit_violations == []
    assert bundle.metrics["test_rows"] == 1100.0
    assert bundle.metrics["train_rows"] == 1200.0
    assert bundle.metrics["accuracy"] == 1.0
    assert bundle.metrics["macro_f1"] == 1.0
    assert report.status is ValidationStatus.PASSED
    assert report.statistical_notes
    source_payload = json.loads(
        (experiment_dir / "artifacts" / "dataset_sources.json").read_text(encoding="utf-8")
    )
    assert source_payload["license"] == "CC BY 4.0"
    assert all(source["sha256"] for source in source_payload["sources"])
    for expected_output in task.expected_outputs:
        assert (experiment_dir / expected_output).exists()


def test_create_pendigits_prototype_shrinkage_task_defines_method_contract() -> None:
    task = create_pendigits_prototype_shrinkage_task(timeout_seconds=30)

    assert task.id == "pendigits_prototype_shrinkage"
    assert task.status is TaskStatus.READY
    assert task.resource_budget["gpu_hours"] == 0.0
    assert task.metadata["real_dataset"] is True
    assert task.metadata["baseline_only"] is False
    assert "proposed_method" in task.metadata
    assert "novel_contribution" in task.metadata
    assert "accuracy_delta_vs_baseline" in task.metrics
    assert "prototype_shift_l2_mean" in task.metrics
    assert task.expected_outputs == [
        "metrics.json",
        "logs/run.log",
        "artifacts/summary.md",
        "artifacts/predictions.csv",
        "artifacts/ablation.csv",
        "artifacts/dataset_sources.json",
        "artifacts/innovation_evidence.json",
    ]


def test_pendigits_prototype_shrinkage_runs_with_innovation_evidence(
    tmp_path: Path,
) -> None:
    experiment_dir, task = generate_pendigits_prototype_shrinkage_demo(
        tmp_path,
        timeout_seconds=20,
    )
    _write_cached_pendigits_file(experiment_dir / "data" / "pendigits.tra", rows_per_label=120)
    _write_cached_pendigits_file(experiment_dir / "data" / "pendigits.tes", rows_per_label=110)

    run = execute_experiment_task(experiment_dir, task, entrypoint="run.py")
    run = run.model_copy(
        update={
            "data_hash": file_hash(
                experiment_dir / "data" / "pendigits_prototype_shrinkage.csv"
            ),
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
            "macro_f1": (0.0, 1.0),
            "baseline_accuracy": (0.0, 1.0),
            "accuracy_delta_vs_baseline": (-1.0, 1.0),
            "test_rows": (1000.0, None),
            "train_rows": (1000.0, None),
            "dataset_rows": (1000.0, None),
            "accuracy_standard_error": (0.0, 1.0),
            "prototype_shift_l2_mean": (0.0, None),
            "shrinkage_alpha": (0.0, 1.0),
        },
        expected_artifacts=[
            "artifacts/summary.md",
            "artifacts/predictions.csv",
            "artifacts/ablation.csv",
            "artifacts/dataset_sources.json",
            "artifacts/innovation_evidence.json",
        ],
        statistical_checks=[
            StatisticalCheck(
                metric_name="accuracy",
                sample_size=int(bundle.metrics["test_rows"]),
                mean=bundle.metrics["accuracy"],
                standard_error=bundle.metrics["accuracy_standard_error"],
                baseline_mean=bundle.metrics["baseline_accuracy"],
                comparison_mean=bundle.metrics["accuracy"],
                min_sample_size=1000,
            )
        ],
    )

    assert run.status is ExecutionStatus.SUCCESS
    assert run.exit_code == 0
    assert bundle.metrics["test_rows"] == 1100.0
    assert bundle.metrics["baseline_accuracy"] == 1.0
    assert bundle.metrics["accuracy"] == 1.0
    assert bundle.metrics["accuracy_delta_vs_baseline"] == 0.0
    assert bundle.metrics["prototype_shift_l2_mean"] > 0.0
    assert report.status is ValidationStatus.PASSED
    innovation_payload = json.loads(
        (experiment_dir / "artifacts" / "innovation_evidence.json").read_text(
            encoding="utf-8"
        )
    )
    assert innovation_payload["proposed_method"] == "class prototype shrinkage toward global mean"
    assert innovation_payload["accuracy_delta_vs_baseline"] == 0.0
    assert "do not claim empirical gain" in innovation_payload["interpretation"]
    for expected_output in task.expected_outputs:
        assert (experiment_dir / expected_output).exists()


def _write_cached_pendigits_file(path: Path, *, rows_per_label: int) -> None:
    lines = []
    for label in range(10):
        features = [str(label * 10)] * 16
        line = ",".join([*features, str(label)])
        lines.extend([line] * rows_per_label)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
