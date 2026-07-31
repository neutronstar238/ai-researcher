"""Interoperable Open Science overlay for the immutable Task 260 paper object.

The overlay is additive.  It copies every frozen Task 260 byte into the
internal view, exposes only sanitized review evidence, and maps the historical
package plus its later audit, reanalysis, and rewrite into RO-Crate/PROV.  It
never upgrades metadata interoperability into scientific confirmation or
publication authority.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from autoresearch.kernel import (
    Activity,
    ActivityKind,
    Agent,
    Association,
    Claim,
    Counterevidence,
    Decision,
    Derivation,
    Entity,
    EntityKind,
    Evidence,
    EvidenceDirection,
    Generation,
    Plan,
    ProvenanceAgentKind,
    ProvenanceBundle,
    SourceSnapshot,
    Usage,
    Validation,
    canonical_sha256,
)
from autoresearch.reports.open_science import (
    ArtifactAccess,
    ArtifactTransform,
    Contributor,
    JsonAssertion,
    OpenScienceExport,
    ResearchObjectArtifact,
    ResearchObjectMetadata,
    ResearchObjectView,
    export_open_science_research_object,
    run_clean_directory_reproduction,
    validate_open_science_view,
)
from autoresearch.schemas import ValidationStatus, file_hash

from .systems_paper_currency_audit import (
    ParentSystemsPaperEvidence,
    SourceResponse,
    fetch_source_response,
    load_systems_paper_currency_audit,
)
from .systems_paper_current_field_rewrite import (
    load_current_field_manuscript_rewrite,
)
from .systems_paper_task_unit_reanalysis import load_task_unit_reanalysis

TASK_ID = "263.7.3"
PACKAGE_ID = "task26373-open-science-overlay-v1"
REPORT_FILENAME = "open-science-overlay.json"
MARKDOWN_FILENAME = "open-science-overlay.md"
SOURCE_REGISTRY_FILENAME = "standards/source-registry.json"
QUERY_FILENAME = "provenance/provenance-query-report.json"
RECONSTRUCTION_FILENAME = "reconstruction/exact-reconstruction.json"
PROFILE_VALIDATION_FILENAME = "validation/profile-validation.json"
SCHEMAS_FILENAME = "open-science-overlay-schemas.json"
MANIFEST_FILENAME = "open-science-overlay-manifest.json"

BASE_COMMIT = "a34c04413e2a9d198ebd4feb3e457d1dcca586ef"
EXPECTED_AUDIT_REPORT_HASH = "92a478ee85f2324353f5310425408fb60d5c58fc2ee222b16069cbcdc1bfa190"
EXPECTED_AUDIT_MANIFEST_HASH = "8e2dd7b5cbee5aa4274b125bc9f7c2cdab3ef33017a38f37e782ea35d089b9c9"
EXPECTED_REANALYSIS_REPORT_HASH = "476b920607ad981a1f0d7b0a33ff4d74e813a70159959c70386e9e15d6c37d99"
EXPECTED_REANALYSIS_MANIFEST_HASH = (
    "f6d8371c9b1c54cb5ffa885c407210b74ede4b0c74d45466c6a2e074d089a6ab"
)
EXPECTED_REWRITE_REPORT_HASH = "0182c044157b293e69227118a40431fd8fa2d36be23dbf4556569fb135708a31"
EXPECTED_REWRITE_MANIFEST_HASH = "83baa8a732560facc6d6401fbc3ef0d87c3958ef45d56de447d72b32c8a7b6df"

RO_CRATE_PROFILE = "https://w3id.org/ro/crate/1.3"
WORKFLOW_RO_CRATE_PROFILE = "https://w3id.org/workflowhub/workflow-ro-crate/1.0"
PROCESS_RUN_PROFILE = "https://w3id.org/ro/wfrun/process/0.5"
WORKFLOW_RUN_PROFILE = "https://w3id.org/ro/wfrun/workflow/0.5"
PROVENANCE_RUN_PROFILE = "https://w3id.org/ro/wfrun/provenance/0.5"
PROV_O_PROFILE = "https://www.w3.org/TR/prov-o/"

EXTERNAL_PROFILE_IDS = (
    "workflow-ro-crate-1.0",
    "process-run-crate-0.5",
    "workflow-run-crate-0.5",
    "provenance-run-crate-0.5",
)

_JSON_ADAPTER = TypeAdapter(dict[str, Any])
_PRIVATE_PATH_PATTERNS = (
    re.compile(r"(?i)(?:^|[\s\"'=])(?:[a-z]:[\\/][^\s\"']+)"),
    re.compile(r"(?i)(?:^|[\s\"'=])(?:(?:/home/|/users/|/root/)[^\s\"']+)"),
)


class SystemsPaperOpenScienceIntegrityError(ValueError):
    """Raised when a dependency, profile, reconstruction, or hash gate fails."""


class StrictModel(BaseModel):
    """Strict contract base for the Task 263.7.3 package."""

    model_config = ConfigDict(extra="forbid")


def _addressed(payload: Mapping[str, Any], hash_field: str) -> dict[str, Any]:
    normalized = _JSON_ADAPTER.dump_python(dict(payload), mode="json")
    result = dict(payload)
    result[hash_field] = canonical_sha256(normalized)
    return result


def _file_sha256(path: Path) -> str:
    return file_hash(path)


def _pretty_json(value: Any) -> str:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n"
    )


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_pretty_json(value), encoding="utf-8", newline="\n")


def _read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _validate_addressed(
    payload: Mapping[str, Any],
    hash_field: str,
    *,
    label: str,
) -> None:
    expected = payload.get(hash_field)
    body = dict(payload)
    body.pop(hash_field, None)
    normalized = _JSON_ADAPTER.dump_python(body, mode="json")
    if expected != canonical_sha256(normalized):
        raise SystemsPaperOpenScienceIntegrityError(f"{label} hash mismatch")


def _require_utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone aware")
    return value.astimezone(timezone.utc)


def _normalized_source_text(body: bytes) -> str:
    text = html.unescape(body.decode("utf-8", errors="replace"))
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


@dataclass(frozen=True)
class StandardSourceDefinition:
    source_id: str
    title: str
    url: str
    standard: str
    version: str
    required_markers: tuple[str, ...]


StandardSourceFetcher = Callable[[str], SourceResponse]


def standard_source_definitions() -> tuple[StandardSourceDefinition, ...]:
    """Return the frozen authoritative interoperability source set."""

    return (
        StandardSourceDefinition(
            source_id="ro-crate-specification-1-3",
            title="RO-Crate Metadata Specification 1.3",
            url="https://www.researchobject.org/ro-crate/specification/1.3/index.html",
            standard="RO-Crate",
            version="1.3",
            required_markers=("ro-crate 1.3", "recommendation"),
        ),
        StandardSourceDefinition(
            source_id="ro-crate-profiles-1-3",
            title="RO-Crate 1.3 Profiles",
            url="https://www.researchobject.org/ro-crate/specification/1.3/profiles.html",
            standard="RO-Crate Profiles",
            version="1.3",
            required_markers=("ro-crate profiles", "conformsto"),
        ),
        StandardSourceDefinition(
            source_id="workflow-run-crate-0-5",
            title="Workflow Run Crate Profile 0.5",
            url=WORKFLOW_RUN_PROFILE,
            standard="Workflow Run Crate",
            version="0.5",
            required_markers=("workflow run crate", "version: 0.5"),
        ),
        StandardSourceDefinition(
            source_id="provenance-run-crate-0-5",
            title="Provenance Run Crate Profile 0.5",
            url=PROVENANCE_RUN_PROFILE,
            standard="Provenance Run Crate",
            version="0.5",
            required_markers=("provenance run crate", "version: 0.5"),
        ),
        StandardSourceDefinition(
            source_id="prov-o-w3c-recommendation",
            title="PROV-O: The PROV Ontology",
            url=PROV_O_PROFILE,
            standard="W3C PROV-O",
            version="Recommendation 2013",
            required_markers=("prov-o: the prov ontology", "w3c recommendation"),
        ),
        StandardSourceDefinition(
            source_id="rocrate-validator-0-11-3-docs",
            title="rocrate-validator documentation",
            url="https://rocrate-validator.readthedocs.io/en/stable/",
            standard="rocrate-validator",
            version="0.11.3",
            required_markers=("rocrate-validator", "0.11.3"),
        ),
    )


class StandardSourceSnapshot(StrictModel):
    schema_version: Literal["task26373-standard-source-snapshot-v1"] = (
        "task26373-standard-source-snapshot-v1"
    )
    source_id: str
    title: str
    requested_url: str
    final_url: str
    standard: str
    version: str
    retrieved_at: datetime
    status_code: int = Field(ge=200, le=299)
    media_type: str
    byte_count: int = Field(gt=0, le=8_000_000)
    body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    required_markers: list[str]
    matched_markers: list[str]
    raw_relative_path: str
    rights_status: Literal["reference-only-no-redistribution-license-inferred"] = (
        "reference-only-no-redistribution-license-inferred"
    )
    review_exposes_raw_body: Literal[False] = False
    snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("retrieved_at")
    @classmethod
    def _utc_retrieved(cls, value: datetime) -> datetime:
        return _require_utc(value, "retrieved_at")

    @model_validator(mode="after")
    def _validate_snapshot(self) -> StandardSourceSnapshot:
        if sorted(self.required_markers) != sorted(self.matched_markers):
            raise ValueError(f"standard source markers did not all match: {self.source_id}")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"snapshot_hash"}))
        if self.snapshot_hash != expected:
            raise SystemsPaperOpenScienceIntegrityError(
                f"standard source snapshot hash mismatch: {self.source_id}"
            )
        return self

    @classmethod
    def create(
        cls,
        definition: StandardSourceDefinition,
        response: SourceResponse,
        retrieved_at: datetime,
    ) -> StandardSourceSnapshot:
        normalized = _normalized_source_text(response.body)
        matched = [
            marker for marker in definition.required_markers if marker.casefold() in normalized
        ]
        if len(matched) != len(definition.required_markers):
            missing = sorted(set(definition.required_markers) - set(matched))
            raise SystemsPaperOpenScienceIntegrityError(
                f"standard source markers missing for {definition.source_id}: {missing}"
            )
        payload = {
            "schema_version": "task26373-standard-source-snapshot-v1",
            "source_id": definition.source_id,
            "title": definition.title,
            "requested_url": definition.url,
            "final_url": response.final_url,
            "standard": definition.standard,
            "version": definition.version,
            "retrieved_at": _require_utc(retrieved_at, "retrieved_at"),
            "status_code": response.status_code,
            "media_type": response.media_type,
            "byte_count": len(response.body),
            "body_sha256": hashlib.sha256(response.body).hexdigest(),
            "required_markers": sorted(definition.required_markers),
            "matched_markers": sorted(matched),
            "raw_relative_path": f"standards/raw/{definition.source_id}.html",
            "rights_status": "reference-only-no-redistribution-license-inferred",
            "review_exposes_raw_body": False,
        }
        return cls.model_validate(_addressed(payload, "snapshot_hash"))


class StandardSourceRegistry(StrictModel):
    schema_version: Literal["task26373-standard-source-registry-v1"] = (
        "task26373-standard-source-registry-v1"
    )
    retrieved_at: datetime
    sources: list[StandardSourceSnapshot]
    source_count: Literal[6] = 6
    authoritative_only: Literal[True] = True
    raw_snapshots_internal_only: Literal[True] = True
    no_redistribution_license_inferred: Literal[True] = True
    registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_registry(self) -> StandardSourceRegistry:
        if len(self.sources) != self.source_count:
            raise ValueError("standard source registry must contain exactly six sources")
        ids = [item.source_id for item in self.sources]
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise ValueError("standard source registry must be uniquely ID-sorted")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"registry_hash"}))
        if self.registry_hash != expected:
            raise SystemsPaperOpenScienceIntegrityError("standard source registry hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        retrieved_at: datetime,
        sources: Sequence[StandardSourceSnapshot],
    ) -> StandardSourceRegistry:
        payload = {
            "schema_version": "task26373-standard-source-registry-v1",
            "retrieved_at": _require_utc(retrieved_at, "retrieved_at"),
            "sources": sorted(sources, key=lambda item: item.source_id),
            "source_count": 6,
            "authoritative_only": True,
            "raw_snapshots_internal_only": True,
            "no_redistribution_license_inferred": True,
        }
        return cls.model_validate(_addressed(payload, "registry_hash"))


class FileRecord(StrictModel):
    relative_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(ge=0)


class ClaimTraceRecord(StrictModel):
    claim_id: str
    evidence_ids: list[str]
    counterevidence_ids: list[str]
    limiting_evidence_ids: list[str]
    source_entity_ids: list[str]
    input_entity_ids: list[str]
    activity_ids: list[str]
    agent_ids: list[str]
    artifact_entity_ids: list[str]
    validation_ids: list[str]
    decision_ids: list[str]


class ProvenanceQueryReport(StrictModel):
    schema_version: Literal["task26373-provenance-query-v1"] = "task26373-provenance-query-v1"
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_traces: list[ClaimTraceRecord]
    recursive_decision_ancestor_entity_ids: list[str]
    negative_result_entity_ids: list[str]
    relationship_counts: dict[str, int]
    software_input_output_action_complete: Literal[True] = True
    claim_evidence_complete: Literal[True] = True
    contradiction_present: Literal[True] = True
    limitation_present: Literal[True] = True
    negative_result_lineage_present: Literal[True] = True
    publication_decision: Literal["blocked_pending_independent_confirmation_and_human_review"] = (
        "blocked_pending_independent_confirmation_and_human_review"
    )
    passed: Literal[True] = True
    query_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_query_hash(self) -> ProvenanceQueryReport:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"query_hash"}))
        if self.query_hash != expected:
            raise SystemsPaperOpenScienceIntegrityError("provenance query report hash mismatch")
        return self


class ReconstructionReport(StrictModel):
    schema_version: Literal["task26373-exact-reconstruction-v1"] = (
        "task26373-exact-reconstruction-v1"
    )
    parent_package_id: Literal["task260-final-paper-v2"] = "task260-final-paper-v2"
    parent_package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_file_count: int = Field(gt=0)
    parent_manifest_listed_file_count: int = Field(gt=0)
    reconstructed_file_count: int = Field(gt=0)
    exact_file_set_parity: Literal[True] = True
    exact_byte_hash_parity: Literal[True] = True
    parent_binding_parity: Literal[True] = True
    review_clean_reproduction_status: Literal["passed"] = "passed"
    review_assertion_count: int = Field(gt=0)
    review_checked_files: int = Field(gt=0)
    scientific_experiment_reexecuted: Literal[False] = False
    temporary_reconstruction_removed: Literal[True] = True
    reconstruction_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_reconstruction_hash(self) -> ReconstructionReport:
        if self.parent_file_count != self.reconstructed_file_count:
            raise ValueError("reconstructed Task 260 file count differs")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"reconstruction_hash"}))
        if self.reconstruction_hash != expected:
            raise SystemsPaperOpenScienceIntegrityError("exact reconstruction report hash mismatch")
        return self


class ExternalProfileResult(StrictModel):
    view: Literal["internal-complete", "review-reproduction"]
    profile_id: str
    requirement_severity: Literal["required"] = "required"
    metadata_only: Literal[True] = True
    exit_code: Literal[0] = 0
    status: Literal["passed"] = "passed"
    raw_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    persisted_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    report_relative_path: str


class ProfileValidationReport(StrictModel):
    schema_version: Literal["task26373-profile-validation-v1"] = "task26373-profile-validation-v1"
    validator_name: Literal["rocrate-validator"] = "rocrate-validator"
    validator_version: str
    validator_cli_version_observation: str
    external_validation_performed: bool
    externally_validated_profiles: list[str]
    results: list[ExternalProfileResult]
    internal_ro_crate_1_3_contract_passed: Literal[True] = True
    external_ro_crate_1_3_profile_available: Literal[False] = False
    external_ro_crate_1_3_limitation: Literal["validator-0.11.3-profiles-stop-at-ro-crate-1.2"] = (
        "validator-0.11.3-profiles-stop-at-ro-crate-1.2"
    )
    metadata_interoperability_only: Literal[True] = True
    scientific_confirmation_performed: Literal[False] = False
    profile_validation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_profile_report(self) -> ProfileValidationReport:
        expected_results = 2 * len(EXTERNAL_PROFILE_IDS)
        if self.external_validation_performed:
            if len(self.results) != expected_results:
                raise ValueError("both views require all four external profile checks")
            if sorted(set(self.externally_validated_profiles)) != sorted(EXTERNAL_PROFILE_IDS):
                raise ValueError("external profile set is incomplete")
        elif self.results or self.externally_validated_profiles:
            raise ValueError("unperformed external validation cannot retain results")
        expected = canonical_sha256(
            self.model_dump(mode="json", exclude={"profile_validation_hash"})
        )
        if self.profile_validation_hash != expected:
            raise SystemsPaperOpenScienceIntegrityError("profile validation report hash mismatch")
        return self


class OpenScienceOverlayReport(StrictModel):
    schema_version: Literal["task26373-open-science-overlay-report-v1"] = (
        "task26373-open-science-overlay-report-v1"
    )
    task_id: Literal["263.7.3"] = "263.7.3"
    package_id: Literal["task26373-open-science-overlay-v1"] = "task26373-open-science-overlay-v1"
    built_at: datetime
    parent_evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    audit_report_hash: Literal[
        "92a478ee85f2324353f5310425408fb60d5c58fc2ee222b16069cbcdc1bfa190"
    ] = "92a478ee85f2324353f5310425408fb60d5c58fc2ee222b16069cbcdc1bfa190"
    audit_manifest_hash: Literal[
        "8e2dd7b5cbee5aa4274b125bc9f7c2cdab3ef33017a38f37e782ea35d089b9c9"
    ] = "8e2dd7b5cbee5aa4274b125bc9f7c2cdab3ef33017a38f37e782ea35d089b9c9"
    reanalysis_report_hash: Literal[
        "476b920607ad981a1f0d7b0a33ff4d74e813a70159959c70386e9e15d6c37d99"
    ] = "476b920607ad981a1f0d7b0a33ff4d74e813a70159959c70386e9e15d6c37d99"
    reanalysis_manifest_hash: Literal[
        "f6d8371c9b1c54cb5ffa885c407210b74ede4b0c74d45466c6a2e074d089a6ab"
    ] = "f6d8371c9b1c54cb5ffa885c407210b74ede4b0c74d45466c6a2e074d089a6ab"
    rewrite_report_hash: Literal[
        "0182c044157b293e69227118a40431fd8fa2d36be23dbf4556569fb135708a31"
    ] = "0182c044157b293e69227118a40431fd8fa2d36be23dbf4556569fb135708a31"
    rewrite_manifest_hash: Literal[
        "83baa8a732560facc6d6401fbc3ef0d87c3958ef45d56de447d72b32c8a7b6df"
    ] = "83baa8a732560facc6d6401fbc3ef0d87c3958ef45d56de447d72b32c8a7b6df"
    provenance_bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provenance_query_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reconstruction_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_validation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    internal_hash_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_hash_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_file_count: int = Field(gt=0)
    internal_artifact_count: int = Field(gt=0)
    review_artifact_count: int = Field(gt=0)
    external_profile_validation_complete: bool
    profiles: list[str]
    internal_view_complete: Literal[True] = True
    review_view_sanitized: Literal[True] = True
    public_view_created: Literal[False] = False
    publication_performed: Literal[False] = False
    metadata_interoperability_only: Literal[True] = True
    independent_confirmation_complete: Literal[False] = False
    scientific_confirmation_added: Literal[False] = False
    publication_ready: Literal[False] = False
    independent_human_review_complete: Literal[False] = False
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    next_required_tasks: list[str]
    report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("built_at")
    @classmethod
    def _utc_built(cls, value: datetime) -> datetime:
        return _require_utc(value, "built_at")

    @model_validator(mode="after")
    def _validate_report_hash(self) -> OpenScienceOverlayReport:
        if self.profiles != sorted(self.profiles):
            raise ValueError("profile identifiers must be sorted")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"report_hash"}))
        if self.report_hash != expected:
            raise SystemsPaperOpenScienceIntegrityError("overlay report hash mismatch")
        return self


class OpenScienceOverlayManifest(StrictModel):
    schema_version: Literal["task26373-open-science-overlay-manifest-v1"] = (
        "task26373-open-science-overlay-manifest-v1"
    )
    task_id: Literal["263.7.3"] = "263.7.3"
    package_id: Literal["task26373-open-science-overlay-v1"] = "task26373-open-science-overlay-v1"
    report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    files: list[FileRecord]
    file_count: int = Field(gt=0)
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_manifest(self) -> OpenScienceOverlayManifest:
        paths = [item.relative_path for item in self.files]
        if self.file_count != len(self.files):
            raise ValueError("manifest file_count differs from files")
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("manifest paths must be unique and sorted")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"manifest_hash"}))
        if self.manifest_hash != expected:
            raise SystemsPaperOpenScienceIntegrityError("overlay manifest hash mismatch")
        return self


def fetch_standard_source_registry(
    *,
    output_dir: Path,
    retrieved_at: datetime,
    fetcher: StandardSourceFetcher = fetch_source_response,
) -> StandardSourceRegistry:
    """Fetch, marker-check, hash, and retain the six authoritative sources."""

    snapshots: list[StandardSourceSnapshot] = []
    for definition in standard_source_definitions():
        response = fetcher(definition.url)
        if not 200 <= response.status_code < 300:
            raise SystemsPaperOpenScienceIntegrityError(
                f"standard source returned HTTP {response.status_code}: {definition.url}"
            )
        snapshot = StandardSourceSnapshot.create(
            definition,
            response,
            retrieved_at,
        )
        raw_path = output_dir / snapshot.raw_relative_path
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(response.body)
        if _file_sha256(raw_path) != snapshot.body_sha256:
            raise SystemsPaperOpenScienceIntegrityError(
                f"persisted standard source hash changed: {snapshot.source_id}"
            )
        snapshots.append(snapshot)
    registry = StandardSourceRegistry.create(
        retrieved_at=retrieved_at,
        sources=snapshots,
    )
    _write_json(
        output_dir / SOURCE_REGISTRY_FILENAME,
        registry.model_dump(mode="json"),
    )
    return registry


def _assert_dependencies(
    parent_dir: Path,
    audit_dir: Path,
    reanalysis_dir: Path,
    rewrite_dir: Path,
) -> tuple[Any, Any, Any, Any, Any, Any, ParentSystemsPaperEvidence]:
    parent = ParentSystemsPaperEvidence.from_package(parent_dir)
    audit, audit_manifest = load_systems_paper_currency_audit(audit_dir)
    reanalysis, reanalysis_manifest = load_task_unit_reanalysis(reanalysis_dir)
    rewrite, rewrite_manifest = load_current_field_manuscript_rewrite(rewrite_dir)
    observed = {
        "audit report": audit.report_hash,
        "audit manifest": audit_manifest.manifest_hash,
        "reanalysis report": reanalysis.report_hash,
        "reanalysis manifest": reanalysis_manifest.manifest_hash,
        "rewrite report": rewrite.report_hash,
        "rewrite manifest": rewrite_manifest.manifest_hash,
    }
    expected = {
        "audit report": EXPECTED_AUDIT_REPORT_HASH,
        "audit manifest": EXPECTED_AUDIT_MANIFEST_HASH,
        "reanalysis report": EXPECTED_REANALYSIS_REPORT_HASH,
        "reanalysis manifest": EXPECTED_REANALYSIS_MANIFEST_HASH,
        "rewrite report": EXPECTED_REWRITE_REPORT_HASH,
        "rewrite manifest": EXPECTED_REWRITE_MANIFEST_HASH,
    }
    for label, expected_hash in expected.items():
        if observed[label] != expected_hash:
            raise SystemsPaperOpenScienceIntegrityError(f"frozen dependency changed: {label}")
    if audit.parent != parent or reanalysis.parent != parent:
        raise SystemsPaperOpenScienceIntegrityError(
            "audit/reanalysis no longer bind the immutable Task 260 parent"
        )
    if rewrite.independent_confirmation_complete or rewrite.publication_ready:
        raise SystemsPaperOpenScienceIntegrityError(
            "rewrite unexpectedly claims confirmation or publication readiness"
        )
    return (
        audit,
        audit_manifest,
        reanalysis,
        reanalysis_manifest,
        rewrite,
        rewrite_manifest,
        parent,
    )


def _parse_parent_time(parent_dir: Path) -> datetime:
    raw = _read_json(parent_dir / "paper-package.json")["created_at"]
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(timezone.utc)


def _entity(
    entity_id: str,
    kind: EntityKind,
    label: str,
    digest: str,
    source_uri: str,
    valid_from: datetime,
    *,
    attributes: Mapping[str, Any] | None = None,
) -> Entity:
    return Entity(
        entity_id=entity_id,
        kind=kind,
        label=label,
        content_digest=digest,
        source_uri=source_uri,
        media_type="application/json",
        valid_from=valid_from,
        attributes=dict(attributes or {}),
    )


def build_systems_paper_open_science_provenance(
    *,
    parent_dir: Path,
    audit_dir: Path,
    reanalysis_dir: Path,
    rewrite_dir: Path,
    built_at: datetime,
) -> ProvenanceBundle:
    """Build a causal Task260→audit→reanalysis→rewrite→decision bundle."""

    (
        audit,
        _,
        reanalysis,
        _,
        rewrite,
        _,
        parent,
    ) = _assert_dependencies(parent_dir, audit_dir, reanalysis_dir, rewrite_dir)
    t_parent = _parse_parent_time(parent_dir)
    t_audit = audit.built_at.astimezone(timezone.utc)
    t_reanalysis = reanalysis.built_at.astimezone(timezone.utc)
    t_rewrite = rewrite.built_at.astimezone(timezone.utc)
    t_overlay = _require_utc(built_at, "built_at")
    if not t_parent <= t_audit <= t_reanalysis <= t_rewrite <= t_overlay:
        raise SystemsPaperOpenScienceIntegrityError(
            "dependency timestamps do not form a causal sequence"
        )

    parent_manifest_path = parent_dir / "artifact-hashes.json"
    parent_package_path = parent_dir / "paper-package.json"
    claim_map_path = parent_dir / "evidence/claim-evidence-map.json"
    route1_path = parent_dir / "frozen-inputs/route-a-round-1-unseen.json"
    route2_path = parent_dir / "frozen-inputs/route-a-round-2-unseen.json"
    audit_path = audit_dir / "systems-paper-currency-audit.json"
    reanalysis_path = reanalysis_dir / "task-unit-reanalysis.json"
    rewrite_path = rewrite_dir / "current-field-manuscript-rewrite.json"
    source_hashes = {
        "parent_manifest": _file_sha256(parent_manifest_path),
        "parent_package": _file_sha256(parent_package_path),
        "claim_map": _file_sha256(claim_map_path),
        "route1": _file_sha256(route1_path),
        "route2": _file_sha256(route2_path),
        "audit": _file_sha256(audit_path),
        "reanalysis": _file_sha256(reanalysis_path),
        "rewrite": _file_sha256(rewrite_path),
        "implementation": _file_sha256(Path(__file__)),
    }

    source_specs = (
        (
            "entity.source.task260-manifest",
            "snapshot.task260-manifest",
            "Immutable Task 260 recursive hash inventory",
            source_hashes["parent_manifest"],
            "urn:autoresearch:task260:artifact-hashes",
            t_parent,
        ),
        (
            "entity.source.task260-claim-map",
            "snapshot.task260-claim-map",
            "Historical Task 260 claim-evidence map",
            source_hashes["claim_map"],
            "urn:autoresearch:task260:claim-evidence-map",
            t_parent,
        ),
        (
            "entity.source.route-a-round-1",
            "snapshot.route-a-round-1",
            "Frozen Route A round 1 unseen result",
            source_hashes["route1"],
            "urn:autoresearch:task260:route-a:round-1",
            t_parent,
        ),
        (
            "entity.source.route-a-round-2",
            "snapshot.route-a-round-2",
            "Frozen Route A round 2 unseen result",
            source_hashes["route2"],
            "urn:autoresearch:task260:route-a:round-2",
            t_parent,
        ),
        (
            "entity.source.task26370-audit",
            "snapshot.task26370-audit",
            "Task 263.7.0 audit source snapshot",
            source_hashes["audit"],
            "urn:autoresearch:task26370:audit",
            t_audit,
        ),
        (
            "entity.source.task26371-reanalysis",
            "snapshot.task26371-reanalysis",
            "Task 263.7.1 reanalysis source snapshot",
            source_hashes["reanalysis"],
            "urn:autoresearch:task26371:reanalysis",
            t_reanalysis,
        ),
    )
    entities = [
        _entity(
            entity_id,
            EntityKind.SOURCE_SNAPSHOT,
            label,
            digest,
            uri,
            valid_from,
        )
        for entity_id, _, label, digest, uri, valid_from in source_specs
    ]
    entities.extend(
        [
            _entity(
                "entity.task260.package",
                EntityKind.ARTIFACT,
                "Immutable Task 260 paper package manifest",
                source_hashes["parent_package"],
                "urn:autoresearch:task260:paper-package",
                t_parent,
                attributes={
                    "package_hash": parent.package_hash,
                    "immutable": True,
                    "external_submission_authorized": False,
                },
            ),
            _entity(
                "entity.task260.claim-map",
                EntityKind.ARTIFACT,
                "Historical Task 260 claim-evidence artifact",
                source_hashes["claim_map"],
                "urn:autoresearch:task260:claim-evidence-artifact",
                t_parent,
            ),
            _entity(
                "entity.failure.route-a-round-1",
                EntityKind.FAILURE,
                "Route A round 1 negative result",
                source_hashes["route1"],
                "urn:autoresearch:task260:negative-result:route-a-round-1",
                t_parent,
                attributes={"outcome": "negative_result", "round": 1},
            ),
            _entity(
                "entity.failure.route-a-round-2",
                EntityKind.FAILURE,
                "Route A round 2 negative result",
                source_hashes["route2"],
                "urn:autoresearch:task260:negative-result:route-a-round-2",
                t_parent,
                attributes={"outcome": "negative_result", "round": 2},
            ),
            _entity(
                "entity.task26370.audit",
                EntityKind.ARTIFACT,
                "Publication-currency and independent-unit audit",
                source_hashes["audit"],
                "urn:autoresearch:task26370:report",
                t_audit,
                attributes={"report_hash": audit.report_hash},
            ),
            _entity(
                "entity.task26371.reanalysis",
                EntityKind.ARTIFACT,
                "Additive independent-task reanalysis",
                source_hashes["reanalysis"],
                "urn:autoresearch:task26371:report",
                t_reanalysis,
                attributes={"report_hash": reanalysis.report_hash},
            ),
            _entity(
                "entity.task26372.rewrite",
                EntityKind.ARTIFACT,
                "Current-field manuscript rewrite",
                source_hashes["rewrite"],
                "urn:autoresearch:task26372:report",
                t_rewrite,
                attributes={
                    "report_hash": rewrite.report_hash,
                    "independent_confirmation_complete": False,
                    "publication_ready": False,
                },
            ),
            _entity(
                "entity.task26373.decision",
                EntityKind.DECISION,
                "Open Science overlay publication-boundary decision",
                canonical_sha256(
                    {
                        "outcome": ("blocked_pending_independent_confirmation_and_human_review"),
                        "task": TASK_ID,
                    }
                ),
                "urn:autoresearch:task26373:publication-boundary",
                t_overlay,
            ),
            _entity(
                "entity.task26373.software",
                EntityKind.CODE,
                "Task 263.7.3 deterministic overlay implementation",
                source_hashes["implementation"],
                "https://github.com/neutronstar238/ai-researcher-loop",
                t_overlay,
                attributes={"base_commit": BASE_COMMIT},
            ),
        ]
    )

    activity_specs = (
        ("activity.task260.freeze", ActivityKind.EXECUTION, "Task 260 package freeze", t_parent),
        ("activity.task26370.audit", ActivityKind.VALIDATION, "Task 263.7.0 audit", t_audit),
        (
            "activity.task26371.reanalysis",
            ActivityKind.VALIDATION,
            "Task 263.7.1 independent-unit reanalysis",
            t_reanalysis,
        ),
        (
            "activity.task26372.rewrite",
            ActivityKind.PROJECTION,
            "Task 263.7.2 current-field rewrite",
            t_rewrite,
        ),
        (
            "activity.task26373.decision",
            ActivityKind.DECISION,
            "Task 263.7.3 non-publication decision",
            t_overlay,
        ),
    )
    activities = [
        Activity(
            activity_id=activity_id,
            kind=kind,
            label=label,
            started_at=at_time,
            ended_at=at_time,
            valid_from=at_time,
        )
        for activity_id, kind, label, at_time in activity_specs
    ]
    agents = [
        Agent(
            agent_id="agent.autoresearch-software",
            kind=ProvenanceAgentKind.SOFTWARE,
            label="AutoResearch deterministic package software",
            implementation_hash=source_hashes["implementation"],
            valid_from=t_parent,
            attributes={
                "scientific_review_authority": False,
                "publication_authority": False,
            },
        ),
        Agent(
            agent_id="agent.evidence-policy",
            kind=ProvenanceAgentKind.DETERMINISTIC_POLICY,
            label="Fail-closed evidence and publication policy",
            implementation_hash=source_hashes["implementation"],
            valid_from=t_parent,
            attributes={"human_override_required_for_publication": True},
        ),
    ]
    plans = [
        Plan(
            plan_id="plan.task260-frozen",
            title="Immutable Task 260 package plan",
            description="Preserve all historical artifacts and hashes without reinterpretation.",
            content_digest=parent.preregistration_file_sha256,
            valid_from=t_parent,
        ),
        Plan(
            plan_id="plan.task26373-overlay",
            title="Task 263.7.3 interoperable projection plan",
            description=(
                "Map immutable evidence to internal/review RO-Crate and PROV views while "
                "keeping scientific and publication gates false."
            ),
            content_digest=source_hashes["implementation"],
            valid_from=t_overlay,
        ),
    ]

    usages: list[Usage] = []
    usage_counter = 0

    def add_usage(activity_id: str, entity_id: str, role: str, at_time: datetime) -> None:
        nonlocal usage_counter
        usage_counter += 1
        usages.append(
            Usage(
                usage_id=f"usage.task26373.{usage_counter:02d}",
                activity_id=activity_id,
                entity_id=entity_id,
                role=role,
                at_time=at_time,
                valid_from=at_time,
            )
        )

    for entity_id, role in (
        ("entity.source.task260-manifest", "recursive integrity inventory"),
        ("entity.source.task260-claim-map", "historical claim map"),
        ("entity.source.route-a-round-1", "negative result input"),
        ("entity.source.route-a-round-2", "negative result input"),
    ):
        add_usage("activity.task260.freeze", entity_id, role, t_parent)
    for entity_id, role in (
        ("entity.task260.package", "immutable parent"),
        ("entity.source.task260-manifest", "hash inventory"),
    ):
        add_usage("activity.task26370.audit", entity_id, role, t_audit)
    for entity_id, role in (
        ("entity.task260.package", "immutable parent"),
        ("entity.source.task26370-audit", "audit input"),
    ):
        add_usage("activity.task26371.reanalysis", entity_id, role, t_reanalysis)
    for entity_id, role in (
        ("entity.source.task26370-audit", "audit input"),
        ("entity.source.task26371-reanalysis", "corrected unit analysis"),
    ):
        add_usage("activity.task26372.rewrite", entity_id, role, t_rewrite)
    for entity_id, role in (
        ("entity.task260.package", "immutable historical object"),
        ("entity.task26370.audit", "publication audit"),
        ("entity.task26371.reanalysis", "unit correction"),
        ("entity.task26372.rewrite", "current manuscript projection"),
        ("entity.failure.route-a-round-1", "retained negative result"),
        ("entity.failure.route-a-round-2", "retained negative result"),
        ("entity.task26373.software", "projection implementation"),
    ):
        add_usage("activity.task26373.decision", entity_id, role, t_overlay)

    generation_specs = (
        ("entity.task260.package", "activity.task260.freeze", t_parent),
        ("entity.task260.claim-map", "activity.task260.freeze", t_parent),
        ("entity.failure.route-a-round-1", "activity.task260.freeze", t_parent),
        ("entity.failure.route-a-round-2", "activity.task260.freeze", t_parent),
        ("entity.task26370.audit", "activity.task26370.audit", t_audit),
        ("entity.source.task26370-audit", "activity.task26370.audit", t_audit),
        ("entity.task26371.reanalysis", "activity.task26371.reanalysis", t_reanalysis),
        (
            "entity.source.task26371-reanalysis",
            "activity.task26371.reanalysis",
            t_reanalysis,
        ),
        ("entity.task26372.rewrite", "activity.task26372.rewrite", t_rewrite),
        ("entity.task26373.decision", "activity.task26373.decision", t_overlay),
    )
    generations = [
        Generation(
            generation_id=f"generation.task26373.{index:02d}",
            entity_id=entity_id,
            activity_id=activity_id,
            at_time=at_time,
            valid_from=at_time,
        )
        for index, (entity_id, activity_id, at_time) in enumerate(generation_specs, start=1)
    ]
    derivation_specs = (
        ("entity.task260.package", "entity.source.task260-manifest", "activity.task260.freeze"),
        ("entity.task260.claim-map", "entity.source.task260-claim-map", "activity.task260.freeze"),
        (
            "entity.failure.route-a-round-1",
            "entity.source.route-a-round-1",
            "activity.task260.freeze",
        ),
        (
            "entity.failure.route-a-round-2",
            "entity.source.route-a-round-2",
            "activity.task260.freeze",
        ),
        ("entity.task26370.audit", "entity.task260.package", "activity.task26370.audit"),
        ("entity.task26371.reanalysis", "entity.task26370.audit", "activity.task26371.reanalysis"),
        ("entity.task26371.reanalysis", "entity.task260.package", "activity.task26371.reanalysis"),
        ("entity.task26372.rewrite", "entity.task26371.reanalysis", "activity.task26372.rewrite"),
        ("entity.task26372.rewrite", "entity.task26370.audit", "activity.task26372.rewrite"),
        ("entity.task26373.decision", "entity.task26372.rewrite", "activity.task26373.decision"),
        ("entity.task26373.decision", "entity.task26371.reanalysis", "activity.task26373.decision"),
        ("entity.task26373.decision", "entity.task26370.audit", "activity.task26373.decision"),
        (
            "entity.task26373.decision",
            "entity.failure.route-a-round-1",
            "activity.task26373.decision",
        ),
        (
            "entity.task26373.decision",
            "entity.failure.route-a-round-2",
            "activity.task26373.decision",
        ),
    )
    derivations = [
        Derivation(
            derivation_id=f"derivation.task26373.{index:02d}",
            generated_entity_id=generated,
            used_entity_id=used,
            activity_id=activity,
            valid_from={
                "activity.task260.freeze": t_parent,
                "activity.task26370.audit": t_audit,
                "activity.task26371.reanalysis": t_reanalysis,
                "activity.task26372.rewrite": t_rewrite,
                "activity.task26373.decision": t_overlay,
            }[activity],
        )
        for index, (generated, used, activity) in enumerate(derivation_specs, start=1)
    ]
    associations: list[Association] = []
    for index, (activity_id, _, _, at_time) in enumerate(activity_specs, start=1):
        plan_id = (
            "plan.task260-frozen"
            if activity_id == "activity.task260.freeze"
            else "plan.task26373-overlay"
        )
        associations.extend(
            [
                Association(
                    association_id=f"association.task26373.{index:02d}.software",
                    activity_id=activity_id,
                    agent_id="agent.autoresearch-software",
                    role="deterministic executor",
                    plan_id=plan_id,
                    at_time=at_time,
                    valid_from=at_time,
                ),
                Association(
                    association_id=f"association.task26373.{index:02d}.policy",
                    activity_id=activity_id,
                    agent_id="agent.evidence-policy",
                    role="fail-closed validator",
                    plan_id=plan_id,
                    at_time=at_time,
                    valid_from=at_time,
                ),
            ]
        )
    snapshots = [
        SourceSnapshot(
            snapshot_id=snapshot_id,
            entity_id=entity_id,
            source_uri=uri,
            retrieved_at=valid_from,
            content_digest=digest,
            valid_from=valid_from,
        )
        for entity_id, snapshot_id, _, digest, uri, valid_from in source_specs
    ]
    claims = [
        Claim(
            claim_id="claim.controlled-state-machine-demonstration",
            statement=(
                "Task 260 is a controlled local demonstration of a tamper-evident, "
                "failure-linked research state machine; it is not an external superiority result."
            ),
            project_id="project.autoresearch",
            confidence=1.0,
            core=True,
            valid_from=t_parent,
        ),
        Claim(
            claim_id="claim.thirty-seed-cells-independent",
            statement=(
                "The historical 30 task-seed cells are independent publication-facing "
                "sampling units."
            ),
            project_id="project.autoresearch",
            confidence=0.0,
            core=False,
            valid_from=t_parent,
        ),
        Claim(
            claim_id="claim.route-a-two-negative-rounds",
            statement="Both frozen Route A mechanism rounds remained negative.",
            project_id="project.autoresearch",
            confidence=1.0,
            core=True,
            valid_from=t_parent,
        ),
    ]
    validation_specs = (
        (
            "validation.controlled-demonstration",
            "evidence.controlled-demonstration",
            "activity.task26370.audit",
            ValidationStatus.PASSED,
            "The immutable package and audit support only the bounded local demonstration.",
            "entity.task260.package",
            t_audit,
        ),
        (
            "validation.historical-unit-support",
            "evidence.historical-unit-support",
            "activity.task26371.reanalysis",
            ValidationStatus.WARNING,
            "Historical support is retained, but the sampling-unit interpretation is retired.",
            "entity.task260.claim-map",
            t_reanalysis,
        ),
        (
            "validation.task-unit-counterevidence",
            "counterevidence.task-unit-correction",
            "activity.task26371.reanalysis",
            ValidationStatus.PASSED,
            "Independent-task reconstruction proves deterministic seeds duplicate outputs.",
            "entity.task26371.reanalysis",
            t_reanalysis,
        ),
        (
            "validation.external-validity-limit",
            "evidence.external-validity-limit",
            "activity.task26370.audit",
            ValidationStatus.PASSED,
            "Co-design, two task families, and absent independent confirmation limit inference.",
            "entity.task26370.audit",
            t_audit,
        ),
        (
            "validation.route-a-round-1-negative",
            "evidence.route-a-round-1-negative",
            "activity.task26370.audit",
            ValidationStatus.PASSED,
            "Round 1 remains a frozen negative result.",
            "entity.failure.route-a-round-1",
            t_audit,
        ),
        (
            "validation.route-a-round-2-negative",
            "evidence.route-a-round-2-negative",
            "activity.task26370.audit",
            ValidationStatus.PASSED,
            "Round 2 remains a frozen negative result.",
            "entity.failure.route-a-round-2",
            t_audit,
        ),
    )
    validations = [
        Validation(
            validation_id=validation_id,
            subject_id=subject_id,
            activity_id=activity_id,
            agent_id="agent.evidence-policy",
            status=status,
            summary=summary,
            checked_at=checked_at,
            artifact_entity_id=artifact_id,
            valid_from=checked_at,
        )
        for (
            validation_id,
            subject_id,
            activity_id,
            status,
            summary,
            artifact_id,
            checked_at,
        ) in validation_specs
    ]
    evidence = [
        Evidence(
            evidence_id="evidence.controlled-demonstration",
            claim_id="claim.controlled-state-machine-demonstration",
            artifact_entity_id="entity.task260.package",
            source_entity_id="entity.source.task260-manifest",
            source_snapshot_id="snapshot.task260-manifest",
            generating_activity_id="activity.task260.freeze",
            responsible_agent_ids=["agent.autoresearch-software"],
            validation_ids=["validation.controlled-demonstration"],
            summary="The complete immutable package preserves the local state-machine run.",
            confidence=1.0,
            direction=EvidenceDirection.SUPPORTS,
            valid_from=t_audit,
        ),
        Evidence(
            evidence_id="evidence.historical-unit-support",
            claim_id="claim.thirty-seed-cells-independent",
            artifact_entity_id="entity.task260.claim-map",
            source_entity_id="entity.source.task260-claim-map",
            source_snapshot_id="snapshot.task260-claim-map",
            generating_activity_id="activity.task260.freeze",
            responsible_agent_ids=["agent.autoresearch-software"],
            validation_ids=["validation.historical-unit-support"],
            summary="The original claim map retained the historical 30-cell interpretation.",
            confidence=0.0,
            direction=EvidenceDirection.SUPPORTS,
            valid_from=t_reanalysis,
        ),
        Evidence(
            evidence_id="evidence.external-validity-limit",
            claim_id="claim.controlled-state-machine-demonstration",
            artifact_entity_id="entity.task26370.audit",
            source_entity_id="entity.source.task260-manifest",
            source_snapshot_id="snapshot.task260-manifest",
            generating_activity_id="activity.task26370.audit",
            responsible_agent_ids=["agent.autoresearch-software"],
            validation_ids=["validation.external-validity-limit"],
            summary=("The audit limits any inference beyond the co-designed local demonstration."),
            confidence=1.0,
            direction=EvidenceDirection.LIMITS,
            valid_from=t_audit,
        ),
        Evidence(
            evidence_id="evidence.route-a-round-1-negative",
            claim_id="claim.route-a-two-negative-rounds",
            artifact_entity_id="entity.failure.route-a-round-1",
            source_entity_id="entity.source.route-a-round-1",
            source_snapshot_id="snapshot.route-a-round-1",
            generating_activity_id="activity.task260.freeze",
            responsible_agent_ids=["agent.autoresearch-software"],
            validation_ids=["validation.route-a-round-1-negative"],
            summary="The first frozen unseen confidence interval failed the positive gate.",
            confidence=1.0,
            direction=EvidenceDirection.SUPPORTS,
            valid_from=t_audit,
        ),
        Evidence(
            evidence_id="evidence.route-a-round-2-negative",
            claim_id="claim.route-a-two-negative-rounds",
            artifact_entity_id="entity.failure.route-a-round-2",
            source_entity_id="entity.source.route-a-round-2",
            source_snapshot_id="snapshot.route-a-round-2",
            generating_activity_id="activity.task260.freeze",
            responsible_agent_ids=["agent.autoresearch-software"],
            validation_ids=["validation.route-a-round-2-negative"],
            summary="The second frozen unseen confidence interval failed the positive gate.",
            confidence=1.0,
            direction=EvidenceDirection.SUPPORTS,
            valid_from=t_audit,
        ),
    ]
    counterevidence = [
        Counterevidence(
            evidence_id="counterevidence.task-unit-correction",
            claim_id="claim.thirty-seed-cells-independent",
            artifact_entity_id="entity.task26371.reanalysis",
            source_entity_id="entity.source.task26370-audit",
            source_snapshot_id="snapshot.task26370-audit",
            generating_activity_id="activity.task26371.reanalysis",
            responsible_agent_ids=["agent.autoresearch-software"],
            validation_ids=["validation.task-unit-counterevidence"],
            summary=(
                "The three seeds duplicate scientific outputs; ten tasks, not 30 cells, "
                "are the independent units."
            ),
            confidence=1.0,
            direction=EvidenceDirection.CONTRADICTS,
            valid_from=t_reanalysis,
        )
    ]
    all_validation_ids = [item[0] for item in validation_specs]
    decisions = [
        Decision(
            decision_id="decision.task26373.publication-boundary",
            claim_ids=[item.claim_id for item in claims],
            activity_id="activity.task26373.decision",
            responsible_agent_id="agent.evidence-policy",
            validation_ids=all_validation_ids,
            artifact_entity_id="entity.task26373.decision",
            outcome="blocked_pending_independent_confirmation_and_human_review",
            rationale=(
                "Interoperable metadata and exact reconstruction close portability defects "
                "but add no independent task, effect, human review, or publication approval."
            ),
            decided_at=t_overlay,
            valid_from=t_overlay,
        )
    ]
    return ProvenanceBundle.create(
        bundle_id="bundle.task26373.open-science-overlay",
        project_id="project.autoresearch",
        run_id=PACKAGE_ID,
        created_at=t_overlay,
        entities=entities,
        activities=activities,
        agents=agents,
        plans=plans,
        usages=usages,
        generations=generations,
        derivations=derivations,
        associations=associations,
        source_snapshots=snapshots,
        claims=claims,
        evidence=evidence,
        counterevidence=counterevidence,
        validations=validations,
        decisions=decisions,
        metadata={
            "task_id": TASK_ID,
            "base_commit": BASE_COMMIT,
            "metadata_interoperability_only": True,
            "scientific_confirmation_added": False,
            "public_release_authorized": False,
            "external_submission_authorized": False,
        },
    )


def run_systems_paper_provenance_queries(
    bundle: ProvenanceBundle,
) -> ProvenanceQueryReport:
    """Run fail-closed claim traces and recursive decision ancestry queries."""

    bundle.verify_integrity()
    traces = [
        ClaimTraceRecord.model_validate(
            bundle.require_claim_trace(claim_id).model_dump(mode="json")
        )
        for claim_id in (
            "claim.controlled-state-machine-demonstration",
            "claim.route-a-two-negative-rounds",
            "claim.thirty-seed-cells-independent",
        )
    ]
    by_claim = {item.claim_id: item for item in traces}
    if not by_claim["claim.controlled-state-machine-demonstration"].limiting_evidence_ids:
        raise SystemsPaperOpenScienceIntegrityError("core claim lacks limitation evidence")
    if not by_claim["claim.thirty-seed-cells-independent"].counterevidence_ids:
        raise SystemsPaperOpenScienceIntegrityError(
            "retired unit claim lacks explicit counterevidence"
        )
    negative_entities = sorted(
        entity.entity_id
        for entity in bundle.entities
        if entity.kind is EntityKind.FAILURE
        and entity.attributes.get("outcome") == "negative_result"
    )
    if negative_entities != [
        "entity.failure.route-a-round-1",
        "entity.failure.route-a-round-2",
    ]:
        raise SystemsPaperOpenScienceIntegrityError("negative-result lineage is incomplete")

    parents: dict[str, set[str]] = {}
    for derivation in bundle.derivations:
        parents.setdefault(derivation.generated_entity_id, set()).add(derivation.used_entity_id)
    ancestors: set[str] = set()
    pending = ["entity.task26373.decision"]
    while pending:
        current = pending.pop()
        for parent_id in sorted(parents.get(current, set())):
            if parent_id not in ancestors:
                ancestors.add(parent_id)
                pending.append(parent_id)
    required_ancestors = {
        "entity.task26370.audit",
        "entity.task26371.reanalysis",
        "entity.task26372.rewrite",
        "entity.failure.route-a-round-1",
        "entity.failure.route-a-round-2",
    }
    if not required_ancestors <= ancestors:
        raise SystemsPaperOpenScienceIntegrityError(
            "publication decision recursive ancestry is incomplete"
        )
    payload = {
        "schema_version": "task26373-provenance-query-v1",
        "bundle_hash": bundle.bundle_hash,
        "claim_traces": traces,
        "recursive_decision_ancestor_entity_ids": sorted(ancestors),
        "negative_result_entity_ids": negative_entities,
        "relationship_counts": {
            "activities": len(bundle.activities),
            "agents": len(bundle.agents),
            "associations": len(bundle.associations),
            "counterevidence": len(bundle.counterevidence),
            "derivations": len(bundle.derivations),
            "entities": len(bundle.entities),
            "evidence": len(bundle.evidence),
            "generations": len(bundle.generations),
            "source_snapshots": len(bundle.source_snapshots),
            "usages": len(bundle.usages),
            "validations": len(bundle.validations),
        },
        "software_input_output_action_complete": True,
        "claim_evidence_complete": True,
        "contradiction_present": True,
        "limitation_present": True,
        "negative_result_lineage_present": True,
        "publication_decision": ("blocked_pending_independent_confirmation_and_human_review"),
        "passed": True,
    }
    return ProvenanceQueryReport.model_validate(_addressed(payload, "query_hash"))


def _media_type(path: Path) -> str:
    suffix = path.suffix.casefold()
    return {
        ".bib": "application/x-bibtex",
        ".csv": "text/csv",
        ".html": "text/html",
        ".json": "application/json",
        ".md": "text/markdown",
        ".pdf": "application/pdf",
        ".py": "text/x-python",
        ".tex": "application/x-tex",
        ".txt": "text/plain",
        ".yaml": "application/yaml",
        ".yml": "application/yaml",
        ".zip": "application/zip",
    }.get(suffix, "application/octet-stream")


def _parent_inventory(parent_dir: Path) -> dict[str, str]:
    manifest = _read_json(parent_dir / "artifact-hashes.json")
    _validate_addressed(manifest, "manifest_hash", label="Task 260 artifact manifest")
    records = cast(list[dict[str, Any]], manifest["files"])
    if manifest.get("file_count") != len(records):
        raise SystemsPaperOpenScienceIntegrityError("Task 260 artifact manifest file count changed")
    expected = {str(item["relative_path"]): str(item["sha256"]) for item in records}
    if len(expected) != len(records):
        raise SystemsPaperOpenScienceIntegrityError(
            "Task 260 artifact manifest contains duplicate paths"
        )
    observed_paths = {
        path.relative_to(parent_dir).as_posix() for path in parent_dir.rglob("*") if path.is_file()
    }
    manifest_exclusions = {
        "artifact-hashes.json",
        "paper-package.json",
        "paper-package.md",
    }
    if observed_paths - set(expected) != manifest_exclusions:
        raise SystemsPaperOpenScienceIntegrityError(
            "Task 260 manifest exclusions or file set changed"
        )
    for relative, digest in expected.items():
        path = parent_dir / relative
        if not path.is_file() or _file_sha256(path) != digest:
            raise SystemsPaperOpenScienceIntegrityError(f"Task 260 artifact changed: {relative}")
    for relative in manifest_exclusions:
        expected[relative] = _file_sha256(parent_dir / relative)
    return dict(sorted(expected.items()))


def _artifact(
    source: Path,
    crate_path: str,
    *,
    role: str,
    access: ArtifactAccess,
    transform: ArtifactTransform = ArtifactTransform.COPY,
    provenance_entity_id: str | None = None,
    license_id: str = "LicenseRef-Internal-Research",
    description: str,
) -> ResearchObjectArtifact:
    return ResearchObjectArtifact(
        source_path=source,
        crate_path=crate_path,
        role=role,
        media_type=_media_type(source),
        license_id=license_id,
        access=access,
        provenance_entity_id=provenance_entity_id,
        expected_sha256=_file_sha256(source),
        transform=transform,
        description=description,
    )


def build_systems_paper_open_science_artifacts(
    *,
    parent_dir: Path,
    audit_dir: Path,
    reanalysis_dir: Path,
    rewrite_dir: Path,
    staging_dir: Path,
) -> tuple[list[ResearchObjectArtifact], list[JsonAssertion], int]:
    """Bind the complete internal parent and a sanitized review evidence set."""

    inventory = _parent_inventory(parent_dir)
    entity_by_parent_path = {
        "artifact-hashes.json": "entity.source.task260-manifest",
        "paper-package.json": "entity.task260.package",
        "evidence/claim-evidence-map.json": "entity.task260.claim-map",
        "frozen-inputs/route-a-round-1-unseen.json": ("entity.failure.route-a-round-1"),
        "frozen-inputs/route-a-round-2-unseen.json": ("entity.failure.route-a-round-2"),
    }
    artifacts = [
        _artifact(
            parent_dir / relative,
            f"payload/task260-final-paper-v2/{relative}",
            role="immutable_parent_payload",
            access=ArtifactAccess.INTERNAL,
            provenance_entity_id=entity_by_parent_path.get(relative),
            description="Byte-preserved Task 260 internal payload artifact.",
        )
        for relative in inventory
    ]

    review_specs: tuple[tuple[Path, str, str, str | None], ...] = (
        (
            parent_dir / "paper-package.json",
            "evidence/task260/paper-package.json",
            "parent_manifest",
            "entity.task260.package",
        ),
        (
            parent_dir / "artifact-hashes.json",
            "evidence/task260/artifact-hashes.json",
            "parent_hash_inventory",
            "entity.source.task260-manifest",
        ),
        (
            parent_dir / "evidence/claim-evidence-map.json",
            "evidence/task260/claim-evidence-map.json",
            "historical_claim_evidence",
            "entity.task260.claim-map",
        ),
        (
            parent_dir / "frozen-inputs/route-a-round-1-unseen.json",
            "evidence/task260/route-a-round-1-unseen.json",
            "negative_result",
            "entity.failure.route-a-round-1",
        ),
        (
            parent_dir / "frozen-inputs/route-a-round-2-unseen.json",
            "evidence/task260/route-a-round-2-unseen.json",
            "negative_result",
            "entity.failure.route-a-round-2",
        ),
        (
            parent_dir / "frozen-inputs/systems-preregistration.json",
            "evidence/task260/systems-preregistration.json",
            "preregistration",
            None,
        ),
        (
            parent_dir / "frozen-inputs/systems-benchmark-result.json",
            "evidence/task260/systems-benchmark-result.json",
            "historical_result",
            None,
        ),
        (
            parent_dir / "frozen-inputs/systems-contribution-gate.json",
            "evidence/task260/systems-contribution-gate.json",
            "historical_gate",
            None,
        ),
        (
            audit_dir / "systems-paper-currency-audit.json",
            "evidence/task26370/systems-paper-currency-audit.json",
            "publication_audit",
            "entity.task26370.audit",
        ),
        (
            audit_dir / "systems-paper-currency-audit-manifest.json",
            "evidence/task26370/manifest.json",
            "audit_manifest",
            None,
        ),
        (
            audit_dir / "independent-unit-audit.json",
            "evidence/task26370/independent-unit-audit.json",
            "unit_audit",
            None,
        ),
        (
            audit_dir / "repair-plan.json",
            "evidence/task26370/repair-plan.json",
            "repair_plan",
            None,
        ),
        (
            reanalysis_dir / "task-unit-reanalysis.json",
            "evidence/task26371/task-unit-reanalysis.json",
            "unit_reanalysis",
            "entity.task26371.reanalysis",
        ),
        (
            reanalysis_dir / "task-unit-reanalysis-manifest.json",
            "evidence/task26371/manifest.json",
            "reanalysis_manifest",
            None,
        ),
        (
            reanalysis_dir / "claim-disposition-ledger.json",
            "evidence/task26371/claim-disposition-ledger.json",
            "claim_disposition",
            None,
        ),
        (
            reanalysis_dir / "task-level-analysis.json",
            "evidence/task26371/task-level-analysis.json",
            "task_level_analysis",
            None,
        ),
        (
            rewrite_dir / "current-field-manuscript-rewrite.json",
            "evidence/task26372/current-field-manuscript-rewrite.json",
            "current_field_rewrite",
            "entity.task26372.rewrite",
        ),
        (
            rewrite_dir / "current-field-manuscript-manifest.json",
            "evidence/task26372/manifest.json",
            "rewrite_manifest",
            None,
        ),
        (
            rewrite_dir / "current-field-claim-ledger.json",
            "evidence/task26372/current-field-claim-ledger.json",
            "current_claim_ledger",
            None,
        ),
        (
            rewrite_dir / "surface-resolution-ledger.json",
            "evidence/task26372/surface-resolution-ledger.json",
            "surface_resolution",
            None,
        ),
    )
    for source, crate_path, role, entity_id in review_specs:
        artifacts.append(
            _artifact(
                source,
                crate_path,
                role=role,
                access=ArtifactAccess.REVIEW,
                transform=ArtifactTransform.SANITIZE_JSON,
                provenance_entity_id=entity_id,
                description="Sanitized review evidence; no public redistribution approval.",
            )
        )
    artifacts.append(
        _artifact(
            rewrite_dir / "paper/source/main.pdf",
            "manuscript/current-field-manuscript.pdf",
            role="current_manuscript",
            access=ArtifactAccess.REVIEW,
            license_id="LicenseRef-Review-Only-No-Redistribution",
            description="Current-field manuscript for controlled human review only.",
        )
    )
    registry_path = staging_dir / SOURCE_REGISTRY_FILENAME
    artifacts.append(
        _artifact(
            registry_path,
            "standards/source-registry.json",
            role="standards_registry",
            access=ArtifactAccess.REVIEW,
            license_id="LicenseRef-Review-Only-No-Redistribution",
            description="Hashes and metadata for authoritative standards snapshots.",
        )
    )
    assertions = [
        JsonAssertion(
            "evidence/task260/paper-package.json",
            "/external_submission_authorized",
            False,
            "Task 260 external submission remains unauthorized.",
        ),
        JsonAssertion(
            "evidence/task260/route-a-round-1-unseen.json",
            "/outcome",
            "negative_result",
            "Route A round 1 remains negative.",
        ),
        JsonAssertion(
            "evidence/task260/route-a-round-2-unseen.json",
            "/outcome",
            "negative_result",
            "Route A round 2 remains negative.",
        ),
        JsonAssertion(
            "evidence/task26370/systems-paper-currency-audit.json",
            "/publication_ready",
            False,
            "Publication audit remains blocking.",
        ),
        JsonAssertion(
            "evidence/task26371/task-unit-reanalysis.json",
            "/fresh_confirmatory_evidence",
            False,
            "Task-unit correction is not fresh confirmation.",
        ),
        JsonAssertion(
            "evidence/task26372/current-field-manuscript-rewrite.json",
            "/independent_confirmation_complete",
            False,
            "Current-field rewrite adds no independent confirmation.",
        ),
        JsonAssertion(
            "standards/source-registry.json",
            "/source_count",
            6,
            "All six authoritative interoperability sources remain bound.",
        ),
    ]
    return artifacts, assertions, len(inventory)


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _file_sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def run_exact_task260_reconstruction(
    *,
    parent_dir: Path,
    internal_crate_dir: Path,
    review_crate_dir: Path,
    work_root: Path,
    parent: ParentSystemsPaperEvidence,
) -> ReconstructionReport:
    """Reconstruct all Task 260 files from the crate in a fresh directory."""

    payload = internal_crate_dir / "payload/task260-final-paper-v2"
    if not payload.is_dir():
        raise SystemsPaperOpenScienceIntegrityError(
            "internal crate lacks the complete Task 260 payload"
        )
    source_hashes = _tree_hashes(parent_dir)
    manifest = _read_json(parent_dir / "artifact-hashes.json")
    with tempfile.TemporaryDirectory(prefix="task26373-reconstruct-", dir=work_root) as raw:
        clean_root = Path(raw)
        reconstructed = clean_root / "task260-final-paper-v2"
        shutil.copytree(payload, reconstructed)
        reconstructed_hashes = _tree_hashes(reconstructed)
        if source_hashes.keys() != reconstructed_hashes.keys():
            raise SystemsPaperOpenScienceIntegrityError(
                "clean Task 260 reconstruction changed the file set"
            )
        if source_hashes != reconstructed_hashes:
            raise SystemsPaperOpenScienceIntegrityError(
                "clean Task 260 reconstruction changed one or more bytes"
            )
        reconstructed_parent = ParentSystemsPaperEvidence.from_package(reconstructed)
        if reconstructed_parent != parent:
            raise SystemsPaperOpenScienceIntegrityError(
                "clean Task 260 reconstruction changed the parent binding"
            )
        review_clean = run_clean_directory_reproduction(
            review_crate_dir,
            clean_dir=clean_root / "review-reproduction",
        )
        payload_report = {
            "schema_version": "task26373-exact-reconstruction-v1",
            "parent_package_id": parent.package_id,
            "parent_package_hash": parent.package_hash,
            "parent_evidence_hash": parent.parent_evidence_hash,
            "parent_file_count": len(source_hashes),
            "parent_manifest_listed_file_count": int(manifest["file_count"]),
            "reconstructed_file_count": len(reconstructed_hashes),
            "exact_file_set_parity": True,
            "exact_byte_hash_parity": True,
            "parent_binding_parity": True,
            "review_clean_reproduction_status": review_clean.status,
            "review_assertion_count": review_clean.assertion_count,
            "review_checked_files": review_clean.checked_files,
            "scientific_experiment_reexecuted": False,
            "temporary_reconstruction_removed": True,
        }
    return ReconstructionReport.model_validate(_addressed(payload_report, "reconstruction_hash"))


def _sanitize_validator_text(text: str, crate_dir: Path, executable: Path) -> str:
    validator_root = executable.resolve().parent.parent
    replacements = {
        crate_dir.resolve().as_posix(): "$CRATE",
        str(crate_dir.resolve()): "$CRATE",
        executable.resolve().as_posix(): "$VALIDATOR",
        str(executable.resolve()): "$VALIDATOR",
        validator_root.as_posix(): "$VALIDATOR_ROOT",
        str(validator_root): "$VALIDATOR_ROOT",
        Path.home().resolve().as_posix(): "$USER_HOME",
        str(Path.home().resolve()): "$USER_HOME",
    }
    sanitized = text
    for source, replacement in replacements.items():
        sanitized = sanitized.replace(source, replacement)
        sanitized = sanitized.replace(source.replace("\\", "\\\\"), replacement)
    return sanitized


def run_external_profile_validation(
    *,
    output_dir: Path,
    export: OpenScienceExport,
    validator_executable: Path | None,
) -> ProfileValidationReport:
    """Run supported required profiles and record the explicit 1.3 tool gap."""

    internal = Path(export.internal.crate_dir)
    review = Path(export.review.crate_dir)
    for view, root in (
        (ResearchObjectView.INTERNAL, internal),
        (ResearchObjectView.REVIEW, review),
    ):
        validation = validate_open_science_view(root, view=view)
        if validation.status != "passed" or not validation.checks.get("ro_crate_1_3"):
            raise SystemsPaperOpenScienceIntegrityError(
                f"internal RO-Crate 1.3 contract failed for {view.value}"
            )
    if validator_executable is None:
        payload = {
            "schema_version": "task26373-profile-validation-v1",
            "validator_name": "rocrate-validator",
            "validator_version": "not-run-deterministic-test-mode",
            "validator_cli_version_observation": "not-run-deterministic-test-mode",
            "external_validation_performed": False,
            "externally_validated_profiles": [],
            "results": [],
            "internal_ro_crate_1_3_contract_passed": True,
            "external_ro_crate_1_3_profile_available": False,
            "external_ro_crate_1_3_limitation": ("validator-0.11.3-profiles-stop-at-ro-crate-1.2"),
            "metadata_interoperability_only": True,
            "scientific_confirmation_performed": False,
        }
        return ProfileValidationReport.model_validate(
            _addressed(payload, "profile_validation_hash")
        )
    executable = validator_executable.resolve()
    if not executable.is_file():
        raise SystemsPaperOpenScienceIntegrityError(
            f"rocrate-validator executable is missing: {executable}"
        )
    version = subprocess.run(
        [str(executable), "--version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if version.returncode != 0:
        raise SystemsPaperOpenScienceIntegrityError(
            f"rocrate-validator version probe failed: {version.stderr}"
        )
    validator_python = executable.parent / ("python.exe" if os.name == "nt" else "python")
    package_version = subprocess.run(
        [
            str(validator_python),
            "-c",
            "import importlib.metadata as m; print(m.version('roc-validator'))",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if package_version.returncode != 0 or package_version.stdout.strip() != "0.11.3":
        raise SystemsPaperOpenScienceIntegrityError(
            "isolated validator package is not the frozen roc-validator 0.11.3"
        )
    capability = subprocess.run(
        [
            str(executable),
            "--no-interactive",
            "--disable-color",
            "profiles",
            "describe",
            "ro-crate-1.3",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if capability.returncode == 0:
        raise SystemsPaperOpenScienceIntegrityError(
            "validator now exposes RO-Crate 1.3; update the frozen validation contract"
        )

    results: list[ExternalProfileResult] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="task26373-validator-") as raw:
        raw_dir = Path(raw)
        for view_name, crate_dir in (
            ("internal-complete", internal),
            ("review-reproduction", review),
        ):
            for profile_id in EXTERNAL_PROFILE_IDS:
                raw_report = raw_dir / f"{view_name}-{profile_id}.json"
                completed = subprocess.run(
                    [
                        str(executable),
                        "--no-interactive",
                        "--disable-color",
                        "validate",
                        "--metadata-only",
                        "--profile-identifier",
                        profile_id,
                        "--requirement-severity",
                        "required",
                        "--output-format",
                        "json",
                        "--output-file",
                        str(raw_report),
                        str(crate_dir),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                if not raw_report.is_file():
                    raw_report.write_text(
                        completed.stdout + "\n" + completed.stderr,
                        encoding="utf-8",
                    )
                raw_bytes = raw_report.read_bytes()
                if completed.returncode != 0:
                    raise SystemsPaperOpenScienceIntegrityError(
                        f"{profile_id} failed for {view_name}: "
                        f"{completed.stdout[-800:]} {completed.stderr[-800:]}"
                    )
                try:
                    raw_payload = json.loads(raw_bytes)
                except json.JSONDecodeError as exc:
                    raise SystemsPaperOpenScienceIntegrityError(
                        f"{profile_id} emitted non-JSON validation output"
                    ) from exc
                if raw_payload.get("passed") is not True:
                    raise SystemsPaperOpenScienceIntegrityError(
                        f"{profile_id} did not report passed=true for {view_name}"
                    )
                relative = f"validation/external/{view_name}-{profile_id}.json"
                persisted = output_dir.parent.parent / relative
                text = raw_bytes.decode("utf-8", errors="replace")
                persisted.parent.mkdir(parents=True, exist_ok=True)
                persisted.write_text(
                    _sanitize_validator_text(text, crate_dir, executable),
                    encoding="utf-8",
                    newline="\n",
                )
                results.append(
                    ExternalProfileResult(
                        view=cast(
                            Literal["internal-complete", "review-reproduction"],
                            view_name,
                        ),
                        profile_id=profile_id,
                        raw_report_sha256=hashlib.sha256(raw_bytes).hexdigest(),
                        persisted_report_sha256=_file_sha256(persisted),
                        report_relative_path=relative,
                    )
                )
    payload = {
        "schema_version": "task26373-profile-validation-v1",
        "validator_name": "rocrate-validator",
        "validator_version": package_version.stdout.strip(),
        "validator_cli_version_observation": version.stdout.strip(),
        "external_validation_performed": True,
        "externally_validated_profiles": sorted(EXTERNAL_PROFILE_IDS),
        "results": sorted(results, key=lambda item: (item.view, item.profile_id)),
        "internal_ro_crate_1_3_contract_passed": True,
        "external_ro_crate_1_3_profile_available": False,
        "external_ro_crate_1_3_limitation": ("validator-0.11.3-profiles-stop-at-ro-crate-1.2"),
        "metadata_interoperability_only": True,
        "scientific_confirmation_performed": False,
    }
    return ProfileValidationReport.model_validate(_addressed(payload, "profile_validation_hash"))


def _overlay_schemas() -> dict[str, dict[str, Any]]:
    models = (
        StandardSourceSnapshot,
        StandardSourceRegistry,
        ClaimTraceRecord,
        ProvenanceQueryReport,
        ReconstructionReport,
        ExternalProfileResult,
        ProfileValidationReport,
        OpenScienceOverlayReport,
        OpenScienceOverlayManifest,
    )
    return {model.__name__: model.model_json_schema() for model in models}


def _file_records(root: Path) -> list[FileRecord]:
    records = [
        FileRecord(
            relative_path=path.relative_to(root).as_posix(),
            sha256=_file_sha256(path),
            byte_count=path.stat().st_size,
        )
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != MANIFEST_FILENAME
    ]
    return sorted(records, key=lambda item: item.relative_path)


def _write_manifest(
    root: Path,
    report_hash: str,
) -> OpenScienceOverlayManifest:
    records = _file_records(root)
    payload = {
        "schema_version": "task26373-open-science-overlay-manifest-v1",
        "task_id": TASK_ID,
        "package_id": PACKAGE_ID,
        "report_hash": report_hash,
        "files": records,
        "file_count": len(records),
    }
    manifest = OpenScienceOverlayManifest.model_validate(_addressed(payload, "manifest_hash"))
    _write_json(root / MANIFEST_FILENAME, manifest.model_dump(mode="json"))
    return manifest


def render_open_science_overlay_markdown(report: OpenScienceOverlayReport) -> str:
    """Render the human-facing boundary and verification summary."""

    return "\n".join(
        [
            "# Task 263.7.3 - interoperable Open Science overlay",
            "",
            f"- Package: `{report.package_id}`",
            f"- Immutable parent hash: `{report.parent_package_hash}`",
            f"- Provenance bundle: `{report.provenance_bundle_hash}`",
            f"- Report hash: `{report.report_hash}`",
            f"- Parent files reconstructed byte-for-byte: `{report.parent_file_count}`",
            (
                "- External required-profile validation complete: "
                f"`{str(report.external_profile_validation_complete).lower()}`"
            ),
            "- Public view, release, and submission: `false`",
            "",
            "## What this closes",
            "",
            (
                "The internal view retains every Task 260 file and original hash. The review "
                "view exposes only sanitized, rights-labelled evidence. RO-Crate 1.3, Workflow "
                "Run Crate, and PROV-O connect software, inputs, outputs, actions, claims, "
                "counterevidence, limitations, decisions, and both Route A negative results."
            ),
            "",
            "## What this does not close",
            "",
            (
                "Metadata validation and byte reconstruction do not rerun the scientific "
                "experiment, create independent tasks, establish a method effect, provide "
                "peer review, choose authors or licenses, authorize release, or submit a paper."
            ),
            "",
            "## Validator boundary",
            "",
            (
                "rocrate-validator 0.11.3 validates the required Workflow RO-Crate 1.0 and "
                "Process/Workflow/Provenance Run Crate 0.5 profiles. Its bundled base profiles "
                "stop at RO-Crate 1.2, so the RO-Crate 1.3 contract is checked against the "
                "official 1.3 specification by the exporter and is not misreported as an "
                "external 1.3 validation."
            ),
            "",
            "## Next non-compensating gates",
            "",
            "1. Task 263.7.4: complete the independent human benchmark-validity census.",
            "2. Task 263.7.5: freeze an independently authored confirmation protocol.",
            "3. Task 263.7.6: execute the one-use external confirmation.",
            "4. Task 263.7.7: obtain the human publication decision.",
            "",
        ]
    )


def _make_report(
    *,
    built_at: datetime,
    parent: ParentSystemsPaperEvidence,
    dependencies: tuple[Any, Any, Any, Any, Any, Any],
    bundle: ProvenanceBundle,
    registry: StandardSourceRegistry,
    query: ProvenanceQueryReport,
    reconstruction: ReconstructionReport,
    profile: ProfileValidationReport,
    export: OpenScienceExport,
    parent_file_count: int,
) -> OpenScienceOverlayReport:
    audit, audit_manifest, reanalysis, reanalysis_manifest, rewrite, rewrite_manifest = dependencies
    payload = {
        "schema_version": "task26373-open-science-overlay-report-v1",
        "task_id": TASK_ID,
        "package_id": PACKAGE_ID,
        "built_at": _require_utc(built_at, "built_at"),
        "parent_evidence_hash": parent.parent_evidence_hash,
        "parent_package_hash": parent.package_hash,
        "audit_report_hash": audit.report_hash,
        "audit_manifest_hash": audit_manifest.manifest_hash,
        "reanalysis_report_hash": reanalysis.report_hash,
        "reanalysis_manifest_hash": reanalysis_manifest.manifest_hash,
        "rewrite_report_hash": rewrite.report_hash,
        "rewrite_manifest_hash": rewrite_manifest.manifest_hash,
        "provenance_bundle_hash": bundle.bundle_hash,
        "source_registry_hash": registry.registry_hash,
        "provenance_query_hash": query.query_hash,
        "reconstruction_hash": reconstruction.reconstruction_hash,
        "profile_validation_hash": profile.profile_validation_hash,
        "internal_hash_manifest_sha256": export.internal.hash_manifest_sha256,
        "review_hash_manifest_sha256": export.review.hash_manifest_sha256,
        "parent_file_count": parent_file_count,
        "internal_artifact_count": export.internal.artifact_count,
        "review_artifact_count": export.review.artifact_count,
        "external_profile_validation_complete": profile.external_validation_performed,
        "profiles": sorted(
            [
                PROCESS_RUN_PROFILE,
                PROVENANCE_RUN_PROFILE,
                PROV_O_PROFILE,
                RO_CRATE_PROFILE,
                WORKFLOW_RO_CRATE_PROFILE,
                WORKFLOW_RUN_PROFILE,
            ]
        ),
        "internal_view_complete": True,
        "review_view_sanitized": True,
        "public_view_created": False,
        "publication_performed": False,
        "metadata_interoperability_only": True,
        "independent_confirmation_complete": False,
        "scientific_confirmation_added": False,
        "publication_ready": False,
        "independent_human_review_complete": False,
        "public_release_authorized": False,
        "external_submission_authorized": False,
        "next_required_tasks": ["263.7.4", "263.7.5", "263.7.6", "263.7.7"],
    }
    return OpenScienceOverlayReport.model_validate(_addressed(payload, "report_hash"))


def execute_systems_paper_open_science_overlay(
    *,
    parent_package_dir: Path | str,
    audit_dir: Path | str,
    reanalysis_dir: Path | str,
    rewrite_dir: Path | str,
    output_dir: Path | str,
    built_at: datetime | None = None,
    fetcher: StandardSourceFetcher = fetch_source_response,
    validator_executable: Path | str | None = None,
) -> tuple[OpenScienceOverlayReport, OpenScienceOverlayManifest]:
    """Build and atomically install the Task 263.7.3 research object."""

    parent_dir = Path(parent_package_dir).resolve()
    audit_path = Path(audit_dir).resolve()
    reanalysis_path = Path(reanalysis_dir).resolve()
    rewrite_path = Path(rewrite_dir).resolve()
    output = Path(output_dir).resolve()
    if (output / MANIFEST_FILENAME).is_file():
        return load_systems_paper_open_science_overlay(output)
    if output.exists() and any(output.iterdir()):
        raise SystemsPaperOpenScienceIntegrityError(
            "partial overlay output requires manual inspection"
        )
    timestamp = _require_utc(
        built_at or datetime.now(timezone.utc),
        "built_at",
    )
    (
        audit,
        audit_manifest,
        reanalysis,
        reanalysis_manifest,
        rewrite,
        rewrite_manifest,
        parent_before,
    ) = _assert_dependencies(
        parent_dir,
        audit_path,
        reanalysis_path,
        rewrite_path,
    )
    staging = output.parent / f".{output.name}.building-{uuid.uuid4().hex}"
    staging.mkdir(parents=True)
    try:
        registry = fetch_standard_source_registry(
            output_dir=staging,
            retrieved_at=timestamp,
            fetcher=fetcher,
        )
        bundle = build_systems_paper_open_science_provenance(
            parent_dir=parent_dir,
            audit_dir=audit_path,
            reanalysis_dir=reanalysis_path,
            rewrite_dir=rewrite_path,
            built_at=timestamp,
        )
        query = run_systems_paper_provenance_queries(bundle)
        _write_json(staging / QUERY_FILENAME, query.model_dump(mode="json"))
        artifacts, assertions, parent_file_count = build_systems_paper_open_science_artifacts(
            parent_dir=parent_dir,
            audit_dir=audit_path,
            reanalysis_dir=reanalysis_path,
            rewrite_dir=rewrite_path,
            staging_dir=staging,
        )
        metadata = ResearchObjectMetadata(
            identifier="urn:autoresearch:task26373:task260-open-science-overlay-v1",
            title="Task 260 immutable paper object with interoperable evidence overlay",
            description=(
                "An unreleased internal/review research object that preserves Task 260, "
                "its audit, task-unit correction, negative results, limitations, and current "
                "manuscript. Metadata interoperability is not scientific confirmation."
            ),
            version="1.0.0",
            publisher="Local AutoResearch workspace (unreleased)",
            published_at=timestamp,
            license_id="LicenseRef-Internal-Research",
            repository_url=("https://github.com/neutronstar238/ai-researcher-loop"),
            commit_sha=BASE_COMMIT,
            contributors=(
                Contributor(
                    family_names=("AutoResearch system (software agent; not a manuscript author)"),
                    roles=("Data curation", "Software", "Validation"),
                    affiliation="Local AutoResearch workspace",
                ),
            ),
            keywords=(
                "negative results",
                "open science",
                "PROV-O",
                "RO-Crate",
                "workflow provenance",
            ),
        )
        export = export_open_science_research_object(
            export_dir=staging / "open-science",
            bundle=bundle,
            metadata=metadata,
            artifacts=artifacts,
            reproduction_assertions=assertions,
            created_at=timestamp,
        )
        if export.public is not None or (staging / "open-science/public").exists():
            raise SystemsPaperOpenScienceIntegrityError(
                "public view was created without human approval"
            )
        review_validation = validate_open_science_view(
            export.review.crate_dir,
            view=ResearchObjectView.REVIEW,
        )
        if review_validation.status != "passed" or not all(review_validation.checks.values()):
            raise SystemsPaperOpenScienceIntegrityError(
                "review view failed a required internal validation"
            )
        review_text = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in Path(export.review.crate_dir).rglob("*")
            if path.is_file()
        )
        if any(pattern.search(review_text) for pattern in _PRIVATE_PATH_PATTERNS):
            raise SystemsPaperOpenScienceIntegrityError(
                "review view leaked a private absolute path"
            )
        reconstruction = run_exact_task260_reconstruction(
            parent_dir=parent_dir,
            internal_crate_dir=Path(export.internal.crate_dir),
            review_crate_dir=Path(export.review.crate_dir),
            work_root=output.parent,
            parent=parent_before,
        )
        _write_json(
            staging / RECONSTRUCTION_FILENAME,
            reconstruction.model_dump(mode="json"),
        )
        profile = run_external_profile_validation(
            output_dir=staging / "validation/external",
            export=export,
            validator_executable=(
                Path(validator_executable) if validator_executable is not None else None
            ),
        )
        _write_json(
            staging / PROFILE_VALIDATION_FILENAME,
            profile.model_dump(mode="json"),
        )
        _write_json(staging / SCHEMAS_FILENAME, _overlay_schemas())
        report = _make_report(
            built_at=timestamp,
            parent=parent_before,
            dependencies=(
                audit,
                audit_manifest,
                reanalysis,
                reanalysis_manifest,
                rewrite,
                rewrite_manifest,
            ),
            bundle=bundle,
            registry=registry,
            query=query,
            reconstruction=reconstruction,
            profile=profile,
            export=export,
            parent_file_count=parent_file_count,
        )
        _write_json(staging / REPORT_FILENAME, report.model_dump(mode="json"))
        (staging / MARKDOWN_FILENAME).write_text(
            render_open_science_overlay_markdown(report),
            encoding="utf-8",
            newline="\n",
        )
        _write_manifest(staging, report.report_hash)
        parent_after = ParentSystemsPaperEvidence.from_package(parent_dir)
        if parent_after != parent_before:
            raise SystemsPaperOpenScienceIntegrityError(
                "immutable Task 260 parent changed during overlay construction"
            )
        if output.exists():
            output.rmdir()
        os.replace(staging, output)
        return load_systems_paper_open_science_overlay(output)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def load_systems_paper_open_science_overlay(
    output_dir: Path | str,
) -> tuple[OpenScienceOverlayReport, OpenScienceOverlayManifest]:
    """Load and recursively verify a persisted Task 263.7.3 package."""

    root = Path(output_dir).resolve()
    manifest_path = root / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise SystemsPaperOpenScienceIntegrityError("overlay manifest is missing")
    manifest_payload = _read_json(manifest_path)
    _validate_addressed(manifest_payload, "manifest_hash", label="overlay manifest")
    manifest = OpenScienceOverlayManifest.model_validate(manifest_payload)
    listed = {item.relative_path: item for item in manifest.files}
    observed = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != MANIFEST_FILENAME
    }
    if observed != set(listed):
        raise SystemsPaperOpenScienceIntegrityError(
            f"overlay file set changed: missing={sorted(set(listed)-observed)}, "
            f"extra={sorted(observed-set(listed))}"
        )
    for relative, record in listed.items():
        path = root / relative
        if path.stat().st_size != record.byte_count or _file_sha256(path) != record.sha256:
            raise SystemsPaperOpenScienceIntegrityError(f"overlay file hash changed: {relative}")
    report_payload = _read_json(root / REPORT_FILENAME)
    _validate_addressed(report_payload, "report_hash", label="overlay report")
    report = OpenScienceOverlayReport.model_validate(report_payload)
    if report.report_hash != manifest.report_hash:
        raise SystemsPaperOpenScienceIntegrityError("overlay report and manifest hashes disagree")
    registry = StandardSourceRegistry.model_validate(_read_json(root / SOURCE_REGISTRY_FILENAME))
    query = ProvenanceQueryReport.model_validate(_read_json(root / QUERY_FILENAME))
    reconstruction = ReconstructionReport.model_validate(_read_json(root / RECONSTRUCTION_FILENAME))
    profile = ProfileValidationReport.model_validate(_read_json(root / PROFILE_VALIDATION_FILENAME))
    if (
        registry.registry_hash != report.source_registry_hash
        or query.query_hash != report.provenance_query_hash
        or reconstruction.reconstruction_hash != report.reconstruction_hash
        or profile.profile_validation_hash != report.profile_validation_hash
    ):
        raise SystemsPaperOpenScienceIntegrityError(
            "overlay component hash differs from report binding"
        )
    internal = root / "open-science/internal-complete"
    review = root / "open-science/review-reproduction"
    if validate_open_science_view(internal, view=ResearchObjectView.INTERNAL).status != "passed":
        raise SystemsPaperOpenScienceIntegrityError("internal crate no longer validates")
    if validate_open_science_view(review, view=ResearchObjectView.REVIEW).status != "passed":
        raise SystemsPaperOpenScienceIntegrityError("review crate no longer validates")
    if (root / "open-science/public").exists():
        raise SystemsPaperOpenScienceIntegrityError("unexpected public view exists")
    bundle = ProvenanceBundle.load_json(internal / "internal/provenance-bundle.json")
    if bundle.bundle_hash != report.provenance_bundle_hash:
        raise SystemsPaperOpenScienceIntegrityError(
            "persisted provenance bundle hash differs from report"
        )
    embedded_parent = ParentSystemsPaperEvidence.from_package(
        internal / "payload/task260-final-paper-v2"
    )
    if embedded_parent.parent_evidence_hash != report.parent_evidence_hash:
        raise SystemsPaperOpenScienceIntegrityError(
            "embedded Task 260 parent binding differs from report"
        )
    for result in profile.results:
        profile_path = root / result.report_relative_path
        if _file_sha256(profile_path) != result.persisted_report_sha256:
            raise SystemsPaperOpenScienceIntegrityError(
                f"external profile report changed: {result.report_relative_path}"
            )
    return report, manifest


__all__ = [
    "EXTERNAL_PROFILE_IDS",
    "MANIFEST_FILENAME",
    "OpenScienceOverlayManifest",
    "OpenScienceOverlayReport",
    "PACKAGE_ID",
    "ProfileValidationReport",
    "ProvenanceQueryReport",
    "ReconstructionReport",
    "StandardSourceDefinition",
    "StandardSourceRegistry",
    "SourceResponse",
    "SystemsPaperOpenScienceIntegrityError",
    "TASK_ID",
    "build_systems_paper_open_science_artifacts",
    "build_systems_paper_open_science_provenance",
    "execute_systems_paper_open_science_overlay",
    "fetch_standard_source_registry",
    "load_systems_paper_open_science_overlay",
    "render_open_science_overlay_markdown",
    "run_exact_task260_reconstruction",
    "run_external_profile_validation",
    "run_systems_paper_provenance_queries",
    "standard_source_definitions",
]
