from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.research.systems_paper_currency_audit import (
    AUDIT_MANIFEST_FILENAME,
    BANNED_AI_TONE_TERMS,
    PARENT_GIT_COMMIT,
    PARENT_MATRIX_FILE_SHA256,
    PARENT_PACKAGE_FILE_SHA256,
    PARENT_PACKAGE_HASH,
    PARENT_PDF_SHA256,
    PARENT_PREREGISTRATION_FILE_SHA256,
    PARENT_SYSTEMS_GATE_FILE_SHA256,
    PARENT_SYSTEMS_GATE_HASH,
    PARENT_SYSTEMS_RESULT_FILE_SHA256,
    PARENT_SYSTEMS_RESULT_HASH,
    AuditDimension,
    AuditResearchBrief,
    FindingSeverity,
    IndependentUnitAudit,
    LiteraturePerspective,
    PaperFinding,
    ParentSystemsPaperEvidence,
    PrimarySourceFetchError,
    PrimarySourceSnapshot,
    RepairClass,
    SourceResponse,
    StatisticalReplayCertificate,
    StatisticalReplayObservation,
    StatisticalReplayProjection,
    SystemsPaperCurrencyAuditReport,
    SystemsPaperCurrencyIntegrityError,
    SystemsPaperRepairPlan,
    build_independent_unit_audit,
    build_statistical_replay_payload,
    exact_sign_test,
    fetch_primary_source_registry,
    load_systems_paper_currency_audit,
    scan_paper_language,
    source_definitions,
    write_systems_paper_currency_audit,
)
from autoresearch.research.workload_qualified_opportunity import InterpreterRuntime

ROOT = Path(__file__).resolve().parents[3]
RUNNER = (
    ROOT
    / "src/autoresearch/research/assets/frozen_systems_paper_currency_probe_v1.py"
)
CHECKED_AT = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
TASK_IDS = (
    "pendigits_variance_calibrated_prototypes",
    "letter_variance_calibrated_prototypes",
    "spambase_variance_calibrated_prototypes",
    "skin_variance_calibrated_prototypes",
    "mdbench-binocular-rivalry-model",
    "mdbench-interacting-bar-magnets",
    "mdbench-oscillator-death-model",
    "mdbench-population-growth-naive",
    "mdbench-rc-circuit",
    "mdbench-van-der-pol-oscillator-simplified",
)
TASK_DIFFERENCES = (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _parent() -> ParentSystemsPaperEvidence:
    payload = {
        "schema_version": "task260-parent-systems-paper-evidence-v1",
        "parent_git_commit": PARENT_GIT_COMMIT,
        "package_relative_path": "fixture/task260-final-paper-v2",
        "package_id": "task260-final-paper-v2",
        "package_hash": PARENT_PACKAGE_HASH,
        "package_file_sha256": PARENT_PACKAGE_FILE_SHA256,
        "manuscript_pdf_sha256": PARENT_PDF_SHA256,
        "systems_result_hash": PARENT_SYSTEMS_RESULT_HASH,
        "systems_result_file_sha256": PARENT_SYSTEMS_RESULT_FILE_SHA256,
        "systems_gate_hash": PARENT_SYSTEMS_GATE_HASH,
        "systems_gate_file_sha256": PARENT_SYSTEMS_GATE_FILE_SHA256,
        "matrix_file_sha256": PARENT_MATRIX_FILE_SHA256,
        "preregistration_file_sha256": PARENT_PREREGISTRATION_FILE_SHA256,
        "external_submission_authorized": False,
        "immutable_parent": True,
    }
    payload["parent_evidence_hash"] = canonical_sha256(payload)
    return ParentSystemsPaperEvidence.model_validate(payload)


def _write_synthetic_route_b(package_dir: Path, *, vary_seed_hash: bool = False) -> None:
    inputs = package_dir / "frozen-inputs"
    inputs.mkdir(parents=True)
    tasks = [
        {
            "task_id": task_id,
            "family": "uci" if index < 4 else "mdbench",
        }
        for index, task_id in enumerate(TASK_IDS)
    ]
    (inputs / "systems-preregistration.json").write_text(
        json.dumps({"seeds": [211, 223, 227], "tasks": tasks}),
        encoding="utf-8",
    )
    entries: list[dict[str, str]] = []
    baseline_successes = [difference == 0 for difference in TASK_DIFFERENCES]
    for mode in ("full_loop", "execute_once"):
        for seed in (211, 223, 227):
            for task_index, task in enumerate(tasks):
                task_id = task["task_id"]
                cell_id = f"{mode}--seed-{seed}--{task_id}"
                scientific_key = f"{mode}:{task_id}"
                if vary_seed_hash and mode == "full_loop" and task_index == 0 and seed == 227:
                    scientific_key += ":changed"
                scientific_hash = _hash(scientific_key)
                result_hash = _hash(cell_id)
                success = True if mode == "full_loop" else baseline_successes[task_index]
                cell = {
                    "cell_id": cell_id,
                    "result_hash": result_hash,
                    "scientific_result_hash": scientific_hash,
                    "task_id": task_id,
                    "family": task["family"],
                    "mode": mode,
                    "seed": seed,
                    "task_success": success,
                }
                path = (
                    package_dir
                    / "dossier/route-b-systems-benchmark/cells"
                    / cell_id
                    / "cell-result.json"
                )
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(cell), encoding="utf-8")
                entries.append(
                    {
                        "cell_id": cell_id,
                        "result_hash": result_hash,
                        "scientific_result_hash": scientific_hash,
                    }
                )
    for index in range(150):
        entries.append(
            {
                "cell_id": f"unused-{index}",
                "result_hash": _hash(f"unused-result-{index}"),
                "scientific_result_hash": _hash(f"unused-science-{index}"),
            }
        )
    (inputs / "systems-matrix-manifest.json").write_text(
        json.dumps({"cells": entries}),
        encoding="utf-8",
    )
    (inputs / "systems-benchmark-result.json").write_text(
        json.dumps(
            {
                "paired_differences": list(TASK_DIFFERENCES) * 3,
                "paired_mean_gain_vs_execute_once": 0.5,
                "bootstrap_ci95_lower": 1 / 3,
                "bootstrap_ci95_upper": 2 / 3,
            }
        ),
        encoding="utf-8",
    )


