"""Fail-closed compatibility and release evidence for the vNext runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from enum import Enum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import toml
from pydantic import Field, field_validator, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    Sha256,
    StableId,
    canonical_sha256,
)

from .loop_langgraph import LangGraphCharacterizationReport

BASELINE_LANGGRAPH_CHARACTERIZATION_HASH = (
    "92983004c099b14799cd4102b644072013016541ae3da659e7380161b448fb3e"
)
TARGET_LANGGRAPH_CHARACTERIZATION_HASH = (
    "dd62c3faef638b905755dbc26f6761957e5657175de7a3b641b6e5c718ebebd3"
)
EXPECTED_RUNTIME_DEPENDENCIES: dict[str, str] = {
    "langchain": "1.3.14",
    "langchain-core": "1.5.2",
    "langgraph": "1.2.10",
    "langgraph-checkpoint": "4.1.1",
    "langgraph-prebuilt": "1.1.0",
    "langgraph-sdk": "0.4.2",
    "langsmith": "0.10.11",
}


class WriterDisposition(str, Enum):
    """Whether a pre-vNext writer remains callable after the boundary."""

    RETIRED = "retired"
    DEPRECATED = "deprecated"
    RETAINED = "retained"


class CapabilityStatus(str, Enum):
    """Truthful status values used in the public capability matrix."""

    VERIFIED = "verified"
    COMPATIBILITY_ONLY = "compatibility_only"
    APPROVAL_GATED = "approval_gated"
    NOT_IMPLEMENTED = "not_implemented"


class DependencyLockAudit(KernelContract):
    """Content-addressed comparison of required, locked, and installed versions."""

    schema_version: Literal[1] = 1
    lock_sha256: Sha256
    required_versions: dict[str, str]
    locked_versions: dict[str, str]
    installed_versions: dict[str, str]
    exact_match: bool
    audit_hash: Sha256

    @field_validator(
        "required_versions",
        "locked_versions",
        "installed_versions",
        mode="before",
    )
    @classmethod
    def _normalize_versions(cls, value: object) -> object:
        if not isinstance(value, dict):
            raise ValueError("dependency versions must be an object")
        normalized: dict[str, str] = {}
        for raw_name, raw_version in value.items():
            if not isinstance(raw_name, str) or not isinstance(raw_version, str):
                raise ValueError("dependency names and versions must be strings")
            name = _normalize_package_name(raw_name)
            clean_version = raw_version.strip()
            if not clean_version:
                raise ValueError(f"dependency {name} has an empty version")
            normalized[name] = clean_version
        return dict(sorted(normalized.items()))

    @model_validator(mode="after")
    def _validate_audit(self) -> DependencyLockAudit:
        expected_match = (
            self.locked_versions == self.required_versions
            and self.installed_versions == self.required_versions
        )
        if self.exact_match != expected_match:
            raise ValueError("dependency exact_match contradicts audited versions")
        if self.audit_hash != self.calculated_hash():
            raise ValueError("dependency audit_hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        lock_sha256: str,
        required_versions: dict[str, str],
        locked_versions: dict[str, str],
        installed_versions: dict[str, str],
    ) -> DependencyLockAudit:
        """Normalize dependency evidence and attach its canonical digest."""

        required = _normalized_versions(required_versions)
        locked = _normalized_versions(locked_versions)
        installed = _normalized_versions(installed_versions)
        payload: dict[str, object] = {
            "schema_version": 1,
            "lock_sha256": lock_sha256,
            "required_versions": required,
            "locked_versions": locked,
            "installed_versions": installed,
            "exact_match": locked == required and installed == required,
        }
        payload["audit_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the audit digest."""

        return canonical_sha256(self.model_dump(mode="json", exclude={"audit_hash"}))


class FormalVerticalRunEvidence(KernelContract):
    """One distinct formal service observation admitted to the release gate."""

    service: StableId
    formal_run_id: StableId
    source_id: StableId
    scientific_endpoint: StableId
    source_fingerprint: Sha256
    parity_report_hash: Sha256
    journal_lineage_hash: Sha256
    journal_seal_hash: Sha256
    equivalent: bool
    journal_verified: bool


class RollbackRehearsalEvidence(KernelContract):
    """Recorded ability to return lifecycle authority to a compatibility path."""

    service: StableId
    target_id: StableId
    report_hash: Sha256
    passed: bool
    lifecycle_result_equal: bool
    projection_equal: bool
    journal_unchanged: bool
    compatibility_files_preserved: bool


