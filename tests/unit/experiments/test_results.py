import json
from pathlib import Path

import pytest

from autoresearch.experiments import ResultCollectionError, collect_result_bundle
from autoresearch.schemas import ExecutionRun, ExecutionStatus, ValidationStatus


def _run(status: ExecutionStatus = ExecutionStatus.SUCCESS) -> ExecutionRun:
    return ExecutionRun(
        id="run_001",
        project_id="project-001",
        task_id="task-001",
        status=status,
        metrics_path="metrics.json",
    )


def test_collect_result_bundle_parses_metrics_logs_artifacts_and_csv(
    tmp_path: Path,
) -> None:
    _write_outputs(tmp_path)
    (tmp_path / "extra_metrics.csv").write_text(
        "metric,value\nprecision,0.75\n",
        encoding="utf-8",
    )

    bundle = collect_result_bundle(
        tmp_path,
        _run(),
        csv_outputs=["extra_metrics.csv"],
    )

    assert bundle.run_id == "run_001"
    assert bundle.metrics == {"accuracy": 0.9, "loss": 0.1, "precision": 0.75}
    assert bundle.logs == ["logs/run.log"]
    assert bundle.artifacts == ["artifacts/summary.md", "extra_metrics.csv"]
    assert bundle.summary == "# Summary\n\nDone.\n"
    assert bundle.validation_status is ValidationStatus.PASSED


def test_collect_result_bundle_rejects_success_without_metrics(tmp_path: Path) -> None:
    with pytest.raises(ResultCollectionError, match="metrics file is missing"):
        collect_result_bundle(tmp_path, _run())


def test_collect_result_bundle_allows_failed_run_without_metrics(
    tmp_path: Path,
) -> None:
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "run.log").write_text("failed\n", encoding="utf-8")

    bundle = collect_result_bundle(tmp_path, _run(ExecutionStatus.FAILED))

    assert bundle.metrics == {}
    assert bundle.logs == ["logs/run.log"]
    assert bundle.validation_status is ValidationStatus.FAILED


def test_collect_result_bundle_rejects_non_numeric_csv_metric(
    tmp_path: Path,
) -> None:
    _write_outputs(tmp_path)
    (tmp_path / "extra_metrics.csv").write_text(
        "metric,value\nprecision,not-a-number\n",
        encoding="utf-8",
    )

    with pytest.raises(ResultCollectionError, match="not numeric"):
        collect_result_bundle(tmp_path, _run(), csv_outputs=["extra_metrics.csv"])


def test_collect_result_bundle_rejects_metric_path_outside_sandbox(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside" / "metrics.json"
    outside.parent.mkdir()
    outside.write_text("{}", encoding="utf-8")
    experiment_dir = tmp_path / "experiment"
    experiment_dir.mkdir()
    run = _run()
    run = run.model_copy(update={"metrics_path": outside.as_posix()})

    with pytest.raises(PermissionError):
        collect_result_bundle(experiment_dir, run)


def _write_outputs(root: Path) -> None:
    (root / "logs").mkdir()
    (root / "artifacts").mkdir()
    (root / "metrics.json").write_text(
        json.dumps({"status": "success", "metrics": {"accuracy": 0.9, "loss": 0.1}}),
        encoding="utf-8",
    )
    (root / "logs" / "run.log").write_text("completed\n", encoding="utf-8")
    (root / "artifacts" / "summary.md").write_text("# Summary\n\nDone.\n", encoding="utf-8")
