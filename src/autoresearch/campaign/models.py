"""Typed contracts for persistent autonomous research campaigns.

The campaign layer owns the recursive scientific lifecycle.  It deliberately
keeps current-round unseen references out of proposal-time context, freezes the
evaluation contract before execution, and treats a negative result as evidence
for a new round rather than permission to tune against revealed results.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class StrictCampaignModel(BaseModel):
    """Immutable, extra-forbid base for persisted campaign contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class CampaignPolicy(str, Enum):
    """Supported bounded campaign policies."""

    FAST_CCFB = "fast-ccfb"


class CampaignTrack(str, Enum):
    """Scientific route used by one campaign round."""

    SCIENTIFIC_ML_METHOD = "scientific-ml-method"
    AUTONOMOUS_RESEARCH_SYSTEM = "autonomous-research-system"


class CampaignStage(str, Enum):
    """Persisted state-machine stages for one autonomous research round."""

    OBSERVE = "observe"
    DIAGNOSE = "diagnose"
    PROPOSE = "propose"
    SCREEN = "screen"
    PREREGISTER = "preregister"
    DEVELOP = "develop"
    FREEZE = "freeze"
    UNSEEN_EVALUATE = "unseen_evaluate"
    ADJUDICATE = "adjudicate"
    REPORT = "report"
    NEXT_ROUND = "next_round"
    PAPER_BUILD = "paper_build"
    STOP = "stop"


class CampaignOutcome(str, Enum):
    """Top-level campaign outcome."""

    RUNNING = "running"
    CONTRIBUTION_READY = "contribution_ready"
    STOPPED = "stopped"
    DEADLINE_REACHED = "deadline_reached"
    BLOCKED = "blocked"
    FAILED = "failed"


class RoundOutcome(str, Enum):
    """Scientific outcome of one completed round."""

    RUNNING = "running"
    POSITIVE_RESULT = "positive_result"
    NEGATIVE_RESULT = "negative_result"
    BLOCKED = "blocked"
    FAILED = "failed"


class RoundDecisionKind(str, Enum):
    """Allowed deterministic transitions after adjudication."""

    NEXT_ROUND = "next_round"
    PAPER_BUILD = "paper_build"
    STOP = "stop"


class FailureKind(str, Enum):
    """Coarse, auditable failure categories used to drive repair hypotheses."""

    ROOT_NEGATIVE_RESULT = "root_negative_result"
    DEVELOPMENT_GATE = "development_gate"
    UNSEEN_PERFORMANCE = "unseen_performance"
    REPRODUCIBILITY = "reproducibility"
    EVIDENCE_INCOMPLETE = "evidence_incomplete"
    CONTRIBUTION_INSUFFICIENT = "contribution_insufficient"
    CONFIRMATION_REQUIRED = "confirmation_required"


class CampaignRoundDesign(StrictCampaignModel):
    """Result-blind data and acceptance envelope reserved for one round."""

    round_number: int = Field(ge=1)
    track: CampaignTrack
    development_data_refs: tuple[str, ...] = Field(min_length=1)
    unseen_data_refs: tuple[str, ...] = Field(min_length=1)
    seeds: tuple[int, ...] = Field(min_length=3)
    candidate_mechanism_families: tuple[str, ...] = Field(min_length=1)
    primary_metric: str = Field(min_length=1)
    acceptance_criteria: tuple[str, ...] = Field(min_length=1)
    max_wall_time_seconds: int = Field(default=10_800, ge=1)
    disjoint_unseen_required: bool = True

    @model_validator(mode="after")
    def _require_result_blind_design(self) -> CampaignRoundDesign:
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError("campaign round seeds must be unique")
        if len(set(self.development_data_refs)) != len(self.development_data_refs):
            raise ValueError("development data references must be unique")
        if len(set(self.unseen_data_refs)) != len(self.unseen_data_refs):
            raise ValueError("unseen data references must be unique")
        overlap = set(self.development_data_refs) & set(self.unseen_data_refs)
        if overlap:
            raise ValueError("development and unseen data references must be disjoint")
        return self


