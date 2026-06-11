import json
from pathlib import Path

from autoresearch.experiments import reproduce_tabular_baseline
from autoresearch.schemas import ExecutionStatus, ValidationStatus


def test_reproduce_tabular_baseline_records_validated_baseline_run(tmp_path: Path) -> None:
    result = reproduce_tabular_baseline(tmp_path, timeout_seconds=5, commit_sha="abc123")

    payload = json.loads(result.record_path.read_text(encoding="utf-8"))

    assert result.task.id == "tabular_baseline"
    assert result.run.status is ExecutionStatus.SUCCESS
    assert result.run.commit_sha == "abc123"
    assert result.results.metrics == {"accuracy": 1.0, "test_rows": 4.0}
    assert result.validation.status is ValidationStatus.PASSED
    assert payload["run_id"] == result.run.id
    assert payload["run_status"] == "success"
    assert payload["metrics"] == {"accuracy": 1.0, "test_rows": 4.0}
    assert payload["validation_status"] == "passed"
    assert payload["baseline_config"]["config_hash"] == result.run.config_hash
    assert Path(payload["baseline_config"]["config_path"]).is_file()
