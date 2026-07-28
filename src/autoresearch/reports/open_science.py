"""Validated, approval-gated Open Science research-object exports.

This module adds interoperable projections beside the existing reproducibility
package.  It deliberately does not reinterpret scientific outcomes, mint
identifiers, publish artifacts, or claim that metadata validation reproduces an
experiment.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

from autoresearch.kernel.provenance import (
    Activity,
    Agent,
    Association,
    Counterevidence,
    Decision,
    Derivation,
    Entity,
    Evidence,
    Generation,
    Plan,
    ProvenanceBundle,
    Usage,
)
from autoresearch.schemas import file_hash

RO_CRATE_CONTEXT = "https://w3id.org/ro/crate/1.3/context"
RO_CRATE_PROFILE = "https://w3id.org/ro/crate/1.3"
RO_CRATE_WRROC_BASE_PROFILE = "https://w3id.org/ro/crate/1.1"
WRROC_CONTEXT = "https://w3id.org/ro/terms/workflow-run/context"
PROCESS_RUN_PROFILE = "https://w3id.org/ro/wfrun/process/0.5"
WORKFLOW_RUN_PROFILE = "https://w3id.org/ro/wfrun/workflow/0.5"
PROVENANCE_RUN_PROFILE = "https://w3id.org/ro/wfrun/provenance/0.5"
WORKFLOW_RO_CRATE_PROFILE = "https://w3id.org/workflowhub/workflow-ro-crate/1.0"
BIOSCHEMAS_COMPUTATIONAL_WORKFLOW_PROFILE = (
    "https://bioschemas.org/profiles/ComputationalWorkflow/1.0-RELEASE"
)
REPRODUCTION_PLAN_PROFILE = (
    "urn:autoresearch:profile:clean-directory-reproduction-plan:1"
)
CODEMETA_CONTEXT = "https://w3id.org/codemeta/3.1"
SPDX_CONTEXT = "https://spdx.org/rdf/3.0.1/spdx-context.jsonld"
SLSA_PREDICATE = "https://slsa.dev/provenance/v1"
IN_TOTO_STATEMENT = "https://in-toto.io/Statement/v1"
PROV_CONTEXT = "http://www.w3.org/ns/prov#"

PROFILE_VERSIONS = {
    "ro_crate": "1.3",
    "workflow_run_ro_crate": "0.5",
    "bioschemas_computational_workflow": "1.0-RELEASE",
    "codemeta": "3.1",
    "citation_cff": "1.2.0",
    "datacite": "4.7",
    "spdx": "3.0.1",
    "slsa": "1.2-format-v1",
    "fair4rs": "1.0",
}

CREDIT_ROLE_URIS = {
    "Conceptualization": "https://credit.niso.org/contributor-roles/conceptualization/",
    "Data curation": "https://credit.niso.org/contributor-roles/data-curation/",
    "Formal analysis": "https://credit.niso.org/contributor-roles/formal-analysis/",
    "Funding acquisition": "https://credit.niso.org/contributor-roles/funding-acquisition/",
    "Investigation": "https://credit.niso.org/contributor-roles/investigation/",
    "Methodology": "https://credit.niso.org/contributor-roles/methodology/",
    "Project administration": (
        "https://credit.niso.org/contributor-roles/project-administration/"
    ),
    "Resources": "https://credit.niso.org/contributor-roles/resources/",
    "Software": "https://credit.niso.org/contributor-roles/software/",
    "Supervision": "https://credit.niso.org/contributor-roles/supervision/",
    "Validation": "https://credit.niso.org/contributor-roles/validation/",
    "Visualization": "https://credit.niso.org/contributor-roles/visualization/",
    "Writing – original draft": (
        "https://credit.niso.org/contributor-roles/writing-original-draft/"
    ),
    "Writing – review & editing": (
        "https://credit.niso.org/contributor-roles/writing-review-editing/"
    ),
}

PUBLIC_LICENSE_IDS = frozenset(
    {
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "CC-BY-4.0",
        "CC0-1.0",
        "MIT",
        "MPL-2.0",
    }
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
_ORCID_RE = re.compile(r"^https://orcid\.org/\d{4}-\d{4}-\d{4}-[\dX]{4}$")
_SWHID_RE = re.compile(r"^swh:1:rev:([0-9a-f]{40})$")
_HTTP_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)
_WRROC_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}\+\d{2}:\d{2}$"
)
_WINDOWS_PATH_RE = re.compile(r"(?i)(?:^|[\s\"'=])([a-z]:[\\/][^\s\"']+)")
_POSIX_PRIVATE_PATH_RE = re.compile(
    r"(?:^|[\s\"'=])((?:/home/|/users/|/root/)[^\s\"']+)",
    re.IGNORECASE,
)
_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:api[_-]?key|password|private[_-]?key|secret|token)\s*[:=]\s*\S+"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}\b"),
)
_SECRET_NAME_FRAGMENTS = (
    ".env",
    "credential",
    "id_rsa",
    "private_key",
    "secret",
    "token",
)
_GENERATED_CRATE_PATHS = frozenset(
    {
        "README.md",
        "export-policy.json",
        "internal/provenance-bundle.json",
        "manifest-sha256.json",
        "metadata/CITATION.cff",
        "metadata/codemeta.json",
        "metadata/contributions.json",
        "metadata/datacite-4.7-draft.json",
        "provenance/prov.jsonld",
        "reproduction/reproduce.py",
        "reproduction/reproduction-plan.json",
        "reproduction/reproduction-result.json",
        "ro-crate-metadata.json",
        "supply-chain/attestation-policy.json",
        "supply-chain/slsa-provenance.json",
        "supply-chain/spdx-3.0.1-sbom.jsonld",
        "validation-report.json",
        "workflow/workflow.json",
    }
)
_GENERATED_CRATE_PATH_KEYS = frozenset(
    path.casefold() for path in _GENERATED_CRATE_PATHS
)


class OpenScienceExportError(ValueError):
    """Raised when an Open Science export cannot be safely produced."""


class ResearchObjectView(str, Enum):
    """Visibility boundary for one materialized research object."""

    INTERNAL = "internal-complete"
    REVIEW = "review-reproduction"
    PUBLIC = "public"


class ArtifactAccess(str, Enum):
    """Most permissive view in which an artifact may appear."""

    INTERNAL = "internal"
    REVIEW = "review"
    PUBLIC = "public"


class ArtifactTransform(str, Enum):
    """Allowed deterministic transformations for copied artifacts."""

    COPY = "copy"
    SANITIZE_JSON = "sanitize_json"


class ValidationSeverity(str, Enum):
    """Severity of a research-object validation issue."""

    WARNING = "warning"
    FAILED = "failed"


@dataclass(frozen=True)
class Contributor:
    """One contributor with explicit CRediT roles."""

    family_names: str
    given_names: str = ""
    roles: tuple[str, ...] = ()
    orcid: str | None = None
    affiliation: str | None = None

    @property
    def display_name(self) -> str:
        """Return a stable human-readable contributor name."""

        return " ".join(
            part.strip() for part in (self.given_names, self.family_names) if part.strip()
        )


@dataclass(frozen=True)
class ResearchObjectMetadata:
    """Metadata shared consistently across all export formats."""

    identifier: str
    title: str
    description: str
    version: str
    publisher: str
    published_at: datetime
    license_id: str
    repository_url: str
    commit_sha: str
    contributors: tuple[Contributor, ...]
    keywords: tuple[str, ...] = ()
    doi: str | None = None
    swhid: str | None = None
    programming_language: str = "Python"
    runtime_platform: str = "Python 3.10+"


@dataclass(frozen=True)
class ResearchObjectArtifact:
    """One source file plus its license and visibility policy."""

    source_path: Path | str
    crate_path: str
    role: str
    media_type: str
    license_id: str
    access: ArtifactAccess
    provenance_entity_id: str | None = None
    expected_sha256: str | None = None
    transform: ArtifactTransform = ArtifactTransform.COPY
    description: str = ""


@dataclass(frozen=True)
class JsonAssertion:
    """One deterministic assertion run by the clean-directory verifier."""

    crate_path: str
    json_pointer: str
    expected: Any
    label: str


@dataclass(frozen=True)
class PublicationApproval:
    """Explicit human approval scoped to one public research object."""

    approval_id: str
    approver: str
    approved_at: datetime
    scope_identifier: str


@dataclass(frozen=True)
class OpenScienceValidationIssue:
    """One profile, consistency, privacy, or integrity finding."""

    check: str
    message: str
    severity: ValidationSeverity
    path: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        """Serialize a validation issue."""

        return {
            "check": self.check,
            "message": self.message,
            "severity": self.severity.value,
            "path": self.path,
        }


@dataclass(frozen=True)
class OpenScienceValidation:
    """Validation report for one materialized research-object view."""

    view: ResearchObjectView
    status: str
    checks: Mapping[str, bool]
    issues: tuple[OpenScienceValidationIssue, ...]
    checked_files: int
    metadata_interoperability_only: bool = True
    scientific_experiment_reexecuted: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize a validation report."""

        return {
            "view": self.view.value,
            "status": self.status,
            "checks": dict(sorted(self.checks.items())),
            "issues": [issue.to_dict() for issue in self.issues],
            "checked_files": self.checked_files,
            "metadata_interoperability_only": self.metadata_interoperability_only,
            "scientific_experiment_reexecuted": self.scientific_experiment_reexecuted,
        }


@dataclass(frozen=True)
class ResearchObjectViewResult:
    """Paths and digest for one validated view."""

    view: ResearchObjectView
    crate_dir: str
    validation_path: str
    hash_manifest_path: str
    hash_manifest_sha256: str
    artifact_count: int

    def to_dict(self) -> dict[str, Any]:
        """Serialize one materialized view result."""

        return {
            "view": self.view.value,
            "crate_dir": self.crate_dir,
            "validation_path": self.validation_path,
            "hash_manifest_path": self.hash_manifest_path,
            "hash_manifest_sha256": self.hash_manifest_sha256,
            "artifact_count": self.artifact_count,
        }


@dataclass(frozen=True)
class CleanReproductionResult:
    """Result of the isolated, standard-library-only reproduction check."""

    status: str
    clean_dir: str
    assertion_count: int
    checked_files: int
    result_path: str
    scientific_experiment_reexecuted: bool

    def to_dict(self) -> dict[str, Any]:
        """Serialize the clean-directory check result."""

        return {
            "status": self.status,
            "clean_dir": self.clean_dir,
            "assertion_count": self.assertion_count,
            "checked_files": self.checked_files,
            "result_path": self.result_path,
            "scientific_experiment_reexecuted": (
                self.scientific_experiment_reexecuted
            ),
        }