class CampaignSpec(StrictCampaignModel):
    """Immutable top-level policy for one autonomous campaign."""

    campaign_id: str = Field(default_factory=lambda: _id("campaign"), min_length=1)
    project_id: str = Field(default="autoresearch-ccfb", min_length=1)
    policy: CampaignPolicy = CampaignPolicy.FAST_CCFB
    adapter_id: str = Field(default="development-fixture-v1", min_length=1)
    adapter_config: dict[str, Any] = Field(default_factory=dict)
    deadline: datetime
    pivot_after_hours: int = Field(default=72, ge=1)
    min_experimental_rounds: int = Field(default=2, ge=1)
    round_designs: tuple[CampaignRoundDesign, ...] = Field(min_length=1)
    root_result_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    root_evidence_refs: tuple[str, ...] = ()
    local_execution_only: bool = True
    external_llm_allowed: bool = False
    allow_external_submission: bool = False
    created_at: datetime = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def _require_bounded_local_campaign(self) -> CampaignSpec:
        if self.deadline.tzinfo is None or self.deadline.utcoffset() is None:
            raise ValueError("campaign deadline must be timezone-aware")
        expected_numbers = tuple(range(1, len(self.round_designs) + 1))
        actual_numbers = tuple(design.round_number for design in self.round_designs)
        if actual_numbers != expected_numbers:
            raise ValueError("round designs must be ordered and numbered from one")
        if len(self.round_designs) < self.min_experimental_rounds:
            raise ValueError(
                "campaign must reserve at least min_experimental_rounds result-blind designs"
            )
        if not self.local_execution_only or self.external_llm_allowed:
            raise ValueError("fast-ccfb campaign must keep execution and language models local")
        if self.allow_external_submission:
            raise ValueError("campaign runtime cannot authorize external submission")
        _reject_embedded_secrets(self.adapter_config)

        previously_reserved: set[str] = set()
        for design in self.round_designs:
            current = set(design.unseen_data_refs)
            if design.disjoint_unseen_required and previously_reserved & current:
                raise ValueError("result-blind unseen references cannot be reused across rounds")
            if design.disjoint_unseen_required:
                previously_reserved.update(current)
        return self


