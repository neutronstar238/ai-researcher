import json
from pathlib import Path

from autoresearch.reports import EvidenceGateVerdict, run_evidence_gate


def test_evidence_gate_passes_when_all_required_artifacts_are_physical(
    tmp_path: Path,
) -> None:
    summary_path, publication_audit_path, paper_build_path = _write_gate_cycle(tmp_path)

    report = run_evidence_gate(
        cycle_summary_path=summary_path,
        publication_audit_path=publication_audit_path,
        paper_build_path=paper_build_path,
    )

    assert report.verdict is EvidenceGateVerdict.PASS
    assert report.release_allowed is True
    assert report.failed_check_count == 0
    assert Path(report.output_path).is_file()
    assert Path(report.markdown_path).is_file()
    payload = json.loads(Path(report.output_path).read_text(encoding="utf-8"))
    assert payload["release_allowed"] is True
    assert {stage["stage_id"]: stage["status"] for stage in payload["lifecycle_trace"]} == {
        "define": "pass",
        "plan": "pass",
        "build": "pass",
        "verify": "pass",
        "review": "pass",
        "ship": "pass",
    }


def test_evidence_gate_blocks_missing_physical_artifact(tmp_path: Path) -> None:
    summary_path, publication_audit_path, paper_build_path = _write_gate_cycle(tmp_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    Path(summary["demo"]["evidence_map_path"]).unlink()

    report = run_evidence_gate(
        cycle_summary_path=summary_path,
        publication_audit_path=publication_audit_path,
        paper_build_path=paper_build_path,
    )

    checks = {check.check_id: check for check in report.checks}
    assert report.verdict is EvidenceGateVerdict.BLOCKED
    assert report.release_allowed is False
    assert checks["evidence_map"].status.value == "fail"


def test_evidence_gate_blocks_non_publishable_publication_audit(
    tmp_path: Path,
) -> None:
    summary_path, publication_audit_path, paper_build_path = _write_gate_cycle(
        tmp_path,
        publishable=False,
    )

    report = run_evidence_gate(
        cycle_summary_path=summary_path,
        publication_audit_path=publication_audit_path,
        paper_build_path=paper_build_path,
    )

    checks = {check.check_id: check for check in report.checks}
    assert report.verdict is EvidenceGateVerdict.BLOCKED
    assert checks["publication_release_gate"].status.value == "fail"
    assert "publishable=false" in checks["publication_release_gate"].message


def test_evidence_gate_blocks_missing_compiled_pdf(tmp_path: Path) -> None:
    summary_path, publication_audit_path, paper_build_path = _write_gate_cycle(
        tmp_path,
        paper_status="rendered",
    )

    report = run_evidence_gate(
        cycle_summary_path=summary_path,
        publication_audit_path=publication_audit_path,
        paper_build_path=paper_build_path,
    )

    checks = {check.check_id: check for check in report.checks}
    assert report.verdict is EvidenceGateVerdict.BLOCKED
    assert checks["paper_pdf_gate"].status.value == "fail"


def test_evidence_gate_blocks_missing_reproduction_rerun_artifact(
    tmp_path: Path,
) -> None:
    summary_path, publication_audit_path, paper_build_path = _write_gate_cycle(tmp_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    Path(summary["reproduction_check"]["run_record_paths"][0]).unlink()

    report = run_evidence_gate(
        cycle_summary_path=summary_path,
        publication_audit_path=publication_audit_path,
        paper_build_path=paper_build_path,
    )

    checks = {check.check_id: check for check in report.checks}
    assert report.verdict is EvidenceGateVerdict.BLOCKED
    assert checks["reproduction_rerun_gate"].status.value == "fail"


def test_evidence_gate_blocks_missing_lifecycle_code_artifact(
    tmp_path: Path,
) -> None:
    summary_path, publication_audit_path, paper_build_path = _write_gate_cycle(tmp_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    Path(summary["demo"]["experiment_dir"], "run.py").unlink()

    report = run_evidence_gate(
        cycle_summary_path=summary_path,
        publication_audit_path=publication_audit_path,
        paper_build_path=paper_build_path,
    )

    checks = {check.check_id: check for check in report.checks}
    trace = {stage.stage_id: stage for stage in report.lifecycle_trace}
    assert report.verdict is EvidenceGateVerdict.BLOCKED
    assert trace["build"].status.value == "fail"
    assert "run.py" in trace["build"].missing_refs[0]
    assert checks["lifecycle_trace_gate"].status.value == "fail"
    assert "build=fail" in checks["lifecycle_trace_gate"].message


def test_evidence_gate_accepts_explicit_review_json_for_skipped_cycle(
    tmp_path: Path,
) -> None:
    summary_path, publication_audit_path, paper_build_path = _write_gate_cycle(tmp_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["review"] = {"status": "skipped"}
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    review_override = summary_path.parent / "manual-llm-review.json"
    review_override.write_text(
        json.dumps(
            {
                "quality": {
                    "score": 1.0,
                    "parsed_output": {
                        "verdict": "pass",
                        "findings": [{"evidence_refs": ["evidence_1"]}],
                        "unsupported_claims": [],
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    report = run_evidence_gate(
        cycle_summary_path=summary_path,
        review_path=review_override,
        publication_audit_path=publication_audit_path,
        paper_build_path=paper_build_path,
    )

    checks = {check.check_id: check for check in report.checks}
    trace = {stage.stage_id: stage for stage in report.lifecycle_trace}
    assert report.verdict is EvidenceGateVerdict.PASS
    assert report.review_path == review_override.as_posix()
    assert checks["review_gate"].status.value == "pass"
    assert checks["review_gate"].evidence_refs == (review_override.as_posix(),)
    assert checks["review_artifact"].status.value == "pass"
    assert trace["review"].status.value == "pass"


def test_evidence_gate_writes_obsidian_review_and_issue_for_blocked_gate(
    tmp_path: Path,
) -> None:
    summary_path, publication_audit_path, paper_build_path = _write_gate_cycle(
        tmp_path,
        publishable=False,
    )
    vault = tmp_path / "vault"

    report = run_evidence_gate(
        cycle_summary_path=summary_path,
        publication_audit_path=publication_audit_path,
        paper_build_path=paper_build_path,
        vault_root=vault,
        project_id="project_1",
    )

    assert report.vault_review_path is not None
    assert report.vault_issue_path is not None
    review_note = Path(report.vault_review_path)
    issue_note = Path(report.vault_issue_path)
    assert review_note.is_file()
    assert issue_note.is_file()
    assert "Evidence Release Gate" in review_note.read_text(encoding="utf-8")
    assert "publication_release_gate" in issue_note.read_text(encoding="utf-8")


def _write_gate_cycle(
    tmp_path: Path,
    *,
    publishable: bool = True,
    paper_status: str = "compiled",
) -> tuple[Path, Path, Path]:
    cycle_dir = tmp_path / "runs" / "cycle-gate"
    experiment_dir = cycle_dir / "demo" / "benchmark"
    for relative in (
        "data",
        "evidence",
        "report",
        "run",
        "validation",
    ):
        (experiment_dir / relative).mkdir(parents=True, exist_ok=True)

    candidate_path = cycle_dir / "candidate.json"
    literature_summary = cycle_dir / "literature.md"
    similarity_summary = cycle_dir / "similarity.md"
    report_path = experiment_dir / "report" / "report.md"
    validation_path = experiment_dir / "validation" / "validation-report.json"
    evidence_map_path = experiment_dir / "evidence" / "evidence-map.json"
    run_record_path = experiment_dir / "run" / "run-record.json"
    review_path = cycle_dir / "llm-review.json"
    publication_audit_path = cycle_dir / "publication-audit.json"
    publication_audit_md = cycle_dir / "publication-audit.md"
    reproduction_dir = cycle_dir / "reproduction-check"
    reproduction_report_path = reproduction_dir / "reproduction-check.json"
    reproduction_markdown_path = reproduction_dir / "reproduction-check.md"
    reproduction_run_record = (
        reproduction_dir / "rerun" / "tabular-baseline" / "run" / "run-record.json"
    )
    reproduction_validation = (
        reproduction_dir
        / "rerun"
        / "tabular-baseline"
        / "validation"
        / "validation-report.json"
    )
    paper_dir = cycle_dir / "paper"
    paper_dir.mkdir(parents=True)
    paper_build_path = paper_dir / "paper-build.json"
    paper_pdf_path = paper_dir / "main.pdf"

    candidate_path.write_text('{"id": "candidate_1"}', encoding="utf-8")
    literature_summary.write_text("# Literature\n", encoding="utf-8")
    similarity_summary.write_text("# Similarity\n", encoding="utf-8")
    (experiment_dir / "README.md").write_text("# Experiment Plan\n", encoding="utf-8")
    (experiment_dir / "config.yaml").write_text("demo: tabular_baseline\n", encoding="utf-8")
    (experiment_dir / "run.py").write_text("print('run')\n", encoding="utf-8")
    report_path.write_text("# Report\n\n## Results\n\nEvidence.", encoding="utf-8")
    validation_path.write_text('{"status": "passed"}', encoding="utf-8")
    evidence_map_path.write_text('{"evidence_edges": []}', encoding="utf-8")
    run_record_path.write_text('{"run": {"status": "success"}}', encoding="utf-8")
    review_path.write_text('{"quality": {"score": 1.0}}', encoding="utf-8")
    reproduction_run_record.parent.mkdir(parents=True, exist_ok=True)
    reproduction_validation.parent.mkdir(parents=True, exist_ok=True)
    reproduction_run_record.write_text('{"run": {"status": "success"}}', encoding="utf-8")
    reproduction_validation.write_text('{"status": "passed"}', encoding="utf-8")
    reproduction_report_path.write_text(
        json.dumps(
            {
                "status": "passed",
                "exit_code": 0,
                "run_record_paths": [reproduction_run_record.as_posix()],
                "validation_json_paths": [reproduction_validation.as_posix()],
            }
        ),
        encoding="utf-8",
    )
    reproduction_markdown_path.write_text("# Reproduction Check\n", encoding="utf-8")
    publication_audit_md.write_text("# Publication Audit\n", encoding="utf-8")
    publication_audit_path.write_text(
        json.dumps(
            {
                "verdict": "pass" if publishable else "needs_revision",
                "publishable": publishable,
            }
        ),
        encoding="utf-8",
    )
    if paper_status == "compiled":
        paper_pdf_path.write_text("%PDF-smoke\n", encoding="utf-8")
    paper_build_path.write_text(
        json.dumps(
            {
                "status": paper_status,
                "pdf_path": paper_pdf_path.as_posix() if paper_status == "compiled" else None,
            }
        ),
        encoding="utf-8",
    )
    summary_path = cycle_dir / "cycle-summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "cycle_id": "cycle-gate",
                "project_id": "project_1",
                "candidate_path": candidate_path.as_posix(),
                "literature": {"summary_path": literature_summary.as_posix()},
                "similarity": {"summary_path": similarity_summary.as_posix()},
                "demo": {
                    "experiment_dir": experiment_dir.as_posix(),
                    "report_path": report_path.as_posix(),
                    "validation_json_path": validation_path.as_posix(),
                    "evidence_map_path": evidence_map_path.as_posix(),
                },
                "review": {
                    "status": "passed",
                    "verdict": "pass",
                    "quality_score": 1.0,
                    "output_path": review_path.as_posix(),
                },
                "reproduction_check": {
                    "status": "passed",
                    "exit_code": 0,
                    "json_path": reproduction_report_path.as_posix(),
                    "markdown_path": reproduction_markdown_path.as_posix(),
                    "run_record_paths": [reproduction_run_record.as_posix()],
                    "validation_json_paths": [reproduction_validation.as_posix()],
                },
                "publication_audit": {
                    "output_path": publication_audit_path.as_posix(),
                    "markdown_path": publication_audit_md.as_posix(),
                    "publishable": publishable,
                    "verdict": "pass" if publishable else "needs_revision",
                },
            }
        ),
        encoding="utf-8",
    )
    return summary_path, publication_audit_path, paper_build_path
