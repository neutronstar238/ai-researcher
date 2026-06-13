"""Local ScientistBench-Lite demo experiment tasks."""

from __future__ import annotations

import textwrap
from pathlib import Path

from autoresearch.schemas import ExperimentTask, TaskStatus

TABULAR_BASELINE_TASK_ID = "tabular_baseline"
TABULAR_BASELINE_DIR = "tabular-baseline"
TEXT_CLASSIFIER_STUB_TASK_ID = "text_classifier_stub"
TEXT_CLASSIFIER_STUB_DIR = "text-classifier-stub"
PENDIGITS_CENTROID_BASELINE_TASK_ID = "pendigits_centroid_baseline"
PENDIGITS_CENTROID_BASELINE_DIR = "pendigits-centroid-baseline"
PENDIGITS_PROTOTYPE_SHRINKAGE_TASK_ID = "pendigits_prototype_shrinkage"
PENDIGITS_PROTOTYPE_SHRINKAGE_DIR = "pendigits-prototype-shrinkage"
PENDIGITS_VARIANCE_CALIBRATED_TASK_ID = "pendigits_variance_calibrated_prototypes"
PENDIGITS_VARIANCE_CALIBRATED_DIR = "pendigits-variance-calibrated-prototypes"


def create_tabular_baseline_task(
    *,
    project_id: str = "scientistbench-lite",
    hypothesis_id: str = "hypothesis_tabular_baseline",
    timeout_seconds: int = 30,
) -> ExperimentTask:
    """Return the local tabular baseline demo task definition."""

    return ExperimentTask(
        id=TABULAR_BASELINE_TASK_ID,
        project_id=project_id,
        hypothesis_id=hypothesis_id,
        name="ScientistBench-Lite tabular_baseline",
        description=(
            "Run a tiny deterministic tabular classification baseline on a local "
            "CSV fixture and emit metrics, logs, and summary artifacts."
        ),
        entrypoint=f"experiments/{TABULAR_BASELINE_DIR}/run.py",
        config_path=f"experiments/{TABULAR_BASELINE_DIR}/config.yaml",
        metrics=["accuracy", "test_rows"],
        resource_budget={
            "cpu_time_seconds": min(timeout_seconds, 30),
            "memory_mb": 256,
            "gpu_hours": 0.0,
            "storage_mb": 16,
        },
        timeout_seconds=timeout_seconds,
        expected_outputs=[
            "metrics.json",
            "logs/run.log",
            "artifacts/summary.md",
            "artifacts/predictions.csv",
        ],
        dependencies=["python>=3.10"],
        priority=5,
        status=TaskStatus.READY,
        metadata={
            "bench_suite": "ScientistBench-Lite",
            "demo_task": TABULAR_BASELINE_TASK_ID,
            "dataset": "local synthetic binary classification CSV",
            "baseline": "predict label 1 when feature signal is at least 1",
            "baseline_metric": {"accuracy": 1.0},
            "validation_checks": [
                "metrics.json exists",
                "accuracy is between 0 and 1",
                "test_rows is greater than 0",
                "artifacts/summary.md exists",
                "artifacts/predictions.csv exists",
                "logs/run.log exists",
            ],
        },
    )


def generate_tabular_baseline_demo(
    root: Path | str,
    *,
    project_id: str = "scientistbench-lite",
    hypothesis_id: str = "hypothesis_tabular_baseline",
    timeout_seconds: int = 30,
) -> tuple[Path, ExperimentTask]:
    """Create the local tabular baseline experiment directory."""

    task = create_tabular_baseline_task(
        project_id=project_id,
        hypothesis_id=hypothesis_id,
        timeout_seconds=timeout_seconds,
    )
    experiment_dir = Path(root) / TABULAR_BASELINE_DIR
    (experiment_dir / "data").mkdir(parents=True, exist_ok=True)
    (experiment_dir / "logs").mkdir(parents=True, exist_ok=True)
    (experiment_dir / "artifacts").mkdir(parents=True, exist_ok=True)

    _write(experiment_dir / "README.md", _readme())
    _write(experiment_dir / "config.yaml", _config_yaml(task))
    _write(experiment_dir / "data" / "tabular_baseline.csv", _dataset_csv())
    _write(experiment_dir / "run.py", _run_py())
    return experiment_dir, task


def create_text_classifier_stub_task(
    *,
    project_id: str = "scientistbench-lite",
    hypothesis_id: str = "hypothesis_text_classifier_stub",
    timeout_seconds: int = 30,
) -> ExperimentTask:
    """Return the local text classifier stub demo task definition."""

    return ExperimentTask(
        id=TEXT_CLASSIFIER_STUB_TASK_ID,
        project_id=project_id,
        hypothesis_id=hypothesis_id,
        name="ScientistBench-Lite text_classifier_stub",
        description=(
            "Run a tiny deterministic text classification stub with a mocked "
            "keyword vectorizer and emit metrics, logs, and validation artifacts."
        ),
        entrypoint=f"experiments/{TEXT_CLASSIFIER_STUB_DIR}/run.py",
        config_path=f"experiments/{TEXT_CLASSIFIER_STUB_DIR}/config.yaml",
        metrics=["accuracy", "test_rows", "vocabulary_size"],
        resource_budget={
            "cpu_time_seconds": min(timeout_seconds, 30),
            "memory_mb": 256,
            "gpu_hours": 0.0,
            "storage_mb": 16,
        },
        timeout_seconds=timeout_seconds,
        expected_outputs=[
            "metrics.json",
            "logs/run.log",
            "artifacts/summary.md",
            "artifacts/predictions.csv",
            "artifacts/vocabulary.txt",
        ],
        dependencies=["python>=3.10"],
        priority=5,
        status=TaskStatus.READY,
        metadata={
            "bench_suite": "ScientistBench-Lite",
            "demo_task": TEXT_CLASSIFIER_STUB_TASK_ID,
            "dataset": "local synthetic text classification CSV",
            "baseline": "mocked keyword vectorizer with deterministic labels",
            "baseline_metric": {"accuracy": 1.0},
            "validation_checks": [
                "metrics.json exists",
                "accuracy is between 0 and 1",
                "test_rows is greater than 0",
                "vocabulary_size is greater than 0",
                "artifacts/summary.md exists",
                "artifacts/predictions.csv exists",
                "artifacts/vocabulary.txt exists",
                "logs/run.log exists",
            ],
        },
    )


def generate_text_classifier_stub_demo(
    root: Path | str,
    *,
    project_id: str = "scientistbench-lite",
    hypothesis_id: str = "hypothesis_text_classifier_stub",
    timeout_seconds: int = 30,
) -> tuple[Path, ExperimentTask]:
    """Create the local text classifier stub experiment directory."""

    task = create_text_classifier_stub_task(
        project_id=project_id,
        hypothesis_id=hypothesis_id,
        timeout_seconds=timeout_seconds,
    )
    experiment_dir = Path(root) / TEXT_CLASSIFIER_STUB_DIR
    (experiment_dir / "data").mkdir(parents=True, exist_ok=True)
    (experiment_dir / "logs").mkdir(parents=True, exist_ok=True)
    (experiment_dir / "artifacts").mkdir(parents=True, exist_ok=True)

    _write(experiment_dir / "README.md", _text_readme())
    _write(experiment_dir / "config.yaml", _text_config_yaml(task))
    _write(experiment_dir / "data" / "text_classifier_stub.csv", _text_dataset_csv())
    _write(experiment_dir / "run.py", _text_run_py())
    return experiment_dir, task


def create_pendigits_centroid_baseline_task(
    *,
    project_id: str = "public-benchmark-pendigits",
    hypothesis_id: str = "hypothesis_pendigits_centroid_baseline",
    timeout_seconds: int = 60,
) -> ExperimentTask:
    """Return a real public benchmark baseline task definition."""

    return ExperimentTask(
        id=PENDIGITS_CENTROID_BASELINE_TASK_ID,
        project_id=project_id,
        hypothesis_id=hypothesis_id,
        name="UCI Pendigits centroid baseline",
        description=(
            "Download the public UCI Pendigits train/test files, merge them into "
            "a local CSV with provenance, run a nearest-centroid baseline, run a "
            "feature-subset ablation, and emit metrics, logs, statistical inputs, "
            "and source artifacts."
        ),
        entrypoint=f"experiments/{PENDIGITS_CENTROID_BASELINE_DIR}/run.py",
        config_path=f"experiments/{PENDIGITS_CENTROID_BASELINE_DIR}/config.yaml",
        metrics=[
            "accuracy",
            "macro_f1",
            "test_rows",
            "train_rows",
            "dataset_rows",
            "class_count",
            "ablation_accuracy_first8",
            "accuracy_delta_vs_ablation",
            "accuracy_standard_error",
        ],
        resource_budget={
            "cpu_time_seconds": min(timeout_seconds, 60),
            "memory_mb": 256,
            "gpu_hours": 0.0,
            "storage_mb": 64,
        },
        timeout_seconds=timeout_seconds,
        expected_outputs=[
            "metrics.json",
            "logs/run.log",
            "artifacts/summary.md",
            "artifacts/predictions.csv",
            "artifacts/ablation.csv",
            "artifacts/dataset_sources.json",
        ],
        dependencies=["python>=3.10"],
        priority=4,
        status=TaskStatus.READY,
        metadata={
            "bench_suite": "UCI ML Repository",
            "demo_task": PENDIGITS_CENTROID_BASELINE_TASK_ID,
            "dataset": "Pen-Based Recognition of Handwritten Digits",
            "dataset_source": (
                "https://archive.ics.uci.edu/ml/machine-learning-databases/pendigits/"
            ),
            "dataset_license": "CC BY 4.0",
            "dataset_rows_expected": 10992,
            "real_dataset": True,
            "dataset_realism": "real_public_benchmark",
            "split_policy": "official UCI pendigits.tra train and pendigits.tes test split",
            "baseline": "nearest-centroid classifier using all 16 pen trajectory features",
            "ablation": "nearest-centroid classifier using only the first 8 trajectory features",
            "baseline_metric": {"accuracy": "computed from official test split"},
            "validation_checks": [
                "metrics.json exists",
                "accuracy is between 0 and 1",
                "macro_f1 is between 0 and 1",
                "test_rows is at least 1000 on the official split",
                "dataset_sources.json records source URLs and byte counts",
                "artifacts/ablation.csv exists",
                "validation report includes statistical sanity notes",
            ],
        },
    )


