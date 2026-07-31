"""Prospective protocol contracts for the AI-scientist benchmark-validity map.

Task 263.6.6 showed that released task counts are not interchangeable with
independent scientific units and that public visibility does not establish
rights, objective measurement, baseline reproducibility, bounded compute, or
a sealed split.  This module freezes the next study *before* any additional
benchmark release is extracted.

The protocol is intentionally result-free.  It fixes discovery sources,
source-specific queries, dates, release and family units, eligibility,
deduplication, the Benchmark Admission Card, human coding, descriptive
endpoints, sensitivities, and stop rules.  The four Task 263.6.6 candidates
remain protocol-development pilots and can never enter the primary prospective
cohort.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from collections.abc import Mapping
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    NonEmptyText,
    Sha256,
    StableId,
    canonical_sha256,
)

from .workload_qualified_opportunity import InterpreterRuntime, probe_interpreter_runtime

BENCHMARK_VALIDITY_PROTOCOL_FILENAME = "benchmark-validity-protocol-freeze.json"
BENCHMARK_VALIDITY_MARKDOWN_FILENAME = "benchmark-validity-protocol-freeze.md"
BENCHMARK_VALIDITY_PROJECTION_FILENAME = "benchmark-validity-protocol-projection.json"
BENCHMARK_VALIDITY_REPLAY_FILENAME = "benchmark-validity-protocol-replay.json"
BENCHMARK_VALIDITY_SCHEMA_FILENAME = "benchmark-validity-schemas.json"
BENCHMARK_VALIDITY_MANIFEST_FILENAME = "benchmark-validity-manifest.json"

PRIMARY_NON_PILOT_RELEASE_TARGET = 20
SEARCH_START_DATE = date(2023, 1, 1)
SEARCH_CUTOFF_DATE = date(2026, 7, 31)
PROTOCOL_BOOTSTRAP_SEED = 2_636_071


class BenchmarkValidityIntegrityError(ValueError):
    """Raised when a protocol or persisted artifact fails content validation."""


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        rendered = value.astimezone(timezone.utc).isoformat()
        return rendered[:-6] + "Z" if rendered.endswith("+00:00") else rendered
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


def _canonical_json_text(value: Any) -> str:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_text_atomic(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)


class ProtocolStatus(str, Enum):
    """Lifecycle status of the systematic-mapping protocol."""

    FROZEN_PRE_EXTRACTION = "frozen-pre-extraction"


class SearchSourceId(str, Enum):
    """Open bibliographic discovery indexes fixed before extraction."""

    ARXIV = "arxiv"
    OPENALEX = "openalex"
    CROSSREF = "crossref"
    DBLP = "dblp"


class SearchLens(str, Enum):
    """Mutually assigned scientific-agent construct lenses."""

    LITERATURE_DISCOVERY = "literature-discovery"
    SCIENTIFIC_PROGRAMMING = "scientific-programming"
    DATA_ANALYSIS = "data-analysis"
    HYPOTHESIS_VALIDATION = "hypothesis-validation"
    COMPUTATIONAL_REPRODUCTION = "computational-reproduction"
    EXPERIMENT_EXECUTION = "experiment-execution"
    FULL_RESEARCH_LIFECYCLE = "full-research-lifecycle"


class ConstructStratum(str, Enum):
    """Primary release strata; secondary tags may preserve additional scope."""

    LITERATURE_DISCOVERY = "literature-discovery"
    SCIENTIFIC_PROGRAMMING = "scientific-programming"
    DATA_ANALYSIS = "data-analysis"
    HYPOTHESIS_VALIDATION = "hypothesis-validation"
    COMPUTATIONAL_REPRODUCTION = "computational-reproduction"
    EXPERIMENT_EXECUTION = "experiment-execution"
    FULL_RESEARCH_LIFECYCLE = "full-research-lifecycle"


class EvidenceState(str, Enum):
    """Fail-closed evidence codes used by every admission field."""

    VERIFIED_PASS = "verified-pass"
    VERIFIED_FAIL = "verified-fail"
    NOT_REPORTED = "not-reported"
    UNREACHABLE = "unreachable"
    AMBIGUOUS = "ambiguous"
    CONFLICTING = "conflicting"
    NOT_APPLICABLE = "not-applicable"


class AdmissionGate(str, Enum):
    """Non-compensating conditions in the complete-conjunction endpoint."""

    FIXED_REVISION = "fixed-revision"
    INDEPENDENT_LINEAGE = "independent-lineage"
    LOCAL_EXECUTION_RIGHTS = "local-execution-rights"
    SOFTWARE_REUSE_RIGHTS = "software-reuse-rights"
    DERIVATIVE_CREATION_RIGHTS = "derivative-creation-rights"
    CONTENT_REDISTRIBUTION_RIGHTS = "content-redistribution-rights"
    DETERMINISTIC_PRIMARY_ENDPOINT = "deterministic-primary-endpoint"
    NON_DECISIVE_MODEL_OR_HUMAN_JUDGE = "non-decisive-model-or-human-judge"
    EXACT_STRONG_BASELINE = "exact-strong-baseline"
    BOUNDED_COMPUTE = "bounded-compute"
    SEALED_RESERVE = "sealed-reserve"
    CONTAMINATION_CONTROL = "contamination-control"


class JudgeRole(str, Enum):
    """Role played by an LLM, VLM, or post-hoc human score."""

    NONE = "none"
    SECONDARY_ONLY = "secondary-only"
    PART_OF_PRIMARY = "part-of-primary"
    PRIMARY = "primary"
    UNKNOWN = "unknown"


class ScreeningDecision(str, Enum):
    """Prospectively allowed screening outcomes."""

    INCLUDE = "include"
    EXCLUDE = "exclude"
    CONFLICT = "conflict"


class MethodologicalAnchor(KernelContract):
    """Primary method or system source and the rule borrowed from it."""

    anchor_id: StableId
    citation: NonEmptyText
    stable_locator: NonEmptyText
    borrowed_rule: str = Field(min_length=1, max_length=2_048)


class SearchSourceSpec(KernelContract):
    """Exact API and traversal behavior for one discovery source."""

    source_id: SearchSourceId
    endpoint_url: NonEmptyText
    documentation_url: NonEmptyText
    response_format: NonEmptyText
    page_size: int = Field(ge=1, le=2_000)
    pagination_rule: str = Field(min_length=1, max_length=2_048)
    date_rule: str = Field(min_length=1, max_length=2_048)
    request_spacing_seconds: float = Field(ge=0)
    retry_count: int = Field(ge=0, le=5)
    retry_window_days: int = Field(ge=0, le=14)


class SourceQueryBinding(KernelContract):
    """One exact construct query bound to one source-specific syntax."""

    binding_id: StableId
    query_id: StableId
    source_id: SearchSourceId
    lens: SearchLens
    canonical_query: str = Field(min_length=1, max_length=4_096)
    backend_query: str = Field(min_length=1, max_length=4_096)
    request_parameters: dict[str, str]
    post_fetch_date_filter_required: bool

    @field_validator("request_parameters")
    @classmethod
    def _sort_parameters(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("source query requires exact request parameters")
        return dict(sorted(value.items()))

    @model_validator(mode="after")
    def _validate_binding(self) -> SourceQueryBinding:
        expected_id = f"{self.source_id.value}:{self.lens.value}"
        if self.binding_id != expected_id or self.query_id != self.lens.value:
            raise ValueError("query binding IDs must derive from source and lens")
        if self.source_id is SearchSourceId.DBLP and not self.post_fetch_date_filter_required:
            raise ValueError("DBLP publication dates must be filtered after retrieval")
        if self.source_id is not SearchSourceId.DBLP and self.post_fetch_date_filter_required:
            raise ValueError("only DBLP lacks a bound publication-date filter")
        return self


class KnownItemSentinel(KernelContract):
    """Pre-protocol known paper used only to test retrieval sensitivity."""

    sentinel_id: StableId
    title: str = Field(min_length=1, max_length=512)
    stable_locator: NonEmptyText
    expected_stratum: ConstructStratum
    pilot_release_id: StableId | None = None
    admission_values_pre_extracted: Literal[False] = False


class PilotReleaseBoundary(KernelContract):
    """Immutable boundary around a Task 263.6.6 calibration candidate."""

    release_id: StableId
    task_263_6_6_report_hash: Sha256
    task_263_6_6_projection_hash: Sha256
    role: Literal["protocol-development-pilot"] = "protocol-development-pilot"
    primary_cohort_eligible: Literal[False] = False
    secondary_calibration_only: Literal[True] = True


class EligibilityCriterion(KernelContract):
    """Ordered inclusion or exclusion rule applied without outcome knowledge."""

    criterion_id: StableId
    decision: Literal["include", "exclude"]
    rule: str = Field(min_length=1, max_length=2_048)
    evidence_required: str = Field(min_length=1, max_length=2_048)


class DeduplicationPlan(KernelContract):
    """Paper, benchmark-family, and revision deduplication contract."""

    paper_identity_priority: list[StableId] = Field(min_length=4)
    benchmark_family_rule: str = Field(min_length=1, max_length=2_048)
    release_selection_rule: str = Field(min_length=1, max_length=2_048)
    related_revision_rule: str = Field(min_length=1, max_length=2_048)
    multi_paper_rule: str = Field(min_length=1, max_length=2_048)
    duplicate_tasks_are_independent: Literal[False] = False
    duplicate_revisions_are_independent: Literal[False] = False

    @field_validator("paper_identity_priority")
    @classmethod
    def _unique_identity_keys(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("paper identity priority keys must be unique")
        return value


class ReleaseUnitPlan(KernelContract):
    """Scientific unit and nested-observation boundary."""

    study_unit: Literal["fixed-revision benchmark release"] = (
        "fixed-revision benchmark release"
    )
    independence_unit: Literal["unique benchmark family"] = "unique benchmark family"
    nested_observation: Literal["technical task, seed, attempt, difficulty, or agent vote"] = (
        "technical task, seed, attempt, difficulty, or agent vote"
    )
    primary_non_pilot_release_target: int = Field(
        ge=PRIMARY_NON_PILOT_RELEASE_TARGET
    )
    primary_excludes_protocol_pilots: Literal[True] = True
    latest_pre_cutoff_revision_primary: Literal[True] = True
    earlier_revisions_longitudinal_only: Literal[True] = True
    same_family_revisions_independent: Literal[False] = False
    primary_construct_assignment_rule: str = Field(min_length=1, max_length=2_048)
    full_lifecycle_definition: str = Field(min_length=1, max_length=2_048)


class EvidenceCodeDefinition(KernelContract):
    """Operational meaning of one evidence state."""

    state: EvidenceState
    definition: str = Field(min_length=1, max_length=2_048)
    counts_as_admission_pass: bool
    counts_as_determinate_coverage: bool

    @model_validator(mode="after")
    def _validate_semantics(self) -> EvidenceCodeDefinition:
        if self.counts_as_admission_pass != (
            self.state is EvidenceState.VERIFIED_PASS
        ):
            raise ValueError("only verified-pass can satisfy an admission gate")
        determinate = self.state in {
            EvidenceState.VERIFIED_PASS,
            EvidenceState.VERIFIED_FAIL,
        }
        if self.counts_as_determinate_coverage != determinate:
            raise ValueError("only supported pass/fail evidence is determinate")
        return self


class ExtractionFieldSpec(KernelContract):
    """Machine-readable codebook entry for one release field."""

    field_id: StableId
    definition: str = Field(min_length=1, max_length=2_048)
    value_type: NonEmptyText
    critical: bool
    dual_human_code_required: bool
    admission_gate: AdmissionGate | None = None
    unknown_policy: Literal[
        "retain-explicit-state-never-impute-pass"
    ] = "retain-explicit-state-never-impute-pass"

    @model_validator(mode="after")
    def _validate_field(self) -> ExtractionFieldSpec:
        if self.dual_human_code_required and not self.critical:
            raise ValueError("dual-coded codebook fields must be critical")
        return self


class HumanCodingPlan(KernelContract):
    """Independent human screening, coding, and adjudication boundary."""

    reviewer_roles: list[StableId]
    adjudicator_role: StableId
    actual_human_identities_assigned: Literal[False] = False
    execution_blocked_until_humans_assigned: Literal[True] = True
    title_abstract_dual_screen_fraction: float = Field(default=1.0, ge=1.0, le=1.0)
    full_text_dual_screen_fraction: float = Field(default=1.0, ge=1.0, le=1.0)
    critical_field_dual_code_fraction: float = Field(default=1.0, ge=1.0, le=1.0)
    coders_blinded_to_other_codes_until_lock: Literal[True] = True
    llm_screening_decision_allowed: Literal[False] = False
    exact_agreement_threshold: float = Field(default=0.9, ge=0.9, le=0.9)
    cohen_kappa_threshold_when_estimable: float = Field(
        default=0.8, ge=0.8, le=0.8
    )
    no_variation_required_exact_agreement: float = Field(
        default=1.0, ge=1.0, le=1.0
    )
    overall_critical_coverage_threshold: float = Field(
        default=0.9, ge=0.9, le=0.9
    )
    per_critical_field_coverage_threshold: float = Field(
        default=0.85, ge=0.85, le=0.85
    )
    critical_dual_code_field_ids: list[StableId] = Field(min_length=8)
    adjudication_rule: str = Field(min_length=1, max_length=2_048)
    legal_opinion_prohibited: Literal[True] = True
    authorship_release_submission_decisions_automated: Literal[False] = False

    @field_validator("reviewer_roles", "critical_dual_code_field_ids")
    @classmethod
    def _sort_unique(cls, value: list[str]) -> list[str]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("human coding lists must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_roles(self) -> HumanCodingPlan:
        if len(self.reviewer_roles) != 2:
            raise ValueError("exactly two independent reviewer roles are required")
        if self.adjudicator_role in self.reviewer_roles:
            raise ValueError("the adjudicator must be a distinct human role")
        return self


class PrimaryEndpointSpec(KernelContract):
    """Frozen descriptive endpoint and exact denominator behavior."""

    endpoint_id: StableId
    estimand: str = Field(min_length=1, max_length=2_048)
    calculation: str = Field(min_length=1, max_length=4_096)
    missing_value_rule: str = Field(min_length=1, max_length=2_048)
    interval_rule: str = Field(min_length=1, max_length=2_048)
    causal_interpretation_allowed: Literal[False] = False


class SensitivityAnalysisSpec(KernelContract):
    """Predeclared descriptive sensitivity without data-driven regrouping."""

    sensitivity_id: StableId
    grouping_or_exclusion: str = Field(min_length=1, max_length=2_048)
    minimum_stratum_size_for_rate: int = Field(ge=2)
    fallback_when_small: Literal["report-counts-only"] = "report-counts-only"
    changes_primary_endpoint: Literal[False] = False


class StopRuleSpec(KernelContract):
    """Prospective terminal condition and truthful negative endpoint."""

    stop_rule_id: StableId
    trigger: str = Field(min_length=1, max_length=2_048)
    terminal_output: Literal[
        "open-resource-or-diagnostic-negative"
    ] = "open-resource-or-diagnostic-negative"
    mechanism_effect_claim_allowed: Literal[False] = False


class FreezeAnchor(KernelContract):
    """Source, runner, parent revision, and registration-time binding."""

    parent_git_commit: StableId
    protocol_source_sha256: Sha256
    frozen_runner_sha256: Sha256
    frozen_at: datetime
    search_start_date: date
    search_cutoff_date: date
    frozen_before_non_pilot_extraction: Literal[True] = True

    @field_validator("frozen_at")
    @classmethod
    def _require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("protocol freeze time must be timezone aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _validate_dates(self) -> FreezeAnchor:
        if self.search_start_date != SEARCH_START_DATE:
            raise ValueError("search start date must remain frozen")
        if self.search_cutoff_date != SEARCH_CUTOFF_DATE:
            raise ValueError("search cutoff date must remain frozen")
        if self.search_start_date > self.search_cutoff_date:
            raise ValueError("search date window is inverted")
        return self


REQUIRED_CODEBOOK_FIELD_IDS = {
    "artifact-hashes",
    "authorship-decision-owner",
    "benchmark-family-id",
    "benchmark-name",
    "cloud-dependency",
    "compression-ratio",
    "contamination-policy",
    "content-redistribution-rights",
    "cpu-envelope",
    "dataset-revision",
    "dependency-lock",
    "derivative-creation-rights",
    "deterministic-scorer-command",
    "evidence-locators",
    "field-conflicts",
    "gpu-envelope",
    "headline-task-count",
    "human-responsibility-boundary",
    "independence-rule",
    "independent-source-upper-bound",
    "judge-role",
    "local-execution-rights",
    "outcome-colocation",
    "paper-revision",
    "primary-construct",
    "primary-endpoint-kind",
    "primary-locator",
    "primary-metric",
    "primary-title",
    "privileged-execution",
    "publication-maturity",
    "publication-year",
    "release-decision-owner",
    "release-id",
    "repository-revision",
    "secondary-constructs",
    "software-reuse-rights",
    "split-seal",
    "strong-baseline-command",
    "strong-baseline-identity",
    "unknown-reason",
    "wall-clock-envelope",
}
REQUIRED_PRIMARY_ENDPOINT_IDS = {
    "complete-conjunction-pass-rate",
    "critical-missing-evidence-rate",
    "per-gate-pass-rates",
    "task-to-independent-unit-compression",
}
REQUIRED_STOP_RULE_IDS = {
    "agreement-failure",
    "candidate-model-or-outcome-use",
    "coverage-failure",
    "human-responsibility-missing",
    "insufficient-release-census",
    "pilot-leakage",
    "post-extraction-protocol-change",
    "search-recall-failure",
    "source-availability-failure",
    "unit-pseudoreplication",
}
EXPECTED_PILOT_RELEASE_IDS = {
    "autosdt-5k",
    "core-bench",
    "qrdata",
    "scienceagentbench",
}


class BenchmarkValidityProtocol(KernelContract):
    """Complete pre-extraction systematic-mapping protocol."""

    schema_version: Literal["benchmark-validity-protocol-v1"] = (
        "benchmark-validity-protocol-v1"
    )
    protocol_id: StableId
    status: ProtocolStatus
    title: str = Field(min_length=1, max_length=512)
    intended_readers: list[NonEmptyText]
    research_questions: list[str] = Field(min_length=3, max_length=3)
    methodological_anchors: list[MethodologicalAnchor] = Field(min_length=8)
    freeze_anchor: FreezeAnchor
    search_sources: list[SearchSourceSpec] = Field(min_length=4, max_length=4)
    query_bindings: list[SourceQueryBinding] = Field(min_length=28, max_length=28)
    known_item_sentinels: list[KnownItemSentinel] = Field(min_length=12)
    known_item_recall_threshold: float = Field(ge=0.9, le=1)
    citation_chaining_rule: str = Field(min_length=1, max_length=2_048)
    source_verification_hierarchy: list[NonEmptyText] = Field(min_length=5)
    pilot_boundaries: list[PilotReleaseBoundary] = Field(min_length=4, max_length=4)
    release_unit_plan: ReleaseUnitPlan
    eligibility_criteria: list[EligibilityCriterion] = Field(min_length=8)
    deduplication_plan: DeduplicationPlan
    construct_strata: list[ConstructStratum] = Field(min_length=7, max_length=7)
    evidence_code_definitions: list[EvidenceCodeDefinition] = Field(
        min_length=7, max_length=7
    )
    extraction_codebook: list[ExtractionFieldSpec] = Field(min_length=40)
    human_coding_plan: HumanCodingPlan
    primary_endpoints: list[PrimaryEndpointSpec] = Field(min_length=4, max_length=4)
    sensitivity_analyses: list[SensitivityAnalysisSpec] = Field(min_length=5)
    stop_rules: list[StopRuleSpec] = Field(min_length=8)
    negative_publication_endpoint: str = Field(min_length=1, max_length=2_048)
    prohibited_claims: list[NonEmptyText] = Field(min_length=5)
    search_execution_started: Literal[False] = False
    extracted_record_count: Literal[0] = 0
    benchmark_outcomes_accessed: Literal[False] = False
    candidate_model_calls: Literal[False] = False
    research_question_issued: Literal[False] = False
    confirmation_panel_created: Literal[False] = False
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    protocol_hash: Sha256

    @field_validator(
        "methodological_anchors",
        "search_sources",
        "query_bindings",
        "known_item_sentinels",
        "pilot_boundaries",
        "eligibility_criteria",
        "evidence_code_definitions",
        "extraction_codebook",
        "primary_endpoints",
        "sensitivity_analyses",
        "stop_rules",
    )
    @classmethod
    def _sort_contract_lists(
        cls, value: list[Any], info: ValidationInfo
    ) -> list[Any]:
        identifiers_by_field = {
            "methodological_anchors": "anchor_id",
            "search_sources": "source_id",
            "query_bindings": "binding_id",
            "known_item_sentinels": "sentinel_id",
            "pilot_boundaries": "release_id",
            "eligibility_criteria": "criterion_id",
            "evidence_code_definitions": "state",
            "extraction_codebook": "field_id",
            "primary_endpoints": "endpoint_id",
            "sensitivity_analyses": "sensitivity_id",
            "stop_rules": "stop_rule_id",
        }
        if info.field_name is None:
            raise ValueError("contract list validator requires a field name")
        id_name = identifiers_by_field[info.field_name]
        normalized = sorted(
            value,
            key=lambda item: str(getattr(item, id_name).value)
            if isinstance(getattr(item, id_name), Enum)
            else str(getattr(item, id_name)),
        )
        identifiers = [
            getattr(item, id_name).value
            if isinstance(getattr(item, id_name), Enum)
            else getattr(item, id_name)
            for item in normalized
        ]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError(f"{id_name} values must be unique")
        return normalized

    @field_validator("construct_strata")
    @classmethod
    def _sort_strata(cls, value: list[ConstructStratum]) -> list[ConstructStratum]:
        normalized = sorted(value, key=lambda item: item.value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("construct strata must be unique")
        return normalized

    @field_validator("prohibited_claims")
    @classmethod
    def _sort_claims(cls, value: list[str]) -> list[str]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("prohibited claims must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_protocol(
        self, info: ValidationInfo
    ) -> BenchmarkValidityProtocol:
        if self.status is not ProtocolStatus.FROZEN_PRE_EXTRACTION:
            raise ValueError("protocol must remain frozen before extraction")
        source_ids = {item.source_id for item in self.search_sources}
        if source_ids != set(SearchSourceId):
            raise ValueError("all four frozen discovery indexes are required")
        expected_pairs = {
            (source_id, lens)
            for source_id in SearchSourceId
            for lens in SearchLens
        }
        observed_pairs = {
            (item.source_id, item.lens) for item in self.query_bindings
        }
        if observed_pairs != expected_pairs:
            raise ValueError("each discovery source must bind each construct lens")
        if set(self.construct_strata) != set(ConstructStratum):
            raise ValueError("the seven construct strata must remain complete")
        pilot_ids = {item.release_id for item in self.pilot_boundaries}
        if pilot_ids != EXPECTED_PILOT_RELEASE_IDS:
            raise ValueError("the Task 263.6.6 pilot boundary changed")
        if self.release_unit_plan.primary_non_pilot_release_target < 20:
            raise ValueError("primary prospective cohort needs at least 20 releases")
        sentinel_pilots = {
            item.pilot_release_id
            for item in self.known_item_sentinels
            if item.pilot_release_id is not None
        }
        if sentinel_pilots != EXPECTED_PILOT_RELEASE_IDS:
            raise ValueError("all protocol pilots must also be recall sentinels")
        code_states = {item.state for item in self.evidence_code_definitions}
        if code_states != set(EvidenceState):
            raise ValueError("unknown and conflict semantics must be exhaustive")
        field_ids = {item.field_id for item in self.extraction_codebook}
        if field_ids != REQUIRED_CODEBOOK_FIELD_IDS:
            raise ValueError("Benchmark Admission Card codebook changed")
        codebook_dual = {
            item.field_id
            for item in self.extraction_codebook
            if item.dual_human_code_required
        }
        if codebook_dual != set(
            self.human_coding_plan.critical_dual_code_field_ids
        ):
            raise ValueError("human coding plan must match the frozen codebook")
        endpoint_ids = {item.endpoint_id for item in self.primary_endpoints}
        if endpoint_ids != REQUIRED_PRIMARY_ENDPOINT_IDS:
            raise ValueError("the four descriptive primary endpoints changed")
        stop_ids = {item.stop_rule_id for item in self.stop_rules}
        if stop_ids != REQUIRED_STOP_RULE_IDS:
            raise ValueError("prospective stop rules changed")
        skip_hash = bool(info.context and info.context.get("skip_hash"))
        if not skip_hash and self.protocol_hash != self.calculated_hash():
            raise BenchmarkValidityIntegrityError("benchmark protocol_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> BenchmarkValidityProtocol:
        """Normalize and content-address a result-free protocol."""

        payload = dict(values)
        payload.update(
            {
                "schema_version": "benchmark-validity-protocol-v1",
                "status": ProtocolStatus.FROZEN_PRE_EXTRACTION,
                "search_execution_started": False,
                "extracted_record_count": 0,
                "benchmark_outcomes_accessed": False,
                "candidate_model_calls": False,
                "research_question_issued": False,
                "confirmation_panel_created": False,
                "public_release_authorized": False,
                "external_submission_authorized": False,
            }
        )
        normalized = cls.model_validate(
            {
                **payload,
                "protocol_hash": "0" * 64,
            },
            context={"skip_hash": True},
        )
        normalized_payload = normalized.model_dump(
            mode="json", exclude={"protocol_hash"}
        )
        normalized_payload["protocol_hash"] = canonical_sha256(normalized_payload)
        return cls.model_validate(normalized_payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"protocol_hash"})
        )

    def verify_integrity(self) -> None:
        if self.protocol_hash != self.calculated_hash():
            raise BenchmarkValidityIntegrityError("benchmark protocol_hash mismatch")


class EvidenceLocator(KernelContract):
    """Exact primary-source evidence supporting a card field."""

    locator_id: StableId
    source_role: Literal[
        "paper",
        "repository",
        "dataset",
        "artifact",
        "license",
        "documentation",
    ]
    stable_locator: NonEmptyText
    revision: NonEmptyText | None = None
    artifact_sha256: Sha256 | None = None
    retrieved_at: datetime


class GateAssessment(KernelContract):
    """One final adjudicated admission decision with evidence."""

    gate: AdmissionGate
    state: EvidenceState
    evidence: list[EvidenceLocator] = Field(default_factory=list)
    rationale: str = Field(min_length=1, max_length=2_048)

    @model_validator(mode="after")
    def _validate_evidence(self) -> GateAssessment:
        if self.state in {
            EvidenceState.VERIFIED_PASS,
            EvidenceState.VERIFIED_FAIL,
        } and not self.evidence:
            raise ValueError("a determinate gate code requires primary evidence")
        return self


class ComputeEnvelope(KernelContract):
    """Reported or reproduced execution-resource boundary."""

    dependency_lock_locator: NonEmptyText | None = None
    cpu_description: NonEmptyText | None = None
    gpu_description: NonEmptyText | None = None
    cloud_dependency: bool | None = None
    privileged_execution: bool | None = None
    download_bytes: int | None = Field(default=None, ge=0)
    wall_clock_seconds: float | None = Field(default=None, ge=0)


class BenchmarkAdmissionCard(KernelContract):
    """Machine-readable final record for one fixed benchmark release."""

    schema_version: Literal["benchmark-admission-card-v1"] = (
        "benchmark-admission-card-v1"
    )
    release_id: StableId
    benchmark_family_id: StableId
    benchmark_name: NonEmptyText
    primary_title: str = Field(min_length=1, max_length=512)
    primary_locator: NonEmptyText
    publication_year: int = Field(ge=2023, le=2026)
    publication_maturity: Literal["peer-reviewed", "preprint", "other"]
    primary_construct: ConstructStratum
    secondary_constructs: list[ConstructStratum] = Field(default_factory=list)
    paper_revision: NonEmptyText
    repository_revision: NonEmptyText | None = None
    dataset_revision: NonEmptyText | None = None
    artifact_hashes: dict[str, Sha256] = Field(default_factory=dict)
    headline_task_count: int | None = Field(default=None, ge=1)
    independent_source_upper_bound: int | None = Field(default=None, ge=1)
    independence_rule: str = Field(min_length=1, max_length=2_048)
    compression_ratio: float | None = Field(default=None, ge=1)
    primary_endpoint_kind: NonEmptyText
    primary_metric: NonEmptyText
    judge_role: JudgeRole
    deterministic_scorer_command: list[NonEmptyText] = Field(default_factory=list)
    strong_baseline_identity: NonEmptyText | None = None
    strong_baseline_command: list[NonEmptyText] = Field(default_factory=list)
    compute_envelope: ComputeEnvelope
    split_seal_description: str = Field(min_length=1, max_length=2_048)
    contamination_policy: str = Field(min_length=1, max_length=2_048)
    outcome_colocation: bool | None = None
    human_responsibility_boundary: str = Field(min_length=1, max_length=2_048)
    gate_assessments: list[GateAssessment] = Field(
        min_length=len(AdmissionGate), max_length=len(AdmissionGate)
    )
    dual_code_record_hashes: list[Sha256] = Field(min_length=1)
    protocol_development_pilot: bool
    primary_cohort_eligible: bool
    pre_protocol_known_item: bool
    card_hash: Sha256

    @field_validator("secondary_constructs")
    @classmethod
    def _sort_secondary(
        cls, value: list[ConstructStratum]
    ) -> list[ConstructStratum]:
        normalized = sorted(value, key=lambda item: item.value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("secondary construct tags must be unique")
        return normalized

    @field_validator("artifact_hashes")
    @classmethod
    def _sort_artifacts(cls, value: dict[str, str]) -> dict[str, str]:
        return dict(sorted(value.items()))

    @field_validator("gate_assessments")
    @classmethod
    def _sort_gates(cls, value: list[GateAssessment]) -> list[GateAssessment]:
        normalized = sorted(value, key=lambda item: item.gate.value)
        if {item.gate for item in normalized} != set(AdmissionGate):
            raise ValueError("admission card must code every non-compensating gate")
        return normalized

    @field_validator("dual_code_record_hashes")
    @classmethod
    def _sort_code_hashes(cls, value: list[str]) -> list[str]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("dual-code record hashes must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_card(self) -> BenchmarkAdmissionCard:
        if self.protocol_development_pilot and self.primary_cohort_eligible:
            raise ValueError("protocol-development pilots cannot enter primary analysis")
        if (
            self.headline_task_count is not None
            and self.independent_source_upper_bound is not None
        ):
            expected = self.headline_task_count / self.independent_source_upper_bound
            if self.compression_ratio is None or not math.isclose(
                self.compression_ratio, expected, rel_tol=1e-12, abs_tol=1e-12
            ):
                raise ValueError("compression ratio must equal tasks divided by units")
        elif self.compression_ratio is not None:
            raise ValueError("compression ratio needs both task and unit counts")
        complete_pass = all(
            item.state is EvidenceState.VERIFIED_PASS
            for item in self.gate_assessments
        )
        if self.primary_cohort_eligible and self.protocol_development_pilot:
            raise ValueError("pilot leakage into the primary cohort")
        if self.card_hash != self.calculated_hash():
            raise BenchmarkValidityIntegrityError("admission card_hash mismatch")
        del complete_pass
        return self

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"card_hash"}))


class SearchExecutionLogEntry(KernelContract):
    """Future append-only query log shape frozen by this protocol."""

    schema_version: Literal["benchmark-search-log-entry-v1"] = (
        "benchmark-search-log-entry-v1"
    )
    binding_id: StableId
    executed_at: datetime
    request_url_sha256: Sha256
    response_artifact_sha256: Sha256
    response_count: int = Field(ge=0)
    page_count: int = Field(ge=1)
    status: Literal["complete", "partial", "unreachable"]
    retry_count: int = Field(ge=0, le=5)
    benchmark_records_extracted_before_protocol_freeze: Literal[False] = False
    log_entry_hash: Sha256

    @model_validator(mode="after")
    def _validate_log(self) -> SearchExecutionLogEntry:
        if self.log_entry_hash != self.calculated_hash():
            raise BenchmarkValidityIntegrityError("search log entry hash mismatch")
        return self

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"log_entry_hash"})
        )


class ScreeningRecord(KernelContract):
    """Future dual-human screening record shape."""

    schema_version: Literal["benchmark-screening-record-v1"] = (
        "benchmark-screening-record-v1"
    )
    candidate_id: StableId
    bibliographic_identity: NonEmptyText
    reviewer_a_decision: ScreeningDecision
    reviewer_b_decision: ScreeningDecision
    adjudicated_decision: ScreeningDecision
    exclusion_criterion_id: StableId | None = None
    rationale: str = Field(min_length=1, max_length=2_048)
    record_hash: Sha256

    @model_validator(mode="after")
    def _validate_record(self) -> ScreeningRecord:
        if (
            self.adjudicated_decision is ScreeningDecision.EXCLUDE
            and self.exclusion_criterion_id is None
        ):
            raise ValueError("exclusion requires a frozen criterion")
        if self.record_hash != self.calculated_hash():
            raise BenchmarkValidityIntegrityError("screening record hash mismatch")
        return self

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"record_hash"})
        )


class BenchmarkValidityProtocolProjection(KernelContract):
    """Dependency-free projection replayed before any search execution."""

    schema_version: Literal["benchmark-validity-protocol-projection-v1"] = (
        "benchmark-validity-protocol-projection-v1"
    )
    protocol_id: StableId
    protocol_hash: Sha256
    frozen_at: datetime
    primary_non_pilot_release_target: int = Field(ge=20)
    pilot_release_ids: list[StableId]
    pilot_primary_eligibility: dict[StableId, Literal[False]]
    source_ids: list[StableId]
    lens_ids: list[StableId]
    query_binding_count: int = Field(ge=28)
    critical_dual_code_field_ids: list[StableId] = Field(min_length=8)
    primary_endpoint_ids: list[StableId] = Field(min_length=4, max_length=4)
    stop_rule_ids: list[StableId] = Field(min_length=8)
    extracted_record_count: Literal[0] = 0
    search_execution_started: Literal[False] = False
    benchmark_outcomes_accessed: Literal[False] = False
    candidate_model_calls: Literal[False] = False
    research_question_issued: Literal[False] = False
    confirmation_panel_created: Literal[False] = False
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    projection_sha256: Sha256

    @model_validator(mode="after")
    def _validate_projection(self) -> BenchmarkValidityProtocolProjection:
        if set(self.pilot_release_ids) != EXPECTED_PILOT_RELEASE_IDS:
            raise ValueError("protocol projection pilot boundary changed")
        if set(self.source_ids) != {item.value for item in SearchSourceId}:
            raise ValueError("protocol projection source set changed")
        if set(self.lens_ids) != {item.value for item in SearchLens}:
            raise ValueError("protocol projection lens set changed")
        if self.query_binding_count != len(SearchSourceId) * len(SearchLens):
            raise ValueError("protocol projection query count changed")
        if self.projection_sha256 != self.calculated_hash():
            raise BenchmarkValidityIntegrityError("protocol projection hash mismatch")
        return self

    @classmethod
    def create(
        cls, protocol: BenchmarkValidityProtocol
    ) -> BenchmarkValidityProtocolProjection:
        protocol.verify_integrity()
        payload: dict[str, Any] = {
            "schema_version": "benchmark-validity-protocol-projection-v1",
            "protocol_id": protocol.protocol_id,
            "protocol_hash": protocol.protocol_hash,
            "frozen_at": protocol.freeze_anchor.frozen_at,
            "primary_non_pilot_release_target": (
                protocol.release_unit_plan.primary_non_pilot_release_target
            ),
            "pilot_release_ids": sorted(
                item.release_id for item in protocol.pilot_boundaries
            ),
            "pilot_primary_eligibility": {
                item.release_id: False
                for item in sorted(
                    protocol.pilot_boundaries, key=lambda item: item.release_id
                )
            },
            "source_ids": sorted(item.value for item in SearchSourceId),
            "lens_ids": sorted(item.value for item in SearchLens),
            "query_binding_count": len(protocol.query_bindings),
            "critical_dual_code_field_ids": (
                protocol.human_coding_plan.critical_dual_code_field_ids
            ),
            "primary_endpoint_ids": sorted(
                item.endpoint_id for item in protocol.primary_endpoints
            ),
            "stop_rule_ids": sorted(
                item.stop_rule_id for item in protocol.stop_rules
            ),
            "extracted_record_count": 0,
            "search_execution_started": False,
            "benchmark_outcomes_accessed": False,
            "candidate_model_calls": False,
            "research_question_issued": False,
            "confirmation_panel_created": False,
            "public_release_authorized": False,
            "external_submission_authorized": False,
        }
        payload["projection_sha256"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"projection_sha256"})
        )

    def runner_projection(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"projection_sha256"})


class ProtocolReplayObservation(KernelContract):
    """One independent interpreter's frozen-probe observation."""

    schema_version: Literal["benchmark-validity-protocol-replay-observation-v1"] = (
        "benchmark-validity-protocol-replay-observation-v1"
    )
    runtime: InterpreterRuntime
    projection_sha256: Sha256
    output_file_sha256: Sha256
    output_contract_sha256: Sha256
    return_code: Literal[0] = 0
    observation_hash: Sha256

    @model_validator(mode="after")
    def _validate_observation(self) -> ProtocolReplayObservation:
        if self.observation_hash != self.calculated_hash():
            raise BenchmarkValidityIntegrityError("replay observation hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ProtocolReplayObservation:
        payload = dict(values)
        payload.update(
            {
                "schema_version": (
                    "benchmark-validity-protocol-replay-observation-v1"
                ),
                "return_code": 0,
            }
        )
        payload["observation_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"observation_hash"})
        )


class ProtocolReplayCertificate(KernelContract):
    """Exact two-interpreter certificate over a result-free projection."""

    schema_version: Literal["benchmark-validity-protocol-replay-certificate-v1"] = (
        "benchmark-validity-protocol-replay-certificate-v1"
    )
    protocol_hash: Sha256
    projection_sha256: Sha256
    replay_input_sha256: Sha256
    frozen_runner_sha256: Sha256
    observations: list[ProtocolReplayObservation] = Field(min_length=2)
    distinct_interpreter_installations: Literal[True] = True
    exact_projection_match: Literal[True] = True
    extracted_record_count: Literal[0] = 0
    benchmark_outcomes_accessed: Literal[False] = False
    candidate_model_calls: Literal[False] = False
    certificate_hash: Sha256

    @field_validator("observations")
    @classmethod
    def _sort_observations(
        cls, value: list[ProtocolReplayObservation]
    ) -> list[ProtocolReplayObservation]:
        normalized = sorted(value, key=lambda item: item.runtime.role_id)
        roles = [item.runtime.role_id for item in normalized]
        if len(roles) != len(set(roles)):
            raise ValueError("replay roles must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_certificate(self) -> ProtocolReplayCertificate:
        locator_hashes = {
            item.runtime.executable_locator_hash for item in self.observations
        }
        if len(locator_hashes) < 2:
            raise ValueError("replay requires distinct interpreter installations")
        projections = {item.projection_sha256 for item in self.observations}
        if projections != {self.projection_sha256}:
            raise ValueError("interpreter projections do not exactly match")
        output_contracts = {
            item.output_contract_sha256 for item in self.observations
        }
        if len(output_contracts) != 1:
            raise ValueError("frozen probe outputs differ across interpreters")
        if self.certificate_hash != self.calculated_hash():
            raise BenchmarkValidityIntegrityError("replay certificate hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ProtocolReplayCertificate:
        payload = dict(values)
        payload.update(
            {
                "schema_version": (
                    "benchmark-validity-protocol-replay-certificate-v1"
                ),
                "distinct_interpreter_installations": True,
                "exact_projection_match": True,
                "extracted_record_count": 0,
                "benchmark_outcomes_accessed": False,
                "candidate_model_calls": False,
            }
        )
        observations = sorted(
            payload["observations"], key=lambda item: item.runtime.role_id
        )
        payload["observations"] = observations
        payload["certificate_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"certificate_hash"})
        )


class BenchmarkValidityProtocolFreezeReport(KernelContract):
    """Formal pre-extraction report; it contains no benchmark cards."""

    schema_version: Literal["benchmark-validity-protocol-freeze-report-v1"] = (
        "benchmark-validity-protocol-freeze-report-v1"
    )
    protocol: BenchmarkValidityProtocol
    projection: BenchmarkValidityProtocolProjection
    replay_certificate: ProtocolReplayCertificate
    status: ProtocolStatus
    next_action: Literal["assign-humans-then-execute-frozen-census"] = (
        "assign-humans-then-execute-frozen-census"
    )
    extracted_record_count: Literal[0] = 0
    benchmark_outcomes_accessed: Literal[False] = False
    candidate_model_calls: Literal[False] = False
    mechanism_effect_claim_authorized: Literal[False] = False
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    report_hash: Sha256

    @model_validator(mode="after")
    def _validate_report(self) -> BenchmarkValidityProtocolFreezeReport:
        self.protocol.verify_integrity()
        if self.projection.protocol_hash != self.protocol.protocol_hash:
            raise ValueError("projection is not bound to the protocol")
        if self.replay_certificate.protocol_hash != self.protocol.protocol_hash:
            raise ValueError("replay certificate is not bound to the protocol")
        if (
            self.replay_certificate.projection_sha256
            != self.projection.projection_sha256
        ):
            raise ValueError("replay certificate is not bound to the projection")
        if self.status is not ProtocolStatus.FROZEN_PRE_EXTRACTION:
            raise ValueError("freeze report has an invalid status")
        if self.report_hash != self.calculated_hash():
            raise BenchmarkValidityIntegrityError("freeze report_hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        protocol: BenchmarkValidityProtocol,
        projection: BenchmarkValidityProtocolProjection,
        replay_certificate: ProtocolReplayCertificate,
    ) -> BenchmarkValidityProtocolFreezeReport:
        payload: dict[str, Any] = {
            "schema_version": "benchmark-validity-protocol-freeze-report-v1",
            "protocol": protocol,
            "projection": projection,
            "replay_certificate": replay_certificate,
            "status": ProtocolStatus.FROZEN_PRE_EXTRACTION,
            "next_action": "assign-humans-then-execute-frozen-census",
            "extracted_record_count": 0,
            "benchmark_outcomes_accessed": False,
            "candidate_model_calls": False,
            "mechanism_effect_claim_authorized": False,
            "public_release_authorized": False,
            "external_submission_authorized": False,
        }
        payload["report_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"report_hash"}))

    def verify_integrity(self) -> None:
        self.protocol.verify_integrity()
        if self.report_hash != self.calculated_hash():
            raise BenchmarkValidityIntegrityError("freeze report_hash mismatch")


class BenchmarkValidityArtifactManifest(KernelContract):
    """Content inventory for protocol, projection, replay, and schemas."""

    schema_version: Literal["benchmark-validity-artifact-manifest-v1"] = (
        "benchmark-validity-artifact-manifest-v1"
    )
    protocol_hash: Sha256
    report_hash: Sha256
    projection_sha256: Sha256
    replay_certificate_hash: Sha256
    files: dict[NonEmptyText, Sha256]
    extracted_record_count: Literal[0] = 0
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    manifest_hash: Sha256

    @field_validator("files")
    @classmethod
    def _sort_files(cls, value: dict[str, str]) -> dict[str, str]:
        return dict(sorted(value.items()))

    @model_validator(mode="after")
    def _validate_manifest(self) -> BenchmarkValidityArtifactManifest:
        if self.manifest_hash != self.calculated_hash():
            raise BenchmarkValidityIntegrityError("protocol manifest_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> BenchmarkValidityArtifactManifest:
        payload = dict(values)
        payload.update(
            {
                "schema_version": "benchmark-validity-artifact-manifest-v1",
                "extracted_record_count": 0,
                "public_release_authorized": False,
                "external_submission_authorized": False,
            }
        )
        payload["files"] = dict(sorted(payload["files"].items()))
        payload["manifest_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"manifest_hash"})
        )


CANONICAL_QUERIES: dict[SearchLens, str] = {
    SearchLens.LITERATURE_DISCOVERY: (
        '("scientific agent" OR "research agent" OR "deep research agent") AND '
        '("literature discovery" OR "literature search" OR "scientific literature") '
        "AND (benchmark OR evaluation)"
    ),
    SearchLens.SCIENTIFIC_PROGRAMMING: (
        '("scientific agent" OR "research agent" OR "AI scientist") AND '
        '("scientific programming" OR "code generation" OR '
        '"machine learning experimentation") AND (benchmark OR evaluation)'
    ),
    SearchLens.DATA_ANALYSIS: (
        '("scientific agent" OR "research agent" OR "AI scientist") AND '
        '("data analysis" OR "data-driven discovery" OR "statistical reasoning") '
        "AND (benchmark OR evaluation)"
    ),
    SearchLens.HYPOTHESIS_VALIDATION: (
        '("scientific agent" OR "AI scientist") AND '
        '("hypothesis generation" OR "hypothesis validation" OR falsification) '
        "AND (benchmark OR evaluation)"
    ),
    SearchLens.COMPUTATIONAL_REPRODUCTION: (
        '("scientific agent" OR "research agent" OR "AI scientist") AND '
        '(reproducibility OR replication OR "paper reproduction") '
        "AND (benchmark OR evaluation)"
    ),
    SearchLens.EXPERIMENT_EXECUTION: (
        '("scientific agent" OR "AI scientist" OR "autonomous laboratory") AND '
        '("experiment execution" OR "laboratory automation" OR '
        '"closed-loop experiment") AND (benchmark OR evaluation)'
    ),
    SearchLens.FULL_RESEARCH_LIFECYCLE: (
        '("AI scientist" OR "automated scientific discovery" OR '
        '"autonomous scientific discovery" OR "automated AI research") AND '
        '("end-to-end" OR "full lifecycle" OR "research lifecycle") '
        "AND (benchmark OR evaluation OR dataset OR suite)"
    ),
}

ARXIV_QUERIES: dict[SearchLens, str] = {
    SearchLens.LITERATURE_DISCOVERY: (
        '(all:"scientific agent" OR all:"research agent" OR all:"deep research agent") '
        'AND (all:"literature discovery" OR all:"literature search" OR '
        'all:"scientific literature") AND (all:benchmark OR all:evaluation) '
        "AND submittedDate:[202301010000 TO 202607312359]"
    ),
    SearchLens.SCIENTIFIC_PROGRAMMING: (
        '(all:"scientific agent" OR all:"research agent" OR all:"AI scientist") '
        'AND (all:"scientific programming" OR all:"code generation" OR '
        'all:"machine learning experimentation") '
        "AND (all:benchmark OR all:evaluation) "
        "AND submittedDate:[202301010000 TO 202607312359]"
    ),
    SearchLens.DATA_ANALYSIS: (
        '(all:"scientific agent" OR all:"research agent" OR all:"AI scientist") '
        'AND (all:"data analysis" OR all:"data-driven discovery" OR '
        'all:"statistical reasoning") AND (all:benchmark OR all:evaluation) '
        "AND submittedDate:[202301010000 TO 202607312359]"
    ),
    SearchLens.HYPOTHESIS_VALIDATION: (
        '(all:"scientific agent" OR all:"AI scientist") AND '
        '(all:"hypothesis generation" OR all:"hypothesis validation" OR '
        "all:falsification) AND (all:benchmark OR all:evaluation) "
        "AND submittedDate:[202301010000 TO 202607312359]"
    ),
    SearchLens.COMPUTATIONAL_REPRODUCTION: (
        '(all:"scientific agent" OR all:"research agent" OR all:"AI scientist") '
        'AND (all:reproducibility OR all:replication OR all:"paper reproduction") '
        "AND (all:benchmark OR all:evaluation) "
        "AND submittedDate:[202301010000 TO 202607312359]"
    ),
    SearchLens.EXPERIMENT_EXECUTION: (
        '(all:"scientific agent" OR all:"AI scientist" OR '
        'all:"autonomous laboratory") AND (all:"experiment execution" OR '
        'all:"laboratory automation" OR all:"closed-loop experiment") '
        "AND (all:benchmark OR all:evaluation) "
        "AND submittedDate:[202301010000 TO 202607312359]"
    ),
    SearchLens.FULL_RESEARCH_LIFECYCLE: (
        '(all:"AI scientist" OR all:"automated scientific discovery" OR '
        'all:"autonomous scientific discovery" OR all:"automated AI research") '
        'AND (all:"end-to-end" OR all:"full lifecycle" OR '
        'all:"research lifecycle") AND (all:benchmark OR all:evaluation '
        "OR all:dataset OR all:suite) "
        "AND submittedDate:[202301010000 TO 202607312359]"
    ),
}

DBLP_QUERIES: dict[SearchLens, str] = {
    SearchLens.LITERATURE_DISCOVERY: (
        "scientific$|research$|deep$ agent$ literature$|discovery$|search$ "
        "benchmark$|evaluation$"
    ),
    SearchLens.SCIENTIFIC_PROGRAMMING: (
        "scientific$|research$|ai$ agent$|scientist$ programming$|code$|"
        "experimentation$ benchmark$|evaluation$"
    ),
    SearchLens.DATA_ANALYSIS: (
        "scientific$|research$|ai$ agent$|scientist$ data$ "
        "analysis$|discovery$|statistical$ benchmark$|evaluation$"
    ),
    SearchLens.HYPOTHESIS_VALIDATION: (
        "scientific$|ai$ agent$|scientist$ hypothesis$|falsification$ "
        "benchmark$|evaluation$"
    ),
    SearchLens.COMPUTATIONAL_REPRODUCTION: (
        "scientific$|research$|ai$ agent$|scientist$ "
        "reproducibility$|replication$|reproduction$ benchmark$|evaluation$"
    ),
    SearchLens.EXPERIMENT_EXECUTION: (
        "scientific$|ai$ agent$|scientist$|laboratory$ "
        "experiment$|automation$|closed-loop$ benchmark$|evaluation$"
    ),
    SearchLens.FULL_RESEARCH_LIFECYCLE: (
        "ai$|scientific$|research$ scientist$|agent$ automated$|autonomous$|"
        "end-to-end$ benchmark$|evaluation$|dataset$|suite$"
    ),
}


def _search_sources() -> list[SearchSourceSpec]:
    return [
        SearchSourceSpec(
            source_id=SearchSourceId.ARXIV,
            endpoint_url="https://export.arxiv.org/api/query",
            documentation_url="https://info.arxiv.org/help/api/user-manual.html",
            response_format="Atom 1.0 XML",
            page_size=200,
            pagination_rule=(
                "Start at zero; increase start by 200 until totalResults is "
                "exhausted; wait at least three seconds between requests."
            ),
            date_rule=(
                "submittedDate is embedded in every exact query and results are "
                "also checked against first-public-version date."
            ),
            request_spacing_seconds=3.0,
            retry_count=3,
            retry_window_days=7,
        ),
        SearchSourceSpec(
            source_id=SearchSourceId.OPENALEX,
            endpoint_url="https://api.openalex.org/works",
            documentation_url=(
                "https://developers.openalex.org/api-reference/works/list-works"
            ),
            response_format="JSON",
            page_size=100,
            pagination_rule=(
                "Begin with cursor=* and follow meta.next_cursor until null; "
                "store each raw response before deduplication."
            ),
            date_rule=(
                "Apply from_publication_date:2023-01-01 and "
                "to_publication_date:2026-07-31 in the filter parameter."
            ),
            request_spacing_seconds=1.0,
            retry_count=3,
            retry_window_days=7,
        ),
        SearchSourceSpec(
            source_id=SearchSourceId.CROSSREF,
            endpoint_url="https://api.crossref.org/works",
            documentation_url=(
                "https://www.crossref.org/documentation/retrieve-metadata/rest-api/"
            ),
            response_format="JSON",
            page_size=1_000,
            pagination_rule=(
                "Begin with cursor=*; follow message.next-cursor until empty; "
                "retain deposited metadata and stable identifiers."
            ),
            date_rule=(
                "Apply inclusive from-pub-date:2023-01-01 and "
                "until-pub-date:2026-07-31 filters."
            ),
            request_spacing_seconds=1.0,
            retry_count=3,
            retry_window_days=7,
        ),
        SearchSourceSpec(
            source_id=SearchSourceId.DBLP,
            endpoint_url="https://dblp.org/search/publ/api",
            documentation_url="https://dblp.org/faq/13501473.html",
            response_format="JSON",
            page_size=1_000,
            pagination_rule=(
                "Use f=0,h=1000,c=0. If a query reaches the 1000 cap, split it "
                "by frozen publication year 2023, 2024, 2025, 2026 without "
                "changing concept terms."
            ),
            date_rule=(
                "DBLP search has no bound date filter; retain only records whose "
                "metadata publication year is 2023 through 2026 and whose exact "
                "publication date, when available, is not after 2026-07-31."
            ),
            request_spacing_seconds=2.0,
            retry_count=3,
            retry_window_days=7,
        ),
    ]


def _query_bindings() -> list[SourceQueryBinding]:
    bindings: list[SourceQueryBinding] = []
    for source_id in SearchSourceId:
        for lens in SearchLens:
            if source_id is SearchSourceId.ARXIV:
                backend_query = ARXIV_QUERIES[lens]
                parameters = {
                    "max_results": "200",
                    "search_query": backend_query,
                    "sortBy": "submittedDate",
                    "sortOrder": "ascending",
                    "start": "0",
                }
            elif source_id is SearchSourceId.OPENALEX:
                backend_query = CANONICAL_QUERIES[lens]
                parameters = {
                    "cursor": "*",
                    "filter": (
                        "from_publication_date:2023-01-01,"
                        "to_publication_date:2026-07-31"
                    ),
                    "per-page": "100",
                    "search": backend_query,
                }
            elif source_id is SearchSourceId.CROSSREF:
                backend_query = CANONICAL_QUERIES[lens]
                parameters = {
                    "cursor": "*",
                    "filter": (
                        "from-pub-date:2023-01-01,"
                        "until-pub-date:2026-07-31"
                    ),
                    "query.bibliographic": backend_query,
                    "rows": "1000",
                }
            else:
                backend_query = DBLP_QUERIES[lens]
                parameters = {
                    "c": "0",
                    "f": "0",
                    "format": "json",
                    "h": "1000",
                    "q": backend_query,
                }
            bindings.append(
                SourceQueryBinding(
                    binding_id=f"{source_id.value}:{lens.value}",
                    query_id=lens.value,
                    source_id=source_id,
                    lens=lens,
                    canonical_query=CANONICAL_QUERIES[lens],
                    backend_query=backend_query,
                    request_parameters=parameters,
                    post_fetch_date_filter_required=source_id is SearchSourceId.DBLP,
                )
            )
    return bindings


def _methodological_anchors() -> list[MethodologicalAnchor]:
    return [
        MethodologicalAnchor(
            anchor_id="prisma-2020",
            citation="Page et al. The PRISMA 2020 statement. BMJ, 2021.",
            stable_locator="doi:10.1136/bmj.n71",
            borrowed_rule=(
                "Retain a complete identification, screening, eligibility, and "
                "inclusion flow with explicit exclusion reasons."
            ),
        ),
        MethodologicalAnchor(
            anchor_id="prisma-s",
            citation=(
                "Rethlefsen et al. PRISMA-S: reporting literature searches. "
                "Systematic Reviews, 2021."
            ),
            stable_locator="doi:10.1186/s13643-020-01542-z",
            borrowed_rule=(
                "Record every information source, exact query, date, limit, "
                "deduplication step, and supplementary search route."
            ),
        ),
        MethodologicalAnchor(
            anchor_id="petersen-mapping",
            citation=(
                "Petersen, Vakkalanka, and Kuzniarz. Systematic mapping studies "
                "in software engineering: an update. IST, 2015."
            ),
            stable_locator="doi:10.1016/j.infsof.2015.03.007",
            borrowed_rule=(
                "Use a broad mapping taxonomy and descriptive synthesis rather "
                "than forcing heterogeneous releases into one effect estimate."
            ),
        ),
        MethodologicalAnchor(
            anchor_id="benchmark-cards",
            citation=(
                "Sokol et al. BenchmarkCards: standardized documentation for "
                "large language model benchmarks. NeurIPS, 2025."
            ),
            stable_locator="neurips:76175f4355e2f67cf91be468c8860070",
            borrowed_rule=(
                "Represent benchmark purpose, data, evaluation, limitations, and "
                "responsibility in one structured, comparable record."
            ),
        ),
        MethodologicalAnchor(
            anchor_id="asta-bench",
            citation=(
                "Bragg et al. AstaBench: rigorous benchmarking of AI agents with "
                "a scientific research suite. ICLR, 2026."
            ),
            stable_locator="arxiv:2510.21652v2",
            borrowed_rule=(
                "Separate task interfaces, agent harness, evaluator, baseline, "
                "cost, and failure semantics."
            ),
        ),
        MethodologicalAnchor(
            anchor_id="popper",
            citation=(
                "Huang et al. Automated hypothesis validation with agentic "
                "sequential falsifications. ICML, 2025."
            ),
            stable_locator="pmlr:v267/huang25n",
            borrowed_rule=(
                "Predeclare falsifiers, error-control policy, promotion, and "
                "stopping instead of extending a loop until a favorable result."
            ),
        ),
        MethodologicalAnchor(
            anchor_id="fair4rs",
            citation=(
                "Barker et al. Introducing the FAIR Principles for research "
                "software. Scientific Data, 2022."
            ),
            stable_locator="doi:10.1038/s41597-022-01710-x",
            borrowed_rule=(
                "Code findability, accessibility, interoperability, and reuse "
                "separately from content rights and scientific validity."
            ),
        ),
        MethodologicalAnchor(
            anchor_id="prov-o",
            citation="W3C. PROV-O: The PROV Ontology. Recommendation, 2013.",
            stable_locator="w3c:prov-o",
            borrowed_rule=(
                "Bind every coded value to an entity, activity, responsible "
                "agent, derivation, revision, and evidence locator."
            ),
        ),
        MethodologicalAnchor(
            anchor_id="ro-crate",
            citation=(
                "Soiland-Reyes et al. Packaging research artefacts with "
                "RO-Crate. Data Science, 2022."
            ),
            stable_locator="doi:10.3233/DS-210053",
            borrowed_rule=(
                "Package protocol, search log, source artifacts, cards, code, "
                "environment, and analysis as one inspectable research object."
            ),
        ),
        MethodologicalAnchor(
            anchor_id="ai-scientist-v2",
            citation=(
                "Yamada et al. The AI Scientist-v2: workshop-level automated "
                "scientific discovery via agentic tree search. 2025."
            ),
            stable_locator="arxiv:2504.08066",
            borrowed_rule=(
                "Tree search and experiment management belong in development; "
                "they cannot access or adapt to one-use confirmation evidence."
            ),
        ),
        MethodologicalAnchor(
            anchor_id="kosmos",
            citation=(
                "Mitchener et al. Kosmos: an AI scientist for autonomous "
                "discovery. 2025."
            ),
            stable_locator="arxiv:2511.02824",
            borrowed_rule=(
                "Preserve claim-to-code and claim-to-literature traceability, "
                "while treating traceability as distinct from correctness."
            ),
        ),
        MethodologicalAnchor(
            anchor_id="ideation-execution-gap",
            citation=(
                "Si et al. The ideation-execution gap: execution outcomes of "
                "LLM-generated versus human research ideas. ICLR, 2026."
            ),
            stable_locator="arxiv:2506.20803",
            borrowed_rule=(
                "Do not use idea or reviewer scores as substitutes for executable "
                "effects, independent confirmation, or publication validity."
            ),
        ),
    ]


def _known_item_sentinels() -> list[KnownItemSentinel]:
    items = [
        (
            "autosdt",
            "AutoSDT: Scaling Data-Driven Discovery Tasks Toward Open Co-Scientists",
            "arxiv:2506.08140",
            ConstructStratum.SCIENTIFIC_PROGRAMMING,
            "autosdt-5k",
        ),
        (
            "scienceagentbench",
            "ScienceAgentBench: Toward Rigorous Assessment of Language Agents for Data-Driven Scientific Discovery",
            "arxiv:2410.05080",
            ConstructStratum.SCIENTIFIC_PROGRAMMING,
            "scienceagentbench",
        ),
        (
            "core-bench",
            "CORE-Bench: Fostering the Credibility of Published Research Through a Computational Reproducibility Agent Benchmark",
            "arxiv:2409.11363",
            ConstructStratum.COMPUTATIONAL_REPRODUCTION,
            "core-bench",
        ),
        (
            "qrdata",
            "Are LLMs Capable of Data-based Statistical and Causal Reasoning?",
            "arxiv:2402.17644",
            ConstructStratum.DATA_ANALYSIS,
            "qrdata",
        ),
        (
            "paperbench",
            "PaperBench: Evaluating AI's Ability to Replicate AI Research",
            "pmlr:v267/starace25a",
            ConstructStratum.COMPUTATIONAL_REPRODUCTION,
            None,
        ),
        (
            "discoverybench",
            "DiscoveryBench: Towards Data-Driven Discovery with Large Language Models",
            "arxiv:2407.01725",
            ConstructStratum.HYPOTHESIS_VALIDATION,
            None,
        ),
        (
            "blade",
            "BLADE: Benchmarking Language Model Agents for Data-Driven Science",
            "arxiv:2408.09667",
            ConstructStratum.DATA_ANALYSIS,
            None,
        ),
        (
            "mlrc-bench",
            "MLRC-Bench: Can Language Agents Solve Machine Learning Research Challenges?",
            "arxiv:2504.09702",
            ConstructStratum.FULL_RESEARCH_LIFECYCLE,
            None,
        ),
        (
            "mlr-bench",
            "MLR-Bench: Evaluating AI Agents on Open-Ended Machine Learning Research",
            "neurips:ab8dd000d6f87f40061a73f8bca7fae4",
            ConstructStratum.FULL_RESEARCH_LIFECYCLE,
            None,
        ),
        (
            "mle-bench",
            "MLE-bench: Evaluating Machine Learning Agents on Machine Learning Engineering",
            "arxiv:2410.07095",
            ConstructStratum.SCIENTIFIC_PROGRAMMING,
            None,
        ),
        (
            "re-bench",
            "RE-Bench: Evaluating Frontier AI R&D Capabilities of Language Model Agents against Human Experts",
            "arxiv:2411.15114",
            ConstructStratum.FULL_RESEARCH_LIFECYCLE,
            None,
        ),
        (
            "airs-bench",
            "AIRS-Bench: a Suite of Tasks for Frontier AI Research Science Agents",
            "arxiv:2602.06855v3",
            ConstructStratum.FULL_RESEARCH_LIFECYCLE,
            None,
        ),
        (
            "mlagentbench",
            "MLAgentBench: Evaluating Language Agents on Machine Learning Experimentation",
            "pmlr:v235/huang24y",
            ConstructStratum.SCIENTIFIC_PROGRAMMING,
            None,
        ),
        (
            "asta-bench-sentinel",
            "AstaBench: Rigorous Benchmarking of AI Agents with a Scientific Research Suite",
            "arxiv:2510.21652v2",
            ConstructStratum.FULL_RESEARCH_LIFECYCLE,
            None,
        ),
        (
            "autoresearchbench",
            "AutoResearchBench: Benchmarking AI Agents on Complex Scientific Literature Discovery",
            "arxiv:2604.25256",
            ConstructStratum.LITERATURE_DISCOVERY,
            None,
        ),
        (
            "researchbench",
            "ResearchBench: Benchmarking LLMs in Scientific Research Idea Generation",
            "acl:2026.findings-acl.644",
            ConstructStratum.HYPOTHESIS_VALIDATION,
            None,
        ),
    ]
    return [
        KnownItemSentinel(
            sentinel_id=sentinel_id,
            title=title,
            stable_locator=locator,
            expected_stratum=stratum,
            pilot_release_id=pilot,
        )
        for sentinel_id, title, locator, stratum, pilot in items
    ]


def _pilot_boundaries() -> list[PilotReleaseBoundary]:
    report_hash = "292899ec660d38490fd95dd40c832e304f6c816a1dd5f9f401b19f6615eea89a"
    projection_hash = "265d8c1b1195f6ad488a2d2fe12dd5133afaeadfd18d109fff56edefd11c7491"
    return [
        PilotReleaseBoundary(
            release_id=release_id,
            task_263_6_6_report_hash=report_hash,
            task_263_6_6_projection_hash=projection_hash,
        )
        for release_id in sorted(EXPECTED_PILOT_RELEASE_IDS)
    ]


def _eligibility_criteria() -> list[EligibilityCriterion]:
    include = [
        (
            "include-date",
            "The primary paper or first public benchmark specification is dated "
            "2023-01-01 through 2026-07-31 inclusive.",
            "Primary paper version history, DOI metadata, or official proceedings date.",
        ),
        (
            "include-agentic-science",
            "The evaluated system autonomously selects or executes at least one "
            "scientific-research action beyond static knowledge question answering.",
            "Primary task description and evaluator or environment specification.",
        ),
        (
            "include-named-evaluation-release",
            "A named benchmark, suite, environment, or task release with repeatable "
            "instances and an explicit scoring procedure is described.",
            "Primary paper plus official repository, dataset, or evaluator documentation.",
        ),
        (
            "include-fixed-anchor",
            "At least the paper revision is fixed at cutoff; repository and dataset "
            "revisions are fixed when available and missing artifacts remain coded.",
            "Versioned paper locator and exact commit/revision evidence where available.",
        ),
        (
            "include-primary-source",
            "A primary paper, official proceedings page, author repository, or "
            "official dataset page is recoverable.",
            "One or more primary-source evidence locators.",
        ),
    ]
    exclude = [
        (
            "exclude-static-scientific-qa",
            "Exclude static scientific knowledge QA or exam benchmarks with no "
            "agentic research action, tool use, environment interaction, or workflow.",
            "Primary task definition.",
        ),
        (
            "exclude-single-case-demonstration",
            "Exclude one-off case studies, wet-lab demonstrations, or generated "
            "papers that do not define a reusable evaluation release.",
            "Primary method and evaluation sections.",
        ),
        (
            "exclude-system-self-score-only",
            "Exclude system papers evaluated only on ad hoc author-selected examples "
            "without a named, repeatable task suite.",
            "Primary evaluation design.",
        ),
        (
            "exclude-duplicate-family-revision",
            "Exclude earlier revisions from the primary cross-sectional cohort when "
            "a later pre-cutoff revision of the same benchmark family exists.",
            "Release lineage and revision dates.",
        ),
        (
            "exclude-after-cutoff",
            "Exclude first-public versions or benchmark releases after 2026-07-31, "
            "even if later metadata backdates associated artifacts.",
            "Version history and artifact creation time.",
        ),
    ]
    return [
        EligibilityCriterion(
            criterion_id=criterion_id,
            decision="include",
            rule=rule,
            evidence_required=evidence,
        )
        for criterion_id, rule, evidence in include
    ] + [
        EligibilityCriterion(
            criterion_id=criterion_id,
            decision="exclude",
            rule=rule,
            evidence_required=evidence,
        )
        for criterion_id, rule, evidence in exclude
    ]


def _evidence_code_definitions() -> list[EvidenceCodeDefinition]:
    definitions = {
        EvidenceState.VERIFIED_PASS: (
            "One or more exact primary sources directly establish that the frozen "
            "criterion passes for this release."
        ),
        EvidenceState.VERIFIED_FAIL: (
            "One or more exact primary sources directly establish that the frozen "
            "criterion fails for this release."
        ),
        EvidenceState.NOT_REPORTED: (
            "All planned primary sources were inspected, but the required fact was "
            "not stated or bound to the release."
        ),
        EvidenceState.UNREACHABLE: (
            "The planned primary source remained inaccessible after the frozen "
            "retry count and seven-day retry window."
        ),
        EvidenceState.AMBIGUOUS: (
            "Primary evidence supports more than one plausible code and no explicit "
            "source resolves the interpretation."
        ),
        EvidenceState.CONFLICTING: (
            "Two or more primary sources make incompatible claims about the same "
            "release field or revision."
        ),
        EvidenceState.NOT_APPLICABLE: (
            "The field is structurally irrelevant to the release; it is excluded "
            "from coverage denominators and never converted into a pass."
        ),
    }
    return [
        EvidenceCodeDefinition(
            state=state,
            definition=definition,
            counts_as_admission_pass=state is EvidenceState.VERIFIED_PASS,
            counts_as_determinate_coverage=state
            in {EvidenceState.VERIFIED_PASS, EvidenceState.VERIFIED_FAIL},
        )
        for state, definition in definitions.items()
    ]


def _extraction_codebook() -> list[ExtractionFieldSpec]:
    dual_fields = {
        "benchmark-family-id",
        "primary-construct",
        "independence-rule",
        "independent-source-upper-bound",
        "local-execution-rights",
        "software-reuse-rights",
        "derivative-creation-rights",
        "content-redistribution-rights",
        "split-seal",
        "outcome-colocation",
        "contamination-policy",
    }
    critical_fields = dual_fields | {
        "artifact-hashes",
        "compression-ratio",
        "dataset-revision",
        "deterministic-scorer-command",
        "headline-task-count",
        "judge-role",
        "paper-revision",
        "primary-endpoint-kind",
        "primary-metric",
        "privileged-execution",
        "repository-revision",
        "strong-baseline-command",
        "strong-baseline-identity",
        "wall-clock-envelope",
    }
    gate_map = {
        "paper-revision": AdmissionGate.FIXED_REVISION,
        "repository-revision": AdmissionGate.FIXED_REVISION,
        "dataset-revision": AdmissionGate.FIXED_REVISION,
        "independence-rule": AdmissionGate.INDEPENDENT_LINEAGE,
        "independent-source-upper-bound": AdmissionGate.INDEPENDENT_LINEAGE,
        "local-execution-rights": AdmissionGate.LOCAL_EXECUTION_RIGHTS,
        "software-reuse-rights": AdmissionGate.SOFTWARE_REUSE_RIGHTS,
        "derivative-creation-rights": AdmissionGate.DERIVATIVE_CREATION_RIGHTS,
        "content-redistribution-rights": (
            AdmissionGate.CONTENT_REDISTRIBUTION_RIGHTS
        ),
        "primary-endpoint-kind": AdmissionGate.DETERMINISTIC_PRIMARY_ENDPOINT,
        "deterministic-scorer-command": (
            AdmissionGate.DETERMINISTIC_PRIMARY_ENDPOINT
        ),
        "judge-role": AdmissionGate.NON_DECISIVE_MODEL_OR_HUMAN_JUDGE,
        "strong-baseline-command": AdmissionGate.EXACT_STRONG_BASELINE,
        "strong-baseline-identity": AdmissionGate.EXACT_STRONG_BASELINE,
        "dependency-lock": AdmissionGate.BOUNDED_COMPUTE,
        "cpu-envelope": AdmissionGate.BOUNDED_COMPUTE,
        "gpu-envelope": AdmissionGate.BOUNDED_COMPUTE,
        "cloud-dependency": AdmissionGate.BOUNDED_COMPUTE,
        "privileged-execution": AdmissionGate.BOUNDED_COMPUTE,
        "wall-clock-envelope": AdmissionGate.BOUNDED_COMPUTE,
        "split-seal": AdmissionGate.SEALED_RESERVE,
        "outcome-colocation": AdmissionGate.SEALED_RESERVE,
        "contamination-policy": AdmissionGate.CONTAMINATION_CONTROL,
    }
    definitions: dict[str, tuple[str, str]] = {
        "artifact-hashes": ("Exact hashes of every recovered release artifact.", "map"),
        "authorship-decision-owner": (
            "Human role responsible for authorship decisions; automation cannot decide.",
            "text",
        ),
        "benchmark-family-id": (
            "Stable cluster identifier joining papers and revisions of one benchmark.",
            "stable-id",
        ),
        "benchmark-name": ("Official name of the benchmark or suite.", "text"),
        "cloud-dependency": (
            "Whether valid execution requires an external cloud service.",
            "boolean-or-unknown",
        ),
        "compression-ratio": (
            "Headline technical task count divided by independent-source upper bound.",
            "number-or-unknown",
        ),
        "contamination-policy": (
            "Released policy for train/test exposure, benchmark leakage, and updates.",
            "text-and-evidence-state",
        ),
        "content-redistribution-rights": (
            "Source-bound permission to redistribute benchmark content.",
            "evidence-state",
        ),
        "cpu-envelope": ("Reported or reproduced CPU requirement.", "text-or-unknown"),
        "dataset-revision": (
            "Exact dataset revision at or before cutoff.",
            "revision-or-unknown",
        ),
        "dependency-lock": (
            "Exact dependency or environment lock and its locator.",
            "locator-or-unknown",
        ),
        "derivative-creation-rights": (
            "Source-bound permission to create and retain derivatives.",
            "evidence-state",
        ),
        "deterministic-scorer-command": (
            "Executable command that determines the primary score without an LLM "
            "or post-hoc human decision.",
            "argv-or-empty",
        ),
        "evidence-locators": (
            "Exact paper, repository, dataset, artifact, license, and documentation "
            "locators supporting every code.",
            "list",
        ),
        "field-conflicts": (
            "All incompatible primary-source claims retained without silent resolution.",
            "list",
        ),
        "gpu-envelope": ("Reported or reproduced GPU requirement.", "text-or-unknown"),
        "headline-task-count": (
            "Largest task count claimed for the exact audited release.",
            "integer-or-unknown",
        ),
        "human-responsibility-boundary": (
            "Tasks and legal/scientific decisions explicitly retained by humans.",
            "text",
        ),
        "independence-rule": (
            "Scientific lineage rule collapsing technical variants to source units.",
            "text-and-evidence-state",
        ),
        "independent-source-upper-bound": (
            "Conservative maximum number of disjoint scientific source groups.",
            "integer-or-unknown",
        ),
        "judge-role": (
            "Role of any LLM, VLM, or post-hoc human judgment in the primary score.",
            "enum",
        ),
        "local-execution-rights": (
            "Source-bound permission to retrieve and run the release locally.",
            "evidence-state",
        ),
        "outcome-colocation": (
            "Whether answers, tests, or outcome-bearing artifacts are public with inputs.",
            "boolean-or-unknown",
        ),
        "paper-revision": (
            "Exact paper/DOI/arXiv version used as the release anchor.",
            "revision",
        ),
        "primary-construct": (
            "Single MECE stratum assigned by the frozen terminal-scored-activity rule.",
            "enum",
        ),
        "primary-endpoint-kind": (
            "Executable, numeric, rubric, LLM-judged, human-judged, or mixed endpoint.",
            "enum",
        ),
        "primary-locator": ("Stable primary-paper locator.", "locator"),
        "primary-metric": ("Official primary evaluation metric.", "text"),
        "primary-title": ("Exact title of the primary release paper.", "text"),
        "privileged-execution": (
            "Whether execution requires privileged containers or administrator rights.",
            "boolean-or-unknown",
        ),
        "publication-maturity": (
            "Peer-reviewed, preprint, or other status at cutoff.",
            "enum",
        ),
        "publication-year": ("Year of first public benchmark specification.", "integer"),
        "release-decision-owner": (
            "Human role responsible for public-release decisions.",
            "text",
        ),
        "release-id": ("Stable fixed-revision release identifier.", "stable-id"),
        "repository-revision": (
            "Exact official repository commit at or before cutoff.",
            "revision-or-unknown",
        ),
        "secondary-constructs": (
            "Non-primary construct tags preserved without entering the primary stratum.",
            "list",
        ),
        "software-reuse-rights": (
            "Source-bound permission to reuse benchmark and evaluator software.",
            "evidence-state",
        ),
        "split-seal": (
            "Evidence that reserve outcomes were hidden from development and remain "
            "one-use.",
            "evidence-state",
        ),
        "strong-baseline-command": (
            "Exact official or clean-room strongest comparable baseline command.",
            "argv-or-empty",
        ),
        "strong-baseline-identity": (
            "Closest strong baseline bound to paper, code, and release.",
            "text-or-unknown",
        ),
        "unknown-reason": (
            "Explicit not-reported, unreachable, ambiguous, conflicting, or "
            "not-applicable rationale.",
            "evidence-state-and-text",
        ),
        "wall-clock-envelope": (
            "Reported or reproduced bounded wall-clock for one release evaluation.",
            "number-or-unknown",
        ),
    }
    return [
        ExtractionFieldSpec(
            field_id=field_id,
            definition=definitions[field_id][0],
            value_type=definitions[field_id][1],
            critical=field_id in critical_fields,
            dual_human_code_required=field_id in dual_fields,
            admission_gate=gate_map.get(field_id),
        )
        for field_id in sorted(definitions)
    ]


def _primary_endpoints() -> list[PrimaryEndpointSpec]:
    return [
        PrimaryEndpointSpec(
            endpoint_id="per-gate-pass-rates",
            estimand=(
                "For each non-compensating admission gate, the proportion of "
                "primary non-pilot benchmark families coded verified-pass."
            ),
            calculation=(
                "Numerator is verified-pass releases; denominator is every eligible "
                "primary release. Unknown, conflicting, unreachable, ambiguous, and "
                "not-applicable states never enter the numerator. Report raw n/N and "
                "two-sided 95% Wilson score interval."
            ),
            missing_value_rule=(
                "Unknown states count as non-pass for the pass-rate denominator and "
                "are also reported separately in evidence coverage."
            ),
            interval_rule="Two-sided 95% Wilson score interval with z=1.959963984540054.",
        ),
        PrimaryEndpointSpec(
            endpoint_id="complete-conjunction-pass-rate",
            estimand=(
                "Proportion of primary non-pilot benchmark families for which all "
                "twelve admission gates are verified-pass."
            ),
            calculation=(
                "A release passes only when every gate is verified-pass; no weighted "
                "score, majority vote, or compensation is permitted. Report n/N and "
                "two-sided 95% Wilson interval."
            ),
            missing_value_rule="Any non-pass or unknown gate makes the conjunction fail.",
            interval_rule="Two-sided 95% Wilson score interval with z=1.959963984540054.",
        ),
        PrimaryEndpointSpec(
            endpoint_id="task-to-independent-unit-compression",
            estimand=(
                "Distribution of headline technical task count divided by the "
                "conservative independent-source upper bound."
            ),
            calculation=(
                "For releases with both positive counts, calculate tasks/units. "
                "Report n, median, Q1, Q3, minimum, maximum, and a release-cluster "
                f"percentile bootstrap 95% interval for the median using 10000 "
                f"resamples and seed {PROTOCOL_BOOTSTRAP_SEED}."
            ),
            missing_value_rule=(
                "Do not impute either count; exclude that ratio and report the "
                "release in the missing-evidence endpoint."
            ),
            interval_rule=(
                "Percentile bootstrap over release families, 10000 resamples, "
                f"fixed seed {PROTOCOL_BOOTSTRAP_SEED}."
            ),
        ),
        PrimaryEndpointSpec(
            endpoint_id="critical-missing-evidence-rate",
            estimand=(
                "Fraction of applicable critical release fields without a supported "
                "verified-pass or verified-fail code."
            ),
            calculation=(
                "Compute one missing fraction per release; report its distribution "
                "and a release-cluster percentile bootstrap 95% interval for the "
                "mean. Not-applicable fields leave the denominator; all other "
                "non-determinate states count missing."
            ),
            missing_value_rule=(
                "Never convert absence, ambiguity, conflict, or source outage into a "
                "negative fact or an admission pass."
            ),
            interval_rule=(
                "Percentile bootstrap over release families, 10000 resamples, "
                f"fixed seed {PROTOCOL_BOOTSTRAP_SEED}."
            ),
        ),
    ]


def _sensitivity_analyses() -> list[SensitivityAnalysisSpec]:
    return [
        SensitivityAnalysisSpec(
            sensitivity_id="by-primary-construct",
            grouping_or_exclusion="Repeat descriptive endpoints by the seven frozen strata.",
            minimum_stratum_size_for_rate=5,
        ),
        SensitivityAnalysisSpec(
            sensitivity_id="by-publication-year",
            grouping_or_exclusion="Repeat descriptive endpoints for 2023, 2024, 2025, and 2026.",
            minimum_stratum_size_for_rate=5,
        ),
        SensitivityAnalysisSpec(
            sensitivity_id="by-publication-maturity",
            grouping_or_exclusion="Compare peer-reviewed and preprint/other releases.",
            minimum_stratum_size_for_rate=5,
        ),
        SensitivityAnalysisSpec(
            sensitivity_id="exclude-all-pre-protocol-known-items",
            grouping_or_exclusion=(
                "Repeat all endpoints after excluding every known-item sentinel, "
                "not only the four protocol pilots."
            ),
            minimum_stratum_size_for_rate=5,
        ),
        SensitivityAnalysisSpec(
            sensitivity_id="conservative-versus-reported-unit-count",
            grouping_or_exclusion=(
                "Compare conservative source-lineaged compression with the authors' "
                "reported unit interpretation; never use reported technical tasks as "
                "the primary independent count."
            ),
            minimum_stratum_size_for_rate=5,
        ),
        SensitivityAnalysisSpec(
            sensitivity_id="complete-case-only",
            grouping_or_exclusion=(
                "Repeat gate rates among releases with determinate evidence for every "
                "critical field and label this selection-sensitive secondary analysis."
            ),
            minimum_stratum_size_for_rate=5,
        ),
    ]


def _stop_rules() -> list[StopRuleSpec]:
    rules = {
        "agreement-failure": (
            "Before adjudication, any critical field has exact agreement below 0.90 "
            "or estimable Cohen kappa below 0.80; if kappa is not estimable because "
            "both coders use one category, exact agreement must be 1.00."
        ),
        "candidate-model-or-outcome-use": (
            "A candidate research model is run, benchmark outcomes are used to alter "
            "eligibility/codebook/endpoints, or a favorable panel is selected."
        ),
        "coverage-failure": (
            "Overall determinate coverage of applicable critical fields is below "
            "0.90 or any critical field is below 0.85."
        ),
        "human-responsibility-missing": (
            "Two independent human reviewers and a distinct human adjudicator are "
            "not assigned before screening or critical-field extraction."
        ),
        "insufficient-release-census": (
            "After every frozen database query and one backward/one forward citation "
            "round, fewer than 20 non-pilot unique benchmark families have a fixed "
            "pre-cutoff paper revision."
        ),
        "pilot-leakage": (
            "Any Task 263.6.6 pilot enters the primary prospective cohort or is "
            "reported as independent confirmation."
        ),
        "post-extraction-protocol-change": (
            "Any query, date, eligibility rule, unit, codebook field, endpoint, "
            "agreement threshold, analysis, or stop rule changes after the first "
            "non-pilot record is opened for extraction."
        ),
        "search-recall-failure": (
            "Fewer than 90% of the frozen known-item sentinels are recovered by at "
            "least one database query or the fixed citation-chaining route."
        ),
        "source-availability-failure": (
            "Two or more bibliographic indexes remain unavailable after three "
            "attempts distributed across the seven-day retry window."
        ),
        "unit-pseudoreplication": (
            "Technical tasks, seeds, attempts, difficulty variants, agent votes, or "
            "multiple revisions of one family are counted as independent releases."
        ),
    }
    return [
        StopRuleSpec(stop_rule_id=rule_id, trigger=trigger)
        for rule_id, trigger in rules.items()
    ]


def build_benchmark_validity_protocol(
    *,
    frozen_at: datetime,
    parent_git_commit: str,
    protocol_source_sha256: str,
    frozen_runner_sha256: str,
) -> BenchmarkValidityProtocol:
    """Build the canonical Task 263.6.7.1 protocol without source extraction."""

    dual_fields = sorted(
        item.field_id
        for item in _extraction_codebook()
        if item.dual_human_code_required
    )
    return BenchmarkValidityProtocol.create(
        protocol_id="task-263.6.7.1-ai-scientist-benchmark-validity-v1",
        title=(
            "AI-scientist benchmark validity: a prospective systematic mapping "
            "of independence, rights, measurement, baselines, compute, and seals"
        ),
        intended_readers=[
            "automated-science researchers",
            "benchmark maintainers",
            "research-software and Open Science reviewers",
        ],
        research_questions=[
            (
                "RQ1: How much do released AI-scientist benchmark task counts "
                "contract when re-counted at independent scientific-source level?"
            ),
            (
                "RQ2: What proportion of fixed-revision releases passes each "
                "rights, endpoint, baseline, compute, seal, and contamination gate "
                "and the complete non-compensating conjunction?"
            ),
            (
                "RQ3: Which construct strata, years, maturity classes, and missing "
                "evidence patterns describe admission failure, and do the frozen "
                "descriptive conclusions survive prospective sensitivities?"
            ),
        ],
        methodological_anchors=_methodological_anchors(),
        freeze_anchor=FreezeAnchor(
            parent_git_commit=parent_git_commit,
            protocol_source_sha256=protocol_source_sha256,
            frozen_runner_sha256=frozen_runner_sha256,
            frozen_at=frozen_at,
            search_start_date=SEARCH_START_DATE,
            search_cutoff_date=SEARCH_CUTOFF_DATE,
        ),
        search_sources=_search_sources(),
        query_bindings=_query_bindings(),
        known_item_sentinels=_known_item_sentinels(),
        known_item_recall_threshold=0.9,
        citation_chaining_rule=(
            "After database deduplication and full-text inclusion, perform exactly "
            "one backward-reference round from each included primary paper and one "
            "forward-citation round through OpenAlex. Apply the same cutoff and "
            "eligibility rules; do not iterate a second round or add expert-nominated "
            "records outside the frozen routes."
        ),
        source_verification_hierarchy=[
            "versioned primary paper or official proceedings record",
            "official version-control repository at an exact commit",
            "official dataset release at an exact revision",
            "source-specific license text or rights statement",
            "official evaluator, baseline, environment, and split documentation",
            "archived primary locator only when the live original is unreachable",
        ],
        pilot_boundaries=_pilot_boundaries(),
        release_unit_plan=ReleaseUnitPlan(
            primary_non_pilot_release_target=PRIMARY_NON_PILOT_RELEASE_TARGET,
            primary_construct_assignment_rule=(
                "Assign the activity whose output determines the official primary "
                "score. Preserve all other activities as secondary tags. If several "
                "activities jointly determine the score, assign the latest scored "
                "research-lifecycle activity; use full-research-lifecycle only when "
                "the release independently scores at least four phases including "
                "problem/hypothesis formation and execution/result synthesis."
            ),
            full_lifecycle_definition=(
                "At least four separately specified research phases, including "
                "problem or hypothesis formation plus execution or result synthesis, "
                "are required. Merely writing a report after one coding task is not "
                "full lifecycle."
            ),
        ),
        eligibility_criteria=_eligibility_criteria(),
        deduplication_plan=DeduplicationPlan(
            paper_identity_priority=[
                "doi",
                "arxiv-id-without-version",
                "openalex-work-id",
                "dblp-key",
                "normalized-title-first-author-year",
            ],
            benchmark_family_rule=(
                "Cluster releases sharing the same named benchmark, underlying task "
                "pool, generator, source corpus, or official successor lineage. "
                "Renaming, adding difficulty variants, or adding model results does "
                "not create an independent family."
            ),
            release_selection_rule=(
                "Use the latest public fixed revision at or before 2026-07-31 as the "
                "cross-sectional primary release. Bind the paper version plus exact "
                "repository/dataset commits when recoverable."
            ),
            related_revision_rule=(
                "Retain every earlier revision in a longitudinal relation table, but "
                "do not add it to the primary independent-release denominator."
            ),
            multi_paper_rule=(
                "Merge papers that introduce, extend, or report results for the same "
                "benchmark family; choose the paper that defines the audited release "
                "as primary and retain the others as related evidence."
            ),
        ),
        construct_strata=list(ConstructStratum),
        evidence_code_definitions=_evidence_code_definitions(),
        extraction_codebook=_extraction_codebook(),
        human_coding_plan=HumanCodingPlan(
            reviewer_roles=["reviewer-a", "reviewer-b"],
            adjudicator_role="adjudicator",
            critical_dual_code_field_ids=dual_fields,
            adjudication_rule=(
                "Both reviewers independently lock screening and critical-field "
                "records before seeing the other's codes. A distinct human "
                "adjudicator reviews both evidence packets and records a reasoned "
                "final code. Adjudication does not repair the pre-adjudication "
                "agreement endpoint. Any codebook clarification creates a new "
                "protocol version and cannot alter this primary study."
            ),
        ),
        primary_endpoints=_primary_endpoints(),
        sensitivity_analyses=_sensitivity_analyses(),
        stop_rules=_stop_rules(),
        negative_publication_endpoint=(
            "If any frozen stop rule fires, retain the complete search log, excluded "
            "records, unknown/conflicting evidence, codebook, and cards as an open "
            "resource or diagnostic negative. Do not claim a field-wide prevalence, "
            "a mechanism effect, or that no qualifying benchmark exists."
        ),
        prohibited_claims=[
            "automation or agent count causes scientific validity",
            "complete metadata implies a publishable scientific effect",
            "public repository visibility implies content rights",
            "released task count equals independent scientific sample size",
            "a discovered qualifying panel authorizes immediate model execution",
            "a systematic mapping pass rate estimates a causal critic or loop effect",
        ],
    )


def build_protocol_replay_payload(
    projection: BenchmarkValidityProtocolProjection,
) -> dict[str, Any]:
    """Return the only data accepted by the dependency-free replay probe."""

    runner_projection = projection.runner_projection()
    return {
        "expected_projection_sha256": canonical_sha256(runner_projection),
        "projection": runner_projection,
    }


def run_benchmark_validity_protocol_replay(
    *,
    protocol: BenchmarkValidityProtocol,
    runner_path: Path,
    interpreters: Mapping[str, Path],
    work_dir: Path,
) -> tuple[BenchmarkValidityProtocolProjection, ProtocolReplayCertificate]:
    """Replay the result-free freeze in at least two clean interpreters."""

    protocol.verify_integrity()
    if len(interpreters) < 2:
        raise ValueError("protocol replay requires at least two interpreters")
    runner = runner_path.resolve()
    if _file_sha256(runner) != protocol.freeze_anchor.frozen_runner_sha256:
        raise BenchmarkValidityIntegrityError("frozen runner source hash changed")
    projection = BenchmarkValidityProtocolProjection.create(protocol)
    replay_payload = build_protocol_replay_payload(projection)
    work_dir.mkdir(parents=True, exist_ok=True)
    input_path = work_dir / "protocol-replay-input.json"
    _write_text_atomic(input_path, _canonical_json_text(replay_payload) + "\n")
    observations: list[ProtocolReplayObservation] = []
    for role_id, interpreter in sorted(interpreters.items()):
        runtime = probe_interpreter_runtime(role_id=role_id, executable=interpreter)
        output_path = work_dir / f"protocol-replay-{role_id}.json"
        completed = subprocess.run(
            [
                str(interpreter.resolve()),
                str(runner),
                "--input",
                str(input_path),
                "--output",
                str(output_path),
            ],
            capture_output=True,
            check=False,
            timeout=30,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(f"protocol replay failed for {role_id}: {stderr}")
        output = json.loads(output_path.read_text(encoding="utf-8"))
        expected_output_hash = output.pop("output_sha256", None)
        if expected_output_hash != canonical_sha256(output):
            raise BenchmarkValidityIntegrityError("frozen probe output hash mismatch")
        if output.get("projection_sha256") != projection.projection_sha256:
            raise BenchmarkValidityIntegrityError("frozen probe projection mismatch")
        if output.get("protocol_hash") != protocol.protocol_hash:
            raise BenchmarkValidityIntegrityError("frozen probe protocol mismatch")
        if output.get("extracted_record_count") != 0:
            raise BenchmarkValidityIntegrityError("replay accessed extracted records")
        observations.append(
            ProtocolReplayObservation.create(
                runtime=runtime,
                projection_sha256=projection.projection_sha256,
                output_file_sha256=_file_sha256(output_path),
                output_contract_sha256=canonical_sha256(output),
            )
        )
    certificate = ProtocolReplayCertificate.create(
        protocol_hash=protocol.protocol_hash,
        projection_sha256=projection.projection_sha256,
        replay_input_sha256=_file_sha256(input_path),
        frozen_runner_sha256=_file_sha256(runner),
        observations=observations,
    )
    return projection, certificate


def render_benchmark_validity_protocol_markdown(
    report: BenchmarkValidityProtocolFreezeReport,
) -> str:
    """Render the full prospective protocol without inventing study results."""

    report.verify_integrity()
    protocol = report.protocol
    rows = [
        "# AI-scientist benchmark-validity systematic mapping protocol",
        "",
        "> This is a pre-extraction protocol, not a benchmark census result.",
        "",
        f"- Status: `{protocol.status.value}`",
        f"- Frozen at: `{protocol.freeze_anchor.frozen_at.isoformat()}`",
        f"- Protocol hash: `{protocol.protocol_hash}`",
        f"- Projection hash: `{report.projection.projection_sha256}`",
        f"- Replay certificate: `{report.replay_certificate.certificate_hash}`",
        f"- Extracted non-pilot records: `{protocol.extracted_record_count}`",
        "- Search execution started: `false`",
        "- Benchmark outcomes accessed: `false`",
        "- Candidate model calls: `false`",
        "- Public release / external submission: `false / false`",
        "",
        "## Research questions",
        "",
    ]
    rows.extend(f"{index}. {question}" for index, question in enumerate(
        protocol.research_questions, start=1
    ))
    rows.extend(
        [
            "",
            "## Scientific unit and pilot boundary",
            "",
            f"- Primary target: at least "
            f"`{protocol.release_unit_plan.primary_non_pilot_release_target}` "
            "additional non-pilot benchmark families.",
            f"- Study unit: `{protocol.release_unit_plan.study_unit}`.",
            f"- Independence unit: `{protocol.release_unit_plan.independence_unit}`.",
            f"- Nested only: `{protocol.release_unit_plan.nested_observation}`.",
            "- Current four releases are protocol-development pilots and are excluded "
            "from the primary prospective cohort:",
        ]
    )
    rows.extend(
        f"  - `{pilot.release_id}` — primary eligible: `false`"
        for pilot in protocol.pilot_boundaries
    )
    rows.extend(
        [
            "",
            "## Frozen search",
            "",
            f"- Date window: `{protocol.freeze_anchor.search_start_date}` through "
            f"`{protocol.freeze_anchor.search_cutoff_date}`.",
            f"- Known-item recall gate: `{protocol.known_item_recall_threshold:.2f}`.",
            f"- Citation chaining: {protocol.citation_chaining_rule}",
            "",
            "| Source | Lens | Exact backend query |",
            "|---|---|---|",
        ]
    )
    for binding in protocol.query_bindings:
        escaped = binding.backend_query.replace("|", r"\|")
        rows.append(
            f"| `{binding.source_id.value}` | `{binding.lens.value}` | `{escaped}` |"
        )
    rows.extend(
        [
            "",
            "## Evidence semantics",
            "",
            "| Code | Admission pass | Determinate coverage | Meaning |",
            "|---|---:|---:|---|",
        ]
    )
    for definition in protocol.evidence_code_definitions:
        rows.append(
            f"| `{definition.state.value}` | "
            f"`{str(definition.counts_as_admission_pass).lower()}` | "
            f"`{str(definition.counts_as_determinate_coverage).lower()}` | "
            f"{definition.definition} |"
        )
    rows.extend(
        [
            "",
            "## Human validity boundary",
            "",
            "- Two independent humans screen 100% of titles/abstracts and full texts.",
            "- Ambiguous construct, lineage, rights, and seal fields are independently "
            "coded before a distinct human adjudicator sees them.",
            f"- Exact agreement threshold: "
            f"`{protocol.human_coding_plan.exact_agreement_threshold:.2f}`.",
            f"- Cohen kappa threshold when estimable: "
            f"`{protocol.human_coding_plan.cohen_kappa_threshold_when_estimable:.2f}`.",
            f"- Overall/per-field critical evidence coverage: "
            f"`{protocol.human_coding_plan.overall_critical_coverage_threshold:.2f}` / "
            f"`{protocol.human_coding_plan.per_critical_field_coverage_threshold:.2f}`.",
            "- Human identities are not yet assigned; execution remains blocked until "
            "that responsibility is real.",
            "",
            "## Descriptive primary endpoints",
            "",
        ]
    )
    for endpoint in protocol.primary_endpoints:
        rows.extend(
            [
                f"### `{endpoint.endpoint_id}`",
                "",
                endpoint.estimand,
                "",
                f"Calculation: {endpoint.calculation}",
                "",
            ]
        )
    rows.extend(["## Prospective stop rules", ""])
    rows.extend(
        f"- `{rule.stop_rule_id}`: {rule.trigger}" for rule in protocol.stop_rules
    )
    rows.extend(
        [
            "",
            "## Legal terminal interpretation",
            "",
            protocol.negative_publication_endpoint,
            "",
            "A qualifying release, if one is found, authorizes only a later clean "
            "baseline and Research Question preregistration task. It does not "
            "authorize a candidate-model run, a confirmation panel, publication, "
            "release, or submission.",
            "",
        ]
    )
    return "\n".join(rows)


BENCHMARK_VALIDITY_CONTRACT_MODELS = (
    BenchmarkAdmissionCard,
    BenchmarkValidityArtifactManifest,
    BenchmarkValidityProtocol,
    BenchmarkValidityProtocolFreezeReport,
    BenchmarkValidityProtocolProjection,
    ComputeEnvelope,
    DeduplicationPlan,
    EligibilityCriterion,
    EvidenceCodeDefinition,
    EvidenceLocator,
    ExtractionFieldSpec,
    FreezeAnchor,
    GateAssessment,
    HumanCodingPlan,
    KnownItemSentinel,
    MethodologicalAnchor,
    PilotReleaseBoundary,
    PrimaryEndpointSpec,
    ProtocolReplayCertificate,
    ProtocolReplayObservation,
    ReleaseUnitPlan,
    ScreeningRecord,
    SearchExecutionLogEntry,
    SearchSourceSpec,
    SensitivityAnalysisSpec,
    SourceQueryBinding,
    StopRuleSpec,
)


def benchmark_validity_protocol_json_schemas() -> dict[str, dict[str, Any]]:
    """Export deterministic schemas for protocol and future execution records."""

    return {
        model.__name__: model.model_json_schema()
        for model in BENCHMARK_VALIDITY_CONTRACT_MODELS
    }


def write_benchmark_validity_protocol_freeze(
    output_dir: Path,
    report: BenchmarkValidityProtocolFreezeReport,
) -> BenchmarkValidityArtifactManifest:
    """Persist protocol, replay, reader view, schemas, and tamper-evident manifest."""

    report.verify_integrity()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError("protocol freeze output directory must be empty")
    output_dir.mkdir(parents=True, exist_ok=True)
    protocol_path = output_dir / BENCHMARK_VALIDITY_PROTOCOL_FILENAME
    markdown_path = output_dir / BENCHMARK_VALIDITY_MARKDOWN_FILENAME
    projection_path = output_dir / BENCHMARK_VALIDITY_PROJECTION_FILENAME
    replay_path = output_dir / BENCHMARK_VALIDITY_REPLAY_FILENAME
    schema_path = output_dir / BENCHMARK_VALIDITY_SCHEMA_FILENAME
    _write_text_atomic(
        protocol_path,
        _canonical_json_text(report.model_dump(mode="json")) + "\n",
    )
    _write_text_atomic(
        markdown_path,
        render_benchmark_validity_protocol_markdown(report),
    )
    _write_text_atomic(
        projection_path,
        _canonical_json_text(report.projection.model_dump(mode="json")) + "\n",
    )
    _write_text_atomic(
        replay_path,
        _canonical_json_text(report.replay_certificate.model_dump(mode="json")) + "\n",
    )
    _write_text_atomic(
        schema_path,
        _canonical_json_text(benchmark_validity_protocol_json_schemas()) + "\n",
    )
    manifest = BenchmarkValidityArtifactManifest.create(
        protocol_hash=report.protocol.protocol_hash,
        report_hash=report.report_hash,
        projection_sha256=report.projection.projection_sha256,
        replay_certificate_hash=report.replay_certificate.certificate_hash,
        files={
            path.name: _file_sha256(path)
            for path in (
                markdown_path,
                projection_path,
                protocol_path,
                replay_path,
                schema_path,
            )
        },
    )
    _write_text_atomic(
        output_dir / BENCHMARK_VALIDITY_MANIFEST_FILENAME,
        _canonical_json_text(manifest.model_dump(mode="json")) + "\n",
    )
    return manifest


def load_benchmark_validity_protocol_freeze(
    output_dir: Path,
) -> tuple[
    BenchmarkValidityProtocolFreezeReport,
    BenchmarkValidityArtifactManifest,
]:
    """Load, recursively verify, and rehash every persisted freeze artifact."""

    manifest_path = output_dir / BENCHMARK_VALIDITY_MANIFEST_FILENAME
    manifest = BenchmarkValidityArtifactManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    for filename, expected_hash in manifest.files.items():
        artifact_path = output_dir / filename
        if not artifact_path.is_file():
            raise BenchmarkValidityIntegrityError(f"missing protocol artifact: {filename}")
        if _file_sha256(artifact_path) != expected_hash:
            raise BenchmarkValidityIntegrityError(
                f"protocol artifact hash mismatch: {filename}"
            )
    report = BenchmarkValidityProtocolFreezeReport.model_validate_json(
        (output_dir / BENCHMARK_VALIDITY_PROTOCOL_FILENAME).read_text(
            encoding="utf-8"
        )
    )
    report.verify_integrity()
    if report.report_hash != manifest.report_hash:
        raise BenchmarkValidityIntegrityError("manifest report binding mismatch")
    if report.protocol.protocol_hash != manifest.protocol_hash:
        raise BenchmarkValidityIntegrityError("manifest protocol binding mismatch")
    if report.projection.projection_sha256 != manifest.projection_sha256:
        raise BenchmarkValidityIntegrityError("manifest projection binding mismatch")
    if (
        report.replay_certificate.certificate_hash
        != manifest.replay_certificate_hash
    ):
        raise BenchmarkValidityIntegrityError("manifest replay binding mismatch")
    return report, manifest


__all__ = [
    "BENCHMARK_VALIDITY_MANIFEST_FILENAME",
    "BENCHMARK_VALIDITY_MARKDOWN_FILENAME",
    "BENCHMARK_VALIDITY_PROJECTION_FILENAME",
    "BENCHMARK_VALIDITY_PROTOCOL_FILENAME",
    "BENCHMARK_VALIDITY_REPLAY_FILENAME",
    "BENCHMARK_VALIDITY_SCHEMA_FILENAME",
    "AdmissionGate",
    "BenchmarkAdmissionCard",
    "BenchmarkValidityArtifactManifest",
    "BenchmarkValidityIntegrityError",
    "BenchmarkValidityProtocol",
    "BenchmarkValidityProtocolFreezeReport",
    "BenchmarkValidityProtocolProjection",
    "ComputeEnvelope",
    "ConstructStratum",
    "DeduplicationPlan",
    "EligibilityCriterion",
    "EvidenceCodeDefinition",
    "EvidenceLocator",
    "EvidenceState",
    "ExtractionFieldSpec",
    "FreezeAnchor",
    "GateAssessment",
    "HumanCodingPlan",
    "JudgeRole",
    "KnownItemSentinel",
    "MethodologicalAnchor",
    "PilotReleaseBoundary",
    "PrimaryEndpointSpec",
    "ProtocolReplayCertificate",
    "ProtocolReplayObservation",
    "ProtocolStatus",
    "ReleaseUnitPlan",
    "ScreeningDecision",
    "ScreeningRecord",
    "SearchExecutionLogEntry",
    "SearchLens",
    "SearchSourceId",
    "SearchSourceSpec",
    "SensitivityAnalysisSpec",
    "SourceQueryBinding",
    "StopRuleSpec",
    "benchmark_validity_protocol_json_schemas",
    "build_benchmark_validity_protocol",
    "build_protocol_replay_payload",
    "load_benchmark_validity_protocol_freeze",
    "render_benchmark_validity_protocol_markdown",
    "run_benchmark_validity_protocol_replay",
    "write_benchmark_validity_protocol_freeze",
]
