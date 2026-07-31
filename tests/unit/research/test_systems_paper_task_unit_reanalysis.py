from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.research import systems_paper_task_unit_reanalysis as module
from autoresearch.research.systems_paper_currency_audit import (
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
    IndependentUnitAudit,
    ParentSystemsPaperEvidence,
    StatisticalReplayCertificate,
    StatisticalReplayObservation,
    StatisticalReplayProjection,
    TaskLevelComparison,
    bootstrap_mean_interval,
    build_statistical_replay_payload,
    exact_sign_test,
)
from autoresearch.research.systems_paper_task_unit_reanalysis import (
    AUDIT_GIT_COMMIT,
    AUDIT_MANIFEST_FILE_SHA256,
    AUDIT_MANIFEST_HASH,
    AUDIT_PROJECTION_HASH,
    AUDIT_REPAIR_PLAN_HASH,
    AUDIT_REPORT_FILE_SHA256,
    AUDIT_REPORT_HASH,
    AUDIT_SOURCE_REGISTRY_HASH,
    AdditiveNoteMechanicalReview,
    AuditEvidenceBinding,
    ManuscriptSurfaceDisposition,
    OriginalClaimDisposition,
    TaskUnitReanalysisIntegrityError,
    TaskUnitReanalysisReport,
    build_additive_note_claims,
    build_claim_disposition_ledger,
    build_paper_surface_inventory,
    load_task_unit_reanalysis,
    render_task_unit_reanalysis_markdown,
    task_unit_reanalysis_json_schemas,
    write_task_unit_reanalysis,
)
from autoresearch.research.workload_qualified_opportunity import InterpreterRuntime

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "src/autoresearch/research/assets/frozen_systems_paper_currency_probe_v1.py"
BUILT_AT = datetime(2026, 7, 31, 12, 30, tzinfo=timezone.utc)
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
        "package_relative_path": "runs/manual-live/task260-final-paper-v2",
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


def _audit(parent: ParentSystemsPaperEvidence) -> IndependentUnitAudit:
    comparisons = []
    for index, (task_id, difference) in enumerate(zip(TASK_IDS, TASK_DIFFERENCES, strict=True)):
        family = "uci" if index < 4 else "mdbench"
        baseline_success = difference == 0.0
        comparisons.append(
            TaskLevelComparison(
                task_id=task_id,
                family=family,
                seeds=[211, 223, 227],
                full_loop_success_by_seed={"211": True, "223": True, "227": True},
                execute_once_success_by_seed={
                    "211": baseline_success,
                    "223": baseline_success,
                    "227": baseline_success,
                },
                full_loop_scientific_hashes=[_hash(f"full:{task_id}")] * 3,
                execute_once_scientific_hashes=[_hash(f"baseline:{task_id}")] * 3,
                deterministic_seed_duplicate=True,
                task_difference=difference,
            )
        )
    values = list(TASK_DIFFERENCES)
    wins, losses, ties, one_sided, two_sided = exact_sign_test(values)
    return IndependentUnitAudit.create(
        parent_evidence_hash=parent.parent_evidence_hash,
        task_comparisons=comparisons,
        frozen_seed_pair_differences=values * 3,
        frozen_seed_pair_mean=0.5,
        frozen_seed_pair_ci95=(1 / 3, 2 / 3),
        task_level_differences=values,
        task_level_mean=0.5,
        task_level_ci95=bootstrap_mean_interval(values, resamples=20_000, seed=2604),
        sign_test_wins=wins,
        sign_test_losses=losses,
        sign_test_ties=ties,
        sign_test_one_sided_p=one_sided,
        sign_test_two_sided_p=two_sided,
        family_task_counts={"mdbench": 6, "uci": 4},
        family_mean_differences={"mdbench": 2 / 3, "uci": 0.25},
        family_balanced_mean=11 / 24,
        conclusion="Synthetic independent-task unit correction for deterministic tests.",
    )


