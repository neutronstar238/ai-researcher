import json
from datetime import datetime, timezone
from pathlib import Path

from autoresearch.experiments import StatisticalCheck, validate_result_bundle
from autoresearch.schemas import (
    CostRecord,
    ExecutionRun,
    ExecutionStatus,
    ResultBundle,
    ValidationStatus,
    data_hash,
    file_hash,
)


def test_validate_result_bundle_writes_passing_reports(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    artifact_path = tmp_path / "artifacts" / "summary.md"
    artifact_path.parent.mkdir()
    config_path.write_text("lr: 0.1\n", encoding="utf-8")
    artifact_path.write_text("# Summary\n", encoding="utf-8")
    run = _run(
        config_hash=file_hash(config_path),
        data_hash=data_hash("dataset"),
        cost_record=CostRecord(model_name="local-runner", cpu_time_seconds=1.0),
    )
    bundle = ResultBundle(
        run_id=run.id,
        metrics={"accuracy": 0.9},
        artifacts=["artifacts/summary.md"],
        validation_status=ValidationStatus.PASSED,
    )

    report = validate_result_bundle(
        tmp_path,
        run,
        bundle,
        expected_metrics=["accuracy"],
        metric_bounds={"accuracy": (0.0, 1.0)},
        expected_artifacts=["artifacts/summary.md"],
    )

    payload = json.loads(Path(report.json_path).read_text(encoding="utf-8"))
    markdown = Path(report.markdown_path).read_text(encoding="utf-8")
    assert report.status is ValidationStatus.PASSED
    assert report.issues == ()
    assert payload["status"] == "passed"
    assert "# Validation Report" in markdown
    assert "No validation issues" in markdown


def test_validate_result_bundle_warns_for_missing_hashes_and_cost(
    tmp_path: Path,
) -> None:
    (tmp_path / "config.yaml").write_text("lr: 0.1\n", encoding="utf-8")
    run = _run(config_hash=None, data_hash=None, cost_record=None)
    bundle = ResultBundle(run_id=run.id, metrics={"accuracy": 0.9})

    report = validate_result_bundle(
        tmp_path,
        run,
        bundle,
        expected_metrics=["accuracy"],
    )

    assert report.status is ValidationStatus.WARNING
    assert {issue.check for issue in report.issues} == {
        "config_hash",
        "data_hash",
        "cost_record",
    }


def test_validate_result_bundle_fails_for_incomplete_or_invalid_results(
    tmp_path: Path,
) -> None:
    (tmp_path / "config.yaml").write_text("lr: 0.1\n", encoding="utf-8")
    run = _run(
        status=ExecutionStatus.FAILED,
        config_hash="wrong-hash",
        data_hash=data_hash("dataset"),
        cost_record=CostRecord(model_name="local-runner"),
    )
    bundle = ResultBundle(
        run_id=run.id,
        metrics={"accuracy": 1.5},
        artifacts=[],
        validation_status=ValidationStatus.FAILED,
    )

    report = validate_result_bundle(
        tmp_path,
        run,
        bundle,
        expected_metrics=["accuracy", "loss"],
        metric_bounds={"accuracy": (0.0, 1.0)},
        expected_artifacts=["artifacts/summary.md"],
    )

    assert report.status is ValidationStatus.FAILED
    assert {
        "run_completion",
        "metric_presence",
        "metric_bounds",
        "artifact_existence",
        "config_hash",
    }.issubset({issue.check for issue in report.issues})
    assert "failed" in Path(report.markdown_path).read_text(encoding="utf-8")


def test_validate_result_bundle_labels_underpowered_comparison(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("lr: 0.1\n", encoding="utf-8")
    run = _run(
        config_hash=file_hash(config_path),
        data_hash=data_hash("dataset"),
        cost_record=CostRecord(model_name="local-runner", cpu_time_seconds=1.0),
    )
    bundle = ResultBundle(run_id=run.id, metrics={"accuracy": 0.9})

    report = validate_result_bundle(
        tmp_path,
        run,
        bundle,
        expected_metrics=["accuracy"],
        statistical_checks=[
            StatisticalCheck(
                metric_name="accuracy",
                sample_size=4,
                mean=0.9,
                standard_error=0.05,
                baseline_mean=0.8,
                comparison_mean=0.9,
                min_sample_size=10,
            )
        ],
    )

    payload = json.loads(Path(report.json_path).read_text(encoding="utf-8"))
    markdown = Path(report.markdown_path).read_text(encoding="utf-8")
    assert report.status is ValidationStatus.WARNING
    assert any(
        issue.check == "statistical_power" and "underpowered" in issue.message
        for issue in report.issues
    )
    assert "do not overstate significance" in markdown
    assert "95% CI" in markdown
    assert "repeated-run comparison delta" in markdown
    assert {note["check"] for note in payload["statistical_notes"]} == {
        "statistical_power",
        "confidence_interval",
        "repeated_run_delta",
    }


def _run(
    *,
    status: ExecutionStatus = ExecutionStatus.SUCCESS,
    config_hash: str | None,
    data_hash: str | None,
    cost_record: CostRecord | None,
) -> ExecutionRun:
    return ExecutionRun(
        id="run_001",
        project_id="project-001",
        task_id="task-001",
        status=status,
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc)
        if status is ExecutionStatus.SUCCESS
        else None,
        config_hash=config_hash,
        data_hash=data_hash,
        cost_record=cost_record,
    )
