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


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
