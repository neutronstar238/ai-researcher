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


def test_publication_audit_accepts_real_benchmark_data_evidence_but_keeps_manuscript_gate(
    tmp_path: Path,
) -> None:
    summary_path = _write_real_benchmark_cycle(
        tmp_path,
        similarity_classification="adjacent_work",
    )

    report = audit_publication_quality(cycle_summary_path=summary_path, target="ccf-b")

    checks = {check.check_id: check for check in report.checks}
    assert report.verdict is PublicationAuditVerdict.NEEDS_REVISION
    assert report.publishable is False
    assert checks["script_data_verification"].status.value == "pass"
    assert checks["data_strength"].status.value == "pass"
    assert checks["dataset_realism"].status.value == "pass"
    assert checks["baseline_reproduction"].status.value == "pass"
    assert checks["ablation_coverage"].status.value == "pass"
    assert checks["statistical_sanity"].status.value == "pass"
    assert checks["method_innovation_evidence"].status.value == "fail"
    assert checks["manuscript_structure"].status.value == "fail"


def test_publication_audit_keeps_baseline_only_paper_from_passing(
    tmp_path: Path,
) -> None:
    summary_path = _write_real_benchmark_cycle(
        tmp_path,
        similarity_classification="adjacent_work",
    )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    report_path = Path(summary["demo"]["report_path"])
    report_path.write_text(_paper_style_report(), encoding="utf-8")

    report = audit_publication_quality(cycle_summary_path=summary_path, target="ccf-b")

    checks = {check.check_id: check for check in report.checks}
    assert checks["manuscript_structure"].status.value == "pass"
    assert checks["method_innovation_evidence"].status.value == "fail"
    assert report.verdict is PublicationAuditVerdict.NEEDS_REVISION
    assert report.publishable is False


def test_publication_audit_passes_when_method_innovation_has_file_evidence(
    tmp_path: Path,
) -> None:
    summary_path = _write_real_benchmark_cycle(tmp_path, novel_method=True)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    report_path = Path(summary["demo"]["report_path"])
    report_path.write_text(_paper_style_report(), encoding="utf-8")

    report = audit_publication_quality(cycle_summary_path=summary_path, target="ccf-b")

    checks = {check.check_id: check for check in report.checks}
    assert checks["method_innovation_evidence"].status.value == "pass"
    assert checks["method_effect_evidence"].status.value == "pass"
    assert report.verdict is PublicationAuditVerdict.PASS
    assert report.publishable is True