def generate_pendigits_centroid_baseline_demo(
    root: Path | str,
    *,
    project_id: str = "public-benchmark-pendigits",
    hypothesis_id: str = "hypothesis_pendigits_centroid_baseline",
    timeout_seconds: int = 60,
) -> tuple[Path, ExperimentTask]:
    """Create the UCI Pendigits real benchmark experiment directory."""

    task = create_pendigits_centroid_baseline_task(
        project_id=project_id,
        hypothesis_id=hypothesis_id,
        timeout_seconds=timeout_seconds,
    )
    experiment_dir = Path(root) / PENDIGITS_CENTROID_BASELINE_DIR
    (experiment_dir / "data").mkdir(parents=True, exist_ok=True)
    (experiment_dir / "logs").mkdir(parents=True, exist_ok=True)
    (experiment_dir / "artifacts").mkdir(parents=True, exist_ok=True)

    _write(experiment_dir / "README.md", _pendigits_readme())
    _write(experiment_dir / "config.yaml", _pendigits_config_yaml(task))
    _write(experiment_dir / "run.py", _pendigits_run_py())
    return experiment_dir, task


def create_pendigits_prototype_shrinkage_task(
    *,
    project_id: str = "public-benchmark-pendigits",
    hypothesis_id: str = "hypothesis_pendigits_prototype_shrinkage",
    timeout_seconds: int = 60,
) -> ExperimentTask:
    """Return a real public benchmark method-candidate task definition."""

    return ExperimentTask(
        id=PENDIGITS_PROTOTYPE_SHRINKAGE_TASK_ID,
        project_id=project_id,
        hypothesis_id=hypothesis_id,
        name="UCI Pendigits prototype shrinkage candidate",
        description=(
            "Download the public UCI Pendigits train/test files, compare a "
            "nearest-centroid baseline against a class-prototype shrinkage "
            "candidate, run a feature-subset ablation, and emit metrics, logs, "
            "statistical inputs, source artifacts, and method-innovation evidence."
        ),
        entrypoint=f"experiments/{PENDIGITS_PROTOTYPE_SHRINKAGE_DIR}/run.py",
        config_path=f"experiments/{PENDIGITS_PROTOTYPE_SHRINKAGE_DIR}/config.yaml",
        metrics=[
            "accuracy",
            "macro_f1",
            "baseline_accuracy",
            "accuracy_delta_vs_baseline",
            "test_rows",
            "train_rows",
            "dataset_rows",
            "class_count",
            "ablation_accuracy_first8",
            "accuracy_delta_vs_ablation",
            "accuracy_standard_error",
            "prototype_shift_l2_mean",
            "shrinkage_alpha",
        ],
        resource_budget={
            "cpu_time_seconds": min(timeout_seconds, 60),
            "memory_mb": 256,
            "gpu_hours": 0.0,
            "storage_mb": 64,
        },
        timeout_seconds=timeout_seconds,
        expected_outputs=[
            "metrics.json",
            "logs/run.log",
            "artifacts/summary.md",
            "artifacts/predictions.csv",
            "artifacts/ablation.csv",
            "artifacts/dataset_sources.json",
            "artifacts/innovation_evidence.json",
        ],
        dependencies=["python>=3.10"],
        priority=3,
        status=TaskStatus.READY,
        metadata={
            "bench_suite": "UCI ML Repository",
            "demo_task": PENDIGITS_PROTOTYPE_SHRINKAGE_TASK_ID,
            "dataset": "Pen-Based Recognition of Handwritten Digits",
            "dataset_source": (
                "https://archive.ics.uci.edu/ml/machine-learning-databases/pendigits/"
            ),
            "dataset_license": "CC BY 4.0",
            "dataset_rows_expected": 10992,
            "real_dataset": True,
            "dataset_realism": "real_public_benchmark",
            "split_policy": "official UCI pendigits.tra train and pendigits.tes test split",
            "baseline": "nearest-centroid classifier using all 16 pen trajectory features",
            "ablation": "nearest-centroid classifier using only the first 8 trajectory features",
            "proposed_method": "class prototype shrinkage toward the global feature mean",
            "novel_contribution": (
                "Evaluate whether global-mean shrinkage makes nearest-centroid "
                "prototypes more stable on the public Pendigits benchmark."
            ),
            "method_contribution": "prototype shrinkage calibration",
            "baseline_only": False,
            "baseline_metric": {"accuracy": "computed from official test split"},
            "validation_checks": [
                "metrics.json exists",
                "accuracy is between 0 and 1",
                "macro_f1 is between 0 and 1",
                "baseline_accuracy is between 0 and 1",
                "test_rows is at least 1000 on the official split",
                "dataset_sources.json records source URLs and byte counts",
                "artifacts/ablation.csv exists",
                "artifacts/innovation_evidence.json exists",
                "validation report includes statistical sanity notes",
            ],
        },
    )


def generate_pendigits_prototype_shrinkage_demo(
    root: Path | str,
    *,
    project_id: str = "public-benchmark-pendigits",
    hypothesis_id: str = "hypothesis_pendigits_prototype_shrinkage",
    timeout_seconds: int = 60,
) -> tuple[Path, ExperimentTask]:
    """Create the UCI Pendigits method-candidate experiment directory."""

    task = create_pendigits_prototype_shrinkage_task(
        project_id=project_id,
        hypothesis_id=hypothesis_id,
        timeout_seconds=timeout_seconds,
    )
    experiment_dir = Path(root) / PENDIGITS_PROTOTYPE_SHRINKAGE_DIR
    (experiment_dir / "data").mkdir(parents=True, exist_ok=True)
    (experiment_dir / "logs").mkdir(parents=True, exist_ok=True)
    (experiment_dir / "artifacts").mkdir(parents=True, exist_ok=True)

    _write(experiment_dir / "README.md", _pendigits_shrinkage_readme())
    _write(experiment_dir / "config.yaml", _pendigits_shrinkage_config_yaml(task))
    _write(experiment_dir / "run.py", _pendigits_prototype_shrinkage_run_py())
    return experiment_dir, task


def create_pendigits_variance_calibrated_task(
    *,
    project_id: str = "public-benchmark-pendigits",
    hypothesis_id: str = "hypothesis_pendigits_variance_calibrated",
    timeout_seconds: int = 60,
) -> ExperimentTask:
    """Return a real public benchmark positive-effect method-candidate task."""

    return ExperimentTask(
        id=PENDIGITS_VARIANCE_CALIBRATED_TASK_ID,
        project_id=project_id,
        hypothesis_id=hypothesis_id,
        name="UCI Pendigits variance-calibrated prototype candidate",
        description=(
            "Download the public UCI Pendigits train/test files, compare a "
            "nearest-centroid baseline against a diagonal variance-calibrated "
            "prototype classifier, run a z-score centroid ablation, and emit "
            "metrics, logs, statistical inputs, source artifacts, and positive "
            "method-effect evidence."
        ),
        entrypoint=f"experiments/{PENDIGITS_VARIANCE_CALIBRATED_DIR}/run.py",
        config_path=f"experiments/{PENDIGITS_VARIANCE_CALIBRATED_DIR}/config.yaml",
        metrics=[
            "accuracy",
            "macro_f1",
            "baseline_accuracy",
            "accuracy_delta_vs_baseline",
            "zscore_centroid_accuracy",
            "accuracy_delta_vs_zscore",
            "test_rows",
            "train_rows",
            "dataset_rows",
            "class_count",
            "accuracy_standard_error",
            "variance_shrinkage",
        ],
        resource_budget={
            "cpu_time_seconds": min(timeout_seconds, 60),
            "memory_mb": 256,
            "gpu_hours": 0.0,
            "storage_mb": 64,
        },
        timeout_seconds=timeout_seconds,
        expected_outputs=[
            "metrics.json",
            "logs/run.log",
            "artifacts/summary.md",
            "artifacts/predictions.csv",
            "artifacts/ablation.csv",
            "artifacts/dataset_sources.json",
            "artifacts/innovation_evidence.json",
        ],
        dependencies=["python>=3.10"],
        priority=3,
        status=TaskStatus.READY,
        metadata={
            "bench_suite": "UCI ML Repository",
            "demo_task": PENDIGITS_VARIANCE_CALIBRATED_TASK_ID,
            "dataset": "Pen-Based Recognition of Handwritten Digits",
            "dataset_source": (
                "https://archive.ics.uci.edu/ml/machine-learning-databases/pendigits/"
            ),
            "dataset_license": "CC BY 4.0",
            "dataset_rows_expected": 10992,
            "real_dataset": True,
            "dataset_realism": "real_public_benchmark",
            "split_policy": "official UCI pendigits.tra train and pendigits.tes test split",
            "baseline": "nearest-centroid classifier using all 16 pen trajectory features",
            "ablation": "z-score normalized nearest-centroid classifier",
            "proposed_method": "diagonal variance-calibrated class prototypes",
            "novel_contribution": (
                "Evaluate whether per-class diagonal variance calibration gives "
                "prototype classifiers a stronger distance model on Pendigits."
            ),
            "method_contribution": "heteroscedastic prototype distance calibration",
            "baseline_only": False,
            "baseline_metric": {"accuracy": "computed from official test split"},
            "validation_checks": [
                "metrics.json exists",
                "accuracy is between 0 and 1",
                "macro_f1 is between 0 and 1",
                "baseline_accuracy is between 0 and 1",
                "test_rows is at least 1000 on the official split",
                "dataset_sources.json records source URLs and byte counts",
                "artifacts/ablation.csv exists",
                "artifacts/innovation_evidence.json exists",
                "validation report includes statistical sanity notes",
            ],
        },
    )


def generate_pendigits_variance_calibrated_demo(
    root: Path | str,
    *,
    project_id: str = "public-benchmark-pendigits",
    hypothesis_id: str = "hypothesis_pendigits_variance_calibrated",
    timeout_seconds: int = 60,
) -> tuple[Path, ExperimentTask]:
    """Create the UCI Pendigits positive-effect method-candidate experiment."""

    task = create_pendigits_variance_calibrated_task(
        project_id=project_id,
        hypothesis_id=hypothesis_id,
        timeout_seconds=timeout_seconds,
    )
    experiment_dir = Path(root) / PENDIGITS_VARIANCE_CALIBRATED_DIR
    (experiment_dir / "data").mkdir(parents=True, exist_ok=True)
    (experiment_dir / "logs").mkdir(parents=True, exist_ok=True)
    (experiment_dir / "artifacts").mkdir(parents=True, exist_ok=True)

    _write(experiment_dir / "README.md", _pendigits_variance_calibrated_readme())
    _write(experiment_dir / "config.yaml", _pendigits_variance_calibrated_config_yaml(task))
    _write(experiment_dir / "run.py", _pendigits_variance_calibrated_run_py())
    return experiment_dir, task


