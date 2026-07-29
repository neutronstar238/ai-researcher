"""Evidence-bound child-paper package for task 261.2.4.

The package is generated only from the hash-valid task 261.2 foundation and
one-shot confirmatory endpoint.  It deliberately reports the retained negative
result, requires every manuscript paragraph to be a typed claim, checks every
named work and display item, rebuilds deterministic paper sources in a clean
directory, and never grants submission or publication authority.
"""

from __future__ import annotations

import json
import re
import shutil
from collections import Counter
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal

import requests
from pydantic import Field, field_validator, model_validator
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from autoresearch.campaign.mechanism_confirmatory import (
    MechanismConfirmatoryEndpoint,
    MechanismConfirmatoryManifest,
    MechanismConfirmatoryPreregistration,
    MechanismConfirmatoryTaskResult,
    MechanismReproductionReport,
    MechanismScientificOutcome,
    load_mechanism_confirmatory,
    load_mechanism_confirmatory_preregistration,
)
from autoresearch.campaign.mechanism_round import (
    ClaimEvidenceKind,
    ClaimEvidenceLink,
    ClaimEvidenceRequirement,
    ClaimKind,
    LiteratureArea,
    ManuscriptClaimEvidenceAudit,
    MechanismLiteratureSource,
    MechanismResearchBrief,
    load_mechanism_foundation,
)
from autoresearch.competition.manifest import write_json_model
from autoresearch.kernel.contracts import (
    KernelContract,
    NonEmptyText,
    Sha256,
    StableId,
    canonical_sha256,
)
from autoresearch.reports.figures import (
    FigureArtifact,
    generate_flow_diagram_figure,
    generate_metric_bar_figure,
)
from autoresearch.reports.paper_build import (
    LatexPaperBuildArtifact,
    LatexPaperBuildStatus,
    build_latex_paper_from_markdown,
)
from autoresearch.schemas import file_hash

_PAPER_SCHEMA_VERSION = "mechanism-child-paper-v1"
_EXPECTED_SOURCE_COUNT = 14
_EXPECTED_TASK_COUNT = 6
_EXPECTED_FIGURE_COUNT = 5
_SOURCE_TOKEN = re.compile(r"\[(source-\d{3})\]")
_REFERENCE_LINE = re.compile(r"^[-*]\s+\[(source-\d{3})\]\s+")
_PAPER_SECTIONS = (
    "Abstract",
    "Introduction",
    "Related Work",
    "Method",
    "Experiments",
    "Results",
    "Limitations",
    "Conclusion",
)
_REQUIRED_EVIDENCE_BY_KIND = {
    ClaimKind.NAMED_PRIOR_WORK: (ClaimEvidenceKind.VERIFIED_LITERATURE,),
    ClaimKind.METHOD: (
        ClaimEvidenceKind.GENERATED_CODE,
        ClaimEvidenceKind.PREREGISTERED_PROTOCOL,
    ),
    ClaimKind.EXPERIMENT: (
        ClaimEvidenceKind.PREREGISTERED_PROTOCOL,
        ClaimEvidenceKind.EXECUTION_ARTIFACT,
    ),
    ClaimKind.RESULT: (
        ClaimEvidenceKind.METRIC,
        ClaimEvidenceKind.ADJUDICATION,
    ),
    ClaimKind.LIMITATION: (ClaimEvidenceKind.FAILURE_OR_UNCERTAINTY,),
    ClaimKind.FIGURE_DESCRIPTION: (
        ClaimEvidenceKind.FIGURE_ARTIFACT,
        ClaimEvidenceKind.METRIC,
    ),
}

PaperSection = Literal[
    "Abstract",
    "Introduction",
    "Related Work",
    "Method",
    "Experiments",
    "Results",
    "Limitations",
    "Conclusion",
]


class MechanismPaperIntegrityError(ValueError):
    """Raised when child-paper evidence, claims, or artifacts are inconsistent."""


class MechanismPaperStatus(str, Enum):
    """Terminal local status for the child-paper package."""

    NEGATIVE_RESULT_PAPER_BUILT = "negative_result_paper_built"
    NEGATIVE_RESULT_PAPER_BUILT_WITH_QUALITY_ISSUES = (
        "negative_result_paper_built_with_quality_issues"
    )


class MechanismPaperEvidenceRecord(KernelContract):
    """One typed, hash-bound evidence item admitted by the paper audit."""

    evidence_id: StableId
    evidence_kind: ClaimEvidenceKind
    artifact_path: NonEmptyText
    json_pointer: NonEmptyText | None = None
    evidence_hash: Sha256
    support_statement: NonEmptyText
    verified: bool


class MechanismPaperClaimRecord(KernelContract):
    """One material manuscript paragraph and its required evidence IDs."""

    claim_id: StableId
    claim_kind: ClaimKind
    section: PaperSection
    claim_text: NonEmptyText
    evidence_ids: list[StableId] = Field(min_length=1)
    citation_source_ids: list[StableId] = Field(default_factory=list)

    @field_validator("evidence_ids", "citation_source_ids")
    @classmethod
    def _normalize_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("claim record IDs must be unique")
        return sorted(value)

    @model_validator(mode="after")
    def _validate_named_work(self) -> MechanismPaperClaimRecord:
        if self.claim_kind is ClaimKind.NAMED_PRIOR_WORK:
            if len(self.citation_source_ids) != 1:
                raise ValueError("named-work claims require exactly one source ID")
            token = f"[{self.citation_source_ids[0]}]"
            if token not in self.claim_text:
                raise ValueError("named-work claim lacks its source token")
        elif self.citation_source_ids:
            raise ValueError("only named-work claims may carry citation source IDs")
        return self


class MechanismClaimEntailmentCheck(KernelContract):
    """Deterministic entailment checks for one rendered claim paragraph."""

    claim_id: StableId
    manuscript_occurrences: int = Field(ge=0)
    evidence_ids_resolved: bool
    typed_evidence_complete: bool
    frozen_source_text_present: bool
    passed: bool


