"""Local ScientistBench-Lite demo experiment tasks."""

from __future__ import annotations

import textwrap
from pathlib import Path

from autoresearch.schemas import ExperimentTask, TaskStatus

TABULAR_BASELINE_TASK_ID = "tabular_baseline"
TABULAR_BASELINE_DIR = "tabular-baseline"


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


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
