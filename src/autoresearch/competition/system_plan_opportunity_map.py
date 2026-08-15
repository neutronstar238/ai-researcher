"""Evidence-bound research opportunity mapping before direction ideation.

The orchestration in this module performs only mechanical work: it projects the
frozen protocol and signed prior results into indexed facts, checks identifiers,
and preserves exact provider receipts.  A configured model authors every
scientific interpretation in the opportunity cells; a separate interaction may
only reject those cells.  No hypothesis, mechanism, experiment, or expected result
is supplied by Python code.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import Field, ValidationError, model_validator

from autoresearch.competition.language_guard import non_chinese_prose_fields
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.model_authorship import (
    ModelAuthorshipReceipt,
    record_model_authorship_receipt,
)
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.competition.public_data_profile import (
    PublicSystemDataProfile,
    public_data_profile_evidence_view,
    public_data_profile_feature_values,
)
from autoresearch.competition.system_plan_methodology import (
    SystemPlanMethodSkillSelectionBinding,
)
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion

_OPPORTUNITY_COUNT = 7
_MIN_UNIQUE_OPPORTUNITIES = 5
_MIN_ACCEPTED_OPPORTUNITIES = 1
_MAX_MAP_ATTEMPTS = 3
_MAX_REPAIR_ATTEMPTS = 2
_MAX_REVIEW_REPAIR_ATTEMPTS = 3
_MIN_METHOD_REASONING_CHARACTERS = 200
_ARTIFACT_NAME = "system-plan-opportunity-map.json"
_OPPORTUNITY_REVIEW_GATE_FIELDS = (
    "evidence_grounded",
    "prerequisite_matches_target",
    "intervention_preserves_semantics",
    "alternative_is_distinguishable",
    "feasible_under_frozen_contract",
    "gap_not_covered_by_catalog",
    "generalizable_scientific_question",
)
_SENTINEL_SCOPE_TOKENS = (
    "maximum_fit_seconds_per_sentinel",
    "maximum_predict_seconds_per_query",
    "fit_call_count",
    "free_symbol_count_maximum",
    "concrete_numeric_equations_required",
    "20 秒 sentinel",
    "20秒 sentinel",
    "512 MB",
)
_OPPORTUNITY_PROSE_FIELDS = (
    "unresolved_contradiction",
    "operational_construct",
    "mechanism_preconditions",
    "manipulable_factor",
    "measurable_outcome",
    "alternative_explanation",
    "single_component_counterfactual",
    "negative_control",
    "sensitivity_control",
    "orthogonal_diagnostic",
    "independent_analysis_unit",
    "result_blind_decision_rule",
    "resource_bounded_minimal_diagnostic",
    "discriminating_observation",
    "expected_directional_pattern",
    "refuting_observation",
    "why_not_component_composition",
    "feasibility_risk",
)
_OPPORTUNITY_LANGUAGE_EXEMPT_IDENTIFIERS = (
    "condition",
    "seed",
    "estimand",
    "bootstrap",
    "cell",
    "lineage",
    "clean",
    "snr_20",
    "fully_observed_pair",
    "baseline_available",
    "paired_log_effect",
    "jointly_confounded",
    "derivative",
    "STRidge",
    "STLSQ",
    "SINDy",
    "FastLSQ",
    "LES-SINDy",
    "Multi-Fidelity SINDy",
    "Savitzky-Golay",
    "Fourier",
)


class SystemPlanOpportunityMapError(RuntimeError):
    """Raised when no evidence-grounded opportunity map survives review."""


class EvidenceFact(StrictFrozenModel):
    """One mechanically indexed value copied from frozen or signed evidence."""

    fact_id: str = Field(pattern=r"^E[0-9]{3}$")
    fact_kind: Literal[
        "eligible_systems",
        "excluded_systems",
        "data_boundary",
        "data_profile",
        "profile_effect_association",
        "cross_lineage_effect_matrix",
        "protocol_constraint",
        "stage_boundary",
        "aggregate_result",
        "gate_check",
        "status_count",
        "failure_count",
        "system_effect",
        "candidate_provenance",
    ]
    scope: Literal[
        "current_preregistered_policy",
        "public_development_panel",
        "public_development_data_profile",
        "retained_selected_candidate_exploratory_profile_association",
        "retained_selected_candidates_cross_lineage_full_evaluation",
        "synthetic_sentinel_contract",
        "official_development_estimand",
        "official_development_budget",
        "current_stage_boundary",
        "retained_selected_candidate_metadata",
        "retained_selected_candidate_full_evaluation",
        "retained_selected_candidate_adjudication",
        "retained_all_candidates_all_stages",
    ]
    source_locator: str = Field(min_length=1)
    value: Any


class ExploratoryFeatureAssociation(StrictFrozenModel):
    """One predeclared profile feature associated with signed system effects."""

    feature_name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    system_names: tuple[str, ...] = Field(min_length=4)
    data_types: tuple[Literal["ode", "pde"], ...] = Field(min_length=4)
    feature_values: tuple[float, ...] = Field(min_length=4)
    paired_log_effects: tuple[float, ...] = Field(min_length=4)
    spearman_rho: float = Field(ge=-1.0, le=1.0)
    leave_one_system_out_rhos: tuple[float, ...] = Field(min_length=4)
    leave_one_system_out_minimum: float = Field(ge=-1.0, le=1.0)
    leave_one_system_out_maximum: float = Field(ge=-1.0, le=1.0)
    leave_one_system_out_sign_consistent: bool
    within_data_type_associations: tuple[WithinDataTypeFeatureAssociation, ...] = ()
    overall_data_type_confounding_not_ruled_out: Literal[True] = True

    @model_validator(mode="after")
    def _validate_lengths(self) -> ExploratoryFeatureAssociation:
        count = len(self.system_names)
        if (
            len(set(self.system_names)) != count
            or len(self.data_types) != count
            or len(self.feature_values) != count
            or len(self.paired_log_effects) != count
            or len(self.leave_one_system_out_rhos) != count
        ):
            raise SystemPlanOpportunityMapError(
                "探索性画像—效果关联的系统与数值长度不一致"
            )
        return self


class WithinDataTypeFeatureAssociation(StrictFrozenModel):
    """The same descriptive association recomputed inside one data-type stratum."""

    data_type: Literal["ode", "pde"]
    system_names: tuple[str, ...] = Field(min_length=4)
    feature_values: tuple[float, ...] = Field(min_length=4)
    paired_log_effects: tuple[float, ...] = Field(min_length=4)
    spearman_rho: float = Field(ge=-1.0, le=1.0)
    leave_one_system_out_rhos: tuple[float, ...] = Field(min_length=4)
    leave_one_system_out_minimum: float = Field(ge=-1.0, le=1.0)
    leave_one_system_out_maximum: float = Field(ge=-1.0, le=1.0)
    leave_one_system_out_sign_consistent: bool

    @model_validator(mode="after")
    def _validate_lengths(self) -> WithinDataTypeFeatureAssociation:
        count = len(self.system_names)
        if (
            len(set(self.system_names)) != count
            or len(self.feature_values) != count
            or len(self.paired_log_effects) != count
            or len(self.leave_one_system_out_rhos) != count
        ):
            raise SystemPlanOpportunityMapError(
                "分层探索性画像—效果关联的系统与数值长度不一致"
            )
        return self


class ExploratoryProfileEffectAssociationPanel(StrictFrozenModel):
    """All estimable predeclared associations for one retained signed lineage."""

    schema_version: Literal["exploratory-profile-effect-association-panel-v1"] = (
        "exploratory-profile-effect-association-panel-v1"
    )
    source_lineage_id: str = Field(min_length=1)
    source_package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_profile_hashes: dict[str, str] = Field(min_length=4)
    source_effect_coverage_rule: Literal[
        "candidate_success_count_equals_candidate_cell_count_and_baseline_available"
    ] = "candidate_success_count_equals_candidate_cell_count_and_baseline_available"
    excluded_incomplete_systems: tuple[str, ...] = ()
    effect_field: Literal["paired_log_effect"] = "paired_log_effect"
    predeclared_feature_names: tuple[str, ...] = Field(min_length=1)
    associations: tuple[ExploratoryFeatureAssociation, ...] = Field(min_length=1)
    exploratory_only: Literal[True] = True
    causal_interpretation_authorized: Literal[False] = False
    multiple_comparisons_adjusted: Literal[False] = False
    confirmatory_use_requires_new_preregistered_test: Literal[True] = True
    panel_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_panel(self) -> ExploratoryProfileEffectAssociationPanel:
        association_names = tuple(item.feature_name for item in self.associations)
        if len(set(association_names)) != len(association_names):
            raise SystemPlanOpportunityMapError(
                "探索性画像—效果关联特征不得重复"
            )
        if any(
            name not in self.predeclared_feature_names for name in association_names
        ):
            raise SystemPlanOpportunityMapError(
                "探索性关联包含未预声明画像特征"
            )
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"panel_hash"})
        )
        if self.panel_hash != expected:
            raise SystemPlanOpportunityMapError("探索性画像—效果关联面板哈希不符")
        return self


class CrossLineageEffectObservation(StrictFrozenModel):
    """One signed effect plus the mechanical coverage needed for comparison."""

    lineage_id: str = Field(min_length=1)
    package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_candidate_id: str = Field(min_length=1)
    system_name: str = Field(min_length=1)
    data_type: Literal["ode", "pde"]
    candidate_median_loss: float
    baseline_median_loss: float
    paired_log_effect: float
    candidate_cell_count: int = Field(ge=1)
    candidate_success_count: int = Field(ge=0)
    baseline_available: bool
    fully_observed_pair: bool

    @model_validator(mode="after")
    def _validate_coverage(self) -> CrossLineageEffectObservation:
        expected = (
            self.candidate_success_count == self.candidate_cell_count
            and self.baseline_available
        )
        if self.fully_observed_pair != expected:
            raise SystemPlanOpportunityMapError(
                "跨谱系效果的完整观测标记与单元覆盖不一致"
            )
        return self


class ComparableLineageCandidate(StrictFrozenModel):
    """A selected candidate whose result lineage shares one frozen identity."""

    lineage_id: str = Field(min_length=1)
    package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_candidate_id: str = Field(min_length=1)
    selected_candidate_summary: str = Field(min_length=1)
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    development_panel_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    runner_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_environment_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    conditions: tuple[str, ...] = Field(min_length=1)
    search_freeze_receipt_issued: bool


class CrossLineageSystemEffectRow(StrictFrozenModel):
    """Fully observed effects for one system under at least two candidates."""

    system_name: str = Field(min_length=1)
    data_type: Literal["ode", "pde"]
    observations: tuple[CrossLineageEffectObservation, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def _validate_observations(self) -> CrossLineageSystemEffectRow:
        if len({item.lineage_id for item in self.observations}) != len(
            self.observations
        ):
            raise SystemPlanOpportunityMapError(
                "跨谱系系统效果的 lineage_id 不得重复"
            )
        if any(
            item.system_name != self.system_name
            or item.data_type != self.data_type
            or not item.fully_observed_pair
            for item in self.observations
        ):
            raise SystemPlanOpportunityMapError(
                "跨谱系系统效果行混入不同系统、类型或不完整观测"
            )
        if len({item.candidate_cell_count for item in self.observations}) != 1:
            raise SystemPlanOpportunityMapError(
                "跨谱系系统效果的重复单元数不同，不能直接比较"
            )
        return self


class CrossLineageSystemEffectMatrix(StrictFrozenModel):
    """A result matrix with no component-level causal interpretation attached."""

    schema_version: Literal["cross-lineage-system-effect-matrix-v1"] = (
        "cross-lineage-system-effect-matrix-v1"
    )
    candidates: tuple[ComparableLineageCandidate, ...] = Field(min_length=2)
    coverage_ledger: tuple[CrossLineageEffectObservation, ...] = Field(min_length=2)
    comparable_system_rows: tuple[CrossLineageSystemEffectRow, ...] = Field(
        min_length=1
    )
    comparability_rule: Literal[
        "same_plan_panel_runner_runtime_conditions_and_fully_observed_candidate_cells"
    ] = "same_plan_panel_runner_runtime_conditions_and_fully_observed_candidate_cells"
    candidate_differences_jointly_confounded: Literal[True] = True
    component_attribution_authorized: Literal[False] = False
    confirmatory_use_requires_model_authored_component_ablation: Literal[True] = True
    matrix_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_matrix(self) -> CrossLineageSystemEffectMatrix:
        lineage_ids = {item.lineage_id for item in self.candidates}
        if len(lineage_ids) != len(self.candidates):
            raise SystemPlanOpportunityMapError("跨谱系矩阵的候选谱系不得重复")
        bindings = {
            (
                item.plan_hash,
                item.development_panel_hash,
                item.runner_sha256,
                item.runtime_environment_hash,
                item.conditions,
            )
            for item in self.candidates
        }
        if len(bindings) != 1:
            raise SystemPlanOpportunityMapError(
                "跨谱系矩阵混入不可直接比较的计划、面板、运行器或环境"
            )
        if any(item.lineage_id not in lineage_ids for item in self.coverage_ledger):
            raise SystemPlanOpportunityMapError(
                "跨谱系覆盖账本引用了未声明候选谱系"
            )
        expected_rows: dict[tuple[str, str], set[tuple[str, str]]] = {}
        for item in self.coverage_ledger:
            if not item.fully_observed_pair:
                continue
            key = (item.system_name, item.data_type)
            expected_rows.setdefault(key, set()).add(
                (item.lineage_id, item.package_hash)
            )
        expected_rows = {
            key: value for key, value in expected_rows.items() if len(value) >= 2
        }
        actual_rows = {
            (row.system_name, row.data_type): {
                (item.lineage_id, item.package_hash) for item in row.observations
            }
            for row in self.comparable_system_rows
        }
        if actual_rows != expected_rows:
            raise SystemPlanOpportunityMapError(
                "跨谱系矩阵未完整覆盖所有可比较的系统效果"
            )
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"matrix_hash"})
        )
        if self.matrix_hash != expected_hash:
            raise SystemPlanOpportunityMapError("跨谱系系统效果矩阵哈希不符")
        return self


def exploratory_evidence_panel_literature_view(
    fact: EvidenceFact,
) -> dict[str, Any]:
    """Compact every row of an exploratory panel without selecting a signal."""

    value = _mapping(fact.value)
    base = {
        "fact_id": fact.fact_id,
        "fact_kind": fact.fact_kind,
        "scope": fact.scope,
    }
    if fact.fact_kind == "profile_effect_association":
        panel = ExploratoryProfileEffectAssociationPanel.model_validate(value)
        return {
            **base,
            "panel_hash": panel.panel_hash,
            "source_lineage_id": panel.source_lineage_id,
            "source_package_hash": panel.source_package_hash,
            "source_effect_coverage_rule": panel.source_effect_coverage_rule,
            "excluded_incomplete_systems": list(
                panel.excluded_incomplete_systems
            ),
            "exploratory_only": panel.exploratory_only,
            "causal_interpretation_authorized": (
                panel.causal_interpretation_authorized
            ),
            "multiple_comparisons_adjusted": (
                panel.multiple_comparisons_adjusted
            ),
            "associations": [
                {
                    "feature_name": item.feature_name,
                    "system_count": len(item.system_names),
                    "spearman_rho": item.spearman_rho,
                    "leave_one_system_out_minimum": (
                        item.leave_one_system_out_minimum
                    ),
                    "leave_one_system_out_maximum": (
                        item.leave_one_system_out_maximum
                    ),
                    "leave_one_system_out_sign_consistent": (
                        item.leave_one_system_out_sign_consistent
                    ),
                    "overall_data_type_confounding_not_ruled_out": (
                        item.overall_data_type_confounding_not_ruled_out
                    ),
                    "within_data_type_associations": [
                        {
                            "data_type": stratum.data_type,
                            "system_count": len(stratum.system_names),
                            "spearman_rho": stratum.spearman_rho,
                            "leave_one_system_out_minimum": (
                                stratum.leave_one_system_out_minimum
                            ),
                            "leave_one_system_out_maximum": (
                                stratum.leave_one_system_out_maximum
                            ),
                            "leave_one_system_out_sign_consistent": (
                                stratum.leave_one_system_out_sign_consistent
                            ),
                        }
                        for stratum in item.within_data_type_associations
                    ],
                }
                for item in panel.associations
            ],
        }
    if fact.fact_kind == "cross_lineage_effect_matrix":
        matrix = CrossLineageSystemEffectMatrix.model_validate(value)
        return {
            **base,
            "matrix_hash": matrix.matrix_hash,
            "comparability_rule": matrix.comparability_rule,
            "candidate_differences_jointly_confounded": (
                matrix.candidate_differences_jointly_confounded
            ),
            "component_attribution_authorized": (
                matrix.component_attribution_authorized
            ),
            "candidates": [
                {
                    "lineage_id": item.lineage_id,
                    "package_hash": item.package_hash,
                    "selected_candidate_id": item.selected_candidate_id,
                    "selected_candidate_summary": (
                        item.selected_candidate_summary
                    ),
                }
                for item in matrix.candidates
            ],
            "comparable_system_rows": [
                {
                    "system_name": row.system_name,
                    "data_type": row.data_type,
                    "observations": [
                        {
                            "lineage_id": item.lineage_id,
                            "candidate_median_loss": item.candidate_median_loss,
                            "baseline_median_loss": item.baseline_median_loss,
                            "paired_log_effect": item.paired_log_effect,
                        }
                        for item in row.observations
                    ],
                }
                for row in matrix.comparable_system_rows
            ],
            "excluded_incomplete_observations": [
                {
                    "lineage_id": item.lineage_id,
                    "system_name": item.system_name,
                    "candidate_success_count": item.candidate_success_count,
                    "candidate_cell_count": item.candidate_cell_count,
                }
                for item in matrix.coverage_ledger
                if not item.fully_observed_pair
            ],
        }
    raise SystemPlanOpportunityMapError(
        f"不支持的探索证据面板类型：{fact.fact_kind}"
    )


class EligibleResearchSystem(StrictFrozenModel):
    """A public system that the preregistered baseline policy permits scoring."""

    system_name: str = Field(min_length=1)
    data_type: Literal["ode", "pde"]


class ExcludedResearchSystem(StrictFrozenModel):
    """A public system that may not be targeted by the new research direction."""

    system_name: str = Field(min_length=1)
    data_type: Literal["ode", "pde"]
    handling: str = Field(min_length=1)
    mechanism: str | None = None


class ResearchFeasibilityEnvelope(StrictFrozenModel):
    """Compact, deterministic projection of the current evidence and boundaries."""

    schema_version: Literal["research-feasibility-envelope-v2"] = (
        "research-feasibility-envelope-v2"
    )
    source_context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    eligible_systems: tuple[EligibleResearchSystem, ...] = Field(min_length=1)
    excluded_systems: tuple[ExcludedResearchSystem, ...]
    conditions: tuple[str, ...] = Field(min_length=1)
    seeds: tuple[int, ...] = Field(min_length=1)
    contract_gate: dict[str, Any]
    estimand: dict[str, Any]
    search_budget: dict[str, Any]
    stage_breadth: dict[str, Any]
    execution_semantics: dict[str, Any]
    evidence_facts: tuple[EvidenceFact, ...] = Field(min_length=5)
    envelope_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_envelope(self) -> ResearchFeasibilityEnvelope:
        eligible_names = [item.system_name for item in self.eligible_systems]
        excluded_names = [item.system_name for item in self.excluded_systems]
        if len(set(eligible_names)) != len(eligible_names):
            raise SystemPlanOpportunityMapError("可研究系统名称不得重复")
        if len(set(excluded_names)) != len(excluded_names):
            raise SystemPlanOpportunityMapError("排除系统名称不得重复")
        overlap = sorted(set(eligible_names) & set(excluded_names))
        if overlap:
            raise SystemPlanOpportunityMapError(
                f"系统不得同时属于可研究和排除集合：{overlap}"
            )
        fact_ids = [item.fact_id for item in self.evidence_facts]
        if len(set(fact_ids)) != len(fact_ids):
            raise SystemPlanOpportunityMapError("证据事实编号不得重复")
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"envelope_hash"})
        )
        if self.envelope_hash != expected_hash:
            raise SystemPlanOpportunityMapError("研究可行性边界哈希不符")
        return self


class OpportunityMethodApplicationTrace(StrictFrozenModel):
    """Structured, model-authored audit summary of the selected SKILL methodology."""

    verified_fact_ids: tuple[str, ...] = Field(min_length=2)
    evidence_scope_audit: str = Field(min_length=30)
    changed_component: str = Field(min_length=20)
    frozen_components: tuple[str, ...] = Field(min_length=3)
    negative_control_audit: str = Field(min_length=30)
    orthogonal_diagnostic_audit: str = Field(min_length=30)
    independent_unit_audit: str = Field(min_length=30)
    target_mechanism_outcome: str = Field(min_length=30)
    alternative_explanation_outcome: str = Field(min_length=30)
    indeterminate_outcome: str = Field(min_length=30)
    resource_bound_audit: str = Field(min_length=30)
    closest_prior_reference_indices: tuple[int, ...] = Field(min_length=3)
    closest_prior_gap_audit: str = Field(min_length=30)

    @model_validator(mode="after")
    def _validate_trace(self) -> OpportunityMethodApplicationTrace:
        if len(set(self.verified_fact_ids)) != len(self.verified_fact_ids):
            raise SystemPlanOpportunityMapError("方法应用轨迹的事实编号不得重复")
        if len(set(self.closest_prior_reference_indices)) != len(
            self.closest_prior_reference_indices
        ):
            raise SystemPlanOpportunityMapError("方法应用轨迹的近邻文献编号不得重复")
        if len(set(self.frozen_components)) != len(self.frozen_components):
            raise SystemPlanOpportunityMapError("方法应用轨迹的冻结组件不得重复")
        return self


class ResearchOpportunityCell(StrictFrozenModel):
    """One model-authored gap whose mechanism can be discriminated empirically."""

    cell_id: str = Field(pattern=r"^O0[1-7]$")
    evidence_fact_ids: tuple[str, ...] = Field(min_length=2)
    literature_indices: tuple[int, ...] = Field(min_length=3)
    unresolved_contradiction: str = Field(min_length=30)
    operational_construct: str = Field(min_length=30)
    mechanism_preconditions: tuple[str, ...] = Field(min_length=2)
    eligible_target_systems: tuple[str, ...] = Field(min_length=1)
    manipulable_factor: str = Field(min_length=20)
    measurable_outcome: str = Field(min_length=20)
    alternative_explanation: str = Field(min_length=20)
    single_component_counterfactual: str = Field(min_length=30)
    negative_control: str = Field(min_length=30)
    sensitivity_control: str = Field(min_length=30)
    orthogonal_diagnostic: str = Field(min_length=30)
    independent_analysis_unit: str = Field(min_length=20)
    result_blind_decision_rule: str = Field(min_length=30)
    resource_bounded_minimal_diagnostic: str = Field(min_length=30)
    discriminating_observation: str = Field(min_length=30)
    expected_directional_pattern: str = Field(min_length=30)
    refuting_observation: str = Field(min_length=30)
    why_not_component_composition: str = Field(min_length=30)
    feasibility_risk: str = Field(min_length=20)
    method_application_trace: OpportunityMethodApplicationTrace

    @model_validator(mode="after")
    def _validate_cell(self) -> ResearchOpportunityCell:
        for label, values in (
            ("证据事实编号", self.evidence_fact_ids),
            ("文献编号", self.literature_indices),
            ("目标系统", self.eligible_target_systems),
        ):
            if len(set(values)) != len(values):
                raise SystemPlanOpportunityMapError(
                    f"研究机会的{label}不得重复：{self.cell_id}"
                )
        language_failures = non_chinese_prose_fields(
            {
                "unresolved_contradiction": self.unresolved_contradiction,
                "operational_construct": self.operational_construct,
                "mechanism_preconditions": self.mechanism_preconditions,
                "manipulable_factor": self.manipulable_factor,
                "measurable_outcome": self.measurable_outcome,
                "alternative_explanation": self.alternative_explanation,
                "single_component_counterfactual": (
                    self.single_component_counterfactual
                ),
                "negative_control": self.negative_control,
                "sensitivity_control": self.sensitivity_control,
                "orthogonal_diagnostic": self.orthogonal_diagnostic,
                "independent_analysis_unit": self.independent_analysis_unit,
                "result_blind_decision_rule": self.result_blind_decision_rule,
                "resource_bounded_minimal_diagnostic": (
                    self.resource_bounded_minimal_diagnostic
                ),
                "discriminating_observation": self.discriminating_observation,
                "expected_directional_pattern": self.expected_directional_pattern,
                "refuting_observation": self.refuting_observation,
                "why_not_component_composition": self.why_not_component_composition,
                "feasibility_risk": self.feasibility_risk,
                "method_application_trace.evidence_scope_audit": (
                    self.method_application_trace.evidence_scope_audit
                ),
                "method_application_trace.changed_component": (
                    self.method_application_trace.changed_component
                ),
                "method_application_trace.frozen_components": (
                    self.method_application_trace.frozen_components
                ),
                "method_application_trace.negative_control_audit": (
                    self.method_application_trace.negative_control_audit
                ),
                "method_application_trace.orthogonal_diagnostic_audit": (
                    self.method_application_trace.orthogonal_diagnostic_audit
                ),
                "method_application_trace.independent_unit_audit": (
                    self.method_application_trace.independent_unit_audit
                ),
                "method_application_trace.target_mechanism_outcome": (
                    self.method_application_trace.target_mechanism_outcome
                ),
                "method_application_trace.alternative_explanation_outcome": (
                    self.method_application_trace.alternative_explanation_outcome
                ),
                "method_application_trace.indeterminate_outcome": (
                    self.method_application_trace.indeterminate_outcome
                ),
                "method_application_trace.resource_bound_audit": (
                    self.method_application_trace.resource_bound_audit
                ),
                "method_application_trace.closest_prior_gap_audit": (
                    self.method_application_trace.closest_prior_gap_audit
                ),
            },
            exempt_identifiers=(
                *self.eligible_target_systems,
                *_OPPORTUNITY_LANGUAGE_EXEMPT_IDENTIFIERS,
            ),
        )
        if language_failures:
            raise SystemPlanOpportunityMapError(
                f"研究机会不是中文：{list(language_failures)}"
            )
        if set(self.method_application_trace.verified_fact_ids) != set(
            self.evidence_fact_ids
        ):
            raise SystemPlanOpportunityMapError(
                f"{self.cell_id} 方法应用轨迹必须逐一核对全部 evidence_fact_ids"
            )
        if set(self.method_application_trace.closest_prior_reference_indices) != set(
            self.literature_indices
        ):
            raise SystemPlanOpportunityMapError(
                f"{self.cell_id} 方法应用轨迹必须逐一比较全部 literature_indices"
            )
        return self


class ResearchOpportunityMapDraft(StrictFrozenModel):
    """Exactly seven raw model-authored opportunities before mechanical deduping."""

    opportunities: tuple[ResearchOpportunityCell, ...] = Field(
        min_length=_OPPORTUNITY_COUNT,
        max_length=_OPPORTUNITY_COUNT,
    )

    @model_validator(mode="after")
    def _validate_draft(self) -> ResearchOpportunityMapDraft:
        expected_ids = [f"O{index:02d}" for index in range(1, 8)]
        actual_ids = [item.cell_id for item in self.opportunities]
        if actual_ids != expected_ids:
            raise SystemPlanOpportunityMapError(
                f"研究机会必须按顺序使用编号 O01..O07：{actual_ids}"
            )
        normalized_gaps = {
            item.unresolved_contradiction.casefold().strip()
            for item in self.opportunities
        }
        if len(normalized_gaps) != _OPPORTUNITY_COUNT:
            raise SystemPlanOpportunityMapError("七个研究机会不得重复同一未解矛盾")
        return self


class ResearchOpportunityMap(StrictFrozenModel):
    """Five to seven unique model-authored opportunities after stable deduping."""

    opportunities: tuple[ResearchOpportunityCell, ...] = Field(
        min_length=_MIN_UNIQUE_OPPORTUNITIES,
        max_length=_OPPORTUNITY_COUNT,
    )

    @model_validator(mode="after")
    def _validate_map(self) -> ResearchOpportunityMap:
        expected_ids = [
            f"O{index:02d}" for index in range(1, len(self.opportunities) + 1)
        ]
        actual_ids = [item.cell_id for item in self.opportunities]
        if actual_ids != expected_ids:
            raise SystemPlanOpportunityMapError(
                f"去重后的研究机会必须按顺序连续编号：{actual_ids}"
            )
        evidence_target_signatures = {
            (
                frozenset(item.evidence_fact_ids),
                frozenset(item.eligible_target_systems),
            )
            for item in self.opportunities
        }
        if len(evidence_target_signatures) != len(self.opportunities):
            raise SystemPlanOpportunityMapError(
                "去重后的研究机会不得复用同一证据事实集合与目标系统集合"
            )
        return self


def _deduplicate_opportunity_map(
    draft: ResearchOpportunityMapDraft,
) -> tuple[ResearchOpportunityMap, tuple[str, ...]]:
    """Keep first evidence-target signature and stably renumber; author no prose."""

    seen: set[tuple[frozenset[str], frozenset[str]]] = set()
    retained: list[ResearchOpportunityCell] = []
    removed: list[str] = []
    for cell in draft.opportunities:
        signature = (
            frozenset(cell.evidence_fact_ids),
            frozenset(cell.eligible_target_systems),
        )
        if signature in seen:
            removed.append(cell.cell_id)
            continue
        seen.add(signature)
        retained.append(cell)
    if len(retained) < _MIN_UNIQUE_OPPORTUNITIES:
        raise SystemPlanOpportunityMapError(
            "研究机会稳定去重后少于五格，不能进入独立评审"
        )
    normalized = ResearchOpportunityMap(
        opportunities=tuple(
            cell.model_copy(update={"cell_id": f"O{index:02d}"})
            for index, cell in enumerate(retained, 1)
        )
    )
    return normalized, tuple(removed)


def _cell_evidence_scope_findings(
    *,
    cell: ResearchOpportunityCell,
    envelope: ResearchFeasibilityEnvelope,
) -> tuple[str, ...]:
    """Mechanically reject unsupported target attribution and scope joins."""

    facts_by_id = {item.fact_id: item for item in envelope.evidence_facts}
    cited_facts = [
        facts_by_id[fact_id]
        for fact_id in cell.evidence_fact_ids
        if fact_id in facts_by_id
    ]
    findings: list[str] = []
    all_stage_facts = [
        fact.fact_id
        for fact in cited_facts
        if fact.scope == "retained_all_candidates_all_stages"
    ]
    if all_stage_facts:
        findings.append(
            f"{cell.cell_id} 使用了不能归因到具体目标系统的全候选/全阶段事实："
            f"{all_stage_facts}"
        )
    targets = set(cell.eligible_target_systems)
    eligible_types = {
        item.system_name: item.data_type for item in envelope.eligible_systems
    }
    effect_systems = {
        str(fact.value.get("system_name"))
        for fact in cited_facts
        if fact.fact_kind == "system_effect"
        and isinstance(fact.value, Mapping)
        and fact.value.get("system_name")
    }
    profile_systems = {
        str(fact.value.get("system_name"))
        for fact in cited_facts
        if fact.fact_kind == "data_profile"
        and isinstance(fact.value, Mapping)
        and fact.value.get("system_name")
    }
    if len(targets) < 2:
        findings.append(f"{cell.cell_id} 少于两个独立目标系统，不能支撑可推广机会")
    available_pattern_facts = {
        fact.fact_id
        for fact in envelope.evidence_facts
        if fact.fact_kind
        in {"profile_effect_association", "cross_lineage_effect_matrix"}
    }
    cited_pattern_facts = [
        fact
        for fact in cited_facts
        if fact.fact_kind
        in {"profile_effect_association", "cross_lineage_effect_matrix"}
    ]
    if available_pattern_facts and not cited_pattern_facts:
        findings.append(
            f"{cell.cell_id} 未引用任何跨系统或跨谱系探索面板，不能从孤立配对"
            "推广机制"
        )
    cited_matrix_facts = [
        fact for fact in cited_facts if fact.fact_kind == "cross_lineage_effect_matrix"
    ]
    if cited_matrix_facts:
        if len(targets) < 3:
            findings.append(
                f"{cell.cell_id} 使用跨谱系矩阵却少于三个独立目标系统"
            )
        comparable_targets = {
            str(row.get("system_name"))
            for fact in cited_matrix_facts
            if isinstance(fact.value, Mapping)
            for row in fact.value.get("comparable_system_rows") or []
            if isinstance(row, Mapping) and row.get("system_name")
        }
        invalid_matrix_targets = sorted(targets - comparable_targets)
        if invalid_matrix_targets:
            findings.append(
                f"{cell.cell_id} 的目标不在完整观测跨谱系矩阵中："
                f"{invalid_matrix_targets}"
            )
        for target in sorted(targets):
            lineage_count = len(
                {
                    str(fact.value.get("lineage_id"))
                    for fact in cited_facts
                    if fact.fact_kind == "system_effect"
                    and isinstance(fact.value, Mapping)
                    and fact.value.get("system_name") == target
                    and fact.value.get("lineage_id")
                    and fact.value.get("baseline_available") is True
                    and fact.value.get("candidate_success_count")
                    == fact.value.get("candidate_cell_count")
                }
            )
            if lineage_count < 2:
                findings.append(
                    f"{cell.cell_id} 对目标 {target} 未引用至少两个完整观测谱系的"
                    "逐系统效果"
                )
    elif any(
        fact.fact_kind == "profile_effect_association"
        for fact in cited_pattern_facts
    ):
        if len(targets) < 4:
            findings.append(
                f"{cell.cell_id} 仅用画像—效果关联却少于四个独立目标系统"
            )
        target_types = {eligible_types.get(target) for target in targets}
        if len(target_types) != 1 or None in target_types:
            findings.append(
                f"{cell.cell_id} 使用画像—效果关联时混合了 ODE/PDE 数据类型"
            )
    missing_effects = sorted(targets - effect_systems)
    extra_effects = sorted(effect_systems - targets)
    if missing_effects:
        findings.append(
            f"{cell.cell_id} 的目标缺少各自逐系统 system_effect 事实："
            f"{missing_effects}"
        )
    if extra_effects:
        findings.append(
            f"{cell.cell_id} 引用的逐系统事实未全部进入目标集合：{extra_effects}"
        )
    missing_profiles = sorted(targets - profile_systems)
    extra_profiles = sorted(profile_systems - targets)
    if missing_profiles:
        findings.append(
            f"{cell.cell_id} 的目标缺少各自公开数据 data_profile 事实："
            f"{missing_profiles}"
        )
    if extra_profiles:
        findings.append(
            f"{cell.cell_id} 引用的数据画像未全部进入目标集合：{extra_profiles}"
        )
    cell_payload = cell.model_dump(mode="json")
    prose_by_field = {
        field_name: cell_payload[field_name]
        for field_name in _OPPORTUNITY_PROSE_FIELDS
    }
    prose_by_field.update(
        {
            f"method_application_trace.{field_name}": value
            for field_name, value in cell_payload["method_application_trace"].items()
            if field_name
            not in {"verified_fact_ids", "closest_prior_reference_indices"}
        }
    )
    for field_name, raw_value in prose_by_field.items():
        values = raw_value if isinstance(raw_value, list) else [raw_value]
        matched_tokens = sorted(
            {
                token
                for value in values
                if isinstance(value, str)
                for token in _SENTINEL_SCOPE_TOKENS
                if token in value
            }
        )
        if matched_tokens:
            findings.append(
                f"{cell.cell_id}.{field_name} 把仅适用于小型合成 sentinel 的契约"
                f"用于正式系统机会：{matched_tokens}"
            )
    return tuple(findings)


class OpportunityCellAssessment(StrictFrozenModel):
    """Independent all-gates verdict for one opportunity cell."""

    cell_id: str = Field(pattern=r"^O0[1-7]$")
    supporting_fact_ids: tuple[str, ...] = Field(min_length=1)
    supporting_literature_indices: tuple[int, ...] = Field(min_length=1)
    evidence_grounded: bool
    prerequisite_matches_target: bool
    intervention_preserves_semantics: bool
    alternative_is_distinguishable: bool
    feasible_under_frozen_contract: bool
    gap_not_covered_by_catalog: bool
    generalizable_scientific_question: bool
    critical_findings: tuple[str, ...] = Field(
        description=(
            "只填写尚未解决且足以否决机会格的缺陷。存在 finding 时该格保守地"
            "不通过，即使审查者误把七项布尔门全部写成 true；正面评价不得写入此字段。"
        )
    )

    @model_validator(mode="after")
    def _validate_gate_findings(self) -> OpportunityCellAssessment:
        gates = (
            self.evidence_grounded,
            self.prerequisite_matches_target,
            self.intervention_preserves_semantics,
            self.alternative_is_distinguishable,
            self.feasible_under_frozen_contract,
            self.gap_not_covered_by_catalog,
            self.generalizable_scientific_question,
        )
        # A reviewer can accidentally tick every Boolean while still recording a
        # scientific veto.  Preserve that veto and let ``qualifies`` conservatively
        # reject the cell instead of crashing the entire seven-worker batch.  The
        # opposite inconsistency remains invalid because a false gate needs a reason.
        if not all(gates) and not self.critical_findings:
            raise SystemPlanOpportunityMapError(
                f"{self.cell_id} 存在未通过门禁时必须给出 critical finding"
            )
        return self

    def qualifies(self) -> bool:
        return (
            self.evidence_grounded
            and self.prerequisite_matches_target
            and self.intervention_preserves_semantics
            and self.alternative_is_distinguishable
            and self.feasible_under_frozen_contract
            and self.gap_not_covered_by_catalog
            and self.generalizable_scientific_question
            and not self.critical_findings
        )


class ResearchOpportunityMapReview(StrictFrozenModel):
    """Fail-closed review that may reject every proposed opportunity."""

    schema_version: Literal["research-opportunity-map-review-v3"] = (
        "research-opportunity-map-review-v3"
    )
    assessments: tuple[OpportunityCellAssessment, ...] = Field(
        min_length=_MIN_UNIQUE_OPPORTUNITIES,
        max_length=_OPPORTUNITY_COUNT,
    )
    accepted_cell_ids: tuple[str, ...]
    review_summary: str = Field(min_length=30)
    map_ready: bool

    @model_validator(mode="after")
    def _validate_review(self) -> ResearchOpportunityMapReview:
        expected_ids = [
            f"O{index:02d}" for index in range(1, len(self.assessments) + 1)
        ]
        actual_ids = [item.cell_id for item in self.assessments]
        if actual_ids != expected_ids:
            raise SystemPlanOpportunityMapError(
                f"机会图评审必须按顺序覆盖 O01..O07：{actual_ids}"
            )
        if len(set(self.accepted_cell_ids)) != len(self.accepted_cell_ids):
            raise SystemPlanOpportunityMapError("通过评审的机会编号不得重复")
        qualifying = tuple(
            item.cell_id for item in self.assessments if item.qualifies()
        )
        if self.accepted_cell_ids != qualifying:
            raise SystemPlanOpportunityMapError(
                "通过机会编号必须与七项硬门禁的逐格结果完全一致"
            )
        expected_ready = len(qualifying) >= _MIN_ACCEPTED_OPPORTUNITIES
        if self.map_ready != expected_ready:
            raise SystemPlanOpportunityMapError(
                "机会图 ready 状态与至少一格通过的规则矛盾"
            )
        language_failures = non_chinese_prose_fields(
            {"review_summary": self.review_summary}
        ) + non_chinese_prose_fields(
            {
                "critical_findings": tuple(
                    finding
                    for assessment in self.assessments
                    for finding in assessment.critical_findings
                )
            },
            # Audit findings legitimately carry exact field, method, and artifact
            # identifiers.  Requiring at least half Chinese still rejects English
            # prose while avoiding false failures at the global 0.55 boundary.
            minimum_ratio=0.50,
        )
        if language_failures:
            raise SystemPlanOpportunityMapError(
                f"机会图评审不是中文：{list(language_failures)}"
            )
        return self

    def feedback(self) -> tuple[str, ...]:
        """Return exact reviewer-authored vetoes for a fresh system attempt."""

        return tuple(
            dict.fromkeys(
                (
                    self.review_summary,
                    *(
                        f"{assessment.cell_id}：{finding}"
                        for assessment in self.assessments
                        for finding in assessment.critical_findings
                    ),
                )
            )
        )


def _merge_feedback(
    existing: Sequence[str], *additional: str
) -> tuple[str, ...]:
    """Append loop diagnostics without erasing an earlier scientific veto."""

    return tuple(dict.fromkeys((*existing, *(item for item in additional if item))))


def _review_repair_monotonic_findings(
    *,
    prior_reviews: Sequence[Mapping[str, Any]],
    candidate: ResearchOpportunityMapReview,
) -> tuple[str, ...]:
    """Forbid a JSON-repair turn from weakening any earlier scientific judgment."""

    candidate_by_id = {item.cell_id: item for item in candidate.assessments}
    candidate_accepted = set(candidate.accepted_cell_ids)
    findings: list[str] = []
    for repair_index, prior in enumerate(prior_reviews, 1):
        if prior.get("map_ready") is False and candidate.map_ready:
            findings.append(
                f"第{repair_index}份待修评审已判 map_ready=false，结构修复不得改成 true"
            )
        raw_accepted = prior.get("accepted_cell_ids")
        if isinstance(raw_accepted, list | tuple):
            prior_accepted = {
                item for item in raw_accepted if isinstance(item, str)
            }
            expanded = sorted(candidate_accepted - prior_accepted)
            if expanded:
                findings.append(
                    f"第{repair_index}份待修评审未接受 {expanded}，结构修复不得扩张通过集合"
                )
        raw_assessments = prior.get("assessments")
        if not isinstance(raw_assessments, list | tuple):
            continue
        for raw_assessment in raw_assessments:
            if not isinstance(raw_assessment, Mapping):
                continue
            cell_id = raw_assessment.get("cell_id")
            if not isinstance(cell_id, str) or cell_id not in candidate_by_id:
                continue
            candidate_assessment = candidate_by_id[cell_id]
            for field_name in _OPPORTUNITY_REVIEW_GATE_FIELDS:
                if raw_assessment.get(field_name) is False and getattr(
                    candidate_assessment, field_name
                ):
                    findings.append(
                        f"{cell_id}.{field_name} 已被第{repair_index}份评审否决，"
                        "结构修复不得从 false 改为 true"
                    )
            raw_critical = raw_assessment.get("critical_findings")
            if not isinstance(raw_critical, list | tuple):
                continue
            required_findings = {
                item
                for item in raw_critical
                if isinstance(item, str)
                and not any(token in item for token in _SENTINEL_SCOPE_TOKENS)
            }
            removed = sorted(
                required_findings - set(candidate_assessment.critical_findings)
            )
            if removed:
                findings.append(
                    f"{cell_id} 的结构修复删除了既有科学否决理由：{removed}"
                )
    return tuple(dict.fromkeys(findings))


class ResearchOpportunityMapBinding(StrictFrozenModel):
    """Minimal accepted input consumed by the later divergent ideation stage."""

    opportunity_map_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    feasibility_envelope: ResearchFeasibilityEnvelope
    accepted_cells: tuple[ResearchOpportunityCell, ...] = Field(min_length=1)
    method_skill_selection: SystemPlanMethodSkillSelectionBinding | None = None

    @model_validator(mode="after")
    def _validate_binding_scope(self) -> ResearchOpportunityMapBinding:
        findings = tuple(
            finding
            for cell in self.accepted_cells
            for finding in _cell_evidence_scope_findings(
                cell=cell,
                envelope=self.feasibility_envelope,
            )
        )
        if findings:
            raise SystemPlanOpportunityMapError(
                "研究机会绑定包含不可归因的目标或证据 scope："
                + "；".join(findings)
            )
        return self


class RemovedInvalidReviewFinding(StrictFrozenModel):
    """One exact reviewer sentence removed by a declared mechanical scope rule."""

    cell_id: str = Field(pattern=r"^O0[1-7]$")
    finding_index: int = Field(ge=0)
    finding: str = Field(min_length=1)
    reason: Literal["synthetic_sentinel_scope_not_official_cell_scope"] = (
        "synthetic_sentinel_scope_not_official_cell_scope"
    )


class SystemPlanOpportunityMapArtifact(StrictFrozenModel):
    """Accepted map, independent review, and exact model-authorship receipts."""

    schema_version: Literal["system-plan-opportunity-map-v3"] = (
        "system-plan-opportunity-map-v3"
    )
    lineage_id: str = Field(min_length=1)
    authoring_attempt: int = Field(ge=1)
    feasibility_envelope: ResearchFeasibilityEnvelope
    opportunity_map: ResearchOpportunityMap
    source_opportunity_map_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    opportunity_map_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    deterministic_normalization_rule: Literal[
        "first_cell_per_evidence_target_signature_then_stable_renumber"
    ] = "first_cell_per_evidence_target_signature_then_stable_renumber"
    removed_duplicate_cell_ids: tuple[str, ...]
    source_review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_normalization_rule: Literal[
        "drop_exact_synthetic_sentinel_scope_findings_only"
    ] = "drop_exact_synthetic_sentinel_scope_findings_only"
    removed_invalid_review_findings: tuple[RemovedInvalidReviewFinding, ...]
    review: ResearchOpportunityMapReview
    accepted_cells: tuple[ResearchOpportunityCell, ...] = Field(min_length=1)
    method_skill_selection: SystemPlanMethodSkillSelectionBinding | None = None
    map_authorship_receipt_relative_path: str
    map_authorship_receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_authorship_receipt_relative_path: str
    review_authorship_receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    map_model_name: str = Field(min_length=1)
    review_model_name: str = Field(min_length=1)
    authored_by_model: Literal[True] = True
    hand_written_scientific_prose_count: Literal[0] = 0
    execution_authorized: Literal[False] = False
    is_scientific_evidence: Literal[False] = False
    created_at: datetime
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate_artifact(self) -> SystemPlanOpportunityMapArtifact:
        if not self.review.map_ready:
            raise SystemPlanOpportunityMapError(
                "规范研究机会图不得包含未通过独立评审的结果"
            )
        expected_cells = tuple(
            item
            for item in self.opportunity_map.opportunities
            if item.cell_id in self.review.accepted_cell_ids
        )
        if self.accepted_cells != expected_cells:
            raise SystemPlanOpportunityMapError("通过机会与逐格评审编号不一致")
        accepted_scope_findings = tuple(
            finding
            for cell in self.accepted_cells
            for finding in _cell_evidence_scope_findings(
                cell=cell,
                envelope=self.feasibility_envelope,
            )
        )
        if accepted_scope_findings:
            raise SystemPlanOpportunityMapError(
                "通过机会仍含不可归因或错误预算 scope："
                + "；".join(accepted_scope_findings)
            )
        expected_map_hash = canonical_model_hash(
            self.opportunity_map.model_dump(mode="json")
        )
        if self.opportunity_map_hash != expected_map_hash:
            raise SystemPlanOpportunityMapError("模型生成的研究机会图哈希不符")
        if len(set(self.removed_duplicate_cell_ids)) != len(
            self.removed_duplicate_cell_ids
        ):
            raise SystemPlanOpportunityMapError("去重移除的原始机会编号不得重复")
        if len(self.opportunity_map.opportunities) + len(
            self.removed_duplicate_cell_ids
        ) != _OPPORTUNITY_COUNT:
            raise SystemPlanOpportunityMapError("机会图稳定去重数量账本不守恒")
        removal_keys = [
            (item.cell_id, item.finding_index, item.finding)
            for item in self.removed_invalid_review_findings
        ]
        if len(set(removal_keys)) != len(removal_keys):
            raise SystemPlanOpportunityMapError("被过滤的无效评审原句不得重复")
        normalized_review_hash = canonical_model_hash(
            self.review.model_dump(mode="json")
        )
        if (
            not self.removed_invalid_review_findings
            and self.source_review_hash != normalized_review_hash
        ):
            raise SystemPlanOpportunityMapError(
                "未过滤评审原句时 source_review_hash 必须等于规范评审哈希"
            )
        if (
            self.removed_invalid_review_findings
            and self.source_review_hash == normalized_review_hash
        ):
            raise SystemPlanOpportunityMapError(
                "过滤评审原句后 source_review_hash 不得等于规范评审哈希"
            )
        expected_artifact_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"artifact_hash", "output_path"})
        )
        if self.artifact_hash != expected_artifact_hash:
            raise SystemPlanOpportunityMapError("研究机会图制品哈希不符")
        return self

    def binding(self) -> ResearchOpportunityMapBinding:
        """Return the hash-bound subset required by direction ideation."""

        return ResearchOpportunityMapBinding(
            opportunity_map_hash=self.artifact_hash,
            feasibility_envelope=self.feasibility_envelope,
            accepted_cells=self.accepted_cells,
            method_skill_selection=self.method_skill_selection,
        )


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _average_ranks(values: Sequence[float]) -> tuple[float, ...]:
    ordered = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    ranks = [0.0] * len(values)
    start = 0
    while start < len(ordered):
        stop = start + 1
        while stop < len(ordered) and ordered[stop][1] == ordered[start][1]:
            stop += 1
        average_rank = (start + 1 + stop) / 2.0
        for position in range(start, stop):
            ranks[ordered[position][0]] = average_rank
        start = stop
    return tuple(ranks)


def _spearman_rho(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 3:
        return None
    if len(set(left)) < 2 or len(set(right)) < 2:
        return None
    left_ranks = _average_ranks(left)
    right_ranks = _average_ranks(right)
    left_mean = math.fsum(left_ranks) / len(left_ranks)
    right_mean = math.fsum(right_ranks) / len(right_ranks)
    numerator = math.fsum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left_ranks, right_ranks, strict=True)
    )
    left_square = math.fsum((value - left_mean) ** 2 for value in left_ranks)
    right_square = math.fsum((value - right_mean) ** 2 for value in right_ranks)
    denominator = math.sqrt(left_square * right_square)
    if denominator == 0.0:
        return None
    return round(max(-1.0, min(1.0, numerator / denominator)), 12)


def _association_diagnostics(
    feature_values: Sequence[float],
    effects: Sequence[float],
) -> tuple[float, tuple[float, ...]] | None:
    """Return an overall rho plus complete leave-one-system-out diagnostics."""

    if len(feature_values) != len(effects) or len(feature_values) < 4:
        return None
    rho = _spearman_rho(feature_values, effects)
    if rho is None:
        return None
    leave_one_out: list[float] = []
    for omitted in range(len(feature_values)):
        omitted_features = tuple(
            value for index, value in enumerate(feature_values) if index != omitted
        )
        omitted_effects = tuple(
            value for index, value in enumerate(effects) if index != omitted
        )
        omitted_rho = _spearman_rho(omitted_features, omitted_effects)
        if omitted_rho is None:
            return None
        leave_one_out.append(omitted_rho)
    return rho, tuple(leave_one_out)


def _build_exploratory_profile_effect_association_panel(
    *,
    profiles: Sequence[PublicSystemDataProfile],
    retained_result: Mapping[str, Any],
) -> ExploratoryProfileEffectAssociationPanel | None:
    """Associate every estimable predeclared profile feature with signed effects."""

    profiles_by_name = {profile.system_name: profile for profile in profiles}
    feature_values = {
        profile.system_name: public_data_profile_feature_values(profile)
        for profile in profiles
    }
    predeclared_features = tuple(
        sorted(
            {
                feature_name
                for values in feature_values.values()
                for feature_name in values
            }
        )
    )
    raw_effects = [
        item
        for item in retained_result.get("system_effects") or []
        if isinstance(item, Mapping)
        and item.get("system_name")
        and isinstance(item.get("paired_log_effect"), int | float)
        and math.isfinite(float(item["paired_log_effect"]))
    ]
    effects = {
        str(item.get("system_name")): float(item["paired_log_effect"])
        for item in raw_effects
        if isinstance(item.get("candidate_cell_count"), int)
        and isinstance(item.get("candidate_success_count"), int)
        and int(item["candidate_success_count"])
        == int(item["candidate_cell_count"])
        and item.get("baseline_available") is True
    }
    excluded_incomplete = tuple(
        sorted(
            str(item.get("system_name"))
            for item in raw_effects
            if str(item.get("system_name")) not in effects
        )
    )
    associations: list[ExploratoryFeatureAssociation] = []
    for feature_name in predeclared_features:
        rows = [
            (
                system_name,
                profiles_by_name[system_name].data_type,
                values[feature_name],
                effects[system_name],
            )
            for system_name, values in sorted(feature_values.items())
            if feature_name in values and system_name in effects
        ]
        if len(rows) < 4:
            continue
        observed_features = tuple(float(item[2]) for item in rows)
        observed_effects = tuple(float(item[3]) for item in rows)
        diagnostics = _association_diagnostics(
            observed_features,
            observed_effects,
        )
        if diagnostics is None:
            continue
        rho, leave_one_out = diagnostics
        sign_consistent = all(item >= 0.0 for item in leave_one_out) or all(
            item <= 0.0 for item in leave_one_out
        )
        within_data_type: list[WithinDataTypeFeatureAssociation] = []
        for data_type in ("ode", "pde"):
            stratum_rows = [item for item in rows if item[1] == data_type]
            stratum_features = tuple(float(item[2]) for item in stratum_rows)
            stratum_effects = tuple(float(item[3]) for item in stratum_rows)
            stratum_diagnostics = _association_diagnostics(
                stratum_features,
                stratum_effects,
            )
            if stratum_diagnostics is None:
                continue
            stratum_rho, stratum_leave_one_out = stratum_diagnostics
            stratum_sign_consistent = all(
                item >= 0.0 for item in stratum_leave_one_out
            ) or all(item <= 0.0 for item in stratum_leave_one_out)
            within_data_type.append(
                WithinDataTypeFeatureAssociation(
                    data_type=data_type,
                    system_names=tuple(item[0] for item in stratum_rows),
                    feature_values=stratum_features,
                    paired_log_effects=stratum_effects,
                    spearman_rho=stratum_rho,
                    leave_one_system_out_rhos=stratum_leave_one_out,
                    leave_one_system_out_minimum=min(stratum_leave_one_out),
                    leave_one_system_out_maximum=max(stratum_leave_one_out),
                    leave_one_system_out_sign_consistent=(
                        stratum_sign_consistent
                    ),
                )
            )
        associations.append(
            ExploratoryFeatureAssociation(
                feature_name=feature_name,
                system_names=tuple(item[0] for item in rows),
                data_types=tuple(item[1] for item in rows),
                feature_values=observed_features,
                paired_log_effects=observed_effects,
                spearman_rho=rho,
                leave_one_system_out_rhos=leave_one_out,
                leave_one_system_out_minimum=min(leave_one_out),
                leave_one_system_out_maximum=max(leave_one_out),
                leave_one_system_out_sign_consistent=sign_consistent,
                within_data_type_associations=tuple(within_data_type),
                overall_data_type_confounding_not_ruled_out=True,
            )
        )
    if not associations:
        return None
    payload: dict[str, Any] = {
        "schema_version": "exploratory-profile-effect-association-panel-v1",
        "source_lineage_id": str(retained_result.get("lineage_id") or ""),
        "source_package_hash": str(retained_result.get("package_hash") or ""),
        "source_profile_hashes": {
            profile.system_name: profile.profile_hash for profile in profiles
        },
        "source_effect_coverage_rule": (
            "candidate_success_count_equals_candidate_cell_count_and_baseline_available"
        ),
        "excluded_incomplete_systems": list(excluded_incomplete),
        "effect_field": "paired_log_effect",
        "predeclared_feature_names": list(predeclared_features),
        "associations": [item.model_dump(mode="json") for item in associations],
        "exploratory_only": True,
        "causal_interpretation_authorized": False,
        "multiple_comparisons_adjusted": False,
        "confirmatory_use_requires_new_preregistered_test": True,
    }
    payload["panel_hash"] = canonical_model_hash(payload)
    return ExploratoryProfileEffectAssociationPanel.model_validate(payload)


def _build_cross_lineage_system_effect_matrix(
    retained_results: Sequence[Mapping[str, Any]],
) -> CrossLineageSystemEffectMatrix | None:
    """Build a complete comparable matrix without interpreting method components."""

    candidates: list[ComparableLineageCandidate] = []
    coverage: list[CrossLineageEffectObservation] = []
    for result in retained_results:
        identity = _mapping(result.get("identity_binding"))
        lineage_id = str(result.get("lineage_id") or "")
        package_hash = str(result.get("package_hash") or "")
        candidate_id = str(result.get("selected_candidate_id") or "")
        candidate_summary = str(result.get("selected_candidate_summary") or "")
        required_identity = (
            "plan_hash",
            "development_panel_hash",
            "runner_sha256",
            "runtime_environment_hash",
        )
        if (
            not lineage_id
            or not package_hash
            or not candidate_id
            or not candidate_summary
            or any(not identity.get(key) for key in required_identity)
            or not identity.get("conditions")
        ):
            continue
        candidate = ComparableLineageCandidate(
            lineage_id=lineage_id,
            package_hash=package_hash,
            selected_candidate_id=candidate_id,
            selected_candidate_summary=candidate_summary,
            plan_hash=str(identity["plan_hash"]),
            development_panel_hash=str(identity["development_panel_hash"]),
            runner_sha256=str(identity["runner_sha256"]),
            runtime_environment_hash=str(identity["runtime_environment_hash"]),
            conditions=tuple(str(item) for item in identity["conditions"]),
            search_freeze_receipt_issued=bool(
                result.get("search_freeze_receipt_issued")
            ),
        )
        candidates.append(candidate)
        for raw_effect in result.get("system_effects") or []:
            if not isinstance(raw_effect, Mapping):
                continue
            data_type = str(raw_effect.get("data_type") or "")
            if data_type not in {"ode", "pde"}:
                continue
            candidate_count = raw_effect.get("candidate_cell_count")
            success_count = raw_effect.get("candidate_success_count")
            if not isinstance(candidate_count, int) or not isinstance(
                success_count, int
            ):
                continue
            baseline_available = raw_effect.get("baseline_available") is True
            coverage.append(
                CrossLineageEffectObservation(
                    lineage_id=lineage_id,
                    package_hash=package_hash,
                    selected_candidate_id=candidate_id,
                    system_name=str(raw_effect.get("system_name") or ""),
                    data_type=cast(Literal["ode", "pde"], data_type),
                    candidate_median_loss=float(
                        raw_effect["candidate_median_loss"]
                    ),
                    baseline_median_loss=float(raw_effect["baseline_median_loss"]),
                    paired_log_effect=float(raw_effect["paired_log_effect"]),
                    candidate_cell_count=candidate_count,
                    candidate_success_count=success_count,
                    baseline_available=baseline_available,
                    fully_observed_pair=(
                        success_count == candidate_count and baseline_available
                    ),
                )
            )
    if len(candidates) < 2:
        return None
    candidates.sort(key=lambda item: item.lineage_id)
    coverage.sort(key=lambda item: (item.system_name, item.lineage_id))
    grouped: dict[tuple[str, Literal["ode", "pde"]], list[CrossLineageEffectObservation]] = {}
    for observation in coverage:
        if not observation.fully_observed_pair:
            continue
        grouped.setdefault(
            (observation.system_name, observation.data_type), []
        ).append(observation)
    rows = tuple(
        CrossLineageSystemEffectRow(
            system_name=system_name,
            data_type=data_type,
            observations=tuple(observations),
        )
        for (system_name, data_type), observations in sorted(grouped.items())
        if len(observations) >= 2
    )
    if not rows:
        return None
    payload: dict[str, Any] = {
        "schema_version": "cross-lineage-system-effect-matrix-v1",
        "candidates": [item.model_dump(mode="json") for item in candidates],
        "coverage_ledger": [item.model_dump(mode="json") for item in coverage],
        "comparable_system_rows": [item.model_dump(mode="json") for item in rows],
        "comparability_rule": (
            "same_plan_panel_runner_runtime_conditions_and_fully_observed_candidate_cells"
        ),
        "candidate_differences_jointly_confounded": True,
        "component_attribution_authorized": False,
        "confirmatory_use_requires_model_authored_component_ablation": True,
    }
    payload["matrix_hash"] = canonical_model_hash(payload)
    return CrossLineageSystemEffectMatrix.model_validate(payload)


def build_research_feasibility_envelope(
    frozen_evidence_context: Mapping[str, Any],
) -> ResearchFeasibilityEnvelope:
    """Mechanically index protocol boundaries and signed observations.

    This function contains no scientific interpretation.  It copies exact values
    and assigns stable local identifiers that model outputs must cite.
    """

    context = dict(frozen_evidence_context)
    parent = _mapping(context.get("immutable_parent_protocol"))
    panel = _mapping(context.get("public_development_panel"))
    current = _mapping(context.get("current_lineage_preregistered_boundaries"))
    policy = _mapping(current.get("preregistered_baseline_policy"))
    stage_breadth = _mapping(current.get("preregistered_stage_breadth"))
    panel_systems = {
        str(item.get("system_name")): str(item.get("data_type"))
        for item in panel.get("systems", [])
        if isinstance(item, Mapping)
        and item.get("system_name")
        and item.get("data_type") in {"ode", "pde"}
    }

    eligible: list[EligibleResearchSystem] = []
    excluded: list[ExcludedResearchSystem] = []
    policy_systems = [
        item for item in policy.get("systems", []) if isinstance(item, Mapping)
    ]
    if policy_systems:
        for item in policy_systems:
            name = str(item.get("system_name") or "")
            data_type = str(item.get("data_type") or panel_systems.get(name, ""))
            if not name or data_type not in {"ode", "pde"}:
                continue
            if item.get("handling") == "paired_against_pinned_baseline":
                eligible.append(
                    EligibleResearchSystem(
                        system_name=name,
                        data_type=cast(Literal["ode", "pde"], data_type),
                    )
                )
            else:
                excluded.append(
                    ExcludedResearchSystem(
                        system_name=name,
                        data_type=cast(Literal["ode", "pde"], data_type),
                        handling=str(item.get("handling") or "excluded"),
                        mechanism=(
                            str(item["mechanism"]) if item.get("mechanism") else None
                        ),
                    )
                )
    else:
        eligible = [
            EligibleResearchSystem(
                system_name=name,
                data_type=cast(Literal["ode", "pde"], data_type),
            )
            for name, data_type in panel_systems.items()
        ]
    if not eligible:
        raise SystemPlanOpportunityMapError(
            "冻结证据中没有可进入研究计划的 preregistered eligible system"
        )

    facts: list[EvidenceFact] = []

    def add_fact(kind: str, scope: str, locator: str, value: Any) -> None:
        facts.append(
            EvidenceFact(
                fact_id=f"E{len(facts) + 1:03d}",
                fact_kind=kind,  # type: ignore[arg-type]
                scope=scope,  # type: ignore[arg-type]
                source_locator=locator,
                value=value,
            )
        )

    add_fact(
        "eligible_systems",
        "current_preregistered_policy",
        "current_lineage_preregistered_boundaries.preregistered_baseline_policy.systems",
        [item.model_dump(mode="json") for item in eligible],
    )
    add_fact(
        "excluded_systems",
        "current_preregistered_policy",
        "current_lineage_preregistered_boundaries.preregistered_baseline_policy.systems",
        [item.model_dump(mode="json") for item in excluded],
    )
    add_fact(
        "data_boundary",
        "public_development_panel",
        "public_development_panel",
        {
            "conditions": list(panel.get("conditions") or []),
            "seeds": list(panel.get("seeds") or []),
            "system_count": len(panel_systems),
        },
    )
    raw_profiles = context.get("public_development_data_profiles") or []
    profiles = tuple(
        PublicSystemDataProfile.model_validate(item)
        for item in raw_profiles
        if isinstance(item, Mapping)
    )
    profile_names = {item.system_name for item in profiles}
    eligible_names = {item.system_name for item in eligible}
    if len(profile_names) != len(profiles) or profile_names != eligible_names:
        raise SystemPlanOpportunityMapError(
            "公开数据画像必须恰好覆盖全部可研究系统："
            f"missing={sorted(eligible_names - profile_names)}, "
            f"extra={sorted(profile_names - eligible_names)}"
        )
    for profile in profiles:
        add_fact(
            "data_profile",
            "public_development_data_profile",
            f"public_development_data_profiles.{profile.system_name}",
            public_data_profile_evidence_view(profile),
        )
    add_fact(
        "protocol_constraint",
        "synthetic_sentinel_contract",
        "immutable_parent_protocol.contract_gate",
        _mapping(parent.get("contract_gate")),
    )
    add_fact(
        "protocol_constraint",
        "official_development_estimand",
        "immutable_parent_protocol.estimand",
        _mapping(parent.get("estimand")),
    )
    add_fact(
        "protocol_constraint",
        "official_development_budget",
        "immutable_parent_protocol.search_budget",
        _mapping(parent.get("search_budget")),
    )
    add_fact(
        "stage_boundary",
        "current_stage_boundary",
        "current_lineage_preregistered_boundaries.preregistered_stage_breadth",
        stage_breadth,
    )
    retained = context.get("retained_signed_prior_results") or []
    for lineage_index, raw_result in enumerate(retained, 1):
        if not isinstance(raw_result, Mapping):
            continue
        result = dict(raw_result)
        root = f"retained_signed_prior_results[{lineage_index}]"
        add_fact(
            "candidate_provenance",
            "retained_selected_candidate_metadata",
            root,
            {
                key: result.get(key)
                for key in (
                    "lineage_id",
                    "package_hash",
                    "selected_candidate_id",
                    "selection_basis",
                    "selected_candidate_summary",
                    "search_freeze_receipt_issued",
                )
            },
        )
        add_fact(
            "aggregate_result",
            "retained_selected_candidate_full_evaluation",
            f"{root}.aggregate_results",
            _mapping(result.get("aggregate_results")),
        )
        for gate_name, passed in sorted(
            _mapping(result.get("gate_checks")).items()
        ):
            add_fact(
                "gate_check",
                "retained_selected_candidate_adjudication",
                f"{root}.gate_checks.{gate_name}",
                {"gate_name": gate_name, "passed": passed},
            )
        for status in result.get("cell_status_counts") or []:
            if isinstance(status, Mapping):
                add_fact(
                    "status_count",
                    "retained_all_candidates_all_stages",
                    f"{root}.cell_status_counts",
                    dict(status),
                )
        for failure in result.get("failure_reason_counts") or []:
            if isinstance(failure, Mapping):
                add_fact(
                    "failure_count",
                    "retained_all_candidates_all_stages",
                    f"{root}.failure_reason_counts",
                    dict(failure),
                )
        for effect in result.get("system_effects") or []:
            if isinstance(effect, Mapping):
                add_fact(
                    "system_effect",
                    "retained_selected_candidate_full_evaluation",
                    f"{root}.system_effects",
                    {
                        **dict(effect),
                        "lineage_id": result.get("lineage_id"),
                        "package_hash": result.get("package_hash"),
                        "selected_candidate_id": result.get(
                            "selected_candidate_id"
                        ),
                    },
                )
        association_panel = _build_exploratory_profile_effect_association_panel(
            profiles=profiles,
            retained_result=result,
        )
        if association_panel is not None:
            add_fact(
                "profile_effect_association",
                "retained_selected_candidate_exploratory_profile_association",
                f"{root}.exploratory_profile_effect_associations",
                association_panel.model_dump(mode="json"),
            )
    retained_mappings = tuple(
        dict(item) for item in retained if isinstance(item, Mapping)
    )
    cross_lineage_matrix = _build_cross_lineage_system_effect_matrix(
        retained_mappings
    )
    if cross_lineage_matrix is not None:
        add_fact(
            "cross_lineage_effect_matrix",
            "retained_selected_candidates_cross_lineage_full_evaluation",
            "retained_signed_prior_results.cross_lineage_system_effect_matrix",
            cross_lineage_matrix.model_dump(mode="json"),
        )

    contract_gate = _mapping(parent.get("contract_gate"))
    search_budget = _mapping(parent.get("search_budget"))
    execution_semantics = {
        "synthetic_sentinel_budget": {
            "scope": "small_synthetic_contract_sentinels_only",
            "maximum_fit_seconds_per_sentinel": contract_gate.get(
                "maximum_fit_seconds_per_sentinel"
            ),
            "maximum_memory_mb": contract_gate.get("maximum_memory_mb"),
        },
        "official_development_cell_budget": {
            "scope": "each_official_development_system_condition_seed_cell",
            "maximum_seconds_per_cell": search_budget.get(
                "maximum_seconds_per_cell"
            ),
            "maximum_memory_mb_per_cell": search_budget.get(
                "maximum_memory_mb_per_cell"
            ),
            "maximum_cpu_cores_per_cell": search_budget.get(
                "maximum_cpu_cores_per_cell"
            ),
        },
        "equation_output_rule": {
            "free_symbol_count_maximum": contract_gate.get(
                "free_symbol_count_maximum"
            ),
            "concrete_numeric_equations_required": contract_gate.get(
                "concrete_numeric_equations_required"
            ),
            "numeric_literals_are_free_symbols": False,
        },
        "scope_join_rules": [
            "failure_counts_cover_all_candidates_and_stages_not_selected_systems",
            "system_effects_cover_the_selected_candidate_full_evaluation",
            "system_identifiers_do_not_measure_stiffness_dimension_terms_or_physics",
            "sentinel_budget_and_official_cell_budget_have_different_scopes",
        ],
    }
    payload: dict[str, Any] = {
        "schema_version": "research-feasibility-envelope-v2",
        "source_context_hash": canonical_model_hash(context),
        "eligible_systems": [item.model_dump(mode="json") for item in eligible],
        "excluded_systems": [item.model_dump(mode="json") for item in excluded],
        "conditions": list(panel.get("conditions") or []),
        "seeds": list(panel.get("seeds") or []),
        "contract_gate": contract_gate,
        "estimand": _mapping(parent.get("estimand")),
        "search_budget": search_budget,
        "stage_breadth": stage_breadth,
        "execution_semantics": execution_semantics,
        "evidence_facts": [item.model_dump(mode="json") for item in facts],
    }
    if not payload["conditions"] or not payload["seeds"]:
        raise SystemPlanOpportunityMapError("冻结开发面板缺少 conditions 或 seeds")
    payload["envelope_hash"] = canonical_model_hash(payload)
    return ResearchFeasibilityEnvelope.model_validate(payload)


def _catalog_payload(
    retrieved_catalog: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "index": index,
            "title": item.get("title"),
            "publication_date": item.get("publication_date"),
            "doi": item.get("doi"),
            "url": item.get("url"),
            "abstract": str(item.get("abstract") or "")[:1_200],
        }
        for index, item in enumerate(retrieved_catalog, 1)
    ]


def _method_skill_context_message(
    selection: SystemPlanMethodSkillSelectionBinding,
) -> dict[str, str]:
    """Materialize selected project skills as a distinct, hash-bound message."""

    return {
        "role": "user",
        "content": json.dumps(
            {
                "context_kind": "selected_project_method_skills",
                "selection_artifact_hash": selection.selection_artifact_hash,
                "system_authored_skill_selection": selection.selection.model_dump(
                    mode="json"
                ),
                "selected_method_skills": [
                    item.model_dump(mode="json")
                    for item in selection.selected_skills
                ],
                "use_boundary": (
                    "技能只约束推理方法，不是事实、文献、假设、计划或实验结果。"
                ),
            },
            ensure_ascii=False,
        ),
    }


def _method_skill_selection_from_receipt(
    receipt: ModelAuthorshipReceipt,
) -> SystemPlanMethodSkillSelectionBinding | None:
    """Recover and validate the distinct method-skill message from a receipt."""

    selections: list[SystemPlanMethodSkillSelectionBinding] = []
    for message in receipt.messages:
        try:
            payload = json.loads(message.get("content", ""))
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(payload, Mapping) or payload.get("context_kind") != (
            "selected_project_method_skills"
        ):
            continue
        try:
            selection = SystemPlanMethodSkillSelectionBinding.model_validate(
                {
                    "selection_artifact_hash": payload["selection_artifact_hash"],
                    "selection": payload["system_authored_skill_selection"],
                    "selected_skills": payload["selected_method_skills"],
                }
            )
        except (KeyError, ValidationError, ValueError) as exc:
            raise SystemPlanOpportunityMapError(
                "回执中的方法技能绑定无效"
            ) from exc
        for skill in selection.selected_skills:
            actual_hash = hashlib.sha256(skill.content.encode("utf-8")).hexdigest()
            if actual_hash != skill.content_sha256:
                raise SystemPlanOpportunityMapError(
                    f"回执中的方法技能内容哈希不符：{skill.skill_id}"
                )
        selections.append(selection)
    if not selections:
        return None
    if any(item != selections[0] for item in selections[1:]):
        raise SystemPlanOpportunityMapError("同一回执包含互相矛盾的方法技能绑定")
    return selections[0]


def _shared_receipt_method_skill_selection(
    *,
    author_receipt: ModelAuthorshipReceipt,
    review_receipt: ModelAuthorshipReceipt,
) -> SystemPlanMethodSkillSelectionBinding | None:
    author_selection = _method_skill_selection_from_receipt(author_receipt)
    review_selection = _method_skill_selection_from_receipt(review_receipt)
    if author_selection != review_selection:
        raise SystemPlanOpportunityMapError(
            "作者与评审回执的方法技能绑定不一致"
        )
    if author_selection is not None:
        for label, receipt in (
            ("作者", author_receipt),
            ("评审", review_receipt),
        ):
            if len(str(receipt.reasoning_content or "").strip()) < (
                _MIN_METHOD_REASONING_CHARACTERS
            ):
                raise SystemPlanOpportunityMapError(
                    f"{label}回执缺少至少二百字符的 Qwen reasoning_content"
                )
    return author_selection


def _author_messages(
    *,
    envelope: ResearchFeasibilityEnvelope,
    retrieved_catalog: Sequence[Mapping[str, Any]],
    previous_map: Mapping[str, Any] | None,
    prior_feedback: Sequence[str],
    method_skill_selection: SystemPlanMethodSkillSelectionBinding | None = None,
) -> list[dict[str, str]]:
    profile_fact_id_by_system = {
        str(item.value.get("system_name")): item.fact_id
        for item in envelope.evidence_facts
        if item.fact_kind == "data_profile"
        and isinstance(item.value, Mapping)
        and item.value.get("system_name")
    }
    fully_observed_effects_by_system: dict[str, list[dict[str, Any]]] = {}
    for item in envelope.evidence_facts:
        if item.fact_kind != "system_effect" or not isinstance(
            item.value, Mapping
        ):
            continue
        value = item.value
        if (
            value.get("baseline_available") is not True
            or value.get("candidate_success_count")
            != value.get("candidate_cell_count")
        ):
            continue
        system_name = str(value.get("system_name") or "")
        if not system_name:
            continue
        fully_observed_effects_by_system.setdefault(system_name, []).append(
            {
                "fact_id": item.fact_id,
                "lineage_id": value.get("lineage_id"),
                "selected_candidate_id": value.get("selected_candidate_id"),
            }
        )
    for observations in fully_observed_effects_by_system.values():
        observations.sort(key=lambda item: str(item.get("lineage_id") or ""))
    matrix_facts = [
        item
        for item in envelope.evidence_facts
        if item.fact_kind == "cross_lineage_effect_matrix"
        and isinstance(item.value, Mapping)
    ]
    comparable_systems = sorted(
        {
            str(row.get("system_name"))
            for fact in matrix_facts
            for row in fact.value.get("comparable_system_rows") or []
            if isinstance(row, Mapping) and row.get("system_name")
        }
    )
    required_matrix_facts_by_system = {
        system_name: {
            "profile_fact_id": profile_fact_id_by_system.get(system_name),
            "fully_observed_system_effects": (
                fully_observed_effects_by_system.get(system_name, [])
            ),
            "cross_lineage_matrix_fact_ids": [
                item.fact_id for item in matrix_facts
            ],
        }
        for system_name in comparable_systems
    }
    association_fact_ids = [
        item.fact_id
        for item in envelope.evidence_facts
        if item.fact_kind == "profile_effect_association"
    ]
    hard_machine_contract: dict[str, Any] = {
        "contract_kind": "non_scientific_structural_output_contract",
        "exact_raw_opportunity_count": _OPPORTUNITY_COUNT,
        "minimum_chinese_characters_per_prose_field": 40,
        "prose_fields": list(_OPPORTUNITY_PROSE_FIELDS),
        "required_identification_fields": [
            "single_component_counterfactual",
            "negative_control",
            "sensitivity_control",
            "orthogonal_diagnostic",
            "independent_analysis_unit",
            "result_blind_decision_rule",
            "resource_bounded_minimal_diagnostic",
        ],
        "required_method_application_trace_fields": list(
            OpportunityMethodApplicationTrace.model_fields
        ),
        "method_trace_fact_ids_must_equal_cell_fact_ids": True,
        "method_trace_reference_indices_must_equal_cell_indices": True,
        "cross_lineage_matrix_present": bool(matrix_facts),
        "if_cross_lineage_matrix_fact_is_cited": {
            "minimum_target_system_count": 3,
            "two_target_cells_are_always_invalid": True,
            "target_system_whitelist": comparable_systems,
            "copy_every_required_fact_id_for_each_target": True,
        },
        "if_only_profile_effect_association_fact_is_cited": {
            "minimum_target_system_count": 4,
            "all_targets_must_share_one_data_type": True,
        },
    }
    if matrix_facts:
        target_system_instruction = (
            "本轮 envelope 明确存在 cross_lineage_effect_matrix。凡引用任一该类事实的机会格，"
            "eligible_target_systems 至少三项；两项在本轮无条件非法，不能被前文任何『至少两个』"
            "理解覆盖。若只引用 profile_effect_association 而不引用矩阵，则至少四个同一 "
            "data_type 的系统。"
        )
    else:
        target_system_instruction = "每个机会格至少针对两个独立系统。"
    reasoning_instruction = (
        "必须先在 reasoning_content 中按 system_authored_skill_selection 的阶段顺序完成证据"
        "账本、替代解释、单组件反事实、对照、资源和文献检查；reasoning_content 只作过程审计，"
        "不得当作证据。程序会拒绝缺失或少于二百字符的 reasoning_content。"
        if method_skill_selection is not None
        else ""
    )
    instruction = (
        "你是自主科研系统的研究机会发现器。你现在不能提出算法、完整假设或研究计划；"
        "必须先从冻结证据和真实检索目录中自主构造七个研究机会格。所有科研散文必须使用"
        "简体中文，原始系统名、论文题名和代码标识可保留原文。"
        + reasoning_instruction
        + "只返回严格 JSON："
        + json.dumps(
            ResearchOpportunityMapDraft.model_json_schema(),
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n\n每格必须按 evidence_fact_ids 引用至少两条确实存在的事实，按 "
        "literature_indices 对照至少三篇完整目录中的真实文献，并且只能选择 "
        "eligible_systems 中的系统；excluded_systems 只可用于理解边界，绝不能作为目标。"
        "每条事实的 scope 是不可更改的语义：retained_all_candidates_all_stages 的失败计数"
        "不能与 retained_selected_candidate_full_evaluation 的逐系统效应拼成同一候选的因果"
        "故事。系统名称只是标识符，不是刚性、维度、真实项数、物理量纲、混沌性或方程结构"
        "的测量；除非所引事实或真实文献直接给出，不得从名称猜测这些属性。不得从相关性直接"
        "跳到因果机制，也不得把总体输赢、单个系统差异或程序报错直接解释成自然机制。"
        "execution_semantics 明确区分小型合成 sentinel 门与正式 system-condition-seed 单元"
        "预算；机会格针对正式系统，因此任何科研字段均不得使用 sentinel 的 20 秒/512 MB、"
        "fit_call_count、free_symbol_count 或其他 sentinel 门来判断正式机会的可行性。"
        "free_symbol_count=0 只禁止未绑定符号，不禁止预注册数值字面量。必须逐项写清："
        "尚未解决的证据矛盾、可操作构念、机制成立的前提、可单独"
        "操纵的因素、可测结局、一个具体替代解释、能区分两者的观测、事先方向性模式、明确"
        "反驳观测、为何不是既有组件拼接，以及在冻结预算内最可能失败之处。还必须分别填写"
        " single_component_counterfactual、negative_control、sensitivity_control、"
        "orthogonal_diagnostic、independent_analysis_unit、result_blind_decision_rule 与"
        " resource_bounded_minimal_diagnostic。这些字段的学科方法只取自独立消息中的 selected_"
        "method_skills；技能不是证据，也不得把技能中的通用检查项复制成具体科学结论。"
        "method_application_trace 是可公开审计的方法摘要，不是隐藏思维链：必须逐项复核本格"
        "全部事实编号与全部近邻文献编号，明确唯一改变组件、至少三个冻结组件、负对照、正交"
        "诊断、独立单位、目标机制/替代解释/无法判定三种结果和确定资源上界；不得写空泛套话。"
        "measurable_outcome"
        "只能定义测什么，不能预写『提升到正值』『降至零』『达到门槛』等成功结果；"
        "expected_directional_pattern 与 refuting_observation 必须分别写出目标机制和替代解释"
        "可区分的相反预期，正、负、零结果都必须可解释。\n\n"
        + target_system_instruction
        + "evidence_fact_ids 必须同时包含每个目标系统各自的 "
        "system_effect 与 data_profile 事实，目标系统集合必须与这两类逐系统事实中的 "
        "system_name 完全一致。data_profile 只给出公开数组的描述统计，不等于机制结论；"
        "未解矛盾与构念必须引用其中实际存在的可观测量，不能继续从系统名称猜方程或物理属性。"
        "retained_all_candidates_all_stages 的 status_count 或 failure_count 不能进入具体系统"
        "机会格，因为它们不能归因到入选候选或目标系统。profile_effect_association 若存在，"
        "会完整列出预声明画像特征与逐系统效果的探索性 Spearman 关联和留一系统稳定性；"
        "它没有多重比较校正，causal_interpretation_authorized=false。每项总体关联还会"
        "给出 data_types、可估计的 within_data_type_associations，并明确"
        " overall_data_type_confounding_not_ruled_out=true。不得用 ODE/PDE 之间的样本数、"
        "时间间隔或通道数差异冒充跨系统机制，也不得挑选最大相关后写成因果机制；总体相关"
        "与同类型内相关不一致时必须按混杂未排除处理。该面板只能用于形成待检验问题，并"
        "另行提出结果盲的干预、负对照或正交诊断。"
        "system_effect 中 candidate_success_count 必须等于 candidate_cell_count 且"
        " baseline_available=true 才是完整观测比较；画像—效果面板已机械排除不完整系统。"
        "若 envelope 提供 cross_lineage_effect_matrix，每格必须引用至少一个画像—效果或"
        "跨谱系面板，不能再从孤立两系统配对推广机制；七格中至少三格必须引用跨谱系矩阵。"
        "跨谱系矩阵只纳入计划、面板、运行器、环境、条件完全相同且候选单元完整成功的比较，"
        "但不同候选同时改变了多个组件，candidate_differences_jointly_confounded=true 且"
        " component_attribution_authorized=false。因此引用矩阵的机会至少选三个可比较系统，"
        "为每个目标引用至少两个完整谱系的 system_effect，并把单组件反事实消融、负对照和"
        "正交诊断作为待检验设计；绝不能把某个候选摘要中的组件直接宣布为成因。只引用"
        " profile_effect_association 而不引用矩阵的机会至少选四个同一 data_type 系统，"
        "不得混合 ODE/PDE 后解释总体相关。用户消息中的 mechanical_evidence_index 是程序"
        "从同一 envelope 无解释投影出的抄号表，不是科学建议。引用矩阵时 target systems"
        "必须严格取 hard_cross_lineage_comparable_system_whitelist，并对每个目标逐字复制"
        " required_matrix_facts_by_system 中 profile_fact_id、至少两个"
        " fully_observed_system_effects.fact_id 及 cross_lineage_matrix_fact_ids；不得再从"
        "长 envelope 猜编号。所有科研散文字段都至少写满四十个中文字符，不能用省略号缩短；"
        "必须恰好返回七个原始机会格。\n\n"
        "七格的（evidence_fact_ids 无序集合，eligible_target_systems 无序集合）组合必须两两"
        "不同；同一批事实和同一批目标即使改写构念、替代解释或措辞，仍然是重复机会。程序"
        "会稳定保留首次出现者并记录被删编号；去重后少于五格则整轮失败。\n\n"
        "七格应覆盖不同的证据矛盾与识别逻辑，而不是七种算法名字。任何构念若只是给残差、"
        "条件数、不确定性、正则化或已知统计量重新命名，应主动放弃。若文献目录已经覆盖同一"
        "识别逻辑，应主动放弃。不得声称尚未运行的结果已经发生。"
    )
    if prior_feedback:
        instruction += (
            "\n\n上一份系统机会图未获接受。若反馈只涉及 JSON、中文、编号或目标越界，"
            "仅修复机器契约；若反馈属于科学否决，不得润色被否决构念，必须从其他证据矛盾"
            "重新生成。精确反馈："
            + json.dumps(list(prior_feedback), ensure_ascii=False)
        )
    payload: dict[str, Any] = {
        "hard_machine_contract": hard_machine_contract,
        "mechanical_evidence_index": {
            "hard_cross_lineage_comparable_system_whitelist": (
                comparable_systems
            ),
            "required_matrix_facts_by_system": (
                required_matrix_facts_by_system
            ),
            "profile_fact_id_by_system": profile_fact_id_by_system,
            "fully_observed_effect_fact_ids_by_system": (
                fully_observed_effects_by_system
            ),
            "profile_effect_association_fact_ids": association_fact_ids,
            "minimum_matrix_target_system_count": 3,
            "minimum_fully_observed_lineages_per_matrix_target": 2,
        },
        "frozen_feasibility_envelope": envelope.model_dump(mode="json"),
        "retrieved_prior_work_catalog": _catalog_payload(retrieved_catalog),
    }
    if previous_map is not None:
        payload["previous_system_authored_opportunity_map"] = dict(previous_map)
    payload["final_hard_machine_contract_repeat"] = hard_machine_contract
    messages = [{"role": "system", "content": instruction}]
    if method_skill_selection is not None:
        messages.append(_method_skill_context_message(method_skill_selection))
    messages.append(
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False),
        }
    )
    return messages


def _review_messages(
    *,
    envelope: ResearchFeasibilityEnvelope,
    opportunity_map: ResearchOpportunityMap,
    retrieved_catalog: Sequence[Mapping[str, Any]],
    previous_review: Mapping[str, Any] | None,
    prior_feedback: Sequence[str],
    method_skill_selection: SystemPlanMethodSkillSelectionBinding | None = None,
) -> list[dict[str, str]]:
    reasoning_instruction = (
        "必须在 reasoning_content 中逐格应用已选择 SKILL.md 的立即否决条件并记录保留或否决"
        "路径；程序会拒绝缺失或少于二百字符的 reasoning_content。reasoning 只用于过程审计，"
        "不是科学证据。"
        if method_skill_selection is not None
        else ""
    )
    instruction = (
        "你是独立研究机会审查员，只能逐格接受或否决，不能替作者补写构念、机制、实验或"
        "研究计划。所有评审散文必须使用简体中文。"
        + reasoning_instruction
        + "必须按输入中连续的 O 编号顺序逐格检查"
        "且不多不少；输入已机械去除重复证据-目标签名。逐格检查七项不可"
        "加权硬门禁：引用事实是否真正支持未解问题而非事后故事；机制前提是否在所列目标系统"
        "中成立；操纵是否保持原始数据生成语义；预注册观测能否区分具体替代解释；冻结接口、"
        "独立分析单位和预算是否足够；完整检索目录是否尚未覆盖同一识别逻辑；无论结果正负，"
        "是否都能产生超越本仓库、本评估器和字段契约的可推广科学知识。只修复字段名、字符串"
        "匹配、超时、内存、日志或评估器契约的机会属于工程缺陷，不能通过最后一门。摘要不足以排除"
        "先前工作时不得猜测，可记录为 critical finding。每格必须填写真实存在的 "
        "supporting_fact_ids 与 supporting_literature_indices；否决理由必须由这些编号支持，"
        "critical_findings 正文中每一个 E### 编号都必须同时列入该格 supporting_fact_ids；"
        "返回前逐字扫描，不得漏列。"
        "不得凭系统名字猜测维度、刚性、真实项数或物理性质。严格遵守 evidence fact 的 scope，"
        "不得把全候选/全阶段错误计数嫁接到入选候选的逐系统效应。严格遵守 execution_semantics："
        "每个目标必须同时由自己的 system_effect 与 data_profile 支撑；data_profile 中没有出现的"
        "方程项、刚性、边界条件或自然机制仍然不得从名称补全。若作者的构念依赖画像中不存在"
        "的属性，evidence_grounded 与 prerequisite_matches_target 必须为 false。"
        "profile_effect_association 是没有多重比较校正的探索性关联，不能单独证明因果；"
        "总体关联还明确标记数据类型混杂未排除，必须核对同 ODE/PDE 内的关联，不能把"
        "跨类型样本规模、时间间隔或通道数差异解释成目标机制。"
        "cross_lineage_effect_matrix 只收录冻结身份一致且候选单元完整成功的系统比较，"
        "但候选之间多组件共同变化，所以不能直接归因某个组件；作者必须提出结果盲的单组件"
        "消融及对照。使用矩阵的机会若少于三个可比较系统、每个目标少于两个完整谱系效果，"
        "或只引用画像关联的机会少于四个同类型系统，应判 evidence_grounded=false。"
        "若机会没有独立干预、负对照或正交诊断来区分替代解释，evidence_grounded、"
        "alternative_is_distinguishable 或 generalizable_scientific_question 必须为 false。"
        "必须逐字审查 single_component_counterfactual、negative_control、sensitivity_control、"
        "orthogonal_diagnostic、independent_analysis_unit、result_blind_decision_rule 和"
        " resource_bounded_minimal_diagnostic。若反事实两臂不明确或改变超过一个组件，若负对照"
        "不能在不触发目标机制时复现混杂，若正交诊断只是主损失改名，若把 condition-seed 当作"
        "独立单位，若结果盲规则没有分别覆盖目标机制、替代解释和无法判定，或最小诊断没有"
        "无需搜索的时间/内存确定上界，相应门禁必须为 false。"
        "还必须核对 method_application_trace：verified_fact_ids 和近邻文献编号必须完整，"
        "唯一改变组件与冻结组件必须和正文同一设计，三种结果解释不得互相重叠；任何轨迹与正文"
        "矛盾、缺项或只是复述技能模板时，evidence_grounded 或 alternative_is_distinguishable"
        "必须为 false。"
        "合成 sentinel 的拟合/内存门只用于小型 sentinel，正式单元使用 official development"
        "单元预算；free_symbol_count=0 不等于禁止预注册数值常量。不得仅以『可能超时』『可能"
        "超内存』作否决，除非能引用边界并说明该机会的最小诊断为何必然越界。机会阶段只审查"
        "构念与最小可判别诊断，不要求作者已经写出完整算法参数。任一布尔项为 false 或仍有 critical "
        "finding，该格必须拒绝。可以七格全部拒绝；只要至少一格全部过门禁，map_ready 才能"
        "为 true。accepted_cell_ids 必须严格等于全部合格格，保持原顺序。不得因后续需要五个"
        "方向而放宽；后续五方向可以围绕同一合格机会采用不同机制发散。只返回严格 JSON："
        + json.dumps(
            ResearchOpportunityMapReview.model_json_schema(),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if prior_feedback:
        instruction += (
            "\n\n上一份评审未通过机器校验。保留科学判断，只修复结构、中文或编号，"
            "不得借修复改成通过。任何既有 false 门禁、拒绝编号和非 scope 类 critical "
            "finding 都不得删除或"
            "改成通过。若精确错误指出把 synthetic sentinel 契约错用于正式"
            "system-condition-seed 机会，则这部分不是可保留的科学判断：必须从 critical "
            "findings 删除 maximum_fit_seconds_per_sentinel、"
            "maximum_predict_seconds_per_query、fit_call_count、"
            "free_symbol_count_maximum、concrete_numeric_equations_required 及 20 秒/512 MB "
            "错误 scope 原句；但同一修复回合仍不得把 feasible 或其他门禁从 false 改为 true，"
            "必须保留其他模型撰写的合法否决理由。精确错误："
            + json.dumps(list(prior_feedback), ensure_ascii=False)
        )
    payload: dict[str, Any] = {
        "frozen_feasibility_envelope": envelope.model_dump(mode="json"),
        "system_authored_opportunity_map": opportunity_map.model_dump(mode="json"),
        "retrieved_prior_work_catalog": _catalog_payload(retrieved_catalog),
    }
    if previous_review is not None:
        payload["previous_system_authored_opportunity_review"] = dict(previous_review)
    messages = [{"role": "system", "content": instruction}]
    if method_skill_selection is not None:
        messages.append(_method_skill_context_message(method_skill_selection))
    messages.append(
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False, sort_keys=True),
        }
    )
    return messages


def _binding_findings(
    *,
    opportunity_map: ResearchOpportunityMap,
    envelope: ResearchFeasibilityEnvelope,
    catalog_size: int,
) -> tuple[str, ...]:
    valid_facts = {item.fact_id for item in envelope.evidence_facts}
    matrix_fact_ids = {
        item.fact_id
        for item in envelope.evidence_facts
        if item.fact_kind == "cross_lineage_effect_matrix"
    }
    eligible_systems = {item.system_name for item in envelope.eligible_systems}
    excluded_systems = {item.system_name for item in envelope.excluded_systems}
    findings: list[str] = []
    for cell in opportunity_map.opportunities:
        bad_facts = sorted(set(cell.evidence_fact_ids) - valid_facts)
        if bad_facts:
            findings.append(f"{cell.cell_id} 引用了不存在的证据事实：{bad_facts}")
        bad_literature = sorted(
            index
            for index in set(cell.literature_indices)
            if not (1 <= index <= catalog_size)
        )
        if bad_literature:
            findings.append(f"{cell.cell_id} 引用了不存在的检索目录：{bad_literature}")
        targets = set(cell.eligible_target_systems)
        bad_targets = sorted(targets - eligible_systems)
        if bad_targets:
            findings.append(f"{cell.cell_id} 目标不在可研究系统集合：{bad_targets}")
        explicitly_excluded = sorted(targets & excluded_systems)
        if explicitly_excluded:
            findings.append(f"{cell.cell_id} 违规使用已排除系统：{explicitly_excluded}")
        findings.extend(
            _cell_evidence_scope_findings(cell=cell, envelope=envelope)
        )
    if matrix_fact_ids:
        matrix_bound_count = sum(
            bool(set(cell.evidence_fact_ids) & matrix_fact_ids)
            for cell in opportunity_map.opportunities
        )
        if matrix_bound_count < 3:
            findings.append(
                "存在可比较的跨谱系效果矩阵时，七格中至少三格必须引用该矩阵并"
                "提出不同的组件级反事实消融问题"
            )
    return tuple(findings)


def _review_binding_findings(
    *,
    review: ResearchOpportunityMapReview,
    opportunity_map: ResearchOpportunityMap,
    envelope: ResearchFeasibilityEnvelope,
    catalog_size: int,
) -> tuple[str, ...]:
    valid_facts = {item.fact_id for item in envelope.evidence_facts}
    cells = {item.cell_id: item for item in opportunity_map.opportunities}
    findings: list[str] = []
    reviewed_ids = {item.cell_id for item in review.assessments}
    expected_ids = set(cells)
    if reviewed_ids != expected_ids:
        findings.append(
            "机会图评审必须恰好覆盖去重后的全部机会："
            f"missing={sorted(expected_ids - reviewed_ids)}, "
            f"extra={sorted(reviewed_ids - expected_ids)}"
        )
    for assessment in review.assessments:
        cell = cells.get(assessment.cell_id)
        if cell is None:
            continue
        fact_ids = set(assessment.supporting_fact_ids)
        invalid_facts = sorted(fact_ids - valid_facts)
        if invalid_facts:
            findings.append(
                f"{assessment.cell_id} 评审引用了不存在的证据事实：{invalid_facts}"
            )
        if not fact_ids.intersection(cell.evidence_fact_ids):
            findings.append(
                f"{assessment.cell_id} 评审没有引用该机会格自己的任何证据事实"
            )
        literature_indices = set(assessment.supporting_literature_indices)
        invalid_literature = sorted(
            index
            for index in literature_indices
            if not (1 <= index <= catalog_size)
        )
        if invalid_literature:
            findings.append(
                f"{assessment.cell_id} 评审引用了不存在的检索目录："
                f"{invalid_literature}"
            )
        if not literature_indices.intersection(cell.literature_indices):
            findings.append(
                f"{assessment.cell_id} 评审没有引用该机会格自己的任何近邻文献"
            )
        cited_in_prose = {
            match
            for finding in assessment.critical_findings
            for match in re.findall(r"E[0-9]{3}", finding)
        }
        missing_citations = sorted(cited_in_prose - fact_ids)
        if missing_citations:
            findings.append(
                f"{assessment.cell_id} 致命问题引用了未列入 supporting_fact_ids 的事实："
                f"{missing_citations}"
            )
        invalid_scope_findings = [
            finding
            for finding in assessment.critical_findings
            if any(token in finding for token in _SENTINEL_SCOPE_TOKENS)
        ]
        if invalid_scope_findings:
            findings.append(
                f"{assessment.cell_id} 错把合成 sentinel 契约用于否决正式系统机会；"
                "正式 system-condition-seed 诊断必须使用 official development cell "
                "的 300 秒/4096 MB 语义"
            )
    return tuple(findings)


def _raw_review_scope_findings(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Recover scope feedback even when another review field is inconsistent."""

    findings: list[str] = []
    for raw_assessment in payload.get("assessments") or []:
        if not isinstance(raw_assessment, Mapping):
            continue
        cell_id = str(raw_assessment.get("cell_id") or "未知机会")
        critical = raw_assessment.get("critical_findings") or []
        if any(
            isinstance(item, str)
            and any(token in item for token in _SENTINEL_SCOPE_TOKENS)
            for item in critical
        ):
            findings.append(
                f"{cell_id} 错把合成 sentinel 契约用于否决正式系统机会；"
                "必须删除相关 finding 并使用 official development cell 语义"
            )
    return tuple(findings)


