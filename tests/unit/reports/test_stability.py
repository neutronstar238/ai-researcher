import json
from pathlib import Path

from autoresearch.reports import PublicationStabilityVerdict, audit_publication_stability


def test_publication_stability_passes_multi_dataset_matrix(tmp_path: Path) -> None:
    cycles = (
        _write_cycle(tmp_path, "cycle-a", dataset="UCI Pendigits", template="generic-article-one-column"),
        _write_cycle(
            tmp_path,
            "cycle-b",
            dataset="UCI Letter Recognition",
            template="acm-acmart-sigconf",
            template_source_kind="external_fetched",
        ),
        _write_cycle(
            tmp_path,
            "cycle-c",
            dataset="UCI Optical Digits",
            template="springer-nature-sn-jnl",
            template_source_kind="external_fetched",
        ),
    )

    report = audit_publication_stability(
        cycle_summary_paths=cycles,
        target="ccf-b-matrix",
        output_dir=tmp_path / "matrix",
    )

    checks = {check.check_id: check for check in report.checks}
    assert report.verdict is PublicationStabilityVerdict.PASS
    assert report.stable is True
    assert checks["cycle_count"].status.value == "pass"
    assert checks["distinct_real_datasets"].status.value == "pass"
    assert checks["paper_template_diversity"].status.value == "pass"
    assert checks["external_template_coverage"].status.value == "pass"
    assert checks["external_conference_template_coverage"].status.value == "pass"
    assert checks["external_journal_template_coverage"].status.value == "pass"
    assert checks["strict_review_context_all_releases"].status.value == "pass"
    assert report.cycles[1].paper_template_venue_kind == "conference"
    assert report.cycles[2].paper_template_venue_kind == "journal"
    assert Path(report.output_path).is_file()
    assert Path(report.markdown_path).is_file()
    payload = json.loads(Path(report.output_path).read_text(encoding="utf-8"))
    assert payload["target"]["min_external_templates"] == 1
    assert payload["target"]["min_external_conference_templates"] == 1
    assert payload["target"]["min_external_journal_templates"] == 1
    assert payload["target"]["require_strict_review_context"] is True
    assert payload["cycles"][2]["paper_template_source_kind"] == "external_fetched"
    assert payload["cycles"][2]["paper_template_venue_kind"] == "journal"
    assert payload["cycles"][2]["review_verdict"] == "pass"
    assert payload["cycles"][2]["strict_review_context_passed"] is True


def test_publication_stability_blocks_stale_cycle_without_strict_review_context(
    tmp_path: Path,
) -> None:
    cycles = (
        _write_cycle(tmp_path, "cycle-a", dataset="UCI Pendigits", template="generic-article-one-column"),
        _write_cycle(
            tmp_path,
            "cycle-b",
            dataset="UCI Letter Recognition",
            template="acm-acmart-sigconf",
            template_source_kind="external_fetched",
        ),
        _write_cycle(
            tmp_path,
            "cycle-c",
            dataset="UCI Optical Digits",
            template="springer-nature-sn-jnl",
            template_source_kind="external_fetched",
            strict_review_context=False,
        ),
    )

    report = audit_publication_stability(
        cycle_summary_paths=cycles,
        target="ccf-b-matrix",
        output_dir=tmp_path / "matrix",
    )

    checks = {check.check_id: check for check in report.checks}
    assert report.verdict is PublicationStabilityVerdict.BLOCKED
    assert checks["strict_review_context_all_releases"].status.value == "fail"
    assert checks["strict_review_context_all_releases"].evidence_refs == (cycles[2].as_posix(),)
    assert report.cycles[2].strict_review_context_status == "review_verdict=unknown"


def test_publication_stability_does_not_require_strict_context_for_mvp(
    tmp_path: Path,
) -> None:
    cycle = _write_cycle(
        tmp_path,
        "cycle-a",
        dataset="UCI Pendigits",
        template="generic-article-one-column",
        strict_review_context=False,
    )

    report = audit_publication_stability(
        cycle_summary_paths=(cycle,),
        target="mvp-matrix",
        output_dir=tmp_path / "matrix",
    )

    checks = {check.check_id: check for check in report.checks}
    assert report.verdict is PublicationStabilityVerdict.PASS
    assert checks["strict_review_context_all_releases"].status.value == "pass"


