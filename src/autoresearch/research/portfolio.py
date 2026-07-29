"""Evidence-first contracts for publication-grade research portfolio search.

This module owns the result-blind front end introduced by task 263.2.  It does
not generate ideas, execute experiments, score scientific outcomes, or authorize
publication.  Instead it makes the minimum preconditions for novelty search
machine-checkable:

* one falsifiable main claim is frozen in a Research Question Certificate;
* an opportunity assessment separates track selection from novelty readiness;
* a strong baseline must be independently reproduced before portfolio search;
* a portfolio must preserve diverse branches, a null/rule arm, bounded
  multi-fidelity survival, and sealed confirmatory evidence; and
* all external release and submission decisions remain human-gated.
"""

from __future__ import annotations

import math
from datetime import date
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    NonEmptyText,
    Sha256,
    StableId,
    canonical_sha256,
)


class PortfolioIntegrityError(ValueError):
    """Raised when a content-addressed research-front-end contract is invalid."""


class PublicationEndpoint(str, Enum):
    """Result-blind publication routes that must be fixed before execution."""

    POSITIVE_METHOD = "positive_method"
    SYSTEM_CONTRIBUTION = "system_contribution"
    DIAGNOSTIC_NEGATIVE = "diagnostic_negative"


class SourceMaturity(str, Enum):
    """Evidence maturity for an adjacent-work source."""

    PEER_REVIEWED = "peer_reviewed"
    OFFICIAL_PRIMARY = "official_primary"
    PREPRINT = "preprint"


class MetricDirection(str, Enum):
    """Direction in which the frozen primary metric improves."""

    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"


class OpportunityStage(str, Enum):
    """Two gates between track triage and execution of novel candidates."""

    TRACK_SELECTION = "track_selection"
    NOVELTY_SEARCH = "novelty_search"


class PortfolioArmKind(str, Enum):
    """Whether a branch proposes a mechanism or acts as a control."""

    MECHANISM = "mechanism"
    NULL_OR_RULE = "null_or_rule"


class FidelityKind(str, Enum):
    """Required ordered stages for multi-fidelity portfolio search."""

    F0_STATIC = "f0_static"
    F1_MINIMAL = "f1_minimal"
    F2_MULTI_TASK = "f2_multi_task"
    F3_FULL_DEVELOPMENT = "f3_full_development"


def _jsonable(value: Any) -> Any:
    """Convert nested contract inputs to the same JSON form used after validation."""

    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


class ResearchSource(KernelContract):
    """One primary or official source verified before question formation."""

    source_id: StableId
    title: NonEmptyText
    year: int = Field(ge=1900, le=2100)
    locator: NonEmptyText
    source_url: NonEmptyText
    maturity: SourceMaturity
    source_fingerprint: Sha256
    verified: Literal[True] = True


class PrimaryMetricSpec(KernelContract):
    """Objective primary metric and smallest effect worth claiming."""

    metric_id: StableId
    name: NonEmptyText
    direction: MetricDirection
    unit: NonEmptyText
    meaningful_effect_threshold: float = Field(gt=0)
    evaluator_description: NonEmptyText
    deterministic_evaluator: Literal[True] = True
    llm_judge_is_gate: Literal[False] = False


class ProspectivePowerPlan(KernelContract):
    """Prospective task-level power or sensitivity assumptions."""

    analysis_unit: NonEmptyText
    confirmatory_independent_unit_count: int = Field(ge=6)
    within_unit_repeat_count: int = Field(ge=1)
    target_power: float = Field(ge=0.8, lt=1)
    alpha: float = Field(gt=0, le=0.05)
    minimum_detectable_effect: float = Field(gt=0)
    uncertainty_method: NonEmptyText
    bootstrap_resamples: int = Field(ge=1_000)
    heterogeneity_plan: NonEmptyText
    analysis_artifact_hash: Sha256
    calculation_verified: Literal[True] = True
    prospective: Literal[True] = True
    seed_repeats_are_independent_units: Literal[False] = False