def _mock_response(url: str) -> SourceResponse:
    definition = next(item for item in source_definitions() if item.url == url)
    body = ("\n".join(definition.required_markers) + "\n").encode()
    return SourceResponse(
        status_code=200,
        media_type="text/html",
        body=body,
        final_url=url,
    )


def _runtime(role_id: str, digit: str) -> InterpreterRuntime:
    return InterpreterRuntime.create(
        role_id=role_id,
        executable_locator_hash=_hash(f"locator-{digit}"),
        executable_sha256=digit * 64,
        python_version="Python 3.10.test",
    )


def _replay(audit: IndependentUnitAudit) -> StatisticalReplayCertificate:
    projection = StatisticalReplayProjection.create_from_tasks(audit.task_comparisons)
    output_contract = canonical_sha256(projection.model_dump(mode="json"))
    observations = [
        StatisticalReplayObservation.create(
            runtime=_runtime("auditor-a", "a"),
            projection_sha256=projection.projection_sha256,
            output_file_sha256="1" * 64,
            output_contract_sha256=output_contract,
        ),
        StatisticalReplayObservation.create(
            runtime=_runtime("auditor-b", "b"),
            projection_sha256=projection.projection_sha256,
            output_file_sha256="2" * 64,
            output_contract_sha256=output_contract,
        ),
    ]
    return StatisticalReplayCertificate.create(
        replay_input_sha256=canonical_sha256(build_statistical_replay_payload(audit)),
        frozen_runner_sha256=_hash("runner"),
        projection_sha256=projection.projection_sha256,
        observations=observations,
    )


def test_task_level_reanalysis_collapses_deterministic_seed_duplicates(tmp_path: Path) -> None:
    package_dir = tmp_path / "parent"
    _write_synthetic_route_b(package_dir)

    audit = build_independent_unit_audit(package_dir, parent=_parent())

    assert audit.frozen_seed_pair_differences == list(TASK_DIFFERENCES) * 3
    assert audit.task_level_differences == list(TASK_DIFFERENCES)
    assert audit.task_level_mean == 0.5
    assert audit.task_level_ci95 == (0.2, 0.8)
    assert audit.sign_test_wins == 5
    assert audit.sign_test_losses == 0
    assert audit.sign_test_ties == 5
    assert audit.sign_test_one_sided_p == 0.03125
    assert audit.sign_test_two_sided_p == 0.0625
    assert audit.family_mean_differences == {"mdbench": 2 / 3, "uci": 0.25}
    assert audit.family_balanced_mean == pytest.approx(11 / 24)
    assert audit.original_interval_valid_for_independent_task_inference is False
    assert audit.original_contribution_gate_reusable_for_publication_inference is False
    assert all(item.deterministic_seed_duplicate for item in audit.task_comparisons)


def test_seed_hash_variation_fails_closed_instead_of_being_silently_collapsed(
    tmp_path: Path,
) -> None:
    package_dir = tmp_path / "parent"
    _write_synthetic_route_b(package_dir, vary_seed_hash=True)

    with pytest.raises(ValueError, match="scientific results vary"):
        build_independent_unit_audit(package_dir, parent=_parent())


def test_exact_sign_test_handles_ties_and_two_sided_evidence() -> None:
    assert exact_sign_test(TASK_DIFFERENCES) == (5, 0, 5, 0.03125, 0.0625)
    assert exact_sign_test([0.0, 0.0]) == (0, 0, 2, 1.0, 1.0)