def test_publication_audit_accepts_standalone_review_json(
    tmp_path: Path,
) -> None:
    summary_path = _write_real_benchmark_cycle(tmp_path, novel_method=True)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["review"] = {"status": "skipped", "quality_score": 0.0, "verdict": "missing"}
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    report_path = Path(summary["demo"]["report_path"])
    report_path.write_text(_paper_style_report(), encoding="utf-8")
    validation_path = Path(summary["demo"]["validation_json_path"])
    evidence_map_path = Path(summary["demo"]["evidence_map_path"])
    review_path = tmp_path / "llm-review.json"
    review_path.write_text(
        json.dumps(
            {
                "subject_path": report_path.as_posix(),
                "subject_sha256": file_hash(report_path),
                "evidence": [
                    {
                        "evidence_id": "evidence_1",
                        "path": validation_path.as_posix(),
                        "sha256": file_hash(validation_path),
                    },
                    {
                        "evidence_id": "evidence_2",
                        "path": evidence_map_path.as_posix(),
                        "sha256": file_hash(evidence_map_path),
                    },
                ],
                "quality": {
                    "score": 1.0,
                    "parsed_output": {
                        "verdict": "pass",
                        "findings": [
                            {
                                "issue": "No blocker.",
                                "evidence_refs": ["evidence_1"],
                            }
                        ],
                        "unsupported_claims": [],
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    report = audit_publication_quality(
        cycle_summary_path=summary_path,
        target="ccf-b",
        review_path=review_path,
    )

    checks = {check.check_id: check for check in report.checks}
    assert report.review_path == review_path.as_posix()
    assert checks["llm_evidence_review"].status.value == "pass"
    assert checks["review_verdict_strength"].status.value == "pass"
    assert checks["review_artifact_binding"].status.value == "pass"
    assert checks["llm_evidence_review"].evidence_refs == (review_path.as_posix(),)
    assert report.verdict is PublicationAuditVerdict.PASS
    assert report.publishable is True
    assert f"Review artifact: `{review_path.as_posix()}`" in Path(
        report.markdown_path
    ).read_text(encoding="utf-8")


def test_publication_audit_blocks_standalone_review_for_different_subject(
    tmp_path: Path,
) -> None:
    summary_path = _write_real_benchmark_cycle(tmp_path, novel_method=True)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["review"] = {"status": "skipped", "quality_score": 0.0, "verdict": "missing"}
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    report_path = Path(summary["demo"]["report_path"])
    report_path.write_text(_paper_style_report(), encoding="utf-8")
    validation_path = Path(summary["demo"]["validation_json_path"])
    evidence_map_path = Path(summary["demo"]["evidence_map_path"])
    unrelated_subject = tmp_path / "unrelated-report.md"
    unrelated_subject.write_text("# Different paper\n", encoding="utf-8")
    review_path = tmp_path / "llm-review.json"
    review_path.write_text(
        json.dumps(
            {
                "subject_path": unrelated_subject.as_posix(),
                "subject_sha256": file_hash(unrelated_subject),
                "evidence": [
                    {
                        "evidence_id": "evidence_1",
                        "path": validation_path.as_posix(),
                        "sha256": file_hash(validation_path),
                    },
                    {
                        "evidence_id": "evidence_2",
                        "path": evidence_map_path.as_posix(),
                        "sha256": file_hash(evidence_map_path),
                    },
                ],
                "quality": {
                    "score": 1.0,
                    "parsed_output": {
                        "verdict": "pass",
                        "findings": [{"issue": "No blocker.", "evidence_refs": ["evidence_1"]}],
                        "unsupported_claims": [],
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    report = audit_publication_quality(
        cycle_summary_path=summary_path,
        target="ccf-b",
        review_path=review_path,
    )

    checks = {check.check_id: check for check in report.checks}
    assert checks["llm_evidence_review"].status.value == "pass"
    assert checks["review_artifact_binding"].status.value == "fail"
    assert "subject_match=false" in checks["review_artifact_binding"].message
    assert report.verdict is PublicationAuditVerdict.FAIL
    assert report.publishable is False


def test_publication_audit_blocks_unknown_only_similarity_classifications(
    tmp_path: Path,
) -> None:
    summary_path = _write_real_benchmark_cycle(
        tmp_path,
        novel_method=True,
        similarity_classification="unknown",
    )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    report_path = Path(summary["demo"]["report_path"])
    report_path.write_text(_paper_style_report(), encoding="utf-8")

    report = audit_publication_quality(cycle_summary_path=summary_path, target="ccf-b")

    checks = {check.check_id: check for check in report.checks}
    assert checks["similarity_classification_coverage"].status.value == "fail"
    assert checks["similarity_classified_finding_breadth"].status.value == "fail"
    assert "unknown" in checks["similarity_classification_coverage"].message
    assert report.verdict is PublicationAuditVerdict.FAIL
    assert report.publishable is False


def test_publication_audit_blocks_sparse_classified_similarity_findings(
    tmp_path: Path,
) -> None:
    summary_path = _write_real_benchmark_cycle(
        tmp_path,
        novel_method=True,
        similarity_classifications=("adjacent_work", *("unknown" for _ in range(9))),
    )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    report_path = Path(summary["demo"]["report_path"])
    report_path.write_text(_paper_style_report(), encoding="utf-8")

    report = audit_publication_quality(cycle_summary_path=summary_path, target="ccf-b")

    checks = {check.check_id: check for check in report.checks}
    assert checks["similarity_classified_finding_breadth"].status.value == "fail"
    assert checks["similarity_classification_coverage"].status.value == "pass"
    assert report.verdict is PublicationAuditVerdict.FAIL
    assert report.publishable is False


def test_publication_audit_blocks_underperforming_method_candidate(
    tmp_path: Path,
) -> None:
    summary_path = _write_real_benchmark_cycle(
        tmp_path,
        novel_method=True,
        method_delta=-0.0011,
    )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    report_path = Path(summary["demo"]["report_path"])
    report_path.write_text(_paper_style_report(), encoding="utf-8")

    report = audit_publication_quality(cycle_summary_path=summary_path, target="ccf-b")

    checks = {check.check_id: check for check in report.checks}
    assert checks["method_innovation_evidence"].status.value == "pass"
    assert checks["method_effect_evidence"].status.value == "fail"
    assert "underperformed" in checks["method_effect_evidence"].message
    assert report.verdict is PublicationAuditVerdict.NEEDS_REVISION
    assert report.publishable is False


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


def _paper_style_report() -> str:
    return "\n".join(
        [
            "# UCI Pendigits Baseline Report",
            "",
            "## Abstract",
            "",
            "Evidence-backed abstract.",
            "",
            "## Introduction",
            "",
            "Evidence-backed introduction.",
            "",
            "## Related Work",
            "",
            "Source-backed related work.",
            "",
            "## Method",
            "",
            "Executed method.",
            "",
            "## Experiments",
            "",
            "Executed experiments.",
            "",
            "## Results",
            "",
            "- accuracy = 0.91",
            "",
            "## Limitations",
            "",
            "- Baseline-only benchmark.",
            "",
            "## Conclusion",
            "",
            "Bounded conclusion.",
            "",
            "## References",
            "",
            "- Source-backed references.",
            "",
        ]
    )


def _write_real_benchmark_cycle(
    tmp_path: Path,
    *,
    novel_method: bool = False,
    method_delta: float | None = 0.03,
    similarity_classification: str | None = None,
    similarity_classifications: tuple[str, ...] | None = None,
) -> Path:
    cycle_dir = tmp_path / "runs" / "cycle-real"
    task_id = "pendigits_contrastive_centroid" if novel_method else "pendigits_centroid_baseline"
    demo_slug = task_id.replace("_", "-")
    experiment_dir = cycle_dir / "demo" / demo_slug
    (experiment_dir / "data").mkdir(parents=True)
    (experiment_dir / "artifacts").mkdir()
    (experiment_dir / "logs").mkdir()
    (experiment_dir / "validation").mkdir()
    (experiment_dir / "evidence").mkdir()
    (experiment_dir / "run").mkdir()
    (experiment_dir / "report").mkdir()

    run_py = experiment_dir / "run.py"
    run_py.write_text("print('ran pendigits')\n", encoding="utf-8")
    data_path = experiment_dir / "data" / f"{task_id}.csv"
    data_path.write_text("row_id,split,x0,label\n1,test,0,0\n", encoding="utf-8")
    metrics_path = experiment_dir / "metrics.json"
    metrics = {
        "accuracy": 0.91,
        "macro_f1": 0.90,
        "test_rows": 3498.0,
        "train_rows": 7494.0,
        "dataset_rows": 10992.0,
        "class_count": 10.0,
        "ablation_accuracy_first8": 0.85,
        "accuracy_delta_vs_ablation": 0.06,
        "accuracy_standard_error": 0.0048,
    }
    metrics_path.write_text(
        json.dumps({"status": "success", "metrics": metrics}),
        encoding="utf-8",
    )
    (experiment_dir / "artifacts" / "predictions.csv").write_text("y_hat\n1\n", encoding="utf-8")
    (experiment_dir / "artifacts" / "summary.md").write_text("# Summary\n", encoding="utf-8")
    (experiment_dir / "artifacts" / "ablation.csv").write_text(
        "model,accuracy\nbaseline,0.91\nablation,0.85\n",
        encoding="utf-8",
    )
    (experiment_dir / "artifacts" / "dataset_sources.json").write_text(
        json.dumps({"real_dataset": True, "sources": ["https://archive.ics.uci.edu/"]}),
        encoding="utf-8",
    )
    innovation_artifacts = []
    if novel_method:
        innovation_path = experiment_dir / "artifacts" / "innovation_evidence.json"
        innovation_path.write_text(
            json.dumps(
                {
                    "proposed_method": "contrastive centroid calibration",
                    "mechanism": "calibrates class centroids with evidence-bound ablation.",
                    "baseline_comparison": "nearest centroid",
                    **(
                        {
                            "baseline_accuracy": 0.88,
                            "candidate_accuracy": 0.88 + method_delta,
                            "accuracy_delta_vs_baseline": method_delta,
                        }
                        if method_delta is not None
                        else {}
                    ),
                }
            ),
            encoding="utf-8",
        )
        innovation_artifacts.append("artifacts/innovation_evidence.json")
    (experiment_dir / "logs" / "run.log").write_text("ok\n", encoding="utf-8")
    validation_json = experiment_dir / "validation" / "validation-report.json"
    validation_json.write_text(
        json.dumps(
            {
                "run_id": "run_real",
                "status": "passed",
                "issues": [],
                "statistical_notes": [
                    {
                        "metric_name": "accuracy",
                        "check": "confidence_interval",
                        "message": "95% CI for accuracy mean: [0.9, 0.92]",
                    }
                ],
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
                        "claim_id": "pendigits_centroid_baseline_claim",
                        "evidence_ref": "run_real:accuracy",
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
        "# UCI Pendigits Baseline Report\n\n"
        "## Results\n\n- accuracy = 0.91\n\n"
        "## Limitations\n\n- Missing full manuscript sections.\n",
        encoding="utf-8",
    )
    run_record = {
        "task_metadata": {
            "real_dataset": True,
            "dataset_realism": "real_public_benchmark",
            "baseline": "nearest centroid",
            "ablation": "first-8-features ablation",
            "baseline_only": not novel_method,
            **(
                {
                    "proposed_method": "contrastive centroid calibration",
                    "novel_contribution": "calibration mechanism tested against baseline and ablation",
                }
                if novel_method
                else {}
            ),
        },
        "artifacts": [
            "artifacts/predictions.csv",
            "artifacts/summary.md",
            "artifacts/ablation.csv",
            "artifacts/dataset_sources.json",
            *innovation_artifacts,
        ],
        "logs": ["logs/run.log"],
        "metrics": {
            "path": metrics_path.as_posix(),
            "values": metrics,
        },
        "reproducibility": {
            "command": f"airesearcher run-demo --demo {task_id}",
            "commit_sha": "abc1234",
            "config_hash": "cfg",
            "data_hash": file_hash(data_path),
            "dependency_lock_status": "poetry.lock present",
            "python_version": "3.10.20",
        },
        "run": {
            "id": "run_real",
            "task_id": task_id,
            "project_id": "public-benchmark-pendigits",
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
    classification = similarity_classification or (
        "adjacent_work" if novel_method else "unknown"
    )
    classifications = similarity_classifications or tuple(classification for _ in range(10))
    similarity_summary.write_text(
        "\n".join(
            [
                "## Findings",
                "",
                *[
                    f"### Source {index}\n\n- Classification: `{classifications[index]}`\n"
                    f"- Source URL/DOI: `https://arxiv.org/abs/0000.{index:05d}` / `unknown`"
                    for index in range(len(classifications))
                ],
            ]
        ),
        encoding="utf-8",
    )
    cycle_summary = {
        "cycle_id": "cycle-real",
        "project_id": "project_1",
        "literature": {
            "query_count": 4,
            "document_count": 20,
            "fetches": [
                {"source": "arxiv", "query": "q1", "paper_count": 5, "error": None},
                {"source": "semantic_scholar", "query": "q1", "paper_count": 5, "error": None},
            ],
        },
        "similarity": {
            "finding_count": 10,
            "summary_path": similarity_summary.as_posix(),
            "fetches": [
                {"source": "arxiv", "query": "q1", "paper_count": 3, "error": None},
                {"source": "semantic_scholar", "query": "q2", "paper_count": 3, "error": None},
                {"source": "arxiv", "query": "q3", "paper_count": 3, "error": None},
                {"source": "semantic_scholar", "query": "q4", "paper_count": 3, "error": None},
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
