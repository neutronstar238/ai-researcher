"""Result-blind successor protocol for identifiable delayed-memory evaluation.

The superseded v3 benchmark expired early events but did not bound or audit the
ordinary controller state that could copy those events.  This module freezes a new
synthetic paired design without changing the historical v3 bytes.  It separates
public commitments from runner-only stimuli, hidden oracles, and arm allocation;
it does not execute a model, score a cell, or claim a memory benefit.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from collections.abc import Sequence
from enum import Enum
from math import comb
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import Field, field_validator, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    Sha256,
    StableId,
    canonical_json,
    canonical_sha256,
)
from autoresearch.research.adaptive_loop_benchmark import AdaptiveLoopBenchmarkArm
from autoresearch.research.adaptive_sovereign_loop import ResearchOperator

_SCENARIOS_PER_DOMAIN = 28
_DOMAIN_COUNT = 5
_SCENARIO_COUNT = _SCENARIOS_PER_DOMAIN * _DOMAIN_COUNT
_CELL_COUNT = _SCENARIO_COUNT * 4
_TURN_COUNT = 13
_EARLY_PANEL_TURNS = (1, 2, 3)
_DISTRACTOR_TURNS = tuple(range(4, 12))
_TERMINAL_CUE_TURN = 12
_SCORED_RESPONSE_TURN = 13
_FACTS_PER_EARLY_TURN = 64
_FACTS_PER_SCENARIO = len(_EARLY_PANEL_TURNS) * _FACTS_PER_EARLY_TURN
_VALUE_CHARACTER_COUNT = 22
_VALUE_ALPHABET_BITS = 6
_VALUE_BITS = _VALUE_CHARACTER_COUNT * _VALUE_ALPHABET_BITS
_WORKING_STATE_BYTE_BUDGET = 2_048
_RECENT_EVENT_WINDOW = 8
_PRIMARY_ALPHA = 0.05
_PRIMARY_SESOI = 0.25
_TARGET_POWER = 0.80
_POWER_FORMULA_ID = "exact-two-sided-mcnemar-binomial-mixture-v1"
_MINIMUM_SECRET_SEED_BITS = 128
_FIXED_SUCCESSOR_OPERATOR_SEQUENCE = (
    ResearchOperator.DECOMPOSE_UNCERTAINTY,
    ResearchOperator.ADVERSARIAL_CRITIQUE,
    ResearchOperator.MUTATE_WORKFLOW_PROPOSAL,
) * 4 + (ResearchOperator.STOP_EXPLORATION,)
_VALUE_ALPHABET = tuple(
    dict.fromkeys(
        "天地玄黄宇宙洪荒日月星辰风雨雷电山川湖海江河春夏秋冬东西南北"
        "金木水火土云霞霜雪松竹梅兰菊桃杏柳石泉溪谷峰岭原野晨暮昼夜"
        "明暗青红白黑"
    )
)[: 2**_VALUE_ALPHABET_BITS]
if len(_VALUE_ALPHABET) != 2**_VALUE_ALPHABET_BITS:  # pragma: no cover - import invariant
    raise RuntimeError("delayed-memory value alphabet must contain exactly 64 symbols")

_T = TypeVar("_T", bound=KernelContract)


class AdaptiveLoopMemorySuccessorError(RuntimeError):
    """Raised when successor preregistration or release evidence is inconsistent."""


class DelayedMemoryDomain(str, Enum):
    LITERATURE_EVIDENCE = "literature_evidence"
    INSTRUMENT_CALIBRATION = "instrument_calibration"
    DATASET_LINEAGE = "dataset_lineage"
    EXPERIMENT_RECEIPT = "experiment_receipt"
    METHOD_CONSTRAINT = "method_constraint"


class DelayedMemoryStimulusKind(str, Enum):
    EARLY_RANDOM_PANEL = "early_random_panel"
    NEUTRAL_DISTRACTOR = "neutral_distractor"
    TERMINAL_ADDRESS_CUE = "terminal_address_cue"
    SCORED_RESPONSE_REQUEST = "scored_response_request"


class DelayedMemoryTurnCommitment(KernelContract):
    schema_version: Literal["delayed-memory-turn-commitment-v1"] = (
        "delayed-memory-turn-commitment-v1"
    )
    scenario_id: StableId
    turn_index: int = Field(ge=1, le=_TURN_COUNT)
    stimulus_kind: DelayedMemoryStimulusKind
    private_stimulus_hash: Sha256
    payload_utf8_byte_count: int = Field(ge=1, le=8_000)
    public_fact_count: int = Field(ge=0, le=_FACTS_PER_EARLY_TURN)
    release_not_before_turn_index: int = Field(ge=1, le=_TURN_COUNT)
    payload_text_public_before_release: Literal[False] = False
    future_stimulus_content_controller_visible: Literal[False] = False
    commitment_hash: Sha256

    @model_validator(mode="after")
    def _validate_contract(self) -> DelayedMemoryTurnCommitment:
        if self.release_not_before_turn_index != self.turn_index:
            raise ValueError("turn commitment release index mismatch")
        expected_count = (
            _FACTS_PER_EARLY_TURN
            if self.stimulus_kind is DelayedMemoryStimulusKind.EARLY_RANDOM_PANEL
            else 0
        )
        if self.public_fact_count != expected_count:
            raise ValueError("turn commitment fact count mismatch")
        _require_hash(self, "commitment_hash")
        return self

    @classmethod
    def create(cls, **values: Any) -> DelayedMemoryTurnCommitment:
        return _create_hashed(cls, "commitment_hash", values)


class DelayedMemoryWorkingStateContract(KernelContract):
    schema_version: Literal["delayed-memory-working-state-contract-v1"] = (
        "delayed-memory-working-state-contract-v1"
    )
    maximum_non_sovereign_terminal_projection_utf8_bytes: Literal[2048] = 2048
    maximum_non_sovereign_terminal_projection_bits: Literal[16384] = 16384
    recent_event_window_turns: Literal[8] = 8
    early_random_fact_count: Literal[192] = 192
    nominal_random_bits_per_value: Literal[132] = 132
    nominal_early_value_information_bits: Literal[25344] = 25344
    early_information_exceeds_working_state_bits: Literal[True] = True
    projection_includes_all_model_authored_terminal_visible_state: Literal[True] = True
    projection_includes_branch_titles_and_hypotheses: Literal[True] = True
    projection_includes_workflow_proposal_history: Literal[True] = True
    projection_includes_non_sovereign_feedback_and_notes: Literal[True] = True
    projection_excludes_current_turn_stimulus: Literal[True] = True
    projection_excludes_static_system_and_skill_bytes: Literal[True] = True
    projection_excludes_provenance_bound_sovereign_exposures: Literal[True] = True
    overflow_scores_terminal_task_failure: Literal[True] = True
    complete_projection_receipt_required_for_scoring: Literal[True] = True
    bounded_non_sovereign_state_may_use_any_encoding: Literal[True] = True
    exact_value_presence_is_diagnostic_not_automatic_failure: Literal[True] = True
    truncation_after_observing_overflow_allowed: Literal[False] = False
    same_projection_budget_all_arms: Literal[True] = True
    contract_hash: Sha256

    @model_validator(mode="after")
    def _validate_contract(self) -> DelayedMemoryWorkingStateContract:
        if self.maximum_non_sovereign_terminal_projection_bits != (
            8 * self.maximum_non_sovereign_terminal_projection_utf8_bytes
        ):
            raise ValueError("working-state bit and byte budgets disagree")
        if self.nominal_early_value_information_bits != (
            self.early_random_fact_count * self.nominal_random_bits_per_value
        ):
            raise ValueError("working-state early information total mismatch")
        if self.nominal_early_value_information_bits <= (
            self.maximum_non_sovereign_terminal_projection_bits
        ):
            raise ValueError("early random panel does not exceed the working-state budget")
        _require_hash(self, "contract_hash")
        return self

    @classmethod
    def create(cls, **values: Any) -> DelayedMemoryWorkingStateContract:
        return _create_hashed(cls, "contract_hash", values)


class DelayedMemoryArmContract(KernelContract):
    schema_version: Literal["delayed-memory-arm-contract-v1"] = "delayed-memory-arm-contract-v1"
    arm: AdaptiveLoopBenchmarkArm
    turn_count: Literal[13] = 13
    next_operator_selected_by_model: bool
    operator_topology_fixed: bool
    fixed_operator_sequence: list[ResearchOperator] = Field(max_length=_TURN_COUNT)
    branch_archive_available: bool
    controller_sovereign_raw_recall_available: bool
    rebuildable_dreaming_available: bool
    dynamic_zero_or_more_skills: bool
    main_agent_temporary_dispatch_available: bool
    exact_action_schema_identical_across_arms: Literal[True] = True
    same_model_configuration_across_arms: Literal[True] = True
    same_request_and_reasoning_budget_across_arms: Literal[True] = True
    same_non_memory_capabilities_across_primary_contrast: Literal[True] = True
    strict_promotion_and_safety_policy_identical: Literal[True] = True
    audit_raw_capture_retained_all_arms: Literal[True] = True
    controller_visibility_respects_arm: Literal[True] = True
    non_intervention_configuration_hash: Sha256
    arm_contract_hash: Sha256

    @model_validator(mode="after")
    def _validate_arm(self) -> DelayedMemoryArmContract:
        fixed = self.arm in {
            AdaptiveLoopBenchmarkArm.FIXED_PIPELINE,
            AdaptiveLoopBenchmarkArm.LINEAR_MODEL_LOOP,
        }
        if self.operator_topology_fixed != fixed:
            raise ValueError("arm fixed-topology flag mismatch")
        if self.next_operator_selected_by_model == fixed:
            raise ValueError("arm model-selection flag mismatch")
        expected_sequence = list(_FIXED_SUCCESSOR_OPERATOR_SEQUENCE) if fixed else []
        if self.fixed_operator_sequence != expected_sequence:
            raise ValueError("arm fixed operator sequence mismatch")
        adaptive = self.arm in {
            AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY,
            AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN,
        }
        if self.branch_archive_available != adaptive:
            raise ValueError("arm branch-archive flag mismatch")
        sovereign = self.arm is AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN
        if (
            self.controller_sovereign_raw_recall_available != sovereign
            or self.rebuildable_dreaming_available != sovereign
        ):
            raise ValueError("arm sovereign-memory intervention mismatch")
        expected_skills = self.arm is not AdaptiveLoopBenchmarkArm.FIXED_PIPELINE
        if self.dynamic_zero_or_more_skills != expected_skills:
            raise ValueError("arm dynamic-skill flag mismatch")
        if self.main_agent_temporary_dispatch_available != adaptive:
            raise ValueError("arm temporary-dispatch flag mismatch")
        expected_non_intervention = canonical_sha256(
            _arm_non_intervention_configuration(
                next_operator_selected_by_model=self.next_operator_selected_by_model,
                operator_topology_fixed=self.operator_topology_fixed,
                fixed_operator_sequence=self.fixed_operator_sequence,
                branch_archive_available=self.branch_archive_available,
                dynamic_zero_or_more_skills=self.dynamic_zero_or_more_skills,
                main_agent_temporary_dispatch_available=(
                    self.main_agent_temporary_dispatch_available
                ),
            )
        )
        if self.non_intervention_configuration_hash != expected_non_intervention:
            raise ValueError("arm non-intervention configuration hash mismatch")
        _require_hash(self, "arm_contract_hash")
        return self

    @classmethod
    def create(cls, **values: Any) -> DelayedMemoryArmContract:
        return _create_hashed(cls, "arm_contract_hash", values)


class DelayedMemoryPowerSensitivityPoint(KernelContract):
    schema_version: Literal["delayed-memory-power-sensitivity-v1"] = (
        "delayed-memory-power-sensitivity-v1"
    )
    paired_scenario_count: Literal[140] = 140
    sesoi_risk_difference: float = Field(default=0.25, ge=0.25, le=0.25)
    total_discordance_probability: float = Field(gt=0.0, le=1.0)
    a4_success_a3_failure_probability: float = Field(ge=0.0, le=1.0)
    a4_failure_a3_success_probability: float = Field(ge=0.0, le=1.0)
    exact_two_sided_mcnemar_power: float = Field(ge=0.0, le=1.0)
    formula_id: Literal["exact-two-sided-mcnemar-binomial-mixture-v1"] = (
        "exact-two-sided-mcnemar-binomial-mixture-v1"
    )
    point_hash: Sha256

    @model_validator(mode="after")
    def _validate_point(self) -> DelayedMemoryPowerSensitivityPoint:
        if self.sesoi_risk_difference != _PRIMARY_SESOI:
            raise ValueError("power sensitivity SESOI mismatch")
        discordance = self.total_discordance_probability
        expected_p10 = (discordance + self.sesoi_risk_difference) / 2.0
        expected_p01 = (discordance - self.sesoi_risk_difference) / 2.0
        if expected_p01 < 0.0:
            raise ValueError("power sensitivity discordance is below the SESOI")
        if abs(self.a4_success_a3_failure_probability - expected_p10) > 1e-12:
            raise ValueError("power sensitivity p10 mismatch")
        if abs(self.a4_failure_a3_success_probability - expected_p01) > 1e-12:
            raise ValueError("power sensitivity p01 mismatch")
        expected_power = round(
            _exact_two_sided_mcnemar_power(
                paired_scenarios=self.paired_scenario_count,
                total_discordance=discordance,
                risk_difference=self.sesoi_risk_difference,
                alpha=_PRIMARY_ALPHA,
            ),
            12,
        )
        if abs(self.exact_two_sided_mcnemar_power - expected_power) > 1e-12:
            raise ValueError("power sensitivity result mismatch")
        _require_hash(self, "point_hash")
        return self

    @classmethod
    def create(cls, **values: Any) -> DelayedMemoryPowerSensitivityPoint:
        return _create_hashed(cls, "point_hash", values)


class DelayedMemoryAnalysisContract(KernelContract):
    schema_version: Literal["delayed-memory-analysis-contract-v1"] = (
        "delayed-memory-analysis-contract-v1"
    )
    experimental_unit: Literal["independent_synthetic_scenario"] = "independent_synthetic_scenario"
    paired_scenario_count: Literal[140] = 140
    cells_per_scenario: Literal[4] = 4
    total_cell_count: Literal[560] = 560
    primary_endpoint: Literal[
        "exact_terminal_value_with_complete_bounded_working_state_projection"
    ] = "exact_terminal_value_with_complete_bounded_working_state_projection"
    primary_contrast: Literal["adaptive_sovereign_minus_adaptive_derived_only"] = (
        "adaptive_sovereign_minus_adaptive_derived_only"
    )
    primary_test: Literal["two_sided_exact_mcnemar"] = "two_sided_exact_mcnemar"
    primary_alpha: float = Field(default=0.05, ge=0.05, le=0.05)
    target_power: float = Field(default=0.8, ge=0.8, le=0.8)
    sesoi_risk_difference: float = Field(default=0.25, ge=0.25, le=0.25)
    sesoi_basis_cn: str = Field(min_length=20, max_length=1_000)
    power_formula_id: Literal["exact-two-sided-mcnemar-binomial-mixture-v1"] = (
        "exact-two-sided-mcnemar-binomial-mixture-v1"
    )
    sensitivity_points: list[DelayedMemoryPowerSensitivityPoint] = Field(
        min_length=5,
        max_length=5,
    )
    worst_case_total_discordance_for_target_power: float = Field(default=1.0, ge=1.0, le=1.0)
    worst_case_exact_power: float = Field(ge=0.8, le=1.0)
    all_four_arms_randomized_within_each_scenario: Literal[True] = True
    scenario_is_block_and_unit_of_replication: Literal[True] = True
    turns_or_model_calls_are_not_independent_replicates: Literal[True] = True
    missing_failed_or_invalid_cell_scores_zero: Literal[True] = True
    incomplete_pairs_are_not_dropped: Literal[True] = True
    observed_effect_power_recalculation_allowed: Literal[False] = False
    secondary_endpoints_separate_raw_recall_exposure_and_consumption: Literal[True] = True
    ordinary_working_memory_compression_is_permitted: Literal[True] = True
    primary_success_requires_complete_working_state_projection: Literal[True] = True
    unbounded_state_or_posthoc_truncation_scores_failure: Literal[True] = True
    memory_benefit_claim_requires_primary_significance: Literal[True] = True
    memory_benefit_claim_requires_observed_effect_at_least_sesoi: Literal[True] = True
    memory_benefit_claim_requires_actual_use_for_every_a4_only_win: Literal[True] = True
    generalization_limited_to_frozen_synthetic_generator_family: Literal[True] = True
    scientific_correctness_verified: Literal[False] = False
    innovation_verified: Literal[False] = False
    publication_authorized: Literal[False] = False
    analysis_hash: Sha256

    @field_validator("sesoi_basis_cn")
    @classmethod
    def _require_chinese_basis(cls, value: str) -> str:
        return _require_chinese(value, label="SESOI basis")

    @model_validator(mode="after")
    def _validate_analysis(self) -> DelayedMemoryAnalysisContract:
        if (
            self.primary_alpha != _PRIMARY_ALPHA
            or self.target_power != _TARGET_POWER
            or self.sesoi_risk_difference != _PRIMARY_SESOI
            or self.worst_case_total_discordance_for_target_power != 1.0
        ):
            raise ValueError("analysis fixed numeric contract mismatch")
        discordances = [item.total_discordance_probability for item in self.sensitivity_points]
        if discordances != [0.30, 0.35, 0.50, 0.75, 1.0]:
            raise ValueError("power sensitivity grid mismatch")
        if self.total_cell_count != self.paired_scenario_count * self.cells_per_scenario:
            raise ValueError("analysis cell count mismatch")
        if (
            abs(
                self.worst_case_exact_power
                - self.sensitivity_points[-1].exact_two_sided_mcnemar_power
            )
            > 1e-12
        ):
            raise ValueError("analysis worst-case power mismatch")
        if self.worst_case_exact_power < self.target_power:
            raise ValueError("analysis does not meet target power at worst-case discordance")
        _require_hash(self, "analysis_hash")
        return self

    @classmethod
    def create(cls, **values: Any) -> DelayedMemoryAnalysisContract:
        return _create_hashed(cls, "analysis_hash", values)


class DelayedMemoryScenarioCommitment(KernelContract):
    schema_version: Literal["delayed-memory-scenario-commitment-v1"] = (
        "delayed-memory-scenario-commitment-v1"
    )
    scenario_id: StableId
    domain: DelayedMemoryDomain
    instance_index: int = Field(ge=1, le=_SCENARIOS_PER_DOMAIN)
    independence_key: StableId
    turn_commitments: list[DelayedMemoryTurnCommitment] = Field(
        min_length=_TURN_COUNT,
        max_length=_TURN_COUNT,
    )
    private_scenario_stimuli_hash: Sha256
    private_oracle_hash: Sha256
    early_random_fact_count: Literal[192] = 192
    nominal_random_bits_per_value: Literal[132] = 132
    terminal_query_selection_unavailable_before_turn_twelve: Literal[True] = True
    expected_value_absent_from_turns_four_through_thirteen: Literal[True] = True
    future_turn_content_committed_but_not_controller_visible: Literal[True] = True
    contains_required_operator_or_skill: Literal[False] = False
    content_is_seed_repeat: Literal[False] = False
    commitment_hash: Sha256

    @model_validator(mode="after")
    def _validate_scenario(self) -> DelayedMemoryScenarioCommitment:
        if [item.turn_index for item in self.turn_commitments] != list(range(1, 14)):
            raise ValueError("scenario commitments must cover turns one through thirteen")
        if any(item.scenario_id != self.scenario_id for item in self.turn_commitments):
            raise ValueError("scenario commitment turn belongs to another scenario")
        expected_kinds = [
            *([DelayedMemoryStimulusKind.EARLY_RANDOM_PANEL] * 3),
            *([DelayedMemoryStimulusKind.NEUTRAL_DISTRACTOR] * 8),
            DelayedMemoryStimulusKind.TERMINAL_ADDRESS_CUE,
            DelayedMemoryStimulusKind.SCORED_RESPONSE_REQUEST,
        ]
        if [item.stimulus_kind for item in self.turn_commitments] != expected_kinds:
            raise ValueError("scenario stimulus-kind schedule mismatch")
        if sum(item.public_fact_count for item in self.turn_commitments) != (
            self.early_random_fact_count
        ):
            raise ValueError("scenario early fact total mismatch")
        _require_hash(self, "commitment_hash")
        return self

    @classmethod
    def create(cls, **values: Any) -> DelayedMemoryScenarioCommitment:
        return _create_hashed(cls, "commitment_hash", values)


class DelayedMemoryPublicPreregistration(KernelContract):
    schema_version: Literal["adaptive-loop-delayed-memory-preregistration-v1"] = (
        "adaptive-loop-delayed-memory-preregistration-v1"
    )
    protocol_id: Literal["task2713-delayed-memory-successor-v1"] = (
        "task2713-delayed-memory-successor-v1"
    )
    superseded_v3_execution_protocol_hash: Literal[
        "cfe042f2061f89e3d8a56d1a39fe65a056fd88ab11d7912165a926b67991d6a3"
    ] = "cfe042f2061f89e3d8a56d1a39fe65a056fd88ab11d7912165a926b67991d6a3"
    supersession_reason_cn: str = Field(min_length=20, max_length=2_000)
    arm_contracts: list[DelayedMemoryArmContract] = Field(min_length=4, max_length=4)
    scenario_commitments: list[DelayedMemoryScenarioCommitment] = Field(
        min_length=_SCENARIO_COUNT,
        max_length=_SCENARIO_COUNT,
    )
    working_state_contract: DelayedMemoryWorkingStateContract
    analysis_contract: DelayedMemoryAnalysisContract
    private_stimulus_manifest_hash: Sha256
    private_oracle_manifest_hash: Sha256
    stimulus_seed_controller_visible: Literal[False] = False
    assignment_seed_controller_visible: Literal[False] = False
    per_turn_release_service_required: Literal[True] = True
    formal_execution_requires_external_release_service: Literal[True] = True
    in_process_builder_is_not_independent_secrecy_boundary: Literal[True] = True
    public_tree_contains_stimulus_payloads: Literal[False] = False
    public_tree_contains_oracles_or_arm_assignments: Literal[False] = False
    candidate_receives_run_root_or_manifest_paths: Literal[False] = False
    maximum_main_model_requests_per_cell: Literal[39] = 39
    maximum_external_actions_per_cell: Literal[13] = 13
    maximum_temporary_agents_per_cell: Literal[7] = 7
    maximum_walltime_seconds_per_cell: Literal[3600] = 3600
    fresh_model_session_and_raw_store_per_cell: Literal[True] = True
    cross_cell_or_cross_arm_memory_allowed: Literal[False] = False
    provider_model_base_url_temperature_and_thinking_identical: Literal[True] = True
    next_operator_selected_by_model_in_adaptive_arms: Literal[True] = True
    dreaming_operator_required_at_any_turn: Literal[False] = False
    specific_skill_required_at_any_turn: Literal[False] = False
    protocol_frozen_before_cell_results: Literal[True] = True
    contains_cell_results: Literal[False] = False
    execution_authorized: Literal[False] = False
    scientific_result: Literal[False] = False
    innovation_verified: Literal[False] = False
    publication_authorized: Literal[False] = False
    preregistration_hash: Sha256

    @field_validator("supersession_reason_cn")
    @classmethod
    def _require_chinese_reason(cls, value: str) -> str:
        return _require_chinese(value, label="supersession reason")

    @model_validator(mode="after")
    def _validate_preregistration(self) -> DelayedMemoryPublicPreregistration:
        expected_arms = list(AdaptiveLoopBenchmarkArm)
        if [item.arm for item in self.arm_contracts] != expected_arms:
            raise ValueError("successor preregistration arm order mismatch")
        a3 = next(
            item
            for item in self.arm_contracts
            if item.arm is AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY
        )
        a4 = next(
            item
            for item in self.arm_contracts
            if item.arm is AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN
        )
        if a3.non_intervention_configuration_hash != a4.non_intervention_configuration_hash:
            raise ValueError("primary contrast differs outside sovereign memory capability")
        if len({item.scenario_id for item in self.scenario_commitments}) != _SCENARIO_COUNT:
            raise ValueError("successor preregistration repeats a scenario ID")
        if len({item.independence_key for item in self.scenario_commitments}) != _SCENARIO_COUNT:
            raise ValueError("successor preregistration repeats an independence key")
        counts = Counter(item.domain for item in self.scenario_commitments)
        if counts != Counter({domain: _SCENARIOS_PER_DOMAIN for domain in DelayedMemoryDomain}):
            raise ValueError("successor preregistration domain balance mismatch")
        for domain in DelayedMemoryDomain:
            indices = [
                item.instance_index for item in self.scenario_commitments if item.domain is domain
            ]
            if indices != list(range(1, _SCENARIOS_PER_DOMAIN + 1)):
                raise ValueError("successor preregistration domain indices are not contiguous")
        _require_hash(self, "preregistration_hash")
        return self

    @classmethod
    def create(cls, **values: Any) -> DelayedMemoryPublicPreregistration:
        return _create_hashed(cls, "preregistration_hash", values)


class DelayedMemoryPrivateStimulus(KernelContract):
    schema_version: Literal["delayed-memory-private-stimulus-v1"] = (
        "delayed-memory-private-stimulus-v1"
    )
    scenario_id: StableId
    turn_index: int = Field(ge=1, le=_TURN_COUNT)
    stimulus_kind: DelayedMemoryStimulusKind
    payload_cn: str = Field(min_length=20, max_length=8_000)
    payload_utf8_sha256: Sha256
    release_nonce: Sha256
    public_fact_ids: list[StableId] = Field(default_factory=list, max_length=64)
    release_not_before_turn_index: int = Field(ge=1, le=_TURN_COUNT)
    controller_visible_only_at_declared_turn: Literal[True] = True
    contains_required_operator_or_skill: Literal[False] = False
    stimulus_hash: Sha256

    @field_validator("payload_cn")
    @classmethod
    def _require_chinese_payload(cls, value: str) -> str:
        return _require_chinese(value, label="private stimulus")

    @field_validator("public_fact_ids")
    @classmethod
    def _require_unique_facts(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("private stimulus repeats a public fact ID")
        return value

    @model_validator(mode="after")
    def _validate_stimulus(self) -> DelayedMemoryPrivateStimulus:
        if self.release_not_before_turn_index != self.turn_index:
            raise ValueError("private stimulus release turn mismatch")
        expected_count = (
            _FACTS_PER_EARLY_TURN
            if self.stimulus_kind is DelayedMemoryStimulusKind.EARLY_RANDOM_PANEL
            else 0
        )
        if len(self.public_fact_ids) != expected_count:
            raise ValueError("private stimulus fact count mismatch")
        if self.payload_utf8_sha256 != hashlib.sha256(self.payload_cn.encode()).hexdigest():
            raise ValueError("private stimulus payload hash mismatch")
        _require_hash(self, "stimulus_hash")
        return self

    @classmethod
    def create(cls, **values: Any) -> DelayedMemoryPrivateStimulus:
        return _create_hashed(cls, "stimulus_hash", values)


class DelayedMemoryPrivateScenarioStimuli(KernelContract):
    schema_version: Literal["delayed-memory-private-scenario-stimuli-v1"] = (
        "delayed-memory-private-scenario-stimuli-v1"
    )
    scenario_id: StableId
    domain: DelayedMemoryDomain
    instance_index: int = Field(ge=1, le=_SCENARIOS_PER_DOMAIN)
    stimuli: list[DelayedMemoryPrivateStimulus] = Field(
        min_length=_TURN_COUNT,
        max_length=_TURN_COUNT,
    )
    scenario_stimuli_hash: Sha256

    @model_validator(mode="after")
    def _validate_scenario(self) -> DelayedMemoryPrivateScenarioStimuli:
        if [item.turn_index for item in self.stimuli] != list(range(1, 14)):
            raise ValueError("private scenario stimuli must cover turns one through thirteen")
        if any(item.scenario_id != self.scenario_id for item in self.stimuli):
            raise ValueError("private scenario contains a cross-scenario stimulus")
        _require_hash(self, "scenario_stimuli_hash")
        return self

    @classmethod
    def create(cls, **values: Any) -> DelayedMemoryPrivateScenarioStimuli:
        return _create_hashed(cls, "scenario_stimuli_hash", values)


class DelayedMemoryPrivateStimulusManifest(KernelContract):
    schema_version: Literal["delayed-memory-private-stimulus-manifest-v1"] = (
        "delayed-memory-private-stimulus-manifest-v1"
    )
    protocol_id: Literal["task2713-delayed-memory-successor-v1"] = (
        "task2713-delayed-memory-successor-v1"
    )
    stimulus_seed: int = Field(ge=0)
    scenarios: list[DelayedMemoryPrivateScenarioStimuli] = Field(
        min_length=_SCENARIO_COUNT,
        max_length=_SCENARIO_COUNT,
    )
    controller_visible: Literal[False] = False
    candidate_visible: Literal[False] = False
    per_turn_release_only: Literal[True] = True
    manifest_hash: Sha256

    @field_validator("stimulus_seed")
    @classmethod
    def _require_secret_seed_entropy(cls, value: int) -> int:
        return _require_secret_seed(value, label="stimulus seed")

    @model_validator(mode="after")
    def _validate_manifest(self) -> DelayedMemoryPrivateStimulusManifest:
        if len({item.scenario_id for item in self.scenarios}) != _SCENARIO_COUNT:
            raise ValueError("private stimulus manifest repeats scenario IDs")
        _require_hash(self, "manifest_hash")
        return self

    @classmethod
    def create(cls, **values: Any) -> DelayedMemoryPrivateStimulusManifest:
        return _create_hashed(cls, "manifest_hash", values)


class DelayedMemoryHiddenOracle(KernelContract):
    schema_version: Literal["delayed-memory-hidden-oracle-v1"] = "delayed-memory-hidden-oracle-v1"
    scenario_id: StableId
    private_scenario_stimuli_hash: Sha256
    commitment_nonce: Sha256
    queried_address: StableId
    expected_value_cn: str = Field(min_length=_VALUE_CHARACTER_COUNT, max_length=128)
    expected_value_utf8_sha256: Sha256
    source_early_turn_index: int = Field(ge=1, le=3)
    source_fact_id: StableId
    terminal_cue_turn_index: Literal[12] = 12
    scored_response_turn_index: Literal[13] = 13
    expected_value_not_repeated_after_source_turn: Literal[True] = True
    controller_visible: Literal[False] = False
    oracle_hash: Sha256

    @field_validator("expected_value_cn")
    @classmethod
    def _validate_expected_value(cls, value: str) -> str:
        if len(value) != _VALUE_CHARACTER_COUNT or any(
            character not in _VALUE_ALPHABET for character in value
        ):
            raise ValueError("oracle expected value is not a canonical random Chinese token")
        return value

    @model_validator(mode="after")
    def _validate_oracle(self) -> DelayedMemoryHiddenOracle:
        expected = hashlib.sha256(self.expected_value_cn.encode("utf-8")).hexdigest()
        if self.expected_value_utf8_sha256 != expected:
            raise ValueError("oracle expected-value hash mismatch")
        _require_hash(self, "oracle_hash")
        return self

    @classmethod
    def create(cls, **values: Any) -> DelayedMemoryHiddenOracle:
        return _create_hashed(cls, "oracle_hash", values)


class DelayedMemoryHiddenOracleManifest(KernelContract):
    schema_version: Literal["delayed-memory-hidden-oracle-manifest-v1"] = (
        "delayed-memory-hidden-oracle-manifest-v1"
    )
    protocol_id: Literal["task2713-delayed-memory-successor-v1"] = (
        "task2713-delayed-memory-successor-v1"
    )
    private_stimulus_manifest_hash: Sha256
    oracles: list[DelayedMemoryHiddenOracle] = Field(
        min_length=_SCENARIO_COUNT,
        max_length=_SCENARIO_COUNT,
    )
    reveal_only_after_all_cell_outputs_sealed: Literal[True] = True
    controller_visible: Literal[False] = False
    candidate_visible: Literal[False] = False
    manifest_hash: Sha256

    @model_validator(mode="after")
    def _validate_manifest(self) -> DelayedMemoryHiddenOracleManifest:
        if len({item.scenario_id for item in self.oracles}) != _SCENARIO_COUNT:
            raise ValueError("hidden oracle manifest repeats scenario IDs")
        _require_hash(self, "manifest_hash")
        return self

    @classmethod
    def create(cls, **values: Any) -> DelayedMemoryHiddenOracleManifest:
        return _create_hashed(cls, "manifest_hash", values)


class DelayedMemoryBlindedCell(KernelContract):
    schema_version: Literal["delayed-memory-blinded-cell-v1"] = "delayed-memory-blinded-cell-v1"
    blinded_cell_id: StableId
    scenario_id: StableId
    scenario_commitment_hash: Sha256
    anonymous_within_scenario_slot: int = Field(ge=1, le=4)
    arm_hidden_from_controller_and_evaluator: Literal[True] = True
    cell_hash: Sha256

    @model_validator(mode="after")
    def _validate_cell(self) -> DelayedMemoryBlindedCell:
        _require_hash(self, "cell_hash")
        return self

    @classmethod
    def create(cls, **values: Any) -> DelayedMemoryBlindedCell:
        return _create_hashed(cls, "cell_hash", values)


class DelayedMemoryBlindedCellManifest(KernelContract):
    schema_version: Literal["delayed-memory-blinded-cell-manifest-v1"] = (
        "delayed-memory-blinded-cell-manifest-v1"
    )
    preregistration_hash: Sha256
    cells: list[DelayedMemoryBlindedCell] = Field(min_length=_CELL_COUNT, max_length=_CELL_COUNT)
    contains_arm_assignment: Literal[False] = False
    contains_randomization_seed: Literal[False] = False
    contains_stimulus_or_oracle_content: Literal[False] = False
    manifest_hash: Sha256

    @model_validator(mode="after")
    def _validate_manifest(self) -> DelayedMemoryBlindedCellManifest:
        if len({item.blinded_cell_id for item in self.cells}) != _CELL_COUNT:
            raise ValueError("blinded manifest repeats cell IDs")
        grouped: dict[str, list[int]] = defaultdict(list)
        for cell in self.cells:
            grouped[cell.scenario_id].append(cell.anonymous_within_scenario_slot)
        if len(grouped) != _SCENARIO_COUNT or any(
            sorted(slots) != [1, 2, 3, 4] for slots in grouped.values()
        ):
            raise ValueError("blinded manifest does not contain four slots per scenario")
        _require_hash(self, "manifest_hash")
        return self

    @classmethod
    def create(cls, **values: Any) -> DelayedMemoryBlindedCellManifest:
        return _create_hashed(cls, "manifest_hash", values)


class DelayedMemoryRunnerAssignment(KernelContract):
    schema_version: Literal["delayed-memory-runner-assignment-v1"] = (
        "delayed-memory-runner-assignment-v1"
    )
    blinded_cell_id: StableId
    scenario_id: StableId
    anonymous_within_scenario_slot: int = Field(ge=1, le=4)
    allocation_sequence_id: StableId
    arm: AdaptiveLoopBenchmarkArm
    global_run_position: int = Field(ge=1, le=_CELL_COUNT)
    assignment_hash: Sha256

    @model_validator(mode="after")
    def _validate_assignment(self) -> DelayedMemoryRunnerAssignment:
        _require_hash(self, "assignment_hash")
        return self

    @classmethod
    def create(cls, **values: Any) -> DelayedMemoryRunnerAssignment:
        return _create_hashed(cls, "assignment_hash", values)


class DelayedMemoryRunnerAssignmentManifest(KernelContract):
    schema_version: Literal["delayed-memory-runner-assignment-manifest-v1"] = (
        "delayed-memory-runner-assignment-manifest-v1"
    )
    preregistration_hash: Sha256
    blinded_cell_manifest_hash: Sha256
    private_stimulus_manifest_hash: Sha256
    hidden_oracle_manifest_hash: Sha256
    assignment_seed: int = Field(ge=0)
    assignments: list[DelayedMemoryRunnerAssignment] = Field(
        min_length=_CELL_COUNT,
        max_length=_CELL_COUNT,
    )
    scenario_block_randomization: Literal[True] = True
    each_arm_once_per_scenario: Literal[True] = True
    allocation_sequences_balanced_within_domain: Literal[True] = True
    controller_visible: Literal[False] = False
    evaluator_visible_before_global_seal: Literal[False] = False
    manifest_hash: Sha256

    @field_validator("assignment_seed")
    @classmethod
    def _require_secret_seed_entropy(cls, value: int) -> int:
        return _require_secret_seed(value, label="assignment seed")

    @model_validator(mode="after")
    def _validate_manifest(self) -> DelayedMemoryRunnerAssignmentManifest:
        if len({item.blinded_cell_id for item in self.assignments}) != _CELL_COUNT:
            raise ValueError("runner assignment repeats blinded cells")
        if sorted(item.global_run_position for item in self.assignments) != list(
            range(1, _CELL_COUNT + 1)
        ):
            raise ValueError("runner assignment positions are not contiguous")
        grouped: dict[str, list[DelayedMemoryRunnerAssignment]] = defaultdict(list)
        for assignment in self.assignments:
            grouped[assignment.scenario_id].append(assignment)
        if len(grouped) != _SCENARIO_COUNT or any(
            {item.arm for item in values} != set(AdaptiveLoopBenchmarkArm)
            for values in grouped.values()
        ):
            raise ValueError("runner assignment does not allocate all arms per scenario")
        _require_hash(self, "manifest_hash")
        return self

    @classmethod
    def create(cls, **values: Any) -> DelayedMemoryRunnerAssignmentManifest:
        return _create_hashed(cls, "manifest_hash", values)


class DelayedMemoryTurnRelease(KernelContract):
    schema_version: Literal["delayed-memory-turn-release-v1"] = "delayed-memory-turn-release-v1"
    private_stimulus_manifest_hash: Sha256
    scenario_id: StableId
    turn_index: int = Field(ge=1, le=_TURN_COUNT)
    claimed_completed_turn_indices: list[int] = Field(max_length=_TURN_COUNT - 1)
    stimulus: DelayedMemoryPrivateStimulus
    future_stimulus_count_exposed: Literal[0] = 0
    commitment_sequence_verified: Literal[True] = True
    prior_turn_execution_completion_verified: Literal[False] = False
    proves_runner_process_cannot_read_future_stimuli: Literal[False] = False
    release_hash: Sha256

    @model_validator(mode="after")
    def _validate_release(self) -> DelayedMemoryTurnRelease:
        if self.claimed_completed_turn_indices != list(range(1, self.turn_index)):
            raise ValueError("turn release predecessor schedule mismatch")
        if self.stimulus.scenario_id != self.scenario_id:
            raise ValueError("turn release stimulus belongs to another scenario")
        if self.stimulus.turn_index != self.turn_index:
            raise ValueError("turn release stimulus index mismatch")
        _require_hash(self, "release_hash")
        return self

    @classmethod
    def create(cls, **values: Any) -> DelayedMemoryTurnRelease:
        return _create_hashed(cls, "release_hash", values)


class DelayedMemoryWorkingStateAudit(KernelContract):
    schema_version: Literal["delayed-memory-working-state-audit-v1"] = (
        "delayed-memory-working-state-audit-v1"
    )
    scenario_id: StableId
    oracle_hash: Sha256
    working_state_contract_hash: Sha256
    non_sovereign_projection_utf8_sha256: Sha256
    non_sovereign_projection_utf8_byte_count: int = Field(ge=0)
    sovereign_projection_utf8_sha256: Sha256
    expected_value_present_in_non_sovereign_projection: bool
    expected_value_present_in_sovereign_projection: bool
    non_sovereign_projection_within_budget: bool
    exact_value_presence_is_diagnostic_only: Literal[True] = True
    mechanical_fragment_budget_condition_satisfied: bool
    complete_terminal_prompt_projection_verified: Literal[False] = False
    terminal_task_score_eligible: Literal[False] = False
    does_not_score_terminal_answer: Literal[True] = True
    does_not_establish_causal_memory_benefit: Literal[True] = True
    audit_hash: Sha256

    @model_validator(mode="after")
    def _validate_audit(self) -> DelayedMemoryWorkingStateAudit:
        if self.mechanical_fragment_budget_condition_satisfied != (
            self.non_sovereign_projection_within_budget
        ):
            raise ValueError("working-state fragment budget-condition flag mismatch")
        _require_hash(self, "audit_hash")
        return self

    @classmethod
    def create(cls, **values: Any) -> DelayedMemoryWorkingStateAudit:
        return _create_hashed(cls, "audit_hash", values)


class AdaptiveLoopDelayedMemorySuccessorBundle(KernelContract):
    schema_version: Literal["adaptive-loop-delayed-memory-successor-bundle-v1"] = (
        "adaptive-loop-delayed-memory-successor-bundle-v1"
    )
    preregistration: DelayedMemoryPublicPreregistration
    blinded_cells: DelayedMemoryBlindedCellManifest
    runner_private_stimuli: DelayedMemoryPrivateStimulusManifest
    runner_private_oracles: DelayedMemoryHiddenOracleManifest
    runner_private_assignments: DelayedMemoryRunnerAssignmentManifest
    bundle_is_in_memory_orchestration_only: Literal[True] = True
    combined_public_private_bundle_must_not_be_written: Literal[True] = True
    bundle_does_not_prove_future_content_isolation: Literal[True] = True
    bundle_is_not_formal_execution_evidence: Literal[True] = True
    contains_results: Literal[False] = False
    bundle_hash: Sha256

    @model_validator(mode="after")
    def _validate_bundle(self) -> AdaptiveLoopDelayedMemorySuccessorBundle:
        prereg = self.preregistration
        if prereg.private_stimulus_manifest_hash != self.runner_private_stimuli.manifest_hash:
            raise ValueError("bundle stimulus-manifest binding mismatch")
        if prereg.private_oracle_manifest_hash != self.runner_private_oracles.manifest_hash:
            raise ValueError("bundle oracle-manifest binding mismatch")
        if self.runner_private_oracles.private_stimulus_manifest_hash != (
            self.runner_private_stimuli.manifest_hash
        ):
            raise ValueError("bundle oracle-to-stimulus binding mismatch")
        if self.blinded_cells.preregistration_hash != prereg.preregistration_hash:
            raise ValueError("bundle blinded-to-preregistration binding mismatch")
        assignments = self.runner_private_assignments
        expected_bindings = (
            prereg.preregistration_hash,
            self.blinded_cells.manifest_hash,
            self.runner_private_stimuli.manifest_hash,
            self.runner_private_oracles.manifest_hash,
        )
        actual_bindings = (
            assignments.preregistration_hash,
            assignments.blinded_cell_manifest_hash,
            assignments.private_stimulus_manifest_hash,
            assignments.hidden_oracle_manifest_hash,
        )
        if actual_bindings != expected_bindings:
            raise ValueError("bundle runner-assignment binding mismatch")
        commitments = {item.scenario_id: item for item in prereg.scenario_commitments}
        private_scenarios = {
            item.scenario_id: item for item in self.runner_private_stimuli.scenarios
        }
        oracles = {item.scenario_id: item for item in self.runner_private_oracles.oracles}
        if set(commitments) != set(private_scenarios) or set(commitments) != set(oracles):
            raise ValueError("bundle scenario membership mismatch")
        for scenario_id, commitment in commitments.items():
            private_scenario = private_scenarios[scenario_id]
            oracle = oracles[scenario_id]
            if (
                private_scenario.domain is not commitment.domain
                or private_scenario.instance_index != commitment.instance_index
                or private_scenario.scenario_stimuli_hash
                != commitment.private_scenario_stimuli_hash
                or oracle.private_scenario_stimuli_hash != private_scenario.scenario_stimuli_hash
                or oracle.oracle_hash != commitment.private_oracle_hash
            ):
                raise ValueError("bundle scenario scientific-identity binding mismatch")
            for turn_commitment, stimulus in zip(
                commitment.turn_commitments,
                private_scenario.stimuli,
                strict=True,
            ):
                if (
                    turn_commitment.private_stimulus_hash != stimulus.stimulus_hash
                    or turn_commitment.stimulus_kind is not stimulus.stimulus_kind
                    or turn_commitment.payload_utf8_byte_count
                    != len(stimulus.payload_cn.encode("utf-8"))
                    or turn_commitment.public_fact_count != len(stimulus.public_fact_ids)
                ):
                    raise ValueError("bundle turn commitment-to-stimulus binding mismatch")

        cells = {item.blinded_cell_id: item for item in self.blinded_cells.cells}
        for cell in cells.values():
            cell_commitment = commitments.get(cell.scenario_id)
            if (
                cell_commitment is None
                or cell.scenario_commitment_hash != cell_commitment.commitment_hash
            ):
                raise ValueError("bundle blinded-cell scenario binding mismatch")
        assignment_by_cell = {item.blinded_cell_id: item for item in assignments.assignments}
        if set(assignment_by_cell) != set(cells):
            raise ValueError("bundle assignment-to-blinded-cell membership mismatch")
        for cell_id, assignment in assignment_by_cell.items():
            cell = cells[cell_id]
            if (
                assignment.scenario_id != cell.scenario_id
                or assignment.anonymous_within_scenario_slot != cell.anonymous_within_scenario_slot
            ):
                raise ValueError("bundle assignment-to-blinded-cell identity mismatch")
        _require_hash(self, "bundle_hash")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveLoopDelayedMemorySuccessorBundle:
        return _create_hashed(cls, "bundle_hash", values)


def build_adaptive_loop_delayed_memory_successor_bundle(
    *,
    stimulus_seed: int,
    assignment_seed: int,
) -> AdaptiveLoopDelayedMemorySuccessorBundle:
    """Build the complete private orchestration bundle before any cell result."""

    _require_secret_seed(stimulus_seed, label="stimulus seed")
    _require_secret_seed(assignment_seed, label="assignment seed")
    if stimulus_seed == assignment_seed:
        raise AdaptiveLoopMemorySuccessorError("stimulus and assignment seeds must differ")

    private_scenarios: list[DelayedMemoryPrivateScenarioStimuli] = []
    oracles: list[DelayedMemoryHiddenOracle] = []
    for domain in DelayedMemoryDomain:
        for instance_index in range(1, _SCENARIOS_PER_DOMAIN + 1):
            scenario, oracle = _build_private_scenario(
                domain=domain,
                instance_index=instance_index,
                stimulus_seed=stimulus_seed,
            )
            private_scenarios.append(scenario)
            oracles.append(oracle)

    stimulus_manifest = DelayedMemoryPrivateStimulusManifest.create(
        stimulus_seed=stimulus_seed,
        scenarios=private_scenarios,
    )
    oracle_manifest = DelayedMemoryHiddenOracleManifest.create(
        private_stimulus_manifest_hash=stimulus_manifest.manifest_hash,
        oracles=oracles,
    )
    oracle_by_scenario = {item.scenario_id: item for item in oracles}
    scenario_commitments = [
        _build_scenario_commitment(
            scenario=scenario,
            oracle=oracle_by_scenario[scenario.scenario_id],
        )
        for scenario in private_scenarios
    ]
    analysis = _build_analysis_contract()
    working_state = DelayedMemoryWorkingStateContract.create()
    preregistration = DelayedMemoryPublicPreregistration.create(
        supersession_reason_cn=(
            "旧版只让早期事件离开最近八轮，却未限制模型把关键值复制到分支假设或工作流记录，"
            "因此无法把终轮正确归因于主权原始记忆。后继版冻结随机高熵面板、逐轮密封释放、"
            "非主权工作状态预算与旁路审计，并把任务正确、召回、暴露和消费分开。"
        ),
        arm_contracts=_build_arm_contracts(),
        scenario_commitments=scenario_commitments,
        working_state_contract=working_state,
        analysis_contract=analysis,
        private_stimulus_manifest_hash=stimulus_manifest.manifest_hash,
        private_oracle_manifest_hash=oracle_manifest.manifest_hash,
    )
    blinded, assignments = _build_cell_manifests(
        preregistration=preregistration,
        stimulus_manifest=stimulus_manifest,
        oracle_manifest=oracle_manifest,
        assignment_seed=assignment_seed,
    )
    return AdaptiveLoopDelayedMemorySuccessorBundle.create(
        preregistration=preregistration,
        blinded_cells=blinded,
        runner_private_stimuli=stimulus_manifest,
        runner_private_oracles=oracle_manifest,
        runner_private_assignments=assignments,
    )


def write_adaptive_loop_delayed_memory_successor_preregistration(
    *,
    public_output_dir: Path | str,
    runner_private_output_dir: Path | str,
    stimulus_seed: int,
    assignment_seed: int,
) -> AdaptiveLoopDelayedMemorySuccessorBundle:
    """Write public and runner-private artifacts to disjoint directory trees."""

    public_root = Path(public_output_dir).resolve()
    private_root = Path(runner_private_output_dir).resolve()
    if (
        public_root == private_root
        or public_root.is_relative_to(private_root)
        or private_root.is_relative_to(public_root)
    ):
        raise AdaptiveLoopMemorySuccessorError(
            "public and runner-private successor roots must be disjoint siblings"
        )
    public_paths = (
        public_root / "adaptive-loop-delayed-memory-preregistration-v1.json",
        public_root / "adaptive-loop-delayed-memory-blinded-cells-v1.json",
    )
    private_paths = (
        private_root / "adaptive-loop-delayed-memory-private-stimuli-v1.json",
        private_root / "adaptive-loop-delayed-memory-hidden-oracles-v1.json",
        private_root / "adaptive-loop-delayed-memory-runner-assignments-v1.json",
    )
    existing = [path for path in (*public_paths, *private_paths) if path.exists()]
    if existing:
        raise AdaptiveLoopMemorySuccessorError(f"successor artifact already exists: {existing[0]}")
    bundle = build_adaptive_loop_delayed_memory_successor_bundle(
        stimulus_seed=stimulus_seed,
        assignment_seed=assignment_seed,
    )
    public_root.mkdir(parents=True, exist_ok=True)
    private_root.mkdir(parents=True, exist_ok=True)
    _write_once(public_paths[0], bundle.preregistration)
    _write_once(public_paths[1], bundle.blinded_cells)
    _write_once(private_paths[0], bundle.runner_private_stimuli)
    _write_once(private_paths[1], bundle.runner_private_oracles)
    _write_once(private_paths[2], bundle.runner_private_assignments)
    return bundle


def release_adaptive_loop_delayed_memory_turn(
    manifest: DelayedMemoryPrivateStimulusManifest,
    *,
    scenario_id: str,
    turn_index: int,
    completed_turn_indices: Sequence[int],
) -> DelayedMemoryTurnRelease:
    """Release exactly one committed turn; this is not independent process isolation."""

    expected_completed = list(range(1, turn_index))
    if list(completed_turn_indices) != expected_completed:
        raise AdaptiveLoopMemorySuccessorError(
            "successor turn release requires every exact predecessor and no future turn"
        )
    scenario = next((item for item in manifest.scenarios if item.scenario_id == scenario_id), None)
    if scenario is None:
        raise AdaptiveLoopMemorySuccessorError("successor turn release scenario is absent")
    if turn_index < 1 or turn_index > len(scenario.stimuli):
        raise AdaptiveLoopMemorySuccessorError("successor turn release index is outside protocol")
    stimulus = scenario.stimuli[turn_index - 1]
    return DelayedMemoryTurnRelease.create(
        private_stimulus_manifest_hash=manifest.manifest_hash,
        scenario_id=scenario_id,
        turn_index=turn_index,
        claimed_completed_turn_indices=expected_completed,
        stimulus=stimulus,
    )


def audit_delayed_memory_terminal_working_state(
    *,
    oracle: DelayedMemoryHiddenOracle,
    contract: DelayedMemoryWorkingStateContract,
    non_sovereign_text_fragments: Sequence[str],
    sovereign_memory_text_fragments: Sequence[str],
) -> DelayedMemoryWorkingStateAudit:
    """Audit terminal prompt provenance without scoring the model's answer."""

    if any(not isinstance(item, str) for item in non_sovereign_text_fragments):
        raise AdaptiveLoopMemorySuccessorError("non-sovereign projection contains non-text")
    if any(not isinstance(item, str) for item in sovereign_memory_text_fragments):
        raise AdaptiveLoopMemorySuccessorError("sovereign projection contains non-text")
    non_sovereign = "\n".join(non_sovereign_text_fragments)
    sovereign = "\n".join(sovereign_memory_text_fragments)
    non_sovereign_bytes = non_sovereign.encode("utf-8")
    sovereign_bytes = sovereign.encode("utf-8")
    leaked = oracle.expected_value_cn in non_sovereign
    sovereign_present = oracle.expected_value_cn in sovereign
    within_budget = len(non_sovereign_bytes) <= (
        contract.maximum_non_sovereign_terminal_projection_utf8_bytes
    )
    return DelayedMemoryWorkingStateAudit.create(
        scenario_id=oracle.scenario_id,
        oracle_hash=oracle.oracle_hash,
        working_state_contract_hash=contract.contract_hash,
        non_sovereign_projection_utf8_sha256=hashlib.sha256(non_sovereign_bytes).hexdigest(),
        non_sovereign_projection_utf8_byte_count=len(non_sovereign_bytes),
        sovereign_projection_utf8_sha256=hashlib.sha256(sovereign_bytes).hexdigest(),
        expected_value_present_in_non_sovereign_projection=leaked,
        expected_value_present_in_sovereign_projection=sovereign_present,
        non_sovereign_projection_within_budget=within_budget,
        mechanical_fragment_budget_condition_satisfied=within_budget,
    )