def _write_surface_fixture(package_dir: Path) -> dict[str, str]:
    claims = [
        {
            "claim_id": f"C{index}",
            "text": f"Original claim {index}.",
            "status": "supported",
            "evidence_id": f"evidence-{index}",
        }
        for index in range(1, 9)
    ]
    files = {
        "evidence/claim-evidence-map.json": json.dumps(
            {"claims": claims, "graph_hash": _hash("claim-graph")}
        ),
        "frozen-inputs/paper-values.json": json.dumps(
            {
                "task_count": 10,
                "task_family_counts": {"uci": 4, "mdbench": 6},
                "seed_count": 3,
                "seeds": [211, 223, 227],
                "paired_mean_gain": 0.5,
                "paired_differences": list(TASK_DIFFERENCES) * 3,
                "bootstrap_ci95_lower": 1 / 3,
                "bootstrap_ci95_upper": 2 / 3,
                "mode_metrics": {
                    "full_loop": {
                        "task_success_rate": 1.0,
                        "exact_reproduction_rate": 1.0,
                        "unsupported_claim_count": 0,
                    },
                    "execute_once": {"task_success_rate": 0.5},
                },
                "route_a_rounds": [{"ci95_lower": -1.0, "ci95_upper": 0.5}],
            }
        ),
        "paper/source/values.tex": (
            "\\newcommand{\\BootstrapResamples}{20000}\n"
            "\\newcommand{\\PairedGain}{0.50}\n"
            "\\newcommand{\\PairedCILower}{0.333333}\n"
            "\\newcommand{\\PairedCIUpper}{0.666667}\n"
        ),
        "paper/source/tables/mode-results.tex": "Full loop & 1.00 \\\\\n",
        "paper/source/tables/route-a-results.tex": "Round 1 & negative \\\\\n",
        "paper/source/sections/abstract.tex": (
            "The study uses \\SeedCount{} seeds. The paired interval uses repeated cells.\n"
        ),
        "paper/source/sections/introduction.tex": (
            "The principal endpoint is paired task success.\n"
        ),
        "paper/source/sections/experiments.tex": (
            "Seeds are included in each cell identity.\n"
            "We report the mean over the 30 task-seed pairs.\n"
        ),
        "paper/source/sections/results.tex": (
            "The \\PairedGain{} result uses \\BootstrapResamples{} resamples.\n"
        ),
        "paper/source/sections/discussion.tex": (
            "The paired confidence interval excludes zero.\n"
        ),
        "paper/source/sections/limitations.tex": (
            "Seeds do not provide independent stochastic policies.\n"
        ),
        "paper/source/sections/conclusion.tex": (
            "The complete loop exceeded execute-once in the frozen matrix.\n"
        ),
        "paper/source/sections/appendix.tex": "Recompute the paired mean.\n",
    }
    hashes = {}
    for relative_path, content in files.items():
        path = package_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        hashes[relative_path] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _runtime(role_id: str, digit: str) -> InterpreterRuntime:
    return InterpreterRuntime.create(
        role_id=role_id,
        executable_locator_hash=_hash(f"locator-{digit}"),
        executable_sha256=digit * 64,
        python_version="Python 3.10.test",
    )


def _replay(audit: IndependentUnitAudit) -> StatisticalReplayCertificate:
    projection = StatisticalReplayProjection.create_from_tasks(audit.task_comparisons)
    contract_hash = canonical_sha256(projection.model_dump(mode="json"))
    observations = [
        StatisticalReplayObservation.create(
            runtime=_runtime("auditor-a", "a"),
            projection_sha256=projection.projection_sha256,
            output_file_sha256="1" * 64,
            output_contract_sha256=contract_hash,
        ),
        StatisticalReplayObservation.create(
            runtime=_runtime("auditor-b", "b"),
            projection_sha256=projection.projection_sha256,
            output_file_sha256="2" * 64,
            output_contract_sha256=contract_hash,
        ),
    ]
    return StatisticalReplayCertificate.create(
        replay_input_sha256=canonical_sha256(build_statistical_replay_payload(audit)),
        frozen_runner_sha256=_hash("runner"),
        projection_sha256=projection.projection_sha256,
        observations=observations,
    )


