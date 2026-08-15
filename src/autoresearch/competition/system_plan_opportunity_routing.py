"""Compact, evidence-bound routing before opportunity-map worker authoring.

The current-stage Qwen model receives a mechanical projection of the frozen
envelope and assigns seven distinct, bounded worker scopes.  Python supplies no
research hypothesis, component choice, mechanism, or expected result.  It only
checks that every route is reconstructible from an independently reviewed atom
catalog, complete cross-lineage effects, public-data profile facts, and selected
real-literature records. The resulting bindings remain non-evidence and
execution-disabled.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, model_validator

from autoresearch.competition.language_guard import non_chinese_prose_fields
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.model_authorship import (
    ModelAuthorshipReceipt,
    record_model_authorship_receipt,
)
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.competition.system_plan_component_atoms import (
    SystemPlanComponentAtom,
    SystemPlanComponentAtomBinding,
)
from autoresearch.competition.system_plan_methodology import (
    SystemPlanMethodSkillSelectionBinding,
)
from autoresearch.competition.system_plan_opportunity_map import (
    CrossLineageSystemEffectMatrix,
    EvidenceFact,
    ExploratoryProfileEffectAssociationPanel,
    ResearchFeasibilityEnvelope,
)
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion

_ROUTE_IDS = tuple(f"O{index:02d}" for index in range(1, 8))
_OUTPUT_NAME = "system-plan-opportunity-routing.json"
_MAX_ROUTING_ATTEMPTS = 2
_MIN_REASONING_CHARACTERS = 200
_THINKING_BUDGET = 4_000
_LITERATURE_TITLE_LIMIT = 240
_LITERATURE_ABSTRACT_LIMIT = 360


class SystemPlanOpportunityRoutingError(RuntimeError):
    """Raised when a compact worker portfolio cannot be proved from evidence."""


class CompactEffectFactReference(StrictFrozenModel):
    """One complete per-system effect fact addressable by a worker route."""

    fact_id: str = Field(pattern=r"^E[0-9]{3}$")
    lineage_id: str = Field(min_length=1)
    selected_candidate_id: str = Field(min_length=1)
    paired_log_effect: float
    candidate_cell_count: int = Field(ge=1)
    candidate_success_count: int = Field(ge=1)


class CompactTargetEvidenceIndex(StrictFrozenModel):
    """Exact fact ledger required when one system is assigned to a worker."""

    system_name: str = Field(min_length=1)
    data_type: Literal["ode", "pde"]
    profile_fact_id: str = Field(pattern=r"^E[0-9]{3}$")
    complete_system_effects: tuple[CompactEffectFactReference, ...] = Field(
        min_length=2
    )
    cross_lineage_matrix_fact_id: str = Field(pattern=r"^E[0-9]{3}$")
    required_fact_ids: tuple[str, ...] = Field(min_length=4)

    @model_validator(mode="after")
    def _validate_index(self) -> CompactTargetEvidenceIndex:
        lineages = tuple(item.lineage_id for item in self.complete_system_effects)
        if len(set(lineages)) != len(lineages):
            raise SystemPlanOpportunityRoutingError(
                f"目标 {self.system_name} 的完整效果谱系不得重复"
            )
        expected = {
            self.profile_fact_id,
            self.cross_lineage_matrix_fact_id,
            *(item.fact_id for item in self.complete_system_effects),
        }
        if len(self.required_fact_ids) != len(set(self.required_fact_ids)):
            raise SystemPlanOpportunityRoutingError(
                f"目标 {self.system_name} 的必需事实编号不得重复"
            )
        if set(self.required_fact_ids) != expected:
            raise SystemPlanOpportunityRoutingError(
                f"目标 {self.system_name} 的必需事实账本不完整"
            )
        return self


class CompactComparableObservation(StrictFrozenModel):
    """Numeric row entry copied from the signed cross-lineage matrix."""

    lineage_id: str = Field(min_length=1)
    candidate_median_loss: float
    baseline_median_loss: float
    paired_log_effect: float


class CompactComparableSystem(StrictFrozenModel):
    """One matrix-comparable system and its signed numeric observations."""

    system_name: str = Field(min_length=1)
    data_type: Literal["ode", "pde"]
    observations: tuple[CompactComparableObservation, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def _validate_observations(self) -> CompactComparableSystem:
        lineages = tuple(item.lineage_id for item in self.observations)
        if len(set(lineages)) != len(lineages):
            raise SystemPlanOpportunityRoutingError(
                f"矩阵系统 {self.system_name} 的谱系不得重复"
            )
        return self


class CompactAssociationSystemValue(StrictFrozenModel):
    """One numeric feature/effect pair from an exploratory association panel."""

    system_name: str = Field(min_length=1)
    data_type: Literal["ode", "pde"]
    feature_value: float
    paired_log_effect: float


class CompactWithinTypeAssociation(StrictFrozenModel):
    """One within-type numeric association copied without interpretation."""

    data_type: Literal["ode", "pde"]
    system_count: int = Field(ge=4)
    spearman_rho: float = Field(ge=-1.0, le=1.0)
    leave_one_system_out_minimum: float = Field(ge=-1.0, le=1.0)
    leave_one_system_out_maximum: float = Field(ge=-1.0, le=1.0)
    leave_one_system_out_sign_consistent: bool


class CompactAssociationNumericEntry(StrictFrozenModel):
    """All relevant numeric entries for one predeclared profile feature."""

    panel_fact_id: str = Field(pattern=r"^E[0-9]{3}$")
    source_lineage_id: str = Field(min_length=1)
    feature_name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    system_values: tuple[CompactAssociationSystemValue, ...] = Field(min_length=4)
    spearman_rho: float = Field(ge=-1.0, le=1.0)
    leave_one_system_out_minimum: float = Field(ge=-1.0, le=1.0)
    leave_one_system_out_maximum: float = Field(ge=-1.0, le=1.0)
    leave_one_system_out_sign_consistent: bool
    overall_data_type_confounding_not_ruled_out: Literal[True] = True
    within_data_type_associations: tuple[CompactWithinTypeAssociation, ...]


class CompactLiteratureRecord(StrictFrozenModel):
    """Selected real paper joined back to its full retrieval-catalog record."""

    index: int = Field(ge=1)
    retrieval_index: int = Field(ge=0)
    source_record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    title: str = Field(min_length=1, max_length=_LITERATURE_TITLE_LIMIT)
    abstract_excerpt: str = Field(min_length=1, max_length=_LITERATURE_ABSTRACT_LIMIT)


class MechanicalAssignmentRationale(StrictFrozenModel):
    """Closed-vocabulary proof that a route is only a mechanical dispatch."""

    schema_version: Literal["mechanical-assignment-rationale-v1"]
    rationale_kind: Literal["冻结事实覆盖与独立核查"]
    fact_categories: tuple[
        Literal["数据画像事实"],
        Literal["完整系统效果事实"],
        Literal["跨谱系效果矩阵事实"],
    ]
    coverage_scope: Literal["本路全部目标的必需冻结事实"]
    literature_scope: Literal["本路三篇入选文献"]
    independent_check_required: Literal[True]
    scientific_inference_authorized: Literal[False]
    system_property_inference_authorized: Literal[False]
    mechanism_inference_authorized: Literal[False]
    performance_inference_authorized: Literal[False]


class CompactOpportunityRoutingContext(StrictFrozenModel):
    """Mechanical short context passed to the current-stage routing Qwen."""

    schema_version: Literal["compact-opportunity-routing-context-v4"] = (
        "compact-opportunity-routing-context-v4"
    )
    feasibility_envelope_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    component_atom_binding: SystemPlanComponentAtomBinding
    source_catalog_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_references_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_system_whitelist: tuple[str, ...] = Field(min_length=5)
    cross_lineage_matrix_fact_id: str = Field(pattern=r"^E[0-9]{3}$")
    comparable_systems_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_evidence_index: tuple[CompactTargetEvidenceIndex, ...] = Field(
        min_length=5
    )
    association_numeric_entries: tuple[CompactAssociationNumericEntry, ...]
    literature_catalog: tuple[CompactLiteratureRecord, ...] = Field(min_length=3)
    frozen_budget: dict[str, Any]
    context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_context(self) -> CompactOpportunityRoutingContext:
        if (
            self.component_atom_binding.feasibility_envelope_hash
            != self.feasibility_envelope_hash
        ):
            raise SystemPlanOpportunityRoutingError(
                "原子组件绑定与路由可行性边界哈希不一致"
            )
        index_names = tuple(item.system_name for item in self.target_evidence_index)
        if (
            len(set(self.target_system_whitelist)) != len(
                self.target_system_whitelist
            )
            or index_names != self.target_system_whitelist
        ):
            raise SystemPlanOpportunityRoutingError(
                "目标白名单与矩阵事实索引顺序不一致"
            )
        literature_indices = tuple(item.index for item in self.literature_catalog)
        if literature_indices != tuple(range(1, len(literature_indices) + 1)):
            raise SystemPlanOpportunityRoutingError("紧凑文献编号必须从一连续递增")
        retrieval_indices = tuple(
            item.retrieval_index for item in self.literature_catalog
        )
        if len(set(retrieval_indices)) != len(retrieval_indices):
            raise SystemPlanOpportunityRoutingError("入选文献检索编号不得重复")
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"context_hash"})
        )
        if self.context_hash != expected_hash:
            raise SystemPlanOpportunityRoutingError("紧凑路由上下文哈希不符")
        return self


class OpportunityWorkerRoute(StrictFrozenModel):
    """One Qwen-authored, evidence-addressed temporary-worker assignment."""

    schema_version: Literal["opportunity-worker-route-v4"]
    cell_id: str = Field(pattern=r"^O0[1-7]$")
    target_systems: tuple[str, ...] = Field(min_length=3, max_length=4)
    evidence_fact_ids: tuple[str, ...] = Field(min_length=8)
    literature_indices: tuple[int, ...] = Field(min_length=3, max_length=3)
    component_atom_id: str = Field(pattern=r"^A[0-9]{3}$")
    single_component_assignment: str = Field(min_length=20, max_length=500)
    assignment_rationale: MechanicalAssignmentRationale

    @model_validator(mode="after")
    def _validate_route(self) -> OpportunityWorkerRoute:
        for label, values in (
            ("目标系统", self.target_systems),
            ("证据事实", self.evidence_fact_ids),
            ("文献编号", self.literature_indices),
        ):
            if len(set(values)) != len(values):
                raise SystemPlanOpportunityRoutingError(
                    f"{self.cell_id} 的{label}不得重复"
                )
        if self.single_component_assignment != self.single_component_assignment.strip():
            raise SystemPlanOpportunityRoutingError(
                f"{self.cell_id} 的单组件派工不得包含首尾空白"
            )
        language_failures = non_chinese_prose_fields(
            {
                "single_component_assignment": self.single_component_assignment,
            },
            exempt_identifiers=(self.component_atom_id,),
        )
        if language_failures:
            raise SystemPlanOpportunityRoutingError(
                f"{self.cell_id} 的科研派工散文不是中文："
                f"{list(language_failures)}"
            )
        if (
            not self.single_component_assignment.startswith("待核查组件：")
            or self.single_component_assignment.count("待核查组件：") != 1
            or self.single_component_assignment.count("核查边界：") != 1
        ):
            raise SystemPlanOpportunityRoutingError(
                f"{self.cell_id} 的单组件派工格式无效"
            )
        return self


class OpportunityWorkerRoutePortfolio(StrictFrozenModel):
    """Exactly seven structurally distinct assignments authored by main Qwen."""

    schema_version: Literal["opportunity-worker-route-portfolio-v4"] = (
        "opportunity-worker-route-portfolio-v4"
    )
    target_system_whitelist: tuple[str, ...] = Field(min_length=4)
    routes: tuple[OpportunityWorkerRoute, ...] = Field(min_length=7, max_length=7)

    @model_validator(mode="after")
    def _validate_portfolio(self) -> OpportunityWorkerRoutePortfolio:
        if len(set(self.target_system_whitelist)) != len(
            self.target_system_whitelist
        ):
            raise SystemPlanOpportunityRoutingError("目标系统白名单不得重复")
        route_ids = tuple(item.cell_id for item in self.routes)
        if route_ids != _ROUTE_IDS:
            raise SystemPlanOpportunityRoutingError(
                f"派工路由必须按顺序恰好覆盖 O01..O07：{list(route_ids)}"
            )
        whitelist = set(self.target_system_whitelist)
        for route in self.routes:
            targets = set(route.target_systems)
            unknown = sorted(targets - whitelist)
            if unknown:
                raise SystemPlanOpportunityRoutingError(
                    f"{route.cell_id} 引用了白名单外目标：{unknown}"
                )
            if targets == whitelist:
                raise SystemPlanOpportunityRoutingError(
                    f"{route.cell_id} 不得全选完整目标白名单"
                )
        route_scopes = tuple(
            (item.component_atom_id, frozenset(item.target_systems))
            for item in self.routes
        )
        if len(set(route_scopes)) != len(route_scopes):
            raise SystemPlanOpportunityRoutingError(
                "七条派工的原子组件与目标集合组合必须两两不同"
            )
        return self


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _validate_method_skill_binding(
    binding: SystemPlanMethodSkillSelectionBinding,
) -> None:
    for skill in binding.selected_skills:
        actual_hash = hashlib.sha256(skill.content.encode("utf-8")).hexdigest()
        if actual_hash != skill.content_sha256:
            raise SystemPlanOpportunityRoutingError(
                f"路由方法技能内容哈希不符：{skill.skill_id}"
            )


def _compact_literature_records(
    retrieved_catalog: Sequence[Mapping[str, Any]],
    selected_references: Sequence[Mapping[str, Any]],
) -> tuple[CompactLiteratureRecord, ...]:
    catalog_by_index: dict[int, Mapping[str, Any]] = {}
    for fallback_index, item in enumerate(retrieved_catalog):
        raw_index = item.get("retrieval_index", fallback_index)
        if isinstance(raw_index, bool) or not isinstance(raw_index, int):
            raise SystemPlanOpportunityRoutingError(
                f"真实检索目录第 {fallback_index} 条的 retrieval_index 无效"
            )
        if raw_index in catalog_by_index:
            raise SystemPlanOpportunityRoutingError(
                f"真实检索目录的 retrieval_index 重复：{raw_index}"
            )
        catalog_by_index[raw_index] = item
    records: list[CompactLiteratureRecord] = []
    seen_selected: set[int] = set()
    for index, selected in enumerate(selected_references, 1):
        retrieval_index = selected.get("retrieval_index")
        if (
            isinstance(retrieval_index, bool)
            or not isinstance(retrieval_index, int)
            or retrieval_index in seen_selected
        ):
            raise SystemPlanOpportunityRoutingError(
                f"入选文献第 {index} 条的 retrieval_index 无效或重复"
            )
        seen_selected.add(retrieval_index)
        source_item = catalog_by_index.get(retrieval_index)
        if source_item is None:
            raise SystemPlanOpportunityRoutingError(
                f"入选文献检索编号不在真实目录中：{retrieval_index}"
            )
        for identity_field in ("title", "doi", "url"):
            if str(selected.get(identity_field) or "") != str(
                source_item.get(identity_field) or ""
            ):
                raise SystemPlanOpportunityRoutingError(
                    f"入选文献 {retrieval_index} 的 {identity_field} 与真实目录不一致"
                )
        title = str(source_item.get("title") or "").strip()
        if not title:
            raise SystemPlanOpportunityRoutingError(
                f"检索目录第 {retrieval_index} 条缺少真实论文题名"
            )
        abstract = str(source_item.get("abstract") or "").strip()
        if not abstract:
            raise SystemPlanOpportunityRoutingError(
                f"入选文献第 {retrieval_index} 条缺少可供新颖性核查的真实摘要"
            )
        records.append(
            CompactLiteratureRecord(
                index=index,
                retrieval_index=retrieval_index,
                source_record_hash=canonical_model_hash(dict(source_item)),
                title=title[:_LITERATURE_TITLE_LIMIT],
                abstract_excerpt=abstract[:_LITERATURE_ABSTRACT_LIMIT],
            )
        )
    if len(records) < 3:
        raise SystemPlanOpportunityRoutingError("路由前真实文献目录少于三篇")
    return tuple(records)


def _matrix_fact_and_value(
    envelope: ResearchFeasibilityEnvelope,
) -> tuple[EvidenceFact, CrossLineageSystemEffectMatrix]:
    facts = tuple(
        item
        for item in envelope.evidence_facts
        if item.fact_kind == "cross_lineage_effect_matrix"
    )
    if len(facts) != 1:
        raise SystemPlanOpportunityRoutingError(
            "短上下文派工要求恰好一个跨谱系效果矩阵事实"
        )
    try:
        matrix = CrossLineageSystemEffectMatrix.model_validate(facts[0].value)
    except (ValidationError, RuntimeError, ValueError) as exc:
        raise SystemPlanOpportunityRoutingError("跨谱系效果矩阵无效") from exc
    return facts[0], matrix


def _profile_facts_by_system(
    envelope: ResearchFeasibilityEnvelope,
) -> dict[str, EvidenceFact]:
    profiles: dict[str, EvidenceFact] = {}
    for fact in envelope.evidence_facts:
        if fact.fact_kind != "data_profile":
            continue
        value = _mapping(fact.value)
        system_name = str(value.get("system_name") or "")
        if not system_name or system_name in profiles:
            raise SystemPlanOpportunityRoutingError(
                "公开数据画像事实缺少系统名或同一系统出现多次"
            )
        profiles[system_name] = fact
    return profiles


def _complete_effect_facts_by_system_lineage(
    envelope: ResearchFeasibilityEnvelope,
) -> dict[tuple[str, str], EvidenceFact]:
    effects: dict[tuple[str, str], EvidenceFact] = {}
    for fact in envelope.evidence_facts:
        if fact.fact_kind != "system_effect":
            continue
        value = _mapping(fact.value)
        system_name = str(value.get("system_name") or "")
        lineage_id = str(value.get("lineage_id") or "")
        cell_count = value.get("candidate_cell_count")
        success_count = value.get("candidate_success_count")
        if (
            not system_name
            or not lineage_id
            or value.get("baseline_available") is not True
            or isinstance(cell_count, bool)
            or not isinstance(cell_count, int)
            or cell_count < 1
            or success_count != cell_count
        ):
            continue
        key = (system_name, lineage_id)
        if key in effects:
            raise SystemPlanOpportunityRoutingError(
                f"系统 {system_name} 在谱系 {lineage_id} 有重复完整效果事实"
            )
        effects[key] = fact
    return effects


def _compact_association_entries(
    envelope: ResearchFeasibilityEnvelope,
) -> tuple[CompactAssociationNumericEntry, ...]:
    entries: list[CompactAssociationNumericEntry] = []
    for fact in envelope.evidence_facts:
        if fact.fact_kind != "profile_effect_association":
            continue
        try:
            panel = ExploratoryProfileEffectAssociationPanel.model_validate(
                fact.value
            )
        except (ValidationError, RuntimeError, ValueError) as exc:
            raise SystemPlanOpportunityRoutingError(
                f"画像—效果关联事实无效：{fact.fact_id}"
            ) from exc
        for association in panel.associations:
            system_values = tuple(
                CompactAssociationSystemValue(
                    system_name=system_name,
                    data_type=data_type,
                    feature_value=feature_value,
                    paired_log_effect=paired_log_effect,
                )
                for system_name, data_type, feature_value, paired_log_effect in zip(
                    association.system_names,
                    association.data_types,
                    association.feature_values,
                    association.paired_log_effects,
                    strict=True,
                )
            )
            numeric_values = tuple(
                value
                for item in system_values
                for value in (item.feature_value, item.paired_log_effect)
            )
            if not all(math.isfinite(value) for value in numeric_values):
                raise SystemPlanOpportunityRoutingError(
                    f"画像—效果关联包含非有限数值：{fact.fact_id}"
                )
            entries.append(
                CompactAssociationNumericEntry(
                    panel_fact_id=fact.fact_id,
                    source_lineage_id=panel.source_lineage_id,
                    feature_name=association.feature_name,
                    system_values=system_values,
                    spearman_rho=association.spearman_rho,
                    leave_one_system_out_minimum=(
                        association.leave_one_system_out_minimum
                    ),
                    leave_one_system_out_maximum=(
                        association.leave_one_system_out_maximum
                    ),
                    leave_one_system_out_sign_consistent=(
                        association.leave_one_system_out_sign_consistent
                    ),
                    overall_data_type_confounding_not_ruled_out=(
                        association.overall_data_type_confounding_not_ruled_out
                    ),
                    within_data_type_associations=tuple(
                        CompactWithinTypeAssociation(
                            data_type=item.data_type,
                            system_count=len(item.system_names),
                            spearman_rho=item.spearman_rho,
                            leave_one_system_out_minimum=(
                                item.leave_one_system_out_minimum
                            ),
                            leave_one_system_out_maximum=(
                                item.leave_one_system_out_maximum
                            ),
                            leave_one_system_out_sign_consistent=(
                                item.leave_one_system_out_sign_consistent
                            ),
                        )
                        for item in association.within_data_type_associations
                    ),
                )
            )
    return tuple(entries)


def _compact_context_from_records(
    *,
    envelope: ResearchFeasibilityEnvelope,
    literature_records: Sequence[CompactLiteratureRecord],
    component_atom_binding: SystemPlanComponentAtomBinding,
    source_catalog_hash: str,
    selected_references_hash: str,
) -> CompactOpportunityRoutingContext:
    matrix_fact, matrix = _matrix_fact_and_value(envelope)
    eligible_types = {
        item.system_name: item.data_type for item in envelope.eligible_systems
    }
    profile_facts = _profile_facts_by_system(envelope)
    complete_effects = _complete_effect_facts_by_system_lineage(envelope)
    target_indices: list[CompactTargetEvidenceIndex] = []
    comparable_systems: list[CompactComparableSystem] = []
    for row in matrix.comparable_system_rows:
        if row.system_name not in eligible_types:
            raise SystemPlanOpportunityRoutingError(
                f"矩阵系统不在预注册可研究集合：{row.system_name}"
            )
        if eligible_types[row.system_name] != row.data_type:
            raise SystemPlanOpportunityRoutingError(
                f"矩阵系统类型与可研究白名单不一致：{row.system_name}"
            )
        profile_fact = profile_facts.get(row.system_name)
        if profile_fact is None:
            raise SystemPlanOpportunityRoutingError(
                f"矩阵系统缺少 data_profile 事实：{row.system_name}"
            )
        effect_references: list[CompactEffectFactReference] = []
        compact_observations: list[CompactComparableObservation] = []
        for observation in row.observations:
            effect_fact = complete_effects.get(
                (row.system_name, observation.lineage_id)
            )
            if effect_fact is None:
                raise SystemPlanOpportunityRoutingError(
                    f"矩阵系统 {row.system_name} 缺少谱系 "
                    f"{observation.lineage_id} 的完整 system_effect 事实"
                )
            effect = _mapping(effect_fact.value)
            if (
                effect.get("selected_candidate_id")
                != observation.selected_candidate_id
                or effect.get("package_hash") != observation.package_hash
                or effect.get("paired_log_effect")
                != observation.paired_log_effect
            ):
                raise SystemPlanOpportunityRoutingError(
                    f"矩阵与逐系统效果事实不一致：{row.system_name}/"
                    f"{observation.lineage_id}"
                )
            effect_references.append(
                CompactEffectFactReference(
                    fact_id=effect_fact.fact_id,
                    lineage_id=observation.lineage_id,
                    selected_candidate_id=observation.selected_candidate_id,
                    paired_log_effect=observation.paired_log_effect,
                    candidate_cell_count=observation.candidate_cell_count,
                    candidate_success_count=observation.candidate_success_count,
                )
            )
            compact_observations.append(
                CompactComparableObservation(
                    lineage_id=observation.lineage_id,
                    candidate_median_loss=observation.candidate_median_loss,
                    baseline_median_loss=observation.baseline_median_loss,
                    paired_log_effect=observation.paired_log_effect,
                )
            )
        effect_references.sort(key=lambda item: item.lineage_id)
        compact_observations.sort(key=lambda item: item.lineage_id)
        required_fact_ids = tuple(
            sorted(
                {
                    profile_fact.fact_id,
                    matrix_fact.fact_id,
                    *(item.fact_id for item in effect_references),
                }
            )
        )
        target_indices.append(
            CompactTargetEvidenceIndex(
                system_name=row.system_name,
                data_type=row.data_type,
                profile_fact_id=profile_fact.fact_id,
                complete_system_effects=tuple(effect_references),
                cross_lineage_matrix_fact_id=matrix_fact.fact_id,
                required_fact_ids=required_fact_ids,
            )
        )
        comparable_systems.append(
            CompactComparableSystem(
                system_name=row.system_name,
                data_type=row.data_type,
                observations=tuple(compact_observations),
            )
        )
    if len(comparable_systems) < 5:
        raise SystemPlanOpportunityRoutingError(
            "至少需要五个矩阵可比较系统才能形成七条不同的三至四目标路由"
        )
    frozen_budget = {
        "conditions": list(envelope.conditions),
        "seeds": list(envelope.seeds),
        "search_budget": envelope.search_budget,
        "stage_breadth": envelope.stage_breadth,
        "official_development_cell_budget": _mapping(
            envelope.execution_semantics.get("official_development_cell_budget")
        ),
        "estimand": envelope.estimand,
    }
    payload: dict[str, Any] = {
        "schema_version": "compact-opportunity-routing-context-v4",
        "feasibility_envelope_hash": envelope.envelope_hash,
        "component_atom_binding": component_atom_binding.model_dump(mode="json"),
        "source_catalog_hash": source_catalog_hash,
        "selected_references_hash": selected_references_hash,
        "target_system_whitelist": [
            item.system_name for item in comparable_systems
        ],
        "cross_lineage_matrix_fact_id": matrix_fact.fact_id,
        # The exact numeric matrix is already bound by the matrix fact in the
        # immutable feasibility envelope and is supplied to each scientific
        # worker.  The router only needs to prove that it selected from the
        # comparable closed set, so retain the canonical hash instead of sending
        # the same numeric observations a second time.
        "comparable_systems_hash": canonical_model_hash(
            {
                "comparable_systems": [
                    item.model_dump(mode="json") for item in comparable_systems
                ]
            }
        ),
        "target_evidence_index": [
            item.model_dump(mode="json") for item in target_indices
        ],
        # The route is only a dispatch contract. Full association panels remain in
        # the immutable feasibility envelope and later scientific stages; repeating
        # every per-system value here made the mechanical router spend most of its
        # context on evidence it cannot cite in a route.
        "association_numeric_entries": [],
        "literature_catalog": [
            item.model_dump(mode="json") for item in literature_records
        ],
        "frozen_budget": frozen_budget,
    }
    payload["context_hash"] = canonical_model_hash(payload)
    return CompactOpportunityRoutingContext.model_validate(payload)


def build_compact_opportunity_routing_context(
    *,
    feasibility_envelope: ResearchFeasibilityEnvelope,
    retrieved_catalog: Sequence[Mapping[str, Any]],
    selected_references: Sequence[Mapping[str, Any]],
    component_atom_binding: SystemPlanComponentAtomBinding,
) -> CompactOpportunityRoutingContext:
    """Project only the evidence needed for main-Qwen worker dispatch."""

    return _compact_context_from_records(
        envelope=feasibility_envelope,
        literature_records=_compact_literature_records(
            retrieved_catalog,
            selected_references,
        ),
        component_atom_binding=component_atom_binding,
        source_catalog_hash=_source_catalog_hash(retrieved_catalog),
        selected_references_hash=_selected_references_hash(selected_references),
    )


def _method_skill_context_message(
    binding: SystemPlanMethodSkillSelectionBinding,
) -> dict[str, str]:
    _validate_method_skill_binding(binding)
    return {
        "role": "user",
        "content": json.dumps(
            {
                "context_kind": "selected_project_method_skills",
                "selection_artifact_hash": binding.selection_artifact_hash,
                "system_authored_skill_selection": binding.selection.model_dump(
                    mode="json"
                ),
                "selected_method_skills": [
                    item.model_dump(mode="json") for item in binding.selected_skills
                ],
                "use_boundary": (
                    "技能只约束派工方法，不是事实、假设、科研结论或实验结果。"
                ),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
    }


def _routing_messages(
    *,
    context: CompactOpportunityRoutingContext,
    method_skill_selection: SystemPlanMethodSkillSelectionBinding,
    prior_feedback: Sequence[str] = (),
) -> list[dict[str, str]]:
    instruction = (
        "你是当前研究阶段的主 Qwen，只负责把后续研究机会检查机械分派给七个临时 worker，"
        "不得提出科研假设、算法方案、机制结论、预期结果或完整研究计划。必须开启 thinking，"
        "先在 reasoning_content 中核对独立审查通过的原子组件、矩阵可比较系统、逐系统必需"
        "事实、入选文献和冻结预算；不得从系统名称推断动力学、物理、方程、系统性质或性能"
        "机制。reasoning_content 至少二百字符，只作过程审计，不是科学证据。只返回严格 JSON："
        + json.dumps(
            OpportunityWorkerRoutePortfolio.model_json_schema(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "。target_system_whitelist 必须逐项原样复制用户消息中的同名白名单。routes 必须按"
        " O01 至 O07 排列且恰好七条；每条选择三至四个目标但不得全选完整白名单。对每个目标，"
        "evidence_fact_ids 必须完整复制 target_evidence_index.required_fact_ids 的并集，不得"
        "漏项、增项或编造编号，因此必须包含每个目标的 data_profile、至少两个不同完整谱系的"
        " system_effect 以及 cross_lineage_matrix_fact_id。每条恰好选择三个互异且存在的"
        " literature index。component_atom_id 必须逐字复制 component_atom_binding.atoms"
        " 中一个已经独立审查通过的 atom_id；不得自行截取来源、改名或拼接第二个组件。"
        "single_component_assignment 必须逐字写成『待核查组件：<逐字复制该 atom 的"
        " label_zh>（<逐字复制 atom_id>）。核查边界：仅核查这一冻结组件；其余组件、数据、"
        "条件、随机种子、预算与评分规则保持不变；不得从本路由推断效果、机制或系统性质。』。"
        "assignment_rationale 不是自由文本，必须逐字段填写 JSON Schema 中的封闭中文枚举与"
        " false/true 常量；不得增加任何解释、猜测或科学主张。所有目标的数据类型都必须"
        "包含在该 atom 的 applicable_data_types 中。允许同一个 atom 分派给不同目标集合；"
        "但七条的（component_atom_id，目标无序集合）组合必须两两不同。独立消息中的"
        " SKILL.md 只约束核查方法，不能充当证据或具体科学结论。"
    )
    if prior_feedback:
        instruction += (
            "上一轮只违反了结构或证据绑定契约；不得补写科研结论，只修复下列机械错误："
            + json.dumps(
                list(prior_feedback),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    return [
        {"role": "system", "content": instruction},
        _method_skill_context_message(method_skill_selection),
        {
            "role": "user",
            "content": json.dumps(
                {
                    "context_kind": "compact_mechanical_opportunity_routing",
                    "routing_context": context.model_dump(mode="json"),
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
        },
    ]


def _expected_single_component_assignment(atom: SystemPlanComponentAtom) -> str:
    return (
        f"待核查组件：{atom.label_zh}（{atom.atom_id}）。核查边界："
        "仅核查这一冻结组件；其余组件、数据、条件、随机种子、预算与评分规则"
        "保持不变；不得从本路由推断效果、机制或系统性质。"
    )


def _portfolio_findings(
    *,
    portfolio: OpportunityWorkerRoutePortfolio,
    context: CompactOpportunityRoutingContext,
    envelope: ResearchFeasibilityEnvelope,
) -> tuple[str, ...]:
    findings: list[str] = []
    if portfolio.target_system_whitelist != context.target_system_whitelist:
        findings.append("模型返回的目标白名单与紧凑上下文不一致")
    target_index = {item.system_name: item for item in context.target_evidence_index}
    literature_indices = {item.index for item in context.literature_catalog}
    atoms_by_id = {
        item.atom_id: item for item in context.component_atom_binding.atoms
    }
    facts_by_id = {item.fact_id: item for item in envelope.evidence_facts}
    for route in portfolio.routes:
        expected_fact_ids: set[str] = set()
        for target in route.target_systems:
            target_evidence = target_index.get(target)
            if target_evidence is None:
                findings.append(
                    f"{route.cell_id} 的目标没有矩阵可比较事实索引：{target}"
                )
                continue
            if len(
                {
                    item.lineage_id
                    for item in target_evidence.complete_system_effects
                }
            ) < 2:
                findings.append(
                    f"{route.cell_id} 的目标 {target} 少于两个不同完整谱系效果"
                )
            expected_fact_ids.update(target_evidence.required_fact_ids)
        actual_fact_ids = set(route.evidence_fact_ids)
        missing = sorted(expected_fact_ids - actual_fact_ids)
        extra = sorted(actual_fact_ids - expected_fact_ids)
        if missing:
            findings.append(f"{route.cell_id} 缺少必需事实编号：{missing}")
        if extra:
            findings.append(f"{route.cell_id} 增加了非必需事实编号：{extra}")
        if context.cross_lineage_matrix_fact_id not in actual_fact_ids:
            findings.append(f"{route.cell_id} 未引用跨谱系效果矩阵事实")
        unknown_facts = sorted(actual_fact_ids - set(facts_by_id))
        if unknown_facts:
            findings.append(f"{route.cell_id} 引用未知事实编号：{unknown_facts}")
        invalid_literature = sorted(
            set(route.literature_indices) - literature_indices
        )
        if invalid_literature:
            findings.append(
                f"{route.cell_id} 引用未知文献编号：{invalid_literature}"
            )
        atom = atoms_by_id.get(route.component_atom_id)
        if atom is None:
            findings.append(
                f"{route.cell_id} 引用了未通过独立审查的未知 atom："
                f"{route.component_atom_id}"
            )
            continue
        expected_assignment = _expected_single_component_assignment(atom)
        if route.single_component_assignment != expected_assignment:
            findings.append(
                f"{route.cell_id} 的中文派工不是冻结 atom 的确定性机械边界"
            )
        target_types = {
            target_index[target].data_type
            for target in route.target_systems
            if target in target_index
        }
        unsupported_types = sorted(
            target_types - set(atom.applicable_data_types)
        )
        if unsupported_types:
            findings.append(
                f"{route.cell_id} 的目标类型超出冻结 atom 适用范围："
                f"{unsupported_types}"
            )
    return tuple(findings)


class OpportunityWorkerBinding(StrictFrozenModel):
    """Hash-bound compact input for one temporary opportunity worker."""

    schema_version: Literal["opportunity-worker-binding-v4"] = (
        "opportunity-worker-binding-v4"
    )
    routing_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    feasibility_envelope_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    routing_context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    component_atom_binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    route: OpportunityWorkerRoute
    evidence_facts: tuple[EvidenceFact, ...] = Field(min_length=8)
    literature_records: tuple[CompactLiteratureRecord, ...] = Field(
        min_length=3, max_length=3
    )
    component_source: SystemPlanComponentAtom
    frozen_budget: dict[str, Any]
    method_skill_selection: SystemPlanMethodSkillSelectionBinding
    is_scientific_evidence: Literal[False] = False
    execution_authorized: Literal[False] = False
    binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_binding(self) -> OpportunityWorkerBinding:
        if tuple(item.fact_id for item in self.evidence_facts) != (
            self.route.evidence_fact_ids
        ):
            raise SystemPlanOpportunityRoutingError(
                "worker binding 的事实顺序与路由不一致"
            )
        if tuple(item.index for item in self.literature_records) != (
            self.route.literature_indices
        ):
            raise SystemPlanOpportunityRoutingError(
                "worker binding 的文献顺序与路由不一致"
            )
        if (
            self.component_source.atom_id != self.route.component_atom_id
        ):
            raise SystemPlanOpportunityRoutingError(
                "worker binding 的冻结原子组件与路由不一致"
            )
        _validate_method_skill_binding(self.method_skill_selection)
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"binding_hash"})
        )
        if self.binding_hash != expected_hash:
            raise SystemPlanOpportunityRoutingError("worker binding 哈希不符")
        return self


class SystemPlanOpportunityRoutingArtifact(StrictFrozenModel):
    """Persisted main-Qwen routing portfolio and exact provider receipt."""

    schema_version: Literal["system-plan-opportunity-routing-artifact-v4"] = (
        "system-plan-opportunity-routing-artifact-v4"
    )
    lineage_id: str = Field(min_length=1)
    authoring_attempt: int = Field(ge=1)
    prior_feedback: tuple[str, ...]
    feasibility_envelope: ResearchFeasibilityEnvelope
    component_atom_binding: SystemPlanComponentAtomBinding
    compact_routing_context: CompactOpportunityRoutingContext
    source_catalog_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_references_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    method_skill_selection: SystemPlanMethodSkillSelectionBinding
    portfolio: OpportunityWorkerRoutePortfolio
    provider_receipt: ModelAuthorshipReceipt
    provider_receipt_relative_path: str = Field(min_length=1)
    reasoning_required: Literal[True] = True
    reasoning_is_evidence: Literal[False] = False
    authored_by_model: Literal[True] = True
    hand_written_scientific_prose_count: Literal[0] = 0
    is_scientific_evidence: Literal[False] = False
    execution_authorized: Literal[False] = False
    created_at: datetime
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate_artifact(self) -> SystemPlanOpportunityRoutingArtifact:
        _validate_method_skill_binding(self.method_skill_selection)
        if (
            self.component_atom_binding.feasibility_envelope_hash
            != self.feasibility_envelope.envelope_hash
            or self.component_atom_binding.method_skill_selection_artifact_hash
            != self.method_skill_selection.selection_artifact_hash
            or self.compact_routing_context.component_atom_binding
            != self.component_atom_binding
            or self.compact_routing_context.source_catalog_hash
            != self.source_catalog_hash
            or self.compact_routing_context.selected_references_hash
            != self.selected_references_hash
        ):
            raise SystemPlanOpportunityRoutingError(
                "路由制品没有绑定同一可行性边界、方法技能、原子组件与文献来源"
            )
        expected_context = _compact_context_from_records(
            envelope=self.feasibility_envelope,
            literature_records=self.compact_routing_context.literature_catalog,
            component_atom_binding=self.component_atom_binding,
            source_catalog_hash=self.source_catalog_hash,
            selected_references_hash=self.selected_references_hash,
        )
        if self.compact_routing_context != expected_context:
            raise SystemPlanOpportunityRoutingError(
                "紧凑路由上下文不是完整 envelope 的确定性投影"
            )
        findings = _portfolio_findings(
            portfolio=self.portfolio,
            context=self.compact_routing_context,
            envelope=self.feasibility_envelope,
        )
        if findings:
            raise SystemPlanOpportunityRoutingError(
                "派工路由未通过确定性事实绑定：" + "；".join(findings)
            )
        if self.provider_receipt.artifact_kind != "plan_opportunity_map":
            raise SystemPlanOpportunityRoutingError("路由回执 artifact_kind 无效")
        if not self.provider_receipt.interaction_id.startswith(
            "system-plan-opportunity-routing-attempt-"
        ):
            raise SystemPlanOpportunityRoutingError("路由回执 interaction_id 无效")
        if self.provider_receipt.parsed_payload != self.portfolio.model_dump(
            mode="json"
        ):
            raise SystemPlanOpportunityRoutingError(
                "路由组合不是 provider parsed payload 的逐字段原文"
            )
        reasoning = str(self.provider_receipt.reasoning_content or "").strip()
        if len(reasoning) < _MIN_REASONING_CHARACTERS:
            raise SystemPlanOpportunityRoutingError(
                "路由回执缺少至少二百字符的 Qwen reasoning_content"
            )
        if self.provider_receipt.reasoning_transport != (
            "dashscope_enable_thinking"
        ):
            raise SystemPlanOpportunityRoutingError(
                "路由回执未记录 DashScope thinking transport"
            )
        qwen_identity = (
            self.provider_receipt.provider + " " + self.provider_receipt.model_name
        ).casefold()
        if "qwen" not in qwen_identity:
            raise SystemPlanOpportunityRoutingError("路由主模型不是 Qwen")
        expected_messages = tuple(
            _routing_messages(
                context=self.compact_routing_context,
                method_skill_selection=self.method_skill_selection,
                prior_feedback=self.prior_feedback,
            )
        )
        if self.provider_receipt.messages != expected_messages:
            raise SystemPlanOpportunityRoutingError(
                "路由回执消息不是紧凑上下文与独立 SKILL 消息的精确组合"
            )
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"artifact_hash", "output_path"})
        )
        if self.artifact_hash != expected_hash:
            raise SystemPlanOpportunityRoutingError("机会派工制品哈希不符")
        return self

    def worker_binding(self, cell_id: str) -> OpportunityWorkerBinding:
        """Materialize only one route's facts, references, budget, and SKILL."""

        route = next(
            (item for item in self.portfolio.routes if item.cell_id == cell_id),
            None,
        )
        if route is None:
            raise SystemPlanOpportunityRoutingError(
                f"机会派工制品没有路由：{cell_id}"
            )
        facts_by_id = {
            item.fact_id: item for item in self.feasibility_envelope.evidence_facts
        }
        literature_by_index = {
            item.index: item
            for item in self.compact_routing_context.literature_catalog
        }
        atom_by_id = {
            item.atom_id: item for item in self.component_atom_binding.atoms
        }
        payload: dict[str, Any] = {
            "schema_version": "opportunity-worker-binding-v4",
            "routing_artifact_hash": self.artifact_hash,
            "feasibility_envelope_hash": self.feasibility_envelope.envelope_hash,
            "routing_context_hash": self.compact_routing_context.context_hash,
            "component_atom_binding_hash": (
                self.component_atom_binding.binding_hash
            ),
            "route": route.model_dump(mode="json"),
            "evidence_facts": [
                facts_by_id[fact_id].model_dump(mode="json")
                for fact_id in route.evidence_fact_ids
            ],
            "literature_records": [
                literature_by_index[index].model_dump(mode="json")
                for index in route.literature_indices
            ],
            "component_source": atom_by_id[route.component_atom_id].model_dump(
                mode="json"
            ),
            "frozen_budget": self.compact_routing_context.frozen_budget,
            "method_skill_selection": self.method_skill_selection.model_dump(
                mode="json"
            ),
            "is_scientific_evidence": False,
            "execution_authorized": False,
        }
        payload["binding_hash"] = canonical_model_hash(payload)
        return OpportunityWorkerBinding.model_validate(payload)

    def worker_bindings(self) -> tuple[OpportunityWorkerBinding, ...]:
        """Return seven independent bindings for ephemeral worker dispatch."""

        return tuple(self.worker_binding(cell_id) for cell_id in _ROUTE_IDS)


