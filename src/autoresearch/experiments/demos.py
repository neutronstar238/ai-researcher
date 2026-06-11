"""Local ScientistBench-Lite demo experiment tasks."""

from __future__ import annotations

import textwrap
from pathlib import Path

from autoresearch.schemas import ExperimentTask, TaskStatus

TABULAR_BASELINE_TASK_ID = "tabular_baseline"
TABULAR_BASELINE_DIR = "tabular-baseline"
TEXT_CLASSIFIER_STUB_TASK_ID = "text_classifier_stub"
TEXT_CLASSIFIER_STUB_DIR = "text-classifier-stub"


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


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