def _binding(
    monkeypatch: pytest.MonkeyPatch,
    parent: ParentSystemsPaperEvidence,
    audit: IndependentUnitAudit,
) -> AuditEvidenceBinding:
    monkeypatch.setattr(module, "AUDIT_UNIT_HASH", audit.audit_hash)
    payload = {
        "schema_version": "systems-paper-task-unit-audit-binding-v1",
        "audit_git_commit": AUDIT_GIT_COMMIT,
        "audit_package_relative_path": "fixture/task26370",
        "parent_evidence_hash": parent.parent_evidence_hash,
        "audit_report_hash": AUDIT_REPORT_HASH,
        "audit_report_file_sha256": AUDIT_REPORT_FILE_SHA256,
        "audit_manifest_hash": AUDIT_MANIFEST_HASH,
        "audit_manifest_file_sha256": AUDIT_MANIFEST_FILE_SHA256,
        "independent_unit_audit_hash": audit.audit_hash,
        "independent_unit_file_sha256": module.AUDIT_UNIT_FILE_SHA256,
        "statistical_projection_hash": AUDIT_PROJECTION_HASH,
        "repair_plan_hash": AUDIT_REPAIR_PLAN_HASH,
        "source_registry_hash": AUDIT_SOURCE_REGISTRY_HASH,
        "publication_ready": False,
        "public_release_authorized": False,
        "external_submission_authorized": False,
    }
    payload["binding_hash"] = canonical_sha256(payload)
    return AuditEvidenceBinding.model_validate(payload)


def _report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> TaskUnitReanalysisReport:
    package_dir = tmp_path / "parent"
    hashes = _write_surface_fixture(package_dir)
    monkeypatch.setattr(module, "EXPECTED_PAPER_SURFACE_HASHES", hashes)
    parent = _parent()
    audit = _audit(parent)
    binding = _binding(monkeypatch, parent, audit)
    inventory = build_paper_surface_inventory(package_dir, parent=parent)
    ledger = build_claim_disposition_ledger(
        package_dir,
        parent=parent,
        audit_binding=binding,
        surface_inventory=inventory,
    )
    claims = build_additive_note_claims(
        audit=audit,
        audit_binding=binding,
        parent=parent,
    )
    review = AdditiveNoteMechanicalReview(
        scan_scope=["full-rendered-markdown"],
        banned_terms=list(BANNED_AI_TONE_TERMS),
        banned_term_counts={},
        em_dash_count=0,
        unbound_original_claim_count=0,
        unbound_numeric_leaf_count=0,
        unbound_table_count=0,
        unbound_inference_surface_count=0,
        venue_fit_certified=False,
        target_venue_unspecified=True,
        passed=True,
    )
    return TaskUnitReanalysisReport.create(
        built_at=BUILT_AT,
        parent=parent,
        audit_binding=binding,
        surface_inventory=inventory,
        claim_ledger=ledger,
        independent_unit_audit=audit,
        note_claims=claims,
        replay_certificate=_replay(audit),
        mechanical_review=review,
    )


def test_surface_inventory_covers_every_claim_number_table_and_inference_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _report(tmp_path, monkeypatch)
    inventory = report.surface_inventory

    assert inventory.original_claim_ids == list(module.EXPECTED_ORIGINAL_CLAIM_IDS)
    assert len(inventory.numeric_bindings) == len(
        list(
            module._numeric_leaves(  # noqa: SLF001
                json.loads(
                    (tmp_path / "parent" / module.PAPER_VALUES_PATH).read_text(
                        encoding="utf-8"
                    )
                )
            )
        )
    )
    assert len(inventory.table_bindings) == 2
    assert inventory.manuscript_surfaces
    assert any(
        item.disposition is ManuscriptSurfaceDisposition.RETIRE_PUBLICATION_INFERENCE
        for item in inventory.manuscript_surfaces
    )
    assert inventory.unbound_original_claim_count == 0
    assert inventory.unbound_numeric_leaf_count == 0
    assert inventory.unbound_table_count == 0
    assert inventory.unbound_inference_surface_count == 0