def _reject_embedded_secrets(value: Any, *, path: str = "adapter_config") -> None:
    """Keep persisted campaign specifications free of credentials and bearer tokens."""

    secret_markers = (
        "api_key",
        "apikey",
        "access_token",
        "auth_token",
        "bearer",
        "password",
        "secret",
    )
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(marker in normalized for marker in secret_markers) and not normalized.endswith(
                "_env"
            ):
                raise ValueError(f"{path}.{key} must reference an environment variable, not a secret")
            _reject_embedded_secrets(item, path=f"{path}.{key}")
        return
    if isinstance(value, list | tuple):
        for index, item in enumerate(value):
            _reject_embedded_secrets(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered.startswith(("sk-", "bearer ", "ghp_", "github_pat_")):
            raise ValueError(f"{path} contains a credential-like value")


class RoundDevelopmentContext(StrictCampaignModel):
    """Proposal-time context that intentionally excludes current unseen refs."""

    campaign_id: str
    round_id: str
    round_number: int
    track: CampaignTrack
    parent_result_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    historical_evidence_refs: tuple[str, ...] = ()
    development_data_refs: tuple[str, ...] = Field(min_length=1)
    seeds: tuple[int, ...] = Field(min_length=3)
    candidate_mechanism_families: tuple[str, ...] = Field(min_length=1)
    primary_metric: str
    deadline: datetime


class RoundObservation(StrictCampaignModel):
    """Bounded observation of historical evidence at the start of a round."""

    round_id: str
    parent_result_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    evidence_refs: tuple[str, ...] = ()
    summary: str = Field(min_length=1)
    observed_failures: tuple[str, ...] = ()
    observation_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class FailureDiagnosis(StrictCampaignModel):
    """Causal diagnosis that must lead to a falsifiable mechanism change."""

    round_id: str
    parent_result_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    failure_kind: FailureKind
    observations: tuple[str, ...] = Field(min_length=1)
    causal_hypothesis: str = Field(min_length=1)
    required_mechanism_change: str = Field(min_length=1)
    constraints: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = ()
    diagnosis_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class HypothesisProposal(StrictCampaignModel):
    """A new, parent-bound and explicitly falsifiable research hypothesis."""

    hypothesis_id: str = Field(default_factory=lambda: _id("hypothesis"))
    round_id: str
    parent_result_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    title: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    mechanism_family: str = Field(min_length=1)
    mechanism_change: str = Field(min_length=1)
    repair_rationale: str = Field(min_length=1)
    predicted_effect: str = Field(min_length=1)
    primary_metric: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    falsification_conditions: tuple[str, ...] = Field(min_length=1)
    proposal_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class HypothesisScreening(StrictCampaignModel):
    """Development-only feasibility and novelty screen."""

    round_id: str
    hypothesis_id: str
    passed: bool
    reasons: tuple[str, ...] = ()
    development_score: float | None = Field(default=None, allow_inf_nan=False)
    duplicate_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    estimated_wall_time_seconds: int = Field(default=0, ge=0)
    screening_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class PreregistrationInputs(StrictCampaignModel):
    """Adapter-provided result-blind protocol inputs."""

    parameter_space: dict[str, Any] = Field(min_length=1)
    stop_rules: tuple[str, ...] = Field(min_length=1)
    implementation_family_hashes: dict[str, str] = Field(min_length=1)
    adjudicator_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _require_content_hashes(self) -> PreregistrationInputs:
        for digest in self.implementation_family_hashes.values():
            if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
                raise ValueError("implementation family hashes must be lowercase SHA-256 values")
        return self


class Preregistration(StrictCampaignModel):
    """Result-blind experiment contract frozen before development results."""

    round_id: str
    hypothesis_id: str
    proposal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    track: CampaignTrack
    development_data_refs: tuple[str, ...] = Field(min_length=1)
    unseen_data_refs: tuple[str, ...] = Field(min_length=1)
    seeds: tuple[int, ...] = Field(min_length=3)
    primary_metric: str
    acceptance_criteria: tuple[str, ...] = Field(min_length=1)
    parameter_space: dict[str, Any] = Field(min_length=1)
    parameter_space_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    stop_rules: tuple[str, ...] = Field(min_length=1)
    implementation_family_hashes: dict[str, str] = Field(min_length=1)
    adjudicator_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_blind: bool = True
    frozen_at: datetime = Field(default_factory=_utc_now)
    preregistration_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _require_disjoint_frozen_data(self) -> Preregistration:
        if not self.result_blind:
            raise ValueError("campaign preregistration must be result-blind")
        if set(self.development_data_refs) & set(self.unseen_data_refs):
            raise ValueError("preregistered development and unseen references overlap")
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError("preregistered seeds must be unique")
        return self


class DevelopmentResult(StrictCampaignModel):
    """Development-only execution result used to select or reject a candidate."""

    round_id: str
    hypothesis_id: str
    preregistration_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    passed: bool
    selected_configuration: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, float] = Field(default_factory=dict)
    evidence_paths: tuple[str, ...] = ()
    failure_reasons: tuple[str, ...] = ()
    started_at: datetime
    completed_at: datetime
    result_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _require_development_evidence(self) -> DevelopmentResult:
        if self.completed_at < self.started_at:
            raise ValueError("development completion cannot precede its start")
        if self.passed and (not self.selected_configuration or not self.metrics):
            raise ValueError("passing development requires a selected configuration and metrics")
        if not self.passed and not self.failure_reasons:
            raise ValueError("failed development requires at least one reason")
        return self


class FreezeInputs(StrictCampaignModel):
    """Final code/config identity selected using development evidence only."""

    selected_config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    code_hashes: dict[str, str] = Field(min_length=1)
    adjudicator_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _require_code_hashes(self) -> FreezeInputs:
        for digest in self.code_hashes.values():
            if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
                raise ValueError("code hashes must be lowercase SHA-256 values")
        return self


class FrozenRoundProtocol(StrictCampaignModel):
    """Selected implementation and adjudicator identity sealed before unseen execution."""

    round_id: str
    hypothesis_id: str
    preregistration_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    development_result_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    code_hashes: dict[str, str] = Field(min_length=1)
    adjudicator_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    unseen_data_refs: tuple[str, ...] = Field(min_length=1)
    frozen_at: datetime = Field(default_factory=_utc_now)
    frozen_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class UnseenEvaluation(StrictCampaignModel):
    """Terminal evidence from an unchanged frozen protocol on unseen data."""

    round_id: str
    hypothesis_id: str
    frozen_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome: RoundOutcome
    metrics: dict[str, float] = Field(default_factory=dict)
    evidence_paths: tuple[str, ...] = Field(min_length=1)
    mandatory_evidence_complete: bool
    human_intervention_count: int = Field(default=0, ge=0)
    started_at: datetime
    completed_at: datetime
    result_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _require_terminal_unseen_evidence(self) -> UnseenEvaluation:
        if self.outcome is RoundOutcome.RUNNING:
            raise ValueError("unseen evaluation must have a terminal outcome")
        if self.completed_at < self.started_at:
            raise ValueError("unseen completion cannot precede its start")
        if self.outcome is RoundOutcome.POSITIVE_RESULT and not self.metrics:
            raise ValueError("positive unseen evaluation requires metrics")
        return self


