"""Opt-in vNext dependency, compatibility, and release-boundary smoke."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from autoresearch.kernel import EventJournal
from autoresearch.runtime import (
    BASELINE_LANGGRAPH_CHARACTERIZATION_HASH,
    FormalVerticalRunEvidence,
    HumanApprovalBoundary,
    IndependentReproductionEvidence,
    RollbackRehearsalEvidence,
    VNextReleaseReport,
    audit_runtime_dependency_lock,
    characterize_installed_langgraph,
    default_capability_matrix,
    default_compatibility_paths,
    load_vnext_release_report,
    write_vnext_release_report,
)

LIVE_ENV = "AUTORESEARCH_VNEXT_RELEASE_LIVE"
MIGRATION_ROOT_ENV = "AUTORESEARCH_VNEXT_RELEASE_MIGRATION_ROOT"
OUTPUT_ENV = "AUTORESEARCH_VNEXT_RELEASE_OUTPUT"

pytestmark = pytest.mark.skipif(
    os.getenv(LIVE_ENV) != "1",
    reason=(
        f"set {LIVE_ENV}=1 after a fresh Sprint migration smoke to audit "
        "the upgraded runtime and reproduce the R1 evidence"
    ),
)


def _read_json(path: Path) -> dict[str, Any]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise AssertionError(f"{path.name} must contain a JSON object")
    return parsed


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_upgraded_runtime_closes_internal_vnext_boundary() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    default_source = (
        repository_root
        / "runs"
        / "manual-live"
        / "task262-sprint-migration-release-live-v1"
        / "migration"
    )
    migration_root = Path(
        os.getenv(MIGRATION_ROOT_ENV, str(default_source))
    ).resolve()
    output_root = Path(
        os.getenv(
            OUTPUT_ENV,
            str(
                repository_root
                / "runs"
                / "manual-live"
                / "task262-vnext-release-live-v1"
            ),
        )
    ).resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise AssertionError("vNext release smoke output must be absent or empty")
    output_root.mkdir(parents=True, exist_ok=True)

    dependency_audit = audit_runtime_dependency_lock(repository_root / "poetry.lock")
    assert dependency_audit.exact_match is True
    characterization = characterize_installed_langgraph()
    assert characterization.all_passed is True

    ledger_path = migration_root / "promotion-ledger.json"
    ledger = _read_json(ledger_path)
    assert ledger["cutover_eligible"] is True
    raw_formal_runs = ledger["formal_runs"]
    assert isinstance(raw_formal_runs, list)
    assert len(raw_formal_runs) == 2

    formal_runs: list[FormalVerticalRunEvidence] = []
    for raw_record in raw_formal_runs:
        assert isinstance(raw_record, dict)
        parity_path = migration_root / str(raw_record["parity_report_path"])
        parity = _read_json(parity_path)
        assert _sha256(parity_path) == raw_record["parity_report_sha256"]
        journal = EventJournal.open(migration_root / str(parity["journal_path"]))
        snapshot = journal.snapshot()
        assert snapshot.seal is not None
        assert snapshot.lineage_hash == parity["journal_lineage_hash"]
        assert snapshot.seal.seal_hash == parity["journal_seal_hash"]
        assert parity["equivalent"] is True
        legacy = parity["legacy"]
        assert isinstance(legacy, dict)
        formal_runs.append(
            FormalVerticalRunEvidence(
                service=str(parity["service"]),
                formal_run_id=str(parity["formal_run_id"]),
                source_id=str(legacy["sprint_id"]),
                scientific_endpoint=str(legacy["scientific_endpoint"]),
                source_fingerprint=str(parity["source_fingerprint"]),
                parity_report_hash=str(raw_record["parity_report_sha256"]),
                journal_lineage_hash=str(parity["journal_lineage_hash"]),
                journal_seal_hash=str(parity["journal_seal_hash"]),
                equivalent=bool(parity["equivalent"]),
                journal_verified=True,
            )
        )

    rollback_path = next(
        (migration_root / "rollback-rehearsals").glob("*.json")
    )
    rollback = _read_json(rollback_path)
    rollback_evidence = RollbackRehearsalEvidence(
        service=str(rollback["service"]),
        target_id="flag.AUTORESEARCH_SPRINT_MIGRATION_MODE.legacy",
        report_hash=_sha256(rollback_path),
        passed=bool(rollback["passed"]),
        lifecycle_result_equal=bool(rollback["lifecycle_result_equal"]),
        projection_equal=bool(rollback["projection_equal"]),
        journal_unchanged=bool(rollback["journal_unchanged"]),
        compatibility_files_preserved=bool(
            rollback["compatibility_files_preserved"]
        ),
    )

    source_summary = migration_root.parent / "smoke-summary.json"
    reproduction_root = output_root / "independent-reproduction"
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "autoresearch.runtime.release",
            str(source_summary),
            str(reproduction_root),
            "--reproduction-id",
            "task262-vnext-release-reproduction-1",
        ],
        cwd=output_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    reproduction = IndependentReproductionEvidence.model_validate_json(
        (
            reproduction_root / "independent-reproduction.json"
        ).read_text(encoding="utf-8")
    )
    assert reproduction.passed is True

    report = VNextReleaseReport.create(
        baseline_characterization_hash=BASELINE_LANGGRAPH_CHARACTERIZATION_HASH,
        dependency_audit=dependency_audit,
        upgraded_characterization=characterization,
        formal_vertical_runs=formal_runs,
        rollback_rehearsal=rollback_evidence,
        independent_reproduction=reproduction,
        compatibility_paths=default_compatibility_paths(),
        capabilities=default_capability_matrix(),
        approval_boundary=HumanApprovalBoundary(),
    )
    report_path = write_vnext_release_report(
        output_root / "vnext-release-report.json",
        report,
    )
    loaded = load_vnext_release_report(report_path)

    assert loaded == report
    assert loaded.release_boundary_passed is True
    assert loaded.release_scope == "internal-compatibility-boundary"
    assert loaded.approval_boundary.unrestricted_execution_enabled is False
    assert loaded.approval_boundary.public_release_enabled is False
    assert loaded.approval_boundary.external_submission_enabled is False
    assert (
        loaded.approval_boundary.safety_policy_self_modification_enabled
        is False
    )

    summary = {
        "schema_version": 1,
        "release_report_hash": loaded.report_hash,
        "dependency_audit_hash": loaded.dependency_audit.audit_hash,
        "dependency_lock_sha256": loaded.dependency_audit.lock_sha256,
        "characterization_hash": loaded.upgraded_characterization.report_hash,
        "formal_vertical_run_ids": [
            item.formal_run_id for item in loaded.formal_vertical_runs
        ],
        "rollback_report_hash": loaded.rollback_rehearsal.report_hash,
        "independent_reproduction_digest": (
            loaded.independent_reproduction.reproduced_digest
        ),
        "internal_boundary_passed": True,
        "public_release_enabled": False,
        "external_submission_enabled": False,
    }
    (output_root / "smoke-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