class MechanismClaimEntailmentReport(KernelContract):
    """Coverage and entailment verdict over every material manuscript paragraph."""

    schema_version: Literal["mechanism-claim-entailment-v1"] = (
        "mechanism-claim-entailment-v1"
    )
    manuscript_sha256: Sha256
    registered_claim_count: int = Field(ge=1)
    rendered_material_paragraph_count: int = Field(ge=1)
    checks: list[MechanismClaimEntailmentCheck] = Field(min_length=1)
    unregistered_paragraph_hashes: list[Sha256]
    missing_claim_ids: list[StableId]
    passed: bool
    report_hash: Sha256

    @field_validator("unregistered_paragraph_hashes", "missing_claim_ids")
    @classmethod
    def _normalize_failures(cls, value: list[str]) -> list[str]:
        return sorted(value)

    @model_validator(mode="after")
    def _validate_hash(self) -> MechanismClaimEntailmentReport:
        if self.report_hash != self.calculated_hash():
            raise MechanismPaperIntegrityError("claim-entailment report hash mismatch")
        expected = (
            all(check.passed for check in self.checks)
            and not self.unregistered_paragraph_hashes
            and not self.missing_claim_ids
            and self.registered_claim_count == self.rendered_material_paragraph_count
        )
        if self.passed != expected:
            raise ValueError("claim-entailment verdict contradicts its checks")
        return self

    def calculated_hash(self) -> str:
        """Recompute the report digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"report_hash"})
        )


class MechanismCitationAudit(KernelContract):
    """Named-work, bibliography, adjacent-work, and reachability audit."""

    schema_version: Literal["mechanism-paper-citation-audit-v1"] = (
        "mechanism-paper-citation-audit-v1"
    )
    research_brief_hash: Sha256
    manuscript_sha256: Sha256
    source_reachability_sha256: Sha256
    source_count: int = Field(ge=1)
    inline_source_ids: list[StableId]
    reference_source_ids: list[StableId]
    named_claim_source_ids: list[StableId]
    missing_inline_ids: list[StableId]
    missing_reference_ids: list[StableId]
    missing_named_claim_ids: list[StableId]
    area_source_counts: dict[str, int]
    all_sources_reachable: bool
    live_source_check_performed: bool
    adequate_adjacent_work_coverage: bool
    passed: bool
    audit_hash: Sha256

    @field_validator(
        "inline_source_ids",
        "reference_source_ids",
        "named_claim_source_ids",
        "missing_inline_ids",
        "missing_reference_ids",
        "missing_named_claim_ids",
    )
    @classmethod
    def _normalize_source_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("citation source IDs must be unique")
        return sorted(value)

    @model_validator(mode="after")
    def _validate_hash(self) -> MechanismCitationAudit:
        if self.audit_hash != self.calculated_hash():
            raise MechanismPaperIntegrityError("citation audit hash mismatch")
        expected = (
            not self.missing_inline_ids
            and not self.missing_reference_ids
            and not self.missing_named_claim_ids
            and self.all_sources_reachable
            and self.adequate_adjacent_work_coverage
        )
        if self.passed != expected:
            raise ValueError("citation verdict contradicts citation checks")
        return self

    def calculated_hash(self) -> str:
        """Recompute the citation-audit digest."""

        return canonical_sha256(self.model_dump(mode="json", exclude={"audit_hash"}))


class MechanismFigureTableAudit(KernelContract):
    """Source, metric, caption, and table consistency for paper displays."""

    schema_version: Literal["mechanism-paper-display-audit-v1"] = (
        "mechanism-paper-display-audit-v1"
    )
    endpoint_hash: Sha256
    manuscript_sha256: Sha256
    figure_count: int = Field(ge=0)
    table_count: int = Field(ge=0)
    figure_file_sha256s: dict[str, Sha256]
    table_file_sha256s: dict[str, Sha256]
    checks: dict[str, bool]
    failures: list[StableId]
    passed: bool
    audit_hash: Sha256

    @field_validator("failures")
    @classmethod
    def _normalize_failures(cls, value: list[str]) -> list[str]:
        return sorted(value)

    @model_validator(mode="after")
    def _validate_hash(self) -> MechanismFigureTableAudit:
        if self.audit_hash != self.calculated_hash():
            raise MechanismPaperIntegrityError("figure/table audit hash mismatch")
        expected_failures = sorted(
            name for name, passed in self.checks.items() if not passed
        )
        if self.failures != expected_failures or self.passed != (not expected_failures):
            raise ValueError("figure/table verdict contradicts display checks")
        return self

    def calculated_hash(self) -> str:
        """Recompute the display-audit digest."""

        return canonical_sha256(self.model_dump(mode="json", exclude={"audit_hash"}))


class MechanismChildRoundReport(KernelContract):
    """Content-addressed report of the immutable child scientific endpoint."""

    schema_version: Literal["mechanism-child-round-report-v1"] = (
        "mechanism-child-round-report-v1"
    )
    run_id: StableId
    parent_endpoint_hash: Sha256
    development_manifest_hash: Sha256
    confirmatory_manifest_hash: Sha256
    endpoint_hash: Sha256
    scientific_projection_hash: Sha256
    outcome: Literal["negative_result"] = "negative_result"
    task_count: int = Field(ge=1)
    claim_count: int = Field(ge=1)
    accepted_count: int = Field(ge=0)
    abstained_count: int = Field(ge=0)
    accepted_unsupported_count: int = Field(ge=0)
    coverage: float = Field(ge=0.0, le=1.0)
    coverage_ci95_lower: float = Field(ge=0.0, le=1.0)
    coverage_ci95_upper: float = Field(ge=0.0, le=1.0)
    minimum_coverage: float = Field(ge=0.0, le=1.0)
    unsupported_claim_rate: float = Field(ge=0.0, le=1.0)
    unsupported_rate_ci95_lower: float = Field(ge=0.0, le=1.0)
    unsupported_rate_ci95_upper: float = Field(ge=0.0, le=1.0)
    maximum_unsupported_claim_rate: float = Field(ge=0.0, le=1.0)
    failure_codes: list[StableId] = Field(min_length=1)
    verdict_rewritten: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    report_hash: Sha256

    @model_validator(mode="after")
    def _validate_report(self) -> MechanismChildRoundReport:
        if self.abstained_count != self.claim_count - self.accepted_count:
            raise ValueError("round-report abstention count is inconsistent")
        if self.coverage >= self.minimum_coverage:
            raise ValueError("negative child report no longer reflects coverage failure")
        if self.unsupported_claim_rate > self.maximum_unsupported_claim_rate:
            raise ValueError("child report misstates the unsupported-risk gate")
        if "minimum_coverage_met" not in self.failure_codes:
            raise ValueError("child report omits the frozen coverage failure")
        if self.report_hash != self.calculated_hash():
            raise MechanismPaperIntegrityError("child round-report hash mismatch")
        return self

    def calculated_hash(self) -> str:
        """Recompute the child-round report digest."""

        return canonical_sha256(self.model_dump(mode="json", exclude={"report_hash"}))


class MechanismPaperReproductionReport(KernelContract):
    """Independent source rebuild and PDF-quality comparison."""

    schema_version: Literal["mechanism-paper-reproduction-v1"] = (
        "mechanism-paper-reproduction-v1"
    )
    endpoint_hash: Sha256
    scientific_projection_hash: Sha256
    confirmatory_reproduction_passed: bool
    source_file_count: int = Field(ge=1)
    matched_source_files: list[NonEmptyText]
    mismatched_source_files: list[NonEmptyText]
    primary_pdf_compiled: bool
    reproduced_pdf_compiled: bool
    primary_pdf_quality_passed: bool
    reproduced_pdf_quality_passed: bool
    primary_page_count: int | None = Field(default=None, ge=1)
    reproduced_page_count: int | None = Field(default=None, ge=1)
    passed: bool
    report_hash: Sha256

    @field_validator("matched_source_files", "mismatched_source_files")
    @classmethod
    def _normalize_paths(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("reproduction paths must be unique")
        return sorted(value)

    @model_validator(mode="after")
    def _validate_hash(self) -> MechanismPaperReproductionReport:
        if self.report_hash != self.calculated_hash():
            raise MechanismPaperIntegrityError("paper reproduction hash mismatch")
        expected = (
            self.confirmatory_reproduction_passed
            and not self.mismatched_source_files
            and len(self.matched_source_files) == self.source_file_count
            and self.primary_pdf_compiled == self.reproduced_pdf_compiled
            and self.primary_pdf_quality_passed
            == self.reproduced_pdf_quality_passed
        )
        if self.passed != expected:
            raise ValueError("paper reproduction verdict contradicts its evidence")
        return self

    def calculated_hash(self) -> str:
        """Recompute the reproduction-report digest."""

        return canonical_sha256(self.model_dump(mode="json", exclude={"report_hash"}))


class MechanismPaperAudit(KernelContract):
    """Final fail-closed paper and submission-readiness audit."""

    schema_version: Literal["mechanism-paper-final-audit-v1"] = (
        "mechanism-paper-final-audit-v1"
    )
    endpoint_hash: Sha256
    manuscript_sha256: Sha256
    checks: dict[str, bool]
    failed_gates: list[StableId]
    faithful_negative_result_reported: bool
    positive_contribution_supported: Literal[False] = False
    submission_readiness_granted: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    verdict: Literal["not_ready"] = "not_ready"
    audit_hash: Sha256

    @field_validator("failed_gates")
    @classmethod
    def _normalize_failures(cls, value: list[str]) -> list[str]:
        return sorted(value)

    @model_validator(mode="after")
    def _validate_audit(self) -> MechanismPaperAudit:
        expected_failures = sorted(
            name for name, passed in self.checks.items() if not passed
        )
        if self.failed_gates != expected_failures:
            raise ValueError("paper audit failed gates contradict checks")
        if not self.faithful_negative_result_reported:
            raise ValueError("paper package must faithfully report the negative result")
        if self.audit_hash != self.calculated_hash():
            raise MechanismPaperIntegrityError("paper final audit hash mismatch")
        return self

    def calculated_hash(self) -> str:
        """Recompute the final paper-audit digest."""

        return canonical_sha256(self.model_dump(mode="json", exclude={"audit_hash"}))


class MechanismPaperManifest(KernelContract):
    """Hash-bound terminal index for the complete local child-paper package."""

    schema_version: Literal["mechanism-paper-manifest-v1"] = (
        "mechanism-paper-manifest-v1"
    )
    package_id: StableId
    created_at: datetime
    status: MechanismPaperStatus
    foundation_manifest_hash: Sha256
    research_brief_hash: Sha256
    confirmatory_manifest_hash: Sha256
    endpoint_hash: Sha256
    scientific_projection_hash: Sha256
    round_report_hash: Sha256
    manuscript_sha256: Sha256
    claim_evidence_audit_hash: Sha256
    entailment_report_hash: Sha256
    citation_audit_hash: Sha256
    display_audit_hash: Sha256
    reproduction_report_hash: Sha256
    paper_audit_hash: Sha256
    manuscript_path: NonEmptyText
    pdf_path: NonEmptyText | None = None
    deliverables_index_path: NonEmptyText
    artifact_file_sha256s: dict[str, Sha256] = Field(min_length=1)
    scientific_outcome: Literal["negative_result"] = "negative_result"
    submission_readiness_granted: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    manifest_hash: Sha256

    @model_validator(mode="after")
    def _validate_manifest(self) -> MechanismPaperManifest:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("paper manifest created_at must be timezone-aware")
        if self.manifest_hash != self.calculated_hash():
            raise MechanismPaperIntegrityError("paper manifest hash mismatch")
        return self

    def calculated_hash(self) -> str:
        """Recompute the package-manifest digest."""

        return canonical_sha256(self.model_dump(mode="json", exclude={"manifest_hash"}))


class MechanismPaperBuildResult(KernelContract):
    """User-facing result for build and status operations."""

    package_dir: NonEmptyText
    status: MechanismPaperStatus
    manifest_hash: Sha256
    endpoint_hash: Sha256
    manuscript_path: NonEmptyText
    pdf_path: NonEmptyText | None
    paper_quality_passed: bool
    claim_coverage_complete: bool
    submission_readiness_granted: Literal[False] = False
    external_submission_authorized: Literal[False] = False


def build_task2612_child_paper(
    *,
    foundation_dir: Path | str,
    confirmatory_dir: Path | str,
    output_dir: Path | str,
    reproduction_dir: Path | str,
    compile_pdf: bool = True,
    live_source_check: bool = False,
) -> MechanismPaperBuildResult:
    """Build, independently reproduce, and audit the task 261.2 child paper."""

    foundation_root = Path(foundation_dir).resolve()
    confirmatory_root = Path(confirmatory_dir).resolve()
    package_root = Path(output_dir).resolve()
    reproduction_root = Path(reproduction_dir).resolve()
    if package_root == reproduction_root:
        raise MechanismPaperIntegrityError(
            "paper package and reproduction directories must differ"
        )
    if (package_root / "paper-manifest.json").is_file():
        return load_task2612_child_paper(package_root)
    _require_absent_or_empty(package_root, "paper package")
    _require_absent_or_empty(reproduction_root, "paper reproduction")

    foundation, parent, brief = load_mechanism_foundation(foundation_root)
    confirmatory = load_mechanism_confirmatory(confirmatory_root)
    preregistration = load_mechanism_confirmatory_preregistration(
        confirmatory_root
    )
    endpoint = MechanismConfirmatoryEndpoint.model_validate_json(
        (confirmatory_root / "endpoint.json").read_text(encoding="utf-8")
    )
    task_results = _load_task_results(confirmatory_root, endpoint)
    confirmatory_reproduction = MechanismReproductionReport.model_validate_json(
        (confirmatory_root / "reproduction" / "report.json").read_text(
            encoding="utf-8"
        )
    )
    _validate_paper_inputs(
        foundation_hash=foundation.manifest_hash,
        research_brief_hash=brief.brief_hash,
        parent_evidence_hash=parent.evidence_hash,
        confirmatory_root=confirmatory_root,
        confirmatory=confirmatory,
        endpoint=endpoint,
        task_results=task_results,
        confirmatory_reproduction=confirmatory_reproduction,
    )

    package_root.mkdir(parents=True, exist_ok=True)
    reproduction_root.mkdir(parents=True, exist_ok=True)
    _copy_frozen_paper_inputs(
        foundation_root=foundation_root,
        confirmatory_root=confirmatory_root,
        package_root=package_root,
    )
    reachability = _source_reachability_snapshot(
        foundation_root=foundation_root,
        brief=brief,
        live_source_check=live_source_check,
    )
    reachability_path = _write_json(
        package_root / "frozen" / "source-reachability.json",
        reachability,
    )
    round_report = _build_round_report(
        parent_endpoint_hash=parent.endpoint_hash,
        development_manifest_hash=preregistration.development_manifest_hash,
        confirmatory=confirmatory,
        endpoint=endpoint,
    )
    round_report_path = package_root / "round-report" / "round-report.json"
    write_json_model(round_report_path, round_report)
    _write_text(
        package_root / "round-report" / "round-report.md",
        _round_report_markdown(round_report),
    )

    primary_core = _render_manuscript_core(
        root=package_root / "manuscript",
        brief=brief,
        endpoint=endpoint,
        preregistration_hash=preregistration.preregistration_hash,
        round_freeze_hash=preregistration.round_freeze_hash,
        confirmatory=confirmatory,
        task_results=task_results,
        reachability=reachability,
        reachability_sha256=file_hash(reachability_path),
        compile_pdf=compile_pdf,
    )
    reproduced_core = _render_manuscript_core(
        root=reproduction_root / "manuscript",
        brief=brief,
        endpoint=endpoint,
        preregistration_hash=preregistration.preregistration_hash,
        round_freeze_hash=preregistration.round_freeze_hash,
        confirmatory=confirmatory,
        task_results=task_results,
        reachability=reachability,
        reachability_sha256=file_hash(reachability_path),
        compile_pdf=compile_pdf,
    )
    reproduction = _build_paper_reproduction_report(
        endpoint=endpoint,
        confirmatory_reproduction=confirmatory_reproduction,
        primary=primary_core,
        reproduced=reproduced_core,
    )
    reproduction_path = package_root / "reproduction" / "paper-reproduction.json"
    write_json_model(reproduction_path, reproduction)
    _write_text(
        package_root / "reproduction" / "paper-reproduction.md",
        _paper_reproduction_markdown(reproduction),
    )

    final_audit = _build_final_paper_audit(
        endpoint=endpoint,
        primary=primary_core,
        reproduction=reproduction,
    )
    final_audit_path = package_root / "audit" / "paper-audit.json"
    write_json_model(final_audit_path, final_audit)
    _write_text(
        package_root / "audit" / "paper-audit.md",
        _paper_audit_markdown(final_audit),
    )
    deliverables_path = _write_text(
        package_root / "deliverables" / "index.md",
        _deliverables_markdown(
            endpoint=endpoint,
            primary=primary_core,
            final_audit=final_audit,
        ),
    )
    _write_text(
        package_root / "deliverables" / "EXTERNAL-SUBMISSION-BLOCKED.md",
        (
            "# External submission is blocked\n\n"
            "This package reports an immutable negative confirmatory endpoint. "
            "It has no verified human authorship decision, third-party license "
            "review, venue decision, or explicit submission approval. No upload, "
            "public release, or external submission is authorized.\n"
        ),
    )

    artifact_hashes = _relative_file_hashes(package_root)
    paper_build = primary_core["paper_build"]
    assert isinstance(paper_build, LatexPaperBuildArtifact)
    status = (
        MechanismPaperStatus.NEGATIVE_RESULT_PAPER_BUILT
        if paper_build.quality.passed
        else MechanismPaperStatus.NEGATIVE_RESULT_PAPER_BUILT_WITH_QUALITY_ISSUES
    )
    manifest_values: dict[str, Any] = {
        "schema_version": "mechanism-paper-manifest-v1",
        "package_id": package_root.name,
        "created_at": datetime.now(timezone.utc),
        "status": status,
        "foundation_manifest_hash": foundation.manifest_hash,
        "research_brief_hash": brief.brief_hash,
        "confirmatory_manifest_hash": confirmatory.manifest_hash,
        "endpoint_hash": endpoint.endpoint_hash,
        "scientific_projection_hash": endpoint.scientific_projection_hash,
        "round_report_hash": round_report.report_hash,
        "manuscript_sha256": primary_core["manuscript_sha256"],
        "claim_evidence_audit_hash": primary_core["claim_audit"].audit_hash,
        "entailment_report_hash": primary_core["entailment"].report_hash,
        "citation_audit_hash": primary_core["citation_audit"].audit_hash,
        "display_audit_hash": primary_core["display_audit"].audit_hash,
        "reproduction_report_hash": reproduction.report_hash,
        "paper_audit_hash": final_audit.audit_hash,
        "manuscript_path": "manuscript/manuscript.md",
        "pdf_path": (
            _relative_path(package_root, Path(paper_build.pdf_path))
            if paper_build.pdf_path is not None
            else None
        ),
        "deliverables_index_path": _relative_path(
            package_root,
            deliverables_path,
        ),
        "artifact_file_sha256s": artifact_hashes,
        "scientific_outcome": "negative_result",
        "submission_readiness_granted": False,
        "external_submission_authorized": False,
    }
    normalized_manifest = MechanismPaperManifest.model_construct(
        **manifest_values
    ).model_dump(mode="json", exclude={"manifest_hash"})
    normalized_manifest["manifest_hash"] = canonical_sha256(normalized_manifest)
    manifest = MechanismPaperManifest.model_validate(normalized_manifest)
    write_json_model(package_root / "paper-manifest.json", manifest)
    return _paper_result(package_root, manifest, primary_core)


def load_task2612_child_paper(
    output_dir: Path | str,
) -> MechanismPaperBuildResult:
    """Verify every recorded paper artifact and recompute semantic audits."""

    root = Path(output_dir).resolve()
    manifest = MechanismPaperManifest.model_validate_json(
        (root / "paper-manifest.json").read_text(encoding="utf-8")
    )
    current_hashes = _relative_file_hashes(root)
    if current_hashes != manifest.artifact_file_sha256s:
        raise MechanismPaperIntegrityError("paper package artifact index mismatch")
    round_report = MechanismChildRoundReport.model_validate_json(
        (root / "round-report" / "round-report.json").read_text(encoding="utf-8")
    )
    _validate_loaded_frozen_chain(
        root=root,
        manifest=manifest,
        round_report=round_report,
    )
    claim_audit = ManuscriptClaimEvidenceAudit.model_validate_json(
        (root / "manuscript" / "evidence" / "claim-evidence-audit.json").read_text(
            encoding="utf-8"
        )
    )
    entailment = MechanismClaimEntailmentReport.model_validate_json(
        (root / "manuscript" / "evidence" / "entailment-audit.json").read_text(
            encoding="utf-8"
        )
    )
    citation_audit = MechanismCitationAudit.model_validate_json(
        (root / "manuscript" / "audit" / "citation-audit.json").read_text(
            encoding="utf-8"
        )
    )
    display_audit = MechanismFigureTableAudit.model_validate_json(
        (root / "manuscript" / "audit" / "figure-table-audit.json").read_text(
            encoding="utf-8"
        )
    )
    reproduction = MechanismPaperReproductionReport.model_validate_json(
        (root / "reproduction" / "paper-reproduction.json").read_text(
            encoding="utf-8"
        )
    )
    final_audit = MechanismPaperAudit.model_validate_json(
        (root / "audit" / "paper-audit.json").read_text(encoding="utf-8")
    )
    manuscript_path = root / manifest.manuscript_path
    if file_hash(manuscript_path) != manifest.manuscript_sha256:
        raise MechanismPaperIntegrityError("paper manuscript hash mismatch")
    expected_hashes = {
        "round_report_hash": round_report.report_hash,
        "claim_evidence_audit_hash": claim_audit.audit_hash,
        "entailment_report_hash": entailment.report_hash,
        "citation_audit_hash": citation_audit.audit_hash,
        "display_audit_hash": display_audit.audit_hash,
        "reproduction_report_hash": reproduction.report_hash,
        "paper_audit_hash": final_audit.audit_hash,
    }
    for field_name, expected in expected_hashes.items():
        if getattr(manifest, field_name) != expected:
            raise MechanismPaperIntegrityError(
                f"paper manifest {field_name} mismatch"
            )
    _revalidate_claim_and_display_audits(
        root=root,
        manifest=manifest,
        claim_audit=claim_audit,
        entailment=entailment,
        citation_audit=citation_audit,
        display_audit=display_audit,
    )
    if manifest.submission_readiness_granted or manifest.external_submission_authorized:
        raise MechanismPaperIntegrityError("paper package unexpectedly grants submission")
    paper_build = _load_paper_build(root / "manuscript" / "build")
    primary: dict[str, Any] = {
        "paper_build": paper_build,
        "claim_audit": claim_audit,
    }
    return _paper_result(root, manifest, primary)


def _validate_loaded_frozen_chain(
    *,
    root: Path,
    manifest: MechanismPaperManifest,
    round_report: MechanismChildRoundReport,
) -> None:
    foundation, parent, brief = load_mechanism_foundation(root / "frozen")
    confirmatory = MechanismConfirmatoryManifest.model_validate_json(
        (root / "frozen" / "confirmatory-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    endpoint = MechanismConfirmatoryEndpoint.model_validate_json(
        (root / "frozen" / "endpoint.json").read_text(encoding="utf-8")
    )
    preregistration = MechanismConfirmatoryPreregistration.model_validate_json(
        (root / "frozen" / "preregistration.json").read_text(encoding="utf-8")
    )
    confirmatory_reproduction = MechanismReproductionReport.model_validate_json(
        (root / "frozen" / "confirmatory-reproduction.json").read_text(
            encoding="utf-8"
        )
    )
    expected_identity = {
        "foundation_manifest_hash": foundation.manifest_hash,
        "research_brief_hash": brief.brief_hash,
        "confirmatory_manifest_hash": confirmatory.manifest_hash,
        "endpoint_hash": endpoint.endpoint_hash,
        "scientific_projection_hash": endpoint.scientific_projection_hash,
    }
    observed_identity = {
        field_name: getattr(manifest, field_name)
        for field_name in expected_identity
    }
    if observed_identity != expected_identity:
        raise MechanismPaperIntegrityError(
            "paper manifest differs from its frozen scientific identity"
        )
    if (
        confirmatory.endpoint_hash != endpoint.endpoint_hash
        or confirmatory.scientific_projection_hash
        != endpoint.scientific_projection_hash
        or confirmatory.scientific_outcome
        is not MechanismScientificOutcome.NEGATIVE_RESULT
        or endpoint.outcome is not MechanismScientificOutcome.NEGATIVE_RESULT
        or endpoint.failure_codes != ["minimum_coverage_met"]
        or not confirmatory_reproduction.passed
    ):
        raise MechanismPaperIntegrityError(
            "frozen confirmatory chain no longer supports the retained negative result"
        )
    expected_round_report = _build_round_report(
        parent_endpoint_hash=parent.endpoint_hash,
        development_manifest_hash=preregistration.development_manifest_hash,
        confirmatory=confirmatory,
        endpoint=endpoint,
    )
    if round_report != expected_round_report:
        raise MechanismPaperIntegrityError(
            "child round report differs from the frozen confirmatory endpoint"
        )


def _validate_paper_inputs(
    *,
    foundation_hash: str,
    research_brief_hash: str,
    parent_evidence_hash: str,
    confirmatory_root: Path,
    confirmatory: MechanismConfirmatoryManifest,
    endpoint: MechanismConfirmatoryEndpoint,
    task_results: Sequence[MechanismConfirmatoryTaskResult],
    confirmatory_reproduction: MechanismReproductionReport,
) -> None:
    if confirmatory.scientific_outcome is not MechanismScientificOutcome.NEGATIVE_RESULT:
        raise MechanismPaperIntegrityError(
            "task 261.2.4 requires the retained negative confirmatory endpoint"
        )
    if endpoint.outcome is not MechanismScientificOutcome.NEGATIVE_RESULT:
        raise MechanismPaperIntegrityError("paper endpoint is not negative_result")
    if endpoint.endpoint_hash != confirmatory.endpoint_hash:
        raise MechanismPaperIntegrityError("paper endpoint hash is not terminal")
    if endpoint.failure_codes != ["minimum_coverage_met"]:
        raise MechanismPaperIntegrityError(
            "paper input no longer has the sole frozen coverage failure"
        )
    if len(task_results) != _EXPECTED_TASK_COUNT:
        raise MechanismPaperIntegrityError("paper requires all six task results")
    if not confirmatory_reproduction.passed:
        raise MechanismPaperIntegrityError(
            "confirmatory independent reproduction did not pass"
        )
    if (
        confirmatory.external_submission_authorized
        or endpoint.external_submission_authorized
    ):
        raise MechanismPaperIntegrityError(
            "confirmatory evidence unexpectedly authorizes submission"
        )
    development = _read_json(
        confirmatory_root / "frozen" / "development-manifest.json"
    )
    diagnosis = _read_json(confirmatory_root / "frozen" / "diagnosis.json")
    expected = (
        development.get("foundation_manifest_hash") == foundation_hash
        and development.get("research_brief_hash") == research_brief_hash
        and development.get("parent_evidence_hash") == parent_evidence_hash
        and diagnosis.get("research_brief_hash") == research_brief_hash
        and diagnosis.get("parent_evidence_hash") == parent_evidence_hash
    )
    if not expected:
        raise MechanismPaperIntegrityError(
            "paper foundation and confirmatory causal chain differ"
        )


def _copy_frozen_paper_inputs(
    *,
    foundation_root: Path,
    confirmatory_root: Path,
    package_root: Path,
) -> None:
    files = {
        foundation_root / "foundation-manifest.json": (
            package_root / "frozen" / "foundation-manifest.json"
        ),
        foundation_root / "parent-evidence.json": (
            package_root / "frozen" / "parent-evidence.json"
        ),
        foundation_root / "research-brief.json": (
            package_root / "frozen" / "research-brief.json"
        ),
        confirmatory_root / "confirmatory-manifest.json": (
            package_root / "frozen" / "confirmatory-manifest.json"
        ),
        confirmatory_root / "endpoint.json": (
            package_root / "frozen" / "endpoint.json"
        ),
        confirmatory_root / "preregistration.json": (
            package_root / "frozen" / "preregistration.json"
        ),
        confirmatory_root / "provenance" / "provenance-v2.json": (
            package_root / "frozen" / "provenance-v2.json"
        ),
        confirmatory_root / "evaluation" / "security-report.json": (
            package_root / "frozen" / "evaluation-security-report.json"
        ),
        confirmatory_root / "reproduction" / "report.json": (
            package_root / "frozen" / "confirmatory-reproduction.json"
        ),
        confirmatory_root / "rollback" / "report.json": (
            package_root / "frozen" / "rollback-report.json"
        ),
        confirmatory_root / "frozen" / "round-freeze.json": (
            package_root / "frozen" / "round-freeze.json"
        ),
        confirmatory_root / "frozen" / "mechanism-program.json": (
            package_root / "frozen" / "mechanism-program.json"
        ),
        confirmatory_root / "frozen" / "panel-spec.json": (
            package_root / "frozen" / "panel-spec.json"
        ),
        confirmatory_root / "frozen" / "run.py": (
            package_root / "frozen" / "run.py"
        ),
    }
    for source, destination in files.items():
        if not source.is_file():
            raise MechanismPaperIntegrityError(
                f"required paper input is missing: {source.as_posix()}"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _source_reachability_snapshot(
    *,
    foundation_root: Path,
    brief: MechanismResearchBrief,
    live_source_check: bool,
) -> dict[str, Any]:
    if live_source_check:
        with ThreadPoolExecutor(max_workers=4) as pool:
            observations = list(pool.map(_fetch_source, brief.sources))
        mode = "live"
        checked_at = datetime.now(timezone.utc).isoformat()
    else:
        snapshot_path = foundation_root / "source-reachability.json"
        if not snapshot_path.is_file():
            observations = []
            checked_at = datetime.now(timezone.utc).isoformat()
        else:
            snapshot = _read_json(snapshot_path)
            if snapshot.get("research_brief_hash") != brief.brief_hash:
                raise MechanismPaperIntegrityError(
                    "frozen source reachability is not bound to the research brief"
                )
            observations = list(snapshot.get("observations", []))
            checked_at = str(snapshot.get("checked_at"))
        mode = "frozen_snapshot"
    normalized = sorted(observations, key=lambda item: str(item.get("source_id")))
    expected_ids = {source.source_id for source in brief.sources}
    observed_ids = {
        str(item.get("source_id"))
        for item in normalized
        if isinstance(item, dict)
    }
    all_reachable = (
        expected_ids == observed_ids
        and all(
            isinstance(item.get("status_code"), int)
            and 200 <= int(item["status_code"]) < 400
            and isinstance(item.get("content_bytes"), int)
            and int(item["content_bytes"]) >= 1_000
            for item in normalized
            if isinstance(item, dict)
        )
    )
    return {
        "schema_version": "mechanism-paper-source-reachability-v1",
        "research_brief_hash": brief.brief_hash,
        "mode": mode,
        "checked_at": checked_at,
        "observations": normalized,
        "all_reachable": all_reachable,
        "external_submission_authorized": False,
    }


def _fetch_source(source: MechanismLiteratureSource) -> dict[str, Any]:
    try:
        retry = Retry(
            total=4,
            connect=4,
            read=3,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
        )
        with requests.Session() as session:
            session.mount("https://", HTTPAdapter(max_retries=retry))
            session.mount("http://", HTTPAdapter(max_retries=retry))
            response = session.get(
                source.source_url,
                timeout=30,
                headers={
                    "User-Agent": (
                        "AutoResearch/261.2.4 citation reachability "
                        "(evidence audit; no indexing)"
                    )
                },
            )
        return {
            "source_id": source.source_id,
            "requested_url": source.source_url,
            "resolved_url": response.url,
            "status_code": response.status_code,
            "content_bytes": len(response.content),
        }
    except requests.RequestException as exc:
        return {
            "source_id": source.source_id,
            "requested_url": source.source_url,
            "resolved_url": None,
            "status_code": None,
            "content_bytes": 0,
            "error_type": type(exc).__name__,
        }


def _build_round_report(
    *,
    parent_endpoint_hash: str,
    development_manifest_hash: str,
    confirmatory: MechanismConfirmatoryManifest,
    endpoint: MechanismConfirmatoryEndpoint,
) -> MechanismChildRoundReport:
    values: dict[str, Any] = {
        "schema_version": "mechanism-child-round-report-v1",
        "run_id": f"{endpoint.run_id}-paper",
        "parent_endpoint_hash": parent_endpoint_hash,
        "development_manifest_hash": development_manifest_hash,
        "confirmatory_manifest_hash": confirmatory.manifest_hash,
        "endpoint_hash": endpoint.endpoint_hash,
        "scientific_projection_hash": endpoint.scientific_projection_hash,
        "outcome": "negative_result",
        "task_count": endpoint.task_count,
        "claim_count": endpoint.claim_count,
        "accepted_count": endpoint.accepted_count,
        "abstained_count": endpoint.claim_count - endpoint.accepted_count,
        "accepted_unsupported_count": endpoint.accepted_unsupported_count,
        "coverage": endpoint.coverage,
        "coverage_ci95_lower": endpoint.coverage_ci95_lower,
        "coverage_ci95_upper": endpoint.coverage_ci95_upper,
        "minimum_coverage": endpoint.minimum_coverage,
        "unsupported_claim_rate": endpoint.unsupported_claim_rate,
        "unsupported_rate_ci95_lower": endpoint.unsupported_rate_ci95_lower,
        "unsupported_rate_ci95_upper": endpoint.unsupported_rate_ci95_upper,
        "maximum_unsupported_claim_rate": endpoint.maximum_unsupported_claim_rate,
        "failure_codes": endpoint.failure_codes,
        "verdict_rewritten": False,
        "external_submission_authorized": False,
    }
    values["report_hash"] = canonical_sha256(values)
    return MechanismChildRoundReport.model_validate(values)


def _round_report_markdown(report: MechanismChildRoundReport) -> str:
    return (
        "# Task 261.2 child round report\n\n"
        "The independent confirmatory execution completed all "
        f"{report.task_count} frozen tasks and evaluated {report.claim_count} "
        f"claims. It accepted {report.accepted_count} claims and retained "
        f"{report.abstained_count} abstentions.\n\n"
        f"Coverage was {report.coverage:.4f} with a task-bootstrap 95% interval "
        f"[{report.coverage_ci95_lower:.4f}, {report.coverage_ci95_upper:.4f}], "
        f"below the preregistered floor of {report.minimum_coverage:.2f}. The "
        f"unsupported-accept rate was {report.unsupported_claim_rate:.4f} with "
        "a 95% interval "
        f"[{report.unsupported_rate_ci95_lower:.4f}, "
        f"{report.unsupported_rate_ci95_upper:.4f}], at or below the frozen "
        f"ceiling of {report.maximum_unsupported_claim_rate:.2f}.\n\n"
        "The scientific outcome remains `negative_result`; the sole failure "
        "code is `minimum_coverage_met`. This report does not rewrite that "
        "verdict and does not authorize external submission.\n"
    )


def _render_manuscript_core(
    *,
    root: Path,
    brief: MechanismResearchBrief,
    endpoint: MechanismConfirmatoryEndpoint,
    preregistration_hash: str,
    round_freeze_hash: str,
    confirmatory: MechanismConfirmatoryManifest,
    task_results: Sequence[MechanismConfirmatoryTaskResult],
    reachability: dict[str, Any],
    reachability_sha256: str,
    compile_pdf: bool,
) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    data_dir = root / "data"
    figure_dir = root / "figures"
    table_dir = root / "tables"
    evidence_dir = root / "evidence"
    audit_dir = root / "audit"
    for directory in (data_dir, figure_dir, table_dir, evidence_dir, audit_dir):
        directory.mkdir(parents=True, exist_ok=True)

    data_paths = _write_paper_data(
        data_dir=data_dir,
        brief=brief,
        endpoint=endpoint,
        confirmatory=confirmatory,
        task_results=task_results,
    )
    figures = _generate_paper_figures(data_paths=data_paths, figure_dir=figure_dir)
    table_json, table_markdown = _write_task_table(table_dir, task_results)
    evidence_records = _build_evidence_registry(
        root=root,
        brief=brief,
        endpoint=endpoint,
        preregistration_hash=preregistration_hash,
        confirmatory=confirmatory,
        figures=figures,
        table_path=table_json,
    )
    claims = _build_manuscript_claims(
        brief=brief,
        endpoint=endpoint,
        task_results=task_results,
        figures=figures,
    )
    manuscript = _render_manuscript(
        brief=brief,
        claims=claims,
        table_markdown=table_markdown.read_text(encoding="utf-8"),
        figures=figures,
    )
    manuscript_path = _write_text(root / "manuscript.md", manuscript)
    manuscript_sha256 = file_hash(manuscript_path)
    _write_json(
        evidence_dir / "evidence-registry.json",
        {
            "schema_version": "mechanism-paper-evidence-registry-v1",
            "records": [
                record.model_dump(mode="json")
                for record in sorted(evidence_records, key=lambda item: item.evidence_id)
            ],
        },
    )
    _write_json(
        evidence_dir / "claim-registry.json",
        {
            "schema_version": "mechanism-paper-claim-registry-v1",
            "manuscript_sha256": manuscript_sha256,
            "claims": [
                claim.model_dump(mode="json")
                for claim in sorted(claims, key=lambda item: item.claim_id)
            ],
        },
    )
    claim_audit = _build_claim_evidence_audit(
        round_freeze_hash=round_freeze_hash,
        manuscript_sha256=manuscript_sha256,
        claims=claims,
        evidence_records=evidence_records,
    )
    write_json_model(evidence_dir / "claim-evidence-audit.json", claim_audit)
    entailment = _build_entailment_report(
        manuscript=manuscript,
        manuscript_sha256=manuscript_sha256,
        claims=claims,
        evidence_records=evidence_records,
        brief=brief,
    )
    write_json_model(evidence_dir / "entailment-audit.json", entailment)
    citation_audit = _build_citation_audit(
        manuscript=manuscript,
        manuscript_sha256=manuscript_sha256,
        brief=brief,
        claims=claims,
        reachability=reachability,
        reachability_sha256=reachability_sha256,
    )
    write_json_model(audit_dir / "citation-audit.json", citation_audit)
    display_audit = _build_display_audit(
        root=root,
        manuscript=manuscript,
        manuscript_sha256=manuscript_sha256,
        endpoint=endpoint,
        task_results=task_results,
        figures=figures,
        table_json=table_json,
        table_markdown=table_markdown,
        claims=claims,
    )
    write_json_model(audit_dir / "figure-table-audit.json", display_audit)
    paper_build = build_latex_paper_from_markdown(
        manuscript_path,
        root / "build",
        template_id="generic-article-one-column",
        title=(
            "Selective Evidence Control Can Fail by Over-Abstention: "
            "A Preregistered Negative Confirmatory Study"
        ),
        authors=("AutoResearch machine-generated draft; human authorship pending",),
        compile_pdf=compile_pdf,
        require_complete_sections=True,
        timeout_seconds=120,
    )
    stable_hashes = _stable_manuscript_hashes(root)
    return {
        "manuscript_path": manuscript_path,
        "manuscript_sha256": manuscript_sha256,
        "claim_audit": claim_audit,
        "entailment": entailment,
        "citation_audit": citation_audit,
        "display_audit": display_audit,
        "paper_build": paper_build,
        "stable_hashes": stable_hashes,
    }


def _write_paper_data(
    *,
    data_dir: Path,
    brief: MechanismResearchBrief,
    endpoint: MechanismConfirmatoryEndpoint,
    confirmatory: MechanismConfirmatoryManifest,
    task_results: Sequence[MechanismConfirmatoryTaskResult],
) -> dict[str, Path]:
    graphical = _write_json(
        data_dir / "graphical-abstract-flow.json",
        {
            "stages": [
                {
                    "id": "brief",
                    "label": "Frozen evidence brief",
                    "detail": f"{len(brief.sources)} verified sources",
                },
                {
                    "id": "program",
                    "label": "Model-authored gate",
                    "detail": "Exact reviewed source",
                },
                {
                    "id": "panel",
                    "label": "One-shot panel",
                    "detail": f"{endpoint.task_count} disjoint tasks",
                },
                {
                    "id": "endpoint",
                    "label": "Negative endpoint",
                    "detail": "Coverage below floor",
                },
                {
                    "id": "audit",
                    "label": "Claim audit",
                    "detail": "Submission remains blocked",
                },
            ]
        },
    )
    control = _write_json(
        data_dir / "confirmatory-control-flow.json",
        {
            "stages": [
                {
                    "id": "freeze",
                    "label": "Preregister",
                    "detail": "Code, panel, thresholds",
                },
                {
                    "id": "reveal",
                    "label": "Reveal once",
                    "detail": "No adaptive changes",
                },
                {
                    "id": "execute",
                    "label": "Harness execution",
                    "detail": "One attempt per task",
                },
                {
                    "id": "bootstrap",
                    "label": "Task bootstrap",
                    "detail": f"{endpoint.bootstrap_resamples} resamples",
                },
                {
                    "id": "seal",
                    "label": "Seal endpoint",
                    "detail": confirmatory.scientific_outcome.value,
                },
            ]
        },
    )
    endpoint_metrics = _write_json(
        data_dir / "endpoint-metrics.json",
        {
            "metrics": {
                "coverage": endpoint.coverage,
                "coverage_floor": endpoint.minimum_coverage,
                "unsupported_rate": endpoint.unsupported_claim_rate,
                "risk_ceiling": endpoint.maximum_unsupported_claim_rate,
            }
        },
    )
    task_metrics = _write_json(
        data_dir / "task-coverage.json",
        {
            "metrics": {
                f"Task {index}": result.coverage
                for index, result in enumerate(task_results, start=1)
            }
        },
    )
    area_counts = Counter(
        area.value for source in brief.sources for area in source.areas
    )
    literature_metrics = _write_json(
        data_dir / "literature-coverage.json",
        {
            "metrics": {
                "Selective facts": area_counts[LiteratureArea.SELECTIVE_FACTUALITY.value],
                "Agent eval": area_counts[
                    LiteratureArea.SCIENTIFIC_AGENT_EVALUATION.value
                ],
                "Code security": area_counts[
                    LiteratureArea.GENERATED_CODE_SECURITY.value
                ],
                "Claim alignment": area_counts[
                    LiteratureArea.CLAIM_EVIDENCE_ALIGNMENT.value
                ],
            }
        },
    )
    return {
        "graphical": graphical,
        "control": control,
        "endpoint": endpoint_metrics,
        "tasks": task_metrics,
        "literature": literature_metrics,
    }


def _generate_paper_figures(
    *,
    data_paths: dict[str, Path],
    figure_dir: Path,
) -> dict[str, FigureArtifact]:
    return {
        "graphical": generate_flow_diagram_figure(
            data_paths["graphical"],
            figure_dir,
            title="Evidence-bound child round",
            figure_id="graphical-abstract",
        ),
        "control": generate_flow_diagram_figure(
            data_paths["control"],
            figure_dir,
            title="Frozen confirmatory control flow",
            figure_id="confirmatory-control-flow",
        ),
        "endpoint": generate_metric_bar_figure(
            data_paths["endpoint"],
            figure_dir,
            title="Observed endpoints and frozen thresholds",
            figure_id="endpoint-gates",
        ),
        "tasks": generate_metric_bar_figure(
            data_paths["tasks"],
            figure_dir,
            title="Coverage by independent task",
            figure_id="task-coverage",
        ),
        "literature": generate_metric_bar_figure(
            data_paths["literature"],
            figure_dir,
            title="Frozen literature coverage by evidence area",
            figure_id="literature-coverage",
        ),
    }


def _write_task_table(
    table_dir: Path,
    task_results: Sequence[MechanismConfirmatoryTaskResult],
) -> tuple[Path, Path]:
    rows = [
        {
            "task_id": result.task_id,
            "claims": result.claim_count,
            "accepted": result.accepted_count,
            "abstained": result.claim_count - result.accepted_count,
            "coverage": result.coverage,
            "accepted_unsupported": result.accepted_unsupported_count,
            "unsupported_rate": result.unsupported_claim_rate,
            "attempts": result.one_shot_attempt_count,
            "execution_succeeded": result.execution_succeeded,
        }
        for result in task_results
    ]
    json_path = _write_json(
        table_dir / "task-results.json",
        {
            "schema_version": "mechanism-paper-task-table-v1",
            "rows": rows,
        },
    )
    lines = [
        "| Task | n | Accept | Abstain | Cov. | Unsup. | Try |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    lines.extend(
        (
            f"| T{index} | {row['claims']} | {row['accepted']} | "
            f"{row['abstained']} | {row['coverage']:.3f} | "
            f"{row['accepted_unsupported']} | {row['attempts']} |"
        )
        for index, row in enumerate(rows, start=1)
    )
    markdown_path = _write_text(
        table_dir / "task-results.md",
        "\n".join(lines) + "\n",
    )
    return json_path, markdown_path


def _build_evidence_registry(
    *,
    root: Path,
    brief: MechanismResearchBrief,
    endpoint: MechanismConfirmatoryEndpoint,
    preregistration_hash: str,
    confirmatory: MechanismConfirmatoryManifest,
    figures: dict[str, FigureArtifact],
    table_path: Path,
) -> list[MechanismPaperEvidenceRecord]:
    records: list[MechanismPaperEvidenceRecord] = []
    for index, source in enumerate(brief.sources):
        records.append(
            MechanismPaperEvidenceRecord(
                evidence_id=f"literature-{source.source_id}",
                evidence_kind=ClaimEvidenceKind.VERIFIED_LITERATURE,
                artifact_path="../frozen/research-brief.json",
                json_pointer=f"/sources/{index}",
                evidence_hash=canonical_sha256(source),
                support_statement=f"{source.finding} {source.limitation}",
                verified=True,
            )
        )
    records.extend(
        [
            MechanismPaperEvidenceRecord(
                evidence_id="generated-code",
                evidence_kind=ClaimEvidenceKind.GENERATED_CODE,
                artifact_path="../frozen/run.py",
                evidence_hash=endpoint.generated_source_sha256,
                support_statement=(
                    "The exact reviewed generated source was the source executed by "
                    "every primary confirmatory task."
                ),
                verified=True,
            ),
            MechanismPaperEvidenceRecord(
                evidence_id="preregistered-protocol",
                evidence_kind=ClaimEvidenceKind.PREREGISTERED_PROTOCOL,
                artifact_path="../frozen/preregistration.json",
                evidence_hash=preregistration_hash,
                support_statement=(
                    "Code, task panel, metrics, bootstrap, thresholds, and one-shot "
                    "stop rules were frozen before reveal."
                ),
                verified=True,
            ),
            MechanismPaperEvidenceRecord(
                evidence_id="confirmatory-execution",
                evidence_kind=ClaimEvidenceKind.EXECUTION_ARTIFACT,
                artifact_path="../frozen/confirmatory-manifest.json",
                evidence_hash=confirmatory.manifest_hash,
                support_statement=(
                    "Six disjoint confirmatory tasks completed successfully with one "
                    "attempt per task and no network use."
                ),
                verified=True,
            ),
            MechanismPaperEvidenceRecord(
                evidence_id="endpoint-metrics",
                evidence_kind=ClaimEvidenceKind.METRIC,
                artifact_path="../frozen/endpoint.json",
                evidence_hash=endpoint.scientific_projection_hash,
                support_statement=(
                    "The endpoint contains exact task-aggregated counts, percentile "
                    "bootstrap intervals, and frozen thresholds."
                ),
                verified=True,
            ),
            MechanismPaperEvidenceRecord(
                evidence_id="endpoint-adjudication",
                evidence_kind=ClaimEvidenceKind.ADJUDICATION,
                artifact_path="../frozen/endpoint.json",
                evidence_hash=endpoint.endpoint_hash,
                support_statement=(
                    "The immutable adjudication is negative_result solely because "
                    "minimum_coverage_met is false."
                ),
                verified=True,
            ),
            MechanismPaperEvidenceRecord(
                evidence_id="coverage-failure",
                evidence_kind=ClaimEvidenceKind.FAILURE_OR_UNCERTAINTY,
                artifact_path="../frozen/endpoint.json",
                evidence_hash=endpoint.endpoint_hash,
                support_statement=(
                    "Observed coverage is below the preregistered minimum and its "
                    "task-bootstrap interval shows substantial task uncertainty."
                ),
                verified=True,
            ),
            MechanismPaperEvidenceRecord(
                evidence_id="task-result-table",
                evidence_kind=ClaimEvidenceKind.EXECUTION_ARTIFACT,
                artifact_path=_relative_path(root, table_path),
                evidence_hash=file_hash(table_path),
                support_statement=(
                    "The task table is deterministically derived from all six primary "
                    "confirmatory task-result contracts."
                ),
                verified=True,
            ),
        ]
    )
    for figure_id, artifact in figures.items():
        pdf_path = Path(artifact.pdf_path)
        records.append(
            MechanismPaperEvidenceRecord(
                evidence_id=f"figure-{figure_id}",
                evidence_kind=ClaimEvidenceKind.FIGURE_ARTIFACT,
                artifact_path=_relative_path(root, pdf_path),
                evidence_hash=file_hash(pdf_path),
                support_statement=(
                    "The figure was deterministically generated from its recorded "
                    "frozen JSON source."
                ),
                verified=True,
            )
        )
    return records


def _build_manuscript_claims(
    *,
    brief: MechanismResearchBrief,
    endpoint: MechanismConfirmatoryEndpoint,
    task_results: Sequence[MechanismConfirmatoryTaskResult],
    figures: dict[str, FigureArtifact],
) -> list[MechanismPaperClaimRecord]:
    claims: list[MechanismPaperClaimRecord] = []

    def add(
        claim_id: str,
        kind: ClaimKind,
        section: PaperSection,
        text: str,
        evidence_ids: Sequence[str],
        citation_ids: Sequence[str] = (),
    ) -> None:
        claims.append(
            MechanismPaperClaimRecord(
                claim_id=claim_id,
                claim_kind=kind,
                section=section,
                claim_text=" ".join(text.split()),
                evidence_ids=list(evidence_ids),
                citation_source_ids=list(citation_ids),
            )
        )

    add(
        "abstract-method",
        ClaimKind.METHOD,
        "Abstract",
        (
            "We evaluated a model-authored selective evidence gate whose exact "
            "reviewed source and preregistered thresholds were frozen before an "
            "independent panel was revealed; the trusted wrapper supplied only "
            "bounded input/output plumbing, while the generated expression program "
            "owned the risk and accept decisions."
        ),
        ("generated-code", "preregistered-protocol"),
    )
    add(
        "abstract-experiment",
        ClaimKind.EXPERIMENT,
        "Abstract",
        (
            f"The confirmatory study executed {endpoint.task_count} source-disjoint "
            f"tasks once each under a no-network Harness, retained all "
            f"{endpoint.claim_count - endpoint.accepted_count} abstentions, and "
            "applied a task-level percentile bootstrap with no same-panel tuning."
        ),
        ("preregistered-protocol", "confirmatory-execution"),
    )
    add(
        "abstract-result",
        ClaimKind.RESULT,
        "Abstract",
        (
            f"The mechanism accepted {endpoint.accepted_count} of "
            f"{endpoint.claim_count} claims: unsupported risk was "
            f"{endpoint.unsupported_claim_rate:.4f} with a 95% interval "
            f"[{endpoint.unsupported_rate_ci95_lower:.4f}, "
            f"{endpoint.unsupported_rate_ci95_upper:.4f}], but coverage was "
            f"{endpoint.coverage:.4f} with a 95% interval "
            f"[{endpoint.coverage_ci95_lower:.4f}, "
            f"{endpoint.coverage_ci95_upper:.4f}]."
        ),
        ("endpoint-adjudication", "endpoint-metrics"),
    )
    add(
        "abstract-conclusion",
        ClaimKind.LIMITATION,
        "Abstract",
        (
            f"Because observed coverage remained below the preregistered "
            f"{endpoint.minimum_coverage:.2f} floor, the sealed endpoint is a "
            "negative result: the mechanism controlled residual risk among accepted "
            "claims but abstained too often to satisfy the joint gate."
        ),
        ("coverage-failure",),
    )
    add(
        "abstract-figure",
        ClaimKind.FIGURE_DESCRIPTION,
        "Abstract",
        (
            f"The graphical abstract traces the frozen {len(brief.sources)}-source "
            f"brief through exact generated code, {endpoint.task_count} one-shot "
            "tasks, the negative endpoint, and a claim audit that leaves submission "
            "blocked."
        ),
        ("endpoint-metrics", "figure-graphical"),
    )

    add(
        "introduction-problem",
        ClaimKind.LIMITATION,
        "Introduction",
        (
            "Scientific-agent text can appear precise while still guessing, "
            "misattributing evidence, or describing code that was not the code "
            "executed; a credible system therefore needs separate controls for "
            "abstention, exact execution provenance, independent evaluation, and "
            "manuscript-level evidence alignment. These controls must remain "
            "separable because a hash can establish byte identity without proving "
            "truth, a sandbox can constrain side effects without proving scientific "
            "validity, and a well-formed citation can still fail to entail the claim "
            "placed beside it."
        ),
        ("coverage-failure",),
    )
    add(
        "introduction-question",
        ClaimKind.METHOD,
        "Introduction",
        (
            "This study asks whether a source-count-aware, multi-signal degradation "
            "gate authored by a configured local model can keep unsupported accepts "
            "below a frozen ceiling while retaining at least the preregistered "
            "coverage, with every decision causally bound to reviewed generated code."
        ),
        ("generated-code", "preregistered-protocol"),
    )
    add(
        "introduction-design",
        ClaimKind.EXPERIMENT,
        "Introduction",
        (
            "The design separates a three-task development screen from six "
            "source-fingerprint-disjoint confirmatory tasks, seals the confirmatory "
            "payload until code and statistical policy are fixed, and treats each "
            "task rather than each claim as the resampling unit."
        ),
        ("preregistered-protocol", "confirmatory-execution"),
    )
    add(
        "introduction-outcome",
        ClaimKind.RESULT,
        "Introduction",
        (
            "The one-shot test does not establish a successful contribution: the "
            "unsupported-risk gate passed, but the minimum-coverage gate failed, so "
            "the scientific verdict is retained as negative rather than reframed as "
            "a positive safety result."
        ),
        ("endpoint-adjudication", "endpoint-metrics"),
    )
    add(
        "introduction-scope",
        ClaimKind.LIMITATION,
        "Introduction",
        (
            "The reported autonomy is narrowly bounded to a model-authored "
            "expression program inside human-frozen research questions, evidence "
            "sources, compiler semantics, task fixtures, resource limits, and "
            "approval policy; it is not evidence of unrestricted autonomous science."
        ),
        ("coverage-failure",),
    )

    for source in brief.sources:
        add(
            f"prior-{source.source_id}",
            ClaimKind.NAMED_PRIOR_WORK,
            "Related Work",
            (
                f"{source.title} ({source.year}) reports that {source.finding} "
                f"The frozen brief limits transfer to this study because "
                f"{source.limitation} [{source.source_id}]."
            ),
            (f"literature-{source.source_id}",),
            (source.source_id,),
        )

    add(
        "method-program",
        ClaimKind.METHOD,
        "Method",
        (
            "The generated mechanism computes a composite degradation risk from "
            "citation integrity, evidence consistency, source quality, cross-check "
            "agreement, and entailment confidence, then combines that risk with "
            "source-count conditions to emit accept or abstain and a deterministic "
            "reason code."
        ),
        ("generated-code", "preregistered-protocol"),
    )
    add(
        "method-boundary",
        ClaimKind.METHOD,
        "Method",
        (
            "A fixed safe-expression compiler supplied JSON-lines iteration, numeric "
            "clamping, and serialization but no scientific weights, thresholds, "
            "repair, or fallback; the reviewed generated file and the actual trusted "
            "wrapper both passed baseline security preflight before execution."
        ),
        ("generated-code", "preregistered-protocol"),
    )
    add(
        "method-freeze",
        ClaimKind.METHOD,
        "Method",
        (
            "Before reveal, the preregistration content-addressed the exact program, "
            "compiled source, environment, dependency lock, implementation files, "
            "panel, primary metric, bootstrap seed and resample count, coverage "
            "floor, unsupported-risk ceiling, one-attempt stop rule, and network ban."
        ),
        ("generated-code", "preregistered-protocol"),
    )
    add(
        "method-statistics",
        ClaimKind.METHOD,
        "Method",
        (
            f"The primary analysis aggregates accepted, unsupported, and total "
            f"claims within each of {endpoint.task_count} independent tasks, draws "
            f"{endpoint.bootstrap_resamples} task-level resamples with the frozen "
            f"seed, and computes percentile intervals for coverage and unsupported "
            "risk without claim-level pseudoreplication. Coverage is the ratio of "
            "accepted to evaluated claims, whereas unsupported risk is the ratio of "
            "unsupported accepts to all accepts; a resample with no accepts is "
            "conservatively assigned maximal unsupported risk. The protocol judges "
            "the point estimates and interval bounds against fixed thresholds rather "
            "than recalibrating them after observing the panel."
        ),
        ("generated-code", "preregistered-protocol"),
    )
    add(
        "method-verdict",
        ClaimKind.METHOD,
        "Method",
        (
            "Deterministic code, not the model or manuscript generator, owns metric "
            "aggregation, confidence intervals, gate comparisons, failure codes, and "
            "the positive-or-negative scientific terminal; neither endpoint rewrite "
            "nor same-panel adaptation is allowed. The same separation also keeps "
            "paper prose downstream of the endpoint: sentences, tables, and figures "
            "may explain a result, but none is permitted to alter counts, calibration "
            "rules, thresholds, or the terminal state recorded by the Control Graph."
        ),
        ("generated-code", "preregistered-protocol"),
    )
    add(
        "method-figure",
        ClaimKind.FIGURE_DESCRIPTION,
        "Method",
        (
            "The confirmatory control-flow figure shows the only admitted sequence: "
            "preregister, reveal once, execute one Harness attempt per task, compute "
            "the frozen task bootstrap, and seal the resulting endpoint."
        ),
        ("endpoint-metrics", "figure-control"),
    )

    add(
        "experiment-panel",
        ClaimKind.EXPERIMENT,
        "Experiments",
        (
            f"The primary panel contained {endpoint.task_count} confirmatory tasks "
            "with unique source fingerprints, no task-ID or source overlap with the "
            "development partition, and eight labeled claim fixtures per task. The "
            "fixtures cover literature attribution, execution evidence, figure "
            "description, provenance, and degraded-evidence combinations so that "
            "coverage cannot be increased merely by concentrating on one easy claim "
            "family. Partition checks were performed before reveal and repeated while "
            "loading the terminal package."
        ),
        ("preregistered-protocol", "confirmatory-execution"),
    )
    add(
        "experiment-execution",
        ClaimKind.EXPERIMENT,
        "Experiments",
        (
            "Each task ran the same frozen source in an isolated subprocess with an "
            "explicit allowlisted environment, no secret-bearing environment keys, "
            "no network access, one permitted attempt, a sealed Harness episode, and "
            "a durable Control Graph receipt. The Harness separated task input, "
            "reviewed source, actual wrapper, sandbox observation, output metrics, "
            "grader status, and journal lineage. A crash after a committed side "
            "effect resumes from the receipt rather than executing a second trial, "
            "which protects the one-shot interpretation."
        ),
        ("preregistered-protocol", "confirmatory-execution"),
    )
    add(
        "experiment-retention",
        ClaimKind.EXPERIMENT,
        "Experiments",
        (
            "The analysis retained every accept, abstention, failure code, output "
            "hash, sandbox observation, task journal, and terminal receipt; task "
            "execution continued to deterministic adjudication even if a task-level "
            "failure had occurred. This failure-aware rule prevents selective "
            "deletion of difficult tasks and distinguishes an execution failure from "
            "a scientifically valid negative result. It also makes intervention, "
            "cost, and attempt counts auditable instead of hiding them inside a final "
            "aggregate."
        ),
        ("preregistered-protocol", "confirmatory-execution"),
    )
    add(
        "experiment-reproduction",
        ClaimKind.EXPERIMENT,
        "Experiments",
        (
            "An initially empty-directory reproduction reran the frozen tasks and "
            "independently recomputed counts, bootstrap intervals, gates, failure "
            "codes, and outcome, while a separate rollback rehearsal reconstructed "
            "the pre-reveal state without deleting the terminal evidence. The "
            "reproduction compares a scientific projection rebuilt from frozen "
            "inputs rather than copying gate booleans from the original endpoint. "
            "The paper package then performs a second clean rebuild of manuscript "
            "text, figure sources, vector figures, tables, and semantic audits, so "
            "computational reproducibility is checked at both result and reporting "
            "layers."
        ),
        ("preregistered-protocol", "confirmatory-execution"),
    )
    add(
        "experiment-table",
        ClaimKind.EXPERIMENT,
        "Experiments",
        (
            "The task-level table is generated directly from all six primary result "
            "contracts and records claims, accepts, abstentions, coverage, "
            "unsupported accepts, and attempt counts without manual transcription."
            " The compact display labels T1 through T6 preserve the sorted task order."
        ),
        ("preregistered-protocol", "task-result-table"),
    )

    add(
        "result-completion",
        ClaimKind.RESULT,
        "Results",
        (
            f"All {endpoint.successful_task_count} of "
            f"{endpoint.task_count} task executions succeeded once, with no failed "
            "task and no network use; together they evaluated "
            f"{endpoint.claim_count} claims. Every task produced a hash-valid result "
            "contract, Harness episode, process observation, and terminal journal "
            "seal, and the Control Graph recorded exactly one execution receipt for "
            "each task before entering adjudication. Thus the negative verdict is not "
            "an alias for an incomplete or crashed run."
        ),
        ("endpoint-adjudication", "endpoint-metrics"),
    )
    add(
        "result-coverage",
        ClaimKind.RESULT,
        "Results",
        (
            f"The mechanism accepted {endpoint.accepted_count} claims and abstained "
            f"on {endpoint.claim_count - endpoint.accepted_count}, producing coverage "
            f"{endpoint.coverage:.4f} and a task-bootstrap 95% interval "
            f"[{endpoint.coverage_ci95_lower:.4f}, "
            f"{endpoint.coverage_ci95_upper:.4f}] against the frozen "
            f"{endpoint.minimum_coverage:.2f} floor."
        ),
        ("endpoint-adjudication", "endpoint-metrics"),
    )
    add(
        "result-risk",
        ClaimKind.RESULT,
        "Results",
        (
            f"One of the {endpoint.accepted_count} accepted claims was unsupported, "
            f"giving an unsupported-accept rate of "
            f"{endpoint.unsupported_claim_rate:.4f} and a task-bootstrap 95% interval "
            f"[{endpoint.unsupported_rate_ci95_lower:.4f}, "
            f"{endpoint.unsupported_rate_ci95_upper:.4f}], which did not exceed the "
            f"frozen {endpoint.maximum_unsupported_claim_rate:.2f} ceiling."
        ),
        ("endpoint-adjudication", "endpoint-metrics"),
    )
    add(
        "result-verdict",
        ClaimKind.RESULT,
        "Results",
        (
            "The unsupported-risk point and interval gates passed, but "
            "minimum_coverage_met was false; the sealed adjudication therefore "
            "records negative_result with that single scientific failure code. "
            "Evaluation and security checks, provenance-v2 claim tracing, independent "
            "scientific reproduction, and rollback rehearsal all passed, so the "
            "coverage failure remains isolated rather than being confounded with a "
            "tampered artifact, unsafe execution, missing task, or unverifiable "
            "lineage."
        ),
        ("endpoint-adjudication", "endpoint-metrics"),
    )
    add(
        "result-endpoint-figure",
        ClaimKind.FIGURE_DESCRIPTION,
        "Results",
        (
            f"The endpoint figure places observed coverage {endpoint.coverage:.4f} "
            f"below its {endpoint.minimum_coverage:.2f} floor and unsupported risk "
            f"{endpoint.unsupported_claim_rate:.4f} below its "
            f"{endpoint.maximum_unsupported_claim_rate:.2f} ceiling, making the "
            "asymmetric gate outcome visible without changing the verdict."
        ),
        ("endpoint-metrics", "figure-endpoint"),
    )
    task_coverages = ", ".join(
        f"{result.task_id}={result.coverage:.3f}" for result in task_results
    )
    add(
        "result-task-figure",
        ClaimKind.FIGURE_DESCRIPTION,
        "Results",
        (
            "The task-coverage figure displays heterogeneity across independent "
            f"tasks ({task_coverages}), which is why uncertainty is resampled at the "
            "task level rather than treating 48 claims as independent replicates."
        ),
        ("endpoint-metrics", "figure-tasks"),
    )
    area_counts = Counter(
        area.value for source in brief.sources for area in source.areas
    )
    add(
        "result-literature-figure",
        ClaimKind.FIGURE_DESCRIPTION,
        "Results",
        (
            "The literature-coverage figure records "
            f"{area_counts[LiteratureArea.SELECTIVE_FACTUALITY.value]} selective-"
            "factuality sources, "
            f"{area_counts[LiteratureArea.SCIENTIFIC_AGENT_EVALUATION.value]} "
            "scientific-agent evaluation sources, "
            f"{area_counts[LiteratureArea.GENERATED_CODE_SECURITY.value]} "
            "generated-code security sources, and "
            f"{area_counts[LiteratureArea.CLAIM_EVIDENCE_ALIGNMENT.value]} "
            "claim-alignment sources in the frozen brief."
        ),
        ("endpoint-metrics", "figure-literature"),
    )

    add(
        "limitation-negative",
        ClaimKind.LIMITATION,
        "Limitations",
        (
            "Passing the residual unsupported-risk gate does not rescue the study: "
            "the joint preregistration required adequate coverage, and the observed "
            "over-abstention is the scientific reason the endpoint is negative."
        ),
        ("coverage-failure",),
    )
    add(
        "limitation-panel",
        ClaimKind.LIMITATION,
        "Limitations",
        (
            "The confirmatory panel contains only six synthetic, structured "
            "claim-evaluation tasks, so neither its point estimates nor its "
            "task-bootstrap interval establish behavior on open-domain literature, "
            "deployed agents, other models, or adversarial real-world sources. The "
            "small number of task clusters also makes the percentile interval coarse "
            "and sensitive to which tasks are resampled, even though it is more "
            "appropriate than treating the 48 within-task claims as independent. No "
            "power claim, universal calibration guarantee, or cross-domain "
            "generalization claim is supported."
        ),
        ("coverage-failure",),
    )
    add(
        "limitation-mechanism",
        ClaimKind.LIMITATION,
        "Limitations",
        (
            "The mechanism is one model-authored restricted expression program "
            "compiled by a human-designed safe wrapper; this causal chain proves "
            "which code ran but does not prove that the model independently invented "
            "the research problem, evaluation policy, sandbox, or publication rules."
        ),
        ("coverage-failure",),
    )
    add(
        "limitation-literature",
        ClaimKind.LIMITATION,
        "Limitations",
        (
            "The fourteen-source brief spans four adjacent evidence areas and every "
            "source is cited, but reachability and frozen abstract-level findings do "
            "not substitute for a venue-specific systematic review, full-text "
            "replication, or expert novelty assessment."
        ),
        ("coverage-failure",),
    )
    add(
        "limitation-submission",
        ClaimKind.LIMITATION,
        "Limitations",
        (
            "This machine-generated draft has no settled human authorship, "
            "third-party license review, venue-format decision, or explicit "
            "submission approval; local PDF quality and complete claim links cannot "
            "authorize public release or external submission."
        ),
        ("coverage-failure",),
    )

    add(
        "conclusion-answer",
        ClaimKind.RESULT,
        "Conclusion",
        (
            "Under the frozen confirmatory policy, the multi-signal selective gate "
            "did not meet the joint scientific endpoint because its 0.5833 coverage "
            "fell below the 0.60 floor even though unsupported risk remained within "
            "the 0.10 ceiling."
        ),
        ("endpoint-adjudication", "endpoint-metrics"),
    )
    add(
        "conclusion-interpretation",
        ClaimKind.LIMITATION,
        "Conclusion",
        (
            "The defensible interpretation is narrow: the tested mechanism can "
            "reduce accepted unsupported claims by abstaining, but this panel shows "
            "that such protection can become unusably conservative, and no positive "
            "contribution claim follows from the low residual risk alone. The result "
            "does, however, demonstrate why a selective system must report risk and "
            "coverage jointly, preserve abstentions as first-class outcomes, and "
            "separate a safely executed experiment from a scientifically successful "
            "one. Those engineering observations are bounded to the verified "
            "artifact chain and should not be confused with evidence that this "
            "particular mechanism works."
        ),
        ("coverage-failure",),
    )
    add(
        "conclusion-next",
        ClaimKind.LIMITATION,
        "Conclusion",
        (
            "Any mechanism revision must begin a new development round and freeze a "
            "new independent confirmatory panel; the revealed six-task panel cannot "
            "be reused to tune expressions, thresholds, code, or the manuscript "
            "verdict."
        ),
        ("coverage-failure",),
    )
    add(
        "conclusion-governance",
        ClaimKind.LIMITATION,
        "Conclusion",
        (
            "The package is suitable as a reproducible negative-result dossier for "
            "human review, but submission readiness and external submission remain "
            "false until scientific, citation, reproducibility, authorship, license, "
            "venue, and explicit approval gates are independently satisfied. A "
            "future reviewer can inspect the frozen brief, exact generated source, "
            "task receipts, uncertainty calculation, claim registry, citation map, "
            "display sources, and clean rebuild without granting the system authority "
            "to publish or revise the already revealed endpoint. The dossier remains "
            "local, versioned, and reviewable."
        ),
        ("coverage-failure",),
    )
    if len(figures) != _EXPECTED_FIGURE_COUNT:
        raise MechanismPaperIntegrityError("paper claim renderer requires five figures")
    return claims


def _render_manuscript(
    *,
    brief: MechanismResearchBrief,
    claims: Sequence[MechanismPaperClaimRecord],
    table_markdown: str,
    figures: dict[str, FigureArtifact],
) -> str:
    by_section: dict[str, list[MechanismPaperClaimRecord]] = {
        section: [] for section in _PAPER_SECTIONS
    }
    for claim in claims:
        by_section[claim.section].append(claim)
    lines = [
        "# Selective Evidence Control Can Fail by Over-Abstention",
        "",
    ]
    figure_after_claim = {
        "abstract-figure": figures["graphical"].pdf_path,
        "method-figure": figures["control"].pdf_path,
        "result-endpoint-figure": figures["endpoint"].pdf_path,
        "result-task-figure": figures["tasks"].pdf_path,
        "result-literature-figure": figures["literature"].pdf_path,
    }
    figure_alt = {
        "abstract-figure": (
            "Graphical abstract of the frozen brief, generated mechanism, one-shot "
            "panel, negative endpoint, and claim audit"
        ),
        "method-figure": (
            "Confirmatory control flow from preregistration to sealed endpoint"
        ),
        "result-endpoint-figure": (
            "Observed coverage and unsupported-accept rate with frozen thresholds"
        ),
        "result-task-figure": "Coverage for each of six independent tasks",
        "result-literature-figure": (
            "Frozen literature counts across four evidence areas"
        ),
    }
    root = Path(next(iter(figures.values())).pdf_path).parent.parent
    for section in _PAPER_SECTIONS:
        lines.extend([f"## {section}", ""])
        for claim in by_section[section]:
            lines.extend([claim.claim_text, ""])
            if claim.claim_id in figure_after_claim:
                relative = Path(figure_after_claim[claim.claim_id]).relative_to(root)
                lines.extend(
                    [
                        f"![{figure_alt[claim.claim_id]}]({relative.as_posix()})",
                        "",
                    ]
                )
            if claim.claim_id == "experiment-table":
                lines.extend([table_markdown.rstrip(), ""])
    lines.extend(["## References", ""])
    for source in brief.sources:
        authors = ", ".join(source.authors)
        lines.append(
            f"- [{source.source_id}] {authors}. ({source.year}). "
            f"{source.title}. {source.venue}. {source.source_url}"
        )
    return "\n".join(lines).rstrip() + "\n"


def _build_claim_evidence_audit(
    *,
    round_freeze_hash: str,
    manuscript_sha256: str,
    claims: Sequence[MechanismPaperClaimRecord],
    evidence_records: Sequence[MechanismPaperEvidenceRecord],
) -> ManuscriptClaimEvidenceAudit:
    evidence_by_id = {record.evidence_id: record for record in evidence_records}
    requirements: list[ClaimEvidenceRequirement] = []
    links: list[ClaimEvidenceLink] = []
    for claim in claims:
        requirements.append(
            ClaimEvidenceRequirement(
                claim_id=claim.claim_id,
                claim_kind=claim.claim_kind,
                claim_text=claim.claim_text,
                required_evidence_kinds=list(
                    _REQUIRED_EVIDENCE_BY_KIND[claim.claim_kind]
                ),
            )
        )
        for evidence_id in claim.evidence_ids:
            record = evidence_by_id.get(evidence_id)
            if record is None:
                raise MechanismPaperIntegrityError(
                    f"claim {claim.claim_id} references unknown evidence {evidence_id}"
                )
            links.append(
                ClaimEvidenceLink(
                    claim_id=claim.claim_id,
                    evidence_kind=record.evidence_kind,
                    evidence_id=record.evidence_id,
                    evidence_hash=record.evidence_hash,
                    supports_claim=record.verified,
                )
            )
    return ManuscriptClaimEvidenceAudit.create(
        round_freeze_hash=round_freeze_hash,
        manuscript_sha256=manuscript_sha256,
        requirements=requirements,
        links=links,
    )


def _build_entailment_report(
    *,
    manuscript: str,
    manuscript_sha256: str,
    claims: Sequence[MechanismPaperClaimRecord],
    evidence_records: Sequence[MechanismPaperEvidenceRecord],
    brief: MechanismResearchBrief,
) -> MechanismClaimEntailmentReport:
    evidence_by_id = {record.evidence_id: record for record in evidence_records}
    source_by_id = {source.source_id: source for source in brief.sources}
    rendered = _material_paragraphs(manuscript)
    ordered_claims = sorted(claims, key=lambda item: item.claim_id)
    registered_texts = [claim.claim_text for claim in ordered_claims]
    rendered_counts = Counter(rendered)
    registered_counts = Counter(registered_texts)
    unregistered = [
        canonical_sha256({"paragraph": text})
        for text, count in (rendered_counts - registered_counts).items()
        for _ in range(count)
    ]
    missing_ids = [
        claim.claim_id
        for claim in ordered_claims
        if rendered_counts[claim.claim_text] < registered_counts[claim.claim_text]
    ]
    checks: list[MechanismClaimEntailmentCheck] = []
    for claim in ordered_claims:
        records = [evidence_by_id.get(item) for item in claim.evidence_ids]
        resolved = all(record is not None and record.verified for record in records)
        kinds = {
            record.evidence_kind for record in records if record is not None
        }
        typed = set(_REQUIRED_EVIDENCE_BY_KIND[claim.claim_kind]).issubset(kinds)
        source_text_present = True
        if claim.claim_kind is ClaimKind.NAMED_PRIOR_WORK:
            source = source_by_id[claim.citation_source_ids[0]]
            source_text_present = (
                source.finding in claim.claim_text
                and source.limitation in claim.claim_text
            )
        occurrences = rendered_counts[claim.claim_text]
        passed = occurrences == 1 and resolved and typed and source_text_present
        checks.append(
            MechanismClaimEntailmentCheck(
                claim_id=claim.claim_id,
                manuscript_occurrences=occurrences,
                evidence_ids_resolved=resolved,
                typed_evidence_complete=typed,
                frozen_source_text_present=source_text_present,
                passed=passed,
            )
        )
    passed = (
        all(check.passed for check in checks)
        and not unregistered
        and not missing_ids
        and len(rendered) == len(claims)
    )
    values: dict[str, Any] = {
        "schema_version": "mechanism-claim-entailment-v1",
        "manuscript_sha256": manuscript_sha256,
        "registered_claim_count": len(claims),
        "rendered_material_paragraph_count": len(rendered),
        "checks": [check.model_dump(mode="json") for check in checks],
        "unregistered_paragraph_hashes": sorted(unregistered),
        "missing_claim_ids": sorted(set(missing_ids)),
        "passed": passed,
    }
    values["report_hash"] = canonical_sha256(values)
    return MechanismClaimEntailmentReport.model_validate(values)


def _material_paragraphs(manuscript: str) -> list[str]:
    paragraphs: list[str] = []
    in_references = False
    for raw_line in manuscript.splitlines():
        line = raw_line.strip()
        if line == "## References":
            in_references = True
            continue
        if line.startswith("## "):
            in_references = False
            continue
        if (
            not line
            or line.startswith("# ")
            or in_references
            or line.startswith("![")
            or line.startswith("|")
        ):
            continue
        paragraphs.append(line)
    return paragraphs


def _build_citation_audit(
    *,
    manuscript: str,
    manuscript_sha256: str,
    brief: MechanismResearchBrief,
    claims: Sequence[MechanismPaperClaimRecord],
    reachability: dict[str, Any],
    reachability_sha256: str,
) -> MechanismCitationAudit:
    expected = {source.source_id for source in brief.sources}
    inline = set(_SOURCE_TOKEN.findall(manuscript))
    references = {
        match.group(1)
        for line in manuscript.splitlines()
        if (match := _REFERENCE_LINE.match(line.strip()))
    }
    named = {
        source_id
        for claim in claims
        for source_id in claim.citation_source_ids
    }
    area_counts = Counter(
        area.value for source in brief.sources for area in source.areas
    )
    adjacent = (
        set(area_counts) == {area.value for area in LiteratureArea}
        and all(area_counts[area.value] >= 3 for area in LiteratureArea)
        and len(brief.sources) >= _EXPECTED_SOURCE_COUNT
    )
    values: dict[str, Any] = {
        "schema_version": "mechanism-paper-citation-audit-v1",
        "research_brief_hash": brief.brief_hash,
        "manuscript_sha256": manuscript_sha256,
        "source_reachability_sha256": reachability_sha256,
        "source_count": len(brief.sources),
        "inline_source_ids": sorted(inline),
        "reference_source_ids": sorted(references),
        "named_claim_source_ids": sorted(named),
        "missing_inline_ids": sorted(expected - inline),
        "missing_reference_ids": sorted(expected - references),
        "missing_named_claim_ids": sorted(expected - named),
        "area_source_counts": dict(sorted(area_counts.items())),
        "all_sources_reachable": bool(reachability.get("all_reachable")),
        "live_source_check_performed": reachability.get("mode") == "live",
        "adequate_adjacent_work_coverage": adjacent,
    }
    values["passed"] = (
        not values["missing_inline_ids"]
        and not values["missing_reference_ids"]
        and not values["missing_named_claim_ids"]
        and values["all_sources_reachable"]
        and adjacent
    )
    values["audit_hash"] = canonical_sha256(values)
    return MechanismCitationAudit.model_validate(values)


def _build_display_audit(
    *,
    root: Path,
    manuscript: str,
    manuscript_sha256: str,
    endpoint: MechanismConfirmatoryEndpoint,
    task_results: Sequence[MechanismConfirmatoryTaskResult],
    figures: dict[str, FigureArtifact],
    table_json: Path,
    table_markdown: Path,
    claims: Sequence[MechanismPaperClaimRecord],
) -> MechanismFigureTableAudit:
    table_payload = _read_json(table_json)
    rows = table_payload.get("rows", [])
    expected_rows = [
        {
            "task_id": result.task_id,
            "claims": result.claim_count,
            "accepted": result.accepted_count,
            "abstained": result.claim_count - result.accepted_count,
            "coverage": result.coverage,
            "accepted_unsupported": result.accepted_unsupported_count,
            "unsupported_rate": result.unsupported_claim_rate,
            "attempts": result.one_shot_attempt_count,
            "execution_succeeded": result.execution_succeeded,
        }
        for result in task_results
    ]
    figure_claims = [
        claim for claim in claims if claim.claim_kind is ClaimKind.FIGURE_DESCRIPTION
    ]
    figure_hashes = {
        _relative_path(root, Path(artifact.pdf_path)): file_hash(artifact.pdf_path)
        for artifact in figures.values()
    }
    table_hashes = {
        _relative_path(root, table_json): file_hash(table_json),
        _relative_path(root, table_markdown): file_hash(table_markdown),
    }
    checks = {
        "five_source_backed_figures": len(figures) == _EXPECTED_FIGURE_COUNT,
        "every_figure_referenced": all(
            _relative_path(root, Path(artifact.pdf_path)) in manuscript
            for artifact in figures.values()
        ),
        "every_figure_has_description_claim": len(figure_claims) == len(figures),
        "task_table_matches_primary_results": rows == expected_rows,
        "task_table_is_rendered": table_markdown.read_text(encoding="utf-8").strip()
        in manuscript,
        "endpoint_counts_match_table": (
            sum(int(row["claims"]) for row in rows) == endpoint.claim_count
            and sum(int(row["accepted"]) for row in rows) == endpoint.accepted_count
            and sum(int(row["accepted_unsupported"]) for row in rows)
            == endpoint.accepted_unsupported_count
        ),
    }
    failures = sorted(name for name, passed in checks.items() if not passed)
    values: dict[str, Any] = {
        "schema_version": "mechanism-paper-display-audit-v1",
        "endpoint_hash": endpoint.endpoint_hash,
        "manuscript_sha256": manuscript_sha256,
        "figure_count": len(figures),
        "table_count": 1,
        "figure_file_sha256s": dict(sorted(figure_hashes.items())),
        "table_file_sha256s": dict(sorted(table_hashes.items())),
        "checks": checks,
        "failures": failures,
        "passed": not failures,
    }
    values["audit_hash"] = canonical_sha256(values)
    return MechanismFigureTableAudit.model_validate(values)


def _stable_manuscript_hashes(root: Path) -> dict[str, str]:
    included: dict[str, str] = {}
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative.startswith("build/") or relative.endswith(".metadata.json"):
            continue
        included[relative] = file_hash(path)
    return included


def _build_paper_reproduction_report(
    *,
    endpoint: MechanismConfirmatoryEndpoint,
    confirmatory_reproduction: MechanismReproductionReport,
    primary: dict[str, Any],
    reproduced: dict[str, Any],
) -> MechanismPaperReproductionReport:
    primary_hashes = dict(primary["stable_hashes"])
    reproduced_hashes = dict(reproduced["stable_hashes"])
    all_paths = sorted(set(primary_hashes) | set(reproduced_hashes))
    matched = [
        path
        for path in all_paths
        if primary_hashes.get(path) == reproduced_hashes.get(path)
    ]
    mismatched = [path for path in all_paths if path not in matched]
    primary_build = primary["paper_build"]
    reproduced_build = reproduced["paper_build"]
    assert isinstance(primary_build, LatexPaperBuildArtifact)
    assert isinstance(reproduced_build, LatexPaperBuildArtifact)
    compiled_statuses = {
        LatexPaperBuildStatus.COMPILED,
        LatexPaperBuildStatus.COMPILED_WITH_QUALITY_ISSUES,
    }
    primary_compiled = primary_build.status in compiled_statuses
    reproduced_compiled = reproduced_build.status in compiled_statuses
    values: dict[str, Any] = {
        "schema_version": "mechanism-paper-reproduction-v1",
        "endpoint_hash": endpoint.endpoint_hash,
        "scientific_projection_hash": endpoint.scientific_projection_hash,
        "confirmatory_reproduction_passed": confirmatory_reproduction.passed,
        "source_file_count": len(all_paths),
        "matched_source_files": matched,
        "mismatched_source_files": mismatched,
        "primary_pdf_compiled": primary_compiled,
        "reproduced_pdf_compiled": reproduced_compiled,
        "primary_pdf_quality_passed": primary_build.quality.passed,
        "reproduced_pdf_quality_passed": reproduced_build.quality.passed,
        "primary_page_count": primary_build.quality.page_count,
        "reproduced_page_count": reproduced_build.quality.page_count,
    }
    values["passed"] = (
        confirmatory_reproduction.passed
        and not mismatched
        and len(matched) == len(all_paths)
        and primary_compiled == reproduced_compiled
        and primary_build.quality.passed == reproduced_build.quality.passed
    )
    values["report_hash"] = canonical_sha256(values)
    return MechanismPaperReproductionReport.model_validate(values)


def _build_final_paper_audit(
    *,
    endpoint: MechanismConfirmatoryEndpoint,
    primary: dict[str, Any],
    reproduction: MechanismPaperReproductionReport,
) -> MechanismPaperAudit:
    claim_audit = primary["claim_audit"]
    entailment = primary["entailment"]
    citation_audit = primary["citation_audit"]
    display_audit = primary["display_audit"]
    paper_build = primary["paper_build"]
    assert isinstance(claim_audit, ManuscriptClaimEvidenceAudit)
    assert isinstance(entailment, MechanismClaimEntailmentReport)
    assert isinstance(citation_audit, MechanismCitationAudit)
    assert isinstance(display_audit, MechanismFigureTableAudit)
    assert isinstance(paper_build, LatexPaperBuildArtifact)
    checks = {
        "faithful_negative_scientific_verdict": (
            endpoint.outcome is MechanismScientificOutcome.NEGATIVE_RESULT
            and endpoint.failure_codes == ["minimum_coverage_met"]
        ),
        "scientific_submission_gate": False,
        "claim_evidence_coverage": claim_audit.coverage_complete,
        "claim_entailment": entailment.passed,
        "citation_and_adjacent_work": citation_audit.passed,
        "figure_and_table_consistency": display_audit.passed,
        "independent_reproduction": reproduction.passed,
        "pdf_compiled": paper_build.status
        in {
            LatexPaperBuildStatus.COMPILED,
            LatexPaperBuildStatus.COMPILED_WITH_QUALITY_ISSUES,
        },
        "pdf_quality": paper_build.quality.passed,
        "authorship_review": False,
        "license_review": False,
        "explicit_human_approval": False,
    }
    failures = sorted(name for name, passed in checks.items() if not passed)
    values: dict[str, Any] = {
        "schema_version": "mechanism-paper-final-audit-v1",
        "endpoint_hash": endpoint.endpoint_hash,
        "manuscript_sha256": primary["manuscript_sha256"],
        "checks": checks,
        "failed_gates": failures,
        "faithful_negative_result_reported": checks[
            "faithful_negative_scientific_verdict"
        ],
        "positive_contribution_supported": False,
        "submission_readiness_granted": False,
        "external_submission_authorized": False,
        "verdict": "not_ready",
    }
    values["audit_hash"] = canonical_sha256(values)
    return MechanismPaperAudit.model_validate(values)


def _paper_reproduction_markdown(
    report: MechanismPaperReproductionReport,
) -> str:
    return (
        "# Independent paper reproduction\n\n"
        f"The clean rebuild matched {len(report.matched_source_files)} of "
        f"{report.source_file_count} deterministic manuscript, data, figure, "
        "table, claim, citation, and display-audit files. "
        f"Confirmatory scientific reproduction passed: "
        f"`{str(report.confirmatory_reproduction_passed).lower()}`. "
        f"Primary and reproduced page counts were {report.primary_page_count} and "
        f"{report.reproduced_page_count}. Overall reproduction passed: "
        f"`{str(report.passed).lower()}`.\n"
    )


def _paper_audit_markdown(audit: MechanismPaperAudit) -> str:
    failed = ", ".join(audit.failed_gates)
    return (
        "# Child paper audit\n\n"
        "The negative scientific verdict is reported faithfully and the local "
        "claim, citation, display, and reproduction checks are recorded in the "
        "package. Submission readiness is `false` and external submission is "
        "`false`.\n\n"
        f"Failed or intentionally unopened gates: {failed}.\n"
    )


def _deliverables_markdown(
    *,
    endpoint: MechanismConfirmatoryEndpoint,
    primary: dict[str, Any],
    final_audit: MechanismPaperAudit,
) -> str:
    paper_build = primary["paper_build"]
    assert isinstance(paper_build, LatexPaperBuildArtifact)
    pdf_value = paper_build.pdf_path or "not compiled"
    return (
        "# Task 261.2.4 deliverables\n\n"
        f"The immutable endpoint is `{endpoint.outcome.value}` "
        f"(`{endpoint.endpoint_hash}`). The paper does not convert the passed "
        "unsupported-risk gate into a positive overall result; coverage remains "
        f"{endpoint.coverage:.4f} against the {endpoint.minimum_coverage:.2f} "
        "floor.\n\n"
        f"Manuscript: `manuscript/manuscript.md`\n\n"
        f"PDF: `{pdf_value}`\n\n"
        "Claim evidence: `manuscript/evidence/claim-evidence-audit.json`\n\n"
        "Citation audit: `manuscript/audit/citation-audit.json`\n\n"
        "Figure/table audit: `manuscript/audit/figure-table-audit.json`\n\n"
        "Independent rebuild: `reproduction/paper-reproduction.json`\n\n"
        f"Submission readiness: "
        f"`{str(final_audit.submission_readiness_granted).lower()}`. "
        "External submission is not authorized.\n"
    )


def _revalidate_claim_and_display_audits(
    *,
    root: Path,
    manifest: MechanismPaperManifest,
    claim_audit: ManuscriptClaimEvidenceAudit,
    entailment: MechanismClaimEntailmentReport,
    citation_audit: MechanismCitationAudit,
    display_audit: MechanismFigureTableAudit,
) -> None:
    manuscript = (root / manifest.manuscript_path).read_text(encoding="utf-8")
    claim_registry = _read_json(
        root / "manuscript" / "evidence" / "claim-registry.json"
    )
    evidence_registry = _read_json(
        root / "manuscript" / "evidence" / "evidence-registry.json"
    )
    claims = [
        MechanismPaperClaimRecord.model_validate(item)
        for item in claim_registry.get("claims", [])
    ]
    evidence = [
        MechanismPaperEvidenceRecord.model_validate(item)
        for item in evidence_registry.get("records", [])
    ]
    brief = MechanismResearchBrief.model_validate_json(
        (root / "frozen" / "research-brief.json").read_text(encoding="utf-8")
    )
    recalculated_entailment = _build_entailment_report(
        manuscript=manuscript,
        manuscript_sha256=file_hash(root / manifest.manuscript_path),
        claims=claims,
        evidence_records=evidence,
        brief=brief,
    )
    if recalculated_entailment != entailment:
        raise MechanismPaperIntegrityError(
            "claim entailment does not independently recompute"
        )
    if not claim_audit.coverage_complete:
        raise MechanismPaperIntegrityError("paper claim coverage is incomplete")
    expected_source_ids = {source.source_id for source in brief.sources}
    if (
        set(citation_audit.inline_source_ids) != expected_source_ids
        or set(citation_audit.reference_source_ids) != expected_source_ids
        or set(citation_audit.named_claim_source_ids) != expected_source_ids
        or not citation_audit.passed
    ):
        raise MechanismPaperIntegrityError("paper citation audit is incomplete")
    for relative, expected_hash in display_audit.figure_file_sha256s.items():
        if file_hash(root / "manuscript" / relative) != expected_hash:
            raise MechanismPaperIntegrityError(
                f"paper figure hash mismatch: {relative}"
            )
    for relative, expected_hash in display_audit.table_file_sha256s.items():
        if file_hash(root / "manuscript" / relative) != expected_hash:
            raise MechanismPaperIntegrityError(
                f"paper table hash mismatch: {relative}"
            )
    if not display_audit.passed:
        raise MechanismPaperIntegrityError("paper display audit did not pass")


def _load_task_results(
    root: Path,
    endpoint: MechanismConfirmatoryEndpoint,
) -> list[MechanismConfirmatoryTaskResult]:
    results = [
        MechanismConfirmatoryTaskResult.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        for path in sorted((root / "confirmatory").glob("*/task-result.json"))
    ]
    if sorted(result.result_hash for result in results) != sorted(
        endpoint.task_result_hashes
    ):
        raise MechanismPaperIntegrityError(
            "paper task results differ from endpoint task hashes"
        )
    return sorted(results, key=lambda item: item.task_id)


def _load_paper_build(root: Path) -> LatexPaperBuildArtifact:
    payload = _read_json(root / "paper-build.json")
    quality = payload["paper_quality"]
    from autoresearch.reports.latex_templates import (
        LatexTemplateDependencyResolution,
        LatexTemplateDependencyStatus,
        LatexTemplateSourceKind,
        LatexTemplateSpec,
    )
    from autoresearch.reports.paper_build import LatexPaperQualityReport

    template_payload = payload["template"]
    template = LatexTemplateSpec(
        id=template_payload["id"],
        display_name=template_payload["display_name"],
        source_kind=LatexTemplateSourceKind(template_payload["source_kind"]),
        document_class=template_payload["document_class"],
        class_options=tuple(template_payload["class_options"]),
        class_file=template_payload.get("class_file"),
        preamble_lines=tuple(template_payload["preamble_lines"]),
        abstract_before_maketitle=template_payload["abstract_before_maketitle"],
        source_url=template_payload.get("source_url"),
        texlive_package=template_payload.get("texlive_package"),
        source_archive_url=template_payload.get("source_archive_url"),
        source_archive_member=template_payload.get("source_archive_member"),
        license_note=template_payload["license_note"],
    )
    dependency_payload = payload["dependency_resolution"]
    dependency = LatexTemplateDependencyResolution(
        status=LatexTemplateDependencyStatus(dependency_payload["status"]),
        checked_at=dependency_payload["checked_at"],
        class_file=dependency_payload["class_file"],
        message=dependency_payload["message"],
        command=tuple(dependency_payload["command"]),
        returncode=dependency_payload.get("returncode"),
        artifact_path=dependency_payload.get("artifact_path"),
        stdout_tail=dependency_payload.get("stdout_tail"),
        stderr_tail=dependency_payload.get("stderr_tail"),
        error=dependency_payload.get("error"),
    )
    return LatexPaperBuildArtifact(
        status=LatexPaperBuildStatus(payload["status"]),
        generated_at=payload["generated_at"],
        template=template,
        source_markdown_path=payload["source_markdown_path"],
        tex_path=payload.get("tex_path"),
        pdf_path=payload.get("pdf_path"),
        log_path=payload["log_path"],
        markdown_path=payload["markdown_path"],
        json_path=payload["json_path"],
        vault_markdown_path=payload.get("vault_markdown_path"),
        missing_sections=tuple(payload["missing_sections"]),
        engine=payload.get("engine"),
        command=tuple(payload["command"]),
        dependency_resolution=dependency,
        quality=LatexPaperQualityReport(
            passed=quality["passed"],
            page_count=quality["page_count"],
            min_pages=quality["min_pages"],
            word_count=quality["word_count"],
            min_word_count=quality["min_word_count"],
            technical_term_count=quality["technical_term_count"],
            min_technical_terms=quality["min_technical_terms"],
            section_word_counts=quality["section_word_counts"],
            section_min_words=quality["section_min_words"],
            short_sections=tuple(quality["short_sections"]),
            overfull_hbox_count=quality["overfull_hbox_count"],
            max_overfull_hbox_count=quality["max_overfull_hbox_count"],
            max_overfull_hbox_points=quality["max_overfull_hbox_points"],
            max_allowed_overfull_hbox_points=quality[
                "max_allowed_overfull_hbox_points"
            ],
            figure_count=quality["figure_count"],
            min_figures=quality["min_figures"],
            table_count=quality["table_count"],
            min_tables=quality["min_tables"],
            bibliography_item_count=quality["bibliography_item_count"],
            min_bibliography_items=quality["min_bibliography_items"],
            invalid_reference_label_count=quality[
                "invalid_reference_label_count"
            ],
            figure_readability_issue_count=quality[
                "figure_readability_issue_count"
            ],
            figure_readability_issues=tuple(quality["figure_readability_issues"]),
            failures=tuple(quality["failures"]),
        ),
        reason=payload.get("reason"),
    )


def _paper_result(
    root: Path,
    manifest: MechanismPaperManifest,
    primary: dict[str, Any],
) -> MechanismPaperBuildResult:
    paper_build = primary["paper_build"]
    claim_audit = primary["claim_audit"]
    assert isinstance(paper_build, LatexPaperBuildArtifact)
    assert isinstance(claim_audit, ManuscriptClaimEvidenceAudit)
    pdf_path = (
        (root / manifest.pdf_path).resolve().as_posix()
        if manifest.pdf_path is not None
        else None
    )
    return MechanismPaperBuildResult(
        package_dir=root.resolve().as_posix(),
        status=manifest.status,
        manifest_hash=manifest.manifest_hash,
        endpoint_hash=manifest.endpoint_hash,
        manuscript_path=(root / manifest.manuscript_path).resolve().as_posix(),
        pdf_path=pdf_path,
        paper_quality_passed=paper_build.quality.passed,
        claim_coverage_complete=claim_audit.coverage_complete,
    )


def _require_absent_or_empty(path: Path, label: str) -> None:
    if path.exists() and any(path.iterdir()):
        raise MechanismPaperIntegrityError(f"{label} directory must be absent or empty")


def _relative_file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): file_hash(path)
        for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file())
        if path.name != "paper-manifest.json"
    }


def _relative_path(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MechanismPaperIntegrityError(
            f"invalid JSON artifact: {path.as_posix()}"
        ) from exc
    if not isinstance(payload, dict):
        raise MechanismPaperIntegrityError(
            f"JSON artifact must be an object: {path.as_posix()}"
        )
    return payload


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