def _readme() -> str:
    return textwrap.dedent(
        """\
        # ScientistBench-Lite: tabular_baseline

        This local demo runs a deterministic tabular classification baseline on
        a tiny CSV fixture. It is designed to exercise the MVP experiment loop
        without network access, GPUs, or heavyweight ML dependencies.

        ## Expected Outputs

        - `metrics.json`
        - `logs/run.log`
        - `artifacts/summary.md`
        - `artifacts/predictions.csv`
        """
    )


def _text_readme() -> str:
    return textwrap.dedent(
        """\
        # ScientistBench-Lite: text_classifier_stub

        This local demo runs a deterministic text classification stub on a tiny
        CSV fixture. It exercises the MVP loop with a mocked keyword vectorizer
        instead of model training.

        ## Expected Outputs

        - `metrics.json`
        - `logs/run.log`
        - `artifacts/summary.md`
        - `artifacts/predictions.csv`
        - `artifacts/vocabulary.txt`
        """
    )


def _pendigits_readme() -> str:
    return textwrap.dedent(
        """\
        # UCI Pendigits: centroid baseline

        This opt-in demo runs on the real public UCI Pen-Based Recognition of
        Handwritten Digits benchmark. The runner downloads the official
        `pendigits.tra` and `pendigits.tes` files when they are not already
        present under `data/`, writes a merged CSV, then evaluates a
        nearest-centroid baseline and a first-8-features ablation.

        The dataset files are fetched at run time and are not vendored into the
        repository. If `data/pendigits.tra` and `data/pendigits.tes` already
        exist, the runner uses those local files and records them as cached
        sources.

        ## Expected Outputs

        - `metrics.json`
        - `logs/run.log`
        - `artifacts/summary.md`
        - `artifacts/predictions.csv`
        - `artifacts/ablation.csv`
        - `artifacts/dataset_sources.json`
        """
    )


def _pendigits_shrinkage_readme() -> str:
    return textwrap.dedent(
        """\
        # UCI Pendigits: prototype shrinkage candidate

        This opt-in demo runs on the real public UCI Pen-Based Recognition of
        Handwritten Digits benchmark. The runner downloads the official
        `pendigits.tra` and `pendigits.tes` files when they are not already
        present under `data/`, writes a merged CSV, evaluates a nearest-centroid
        baseline, then evaluates a class-prototype shrinkage candidate.

        The method candidate shrinks each class centroid toward the global
        feature mean before classification. This is intentionally small and
        interpretable: it gives the autonomous loop a real method artifact to
        test, not a paper-ready claim. The output records whether the candidate
        improves, ties, or hurts the baseline.

        ## Expected Outputs

        - `metrics.json`
        - `logs/run.log`
        - `artifacts/summary.md`
        - `artifacts/predictions.csv`
        - `artifacts/ablation.csv`
        - `artifacts/dataset_sources.json`
        - `artifacts/innovation_evidence.json`
        """
    )


def _pendigits_variance_calibrated_readme() -> str:
    return textwrap.dedent(
        """\
        # UCI Pendigits: variance-calibrated prototype candidate

        This opt-in demo runs on the real public UCI Pen-Based Recognition of
        Handwritten Digits benchmark. The runner downloads the official
        `pendigits.tra` and `pendigits.tes` files when they are not already
        present under `data/`, writes a merged CSV, evaluates a nearest-centroid
        baseline, evaluates a z-score centroid ablation, then evaluates a
        diagonal variance-calibrated prototype candidate.

        The candidate keeps the prototype-family interpretation but uses each
        class prototype's diagonal feature variance in the distance score. This
        is a method candidate for the autonomous loop to test, not a
        paper-ready novelty claim by itself. The output records the baseline
        delta so the publication audit can verify whether empirical-gain claims
        are supported.

        ## Expected Outputs

        - `metrics.json`
        - `logs/run.log`
        - `artifacts/summary.md`
        - `artifacts/predictions.csv`
        - `artifacts/ablation.csv`
        - `artifacts/dataset_sources.json`
        - `artifacts/innovation_evidence.json`
        """
    )


def _config_yaml(task: ExperimentTask) -> str:
    return textwrap.dedent(
        f"""\
        task_id: {task.id}
        project_id: {task.project_id}
        hypothesis_id: {task.hypothesis_id}
        dataset_path: data/tabular_baseline.csv
        target: label
        prediction_rule: signal >= 1
        metrics:
          - accuracy
          - test_rows
        """
    )


def _text_config_yaml(task: ExperimentTask) -> str:
    return textwrap.dedent(
        f"""\
        task_id: {task.id}
        project_id: {task.project_id}
        hypothesis_id: {task.hypothesis_id}
        dataset_path: data/text_classifier_stub.csv
        target: label
        vectorizer: keyword_stub
        metrics:
          - accuracy
          - test_rows
          - vocabulary_size
        """
    )


def _pendigits_config_yaml(task: ExperimentTask) -> str:
    return textwrap.dedent(
        f"""\
        task_id: {task.id}
        project_id: {task.project_id}
        hypothesis_id: {task.hypothesis_id}
        dataset_path: data/pendigits_centroid_baseline.csv
        train_source_url: https://archive.ics.uci.edu/ml/machine-learning-databases/pendigits/pendigits.tra
        test_source_url: https://archive.ics.uci.edu/ml/machine-learning-databases/pendigits/pendigits.tes
        target: label
        split_policy: official UCI train/test split
        baseline: nearest centroid over 16 features
        ablation: nearest centroid over first 8 features
        metrics:
          - accuracy
          - macro_f1
          - test_rows
          - train_rows
          - dataset_rows
          - class_count
          - ablation_accuracy_first8
          - accuracy_delta_vs_ablation
          - accuracy_standard_error
        """
    )


def _pendigits_shrinkage_config_yaml(task: ExperimentTask) -> str:
    return textwrap.dedent(
        f"""\
        task_id: {task.id}
        project_id: {task.project_id}
        hypothesis_id: {task.hypothesis_id}
        dataset_path: data/pendigits_prototype_shrinkage.csv
        train_source_url: https://archive.ics.uci.edu/ml/machine-learning-databases/pendigits/pendigits.tra
        test_source_url: https://archive.ics.uci.edu/ml/machine-learning-databases/pendigits/pendigits.tes
        target: label
        split_policy: official UCI train/test split
        baseline: nearest centroid over 16 features
        proposed_method: class-prototype shrinkage toward the global feature mean
        shrinkage_alpha: 0.10
        ablation: nearest centroid over first 8 features
        metrics:
          - accuracy
          - macro_f1
          - baseline_accuracy
          - accuracy_delta_vs_baseline
          - test_rows
          - train_rows
          - dataset_rows
          - class_count
          - ablation_accuracy_first8
          - accuracy_delta_vs_ablation
          - accuracy_standard_error
          - prototype_shift_l2_mean
          - shrinkage_alpha
        """
    )


def _pendigits_variance_calibrated_config_yaml(task: ExperimentTask) -> str:
    return textwrap.dedent(
        f"""\
        task_id: {task.id}
        project_id: {task.project_id}
        hypothesis_id: {task.hypothesis_id}
        dataset_path: data/pendigits_variance_calibrated_prototypes.csv
        train_source_url: https://archive.ics.uci.edu/ml/machine-learning-databases/pendigits/pendigits.tra
        test_source_url: https://archive.ics.uci.edu/ml/machine-learning-databases/pendigits/pendigits.tes
        target: label
        split_policy: official UCI train/test split
        baseline: nearest centroid over 16 features
        proposed_method: diagonal variance-calibrated class prototypes
        variance_shrinkage: 0.05
        ablation: z-score normalized nearest centroid
        metrics:
          - accuracy
          - macro_f1
          - baseline_accuracy
          - accuracy_delta_vs_baseline
          - zscore_centroid_accuracy
          - accuracy_delta_vs_zscore
          - test_rows
          - train_rows
          - dataset_rows
          - class_count
          - accuracy_standard_error
          - variance_shrinkage
        """
    )


def _dataset_csv() -> str:
    return textwrap.dedent(
        """\
        row_id,split,signal,noise,label
        1,train,0,0,0
        2,train,0,1,0
        3,train,1,0,1
        4,train,1,1,1
        5,test,0,0,0
        6,test,0,1,0
        7,test,1,0,1
        8,test,1,1,1
        """
    )


def _text_dataset_csv() -> str:
    return textwrap.dedent(
        """\
        row_id,split,text,label
        1,train,graph signal improves retrieval,positive
        2,train,graph memory improves search,positive
        3,train,random noise hurts ranking,negative
        4,train,broken cache hurts recall,negative
        5,test,graph signal improves search,positive
        6,test,broken random noise hurts search,negative
        7,test,graph memory improves retrieval,positive
        8,test,cache noise hurts ranking,negative
        """
    )


