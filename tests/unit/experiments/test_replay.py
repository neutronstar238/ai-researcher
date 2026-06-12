import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.experiments import (
    ReplayDataset,
    ValidationReport,
    build_replay_case,
    load_replay_dataset,
    write_replay_dataset,
)
from autoresearch.schemas import (
    CostRecord,
    EvidenceEdge,
    ExecutionRun,
    ExecutionStatus,
    ExperimentTask,
    ResultBundle,
    ValidationStatus,
)


def test_replay_fixture_reproduces_expected_baseline_score(tmp_path: Path) -> None:
    task = _task()
    run = _run(task.id)
    results = ResultBundle(
        run_id=run.id,
        metrics={"accuracy": 0.91, "loss": 0.12},
        artifacts=["artifacts/summary.md"],
        logs=["logs/run.log"],
        summary="Baseline completed.",
        validation_status=ValidationStatus.PASSED,
    )
    validation = _validation(run.id, ValidationStatus.PASSED)
    evidence = (
        EvidenceEdge(
            claim_id="claim_accuracy",
            evidence_ref="metric_accuracy",
            source_artifact="metrics.json",
            source_run_id=run.id,
            metric_name="accuracy",
            validation_status=ValidationStatus.PASSED,
        ),
    )

    case = build_replay_case(
        task=task,
        run=run,
        results=results,
        validation=validation,
        baseline_metric="accuracy",
        evidence_edges=evidence,
    )
    dataset = ReplayDataset(dataset_id="replay_fixture", cases=(case,))
    path = write_replay_dataset(tmp_path / "replay" / "dataset.json", dataset)
    loaded = load_replay_dataset(path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert loaded.baseline_score("accuracy") == 0.91
    assert payload["cases"][0]["inputs"]["task"]["name"] == "Replay baseline"
    assert payload["cases"][0]["outputs"]["metrics"]["accuracy"] == 0.91
    assert payload["cases"][0]["evidence"][0]["source_artifact"] == "metrics.json"
    assert payload["cases"][0]["costs"]["cost_record"]["model_name"] == "local-runner"
    assert payload["cases"][0]["validation"]["status"] == "passed"


def test_build_replay_case_rejects_missing_baseline_metric() -> None:
    task = _task()
    run = _run(task.id)
    results = ResultBundle(run_id=run.id, metrics={"loss": 0.12})

    with pytest.raises(ValueError, match="baseline metric"):
        build_replay_case(
            task=task,
            run=run,
            results=results,
            validation=_validation(run.id, ValidationStatus.PASSED),
            baseline_metric="accuracy",
        )


def test_build_replay_case_rejects_mismatched_history() -> None:
    task = _task()
    run = _run("other_task")
    results = ResultBundle(run_id=run.id, metrics={"accuracy": 0.91})

    with pytest.raises(ValueError, match="does not match task id"):
        build_replay_case(
            task=task,
            run=run,
            results=results,
            validation=_validation(run.id, ValidationStatus.PASSED),
            baseline_metric="accuracy",
        )


def _task() -> ExperimentTask:
    return ExperimentTask(
        id="task_replay_baseline",
        project_id="project_1",
        hypothesis_id="hypothesis_1",
        name="Replay baseline",
        description="Historical baseline used for offline strategy replay.",
        entrypoint="run.py",
        config_path="config.yaml",
        metrics=["accuracy"],
    )


def _run(task_id: str) -> ExecutionRun:
    return ExecutionRun(
        id="run_replay_baseline",
        project_id="project_1",
        task_id=task_id,
        status=ExecutionStatus.SUCCESS,
        start_time=datetime(2026, 6, 12, tzinfo=timezone.utc),
        end_time=datetime(2026, 6, 12, 0, 0, 2, tzinfo=timezone.utc),
        config_hash="config_hash",
        data_hash="data_hash",
        metrics_path="metrics.json",
        artifact_uri="artifacts/summary.md",
        cost_record=CostRecord(
            model_name="local-runner",
            cpu_time_seconds=1.5,
            storage_artifact_bytes=2048,
        ),
    )


def _validation(run_id: str, status: ValidationStatus) -> ValidationReport:
    return ValidationReport(
        run_id=run_id,
        status=status,
        issues=(),
        json_path="validation/validation-report.json",
        markdown_path="validation/validation-report.md",
    )
