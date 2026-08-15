"""Shadow-only operator-diversity and memory-review steering candidate.

The candidate implements the generic ``OperatorCatalogProvider`` call shape while
remaining deliberately unwired from production.  It observes only immutable loop
structure: the current zone, branch-local operator-family repetition, and the
number of retained events since the last memory-review operator.  It never reads
research text, scores an answer, chooses an operator, adds a capability, or changes
the mechanical order.

The returned catalog is a non-empty order-preserving subset.  Boundary choices
(promotion, abandonment, and stop) are never suppressed.  A memory-review choice
may become relatively more visible only because saturated short-horizon
introspection choices were removed while enough alternatives remained; the
memory-review choice is never forced.  All artifacts are nonconfirmatory candidate
records and make no claim about task outcome, scientific quality, innovation, or
production adoption.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    Sha256,
    StableId,
    canonical_json,
    canonical_sha256,
)
from autoresearch.research.adaptive_sovereign_loop import (
    AdaptiveResearchBranch,
    AdaptiveResearchLoopSnapshot,
    AdaptiveResearchSeed,
    ResearchLoopZone,
    ResearchOperator,
)

_BOUNDARY_OPERATORS = frozenset(
    {
        ResearchOperator.PROMOTE_BRANCH,
        ResearchOperator.ABANDON_BRANCH,
        ResearchOperator.STOP_EXPLORATION,
    }
)


def _is_continuing_research_operator(operator: ResearchOperator) -> bool:
    """Return whether an operator continues work instead of leaving the branch."""

    return operator not in _BOUNDARY_OPERATORS


class AdaptiveOperatorSteeringError(RuntimeError):
    """Raised when a shadow input is contradictory or mechanically invalid."""


class AdaptiveOperatorFamily(str, Enum):
    """Task-independent operator families used only for mechanical repetition."""

    EVIDENCE_ACQUISITION = "evidence_acquisition"
    HYPOTHESIS_EXPANSION = "hypothesis_expansion"
    SHORT_HORIZON_INTROSPECTION = "short_horizon_introspection"
    TEMPORARY_COLLABORATION = "temporary_collaboration"
    MEMORY_REVIEW = "memory_review"
    BOUNDARY = "boundary"


_OPERATOR_FAMILIES: dict[ResearchOperator, AdaptiveOperatorFamily] = {
    ResearchOperator.RETRIEVE_EVIDENCE: AdaptiveOperatorFamily.EVIDENCE_ACQUISITION,
    ResearchOperator.RUN_SANDBOX_PROBE: AdaptiveOperatorFamily.EVIDENCE_ACQUISITION,
    ResearchOperator.BRANCH_HYPOTHESIS: AdaptiveOperatorFamily.HYPOTHESIS_EXPANSION,
    ResearchOperator.ANALOGICAL_TRANSFER: AdaptiveOperatorFamily.HYPOTHESIS_EXPANSION,
    ResearchOperator.REFRAME_QUESTION: AdaptiveOperatorFamily.SHORT_HORIZON_INTROSPECTION,
    ResearchOperator.DECOMPOSE_UNCERTAINTY: (AdaptiveOperatorFamily.SHORT_HORIZON_INTROSPECTION),
    ResearchOperator.ADVERSARIAL_CRITIQUE: (AdaptiveOperatorFamily.SHORT_HORIZON_INTROSPECTION),
    ResearchOperator.MUTATE_WORKFLOW_PROPOSAL: (AdaptiveOperatorFamily.SHORT_HORIZON_INTROSPECTION),
    ResearchOperator.CONSULT_TEMPORARY_AGENTS: (AdaptiveOperatorFamily.TEMPORARY_COLLABORATION),
    ResearchOperator.CONSOLIDATE_DREAMING: AdaptiveOperatorFamily.MEMORY_REVIEW,
    ResearchOperator.PROMOTE_BRANCH: AdaptiveOperatorFamily.BOUNDARY,
    ResearchOperator.ABANDON_BRANCH: AdaptiveOperatorFamily.BOUNDARY,
    ResearchOperator.STOP_EXPLORATION: AdaptiveOperatorFamily.BOUNDARY,
}


class AdaptiveOperatorSteeringStage(str, Enum):
    """Stage-local shadow decision, never a scientific workflow stage."""

    DISABLED_IDENTITY = "disabled_identity"
    NON_EXPLORATION_IDENTITY = "non_exploration_identity"
    OBSERVE_IDENTITY = "observe_identity"
    DIVERSITY_RELIEF = "diversity_relief"
    MEMORY_REVIEW_DEBT_RELIEF = "memory_review_debt_relief"
    MINIMUM_CHOICE_FALLBACK = "minimum_choice_fallback"


class AdaptiveOperatorSteeringApplicationMode(str, Enum):
    """Whether a catalog is merely observed or applied in a development run."""

    SHADOW_OBSERVATION = "shadow_observation"
    DEVELOPMENT_EVALUATION_ONLY = "development_evaluation_only"


class AdaptiveOperatorSteeringReasonCode(str, Enum):
    POLICY_DISABLED = "policy_disabled"
    NON_EXPLORATION_STAGE = "non_exploration_stage"
    NO_RECENT_REPETITION = "no_recent_repetition"
    NON_INTROSPECTION_REPETITION = "non_introspection_repetition"
    REPEATED_OPERATOR_UNAVAILABLE = "repeated_operator_unavailable"
    DIVERSITY_RELIEF = "diversity_relief"
    MEMORY_REVIEW_DEBT_RELIEF = "memory_review_debt_relief"
    MINIMUM_CHOICE_FALLBACK = "minimum_choice_fallback"
    BOUNDARY_CHOICES_PRESERVED = "boundary_choices_preserved"
    MEMORY_REVIEW_NOT_FORCED = "memory_review_not_forced"


_REASON_TEXT_CN: dict[AdaptiveOperatorSteeringReasonCode, str] = {
    AdaptiveOperatorSteeringReasonCode.POLICY_DISABLED: ("影子策略未启用，机械算子目录保持原样。"),
    AdaptiveOperatorSteeringReasonCode.NON_EXPLORATION_STAGE: (
        "当前区域不执行影子抑制，机械算子目录保持原样。"
    ),
    AdaptiveOperatorSteeringReasonCode.NO_RECENT_REPETITION: (
        "当前分支最近算子家族未达到机械重复阈值，目录保持原样。"
    ),
    AdaptiveOperatorSteeringReasonCode.NON_INTROSPECTION_REPETITION: (
        "重复家族不属于可抑制的短视野内省家族，目录保持原样。"
    ),
    AdaptiveOperatorSteeringReasonCode.REPEATED_OPERATOR_UNAVAILABLE: (
        "达到重复阈值的算子当前并非机械可用项，目录保持原样。"
    ),
    AdaptiveOperatorSteeringReasonCode.DIVERSITY_RELIEF: (
        "当前分支短视野内省家族达到机械重复阈值，影子候选仅移除其中已重复的算子。"
    ),
    AdaptiveOperatorSteeringReasonCode.MEMORY_REVIEW_DEBT_RELIEF: (
        "距离最近一次记忆复核达到机械轮数阈值，影子候选仅在保留足够选择时移除饱和的短视野内省算子。"
    ),
    AdaptiveOperatorSteeringReasonCode.MINIMUM_CHOICE_FALLBACK: (
        "拟议抑制会使非记忆选项、继续科研选项或其家族低于机械下限，影子候选回退为原目录。"
    ),
    AdaptiveOperatorSteeringReasonCode.BOUNDARY_CHOICES_PRESERVED: (
        "晋级、放弃与停止中的机械可用项全部保留。"
    ),
    AdaptiveOperatorSteeringReasonCode.MEMORY_REVIEW_NOT_FORCED: (
        "记忆复核算子仅保留为多个选择之一，未被强制选择。"
    ),
}


class AdaptiveOperatorSteeringReason(KernelContract):
    """One fixed mechanical explanation; arbitrary scientific prose is forbidden."""

    code: AdaptiveOperatorSteeringReasonCode
    operator_ids: list[ResearchOperator] = Field(default_factory=list, max_length=13)
    message_cn: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def _validate_reason(self) -> AdaptiveOperatorSteeringReason:
        if self.message_cn != _REASON_TEXT_CN[self.code]:
            raise ValueError("operator-steering reason text is not the fixed mechanical text")
        if len(self.operator_ids) != len(set(self.operator_ids)):
            raise ValueError("operator-steering reason repeats an operator")
        return self


class AdaptiveOperatorSteeringPolicyContent(KernelContract):
    schema_version: Literal["adaptive-operator-steering-policy-v1"] = (
        "adaptive-operator-steering-policy-v1"
    )
    policy_id: StableId
    enabled: bool = True
    recent_branch_window: int = Field(default=4, ge=2, le=32)
    consecutive_family_repetition_threshold: int = Field(default=3, ge=2, le=16)
    memory_review_debt_horizon: int = Field(default=8, ge=3, le=128)
    minimum_choices_when_mechanically_possible: int = Field(default=4, ge=2, le=13)
    minimum_non_memory_continuing_choices_when_mechanically_possible: int = Field(
        default=4,
        ge=4,
        le=10,
    )
    minimum_non_memory_continuing_families_when_mechanically_possible: int = Field(
        default=3,
        ge=3,
        le=5,
    )
    posterior_development_candidate: Literal[True] = True
    frozen_arm_change_authorized: Literal[False] = False
    nonproduction_candidate_only: Literal[True] = True
    may_add_capabilities: Literal[False] = False
    may_reorder_capabilities: Literal[False] = False
    may_choose_operator: Literal[False] = False
    may_force_memory_review: Literal[False] = False
    reacts_to_research_text: Literal[False] = False
    reacts_to_system_name: Literal[False] = False
    production_adoption_authorized: Literal[False] = False
    formal_evidence_generated: Literal[False] = False
    task_benefit_verified: Literal[False] = False
    scientific_benefit_verified: Literal[False] = False
    innovation_verified: Literal[False] = False

    @model_validator(mode="after")
    def _validate_policy(self) -> AdaptiveOperatorSteeringPolicyContent:
        if self.consecutive_family_repetition_threshold > self.recent_branch_window:
            raise ValueError("operator-family repetition threshold exceeds its recent window")
        return self


class AdaptiveOperatorSteeringPolicy(AdaptiveOperatorSteeringPolicyContent):
    policy_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> AdaptiveOperatorSteeringPolicy:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"policy_hash"}))
        if self.policy_hash != expected:
            raise ValueError("adaptive operator-steering policy hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveOperatorSteeringPolicy:
        content = AdaptiveOperatorSteeringPolicyContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, policy_hash=canonical_sha256(payload))


class AdaptiveOperatorSteeringStructuralObservationContent(KernelContract):
    schema_version: Literal["adaptive-operator-steering-observation-v1"] = (
        "adaptive-operator-steering-observation-v1"
    )
    zone: ResearchLoopZone
    retained_event_count: int = Field(ge=0, le=500)
    branch_operator_ids: list[ResearchOperator] = Field(max_length=500)
    turns_since_memory_review: int = Field(ge=0, le=500)

    @model_validator(mode="after")
    def _validate_observation(
        self,
    ) -> AdaptiveOperatorSteeringStructuralObservationContent:
        if len(self.branch_operator_ids) > self.retained_event_count:
            raise ValueError("branch operator count exceeds retained event count")
        if self.turns_since_memory_review > self.retained_event_count:
            raise ValueError("memory-review distance exceeds retained event count")
        return self


class AdaptiveOperatorSteeringStructuralObservation(
    AdaptiveOperatorSteeringStructuralObservationContent
):
    observation_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> AdaptiveOperatorSteeringStructuralObservation:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"observation_hash"}))
        if self.observation_hash != expected:
            raise ValueError("adaptive operator-steering observation hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveOperatorSteeringStructuralObservation:
        content = AdaptiveOperatorSteeringStructuralObservationContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, observation_hash=canonical_sha256(payload))


class AdaptiveOperatorSteeringShadowInputContent(KernelContract):
    schema_version: Literal["adaptive-operator-steering-shadow-input-v1"] = (
        "adaptive-operator-steering-shadow-input-v1"
    )
    seed_hash: Sha256
    snapshot_hash: Sha256
    branch_id: StableId
    branch_hash: Sha256
    structural_observation: AdaptiveOperatorSteeringStructuralObservation
    structural_observation_hash: Sha256
    mechanically_available_operator_ids: list[ResearchOperator] = Field(
        min_length=1,
        max_length=13,
    )

    @model_validator(mode="after")
    def _validate_input(self) -> AdaptiveOperatorSteeringShadowInputContent:
        if self.structural_observation_hash != self.structural_observation.observation_hash:
            raise ValueError("operator-steering input binds the wrong observation hash")
        if len(self.mechanically_available_operator_ids) != len(
            set(self.mechanically_available_operator_ids)
        ):
            raise ValueError("mechanical operator catalog repeats an operator")
        return self


class AdaptiveOperatorSteeringShadowInput(AdaptiveOperatorSteeringShadowInputContent):
    input_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> AdaptiveOperatorSteeringShadowInput:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"input_hash"}))
        if self.input_hash != expected:
            raise ValueError("adaptive operator-steering shadow-input hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveOperatorSteeringShadowInput:
        content = AdaptiveOperatorSteeringShadowInputContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, input_hash=canonical_sha256(payload))


class AdaptiveOperatorSteeringDecisionContent(KernelContract):
    schema_version: Literal["adaptive-operator-steering-decision-v1"] = (
        "adaptive-operator-steering-decision-v1"
    )
    policy: AdaptiveOperatorSteeringPolicy
    policy_hash: Sha256
    shadow_input: AdaptiveOperatorSteeringShadowInput
    shadow_input_hash: Sha256
    seed_hash: Sha256
    snapshot_hash: Sha256
    branch_id: StableId
    branch_hash: Sha256
    structural_observation_hash: Sha256
    zone: ResearchLoopZone
    application_mode: AdaptiveOperatorSteeringApplicationMode
    mechanical_input_ids: list[ResearchOperator] = Field(min_length=1, max_length=13)
    baseline_catalog_ids: list[ResearchOperator] = Field(min_length=1, max_length=13)
    candidate_catalog_ids: list[ResearchOperator] = Field(min_length=1, max_length=13)
    provider_returned_catalog_ids: list[ResearchOperator] = Field(
        min_length=1,
        max_length=13,
    )
    candidate_applied: bool
    controller_intervened: bool
    proposed_suppressed_ids: list[ResearchOperator] = Field(default_factory=list, max_length=13)
    suppressed_ids: list[ResearchOperator] = Field(default_factory=list, max_length=13)
    preserved_boundary_ids: list[ResearchOperator] = Field(default_factory=list, max_length=3)
    recent_branch_operator_ids: list[ResearchOperator] = Field(default_factory=list, max_length=32)
    recent_branch_operator_families: list[AdaptiveOperatorFamily] = Field(
        default_factory=list,
        max_length=32,
    )
    repeated_family: AdaptiveOperatorFamily | None = None
    turns_since_memory_review: int = Field(ge=0, le=500)
    long_horizon_memory_review_debt: bool
    minimum_catalog_choice_floor_excluding_memory_review: int = Field(ge=0, le=12)
    mechanical_continuing_research_ids: list[ResearchOperator] = Field(max_length=10)
    candidate_continuing_research_ids: list[ResearchOperator] = Field(
        max_length=10,
    )
    mechanical_non_memory_continuing_ids: list[ResearchOperator] = Field(max_length=9)
    candidate_non_memory_continuing_ids: list[ResearchOperator] = Field(max_length=9)
    mechanical_non_memory_continuing_families: list[AdaptiveOperatorFamily] = Field(max_length=5)
    candidate_non_memory_continuing_families: list[AdaptiveOperatorFamily] = Field(max_length=5)
    minimum_non_memory_continuing_choice_floor: int = Field(ge=0, le=9)
    minimum_non_memory_continuing_family_floor: int = Field(ge=0, le=5)
    stage: AdaptiveOperatorSteeringStage
    reasons: list[AdaptiveOperatorSteeringReason] = Field(min_length=1, max_length=4)
    output_is_order_preserving_subset: Literal[True] = True
    boundary_choices_preserved: Literal[True] = True
    unique_operator_created_by_candidate: Literal[False] = False
    memory_review_forced_by_candidate: Literal[False] = False
    minimum_continuing_research_choices_preserved: Literal[True] = True
    candidate_did_not_create_memory_review_as_only_continuing_choice: Literal[True] = True
    nonconfirmatory: Literal[True] = True
    production_adoption_authorized: Literal[False] = False
    formal_evidence_generated: Literal[False] = False
    task_outcome_compared: Literal[False] = False
    task_benefit_verified: Literal[False] = False
    scientific_benefit_verified: Literal[False] = False
    innovation_verified: Literal[False] = False

    @model_validator(mode="after")
    def _validate_decision(self) -> AdaptiveOperatorSteeringDecisionContent:
        if self.policy_hash != self.policy.policy_hash:
            raise ValueError("operator-steering decision binds the wrong policy hash")
        if self.shadow_input_hash != self.shadow_input.input_hash:
            raise ValueError("operator-steering decision binds the wrong shadow input")
        expected = _derive_decision(
            self.policy,
            self.shadow_input,
            application_mode=self.application_mode,
        )
        actual = _decision_projection(self)
        if actual != expected:
            raise ValueError("operator-steering decision differs from deterministic replay")
        candidate_set = set(self.candidate_catalog_ids)
        ordered_subset = [item for item in self.mechanical_input_ids if item in candidate_set]
        if ordered_subset != self.candidate_catalog_ids:
            raise ValueError("candidate catalog is not an order-preserving subset")
        if any(item not in self.candidate_catalog_ids for item in self.preserved_boundary_ids):
            raise ValueError("candidate catalog removed a boundary operator")
        if len(self.mechanical_input_ids) >= 2 and len(self.candidate_catalog_ids) < 2:
            raise ValueError("candidate catalog created a unique choice")
        if (
            len(self.mechanical_continuing_research_ids) >= 4
            and len(self.candidate_continuing_research_ids) < 4
        ):
            raise ValueError("candidate catalog retained fewer than four continuing choices")
        if (
            len(_ordered_operator_families(self.mechanical_continuing_research_ids)) >= 3
            and len(_ordered_operator_families(self.candidate_continuing_research_ids)) < 3
        ):
            raise ValueError("candidate catalog retained fewer than three continuing families")
        if ResearchOperator.CONSOLIDATE_DREAMING in self.mechanical_input_ids:
            if (
                len(self.mechanical_non_memory_continuing_ids) >= 3
                and len(self.candidate_non_memory_continuing_ids) < 3
            ):
                raise ValueError(
                    "memory-review catalog retained fewer than three non-memory choices"
                )
            if (
                len(self.mechanical_non_memory_continuing_families) >= 2
                and len(self.candidate_non_memory_continuing_families) < 2
            ):
                raise ValueError(
                    "memory-review catalog retained fewer than two non-memory families"
                )
        return self


class AdaptiveOperatorSteeringDecision(AdaptiveOperatorSteeringDecisionContent):
    decision_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> AdaptiveOperatorSteeringDecision:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"decision_hash"}))
        if self.decision_hash != expected:
            raise ValueError("adaptive operator-steering decision hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveOperatorSteeringDecision:
        content = AdaptiveOperatorSteeringDecisionContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, decision_hash=canonical_sha256(payload))


class AdaptiveOperatorSteeringShadowAuditContent(KernelContract):
    schema_version: Literal["adaptive-operator-steering-shadow-audit-v1"] = (
        "adaptive-operator-steering-shadow-audit-v1"
    )
    policy: AdaptiveOperatorSteeringPolicy
    policy_hash: Sha256
    retained_inputs: list[AdaptiveOperatorSteeringShadowInput] = Field(
        min_length=1,
        max_length=512,
    )
    decisions: list[AdaptiveOperatorSteeringDecision] = Field(
        min_length=1,
        max_length=512,
    )
    comparison_count: int = Field(ge=1, le=512)
    changed_catalog_count: int = Field(ge=0, le=512)
    identity_catalog_count: int = Field(ge=0, le=512)
    baseline_catalog_remained_authoritative: Literal[True] = True
    candidate_catalog_was_not_executed: Literal[True] = True
    every_candidate_is_nonempty_ordered_subset: Literal[True] = True
    every_boundary_choice_preserved: Literal[True] = True
    no_unique_operator_created: Literal[True] = True
    no_memory_review_forced: Literal[True] = True
    minimum_continuing_research_choices_preserved: Literal[True] = True
    candidate_never_created_memory_review_as_only_continuing_choice: Literal[True] = True
    production_adoption_authorized: Literal[False] = False
    formal_evidence_generated: Literal[False] = False
    task_outcome_compared: Literal[False] = False
    task_benefit_verified: Literal[False] = False
    scientific_benefit_verified: Literal[False] = False
    innovation_verified: Literal[False] = False

    @model_validator(mode="after")
    def _validate_audit(self) -> AdaptiveOperatorSteeringShadowAuditContent:
        if self.policy_hash != self.policy.policy_hash:
            raise ValueError("operator-steering shadow audit binds the wrong policy")
        if self.comparison_count != len(self.retained_inputs) or len(self.decisions) != len(
            self.retained_inputs
        ):
            raise ValueError("operator-steering shadow comparison count mismatch")
        if len({item.input_hash for item in self.retained_inputs}) != len(self.retained_inputs):
            raise ValueError("operator-steering shadow audit repeats a retained input")
        replayed = [
            build_adaptive_operator_steering_decision(
                policy=self.policy,
                shadow_input=shadow_input,
            )
            for shadow_input in self.retained_inputs
        ]
        if replayed != self.decisions:
            raise ValueError("operator-steering shadow decisions fail deterministic replay")
        changed = sum(
            item.candidate_catalog_ids != item.baseline_catalog_ids for item in self.decisions
        )
        if self.changed_catalog_count != changed:
            raise ValueError("operator-steering changed-catalog count mismatch")
        if self.identity_catalog_count != self.comparison_count - changed:
            raise ValueError("operator-steering identity-catalog count mismatch")
        return self


class AdaptiveOperatorSteeringShadowAudit(AdaptiveOperatorSteeringShadowAuditContent):
    audit_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> AdaptiveOperatorSteeringShadowAudit:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"audit_hash"}))
        if self.audit_hash != expected:
            raise ValueError("adaptive operator-steering shadow-audit hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveOperatorSteeringShadowAudit:
        content = AdaptiveOperatorSteeringShadowAuditContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, audit_hash=canonical_sha256(payload))


class ShadowAdaptiveOperatorCatalogProvider:
    """Observe a candidate but return the unchanged baseline catalog."""

    shadow_only: Literal[True] = True
    candidate_applied: Literal[False] = False
    nonconfirmatory: Literal[True] = True
    production_adoption_authorized: Literal[False] = False

    def __init__(self, policy: AdaptiveOperatorSteeringPolicy) -> None:
        self.policy = AdaptiveOperatorSteeringPolicy.model_validate(policy.model_dump(mode="json"))
        self._decisions: list[AdaptiveOperatorSteeringDecision] = []

    @property
    def decisions(self) -> tuple[AdaptiveOperatorSteeringDecision, ...]:
        return tuple(self._decisions)

    @property
    def last_decision(self) -> AdaptiveOperatorSteeringDecision | None:
        return self._decisions[-1] if self._decisions else None

    def __call__(
        self,
        *,
        seed: AdaptiveResearchSeed,
        snapshot: AdaptiveResearchLoopSnapshot,
        branch: AdaptiveResearchBranch,
        mechanically_available_operator_ids: Sequence[str],
    ) -> Sequence[str]:
        shadow_input = build_adaptive_operator_steering_shadow_input(
            seed=seed,
            snapshot=snapshot,
            branch=branch,
            mechanically_available_operator_ids=mechanically_available_operator_ids,
        )
        decision = build_adaptive_operator_steering_decision(
            policy=self.policy,
            shadow_input=shadow_input,
            application_mode=AdaptiveOperatorSteeringApplicationMode.SHADOW_OBSERVATION,
        )
        self._decisions.append(decision)
        return [item.value for item in decision.provider_returned_catalog_ids]


class DevelopmentAdaptiveOperatorCatalogProvider:
    """Apply the candidate catalog only in an explicitly nonconfirmatory run."""

    shadow_only: Literal[False] = False
    candidate_applied: Literal[True] = True
    development_evaluation_only: Literal[True] = True
    nonconfirmatory: Literal[True] = True
    production_adoption_authorized: Literal[False] = False

    def __init__(
        self,
        policy: AdaptiveOperatorSteeringPolicy,
        *,
        decision_receipt_path_provider: Callable[[AdaptiveOperatorSteeringDecision], Path],
    ) -> None:
        self.policy = AdaptiveOperatorSteeringPolicy.model_validate(policy.model_dump(mode="json"))
        self._decision_receipt_path_provider = decision_receipt_path_provider
        self._decisions: list[AdaptiveOperatorSteeringDecision] = []
        self._sealed_receipt_paths: list[Path] = []

    @property
    def decisions(self) -> tuple[AdaptiveOperatorSteeringDecision, ...]:
        return tuple(self._decisions)

    @property
    def last_decision(self) -> AdaptiveOperatorSteeringDecision | None:
        return self._decisions[-1] if self._decisions else None

    @property
    def sealed_receipt_paths(self) -> tuple[Path, ...]:
        return tuple(self._sealed_receipt_paths)

    def __call__(
        self,
        *,
        seed: AdaptiveResearchSeed,
        snapshot: AdaptiveResearchLoopSnapshot,
        branch: AdaptiveResearchBranch,
        mechanically_available_operator_ids: Sequence[str],
    ) -> Sequence[str]:
        shadow_input = build_adaptive_operator_steering_shadow_input(
            seed=seed,
            snapshot=snapshot,
            branch=branch,
            mechanically_available_operator_ids=mechanically_available_operator_ids,
        )
        decision = build_adaptive_operator_steering_decision(
            policy=self.policy,
            shadow_input=shadow_input,
            application_mode=(AdaptiveOperatorSteeringApplicationMode.DEVELOPMENT_EVALUATION_ONLY),
        )
        receipt_path = seal_adaptive_operator_steering_development_decision(
            decision=decision,
            receipt_path=self._decision_receipt_path_provider(decision),
        )
        self._decisions.append(decision)
        self._sealed_receipt_paths.append(receipt_path)
        return [item.value for item in decision.provider_returned_catalog_ids]


def build_adaptive_operator_steering_policy(
    *,
    policy_id: str = "adaptive-operator-steering-shadow-v1",
    enabled: bool = True,
    recent_branch_window: int = 4,
    consecutive_family_repetition_threshold: int = 3,
    memory_review_debt_horizon: int = 8,
    minimum_choices_when_mechanically_possible: int = 4,
    minimum_non_memory_continuing_choices_when_mechanically_possible: int = 4,
    minimum_non_memory_continuing_families_when_mechanically_possible: int = 3,
) -> AdaptiveOperatorSteeringPolicy:
    return AdaptiveOperatorSteeringPolicy.create(
        policy_id=policy_id,
        enabled=enabled,
        recent_branch_window=recent_branch_window,
        consecutive_family_repetition_threshold=(consecutive_family_repetition_threshold),
        memory_review_debt_horizon=memory_review_debt_horizon,
        minimum_choices_when_mechanically_possible=(minimum_choices_when_mechanically_possible),
        minimum_non_memory_continuing_choices_when_mechanically_possible=(
            minimum_non_memory_continuing_choices_when_mechanically_possible
        ),
        minimum_non_memory_continuing_families_when_mechanically_possible=(
            minimum_non_memory_continuing_families_when_mechanically_possible
        ),
    )


def build_adaptive_operator_steering_shadow_input(
    *,
    seed: AdaptiveResearchSeed,
    snapshot: AdaptiveResearchLoopSnapshot,
    branch: AdaptiveResearchBranch,
    mechanically_available_operator_ids: Sequence[str],
) -> AdaptiveOperatorSteeringShadowInput:
    try:
        mechanical = [ResearchOperator(item) for item in mechanically_available_operator_ids]
    except (TypeError, ValueError) as exc:
        raise AdaptiveOperatorSteeringError(
            "mechanical operator catalog contains an unknown operator"
        ) from exc
    if snapshot.seed != seed:
        raise AdaptiveOperatorSteeringError("operator-steering snapshot belongs to another seed")
    matches = [item for item in snapshot.branches if item.branch_id == branch.branch_id]
    if matches != [branch]:
        raise AdaptiveOperatorSteeringError(
            "operator-steering branch is absent or differs from the snapshot"
        )
    observation = build_adaptive_operator_steering_structural_observation(
        snapshot=snapshot,
        branch=branch,
    )
    try:
        return AdaptiveOperatorSteeringShadowInput.create(
            seed_hash=canonical_sha256(seed),
            snapshot_hash=snapshot.snapshot_hash,
            branch_id=branch.branch_id,
            branch_hash=canonical_sha256(branch),
            structural_observation=observation,
            structural_observation_hash=observation.observation_hash,
            mechanically_available_operator_ids=mechanical,
        )
    except ValueError as exc:
        raise AdaptiveOperatorSteeringError(f"invalid operator-steering input: {exc}") from exc


def build_adaptive_operator_steering_structural_observation(
    *,
    snapshot: AdaptiveResearchLoopSnapshot,
    branch: AdaptiveResearchBranch,
) -> AdaptiveOperatorSteeringStructuralObservation:
    matches = [item for item in snapshot.branches if item.branch_id == branch.branch_id]
    if matches != [branch]:
        raise AdaptiveOperatorSteeringError(
            "operator-steering branch is absent or differs from the snapshot"
        )
    branch_operator_ids = [
        event.interaction.proposal.operator
        for event in snapshot.events
        if event.branch_id == branch.branch_id
    ]
    return AdaptiveOperatorSteeringStructuralObservation.create(
        zone=snapshot.zone,
        retained_event_count=len(snapshot.events),
        branch_operator_ids=branch_operator_ids,
        turns_since_memory_review=_turns_since_memory_review(snapshot),
    )


def build_adaptive_operator_steering_decision(
    *,
    policy: AdaptiveOperatorSteeringPolicy,
    shadow_input: AdaptiveOperatorSteeringShadowInput,
    application_mode: AdaptiveOperatorSteeringApplicationMode = (
        AdaptiveOperatorSteeringApplicationMode.SHADOW_OBSERVATION
    ),
) -> AdaptiveOperatorSteeringDecision:
    checked_policy = AdaptiveOperatorSteeringPolicy.model_validate(policy.model_dump(mode="json"))
    checked_input = AdaptiveOperatorSteeringShadowInput.model_validate(
        shadow_input.model_dump(mode="json")
    )
    try:
        checked_mode = AdaptiveOperatorSteeringApplicationMode(application_mode)
    except (TypeError, ValueError) as exc:
        raise AdaptiveOperatorSteeringError("unknown operator-steering application mode") from exc
    derived = _derive_decision(
        checked_policy,
        checked_input,
        application_mode=checked_mode,
    )
    return AdaptiveOperatorSteeringDecision.create(
        policy=checked_policy,
        policy_hash=checked_policy.policy_hash,
        shadow_input=checked_input,
        shadow_input_hash=checked_input.input_hash,
        **derived,
    )


def audit_adaptive_operator_steering_shadow(
    *,
    policy: AdaptiveOperatorSteeringPolicy,
    retained_inputs: Sequence[AdaptiveOperatorSteeringShadowInput],
) -> AdaptiveOperatorSteeringShadowAudit:
    checked_policy = AdaptiveOperatorSteeringPolicy.model_validate(policy.model_dump(mode="json"))
    checked_inputs = [
        AdaptiveOperatorSteeringShadowInput.model_validate(item.model_dump(mode="json"))
        for item in retained_inputs
    ]
    decisions = [
        build_adaptive_operator_steering_decision(
            policy=checked_policy,
            shadow_input=item,
            application_mode=AdaptiveOperatorSteeringApplicationMode.SHADOW_OBSERVATION,
        )
        for item in checked_inputs
    ]
    changed = sum(item.candidate_catalog_ids != item.baseline_catalog_ids for item in decisions)
    return AdaptiveOperatorSteeringShadowAudit.create(
        policy=checked_policy,
        policy_hash=checked_policy.policy_hash,
        retained_inputs=checked_inputs,
        decisions=decisions,
        comparison_count=len(checked_inputs),
        changed_catalog_count=changed,
        identity_catalog_count=len(checked_inputs) - changed,
    )


def adaptive_operator_steering_development_receipt_filename(
    decision: AdaptiveOperatorSteeringDecision,
) -> str:
    """Return the only accepted filename for a pre-application receipt."""

    checked = AdaptiveOperatorSteeringDecision.model_validate(decision.model_dump(mode="json"))
    return f"{checked.decision_hash}.adaptive-operator-steering-development.json"


def seal_adaptive_operator_steering_development_decision(
    *,
    decision: AdaptiveOperatorSteeringDecision,
    receipt_path: Path,
) -> Path:
    """Write one canonical development decision before its catalog is returned."""

    checked = AdaptiveOperatorSteeringDecision.model_validate(decision.model_dump(mode="json"))
    if (
        checked.application_mode
        is not AdaptiveOperatorSteeringApplicationMode.DEVELOPMENT_EVALUATION_ONLY
        or not checked.candidate_applied
    ):
        raise AdaptiveOperatorSteeringError("only an applied development decision can be sealed")
    path = Path(receipt_path)
    expected_name = adaptive_operator_steering_development_receipt_filename(checked)
    if path.name != expected_name:
        raise AdaptiveOperatorSteeringError(
            "development decision receipt path violates the canonical filename contract"
        )
    if not path.parent.is_dir():
        raise AdaptiveOperatorSteeringError(
            "development decision receipt parent must already exist"
        )
    payload = (canonical_json(checked) + "\n").encode("utf-8")
    try:
        with path.open("xb") as handle:
            handle.write(payload)
    except FileExistsError as exc:
        raise AdaptiveOperatorSteeringError(
            "development decision receipt already exists; overwrite is forbidden"
        ) from exc
    return path


def load_adaptive_operator_steering_development_decision(
    receipt_path: Path,
) -> AdaptiveOperatorSteeringDecision:
    """Load an exact canonical receipt and reject stale or modified schemas."""

    path = Path(receipt_path)
    try:
        payload = path.read_bytes()
        parsed = json.loads(payload.decode("utf-8"))
        decision = AdaptiveOperatorSteeringDecision.model_validate(parsed)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise AdaptiveOperatorSteeringError(
            "development decision receipt is unreadable or invalid"
        ) from exc
    if path.name != adaptive_operator_steering_development_receipt_filename(decision):
        raise AdaptiveOperatorSteeringError(
            "development decision receipt filename does not bind its decision hash"
        )
    if payload != (canonical_json(decision) + "\n").encode("utf-8"):
        raise AdaptiveOperatorSteeringError(
            "development decision receipt is not exact canonical JSON"
        )
    if (
        decision.application_mode
        is not AdaptiveOperatorSteeringApplicationMode.DEVELOPMENT_EVALUATION_ONLY
        or not decision.candidate_applied
    ):
        raise AdaptiveOperatorSteeringError(
            "development decision receipt contains a non-applied decision"
        )
    return decision


def _derive_decision(
    policy: AdaptiveOperatorSteeringPolicy,
    shadow_input: AdaptiveOperatorSteeringShadowInput,
    *,
    application_mode: AdaptiveOperatorSteeringApplicationMode,
) -> dict[str, Any]:
    observation = shadow_input.structural_observation
    mechanical = list(shadow_input.mechanically_available_operator_ids)
    recent_ids = observation.branch_operator_ids[-policy.recent_branch_window :]
    recent_families = [_OPERATOR_FAMILIES[item] for item in recent_ids]
    repeated_family = _consecutive_repeated_family(
        recent_families,
        threshold=policy.consecutive_family_repetition_threshold,
    )
    turns_since_memory_review = observation.turns_since_memory_review
    debt = turns_since_memory_review >= policy.memory_review_debt_horizon
    boundary = [item for item in mechanical if item in _BOUNDARY_OPERATORS]
    mechanical_without_memory_review = [
        item for item in mechanical if item is not ResearchOperator.CONSOLIDATE_DREAMING
    ]
    minimum_catalog_floor = min(
        policy.minimum_choices_when_mechanically_possible,
        len(mechanical_without_memory_review),
    )
    mechanical_continuing = [item for item in mechanical if _is_continuing_research_operator(item)]
    mechanical_non_memory_continuing = [
        item for item in mechanical_continuing if item is not ResearchOperator.CONSOLIDATE_DREAMING
    ]
    mechanical_non_memory_families = _ordered_operator_families(mechanical_non_memory_continuing)
    minimum_non_memory_continuing_floor = min(
        policy.minimum_non_memory_continuing_choices_when_mechanically_possible,
        len(mechanical_non_memory_continuing),
    )
    minimum_non_memory_family_floor = min(
        policy.minimum_non_memory_continuing_families_when_mechanically_possible,
        len(mechanical_non_memory_families),
    )
    proposed: list[ResearchOperator] = []
    suppressed: list[ResearchOperator] = []
    candidate = list(mechanical)

    if not policy.enabled:
        stage = AdaptiveOperatorSteeringStage.DISABLED_IDENTITY
        primary_reason = AdaptiveOperatorSteeringReasonCode.POLICY_DISABLED
    elif observation.zone is not ResearchLoopZone.OPEN_EXPLORATION:
        stage = AdaptiveOperatorSteeringStage.NON_EXPLORATION_IDENTITY
        primary_reason = AdaptiveOperatorSteeringReasonCode.NON_EXPLORATION_STAGE
    elif repeated_family is None:
        stage = AdaptiveOperatorSteeringStage.OBSERVE_IDENTITY
        primary_reason = AdaptiveOperatorSteeringReasonCode.NO_RECENT_REPETITION
    elif repeated_family is not AdaptiveOperatorFamily.SHORT_HORIZON_INTROSPECTION:
        stage = AdaptiveOperatorSteeringStage.OBSERVE_IDENTITY
        primary_reason = AdaptiveOperatorSteeringReasonCode.NON_INTROSPECTION_REPETITION
    else:
        if debt:
            proposed = [
                item
                for item in mechanical
                if _OPERATOR_FAMILIES[item] is AdaptiveOperatorFamily.SHORT_HORIZON_INTROSPECTION
            ]
        else:
            repeated_tail = recent_ids[-policy.consecutive_family_repetition_threshold :]
            repeated_ids = set(repeated_tail)
            proposed = [item for item in mechanical if item in repeated_ids]
        if not proposed:
            stage = AdaptiveOperatorSteeringStage.OBSERVE_IDENTITY
            primary_reason = AdaptiveOperatorSteeringReasonCode.REPEATED_OPERATOR_UNAVAILABLE
        else:
            proposed_set = set(proposed)
            tentative = [item for item in mechanical if item not in proposed_set]
            tentative_without_memory_review = [
                item for item in tentative if item is not ResearchOperator.CONSOLIDATE_DREAMING
            ]
            tentative_non_memory_continuing = [
                item
                for item in tentative_without_memory_review
                if _is_continuing_research_operator(item)
            ]
            tentative_non_memory_families = _ordered_operator_families(
                tentative_non_memory_continuing
            )
            if (
                len(tentative_without_memory_review) < minimum_catalog_floor
                or len(tentative_non_memory_continuing) < minimum_non_memory_continuing_floor
                or len(tentative_non_memory_families) < minimum_non_memory_family_floor
            ):
                stage = AdaptiveOperatorSteeringStage.MINIMUM_CHOICE_FALLBACK
                primary_reason = AdaptiveOperatorSteeringReasonCode.MINIMUM_CHOICE_FALLBACK
            else:
                candidate = tentative
                suppressed = proposed
                if debt:
                    stage = AdaptiveOperatorSteeringStage.MEMORY_REVIEW_DEBT_RELIEF
                    primary_reason = AdaptiveOperatorSteeringReasonCode.MEMORY_REVIEW_DEBT_RELIEF
                else:
                    stage = AdaptiveOperatorSteeringStage.DIVERSITY_RELIEF
                    primary_reason = AdaptiveOperatorSteeringReasonCode.DIVERSITY_RELIEF

    reasons = [_reason(primary_reason, proposed if proposed else suppressed)]
    if boundary:
        reasons.append(
            _reason(
                AdaptiveOperatorSteeringReasonCode.BOUNDARY_CHOICES_PRESERVED,
                boundary,
            )
        )
    if debt and ResearchOperator.CONSOLIDATE_DREAMING in mechanical:
        reasons.append(
            _reason(
                AdaptiveOperatorSteeringReasonCode.MEMORY_REVIEW_NOT_FORCED,
                [ResearchOperator.CONSOLIDATE_DREAMING],
            )
        )

    candidate_continuing = [item for item in candidate if _is_continuing_research_operator(item)]
    candidate_non_memory_continuing = [
        item for item in candidate_continuing if item is not ResearchOperator.CONSOLIDATE_DREAMING
    ]
    candidate_non_memory_families = _ordered_operator_families(candidate_non_memory_continuing)
    if application_mode is AdaptiveOperatorSteeringApplicationMode.SHADOW_OBSERVATION:
        provider_returned = list(mechanical)
        candidate_applied = False
    else:
        provider_returned = list(candidate)
        candidate_applied = True
    controller_intervened = candidate_applied and candidate != mechanical

    return {
        "seed_hash": shadow_input.seed_hash,
        "snapshot_hash": shadow_input.snapshot_hash,
        "branch_id": shadow_input.branch_id,
        "branch_hash": shadow_input.branch_hash,
        "structural_observation_hash": shadow_input.structural_observation_hash,
        "zone": observation.zone,
        "application_mode": application_mode,
        "mechanical_input_ids": mechanical,
        "baseline_catalog_ids": mechanical,
        "candidate_catalog_ids": candidate,
        "provider_returned_catalog_ids": provider_returned,
        "candidate_applied": candidate_applied,
        "controller_intervened": controller_intervened,
        "proposed_suppressed_ids": proposed,
        "suppressed_ids": suppressed,
        "preserved_boundary_ids": boundary,
        "recent_branch_operator_ids": recent_ids,
        "recent_branch_operator_families": recent_families,
        "repeated_family": repeated_family,
        "turns_since_memory_review": turns_since_memory_review,
        "long_horizon_memory_review_debt": debt,
        "minimum_catalog_choice_floor_excluding_memory_review": minimum_catalog_floor,
        "mechanical_continuing_research_ids": mechanical_continuing,
        "candidate_continuing_research_ids": candidate_continuing,
        "mechanical_non_memory_continuing_ids": mechanical_non_memory_continuing,
        "candidate_non_memory_continuing_ids": candidate_non_memory_continuing,
        "mechanical_non_memory_continuing_families": (mechanical_non_memory_families),
        "candidate_non_memory_continuing_families": candidate_non_memory_families,
        "minimum_non_memory_continuing_choice_floor": (minimum_non_memory_continuing_floor),
        "minimum_non_memory_continuing_family_floor": (minimum_non_memory_family_floor),
        "stage": stage,
        "reasons": reasons,
    }


def _decision_projection(
    decision: AdaptiveOperatorSteeringDecisionContent,
) -> dict[str, Any]:
    fields = (
        "seed_hash",
        "snapshot_hash",
        "branch_id",
        "branch_hash",
        "structural_observation_hash",
        "zone",
        "application_mode",
        "mechanical_input_ids",
        "baseline_catalog_ids",
        "candidate_catalog_ids",
        "provider_returned_catalog_ids",
        "candidate_applied",
        "controller_intervened",
        "proposed_suppressed_ids",
        "suppressed_ids",
        "preserved_boundary_ids",
        "recent_branch_operator_ids",
        "recent_branch_operator_families",
        "repeated_family",
        "turns_since_memory_review",
        "long_horizon_memory_review_debt",
        "minimum_catalog_choice_floor_excluding_memory_review",
        "mechanical_continuing_research_ids",
        "candidate_continuing_research_ids",
        "mechanical_non_memory_continuing_ids",
        "candidate_non_memory_continuing_ids",
        "mechanical_non_memory_continuing_families",
        "candidate_non_memory_continuing_families",
        "minimum_non_memory_continuing_choice_floor",
        "minimum_non_memory_continuing_family_floor",
        "stage",
        "reasons",
    )
    return {name: getattr(decision, name) for name in fields}


def _ordered_operator_families(
    operators: Sequence[ResearchOperator],
) -> list[AdaptiveOperatorFamily]:
    ordered: list[AdaptiveOperatorFamily] = []
    for operator in operators:
        family = _OPERATOR_FAMILIES[operator]
        if family not in ordered:
            ordered.append(family)
    return ordered


def _consecutive_repeated_family(
    families: Sequence[AdaptiveOperatorFamily],
    *,
    threshold: int,
) -> AdaptiveOperatorFamily | None:
    if len(families) < threshold:
        return None
    tail = list(families[-threshold:])
    return tail[0] if len(set(tail)) == 1 else None


def _turns_since_memory_review(snapshot: AdaptiveResearchLoopSnapshot) -> int:
    memory_steps = [
        event.step_index
        for event in snapshot.events
        if event.interaction.proposal.operator is ResearchOperator.CONSOLIDATE_DREAMING
    ]
    return len(snapshot.events) - memory_steps[-1] if memory_steps else len(snapshot.events)


def _reason(
    code: AdaptiveOperatorSteeringReasonCode,
    operator_ids: Sequence[ResearchOperator],
) -> AdaptiveOperatorSteeringReason:
    return AdaptiveOperatorSteeringReason(
        code=code,
        operator_ids=list(operator_ids),
        message_cn=_REASON_TEXT_CN[code],
    )


__all__ = [
    "AdaptiveOperatorFamily",
    "AdaptiveOperatorSteeringApplicationMode",
    "AdaptiveOperatorSteeringDecision",
    "AdaptiveOperatorSteeringError",
    "AdaptiveOperatorSteeringPolicy",
    "AdaptiveOperatorSteeringReason",
    "AdaptiveOperatorSteeringReasonCode",
    "AdaptiveOperatorSteeringShadowAudit",
    "AdaptiveOperatorSteeringShadowInput",
    "AdaptiveOperatorSteeringStage",
    "AdaptiveOperatorSteeringStructuralObservation",
    "DevelopmentAdaptiveOperatorCatalogProvider",
    "ShadowAdaptiveOperatorCatalogProvider",
    "adaptive_operator_steering_development_receipt_filename",
    "audit_adaptive_operator_steering_shadow",
    "build_adaptive_operator_steering_decision",
    "build_adaptive_operator_steering_policy",
    "build_adaptive_operator_steering_shadow_input",
    "build_adaptive_operator_steering_structural_observation",
    "load_adaptive_operator_steering_development_decision",
    "seal_adaptive_operator_steering_development_decision",
]
