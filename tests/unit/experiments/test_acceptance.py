import json
from pathlib import Path

from autoresearch.experiments import run_mvp_acceptance


def test_run_mvp_acceptance_writes_report_with_rerun_outcomes(tmp_path: Path) -> None:
    result = run_mvp_acceptance(
        output_dir=tmp_path / "acceptance",
        vault_root=tmp_path / "autoresearch-vault",
        timeout_seconds=5,
    )

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    markdown = result.report_path.read_text(encoding="utf-8")

    assert result.passed
    assert result.success_rate == 1.0
    assert result.rerun_success_rate == 1.0
    assert payload["available_demo_count"] == 2
    assert payload["passed"] is True
    assert {entry["demo"] for entry in payload["results"]} == {
        "tabular_baseline",
        "text_classifier_stub",
    }
    for entry in payload["results"]:
        assert entry["run_id"]
        assert entry["rerun_id"]
        assert entry["success"] is True
        assert entry["rerun_success"] is True
    assert "## Run Outcomes" in markdown
    assert "tabular_baseline" in markdown
    assert "text_classifier_stub" in markdown

    run_records = sorted((tmp_path / "acceptance").glob("**/run/run-record.json"))
    assert len(run_records) == 4
    for run_record_path in run_records:
        run_record = json.loads(run_record_path.read_text(encoding="utf-8"))
        run = run_record["run"]
        assert run["id"].startswith("run_")
        assert run["commit_sha"]
        assert run["config_hash"]
        assert run["data_hash"]
        assert run_record["metrics"]["path"].endswith("metrics.json")
        assert run_record["metrics"]["values"]
        assert run_record["logs"]
        assert run_record["artifacts"]
        assert run_record["validation_report"]["status"] == "passed"
        assert run_record["validation_report"]["json_path"].endswith(
            "validation-report.json"
        )
        assert run_record["cost_record"]["model_name"] == "local-runner"
        assert run_record["cost_record"]["gpu_hours"] == 0.0
