"""Result-blind v3 execution protocol for the adaptive-loop benchmark.

This module freezes independent Chinese challenge instances, hidden mechanical
oracles, balanced run order, and the confirmatory analysis contract.  It does
not execute a model, contact a network service, or contain cell outcomes.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    Sha256,
    StableId,
    canonical_json,
    canonical_sha256,
)
from autoresearch.research.adaptive_loop_benchmark import (
    AdaptiveLoopBenchmarkArm,
    AdaptiveLoopBenchmarkProtocol,
    AdaptiveLoopChallengeKind,
    build_adaptive_loop_benchmark_protocol,
)
from autoresearch.research.adaptive_loop_benchmark_design import (
    AdaptiveLoopBenchmarkDesignAudit,
    audit_adaptive_loop_benchmark_design,
)

_SCENARIOS_PER_CHALLENGE = 12
_CONFIRMATORY_SCENARIO_COUNT = 60
_CONFIRMATORY_CELL_COUNT = 240
_STIMULUS_TURN_COUNT = 12
_NON_SOVEREIGN_RECENT_WINDOW_TURNS = 8
_NEUTRAL_DISTRACTOR_TURNS = tuple(range(4, 12))
_PROHIBITED_SEED_TERMS = (
    "假设",
    "方法",
    "计划",
    "预期结果",
    "研究方案",
    "hypothesis",
    "method",
    "plan",
)


class AdaptiveLoopBenchmarkExecutionProtocolError(RuntimeError):
    """Raised when a frozen execution artifact is inconsistent or changed."""


class AdaptiveLoopBenchmarkStimulusKind(str, Enum):
    SOURCE_RECORD = "source_record"
    TASK_CONTEXT = "task_context"
    TOOL_RECEIPT = "tool_receipt"
    PROVENANCE_NOTICE = "provenance_notice"
    TERMINAL_REQUEST = "terminal_request"


class AdaptiveLoopBenchmarkTerminalState(str, Enum):
    INTEGRATE_DELAYED_EVIDENCE = "integrate_delayed_evidence"
    ADOPT_SUPERSEDING_RECORD = "adopt_superseding_record"
    RESOLVE_SOURCE_CONFLICT = "resolve_source_conflict"
    ADAPT_AFTER_EMPTY_RESULT = "adapt_after_empty_result"
    QUARANTINE_UNPROVEN_DERIVED_MEMORY = "quarantine_unproven_derived_memory"


class AdaptiveLoopBenchmarkPublicStimulus(KernelContract):
    schema_version: Literal["adaptive-loop-public-stimulus-v3"] = "adaptive-loop-public-stimulus-v3"
    stimulus_id: StableId
    turn_index: int = Field(ge=1, le=32)
    kind: AdaptiveLoopBenchmarkStimulusKind
    payload_cn: str = Field(min_length=20, max_length=4_000)
    public_fact_ids: list[StableId] = Field(min_length=1, max_length=16)
    neutral_distractor: bool
    controller_visible: Literal[True] = True
    injected_exactly_once: Literal[True] = True
    injected_before_turn_action: Literal[True] = True
    stimulus_hash: Sha256

    @field_validator("payload_cn")
    @classmethod
    def _require_chinese_payload(cls, value: str) -> str:
        return _require_chinese(value, label="public stimulus")

    @field_validator("public_fact_ids")
    @classmethod
    def _require_unique_facts(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("public stimulus fact IDs must be unique")
        return value

    @model_validator(mode="after")
    def _validate_hash(self) -> AdaptiveLoopBenchmarkPublicStimulus:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"stimulus_hash"}))
        if self.stimulus_hash != expected:
            raise ValueError("public stimulus hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveLoopBenchmarkPublicStimulus:
        payload = {
            "schema_version": "adaptive-loop-public-stimulus-v3",
            "controller_visible": True,
            "injected_exactly_once": True,
            "injected_before_turn_action": True,
            **values,
        }
        payload["stimulus_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)


class AdaptiveLoopBenchmarkPublicScenarioContent(KernelContract):
    schema_version: Literal["adaptive-loop-public-scenario-v3"] = "adaptive-loop-public-scenario-v3"
    scenario_id: StableId
    challenge_kind: AdaptiveLoopChallengeKind
    instance_index: int = Field(ge=1, le=_SCENARIOS_PER_CHALLENGE)
    independence_key: StableId
    independence_basis_cn: str = Field(min_length=20, max_length=2_000)
    objective_cn: str = Field(min_length=20, max_length=2_000)
    scope_cn: str = Field(min_length=20, max_length=2_000)
    stimuli: list[AdaptiveLoopBenchmarkPublicStimulus] = Field(
        min_length=_STIMULUS_TURN_COUNT,
        max_length=_STIMULUS_TURN_COUNT,
    )
    non_sovereign_recent_window_turns: Literal[8] = 8
    terminal_turn_index: Literal[12] = 12
    every_turn_injection_content_addressed: Literal[True] = True
    objective_contains_hypothesis: Literal[False] = False
    objective_contains_method: Literal[False] = False
    objective_contains_research_plan: Literal[False] = False
    scope_contains_hypothesis: Literal[False] = False
    scope_contains_method: Literal[False] = False
    scope_contains_research_plan: Literal[False] = False
    contains_required_operator_sequence: Literal[False] = False
    content_is_seed_repeat: Literal[False] = False

    @field_validator("independence_basis_cn", "objective_cn", "scope_cn")
    @classmethod
    def _require_chinese_text(cls, value: str) -> str:
        return _require_chinese(value, label="scenario text")

    @field_validator("objective_cn", "scope_cn")
    @classmethod
    def _reject_scientific_answer_in_seed(cls, value: str) -> str:
        folded = value.casefold()
        for term in _PROHIBITED_SEED_TERMS:
            if term.casefold() in folded:
                raise ValueError(f"scenario objective/scope contains prohibited seed term: {term}")
        return value

    @model_validator(mode="after")
    def _validate_turns(self) -> AdaptiveLoopBenchmarkPublicScenarioContent:
        if [item.turn_index for item in self.stimuli] != list(range(1, _STIMULUS_TURN_COUNT + 1)):
            raise ValueError("public stimuli must be frozen in turns 1 through 12")
        stimulus_ids = [item.stimulus_id for item in self.stimuli]
        if len(stimulus_ids) != len(set(stimulus_ids)):
            raise ValueError("public stimulus IDs must be unique within a scenario")
        fact_ids = [fact_id for item in self.stimuli for fact_id in item.public_fact_ids]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("public fact IDs must be unique within a scenario")
        if self.stimuli[-1].kind != AdaptiveLoopBenchmarkStimulusKind.TERMINAL_REQUEST:
            raise ValueError("turn twelve must be the public terminal request")
        if any(
            item.kind == AdaptiveLoopBenchmarkStimulusKind.TERMINAL_REQUEST
            for item in self.stimuli[:-1]
        ):
            raise ValueError("terminal request may occur only at turn twelve")
        neutral_turns = [item.turn_index for item in self.stimuli if item.neutral_distractor]
        if neutral_turns != list(_NEUTRAL_DISTRACTOR_TURNS):
            raise ValueError("turns four through eleven must be neutral distractors")
        if self.terminal_turn_index - 1 <= self.non_sovereign_recent_window_turns:
            raise ValueError("turn-one evidence remains inside the non-sovereign recent window")
        return self


class AdaptiveLoopBenchmarkPublicScenario(AdaptiveLoopBenchmarkPublicScenarioContent):
    public_scenario_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> AdaptiveLoopBenchmarkPublicScenario:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"public_scenario_hash"}))
        if self.public_scenario_hash != expected:
            raise ValueError("public scenario hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveLoopBenchmarkPublicScenario:
        content = AdaptiveLoopBenchmarkPublicScenarioContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, public_scenario_hash=canonical_sha256(payload))


class AdaptiveLoopBenchmarkMachineOracleContent(KernelContract):
    schema_version: Literal["adaptive-loop-machine-oracle-v3"] = "adaptive-loop-machine-oracle-v3"
    scenario_id: StableId
    public_scenario_hash: Sha256
    expected_terminal_state: AdaptiveLoopBenchmarkTerminalState
    required_public_fact_ids: list[StableId] = Field(min_length=1, max_length=16)
    forbidden_as_current_fact_ids: list[StableId] = Field(
        default_factory=list,
        max_length=16,
    )
    minimum_distinct_public_fact_references: int = Field(ge=1, le=16)
    required_terminal_tokens: list[str] = Field(min_length=1, max_length=16)
    forbidden_terminal_tokens: list[str] = Field(
        default_factory=list,
        max_length=16,
    )
    supersession_trace_required: bool
    strategy_change_after_negative_feedback_required: bool
    contamination_quarantine_required: bool
    latest_scoring_relevant_turn_index: Literal[3] = 3
    terminal_turn_index: Literal[12] = 12
    non_sovereign_recent_window_turns: Literal[8] = 8
    scoring_evidence_outside_non_sovereign_recent_window: Literal[True] = True
    nonzero_auditable_action_required: Literal[True] = True
    all_conditions_required: Literal[True] = True
    machine_scored: Literal[True] = True
    controller_visible: Literal[False] = False

    @field_validator(
        "required_public_fact_ids",
        "forbidden_as_current_fact_ids",
        "required_terminal_tokens",
        "forbidden_terminal_tokens",
    )
    @classmethod
    def _require_unique_values(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("oracle lists cannot contain empty values")
        if len(normalized) != len(set(normalized)):
            raise ValueError("oracle lists must contain unique values")
        return normalized

    @model_validator(mode="after")
    def _validate_recent_window_expiry(
        self,
    ) -> AdaptiveLoopBenchmarkMachineOracleContent:
        if (
            self.terminal_turn_index - self.latest_scoring_relevant_turn_index
            <= self.non_sovereign_recent_window_turns
        ):
            raise ValueError("scoring-relevant evidence remains in the non-sovereign recent window")
        return self


class AdaptiveLoopBenchmarkMachineOracle(AdaptiveLoopBenchmarkMachineOracleContent):
    oracle_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> AdaptiveLoopBenchmarkMachineOracle:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"oracle_hash"}))
        if self.oracle_hash != expected:
            raise ValueError("machine oracle hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveLoopBenchmarkMachineOracle:
        content = AdaptiveLoopBenchmarkMachineOracleContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, oracle_hash=canonical_sha256(payload))


class AdaptiveLoopBenchmarkHiddenOracleManifestContent(KernelContract):
    schema_version: Literal["adaptive-loop-hidden-oracle-manifest-v3"] = (
        "adaptive-loop-hidden-oracle-manifest-v3"
    )
    parent_v1_protocol_hash: Sha256
    design_audit_hash: Sha256
    public_scenario_panel_hash: Sha256
    oracles: list[AdaptiveLoopBenchmarkMachineOracle] = Field(
        min_length=_CONFIRMATORY_SCENARIO_COUNT,
        max_length=_CONFIRMATORY_SCENARIO_COUNT,
    )
    runner_and_post_seal_evaluator_only: Literal[True] = True
    controller_access_allowed: Literal[False] = False
    blinded_evaluator_access_before_reveal_allowed: Literal[False] = False
    reveal_allowed_only_after_all_cell_outputs_sealed: Literal[True] = True
    reveal_barrier_initially_closed: Literal[True] = True
    result_fields_absent: Literal[True] = True
    scientific_superiority_established: Literal[False] = False
    innovation_verified: Literal[False] = False
    publication_authorized: Literal[False] = False

    @model_validator(mode="after")
    def _validate_oracle_panel(
        self,
    ) -> AdaptiveLoopBenchmarkHiddenOracleManifestContent:
        scenario_ids = [item.scenario_id for item in self.oracles]
        public_hashes = [item.public_scenario_hash for item in self.oracles]
        oracle_hashes = [item.oracle_hash for item in self.oracles]
        for label, values in (
            ("oracle scenario ID", scenario_ids),
            ("oracle public hash", public_hashes),
            ("oracle hash", oracle_hashes),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} values must be unique")
        return self


class AdaptiveLoopBenchmarkHiddenOracleManifest(AdaptiveLoopBenchmarkHiddenOracleManifestContent):
    hidden_oracle_manifest_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> AdaptiveLoopBenchmarkHiddenOracleManifest:
        expected = canonical_sha256(
            self.model_dump(mode="json", exclude={"hidden_oracle_manifest_hash"})
        )
        if self.hidden_oracle_manifest_hash != expected:
            raise ValueError("hidden oracle manifest hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveLoopBenchmarkHiddenOracleManifest:
        content = AdaptiveLoopBenchmarkHiddenOracleManifestContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(
            **payload,
            hidden_oracle_manifest_hash=canonical_sha256(payload),
        )


class AdaptiveLoopBenchmarkBlindedCell(KernelContract):
    blinded_cell_id: StableId
    scenario_id: StableId
    challenge_kind: AdaptiveLoopChallengeKind
    public_scenario_hash: Sha256
    run_position: int = Field(ge=1, le=4)
    model_draw_ordinal: Literal[1] = 1


class AdaptiveLoopBenchmarkBlindedCellManifestContent(KernelContract):
    schema_version: Literal["adaptive-loop-blinded-cell-manifest-v3"] = (
        "adaptive-loop-blinded-cell-manifest-v3"
    )
    parent_v1_protocol_hash: Sha256
    design_audit_hash: Sha256
    public_scenario_panel_hash: Sha256
    cells: list[AdaptiveLoopBenchmarkBlindedCell] = Field(
        min_length=_CONFIRMATORY_CELL_COUNT,
        max_length=_CONFIRMATORY_CELL_COUNT,
    )
    evaluator_blinded: Literal[True] = True
    assignment_labels_absent: Literal[True] = True
    private_scoring_rules_absent: Literal[True] = True
    result_fields_absent: Literal[True] = True
    scientific_superiority_established: Literal[False] = False
    innovation_verified: Literal[False] = False
    publication_authorized: Literal[False] = False

    @model_validator(mode="after")
    def _validate_blinded_cells(
        self,
    ) -> AdaptiveLoopBenchmarkBlindedCellManifestContent:
        cell_ids = [item.blinded_cell_id for item in self.cells]
        if len(cell_ids) != len(set(cell_ids)):
            raise ValueError("blinded cell IDs must be unique")
        by_scenario: dict[str, list[AdaptiveLoopBenchmarkBlindedCell]] = defaultdict(list)
        for cell in self.cells:
            by_scenario[cell.scenario_id].append(cell)
        if len(by_scenario) != _CONFIRMATORY_SCENARIO_COUNT:
            raise ValueError("blinded manifest must cover 60 independent scenarios")
        for cells in by_scenario.values():
            if sorted(item.run_position for item in cells) != [1, 2, 3, 4]:
                raise ValueError("each blinded scenario must have four run positions")
            if len({item.public_scenario_hash for item in cells}) != 1:
                raise ValueError("blinded scenario public hashes disagree")
            if len({item.challenge_kind for item in cells}) != 1:
                raise ValueError("blinded scenario challenge kinds disagree")
        return self


class AdaptiveLoopBenchmarkBlindedCellManifest(AdaptiveLoopBenchmarkBlindedCellManifestContent):
    blinded_manifest_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> AdaptiveLoopBenchmarkBlindedCellManifest:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"blinded_manifest_hash"}))
        if self.blinded_manifest_hash != expected:
            raise ValueError("blinded cell manifest hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveLoopBenchmarkBlindedCellManifest:
        content = AdaptiveLoopBenchmarkBlindedCellManifestContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, blinded_manifest_hash=canonical_sha256(payload))


class AdaptiveLoopBenchmarkRunSequence(KernelContract):
    sequence_id: StableId
    ordered_arms: list[AdaptiveLoopBenchmarkArm] = Field(min_length=4, max_length=4)

    @field_validator("ordered_arms")
    @classmethod
    def _require_each_arm_once(
        cls,
        value: list[AdaptiveLoopBenchmarkArm],
    ) -> list[AdaptiveLoopBenchmarkArm]:
        if set(value) != set(AdaptiveLoopBenchmarkArm):
            raise ValueError("each run sequence must contain every arm exactly once")
        return value


class AdaptiveLoopBenchmarkRunnerAssignment(KernelContract):
    blinded_cell_id: StableId
    scenario_id: StableId
    challenge_kind: AdaptiveLoopChallengeKind
    sequence_id: StableId
    run_position: int = Field(ge=1, le=4)
    arm: AdaptiveLoopBenchmarkArm
    model_draw_ordinal: Literal[1] = 1


class AdaptiveLoopBenchmarkRunnerAssignmentManifestContent(KernelContract):
    schema_version: Literal["adaptive-loop-runner-assignment-manifest-v3"] = (
        "adaptive-loop-runner-assignment-manifest-v3"
    )
    parent_v1_protocol_hash: Sha256
    design_audit_hash: Sha256
    blinded_manifest_hash: Sha256
    private_scoring_manifest_hash: Sha256
    randomization_seed: int = Field(ge=0)
    randomization_algorithm: Literal["sha256_seeded_balanced_latin_square_v1"] = (
        "sha256_seeded_balanced_latin_square_v1"
    )
    sequences: list[AdaptiveLoopBenchmarkRunSequence] = Field(
        min_length=4,
        max_length=4,
    )
    assignments: list[AdaptiveLoopBenchmarkRunnerAssignment] = Field(
        min_length=_CONFIRMATORY_CELL_COUNT,
        max_length=_CONFIRMATORY_CELL_COUNT,
    )
    runner_only: Literal[True] = True
    controller_access_allowed: Literal[False] = False
    blinded_evaluator_access_allowed: Literal[False] = False
    result_fields_absent: Literal[True] = True
    scientific_superiority_established: Literal[False] = False
    innovation_verified: Literal[False] = False
    publication_authorized: Literal[False] = False

    @model_validator(mode="after")
    def _validate_randomization(
        self,
    ) -> AdaptiveLoopBenchmarkRunnerAssignmentManifestContent:
        expected_sequences = _run_sequences()
        if self.sequences != expected_sequences:
            raise ValueError("runner sequence definitions changed")
        cell_ids = [item.blinded_cell_id for item in self.assignments]
        if len(cell_ids) != len(set(cell_ids)):
            raise ValueError("runner assignment cell IDs must be unique")
        by_scenario: dict[str, list[AdaptiveLoopBenchmarkRunnerAssignment]] = defaultdict(list)
        for item in self.assignments:
            by_scenario[item.scenario_id].append(item)
        if len(by_scenario) != _CONFIRMATORY_SCENARIO_COUNT:
            raise ValueError("runner assignments must cover 60 scenarios")
        sequence_map = {item.sequence_id: item.ordered_arms for item in self.sequences}
        for items in by_scenario.values():
            ordered = sorted(items, key=lambda item: item.run_position)
            if [item.run_position for item in ordered] != [1, 2, 3, 4]:
                raise ValueError("each scenario needs all four run positions")
            if len({item.arm for item in ordered}) != 4:
                raise ValueError("each scenario needs all four comparison arms")
            if len({item.sequence_id for item in ordered}) != 1:
                raise ValueError("one scenario cannot mix run sequences")
            sequence_id = ordered[0].sequence_id
            if sequence_id not in sequence_map:
                raise ValueError("runner assignment uses an unknown sequence")
            if [item.arm for item in ordered] != sequence_map[sequence_id]:
                raise ValueError("runner assignment does not match its sequence")
        for kind in AdaptiveLoopChallengeKind:
            kind_items = [item for item in self.assignments if item.challenge_kind == kind]
            kind_scenarios = {item.scenario_id for item in kind_items}
            if len(kind_scenarios) != _SCENARIOS_PER_CHALLENGE:
                raise ValueError("each challenge kind needs 12 independent scenarios")
            sequence_counts = Counter(
                by_scenario[scenario_id][0].sequence_id for scenario_id in kind_scenarios
            )
            if sequence_counts != Counter({sequence.sequence_id: 3 for sequence in self.sequences}):
                raise ValueError("each balanced sequence must occur three times per kind")
            for arm in AdaptiveLoopBenchmarkArm:
                for position in range(1, 5):
                    count = sum(
                        item.arm == arm and item.run_position == position for item in kind_items
                    )
                    if count != 3:
                        raise ValueError(
                            "each challenge/arm/run-position cell must occur three times"
                        )
        return self


class AdaptiveLoopBenchmarkRunnerAssignmentManifest(
    AdaptiveLoopBenchmarkRunnerAssignmentManifestContent
):
    runner_assignment_manifest_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> AdaptiveLoopBenchmarkRunnerAssignmentManifest:
        expected = canonical_sha256(
            self.model_dump(
                mode="json",
                exclude={"runner_assignment_manifest_hash"},
            )
        )
        if self.runner_assignment_manifest_hash != expected:
            raise ValueError("runner assignment manifest hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        **values: Any,
    ) -> AdaptiveLoopBenchmarkRunnerAssignmentManifest:
        content = AdaptiveLoopBenchmarkRunnerAssignmentManifestContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(
            **payload,
            runner_assignment_manifest_hash=canonical_sha256(payload),
        )


class AdaptiveLoopBenchmarkAnalysisContractContent(KernelContract):
    schema_version: Literal["adaptive-loop-analysis-contract-v3"] = (
        "adaptive-loop-analysis-contract-v3"
    )
    analysis_unit: Literal["independent_challenge_instance"] = "independent_challenge_instance"
    primary_endpoint: Literal["objectively_confirmed_terminal_success"] = (
        "objectively_confirmed_terminal_success"
    )
    primary_contrast: Literal["adaptive_sovereign_minus_adaptive_derived_only"] = (
        "adaptive_sovereign_minus_adaptive_derived_only"
    )
    a4_arm: Literal[AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN] = (
        AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN
    )
    a3_arm: Literal[AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY] = (
        AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY
    )
    primary_effect_measure: Literal["paired_risk_difference"] = "paired_risk_difference"
    primary_test: Literal["two_sided_exact_mcnemar"] = "two_sided_exact_mcnemar"
    primary_alpha: float = Field(default=0.05, gt=0.0, lt=1.0)
    sesoi_risk_difference: float = Field(default=0.25, gt=0.0, lt=1.0)
    primary_multiplicity_adjustment: Literal["none_single_preregistered_primary"] = (
        "none_single_preregistered_primary"
    )
    secondary_multiplicity_adjustment: Literal["holm_step_down"] = "holm_step_down"
    holm_applies_to_primary: Literal[False] = False
    holm_applies_only_to_secondary: Literal[True] = True
    all_preregistered_primary_pairs_included: Literal[True] = True
    runtime_failure_terminal_success: Literal[False] = False
    missing_artifact_terminal_success: Literal[False] = False
    zero_auditable_action_terminal_success: Literal[False] = False
    failed_missing_or_zero_action_pairs_dropped: Literal[False] = False
    failed_missing_or_zero_action_score: Literal[0] = 0
    outcome_imputation_allowed: Literal[False] = False
    parent_v1_cells_are_engineering_pilot_only: Literal[True] = True
    parent_v1_metrics_are_secondary_descriptive_only: Literal[True] = True
    parent_v1_observations_enter_confirmatory_test: Literal[False] = False
    confirmatory_scenario_count: Literal[60] = 60
    confirmatory_cell_count: Literal[240] = 240
    single_model_draw_per_scenario_arm: Literal[True] = True
    terminal_after_non_sovereign_recent_window_expiry: Literal[True] = True
    private_scoring_revealed_only_after_all_cell_outputs_sealed: Literal[True] = True
    protocol_change_after_observation_requires_new_registration: Literal[True] = True
    confirmatory_superiority_claim_allowed: Literal[False] = False
    innovation_verified: Literal[False] = False
    publication_authorized: Literal[False] = False

    @model_validator(mode="after")
    def _validate_frozen_thresholds(
        self,
    ) -> AdaptiveLoopBenchmarkAnalysisContractContent:
        if self.primary_alpha != 0.05:
            raise ValueError("confirmatory primary alpha changed")
        if self.sesoi_risk_difference != 0.25:
            raise ValueError("confirmatory SESOI risk difference changed")
        return self


class AdaptiveLoopBenchmarkAnalysisContract(AdaptiveLoopBenchmarkAnalysisContractContent):
    analysis_contract_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> AdaptiveLoopBenchmarkAnalysisContract:
        expected = canonical_sha256(
            self.model_dump(mode="json", exclude={"analysis_contract_hash"})
        )
        if self.analysis_contract_hash != expected:
            raise ValueError("adaptive benchmark analysis contract hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveLoopBenchmarkAnalysisContract:
        content = AdaptiveLoopBenchmarkAnalysisContractContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, analysis_contract_hash=canonical_sha256(payload))


class AdaptiveLoopBenchmarkExecutionProtocolContent(KernelContract):
    schema_version: Literal["adaptive-loop-benchmark-execution-protocol-v3"] = (
        "adaptive-loop-benchmark-execution-protocol-v3"
    )
    execution_protocol_id: StableId
    parent_v1_protocol_hash: Sha256
    design_audit_hash: Sha256
    public_scenario_panel_hash: Sha256
    private_scoring_manifest_hash: Sha256
    blinded_manifest_hash: Sha256
    runner_assignment_manifest_hash: Sha256
    challenge_kind_count: Literal[5] = 5
    independent_scenarios_per_challenge: Literal[12] = 12
    independent_scenario_count: Literal[60] = 60
    comparison_arm_count: Literal[4] = 4
    model_draws_per_scenario_arm: Literal[1] = 1
    confirmatory_cell_count: Literal[240] = 240
    public_scenarios: list[AdaptiveLoopBenchmarkPublicScenario] = Field(
        min_length=_CONFIRMATORY_SCENARIO_COUNT,
        max_length=_CONFIRMATORY_SCENARIO_COUNT,
    )
    analysis: AdaptiveLoopBenchmarkAnalysisContract
    same_scenario_forms_four_arm_block: Literal[True] = True
    same_model_configuration_across_cells: Literal[True] = True
    same_tool_replay_within_scenario: Literal[True] = True
    public_stimuli_released_turn_by_turn: Literal[True] = True
    public_stimulus_turn_count: Literal[12] = 12
    non_sovereign_recent_window_turns: Literal[8] = 8
    private_scoring_data_absent: Literal[True] = True
    controller_and_blinded_evaluator_schema_public_only: Literal[True] = True
    runner_assignment_kept_separate: Literal[True] = True
    result_blind_when_frozen: Literal[True] = True
    execution_started: Literal[False] = False
    result_cell_count: Literal[0] = 0
    scientific_superiority_established: Literal[False] = False
    innovation_verified: Literal[False] = False
    publication_authorized: Literal[False] = False

    @model_validator(mode="after")
    def _validate_scenario_panel(
        self,
    ) -> AdaptiveLoopBenchmarkExecutionProtocolContent:
        scenario_ids = [item.scenario_id for item in self.public_scenarios]
        public_hashes = [item.public_scenario_hash for item in self.public_scenarios]
        independence_keys = [item.independence_key for item in self.public_scenarios]
        for label, values in (
            ("scenario ID", scenario_ids),
            ("public scenario hash", public_hashes),
            ("independence key", independence_keys),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} values must be unique")
        expected_order = [
            (kind, index)
            for kind in AdaptiveLoopChallengeKind
            for index in range(1, _SCENARIOS_PER_CHALLENGE + 1)
        ]
        actual_order = [
            (item.challenge_kind, item.instance_index) for item in self.public_scenarios
        ]
        if actual_order != expected_order:
            raise ValueError("scenario panel order or stratum coverage changed")
        expected_panel_hash = canonical_sha256(
            [item.model_dump(mode="json") for item in self.public_scenarios]
        )
        if self.public_scenario_panel_hash != expected_panel_hash:
            raise ValueError("public scenario panel hash mismatch")
        return self


class AdaptiveLoopBenchmarkExecutionProtocol(AdaptiveLoopBenchmarkExecutionProtocolContent):
    execution_protocol_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> AdaptiveLoopBenchmarkExecutionProtocol:
        expected = canonical_sha256(
            self.model_dump(mode="json", exclude={"execution_protocol_hash"})
        )
        if self.execution_protocol_hash != expected:
            raise ValueError("adaptive benchmark execution protocol hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveLoopBenchmarkExecutionProtocol:
        content = AdaptiveLoopBenchmarkExecutionProtocolContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, execution_protocol_hash=canonical_sha256(payload))


class AdaptiveLoopBenchmarkExecutionBundle(KernelContract):
    protocol: AdaptiveLoopBenchmarkExecutionProtocol
    blinded_cells: AdaptiveLoopBenchmarkBlindedCellManifest
    runner_assignments: AdaptiveLoopBenchmarkRunnerAssignmentManifest
    runner_only_scoring: AdaptiveLoopBenchmarkHiddenOracleManifest

    @model_validator(mode="after")
    def _validate_cross_artifact_bindings(
        self,
    ) -> AdaptiveLoopBenchmarkExecutionBundle:
        protocol = self.protocol
        blinded = self.blinded_cells
        runner = self.runner_assignments
        scoring = self.runner_only_scoring
        if protocol.blinded_manifest_hash != blinded.blinded_manifest_hash:
            raise ValueError("execution protocol does not bind blinded manifest")
        if protocol.runner_assignment_manifest_hash != runner.runner_assignment_manifest_hash:
            raise ValueError("execution protocol does not bind runner assignments")
        if protocol.private_scoring_manifest_hash != scoring.hidden_oracle_manifest_hash:
            raise ValueError("execution protocol does not bind private scoring")
        if runner.private_scoring_manifest_hash != scoring.hidden_oracle_manifest_hash:
            raise ValueError("runner assignment does not bind private scoring")
        for artifact in (blinded, runner, scoring):
            if artifact.parent_v1_protocol_hash != protocol.parent_v1_protocol_hash:
                raise ValueError("execution artifact parent protocol hash mismatch")
            if artifact.design_audit_hash != protocol.design_audit_hash:
                raise ValueError("execution artifact design audit hash mismatch")
        if scoring.public_scenario_panel_hash != protocol.public_scenario_panel_hash:
            raise ValueError("private scoring does not bind public scenario panel")
        if runner.blinded_manifest_hash != blinded.blinded_manifest_hash:
            raise ValueError("runner assignment does not bind blinded manifest")
        protocol_public = {
            item.scenario_id: (
                item.challenge_kind,
                item.public_scenario_hash,
            )
            for item in protocol.public_scenarios
        }
        for cell in blinded.cells:
            expected = protocol_public.get(cell.scenario_id)
            if expected != (cell.challenge_kind, cell.public_scenario_hash):
                raise ValueError("blinded cell does not bind the public scenario")
        blinded_ids = {item.blinded_cell_id for item in blinded.cells}
        runner_ids = {item.blinded_cell_id for item in runner.assignments}
        if blinded_ids != runner_ids:
            raise ValueError("blinded and runner cell sets disagree")
        public_by_id = {item.scenario_id: item for item in protocol.public_scenarios}
        if set(public_by_id) != {item.scenario_id for item in scoring.oracles}:
            raise ValueError("public and private scoring scenario sets disagree")
        expected_states = _expected_terminal_states()
        for oracle in scoring.oracles:
            public = public_by_id[oracle.scenario_id]
            if oracle.public_scenario_hash != public.public_scenario_hash:
                raise ValueError("private scoring public-scenario binding mismatch")
            _validate_oracle_against_public_scenario(public=public, oracle=oracle)
            kind = public.challenge_kind
            if oracle.expected_terminal_state != expected_states[kind]:
                raise ValueError("private terminal state changed by challenge kind")
            if oracle.supersession_trace_required != (
                kind == AdaptiveLoopChallengeKind.STALE_SUPERSESSION
            ):
                raise ValueError("private supersession flag changed")
            if oracle.strategy_change_after_negative_feedback_required != (
                kind == AdaptiveLoopChallengeKind.EMPTY_TOOL_RESULT
            ):
                raise ValueError("private negative-feedback flag changed")
            if oracle.contamination_quarantine_required != (
                kind == AdaptiveLoopChallengeKind.MEMORY_POLLUTION
            ):
                raise ValueError("private contamination flag changed")
        return self


@dataclass(frozen=True)
class _ScenarioFixture:
    independence_key: str
    context_cn: str
    turn1_cn: str
    turn2_cn: str
    turn3_cn: str
    required_token: str
    forbidden_token: str | None


def build_adaptive_loop_benchmark_execution_bundle(
    parent_protocol: AdaptiveLoopBenchmarkProtocol | None = None,
    design_audit: AdaptiveLoopBenchmarkDesignAudit | None = None,
    *,
    randomization_seed: int,
) -> AdaptiveLoopBenchmarkExecutionBundle:
    """Build the deterministic result-blind v3 protocol and split manifests.

    ``randomization_seed`` is deliberately required instead of defaulted.  The
    caller must keep it with the runner-only assignment artifact; it is absent
    from the blinded manifest so an evaluator cannot reconstruct cell labels.
    """

    parent = parent_protocol or build_adaptive_loop_benchmark_protocol()
    audit = design_audit or audit_adaptive_loop_benchmark_design(parent)
    _validate_parent_design(parent, audit)
    public_scenarios, oracles = _build_public_scenarios_and_oracles()
    public_scenario_panel_hash = canonical_sha256(
        [item.model_dump(mode="json") for item in public_scenarios]
    )
    scoring = AdaptiveLoopBenchmarkHiddenOracleManifest.create(
        parent_v1_protocol_hash=parent.protocol_hash,
        design_audit_hash=audit.design_audit_hash,
        public_scenario_panel_hash=public_scenario_panel_hash,
        oracles=oracles,
    )
    blinded, runner = _build_cell_manifests(
        public_scenarios=public_scenarios,
        parent_protocol_hash=parent.protocol_hash,
        design_audit_hash=audit.design_audit_hash,
        public_scenario_panel_hash=public_scenario_panel_hash,
        private_scoring_manifest_hash=scoring.hidden_oracle_manifest_hash,
        randomization_seed=randomization_seed,
    )
    analysis = AdaptiveLoopBenchmarkAnalysisContract.create()
    protocol = AdaptiveLoopBenchmarkExecutionProtocol.create(
        execution_protocol_id="adaptive-sovereign-four-arm-confirmatory-v3",
        parent_v1_protocol_hash=parent.protocol_hash,
        design_audit_hash=audit.design_audit_hash,
        public_scenario_panel_hash=public_scenario_panel_hash,
        private_scoring_manifest_hash=scoring.hidden_oracle_manifest_hash,
        blinded_manifest_hash=blinded.blinded_manifest_hash,
        runner_assignment_manifest_hash=runner.runner_assignment_manifest_hash,
        public_scenarios=public_scenarios,
        analysis=analysis,
    )
    return AdaptiveLoopBenchmarkExecutionBundle(
        protocol=protocol,
        blinded_cells=blinded,
        runner_assignments=runner,
        runner_only_scoring=scoring,
    )


def build_adaptive_loop_benchmark_execution_protocol(
    parent_protocol: AdaptiveLoopBenchmarkProtocol | None = None,
    design_audit: AdaptiveLoopBenchmarkDesignAudit | None = None,
    *,
    randomization_seed: int,
) -> AdaptiveLoopBenchmarkExecutionProtocol:
    """Return only the public frozen v3 protocol; use the bundle internally."""

    return build_adaptive_loop_benchmark_execution_bundle(
        parent_protocol,
        design_audit,
        randomization_seed=randomization_seed,
    ).protocol


def write_adaptive_loop_benchmark_execution_protocol(
    output_dir: Path | str,
    parent_protocol: AdaptiveLoopBenchmarkProtocol | None = None,
    design_audit: AdaptiveLoopBenchmarkDesignAudit | None = None,
    *,
    randomization_seed: int,
) -> AdaptiveLoopBenchmarkExecutionBundle:
    """Write immutable public artifacts and separately sealed runner artifacts."""

    bundle = build_adaptive_loop_benchmark_execution_bundle(
        parent_protocol,
        design_audit,
        randomization_seed=randomization_seed,
    )
    root = Path(output_dir)
    _write_once(
        root / "adaptive-loop-benchmark-execution-protocol-v3.json",
        (canonical_json(bundle.protocol) + "\n").encode("utf-8"),
    )
    _write_once(
        root / "adaptive-loop-benchmark-blinded-cell-manifest-v3.json",
        (canonical_json(bundle.blinded_cells) + "\n").encode("utf-8"),
    )
    _write_once(
        root / "runner-only" / "adaptive-loop-benchmark-runner-assignment-manifest-v3.json",
        (canonical_json(bundle.runner_assignments) + "\n").encode("utf-8"),
    )
    _write_once(
        root / "runner-only" / "adaptive-loop-benchmark-hidden-oracle-manifest-v3.json",
        (canonical_json(bundle.runner_only_scoring) + "\n").encode("utf-8"),
    )
    return bundle


def _validate_parent_design(
    parent: AdaptiveLoopBenchmarkProtocol,
    audit: AdaptiveLoopBenchmarkDesignAudit,
) -> None:
    if audit.protocol_hash != parent.protocol_hash:
        raise AdaptiveLoopBenchmarkExecutionProtocolError(
            "v2 design audit does not bind the supplied parent v1 protocol"
        )
    if not parent.no_result_observed_when_frozen:
        raise AdaptiveLoopBenchmarkExecutionProtocolError(
            "v2 execution protocol requires a result-blind parent"
        )
    if audit.recommended_confirmatory_independent_scenario_count != 60:
        raise AdaptiveLoopBenchmarkExecutionProtocolError(
            "v2 design audit no longer recommends 60 independent scenarios"
        )
    if audit.recommended_confirmatory_cell_count != 240:
        raise AdaptiveLoopBenchmarkExecutionProtocolError(
            "v2 design audit no longer recommends 240 confirmatory cells"
        )
    if audit.confirmatory_superiority_claim_allowed:
        raise AdaptiveLoopBenchmarkExecutionProtocolError(
            "result-blind design audit cannot authorize superiority"
        )


def _build_public_scenarios_and_oracles() -> (
    tuple[
        list[AdaptiveLoopBenchmarkPublicScenario],
        list[AdaptiveLoopBenchmarkMachineOracle],
    ]
):
    fixtures_by_kind = _fixtures_by_kind()
    public_scenarios: list[AdaptiveLoopBenchmarkPublicScenario] = []
    oracles: list[AdaptiveLoopBenchmarkMachineOracle] = []
    for kind in AdaptiveLoopChallengeKind:
        fixtures = fixtures_by_kind[kind]
        if len(fixtures) != _SCENARIOS_PER_CHALLENGE:
            raise AdaptiveLoopBenchmarkExecutionProtocolError(
                f"challenge {kind.value} does not have 12 independent fixtures"
            )
        for index, fixture in enumerate(fixtures, start=1):
            public, oracle = _build_scenario(
                kind=kind,
                instance_index=index,
                fixture=fixture,
            )
            public_scenarios.append(public)
            oracles.append(oracle)
    return public_scenarios, oracles


def _build_scenario(
    *,
    kind: AdaptiveLoopChallengeKind,
    instance_index: int,
    fixture: _ScenarioFixture,
) -> tuple[AdaptiveLoopBenchmarkPublicScenario, AdaptiveLoopBenchmarkMachineOracle]:
    scenario_id = f"scn-{kind.value.replace('_', '-')}-{instance_index:02d}"
    fact_ids = [f"{scenario_id}.fact-{index}" for index in range(1, _STIMULUS_TURN_COUNT + 1)]
    stimulus_kinds = _stimulus_kinds()[kind]
    terminal_payload = (
        f"终态请求：请在{fixture.context_cn}中形成可审计的当前状态。可以继续查验、"
        "修订、隔离或停止，但必须引用本场景已经公开的记录编号，不得获得隐藏判定。"
    )
    payloads = [
        fixture.turn1_cn,
        fixture.turn2_cn,
        fixture.turn3_cn,
        *_neutral_distractor_payloads(scenario_id=scenario_id),
        terminal_payload,
    ]
    stimuli = [
        AdaptiveLoopBenchmarkPublicStimulus.create(
            stimulus_id=f"{scenario_id}.turn-{turn_index}",
            turn_index=turn_index,
            kind=stimulus_kinds[turn_index - 1],
            payload_cn=payload,
            public_fact_ids=[fact_ids[turn_index - 1]],
            neutral_distractor=(turn_index in _NEUTRAL_DISTRACTOR_TURNS),
        )
        for turn_index, payload in enumerate(payloads, start=1)
    ]
    public = AdaptiveLoopBenchmarkPublicScenario.create(
        scenario_id=scenario_id,
        challenge_kind=kind,
        instance_index=instance_index,
        independence_key=f"{kind.value}:{fixture.independence_key}",
        independence_basis_cn=(
            f"该实例围绕{fixture.context_cn}的独立记录、实体和值展开；内容不是由随机"
            "种子对另一个场景重复采样，也不与本面板其他实例共享判定事实。"
        ),
        objective_cn=(
            f"在{fixture.context_cn}的材料逐轮公开后，识别当前可核验状态并给出可追溯"
            "终态，同时保留不确定与冲突记录。"
        ),
        scope_cn=(
            "只允许使用本场景逐轮公开的记录与既定工具回执；不得访问网络、隐藏判定"
            "或其他场景内容，也不得由人工在启动后指定科研结论。"
        ),
        stimuli=stimuli,
    )
    required_fact_ids, forbidden_fact_ids = _oracle_fact_ids(kind, fact_ids)
    oracle = AdaptiveLoopBenchmarkMachineOracle.create(
        scenario_id=scenario_id,
        public_scenario_hash=public.public_scenario_hash,
        expected_terminal_state=_expected_terminal_states()[kind],
        required_public_fact_ids=required_fact_ids,
        forbidden_as_current_fact_ids=forbidden_fact_ids,
        minimum_distinct_public_fact_references=2,
        required_terminal_tokens=[fixture.required_token],
        forbidden_terminal_tokens=([fixture.forbidden_token] if fixture.forbidden_token else []),
        supersession_trace_required=(kind == AdaptiveLoopChallengeKind.STALE_SUPERSESSION),
        strategy_change_after_negative_feedback_required=(
            kind == AdaptiveLoopChallengeKind.EMPTY_TOOL_RESULT
        ),
        contamination_quarantine_required=(kind == AdaptiveLoopChallengeKind.MEMORY_POLLUTION),
    )
    return public, oracle


def _build_cell_manifests(
    *,
    public_scenarios: list[AdaptiveLoopBenchmarkPublicScenario],
    parent_protocol_hash: str,
    design_audit_hash: str,
    public_scenario_panel_hash: str,
    private_scoring_manifest_hash: str,
    randomization_seed: int,
) -> tuple[
    AdaptiveLoopBenchmarkBlindedCellManifest,
    AdaptiveLoopBenchmarkRunnerAssignmentManifest,
]:
    if randomization_seed < 0:
        raise AdaptiveLoopBenchmarkExecutionProtocolError("randomization seed must be non-negative")
    sequences = _run_sequences()
    sequence_map = {item.sequence_id: item.ordered_arms for item in sequences}
    blinded_cells: list[AdaptiveLoopBenchmarkBlindedCell] = []
    assignments: list[AdaptiveLoopBenchmarkRunnerAssignment] = []
    for kind in AdaptiveLoopChallengeKind:
        kind_scenarios = [item for item in public_scenarios if item.challenge_kind == kind]
        sequence_ids = _seeded_balanced_sequence_ids(
            challenge_kind=kind,
            randomization_seed=randomization_seed,
        )
        for scenario, sequence_id in zip(kind_scenarios, sequence_ids, strict=True):
            for run_position, arm in enumerate(sequence_map[sequence_id], start=1):
                cell_id = _blinded_cell_id(
                    scenario_id=scenario.scenario_id,
                    run_position=run_position,
                    randomization_seed=randomization_seed,
                )
                blinded_cells.append(
                    AdaptiveLoopBenchmarkBlindedCell(
                        blinded_cell_id=cell_id,
                        scenario_id=scenario.scenario_id,
                        challenge_kind=kind,
                        public_scenario_hash=scenario.public_scenario_hash,
                        run_position=run_position,
                    )
                )
                assignments.append(
                    AdaptiveLoopBenchmarkRunnerAssignment(
                        blinded_cell_id=cell_id,
                        scenario_id=scenario.scenario_id,
                        challenge_kind=kind,
                        sequence_id=sequence_id,
                        run_position=run_position,
                        arm=arm,
                    )
                )
    blinded = AdaptiveLoopBenchmarkBlindedCellManifest.create(
        parent_v1_protocol_hash=parent_protocol_hash,
        design_audit_hash=design_audit_hash,
        public_scenario_panel_hash=public_scenario_panel_hash,
        cells=blinded_cells,
    )
    runner = AdaptiveLoopBenchmarkRunnerAssignmentManifest.create(
        parent_v1_protocol_hash=parent_protocol_hash,
        design_audit_hash=design_audit_hash,
        blinded_manifest_hash=blinded.blinded_manifest_hash,
        private_scoring_manifest_hash=private_scoring_manifest_hash,
        randomization_seed=randomization_seed,
        sequences=sequences,
        assignments=assignments,
    )
    return blinded, runner


def _run_sequences() -> list[AdaptiveLoopBenchmarkRunSequence]:
    arms = list(AdaptiveLoopBenchmarkArm)
    return [
        AdaptiveLoopBenchmarkRunSequence(
            sequence_id=f"balanced-sequence-{offset + 1}",
            ordered_arms=arms[offset:] + arms[:offset],
        )
        for offset in range(4)
    ]


def _seeded_balanced_sequence_ids(
    *,
    challenge_kind: AdaptiveLoopChallengeKind,
    randomization_seed: int,
) -> list[str]:
    slots = [
        (sequence.sequence_id, repetition)
        for sequence in _run_sequences()
        for repetition in range(1, 4)
    ]

    def seeded_digest(slot: tuple[str, int]) -> str:
        sequence_id, repetition = slot
        payload = (
            f"adaptive-loop-v3|{randomization_seed}|{challenge_kind.value}|"
            f"{sequence_id}|{repetition}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    return [sequence_id for sequence_id, _ in sorted(slots, key=seeded_digest)]


def _blinded_cell_id(
    *,
    scenario_id: str,
    run_position: int,
    randomization_seed: int,
) -> str:
    payload = f"adaptive-loop-v3-blinded-cell|{randomization_seed}|{scenario_id}|" f"{run_position}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"cell-{digest[:32]}"


def _oracle_fact_ids(
    kind: AdaptiveLoopChallengeKind,
    fact_ids: list[str],
) -> tuple[list[str], list[str]]:
    if kind == AdaptiveLoopChallengeKind.DELAYED_RELEVANCE:
        return [fact_ids[0], fact_ids[2]], []
    if kind == AdaptiveLoopChallengeKind.STALE_SUPERSESSION:
        return [fact_ids[0], fact_ids[2]], [fact_ids[0]]
    if kind == AdaptiveLoopChallengeKind.CONTRADICTORY_SOURCES:
        return [fact_ids[1], fact_ids[2]], [fact_ids[0]]
    if kind == AdaptiveLoopChallengeKind.EMPTY_TOOL_RESULT:
        return [fact_ids[1], fact_ids[2]], []
    return [fact_ids[0], fact_ids[2]], [fact_ids[1]]


def _validate_oracle_against_public_scenario(
    *,
    public: AdaptiveLoopBenchmarkPublicScenario,
    oracle: AdaptiveLoopBenchmarkMachineOracle,
) -> None:
    turn_by_fact_id = {
        fact_id: stimulus.turn_index
        for stimulus in public.stimuli
        for fact_id in stimulus.public_fact_ids
    }
    scoring_fact_ids = set(oracle.required_public_fact_ids) | set(
        oracle.forbidden_as_current_fact_ids
    )
    if not scoring_fact_ids <= set(turn_by_fact_id):
        raise ValueError("private scoring references a non-public fact ID")
    if oracle.minimum_distinct_public_fact_references > len(oracle.required_public_fact_ids):
        raise ValueError("private scoring requires more facts than it names")
    scoring_turns = [turn_by_fact_id[fact_id] for fact_id in scoring_fact_ids]
    if max(scoring_turns) != oracle.latest_scoring_relevant_turn_index:
        raise ValueError("private scoring latest relevant turn is incorrect")
    if any(turn_index > 3 for turn_index in scoring_turns):
        raise ValueError("private scoring facts must be confined to turns one through three")
    early_text = "\n".join(item.payload_cn for item in public.stimuli if item.turn_index <= 3)
    late_text = "\n".join(item.payload_cn for item in public.stimuli if item.turn_index >= 4)
    for token in oracle.required_terminal_tokens + oracle.forbidden_terminal_tokens:
        if token not in early_text:
            raise ValueError("private scoring token is absent from early public evidence")
        if token in late_text:
            raise ValueError("private scoring token leaks into the recent public window")
    if (
        public.terminal_turn_index - oracle.latest_scoring_relevant_turn_index
        <= public.non_sovereign_recent_window_turns
    ):
        raise ValueError("early scoring evidence remains controller-visible at terminal")


def _neutral_distractor_payloads(*, scenario_id: str) -> list[str]:
    return [
        f"中性干扰记录N04（{scenario_id}）：队列心跳正常；本条不补充实体取值、来源优先级或修订关系。",
        f"中性干扰记录N05（{scenario_id}）：临时目录边界检查完成；本条不改变此前公开记录的证据状态。",
        f"中性干扰记录N06（{scenario_id}）：预算计数仍在许可范围；本条不提供任何用于终态判别的新数值。",
        f"中性干扰记录N07（{scenario_id}）：界面语言保持中文；本条与场景实体、冲突及来源质量相互独立。",
        f"中性干扰记录N08（{scenario_id}）：公开日志序号连续；本条不重述早期记录的文字或标识内容。",
        f"中性干扰记录N09（{scenario_id}）：任务标识保持不变；本条不新增人工科研判断或外部资料。",
        f"中性干扰记录N10（{scenario_id}）：权限状态没有变化；本条不提示应选择的动作、结论或证据。",
        f"中性干扰记录N11（{scenario_id}）：下一轮刺激尚未公开；本条仅维持时序，不携带判定线索。",
    ]


def _expected_terminal_states() -> (
    dict[
        AdaptiveLoopChallengeKind,
        AdaptiveLoopBenchmarkTerminalState,
    ]
):
    return {
        AdaptiveLoopChallengeKind.DELAYED_RELEVANCE: (
            AdaptiveLoopBenchmarkTerminalState.INTEGRATE_DELAYED_EVIDENCE
        ),
        AdaptiveLoopChallengeKind.STALE_SUPERSESSION: (
            AdaptiveLoopBenchmarkTerminalState.ADOPT_SUPERSEDING_RECORD
        ),
        AdaptiveLoopChallengeKind.CONTRADICTORY_SOURCES: (
            AdaptiveLoopBenchmarkTerminalState.RESOLVE_SOURCE_CONFLICT
        ),
        AdaptiveLoopChallengeKind.EMPTY_TOOL_RESULT: (
            AdaptiveLoopBenchmarkTerminalState.ADAPT_AFTER_EMPTY_RESULT
        ),
        AdaptiveLoopChallengeKind.MEMORY_POLLUTION: (
            AdaptiveLoopBenchmarkTerminalState.QUARANTINE_UNPROVEN_DERIVED_MEMORY
        ),
    }


def _stimulus_kinds() -> (
    dict[
        AdaptiveLoopChallengeKind,
        list[AdaptiveLoopBenchmarkStimulusKind],
    ]
):
    terminal = AdaptiveLoopBenchmarkStimulusKind.TERMINAL_REQUEST
    source = AdaptiveLoopBenchmarkStimulusKind.SOURCE_RECORD
    neutral = [AdaptiveLoopBenchmarkStimulusKind.TASK_CONTEXT] * 8
    return {
        AdaptiveLoopChallengeKind.DELAYED_RELEVANCE: [
            source,
            AdaptiveLoopBenchmarkStimulusKind.TASK_CONTEXT,
            source,
            *neutral,
            terminal,
        ],
        AdaptiveLoopChallengeKind.STALE_SUPERSESSION: [
            source,
            AdaptiveLoopBenchmarkStimulusKind.TASK_CONTEXT,
            source,
            *neutral,
            terminal,
        ],
        AdaptiveLoopChallengeKind.CONTRADICTORY_SOURCES: [
            source,
            source,
            AdaptiveLoopBenchmarkStimulusKind.PROVENANCE_NOTICE,
            *neutral,
            terminal,
        ],
        AdaptiveLoopChallengeKind.EMPTY_TOOL_RESULT: [
            AdaptiveLoopBenchmarkStimulusKind.TASK_CONTEXT,
            AdaptiveLoopBenchmarkStimulusKind.TOOL_RECEIPT,
            source,
            *neutral,
            terminal,
        ],
        AdaptiveLoopChallengeKind.MEMORY_POLLUTION: [
            source,
            AdaptiveLoopBenchmarkStimulusKind.PROVENANCE_NOTICE,
            AdaptiveLoopBenchmarkStimulusKind.PROVENANCE_NOTICE,
            *neutral,
            terminal,
        ],
    }


def _fixtures_by_kind() -> (
    dict[
        AdaptiveLoopChallengeKind,
        tuple[_ScenarioFixture, ...],
    ]
):
    return {
        AdaptiveLoopChallengeKind.DELAYED_RELEVANCE: _delayed_relevance_fixtures(),
        AdaptiveLoopChallengeKind.STALE_SUPERSESSION: _stale_supersession_fixtures(),
        AdaptiveLoopChallengeKind.CONTRADICTORY_SOURCES: (_contradictory_source_fixtures()),
        AdaptiveLoopChallengeKind.EMPTY_TOOL_RESULT: _empty_tool_fixtures(),
        AdaptiveLoopChallengeKind.MEMORY_POLLUTION: _memory_pollution_fixtures(),
    }


def _delayed_relevance_fixtures() -> tuple[_ScenarioFixture, ...]:
    return (
        _ScenarioFixture(
            "satellite-clock-offset",
            "卫星遥测时钟校准记录",
            "记录D01：首日固件日志注明遥测时间戳固定慢0.8毫秒，当时被标为低相关背景。",
            "记录D02：第三日轨道事件出现先后次序无法解释的细小偏移，当前材料尚不能归因。",
            "记录D03：事件偏移恰为0.8毫秒且只出现在同一固件批次，首日校准值现在具有判别力。",
            "0.8毫秒",
            None,
        ),
        _ScenarioFixture(
            "soil-salinity-baseline",
            "农田光谱与土壤盐度记录",
            "记录D01：播种前角落样方盐度为3.2毫西门子每厘米，当时未进入主表。",
            "记录D02：两周后该样方近红外反射突然下降，其他样方保持稳定，原因暂不明确。",
            "记录D03：复核坐标发现异常像元正对应盐度3.2的角落样方，早期测量必须重新纳入。",
            "3.2毫西门子每厘米",
            None,
        ),
        _ScenarioFixture(
            "cpu-governor-version",
            "软件延迟与处理器调频记录",
            "记录D01：基线机器曾短暂使用powersave调频器，维护者认为与吞吐测试无关。",
            "记录D02：新版本仅在一台机器上出现百分位延迟抬升，代码提交之间没有差异。",
            "记录D03：异常机器正是保留powersave设置的节点，早期系统状态成为必要解释变量。",
            "powersave",
            None,
        ),
        _ScenarioFixture(
            "microscopy-stain-lot",
            "显微图像染色批次记录",
            "记录D01：首批切片使用染色批号S17，实验员仅在纸质交接表中留下该编号。",
            "记录D02：分割边界在一组切片上系统性偏暗，但相机参数和曝光值完全一致。",
            "记录D03：偏暗切片全部来自批号S17，交接表中的早期批次信息因此转为关键证据。",
            "S17",
            None,
        ),
        _ScenarioFixture(
            "battery-humidity",
            "电池阻抗与环境湿度记录",
            "记录D01：装配日上午环境湿度达到68%，当时被视为与后续循环无关的天气信息。",
            "记录D02：第五十次循环后只有当日上午装配的电芯出现阻抗阶跃，其余批次平稳。",
            "记录D03：密封复核显示该批电芯存在吸湿路径，68%的早期湿度读数需要重新调用。",
            "68%",
            None,
        ),
        _ScenarioFixture(
            "speech-codec",
            "语音语料采集编码记录",
            "记录D01：一间录音室在首日使用OPUS编码，整理时只保留在设备备注中。",
            "记录D02：特定说话人组的词错误率异常升高，方言、年龄和文本长度均不解释差异。",
            "记录D03：异常样本全部来自使用OPUS的录音室，早期编码备注成为分层依据。",
            "OPUS",
            None,
        ),
        _ScenarioFixture(
            "traffic-clock-skew",
            "道路传感器事件顺序记录",
            "记录D01：路口B控制器时钟比路口A快2.4秒，安装验收时被列为轻微偏差。",
            "记录D02：拥堵波记录显示路口B似乎早于上游路口A触发，违反空间传播顺序。",
            "记录D03：表观提前量与2.4秒时钟偏差一致，验收记录必须参与事件重排。",
            "2.4秒",
            None,
        ),
        _ScenarioFixture(
            "ocean-buoy-depth",
            "海洋浮标温度与深度元数据",
            "记录D01：浮标温度探头实际安装深度为7米，数据目录最初只展示默认的5米标签。",
            "记录D02：一次温度逆转只发生在该浮标，邻近站点没有同步信号，真实性存疑。",
            "记录D03：重新读取安装表后，7米深度恰处于跃层下方，早期元数据决定解释边界。",
            "7米",
            None,
        ),
        _ScenarioFixture(
            "assay-buffer-lot",
            "蛋白结合测定缓冲液记录",
            "记录D01：首轮板使用缓冲液批号B42，批号在清洗后被归入普通耗材备注。",
            "记录D02：首轮板的结合曲线斜率与后续板不同，浓度梯度和仪器通道均已排除。",
            "记录D03：留样复测确认批号B42的离子强度偏高，早期耗材信息变成判别证据。",
            "B42",
            None,
        ),
        _ScenarioFixture(
            "market-holiday-calendar",
            "交易量序列与市场日历记录",
            "记录D01：数据供应商把半日交易标记为普通工作日，该标记最初未影响收盘价分析。",
            "记录D02：模型在一个日期产生异常低成交量残差，价格字段和复权过程均正常。",
            "记录D03：异常日期正是半日交易日，早期日历标记必须恢复为解释变量。",
            "半日交易",
            None,
        ),
        _ScenarioFixture(
            "robot-wheel-diameter",
            "移动机器人里程计校准记录",
            "记录D01：左轮实测直径为98.6毫米，比配置值小1.4毫米，调试时未立即修改。",
            "记录D02：长走廊运行出现持续向左漂移，定位相机和地图匹配没有发现异常。",
            "记录D03：漂移方向与98.6毫米左轮直径完全一致，早期机械测量必须进入当前状态。",
            "98.6毫米",
            None,
        ),
        _ScenarioFixture(
            "survey-translation-version",
            "双语问卷版本与条目偏差记录",
            "记录D01：一所学校使用译本T3，其措辞差异当时只写在发放清单的备注列。",
            "记录D02：该校某条目的选择分布显著偏移，但年级和样本规模无法解释。",
            "记录D03：偏移条目正是译本T3改写的句子，早期版本备注现在不可忽略。",
            "T3",
            None,
        ),
    )


def _stale_supersession_fixtures() -> tuple[_ScenarioFixture, ...]:
    return (
        _ScenarioFixture(
            "dataset-license",
            "数据集许可证修订记录",
            "记录S01：初版数据卡把许可证写为CC-BY-NC-4.0，并据此限制商业复用。",
            "记录S02：项目当前需要确认可用边界，缓存索引仍把初版字段标成现行。",
            "记录S03：维护者签名勘误明确取代S01，现行许可证为CC-BY-4.0且版本号为2.1。",
            "CC-BY-4.0",
            "CC-BY-NC-4.0",
        ),
        _ScenarioFixture(
            "paper-sample-count",
            "论文样本数量勘误记录",
            "记录S01：论文初版摘要声称纳入120个样本，多个笔记沿用了该数字。",
            "记录S02：当前需要核对统计分母，派生表仍显示初版样本量。",
            "记录S03：期刊勘误取代S01，排除重复后有效样本为96个，附有修订时间戳。",
            "96个",
            "120个",
        ),
        _ScenarioFixture(
            "api-version",
            "服务接口版本迁移记录",
            "记录S01：旧发布说明指定请求路径为/api/v2/items，客户端缓存一直引用该路径。",
            "记录S02：当前需要确认可调用接口，但历史示例仍优先出现在检索结果中。",
            "记录S03：正式迁移公告取代S01，现行路径为/api/v3/items且v2已停止响应。",
            "/api/v3/items",
            "/api/v2/items",
        ),
        _ScenarioFixture(
            "taxonomy-label",
            "分类标签定义修订记录",
            "记录S01：早期标注手册把代码U解释为阳性，并生成了相应派生摘要。",
            "记录S02：当前需要汇总代码U的样本，旧摘要仍处于高优先级。",
            "记录S03：委员会修订表明确取代S01，代码U现表示不确定而不是阳性。",
            "不确定",
            "阳性",
        ),
        _ScenarioFixture(
            "sensor-coefficient",
            "传感器换算系数修订记录",
            "记录S01：设备手册初印本给出电压换算系数1.20，早期脚本据此生成结果。",
            "记录S02：当前需要解释数值尺度，旧脚本输出仍可见但没有版本标记。",
            "记录S03：制造商勘误取代S01，正确换算系数为0.12，并说明初印本漏写小数点。",
            "0.12",
            "1.20",
        ),
        _ScenarioFixture(
            "benchmark-baseline",
            "基准分数勘误记录",
            "记录S01：排行榜快照把基线宏平均分写为74.2，项目笔记据此计算差值。",
            "记录S02：当前需要报告比较边界，旧快照仍是最近一次本地索引。",
            "记录S03：官方更正记录取代S01，去除重复样本后基线宏平均分为71.4。",
            "71.4",
            "74.2",
        ),
        _ScenarioFixture(
            "genome-build",
            "基因组坐标版本修订记录",
            "记录S01：数据说明初版把变异坐标标为hg19，分析缓存沿用该参考版本。",
            "记录S02：当前需要定位一个区间，旧说明与文件名看起来相互一致。",
            "记录S03：提交者修订声明取代S01，全部坐标实际基于hg38，文件名没有同步更新。",
            "hg38",
            "hg19",
        ),
        _ScenarioFixture(
            "checkpoint-digest",
            "模型检查点摘要修订记录",
            "记录S01：发布页初次列出的检查点摘要前缀为9fa2，下载缓存记录了该值。",
            "记录S02：当前需要核验本地文件身份，旧发布页已被镜像保存。",
            "记录S03：签名发布清单取代S01，正确摘要前缀为c81d，旧值来自上传中断文件。",
            "c81d",
            "9fa2",
        ),
        _ScenarioFixture(
            "temperature-unit",
            "温度字段单位修订记录",
            "记录S01：字段表初版把反应温度单位写成摄氏度，派生图按此加了标签。",
            "记录S02：当前需要解释数值298，旧图与字段表互相支持但未检查修订。",
            "记录S03：数据维护者声明取代S01，该字段单位实际为开尔文，298应按开尔文读取。",
            "开尔文",
            "摄氏度",
        ),
        _ScenarioFixture(
            "data-split",
            "数据划分说明修订记录",
            "记录S01：预发布文档称样本采用随机划分，复现笔记把它当作现行设置。",
            "记录S02：当前需要判断泄漏风险，旧文档仍在本地搜索结果首位。",
            "记录S03：正式数据卡取代S01，实际采用按主体分组划分，并附分组清单摘要。",
            "按主体分组",
            "随机划分",
        ),
        _ScenarioFixture(
            "multiple-testing",
            "统计校正说明修订记录",
            "记录S01：补充材料初版把显著性列描述为未校正值，派生表保留了该说明。",
            "记录S02：当前需要确认阈值含义，数值列本身没有变化。",
            "记录S03：作者勘误取代S01，该列实际为FDR校正值，初版图注遗漏了校正说明。",
            "FDR校正值",
            "未校正值",
        ),
        _ScenarioFixture(
            "telescope-exposure",
            "望远镜曝光时长修订记录",
            "记录S01：观测日志导出页把单帧曝光写为30秒，早期质量笔记引用该值。",
            "记录S02：当前需要解释信噪比，旧导出页与文件名都没有修订提示。",
            "记录S03：台站签名日志取代S01，单帧曝光实际为300秒，导出页少写一个零。",
            "300秒",
            "30秒",
        ),
    )


def _contradictory_source_fixtures() -> tuple[_ScenarioFixture, ...]:
    return (
        _ScenarioFixture(
            "dataset-row-count",
            "数据集行数来源冲突记录",
            "记录C01：个人博客声称清洗后数据共有12000行，但没有给出摘要或版本。",
            "记录C02：官方数据卡标明版本3.0共有10000行，并列出内容摘要前缀a61c。",
            "记录C03：仓库签名清单复核前缀a61c且总行数为10000，来源链完整。",
            "10000行",
            "12000行",
        ),
        _ScenarioFixture(
            "instrument-voltage",
            "仪器供电电压来源冲突记录",
            "记录C01：论坛帖子建议给传感器接12伏电源，没有型号照片或版本信息。",
            "记录C02：制造商手册对型号MX-5明确规定额定电压为5伏。",
            "记录C03：设备铭牌照片与手册序列号一致，并再次标示5伏输入。",
            "5伏",
            "12伏",
        ),
        _ScenarioFixture(
            "corrected-effect",
            "论文效应结论来源冲突记录",
            "记录C01：未更新的预印本摘要声称处理组存在显著正效应，版本号为v1。",
            "记录C02：期刊勘误后的正式版本报告校正后效应不显著，版本日期更晚。",
            "记录C03：出版方修订历史把正式版本绑定到勘误编号E17并撤回v1结论。",
            "效应不显著",
            "显著正效应",
        ),
        _ScenarioFixture(
            "release-parameter-name",
            "软件参数名称来源冲突记录",
            "记录C01：第三方教程仍要求使用参数--old-cache，并称适用于当前版本。",
            "记录C02：官方2.4发布说明把现行参数列为--cache-mode并移除旧名称。",
            "记录C03：带签名的命令帮助输出来自2.4二进制，只包含--cache-mode。",
            "--cache-mode",
            "--old-cache",
        ),
        _ScenarioFixture(
            "registry-endpoint",
            "样本登记终点来源冲突记录",
            "记录C01：二次汇总网页写主要终点是第14天评分，未链接登记版本。",
            "记录C02：带时间戳的公开登记表把主要终点固定为第28天评分。",
            "记录C03：登记修订历史显示第28天字段在入组前已冻结，二次网页无版本依据。",
            "第28天评分",
            "第14天评分",
        ),
        _ScenarioFixture(
            "satellite-resolution",
            "卫星影像分辨率来源冲突记录",
            "记录C01：聚合目录把产品像元大小写为30米，但没有产品版本号。",
            "记录C02：任务方产品说明对L2A-7标明像元大小为10米。",
            "记录C03：样例栅格头信息与L2A-7校验摘要匹配，像元间距确为10米。",
            "10米",
            "30米",
        ),
        _ScenarioFixture(
            "repository-license",
            "代码许可证来源冲突记录",
            "记录C01：非官方镜像README把项目许可证写成MIT，但没有保留标签信息。",
            "记录C02：上游v4.1标签中的LICENSE文件明确为Apache-2.0。",
            "记录C03：上游标签签名验证通过，镜像README提交早于v4.1且无授权依据。",
            "Apache-2.0",
            "MIT",
        ),
        _ScenarioFixture(
            "leaderboard-metric",
            "排行榜指标来源冲突记录",
            "记录C01：新闻稿把排行榜数字解释为准确率，但没有链接评分脚本。",
            "记录C02：官方榜单列名与评分说明均写为宏平均F1。",
            "记录C03：公开评分脚本摘要与榜单版本匹配，输出字段名为macro_f1。",
            "宏平均F1",
            "准确率",
        ),
        _ScenarioFixture(
            "archive-date",
            "档案年代来源冲突记录",
            "记录C01：旅游网页把器物年代写为十八世纪，未提供目录号或照片。",
            "记录C02：馆藏目录按编号Q-19将年代登记为十九世纪中叶。",
            "记录C03：器物底款照片与Q-19目录图一致，馆藏记录有修订责任人。",
            "十九世纪中叶",
            "十八世纪",
        ),
        _ScenarioFixture(
            "sequence-species",
            "序列物种归属来源冲突记录",
            "记录C01：社区表格把序列X7标为小鼠来源，但没有提交号。",
            "记录C02：权威序列库条目以提交号AB77标明X7来自大鼠。",
            "记录C03：原始提交文件和条目摘要一致，物种字段为大鼠且有提交者签名。",
            "大鼠",
            "小鼠",
        ),
        _ScenarioFixture(
            "compiler-determinism",
            "编译器确定性来源冲突记录",
            "记录C01：匿名问答称编译器默认保证位级确定性，没有给出版本或命令。",
            "记录C02：官方17.2文档说明只有启用--reproducible才保证可复现构建。",
            "记录C03：17.2发布包内帮助文本与官方文档一致，并列出该开关。",
            "--reproducible",
            "默认保证位级确定性",
        ),
        _ScenarioFixture(
            "catalog-calibration",
            "天文目录亮度校准来源冲突记录",
            "记录C01：爱好者列表把目标星等写为14.8，未注明滤镜或校准日期。",
            "记录C02：台站校准目录在r波段给出星等15.3并绑定观测批次R62。",
            "记录C03：R62原始标定表摘要验证通过，滤镜字段和15.3数值均可追溯。",
            "15.3",
            "14.8",
        ),
    )


def _empty_tool_fixtures() -> tuple[_ScenarioFixture, ...]:
    return (
        _ScenarioFixture(
            "translated-acronym",
            "论文缩写检索记录",
            "记录E01：初始检索词为“LTM agent memory”，目标条目可能使用中文译名。",
            "记录E02：工具运输成功并对“LTM agent memory”返回零条，错误码为空。",
            "记录E03：目录备注显示目标系列全称含“long-term agent state”，可作为替代表达。",
            "long-term agent state",
            "LTM agent memory",
        ),
        _ScenarioFixture(
            "renamed-dataset",
            "更名数据集检索记录",
            "记录E01：初始检索词为“RiverBench 2023”，目标数据集可能已经更名。",
            "记录E02：工具运输成功并对“RiverBench 2023”返回零条，没有超时或权限错误。",
            "记录E03：维护日志提到新名称“HydroStream Benchmark”，应据此改变检索表达。",
            "HydroStream Benchmark",
            "RiverBench 2023",
        ),
        _ScenarioFixture(
            "doi-punctuation",
            "文献标识符标点检索记录",
            "记录E01：初始检索词为“doi:10.5555／abc.17”，其中斜线来自全角录入。",
            "记录E02：工具运输成功并对“doi:10.5555／abc.17”返回零条。",
            "记录E03：登记页示例采用半角形式“10.5555/abc.17”，可用于下一次查询。",
            "10.5555/abc.17",
            "doi:10.5555／abc.17",
        ),
        _ScenarioFixture(
            "author-transliteration",
            "作者姓名转写检索记录",
            "记录E01：初始检索词为“Chjan Wei graph memory”，姓名可能采用另一种转写。",
            "记录E02：工具运输成功并对“Chjan Wei graph memory”返回零条。",
            "记录E03：机构名录把同一研究者列为“Zhang Wei”，并给出相同主题关键词。",
            "Zhang Wei",
            "Chjan Wei graph memory",
        ),
        _ScenarioFixture(
            "package-fork",
            "软件分支名称检索记录",
            "记录E01：初始检索词为“tensor-cache legacy”，但旧项目可能迁移到新分支。",
            "记录E02：工具运输成功并对“tensor-cache legacy”返回零个仓库。",
            "记录E03：归档页写明后继分支名称“cacheflow-ng”，应改用该名称检索。",
            "cacheflow-ng",
            "tensor-cache legacy",
        ),
        _ScenarioFixture(
            "chemical-synonym",
            "化合物同义名检索记录",
            "记录E01：初始检索词为“维生素B2光谱”，目标数据库可能只收录系统名称。",
            "记录E02：工具运输成功并对“维生素B2光谱”返回零个条目。",
            "记录E03：同义词表给出规范词“riboflavin spectrum”，可扩大检索召回。",
            "riboflavin spectrum",
            "维生素B2光谱",
        ),
        _ScenarioFixture(
            "astronomy-alias",
            "天体目录别名检索记录",
            "记录E01：初始检索词为“Blue Nebula 17”，该俗名可能不在正式目录。",
            "记录E02：工具运输成功并对“Blue Nebula 17”返回零个天体。",
            "记录E03：交叉表把该俗名映射为“NGC 7129”，应改用正式目录号。",
            "NGC 7129",
            "Blue Nebula 17",
        ),
        _ScenarioFixture(
            "place-name-variant",
            "地名变体检索记录",
            "记录E01：初始检索词为“Mt. Taibai snow station”，目录可能使用完整地名。",
            "记录E02：工具运输成功并对“Mt. Taibai snow station”返回零个站点。",
            "记录E03：行政元数据列出规范表达“Taibai Mountain Station”，可用于改写查询。",
            "Taibai Mountain Station",
            "Mt. Taibai snow station",
        ),
        _ScenarioFixture(
            "patent-family",
            "专利族编号检索记录",
            "记录E01：初始检索词为“CN-temp-8842 memory device”，其中编号是内部临时号。",
            "记录E02：工具运输成功并对“CN-temp-8842 memory device”返回零个专利。",
            "记录E03：交接表把临时号映射到公开族号“WO2026-118842”，应切换标识符。",
            "WO2026-118842",
            "CN-temp-8842 memory device",
        ),
        _ScenarioFixture(
            "workshop-old-name",
            "会议专题名称检索记录",
            "记录E01：初始检索词为“Autonomous Recall Workshop”，专题后来可能改名。",
            "记录E02：工具运输成功并对“Autonomous Recall Workshop”返回零条日程。",
            "记录E03：会议变更通知给出新名称“Persistent Agent State Workshop”。",
            "Persistent Agent State Workshop",
            "Autonomous Recall Workshop",
        ),
        _ScenarioFixture(
            "gene-alias",
            "基因别名检索记录",
            "记录E01：初始检索词为“C10orf99 memory response”，旧别名可能已停用。",
            "记录E02：工具运输成功并对“C10orf99 memory response”返回零篇目标记录。",
            "记录E03：基因命名表把现行符号列为“GPR15L”，可据此替换查询词。",
            "GPR15L",
            "C10orf99 memory response",
        ),
        _ScenarioFixture(
            "benchmark-abbreviation",
            "基准简称检索记录",
            "记录E01：初始检索词为“ARS benchmark agent”，简称与多个无关项目重名。",
            "记录E02：工具运输成功但过滤后返回零条匹配记录，没有服务异常。",
            "记录E03：项目说明给出全称“Adaptive Research State Benchmark”，应改用全称。",
            "Adaptive Research State Benchmark",
            "ARS benchmark agent",
        ),
    )


def _memory_pollution_fixtures() -> tuple[_ScenarioFixture, ...]:
    return (
        _ScenarioFixture(
            "model-version",
            "模型版本记忆污染记录",
            "记录M01：签名运行清单明确模型版本为Qwen-3.7-20260801，并绑定配置摘要。",
            "记录M02：无来源派生摘要高置信写成模型版本Qwen-4.0，未绑定任何原始记录。",
            "记录M03：来源审计确认M02没有父记录，M01的签名与配置摘要均验证通过。",
            "Qwen-3.7-20260801",
            "Qwen-4.0",
        ),
        _ScenarioFixture(
            "license-pollution",
            "许可证记忆污染记录",
            "记录M01：上游标签中的许可证文件明确为BSD-3-Clause并通过签名验证。",
            "记录M02：夜间摘要无引用地写成GPL-3.0，并把自身置信度标为0.99。",
            "记录M03：谱系检查显示M02没有原始父节点，M01仍是唯一可追溯来源。",
            "BSD-3-Clause",
            "GPL-3.0",
        ),
        _ScenarioFixture(
            "metric-pollution",
            "评测指标记忆污染记录",
            "记录M01：评分脚本与榜单字段均明确主指标为macro_f1，摘要前缀一致。",
            "记录M02：派生卡片无来源地把主指标改写成accuracy，并声称已经复核。",
            "记录M03：派生卡片没有输入引用，评分脚本的内容摘要与原始清单匹配。",
            "macro_f1",
            "accuracy",
        ),
        _ScenarioFixture(
            "release-date-pollution",
            "发布日期记忆污染记录",
            "记录M01：带签名的发布清单记录版本发布日期为2026-07-18。",
            "记录M02：无来源时间线把发布日期写为2026-06-18，并标为已确认事实。",
            "记录M03：审计发现M02来自一次未保存输入的摘要，M01签名仍然有效。",
            "2026-07-18",
            "2026-06-18",
        ),
        _ScenarioFixture(
            "sample-size-pollution",
            "样本数量记忆污染记录",
            "记录M01：冻结数据清单列出有效样本2048个，并绑定行级摘要。",
            "记录M02：派生笔记无引用地写成有效样本4096个，数值看似更整齐。",
            "记录M03：重新核对清单摘要确认2048个，M02没有任何可重放来源。",
            "2048个",
            "4096个",
        ),
        _ScenarioFixture(
            "calibration-pollution",
            "仪器校准值记忆污染记录",
            "记录M01：校准证书给出零点偏移-0.06伏，并带设备序列号。",
            "记录M02：派生摘要无来源地把零点偏移写为+0.06伏，符号发生反转。",
            "记录M03：证书序列号与当前设备匹配，M02无法定位到任何原始字节。",
            "-0.06伏",
            "+0.06伏",
        ),
        _ScenarioFixture(
            "checksum-pollution",
            "文件摘要记忆污染记录",
            "记录M01：发布清单中的文件摘要前缀为7bc4，并通过签名验证。",
            "记录M02：派生索引无来源地把摘要前缀改成7cb4，只交换了两个字符。",
            "记录M03：重新计算文件摘要得到7bc4，派生索引没有绑定计算回执。",
            "7bc4",
            "7cb4",
        ),
        _ScenarioFixture(
            "api-status-pollution",
            "接口状态记忆污染记录",
            "记录M01：正式状态页记录接口v1已停用且v2当前可用，并带更新时间。",
            "记录M02：派生摘要无来源地写成v1仍可用，并把状态标为稳定。",
            "记录M03：状态页签名和实时本地回执均支持v2可用，M02没有来源链接。",
            "v2当前可用",
            "v1仍可用",
        ),
        _ScenarioFixture(
            "gpu-memory-pollution",
            "硬件显存记忆污染记录",
            "记录M01：资产清单与设备查询回执均显示显存为24GB。",
            "记录M02：派生资源卡无来源地写成显存48GB，并据此抬高可运行规模。",
            "记录M03：设备序列号与24GB查询回执一致，资源卡没有父制品。",
            "24GB",
            "48GB",
        ),
        _ScenarioFixture(
            "threshold-pollution",
            "决策阈值记忆污染记录",
            "记录M01：冻结配置把异常阈值写为0.15，并绑定配置文件摘要。",
            "记录M02：派生说明无来源地把阈值写为0.05，且没有记录修改者。",
            "记录M03：当前配置摘要仍与0.15版本匹配，M02不属于任何修订链。",
            "0.15",
            "0.05",
        ),
        _ScenarioFixture(
            "language-share-pollution",
            "语料语言比例记忆污染记录",
            "记录M01：数据卡统计中文样本占60%，并链接到可重算计数表。",
            "记录M02：派生摘要无来源地声称中文样本占80%，未附计数。",
            "记录M03：计数表复算仍为60%，派生摘要的输入列表为空。",
            "60%",
            "80%",
        ),
        _ScenarioFixture(
            "missing-rate-pollution",
            "缺失率记忆污染记录",
            "记录M01：质量报告给出关键字段缺失率2.3%，并绑定数据摘要。",
            "记录M02：派生总览无来源地把缺失率写成0%，声称数据完全。",
            "记录M03：同一摘要的数据复算仍为2.3%，派生总览没有证据引用。",
            "2.3%",
            "0%",
        ),
    )


def _require_chinese(value: str, *, label: str) -> str:
    normalized = value.strip()
    if not any("\u3400" <= char <= "\u9fff" for char in normalized):
        raise ValueError(f"{label} must contain Chinese")
    return normalized


def _write_once(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
    except FileExistsError:
        if path.read_bytes() != payload:
            raise AdaptiveLoopBenchmarkExecutionProtocolError(
                f"immutable adaptive benchmark execution artifact changed: {path}"
            ) from None


__all__ = [
    "AdaptiveLoopBenchmarkAnalysisContract",
    "AdaptiveLoopBenchmarkBlindedCell",
    "AdaptiveLoopBenchmarkBlindedCellManifest",
    "AdaptiveLoopBenchmarkExecutionBundle",
    "AdaptiveLoopBenchmarkExecutionProtocol",
    "AdaptiveLoopBenchmarkExecutionProtocolError",
    "AdaptiveLoopBenchmarkHiddenOracleManifest",
    "AdaptiveLoopBenchmarkMachineOracle",
    "AdaptiveLoopBenchmarkPublicScenario",
    "AdaptiveLoopBenchmarkPublicStimulus",
    "AdaptiveLoopBenchmarkRunnerAssignment",
    "AdaptiveLoopBenchmarkRunnerAssignmentManifest",
    "AdaptiveLoopBenchmarkTerminalState",
    "build_adaptive_loop_benchmark_execution_bundle",
    "build_adaptive_loop_benchmark_execution_protocol",
    "write_adaptive_loop_benchmark_execution_protocol",
]