class ResearchDataSplit(KernelContract):
    """Disjoint development and one-use confirmatory scientific units."""

    development_unit_ids: list[StableId] = Field(min_length=3)
    confirmatory_unit_ids: list[StableId] = Field(min_length=6)
    confirmatory_access_policy: NonEmptyText
    confirmatory_reveal_count: Literal[1] = 1

    @field_validator("development_unit_ids", "confirmatory_unit_ids")
    @classmethod
    def _normalize_unit_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("research data-split unit IDs must be unique")
        return sorted(value)

    @model_validator(mode="after")
    def _validate_disjoint_units(self) -> ResearchDataSplit:
        overlap = set(self.development_unit_ids) & set(self.confirmatory_unit_ids)
        if overlap:
            raise ValueError(
                "development and confirmatory units overlap: "
                + ", ".join(sorted(overlap))
            )
        return self


class ResearchBudget(KernelContract):
    """Hard cost, duration, model-token, and trial bounds."""

    max_cost_usd: float = Field(gt=0)
    max_walltime_minutes: int = Field(ge=1)
    max_model_tokens: int = Field(ge=0)
    max_trials: int = Field(ge=1)


class ResearchQuestionCertificate(KernelContract):
    """One falsifiable, result-blind research question and decisive test."""

    schema_version: Literal["research-question-certificate-v1"] = (
        "research-question-certificate-v1"
    )
    certificate_id: StableId
    literature_cutoff: date
    question: NonEmptyText
    primitives: list[NonEmptyText] = Field(min_length=2)
    assumptions: list[NonEmptyText] = Field(min_length=1)
    mechanism_model: NonEmptyText
    nearest_work_tension: NonEmptyText
    main_claim: NonEmptyText
    falsifier: NonEmptyText
    failure_update: NonEmptyText
    minimal_decisive_test: NonEmptyText
    primary_metric: PrimaryMetricSpec
    strong_baseline_ids: list[StableId] = Field(min_length=1)
    null_or_control_ids: list[StableId] = Field(min_length=1)
    required_ablation_ids: list[StableId] = Field(min_length=1)
    source_ids: list[StableId] = Field(min_length=3)
    power_plan: ProspectivePowerPlan
    data_split: ResearchDataSplit
    budget: ResearchBudget
    publication_endpoint: PublicationEndpoint
    endpoint_rationale: NonEmptyText
    result_observed: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    public_release_authorized: Literal[False] = False
    human_publication_review_required: Literal[True] = True
    certificate_hash: Sha256

    @field_validator(
        "primitives",
        "assumptions",
        "strong_baseline_ids",
        "null_or_control_ids",
        "required_ablation_ids",
        "source_ids",
    )
    @classmethod
    def _normalize_unique_lists(cls, value: list[str]) -> list[str]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("certificate list entries must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_certificate(self) -> ResearchQuestionCertificate:
        if (
            self.power_plan.confirmatory_independent_unit_count
            != len(self.data_split.confirmatory_unit_ids)
        ):
            raise ValueError(
                "power-plan confirmatory independent-unit count must match "
                "the confirmatory data split"
            )
        if self.certificate_hash != self.calculated_hash():
            raise PortfolioIntegrityError("research certificate_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ResearchQuestionCertificate:
        """Normalize a result-blind question and attach its canonical digest."""

        payload = dict(values)
        payload.update(
            {
                "schema_version": "research-question-certificate-v1",
                "result_observed": False,
                "external_submission_authorized": False,
                "public_release_authorized": False,
                "human_publication_review_required": True,
            }
        )
        for field in (
            "primitives",
            "assumptions",
            "strong_baseline_ids",
            "null_or_control_ids",
            "required_ablation_ids",
            "source_ids",
        ):
            payload[field] = sorted(payload[field])
        payload["certificate_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the certificate digest after validation or loading."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"certificate_hash"})
        )

    def verify_integrity(self) -> None:
        """Reject in-memory certificate mutation before downstream use."""

        if self.certificate_hash != self.calculated_hash():
            raise PortfolioIntegrityError("research certificate_hash mismatch")


class NearestWorkDelta(KernelContract):
    """Auditable overlap and claimed delta against one adjacent work."""

    source_id: StableId
    shared_scope: NonEmptyText
    claimed_delta: NonEmptyText
    overlap_risk: NonEmptyText
    decisive_comparison: NonEmptyText


