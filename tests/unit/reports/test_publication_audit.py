import json
from pathlib import Path

from autoresearch.reports import PublicationAuditVerdict, audit_publication_quality
from autoresearch.schemas import file_hash


def test_publication_audit_verifies_script_data_but_fails_ccfb_for_toy_cycle(
    tmp_path: Path,
) -> None:
    summary_path = _write_toy_cycle(tmp_path)

    report = audit_publication_quality(cycle_summary_path=summary_path, target="ccf-b")

    checks = {check.check_id: check for check in report.checks}
    assert report.verdict is PublicationAuditVerdict.FAIL
    assert report.publishable is False
    assert checks["script_data_verification"].status.value == "pass"
    assert checks["data_strength"].status.value == "fail"
    assert checks["dataset_realism"].status.value == "fail"
    assert checks["literature_source_breadth"].status.value == "fail"
    assert checks["similarity_source_breadth"].status.value == "fail"
    assert Path(report.output_path).is_file()
    assert Path(report.markdown_path).is_file()
    assert "not publication-ready" not in Path(report.markdown_path).read_text(encoding="utf-8")


def test_publication_audit_writes_vault_review_and_issue_for_failed_audit(
    tmp_path: Path,
) -> None:
    summary_path = _write_toy_cycle(tmp_path)
    vault = tmp_path / "vault"

    report = audit_publication_quality(
        cycle_summary_path=summary_path,
        target="ccf-b",
        vault_root=vault,
        project_id="project_1",
    )

    assert report.vault_review_path is not None
    assert report.vault_issue_path is not None
    review_note = Path(report.vault_review_path)
    issue_note = Path(report.vault_issue_path)
    assert review_note.is_file()
    assert issue_note.is_file()
    assert "Publication Quality Audit" in review_note.read_text(encoding="utf-8")
    assert "publication-audit" in issue_note.read_text(encoding="utf-8")


def _write_toy_cycle(tmp_path: Path) -> Path:
    cycle_dir = tmp_path / "runs" / "cycle-test"
    experiment_dir = cycle_dir / "demo" / "tabular-baseline"
    (experiment_dir / "data").mkdir(parents=True)
    (experiment_dir / "artifacts").mkdir()
    (experiment_dir / "logs").mkdir()
    (experiment_dir / "validation").mkdir()
    (experiment_dir / "evidence").mkdir()
    (experiment_dir / "run").mkdir()
    (experiment_dir / "report").mkdir()

    run_py = experiment_dir / "run.py"
    run_py.write_text("print('ran')\n", encoding="utf-8")
    data_path = experiment_dir / "data" / "tabular_baseline.csv"
    data_path.write_text("x,y\n1,1\n2,0\n3,1\n4,0\n", encoding="utf-8")
    metrics_path = experiment_dir / "metrics.json"
    metrics_path.write_text(
        json.dumps({"status": "success", "metrics": {"accuracy": 1.0, "test_rows": 4.0}}),
        encoding="utf-8",
    )
    (experiment_dir / "artifacts" / "predictions.csv").write_text("y_hat\n1\n0\n", encoding="utf-8")
    (experiment_dir / "artifacts" / "summary.md").write_text("# Summary\n", encoding="utf-8")
    (experiment_dir / "logs" / "run.log").write_text("ok\n", encoding="utf-8")
    validation_json = experiment_dir / "validation" / "validation-report.json"
    validation_json.write_text(
        json.dumps(
            {
                "run_id": "run_test",
                "status": "passed",
                "issues": [],
                "statistical_notes": [],
            }
        ),
        encoding="utf-8",
    )
    evidence_map = experiment_dir / "evidence" / "evidence-map.json"
    evidence_map.write_text(
        json.dumps(
            {
                "evidence_edges": [
                    {
                        "claim_id": "tabular_baseline_claim",
                        "evidence_ref": "run_test:accuracy",
                        "source_artifact": "metrics.json",
                        "validation_status": "passed",
                        "supports_claim": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    report_path = experiment_dir / "report" / "report.md"
    report_path.write_text(
        "# ScientistBench-Lite Report\n\n"
        "## Results\n\n- accuracy = 1.0\n\n"
        "## Limitations\n\n- Synthetic fixture only.\n",
        encoding="utf-8",
    )
    run_record = {
        "artifacts": ["artifacts/predictions.csv", "artifacts/summary.md"],
        "logs": ["logs/run.log"],
        "metrics": {
            "path": metrics_path.as_posix(),
            "values": {"accuracy": 1.0, "test_rows": 4.0},
        },
        "reproducibility": {
            "command": "airesearcher run-demo --demo tabular_baseline",
            "commit_sha": "abc1234",
            "config_hash": "cfg",
            "data_hash": file_hash(data_path),
            "dependency_lock_status": "poetry.lock present",
            "python_version": "3.10.20",
        },
        "run": {
            "id": "run_test",
            "task_id": "tabular_baseline",
            "project_id": "scientistbench-lite",
            "status": "success",
            "exit_code": 0,
            "metrics_path": metrics_path.as_posix(),
            "data_hash": file_hash(data_path),
            "metadata": {"entrypoint": run_py.as_posix()},
        },
        "validation_report": {
            "status": "passed",
            "json_path": validation_json.as_posix(),
        },
    }
    (experiment_dir / "run" / "run-record.json").write_text(
        json.dumps(run_record, indent=2),
        encoding="utf-8",
    )
    similarity_summary = cycle_dir / "similarity.md"
    similarity_summary.write_text(
        "## Findings\n\n"
        "### Adjacent Source\n\n"
        "- Classification: `unknown`\n"
        "- Source URL/DOI: `https://arxiv.org/abs/0000.00000` / `unknown`\n",
        encoding="utf-8",
    )
    cycle_summary = {
        "cycle_id": "cycle-test",
        "project_id": "project_1",
        "literature": {
            "query_count": 1,
            "document_count": 1,
            "fetches": [
                {"source": "arxiv", "query": "q", "paper_count": 1, "error": None},
                {
                    "source": "semantic_scholar",
                    "query": "q",
                    "paper_count": 0,
                    "error": "HTTP 429",
                },
            ],
        },
        "similarity": {
            "finding_count": 1,
            "summary_path": similarity_summary.as_posix(),
            "fetches": [
                {"source": "arxiv", "query": "q", "paper_count": 1, "error": None},
                {
                    "source": "semantic_scholar",
                    "query": "q",
                    "paper_count": 0,
                    "error": "HTTP 429",
                },
            ],
        },
        "demo": {
            "experiment_dir": experiment_dir.as_posix(),
            "report_path": report_path.as_posix(),
            "validation_json_path": validation_json.as_posix(),
            "evidence_map_path": evidence_map.as_posix(),
        },
        "review": {
            "status": "passed",
            "quality_score": 1.0,
            "verdict": "pass",
        },
    }
    summary_path = cycle_dir / "cycle-summary.json"
    summary_path.write_text(json.dumps(cycle_summary, indent=2), encoding="utf-8")
    return summary_path