def _build_private_scenario(
    *,
    domain: DelayedMemoryDomain,
    instance_index: int,
    stimulus_seed: int,
) -> tuple[DelayedMemoryPrivateScenarioStimuli, DelayedMemoryHiddenOracle]:
    scenario_id = f"dmem.{domain.value}.{instance_index:02d}"
    records = [
        _random_record(stimulus_seed=stimulus_seed, scenario_id=scenario_id, ordinal=ordinal)
        for ordinal in range(1, _FACTS_PER_SCENARIO + 1)
    ]
    addresses = [item[0] for item in records]
    values = [item[1] for item in records]
    if len(set(addresses)) != len(addresses) or len(set(values)) != len(values):
        raise AdaptiveLoopMemorySuccessorError("successor random panel contains a collision")
    query_ordinal = (
        int(_digest_hex(stimulus_seed, scenario_id, "terminal-query")[:16], 16)
        % _FACTS_PER_SCENARIO
    )
    queried_address, expected_value = records[query_ordinal]
    source_turn_index = query_ordinal // _FACTS_PER_EARLY_TURN + 1
    source_fact_id = f"{scenario_id}.fact-{query_ordinal + 1:03d}"

    stimuli: list[DelayedMemoryPrivateStimulus] = []
    domain_label = _domain_label(domain)
    for turn_index in _EARLY_PANEL_TURNS:
        start = (turn_index - 1) * _FACTS_PER_EARLY_TURN
        block = records[start : start + _FACTS_PER_EARLY_TURN]
        rows = [f"记录{address}={value}；" for address, value in block]
        payload = (
            f"{domain_label}的第{turn_index}批独立校准面板如下。每个地址和值都只是待保留的"
            "原始观察，不代表研究结论，也不规定你选择任何算子：\n" + "\n".join(rows)
        )
        fact_ids = [
            f"{scenario_id}.fact-{ordinal:03d}"
            for ordinal in range(start + 1, start + _FACTS_PER_EARLY_TURN + 1)
        ]
        stimuli.append(
            DelayedMemoryPrivateStimulus.create(
                scenario_id=scenario_id,
                turn_index=turn_index,
                stimulus_kind=DelayedMemoryStimulusKind.EARLY_RANDOM_PANEL,
                payload_cn=payload,
                payload_utf8_sha256=hashlib.sha256(payload.encode()).hexdigest(),
                release_nonce=_digest_hex(
                    stimulus_seed,
                    scenario_id,
                    f"turn-{turn_index}-release-nonce",
                ),
                public_fact_ids=fact_ids,
                release_not_before_turn_index=turn_index,
            )
        )
    for turn_index in _DISTRACTOR_TURNS:
        nonce = _digest_hex(stimulus_seed, scenario_id, f"neutral-{turn_index}")[:12]
        payload = (
            f"{domain_label}本轮只收到不含早期地址和值的中性流程观察。流水标识为{nonce}；"
            "它用于形成真实的跨轮间隔，不给出终轮查询键、不要求记忆动作，也不改变科研权限。"
        )
        stimuli.append(
            DelayedMemoryPrivateStimulus.create(
                scenario_id=scenario_id,
                turn_index=turn_index,
                stimulus_kind=DelayedMemoryStimulusKind.NEUTRAL_DISTRACTOR,
                payload_cn=payload,
                payload_utf8_sha256=hashlib.sha256(payload.encode()).hexdigest(),
                release_nonce=_digest_hex(
                    stimulus_seed,
                    scenario_id,
                    f"turn-{turn_index}-release-nonce",
                ),
                public_fact_ids=[],
                release_not_before_turn_index=turn_index,
            )
        )
    cue_payload = (
        f"终轮地址线索现在才首次释放：{queried_address}。请自行决定下一动作；最终需报告"
        "该地址在最初三轮随机校准面板中对应的二十二字校验值。不得猜测或伪造，"
        "本轮仍不指定算子、Skill或记忆策略。"
    )
    stimuli.append(
        DelayedMemoryPrivateStimulus.create(
            scenario_id=scenario_id,
            turn_index=_TERMINAL_CUE_TURN,
            stimulus_kind=DelayedMemoryStimulusKind.TERMINAL_ADDRESS_CUE,
            payload_cn=cue_payload,
            payload_utf8_sha256=hashlib.sha256(cue_payload.encode()).hexdigest(),
            release_nonce=_digest_hex(
                stimulus_seed,
                scenario_id,
                "turn-12-release-nonce",
            ),
            public_fact_ids=[],
            release_not_before_turn_index=_TERMINAL_CUE_TURN,
        )
    )
    response_payload = (
        f"请基于截至目前真实可见的证据，对地址{queried_address}提交最终二十二字校验值，"
        "并说明使用了哪条可追溯记录；仍可自主选择任何机械可用算子。若没有足够证据，"
        "应明确失败，不得由系统补写答案。"
    )
    stimuli.append(
        DelayedMemoryPrivateStimulus.create(
            scenario_id=scenario_id,
            turn_index=_SCORED_RESPONSE_TURN,
            stimulus_kind=DelayedMemoryStimulusKind.SCORED_RESPONSE_REQUEST,
            payload_cn=response_payload,
            payload_utf8_sha256=hashlib.sha256(response_payload.encode()).hexdigest(),
            release_nonce=_digest_hex(
                stimulus_seed,
                scenario_id,
                "turn-13-release-nonce",
            ),
            public_fact_ids=[],
            release_not_before_turn_index=_SCORED_RESPONSE_TURN,
        )
    )
    scenario = DelayedMemoryPrivateScenarioStimuli.create(
        scenario_id=scenario_id,
        domain=domain,
        instance_index=instance_index,
        stimuli=stimuli,
    )
    late_text = "\n".join(item.payload_cn for item in stimuli[3:])
    early_text = "\n".join(item.payload_cn for item in stimuli[:3])
    if expected_value not in early_text or early_text.count(expected_value) != 1:
        raise AdaptiveLoopMemorySuccessorError("oracle value is not unique in the early panel")
    if expected_value in late_text:
        raise AdaptiveLoopMemorySuccessorError("oracle value leaks into a late stimulus")
    if queried_address in "\n".join(item.payload_cn for item in stimuli[3:11]):
        raise AdaptiveLoopMemorySuccessorError(
            "the selected terminal address is repeated during the distractor window"
        )
    oracle = DelayedMemoryHiddenOracle.create(
        scenario_id=scenario_id,
        private_scenario_stimuli_hash=scenario.scenario_stimuli_hash,
        commitment_nonce=_digest_hex(
            stimulus_seed,
            scenario_id,
            "oracle-commitment-nonce",
        ),
        queried_address=queried_address,
        expected_value_cn=expected_value,
        expected_value_utf8_sha256=hashlib.sha256(expected_value.encode("utf-8")).hexdigest(),
        source_early_turn_index=source_turn_index,
        source_fact_id=source_fact_id,
    )
    return scenario, oracle