def test_publication_stability_blocks_generic_template_only_overclaim(tmp_path: Path) -> None:
    cycles = (
        _write_cycle(tmp_path, "cycle-a", dataset="UCI Pendigits", template="generic-article-one-column"),
        _write_cycle(tmp_path, "cycle-b", dataset="UCI Letter Recognition", template="generic-article-two-column"),
        _write_cycle(tmp_path, "cycle-c", dataset="UCI Optical Digits", template="generic-article-one-column"),
    )

    report = audit_publication_stability(
        cycle_summary_paths=cycles,
        target="ccf-b-matrix",
        output_dir=tmp_path / "matrix",
    )

    checks = {check.check_id: check for check in report.checks}
    assert report.verdict is PublicationStabilityVerdict.BLOCKED
    assert checks["paper_template_diversity"].status.value == "pass"
    assert checks["external_template_coverage"].status.value == "fail"
    assert checks["external_conference_template_coverage"].status.value == "fail"
    assert checks["external_journal_template_coverage"].status.value == "fail"
    assert checks["external_template_coverage"].next_action


def test_publication_stability_blocks_journal_only_template_overclaim(tmp_path: Path) -> None:
    cycles = (
        _write_cycle(tmp_path, "cycle-a", dataset="UCI Pendigits", template="generic-article-one-column"),
        _write_cycle(tmp_path, "cycle-b", dataset="UCI Letter Recognition", template="generic-article-two-column"),
        _write_cycle(
            tmp_path,
            "cycle-c",
            dataset="UCI Optical Digits",
            template="springer-nature-sn-jnl",
            template_source_kind="external_fetched",
        ),
    )

    report = audit_publication_stability(
        cycle_summary_paths=cycles,
        target="ccf-b-matrix",
        output_dir=tmp_path / "matrix",
    )

    checks = {check.check_id: check for check in report.checks}
    assert report.verdict is PublicationStabilityVerdict.BLOCKED
    assert checks["external_template_coverage"].status.value == "pass"
    assert checks["external_journal_template_coverage"].status.value == "pass"
    assert checks["external_conference_template_coverage"].status.value == "fail"


def test_publication_stability_blocks_single_cycle_overclaim(tmp_path: Path) -> None:
    cycle = _write_cycle(tmp_path, "cycle-a", dataset="UCI Pendigits", template="generic-article-one-column")

    report = audit_publication_stability(
        cycle_summary_paths=(cycle,),
        target="ccf-b-matrix",
        output_dir=tmp_path / "matrix",
        vault_root=tmp_path / "vault",
        project_id="stability_project",
    )

    checks = {check.check_id: check for check in report.checks}
    assert report.verdict is PublicationStabilityVerdict.BLOCKED
    assert report.stable is False
    assert checks["cycle_count"].status.value == "fail"
    assert checks["release_allowed_cycles"].status.value == "fail"
    assert checks["distinct_real_datasets"].status.value == "fail"
    assert checks["paper_template_diversity"].status.value == "fail"
    assert report.vault_review_path is not None
    assert report.vault_issue_path is not None
    issue = Path(report.vault_issue_path).read_text(encoding="utf-8")
    assert "Publication Stability Blockers" in issue


def test_publication_stability_blocks_failed_cycle(tmp_path: Path) -> None:
    cycles = (
        _write_cycle(tmp_path, "cycle-a", dataset="UCI Pendigits", template="generic-article-one-column"),
        _write_cycle(
            tmp_path,
            "cycle-b",
            dataset="UCI Letter Recognition",
            template="generic-article-two-column",
            release_allowed=False,
        ),
        _write_cycle(tmp_path, "cycle-c", dataset="UCI Optical Digits", template="generic-article-one-column"),
    )

    report = audit_publication_stability(
        cycle_summary_paths=cycles,
        target="ccf-b-matrix",
        output_dir=tmp_path / "matrix",
    )

    checks = {check.check_id: check for check in report.checks}
    assert report.verdict is PublicationStabilityVerdict.BLOCKED
    assert checks["release_allowed_cycles"].status.value == "fail"
    assert checks["release_pass_rate"].status.value == "fail"
    assert checks["no_failed_cycles"].status.value == "fail"


def test_publication_stability_uses_evidence_gate_paper_artifact(tmp_path: Path) -> None:
    cycles = (
        _write_cycle(
            tmp_path,
            "cycle-a",
            dataset="UCI Pendigits",
            template="generic-article-one-column",
            stale_summary_paper_quality=False,
        ),
        _write_cycle(tmp_path, "cycle-b", dataset="UCI Letter Recognition", template="generic-article-two-column"),
        _write_cycle(tmp_path, "cycle-c", dataset="UCI Optical Digits", template="generic-article-one-column"),
    )

    report = audit_publication_stability(
        cycle_summary_paths=cycles,
        target="ccf-b-matrix",
        output_dir=tmp_path / "matrix",
    )

    checks = {check.check_id: check for check in report.checks}
    assert report.cycles[0].paper_quality_passed is True
    assert checks["paper_quality_all_releases"].status.value == "pass"