@dataclass(frozen=True)
class OpenScienceExport:
    """Complete local export result without any publication side effect."""

    export_dir: str
    bundle_hash: str
    internal: ResearchObjectViewResult
    review: ResearchObjectViewResult
    public: ResearchObjectViewResult | None
    public_blocked_reasons: tuple[str, ...]
    summary_path: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize an export result."""

        return {
            "export_dir": self.export_dir,
            "bundle_hash": self.bundle_hash,
            "internal": self.internal.to_dict(),
            "review": self.review.to_dict(),
            "public": self.public.to_dict() if self.public is not None else None,
            "public_blocked_reasons": list(self.public_blocked_reasons),
            "summary_path": self.summary_path,
            "profile_versions": PROFILE_VERSIONS,
            "publication_performed": False,
        }


@dataclass(frozen=True)
class _MaterializedArtifact:
    source_path: str
    crate_path: str
    role: str
    media_type: str
    license_id: str
    provenance_entity_id: str | None
    original_sha256: str
    exported_sha256: str
    size_bytes: int
    transform: ArtifactTransform
    description: str


def export_open_science_research_object(
    *,
    export_dir: Path | str,
    bundle: ProvenanceBundle,
    metadata: ResearchObjectMetadata,
    artifacts: Sequence[ResearchObjectArtifact],
    reproduction_assertions: Sequence[JsonAssertion],
    publication_approval: PublicationApproval | None = None,
    created_at: datetime | None = None,
) -> OpenScienceExport:
    """Create validated internal/review views and an approval-gated public view."""

    bundle.verify_integrity()
    _validate_metadata(metadata)
    _validate_artifact_inputs(artifacts)
    _validate_assertions(reproduction_assertions, artifacts)
    timestamp = _require_utc(created_at or datetime.now(timezone.utc), "created_at")

    target = Path(export_dir)
    if target.exists():
        raise OpenScienceExportError(f"export directory already exists: {target}")
    target.mkdir(parents=True)

    internal = _build_view(
        target / ResearchObjectView.INTERNAL.value,
        ResearchObjectView.INTERNAL,
        bundle,
        metadata,
        artifacts,
        reproduction_assertions,
        timestamp,
        publication_approval=None,
    )
    review = _build_view(
        target / ResearchObjectView.REVIEW.value,
        ResearchObjectView.REVIEW,
        bundle,
        metadata,
        artifacts,
        reproduction_assertions,
        timestamp,
        publication_approval=None,
    )

    blocked = _public_gate_reasons(metadata, artifacts, publication_approval)
    public: ResearchObjectViewResult | None = None
    if not blocked:
        if publication_approval is None:
            raise AssertionError("public approval gate reported success without approval")
        public = _build_view(
            target / ResearchObjectView.PUBLIC.value,
            ResearchObjectView.PUBLIC,
            bundle,
            metadata,
            artifacts,
            reproduction_assertions,
            timestamp,
            publication_approval=publication_approval,
        )

    summary_path = target / "export-summary.json"
    result = OpenScienceExport(
        export_dir=target.resolve().as_posix(),
        bundle_hash=bundle.bundle_hash,
        internal=internal,
        review=review,
        public=public,
        public_blocked_reasons=tuple(blocked),
        summary_path=summary_path.resolve().as_posix(),
    )
    _write_json(summary_path, result.to_dict())
    return result


def validate_open_science_view(
    crate_dir: Path | str,
    *,
    view: ResearchObjectView | None = None,
) -> OpenScienceValidation:
    """Validate profiles, hashes, metadata consistency, and visibility policy."""

    root = Path(crate_dir)
    issues: list[OpenScienceValidationIssue] = []
    checks: dict[str, bool] = {}
    policy = _load_json_checked(root / "export-policy.json", issues, "export_policy")
    inferred_view = view
    if inferred_view is None and isinstance(policy, dict):
        raw_view = policy.get("view")
        try:
            inferred_view = ResearchObjectView(str(raw_view))
        except ValueError:
            inferred_view = None
    if inferred_view is None:
        inferred_view = ResearchObjectView.REVIEW
        issues.append(
            OpenScienceValidationIssue(
                "view_identity",
                "export-policy.json does not declare a supported view",
                ValidationSeverity.FAILED,
                "export-policy.json",
            )
        )

    required_files = (
        "README.md",
        "ro-crate-metadata.json",
        "provenance/prov.jsonld",
        "workflow/workflow.json",
        "metadata/codemeta.json",
        "metadata/CITATION.cff",
        "metadata/contributions.json",
        "metadata/datacite-4.7-draft.json",
        "supply-chain/spdx-3.0.1-sbom.jsonld",
        "supply-chain/slsa-provenance.json",
        "supply-chain/attestation-policy.json",
        "reproduction/reproduction-plan.json",
        "reproduction/reproduce.py",
        "export-policy.json",
    )
    missing = [relative for relative in required_files if not (root / relative).is_file()]
    checks["required_files"] = not missing
    for relative in missing:
        issues.append(
            OpenScienceValidationIssue(
                "required_file",
                f"required export file is missing: {relative}",
                ValidationSeverity.FAILED,
                relative,
            )
        )

    crate = _load_json_checked(
        root / "ro-crate-metadata.json", issues, "ro_crate_json"
    )
    checks["ro_crate_1_3"] = _validate_ro_crate(root, crate, issues)

    prov = _load_json_checked(
        root / "provenance/prov.jsonld", issues, "prov_jsonld"
    )
    checks["prov_jsonld"] = _validate_prov_jsonld(prov, issues)

    codemeta = _load_json_checked(
        root / "metadata/codemeta.json", issues, "codemeta_json"
    )
    contributions = _load_json_checked(
        root / "metadata/contributions.json", issues, "contributions_json"
    )
    datacite = _load_json_checked(
        root / "metadata/datacite-4.7-draft.json", issues, "datacite_json"
    )
    cff = _load_yaml_checked(root / "metadata/CITATION.cff", issues)
    checks["metadata_consistency"] = _validate_metadata_consistency(
        crate,
        codemeta,
        cff,
        contributions,
        datacite,
        issues,
    )

    spdx = _load_json_checked(
        root / "supply-chain/spdx-3.0.1-sbom.jsonld",
        issues,
        "spdx_jsonld",
    )
    slsa = _load_json_checked(
        root / "supply-chain/slsa-provenance.json",
        issues,
        "slsa_json",
    )
    attestation = _load_json_checked(
        root / "supply-chain/attestation-policy.json",
        issues,
        "attestation_policy",
    )
    checks["spdx_3_0_1"] = _validate_spdx(spdx, issues)
    checks["slsa_v1"] = _validate_slsa(root, slsa, attestation, issues)

    checks["sensitive_content"] = _scan_sensitive_content(
        root, inferred_view, issues
    )
    checks["publication_gate"] = _validate_view_policy(
        policy, inferred_view, issues
    )
    checks["hash_manifest"] = _validate_hash_manifest(root, issues)

    failed = any(issue.severity is ValidationSeverity.FAILED for issue in issues)
    return OpenScienceValidation(
        view=inferred_view,
        status="failed" if failed else "passed",
        checks=checks,
        issues=tuple(issues),
        checked_files=sum(1 for path in root.rglob("*") if path.is_file()),
    )


def run_clean_directory_reproduction(
    crate_dir: Path | str,
    *,
    clean_dir: Path | str,
    python_executable: str | None = None,
) -> CleanReproductionResult:
    """Copy a review crate and run its pure-stdlib verifier in isolated mode."""

    source = Path(crate_dir)
    target = Path(clean_dir)
    if target.exists():
        raise OpenScienceExportError(
            f"clean reproduction directory already exists: {target}"
        )
    if not (source / "reproduction/reproduce.py").is_file():
        raise OpenScienceExportError("crate lacks reproduction/reproduce.py")
    shutil.copytree(source, target)
    result_relative = Path("reproduction/reproduction-result.json")
    completed = subprocess.run(
        [
            python_executable or sys.executable,
            "-I",
            "reproduction/reproduce.py",
            "--output",
            result_relative.as_posix(),
        ],
        cwd=target,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode != 0:
        raise OpenScienceExportError(
            "clean-directory verifier failed: "
            f"exit={completed.returncode}; stdout={completed.stdout.strip()}; "
            f"stderr={completed.stderr.strip()}"
        )
    result_path = target / result_relative
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    if payload.get("status") != "passed":
        raise OpenScienceExportError(
            f"clean-directory verifier returned {payload.get('status')!r}"
        )
    return CleanReproductionResult(
        status="passed",
        clean_dir=target.resolve().as_posix(),
        assertion_count=int(payload["assertion_count"]),
        checked_files=int(payload["checked_files"]),
        result_path=result_path.resolve().as_posix(),
        scientific_experiment_reexecuted=bool(
            payload["scientific_experiment_reexecuted"]
        ),
    )


def _build_view(
    root: Path,
    view: ResearchObjectView,
    bundle: ProvenanceBundle,
    metadata: ResearchObjectMetadata,
    artifacts: Sequence[ResearchObjectArtifact],
    assertions: Sequence[JsonAssertion],
    created_at: datetime,
    *,
    publication_approval: PublicationApproval | None,
) -> ResearchObjectViewResult:
    root.mkdir(parents=True)
    selected = [artifact for artifact in artifacts if _visible_in(artifact, view)]
    materialized = [
        _materialize_artifact(root, artifact, view) for artifact in selected
    ]

    if view is ResearchObjectView.INTERNAL:
        internal_bundle = root / "internal/provenance-bundle.json"
        bundle.save_json(internal_bundle)
        materialized.append(
            _materialized_generated_artifact(
                internal_bundle,
                root,
                role="internal_provenance",
                media_type="application/json",
                license_id="LicenseRef-Internal",
                description="Canonical internal provenance-v2 bundle; not public.",
            )
        )

    workflow_path = root / "workflow/workflow.json"
    _write_json(workflow_path, _workflow_document(bundle, metadata))
    prov_path = root / "provenance/prov.jsonld"
    _write_json(prov_path, _prov_jsonld(bundle))
    contributions_path = root / "metadata/contributions.json"
    _write_json(contributions_path, _contributions_document(metadata))
    codemeta_path = root / "metadata/codemeta.json"
    _write_json(codemeta_path, _codemeta_document(metadata))
    cff_path = root / "metadata/CITATION.cff"
    _write_yaml(cff_path, _citation_cff(metadata))
    datacite_path = root / "metadata/datacite-4.7-draft.json"
    _write_json(datacite_path, _datacite_document(metadata))
    readme_path = root / "README.md"
    readme_path.write_text(
        _readme_document(metadata, view),
        encoding="utf-8",
        newline="\n",
    )

    generated_for_supply_chain = [
        *materialized,
        _materialized_generated_artifact(
            workflow_path,
            root,
            role="workflow",
            media_type="application/json",
            license_id=metadata.license_id,
            description="Prospective workflow projection.",
        ),
        _materialized_generated_artifact(
            prov_path,
            root,
            role="provenance",
            media_type="application/ld+json",
            license_id=metadata.license_id,
            description="W3C PROV JSON-LD projection.",
        ),
        _materialized_generated_artifact(
            readme_path,
            root,
            role="readme",
            media_type="text/markdown",
            license_id=metadata.license_id,
            description="Reader-facing scope and reproduction guide.",
        ),
    ]
    spdx_path = root / "supply-chain/spdx-3.0.1-sbom.jsonld"
    _write_json(
        spdx_path,
        _spdx_document(metadata, generated_for_supply_chain, created_at),
    )
    slsa_path = root / "supply-chain/slsa-provenance.json"
    _write_json(
        slsa_path,
        _slsa_document(
            metadata,
            bundle,
            generated_for_supply_chain,
            view,
            created_at,
        ),
    )
    attestation_path = root / "supply-chain/attestation-policy.json"
    _write_json(
        attestation_path,
        {
            "schema_version": 1,
            "slsa_format": SLSA_PREDICATE,
            "signed": False,
            "slsa_level_claimed": None,
            "trusted_builder_claimed": False,
            "scientific_result_attestation": False,
            "scope": "local construction of this research-object view",
        },
    )
    policy_path = root / "export-policy.json"
    _write_json(
        policy_path,
        _export_policy(
            view,
            bundle,
            metadata,
            materialized,
            publication_approval,
            created_at,
        ),
    )

    reproduction_path = root / "reproduction/reproduction-plan.json"
    applicable_assertions = [
        assertion
        for assertion in assertions
        if any(
            artifact.crate_path == _safe_relative_path(assertion.crate_path)
            for artifact in selected
        )
    ]
    _write_json(
        reproduction_path,
        _reproduction_plan(materialized, applicable_assertions),
    )
    reproduce_path = root / "reproduction/reproduce.py"
    reproduce_path.parent.mkdir(parents=True, exist_ok=True)
    reproduce_path.write_text(_REPRODUCE_SCRIPT, encoding="utf-8", newline="\n")

    crate_path = root / "ro-crate-metadata.json"
    crate_materialized = [
        *materialized,
        *[
            _materialized_generated_artifact(
                path,
                root,
                role=role,
                media_type=media_type,
                license_id=metadata.license_id,
                description=description,
            )
            for path, role, media_type, description in (
                (
                    readme_path,
                    "readme",
                    "text/markdown",
                    "Reader-facing scope and reproduction guide.",
                ),
                (
                    workflow_path,
                    "workflow",
                    "application/json",
                    "Prospective workflow projection.",
                ),
                (
                    prov_path,
                    "provenance",
                    "application/ld+json",
                    "W3C PROV JSON-LD projection.",
                ),
                (
                    contributions_path,
                    "contributions",
                    "application/json",
                    "CRediT contributor-role metadata.",
                ),
                (
                    codemeta_path,
                    "software_metadata",
                    "application/ld+json",
                    "CodeMeta software metadata.",
                ),
                (
                    cff_path,
                    "citation",
                    "application/yaml",
                    "Citation File Format metadata.",
                ),
                (
                    datacite_path,
                    "identifier_metadata",
                    "application/json",
                    "DataCite 4.7 field-aligned draft.",
                ),
                (
                    spdx_path,
                    "sbom",
                    "application/ld+json",
                    "SPDX 3.0.1 SBOM and build metadata.",
                ),
                (
                    slsa_path,
                    "build_provenance",
                    "application/json",
                    "Unsigned SLSA v1-format export-build provenance.",
                ),
                (
                    attestation_path,
                    "attestation_policy",
                    "application/json",
                    "Truthful attestation scope and signature status.",
                ),
                (
                    policy_path,
                    "export_policy",
                    "application/json",
                    "Visibility and publication policy.",
                ),
                (
                    reproduction_path,
                    "reproduction_plan",
                    "application/json",
                    "Hash and decision-level reproduction plan.",
                ),
                (
                    reproduce_path,
                    "reproduction_code",
                    "text/x-python",
                    "Pure-standard-library clean-directory verifier.",
                ),
            )
        ],
    ]
    _write_json(
        crate_path,
        _ro_crate_document(
            bundle,
            metadata,
            crate_materialized,
            created_at,
        ),
    )

    preliminary = validate_open_science_view(root, view=view)
    validation_path = root / "validation-report.json"
    _write_json(validation_path, preliminary.to_dict())
    hash_manifest_path = root / "manifest-sha256.json"
    _write_hash_manifest(root, hash_manifest_path)
    final = validate_open_science_view(root, view=view)
    _write_json(validation_path, final.to_dict())
    if final.status != "passed":
        details = "; ".join(
            f"{issue.check}: {issue.message}"
            for issue in final.issues
            if issue.severity is ValidationSeverity.FAILED
        )
        raise OpenScienceExportError(
            f"{view.value} research object failed validation: {details}"
        )
    return ResearchObjectViewResult(
        view=view,
        crate_dir=root.resolve().as_posix(),
        validation_path=validation_path.resolve().as_posix(),
        hash_manifest_path=hash_manifest_path.resolve().as_posix(),
        hash_manifest_sha256=file_hash(hash_manifest_path),
        artifact_count=len(materialized),
    )


def _validate_metadata(metadata: ResearchObjectMetadata) -> None:
    required = {
        "identifier": metadata.identifier,
        "title": metadata.title,
        "description": metadata.description,
        "version": metadata.version,
        "publisher": metadata.publisher,
        "license_id": metadata.license_id,
        "repository_url": metadata.repository_url,
        "commit_sha": metadata.commit_sha,
    }
    missing = [name for name, value in required.items() if not value.strip()]
    if missing:
        raise OpenScienceExportError(
            f"research-object metadata fields cannot be empty: {', '.join(missing)}"
        )
    _require_utc(metadata.published_at, "published_at")
    if not metadata.contributors:
        raise OpenScienceExportError("at least one contributor is required")
    for contributor in metadata.contributors:
        if not contributor.family_names.strip():
            raise OpenScienceExportError("contributor family_names cannot be empty")
        if not contributor.roles:
            raise OpenScienceExportError(
                f"contributor {contributor.display_name} requires a CRediT role"
            )
        unknown = sorted(set(contributor.roles) - set(CREDIT_ROLE_URIS))
        if unknown:
            raise OpenScienceExportError(
                f"unknown CRediT roles for {contributor.display_name}: "
                f"{', '.join(unknown)}"
            )
        if contributor.orcid is not None and not _ORCID_RE.fullmatch(
            contributor.orcid
        ):
            raise OpenScienceExportError(
                f"invalid ORCID for {contributor.display_name}: {contributor.orcid}"
            )
    if metadata.doi is not None and not _DOI_RE.fullmatch(metadata.doi):
        raise OpenScienceExportError(f"invalid DOI: {metadata.doi}")
    if metadata.swhid is not None:
        match = _SWHID_RE.fullmatch(metadata.swhid)
        if match is None:
            raise OpenScienceExportError(f"invalid SWHID: {metadata.swhid}")
        if not metadata.commit_sha.startswith(match.group(1)):
            raise OpenScienceExportError(
                "SWHID revision digest must equal the declared Git commit"
            )
    if not _HTTP_URL_RE.fullmatch(metadata.repository_url):
        raise OpenScienceExportError(
            "repository_url must be an absolute HTTP(S) URL"
        )


def _validate_artifact_inputs(
    artifacts: Sequence[ResearchObjectArtifact],
) -> None:
    if not artifacts:
        raise OpenScienceExportError("at least one research-object artifact is required")
    path_keys: set[str] = set()
    for artifact in artifacts:
        source = Path(artifact.source_path)
        if not source.is_file():
            raise OpenScienceExportError(f"artifact source is missing: {source}")
        crate_path = _safe_relative_path(artifact.crate_path)
        crate_path_key = crate_path.casefold()
        if crate_path_key in path_keys:
            raise OpenScienceExportError(f"duplicate crate path: {crate_path}")
        path_keys.add(crate_path_key)
        if not artifact.license_id.strip():
            raise OpenScienceExportError(
                f"artifact {crate_path} requires an explicit license identifier"
            )
        if artifact.expected_sha256 is not None:
            if not _SHA256_RE.fullmatch(artifact.expected_sha256):
                raise OpenScienceExportError(
                    f"invalid expected sha256 for {crate_path}"
                )
            if file_hash(source) != artifact.expected_sha256:
                raise OpenScienceExportError(
                    f"source hash mismatch for {crate_path}"
                )


def _validate_assertions(
    assertions: Sequence[JsonAssertion],
    artifacts: Sequence[ResearchObjectArtifact],
) -> None:
    artifact_paths = {
        _safe_relative_path(artifact.crate_path): artifact for artifact in artifacts
    }
    for assertion in assertions:
        crate_path = _safe_relative_path(assertion.crate_path)
        artifact = artifact_paths.get(crate_path)
        if artifact is None:
            raise OpenScienceExportError(
                f"reproduction assertion references unknown artifact: {crate_path}"
            )
        if "json" not in artifact.media_type:
            raise OpenScienceExportError(
                f"reproduction assertion requires JSON artifact: {crate_path}"
            )
        if not assertion.json_pointer.startswith("/"):
            raise OpenScienceExportError(
                f"JSON pointer must begin with '/': {assertion.json_pointer}"
            )
        try:
            json.dumps(assertion.expected)
        except (TypeError, ValueError) as exc:
            raise OpenScienceExportError(
                f"assertion {assertion.label} expected value is not JSON serializable"
            ) from exc


def _materialize_artifact(
    root: Path,
    artifact: ResearchObjectArtifact,
    view: ResearchObjectView,
) -> _MaterializedArtifact:
    source = Path(artifact.source_path)
    relative = _safe_relative_path(artifact.crate_path)
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    original_digest = file_hash(source)
    if artifact.transform is ArtifactTransform.SANITIZE_JSON and view is not ResearchObjectView.INTERNAL:
        payload = json.loads(source.read_text(encoding="utf-8"))
        _write_json(target, _sanitize_json(payload))
    else:
        shutil.copy2(source, target)
    return _MaterializedArtifact(
        source_path=source.resolve().as_posix(),
        crate_path=relative,
        role=artifact.role,
        media_type=artifact.media_type,
        license_id=artifact.license_id,
        provenance_entity_id=artifact.provenance_entity_id,
        original_sha256=original_digest,
        exported_sha256=file_hash(target),
        size_bytes=target.stat().st_size,
        transform=(
            artifact.transform
            if view is not ResearchObjectView.INTERNAL
            else ArtifactTransform.COPY
        ),
        description=artifact.description,
    )


def _materialized_generated_artifact(
    path: Path,
    root: Path,
    *,
    role: str,
    media_type: str,
    license_id: str,
    description: str,
) -> _MaterializedArtifact:
    digest = file_hash(path)
    return _MaterializedArtifact(
        source_path="generated",
        crate_path=path.relative_to(root).as_posix(),
        role=role,
        media_type=media_type,
        license_id=license_id,
        provenance_entity_id=None,
        original_sha256=digest,
        exported_sha256=digest,
        size_bytes=path.stat().st_size,
        transform=ArtifactTransform.COPY,
        description=description,
    )


def _visible_in(
    artifact: ResearchObjectArtifact,
    view: ResearchObjectView,
) -> bool:
    if view is ResearchObjectView.INTERNAL:
        return True
    if view is ResearchObjectView.REVIEW:
        return artifact.access in {ArtifactAccess.REVIEW, ArtifactAccess.PUBLIC}
    return artifact.access is ArtifactAccess.PUBLIC


def _public_gate_reasons(
    metadata: ResearchObjectMetadata,
    artifacts: Sequence[ResearchObjectArtifact],
    approval: PublicationApproval | None,
) -> list[str]:
    reasons: list[str] = []
    if approval is None:
        reasons.append("explicit human publication approval is missing")
    else:
        if approval.scope_identifier != metadata.identifier:
            reasons.append("publication approval scope does not match object identifier")
        if not approval.approval_id.strip() or not approval.approver.strip():
            reasons.append("publication approval identity is incomplete")
        try:
            _require_utc(approval.approved_at, "publication approval timestamp")
        except OpenScienceExportError as exc:
            reasons.append(str(exc))
    public_artifacts = [
        artifact for artifact in artifacts if artifact.access is ArtifactAccess.PUBLIC
    ]
    if not public_artifacts:
        reasons.append("no artifact is explicitly approved for the public view")
    elif metadata.license_id not in PUBLIC_LICENSE_IDS:
        reasons.append(
            "research-object metadata lacks a public-compatible license"
        )
    for artifact in public_artifacts:
        if artifact.license_id not in PUBLIC_LICENSE_IDS:
            reasons.append(
                f"artifact {artifact.crate_path} lacks a public-compatible license"
            )
        findings = _scan_source_file(Path(artifact.source_path))
        if findings:
            reasons.append(
                f"artifact {artifact.crate_path} contains sensitive or private-path content"
            )
    return sorted(set(reasons))


def _workflow_document(
    bundle: ProvenanceBundle,
    metadata: ResearchObjectMetadata,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "workflow_id": f"{metadata.identifier}#workflow",
        "name": f"{metadata.title} workflow",
        "description": (
            "Prospective projection of the recorded activities. The canonical "
            "retrospective history remains the internal provenance bundle."
        ),
        "bundle_hash": bundle.bundle_hash,
        "activities": [
            {
                "activity_id": activity.activity_id,
                "kind": activity.kind.value,
                "label": activity.label,
                "started_at": activity.started_at.isoformat(),
                "ended_at": activity.ended_at.isoformat(),
            }
            for activity in bundle.activities
            if activity.invalidated_at is None
        ],
        "scientific_gate_recomputed_by_export": False,
    }


def _prov_jsonld(bundle: ProvenanceBundle) -> dict[str, Any]:
    bundle.verify_integrity()
    graph: list[dict[str, Any]] = []
    entity_nodes = {
        entity.entity_id: _prov_entity_node(entity) for entity in bundle.entities
    }
    activity_nodes = {
        activity.activity_id: _prov_activity_node(activity)
        for activity in bundle.activities
    }
    agent_nodes = {agent.agent_id: _prov_agent_node(agent) for agent in bundle.agents}
    plan_nodes = {plan.plan_id: _prov_plan_node(plan) for plan in bundle.plans}

    for usage in bundle.usages:
        activity_nodes[usage.activity_id].setdefault("prov:used", []).append(
            {"@id": _prov_id("entity", usage.entity_id)}
        )
        graph.append(_prov_usage_node(usage))
    for generation in bundle.generations:
        entity_nodes[generation.entity_id].setdefault(
            "prov:wasGeneratedBy", []
        ).append({"@id": _prov_id("activity", generation.activity_id)})
        graph.append(_prov_generation_node(generation))
    for derivation in bundle.derivations:
        entity_nodes[derivation.generated_entity_id].setdefault(
            "prov:wasDerivedFrom", []
        ).append({"@id": _prov_id("entity", derivation.used_entity_id)})
        graph.append(_prov_derivation_node(derivation))
    for association in bundle.associations:
        activity_nodes[association.activity_id].setdefault(
            "prov:wasAssociatedWith", []
        ).append({"@id": _prov_id("agent", association.agent_id)})
        graph.append(_prov_association_node(association))

    graph.extend(entity_nodes.values())
    graph.extend(activity_nodes.values())
    graph.extend(agent_nodes.values())
    graph.extend(plan_nodes.values())
    graph.extend(_prov_research_nodes(bundle))
    return {
        "@context": {
            "prov": PROV_CONTEXT,
            "xsd": "http://www.w3.org/2001/XMLSchema#",
            "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
            "autoresearch": "urn:autoresearch:vocab:",
            "label": "rdfs:label",
        },
        "@graph": sorted(graph, key=lambda node: str(node["@id"])),
    }


def _prov_entity_node(entity: Entity) -> dict[str, Any]:
    node: dict[str, Any] = {
        "@id": _prov_id("entity", entity.entity_id),
        "@type": ["prov:Entity", f"autoresearch:{entity.kind.value}"],
        "label": entity.label,
        "prov:generatedAtTime": {
            "@value": entity.valid_from.isoformat(),
            "@type": "xsd:dateTime",
        },
        "autoresearch:recordId": entity.entity_id,
        "autoresearch:version": entity.version,
    }
    if entity.content_digest is not None:
        node["autoresearch:sha256"] = entity.content_digest
    return node


def _prov_activity_node(activity: Activity) -> dict[str, Any]:
    return {
        "@id": _prov_id("activity", activity.activity_id),
        "@type": ["prov:Activity", f"autoresearch:{activity.kind.value}"],
        "label": activity.label,
        "prov:startedAtTime": {
            "@value": activity.started_at.isoformat(),
            "@type": "xsd:dateTime",
        },
        "prov:endedAtTime": {
            "@value": activity.ended_at.isoformat(),
            "@type": "xsd:dateTime",
        },
        "autoresearch:recordId": activity.activity_id,
        "autoresearch:version": activity.version,
    }


def _prov_agent_node(agent: Agent) -> dict[str, Any]:
    node: dict[str, Any] = {
        "@id": _prov_id("agent", agent.agent_id),
        "@type": ["prov:Agent", f"autoresearch:{agent.kind.value}"],
        "label": agent.label,
        "autoresearch:recordId": agent.agent_id,
        "autoresearch:version": agent.version,
    }
    if agent.implementation_hash is not None:
        node["autoresearch:implementationSha256"] = agent.implementation_hash
    return node


def _prov_plan_node(plan: Plan) -> dict[str, Any]:
    return {
        "@id": _prov_id("plan", plan.plan_id),
        "@type": ["prov:Entity", "prov:Plan"],
        "label": plan.title,
        "autoresearch:description": plan.description,
        "autoresearch:sha256": plan.content_digest,
        "autoresearch:recordId": plan.plan_id,
    }


def _prov_usage_node(usage: Usage) -> dict[str, Any]:
    return {
        "@id": _prov_id("usage", usage.usage_id),
        "@type": "prov:Usage",
        "prov:entity": {"@id": _prov_id("entity", usage.entity_id)},
        "prov:atTime": {
            "@value": usage.at_time.isoformat(),
            "@type": "xsd:dateTime",
        },
        "prov:hadRole": usage.role,
        "autoresearch:activity": {
            "@id": _prov_id("activity", usage.activity_id)
        },
    }


def _prov_generation_node(generation: Generation) -> dict[str, Any]:
    return {
        "@id": _prov_id("generation", generation.generation_id),
        "@type": "prov:Generation",
        "prov:entity": {"@id": _prov_id("entity", generation.entity_id)},
        "prov:activity": {
            "@id": _prov_id("activity", generation.activity_id)
        },
        "prov:atTime": {
            "@value": generation.at_time.isoformat(),
            "@type": "xsd:dateTime",
        },
    }


def _prov_derivation_node(derivation: Derivation) -> dict[str, Any]:
    node: dict[str, Any] = {
        "@id": _prov_id("derivation", derivation.derivation_id),
        "@type": "prov:Derivation",
        "prov:generatedEntity": {
            "@id": _prov_id("entity", derivation.generated_entity_id)
        },
        "prov:usedEntity": {
            "@id": _prov_id("entity", derivation.used_entity_id)
        },
        "autoresearch:derivationKind": derivation.kind,
    }
    if derivation.activity_id is not None:
        node["prov:activity"] = {
            "@id": _prov_id("activity", derivation.activity_id)
        }
    return node


def _prov_association_node(association: Association) -> dict[str, Any]:
    node: dict[str, Any] = {
        "@id": _prov_id("association", association.association_id),
        "@type": "prov:Association",
        "prov:agent": {"@id": _prov_id("agent", association.agent_id)},
        "prov:hadRole": association.role,
        "autoresearch:activity": {
            "@id": _prov_id("activity", association.activity_id)
        },
    }
    if association.plan_id is not None:
        node["prov:hadPlan"] = {
            "@id": _prov_id("plan", association.plan_id)
        }
    return node


def _prov_research_nodes(bundle: ProvenanceBundle) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for claim in bundle.claims:
        nodes.append(
            {
                "@id": _prov_id("claim", claim.claim_id),
                "@type": ["prov:Entity", "autoresearch:Claim"],
                "label": claim.statement,
                "autoresearch:confidence": claim.confidence,
                "autoresearch:core": claim.core,
            }
        )
    evidence_items: list[Evidence | Counterevidence] = [
        *bundle.evidence,
        *bundle.counterevidence,
    ]
    for item in evidence_items:
        nodes.append(
            {
                "@id": _prov_id("evidence", item.evidence_id),
                "@type": ["prov:Entity", "autoresearch:Evidence"],
                "label": item.summary,
                "autoresearch:claim": {
                    "@id": _prov_id("claim", item.claim_id)
                },
                "autoresearch:direction": item.direction.value,
                "prov:wasGeneratedBy": {
                    "@id": _prov_id("activity", item.generating_activity_id)
                },
                "prov:wasDerivedFrom": [
                    {"@id": _prov_id("entity", item.source_entity_id)},
                    {"@id": _prov_id("entity", item.artifact_entity_id)},
                ],
            }
        )
    for validation in bundle.validations:
        nodes.append(
            {
                "@id": _prov_id("validation", validation.validation_id),
                "@type": ["prov:Entity", "autoresearch:Validation"],
                "label": validation.summary,
                "autoresearch:status": validation.status.value,
                "autoresearch:subject": validation.subject_id,
                "prov:wasGeneratedBy": {
                    "@id": _prov_id("activity", validation.activity_id)
                },
                "prov:wasAttributedTo": {
                    "@id": _prov_id("agent", validation.agent_id)
                },
            }
        )
    for decision in bundle.decisions:
        nodes.append(_prov_decision_node(decision))
    return nodes


def _prov_decision_node(decision: Decision) -> dict[str, Any]:
    return {
        "@id": _prov_id("decision", decision.decision_id),
        "@type": ["prov:Entity", "autoresearch:Decision"],
        "label": decision.outcome,
        "autoresearch:rationale": decision.rationale,
        "autoresearch:claims": [
            {"@id": _prov_id("claim", claim_id)}
            for claim_id in decision.claim_ids
        ],
        "autoresearch:validations": [
            {"@id": _prov_id("validation", validation_id)}
            for validation_id in decision.validation_ids
        ],
        "prov:wasGeneratedBy": {
            "@id": _prov_id("activity", decision.activity_id)
        },
        "prov:wasAttributedTo": {
            "@id": _prov_id("agent", decision.responsible_agent_id)
        },
    }


def _prov_id(kind: str, record_id: str) -> str:
    return f"urn:autoresearch:prov:{kind}:{quote(record_id, safe='.-_')}"


def _contributions_document(metadata: ResearchObjectMetadata) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "taxonomy": "ANSI/NISO Z39.104-2022 CRediT",
        "taxonomy_url": "https://credit.niso.org/",
        "object_identifier": metadata.identifier,
        "contributors": [
            {
                "name": contributor.display_name,
                "given_names": contributor.given_names or None,
                "family_names": contributor.family_names,
                "orcid": contributor.orcid,
                "affiliation": contributor.affiliation,
                "roles": [
                    {
                        "name": role,
                        "uri": CREDIT_ROLE_URIS[role],
                    }
                    for role in contributor.roles
                ],
            }
            for contributor in metadata.contributors
        ],
    }


def _codemeta_document(metadata: ResearchObjectMetadata) -> dict[str, Any]:
    people = [
        {
            "@id": contributor.orcid or f"#person-{index + 1}",
            "@type": "Person",
            "givenName": contributor.given_names,
            "familyName": contributor.family_names,
            "name": contributor.display_name,
            **(
                {"affiliation": {"@type": "Organization", "name": contributor.affiliation}}
                if contributor.affiliation
                else {}
            ),
        }
        for index, contributor in enumerate(metadata.contributors)
    ]
    identifiers = [metadata.identifier]
    if metadata.swhid is not None:
        identifiers.append(metadata.swhid)
    if metadata.doi is not None:
        identifiers.append(f"https://doi.org/{metadata.doi}")
    return {
        "@context": CODEMETA_CONTEXT,
        "@type": "SoftwareSourceCode",
        "@id": f"{metadata.identifier}#software",
        "identifier": identifiers,
        "name": metadata.title,
        "description": metadata.description,
        "version": metadata.version,
        "datePublished": metadata.published_at.date().isoformat(),
        "license": _license_uri(metadata.license_id),
        "codeRepository": metadata.repository_url,
        "programmingLanguage": metadata.programming_language,
        "runtimePlatform": metadata.runtime_platform,
        "author": people,
        "contributor": people,
        "keywords": list(metadata.keywords),
        "developmentStatus": "active",
    }


def _citation_cff(metadata: ResearchObjectMetadata) -> dict[str, Any]:
    identifiers: list[dict[str, str]] = [
        {"type": "other", "value": metadata.identifier}
    ]
    if metadata.doi is not None:
        identifiers.append({"type": "doi", "value": metadata.doi})
    if metadata.swhid is not None:
        identifiers.append({"type": "swh", "value": metadata.swhid})
    authors: list[dict[str, str]] = []
    for contributor in metadata.contributors:
        author = {
            "family-names": contributor.family_names,
        }
        if contributor.given_names:
            author["given-names"] = contributor.given_names
        if contributor.orcid is not None:
            author["orcid"] = contributor.orcid
        if contributor.affiliation is not None:
            author["affiliation"] = contributor.affiliation
        authors.append(author)
    return {
        "cff-version": "1.2.0",
        "message": "Please cite this research software and its versioned research object.",
        "type": "software",
        "title": metadata.title,
        "abstract": metadata.description,
        "version": metadata.version,
        "date-released": metadata.published_at.date().isoformat(),
        "authors": authors,
        "identifiers": identifiers,
        "repository-code": metadata.repository_url,
        "license": metadata.license_id,
    }


def _datacite_document(metadata: ResearchObjectMetadata) -> dict[str, Any]:
    creators: list[dict[str, Any]] = []
    for contributor in metadata.contributors:
        creator: dict[str, Any] = {
            "name": contributor.display_name,
            "nameType": "Personal",
            "givenName": contributor.given_names,
            "familyName": contributor.family_names,
        }
        if contributor.orcid is not None:
            creator["nameIdentifiers"] = [
                {
                    "nameIdentifier": contributor.orcid,
                    "nameIdentifierScheme": "ORCID",
                    "schemeUri": "https://orcid.org",
                }
            ]
        if contributor.affiliation is not None:
            creator["affiliation"] = [{"name": contributor.affiliation}]
        creators.append(creator)
    related: list[dict[str, str]] = [
        {
            "relatedIdentifier": metadata.repository_url,
            "relatedIdentifierType": "URL",
            "relationType": "IsSupplementTo",
        }
    ]
    if metadata.swhid is not None:
        related.append(
            {
                "relatedIdentifier": metadata.swhid,
                "relatedIdentifierType": "SWHID",
                "relationType": "IsIdenticalTo",
            }
        )
    return {
        "schemaVersion": "4.7",
        "depositReady": metadata.doi is not None,
        "depositBlockers": (
            []
            if metadata.doi is not None
            else ["A real DOI has not been supplied; no identifier was minted."]
        ),
        "identifier": (
            {"identifier": metadata.doi, "identifierType": "DOI"}
            if metadata.doi is not None
            else None
        ),
        "alternateIdentifiers": [
            {
                "alternateIdentifier": metadata.identifier,
                "alternateIdentifierType": "URN",
            }
        ],
        "creators": creators,
        "titles": [{"title": metadata.title}],
        "publisher": metadata.publisher,
        "publicationYear": metadata.published_at.year,
        "resourceType": {
            "resourceType": "Research Object",
            "resourceTypeGeneral": "Workflow",
        },
        "subjects": [{"subject": keyword} for keyword in metadata.keywords],
        "contributors": [
            {
                "name": contributor.display_name,
                "contributorType": "Researcher",
            }
            for contributor in metadata.contributors
        ],
        "dates": [
            {
                "date": metadata.published_at.date().isoformat(),
                "dateType": "Issued",
            }
        ],
        "relatedIdentifiers": related,
        "rightsList": [
            {
                "rights": metadata.license_id,
                "rightsUri": _license_uri(metadata.license_id),
                "rightsIdentifier": metadata.license_id,
                "rightsIdentifierScheme": "SPDX",
                "schemeUri": "https://spdx.org/licenses/",
            }
        ],
        "descriptions": [
            {
                "description": metadata.description,
                "descriptionType": "Abstract",
            }
        ],
        "version": metadata.version,
    }


def _spdx_document(
    metadata: ResearchObjectMetadata,
    artifacts: Sequence[_MaterializedArtifact],
    created_at: datetime,
) -> dict[str, Any]:
    base = f"urn:autoresearch:spdx:{_short_digest(metadata.identifier)}"
    creation_id = "_:creation-info"
    agent_id = f"{base}:agent"
    package_id = f"{base}:package"
    sbom_id = f"{base}:sbom"
    document_id = f"{base}:document"
    build_id = f"{base}:build"
    license_id = f"{base}:license"
    graph: list[dict[str, Any]] = [
        {
            "@id": creation_id,
            "type": "CreationInfo",
            "created": _spdx_timestamp(created_at),
            "createdBy": [agent_id],
            "specVersion": "3.0.1",
        },
        {
            "type": "Agent",
            "spdxId": agent_id,
            "creationInfo": creation_id,
            "name": metadata.publisher,
        },
        {
            "type": "simplelicensing_LicenseExpression",
            "spdxId": license_id,
            "creationInfo": creation_id,
            "simplelicensing_licenseExpression": metadata.license_id,
        },
        {
            "type": "software_Package",
            "spdxId": package_id,
            "creationInfo": creation_id,
            "name": metadata.title,
            "description": metadata.description,
            "software_packageVersion": metadata.version,
            "software_downloadLocation": metadata.repository_url,
            "software_sourceInfo": (
                f"Git commit {metadata.commit_sha}"
                + (f"; {metadata.swhid}" if metadata.swhid else "")
            ),
            "suppliedBy": agent_id,
            "verifiedUsing": [
                {
                    "type": "Hash",
                    "algorithm": "sha256",
                    "hashValue": _aggregate_artifact_digest(artifacts),
                }
            ],
        },
        {
            "type": "build_Build",
            "spdxId": build_id,
            "creationInfo": creation_id,
            "name": "AutoResearch Open Science export build",
            "build_buildType": "urn:autoresearch:build-type:open-science-export-v1",
            "build_buildStartTime": _spdx_timestamp(created_at),
            "build_buildEndTime": _spdx_timestamp(created_at),
        },
    ]
    file_ids: list[str] = []
    for index, artifact in enumerate(sorted(artifacts, key=lambda item: item.crate_path)):
        artifact_id = f"{base}:file:{index + 1}"
        file_ids.append(artifact_id)
        graph.append(
            {
                "type": "software_File",
                "spdxId": artifact_id,
                "creationInfo": creation_id,
                "name": artifact.crate_path,
                "contentType": artifact.media_type,
                "verifiedUsing": [
                    {
                        "type": "Hash",
                        "algorithm": "sha256",
                        "hashValue": artifact.exported_sha256,
                    }
                ],
            }
        )
    relationships = [
        _spdx_relationship(
            base,
            "declared-license",
            package_id,
            [license_id],
            "hasDeclaredLicense",
            creation_id,
        ),
        _spdx_relationship(
            base,
            "concluded-license",
            package_id,
            [license_id],
            "hasConcludedLicense",
            creation_id,
        ),
        _spdx_relationship(
            base,
            "build-output",
            build_id,
            [package_id],
            "hasOutput",
            creation_id,
        ),
        _spdx_relationship(
            base,
            "build-invoker",
            build_id,
            [agent_id],
            "invokedBy",
            creation_id,
        ),
        _spdx_relationship(
            base,
            "package-files",
            package_id,
            file_ids,
            "contains",
            creation_id,
        ),
    ]
    graph.extend(relationships)
    element_ids = [
        agent_id,
        license_id,
        package_id,
        build_id,
        *file_ids,
        *(relationship["spdxId"] for relationship in relationships),
    ]
    graph.extend(
        [
            {
                "type": "software_Sbom",
                "spdxId": sbom_id,
                "creationInfo": creation_id,
                "name": f"{metadata.title} SPDX SBOM",
                "profileConformance": [
                    "core",
                    "software",
                    "simpleLicensing",
                    "build",
                ],
                "element": element_ids,
                "rootElement": [package_id],
                "software_sbomType": ["source"],
            },
            {
                "type": "SpdxDocument",
                "spdxId": document_id,
                "creationInfo": creation_id,
                "name": f"{metadata.title} SPDX 3.0.1 document",
                "profileConformance": [
                    "core",
                    "software",
                    "simpleLicensing",
                    "build",
                ],
                "element": [*element_ids, sbom_id],
                "rootElement": [sbom_id],
                "dataLicense": license_id,
            },
        ]
    )
    return {"@context": SPDX_CONTEXT, "@graph": graph}


def _spdx_relationship(
    base: str,
    suffix: str,
    from_id: str,
    to_ids: Sequence[str],
    relationship_type: str,
    creation_id: str,
) -> dict[str, Any]:
    return {
        "type": "Relationship",
        "spdxId": f"{base}:relationship:{suffix}",
        "creationInfo": creation_id,
        "from": from_id,
        "to": list(to_ids),
        "relationshipType": relationship_type,
    }


def _slsa_document(
    metadata: ResearchObjectMetadata,
    bundle: ProvenanceBundle,
    artifacts: Sequence[_MaterializedArtifact],
    view: ResearchObjectView,
    created_at: datetime,
) -> dict[str, Any]:
    return {
        "_type": IN_TOTO_STATEMENT,
        "subject": [
            {
                "name": artifact.crate_path,
                "digest": {"sha256": artifact.exported_sha256},
            }
            for artifact in sorted(artifacts, key=lambda item: item.crate_path)
        ],
        "predicateType": SLSA_PREDICATE,
        "predicate": {
            "buildDefinition": {
                "buildType": "urn:autoresearch:build-type:open-science-export-v1",
                "externalParameters": {
                    "objectIdentifier": metadata.identifier,
                    "view": view.value,
                    "sourceBundleHash": bundle.bundle_hash,
                },
                "internalParameters": {
                    "profileVersions": PROFILE_VERSIONS,
                    "publicRelease": False,
                },
                "resolvedDependencies": [
                    {
                        "uri": metadata.repository_url,
                        "digest": {"gitCommit": metadata.commit_sha},
                        **(
                            {"annotations": {"swhid": metadata.swhid}}
                            if metadata.swhid is not None
                            else {}
                        ),
                    },
                    {
                        "uri": f"urn:autoresearch:provenance:{bundle.bundle_id}",
                        "digest": {"sha256": bundle.bundle_hash},
                    },
                ],
            },
            "runDetails": {
                "builder": {
                    "id": "urn:autoresearch:builder:local-open-science-exporter-v1",
                    "version": {"ai-researcher": metadata.version},
                },
                "metadata": {
                    "invocationId": (
                        f"urn:autoresearch:export:{_short_digest(metadata.identifier)}:"
                        f"{view.value}"
                    ),
                    "startedOn": created_at.isoformat().replace("+00:00", "Z"),
                    "finishedOn": created_at.isoformat().replace("+00:00", "Z"),
                },
                "byproducts": [
                    {
                        "name": "profile-version-matrix",
                        "uri": "export-policy.json",
                    }
                ],
            },
        },
    }


def _export_policy(
    view: ResearchObjectView,
    bundle: ProvenanceBundle,
    metadata: ResearchObjectMetadata,
    artifacts: Sequence[_MaterializedArtifact],
    approval: PublicationApproval | None,
    created_at: datetime,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "view": view.value,
        "object_identifier": metadata.identifier,
        "source_bundle_hash": bundle.bundle_hash,
        "created_at": created_at.isoformat(),
        "artifact_policies": [
            {
                "crate_path": artifact.crate_path,
                "role": artifact.role,
                "license": artifact.license_id,
                "transformation": artifact.transform.value,
                "original_sha256": artifact.original_sha256,
                "exported_sha256": artifact.exported_sha256,
            }
            for artifact in sorted(artifacts, key=lambda item: item.crate_path)
        ],
        "publication_approved": approval is not None,
        "publication_approval": (
            {
                "approval_id": approval.approval_id,
                "approver": approval.approver,
                "approved_at": approval.approved_at.isoformat(),
                "scope_identifier": approval.scope_identifier,
            }
            if approval is not None
            else None
        ),
        "publication_performed": False,
        "metadata_interoperability_only": True,
        "scientific_experiment_reexecuted": False,
        "data_policy": "as open as possible, as closed as necessary",
    }


def _reproduction_plan(
    artifacts: Sequence[_MaterializedArtifact],
    assertions: Sequence[JsonAssertion],
) -> dict[str, Any]:
    asserted_paths = {assertion.crate_path for assertion in assertions}
    files = [
        {
            "path": artifact.crate_path,
            "sha256": artifact.exported_sha256,
        }
        for artifact in sorted(artifacts, key=lambda item: item.crate_path)
        if artifact.crate_path in asserted_paths
    ]
    return {
        "schema_version": 1,
        "profile": REPRODUCTION_PLAN_PROFILE,
        "scope": "artifact integrity and frozen decision assertions",
        "scientific_experiment_reexecuted": False,
        "files": files,
        "assertions": [
            {
                "path": assertion.crate_path,
                "json_pointer": assertion.json_pointer,
                "expected": assertion.expected,
                "label": assertion.label,
            }
            for assertion in assertions
        ],
    }


def _readme_document(
    metadata: ResearchObjectMetadata,
    view: ResearchObjectView,
) -> str:
    return (
        f"# {metadata.title}\n\n"
        f"- Object identifier: `{metadata.identifier}`\n"
        f"- Version: `{metadata.version}`\n"
        f"- View: `{view.value}`\n"
        f"- Source revision: `{metadata.commit_sha}`\n\n"
        "This RO-Crate is a local, policy-bounded research-object export. "
        "Its metadata, hashes, provenance links, and frozen assertions are "
        "validated for interoperability and review.\n\n"
        "Run `python -I reproduction/reproduce.py` from the crate root to "
        "recompute artifact hashes and the recorded JSON assertions. This "
        "does not rerun the scientific experiment and does not independently "
        "establish the truth of its scientific claims.\n\n"
        "No publication is performed by this export. Public materialization "
        "requires explicit, scope-matched human approval and compatible "
        "artifact licenses.\n"
    )


def _ro_crate_document(
    bundle: ProvenanceBundle,
    metadata: ResearchObjectMetadata,
    artifacts: Sequence[_MaterializedArtifact],
    created_at: datetime,
) -> dict[str, Any]:
    contributor_ids = [
        contributor.orcid or f"#person-{index + 1}"
        for index, contributor in enumerate(metadata.contributors)
    ]
    profile_ids = (
        PROCESS_RUN_PROFILE,
        WORKFLOW_RUN_PROFILE,
        PROVENANCE_RUN_PROFILE,
        WORKFLOW_RO_CRATE_PROFILE,
    )
    workflow_id = "workflow/workflow.json"
    run_id = f"#workflow-run-{_short_digest(bundle.run_id)}"
    action_ids = [
        f"#activity-{index + 1}"
        for index, _activity in enumerate(bundle.activities)
    ]
    has_parts = [
        {"@id": artifact.crate_path}
        for artifact in sorted(artifacts, key=lambda item: item.crate_path)
    ]
    graph: list[dict[str, Any]] = [
        {
            "@id": "ro-crate-metadata.json",
            "@type": "CreativeWork",
            "about": {"@id": "./"},
            "conformsTo": [
                {"@id": RO_CRATE_PROFILE},
                {"@id": RO_CRATE_WRROC_BASE_PROFILE},
                {"@id": WORKFLOW_RO_CRATE_PROFILE},
            ],
        },
        {
            "@id": "./",
            "@type": "Dataset",
            "identifier": metadata.identifier,
            "name": metadata.title,
            "description": metadata.description,
            "version": metadata.version,
            "datePublished": metadata.published_at.date().isoformat(),
            "dateCreated": created_at.isoformat(),
            "publisher": {"@id": "#publisher"},
            "author": [{"@id": identifier} for identifier in contributor_ids],
            "contributor": [{"@id": identifier} for identifier in contributor_ids],
            "license": {"@id": _license_uri(metadata.license_id)},
            "mainEntity": {"@id": workflow_id},
            "hasPart": has_parts,
            "mentions": [
                {"@id": identifier}
                for identifier in (run_id, *action_ids)
            ],
            "conformsTo": [{"@id": profile_id} for profile_id in profile_ids],
        },
        {
            "@id": RO_CRATE_PROFILE,
            "@type": ["CreativeWork", "Profile"],
            "name": "RO-Crate Metadata Specification",
            "version": "1.3",
        },
        *_ro_profile_nodes(),
        {
            "@id": "#publisher",
            "@type": "Organization",
            "name": metadata.publisher,
            "url": metadata.repository_url,
        },
        {
            "@id": _license_uri(metadata.license_id),
            "@type": "CreativeWork",
            "name": metadata.license_id,
        },
    ]
    graph.extend(_ro_contributor_nodes(metadata))
    graph.extend(_ro_artifact_nodes(artifacts))
    graph.extend(_ro_workflow_nodes(bundle, metadata, artifacts, run_id))
    return {
        "@context": [RO_CRATE_CONTEXT, WRROC_CONTEXT],
        "@graph": _deduplicate_graph(graph),
    }


def _ro_profile_nodes() -> list[dict[str, Any]]:
    return [
        {
            "@id": RO_CRATE_WRROC_BASE_PROFILE,
            "@type": ["CreativeWork", "Profile"],
            "name": "RO-Crate Metadata Specification",
            "version": "1.1",
        },
        {
            "@id": PROCESS_RUN_PROFILE,
            "@type": ["CreativeWork", "Profile"],
            "name": "Process Run Crate",
            "version": "0.5",
        },
        {
            "@id": WORKFLOW_RUN_PROFILE,
            "@type": ["CreativeWork", "Profile"],
            "name": "Workflow Run Crate",
            "version": "0.5",
        },
        {
            "@id": PROVENANCE_RUN_PROFILE,
            "@type": ["CreativeWork", "Profile"],
            "name": "Provenance Run Crate",
            "version": "0.5",
        },
        {
            "@id": WORKFLOW_RO_CRATE_PROFILE,
            "@type": ["CreativeWork", "Profile"],
            "name": "Workflow RO-Crate",
            "version": "1.0",
        },
        {
            "@id": BIOSCHEMAS_COMPUTATIONAL_WORKFLOW_PROFILE,
            "@type": ["CreativeWork", "Profile"],
            "name": "Bioschemas ComputationalWorkflow Profile",
            "version": "1.0-RELEASE",
        },
        {
            "@id": REPRODUCTION_PLAN_PROFILE,
            "@type": ["CreativeWork", "Profile"],
            "name": "AutoResearch clean-directory reproduction plan",
            "version": "1",
        },
    ]


def _ro_contributor_nodes(
    metadata: ResearchObjectMetadata,
) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for index, contributor in enumerate(metadata.contributors):
        identifier = contributor.orcid or f"#person-{index + 1}"
        node: dict[str, Any] = {
            "@id": identifier,
            "@type": "Person",
            "name": contributor.display_name,
            "givenName": contributor.given_names,
            "familyName": contributor.family_names,
            "roleName": list(contributor.roles),
        }
        if contributor.affiliation is not None:
            affiliation_id = f"#affiliation-{index + 1}"
            node["affiliation"] = {"@id": affiliation_id}
            nodes.append(
                {
                    "@id": affiliation_id,
                    "@type": "Organization",
                    "name": contributor.affiliation,
                    "url": metadata.repository_url,
                }
            )
        nodes.append(node)
    return nodes


def _ro_artifact_nodes(
    artifacts: Sequence[_MaterializedArtifact],
) -> list[dict[str, Any]]:
    return [
        {
            "@id": artifact.crate_path,
            "@type": "File",
            "name": Path(artifact.crate_path).name,
            "description": artifact.description or artifact.role,
            "encodingFormat": artifact.media_type,
            "contentSize": str(artifact.size_bytes),
            "sha256": artifact.exported_sha256,
            "license": {"@id": _license_uri(artifact.license_id)},
            "additionalType": f"urn:autoresearch:artifact-role:{artifact.role}",
            **(
                {"about": {"@id": "./"}}
                if artifact.crate_path == "README.md"
                else {}
            ),
            **(
                {
                    "conformsTo": {
                        "@id": REPRODUCTION_PLAN_PROFILE,
                    }
                }
                if artifact.crate_path
                == "reproduction/reproduction-plan.json"
                else {}
            ),
            **(
                {
                    "identifier": (
                        f"urn:autoresearch:provenance-entity:"
                        f"{artifact.provenance_entity_id}"
                    )
                }
                if artifact.provenance_entity_id is not None
                else {}
            ),
        }
        for artifact in sorted(artifacts, key=lambda item: item.crate_path)
    ]


def _ro_workflow_nodes(
    bundle: ProvenanceBundle,
    metadata: ResearchObjectMetadata,
    artifacts: Sequence[_MaterializedArtifact],
    run_id: str,
) -> list[dict[str, Any]]:
    workflow_id = "workflow/workflow.json"
    step_ids = [
        f"{workflow_id}#step-{index + 1}"
        for index, _activity in enumerate(bundle.activities)
    ]
    mapping = {
        artifact.provenance_entity_id: artifact.crate_path
        for artifact in artifacts
        if artifact.provenance_entity_id is not None
    }
    usage_by_activity: dict[str, list[str]] = {}
    generation_by_activity: dict[str, list[str]] = {}
    for usage in bundle.usages:
        usage_by_activity.setdefault(usage.activity_id, []).append(usage.entity_id)
    for generation in bundle.generations:
        generation_by_activity.setdefault(generation.activity_id, []).append(
            generation.entity_id
        )
    workflow: dict[str, Any] = {
        "@id": workflow_id,
        "@type": [
            "File",
            "SoftwareSourceCode",
            "ComputationalWorkflow",
            "https://bioschemas.org/ComputationalWorkflow",
            "HowTo",
        ],
        "name": f"{metadata.title} workflow",
        "description": (
            "Provider-neutral prospective projection; retrospective facts are "
            "recorded in provenance/prov.jsonld."
        ),
        "version": metadata.version,
        "url": metadata.repository_url,
        "conformsTo": {
            "@id": BIOSCHEMAS_COMPUTATIONAL_WORKFLOW_PROFILE,
        },
        "programmingLanguage": {"@id": "#python-language"},
        "author": [
            {
                "@id": contributor.orcid or f"#person-{index + 1}"
            }
            for index, contributor in enumerate(metadata.contributors)
        ],
        "license": {"@id": _license_uri(metadata.license_id)},
        "step": [{"@id": step_id} for step_id in step_ids],
        "hasPart": [
            {"@id": _tool_identifier(metadata, activity)}
            for activity in bundle.activities
        ],
        "buildInstructions": {"@id": "reproduction/reproduction-plan.json"},
    }
    nodes: list[dict[str, Any]] = [
        workflow,
        {
            "@id": "#python-language",
            "@type": "ComputerLanguage",
            "name": metadata.programming_language,
            "identifier": "https://www.python.org/",
            "url": "https://www.python.org/",
            "version": metadata.runtime_platform,
        },
    ]
    for index, activity in enumerate(bundle.activities):
        step_id = step_ids[index]
        tool_id = _tool_identifier(metadata, activity)
        action_id = f"#activity-{index + 1}"
        control_id = f"#control-{index + 1}"
        input_ids = [
            mapping.get(entity_id, _prov_id("entity", entity_id))
            for entity_id in usage_by_activity.get(activity.activity_id, [])
        ]
        output_ids = [
            mapping.get(entity_id, _prov_id("entity", entity_id))
            for entity_id in generation_by_activity.get(activity.activity_id, [])
        ]
        nodes.extend(
            [
                {
                    "@id": step_id,
                    "@type": "HowToStep",
                    "name": activity.label,
                    "position": str(index + 1),
                    "workExample": {"@id": tool_id},
                },
                {
                    "@id": tool_id,
                    "@type": "SoftwareApplication",
                    "name": activity.label,
                    "url": metadata.repository_url,
                    "version": metadata.version,
                },
                {
                    "@id": action_id,
                    "@type": "CreateAction",
                    "name": activity.label,
                    "description": (
                        f"Recorded execution of {activity.label}; completion "
                        "denotes process completion, not scientific success."
                    ),
                    "instrument": {"@id": tool_id},
                    "agent": {"@id": "#publisher"},
                    "startTime": _wrroc_timestamp(activity.started_at),
                    "endTime": _wrroc_timestamp(activity.ended_at),
                    "actionStatus": "http://schema.org/CompletedActionStatus",
                    **(
                        {"object": [{"@id": identifier} for identifier in input_ids]}
                        if input_ids
                        else {}
                    ),
                    **(
                        {"result": [{"@id": identifier} for identifier in output_ids]}
                        if output_ids
                        else {}
                    ),
                },
                {
                    "@id": control_id,
                    "@type": "ControlAction",
                    "name": f"Orchestrate {activity.label}",
                    "description": (
                        f"Control edge linking workflow step {index + 1} "
                        "to its recorded execution."
                    ),
                    "instrument": {"@id": step_id},
                    "object": {"@id": action_id},
                },
            ]
        )
    first = min(bundle.activities, key=lambda item: item.started_at)
    last = max(bundle.activities, key=lambda item: item.ended_at)
    used_ids = sorted(
        {
            mapping.get(usage.entity_id, _prov_id("entity", usage.entity_id))
            for usage in bundle.usages
        }
    )
    generated_ids = sorted(
        {
            mapping.get(
                generation.entity_id,
                _prov_id("entity", generation.entity_id),
            )
            for generation in bundle.generations
        }
    )
    nodes.append(
        {
            "@id": run_id,
            "@type": "CreateAction",
            "name": f"Recorded run {bundle.run_id}",
            "description": (
                "Aggregate record of the bounded workflow run; completion "
                "does not imply a positive scientific result."
            ),
            "instrument": {"@id": workflow_id},
            "agent": {"@id": "#publisher"},
            "startTime": _wrroc_timestamp(first.started_at),
            "endTime": _wrroc_timestamp(last.ended_at),
            "actionStatus": "http://schema.org/CompletedActionStatus",
            **(
                {"object": [{"@id": identifier} for identifier in used_ids]}
                if used_ids
                else {}
            ),
            **(
                {"result": [{"@id": identifier} for identifier in generated_ids]}
                if generated_ids
                else {}
            ),
        }
    )
    known = {str(node["@id"]) for node in nodes}
    contextual_ids = sorted(
        {
            identifier
            for identifier in [*used_ids, *generated_ids]
            if identifier not in known
        }
    )
    nodes.extend(
        {
            "@id": identifier,
            "@type": "CreativeWork",
            "name": identifier.rsplit(":", 1)[-1],
        }
        for identifier in contextual_ids
    )
    return nodes


def _deduplicate_graph(
    graph: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for node in graph:
        identifier = str(node["@id"])
        if identifier in by_id:
            previous = by_id[identifier]
            merged = {**previous, **node}
            previous_types = _as_list(previous.get("@type"))
            current_types = _as_list(node.get("@type"))
            if previous_types or current_types:
                merged["@type"] = sorted(set(previous_types + current_types))
            by_id[identifier] = merged
        else:
            by_id[identifier] = node
    return [by_id[identifier] for identifier in sorted(by_id)]


def _validate_ro_crate(
    root: Path,
    crate: Any,
    issues: list[OpenScienceValidationIssue],
) -> bool:
    before = len(issues)
    if not isinstance(crate, dict):
        return False
    contexts = _as_list(crate.get("@context"))
    if RO_CRATE_CONTEXT not in contexts or WRROC_CONTEXT not in contexts:
        issues.append(
            OpenScienceValidationIssue(
                "ro_crate_context",
                "RO-Crate 1.3 and Workflow Run contexts must both be declared",
                ValidationSeverity.FAILED,
                "ro-crate-metadata.json",
            )
        )
    graph = crate.get("@graph")
    if not isinstance(graph, list):
        issues.append(
            OpenScienceValidationIssue(
                "ro_crate_graph",
                "RO-Crate @graph must be an array",
                ValidationSeverity.FAILED,
                "ro-crate-metadata.json",
            )
        )
        return False
    nodes = {
        str(node.get("@id")): node
        for node in graph
        if isinstance(node, dict) and isinstance(node.get("@id"), str)
    }
    if len(nodes) != len(graph):
        issues.append(
            OpenScienceValidationIssue(
                "ro_crate_ids",
                "every RO-Crate graph node must have a unique @id",
                ValidationSeverity.FAILED,
                "ro-crate-metadata.json",
            )
        )
    descriptor = nodes.get("ro-crate-metadata.json")
    root_node = nodes.get("./")
    if not isinstance(descriptor, dict) or not isinstance(root_node, dict):
        issues.append(
            OpenScienceValidationIssue(
                "ro_crate_roots",
                "metadata descriptor and root Dataset are required",
                ValidationSeverity.FAILED,
                "ro-crate-metadata.json",
            )
        )
        return False
    descriptor_profiles = _id_values(descriptor.get("conformsTo"))
    required_descriptor_profiles = {
        RO_CRATE_PROFILE,
        RO_CRATE_WRROC_BASE_PROFILE,
        WORKFLOW_RO_CRATE_PROFILE,
    }
    if not required_descriptor_profiles.issubset(descriptor_profiles):
        issues.append(
            OpenScienceValidationIssue(
                "ro_crate_base_profile",
                "metadata descriptor must declare RO-Crate 1.3 plus the "
                "RO-Crate 1.1 and Workflow RO-Crate compatibility profiles",
                ValidationSeverity.FAILED,
                "ro-crate-metadata.json",
            )
        )
    required_profiles = {
        PROCESS_RUN_PROFILE,
        WORKFLOW_RUN_PROFILE,
        PROVENANCE_RUN_PROFILE,
        WORKFLOW_RO_CRATE_PROFILE,
    }
    if not required_profiles.issubset(_id_values(root_node.get("conformsTo"))):
        issues.append(
            OpenScienceValidationIssue(
                "wrroc_profiles",
                "root Dataset must declare Process, Workflow, Provenance Run 0.5 "
                "and Workflow RO-Crate profiles",
                ValidationSeverity.FAILED,
                "ro-crate-metadata.json",
            )
        )
    for profile in required_profiles:
        profile_node = nodes.get(profile)
        if not isinstance(profile_node, dict) or "Profile" not in _as_list(
            profile_node.get("@type")
        ):
            issues.append(
                OpenScienceValidationIssue(
                    "wrroc_profile_entity",
                    f"profile lacks a Profile contextual entity: {profile}",
                    ValidationSeverity.FAILED,
                    "ro-crate-metadata.json",
                )
            )
    main_ids = _id_values(root_node.get("mainEntity"))
    if len(main_ids) != 1:
        issues.append(
            OpenScienceValidationIssue(
                "workflow_main_entity",
                "root Dataset requires exactly one main workflow",
                ValidationSeverity.FAILED,
                "ro-crate-metadata.json",
            )
        )
    else:
        workflow = nodes.get(next(iter(main_ids)))
        required_types = {
            "File",
            "SoftwareSourceCode",
            "ComputationalWorkflow",
            "HowTo",
        }
        if not isinstance(workflow, dict) or not required_types.issubset(
            set(_as_list(workflow.get("@type")))
        ):
            issues.append(
                OpenScienceValidationIssue(
                    "workflow_profile",
                    "main workflow lacks required Workflow/Provenance Run types",
                    ValidationSeverity.FAILED,
                    "ro-crate-metadata.json",
                )
            )
        elif (
            BIOSCHEMAS_COMPUTATIONAL_WORKFLOW_PROFILE
            not in _id_values(workflow.get("conformsTo"))
            or not _HTTP_URL_RE.fullmatch(str(workflow.get("url", "")))
        ):
            issues.append(
                OpenScienceValidationIssue(
                    "workflow_bioschemas_profile",
                    "main workflow must declare the released Bioschemas "
                    "ComputationalWorkflow 1.0 profile and an HTTP(S) URL",
                    ValidationSeverity.FAILED,
                    "ro-crate-metadata.json",
                )
            )
    readme = nodes.get("README.md")
    if (
        not isinstance(readme, dict)
        or "./" not in _id_values(readme.get("about"))
        or readme.get("encodingFormat") != "text/markdown"
        or not (root / "README.md").is_file()
    ):
        issues.append(
            OpenScienceValidationIssue(
                "workflow_readme",
                "README.md must be a text/markdown File about the root Dataset",
                ValidationSeverity.FAILED,
                "README.md",
            )
        )
    reproduction_plan = nodes.get("reproduction/reproduction-plan.json")
    if (
        not isinstance(reproduction_plan, dict)
        or REPRODUCTION_PLAN_PROFILE
        not in _id_values(reproduction_plan.get("conformsTo"))
    ):
        issues.append(
            OpenScienceValidationIssue(
                "reproduction_plan_profile",
                "build instructions must declare the local reproduction-plan "
                "profile",
                ValidationSeverity.FAILED,
                "reproduction/reproduction-plan.json",
            )
        )
    for part_id in _id_values(root_node.get("hasPart")):
        if part_id not in nodes:
            issues.append(
                OpenScienceValidationIssue(
                    "ro_crate_has_part",
                    f"hasPart references missing graph node: {part_id}",
                    ValidationSeverity.FAILED,
                    "ro-crate-metadata.json",
                )
            )
        if not (root / part_id).is_file():
            issues.append(
                OpenScienceValidationIssue(
                    "ro_crate_payload",
                    f"declared payload is missing: {part_id}",
                    ValidationSeverity.FAILED,
                    part_id,
                )
            )
    create_actions = [
        node
        for node in graph
        if isinstance(node, dict) and "CreateAction" in _as_list(node.get("@type"))
    ]
    if not create_actions:
        issues.append(
            OpenScienceValidationIssue(
                "process_run_action",
                "Workflow Run profile requires a CreateAction",
                ValidationSeverity.FAILED,
                "ro-crate-metadata.json",
            )
        )
    mentioned_ids = _id_values(root_node.get("mentions"))
    for action in create_actions:
        action_id = str(action.get("@id", ""))
        if not _id_values(action.get("instrument")):
            issues.append(
                OpenScienceValidationIssue(
                    "process_run_instrument",
                    f"CreateAction {action_id} lacks an instrument",
                    ValidationSeverity.FAILED,
                    "ro-crate-metadata.json",
                )
            )
        if action_id not in mentioned_ids:
            issues.append(
                OpenScienceValidationIssue(
                    "process_run_mentions",
                    f"CreateAction {action_id} is not mentioned by the root Dataset",
                    ValidationSeverity.FAILED,
                    "ro-crate-metadata.json",
                )
            )
        if not str(action.get("description", "")).strip():
            issues.append(
                OpenScienceValidationIssue(
                    "process_run_description",
                    f"CreateAction {action_id} lacks a description",
                    ValidationSeverity.FAILED,
                    "ro-crate-metadata.json",
                )
            )
        for field_name in ("startTime", "endTime"):
            if not _WRROC_TIMESTAMP_RE.fullmatch(
                str(action.get(field_name, ""))
            ):
                issues.append(
                    OpenScienceValidationIssue(
                        "process_run_timestamp",
                        f"CreateAction {action_id} has an invalid {field_name}",
                        ValidationSeverity.FAILED,
                        "ro-crate-metadata.json",
                    )
                )
        if action.get("actionStatus") not in {
            "http://schema.org/CompletedActionStatus",
            "http://schema.org/FailedActionStatus",
        }:
            issues.append(
                OpenScienceValidationIssue(
                    "process_run_status",
                    f"CreateAction {action_id} has an invalid actionStatus",
                    ValidationSeverity.FAILED,
                    "ro-crate-metadata.json",
                )
            )
    for node in graph:
        if not isinstance(node, dict) or "SoftwareApplication" not in _as_list(
            node.get("@type")
        ):
            continue
        tool_id = str(node.get("@id", ""))
        if not _HTTP_URL_RE.fullmatch(tool_id):
            issues.append(
                OpenScienceValidationIssue(
                    "process_run_tool_identifier",
                    f"SoftwareApplication identifier is not HTTP(S): {tool_id}",
                    ValidationSeverity.FAILED,
                    "ro-crate-metadata.json",
                )
            )
        if "version" in node and "softwareVersion" in node:
            issues.append(
                OpenScienceValidationIssue(
                    "process_run_tool_version",
                    f"SoftwareApplication {tool_id} declares duplicate version fields",
                    ValidationSeverity.FAILED,
                    "ro-crate-metadata.json",
                )
            )
    return not any(
        issue.severity is ValidationSeverity.FAILED
        for issue in issues[before:]
    )


def _validate_prov_jsonld(
    payload: Any,
    issues: list[OpenScienceValidationIssue],
) -> bool:
    before = len(issues)
    if not isinstance(payload, dict) or not isinstance(payload.get("@graph"), list):
        issues.append(
            OpenScienceValidationIssue(
                "prov_shape",
                "PROV JSON-LD requires an @context and flat @graph",
                ValidationSeverity.FAILED,
                "provenance/prov.jsonld",
            )
        )
        return False
    context = payload.get("@context")
    if not isinstance(context, dict) or context.get("prov") != PROV_CONTEXT:
        issues.append(
            OpenScienceValidationIssue(
                "prov_context",
                "PROV JSON-LD must map the W3C PROV namespace",
                ValidationSeverity.FAILED,
                "provenance/prov.jsonld",
            )
        )
    graph = payload["@graph"]
    ids = {
        str(node.get("@id"))
        for node in graph
        if isinstance(node, dict) and isinstance(node.get("@id"), str)
    }
    required_types = {"prov:Entity", "prov:Activity", "prov:Agent"}
    present_types = {
        item
        for node in graph
        if isinstance(node, dict)
        for item in _as_list(node.get("@type"))
    }
    missing = sorted(required_types - present_types)
    if missing:
        issues.append(
            OpenScienceValidationIssue(
                "prov_starting_points",
                f"PROV graph lacks: {', '.join(missing)}",
                ValidationSeverity.FAILED,
                "provenance/prov.jsonld",
            )
        )
    for node in graph:
        if not isinstance(node, dict):
            continue
        for reference in _walk_id_references(node):
            if reference.startswith("urn:autoresearch:prov:") and reference not in ids:
                issues.append(
                    OpenScienceValidationIssue(
                        "prov_reference",
                        f"PROV graph references missing node: {reference}",
                        ValidationSeverity.FAILED,
                        "provenance/prov.jsonld",
                    )
                )
    return not any(
        issue.severity is ValidationSeverity.FAILED
        for issue in issues[before:]
    )


def _validate_metadata_consistency(
    crate: Any,
    codemeta: Any,
    cff: Any,
    contributions: Any,
    datacite: Any,
    issues: list[OpenScienceValidationIssue],
) -> bool:
    before = len(issues)
    root_node: dict[str, Any] = {}
    if isinstance(crate, dict) and isinstance(crate.get("@graph"), list):
        root_node = next(
            (
                node
                for node in crate["@graph"]
                if isinstance(node, dict) and node.get("@id") == "./"
            ),
            {},
        )
    expected = {
        "identifier": root_node.get("identifier"),
        "title": root_node.get("name"),
        "version": root_node.get("version"),
        "license": next(iter(_id_values(root_node.get("license"))), None),
    }
    if not isinstance(codemeta, dict) or codemeta.get("@context") != CODEMETA_CONTEXT:
        issues.append(
            OpenScienceValidationIssue(
                "codemeta_context",
                "CodeMeta document must use the 3.1 context",
                ValidationSeverity.FAILED,
                "metadata/codemeta.json",
            )
        )
    elif (
        codemeta.get("name") != expected["title"]
        or codemeta.get("version") != expected["version"]
        or codemeta.get("license") != expected["license"]
        or expected["identifier"] not in _as_list(codemeta.get("identifier"))
    ):
        issues.append(
            OpenScienceValidationIssue(
                "codemeta_consistency",
                "CodeMeta title/version/license/identifier differ from RO-Crate",
                ValidationSeverity.FAILED,
                "metadata/codemeta.json",
            )
        )
    if not isinstance(cff, dict) or cff.get("cff-version") != "1.2.0":
        issues.append(
            OpenScienceValidationIssue(
                "cff_version",
                "CITATION.cff must declare CFF 1.2.0",
                ValidationSeverity.FAILED,
                "metadata/CITATION.cff",
            )
        )
    elif (
        cff.get("title") != expected["title"]
        or cff.get("version") != expected["version"]
        or _license_uri(str(cff.get("license"))) != expected["license"]
        or not isinstance(cff.get("authors"), list)
        or not cff["authors"]
    ):
        issues.append(
            OpenScienceValidationIssue(
                "cff_consistency",
                "CFF title/version/license/authors differ from shared metadata",
                ValidationSeverity.FAILED,
                "metadata/CITATION.cff",
            )
        )
    if (
        not isinstance(contributions, dict)
        or contributions.get("object_identifier") != expected["identifier"]
        or not isinstance(contributions.get("contributors"), list)
        or not contributions["contributors"]
    ):
        issues.append(
            OpenScienceValidationIssue(
                "credit_consistency",
                "CRediT metadata is missing or references another object",
                ValidationSeverity.FAILED,
                "metadata/contributions.json",
            )
        )
    else:
        for contributor in contributions["contributors"]:
            for role in contributor.get("roles", []):
                if role.get("name") not in CREDIT_ROLE_URIS or CREDIT_ROLE_URIS[
                    role["name"]
                ] != role.get("uri"):
                    issues.append(
                        OpenScienceValidationIssue(
                            "credit_role",
                            f"unknown or inconsistent CRediT role: {role}",
                            ValidationSeverity.FAILED,
                            "metadata/contributions.json",
                        )
                    )
    if not isinstance(datacite, dict) or datacite.get("schemaVersion") != "4.7":
        issues.append(
            OpenScienceValidationIssue(
                "datacite_version",
                "DataCite draft must declare schema version 4.7",
                ValidationSeverity.FAILED,
                "metadata/datacite-4.7-draft.json",
            )
        )
    else:
        alternate = datacite.get("alternateIdentifiers", [])
        alternate_values = {
            item.get("alternateIdentifier")
            for item in alternate
            if isinstance(item, dict)
        }
        if expected["identifier"] not in alternate_values:
            issues.append(
                OpenScienceValidationIssue(
                    "datacite_identifier",
                    "DataCite draft does not carry the shared object identifier",
                    ValidationSeverity.FAILED,
                    "metadata/datacite-4.7-draft.json",
                )
            )
        deposit_ready = datacite.get("depositReady")
        identifier = datacite.get("identifier")
        if deposit_ready is True:
            doi = identifier.get("identifier") if isinstance(identifier, dict) else None
            if not isinstance(doi, str) or not _DOI_RE.fullmatch(doi):
                issues.append(
                    OpenScienceValidationIssue(
                        "datacite_deposit_readiness",
                        "depositReady requires a real DOI-shaped identifier",
                        ValidationSeverity.FAILED,
                        "metadata/datacite-4.7-draft.json",
                    )
                )
        elif identifier is not None:
            issues.append(
                OpenScienceValidationIssue(
                    "datacite_draft_truth",
                    "non-deposit-ready DataCite draft must not invent an identifier",
                    ValidationSeverity.FAILED,
                    "metadata/datacite-4.7-draft.json",
                )
            )
    return not any(
        issue.severity is ValidationSeverity.FAILED
        for issue in issues[before:]
    )


def _validate_spdx(
    payload: Any,
    issues: list[OpenScienceValidationIssue],
) -> bool:
    before = len(issues)
    if (
        not isinstance(payload, dict)
        or payload.get("@context") != SPDX_CONTEXT
        or not isinstance(payload.get("@graph"), list)
    ):
        issues.append(
            OpenScienceValidationIssue(
                "spdx_shape",
                "SPDX 3.0.1 JSON-LD requires the official context and @graph",
                ValidationSeverity.FAILED,
                "supply-chain/spdx-3.0.1-sbom.jsonld",
            )
        )
        return False
    graph = payload["@graph"]
    types = {
        node.get("type")
        for node in graph
        if isinstance(node, dict) and isinstance(node.get("type"), str)
    }
    required_types = {
        "CreationInfo",
        "Agent",
        "software_Package",
        "software_Sbom",
        "SpdxDocument",
        "build_Build",
        "simplelicensing_LicenseExpression",
        "Relationship",
    }
    missing = sorted(required_types - types)
    if missing:
        issues.append(
            OpenScienceValidationIssue(
                "spdx_elements",
                f"SPDX document lacks required elements: {', '.join(missing)}",
                ValidationSeverity.FAILED,
                "supply-chain/spdx-3.0.1-sbom.jsonld",
            )
        )
    relationships = [
        node
        for node in graph
        if isinstance(node, dict) and node.get("type") == "Relationship"
    ]
    relationship_types = {
        relationship.get("relationshipType") for relationship in relationships
    }
    required_relationships = {
        "hasDeclaredLicense",
        "hasConcludedLicense",
        "hasOutput",
        "invokedBy",
    }
    if not required_relationships.issubset(relationship_types):
        issues.append(
            OpenScienceValidationIssue(
                "spdx_relationships",
                "SPDX licensing/build relationships are incomplete",
                ValidationSeverity.FAILED,
                "supply-chain/spdx-3.0.1-sbom.jsonld",
            )
        )
    return not any(
        issue.severity is ValidationSeverity.FAILED
        for issue in issues[before:]
    )


def _validate_slsa(
    root: Path,
    payload: Any,
    attestation: Any,
    issues: list[OpenScienceValidationIssue],
) -> bool:
    before = len(issues)
    if (
        not isinstance(payload, dict)
        or payload.get("_type") != IN_TOTO_STATEMENT
        or payload.get("predicateType") != SLSA_PREDICATE
    ):
        issues.append(
            OpenScienceValidationIssue(
                "slsa_shape",
                "SLSA provenance must be an in-toto Statement using predicate v1",
                ValidationSeverity.FAILED,
                "supply-chain/slsa-provenance.json",
            )
        )
        return False
    predicate = payload.get("predicate")
    if not isinstance(predicate, dict):
        predicate = {}
    definition = predicate.get("buildDefinition")
    details = predicate.get("runDetails")
    if (
        not isinstance(definition, dict)
        or not definition.get("buildType")
        or not isinstance(definition.get("externalParameters"), dict)
        or not isinstance(details, dict)
        or not isinstance(details.get("builder"), dict)
        or not details["builder"].get("id")
    ):
        issues.append(
            OpenScienceValidationIssue(
                "slsa_required_fields",
                "SLSA buildDefinition/runDetails/builder fields are incomplete",
                ValidationSeverity.FAILED,
                "supply-chain/slsa-provenance.json",
            )
        )
    for subject in payload.get("subject", []):
        if not isinstance(subject, dict):
            continue
        name = subject.get("name")
        digest = subject.get("digest", {}).get("sha256")
        if (
            not isinstance(name, str)
            or not isinstance(digest, str)
            or not (root / name).is_file()
            or file_hash(root / name) != digest
        ):
            issues.append(
                OpenScienceValidationIssue(
                    "slsa_subject",
                    f"SLSA subject is missing or hash-mismatched: {name}",
                    ValidationSeverity.FAILED,
                    "supply-chain/slsa-provenance.json",
                )
            )
    if (
        not isinstance(attestation, dict)
        or attestation.get("signed") is not False
        or attestation.get("slsa_level_claimed") is not None
        or attestation.get("scientific_result_attestation") is not False
    ):
        issues.append(
            OpenScienceValidationIssue(
                "slsa_claim_boundary",
                "unsigned local provenance must not claim a SLSA level or scientific truth",
                ValidationSeverity.FAILED,
                "supply-chain/attestation-policy.json",
            )
        )
    return not any(
        issue.severity is ValidationSeverity.FAILED
        for issue in issues[before:]
    )


def _validate_view_policy(
    policy: Any,
    view: ResearchObjectView,
    issues: list[OpenScienceValidationIssue],
) -> bool:
    before = len(issues)
    if not isinstance(policy, dict) or policy.get("view") != view.value:
        issues.append(
            OpenScienceValidationIssue(
                "view_policy",
                "export policy view does not match the materialized directory",
                ValidationSeverity.FAILED,
                "export-policy.json",
            )
        )
        return False
    if policy.get("publication_performed") is not False:
        issues.append(
            OpenScienceValidationIssue(
                "publication_side_effect",
                "local export must not claim that publication was performed",
                ValidationSeverity.FAILED,
                "export-policy.json",
            )
        )
    if view is ResearchObjectView.PUBLIC:
        if policy.get("publication_approved") is not True or not isinstance(
            policy.get("publication_approval"), dict
        ):
            issues.append(
                OpenScienceValidationIssue(
                    "publication_approval",
                    "public view requires explicit scoped human approval",
                    ValidationSeverity.FAILED,
                    "export-policy.json",
                )
            )
        for item in policy.get("artifact_policies", []):
            if isinstance(item, dict) and item.get("license") not in PUBLIC_LICENSE_IDS:
                issues.append(
                    OpenScienceValidationIssue(
                        "public_license",
                        f"public artifact has a non-public license: {item.get('crate_path')}",
                        ValidationSeverity.FAILED,
                        "export-policy.json",
                    )
                )
    elif policy.get("publication_approved") is not False:
        issues.append(
            OpenScienceValidationIssue(
                "nonpublic_approval",
                "internal and review views must not carry publication approval",
                ValidationSeverity.FAILED,
                "export-policy.json",
            )
        )
    return not any(
        issue.severity is ValidationSeverity.FAILED
        for issue in issues[before:]
    )


def _scan_sensitive_content(
    root: Path,
    view: ResearchObjectView,
    issues: list[OpenScienceValidationIssue],
) -> bool:
    before = len(issues)
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if any(fragment in path.name.casefold() for fragment in _SECRET_NAME_FRAGMENTS):
            issues.append(
                OpenScienceValidationIssue(
                    "secret_filename",
                    "secret-like filename is not allowed in any export view",
                    ValidationSeverity.FAILED,
                    relative,
                )
            )
            continue
        if path.stat().st_size > 5 * 1024 * 1024:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in _SECRET_PATTERNS:
            if pattern.search(text):
                issues.append(
                    OpenScienceValidationIssue(
                        "secret_content",
                        "secret-like content detected",
                        ValidationSeverity.FAILED,
                        relative,
                    )
                )
                break
        if _contains_private_path(text):
            severity = (
                ValidationSeverity.WARNING
                if view is ResearchObjectView.INTERNAL
                else ValidationSeverity.FAILED
            )
            issues.append(
                OpenScienceValidationIssue(
                    "private_path",
                    "private absolute path detected",
                    severity,
                    relative,
                )
            )
    return not any(
        issue.severity is ValidationSeverity.FAILED
        for issue in issues[before:]
    )


def _scan_source_file(path: Path) -> list[str]:
    findings: list[str] = []
    if any(fragment in path.name.casefold() for fragment in _SECRET_NAME_FRAGMENTS):
        findings.append("secret-like filename")
    if path.stat().st_size > 5 * 1024 * 1024:
        findings.append("content exceeds the bounded sensitive-scan limit")
        return findings
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return findings
    if _contains_private_path(text):
        findings.append("private absolute path")
    if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
        findings.append("secret-like content")
    return findings


def _validate_hash_manifest(
    root: Path,
    issues: list[OpenScienceValidationIssue],
) -> bool:
    before = len(issues)
    path = root / "manifest-sha256.json"
    if not path.is_file():
        return False
    payload = _load_json_checked(path, issues, "hash_manifest_json")
    if not isinstance(payload, dict) or not isinstance(payload.get("files"), list):
        return False
    expected_paths = {
        item.relative_to(root).as_posix()
        for item in root.rglob("*")
        if item.is_file()
        and item.name not in {"manifest-sha256.json", "validation-report.json"}
    }
    declared_paths: set[str] = set()
    for record in payload["files"]:
        if not isinstance(record, dict):
            continue
        relative = record.get("path")
        digest = record.get("sha256")
        if not isinstance(relative, str) or not isinstance(digest, str):
            continue
        declared_paths.add(relative)
        candidate = root / relative
        if (
            not candidate.is_file()
            or not _SHA256_RE.fullmatch(digest)
            or file_hash(candidate) != digest
        ):
            issues.append(
                OpenScienceValidationIssue(
                    "hash_manifest_entry",
                    f"manifest hash mismatch: {relative}",
                    ValidationSeverity.FAILED,
                    relative,
                )
            )
    if expected_paths != declared_paths:
        issues.append(
            OpenScienceValidationIssue(
                "hash_manifest_coverage",
                "hash manifest does not cover every non-report export file",
                ValidationSeverity.FAILED,
                "manifest-sha256.json",
            )
        )
    return not any(
        issue.severity is ValidationSeverity.FAILED
        for issue in issues[before:]
    )


def _load_json_checked(
    path: Path,
    issues: list[OpenScienceValidationIssue],
    check: str,
) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        issues.append(
            OpenScienceValidationIssue(
                check,
                f"invalid JSON: {exc}",
                ValidationSeverity.FAILED,
                path.as_posix(),
            )
        )
        return None


def _load_yaml_checked(
    path: Path,
    issues: list[OpenScienceValidationIssue],
) -> Any:
    if not path.is_file():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        issues.append(
            OpenScienceValidationIssue(
                "cff_yaml",
                f"invalid CFF YAML: {exc}",
                ValidationSeverity.FAILED,
                path.as_posix(),
            )
        )
        return None


def _write_hash_manifest(root: Path, path: Path) -> None:
    records = [
        {
            "path": item.relative_to(root).as_posix(),
            "sha256": file_hash(item),
            "size_bytes": item.stat().st_size,
        }
        for item in sorted(candidate for candidate in root.rglob("*") if candidate.is_file())
        if item.name not in {"manifest-sha256.json", "validation-report.json"}
    ]
    _write_json(
        path,
        {
            "schema_version": 1,
            "algorithm": "sha256",
            "excluded": ["manifest-sha256.json", "validation-report.json"],
            "files": records,
        },
    )


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_yaml(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            dict(payload),
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        ),
        encoding="utf-8",
        newline="\n",
    )


def _sanitize_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            (
                f"redacted_field_{_short_digest(str(key))}"
                if _secret_key(str(key))
                else str(key)
            ): ("[REDACTED]" if _secret_key(str(key)) else _sanitize_json(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_json(item) for item in value]
    if isinstance(value, str) and _contains_private_path(value):
        return f"urn:autoresearch:redacted-path:{_short_digest(value)}"
    return value


def _secret_key(value: str) -> bool:
    normalized = value.casefold().replace("-", "_")
    return any(
        fragment in normalized
        for fragment in (
            "api_key",
            "apikey",
            "credential",
            "password",
            "private_key",
            "secret",
            "token",
        )
    )


def _contains_private_path(text: str) -> bool:
    return bool(
        _WINDOWS_PATH_RE.search(text) or _POSIX_PRIVATE_PATH_RE.search(text)
    )


def _safe_relative_path(value: str) -> str:
    path = Path(value.replace("\\", "/"))
    if not value.strip() or path.is_absolute() or ".." in path.parts:
        raise OpenScienceExportError(f"unsafe crate path: {value}")
    normalized = path.as_posix()
    if normalized.casefold() in _GENERATED_CRATE_PATH_KEYS:
        raise OpenScienceExportError(
            f"artifact path collides with generated metadata: {normalized}"
        )
    return normalized


def _require_utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise OpenScienceExportError(f"{label} must be timezone-aware UTC")
    return value.astimezone(timezone.utc)


def _license_uri(license_id: str) -> str:
    if license_id.startswith("http://") or license_id.startswith("https://"):
        return license_id
    if license_id.startswith("LicenseRef-"):
        return f"urn:spdx:{license_id}"
    return f"https://spdx.org/licenses/{license_id}"


def _aggregate_artifact_digest(
    artifacts: Sequence[_MaterializedArtifact],
) -> str:
    payload = "\n".join(
        f"{artifact.crate_path}\0{artifact.exported_sha256}"
        for artifact in sorted(artifacts, key=lambda item: item.crate_path)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _short_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _tool_identifier(
    metadata: ResearchObjectMetadata,
    activity: Activity,
) -> str:
    return (
        f"{metadata.repository_url.rstrip('/')}"
        f"#autoresearch-tool-{_short_digest(activity.activity_id)}"
    )


def _wrroc_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def _spdx_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _id_values(value: Any) -> set[str]:
    return {
        str(item["@id"])
        for item in _as_list(value)
        if isinstance(item, dict) and isinstance(item.get("@id"), str)
    }


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _walk_id_references(value: Any) -> list[str]:
    references: list[str] = []
    if isinstance(value, dict):
        if set(value) == {"@id"} and isinstance(value["@id"], str):
            references.append(value["@id"])
        else:
            for item in value.values():
                references.extend(_walk_id_references(item))
    elif isinstance(value, list):
        for item in value:
            references.extend(_walk_id_references(item))
    return references


_REPRODUCE_SCRIPT = '''\
"""Pure-standard-library verifier for one exported research object."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _pointer(document: Any, pointer: str) -> Any:
    current = document
    for token in pointer.lstrip("/").split("/"):
        decoded = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(decoded)]
        elif isinstance(current, dict):
            current = current[decoded]
        else:
            raise KeyError(pointer)
    return current


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="reproduction/reproduction-result.json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    plan = json.loads(
        (root / "reproduction/reproduction-plan.json").read_text(encoding="utf-8")
    )
    failures: list[str] = []
    checked_files = 0
    for record in plan["files"]:
        path = root / record["path"]
        checked_files += 1
        if not path.is_file():
            failures.append(f"missing file: {record['path']}")
        elif _sha256(path) != record["sha256"]:
            failures.append(f"hash mismatch: {record['path']}")
    documents: dict[str, Any] = {}
    for assertion in plan["assertions"]:
        path = assertion["path"]
        if path not in documents:
            documents[path] = json.loads((root / path).read_text(encoding="utf-8"))
        try:
            actual = _pointer(documents[path], assertion["json_pointer"])
        except (KeyError, IndexError, ValueError) as exc:
            failures.append(f"{assertion['label']}: missing pointer ({exc})")
            continue
        if actual != assertion["expected"]:
            failures.append(
                f"{assertion['label']}: expected {assertion['expected']!r}, "
                f"got {actual!r}"
            )
    result = {
        "status": "failed" if failures else "passed",
        "scope": plan["scope"],
        "scientific_experiment_reexecuted": False,
        "checked_files": checked_files,
        "assertion_count": len(plan["assertions"]),
        "failures": failures,
    }
    output = root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\\n",
        encoding="utf-8",
    )
    print(json.dumps(result, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
'''