def _build_scenario_commitment(
    *,
    scenario: DelayedMemoryPrivateScenarioStimuli,
    oracle: DelayedMemoryHiddenOracle,
) -> DelayedMemoryScenarioCommitment:
    commitments = [
        DelayedMemoryTurnCommitment.create(
            scenario_id=scenario.scenario_id,
            turn_index=stimulus.turn_index,
            stimulus_kind=stimulus.stimulus_kind,
            private_stimulus_hash=stimulus.stimulus_hash,
            payload_utf8_byte_count=len(stimulus.payload_cn.encode("utf-8")),
            public_fact_count=len(stimulus.public_fact_ids),
            release_not_before_turn_index=stimulus.turn_index,
        )
        for stimulus in scenario.stimuli
    ]
    independence_key = (
        f"ind.{hashlib.sha256(scenario.scenario_stimuli_hash.encode('ascii')).hexdigest()[:32]}"
    )
    return DelayedMemoryScenarioCommitment.create(
        scenario_id=scenario.scenario_id,
        domain=scenario.domain,
        instance_index=scenario.instance_index,
        independence_key=independence_key,
        turn_commitments=commitments,
        private_scenario_stimuli_hash=scenario.scenario_stimuli_hash,
        private_oracle_hash=oracle.oracle_hash,
    )