def _write_cycle(
    tmp_path: Path,
    cycle_id: str,
    *,
    dataset: str,
    template: str,
    template_source_kind: str = "built_in_generic",
    release_allowed: bool = True,
    warning_count: int = 1,
    stale_summary_paper_quality: bool | None = None,
    strict_review_context: bool = True,
    review_verdict: str = "pass",
) -> Path:
    cycle_dir = tmp_path / cycle_id
    run_dir = cycle_dir / "demo" / cycle_id / "run"
    publication_dir = cycle_dir / "publication-audit"
    evidence_dir = cycle_dir / "evidence-gate"
    paper_dir = cycle_dir / "paper-build"
    for path in (run_dir, publication_dir, evidence_dir, paper_dir):
        path.mkdir(parents=True)

    run_record_path = run_dir / "run-record.json"
    run_record_path.write_text(
        json.dumps(
            {
                "task_metadata": {
                    "feature_count": 16,
                    "dataset": dataset,
                    "real_dataset": True,
                    "dataset_realism": "real_public_benchmark",
                    "demo_task": cycle_id,
                },
                "metrics": {"values": {"feature_count": 16, "test_rows": 4000}},
            }
        ),
        encoding="utf-8",
    )
    review_path = None
    review_context_path = None
    if strict_review_context:
        review_path = cycle_dir / "llm-review.json"
        review_path.write_text(
            json.dumps(
                {
                    "quality": {
                        "score": 1.0,
                        "parsed_output": {
                            "verdict": review_verdict,
                            "unsupported_claims": [],
                        },
                    },
                    "subject_path": (cycle_dir / "paper-manuscript" / "manuscript.md").as_posix(),
                }
            ),
            encoding="utf-8",
        )
        review_context_path = cycle_dir / "review-evidence-context.json"
        review_context_path.write_text(
            json.dumps(
                {
                    "audit_summary": {
                        "candidate": {"recorded_metrics": {"feature_count": 16}},
                        "citations": {
                            "formal_references": {
                                "citation_metadata_status": "all_displayed_keys_present",
                                "displayed_count": 3,
                            }
                        },
                        "paper_build": {"paper_quality": {"passed": release_allowed}},
                    }
                }
            ),
            encoding="utf-8",
        )
    checks = [{"check_id": "ok", "status": "pass"}]
    checks.extend(
        {"check_id": f"warning_{index}", "status": "warning"}
        for index in range(warning_count)
    )
    publication_path = publication_dir / "publication-audit.json"
    publication_path.write_text(
        json.dumps(
            {
                "verdict": "pass" if release_allowed else "fail",
                "publishable": release_allowed,
                "score": 0.95 if release_allowed else 0.5,
                "checks": checks,
                "review_path": review_path.as_posix() if review_path is not None else None,
            }
        ),
        encoding="utf-8",
    )
    paper_path = paper_dir / "paper-build.json"
    paper_path.write_text(
        json.dumps(
            {
                "status": "compiled",
                "template": _template_payload(template, template_source_kind),
                "paper_quality": {"passed": release_allowed},
            }
        ),
        encoding="utf-8",
    )
    evidence_path = evidence_dir / "evidence-gate.json"
    evidence_path.write_text(
        json.dumps(
            {
                "verdict": "pass" if release_allowed else "blocked",
                "release_allowed": release_allowed,
                "failed_check_count": 0 if release_allowed else 1,
                "checks": [],
                "paper_build_path": paper_path.as_posix(),
            }
        ),
        encoding="utf-8",
    )
    summary_paper_path = paper_path
    if stale_summary_paper_quality is not None:
        summary_paper_path = paper_dir / "stale-paper-build.json"
        summary_paper_path.write_text(
            json.dumps(
                {
                    "status": "compiled_with_quality_issues",
                    "template": _template_payload(template, template_source_kind),
                    "paper_quality": {"passed": stale_summary_paper_quality},
                }
            ),
            encoding="utf-8",
        )
    summary_path = cycle_dir / "cycle-summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "cycle_id": cycle_id,
                "project_id": f"project-{cycle_id}",
                "demo": {
                    "demo": cycle_id,
                    "run_record_path": run_record_path.as_posix(),
                },
                "publication_audit": {"json_path": publication_path.as_posix()},
                "evidence_gate": {"json_path": evidence_path.as_posix()},
                "paper_build": {"json_path": summary_paper_path.as_posix()},
                "review_evidence_context": {
                    "json_path": review_context_path.as_posix()
                    if review_context_path is not None
                    else None
                },
            }
        ),
        encoding="utf-8",
    )
    return summary_path


def _template_payload(template_id: str, source_kind: str) -> dict[str, str]:
    payload = {"id": template_id, "source_kind": source_kind}
    if template_id == "acm-acmart-sigconf":
        payload.update({"display_name": "ACM acmart SIGCONF", "document_class": "acmart"})
    if template_id == "springer-nature-sn-jnl":
        payload.update({"display_name": "Springer Nature sn-jnl", "document_class": "sn-jnl"})
    return payload