def _load_retained_model_feedback(
    *,
    author_receipt_path: Path | str,
    review_receipt_path: Path | str,
    envelope: ResearchFeasibilityEnvelope,
    retrieved_catalog: Sequence[Mapping[str, Any]],
    method_skill_selection: SystemPlanMethodSkillSelectionBinding | None,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Resume only from hash-valid model receipts bound to the same frozen input."""

    author_receipt = ModelAuthorshipReceipt.model_validate_json(
        Path(author_receipt_path).read_text(encoding="utf-8")
    )
    review_receipt = ModelAuthorshipReceipt.model_validate_json(
        Path(review_receipt_path).read_text(encoding="utf-8")
    )
    if author_receipt.artifact_kind != "plan_opportunity_map":
        raise SystemPlanOpportunityMapError("续跑作者回执类型不是机会图")
    if review_receipt.artifact_kind != "plan_opportunity_map_review":
        raise SystemPlanOpportunityMapError("续跑评审回执类型不是机会图评审")
    receipt_method_skill_selection = _shared_receipt_method_skill_selection(
        author_receipt=author_receipt,
        review_receipt=review_receipt,
    )
    if receipt_method_skill_selection != method_skill_selection:
        raise SystemPlanOpportunityMapError(
            "续跑回执与当前方法技能选择不一致"
        )
    try:
        author_input = json.loads(author_receipt.messages[-1]["content"])
        review_input = json.loads(review_receipt.messages[-1]["content"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SystemPlanOpportunityMapError("续跑回执缺少可验证的结构化输入") from exc
    expected_envelope = envelope.model_dump(mode="json")
    expected_catalog = _catalog_payload(retrieved_catalog)
    if (
        author_input.get("frozen_feasibility_envelope") != expected_envelope
        or author_input.get("retrieved_prior_work_catalog") != expected_catalog
        or review_input.get("frozen_feasibility_envelope") != expected_envelope
        or review_input.get("retrieved_prior_work_catalog") != expected_catalog
    ):
        raise SystemPlanOpportunityMapError(
            "续跑回执与当前冻结证据或检索目录不一致"
        )
    draft = ResearchOpportunityMapDraft.model_validate(
        author_receipt.parsed_payload
    )
    opportunity_map, _ = _deduplicate_opportunity_map(draft)
    if review_input.get("system_authored_opportunity_map") != (
        opportunity_map.model_dump(mode="json")
    ):
        raise SystemPlanOpportunityMapError("续跑评审回执未绑定对应去重机会图")
    review = ResearchOpportunityMapReview.model_validate(
        review_receipt.parsed_payload
    )
    findings = _review_binding_findings(
        review=review,
        opportunity_map=opportunity_map,
        envelope=envelope,
        catalog_size=len(retrieved_catalog),
    )
    if findings:
        raise SystemPlanOpportunityMapError(
            "续跑评审回执引用绑定无效：" + "；".join(findings)
        )
    if review.map_ready:
        raise SystemPlanOpportunityMapError("续跑回执中的机会图已经通过，无需重写")
    return draft.model_dump(mode="json"), review.feedback()


def _receipt_path_in_output(
    *,
    receipt: ModelAuthorshipReceipt,
    output_root: Path,
) -> Path:
    """Materialize an immutable retained receipt inside a fresh artifact root."""

    source = Path(receipt.output_path).resolve()
    if source.is_relative_to(output_root):
        return source
    target = (
        output_root
        / "interactions"
        / f"retained-{receipt.interaction_id}.json"
    )
    if target.exists():
        existing = ModelAuthorshipReceipt.model_validate_json(
            target.read_text(encoding="utf-8")
        )
        if existing.receipt_hash != receipt.receipt_hash:
            raise SystemPlanOpportunityMapError(
                f"续跑回执目标已存在且内容不同：{target}"
            )
    else:
        write_json_model(target, receipt)
    return target.resolve()


def _normalize_official_review_scope(
    review: ResearchOpportunityMapReview,
) -> tuple[
    ResearchOpportunityMapReview,
    tuple[RemovedInvalidReviewFinding, ...],
    str,
]:
    """Drop only exact critical sentences that use synthetic sentinel scope.

    The operation is deliberately non-scientific: gate booleans, citations,
    accepted identifiers, and every other reviewer-authored sentence remain
    byte-for-byte unchanged.  A rejected cell must retain at least one valid
    reviewer-authored critical finding after filtering.
    """

    source_payload = review.model_dump(mode="json")
    source_review_hash = canonical_model_hash(source_payload)
    normalized_payload = dict(source_payload)
    normalized_assessments: list[dict[str, Any]] = []
    removals: list[RemovedInvalidReviewFinding] = []
    gate_fields = (
        "evidence_grounded",
        "prerequisite_matches_target",
        "intervention_preserves_semantics",
        "alternative_is_distinguishable",
        "feasible_under_frozen_contract",
        "gap_not_covered_by_catalog",
        "generalizable_scientific_question",
    )
    for source_assessment in source_payload["assessments"]:
        assessment = dict(source_assessment)
        retained_findings: list[str] = []
        for finding_index, finding in enumerate(assessment["critical_findings"]):
            if any(token in finding for token in _SENTINEL_SCOPE_TOKENS):
                removals.append(
                    RemovedInvalidReviewFinding(
                        cell_id=assessment["cell_id"],
                        finding_index=finding_index,
                        finding=finding,
                    )
                )
            else:
                retained_findings.append(finding)
        assessment["critical_findings"] = retained_findings
        if (
            not all(bool(assessment[field]) for field in gate_fields)
            and not retained_findings
        ):
            raise SystemPlanOpportunityMapError(
                f"{assessment['cell_id']} 删除错误 sentinel scope 原句后"
                "没有保留任何模型撰写的合法否决理由"
            )
        normalized_assessments.append(assessment)
    normalized_payload["assessments"] = normalized_assessments
    normalized_review = ResearchOpportunityMapReview.model_validate(
        normalized_payload
    )
    return normalized_review, tuple(removals), source_review_hash


def _finalize_opportunity_artifact(
    *,
    lineage_id: str,
    authoring_attempt: int,
    envelope: ResearchFeasibilityEnvelope,
    source_draft: ResearchOpportunityMapDraft,
    opportunity_map: ResearchOpportunityMap,
    removed_duplicate_cell_ids: tuple[str, ...],
    review: ResearchOpportunityMapReview,
    map_receipt: ModelAuthorshipReceipt,
    review_receipt: ModelAuthorshipReceipt,
    map_model_name: str,
    review_model_name: str,
    output_root: Path,
    clock: datetime | None,
    method_skill_selection: SystemPlanMethodSkillSelectionBinding | None = None,
) -> SystemPlanOpportunityMapArtifact:
    """Write one accepted artifact without adding any scientific prose."""

    normalized_review, removed_review_findings, source_review_hash = (
        _normalize_official_review_scope(review)
    )
    accepted_cells = tuple(
        item
        for item in opportunity_map.opportunities
        if item.cell_id in normalized_review.accepted_cell_ids
    )
    map_receipt_path = _receipt_path_in_output(
        receipt=map_receipt,
        output_root=output_root,
    )
    review_receipt_path = _receipt_path_in_output(
        receipt=review_receipt,
        output_root=output_root,
    )
    payload: dict[str, Any] = {
        "schema_version": "system-plan-opportunity-map-v3",
        "lineage_id": lineage_id,
        "authoring_attempt": authoring_attempt,
        "feasibility_envelope": envelope.model_dump(mode="json"),
        "opportunity_map": opportunity_map.model_dump(mode="json"),
        "source_opportunity_map_hash": canonical_model_hash(
            source_draft.model_dump(mode="json")
        ),
        "opportunity_map_hash": canonical_model_hash(
            opportunity_map.model_dump(mode="json")
        ),
        "deterministic_normalization_rule": (
            "first_cell_per_evidence_target_signature_then_stable_renumber"
        ),
        "removed_duplicate_cell_ids": list(removed_duplicate_cell_ids),
        "source_review_hash": source_review_hash,
        "review_normalization_rule": (
            "drop_exact_synthetic_sentinel_scope_findings_only"
        ),
        "removed_invalid_review_findings": [
            item.model_dump(mode="json") for item in removed_review_findings
        ],
        "review": normalized_review.model_dump(mode="json"),
        "accepted_cells": [item.model_dump(mode="json") for item in accepted_cells],
        "method_skill_selection": (
            method_skill_selection.model_dump(mode="json")
            if method_skill_selection is not None
            else None
        ),
        "map_authorship_receipt_relative_path": map_receipt_path.relative_to(
            output_root
        ).as_posix(),
        "map_authorship_receipt_hash": map_receipt.receipt_hash,
        "review_authorship_receipt_relative_path": review_receipt_path.relative_to(
            output_root
        ).as_posix(),
        "review_authorship_receipt_hash": review_receipt.receipt_hash,
        "map_model_name": map_model_name,
        "review_model_name": review_model_name,
        "authored_by_model": True,
        "hand_written_scientific_prose_count": 0,
        "execution_authorized": False,
        "is_scientific_evidence": False,
        "created_at": (clock or datetime.now(timezone.utc))
        .astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    payload["artifact_hash"] = canonical_model_hash(payload)
    output_path = output_root / _ARTIFACT_NAME
    payload["output_path"] = output_path.as_posix()
    artifact = SystemPlanOpportunityMapArtifact.model_validate(payload)
    write_json_model(output_path, artifact)
    return artifact


def run_system_plan_opportunity_map(
    *,
    lineage_id: str,
    frozen_evidence_context: Mapping[str, Any],
    retrieved_catalog: Sequence[Mapping[str, Any]],
    output_dir: Path | str,
    completion: Callable[..., LLMJsonCompletionResult] = run_llm_json_completion,
    review_completion: Callable[..., LLMJsonCompletionResult] | None = None,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    resume_author_receipt_path: Path | str | None = None,
    resume_review_receipt_path: Path | str | None = None,
    method_skill_selection: SystemPlanMethodSkillSelectionBinding | None = None,
    max_attempts: int = _MAX_MAP_ATTEMPTS,
    clock: datetime | None = None,
) -> SystemPlanOpportunityMapArtifact:
    """Author and independently audit an evidence-first research opportunity map."""

    if len(retrieved_catalog) < 3:
        raise SystemPlanOpportunityMapError("研究机会图至少需要三篇真实检索文献")
    if max_attempts < 1:
        raise SystemPlanOpportunityMapError("研究机会图尝试次数必须为正数")
    envelope = build_research_feasibility_envelope(frozen_evidence_context)
    output_root = Path(output_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    reviewer = review_completion or completion
    if (resume_author_receipt_path is None) != (
        resume_review_receipt_path is None
    ):
        raise SystemPlanOpportunityMapError(
            "续跑必须同时提供机会图作者回执与评审回执"
        )
    if resume_author_receipt_path is not None and resume_review_receipt_path is not None:
        previous_map, feedback = _load_retained_model_feedback(
            author_receipt_path=resume_author_receipt_path,
            review_receipt_path=resume_review_receipt_path,
            envelope=envelope,
            retrieved_catalog=retrieved_catalog,
            method_skill_selection=method_skill_selection,
        )
    else:
        previous_map = None
        feedback = ()

    for attempt in range(1, max_attempts + 1):
        map_draft = previous_map
        map_feedback = feedback
        opportunity_map: ResearchOpportunityMap | None = None
        accepted_source_draft: ResearchOpportunityMapDraft | None = None
        removed_duplicate_cell_ids: tuple[str, ...] = ()
        accepted_map_result: LLMJsonCompletionResult | None = None
        accepted_map_receipt: ModelAuthorshipReceipt | None = None
        for repair_attempt in range(1, _MAX_REPAIR_ATTEMPTS + 1):
            messages = _author_messages(
                envelope=envelope,
                retrieved_catalog=retrieved_catalog,
                previous_map=map_draft,
                prior_feedback=map_feedback,
                method_skill_selection=method_skill_selection,
            )
            try:
                result = completion(
                    messages=messages,
                    config_path=config_path,
                    env_path=env_path,
                    timeout_seconds=300,
                    max_tokens=18_000,
                    temperature=0.5,
                    thinking_mode="enabled",
                    thinking_budget=5_000,
                    response_schema=None,
                    response_schema_name="research_opportunity_map",
                )
            except (OSError, RuntimeError, ValueError) as exc:
                map_feedback = _merge_feedback(
                    map_feedback,
                    "机会图模型调用或 JSON 解析失败："
                    f"{type(exc).__name__}: {exc}",
                )
                continue
            interaction_id = f"system-plan-opportunity-map-attempt-{attempt:02d}"
            if repair_attempt > 1:
                interaction_id += f"-repair-{repair_attempt:02d}"
            receipt = record_model_authorship_receipt(
                artifact_kind="plan_opportunity_map",
                interaction_id=interaction_id,
                attempt=repair_attempt,
                messages=messages,
                completion=result,
                output_dir=output_root,
            )
            if isinstance(result.parsed_json, Mapping):
                map_draft = dict(result.parsed_json)
            if (
                method_skill_selection is not None
                and len(str(result.reasoning_text or "").strip())
                < _MIN_METHOD_REASONING_CHARACTERS
            ):
                map_feedback = _merge_feedback(
                    map_feedback,
                    "Qwen 未返回至少二百字符的 reasoning_content，"
                    "研究机会方法链不可审计",
                )
                continue
            try:
                candidate_draft = ResearchOpportunityMapDraft.model_validate(
                    result.parsed_json
                )
                candidate, removed_ids = _deduplicate_opportunity_map(
                    candidate_draft
                )
            except (
                ValidationError,
                SystemPlanOpportunityMapError,
                ValueError,
            ) as exc:
                map_feedback = _merge_feedback(
                    map_feedback, f"机会图结构或中文校验失败：{exc}"
                )
                continue
            binding_findings = _binding_findings(
                opportunity_map=candidate,
                envelope=envelope,
                catalog_size=len(retrieved_catalog),
            )
            if binding_findings:
                map_feedback = _merge_feedback(map_feedback, *binding_findings)
                continue
            opportunity_map = candidate
            accepted_source_draft = candidate_draft
            removed_duplicate_cell_ids = removed_ids
            accepted_map_result = result
            accepted_map_receipt = receipt
            previous_map = candidate_draft.model_dump(mode="json")
            break
        if (
            opportunity_map is None
            or accepted_map_result is None
            or accepted_map_receipt is None
            or accepted_source_draft is None
        ):
            previous_map = map_draft
            feedback = map_feedback
            continue

        previous_review: dict[str, Any] | None = None
        review_judgment_history: list[dict[str, Any]] = []
        review_feedback: tuple[str, ...] = ()
        accepted_review: ResearchOpportunityMapReview | None = None
        accepted_review_result: LLMJsonCompletionResult | None = None
        accepted_review_receipt: ModelAuthorshipReceipt | None = None
        for review_attempt in range(1, _MAX_REVIEW_REPAIR_ATTEMPTS + 1):
            messages = _review_messages(
                envelope=envelope,
                opportunity_map=opportunity_map,
                retrieved_catalog=retrieved_catalog,
                previous_review=previous_review,
                prior_feedback=review_feedback,
                method_skill_selection=method_skill_selection,
            )
            try:
                result = reviewer(
                    messages=messages,
                    config_path=config_path,
                    env_path=env_path,
                    timeout_seconds=300,
                    max_tokens=8_000,
                    temperature=0.0,
                    thinking_mode="enabled",
                    thinking_budget=5_000,
                    response_schema=None,
                    response_schema_name="research_opportunity_map_review",
                )
            except (OSError, RuntimeError, ValueError) as exc:
                review_feedback = _merge_feedback(
                    review_feedback,
                    "机会图评审模型调用或 JSON 解析失败："
                    f"{type(exc).__name__}: {exc}",
                )
                continue
            interaction_id = f"system-plan-opportunity-review-attempt-{attempt:02d}"
            if review_attempt > 1:
                interaction_id += f"-repair-{review_attempt:02d}"
            receipt = record_model_authorship_receipt(
                artifact_kind="plan_opportunity_map_review",
                interaction_id=interaction_id,
                attempt=review_attempt,
                messages=messages,
                completion=result,
                output_dir=output_root,
            )
            prior_reviews = tuple(review_judgment_history)
            if isinstance(result.parsed_json, Mapping):
                previous_review = dict(result.parsed_json)
                review_judgment_history.append(previous_review)
            if (
                method_skill_selection is not None
                and len(str(result.reasoning_text or "").strip())
                < _MIN_METHOD_REASONING_CHARACTERS
            ):
                review_feedback = _merge_feedback(
                    review_feedback,
                    "Qwen 评审未返回至少二百字符的 reasoning_content，"
                    "研究机会审查路径不可审计",
                )
                continue
            try:
                review = ResearchOpportunityMapReview.model_validate(
                    result.parsed_json
                )
            except (
                ValidationError,
                SystemPlanOpportunityMapError,
                ValueError,
            ) as exc:
                review_feedback = _merge_feedback(
                    review_feedback,
                    f"机会图评审结构或逻辑校验失败：{exc}",
                )
                continue
            monotonic_findings = _review_repair_monotonic_findings(
                prior_reviews=prior_reviews,
                candidate=review,
            )
            if monotonic_findings:
                review_feedback = _merge_feedback(
                    review_feedback, *monotonic_findings
                )
                continue
            binding_findings = _review_binding_findings(
                review=review,
                opportunity_map=opportunity_map,
                envelope=envelope,
                catalog_size=len(retrieved_catalog),
            )
            if binding_findings:
                review_feedback = _merge_feedback(
                    review_feedback, *binding_findings
                )
                continue
            accepted_review = review
            accepted_review_result = result
            accepted_review_receipt = receipt
            break
        if (
            accepted_review is None
            or accepted_review_result is None
            or accepted_review_receipt is None
        ):
            feedback = review_feedback
            continue
        if not accepted_review.map_ready:
            feedback = accepted_review.feedback()
            continue

        return _finalize_opportunity_artifact(
            lineage_id=lineage_id,
            authoring_attempt=attempt,
            envelope=envelope,
            source_draft=accepted_source_draft,
            opportunity_map=opportunity_map,
            removed_duplicate_cell_ids=removed_duplicate_cell_ids,
            review=accepted_review,
            map_receipt=accepted_map_receipt,
            review_receipt=accepted_review_receipt,
            map_model_name=accepted_map_result.model_name,
            review_model_name=accepted_review_result.model_name,
            output_root=output_root,
            clock=clock,
            method_skill_selection=method_skill_selection,
        )

    raise SystemPlanOpportunityMapError(
        "系统未能产生至少一个通过独立硬门禁的研究机会；最终反馈："
        f"{list(feedback)}"
    )


def repair_system_plan_opportunity_review_from_receipts(
    *,
    lineage_id: str,
    frozen_evidence_context: Mapping[str, Any],
    retrieved_catalog: Sequence[Mapping[str, Any]],
    author_receipt_path: Path | str,
    invalid_review_receipt_path: Path | str,
    output_dir: Path | str,
    review_completion: Callable[..., LLMJsonCompletionResult] = (
        run_llm_json_completion
    ),
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    clock: datetime | None = None,
) -> SystemPlanOpportunityMapArtifact:
    """Repair only a machine-invalid review while freezing model-authored science."""

    if len(retrieved_catalog) < 3:
        raise SystemPlanOpportunityMapError("研究机会图至少需要三篇真实检索文献")
    envelope = build_research_feasibility_envelope(frozen_evidence_context)
    output_root = Path(output_dir).resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise SystemPlanOpportunityMapError(
            f"机会评审续跑目录必须为空：{output_root}"
        )
    output_root.mkdir(parents=True, exist_ok=True)
    author_receipt = ModelAuthorshipReceipt.model_validate_json(
        Path(author_receipt_path).read_text(encoding="utf-8")
    )
    invalid_review_receipt = ModelAuthorshipReceipt.model_validate_json(
        Path(invalid_review_receipt_path).read_text(encoding="utf-8")
    )
    if author_receipt.artifact_kind != "plan_opportunity_map":
        raise SystemPlanOpportunityMapError("续跑作者回执类型不是机会图")
    if invalid_review_receipt.artifact_kind != "plan_opportunity_map_review":
        raise SystemPlanOpportunityMapError("续跑评审回执类型不是机会图评审")
    method_skill_selection = _shared_receipt_method_skill_selection(
        author_receipt=author_receipt,
        review_receipt=invalid_review_receipt,
    )
    try:
        author_input = json.loads(author_receipt.messages[-1]["content"])
        review_input = json.loads(invalid_review_receipt.messages[-1]["content"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SystemPlanOpportunityMapError("续跑回执缺少可验证的结构化输入") from exc
    expected_envelope = envelope.model_dump(mode="json")
    expected_catalog = _catalog_payload(retrieved_catalog)
    if (
        author_input.get("frozen_feasibility_envelope") != expected_envelope
        or author_input.get("retrieved_prior_work_catalog") != expected_catalog
        or review_input.get("frozen_feasibility_envelope") != expected_envelope
        or review_input.get("retrieved_prior_work_catalog") != expected_catalog
    ):
        raise SystemPlanOpportunityMapError(
            "续跑回执与当前冻结证据或检索目录不一致"
        )
    source_draft = ResearchOpportunityMapDraft.model_validate(
        author_receipt.parsed_payload
    )
    opportunity_map, removed_ids = _deduplicate_opportunity_map(source_draft)
    author_findings = _binding_findings(
        opportunity_map=opportunity_map,
        envelope=envelope,
        catalog_size=len(retrieved_catalog),
    )
    if author_findings:
        raise SystemPlanOpportunityMapError(
            "续跑作者回执的事实绑定无效：" + "；".join(author_findings)
        )
    if review_input.get("system_authored_opportunity_map") != (
        opportunity_map.model_dump(mode="json")
    ):
        raise SystemPlanOpportunityMapError("续跑评审回执未绑定对应去重机会图")

    previous_review = dict(invalid_review_receipt.parsed_payload)
    review_judgment_history = [previous_review]
    try:
        parsed_invalid_review = ResearchOpportunityMapReview.model_validate(
            invalid_review_receipt.parsed_payload
        )
    except (ValidationError, SystemPlanOpportunityMapError, ValueError) as exc:
        review_feedback: tuple[str, ...] = (
            f"保留科学判断并修复评审结构或逻辑：{exc}",
            *_raw_review_scope_findings(invalid_review_receipt.parsed_payload),
        )
    else:
        review_feedback = _review_binding_findings(
            review=parsed_invalid_review,
            opportunity_map=opportunity_map,
            envelope=envelope,
            catalog_size=len(retrieved_catalog),
        )
        if not review_feedback:
            raise SystemPlanOpportunityMapError(
                "所给评审回执已通过机器语义校验，应续跑作者而非修复评审"
            )

    accepted_review: ResearchOpportunityMapReview | None = None
    accepted_result: LLMJsonCompletionResult | None = None
    accepted_receipt: ModelAuthorshipReceipt | None = None
    for repair_attempt in range(1, _MAX_REVIEW_REPAIR_ATTEMPTS + 1):
        messages = _review_messages(
            envelope=envelope,
            opportunity_map=opportunity_map,
            retrieved_catalog=retrieved_catalog,
            previous_review=previous_review,
            prior_feedback=review_feedback,
            method_skill_selection=method_skill_selection,
        )
        try:
            result = review_completion(
                messages=messages,
                config_path=config_path,
                env_path=env_path,
                timeout_seconds=300,
                max_tokens=8_000,
                temperature=0.0,
                thinking_mode="enabled",
                thinking_budget=5_000,
                response_schema=None,
                response_schema_name="research_opportunity_map_review",
            )
        except (OSError, RuntimeError, ValueError) as exc:
            review_feedback = _merge_feedback(
                review_feedback,
                "机会图评审模型调用或 JSON 解析失败："
                f"{type(exc).__name__}: {exc}",
            )
            continue
        interaction_id = "system-plan-opportunity-review-retained-repair-01"
        if repair_attempt > 1:
            interaction_id += f"-repair-{repair_attempt:02d}"
        receipt = record_model_authorship_receipt(
            artifact_kind="plan_opportunity_map_review",
            interaction_id=interaction_id,
            attempt=repair_attempt,
            messages=messages,
            completion=result,
            output_dir=output_root,
        )
        prior_reviews = tuple(review_judgment_history)
        if isinstance(result.parsed_json, Mapping):
            previous_review = dict(result.parsed_json)
            review_judgment_history.append(previous_review)
        if (
            method_skill_selection is not None
            and len(str(result.reasoning_text or "").strip())
            < _MIN_METHOD_REASONING_CHARACTERS
        ):
            review_feedback = _merge_feedback(
                review_feedback,
                "Qwen 评审未返回至少二百字符的 reasoning_content，"
                "研究机会审查路径不可审计",
            )
            continue
        try:
            review = ResearchOpportunityMapReview.model_validate(
                result.parsed_json
            )
        except (ValidationError, SystemPlanOpportunityMapError, ValueError) as exc:
            review_feedback = _merge_feedback(
                review_feedback,
                f"机会图评审结构或逻辑校验失败：{exc}",
            )
            continue
        monotonic_findings = _review_repair_monotonic_findings(
            prior_reviews=prior_reviews,
            candidate=review,
        )
        if monotonic_findings:
            review_feedback = _merge_feedback(
                review_feedback, *monotonic_findings
            )
            continue
        binding_findings = _review_binding_findings(
            review=review,
            opportunity_map=opportunity_map,
            envelope=envelope,
            catalog_size=len(retrieved_catalog),
        )
        if binding_findings:
            review_feedback = _merge_feedback(
                review_feedback, *binding_findings
            )
            continue
        accepted_review = review
        accepted_result = result
        accepted_receipt = receipt
        break
    if (
        accepted_review is None
        or accepted_result is None
        or accepted_receipt is None
    ):
        raise SystemPlanOpportunityMapError(
            "续跑评审未能通过机器语义校验：" f"{list(review_feedback)}"
        )
    if not accepted_review.map_ready:
        raise SystemPlanOpportunityMapError(
            "修复后的独立评审仍否决全部机会："
            f"{list(accepted_review.feedback())}"
        )
    return _finalize_opportunity_artifact(
        lineage_id=lineage_id,
        authoring_attempt=author_receipt.attempt,
        envelope=envelope,
        source_draft=source_draft,
        opportunity_map=opportunity_map,
        removed_duplicate_cell_ids=removed_ids,
        review=accepted_review,
        map_receipt=author_receipt,
        review_receipt=accepted_receipt,
        map_model_name=author_receipt.model_name,
        review_model_name=accepted_result.model_name,
        output_root=output_root,
        clock=clock,
        method_skill_selection=method_skill_selection,
    )


def finalize_system_plan_opportunity_review_from_receipts(
    *,
    lineage_id: str,
    frozen_evidence_context: Mapping[str, Any],
    retrieved_catalog: Sequence[Mapping[str, Any]],
    author_receipt_path: Path | str,
    review_receipt_path: Path | str,
    output_dir: Path | str,
    clock: datetime | None = None,
) -> SystemPlanOpportunityMapArtifact:
    """Finalize a retained review after one declared mechanical scope filter.

    This entry point never calls a model and never changes a scientific gate.
    It exists for hash-valid receipts whose only machine-invalid content is one
    or more complete critical-finding sentences that apply the synthetic
    sentinel contract to an official development cell.
    """

    if len(retrieved_catalog) < 3:
        raise SystemPlanOpportunityMapError("研究机会图至少需要三篇真实检索文献")
    envelope = build_research_feasibility_envelope(frozen_evidence_context)
    output_root = Path(output_dir).resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise SystemPlanOpportunityMapError(
            f"机会评审规范化目录必须为空：{output_root}"
        )

    author_receipt = ModelAuthorshipReceipt.model_validate_json(
        Path(author_receipt_path).read_text(encoding="utf-8")
    )
    review_receipt = ModelAuthorshipReceipt.model_validate_json(
        Path(review_receipt_path).read_text(encoding="utf-8")
    )
    if author_receipt.artifact_kind != "plan_opportunity_map":
        raise SystemPlanOpportunityMapError("续跑作者回执类型不是机会图")
    if review_receipt.artifact_kind != "plan_opportunity_map_review":
        raise SystemPlanOpportunityMapError("续跑评审回执类型不是机会图评审")
    method_skill_selection = _shared_receipt_method_skill_selection(
        author_receipt=author_receipt,
        review_receipt=review_receipt,
    )
    try:
        author_input = json.loads(author_receipt.messages[-1]["content"])
        review_input = json.loads(review_receipt.messages[-1]["content"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SystemPlanOpportunityMapError("续跑回执缺少可验证的结构化输入") from exc

    expected_envelope = envelope.model_dump(mode="json")
    expected_catalog = _catalog_payload(retrieved_catalog)
    if (
        author_input.get("frozen_feasibility_envelope") != expected_envelope
        or author_input.get("retrieved_prior_work_catalog") != expected_catalog
        or review_input.get("frozen_feasibility_envelope") != expected_envelope
        or review_input.get("retrieved_prior_work_catalog") != expected_catalog
    ):
        raise SystemPlanOpportunityMapError(
            "续跑回执与当前冻结证据或检索目录不一致"
        )

    source_draft = ResearchOpportunityMapDraft.model_validate(
        author_receipt.parsed_payload
    )
    opportunity_map, removed_ids = _deduplicate_opportunity_map(source_draft)
    author_findings = _binding_findings(
        opportunity_map=opportunity_map,
        envelope=envelope,
        catalog_size=len(retrieved_catalog),
    )
    if author_findings:
        raise SystemPlanOpportunityMapError(
            "续跑作者回执的事实绑定无效：" + "；".join(author_findings)
        )
    if review_input.get("system_authored_opportunity_map") != (
        opportunity_map.model_dump(mode="json")
    ):
        raise SystemPlanOpportunityMapError("续跑评审回执未绑定对应去重机会图")

    source_review = ResearchOpportunityMapReview.model_validate(
        review_receipt.parsed_payload
    )
    normalized_review, removals, _ = _normalize_official_review_scope(
        source_review
    )
    if not removals:
        raise SystemPlanOpportunityMapError(
            "所给评审没有需要机械删除的 synthetic sentinel scope 原句"
        )
    review_findings = _review_binding_findings(
        review=normalized_review,
        opportunity_map=opportunity_map,
        envelope=envelope,
        catalog_size=len(retrieved_catalog),
    )
    if review_findings:
        raise SystemPlanOpportunityMapError(
            "过滤错误 scope 后评审仍有绑定问题：" + "；".join(review_findings)
        )
    if not normalized_review.map_ready:
        raise SystemPlanOpportunityMapError(
            "过滤错误 scope 后独立评审仍否决全部机会："
            f"{list(normalized_review.feedback())}"
        )

    output_root.mkdir(parents=True, exist_ok=True)
    return _finalize_opportunity_artifact(
        lineage_id=lineage_id,
        authoring_attempt=author_receipt.attempt,
        envelope=envelope,
        source_draft=source_draft,
        opportunity_map=opportunity_map,
        removed_duplicate_cell_ids=removed_ids,
        review=source_review,
        map_receipt=author_receipt,
        review_receipt=review_receipt,
        map_model_name=author_receipt.model_name,
        review_model_name=review_receipt.model_name,
        output_root=output_root,
        clock=clock,
        method_skill_selection=method_skill_selection,
    )