def _run_py() -> str:
    return textwrap.dedent(
        """\
        from __future__ import annotations

        import csv
        import json
        import sys
        from datetime import datetime, timezone
        from pathlib import Path


        def main() -> int:
            root = Path(__file__).resolve().parent
            logs_dir = root / "logs"
            artifacts_dir = root / "artifacts"
            logs_dir.mkdir(exist_ok=True)
            artifacts_dir.mkdir(exist_ok=True)
            log_path = logs_dir / "run.log"
            metrics_path = root / "metrics.json"
            predictions_path = artifacts_dir / "predictions.csv"
            summary_path = artifacts_dir / "summary.md"

            try:
                rows = _read_rows(root / "data" / "tabular_baseline.csv")
                test_rows = [row for row in rows if row["split"] == "test"]
                predictions = [_predict(row) for row in test_rows]
                correct = sum(
                    int(prediction == int(row["label"]))
                    for row, prediction in zip(test_rows, predictions, strict=True)
                )
                accuracy = correct / len(test_rows)

                _write_predictions(predictions_path, test_rows, predictions)
                summary_path.write_text(
                    "# Tabular Baseline Summary\\n\\n"
                    f"- Test rows: {len(test_rows)}\\n"
                    f"- Accuracy: {accuracy:.3f}\\n",
                    encoding="utf-8",
                )
                payload = {
                    "status": "success",
                    "task_id": "tabular_baseline",
                    "metrics": {
                        "accuracy": accuracy,
                        "test_rows": float(len(test_rows)),
                    },
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
                metrics_path.write_text(
                    json.dumps(payload, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                log_path.write_text("tabular baseline completed successfully\\n", encoding="utf-8")
                return 0
            except Exception as exc:
                payload = {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "metrics": {},
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
                metrics_path.write_text(
                    json.dumps(payload, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                log_path.write_text(
                    f"tabular baseline failed: {type(exc).__name__}: {exc}\\n",
                    encoding="utf-8",
                )
                return 1


        def _read_rows(path: Path) -> list[dict[str, str]]:
            with path.open("r", encoding="utf-8", newline="") as handle:
                return list(csv.DictReader(handle))


        def _predict(row: dict[str, str]) -> int:
            return int(int(row["signal"]) >= 1)


        def _write_predictions(
            path: Path,
            rows: list[dict[str, str]],
            predictions: list[int],
        ) -> None:
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["row_id", "label", "prediction", "correct"],
                )
                writer.writeheader()
                for row, prediction in zip(rows, predictions, strict=True):
                    label = int(row["label"])
                    writer.writerow(
                        {
                            "row_id": row["row_id"],
                            "label": label,
                            "prediction": prediction,
                            "correct": int(prediction == label),
                        }
                    )


        if __name__ == "__main__":
            sys.exit(main())
        """
    )


def _text_run_py() -> str:
    return textwrap.dedent(
        """\
        from __future__ import annotations

        import csv
        import json
        import re
        import sys
        from collections import Counter
        from datetime import datetime, timezone
        from pathlib import Path


        def main() -> int:
            root = Path(__file__).resolve().parent
            logs_dir = root / "logs"
            artifacts_dir = root / "artifacts"
            logs_dir.mkdir(exist_ok=True)
            artifacts_dir.mkdir(exist_ok=True)
            log_path = logs_dir / "run.log"
            metrics_path = root / "metrics.json"
            predictions_path = artifacts_dir / "predictions.csv"
            summary_path = artifacts_dir / "summary.md"
            vocabulary_path = artifacts_dir / "vocabulary.txt"

            try:
                rows = _read_rows(root / "data" / "text_classifier_stub.csv")
                train_rows = [row for row in rows if row["split"] == "train"]
                test_rows = [row for row in rows if row["split"] == "test"]
                vocabulary = _vocabulary(train_rows)
                predictions = [_predict(row["text"]) for row in test_rows]
                correct = sum(
                    int(prediction == row["label"])
                    for row, prediction in zip(test_rows, predictions, strict=True)
                )
                accuracy = correct / len(test_rows)

                vocabulary_path.write_text("\\n".join(vocabulary) + "\\n", encoding="utf-8")
                _write_predictions(predictions_path, test_rows, predictions)
                summary_path.write_text(
                    "# Text Classifier Stub Summary\\n\\n"
                    f"- Test rows: {len(test_rows)}\\n"
                    f"- Vocabulary size: {len(vocabulary)}\\n"
                    f"- Accuracy: {accuracy:.3f}\\n",
                    encoding="utf-8",
                )
                payload = {
                    "status": "success",
                    "task_id": "text_classifier_stub",
                    "metrics": {
                        "accuracy": accuracy,
                        "test_rows": float(len(test_rows)),
                        "vocabulary_size": float(len(vocabulary)),
                    },
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
                metrics_path.write_text(
                    json.dumps(payload, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                log_path.write_text("text classifier stub completed successfully\\n", encoding="utf-8")
                return 0
            except Exception as exc:
                payload = {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "metrics": {},
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
                metrics_path.write_text(
                    json.dumps(payload, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                log_path.write_text(
                    f"text classifier stub failed: {type(exc).__name__}: {exc}\\n",
                    encoding="utf-8",
                )
                return 1


        def _read_rows(path: Path) -> list[dict[str, str]]:
            with path.open("r", encoding="utf-8", newline="") as handle:
                return list(csv.DictReader(handle))


        def _vocabulary(rows: list[dict[str, str]]) -> list[str]:
            tokens: Counter[str] = Counter()
            for row in rows:
                tokens.update(_tokens(row["text"]))
            return sorted(tokens)


        def _tokens(text: str) -> list[str]:
            return re.findall(r"[a-z]+", text.casefold())


        def _predict(text: str) -> str:
            tokens = set(_tokens(text))
            if {"graph", "improves"} & tokens and "hurts" not in tokens:
                return "positive"
            return "negative"


        def _write_predictions(
            path: Path,
            rows: list[dict[str, str]],
            predictions: list[str],
        ) -> None:
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["row_id", "label", "prediction", "correct"],
                )
                writer.writeheader()
                for row, prediction in zip(rows, predictions, strict=True):
                    writer.writerow(
                        {
                            "row_id": row["row_id"],
                            "label": row["label"],
                            "prediction": prediction,
                            "correct": int(prediction == row["label"]),
                        }
                    )


        if __name__ == "__main__":
            sys.exit(main())
        """
    )