def _build_arm_contracts() -> list[DelayedMemoryArmContract]:
    contracts: list[DelayedMemoryArmContract] = []
    for arm in AdaptiveLoopBenchmarkArm:
        fixed = arm in {
            AdaptiveLoopBenchmarkArm.FIXED_PIPELINE,
            AdaptiveLoopBenchmarkArm.LINEAR_MODEL_LOOP,
        }
        adaptive = arm in {
            AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY,
            AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN,
        }
        sequence = list(_FIXED_SUCCESSOR_OPERATOR_SEQUENCE) if fixed else []
        non_intervention = _arm_non_intervention_configuration(
            next_operator_selected_by_model=not fixed,
            operator_topology_fixed=fixed,
            fixed_operator_sequence=sequence,
            branch_archive_available=adaptive,
            dynamic_zero_or_more_skills=(arm is not AdaptiveLoopBenchmarkArm.FIXED_PIPELINE),
            main_agent_temporary_dispatch_available=adaptive,
        )
        contracts.append(
            DelayedMemoryArmContract.create(
                arm=arm,
                next_operator_selected_by_model=not fixed,
                operator_topology_fixed=fixed,
                fixed_operator_sequence=sequence,
                branch_archive_available=adaptive,
                controller_sovereign_raw_recall_available=(
                    arm is AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN
                ),
                rebuildable_dreaming_available=(arm is AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN),
                dynamic_zero_or_more_skills=(arm is not AdaptiveLoopBenchmarkArm.FIXED_PIPELINE),
                main_agent_temporary_dispatch_available=adaptive,
                non_intervention_configuration_hash=canonical_sha256(non_intervention),
            )
        )
    return contracts


