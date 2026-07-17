"""Typed contracts for unattended competition research cycles.

The competition layer deliberately keeps scientific decisions separate from
capability grants.  A cycle may finish with a negative result without asking a
human to choose another method; only missing access is represented by an
``AccessRequest``.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class StrictFrozenModel(BaseModel):
    """Immutable, extra-forbid base for persisted competition contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class TopicMode(str, Enum):
    AUTO = "auto"
    SEEDED = "seeded"


class ResearchOperation(str, Enum):
    PROPOSE = "propose"
    IMPLEMENT = "implement"
    DEBUG = "debug"
    ABLATE = "ablate"
    REPLICATE = "replicate"
    STOP = "stop"


class CycleStage(str, Enum):
    INITIALIZED = "initialized"
    TOPIC_SELECTED = "topic_selected"
    HYPOTHESIS_DEFINED = "hypothesis_defined"
    PLAN_COMPILED = "plan_compiled"
    EXPERIMENTS_EXECUTED = "experiments_executed"
    VALIDATED = "validated"
    COMPLETE = "complete"


class CycleOutcome(str, Enum):
    RUNNING = "running"
    DEVELOPMENT_SMOKE_PASSED = "development_smoke_passed"
    NEGATIVE_RESULT = "negative_result"
    ACCESS_REQUIRED = "access_required"
    FAILED = "failed"


class AttemptStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AccessKind(str, Enum):
    CAPABILITY_GRANT = "capability_grant"
    API_KEY = "api_key"
    CONTAINER_RUNTIME = "container_runtime"
    NETWORK = "network"
    DATA_LICENSE = "data_license"
    GPU = "gpu"
    STORAGE = "storage"
    COST = "cost"
    EXTERNAL_SUBMISSION = "external_submission"


class CompetitionScorecard(StrictFrozenModel):
    """Competition rubric scores using the required 40/30/30 split."""

    scientific_value: float = Field(ge=0.0, le=40.0)
    technical_depth: float = Field(ge=0.0, le=30.0)
    application_potential: float = Field(ge=0.0, le=30.0)

    @property
    def total(self) -> float:
        return self.scientific_value + self.technical_depth + self.application_potential


class CompetitionRunSpec(StrictFrozenModel):
    """Top-level input for one resumable competition research run."""

    run_id: str = Field(default_factory=lambda: _id("competition"), min_length=1)
    project_id: str = Field(default="competition-gate-a", min_length=1)
    topic_mode: TopicMode = TopicMode.AUTO
    domain: str = "scientific-ml-dynamical-system-discovery"
    deadline: date = date(2026, 9, 5)
    score_target: CompetitionScorecard = Field(
        default_factory=lambda: CompetitionScorecard(
            scientific_value=36.0,
            technical_depth=27.0,
            application_potential=27.0,
        )
    )
    capability_grant_id: str | None = None
    topic: str | None = None
    reference_uris: tuple[str, ...] = ()
    guidance: tuple[str, ...] = ()
    max_feasibility_candidates: int = Field(default=3, ge=1, le=3)
    timeout_seconds: int = Field(default=30, ge=1)
    development_smoke: bool = True

    @model_validator(mode="after")
    def _seeded_mode_requires_a_seed(self) -> CompetitionRunSpec:
        if self.topic_mode is TopicMode.SEEDED and not (
            self.topic or self.reference_uris or self.guidance
        ):
            raise ValueError(
                "seeded topic mode requires --topic, --reference-uri, or --guidance"
            )
        return self


class TopicCandidate(StrictFrozenModel):
    """Evidence-bound, hard-filterable research topic candidate."""

    topic_id: str = Field(default_factory=lambda: _id("topic"), min_length=1)
    title: str = Field(min_length=1)
    problem_statement: str = Field(min_length=1)
    innovation_claim: str = Field(min_length=1)
    literature_evidence: tuple[str, ...] = Field(min_length=1)
    dataset_refs: tuple[str, ...] = Field(min_length=1)
    baseline_methods: tuple[str, ...] = Field(min_length=1)
    metrics: tuple[str, ...] = Field(min_length=1)
    falsification_conditions: tuple[str, ...] = Field(min_length=1)
    scorecard: CompetitionScorecard
    estimated_cost_usd: float = Field(ge=0.0)
    reproducibility_score: float = Field(ge=0.0, le=1.0)
    duplicate_risk: float = Field(ge=0.0, le=1.0)
    data_available: bool
    license_clear: bool
    compute_feasible: bool
    falsifiable: bool
    reproducible: bool
    adapter_ready: bool
    method_parameters: dict[str, Any] = Field(default_factory=dict)

    def hard_filter_failures(self) -> tuple[str, ...]:
        checks = {
            "data_unavailable": self.data_available,
            "license_unresolved": self.license_clear,
            "compute_infeasible": self.compute_feasible,
            "not_falsifiable": self.falsifiable,
            "not_reproducible": self.reproducible,
            "adapter_not_ready": self.adapter_ready,
            "direct_duplicate_risk": self.duplicate_risk < 0.8,
        }
        return tuple(name for name, passed in checks.items() if not passed)