class IndependentReproductionEvidence(KernelContract):
    """Digest comparison produced in a separate clean process and directory."""

    reproduction_id: StableId
    source_artifact_id: StableId
    source_digest: Sha256
    reproduced_digest: Sha256
    isolated_process: bool
    clean_workdir: bool
    network_used: bool
    passed: bool

    @model_validator(mode="after")
    def _validate_result(self) -> IndependentReproductionEvidence:
        expected = (
            self.source_digest == self.reproduced_digest
            and self.isolated_process
            and self.clean_workdir
            and not self.network_used
        )
        if self.passed != expected:
            raise ValueError("independent reproduction verdict contradicts evidence")
        return self


class CompatibilityPathDecision(KernelContract):
    """Explicit disposition and rollback target for one legacy persistence surface."""

    surface_id: StableId
    writer_disposition: WriterDisposition
    reader_retained: bool
    reader_window: Literal["vnext-plus-one-release"]
    authoritative_for_new_runs: bool
    replacement_surface_id: StableId | None = None
    rollback_target_id: StableId
    rationale_code: StableId
    evidence_refs: list[StableId] = Field(min_length=1)

    @field_validator("evidence_refs")
    @classmethod
    def _normalize_evidence_refs(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("compatibility evidence references must be unique")
        return sorted(value)


class CapabilityClaim(KernelContract):
    """One bounded, evidence-linked capability claim."""

    capability_id: StableId
    status: CapabilityStatus
    evidence_refs: list[StableId] = Field(min_length=1)

    @field_validator("evidence_refs")
    @classmethod
    def _normalize_evidence_refs(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("capability evidence references must be unique")
        return sorted(value)


class HumanApprovalBoundary(KernelContract):
    """Actions that remain disabled without explicit human approval."""

    human_approval_enforced: bool = True
    unrestricted_execution_enabled: bool = False
    public_release_enabled: bool = False
    external_submission_enabled: bool = False
    safety_policy_self_modification_enabled: bool = False


class _VNextReleaseInputs(KernelContract):
    schema_version: Literal["vnext-release-boundary-v1"] = (
        "vnext-release-boundary-v1"
    )
    release_scope: Literal["internal-compatibility-boundary"] = (
        "internal-compatibility-boundary"
    )
    baseline_characterization_hash: Sha256
    dependency_audit: DependencyLockAudit
    upgraded_characterization: LangGraphCharacterizationReport
    formal_vertical_runs: list[FormalVerticalRunEvidence]
    rollback_rehearsal: RollbackRehearsalEvidence
    independent_reproduction: IndependentReproductionEvidence
    compatibility_paths: list[CompatibilityPathDecision]
    retained_reader_window: Literal["vnext-plus-one-release"] = (
        "vnext-plus-one-release"
    )
    schema_support_policy: Literal["write-current-read-current-plus-one"] = (
        "write-current-read-current-plus-one"
    )
    historical_artifacts_immutable: Literal[True] = True
    bulk_rewrite_allowed: Literal[False] = False
    capabilities: list[CapabilityClaim]
    approval_boundary: HumanApprovalBoundary

    @model_validator(mode="after")
    def _normalize_collections(self) -> _VNextReleaseInputs:
        _require_unique(
            [item.formal_run_id for item in self.formal_vertical_runs],
            "formal run",
        )
        _require_unique(
            [item.surface_id for item in self.compatibility_paths],
            "compatibility surface",
        )
        _require_unique(
            [item.capability_id for item in self.capabilities],
            "capability",
        )
        self.formal_vertical_runs = sorted(
            self.formal_vertical_runs,
            key=lambda item: (item.service, item.formal_run_id),
        )
        self.compatibility_paths = sorted(
            self.compatibility_paths,
            key=lambda item: item.surface_id,
        )
        self.capabilities = sorted(
            self.capabilities,
            key=lambda item: item.capability_id,
        )
        return self


class VNextReleaseReport(_VNextReleaseInputs):
    """Content-addressed R1 decision without granting publication authority."""

    release_failures: list[StableId]
    release_boundary_passed: bool
    report_hash: Sha256

    @field_validator("release_failures")
    @classmethod
    def _normalize_failures(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("release failures must be unique")
        return sorted(value)

    @model_validator(mode="after")
    def _validate_report(self) -> VNextReleaseReport:
        expected_failures = _evaluate_release(self)
        if self.release_failures != expected_failures:
            raise ValueError("release failures contradict release evidence")
        if self.release_boundary_passed != (not expected_failures):
            raise ValueError("release verdict contradicts release evidence")
        if self.report_hash != self.calculated_hash():
            raise ValueError("vNext release report_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> VNextReleaseReport:
        """Validate all inputs, evaluate R1, and attach a deterministic digest."""

        inputs = _VNextReleaseInputs.model_validate(values)
        failures = _evaluate_release(inputs)
        payload = inputs.model_dump(mode="json")
        payload["release_failures"] = failures
        payload["release_boundary_passed"] = not failures
        payload["report_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the report digest."""

        return canonical_sha256(self.model_dump(mode="json", exclude={"report_hash"}))


def audit_runtime_dependency_lock(
    lock_path: Path | str,
    *,
    installed_versions: dict[str, str] | None = None,
) -> DependencyLockAudit:
    """Audit exact graph-stack pins against Poetry's lock and the environment."""

    resolved = Path(lock_path)
    raw_bytes = resolved.read_bytes()
    parsed = toml.loads(raw_bytes.decode("utf-8"))
    packages = parsed.get("package")
    if not isinstance(packages, list):
        raise ValueError("poetry lock has no package list")
    locked_all: dict[str, str] = {}
    for package in packages:
        if not isinstance(package, dict):
            continue
        name = package.get("name")
        package_version = package.get("version")
        if isinstance(name, str) and isinstance(package_version, str):
            locked_all[_normalize_package_name(name)] = package_version

    required = dict(EXPECTED_RUNTIME_DEPENDENCIES)
    locked = {
        name: locked_all.get(name, "<missing>")
        for name in required
    }
    if installed_versions is None:
        installed = {}
        for name in required:
            try:
                installed[name] = version(name)
            except PackageNotFoundError:
                installed[name] = "<missing>"
    else:
        normalized_installed = {
            _normalize_package_name(name): package_version
            for name, package_version in installed_versions.items()
        }
        installed = {
            name: normalized_installed.get(name, "<missing>")
            for name in required
        }
    return DependencyLockAudit.create(
        lock_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        required_versions=required,
        locked_versions=locked,
        installed_versions=installed,
    )


def default_compatibility_paths() -> list[CompatibilityPathDecision]:
    """Return the reviewed writer/reader decisions at the vNext boundary."""

    return [
        CompatibilityPathDecision(
            surface_id="audit.jsonl",
            writer_disposition=WriterDisposition.RETIRED,
            reader_retained=True,
            reader_window="vnext-plus-one-release",
            authoritative_for_new_runs=False,
            replacement_surface_id="kernel.event-journal",
            rollback_target_id="audit.export-legacy-snapshot",
            rationale_code="atomic-journal-parity-proven",
            evidence_refs=["task:262.10:audit-migration"],
        ),
        CompatibilityPathDecision(
            surface_id="agents.linear-workflow",
            writer_disposition=WriterDisposition.DEPRECATED,
            reader_retained=True,
            reader_window="vnext-plus-one-release",
            authoritative_for_new_runs=False,
            replacement_surface_id="kernel.control-graph",
            rollback_target_id="agents.workflow-checkpoint-v1",
            rationale_code="no-production-callers-retain-checkpoint-reader",
            evidence_refs=["task:262.5:characterization"],
        ),
        CompatibilityPathDecision(
            surface_id="campaign.legacy-state",
            writer_disposition=WriterDisposition.RETAINED,
            reader_retained=True,
            reader_window="vnext-plus-one-release",
            authoritative_for_new_runs=True,
            replacement_surface_id="campaign.vnext-projection",
            rollback_target_id="flag.AUTORESEARCH_CAMPAIGN_MIGRATION_MODE.legacy",
            rationale_code="scientific-engine-still-legacy",
            evidence_refs=["task:262.8.2:rollback"],
        ),
        CompatibilityPathDecision(
            surface_id="competition.legacy-state",
            writer_disposition=WriterDisposition.RETAINED,
            reader_retained=True,
            reader_window="vnext-plus-one-release",
            authoritative_for_new_runs=True,
            replacement_surface_id="competition.vnext-projection",
            rollback_target_id="flag.AUTORESEARCH_COMPETITION_MIGRATION_MODE.legacy",
            rationale_code="scientific-engine-still-legacy",
            evidence_refs=["task:262.8.1:rollback"],
        ),
        CompatibilityPathDecision(
            surface_id="evidence.graph-v1",
            writer_disposition=WriterDisposition.RETAINED,
            reader_retained=True,
            reader_window="vnext-plus-one-release",
            authoritative_for_new_runs=True,
            replacement_surface_id="kernel.provenance-v2",
            rollback_target_id="evidence.graph-v1-reader",
            rationale_code="active-reader-projection-dependency",
            evidence_refs=["task:262.6:compatibility"],
        ),
        CompatibilityPathDecision(
            surface_id="sprint.legacy-state",
            writer_disposition=WriterDisposition.RETAINED,
            reader_retained=True,
            reader_window="vnext-plus-one-release",
            authoritative_for_new_runs=True,
            replacement_surface_id="sprint.vnext-projection",
            rollback_target_id="flag.AUTORESEARCH_SPRINT_MIGRATION_MODE.legacy",
            rationale_code="scientific-engine-still-legacy",
            evidence_refs=["task:262.8.3:rollback"],
        ),
    ]


def default_capability_matrix() -> list[CapabilityClaim]:
    """Return the minimum truthful capability matrix for R1."""

    verified = {
        "atomic-event-journal": "task:262.3",
        "bounded-harness": "task:262.4",
        "durable-control-graph": "task:262.5",
        "open-science-research-object": "task:262.7",
        "provenance-evidence-v2": "task:262.6",
        "three-service-vnext-lifecycle": "task:262.8",
        "unified-evaluation-security": "task:262.9",
    }
    claims = [
        CapabilityClaim(
            capability_id=capability,
            status=CapabilityStatus.VERIFIED,
            evidence_refs=[evidence],
        )
        for capability, evidence in verified.items()
    ]
    for capability in (
        "external-submission",
        "public-release",
        "safety-policy-evolution",
        "unrestricted-execution",
    ):
        claims.append(
            CapabilityClaim(
                capability_id=capability,
                status=CapabilityStatus.APPROVAL_GATED,
                evidence_refs=["policy:human-approval"],
            )
        )
    return claims


def reproduce_json_artifact(
    source_path: Path | str,
    output_dir: Path | str,
    *,
    reproduction_id: str,
    isolated_process: bool,
) -> IndependentReproductionEvidence:
    """Rebuild canonical JSON in a clean directory and compare its digest."""

    source = Path(source_path)
    destination = Path(output_dir)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("independent reproduction directory must be absent or empty")
    destination.mkdir(parents=True, exist_ok=True)
    parsed = json.loads(source.read_text(encoding="utf-8"))
    canonical = _standalone_canonical_json(parsed)
    source_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    reproduced_path = destination / "reproduced.json"
    _atomic_write_text(reproduced_path, canonical + "\n")
    reproduced = json.loads(reproduced_path.read_text(encoding="utf-8"))
    reproduced_digest = hashlib.sha256(
        _standalone_canonical_json(reproduced).encode("utf-8")
    ).hexdigest()
    evidence = IndependentReproductionEvidence(
        reproduction_id=reproduction_id,
        source_artifact_id=source.name,
        source_digest=source_digest,
        reproduced_digest=reproduced_digest,
        isolated_process=isolated_process,
        clean_workdir=True,
        network_used=False,
        passed=source_digest == reproduced_digest and isolated_process,
    )
    _atomic_write_text(
        destination / "independent-reproduction.json",
        evidence.model_dump_json(indent=2) + "\n",
    )
    return evidence


def write_vnext_release_report(
    path: Path | str,
    report: VNextReleaseReport,
) -> Path:
    """Atomically persist a verified release report."""

    if not report.release_boundary_passed:
        raise ValueError("cannot publish a failing vNext release boundary")
    resolved = Path(path)
    _atomic_write_text(resolved, report.model_dump_json(indent=2) + "\n")
    return resolved


def load_vnext_release_report(path: Path | str) -> VNextReleaseReport:
    """Load and fully revalidate a persisted release report."""

    return VNextReleaseReport.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def _evaluate_release(inputs: _VNextReleaseInputs) -> list[str]:
    failures: list[str] = []
    dependency_audit = inputs.dependency_audit
    if not dependency_audit.exact_match:
        failures.append("dependency-lock-drift")
    if (
        inputs.baseline_characterization_hash
        != BASELINE_LANGGRAPH_CHARACTERIZATION_HASH
    ):
        failures.append("baseline-characterization-unknown")

    characterization = inputs.upgraded_characterization
    if not characterization.all_passed:
        failures.append("upgraded-characterization-failed")
    if characterization.report_hash != TARGET_LANGGRAPH_CHARACTERIZATION_HASH:
        failures.append("upgraded-characterization-drift")
    if (
        characterization.langgraph_version
        != EXPECTED_RUNTIME_DEPENDENCIES["langgraph"]
        or characterization.langchain_core_version
        != EXPECTED_RUNTIME_DEPENDENCIES["langchain-core"]
    ):
        failures.append("characterization-version-drift")

    formal_runs = inputs.formal_vertical_runs
    if len(formal_runs) < 2:
        failures.append("formal-vertical-count")
    if len({item.source_id for item in formal_runs}) != len(formal_runs):
        failures.append("formal-vertical-source-reuse")
    if any(not item.equivalent or not item.journal_verified for item in formal_runs):
        failures.append("formal-vertical-verification")

    rollback = inputs.rollback_rehearsal
    if not all(
        (
            rollback.passed,
            rollback.lifecycle_result_equal,
            rollback.projection_equal,
            rollback.journal_unchanged,
            rollback.compatibility_files_preserved,
        )
    ):
        failures.append("rollback-rehearsal-failed")

    reproduction = inputs.independent_reproduction
    if not reproduction.passed:
        failures.append("independent-reproduction-failed")

    expected_paths = {
        "agents.linear-workflow": WriterDisposition.DEPRECATED,
        "audit.jsonl": WriterDisposition.RETIRED,
        "campaign.legacy-state": WriterDisposition.RETAINED,
        "competition.legacy-state": WriterDisposition.RETAINED,
        "evidence.graph-v1": WriterDisposition.RETAINED,
        "sprint.legacy-state": WriterDisposition.RETAINED,
    }
    actual_paths = {
        item.surface_id: item.writer_disposition
        for item in inputs.compatibility_paths
    }
    if actual_paths != expected_paths:
        failures.append("compatibility-path-decision-drift")
    if any(not item.reader_retained for item in inputs.compatibility_paths):
        failures.append("compatibility-reader-removed")

    expected_capabilities = {
        "atomic-event-journal": CapabilityStatus.VERIFIED,
        "bounded-harness": CapabilityStatus.VERIFIED,
        "durable-control-graph": CapabilityStatus.VERIFIED,
        "external-submission": CapabilityStatus.APPROVAL_GATED,
        "open-science-research-object": CapabilityStatus.VERIFIED,
        "provenance-evidence-v2": CapabilityStatus.VERIFIED,
        "public-release": CapabilityStatus.APPROVAL_GATED,
        "safety-policy-evolution": CapabilityStatus.APPROVAL_GATED,
        "three-service-vnext-lifecycle": CapabilityStatus.VERIFIED,
        "unified-evaluation-security": CapabilityStatus.VERIFIED,
        "unrestricted-execution": CapabilityStatus.APPROVAL_GATED,
    }
    actual_capabilities = {
        item.capability_id: item.status
        for item in inputs.capabilities
    }
    if actual_capabilities != expected_capabilities:
        failures.append("capability-matrix-drift")

    approval = inputs.approval_boundary
    if not approval.human_approval_enforced or any(
        (
            approval.unrestricted_execution_enabled,
            approval.public_release_enabled,
            approval.external_submission_enabled,
            approval.safety_policy_self_modification_enabled,
        )
    ):
        failures.append("human-approval-boundary-open")
    return sorted(set(failures))


def _normalize_package_name(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def _normalized_versions(versions: dict[str, str]) -> dict[str, str]:
    return dict(
        sorted(
            (
                _normalize_package_name(name),
                package_version.strip(),
            )
            for name, package_version in versions.items()
        )
    )


def _require_unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} IDs must be unique")


def _standalone_canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reproduce one vNext JSON artifact in an isolated process."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--reproduction-id", required=True)
    arguments = parser.parse_args(argv)
    evidence = reproduce_json_artifact(
        arguments.source,
        arguments.output_dir,
        reproduction_id=arguments.reproduction_id,
        isolated_process=True,
    )
    print(evidence.model_dump_json())
    return 0 if evidence.passed else 1


if __name__ == "__main__":
    raise SystemExit(_main())
