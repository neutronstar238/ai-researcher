"""Baseline reproduction helpers for experiment workflows."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autoresearch.experiments.demos import (
    TABULAR_BASELINE_TASK_ID,
    generate_tabular_baseline_demo,
)
from autoresearch.experiments.executor import execute_experiment_task
from autoresearch.experiments.results import collect_result_bundle
from autoresearch.experiments.validation import ValidationReport, validate_result_bundle
from autoresearch.schemas import ExecutionRun, ExperimentTask, ResultBundle, file_hash


@dataclass(frozen=True)
class BaselineReproductionResult:
    """Validated baseline reproduction output."""

    experiment_dir: Path
    task: ExperimentTask
    run: ExecutionRun
    results: ResultBundle
    validation: ValidationReport
    record_path: Path


def reproduce_tabular_baseline(
    output_dir: Path | str,
    *,
    timeout_seconds: int = 30,
    commit_sha: str | None = None,
) -> BaselineReproductionResult:
    """Run and record the deterministic tabular baseline reproduction."""

    root = Path(output_dir)
    experiment_dir, task = generate_tabular_baseline_demo(
        root / "experiments",
        timeout_seconds=timeout_seconds,
    )
    run = execute_experiment_task(
        experiment_dir,
        task,
        entrypoint="run.py",
        commit_sha=commit_sha,
    )
    run = run.model_copy(
        update={
            "data_hash": file_hash(experiment_dir / "data" / f"{TABULAR_BASELINE_TASK_ID}.csv"),
            "cost_json": _cost_json(run),
        }
    )
    bundle = collect_result_bundle(experiment_dir, run)
    validation = validate_result_bundle(
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
    record_path = _write_baseline_record(root, experiment_dir, task, run, bundle, validation)
    return BaselineReproductionResult(
        experiment_dir=experiment_dir,
        task=task,
        run=run,
        results=bundle,
        validation=validation,
        record_path=record_path,
    )


def _write_baseline_record(
    root: Path,
    experiment_dir: Path,
    task: ExperimentTask,
    run: ExecutionRun,
    bundle: ResultBundle,
    validation: ValidationReport,
) -> Path:
    record_dir = root / "baselines"
    record_dir.mkdir(parents=True, exist_ok=True)
    record_path = record_dir / f"{task.id}-baseline.json"
    payload: dict[str, Any] = {
        "task_id": task.id,
        "project_id": task.project_id,
        "baseline_config": {
            "config_path": (experiment_dir / "config.yaml").as_posix(),
            "config_hash": run.config_hash,
            "metrics": task.metrics,
            "resource_budget": task.resource_budget,
            "expected_baseline_metric": task.metadata.get("baseline_metric", {}),
        },
        "run_id": run.id,
        "run_status": run.status.value,
        "metrics": bundle.metrics,
        "validation_status": validation.status.value,
        "validation_json_path": validation.json_path,
        "validation_markdown_path": validation.markdown_path,
    }
    record_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return record_path


def _cost_json(run: ExecutionRun) -> dict[str, float | int]:
    cpu_time_seconds = 0.0
    if run.start_time is not None and run.end_time is not None:
        cpu_time_seconds = max((run.end_time - run.start_time).total_seconds(), 0.0)
    return {
        "cpu_time_seconds": cpu_time_seconds,
        "gpu_hours": 0.0,
        "human_approval_count": 0,
    }
