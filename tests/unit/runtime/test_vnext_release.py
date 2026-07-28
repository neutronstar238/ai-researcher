"""Deterministic release-boundary and compatibility-policy tests."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from autoresearch.runtime import (
    BASELINE_LANGGRAPH_CHARACTERIZATION_HASH,
    EXPECTED_RUNTIME_DEPENDENCIES,
    TARGET_LANGGRAPH_CHARACTERIZATION_HASH,
    DependencyLockAudit,
    FormalVerticalRunEvidence,
    HumanApprovalBoundary,
    IndependentReproductionEvidence,
    LangGraphCharacterizationReport,
    RollbackRehearsalEvidence,
    VNextReleaseReport,
    WriterDisposition,
    audit_runtime_dependency_lock,
    default_capability_matrix,
    default_compatibility_paths,
    load_vnext_release_report,
    reproduce_json_artifact,
    write_vnext_release_report,
)


def _write_lock(path: Path, versions: dict[str, str]) -> None:
    blocks = [
        "\n".join(
            (
                "[[package]]",
                f'name = "{name}"',
                f'version = "{package_version}"',
            )
        )
        for name, package_version in sorted(versions.items())
    ]
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def _dependency_audit(
    tmp_path: Path,
    *,
    drift: bool = False,
) -> DependencyLockAudit:
    versions = dict(EXPECTED_RUNTIME_DEPENDENCIES)
    installed = dict(versions)
    if drift:
        installed["langgraph"] = "1.2.9"
    lock_path = tmp_path / "poetry.lock"
    _write_lock(lock_path, versions)
    return audit_runtime_dependency_lock(
        lock_path,
        installed_versions=installed,
    )


def _characterization() -> LangGraphCharacterizationReport:
    report = LangGraphCharacterizationReport.create(
        langgraph_version=EXPECTED_RUNTIME_DEPENDENCIES["langgraph"],
        langchain_core_version=EXPECTED_RUNTIME_DEPENDENCIES["langchain-core"],
        checkpoint_resume=True,
        static_interrupt=True,
        dynamic_interrupt=True,
        subgraph_execution=True,
        parallel_superstep=True,
        resume_idempotent=True,
        json_state_serializable=True,
    )
    assert report.report_hash == TARGET_LANGGRAPH_CHARACTERIZATION_HASH
    return report


def _vertical(index: int, *, source_id: str | None = None) -> FormalVerticalRunEvidence:
    digest = hashlib.sha256(f"vertical-{index}".encode()).hexdigest()
    return FormalVerticalRunEvidence(
        service="sprint",
        formal_run_id=f"formal-{index}",
        source_id=source_id or f"sprint-{index}",
        scientific_endpoint="negative_result",
        source_fingerprint=digest,
        parity_report_hash=digest,
        journal_lineage_hash=digest,
        journal_seal_hash=digest,
        equivalent=True,
        journal_verified=True,
    )


def _rollback(*, passed: bool = True) -> RollbackRehearsalEvidence:
    digest = hashlib.sha256(b"rollback").hexdigest()
    return RollbackRehearsalEvidence(
        service="sprint",
        target_id="flag.AUTORESEARCH_SPRINT_MIGRATION_MODE.legacy",
        report_hash=digest,
        passed=passed,
        lifecycle_result_equal=passed,
        projection_equal=passed,
        journal_unchanged=passed,
        compatibility_files_preserved=passed,
    )


def _reproduction(*, passed: bool = True) -> IndependentReproductionEvidence:
    source = hashlib.sha256(b"source").hexdigest()
    observed = source if passed else hashlib.sha256(b"drift").hexdigest()
    return IndependentReproductionEvidence(
        reproduction_id="reproduction-1",
        source_artifact_id="smoke-summary.json",
        source_digest=source,
        reproduced_digest=observed,
        isolated_process=True,
        clean_workdir=True,
        network_used=False,
        passed=passed,
    )


def _report(
    tmp_path: Path,
    *,
    formal_runs: list[FormalVerticalRunEvidence] | None = None,
    rollback: RollbackRehearsalEvidence | None = None,
    reproduction: IndependentReproductionEvidence | None = None,
    approval: HumanApprovalBoundary | None = None,
    drift: bool = False,
) -> VNextReleaseReport:
    return VNextReleaseReport.create(
        baseline_characterization_hash=BASELINE_LANGGRAPH_CHARACTERIZATION_HASH,
        dependency_audit=_dependency_audit(tmp_path, drift=drift),
        upgraded_characterization=_characterization(),
        formal_vertical_runs=formal_runs or [_vertical(1), _vertical(2)],
        rollback_rehearsal=rollback or _rollback(),
        independent_reproduction=reproduction or _reproduction(),
        compatibility_paths=default_compatibility_paths(),
        capabilities=default_capability_matrix(),
        approval_boundary=approval or HumanApprovalBoundary(),
    )


def test_dependency_lock_audit_requires_exact_lock_and_environment(
    tmp_path: Path,
) -> None:
    audit = _dependency_audit(tmp_path)

    assert audit.exact_match is True
    assert audit.locked_versions == EXPECTED_RUNTIME_DEPENDENCIES
    assert audit.installed_versions == EXPECTED_RUNTIME_DEPENDENCIES
    assert audit.calculated_hash() == audit.audit_hash

    payload = audit.model_dump(mode="json")
    payload["installed_versions"]["langgraph"] = "9.9.9"
    with pytest.raises(ValidationError, match="exact_match"):
        type(audit).model_validate(payload)


def test_dependency_drift_fails_release_without_hiding_the_observation(
    tmp_path: Path,
) -> None:
    report = _report(tmp_path, drift=True)

    assert report.release_boundary_passed is False
    assert report.release_failures == ["dependency-lock-drift"]


def test_release_report_passes_only_with_two_verticals_and_closed_authority(
    tmp_path: Path,
) -> None:
    report = _report(tmp_path)
    path = write_vnext_release_report(tmp_path / "release.json", report)

    assert report.release_boundary_passed is True
    assert report.release_failures == []
    assert report.calculated_hash() == report.report_hash
    assert load_vnext_release_report(path) == report
    path_statuses = {
        item.surface_id: item.writer_disposition
        for item in report.compatibility_paths
    }
    assert path_statuses["audit.jsonl"] is WriterDisposition.RETIRED
    assert path_statuses["sprint.legacy-state"] is WriterDisposition.RETAINED
    assert report.approval_boundary.public_release_enabled is False
    assert report.approval_boundary.external_submission_enabled is False


def test_release_report_is_content_addressed_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    payload = _report(tmp_path).model_dump(mode="json")
    payload["release_boundary_passed"] = False

    with pytest.raises(ValidationError, match="release verdict"):
        VNextReleaseReport.model_validate(payload)

    payload = _report(tmp_path).model_dump(mode="json")
    payload["report_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="report_hash"):
        VNextReleaseReport.model_validate(payload)


def test_release_gate_fails_closed_on_insufficient_or_reused_verticals(
    tmp_path: Path,
) -> None:
    insufficient = _report(tmp_path, formal_runs=[_vertical(1)])
    reused = _report(
        tmp_path,
        formal_runs=[
            _vertical(1, source_id="same-sprint"),
            _vertical(2, source_id="same-sprint"),
        ],
    )

    assert "formal-vertical-count" in insufficient.release_failures
    assert "formal-vertical-source-reuse" in reused.release_failures
    with pytest.raises(ValueError, match="cannot publish"):
        write_vnext_release_report(tmp_path / "blocked.json", insufficient)


def test_release_gate_fails_closed_on_rollback_or_reproduction_failure(
    tmp_path: Path,
) -> None:
    rollback_failure = _report(tmp_path, rollback=_rollback(passed=False))
    reproduction_failure = _report(
        tmp_path,
        reproduction=_reproduction(passed=False),
    )

    assert rollback_failure.release_failures == ["rollback-rehearsal-failed"]
    assert reproduction_failure.release_failures == [
        "independent-reproduction-failed"
    ]


def test_release_gate_cannot_open_human_approval_actions(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        approval=HumanApprovalBoundary(public_release_enabled=True),
    )

    assert report.release_boundary_passed is False
    assert report.release_failures == ["human-approval-boundary-open"]


def test_independent_reproduction_uses_a_clean_canonical_directory(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.json"
    source.write_text('{"z": 1, "a": [2, 3]}\n', encoding="utf-8")
    destination = tmp_path / "clean"

    evidence = reproduce_json_artifact(
        source,
        destination,
        reproduction_id="reproduction-clean",
        isolated_process=True,
    )

    assert evidence.passed is True
    assert evidence.source_digest == evidence.reproduced_digest
    assert (destination / "reproduced.json").read_text(encoding="utf-8") == (
        '{"a":[2,3],"z":1}\n'
    )
    with pytest.raises(ValueError, match="absent or empty"):
        reproduce_json_artifact(
            source,
            destination,
            reproduction_id="reproduction-dirty",
            isolated_process=True,
        )