class ContributionGateResult(StrictCampaignModel):
    """Deterministic CCF-B contribution gate, separate from paper prose quality."""

    round_id: str
    track: CampaignTrack
    evaluated_result_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    passed: bool
    checks: dict[str, bool] = Field(min_length=1)
    failures: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    evidence_paths: tuple[str, ...] = ()
    gate_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _require_consistent_gate(self) -> ContributionGateResult:
        if self.passed and (not all(self.checks.values()) or self.failures):
            raise ValueError("passing contribution gate requires every check and no failures")
        if not self.passed and not self.failures:
            raise ValueError("failed contribution gate requires explicit failures")
        return self


class RoundDecision(StrictCampaignModel):
    """Policy decision bound to one terminal scientific result and contribution gate."""

    round_id: str
    decision: RoundDecisionKind
    outcome: RoundOutcome
    result_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    contribution_gate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1)
    next_round_trigger: str | None = None
    decided_at: datetime = Field(default_factory=_utc_now)
    decision_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _require_transition_context(self) -> RoundDecision:
        if self.decision is RoundDecisionKind.NEXT_ROUND and not self.next_round_trigger:
            raise ValueError("next-round decision requires a trigger")
        if self.decision is not RoundDecisionKind.NEXT_ROUND and self.next_round_trigger:
            raise ValueError("only next-round decisions may carry a trigger")
        if (
            self.decision is RoundDecisionKind.PAPER_BUILD
            and self.outcome is not RoundOutcome.POSITIVE_RESULT
        ):
            raise ValueError("paper build requires a positive scientific outcome")
        return self


class StageTransition(StrictCampaignModel):
    """One persisted state transition for audit and resume diagnostics."""

    stage: CampaignStage
    entered_at: datetime = Field(default_factory=_utc_now)


class RoundManifest(StrictCampaignModel):
    """Mutable-through-replacement manifest for one recursively linked round."""

    round_id: str
    campaign_id: str
    round_number: int = Field(ge=1)
    track: CampaignTrack
    parent_round_id: str | None = None
    parent_round_manifest_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    parent_result_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    design_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    stage: CampaignStage = CampaignStage.OBSERVE
    outcome: RoundOutcome = RoundOutcome.RUNNING
    stage_history: tuple[StageTransition, ...] = ()
    artifact_paths: dict[str, str] = Field(default_factory=dict)
    artifact_hashes: dict[str, str] = Field(default_factory=dict)
    vault_note_path: str | None = None
    human_intervention_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=_utc_now)
    completed_at: datetime | None = None
    manifest_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class CampaignManifest(StrictCampaignModel):
    """Top-level resumable manifest and immutable round lineage."""

    campaign_id: str
    project_id: str
    spec_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    stage: CampaignStage = CampaignStage.OBSERVE
    outcome: CampaignOutcome = CampaignOutcome.RUNNING
    current_round_id: str | None = None
    round_manifest_paths: tuple[str, ...] = ()
    round_manifest_hashes: tuple[str, ...] = ()
    completed_round_count: int = Field(default=0, ge=0)
    experimental_round_count: int = Field(default=0, ge=0)
    human_intervention_count: int = Field(default=0, ge=0)
    lineage_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    artifact_paths: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    manifest_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _require_round_lineage_alignment(self) -> CampaignManifest:
        if len(self.round_manifest_paths) != len(self.round_manifest_hashes):
            raise ValueError("round manifest paths and hashes must align")
        if self.completed_round_count > len(self.round_manifest_paths):
            raise ValueError("completed round count exceeds recorded round manifests")
        if self.experimental_round_count > self.completed_round_count:
            raise ValueError("experimental round count exceeds completed rounds")
        return self


class CampaignResult(StrictCampaignModel):
    """Small return contract for automation and CLI callers."""

    campaign_dir: str
    manifest_path: str
    outcome: CampaignOutcome
    stage: CampaignStage
    completed_round_count: int
    experimental_round_count: int
    human_intervention_count: int
    current_round_id: str | None = None