def _pendigits_run_py() -> str:
    return textwrap.dedent(
        """\
        from __future__ import annotations

        import csv
        import hashlib
        import json
        import math
        import sys
        from collections import defaultdict
        from datetime import datetime, timezone
        from pathlib import Path
        from urllib.request import urlopen


        FEATURE_COUNT = 16
        SOURCE_FILES = {
            "train": (
                "pendigits.tra",
                "https://archive.ics.uci.edu/ml/machine-learning-databases/pendigits/pendigits.tra",
            ),
            "test": (
                "pendigits.tes",
                "https://archive.ics.uci.edu/ml/machine-learning-databases/pendigits/pendigits.tes",
            ),
        }


        def main() -> int:
            root = Path(__file__).resolve().parent
            data_dir = root / "data"
            logs_dir = root / "logs"
            artifacts_dir = root / "artifacts"
            data_dir.mkdir(exist_ok=True)
            logs_dir.mkdir(exist_ok=True)
            artifacts_dir.mkdir(exist_ok=True)
            log_path = logs_dir / "run.log"
            metrics_path = root / "metrics.json"
            merged_csv_path = data_dir / "pendigits_centroid_baseline.csv"
            predictions_path = artifacts_dir / "predictions.csv"
            ablation_path = artifacts_dir / "ablation.csv"
            summary_path = artifacts_dir / "summary.md"
            sources_path = artifacts_dir / "dataset_sources.json"

            try:
                source_records = _ensure_raw_files(data_dir)
                rows = _load_rows(data_dir)
                train_rows = [row for row in rows if row["split"] == "train"]
                test_rows = [row for row in rows if row["split"] == "test"]
                if len(test_rows) < 1000:
                    raise ValueError(
                        f"Pendigits official test split is unexpectedly small: {len(test_rows)}"
                    )
                _write_merged_csv(merged_csv_path, rows)

                baseline = _evaluate(train_rows, test_rows, feature_count=16)
                ablation = _evaluate(train_rows, test_rows, feature_count=8)
                accuracy = baseline["accuracy"]
                accuracy_standard_error = math.sqrt(
                    max(accuracy * (1.0 - accuracy), 0.0) / len(test_rows)
                )

                _write_predictions(predictions_path, baseline["predictions"])
                _write_ablation(ablation_path, baseline, ablation, len(test_rows))
                _write_summary(
                    summary_path,
                    source_records,
                    train_rows=len(train_rows),
                    test_rows=len(test_rows),
                    baseline=baseline,
                    ablation=ablation,
                    accuracy_standard_error=accuracy_standard_error,
                )
                sources_path.write_text(
                    json.dumps(
                        {
                            "dataset": "UCI Pen-Based Recognition of Handwritten Digits",
                            "license": "CC BY 4.0",
                            "real_dataset": True,
                            "split_policy": "official pendigits.tra / pendigits.tes split",
                            "sources": source_records,
                            "merged_csv": merged_csv_path.as_posix(),
                        },
                        indent=2,
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )
                payload = {
                    "status": "success",
                    "task_id": "pendigits_centroid_baseline",
                    "metrics": {
                        "accuracy": accuracy,
                        "macro_f1": baseline["macro_f1"],
                        "test_rows": float(len(test_rows)),
                        "train_rows": float(len(train_rows)),
                        "dataset_rows": float(len(rows)),
                        "class_count": float(len({row["label"] for row in rows})),
                        "ablation_accuracy_first8": ablation["accuracy"],
                        "accuracy_delta_vs_ablation": accuracy - ablation["accuracy"],
                        "accuracy_standard_error": accuracy_standard_error,
                    },
                    "metadata": {
                        "dataset": "UCI Pendigits",
                        "dataset_license": "CC BY 4.0",
                        "real_dataset": True,
                        "source_urls": [record["url"] for record in source_records],
                        "split_policy": "official train/test split",
                        "baseline": "nearest centroid over 16 features",
                        "ablation": "nearest centroid over first 8 features",
                    },
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
                metrics_path.write_text(
                    json.dumps(payload, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                log_path.write_text(
                    "pendigits centroid baseline completed successfully\\n"
                    f"train_rows={len(train_rows)} test_rows={len(test_rows)} "
                    f"accuracy={accuracy:.6f}\\n",
                    encoding="utf-8",
                )
                return 0
            except Exception as exc:
                payload = {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "metrics": {},
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
                metrics_path.write_text(
                    json.dumps(payload, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                log_path.write_text(
                    f"pendigits centroid baseline failed: {type(exc).__name__}: {exc}\\n",
                    encoding="utf-8",
                )
                return 1


        def _ensure_raw_files(data_dir: Path) -> list[dict[str, object]]:
            records = []
            for split, (filename, url) in SOURCE_FILES.items():
                path = data_dir / filename
                if path.exists():
                    status = "cached"
                else:
                    with urlopen(url, timeout=30) as response:
                        payload = response.read()
                    path.write_bytes(payload)
                    status = "downloaded"
                records.append(
                    {
                        "split": split,
                        "filename": filename,
                        "url": url,
                        "path": path.as_posix(),
                        "status": status,
                        "bytes": path.stat().st_size,
                        "sha256": _file_sha256(path),
                    }
                )
            return records


        def _load_rows(data_dir: Path) -> list[dict[str, object]]:
            rows = []
            for split, (filename, _url) in SOURCE_FILES.items():
                path = data_dir / filename
                for row_index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
                    stripped = line.strip()
                    if not stripped:
                        continue
                    parts = [int(piece.strip()) for piece in stripped.split(",") if piece.strip()]
                    if len(parts) != FEATURE_COUNT + 1:
                        raise ValueError(
                            f"{filename}:{row_index + 1} expected 17 comma values, got {len(parts)}"
                        )
                    rows.append(
                        {
                            "row_id": f"{split}_{row_index + 1}",
                            "split": split,
                            "features": [float(value) for value in parts[:FEATURE_COUNT]],
                            "label": int(parts[-1]),
                        }
                    )
            return rows


        def _file_sha256(path: Path) -> str:
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest()


        def _write_merged_csv(path: Path, rows: list[dict[str, object]]) -> None:
            fieldnames = ["row_id", "split", *[f"x{index}" for index in range(FEATURE_COUNT)], "label"]
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                for row in rows:
                    features = _features(row)
                    writer.writerow(
                        {
                            "row_id": row["row_id"],
                            "split": row["split"],
                            **{f"x{index}": features[index] for index in range(FEATURE_COUNT)},
                            "label": row["label"],
                        }
                    )


        def _evaluate(
            train_rows: list[dict[str, object]],
            test_rows: list[dict[str, object]],
            *,
            feature_count: int,
        ) -> dict[str, object]:
            centroids = _centroids(train_rows, feature_count=feature_count)
            predictions = []
            correct = 0
            for row in test_rows:
                label = int(row["label"])
                prediction = _predict(_features(row)[:feature_count], centroids)
                correct += int(prediction == label)
                predictions.append(
                    {
                        "row_id": row["row_id"],
                        "label": label,
                        "prediction": prediction,
                        "correct": int(prediction == label),
                    }
                )
            accuracy = correct / len(test_rows)
            macro_f1 = _macro_f1(
                [int(row["label"]) for row in test_rows],
                [int(row["prediction"]) for row in predictions],
            )
            return {
                "accuracy": accuracy,
                "macro_f1": macro_f1,
                "feature_count": feature_count,
                "predictions": predictions,
            }


        def _centroids(
            rows: list[dict[str, object]],
            *,
            feature_count: int,
        ) -> dict[int, list[float]]:
            sums: dict[int, list[float]] = defaultdict(lambda: [0.0] * feature_count)
            counts: dict[int, int] = defaultdict(int)
            for row in rows:
                label = int(row["label"])
                counts[label] += 1
                for index, value in enumerate(_features(row)[:feature_count]):
                    sums[label][index] += value
            return {
                label: [value / counts[label] for value in sums[label]]
                for label in sorted(sums)
            }


        def _predict(features: list[float], centroids: dict[int, list[float]]) -> int:
            best_label = None
            best_distance = None
            for label, centroid in centroids.items():
                distance = sum((value - centroid[index]) ** 2 for index, value in enumerate(features))
                if best_distance is None or distance < best_distance:
                    best_label = label
                    best_distance = distance
            if best_label is None:
                raise ValueError("no centroid available")
            return best_label


        def _macro_f1(labels: list[int], predictions: list[int]) -> float:
            classes = sorted(set(labels) | set(predictions))
            scores = []
            for klass in classes:
                tp = sum(1 for label, pred in zip(labels, predictions, strict=True) if label == klass and pred == klass)
                fp = sum(1 for label, pred in zip(labels, predictions, strict=True) if label != klass and pred == klass)
                fn = sum(1 for label, pred in zip(labels, predictions, strict=True) if label == klass and pred != klass)
                precision = tp / (tp + fp) if tp + fp else 0.0
                recall = tp / (tp + fn) if tp + fn else 0.0
                f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
                scores.append(f1)
            return sum(scores) / len(scores)


        def _features(row: dict[str, object]) -> list[float]:
            features = row["features"]
            if not isinstance(features, list):
                raise TypeError("row features must be a list")
            return [float(value) for value in features]


        def _write_predictions(path: Path, predictions: list[dict[str, object]]) -> None:
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["row_id", "label", "prediction", "correct"],
                )
                writer.writeheader()
                writer.writerows(predictions)


        def _write_ablation(
            path: Path,
            baseline: dict[str, object],
            ablation: dict[str, object],
            test_rows: int,
        ) -> None:
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["model", "features_used", "accuracy", "macro_f1", "test_rows"],
                )
                writer.writeheader()
                for model, result in (("baseline_full16", baseline), ("ablation_first8", ablation)):
                    writer.writerow(
                        {
                            "model": model,
                            "features_used": result["feature_count"],
                            "accuracy": f"{float(result['accuracy']):.6f}",
                            "macro_f1": f"{float(result['macro_f1']):.6f}",
                            "test_rows": test_rows,
                        }
                    )


        def _write_summary(
            path: Path,
            source_records: list[dict[str, object]],
            *,
            train_rows: int,
            test_rows: int,
            baseline: dict[str, object],
            ablation: dict[str, object],
            accuracy_standard_error: float,
        ) -> None:
            urls = "\\n".join(f"- {record['url']} ({record['status']})" for record in source_records)
            path.write_text(
                "# UCI Pendigits Centroid Baseline Summary\\n\\n"
                "## Dataset\\n\\n"
                "- Name: UCI Pen-Based Recognition of Handwritten Digits\\n"
                "- Split: official `pendigits.tra` train and `pendigits.tes` test\\n"
                f"- Train rows: {train_rows}\\n"
                f"- Test rows: {test_rows}\\n"
                f"{urls}\\n\\n"
                "## Results\\n\\n"
                f"- Baseline accuracy: {float(baseline['accuracy']):.6f}\\n"
                f"- Baseline macro F1: {float(baseline['macro_f1']):.6f}\\n"
                f"- Accuracy standard error: {accuracy_standard_error:.6f}\\n\\n"
                "## Ablation\\n\\n"
                f"- First-8-features accuracy: {float(ablation['accuracy']):.6f}\\n"
                f"- Accuracy delta vs ablation: {float(baseline['accuracy']) - float(ablation['accuracy']):.6f}\\n",
                encoding="utf-8",
            )


        if __name__ == "__main__":
            sys.exit(main())
        """
    )


