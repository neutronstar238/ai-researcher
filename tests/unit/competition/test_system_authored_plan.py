"""The system authors its own plan; the graders teach rather than merely reject.

`P-20260804-086`: the previous plan generator made no model call and carried hardcoded
prose, so the scientific framing was an agent's. These tests pin the inversion: the
model writes every prose field, and deterministic graders decide acceptance.

The important tests are the REFUSALS and the TEACHING loop. A grader that cannot refuse
teaches nothing, and a refusal that does not say why teaches nothing either.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.system_authored_plan import (
    PlanScientificLineageAttestationV2,
    PlanScientificLineageBindingV2,
    SystemAuthoredPlanArtifact,
    SystemAuthoredPlanError,
    _build_plan_scientific_lineage_binding,
    _lineage_attestation_findings,
    _plan_scientific_lineage_findings,
    author_research_plan,
    guard_authored_plan,
)
from autoresearch.competition.system_plan_component_atoms import (
    SystemPlanComponentAtom,
    SystemPlanComponentAtomBinding,
)
from autoresearch.competition.system_plan_ideation import ResearchDirectionCandidate
from autoresearch.competition.system_plan_opportunity_map import ResearchOpportunityCell
from autoresearch.competition.system_plan_prospective_atoms import (
    ComponentExperimentBindingV2,
    ProspectiveAtomBinding,
    ProspectiveComponentAtom,
    ProspectiveInterventionIdentity,
    ProspectiveLiteratureSupport,
    ProspectiveResourceRequest,
)
from autoresearch.llm.client import LLMJsonCompletionResult
from autoresearch.research.plans import ResearchPlan, ResearchPlanStatus

_FROZEN: dict[str, Any] = {
    "frozen_thresholds": {
        "minimum_overall_log_effect": 0.05129329438755058,
        "stratum_median_minimum": 0.0,
    },
    "retained_evidence": {
        "prior_overall_median": -0.8448548894388439,
        "prior_win_count": 3,
        "prior_system_count": 12,
        "failure_reasons": ["container wall-time budget exceeded"],
    },
}


def _authored(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": "Noise-robust sparse recovery under held-out complexity selection",
        "abstract": (
            "Background: the prior lineage reached an overall median of "
            "-0.8448548894388439 across 12 systems. Method: choose model complexity on "
            "held-out evidence rather than fitting once at maximum capacity. Expected "
            "result: the transfer gap narrows and the paired effect exceeds "
            "0.05129329438755058; a null result would refute the mechanism."
        ),
        "problem_statement": (
            "Across 12 systems the prior lineage reached an overall median of "
            "-0.8448548894388439, winning 3, so held-out accuracy did not follow from "
            "training accuracy and the selection rule is the suspected mechanism."
        ),
        "rationale": (
            "If complexity is chosen on held-out evidence rather than fixed at "
            "maximum capacity, the transfer gap should narrow. This is a mechanism "
            "claim and it is testable against the same panel."
        ),
        "technical_details": (
            "Each candidate fits on the training split only, emits concrete numeric "
            "equations, and the orchestrator freezes and hashes that artifact before "
            "prediction reads it."
        ),
        "methods": (
            "Compare against the pinned baseline using derivative NMSE as the cell "
            "loss, aggregating by median within a system and then across systems."
        ),
        "experiments": [
            "Author independent candidates and reject any that fails static review.",
            "Run a bounded pilot and return each candidate its own diagnostics.",
            "Execute the baseline on every system, retaining every failure.",
            "Run the full stage and compute a paired effect with a fixed-seed bootstrap.",
        ],
        "baselines": [
            "the pinned tuned symbolic-regression baseline on the same frozen cells",
        ],
        "metrics": [
            "derivative NMSE as the per-cell loss",
            "paired log effect aggregated by median within and then across systems",
        ],
        "expected_results": (
            "It is expected, and not yet observed, that the paired effect exceeds "
            "0.05129329438755058. A negative or null result would refute the "
            "selection-rule mechanism and is a valid outcome that will be reported."
        ),
        "code_agent_brief": (
            "Run python /harness/runner.py --spec ... --data ... per frozen cell with "
            "network disabled, then validate with pytest before any official cell. "
            "required_method_tokens=[heldout, sparsity]"
        ),
        "risks_and_alternatives": [
            "A candidate may overfit the validation window; the transfer gap is fed back.",
            "A baseline may fail on a system, leaving it unpaired and excluded.",
        ],
        "dataset_source": "the pinned processed archive, clean and noisy conditions",
        "dataset_target": "a chronologically disjoint held-out split of the same systems",
        "references": ["retained prior lineage package"],
    }
    payload.update(overrides)
    return payload


class _Stub:
    """Returns a queued payload per call, so the teaching loop can be observed."""

    def __init__(
        self,
        *payloads: dict[str, Any],
        reasoning_text: str | None = None,
    ) -> None:
        self.payloads = list(payloads)
        self.calls: list[dict[str, Any]] = []
        self.reasoning_text = reasoning_text

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        self.calls.append(kwargs)
        payload = self.payloads[min(len(self.calls) - 1, len(self.payloads) - 1)]
        return LLMJsonCompletionResult(
            provider="qwen-dashscope",
            base_url="https://dashscope.example/compatible-mode/v1",
            model_name="qwen3.7-max",
            endpoint="https://dashscope.example/v1/chat/completions",
            response_text=json.dumps(payload),
            parsed_json=payload,
            usage={
                "prompt_tokens": 900,
                "completion_tokens": 1_100,
                "completion_tokens_details": {"reasoning_tokens": 2_100},
            },
            temperature=0.3,
            reasoning_text=(
                self.reasoning_text
                if self.reasoning_text is not None
                else (
                    "先核对前瞻组件身份、对照处理、冻结维度和文献编号域，再逐字段展开"
                    "研究问题、可证伪机制、实验设计、代码接口与失败判据；最后复核所有"
                    "散文均由模型生成，所有机器身份逐字继承且没有把机会格误作处理边界。"
                )
                * 3
            ),
            reasoning_transport="dashscope_enable_thinking",
        )


def _run(
    tmp_path: Path,
    stub: Callable[..., LLMJsonCompletionResult],
    **kw: Any,
) -> Any:
    evidence = tmp_path / "prior-package.json"
    evidence.write_text("{}", encoding="utf-8")
    return author_research_plan(
        lineage_id="lineage-under-test",
        project_id="project-under-test",
        candidate_id="candidate-under-test",
        frozen_context=kw.pop("frozen_context", _FROZEN),
        evidence_paths=[evidence],
        output_dir=tmp_path,
        completion=stub,
        container_entry_points=kw.pop("container_entry_points", ("/harness/runner.py",)),
        # Most legacy unit fixtures below are English so they can isolate unrelated
        # guards.  Production authoring defaults to the stricter Chinese requirement,
        # which has its own explicit refusal test.
        require_chinese=kw.pop("require_chinese", False),
        **kw,
    )


def _plan(**overrides: Any) -> ResearchPlan:
    authored = _authored(**overrides)
    return ResearchPlan.model_validate(
        {
            "project_id": "p",
            "candidate_id": "c",
            "title": authored["title"],
            "problem_statement": authored["problem_statement"],
            "rationale": authored["rationale"],
            "technical_details": authored["technical_details"],
            "datasets": {
                "source": authored["dataset_source"],
                "target": authored["dataset_target"],
            },
            "methods": authored["methods"],
            "experiments": list(authored["experiments"]),
            "expected_results": authored["expected_results"],
            "code_agent_brief": authored["code_agent_brief"],
            "risks_and_alternatives": list(authored["risks_and_alternatives"]),
            "references": list(authored["references"]),
            "evidence_refs": ["prior-package.json"],
            "status": ResearchPlanStatus.DRAFT,
        }
    )


def _lineage_zh(label: str) -> str:
    return f"{label}必须在冻结数据和独立分析单位上接受预注册反事实检验，并完整报告正负零三类结果。"


def _observed_component_binding() -> SystemPlanComponentAtomBinding:
    atoms = tuple(
        SystemPlanComponentAtom(
            atom_id=f"A{index:03d}",
            source_lineage_id=f"prior-{index}",
            source_summary_sha256=f"{index:x}" * 64,
            source_clause_id=f"SC{index:03d}",
            source_clause=f"既有候选完整实现包含 component{index} 并在冻结接口内运行。",
            technical_identifier=f"component{index}",
            label_zh=f"既有组件{index}",
            applicable_data_types=("ode",),
            rationale_zh=_lineage_zh(f"既有组件{index}的来源理由"),
        )
        for index in range(1, 8)
    )
    payload: dict[str, Any] = {
        "schema_version": "system-plan-component-atom-binding-v1",
        "component_atom_artifact_hash": "a" * 64,
        "feasibility_envelope_hash": "b" * 64,
        "source_clause_catalog_hash": "c" * 64,
        "method_skill_selection_artifact_hash": "d" * 64,
        "atoms": [item.model_dump(mode="json") for item in atoms],
        "independent_review_hash": "e" * 64,
        "is_scientific_evidence": False,
        "execution_authorized": False,
    }
    payload["binding_hash"] = canonical_model_hash(payload)
    return SystemPlanComponentAtomBinding.model_validate(payload)


def _prospective_atom(
    *,
    atom_id: str,
    baseline: SystemPlanComponentAtom,
    implementation_anchor: str,
    retrieval_indices: tuple[int, int],
) -> ProspectiveComponentAtom:
    def _support_span(reference_index: int) -> str:
        return (
            f"Complete abstract support span number {reference_index} for the "
            "prospective single-factor intervention."
        )

    supports = tuple(
        ProspectiveLiteratureSupport(
            reference_index=reference_index,
            retrieval_index=retrieval_index,
            source_record_hash=f"{reference_index}" * 64,
            abstract_sha256=f"{reference_index + 3}" * 64,
            exact_support_span=_support_span(reference_index),
            support_span_sha256=hashlib.sha256(
                _support_span(reference_index).encode("utf-8")
            ).hexdigest(),
            support_role="问题动机" if reference_index == 2 else "可迁移原理",
        )
        for reference_index, retrieval_index in zip(
            (2, 3), retrieval_indices, strict=True
        )
    )
    return ProspectiveComponentAtom(
        atom_id=atom_id,
        origin_kind="prospective_literature_derived",
        baseline_observed_atom_id=baseline.atom_id,
        baseline_observed_atom_hash=canonical_model_hash(baseline),
        label_zh=_lineage_zh(f"{atom_id}前瞻处理")[:90],
        change_mode="替换",
        control_level_zh=_lineage_zh(f"{atom_id}对照水平"),
        intervention_level_zh=_lineage_zh(f"{atom_id}处理水平"),
        single_factor_rationale_zh=_lineage_zh(f"{atom_id}单因子识别理由"),
        literature_synthesis_zh=_lineage_zh(f"{atom_id}文献综合"),
        delta_from_prior_work_zh=_lineage_zh(f"{atom_id}相对先前工作的差异"),
        falsifiable_single_factor_contrast_zh=_lineage_zh(
            f"{atom_id}可证伪单因子对照"
        ),
        implementation_anchor=implementation_anchor,
        public_hooks=("fit_equations", "predict_derivative"),
        target_keys=("T001", "T002", "T003"),
        applicable_data_types=("ode",),
        supporting_fact_ids=tuple(f"E{index:03d}" for index in range(1, 9)),
        literature_supports=supports,
        frozen_dimensions=(
            "输入数据",
            "实验条件",
            "随机种子",
            "估计目标",
            "基线方法",
            "评估指标",
            "公开接口",
            "资源上限",
            "基线组件之外的候选行为",
        ),
        resource_request=ProspectiveResourceRequest(
            seconds_per_cell=120,
            memory_mb_per_cell=1024,
            cpu_cores_per_cell=2,
            public_fit_calls_per_cell=1,
        ),
        single_factor_intervention=True,
        candidate_differences_jointly_confounded=True,
        is_scientific_evidence=False,
        innovation_verified=False,
        execution_authorized=False,
    )


def _component_experiment_binding() -> ComponentExperimentBindingV2:
    observed = _observed_component_binding()
    atoms = (
        _prospective_atom(
            atom_id="P001",
            baseline=observed.atoms[0],
            implementation_anchor="prospective_component",
            retrieval_indices=(4, 8),
        ),
        _prospective_atom(
            atom_id="P002",
            baseline=observed.atoms[1],
            implementation_anchor="alternate_component",
            retrieval_indices=(5, 9),
        ),
    )
    identities = tuple(
        ProspectiveInterventionIdentity(
            atom_id=atom.atom_id,
            origin_kind=atom.origin_kind,
            intervention_hash=canonical_model_hash(atom),
            baseline_observed_atom_id=atom.baseline_observed_atom_id,
            baseline_observed_atom_hash=atom.baseline_observed_atom_hash,
            implementation_anchor=atom.implementation_anchor,
            public_hooks=atom.public_hooks,
        )
        for atom in atoms
    )
    prospective_payload: dict[str, Any] = {
        "schema_version": "prospective-atom-binding-v1",
        "prospective_atom_artifact_hash": "f" * 64,
        "survey_hash": "1" * 64,
        "feasibility_envelope_hash": observed.feasibility_envelope_hash,
        "observed_component_binding_hash": observed.binding_hash,
        "method_skill_selection_artifact_hash": (
            observed.method_skill_selection_artifact_hash
        ),
        "interface_contract_hash": "2" * 64,
        "context_hash": "3" * 64,
        "target_aliases": [
            {
                "target_key": f"T{index:03d}",
                "system_name": f"system_{name}",
                "data_type": "ode",
                "required_fact_ids": ["E001", "E002", "E003", "E004"],
            }
            for index, name in enumerate(("alpha", "beta", "gamma"), 1)
        ],
        "atoms": [item.model_dump(mode="json") for item in atoms],
        "intervention_identities": [
            item.model_dump(mode="json") for item in identities
        ],
        "independent_review_hash": "4" * 64,
        "is_scientific_evidence": False,
        "innovation_verified": False,
        "execution_authorized": False,
    }
    prospective_payload["binding_hash"] = canonical_model_hash(prospective_payload)
    prospective = ProspectiveAtomBinding.model_validate(prospective_payload)
    combined_payload: dict[str, Any] = {
        "schema_version": "component-experiment-binding-v2",
        "observed_components": observed.model_dump(mode="json"),
        "prospective_components": prospective.model_dump(mode="json"),
        "is_scientific_evidence": False,
        "innovation_verified": False,
        "execution_authorized": False,
    }
    combined_payload["binding_hash"] = canonical_model_hash(combined_payload)
    return ComponentExperimentBindingV2.model_validate(combined_payload)


def _motivation_only_cell() -> ResearchOpportunityCell:
    return ResearchOpportunityCell.model_validate(
        {
            "cell_id": "O01",
            "evidence_fact_ids": ["E090", "E091"],
            "literature_indices": [20, 21, 22],
            "unresolved_contradiction": _lineage_zh("机会格未解矛盾"),
            "operational_construct": _lineage_zh("机会格操作构念"),
            "mechanism_preconditions": [
                _lineage_zh("机会格前提一"),
                _lineage_zh("机会格前提二"),
            ],
            "eligible_target_systems": ["motivation_only_system"],
            "manipulable_factor": _lineage_zh("机会格可操纵因素"),
            "measurable_outcome": _lineage_zh("机会格可测结局"),
            "alternative_explanation": _lineage_zh("机会格替代解释"),
            "single_component_counterfactual": _lineage_zh("机会格单组件反事实"),
            "negative_control": _lineage_zh("机会格负对照"),
            "sensitivity_control": _lineage_zh("机会格敏感性对照"),
            "orthogonal_diagnostic": _lineage_zh("机会格正交诊断"),
            "independent_analysis_unit": _lineage_zh("机会格独立分析单位"),
            "result_blind_decision_rule": _lineage_zh("机会格结果盲规则"),
            "resource_bounded_minimal_diagnostic": _lineage_zh("机会格最小诊断"),
            "discriminating_observation": _lineage_zh("机会格区分观测"),
            "expected_directional_pattern": _lineage_zh("机会格预期模式"),
            "refuting_observation": _lineage_zh("机会格反驳观测"),
            "why_not_component_composition": _lineage_zh("机会格非组件拼接理由"),
            "feasibility_risk": _lineage_zh("机会格可行性风险"),
            "method_application_trace": {
                "verified_fact_ids": ["E090", "E091"],
                "evidence_scope_audit": _lineage_zh("机会格证据范围审计"),
                "changed_component": _lineage_zh("机会格历史改变组件"),
                "frozen_components": [
                    _lineage_zh("机会格冻结组件一"),
                    _lineage_zh("机会格冻结组件二"),
                    _lineage_zh("机会格冻结组件三"),
                ],
                "negative_control_audit": _lineage_zh("机会格负对照审计"),
                "orthogonal_diagnostic_audit": _lineage_zh("机会格正交诊断审计"),
                "independent_unit_audit": _lineage_zh("机会格独立单位审计"),
                "target_mechanism_outcome": _lineage_zh("机会格目标机制结果"),
                "alternative_explanation_outcome": _lineage_zh(
                    "机会格替代解释结果"
                ),
                "indeterminate_outcome": _lineage_zh("机会格不确定结果"),
                "resource_bound_audit": _lineage_zh("机会格资源边界审计"),
                "closest_prior_reference_indices": [20, 21, 22],
                "closest_prior_gap_audit": _lineage_zh("机会格近邻差距审计"),
            },
        }
    )


def _v2_direction(
    binding: ComponentExperimentBindingV2,
) -> ResearchDirectionCandidate:
    atom = binding.prospective_components.atoms[0]
    identity = binding.prospective_components.intervention_identities[0]
    return ResearchDirectionCandidate.model_validate(
        {
            "schema_version": "research-direction-candidate-v2",
            "lens": "机制替代",
            "opportunity_cell_id": "O01",
            "prospective_atom_id": atom.atom_id,
            "prospective_atom_hash": canonical_model_hash(atom),
            "prospective_intervention_hash": identity.intervention_hash,
            "prospective_origin_kind": identity.origin_kind,
            "target_systems": ["system_alpha", "system_beta", "system_gamma"],
            "evidence_fact_ids": list(atom.supporting_fact_ids),
            "title": "前瞻单因子干预的反事实机制研究",
            "scientific_gap": _lineage_zh("方向科学缺口"),
            "challenged_assumption": _lineage_zh("方向挑战假设"),
            "core_mechanism": _lineage_zh("方向核心机制"),
            "falsifiable_hypothesis": _lineage_zh("方向可证伪假设"),
            "alternative_explanation": _lineage_zh("方向替代解释"),
            "decisive_test": _lineage_zh("方向决定性检验"),
            "negative_control": _lineage_zh("方向负对照"),
            "sensitivity_control": _lineage_zh("方向敏感性对照"),
            "orthogonal_diagnostic": _lineage_zh("方向正交诊断"),
            "independent_analysis_unit": _lineage_zh("方向独立分析单位"),
            "result_blind_decision_rule": _lineage_zh("方向结果盲规则"),
            "nearest_work_indices": [5, 9],
            "substantive_difference": _lineage_zh("方向实质差异"),
            "execution_fit": _lineage_zh("方向执行适配"),
            "failure_modes": [
                _lineage_zh("方向失败模式一"),
                _lineage_zh("方向失败模式二"),
            ],
            "method_tokens": ["prospective", "counterfactual"],
        }
    )


def _v2_context() -> dict[str, Any]:
    combined = _component_experiment_binding()
    direction = _v2_direction(combined)
    return {
        **_FROZEN,
        "system_selected_method_skills": {
            "selection_artifact_hash": "d" * 64,
        },
        "system_audited_research_opportunity_map": {
            "artifact_hash": "5" * 64,
            "accepted_cells": [_motivation_only_cell().model_dump(mode="json")],
        },
        "system_component_atom_catalog": (
            combined.observed_components.model_dump(mode="json")
        ),
        "system_prospective_component_atoms": (
            combined.prospective_components.model_dump(mode="json")
        ),
        "system_component_experiment_binding": combined.model_dump(mode="json"),
        "system_selected_research_direction": direction.model_dump(mode="json"),
        "system_selected_research_direction_hash": canonical_model_hash(direction),
        "system_plan_ideation_artifact_hash": "6" * 64,
    }


def _v2_attestation(
    binding: PlanScientificLineageBindingV2,
) -> PlanScientificLineageAttestationV2:
    direction = binding.selected_direction
    atom = binding.selected_prospective_atom()
    return PlanScientificLineageAttestationV2(
        schema_version="plan-scientific-lineage-attestation-v2",
        source_opportunity_cell_id=direction.opportunity_cell_id,
        selected_direction_hash=binding.selected_direction_hash,
        selected_direction_title=direction.title,
        target_systems=direction.target_systems,
        evidence_fact_ids=direction.evidence_fact_ids,
        nearest_work_indices=direction.nearest_work_indices,
        method_tokens=direction.method_tokens,
        core_mechanism=direction.core_mechanism,
        falsifiable_hypothesis=direction.falsifiable_hypothesis,
        alternative_explanation=direction.alternative_explanation,
        decisive_test=direction.decisive_test,
        negative_control=direction.negative_control,
        sensitivity_control=direction.sensitivity_control,
        orthogonal_diagnostic=direction.orthogonal_diagnostic,
        independent_analysis_unit=direction.independent_analysis_unit,
        result_blind_decision_rule=direction.result_blind_decision_rule,
        component_experiment_binding_hash=binding.component_experiment_binding_hash,
        selected_intervention_identity=binding.selected_intervention_identity,
        change_mode=atom.change_mode,
        control_level_zh=atom.control_level_zh,
        intervention_level_zh=atom.intervention_level_zh,
        single_factor_rationale_zh=atom.single_factor_rationale_zh,
        falsifiable_single_factor_contrast_zh=(
            atom.falsifiable_single_factor_contrast_zh
        ),
        frozen_dimensions=atom.frozen_dimensions,
        resource_request=atom.resource_request,
        selected_plan_reference_indices=tuple(
            item.reference_index for item in atom.literature_supports
        ),
        continuity_explanation=_lineage_zh("计划逐字延续前瞻干预身份"),
    )


def test_concise_chinese_lineage_prose_is_accepted_without_length_quota() -> None:
    binding = _build_plan_scientific_lineage_binding(_v2_context())
    assert isinstance(binding, PlanScientificLineageBindingV2)
    payload = _v2_attestation(binding).model_dump(mode="json")
    for field in (
        "selected_direction_title",
        "core_mechanism",
        "falsifiable_hypothesis",
        "alternative_explanation",
        "decisive_test",
        "negative_control",
        "sensitivity_control",
        "orthogonal_diagnostic",
        "independent_analysis_unit",
        "result_blind_decision_rule",
        "continuity_explanation",
        "control_level_zh",
        "intervention_level_zh",
        "single_factor_rationale_zh",
        "falsifiable_single_factor_contrast_zh",
    ):
        payload[field] = "可检验。"
    payload["frozen_dimensions"] = ["固定。"]

    attestation = PlanScientificLineageAttestationV2.model_validate(payload)

    assert attestation.control_level_zh == "可检验。"


def test_blank_lineage_prose_is_rejected_without_length_quota() -> None:
    binding = _build_plan_scientific_lineage_binding(_v2_context())
    assert isinstance(binding, PlanScientificLineageBindingV2)
    payload = _v2_attestation(binding).model_dump(mode="json")
    payload["continuity_explanation"] = "   "

    with pytest.raises(SystemAuthoredPlanError, match="not Chinese"):
        PlanScientificLineageAttestationV2.model_validate(payload)


def _identity_declaration(identity: ProspectiveInterventionIdentity) -> str:
    return json.dumps(
        identity.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _v2_plan(binding: PlanScientificLineageBindingV2) -> ResearchPlan:
    direction = binding.selected_direction
    atom = binding.selected_prospective_atom()
    frozen = "、".join(atom.frozen_dimensions)
    identity = _identity_declaration(binding.selected_intervention_identity)
    plan = _plan()
    return plan.model_copy(
        update={
            "title": direction.title + "完整预注册计划",
            "abstract": direction.core_mechanism + direction.falsifiable_hypothesis,
            "problem_statement": (
                direction.scientific_gap + direction.challenged_assumption + "[2][3]"
            ),
            "rationale": direction.core_mechanism + "并比较直接支持工作[2][3]。",
            "technical_details": (
                f"{atom.label_zh}采用{atom.change_mode}；"
                f"{atom.intervention_level_zh}{atom.single_factor_rationale_zh}"
                f"其余维度逐项冻结为{frozen}。"
            ),
            "methods": (
                f"{atom.change_mode}{atom.intervention_level_zh}"
                f"{atom.single_factor_rationale_zh}"
                f"并按直接支持文献[2][3]完成预注册。"
            ),
            "experiments": (
                direction.decisive_test
                + atom.falsifiable_single_factor_contrast_zh
                + f"并逐项冻结{frozen}。",
                direction.negative_control + direction.sensitivity_control,
                direction.orthogonal_diagnostic + direction.independent_analysis_unit,
                direction.result_blind_decision_rule
                + "并运行 system_alpha、system_beta、system_gamma。",
            ),
            "baselines": (atom.control_level_zh,),
            "expected_results": (
                direction.falsifiable_hypothesis
                + "若未满足预注册对照则反驳假设，零结果同样有效。"
            ),
            "code_agent_brief": (
                "运行 python /harness/runner.py 执行冻结计划并用 pytest 校验。"
                f"required_intervention_identity={identity} "
                "required_method_tokens=[prospective, counterfactual]"
            ),
            "risks_and_alternatives": (
                direction.alternative_explanation,
                direction.result_blind_decision_rule,
            ),
            "datasets": {
                "source": "冻结来源数据仅供训练阶段使用。",
                "target": (
                    "system_alpha、system_beta、system_gamma 作为前瞻干预目标系统。"
                ),
            },
        }
    )


def _v2_authored_payload(binding: PlanScientificLineageBindingV2) -> dict[str, Any]:
    plan = _v2_plan(binding)
    return {
        "title": plan.title,
        "abstract": plan.abstract,
        "problem_statement": plan.problem_statement,
        "rationale": plan.rationale,
        "technical_details": plan.technical_details,
        "dataset_source": str(plan.datasets["source"]),
        "dataset_target": str(plan.datasets["target"]),
        "methods": plan.methods,
        "experiments": list(plan.experiments),
        "baselines": list(plan.baselines),
        "metrics": list(plan.metrics),
        "expected_results": plan.expected_results,
        "code_agent_brief": plan.code_agent_brief,
        "risks_and_alternatives": list(plan.risks_and_alternatives),
        "references": list(plan.references),
        "scientific_lineage_attestation": _v2_attestation(binding).model_dump(
            mode="json"
        ),
    }


# --------------------------------------------------------------------------
# The system authors, and the artifact records that no prose was ours
# --------------------------------------------------------------------------


def test_the_model_authors_every_prose_field(tmp_path: Path) -> None:
    artifact = _run(tmp_path, _Stub(_authored()))
    assert artifact.authored_by_model is True
    assert artifact.hand_written_prose_field_count == 0
    assert artifact.plan["title"] == _authored()["title"]
    assert artifact.plan["problem_statement"] == _authored()["problem_statement"]
    assert artifact.reasoning_tokens == 2_100
    assert artifact.guard_report.accepted is True
    assert artifact.authorship_receipt_hash is not None
    receipt_path = tmp_path / str(artifact.authorship_receipt_relative_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["receipt_hash"] == artifact.authorship_receipt_hash
    assert receipt["parsed_payload"]["title"] == artifact.plan["title"]
    assert receipt["api_key_value_logged"] is False


def test_preexperiment_result_is_required_and_copied_exactly_into_plan(
    tmp_path: Path,
) -> None:
    preliminary_result = (
        "本次预实验实际运行固定基线，并保留原始记录：系统=system_alpha，"
        "条件=clean，状态=succeeded，导数NMSE=0.125。该记录只说明公开数据、"
        "固定指标和隔离执行链在有限范围内可运行；拟议干预仍未测量处理效应，"
        "不能据此判断新方法有效、科学假设成立或完整正式实验已经完成。"
    )
    context = {
        **_FROZEN,
        "system_preliminary_experiment": {
            "schema_version": "system-plan-preexperiment-plan-context-v1",
            "artifact_hash": "9" * 64,
            "plan_results_zh": preliminary_result,
            "preliminary_only": True,
            "treatment_effect_measured": False,
            "full_experiment_completed": False,
        },
    }

    artifact = _run(
        tmp_path,
        _Stub(_authored()),
        frozen_context=context,
    )

    assert artifact.plan["results"] == preliminary_result
    receipt = json.loads(
        (tmp_path / str(artifact.authorship_receipt_relative_path)).read_text(
            encoding="utf-8"
        )
    )
    assert "results" not in receipt["parsed_payload"]
    prompt = json.dumps(receipt["messages"], ensure_ascii=False)
    assert "plan_results_zh" in prompt
    assert '"results"' not in receipt["messages"][0]["content"]


def test_concise_bound_preexperiment_result_has_no_length_quota(
    tmp_path: Path,
) -> None:
    preliminary_result = "预实验未测量处理效应。"
    context = {
        **_FROZEN,
        "system_preliminary_experiment": {
            "schema_version": "system-plan-preexperiment-plan-context-v1",
            "artifact_hash": "9" * 64,
            "plan_results_zh": preliminary_result,
            "preliminary_only": True,
            "treatment_effect_measured": False,
            "full_experiment_completed": False,
        },
    }

    artifact = _run(
        tmp_path,
        _Stub(_authored(results=preliminary_result)),
        frozen_context=context,
    )

    assert artifact.plan["results"] == preliminary_result


def test_plan_projection_ignores_qwen_paraphrase_of_bound_preexperiment_result(
    tmp_path: Path,
) -> None:
    preliminary_result = (
        "本次预实验实际运行固定基线并保留完整原始指标；这些结果只说明公开数据、"
        "固定指标和隔离执行链在有限范围内可运行，拟议干预仍未测量处理效应，"
        "不能据此判断新方法有效、科学假设成立或完整正式实验已经完成。"
    )
    context = {
        **_FROZEN,
        "system_preliminary_experiment": {
            "schema_version": "system-plan-preexperiment-plan-context-v1",
            "artifact_hash": "9" * 64,
            "plan_results_zh": preliminary_result,
            "preliminary_only": True,
            "treatment_effect_measured": False,
            "full_experiment_completed": False,
        },
    }

    artifact = _run(
        tmp_path,
        _Stub(_authored(results=preliminary_result + "擅自改写。")),
        frozen_context=context,
    )

    assert artifact.plan["results"] == preliminary_result
    receipt = json.loads(
        (tmp_path / str(artifact.authorship_receipt_relative_path)).read_text(
            encoding="utf-8"
        )
    )
    assert receipt["parsed_payload"]["results"].endswith("擅自改写。")


def test_the_prompt_supplies_constraints_but_no_science(tmp_path: Path) -> None:
    """The teacher sets the standard; it must not hand over the answer."""

    stub = _Stub(_authored())
    _run(tmp_path, stub)
    sent = json.dumps(stub.calls[0]["messages"])
    # Frozen constraints and its own retained evidence are supplied.
    assert "0.05129329438755058" in sent
    assert "-0.8448548894388439" in sent
    # It is told to author its own framing and what would refute it.
    assert "author your own research plan" in sent.lower()
    assert "REFUTE" in sent
    # No hypothesis, mechanism, or title is supplied for it to copy.
    assert "held-out complexity selection" not in sent
    assert "selection rule" not in sent.lower()


def test_v2_lineage_binds_exact_prospective_identity_not_cell_scope() -> None:
    binding = _build_plan_scientific_lineage_binding(_v2_context())

    assert isinstance(binding, PlanScientificLineageBindingV2)
    assert binding.source_opportunity_cell.eligible_target_systems == (
        "motivation_only_system",
    )
    assert binding.selected_direction.target_systems == (
        "system_alpha",
        "system_beta",
        "system_gamma",
    )
    assert binding.selected_direction.nearest_work_indices == (5, 9)
    assert binding.selected_plan_reference_indices() == (2, 3)
    assert _lineage_attestation_findings(
        binding=binding,
        attestation=_v2_attestation(binding),
    ) == ()
    assert _plan_scientific_lineage_findings(
        plan=_v2_plan(binding), binding=binding
    ) == ()


def test_current_authoring_persists_a_round_trip_v2_prospective_artifact(
    tmp_path: Path,
) -> None:
    context = _v2_context()
    binding = _build_plan_scientific_lineage_binding(context)
    assert isinstance(binding, PlanScientificLineageBindingV2)
    literature = [
        {
            "title": f"Retrieved prior work {index}",
            "authors": ["Author"],
            "venue": "Archive",
            "publication_date": "2026-01-01",
            "doi": f"10.0000/example.{index}",
        }
        for index in range(1, 4)
    ]
    raw_payload = _v2_authored_payload(binding)
    continuity = raw_payload["scientific_lineage_attestation"][
        "continuity_explanation"
    ]
    raw_payload["scientific_lineage_attestation"] = {
        "continuity_explanation": continuity
    }
    raw_payload["code_agent_brief"] = raw_payload["code_agent_brief"].replace(
        "required_intervention_identity="
        + _identity_declaration(binding.selected_intervention_identity)
        + " ",
        "",
    )

    artifact = _run(
        tmp_path,
        _Stub(raw_payload),
        frozen_context=context,
        literature=literature,
    )

    assert artifact.schema_version == "system-authored-research-plan-v2"
    assert isinstance(
        artifact.scientific_lineage_binding, PlanScientificLineageBindingV2
    )
    assert isinstance(
        artifact.scientific_lineage_attestation,
        PlanScientificLineageAttestationV2,
    )
    assert artifact.guard_report.accepted is True
    assert artifact.plan["code_agent_brief"].count(
        "required_intervention_identity="
    ) == 1
    receipt = json.loads(
        (tmp_path / str(artifact.authorship_receipt_relative_path)).read_text(
            encoding="utf-8"
        )
    )
    assert receipt["parsed_payload"]["scientific_lineage_attestation"] == {
        "continuity_explanation": continuity
    }
    assert "required_intervention_identity=" not in receipt["parsed_payload"][
        "code_agent_brief"
    ]
    # Machine hashes inside the exact identity are identifiers, not invented results.
    assert artifact.guard_report.untraceable_numbers == ()
    written = tmp_path / "system-authored-research-plan.json"
    loaded = SystemAuthoredPlanArtifact.model_validate_json(
        written.read_text(encoding="utf-8")
    )
    assert loaded == artifact


def test_new_authoring_never_emits_v1_but_v1_without_prospective_chain_loads(
    tmp_path: Path,
) -> None:
    current = _run(tmp_path, _Stub(_authored()))
    assert current.schema_version == "system-authored-research-plan-v2"
    historical = current.model_dump(mode="json")
    historical["schema_version"] = "system-authored-research-plan-v1"
    historical["artifact_hash"] = canonical_model_hash(
        {
            key: value
            for key, value in historical.items()
            if key not in {"artifact_hash", "output_path"}
        }
    )

    loaded = SystemAuthoredPlanArtifact.model_validate(historical)

    assert loaded.schema_version == "system-authored-research-plan-v1"
    assert loaded.scientific_lineage_binding is None


def test_historical_v1_cannot_be_used_to_downgrade_a_formal_prospective_chain(
    tmp_path: Path,
) -> None:
    context = _v2_context()
    binding = _build_plan_scientific_lineage_binding(context)
    assert isinstance(binding, PlanScientificLineageBindingV2)
    literature = [{"title": f"prior {index}"} for index in range(1, 4)]
    current = _run(
        tmp_path,
        _Stub(_v2_authored_payload(binding)),
        frozen_context=context,
        literature=literature,
    )
    downgraded = current.model_dump(mode="json")
    downgraded["schema_version"] = "system-authored-research-plan-v1"

    with pytest.raises(SystemAuthoredPlanError, match="v1 cannot carry a prospective"):
        SystemAuthoredPlanArtifact.model_validate(downgraded)


def test_prospective_context_cannot_fall_back_without_combined_binding() -> None:
    context = _v2_context()
    context.pop("system_component_experiment_binding")

    with pytest.raises(SystemAuthoredPlanError, match="component experiment binding"):
        _build_plan_scientific_lineage_binding(context)


def test_cross_binding_prospective_projection_is_refused() -> None:
    context = _v2_context()
    mismatched = copy.deepcopy(context["system_prospective_component_atoms"])
    mismatched["prospective_atom_artifact_hash"] = "9" * 64
    mismatched["binding_hash"] = canonical_model_hash(
        {key: value for key, value in mismatched.items() if key != "binding_hash"}
    )
    context["system_prospective_component_atoms"] = mismatched

    with pytest.raises(SystemAuthoredPlanError, match="prospective component binding"):
        _build_plan_scientific_lineage_binding(context)


def test_v2_attestation_cannot_change_the_implementation_anchor() -> None:
    binding = _build_plan_scientific_lineage_binding(_v2_context())
    assert isinstance(binding, PlanScientificLineageBindingV2)
    attestation = _v2_attestation(binding)
    altered_identity = attestation.selected_intervention_identity.model_copy(
        update={"implementation_anchor": "alternate_component"}
    )
    altered = attestation.model_copy(
        update={"selected_intervention_identity": altered_identity}
    )

    findings = _lineage_attestation_findings(binding=binding, attestation=altered)

    assert any("selected_intervention_identity" in item for item in findings)


def test_v2_attestation_cannot_change_the_resource_request() -> None:
    binding = _build_plan_scientific_lineage_binding(_v2_context())
    assert isinstance(binding, PlanScientificLineageBindingV2)
    attestation = _v2_attestation(binding)
    altered = attestation.model_copy(
        update={
            "resource_request": attestation.resource_request.model_copy(
                update={
                    "seconds_per_cell": (
                        attestation.resource_request.seconds_per_cell + 1
                    )
                }
            )
        }
    )

    findings = _lineage_attestation_findings(binding=binding, attestation=altered)

    assert any("resource_request" in item for item in findings)


def test_v2_guard_rejects_atom_prose_pasted_only_into_risks() -> None:
    binding = _build_plan_scientific_lineage_binding(_v2_context())
    assert isinstance(binding, PlanScientificLineageBindingV2)
    atom = binding.selected_prospective_atom()
    plan = _v2_plan(binding).model_copy(
        update={
            "technical_details": "本计划技术细节改成另一个未绑定干预。",
            "methods": "本计划方法改成另一个未绑定干预，并保留引用[2][3]。",
            "baselines": ("另一个未绑定对照。",),
            "experiments": (
                binding.selected_direction.decisive_test,
                binding.selected_direction.negative_control,
                binding.selected_direction.sensitivity_control,
            ),
            "risks_and_alternatives": (
                atom.control_level_zh,
                atom.intervention_level_zh,
                atom.single_factor_rationale_zh,
                atom.falsifiable_single_factor_contrast_zh,
            ),
        }
    )

    findings = _plan_scientific_lineage_findings(plan=plan, binding=binding)

    assert any("control_level_zh" in item for item in findings)
    assert any("intervention_level_zh" in item for item in findings)
    assert any("falsifiable_single_factor_contrast_zh" in item for item in findings)


def test_v2_guard_rejects_other_atom_identity_and_missing_hook() -> None:
    binding = _build_plan_scientific_lineage_binding(_v2_context())
    assert isinstance(binding, PlanScientificLineageBindingV2)
    other = binding.component_experiment_binding.prospective_components.atoms[1]
    selected = binding.selected_intervention_identity
    incomplete_identity = selected.model_copy(
        update={"public_hooks": ("fit_equations",)}
    )
    plan = _v2_plan(binding).model_copy(
        update={
            "code_agent_brief": (
                "运行 python /harness/runner.py 并用 pytest 校验。"
                f"required_intervention_identity={_identity_declaration(incomplete_identity)} "
                f"随后调用 {other.implementation_anchor}。"
                "required_method_tokens=[prospective, counterfactual]"
            )
        }
    )

    findings = _plan_scientific_lineage_findings(plan=plan, binding=binding)

    assert any("required_intervention_identity" in item for item in findings)
    assert any(other.implementation_anchor in item for item in findings)


def test_a_system_selected_direction_is_bound_into_the_plan_prompt(
    tmp_path: Path,
) -> None:
    """A model-owned direction may guide its plan without becoming human prose."""

    direction = {
        "title": "反事实不变量驱动的方程发现",
        "core_mechanism": "以跨环境不变量筛除偶然相关项。",
        "decisive_test": "计划采用跨噪声环境的反事实交换检验。",
        "method_tokens": ["counterfactual", "invariance"],
    }
    payload = _authored(
        code_agent_brief=(
            "Run python /harness/runner.py --spec ... per frozen cell and validate "
            "with pytest. required_method_tokens=[counterfactual, invariance]"
        )
    )
    stub = _Stub(payload)
    artifact = _run(
        tmp_path,
        stub,
        frozen_context={
            **_FROZEN,
            "system_selected_research_direction": direction,
            "system_selected_research_direction_hash": "a" * 64,
        },
    )

    sent = json.dumps(stub.calls[0]["messages"], ensure_ascii=False)
    assert "反事实不变量驱动的方程发现" in sent
    assert "not human-authored science" in sent
    assert artifact.hand_written_prose_field_count == 0


def test_the_full_plan_cannot_abandon_selected_direction_tokens() -> None:
    report = guard_authored_plan(
        plan=_plan(),
        evidence_numbers={
            "0.05129329438755058",
            "-0.8448548894388439",
            "3",
            "12",
        },
        cited_evidence=[],
        container_entry_points=("/harness/runner.py",),
        required_direction_tokens=("counterfactual", "invariance"),
    )

    assert report.accepted is False
    assert any(
        "abandoned method identifiers" in finding for finding in report.findings
    )
    assert any("counterfactual" in finding for finding in report.findings)


def test_a_direction_number_does_not_become_observed_evidence(tmp_path: Path) -> None:
    """Prospective model prose must not launder a number into retained evidence."""

    direction = {
        "title": "反事实不变量驱动的方程发现",
        "core_mechanism": "计划采用 47.3 的候选扰动幅度。",
        "method_tokens": ["counterfactual", "invariance"],
    }
    payload = _authored(
        rationale=(
            "Prior evidence measured 47.3, so the counterfactual invariance mechanism "
            "is already supported."
        ),
        code_agent_brief=(
            "Run python /harness/runner.py --spec ... per frozen cell and validate "
            "with pytest. required_method_tokens=[counterfactual, invariance]"
        ),
    )

    with pytest.raises(SystemAuthoredPlanError, match="47.3"):
        _run(
            tmp_path,
            _Stub(payload),
            frozen_context={
                **_FROZEN,
                "system_selected_research_direction": direction,
                "system_selected_research_direction_hash": "b" * 64,
            },
            max_attempts=1,
        )


def test_production_default_refuses_an_english_authored_plan(tmp_path: Path) -> None:
    evidence = tmp_path / "prior-package.json"
    evidence.write_text("{}", encoding="utf-8")

    with pytest.raises(SystemAuthoredPlanError, match="简体中文"):
        author_research_plan(
            lineage_id="lineage-chinese-required",
            project_id="project-under-test",
            candidate_id="candidate-under-test",
            frozen_context=_FROZEN,
            evidence_paths=[evidence],
            output_dir=tmp_path,
            completion=_Stub(_authored()),
            container_entry_points=("/harness/runner.py",),
            max_attempts=1,
        )


def test_evidence_refs_are_derived_not_authored(tmp_path: Path) -> None:
    """A model must not be able to cite a package that was never written."""

    artifact = _run(tmp_path, _Stub(_authored()))
    refs = artifact.plan["evidence_refs"]
    assert refs and all(Path(item).exists() for item in refs)


def test_authoring_against_missing_evidence_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SystemAuthoredPlanError, match="does not exist"):
        author_research_plan(
            lineage_id="l",
            project_id="p",
            candidate_id="c",
            frozen_context=_FROZEN,
            evidence_paths=[tmp_path / "never-written.json"],
            output_dir=tmp_path,
            completion=_Stub(_authored()),
        )


# --------------------------------------------------------------------------
# The graders refuse, and each refusal says why
# --------------------------------------------------------------------------


def test_an_invented_number_is_refused() -> None:
    """The plan may only reason with numbers its own evidence contains."""

    report = guard_authored_plan(
        plan=_plan(
            problem_statement=(
                "The prior lineage lost 47.3 percent of its accuracy, so the "
                "selection rule is implicated across the panel."
            )
        ),
        evidence_numbers={"0.05129329438755058", "-0.8448548894388439", "3", "12"},
        cited_evidence=[],
    )
    assert report.numbers_traceable is False
    assert "47.3" in report.untraceable_numbers
    assert any("invented rather than derived" in f for f in report.findings)


def test_an_explicit_preregistered_design_constant_is_not_fake_evidence() -> None:
    report = guard_authored_plan(
        plan=_plan(
            methods=(
                "本计划预先固定正则化系数为47.3；该数值是前瞻性设计选择，"
                "不是既有观测或预期结果。"
            )
        ),
        evidence_numbers={"0.05129329438755058", "-0.8448548894388439", "3", "12"},
        cited_evidence=[],
    )

    assert "47.3" not in report.untraceable_numbers


def test_an_unfalsifiable_expectation_is_refused() -> None:
    """A plan that only describes success is an announcement, not a plan."""

    report = guard_authored_plan(
        plan=_plan(
            expected_results=(
                "The paired effect is expected to exceed the frozen minimum on every "
                "stratum, confirming the mechanism."
            )
        ),
        evidence_numbers=set(),
        cited_evidence=[],
    )
    assert report.states_falsifiable_expectation is False
    assert any("would REFUTE" in f for f in report.findings)


def test_claiming_an_achieved_result_is_refused() -> None:
    """No measurement exists when a plan is written."""

    report = guard_authored_plan(
        plan=_plan(
            rationale=(
                "We observed that held-out selection narrows the gap, so the same "
                "mechanism should hold here as a valid null is possible."
            )
        ),
        evidence_numbers=set(),
        cited_evidence=[],
    )
    assert report.claims_no_unobserved_result is False
    assert any("before any measurement exists" in f for f in report.findings)


def test_invisible_json_escape_control_character_is_refused() -> None:
    report = guard_authored_plan(
        plan=_plan(
            methods=(
                "Estimate the coefficient $\x08oldsymbol{\x08eta}$ with the same "
                "frozen metric and report a valid null."
            )
        ),
        evidence_numbers=set(),
        cited_evidence=[],
    )
    assert report.accepted is False
    assert any("控制字符" in finding for finding in report.findings)


def test_a_nonexistent_cited_artifact_is_refused(tmp_path: Path) -> None:
    report = guard_authored_plan(
        plan=_plan(),
        evidence_numbers=set(),
        cited_evidence=[tmp_path / "absent.json"],
    )
    assert report.all_cited_evidence_exists is False
    assert any("do not exist on disk" in f for f in report.findings)


def test_the_shared_quality_gate_still_applies() -> None:
    """This module must not invent a second, weaker standard."""

    report = guard_authored_plan(
        plan=_plan(methods="A qualitative comparison with no metric at all."),
        evidence_numbers=set(),
        cited_evidence=[],
    )
    assert report.quality_gate_passed is False
    assert any(f.startswith("quality gate:") for f in report.findings)


def test_the_guard_verdict_cannot_contradict_its_findings() -> None:
    report = guard_authored_plan(
        plan=_plan(), evidence_numbers=set(), cited_evidence=[]
    )
    payload = json.loads(report.model_dump_json())
    payload["accepted"] = not payload["accepted"]
    with pytest.raises(SystemAuthoredPlanError, match="contradicts its own"):
        type(report).model_validate(payload)


# --------------------------------------------------------------------------
# Teaching: a refusal returns the finding, and the model can repair
# --------------------------------------------------------------------------


def test_a_refusal_is_fed_back_and_the_model_repairs(tmp_path: Path) -> None:
    """A grader that only says no teaches nothing. The finding must go back."""

    bad = _authored(
        expected_results="The effect will exceed the frozen minimum on every stratum."
    )
    stub = _Stub(bad, _authored())
    artifact = _run(tmp_path, stub)

    assert artifact.authoring_attempts == 2
    assert artifact.guard_report.accepted is True
    # The second prompt carried the exact finding, not a generic complaint.
    second = json.dumps(stub.calls[1]["messages"])
    assert "REFUSED by the graders" in second
    assert "would REFUTE" in second
    # And it was told to change only what the findings name.
    assert "keep the rest of your plan" in second


def test_malformed_provider_json_is_retried_without_accepting_it(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []
    valid = _Stub(_authored())

    def flaky_completion(**kwargs: Any) -> LLMJsonCompletionResult:
        calls.append(kwargs)
        if len(calls) == 1:
            raise ValueError("LLM JSON completion was not valid JSON")
        return valid(**kwargs)

    artifact = _run(tmp_path, flaky_completion)

    assert artifact.authoring_attempts == 2
    assert artifact.guard_report.accepted is True
    repair_prompt = json.dumps(calls[1]["messages"], ensure_ascii=False)
    assert "JSON parse failed" in repair_prompt
    assert "do not change unaffected scientific content" in repair_prompt
    assert not (
        tmp_path / "interactions" / "system-authored-plan-attempt-01.json"
    ).exists()
    assert (
        tmp_path / "interactions" / "system-authored-plan-attempt-02.json"
    ).is_file()


def test_a_string_experiment_is_refused_not_split_into_characters(
    tmp_path: Path,
) -> None:
    malformed = _authored(
        experiments="这本应是 JSON 数组，绝不能被拆成逐字实验条目。"
    )
    stub = _Stub(malformed, _authored())
    artifact = _run(tmp_path, stub)

    assert artifact.authoring_attempts == 2
    assert len(artifact.plan["experiments"]) == 4
    repair_prompt = json.dumps(stub.calls[1]["messages"], ensure_ascii=False)
    assert "violates the required field shapes" in repair_prompt
    assert "experiments" in repair_prompt
    first_receipt = tmp_path / "interactions" / "system-authored-plan-attempt-01.json"
    assert first_receipt.is_file()
    retained = json.loads(first_receipt.read_text(encoding="utf-8"))
    assert isinstance(retained["parsed_payload"]["experiments"], str)


def test_mandatory_scientific_review_teaches_author_without_writing_plan(
    tmp_path: Path,
) -> None:
    reviews: list[int] = []

    def reviewer(_plan: ResearchPlan, attempt: int) -> tuple[str, ...]:
        reviews.append(attempt)
        if len(reviews) == 1:
            return ("创新主张与最近先前工作没有形成可检验差异。",)
        return ()

    stub = _Stub(_authored(), _authored())
    artifact = _run(tmp_path, stub, scientific_review=reviewer)

    assert artifact.authoring_attempts == 2
    assert reviews == [1, 2]
    repair_prompt = json.dumps(stub.calls[1]["messages"], ensure_ascii=False)
    assert "mandatory adversarial scientific review" in repair_prompt
    assert "创新主张" in repair_prompt
    assert "previous_system_authored_plan" in repair_prompt
    assert _authored()["title"] in repair_prompt
    assert "DISCARD that framing" in repair_prompt


def test_final_error_retains_scientific_review_findings(tmp_path: Path) -> None:
    def reviewer(_plan: ResearchPlan, _attempt: int) -> tuple[str, ...]:
        return ("创新性门禁拒绝：与最近先前工作没有实质差异。",)

    with pytest.raises(
        SystemAuthoredPlanError,
        match="创新性门禁拒绝",
    ):
        _run(
            tmp_path,
            _Stub(_authored()),
            scientific_review=reviewer,
            max_attempts=2,
        )


def test_a_model_that_cannot_meet_the_standard_fails_loudly(tmp_path: Path) -> None:
    """Bounded, so a non-conforming model cannot spin, and never downgraded."""

    bad = _authored(
        expected_results="The effect will exceed the frozen minimum on every stratum."
    )
    stub = _Stub(bad)
    with pytest.raises(SystemAuthoredPlanError, match="could not author a plan"):
        _run(tmp_path, stub, max_attempts=3)
    assert len(stub.calls) == 3


def test_a_refused_plan_is_never_persisted_as_accepted(tmp_path: Path) -> None:
    bad = _authored(
        expected_results="The effect will exceed the frozen minimum on every stratum."
    )
    with pytest.raises(SystemAuthoredPlanError):
        _run(tmp_path, _Stub(bad), max_attempts=2)
    assert not (tmp_path / "system-authored-research-plan.json").is_file()


def test_the_cycle_uses_bounded_reasoning(tmp_path: Path) -> None:
    stub = _Stub(_authored())
    _run(tmp_path, stub)
    assert stub.calls[0]["thinking_mode"] == "enabled"
    assert 0 < stub.calls[0]["thinking_budget"] <= 32_000


def test_concise_nonempty_method_reasoning_is_accepted(tmp_path: Path) -> None:
    context = {**_FROZEN, "system_selected_method_skills": {}}
    artifact = _run(
        tmp_path,
        _Stub(_authored(), reasoning_text="已核对。"),
        frozen_context=context,
    )

    assert artifact.plan["title"] == _authored()["title"]


def test_empty_method_reasoning_is_rejected(tmp_path: Path) -> None:
    context = {**_FROZEN, "system_selected_method_skills": {}}
    stub = _Stub(_authored(), reasoning_text="")

    with pytest.raises(SystemAuthoredPlanError, match="could not author a plan"):
        _run(
            tmp_path,
            stub,
            frozen_context=context,
            max_attempts=2,
        )

    assert len(stub.calls) == 2


def test_the_artifact_persists_and_round_trips(tmp_path: Path) -> None:
    artifact = _run(tmp_path, _Stub(_authored()))
    written = tmp_path / "system-authored-research-plan.json"
    assert written.is_file()
    assert json.loads(written.read_text(encoding="utf-8"))["artifact_hash"] == (
        artifact.artifact_hash
    )
    assert artifact.execution_authorized is False
    assert artifact.is_evidence is False


# --------------------------------------------------------------------------
# The graders must be FAIR as well as strict (P-20260804-087)
# --------------------------------------------------------------------------


def test_sentence_ending_digits_are_not_treated_as_invented_numbers() -> None:
    """A grader that penalises correct prose teaches the wrong lesson.

    The first live authoring run was refused partly for the token `7.`, which came from
    a sentence ending in "step 7." and can never appear in evidence. That was my bug,
    not the system's.
    """

    report = guard_authored_plan(
        plan=_plan(
            technical_details=(
                "The orchestrator freezes the artifact before prediction, as described "
                "in stage 7. Prediction then reads only that artifact."
            )
        ),
        evidence_numbers={"0.05129329438755058"},
        cited_evidence=[],
    )
    assert "7." not in report.untraceable_numbers


def test_budget_arithmetic_is_reachable_from_evidence() -> None:
    """A plan legitimately multiplies its own budget numbers.

    Writing "6 systems by 3 seeds is 18 cells" is sound reasoning, so refusing 18
    because it is absent from the frozen evidence penalises correct work.
    """

    from autoresearch.competition.system_authored_plan import plan_reachable_numbers

    reachable = plan_reachable_numbers({"6", "3"})
    assert "18" in reachable
    assert "9" in reachable


def test_an_expectation_phrased_with_outperform_is_permitted() -> None:
    """"is expected to outperform" is an expectation, not a claimed result."""

    report = guard_authored_plan(
        plan=_plan(
            expected_results=(
                "The candidate is expected to outperform the pinned baseline, and a "
                "negative result would refute the mechanism and is a valid outcome."
            )
        ),
        evidence_numbers=set(),
        cited_evidence=[],
    )
    assert report.claims_no_unobserved_result is True


def test_a_past_tense_result_claim_is_still_refused() -> None:
    """The relaxation must not open the door to asserting an achieved result."""

    report = guard_authored_plan(
        plan=_plan(
            rationale=(
                "The results showed that held-out selection narrows the gap, and a "
                "null outcome remains possible."
            )
        ),
        evidence_numbers=set(),
        cited_evidence=[],
    )
    assert report.claims_no_unobserved_result is False


def test_the_prompt_names_the_literal_words_the_grader_looks_for(tmp_path: Path) -> None:
    """Teach the standard before enforcing it."""

    stub = _Stub(_authored())
    _run(tmp_path, stub)
    sent = json.dumps(stub.calls[0]["messages"])
    assert "pytest" in sent
    assert "COMMAND-ORIENTED" in sent
    assert "required_method_tokens" in sent
    assert "unused helpers cannot pass" in sent


def test_a_command_without_method_tokens_is_not_an_executable_plan(tmp_path: Path) -> None:
    report = guard_authored_plan(
        plan=_plan(
            code_agent_brief=(
                "Run python /harness/runner.py --spec ... per frozen cell."
            )
        ),
        evidence_numbers=set(),
        cited_evidence=[],
        repo_root=tmp_path,
        container_entry_points=("/harness/runner.py",),
    )

    assert report.accepted is False
    assert any("2-8 distinctive method identifiers" in item for item in report.findings)


# --------------------------------------------------------------------------
# A brief must be RUNNABLE, not merely command-shaped (P-20260804-089)
# --------------------------------------------------------------------------


def test_a_brief_naming_a_nonexistent_script_is_refused(tmp_path: Path) -> None:
    """The defect found in the second live authoring run.

    The system wrote `pytest test_candidate.py --stratum-templates=stratified`, which
    contains the word `pytest` and so satisfied the quality rubric, but neither the
    script nor the flags exist anywhere. Command-shaped is not the same as runnable.
    """

    report = guard_authored_plan(
        plan=_plan(
            code_agent_brief=(
                "Run python -m pytest test_candidate.py --stratum-templates=strict "
                "to execute the full evaluation."
            )
        ),
        evidence_numbers=set(),
        cited_evidence=[],
        repo_root=tmp_path,
    )
    assert report.named_scripts_exist is False
    assert "test_candidate.py" in report.missing_script_paths
    assert any("cannot be executed as written" in f for f in report.findings)


def test_a_brief_naming_an_existing_script_is_accepted(tmp_path: Path) -> None:
    (tmp_path / "runner_entry.py").write_text("", encoding="utf-8")
    report = guard_authored_plan(
        plan=_plan(
            code_agent_brief=(
                "Run python runner_entry.py --spec ... per frozen cell, then validate."
            )
        ),
        evidence_numbers=set(),
        cited_evidence=[],
        repo_root=tmp_path,
    )
    assert report.named_scripts_exist is True


def test_a_declared_container_path_passes_the_host_check(tmp_path: Path) -> None:
    """A brief legitimately references the pinned container, IF it was declared.

    This test originally asserted that any absolute path skips checking. That was the
    escape hatch: the system then invented `/app/...` paths to satisfy the guard. The
    exemption is now an allowlist rather than a blanket pass.
    """

    report = guard_authored_plan(
        plan=_plan(
            code_agent_brief=(
                "Run python /harness/runner.py --spec ... --data ... per frozen cell "
                "with network disabled."
            )
        ),
        evidence_numbers=set(),
        cited_evidence=[],
        repo_root=tmp_path,
        container_entry_points=("/harness/runner.py",),
    )
    assert report.named_scripts_exist is True
    assert report.missing_script_paths == ()


def test_the_script_verdict_cannot_contradict_its_list(tmp_path: Path) -> None:
    report = guard_authored_plan(
        plan=_plan(
            code_agent_brief="Run python absent_thing.py --spec ... per frozen cell."
        ),
        evidence_numbers=set(),
        cited_evidence=[],
        repo_root=tmp_path,
    )
    payload = json.loads(report.model_dump_json())
    payload["named_scripts_exist"] = True
    with pytest.raises(SystemAuthoredPlanError, match="contradicts its own missing"):
        type(report).model_validate(payload)


def test_the_prompt_warns_against_inventing_a_script(tmp_path: Path) -> None:
    stub = _Stub(_authored())
    _run(tmp_path, stub)
    sent = json.dumps(stub.calls[0]["messages"])
    assert "must NOT invent a script name" in sent
    assert "RUNNABLE" in sent


def test_an_invented_container_path_is_refused(tmp_path: Path) -> None:
    """The escape hatch my first fix opened.

    Exempting absolute paths so a brief could reference the pinned container let the
    system satisfy the guard by inventing CONTAINER paths instead. An absolute path is
    now only accepted if the caller declared it as a real entry point.
    """

    report = guard_authored_plan(
        plan=_plan(
            code_agent_brief=(
                "Run python /app/run_grammar_conditioned_search.py --pilot-systems all "
                "to execute the pipeline."
            )
        ),
        evidence_numbers=set(),
        cited_evidence=[],
        repo_root=tmp_path,
        container_entry_points=("/harness/runner.py",),
    )
    assert report.named_scripts_exist is False
    assert "/app/run_grammar_conditioned_search.py" in report.missing_script_paths


def test_a_declared_container_entry_point_is_accepted(tmp_path: Path) -> None:
    report = guard_authored_plan(
        plan=_plan(
            code_agent_brief=(
                "Run python /harness/runner.py --spec ... --data ... per frozen cell "
                "with network disabled."
            )
        ),
        evidence_numbers=set(),
        cited_evidence=[],
        repo_root=tmp_path,
        container_entry_points=("/harness/runner.py",),
    )
    assert report.named_scripts_exist is True
    assert report.missing_script_paths == ()


def test_no_declared_entry_point_means_no_absolute_path_is_accepted(
    tmp_path: Path,
) -> None:
    """Silence must not be permission."""

    report = guard_authored_plan(
        plan=_plan(code_agent_brief="Run python /harness/runner.py --spec ... per cell."),
        evidence_numbers=set(),
        cited_evidence=[],
        repo_root=tmp_path,
    )
    assert report.named_scripts_exist is False


def test_the_prompt_lists_the_only_real_entry_points(tmp_path: Path) -> None:
    """Teach what exists, or the system can only guess."""

    evidence = tmp_path / "prior.json"
    evidence.write_text("{}", encoding="utf-8")
    stub = _Stub(_authored())
    author_research_plan(
        lineage_id="l",
        project_id="p",
        candidate_id="c",
        frozen_context=_FROZEN,
        evidence_paths=[evidence],
        output_dir=tmp_path,
        completion=stub,
        container_entry_points=("/harness/runner.py",),
        require_chinese=False,
    )
    sent = json.dumps(stub.calls[0]["messages"])
    assert "/harness/runner.py" in sent
    assert "ONLY entry points that exist" in sent