def _arm_non_intervention_configuration(
    *,
    next_operator_selected_by_model: bool,
    operator_topology_fixed: bool,
    fixed_operator_sequence: Sequence[ResearchOperator],
    branch_archive_available: bool,
    dynamic_zero_or_more_skills: bool,
    main_agent_temporary_dispatch_available: bool,
) -> dict[str, Any]:
    return {
        "schema_version": "delayed-memory-arm-non-intervention-configuration-v1",
        "turn_count": _TURN_COUNT,
        "next_operator_selected_by_model": next_operator_selected_by_model,
        "operator_topology_fixed": operator_topology_fixed,
        "fixed_operator_sequence": [item.value for item in fixed_operator_sequence],
        "branch_archive_available": branch_archive_available,
        "dynamic_zero_or_more_skills": dynamic_zero_or_more_skills,
        "main_agent_temporary_dispatch_available": main_agent_temporary_dispatch_available,
        "exact_action_schema_identical_across_arms": True,
        "same_model_configuration_across_arms": True,
        "same_request_and_reasoning_budget_across_arms": True,
        "strict_promotion_and_safety_policy_identical": True,
        "working_state_utf8_byte_budget": _WORKING_STATE_BYTE_BUDGET,
    }


def _build_analysis_contract() -> DelayedMemoryAnalysisContract:
    points = []
    for discordance in (0.30, 0.35, 0.50, 0.75, 1.0):
        p10 = (discordance + _PRIMARY_SESOI) / 2.0
        p01 = (discordance - _PRIMARY_SESOI) / 2.0
        points.append(
            DelayedMemoryPowerSensitivityPoint.create(
                total_discordance_probability=discordance,
                a4_success_a3_failure_probability=p10,
                a4_failure_a3_success_probability=p01,
                exact_two_sided_mcnemar_power=round(
                    _exact_two_sided_mcnemar_power(
                        paired_scenarios=_SCENARIO_COUNT,
                        total_discordance=discordance,
                        risk_difference=_PRIMARY_SESOI,
                        alpha=_PRIMARY_ALPHA,
                    ),
                    12,
                ),
            )
        )
    return DelayedMemoryAnalysisContract.create(
        sesoi_basis_cn=(
            "在运行任何新单元前，把二十五个百分点定义为值得承担主权原始层额外延迟、"
            "存储和审计成本的最小决策差异；该阈值来自采用决策而不是已观察 pilot 效应。"
        ),
        sensitivity_points=points,
        worst_case_exact_power=points[-1].exact_two_sided_mcnemar_power,
    )