class TopicFeasibility(StrictFrozenModel):
    """Result of a real, bounded feasibility smoke for one topic."""

    topic_id: str
    passed: bool
    metric_name: str
    metric_value: float | None = None
    evidence_path: str | None = None
    failure_reason: str | None = None
    code_hash: str | None = None
    data_hash: str | None = None


class TopicSelectionReport(StrictFrozenModel):
    """Ranking, hard filters, and top-k feasibility evidence."""

    selected_topic_id: str | None
    ranked_topic_ids: tuple[str, ...]
    hard_filter_failures: dict[str, tuple[str, ...]]
    feasibility: tuple[TopicFeasibility, ...]
    decision_policy: str
    negative_reason: str | None = None


class HypothesisProposal(StrictFrozenModel):
    """Testable hypothesis bound to exactly one selected topic."""

    hypothesis_id: str = Field(default_factory=lambda: _id("hypothesis"))
    topic_id: str
    statement: str = Field(min_length=1)
    prediction: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    baseline: str = Field(min_length=1)
    dataset_ref: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    falsification_conditions: tuple[str, ...] = Field(min_length=1)


class ResearchTaskSpec(StrictFrozenModel):
    """One bounded node in a compiled experiment DAG."""

    task_id: str
    operation: ResearchOperation
    description: str = Field(min_length=1)
    dependency_ids: tuple[str, ...] = ()
    expected_outputs: tuple[str, ...] = ()
    timeout_seconds: int = Field(default=30, ge=1)
    max_attempts: int = Field(default=1, ge=1, le=3)


class ExperimentProtocol(StrictFrozenModel):
    """Executable protocol compiled from a topic-bound hypothesis."""

    protocol_id: str = Field(default_factory=lambda: _id("protocol"))
    topic_id: str
    hypothesis_id: str
    adapter_id: str
    adapter_version: str
    benchmark_source: str
    benchmark_revision: str
    baseline_methods: tuple[str, ...] = Field(min_length=1)
    candidate_method: str = Field(min_length=1)
    metrics: tuple[str, ...] = Field(min_length=1)
    seeds: tuple[int, ...] = Field(min_length=1)
    tasks: tuple[ResearchTaskSpec, ...] = Field(min_length=1)
    acceptance_criteria: tuple[str, ...] = Field(min_length=1)
    development_fixture: bool = True


class ExperimentAttempt(StrictFrozenModel):
    """One real sandbox execution and its immutable causal-chain identifiers."""

    attempt_id: str = Field(default_factory=lambda: _id("attempt"))
    topic_id: str
    hypothesis_id: str
    protocol_id: str
    plan_hash: str
    code_hash: str
    data_hash: str
    config_hash: str
    metrics_hash: str
    run_id: str
    seed: int
    status: AttemptStatus
    validation_status: str
    metrics: dict[str, float] = Field(default_factory=dict)
    metrics_path: str | None = None
    validation_path: str | None = None
    parent_attempt_id: str | None = None
    model_version: str = "local-deterministic-runner"
    cost_usd: float = Field(default=0.0, ge=0.0)
    failure_reason: str | None = None


class ClaimBinding(StrictFrozenModel):
    """A bounded claim tied to metrics from specific attempts."""

    claim_id: str = Field(default_factory=lambda: _id("claim"))
    text: str = Field(min_length=1)
    topic_id: str
    hypothesis_id: str
    metric_name: str
    attempt_ids: tuple[str, ...] = Field(min_length=1)
    scope: str = Field(min_length=1)