class BaselineReproductionPlan(KernelContract):
    """Clean-room plan that must precede a novelty-search admission."""

    schema_version: Literal["baseline-reproduction-plan-v1"] = (
        "baseline-reproduction-plan-v1"
    )
    baseline_id: StableId
    source_ids: list[StableId] = Field(min_length=1)
    expected_metric_id: StableId
    reproduction_tolerance: float = Field(ge=0)
    clean_environment_required: Literal[True] = True
    independent_runner_required: Literal[True] = True
    exact_command_hash: Sha256
    environment_hash: Sha256
    plan_hash: Sha256

    @field_validator("source_ids")
    @classmethod
    def _normalize_source_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("baseline source IDs must be unique")
        return sorted(value)

    @model_validator(mode="after")
    def _validate_plan(self) -> BaselineReproductionPlan:
        if self.plan_hash != self.calculated_hash():
            raise PortfolioIntegrityError("baseline reproduction plan_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> BaselineReproductionPlan:
        """Attach a digest to a normalized baseline reproduction plan."""

        payload = dict(values)
        payload.update(
            {
                "schema_version": "baseline-reproduction-plan-v1",
                "clean_environment_required": True,
                "independent_runner_required": True,
            }
        )
        payload["source_ids"] = sorted(payload["source_ids"])
        payload["plan_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the baseline-plan digest."""

        return canonical_sha256(self.model_dump(mode="json", exclude={"plan_hash"}))

    def verify_integrity(self) -> None:
        """Reject in-memory baseline-plan mutation before downstream use."""

        if self.plan_hash != self.calculated_hash():
            raise PortfolioIntegrityError("baseline reproduction plan_hash mismatch")


class BaselineReproductionEvidence(KernelContract):
    """Independent executable evidence that a strong baseline was recovered."""

    schema_version: Literal["baseline-reproduction-evidence-v1"] = (
        "baseline-reproduction-evidence-v1"
    )
    plan_hash: Sha256
    baseline_id: StableId
    metric_id: StableId
    observed_value: float
    within_tolerance: bool
    clean_environment: Literal[True] = True
    independent_runner: Literal[True] = True
    artifact_hashes: list[Sha256] = Field(min_length=3)
    reproduction_passed: bool
    evidence_hash: Sha256

    @field_validator("artifact_hashes")
    @classmethod
    def _normalize_artifact_hashes(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("baseline reproduction artifact hashes must be unique")
        return sorted(value)

    @model_validator(mode="after")
    def _validate_evidence(self) -> BaselineReproductionEvidence:
        if self.reproduction_passed != self.within_tolerance:
            raise ValueError(
                "baseline reproduction_passed must equal within_tolerance"
            )
        if self.evidence_hash != self.calculated_hash():
            raise PortfolioIntegrityError(
                "baseline reproduction evidence_hash mismatch"
            )
        return self

    @classmethod
    def create(cls, **values: Any) -> BaselineReproductionEvidence:
        """Attach a digest to normalized clean-room baseline evidence."""

        payload = dict(values)
        payload.update(
            {
                "schema_version": "baseline-reproduction-evidence-v1",
                "clean_environment": True,
                "independent_runner": True,
            }
        )
        payload["artifact_hashes"] = sorted(payload["artifact_hashes"])
        payload["evidence_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the baseline-evidence digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"evidence_hash"})
        )

    def verify_integrity(self) -> None:
        """Reject in-memory baseline-evidence mutation before downstream use."""

        if self.evidence_hash != self.calculated_hash():
            raise PortfolioIntegrityError(
                "baseline reproduction evidence_hash mismatch"
            )


class ResearchOpportunity(KernelContract):
    """All evidence required to judge whether a track merits more budget."""

    schema_version: Literal["research-opportunity-v1"] = "research-opportunity-v1"
    opportunity_id: StableId
    certificate: ResearchQuestionCertificate
    sources: list[ResearchSource] = Field(min_length=3)
    nearest_work: list[NearestWorkDelta] = Field(min_length=3)
    objective_evaluator_hash: Sha256
    baseline_plan: BaselineReproductionPlan
    baseline_smoke_passed: bool
    baseline_reproduction: BaselineReproductionEvidence | None = None
    data_available: bool
    license_clear: bool
    compute_feasible: bool
    source_snapshot_complete: bool
    external_submission_authorized: Literal[False] = False
    public_release_authorized: Literal[False] = False
    opportunity_hash: Sha256

    @model_validator(mode="after")
    def _validate_opportunity(self) -> ResearchOpportunity:
        self.certificate.verify_integrity()
        self.baseline_plan.verify_integrity()
        if self.baseline_reproduction is not None:
            self.baseline_reproduction.verify_integrity()
        source_ids = [source.source_id for source in self.sources]
        if source_ids != sorted(source_ids) or len(source_ids) != len(set(source_ids)):
            raise ValueError("opportunity sources must be unique and source-id sorted")
        if not set(self.certificate.source_ids).issubset(source_ids):
            raise ValueError("certificate source IDs are missing from opportunity sources")

        delta_ids = [delta.source_id for delta in self.nearest_work]
        if delta_ids != sorted(delta_ids) or len(delta_ids) != len(set(delta_ids)):
            raise ValueError(
                "nearest-work rows must be unique and source-id sorted"
            )
        if not set(delta_ids).issubset(source_ids):
            raise ValueError("nearest-work rows reference unknown opportunity sources")
        if not set(self.baseline_plan.source_ids).issubset(source_ids):
            raise ValueError("baseline plan references unknown opportunity sources")
        if (
            self.baseline_plan.expected_metric_id
            != self.certificate.primary_metric.metric_id
        ):
            raise ValueError("baseline plan metric does not match the primary metric")
        if (
            self.baseline_plan.baseline_id
            not in self.certificate.strong_baseline_ids
        ):
            raise ValueError("baseline plan is not listed in the certificate")

        evidence = self.baseline_reproduction
        if evidence is not None:
            if evidence.plan_hash != self.baseline_plan.plan_hash:
                raise ValueError("baseline evidence does not bind the baseline plan")
            if evidence.baseline_id != self.baseline_plan.baseline_id:
                raise ValueError("baseline evidence baseline_id mismatch")
            if evidence.metric_id != self.baseline_plan.expected_metric_id:
                raise ValueError("baseline evidence metric_id mismatch")

        if self.opportunity_hash != self.calculated_hash():
            raise PortfolioIntegrityError("research opportunity_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ResearchOpportunity:
        """Normalize nested opportunity evidence and attach its digest."""

        payload = dict(values)
        payload.update(
            {
                "schema_version": "research-opportunity-v1",
                "external_submission_authorized": False,
                "public_release_authorized": False,
            }
        )
        sources = [
            source
            if isinstance(source, ResearchSource)
            else ResearchSource.model_validate(source)
            for source in payload["sources"]
        ]
        deltas = [
            delta
            if isinstance(delta, NearestWorkDelta)
            else NearestWorkDelta.model_validate(delta)
            for delta in payload["nearest_work"]
        ]
        payload["sources"] = [
            source.model_dump(mode="json")
            for source in sorted(sources, key=lambda item: item.source_id)
        ]
        payload["nearest_work"] = [
            delta.model_dump(mode="json")
            for delta in sorted(deltas, key=lambda item: item.source_id)
        ]
        payload["opportunity_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the opportunity digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"opportunity_hash"})
        )

    def verify_integrity(self) -> None:
        """Reject nested or top-level opportunity mutation before assessment."""

        self.certificate.verify_integrity()
        self.baseline_plan.verify_integrity()
        if self.baseline_reproduction is not None:
            self.baseline_reproduction.verify_integrity()
        if self.opportunity_hash != self.calculated_hash():
            raise PortfolioIntegrityError("research opportunity_hash mismatch")


class OpportunityAssessment(KernelContract):
    """Content-addressed conjunctive gate with no compensating score."""

    schema_version: Literal["opportunity-assessment-v1"] = (
        "opportunity-assessment-v1"
    )
    opportunity_hash: Sha256
    stage: OpportunityStage
    checks: dict[StableId, bool]
    blockers: list[StableId]
    admitted: bool
    weighted_score_used: Literal[False] = False
    llm_review_can_override: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    assessment_hash: Sha256

    @model_validator(mode="after")
    def _validate_assessment(self) -> OpportunityAssessment:
        if list(self.checks) != sorted(self.checks):
            raise ValueError("opportunity assessment checks must be key-sorted")
        expected_blockers = sorted(
            check_id for check_id, passed in self.checks.items() if not passed
        )
        if self.blockers != expected_blockers:
            raise ValueError("opportunity blockers do not match failed checks")
        if self.admitted != all(self.checks.values()):
            raise ValueError("opportunity admitted must be the conjunction of checks")
        if self.assessment_hash != self.calculated_hash():
            raise PortfolioIntegrityError("opportunity assessment_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> OpportunityAssessment:
        """Attach a digest to deterministic hard-gate results."""

        payload = dict(values)
        payload.update(
            {
                "schema_version": "opportunity-assessment-v1",
                "weighted_score_used": False,
                "llm_review_can_override": False,
                "external_submission_authorized": False,
            }
        )
        payload["checks"] = dict(sorted(payload["checks"].items()))
        payload["blockers"] = sorted(
            key for key, passed in payload["checks"].items() if not passed
        )
        payload["admitted"] = all(payload["checks"].values())
        payload["assessment_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the opportunity-assessment digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"assessment_hash"})
        )

    def verify_integrity(self) -> None:
        """Reject in-memory opportunity-assessment mutation."""

        if self.assessment_hash != self.calculated_hash():
            raise PortfolioIntegrityError("opportunity assessment_hash mismatch")


def assess_research_opportunity(
    opportunity: ResearchOpportunity,
    *,
    stage: OpportunityStage,
) -> OpportunityAssessment:
    """Evaluate a research track using non-compensating, result-blind checks."""

    opportunity.verify_integrity()
    certificate = opportunity.certificate
    checks: dict[str, bool] = {
        "baseline_plan_bound": bool(opportunity.baseline_plan.plan_hash),
        "baseline_smoke_passed": opportunity.baseline_smoke_passed,
        "compute_feasible": opportunity.compute_feasible,
        "confirmatory_units_sufficient": (
            len(certificate.data_split.confirmatory_unit_ids)
            == certificate.power_plan.confirmatory_independent_unit_count
            and len(certificate.data_split.confirmatory_unit_ids) >= 6
        ),
        "data_available": opportunity.data_available,
        "development_confirmatory_disjoint": not bool(
            set(certificate.data_split.development_unit_ids)
            & set(certificate.data_split.confirmatory_unit_ids)
        ),
        "external_actions_blocked": (
            not opportunity.external_submission_authorized
            and not opportunity.public_release_authorized
        ),
        "license_clear": opportunity.license_clear,
        "nearest_work_breadth": len(opportunity.nearest_work) >= 3,
        "objective_evaluator_frozen": bool(opportunity.objective_evaluator_hash),
        "power_plan_prospective": certificate.power_plan.prospective,
        "publication_endpoint_result_blind": not certificate.result_observed,
        "source_breadth_verified": (
            len(opportunity.sources) >= 3
            and all(source.verified for source in opportunity.sources)
            and opportunity.source_snapshot_complete
        ),
    }
    if stage is OpportunityStage.NOVELTY_SEARCH:
        evidence = opportunity.baseline_reproduction
        checks.update(
            {
                "baseline_clean_room": bool(
                    evidence is not None
                    and evidence.clean_environment
                    and evidence.independent_runner
                ),
                "baseline_reproduced": bool(
                    evidence is not None and evidence.reproduction_passed
                ),
            }
        )
    return OpportunityAssessment.create(
        opportunity_hash=opportunity.opportunity_hash,
        stage=stage,
        checks=checks,
    )


class BranchBudget(KernelContract):
    """Maximum reservation for one portfolio branch."""

    max_cost_usd: float = Field(gt=0)
    max_walltime_minutes: int = Field(ge=1)
    max_model_tokens: int = Field(ge=0)
    max_trials: int = Field(ge=1)


class PortfolioBranch(KernelContract):
    """One mechanism or null/rule branch retained through the search ledger."""

    branch_id: StableId
    mechanism_family: StableId
    arm_kind: PortfolioArmKind
    hypothesis: NonEmptyText
    exact_delta: NonEmptyText
    source_ids: list[StableId] = Field(min_length=1)
    generation_evidence_hash: Sha256
    budget: BranchBudget
    parent_branch_id: StableId | None = None
    sealed_confirmatory_evidence_visible: Literal[False] = False

    @field_validator("source_ids")
    @classmethod
    def _normalize_source_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("portfolio branch source IDs must be unique")
        return sorted(value)


class FidelityStageSpec(KernelContract):
    """One ordered screen in the frozen multi-fidelity schedule."""

    kind: FidelityKind
    max_survivors: int = Field(ge=1)
    minimum_independent_units: int = Field(ge=0)
    budget_fraction: float = Field(gt=0, le=1)
    promotion_rule: NonEmptyText


class PortfolioSpec(KernelContract):
    """A bounded, diverse, result-blind portfolio ready for development search."""

    schema_version: Literal["research-portfolio-v1"] = "research-portfolio-v1"
    portfolio_id: StableId
    opportunity: ResearchOpportunity
    opportunity_assessment: OpportunityAssessment
    branches: list[PortfolioBranch] = Field(min_length=8, max_length=16)
    fidelity_stages: list[FidelityStageSpec] = Field(min_length=4, max_length=4)
    total_budget: ResearchBudget
    exploration_quota: int = Field(ge=1)
    survival_rule: NonEmptyText
    selection_metric_id: StableId
    retain_all_branch_records: Literal[True] = True
    confirmatory_claim_limit: Literal[1] = 1
    sealed_confirmatory_evidence_visible: Literal[False] = False
    reviewer_score_is_scientific_gate: Literal[False] = False
    result_observed: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    public_release_authorized: Literal[False] = False
    portfolio_hash: Sha256

    @model_validator(mode="after")
    def _validate_portfolio(self) -> PortfolioSpec:
        self.opportunity.verify_integrity()
        self.opportunity_assessment.verify_integrity()
        assessment = self.opportunity_assessment
        if assessment.opportunity_hash != self.opportunity.opportunity_hash:
            raise ValueError("portfolio assessment does not bind the opportunity")
        if assessment.stage is not OpportunityStage.NOVELTY_SEARCH:
            raise ValueError("portfolio requires a novelty-search opportunity assessment")
        if not assessment.admitted:
            raise ValueError("portfolio cannot bind a blocked research opportunity")

        branch_ids = [branch.branch_id for branch in self.branches]
        if len(branch_ids) != len(set(branch_ids)):
            raise ValueError("portfolio branch IDs must be unique")
        generation_hashes = [
            branch.generation_evidence_hash for branch in self.branches
        ]
        if len(generation_hashes) != len(set(generation_hashes)):
            raise ValueError(
                "portfolio branch generation-evidence hashes must be unique"
            )
        branch_signatures = [
            (branch.mechanism_family, branch.exact_delta)
            for branch in self.branches
        ]
        if len(branch_signatures) != len(set(branch_signatures)):
            raise ValueError("portfolio contains duplicate mechanism deltas")
        known_branch_ids = set(branch_ids)
        for branch in self.branches:
            if (
                branch.parent_branch_id is not None
                and branch.parent_branch_id not in known_branch_ids
            ):
                raise ValueError(
                    f"branch {branch.branch_id} references an unknown parent branch"
                )
            if branch.parent_branch_id == branch.branch_id:
                raise ValueError(f"branch {branch.branch_id} cannot parent itself")

        mechanism_families = {
            branch.mechanism_family
            for branch in self.branches
            if branch.arm_kind is PortfolioArmKind.MECHANISM
        }
        if len(mechanism_families) < 3:
            raise ValueError(
                "portfolio requires at least three distinct mechanism families"
            )
        if not any(
            branch.arm_kind is PortfolioArmKind.NULL_OR_RULE
            for branch in self.branches
        ):
            raise ValueError("portfolio requires at least one null/rule branch")

        source_ids = {source.source_id for source in self.opportunity.sources}
        for branch in self.branches:
            if not set(branch.source_ids).issubset(source_ids):
                raise ValueError(
                    f"branch {branch.branch_id} references an unknown source"
                )

        expected_stage_order = list(FidelityKind)
        observed_stage_order = [stage.kind for stage in self.fidelity_stages]
        if observed_stage_order != expected_stage_order:
            raise ValueError("portfolio fidelity stages must be ordered F0 through F3")
        if not math.isclose(
            sum(stage.budget_fraction for stage in self.fidelity_stages),
            1.0,
            rel_tol=0,
            abs_tol=1e-9,
        ):
            raise ValueError("portfolio fidelity budget fractions must sum to one")

        survivor_counts = [
            stage.max_survivors for stage in self.fidelity_stages
        ]
        if survivor_counts[0] > len(self.branches):
            raise ValueError("F0 survivor count exceeds the branch count")
        if any(
            current < following
            for current, following in zip(
                survivor_counts,
                survivor_counts[1:],
                strict=False,
            )
        ):
            raise ValueError("portfolio survivors must not increase across fidelity")
        if survivor_counts[-1] > self.confirmatory_claim_limit:
            raise ValueError("F3 may promote at most one confirmatory claim")
        if self.exploration_quota > survivor_counts[1]:
            raise ValueError("exploration quota exceeds the F1 survivor count")
        if self.fidelity_stages[0].minimum_independent_units != 0:
            raise ValueError("F0 static screening cannot claim scientific units")
        if self.fidelity_stages[1].minimum_independent_units < 1:
            raise ValueError("F1 requires at least one executable unit")
        if self.fidelity_stages[2].minimum_independent_units < 3:
            raise ValueError("F2 requires at least three development units")
        if self.fidelity_stages[3].minimum_independent_units < 3:
            raise ValueError("F3 requires at least three development units")
        available_development_units = len(
            self.opportunity.certificate.data_split.development_unit_ids
        )
        if any(
            stage.minimum_independent_units > available_development_units
            for stage in self.fidelity_stages
        ):
            raise ValueError(
                "fidelity stage requires more development units than are available"
            )

        branch_budgets = [branch.budget for branch in self.branches]
        if sum(item.max_cost_usd for item in branch_budgets) > (
            self.total_budget.max_cost_usd + 1e-9
        ):
            raise ValueError("portfolio branch cost reservations exceed total budget")
        if sum(item.max_walltime_minutes for item in branch_budgets) > (
            self.total_budget.max_walltime_minutes
        ):
            raise ValueError(
                "portfolio branch walltime reservations exceed total budget"
            )
        if sum(item.max_model_tokens for item in branch_budgets) > (
            self.total_budget.max_model_tokens
        ):
            raise ValueError("portfolio branch token reservations exceed total budget")
        if sum(item.max_trials for item in branch_budgets) > (
            self.total_budget.max_trials
        ):
            raise ValueError("portfolio branch trial reservations exceed total budget")

        if (
            self.selection_metric_id
            != self.opportunity.certificate.primary_metric.metric_id
        ):
            raise ValueError("portfolio selection metric differs from the certificate")
        if self.portfolio_hash != self.calculated_hash():
            raise PortfolioIntegrityError("research portfolio_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> PortfolioSpec:
        """Normalize the frozen portfolio and attach its canonical digest."""

        payload = dict(values)
        payload.update(
            {
                "schema_version": "research-portfolio-v1",
                "retain_all_branch_records": True,
                "confirmatory_claim_limit": 1,
                "sealed_confirmatory_evidence_visible": False,
                "reviewer_score_is_scientific_gate": False,
                "result_observed": False,
                "external_submission_authorized": False,
                "public_release_authorized": False,
            }
        )
        payload["portfolio_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the portfolio digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"portfolio_hash"})
        )

    def verify_integrity(self) -> None:
        """Reject nested or top-level portfolio mutation before assessment."""

        self.opportunity.verify_integrity()
        self.opportunity_assessment.verify_integrity()
        if self.portfolio_hash != self.calculated_hash():
            raise PortfolioIntegrityError("research portfolio_hash mismatch")


class PortfolioAssessment(KernelContract):
    """Independent deterministic audit of a validated portfolio."""

    schema_version: Literal["portfolio-assessment-v1"] = "portfolio-assessment-v1"
    portfolio_hash: Sha256
    checks: dict[StableId, bool]
    blockers: list[StableId]
    admitted: bool
    weighted_score_used: Literal[False] = False
    llm_review_can_override: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    assessment_hash: Sha256

    @model_validator(mode="after")
    def _validate_assessment(self) -> PortfolioAssessment:
        if list(self.checks) != sorted(self.checks):
            raise ValueError("portfolio assessment checks must be key-sorted")
        expected_blockers = sorted(
            check_id for check_id, passed in self.checks.items() if not passed
        )
        if self.blockers != expected_blockers:
            raise ValueError("portfolio blockers do not match failed checks")
        if self.admitted != all(self.checks.values()):
            raise ValueError("portfolio admitted must be the conjunction of checks")
        if self.assessment_hash != self.calculated_hash():
            raise PortfolioIntegrityError("portfolio assessment_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> PortfolioAssessment:
        """Attach a digest to a deterministic portfolio audit."""

        payload = dict(values)
        payload.update(
            {
                "schema_version": "portfolio-assessment-v1",
                "weighted_score_used": False,
                "llm_review_can_override": False,
                "external_submission_authorized": False,
            }
        )
        payload["checks"] = dict(sorted(payload["checks"].items()))
        payload["blockers"] = sorted(
            key for key, passed in payload["checks"].items() if not passed
        )
        payload["admitted"] = all(payload["checks"].values())
        payload["assessment_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the portfolio-assessment digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"assessment_hash"})
        )

    def verify_integrity(self) -> None:
        """Reject in-memory portfolio-assessment mutation."""

        if self.assessment_hash != self.calculated_hash():
            raise PortfolioIntegrityError("portfolio assessment_hash mismatch")


def assess_portfolio(portfolio: PortfolioSpec) -> PortfolioAssessment:
    """Recompute the non-compensating gates for a validated portfolio."""

    portfolio.verify_integrity()
    mechanism_families = {
        branch.mechanism_family
        for branch in portfolio.branches
        if branch.arm_kind is PortfolioArmKind.MECHANISM
    }
    checks = {
        "branch_count": 8 <= len(portfolio.branches) <= 16,
        "budget_bounded": all(
            (
                sum(branch.budget.max_cost_usd for branch in portfolio.branches)
                <= portfolio.total_budget.max_cost_usd + 1e-9,
                sum(
                    branch.budget.max_walltime_minutes
                    for branch in portfolio.branches
                )
                <= portfolio.total_budget.max_walltime_minutes,
                sum(
                    branch.budget.max_model_tokens
                    for branch in portfolio.branches
                )
                <= portfolio.total_budget.max_model_tokens,
                sum(branch.budget.max_trials for branch in portfolio.branches)
                <= portfolio.total_budget.max_trials,
            )
        ),
        "external_actions_blocked": (
            not portfolio.external_submission_authorized
            and not portfolio.public_release_authorized
        ),
        "fidelity_schedule_complete": [
            stage.kind for stage in portfolio.fidelity_stages
        ]
        == list(FidelityKind),
        "full_branch_retention": portfolio.retain_all_branch_records,
        "mechanism_family_diversity": len(mechanism_families) >= 3,
        "null_rule_arm": any(
            branch.arm_kind is PortfolioArmKind.NULL_OR_RULE
            for branch in portfolio.branches
        ),
        "opportunity_admitted": portfolio.opportunity_assessment.admitted,
        "result_blind": not portfolio.result_observed,
        "sealed_evidence_hidden": (
            not portfolio.sealed_confirmatory_evidence_visible
            and all(
                not branch.sealed_confirmatory_evidence_visible
                for branch in portfolio.branches
            )
        ),
        "single_confirmatory_claim": portfolio.confirmatory_claim_limit == 1,
    }
    return PortfolioAssessment.create(
        portfolio_hash=portfolio.portfolio_hash,
        checks=checks,
    )


PORTFOLIO_CONTRACT_MODELS = (
    ResearchSource,
    PrimaryMetricSpec,
    ProspectivePowerPlan,
    ResearchDataSplit,
    ResearchBudget,
    ResearchQuestionCertificate,
    NearestWorkDelta,
    BaselineReproductionPlan,
    BaselineReproductionEvidence,
    ResearchOpportunity,
    OpportunityAssessment,
    BranchBudget,
    PortfolioBranch,
    FidelityStageSpec,
    PortfolioSpec,
    PortfolioAssessment,
)


def portfolio_contract_json_schemas() -> dict[str, dict[str, Any]]:
    """Export deterministic JSON Schemas for task 263 front-end contracts."""

    return {
        model.__name__: model.model_json_schema()
        for model in PORTFOLIO_CONTRACT_MODELS
    }