def _build_cell_manifests(
    *,
    preregistration: DelayedMemoryPublicPreregistration,
    stimulus_manifest: DelayedMemoryPrivateStimulusManifest,
    oracle_manifest: DelayedMemoryHiddenOracleManifest,
    assignment_seed: int,
) -> tuple[DelayedMemoryBlindedCellManifest, DelayedMemoryRunnerAssignmentManifest]:
    sequences = _allocation_sequences()
    sequence_by_scenario: dict[str, tuple[str, tuple[AdaptiveLoopBenchmarkArm, ...]]] = {}
    for domain in DelayedMemoryDomain:
        domain_scenarios = [
            item for item in preregistration.scenario_commitments if item.domain is domain
        ]
        ranked = sorted(
            domain_scenarios,
            key=lambda item: _seeded_rank(assignment_seed, domain.value, item.scenario_id),
        )
        for offset, scenario in enumerate(ranked):
            sequence_by_scenario[scenario.scenario_id] = sequences[offset % len(sequences)]

    blinded_cells: list[DelayedMemoryBlindedCell] = []
    provisional: list[tuple[DelayedMemoryBlindedCell, str, AdaptiveLoopBenchmarkArm]] = []
    for scenario in preregistration.scenario_commitments:
        sequence_id, arms = sequence_by_scenario[scenario.scenario_id]
        for slot, arm in enumerate(arms, start=1):
            cell_id = (
                "cell."
                + _digest_hex(
                    assignment_seed,
                    scenario.scenario_id,
                    f"anonymous-slot-{slot}",
                )[:32]
            )
            cell = DelayedMemoryBlindedCell.create(
                blinded_cell_id=cell_id,
                scenario_id=scenario.scenario_id,
                scenario_commitment_hash=scenario.commitment_hash,
                anonymous_within_scenario_slot=slot,
            )
            blinded_cells.append(cell)
            provisional.append((cell, sequence_id, arm))
    blinded_manifest = DelayedMemoryBlindedCellManifest.create(
        preregistration_hash=preregistration.preregistration_hash,
        cells=blinded_cells,
    )
    ranked_cells = sorted(
        provisional,
        key=lambda item: _seeded_rank(assignment_seed, "global-run-order", item[0].blinded_cell_id),
    )
    position_by_cell = {
        cell.blinded_cell_id: position
        for position, (cell, _, _) in enumerate(ranked_cells, start=1)
    }
    assignments = [
        DelayedMemoryRunnerAssignment.create(
            blinded_cell_id=cell.blinded_cell_id,
            scenario_id=cell.scenario_id,
            anonymous_within_scenario_slot=cell.anonymous_within_scenario_slot,
            allocation_sequence_id=sequence_id,
            arm=arm,
            global_run_position=position_by_cell[cell.blinded_cell_id],
        )
        for cell, sequence_id, arm in provisional
    ]
    assignment_manifest = DelayedMemoryRunnerAssignmentManifest.create(
        preregistration_hash=preregistration.preregistration_hash,
        blinded_cell_manifest_hash=blinded_manifest.manifest_hash,
        private_stimulus_manifest_hash=stimulus_manifest.manifest_hash,
        hidden_oracle_manifest_hash=oracle_manifest.manifest_hash,
        assignment_seed=assignment_seed,
        assignments=assignments,
    )
    _validate_sequence_balance(preregistration, assignment_manifest)
    return blinded_manifest, assignment_manifest