def _pendigits_prototype_shrinkage_run_py() -> str:
    return textwrap.dedent(
        """\
        from __future__ import annotations

        import csv
        import hashlib
        import json
        import math
        import sys
        from collections import defaultdict
        from datetime import datetime, timezone
        from pathlib import Path
        from urllib.request import urlopen


        FEATURE_COUNT = 16
        SHRINKAGE_ALPHA = 0.10
        SOURCE_FILES = {
            "train": (
                "pendigits.tra",
                "https://archive.ics.uci.edu/ml/machine-learning-databases/pendigits/pendigits.tra",
            ),
            "test": (
                "pendigits.tes",
                "https://archive.ics.uci.edu/ml/machine-learning-databases/pendigits/pendigits.tes",
            ),
        }


        def main() -> int:
            root = Path(__file__).resolve().parent
            data_dir = root / "data"
            logs_dir = root / "logs"
            artifacts_dir = root / "artifacts"
            data_dir.mkdir(exist_ok=True)
            logs_dir.mkdir(exist_ok=True)
            artifacts_dir.mkdir(exist_ok=True)
            log_path = logs_dir / "run.log"
            metrics_path = root / "metrics.json"
            merged_csv_path = data_dir / "pendigits_prototype_shrinkage.csv"
            predictions_path = artifacts_dir / "predictions.csv"
            ablation_path = artifacts_dir / "ablation.csv"
            summary_path = artifacts_dir / "summary.md"
            sources_path = artifacts_dir / "dataset_sources.json"
            innovation_path = artifacts_dir / "innovation_evidence.json"

            try:
                source_records = _ensure_raw_files(data_dir)
                rows = _load_rows(data_dir)
                train_rows = [row for row in rows if row["split"] == "train"]
                test_rows = [row for row in rows if row["split"] == "test"]
                if len(test_rows) < 1000:
                    raise ValueError(
                        f"Pendigits official test split is unexpectedly small: {len(test_rows)}"
                    )
                _write_merged_csv(merged_csv_path, rows)

                baseline = _evaluate(train_rows, test_rows, feature_count=16)
                ablation = _evaluate(train_rows, test_rows, feature_count=8)
                global_mean = _global_mean(train_rows, feature_count=16)
                baseline_centroids = _centroids(train_rows, feature_count=16)
                shrinkage_centroids = _shrink_centroids(
                    baseline_centroids,
                    global_mean,
                    alpha=SHRINKAGE_ALPHA,
                )
                shrinkage = _evaluate_with_centroids(test_rows, shrinkage_centroids)
                accuracy = shrinkage["accuracy"]
                baseline_accuracy = baseline["accuracy"]
                ablation_accuracy = ablation["accuracy"]
                accuracy_standard_error = math.sqrt(
                    max(accuracy * (1.0 - accuracy), 0.0) / len(test_rows)
                )
                prototype_shift = _mean_l2_shift(baseline_centroids, shrinkage_centroids)

                _write_predictions(predictions_path, shrinkage["predictions"])
                _write_ablation(
                    ablation_path,
                    baseline=baseline,
                    shrinkage=shrinkage,
                    ablation=ablation,
                    test_rows=len(test_rows),
                )
                _write_summary(
                    summary_path,
                    source_records,
                    train_rows=len(train_rows),
                    test_rows=len(test_rows),
                    baseline=baseline,
                    shrinkage=shrinkage,
                    ablation=ablation,
                    accuracy_standard_error=accuracy_standard_error,
                    prototype_shift=prototype_shift,
                )
                sources_path.write_text(
                    json.dumps(
                        {
                            "dataset": "UCI Pen-Based Recognition of Handwritten Digits",
                            "license": "CC BY 4.0",
                            "real_dataset": True,
                            "split_policy": "official pendigits.tra / pendigits.tes split",
                            "sources": source_records,
                            "merged_csv": merged_csv_path.as_posix(),
                        },
                        indent=2,
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )
                innovation_payload = {
                    "proposed_method": "class prototype shrinkage toward global mean",
                    "mechanism": (
                        "Each class centroid is moved by alpha toward the global "
                        "feature mean before nearest-centroid classification."
                    ),
                    "shrinkage_alpha": SHRINKAGE_ALPHA,
                    "prototype_shift_l2_mean": prototype_shift,
                    "baseline_accuracy": baseline_accuracy,
                    "candidate_accuracy": accuracy,
                    "accuracy_delta_vs_baseline": accuracy - baseline_accuracy,
                    "accuracy_delta_vs_ablation": accuracy - ablation_accuracy,
                    "interpretation": _innovation_interpretation(accuracy - baseline_accuracy),
                    "support_artifacts": [
                        "metrics.json",
                        "artifacts/predictions.csv",
                        "artifacts/ablation.csv",
                        "artifacts/summary.md",
                    ],
                }
                innovation_path.write_text(
                    json.dumps(innovation_payload, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                payload = {
                    "status": "success",
                    "task_id": "pendigits_prototype_shrinkage",
                    "metrics": {
                        "accuracy": accuracy,
                        "macro_f1": shrinkage["macro_f1"],
                        "baseline_accuracy": baseline_accuracy,
                        "accuracy_delta_vs_baseline": accuracy - baseline_accuracy,
                        "test_rows": float(len(test_rows)),
                        "train_rows": float(len(train_rows)),
                        "dataset_rows": float(len(rows)),
                        "class_count": float(len({row["label"] for row in rows})),
                        "ablation_accuracy_first8": ablation_accuracy,
                        "accuracy_delta_vs_ablation": accuracy - ablation_accuracy,
                        "accuracy_standard_error": accuracy_standard_error,
                        "prototype_shift_l2_mean": prototype_shift,
                        "shrinkage_alpha": SHRINKAGE_ALPHA,
                    },
                    "metadata": {
                        "dataset": "UCI Pendigits",
                        "dataset_license": "CC BY 4.0",
                        "real_dataset": True,
                        "source_urls": [record["url"] for record in source_records],
                        "split_policy": "official train/test split",
                        "baseline": "nearest centroid over 16 features",
                        "ablation": "nearest centroid over first 8 features",
                        "proposed_method": "class prototype shrinkage toward global mean",
                        "novel_contribution": "prototype shrinkage calibration",
                        "innovation_artifact": innovation_path.as_posix(),
                    },
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
                metrics_path.write_text(
                    json.dumps(payload, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                log_path.write_text(
                    "pendigits prototype shrinkage completed successfully\\n"
                    f"train_rows={len(train_rows)} test_rows={len(test_rows)} "
                    f"accuracy={accuracy:.6f} baseline_accuracy={baseline_accuracy:.6f} "
                    f"delta={accuracy - baseline_accuracy:.6f}\\n",
                    encoding="utf-8",
                )
                return 0
            except Exception as exc:
                payload = {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "metrics": {},
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
                metrics_path.write_text(
                    json.dumps(payload, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                log_path.write_text(
                    f"pendigits prototype shrinkage failed: {type(exc).__name__}: {exc}\\n",
                    encoding="utf-8",
                )
                return 1


        def _ensure_raw_files(data_dir: Path) -> list[dict[str, object]]:
            records = []
            for split, (filename, url) in SOURCE_FILES.items():
                path = data_dir / filename
                if path.exists():
                    status = "cached"
                else:
                    with urlopen(url, timeout=30) as response:
                        payload = response.read()
                    path.write_bytes(payload)
                    status = "downloaded"
                records.append(
                    {
                        "split": split,
                        "filename": filename,
                        "url": url,
                        "path": path.as_posix(),
                        "status": status,
                        "bytes": path.stat().st_size,
                        "sha256": _file_sha256(path),
                    }
                )
            return records


        def _load_rows(data_dir: Path) -> list[dict[str, object]]:
            rows = []
            for split, (filename, _url) in SOURCE_FILES.items():
                path = data_dir / filename
                for row_index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
                    stripped = line.strip()
                    if not stripped:
                        continue
                    parts = [int(piece.strip()) for piece in stripped.split(",") if piece.strip()]
                    if len(parts) != FEATURE_COUNT + 1:
                        raise ValueError(
                            f"{filename}:{row_index + 1} expected 17 comma values, got {len(parts)}"
                        )
                    rows.append(
                        {
                            "row_id": f"{split}_{row_index + 1}",
                            "split": split,
                            "features": [float(value) for value in parts[:FEATURE_COUNT]],
                            "label": int(parts[-1]),
                        }
                    )
            return rows


        def _file_sha256(path: Path) -> str:
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest()


        def _write_merged_csv(path: Path, rows: list[dict[str, object]]) -> None:
            fieldnames = ["row_id", "split", *[f"x{index}" for index in range(FEATURE_COUNT)], "label"]
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                for row in rows:
                    features = _features(row)
                    writer.writerow(
                        {
                            "row_id": row["row_id"],
                            "split": row["split"],
                            **{f"x{index}": features[index] for index in range(FEATURE_COUNT)},
                            "label": row["label"],
                        }
                    )


        def _evaluate(
            train_rows: list[dict[str, object]],
            test_rows: list[dict[str, object]],
            *,
            feature_count: int,
        ) -> dict[str, object]:
            return _evaluate_with_centroids(
                test_rows,
                _centroids(train_rows, feature_count=feature_count),
            ) | {"feature_count": feature_count}


        def _evaluate_with_centroids(
            test_rows: list[dict[str, object]],
            centroids: dict[int, list[float]],
        ) -> dict[str, object]:
            predictions = []
            correct = 0
            feature_count = len(next(iter(centroids.values())))
            for row in test_rows:
                label = int(row["label"])
                prediction = _predict(_features(row)[:feature_count], centroids)
                correct += int(prediction == label)
                predictions.append(
                    {
                        "row_id": row["row_id"],
                        "label": label,
                        "prediction": prediction,
                        "correct": int(prediction == label),
                    }
                )
            accuracy = correct / len(test_rows)
            macro_f1 = _macro_f1(
                [int(row["label"]) for row in test_rows],
                [int(row["prediction"]) for row in predictions],
            )
            return {
                "accuracy": accuracy,
                "macro_f1": macro_f1,
                "feature_count": feature_count,
                "predictions": predictions,
            }


        def _centroids(
            rows: list[dict[str, object]],
            *,
            feature_count: int,
        ) -> dict[int, list[float]]:
            sums: dict[int, list[float]] = defaultdict(lambda: [0.0] * feature_count)
            counts: dict[int, int] = defaultdict(int)
            for row in rows:
                label = int(row["label"])
                counts[label] += 1
                for index, value in enumerate(_features(row)[:feature_count]):
                    sums[label][index] += value
            return {
                label: [value / counts[label] for value in sums[label]]
                for label in sorted(sums)
            }


        def _global_mean(
            rows: list[dict[str, object]],
            *,
            feature_count: int,
        ) -> list[float]:
            sums = [0.0] * feature_count
            for row in rows:
                for index, value in enumerate(_features(row)[:feature_count]):
                    sums[index] += value
            return [value / len(rows) for value in sums]


        def _shrink_centroids(
            centroids: dict[int, list[float]],
            global_mean: list[float],
            *,
            alpha: float,
        ) -> dict[int, list[float]]:
            return {
                label: [
                    (1.0 - alpha) * value + alpha * global_mean[index]
                    for index, value in enumerate(centroid)
                ]
                for label, centroid in centroids.items()
            }


        def _mean_l2_shift(
            original: dict[int, list[float]],
            shifted: dict[int, list[float]],
        ) -> float:
            distances = []
            for label, centroid in original.items():
                shifted_centroid = shifted[label]
                distances.append(
                    math.sqrt(
                        sum(
                            (value - shifted_centroid[index]) ** 2
                            for index, value in enumerate(centroid)
                        )
                    )
                )
            return sum(distances) / len(distances)


        def _predict(features: list[float], centroids: dict[int, list[float]]) -> int:
            best_label = None
            best_distance = None
            for label, centroid in centroids.items():
                distance = sum((value - centroid[index]) ** 2 for index, value in enumerate(features))
                if best_distance is None or distance < best_distance:
                    best_label = label
                    best_distance = distance
            if best_label is None:
                raise ValueError("no centroid available")
            return best_label


        def _macro_f1(labels: list[int], predictions: list[int]) -> float:
            classes = sorted(set(labels) | set(predictions))
            scores = []
            for klass in classes:
                tp = sum(1 for label, pred in zip(labels, predictions, strict=True) if label == klass and pred == klass)
                fp = sum(1 for label, pred in zip(labels, predictions, strict=True) if label != klass and pred == klass)
                fn = sum(1 for label, pred in zip(labels, predictions, strict=True) if label == klass and pred != klass)
                precision = tp / (tp + fp) if tp + fp else 0.0
                recall = tp / (tp + fn) if tp + fn else 0.0
                f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
                scores.append(f1)
            return sum(scores) / len(scores)


        def _features(row: dict[str, object]) -> list[float]:
            features = row["features"]
            if not isinstance(features, list):
                raise TypeError("row features must be a list")
            return [float(value) for value in features]


        def _write_predictions(path: Path, predictions: list[dict[str, object]]) -> None:
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["row_id", "label", "prediction", "correct"],
                )
                writer.writeheader()
                writer.writerows(predictions)


        def _write_ablation(
            path: Path,
            *,
            baseline: dict[str, object],
            shrinkage: dict[str, object],
            ablation: dict[str, object],
            test_rows: int,
        ) -> None:
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["model", "features_used", "accuracy", "macro_f1", "test_rows"],
                )
                writer.writeheader()
                for model, result in (
                    ("baseline_full16", baseline),
                    ("prototype_shrinkage_full16", shrinkage),
                    ("ablation_first8", ablation),
                ):
                    writer.writerow(
                        {
                            "model": model,
                            "features_used": result["feature_count"],
                            "accuracy": f"{float(result['accuracy']):.6f}",
                            "macro_f1": f"{float(result['macro_f1']):.6f}",
                            "test_rows": test_rows,
                        }
                    )


        def _write_summary(
            path: Path,
            source_records: list[dict[str, object]],
            *,
            train_rows: int,
            test_rows: int,
            baseline: dict[str, object],
            shrinkage: dict[str, object],
            ablation: dict[str, object],
            accuracy_standard_error: float,
            prototype_shift: float,
        ) -> None:
            urls = "\\n".join(f"- {record['url']} ({record['status']})" for record in source_records)
            delta = float(shrinkage["accuracy"]) - float(baseline["accuracy"])
            path.write_text(
                "# UCI Pendigits Prototype Shrinkage Summary\\n\\n"
                "## Dataset\\n\\n"
                "- Name: UCI Pen-Based Recognition of Handwritten Digits\\n"
                "- Split: official `pendigits.tra` train and `pendigits.tes` test\\n"
                f"- Train rows: {train_rows}\\n"
                f"- Test rows: {test_rows}\\n"
                f"{urls}\\n\\n"
                "## Method Candidate\\n\\n"
                "- Proposed method: class prototype shrinkage toward the global feature mean\\n"
                f"- Shrinkage alpha: {SHRINKAGE_ALPHA:.2f}\\n"
                f"- Mean prototype shift L2: {prototype_shift:.6f}\\n\\n"
                "## Results\\n\\n"
                f"- Candidate accuracy: {float(shrinkage['accuracy']):.6f}\\n"
                f"- Candidate macro F1: {float(shrinkage['macro_f1']):.6f}\\n"
                f"- Baseline accuracy: {float(baseline['accuracy']):.6f}\\n"
                f"- Accuracy delta vs baseline: {delta:.6f}\\n"
                f"- Accuracy standard error: {accuracy_standard_error:.6f}\\n\\n"
                "## Ablation\\n\\n"
                f"- First-8-features accuracy: {float(ablation['accuracy']):.6f}\\n"
                f"- Accuracy delta vs ablation: {float(shrinkage['accuracy']) - float(ablation['accuracy']):.6f}\\n\\n"
                "## Interpretation\\n\\n"
                f"- {_innovation_interpretation(delta)}\\n",
                encoding="utf-8",
            )


        def _innovation_interpretation(delta: float) -> str:
            if delta > 0:
                return "The method candidate improved accuracy over the baseline in this run."
            if delta < 0:
                return "The method candidate underperformed the baseline in this run."
            return "The method candidate tied the baseline in this run; do not claim empirical gain."


        if __name__ == "__main__":
            sys.exit(main())
        """
    )


