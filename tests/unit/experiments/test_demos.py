import json
from pathlib import Path

from autoresearch.experiments import (
    StatisticalCheck,
    collect_result_bundle,
    create_letter_variance_calibrated_task,
    create_pendigits_centroid_baseline_task,
    create_pendigits_prototype_shrinkage_task,
    create_pendigits_variance_calibrated_task,
    create_skin_variance_calibrated_task,
    create_spambase_variance_calibrated_task,
    create_tabular_baseline_task,
    create_text_classifier_stub_task,
    execute_experiment_task,
    generate_letter_variance_calibrated_demo,
    generate_pendigits_centroid_baseline_demo,
    generate_pendigits_prototype_shrinkage_demo,
    generate_pendigits_variance_calibrated_demo,
    generate_skin_variance_calibrated_demo,
    generate_spambase_variance_calibrated_demo,
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


def test_public_uci_tasks_define_scoped_network_approval() -> None:
    tasks = [
        create_pendigits_centroid_baseline_task(),
        create_pendigits_prototype_shrinkage_task(),
        create_pendigits_variance_calibrated_task(),
        create_letter_variance_calibrated_task(),
        create_spambase_variance_calibrated_task(),
        create_skin_variance_calibrated_task(),
    ]

    for task in tasks:
        metadata = task.metadata
        assert metadata["network_access_approved"] is True
        assert metadata["approved_network_domains"] == ["archive.ics.uci.edu"]
        assert metadata["network_source_urls"]
        assert "cached files are preferred" in metadata["network_access_scope"]
        assert metadata["real_dataset"] is True


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


def test_create_pendigits_variance_calibrated_task_defines_method_contract() -> None:
    task = create_pendigits_variance_calibrated_task(timeout_seconds=30)

    assert task.id == "pendigits_variance_calibrated_prototypes"
    assert task.status is TaskStatus.READY
    assert task.resource_budget["gpu_hours"] == 0.0
    assert task.metadata["real_dataset"] is True
    assert task.metadata["baseline_only"] is False
    assert task.metadata["method_contribution"] == "heteroscedastic prototype distance calibration"
    assert task.metadata["feature_count"] == 16
    assert "accuracy_delta_vs_baseline" in task.metrics
    assert "zscore_centroid_accuracy" in task.metrics
    assert "feature_count" in task.metrics
    assert task.expected_outputs == [
        "metrics.json",
        "logs/run.log",
        "artifacts/summary.md",
        "artifacts/predictions.csv",
        "artifacts/ablation.csv",
        "artifacts/dataset_sources.json",
        "artifacts/innovation_evidence.json",
    ]


def test_pendigits_variance_calibrated_runs_with_method_effect_evidence(
    tmp_path: Path,
) -> None:
    experiment_dir, task = generate_pendigits_variance_calibrated_demo(
        tmp_path,
        timeout_seconds=20,
    )
    _write_cached_pendigits_file(experiment_dir / "data" / "pendigits.tra", rows_per_label=120)
    _write_cached_pendigits_file(experiment_dir / "data" / "pendigits.tes", rows_per_label=110)

    run = execute_experiment_task(experiment_dir, task, entrypoint="run.py")
    run = run.model_copy(
        update={
            "data_hash": file_hash(
                experiment_dir
                / "data"
                / "pendigits_variance_calibrated_prototypes.csv"
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
            "zscore_centroid_accuracy": (0.0, 1.0),
            "accuracy_delta_vs_zscore": (-1.0, 1.0),
            "test_rows": (1000.0, None),
            "train_rows": (1000.0, None),
            "dataset_rows": (1000.0, None),
            "accuracy_standard_error": (0.0, 1.0),
            "variance_shrinkage": (0.0, 1.0),
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
    assert bundle.metrics["variance_shrinkage"] == 0.05
    assert report.status is ValidationStatus.PASSED
    innovation_payload = json.loads(
        (experiment_dir / "artifacts" / "innovation_evidence.json").read_text(
            encoding="utf-8"
        )
    )
    assert (
        innovation_payload["proposed_method"]
        == "diagonal variance-calibrated class prototypes"
    )
    assert innovation_payload["accuracy_delta_vs_baseline"] == 0.0
    assert innovation_payload["effect_direction"] == "neutral"
    for expected_output in task.expected_outputs:
        assert (experiment_dir / expected_output).exists()


def test_create_letter_variance_calibrated_task_defines_method_contract() -> None:
    task = create_letter_variance_calibrated_task(timeout_seconds=30)

    assert task.id == "letter_variance_calibrated_prototypes"
    assert task.status is TaskStatus.READY
    assert task.resource_budget["gpu_hours"] == 0.0
    assert task.metadata["dataset"] == "Letter Recognition"
    assert task.metadata["real_dataset"] is True
    assert task.metadata["baseline_only"] is False
    assert task.metadata["method_contribution"] == "heteroscedastic prototype distance calibration"
    assert "accuracy_delta_vs_baseline" in task.metrics
    assert "zscore_centroid_accuracy" in task.metrics


def test_letter_variance_calibrated_runs_with_cached_uci_format_data(
    tmp_path: Path,
) -> None:
    experiment_dir, task = generate_letter_variance_calibrated_demo(
        tmp_path,
        timeout_seconds=20,
    )
    _write_cached_letter_file(experiment_dir / "data" / "letter-recognition.data")

    bundle = _run_and_validate_uci_variance_demo(experiment_dir, task)

    assert bundle.metrics["train_rows"] == 16000.0
    assert bundle.metrics["test_rows"] == 4000.0
    assert bundle.metrics["class_count"] == 26.0
    assert bundle.metrics["feature_count"] == 16.0
    assert bundle.metrics["variance_shrinkage"] == 1.0


def test_create_spambase_variance_calibrated_task_defines_method_contract() -> None:
    task = create_spambase_variance_calibrated_task(timeout_seconds=30)

    assert task.id == "spambase_variance_calibrated_prototypes"
    assert task.status is TaskStatus.READY
    assert task.resource_budget["gpu_hours"] == 0.0
    assert task.metadata["dataset"] == "Spambase"
    assert task.metadata["real_dataset"] is True
    assert task.metadata["baseline_only"] is False
    assert task.metadata["method_contribution"] == "heteroscedastic prototype distance calibration"
    assert task.metadata["split_policy"] == "deterministic 75/25 shuffled split with seed 238"


def test_spambase_variance_calibrated_runs_with_cached_uci_format_data(
    tmp_path: Path,
) -> None:
    experiment_dir, task = generate_spambase_variance_calibrated_demo(
        tmp_path,
        timeout_seconds=20,
    )
    _write_cached_spambase_file(experiment_dir / "data" / "spambase.data")

    bundle = _run_and_validate_uci_variance_demo(experiment_dir, task)

    assert bundle.metrics["train_rows"] == 3450.0
    assert bundle.metrics["test_rows"] == 1150.0
    assert bundle.metrics["class_count"] == 2.0
    assert bundle.metrics["feature_count"] == 57.0
    assert bundle.metrics["variance_shrinkage"] == 0.1


def test_create_skin_variance_calibrated_task_defines_method_contract() -> None:
    task = create_skin_variance_calibrated_task(timeout_seconds=30)

    assert task.id == "skin_variance_calibrated_prototypes"
    assert task.status is TaskStatus.READY
    assert task.resource_budget["gpu_hours"] == 0.0
    assert task.metadata["dataset"] == "Skin Segmentation"
    assert task.metadata["real_dataset"] is True
    assert task.metadata["baseline_only"] is False
    assert task.metadata["method_contribution"] == "heteroscedastic prototype distance calibration"
    assert task.metadata["split_policy"] == "deterministic 75/25 shuffled split with seed 238"


def test_skin_variance_calibrated_runs_with_cached_uci_format_data(
    tmp_path: Path,
) -> None:
    experiment_dir, task = generate_skin_variance_calibrated_demo(
        tmp_path,
        timeout_seconds=20,
    )
    _write_cached_skin_file(experiment_dir / "data" / "Skin_NonSkin.txt")

    bundle = _run_and_validate_uci_variance_demo(experiment_dir, task)

    assert bundle.metrics["train_rows"] == 3450.0
    assert bundle.metrics["test_rows"] == 1150.0
    assert bundle.metrics["class_count"] == 2.0
    assert bundle.metrics["feature_count"] == 3.0
    assert bundle.metrics["variance_shrinkage"] == 1.0


def _run_and_validate_uci_variance_demo(experiment_dir: Path, task) -> object:
    run = execute_experiment_task(experiment_dir, task, entrypoint="run.py")
    run = run.model_copy(
        update={
            "data_hash": file_hash(experiment_dir / "data" / f"{task.id}.csv"),
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
            "zscore_centroid_accuracy": (0.0, 1.0),
            "accuracy_delta_vs_zscore": (-1.0, 1.0),
            "test_rows": (1000.0, None),
            "train_rows": (1000.0, None),
            "dataset_rows": (1000.0, None),
            "feature_count": (1.0, None),
            "accuracy_standard_error": (0.0, 1.0),
            "variance_shrinkage": (0.0, 1.0),
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
    assert report.status is ValidationStatus.PASSED
    source_payload = json.loads(
        (experiment_dir / "artifacts" / "dataset_sources.json").read_text(encoding="utf-8")
    )
    assert source_payload["license"] == "CC BY 4.0"
    assert source_payload["sources"][0]["status"] == "cached"
    assert source_payload["sources"][0]["sha256"]
    innovation_payload = json.loads(
        (experiment_dir / "artifacts" / "innovation_evidence.json").read_text(
            encoding="utf-8"
        )
    )
    assert innovation_payload["proposed_method"]
    assert "accuracy_delta_vs_baseline" in innovation_payload
    for expected_output in task.expected_outputs:
        assert (experiment_dir / expected_output).exists()
    return bundle


def _write_cached_pendigits_file(path: Path, *, rows_per_label: int) -> None:
    lines = []
    for label in range(10):
        features = [str(label * 10)] * 16
        line = ",".join([*features, str(label)])
        lines.extend([line] * rows_per_label)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_cached_letter_file(path: Path) -> None:
    lines = []
    for row_index in range(20000):
        label_index = row_index % 26
        label = chr(ord("A") + label_index)
        features = [str(label_index + (feature_index % 4)) for feature_index in range(16)]
        lines.append(",".join([label, *features]))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_cached_spambase_file(path: Path) -> None:
    lines = []
    for row_index in range(4600):
        label = str(row_index % 2)
        base = 6 if label == "1" else 1
        features = [str(base + ((row_index + feature_index) % 3)) for feature_index in range(57)]
        lines.append(",".join([*features, label]))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_cached_skin_file(path: Path) -> None:
    lines = []
    for row_index in range(4600):
        label = "1" if row_index % 2 else "2"
        base = 220 if label == "1" else 30
        features = [str(base + ((row_index + feature_index) % 4)) for feature_index in range(3)]
        lines.append(" ".join([*features, label]))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