def _validate_sequence_balance(
    preregistration: DelayedMemoryPublicPreregistration,
    assignments: DelayedMemoryRunnerAssignmentManifest,
) -> None:
    domain_by_scenario = {
        item.scenario_id: item.domain for item in preregistration.scenario_commitments
    }
    seen_sequence_by_scenario: dict[str, str] = {}
    for assignment in assignments.assignments:
        previous = seen_sequence_by_scenario.setdefault(
            assignment.scenario_id,
            assignment.allocation_sequence_id,
        )
        if previous != assignment.allocation_sequence_id:
            raise AdaptiveLoopMemorySuccessorError("scenario uses multiple allocation sequences")
    for domain in DelayedMemoryDomain:
        counts = Counter(
            sequence_id
            for scenario_id, sequence_id in seen_sequence_by_scenario.items()
            if domain_by_scenario[scenario_id] is domain
        )
        if counts != Counter({f"latin-{index}": 7 for index in range(1, 5)}):
            raise AdaptiveLoopMemorySuccessorError(
                "allocation sequences are not exactly balanced within domain"
            )


def _allocation_sequences() -> (
    tuple[
        tuple[str, tuple[AdaptiveLoopBenchmarkArm, ...]],
        ...,
    ]
):
    arms = tuple(AdaptiveLoopBenchmarkArm)
    return tuple(
        (
            f"latin-{offset + 1}",
            tuple(arms[(index + offset) % len(arms)] for index in range(len(arms))),
        )
        for offset in range(len(arms))
    )