def test_mocked_cross_search_retains_five_perspectives_and_maturity_labels(
    tmp_path: Path,
) -> None:
    registry = fetch_primary_source_registry(
        output_dir=tmp_path,
        retrieved_at=CHECKED_AT,
        fetcher=_mock_response,
    )

    assert len(registry.sources) == 21
    assert set(registry.perspective_counts) == set(LiteraturePerspective)
    assert all(count >= 3 for count in registry.perspective_counts.values())
    assert registry.peer_reviewed_count >= 1
    assert registry.preprint_count >= 1
    assert registry.normative_count >= 1
    for source in registry.sources:
        retained = tmp_path / source.snapshot.relative_path
        assert retained.is_file()
        assert hashlib.sha256(retained.read_bytes()).hexdigest() == source.snapshot.body_sha256


def test_primary_source_markers_fail_closed() -> None:
    definition = source_definitions()[0]
    with pytest.raises(PrimarySourceFetchError, match="missing markers"):
        PrimarySourceSnapshot.create(
            definition=definition,
            response=SourceResponse(
                status_code=200,
                media_type="text/html",
                body=b"title only",
                final_url=definition.url,
            ),
            retrieved_at=CHECKED_AT,
        )


def test_full_paper_language_scan_flags_substrings_and_em_dash(tmp_path: Path) -> None:
    paper = tmp_path / "paper/source/sections"
    paper.mkdir(parents=True)
    (paper / "main.tex").write_text(
        "We reveal one result.\nWe reveal another result.\nWe reveal a third result.\n"
        "A claim—another clause.\n",
        encoding="utf-8",
    )
    (tmp_path / "paper/source/references.bib").write_text(
        "@article{x, title={Neutral}}\n",
        encoding="utf-8",
    )

    scan = scan_paper_language(tmp_path)

    assert "reveal" in BANNED_AI_TONE_TERMS
    assert scan.term_counts["reveal"] == 3
    assert scan.em_dash_count == 1
    assert scan.no_banned_tone_or_em_dash is False
    assert all(hit.severity is FindingSeverity.MAJOR for hit in scan.hits)


def test_stdlib_probe_replays_exact_task_projection(tmp_path: Path) -> None:
    package_dir = tmp_path / "parent"
    _write_synthetic_route_b(package_dir)
    audit = build_independent_unit_audit(package_dir, parent=_parent())
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text(
        json.dumps(build_statistical_replay_payload(audit)),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, str(RUNNER), str(input_path), str(output_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stderr
    observed = StatisticalReplayProjection.model_validate_json(
        output_path.read_text(encoding="utf-8")
    )
    expected = StatisticalReplayProjection.create_from_tasks(audit.task_comparisons)
    assert observed == expected


def test_report_persistence_manifest_and_tamper_gate(tmp_path: Path) -> None:
    package_dir = tmp_path / "parent"
    _write_synthetic_route_b(package_dir)
    parent = _parent()
    audit = build_independent_unit_audit(package_dir, parent=parent)
    output_dir = tmp_path / "audit"
    registry = fetch_primary_source_registry(
        output_dir=output_dir,
        retrieved_at=CHECKED_AT,
        fetcher=_mock_response,
    )
    paper_dir = tmp_path / "paper-fixture/paper/source"
    paper_dir.mkdir(parents=True)
    (paper_dir / "main.tex").write_text("Neutral technical prose.\n", encoding="utf-8")
    (paper_dir / "references.bib").write_text("@article{x}\n", encoding="utf-8")
    language_scan = scan_paper_language(tmp_path / "paper-fixture")
    source_id = registry.sources[0].source_id
    finding = PaperFinding.create(
        finding_id="F-TEST-CRITICAL",
        dimension=AuditDimension.EMPIRICAL_VALIDITY,
        severity=FindingSeverity.CRITICAL,
        title="Fixture critical finding",
        diagnosis="Fixture diagnosis with a publication-blocking defect.",
        paper_relative_path="paper/source/main.tex",
        paper_quote="Neutral technical prose.",
        evidence_source_ids=[source_id],
        repair_class=RepairClass.NEW_INDEPENDENT_EVIDENCE,
        required_repair="Collect new independent evidence.",
    )
    report = SystemsPaperCurrencyAuditReport.create(
        built_at=CHECKED_AT,
        parent=parent,
        brief=AuditResearchBrief.create(),
        source_registry=registry,
        independent_unit_audit=audit,
        language_scan=language_scan,
        findings=[finding],
        repair_plan=SystemsPaperRepairPlan.create(),
        replay_certificate=_replay(audit),
    )

    manifest = write_systems_paper_currency_audit(output_dir, report)
    loaded_report, loaded_manifest = load_systems_paper_currency_audit(output_dir)

    assert (output_dir / AUDIT_MANIFEST_FILENAME).is_file()
    assert loaded_report == report
    assert loaded_manifest == manifest
    assert report.publication_ready is False
    assert report.external_submission_authorized is False
    assert Counter(item.severity for item in report.findings)[FindingSeverity.CRITICAL] == 1

    source_path = output_dir / registry.sources[0].snapshot.relative_path
    source_path.write_bytes(source_path.read_bytes() + b"tamper")
    with pytest.raises(SystemsPaperCurrencyIntegrityError, match="file hash changed"):
        load_systems_paper_currency_audit(output_dir)