def _source_catalog_hash(
    retrieved_catalog: Sequence[Mapping[str, Any]],
) -> str:
    return canonical_model_hash(
        {"retrieved_catalog": [dict(item) for item in retrieved_catalog]}
    )


def _selected_references_hash(
    selected_references: Sequence[Mapping[str, Any]],
) -> str:
    return canonical_model_hash(
        {"selected_references": [dict(item) for item in selected_references]}
    )


def _raw_route_validation_findings(
    payload: Mapping[str, Any],
) -> tuple[str, ...]:
    """Aggregate per-route schema/language failures for one useful Qwen retry."""

    raw_routes = payload.get("routes")
    if not isinstance(raw_routes, list | tuple):
        return ("[ROUTE_SCHEMA] routes 必须是七项数组",)
    findings: list[str] = []
    for index, raw_route in enumerate(raw_routes):
        path = f"routes[{index}]"
        if not isinstance(raw_route, Mapping):
            findings.append(f"[ROUTE_SCHEMA] {path} 必须是对象")
            continue
        try:
            OpportunityWorkerRoute.model_validate(raw_route)
        except (ValidationError, RuntimeError, ValueError) as exc:
            findings.append(f"[ROUTE_SCHEMA] {path}：{exc}")
    return tuple(findings)


def run_system_plan_opportunity_routing(
    *,
    lineage_id: str,
    feasibility_envelope: ResearchFeasibilityEnvelope,
    retrieved_catalog: Sequence[Mapping[str, Any]],
    selected_references: Sequence[Mapping[str, Any]],
    component_atom_binding: SystemPlanComponentAtomBinding,
    method_skill_selection: SystemPlanMethodSkillSelectionBinding,
    output_dir: Path | str,
    completion: Callable[..., LLMJsonCompletionResult] = run_llm_json_completion,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    max_attempts: int = _MAX_ROUTING_ATTEMPTS,
    clock: datetime | None = None,
) -> SystemPlanOpportunityRoutingArtifact:
    """Ask main Qwen for seven compact routes and fail closed on every binding."""

    if max_attempts < 1:
        raise SystemPlanOpportunityRoutingError("机会派工尝试次数必须为正数")
    _validate_method_skill_binding(method_skill_selection)
    if (
        component_atom_binding.feasibility_envelope_hash
        != feasibility_envelope.envelope_hash
        or component_atom_binding.method_skill_selection_artifact_hash
        != method_skill_selection.selection_artifact_hash
    ):
        raise SystemPlanOpportunityRoutingError(
            "原子组件目录没有绑定当前可行性边界与方法技能选择"
        )
    context = build_compact_opportunity_routing_context(
        feasibility_envelope=feasibility_envelope,
        retrieved_catalog=retrieved_catalog,
        selected_references=selected_references,
        component_atom_binding=component_atom_binding,
    )
    output_root = Path(output_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    feedback: tuple[str, ...] = ()
    source_catalog_hash = _source_catalog_hash(retrieved_catalog)
    selected_references_hash = _selected_references_hash(selected_references)
    for attempt in range(1, max_attempts + 1):
        prior_feedback = feedback
        messages = _routing_messages(
            context=context,
            method_skill_selection=method_skill_selection,
            prior_feedback=prior_feedback,
        )
        try:
            result = completion(
                messages=messages,
                config_path=config_path,
                env_path=env_path,
                timeout_seconds=300,
                max_tokens=8_000,
                temperature=0.2,
                thinking_mode="enabled",
                thinking_budget=_THINKING_BUDGET,
                response_schema=None,
                response_schema_name="system_plan_opportunity_routing",
            )
        except (OSError, RuntimeError, ValueError) as exc:
            feedback = (
                "主 Qwen 路由调用或 JSON 解析失败："
                f"{type(exc).__name__}: {exc}",
            )
            continue
        receipt = record_model_authorship_receipt(
            artifact_kind="plan_opportunity_map",
            interaction_id=(
                f"system-plan-opportunity-routing-attempt-{attempt:02d}"
            ),
            attempt=attempt,
            messages=messages,
            completion=result,
            output_dir=output_root,
            clock=clock,
        )
        qwen_identity = (result.provider + " " + result.model_name).casefold()
        if "qwen" not in qwen_identity:
            feedback = ("机会派工必须由当前阶段主 Qwen 生成",)
            continue
        reasoning = str(result.reasoning_text or "").strip()
        if len(reasoning) < _MIN_REASONING_CHARACTERS:
            feedback = (
                "Qwen 未返回至少二百字符的 reasoning_content，派工过程不可审计",
            )
            continue
        if result.reasoning_transport != "dashscope_enable_thinking":
            feedback = ("Qwen 路由未使用 DashScope thinking transport",)
            continue
        if not isinstance(result.parsed_json, Mapping):
            feedback = ("[ROUTE_SCHEMA] Qwen 顶层输出必须是 JSON 对象",)
            continue
        raw_findings = _raw_route_validation_findings(result.parsed_json)
        if raw_findings:
            feedback = raw_findings
            continue
        try:
            portfolio = OpportunityWorkerRoutePortfolio.model_validate(
                result.parsed_json
            )
        except (
            ValidationError,
            SystemPlanOpportunityRoutingError,
            ValueError,
        ) as exc:
            feedback = (f"机会派工结构或中文校验失败：{exc}",)
            continue
        if result.parsed_json != portfolio.model_dump(mode="json"):
            feedback = (
                "Qwen 返回载荷必须显式且逐字段等于规范派工组合，不得依赖默认补值",
            )
            continue
        findings = _portfolio_findings(
            portfolio=portfolio,
            context=context,
            envelope=feasibility_envelope,
        )
        if findings:
            feedback = findings
            continue
        receipt_path = Path(receipt.output_path).resolve()
        output_path = output_root / _OUTPUT_NAME
        payload: dict[str, Any] = {
            "schema_version": "system-plan-opportunity-routing-artifact-v4",
            "lineage_id": lineage_id,
            "authoring_attempt": attempt,
            "prior_feedback": list(prior_feedback),
            "feasibility_envelope": feasibility_envelope.model_dump(mode="json"),
            "component_atom_binding": component_atom_binding.model_dump(
                mode="json"
            ),
            "compact_routing_context": context.model_dump(mode="json"),
            "source_catalog_hash": source_catalog_hash,
            "selected_references_hash": selected_references_hash,
            "method_skill_selection": method_skill_selection.model_dump(
                mode="json"
            ),
            "portfolio": portfolio.model_dump(mode="json"),
            "provider_receipt": receipt.model_dump(mode="json"),
            "provider_receipt_relative_path": receipt_path.relative_to(
                output_root
            ).as_posix(),
            "reasoning_required": True,
            "reasoning_is_evidence": False,
            "authored_by_model": True,
            "hand_written_scientific_prose_count": 0,
            "is_scientific_evidence": False,
            "execution_authorized": False,
            "created_at": (clock or datetime.now(timezone.utc))
            .astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
        }
        payload["artifact_hash"] = canonical_model_hash(payload)
        payload["output_path"] = output_path.as_posix()
        artifact = SystemPlanOpportunityRoutingArtifact.model_validate(payload)
        write_json_model(output_path, artifact)
        return artifact
    raise SystemPlanOpportunityRoutingError(
        "主 Qwen 未能生成可绑定的七路机会派工；最终反馈："
        f"{list(feedback)}"
    )