def _random_record(*, stimulus_seed: int, scenario_id: str, ordinal: int) -> tuple[str, str]:
    digest = hashlib.sha256(
        f"delayed-memory-address-v1|{stimulus_seed}|{scenario_id}|{ordinal}".encode()
    ).hexdigest()
    address = f"A{digest[:12].upper()}"
    value_bytes = hashlib.sha256(
        f"delayed-memory-value-v1|{stimulus_seed}|{scenario_id}|{ordinal}".encode()
    ).digest()
    value = "".join(_VALUE_ALPHABET[byte & 63] for byte in value_bytes[:_VALUE_CHARACTER_COUNT])
    return address, value


def _domain_label(domain: DelayedMemoryDomain) -> str:
    return {
        DelayedMemoryDomain.LITERATURE_EVIDENCE: "文献证据索引",
        DelayedMemoryDomain.INSTRUMENT_CALIBRATION: "仪器校准记录",
        DelayedMemoryDomain.DATASET_LINEAGE: "数据谱系记录",
        DelayedMemoryDomain.EXPERIMENT_RECEIPT: "实验回执索引",
        DelayedMemoryDomain.METHOD_CONSTRAINT: "方法约束登记",
    }[domain]


def _exact_two_sided_mcnemar_power(
    *,
    paired_scenarios: int,
    total_discordance: float,
    risk_difference: float,
    alpha: float,
) -> float:
    p10 = (total_discordance + risk_difference) / 2.0
    p01 = (total_discordance - risk_difference) / 2.0
    if p01 < 0.0 or p10 > 1.0 or p10 + p01 > 1.0:
        raise AdaptiveLoopMemorySuccessorError("invalid McNemar planning probabilities")
    conditional_a4_win = p10 / total_discordance
    power = 0.0
    for discordant_count in range(paired_scenarios + 1):
        discordant_probability = (
            comb(paired_scenarios, discordant_count)
            * (total_discordance**discordant_count)
            * ((1.0 - total_discordance) ** (paired_scenarios - discordant_count))
        )
        conditional_rejection = 0.0
        for a4_win_count in range(discordant_count + 1):
            if _exact_two_sided_binomial_pvalue(a4_win_count, discordant_count) > alpha:
                continue
            conditional_rejection += (
                comb(discordant_count, a4_win_count)
                * (conditional_a4_win**a4_win_count)
                * ((1.0 - conditional_a4_win) ** (discordant_count - a4_win_count))
            )
        power += discordant_probability * conditional_rejection
    return power


def _exact_two_sided_binomial_pvalue(successes: int, trials: int) -> float:
    if trials == 0:
        return 1.0
    tail = min(successes, trials - successes)
    probability = 2.0 * sum(comb(trials, index) for index in range(tail + 1)) / (2**trials)
    return float(min(1.0, probability))


def _seeded_rank(seed: int, namespace: str, value: str) -> str:
    return _digest_hex(seed, namespace, value)


def _digest_hex(seed: int, namespace: str, value: str) -> str:
    return hashlib.sha256(f"{seed}|{namespace}|{value}".encode()).hexdigest()


def _require_secret_seed(value: int, *, label: str) -> int:
    if value.bit_length() < _MINIMUM_SECRET_SEED_BITS or value.bit_length() > 256:
        raise AdaptiveLoopMemorySuccessorError(
            f"{label} must be an explicit independent 128-to-256-bit runner secret"
        )
    return value


def _require_chinese(value: str, *, label: str) -> str:
    normalized = value.strip()
    if not any("\u3400" <= character <= "\u9fff" for character in normalized):
        raise ValueError(f"{label} must contain Chinese")
    return normalized


def _create_hashed(cls: type[_T], hash_field: str, values: dict[str, Any]) -> _T:
    draft_values = {**values, hash_field: "0" * 64}
    draft = cls.model_construct(None, **draft_values)
    payload = draft.model_dump(mode="json", exclude={hash_field})
    payload[hash_field] = canonical_sha256(payload)
    return cls.model_validate(payload)


def _require_hash(model: KernelContract, hash_field: str) -> None:
    payload = model.model_dump(mode="json", exclude={hash_field})
    if getattr(model, hash_field) != canonical_sha256(payload):
        raise ValueError(f"{hash_field} mismatch")


def _write_once(path: Path, model: KernelContract) -> None:
    payload = canonical_json(model).encode("utf-8")
    try:
        with path.open("xb") as handle:
            handle.write(payload)
    except FileExistsError as exc:
        raise AdaptiveLoopMemorySuccessorError(
            f"successor artifact already exists: {path}"
        ) from exc


__all__ = [
    "AdaptiveLoopDelayedMemorySuccessorBundle",
    "AdaptiveLoopMemorySuccessorError",
    "DelayedMemoryAnalysisContract",
    "DelayedMemoryArmContract",
    "DelayedMemoryBlindedCellManifest",
    "DelayedMemoryDomain",
    "DelayedMemoryHiddenOracle",
    "DelayedMemoryHiddenOracleManifest",
    "DelayedMemoryPrivateStimulusManifest",
    "DelayedMemoryPublicPreregistration",
    "DelayedMemoryRunnerAssignment",
    "DelayedMemoryRunnerAssignmentManifest",
    "DelayedMemoryScenarioCommitment",
    "DelayedMemoryStimulusKind",
    "DelayedMemoryTurnRelease",
    "DelayedMemoryWorkingStateAudit",
    "DelayedMemoryWorkingStateContract",
    "audit_delayed_memory_terminal_working_state",
    "build_adaptive_loop_delayed_memory_successor_bundle",
    "release_adaptive_loop_delayed_memory_turn",
    "write_adaptive_loop_delayed_memory_successor_preregistration",
]