class CycleManifest(StrictFrozenModel):
    """Persistent binding across topic, hypothesis, plan, code, data, and claims."""

    manifest_id: str = Field(default_factory=lambda: _id("manifest"))
    run_id: str
    project_id: str
    spec_hash: str
    stage: CycleStage = CycleStage.INITIALIZED
    outcome: CycleOutcome = CycleOutcome.RUNNING
    topic_id: str | None = None
    hypothesis_id: str | None = None
    protocol_id: str | None = None
    plan_hash: str | None = None
    code_hashes: dict[str, str] = Field(default_factory=dict)
    data_hashes: dict[str, str] = Field(default_factory=dict)
    attempts: tuple[ExperimentAttempt, ...] = ()
    claims: tuple[ClaimBinding, ...] = ()
    resolved_models: dict[str, str] = Field(default_factory=dict)
    artifact_paths: dict[str, str] = Field(default_factory=dict)
    human_intervention_count: int = Field(default=0, ge=0)
    access_request_ids: tuple[str, ...] = ()
    release_eligible: bool = False
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    manifest_hash: str | None = None


class CapabilityGrant(StrictFrozenModel):
    """One bounded authorization envelope; it never stores credential values."""

    grant_id: str = Field(default_factory=lambda: _id("grant"))
    api_env_vars: tuple[str, ...] = ()
    network_domains: tuple[str, ...] = ()
    dataset_licenses: tuple[str, ...] = ()
    max_cpu_hours: float = Field(default=1.0, ge=0.0)
    max_gpu_hours: float = Field(default=0.0, ge=0.0)
    max_storage_gb: float = Field(default=1.0, ge=0.0)
    max_cost_usd: float = Field(default=0.0, ge=0.0)
    valid_until: datetime
    allow_external_submission: bool = False
    created_at: datetime = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def _forbid_secret_values(self) -> CapabilityGrant:
        for env_name in self.api_env_vars:
            if not env_name or "=" in env_name or env_name.startswith("sk-"):
                raise ValueError("api_env_vars must contain environment variable names only")
        return self


class AccessRequest(StrictFrozenModel):
    """The only user-waiting output allowed in an unattended research cycle."""

    request_id: str = Field(default_factory=lambda: _id("access"))
    run_id: str
    kind: AccessKind
    reason: str = Field(min_length=1)
    minimum_scope: str = Field(min_length=1)
    environment_variable_names: tuple[str, ...] = ()
    created_at: datetime = Field(default_factory=_utc_now)


class MDBenchDatasetFile(StrictFrozenModel):
    """Immutable metadata for one official MDBench dataset archive."""

    key: str
    size_bytes: int = Field(ge=0)
    checksum: str
    content_url: str


class MDBenchOfficialPreflight(StrictFrozenModel):
    """Live source, license, archive, and container readiness evidence."""

    checked_at: datetime = Field(default_factory=_utc_now)
    repository_url: str
    expected_revision: str
    resolved_revision: str | None = None
    head_revision: str | None = None
    revision_available: bool = False
    head_matches_pin: bool = False
    code_license: str | None = None
    dataset_doi: str
    dataset_record_id: int
    dataset_access_right: str | None = None
    dataset_license: str | None = None
    processed_file: MDBenchDatasetFile | None = None
    processed_metadata_matches: bool = False
    container_runtime: str | None = None
    container_available: bool = False
    ready_to_download: bool = False
    ready_to_execute: bool = False
    blockers: tuple[str, ...] = ()
    access_request_ids: tuple[str, ...] = ()
    output_path: str


class EvidenceGateReport(StrictFrozenModel):
    """Causal-chain validation distinct from scientific release eligibility."""

    passed: bool
    release_allowed: bool
    failures: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    checked_attempt_ids: tuple[str, ...] = ()
    output_path: str | None = None


class CompetitionSubmission(StrictFrozenModel):
    """Competition field contract; development exports may remain blocked."""

    run_id: str
    problem_statement: str
    rationale: str
    technical_details: str
    datasets: tuple[str, ...]
    source: str
    target: str
    paper_title: str
    paper_abstract: str
    methods: tuple[str, ...]
    experiments: tuple[str, ...]
    results: tuple[str, ...]
    references: tuple[str, ...]
    rubric_evidence: CompetitionScorecard
    manifest_path: str
    submission_ready: bool
    blocked_reasons: tuple[str, ...] = ()


class CycleResult(StrictFrozenModel):
    """Small service return object for CLI and automation callers."""

    cycle_dir: str
    manifest_path: str
    evidence_gate_path: str | None
    outcome: CycleOutcome
    release_eligible: bool
    human_intervention_count: int
    access_request_count: int