def test_unknown_original_claim_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_dir = tmp_path / "parent"
    hashes = _write_surface_fixture(package_dir)
    claim_path = package_dir / module.CLAIM_MAP_PATH
    claim_map = json.loads(claim_path.read_text(encoding="utf-8"))
    claim_map["claims"].append(
        {
            "claim_id": "C9",
            "text": "Unexpected claim.",
            "status": "supported",
            "evidence_id": "evidence-9",
        }
    )
    claim_path.write_text(json.dumps(claim_map), encoding="utf-8")
    hashes[module.CLAIM_MAP_PATH] = hashlib.sha256(claim_path.read_bytes()).hexdigest()
    monkeypatch.setattr(module, "EXPECTED_PAPER_SURFACE_HASHES", hashes)

    with pytest.raises(TaskUnitReanalysisIntegrityError, match="claim IDs changed"):
        build_paper_surface_inventory(package_dir, parent=_parent())


def test_claim_ledger_retires_only_original_c2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _report(tmp_path, monkeypatch)

    dispositions = {
        item.original_claim_id: item.disposition
        for item in report.claim_ledger.original_claim_bindings
    }
    assert dispositions["C2"] is OriginalClaimDisposition.RETIRE_PUBLICATION_INFERENCE
    assert report.claim_ledger.retired_publication_inference_claim_ids == ["C2"]
    assert report.claim_ledger.original_preregistration_replaced is False
    assert report.claim_ledger.parent_manuscript_rewritten is False


def test_additive_note_reports_task_statistics_without_claiming_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _report(tmp_path, monkeypatch)
    markdown = render_task_unit_reanalysis_markdown(report)

    assert report.independent_unit_audit.task_level_differences == list(TASK_DIFFERENCES)
    assert report.independent_unit_audit.task_level_ci95 == (0.2, 0.8)
    assert report.independent_unit_audit.sign_test_two_sided_p == 0.0625
    assert report.independent_unit_audit.family_balanced_mean == pytest.approx(11 / 24)
    assert len(report.note_claims) == 9
    assert "post-audit reanalysis" in markdown
    assert "not fresh confirmatory evidence" in markdown
    assert "—" not in markdown
    assert not any(term.casefold() in markdown.casefold() for term in BANNED_AI_TONE_TERMS)
    assert report.publication_ready is False
    assert report.external_submission_authorized is False


def test_report_rejects_audit_hash_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _report(tmp_path, monkeypatch)
    payload = report.model_dump(mode="json")
    payload["audit_binding"]["independent_unit_audit_hash"] = "f" * 64
    payload["audit_binding"]["binding_hash"] = canonical_sha256(
        {
            key: value
            for key, value in payload["audit_binding"].items()
            if key != "binding_hash"
        }
    )
    payload["report_hash"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "report_hash"}
    )

    with pytest.raises(ValueError, match="Task 263.7.0 binding changed"):
        TaskUnitReanalysisReport.model_validate(payload)


def test_stdlib_runner_recomputes_exact_task_projection(
    tmp_path: Path,
) -> None:
    audit = _audit(_parent())
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text(json.dumps(build_statistical_replay_payload(audit)), encoding="utf-8")

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
    assert observed == StatisticalReplayProjection.create_from_tasks(audit.task_comparisons)


def test_persistence_recursive_manifest_and_tamper_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _report(tmp_path, monkeypatch)
    output_dir = tmp_path / "output"

    manifest = write_task_unit_reanalysis(output_dir, report)
    loaded_report, loaded_manifest = load_task_unit_reanalysis(output_dir)

    assert loaded_report == report
    assert loaded_manifest == manifest
    assert manifest.report_hash == report.report_hash
    assert manifest.files[module.REANALYSIS_MARKDOWN_FILENAME]

    markdown_path = output_dir / module.REANALYSIS_MARKDOWN_FILENAME
    markdown_path.write_text(markdown_path.read_text(encoding="utf-8") + "tamper\n", encoding="utf-8")
    with pytest.raises(TaskUnitReanalysisIntegrityError, match="file set or hash changed"):
        load_task_unit_reanalysis(output_dir)


def test_schema_bundle_contains_report_manifest_and_claim_contracts() -> None:
    schemas = task_unit_reanalysis_json_schemas()

    assert "TaskUnitReanalysisReport" in schemas
    assert "TaskUnitReanalysisManifest" in schemas
    assert "ClaimDispositionLedger" in schemas
    assert "PaperSurfaceInventory" in schemas