def _pendigits_variance_calibrated_run_py() -> str:
    return textwrap.dedent(
        """\
        from __future__ import annotations

        import csv
        import hashlib
        import json
        import math
        import sys
        from collections import defaultdict
        from datetime import datetime, timezone
        from pathlib import Path
        from urllib.request import urlopen


        FEATURE_COUNT = 16
        VARIANCE_SHRINKAGE = 0.05
        SOURCE_FILES = {
            "train": (
                "pendigits.tra",
                "https://archive.ics.uci.edu/ml/machine-learning-databases/pendigits/pendigits.tra",
            ),
            "test": (
                "pendigits.tes",
                "https://archive.ics.uci.edu/ml/machine-learning-databases/pendigits/pendigits.tes",
            ),
        }


        def main() -> int:
            root = Path(__file__).resolve().parent
            data_dir = root / "data"
            logs_dir = root / "logs"
            artifacts_dir = root / "artifacts"
            data_dir.mkdir(exist_ok=True)
            logs_dir.mkdir(exist_ok=True)
            artifacts_dir.mkdir(exist_ok=True)
            log_path = logs_dir / "run.log"
            metrics_path = root / "metrics.json"
            merged_csv_path = data_dir / "pendigits_variance_calibrated_prototypes.csv"
            predictions_path = artifacts_dir / "predictions.csv"
            ablation_path = artifacts_dir / "ablation.csv"
            summary_path = artifacts_dir / "summary.md"
            sources_path = artifacts_dir / "dataset_sources.json"
            innovation_path = artifacts_dir / "innovation_evidence.json"

            try:
                source_records = _ensure_raw_files(data_dir)
                rows = _load_rows(data_dir)
                train_rows = [row for row in rows if row["split"] == "train"]
                test_rows = [row for row in rows if row["split"] == "test"]
                if len(test_rows) < 1000:
                    raise ValueError(
                        f"Pendigits official test split is unexpectedly small: {len(test_rows)}"
                    )
                _write_merged_csv(merged_csv_path, rows)

                baseline = _evaluate_centroid(train_rows, test_rows)
                zscore = _evaluate_zscore_centroid(train_rows, test_rows)
                variance_model = _variance_model(
                    train_rows,
                    shrinkage=VARIANCE_SHRINKAGE,
                )
                calibrated = _evaluate_variance_model(test_rows, variance_model)
                accuracy = float(calibrated["accuracy"])
                baseline_accuracy = float(baseline["accuracy"])
                zscore_accuracy = float(zscore["accuracy"])
                accuracy_standard_error = math.sqrt(
                    max(accuracy * (1.0 - accuracy), 0.0) / len(test_rows)
                )
                delta_vs_baseline = accuracy - baseline_accuracy
                delta_vs_zscore = accuracy - zscore_accuracy

                _write_predictions(predictions_path, calibrated["predictions"])
                _write_ablation(
                    ablation_path,
                    baseline=baseline,
                    zscore=zscore,
                    calibrated=calibrated,
                    test_rows=len(test_rows),
                )
                sources_path.write_text(
                    json.dumps(source_records, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                _write_summary(
                    summary_path,
                    source_records,
                    train_rows=len(train_rows),
                    test_rows=len(test_rows),
                    baseline=baseline,
                    zscore=zscore,
                    calibrated=calibrated,
                    delta_vs_baseline=delta_vs_baseline,
                    delta_vs_zscore=delta_vs_zscore,
                    accuracy_standard_error=accuracy_standard_error,
                )
                innovation_path.write_text(
                    json.dumps(
                        {
                            "accuracy_delta_vs_baseline": delta_vs_baseline,
                            "accuracy_delta_vs_zscore": delta_vs_zscore,
                            "baseline_accuracy": baseline_accuracy,
                            "candidate_accuracy": accuracy,
                            "effect_direction": _effect_direction(delta_vs_baseline),
                            "mechanism": (
                                "Class prototypes are scored with per-class diagonal "
                                "feature variances and log-variance penalties."
                            ),
                            "proposed_method": "diagonal variance-calibrated class prototypes",
                            "support_artifacts": [
                                "metrics.json",
                                "artifacts/predictions.csv",
                                "artifacts/ablation.csv",
                                "artifacts/summary.md",
                            ],
                            "variance_shrinkage": VARIANCE_SHRINKAGE,
                        },
                        indent=2,
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )
                metrics = {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "metadata": {
                        "ablation": "z-score normalized nearest centroid",
                        "baseline": "nearest centroid over 16 features",
                        "dataset": "UCI Pendigits",
                        "dataset_license": "CC BY 4.0",
                        "innovation_artifact": innovation_path.as_posix(),
                        "novel_contribution": "diagonal variance-calibrated prototypes",
                        "proposed_method": "diagonal variance-calibrated class prototypes",
                        "real_dataset": True,
                        "source_urls": [record["url"] for record in source_records],
                        "split_policy": "official train/test split",
                    },
                    "metrics": {
                        "accuracy": accuracy,
                        "macro_f1": float(calibrated["macro_f1"]),
                        "baseline_accuracy": baseline_accuracy,
                        "accuracy_delta_vs_baseline": delta_vs_baseline,
                        "zscore_centroid_accuracy": zscore_accuracy,
                        "accuracy_delta_vs_zscore": delta_vs_zscore,
                        "test_rows": float(len(test_rows)),
                        "train_rows": float(len(train_rows)),
                        "dataset_rows": float(len(rows)),
                        "class_count": float(len(_labels(train_rows))),
                        "accuracy_standard_error": accuracy_standard_error,
                        "variance_shrinkage": VARIANCE_SHRINKAGE,
                    },
                    "status": "success",
                    "task_id": "pendigits_variance_calibrated_prototypes",
                }
                metrics_path.write_text(
                    json.dumps(metrics, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                log_path.write_text(
                    "pendigits variance-calibrated prototypes completed successfully\\n"
                    f"train_rows={len(train_rows)} test_rows={len(test_rows)} "
                    f"accuracy={accuracy:.6f} baseline_accuracy={baseline_accuracy:.6f} "
                    f"delta={delta_vs_baseline:.6f}\\n",
                    encoding="utf-8",
                )
                return 0
            except Exception as exc:
                metrics_path.write_text(
                    json.dumps(
                        {
                            "error": str(exc),
                            "error_type": type(exc).__name__,
                            "generated_at": datetime.now(timezone.utc).isoformat(),
                            "metrics": {},
                            "status": "failed",
                        },
                        indent=2,
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )
                log_path.write_text(
                    f"pendigits variance-calibrated prototypes failed: "
                    f"{type(exc).__name__}: {exc}\\n",
                    encoding="utf-8",
                )
                return 1


        def _ensure_raw_files(data_dir: Path) -> list[dict[str, object]]:
            records = []
            for split, (filename, url) in SOURCE_FILES.items():
                path = data_dir / filename
                if path.exists():
                    status = "cached"
                else:
                    with urlopen(url, timeout=30) as response:
                        payload = response.read()
                    path.write_bytes(payload)
                    status = "downloaded"
                records.append(
                    {
                        "split": split,
                        "filename": filename,
                        "url": url,
                        "path": path.as_posix(),
                        "status": status,
                        "bytes": path.stat().st_size,
                        "sha256": _file_sha256(path),
                    }
                )
            return records


        def _load_rows(data_dir: Path) -> list[dict[str, object]]:
            rows = []
            for split, (filename, _url) in SOURCE_FILES.items():
                path = data_dir / filename
                for row_index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
                    stripped = line.strip()
                    if not stripped:
                        continue
                    parts = [int(piece.strip()) for piece in stripped.split(",") if piece.strip()]
                    if len(parts) != FEATURE_COUNT + 1:
                        raise ValueError(
                            f"{filename}:{row_index + 1} expected 17 comma values, got {len(parts)}"
                        )
                    rows.append(
                        {
                            "row_id": f"{split}_{row_index + 1}",
                            "split": split,
                            "features": [float(value) for value in parts[:FEATURE_COUNT]],
                            "label": int(parts[-1]),
                        }
                    )
            return rows


        def _file_sha256(path: Path) -> str:
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest()


        def _write_merged_csv(path: Path, rows: list[dict[str, object]]) -> None:
            fieldnames = ["row_id", "split", *[f"x{index}" for index in range(FEATURE_COUNT)], "label"]
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                for row in rows:
                    features = _features(row)
                    writer.writerow(
                        {
                            "row_id": row["row_id"],
                            "split": row["split"],
                            **{f"x{index}": features[index] for index in range(FEATURE_COUNT)},
                            "label": row["label"],
                        }
                    )


        def _evaluate_centroid(
            train_rows: list[dict[str, object]],
            test_rows: list[dict[str, object]],
        ) -> dict[str, object]:
            return _evaluate_with_centroids(test_rows, _centroids(train_rows))


        def _evaluate_zscore_centroid(
            train_rows: list[dict[str, object]],
            test_rows: list[dict[str, object]],
        ) -> dict[str, object]:
            means = _column_means(train_rows)
            stds = _column_stds(train_rows, means)
            transformed_train = [_transform_row(row, means, stds) for row in train_rows]
            transformed_test = [_transform_row(row, means, stds) for row in test_rows]
            return _evaluate_with_centroids(transformed_test, _centroids(transformed_train))


        def _evaluate_with_centroids(
            test_rows: list[dict[str, object]],
            centroids: dict[int, list[float]],
        ) -> dict[str, object]:
            predictions = []
            correct = 0
            for row in test_rows:
                label = int(row["label"])
                prediction = _predict_centroid(_features(row), centroids)
                correct += int(prediction == label)
                predictions.append(
                    {
                        "row_id": row["row_id"],
                        "label": label,
                        "prediction": prediction,
                        "correct": int(prediction == label),
                    }
                )
            accuracy = correct / len(test_rows)
            return {
                "accuracy": accuracy,
                "macro_f1": _macro_f1(
                    [int(row["label"]) for row in test_rows],
                    [int(row["prediction"]) for row in predictions],
                ),
                "predictions": predictions,
            }


        def _variance_model(
            train_rows: list[dict[str, object]],
            *,
            shrinkage: float,
        ) -> dict[str, object]:
            labels = _labels(train_rows)
            centroids = _centroids(train_rows)
            variances: dict[int, list[float]] = {}
            for label in labels:
                class_rows = [row for row in train_rows if int(row["label"]) == label]
                variances[label] = _class_variance(class_rows, centroids[label])
            global_variance = [
                sum(variances[label][index] for label in labels) / len(labels)
                for index in range(FEATURE_COUNT)
            ]
            calibrated = {
                label: [
                    max(
                        (1.0 - shrinkage) * variances[label][index]
                        + shrinkage * global_variance[index],
                        1e-6,
                    )
                    for index in range(FEATURE_COUNT)
                ]
                for label in labels
            }
            return {
                "centroids": centroids,
                "labels": labels,
                "variances": calibrated,
            }


        def _evaluate_variance_model(
            test_rows: list[dict[str, object]],
            model: dict[str, object],
        ) -> dict[str, object]:
            centroids = model["centroids"]
            variances = model["variances"]
            if not isinstance(centroids, dict) or not isinstance(variances, dict):
                raise TypeError("variance model is malformed")
            predictions = []
            correct = 0
            for row in test_rows:
                label = int(row["label"])
                prediction = _predict_variance(_features(row), centroids, variances)
                correct += int(prediction == label)
                predictions.append(
                    {
                        "row_id": row["row_id"],
                        "label": label,
                        "prediction": prediction,
                        "correct": int(prediction == label),
                    }
                )
            accuracy = correct / len(test_rows)
            return {
                "accuracy": accuracy,
                "macro_f1": _macro_f1(
                    [int(row["label"]) for row in test_rows],
                    [int(row["prediction"]) for row in predictions],
                ),
                "predictions": predictions,
            }


        def _centroids(rows: list[dict[str, object]]) -> dict[int, list[float]]:
            sums: dict[int, list[float]] = defaultdict(lambda: [0.0] * FEATURE_COUNT)
            counts: dict[int, int] = defaultdict(int)
            for row in rows:
                label = int(row["label"])
                counts[label] += 1
                for index, value in enumerate(_features(row)):
                    sums[label][index] += value
            return {
                label: [value / counts[label] for value in sums[label]]
                for label in sorted(sums)
            }


        def _class_variance(
            rows: list[dict[str, object]],
            mean: list[float],
        ) -> list[float]:
            values = [0.0] * FEATURE_COUNT
            for row in rows:
                for index, value in enumerate(_features(row)):
                    values[index] += (value - mean[index]) ** 2
            return [max(value / len(rows), 1e-6) for value in values]


        def _column_means(rows: list[dict[str, object]]) -> list[float]:
            sums = [0.0] * FEATURE_COUNT
            for row in rows:
                for index, value in enumerate(_features(row)):
                    sums[index] += value
            return [value / len(rows) for value in sums]


        def _column_stds(
            rows: list[dict[str, object]],
            means: list[float],
        ) -> list[float]:
            sums = [0.0] * FEATURE_COUNT
            for row in rows:
                for index, value in enumerate(_features(row)):
                    sums[index] += (value - means[index]) ** 2
            return [math.sqrt(value / len(rows)) or 1.0 for value in sums]


        def _transform_row(
            row: dict[str, object],
            means: list[float],
            stds: list[float],
        ) -> dict[str, object]:
            return {
                "row_id": row["row_id"],
                "split": row["split"],
                "features": [
                    (_features(row)[index] - means[index]) / stds[index]
                    for index in range(FEATURE_COUNT)
                ],
                "label": row["label"],
            }


        def _predict_centroid(features: list[float], centroids: dict[int, list[float]]) -> int:
            best_label = None
            best_distance = None
            for label, centroid in centroids.items():
                distance = sum((value - centroid[index]) ** 2 for index, value in enumerate(features))
                if best_distance is None or distance < best_distance:
                    best_label = label
                    best_distance = distance
            if best_label is None:
                raise ValueError("no centroid available")
            return best_label


        def _predict_variance(
            features: list[float],
            centroids: dict[int, list[float]],
            variances: dict[int, list[float]],
        ) -> int:
            best_label = None
            best_score = None
            for label, centroid in centroids.items():
                variance = variances[label]
                score = sum(
                    ((value - centroid[index]) ** 2) / variance[index]
                    + math.log(variance[index])
                    for index, value in enumerate(features)
                )
                if best_score is None or score < best_score:
                    best_label = label
                    best_score = score
            if best_label is None:
                raise ValueError("no variance-calibrated prototype available")
            return best_label


        def _macro_f1(labels: list[int], predictions: list[int]) -> float:
            classes = sorted(set(labels) | set(predictions))
            scores = []
            for klass in classes:
                tp = sum(
                    1
                    for label, pred in zip(labels, predictions, strict=True)
                    if label == klass and pred == klass
                )
                fp = sum(
                    1
                    for label, pred in zip(labels, predictions, strict=True)
                    if label != klass and pred == klass
                )
                fn = sum(
                    1
                    for label, pred in zip(labels, predictions, strict=True)
                    if label == klass and pred != klass
                )
                precision = tp / (tp + fp) if tp + fp else 0.0
                recall = tp / (tp + fn) if tp + fn else 0.0
                scores.append(
                    2 * precision * recall / (precision + recall)
                    if precision + recall
                    else 0.0
                )
            return sum(scores) / len(scores)


        def _features(row: dict[str, object]) -> list[float]:
            features = row["features"]
            if not isinstance(features, list):
                raise TypeError("row features must be a list")
            return [float(value) for value in features]


        def _labels(rows: list[dict[str, object]]) -> list[int]:
            return sorted({int(row["label"]) for row in rows})


        def _write_predictions(path: Path, predictions: list[dict[str, object]]) -> None:
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["row_id", "label", "prediction", "correct"],
                )
                writer.writeheader()
                writer.writerows(predictions)


        def _write_ablation(
            path: Path,
            *,
            baseline: dict[str, object],
            zscore: dict[str, object],
            calibrated: dict[str, object],
            test_rows: int,
        ) -> None:
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["model", "accuracy", "macro_f1", "test_rows"],
                )
                writer.writeheader()
                for model, result in (
                    ("baseline_centroid", baseline),
                    ("zscore_centroid_ablation", zscore),
                    ("variance_calibrated_prototypes", calibrated),
                ):
                    writer.writerow(
                        {
                            "model": model,
                            "accuracy": f"{float(result['accuracy']):.6f}",
                            "macro_f1": f"{float(result['macro_f1']):.6f}",
                            "test_rows": test_rows,
                        }
                    )


        def _write_summary(
            path: Path,
            source_records: list[dict[str, object]],
            *,
            train_rows: int,
            test_rows: int,
            baseline: dict[str, object],
            zscore: dict[str, object],
            calibrated: dict[str, object],
            delta_vs_baseline: float,
            delta_vs_zscore: float,
            accuracy_standard_error: float,
        ) -> None:
            urls = "\\n".join(f"- {record['url']} ({record['status']})" for record in source_records)
            path.write_text(
                "# UCI Pendigits Variance-Calibrated Prototype Summary\\n\\n"
                "## Dataset\\n\\n"
                "- Name: UCI Pen-Based Recognition of Handwritten Digits\\n"
                "- Split: official `pendigits.tra` train and `pendigits.tes` test\\n"
                f"- Train rows: {train_rows}\\n"
                f"- Test rows: {test_rows}\\n"
                f"{urls}\\n\\n"
                "## Method Candidate\\n\\n"
                "- Proposed method: diagonal variance-calibrated class prototypes\\n"
                f"- Variance shrinkage: {VARIANCE_SHRINKAGE:.2f}\\n\\n"
                "## Results\\n\\n"
                f"- Candidate accuracy: {float(calibrated['accuracy']):.6f}\\n"
                f"- Candidate macro F1: {float(calibrated['macro_f1']):.6f}\\n"
                f"- Baseline accuracy: {float(baseline['accuracy']):.6f}\\n"
                f"- Accuracy delta vs baseline: {delta_vs_baseline:.6f}\\n"
                f"- Z-score centroid accuracy: {float(zscore['accuracy']):.6f}\\n"
                f"- Accuracy delta vs z-score centroid: {delta_vs_zscore:.6f}\\n"
                f"- Accuracy standard error: {accuracy_standard_error:.6f}\\n\\n"
                "## Interpretation\\n\\n"
                f"- {_effect_interpretation(delta_vs_baseline)}\\n",
                encoding="utf-8",
            )


        def _effect_direction(delta: float) -> str:
            if delta > 0:
                return "positive"
            if delta < 0:
                return "negative"
            return "neutral"


        def _effect_interpretation(delta: float) -> str:
            if delta > 0:
                return "The method candidate improved accuracy over the baseline in this run."
            if delta < 0:
                return "The method candidate underperformed the baseline in this run."
            return "The method candidate tied the baseline in this run; do not claim empirical gain."


        if __name__ == "__main__":
            sys.exit(main())
        """
    )


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
