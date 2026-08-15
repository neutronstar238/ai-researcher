from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.public_data_profile import PublicSystemDataProfile
from autoresearch.competition.system_plan_methodology import (
    AvailableMethodSkill,
    SystemPlanMethodSkillSelection,
    SystemPlanMethodSkillSelectionBinding,
)
from autoresearch.competition.system_plan_opportunity_map import (
    EvidenceFact,
    OpportunityCellAssessment,
    SystemPlanOpportunityMapError,
    _author_messages,
    _build_cross_lineage_system_effect_matrix,
    _build_exploratory_profile_effect_association_panel,
    build_research_feasibility_envelope,
    exploratory_evidence_panel_literature_view,
    finalize_system_plan_opportunity_review_from_receipts,
    repair_system_plan_opportunity_review_from_receipts,
    run_system_plan_opportunity_map,
)
from autoresearch.llm.client import LLMJsonCompletionResult


def _numeric_summary() -> dict[str, Any]:
    return {
        "count": 4,
        "finite_count": 4,
        "finite_fraction": 1.0,
        "zero_fraction": 0.0,
        "minimum": 1.0,
        "maximum": 4.0,
        "mean": 2.5,
        "standard_deviation": 1.118,
        "root_mean_square": 2.739,
    }


def _profile(system_name: str, data_type: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "public-development-data-profile-v1",
        "system_name": system_name,
        "data_type": data_type,
        "conditions_profiled": ["clean", "snr_20"],
        "clean_relative_path": f"data/{system_name}.npz",
        "clean_sha256": "a" * 64,
        "snr20_relative_path": f"data/{system_name}_snr_20.npz",
        "snr20_sha256": "b" * 64,
        "array_shapes": {"t": [4], "u": [4, 1], "du": [4, 1]},
        "array_dtypes": {"t": "<f8", "u": "<f8", "du": "<f8"},
        "coordinates": [
            {
                "name": "t",
                "values": _numeric_summary(),
                "spacing": _numeric_summary(),
                "strictly_increasing": True,
            }
        ],
        "sample_axis_count": 4,
        "channel_count": 1,
        "state_channel_max_abs_correlation": None,
        "derivative_channel_max_abs_correlation": None,
        "channels": [
            {
                "channel_index": 0,
                "clean_state": _numeric_summary(),
                "clean_derivative": _numeric_summary(),
                "state_derivative_correlation": 0.5,
                "snr20_state_noise_relative_rms": 0.1,
                "snr20_derivative_noise_relative_rms": 0.2,
                "snr20_state_empirical_snr_db": 20.0,
                "snr20_derivative_empirical_snr_db": 13.98,
                "boundary_to_interior_derivative_rms": None,
            }
        ],
    }
    payload["profile_hash"] = canonical_model_hash(payload)
    return payload


def _context() -> dict[str, Any]:
    return {
        "immutable_parent_protocol": {
            "contract_gate": {
                "network_default_deny": True,
                "fit_call_count": 1,
            },
            "estimand": {"independent_unit": "system"},
            "search_budget": {"maximum_seconds_per_cell": 300},
        },
        "public_development_panel": {
            "systems": [
                {"system_name": "eligible-a", "data_type": "ode"},
                {"system_name": "eligible-b", "data_type": "pde"},
                {"system_name": "excluded-c", "data_type": "pde"},
            ],
            "conditions": ["clean", "snr_20"],
            "seeds": [101, 211, 307],
        },
        "current_lineage_preregistered_boundaries": {
            "preregistered_baseline_policy": {
                "systems": [
                    {
                        "system_name": "eligible-a",
                        "data_type": "ode",
                        "handling": "paired_against_pinned_baseline",
                    },
                    {
                        "system_name": "eligible-b",
                        "data_type": "pde",
                        "handling": "paired_against_pinned_baseline",
                    },
                    {
                        "system_name": "excluded-c",
                        "data_type": "pde",
                        "handling": "excluded_from_paired_effect_declared_panel_change",
                        "mechanism": "baseline_incompatible",
                    },
                ]
            },
            "preregistered_stage_breadth": {"pilot_system_count": 2},
        },
        "public_development_data_profiles": [
            _profile("eligible-a", "ode"),
            _profile("eligible-b", "pde"),
        ],
        "retained_signed_prior_results": [
            {
                "lineage_id": "signed-parent",
                "package_hash": "a" * 64,
                "selected_candidate_id": "candidate-1",
                "selection_basis": "frozen",
                "selected_candidate_summary": "model authored prior candidate",
                "search_freeze_receipt_issued": False,
                "aggregate_results": {"overall_median_log_effect": -0.5},
                "gate_checks": {"overall_gate": False},
                "failure_reason_counts": [
                    {"failure_reason": "timeout", "count": 2}
                ],
                "system_effects": [
                    {
                        "system_name": "eligible-a",
                        "data_type": "ode",
                        "paired_log_effect": -0.4,
                    },
                    {
                        "system_name": "eligible-b",
                        "data_type": "pde",
                        "paired_log_effect": 0.2,
                    },
                ],
            }
        ],
    }


def test_cross_system_profile_effect_panel_is_complete_and_exploratory() -> None:
    profiles: list[PublicSystemDataProfile] = []
    effects: list[dict[str, Any]] = []
    for index in range(1, 6):
        name = f"system-{index}"
        payload = _profile(name, "ode")
        payload["channels"][0]["clean_derivative"]["root_mean_square"] = float(
            index
        )
        payload["channels"][0]["state_derivative_correlation"] = index / 10.0
        payload["profile_hash"] = canonical_model_hash(
            {key: value for key, value in payload.items() if key != "profile_hash"}
        )
        profiles.append(PublicSystemDataProfile.model_validate(payload))
        effects.append(
            {
                "system_name": name,
                "paired_log_effect": float(index) / 5.0,
                "candidate_cell_count": 6,
                "candidate_success_count": 6,
                "baseline_available": True,
            }
        )

    panel = _build_exploratory_profile_effect_association_panel(
        profiles=profiles,
        retained_result={
            "lineage_id": "signed-parent",
            "package_hash": "c" * 64,
            "system_effects": effects,
        },
    )

    assert panel is not None
    association = next(
        item
        for item in panel.associations
        if item.feature_name == "median_clean_derivative_root_mean_square"
    )
    assert association.spearman_rho == 1.0
    assert association.leave_one_system_out_sign_consistent is True
    assert len(association.leave_one_system_out_rhos) == 5
    assert association.data_types == ("ode",) * 5
    assert association.overall_data_type_confounding_not_ruled_out is True
    assert len(association.within_data_type_associations) == 1
    assert association.within_data_type_associations[0].data_type == "ode"
    assert association.within_data_type_associations[0].spearman_rho == 1.0
    assert panel.exploratory_only is True
    assert panel.excluded_incomplete_systems == ()
    assert (
        panel.source_effect_coverage_rule
        == "candidate_success_count_equals_candidate_cell_count_and_baseline_available"
    )
    assert panel.causal_interpretation_authorized is False
    assert panel.multiple_comparisons_adjusted is False
    assert panel.confirmatory_use_requires_new_preregistered_test is True


def test_cross_lineage_matrix_uses_only_compatible_fully_observed_effects() -> None:
    identity = {
        "plan_hash": "1" * 64,
        "development_panel_hash": "2" * 64,
        "runner_sha256": "3" * 64,
        "runtime_environment_hash": "4" * 64,
        "conditions": ["clean", "snr_20"],
    }

    def retained(index: int, *, second_successes: int) -> dict[str, Any]:
        return {
            "lineage_id": f"lineage-{index}",
            "package_hash": str(index) * 64,
            "identity_binding": identity,
            "selected_candidate_id": f"candidate-{index}",
            "selected_candidate_summary": f"model-authored candidate {index}",
            "search_freeze_receipt_issued": False,
            "system_effects": [
                {
                    "system_name": "system-a",
                    "data_type": "ode",
                    "candidate_median_loss": 0.2 + index,
                    "baseline_median_loss": 1.0,
                    "paired_log_effect": float(index),
                    "candidate_cell_count": 6,
                    "candidate_success_count": 6,
                    "baseline_available": True,
                },
                {
                    "system_name": "system-b",
                    "data_type": "pde",
                    "candidate_median_loss": 0.4 + index,
                    "baseline_median_loss": 1.0,
                    "paired_log_effect": -float(index),
                    "candidate_cell_count": 6,
                    "candidate_success_count": second_successes,
                    "baseline_available": True,
                },
            ],
        }

    matrix = _build_cross_lineage_system_effect_matrix(
        (retained(1, second_successes=3), retained(2, second_successes=6))
    )

    assert matrix is not None
    assert len(matrix.candidates) == 2
    assert len(matrix.coverage_ledger) == 4
    assert [item.system_name for item in matrix.comparable_system_rows] == [
        "system-a"
    ]
    assert matrix.candidate_differences_jointly_confounded is True
    assert matrix.component_attribution_authorized is False
    assert matrix.confirmatory_use_requires_model_authored_component_ablation is True
    view = exploratory_evidence_panel_literature_view(
        EvidenceFact(
            fact_id="E099",
            fact_kind="cross_lineage_effect_matrix",
            scope=(
                "retained_selected_candidates_cross_lineage_full_evaluation"
            ),
            source_locator="retained.cross_lineage",
            value=matrix.model_dump(mode="json"),
        )
    )
    assert view["matrix_hash"] == matrix.matrix_hash
    assert len(view["candidates"]) == 2
    assert len(view["comparable_system_rows"]) == 1
    assert len(view["excluded_incomplete_observations"]) == 1


def test_author_prompt_includes_exact_mechanical_cross_lineage_fact_index() -> None:
    context = _context()
    system_names = ["system-a", "system-b", "system-c"]
    context["public_development_panel"]["systems"] = [
        {"system_name": name, "data_type": "ode"} for name in system_names
    ]
    context["current_lineage_preregistered_boundaries"][
        "preregistered_baseline_policy"
    ]["systems"] = [
        {
            "system_name": name,
            "data_type": "ode",
            "handling": "paired_against_pinned_baseline",
        }
        for name in system_names
    ]
    context["public_development_data_profiles"] = [
        _profile(name, "ode") for name in system_names
    ]
    identity = {
        "plan_hash": "1" * 64,
        "development_panel_hash": "2" * 64,
        "runner_sha256": "3" * 64,
        "runtime_environment_hash": "4" * 64,
        "conditions": ["clean", "snr_20"],
    }
    context["retained_signed_prior_results"] = [
        {
            "lineage_id": f"lineage-{lineage_index}",
            "package_hash": str(lineage_index) * 64,
            "identity_binding": identity,
            "selected_candidate_id": f"candidate-{lineage_index}",
            "selected_candidate_summary": (
                f"model-authored candidate {lineage_index}"
            ),
            "search_freeze_receipt_issued": False,
            "system_effects": [
                {
                    "system_name": name,
                    "data_type": "ode",
                    "candidate_median_loss": 0.1 * lineage_index,
                    "baseline_median_loss": 1.0,
                    "paired_log_effect": 0.1 * lineage_index,
                    "candidate_cell_count": 6,
                    "candidate_success_count": 6,
                    "baseline_available": True,
                }
                for name in system_names
            ],
        }
        for lineage_index in (1, 2)
    ]

    envelope = build_research_feasibility_envelope(context)
    messages = _author_messages(
        envelope=envelope,
        retrieved_catalog=_catalog(),
        previous_map=None,
        prior_feedback=(),
    )
    user_content = messages[1]["content"]
    payload = json.loads(user_content)
    evidence_index = payload["mechanical_evidence_index"]
    facts = {item.fact_id: item for item in envelope.evidence_facts}

    assert user_content.index('"hard_machine_contract"') < user_content.index(
        '"frozen_feasibility_envelope"'
    )
    assert user_content.rfind('"final_hard_machine_contract_repeat"') > (
        user_content.rfind('"retrieved_prior_work_catalog"')
    )
    assert payload["hard_machine_contract"][
        "if_cross_lineage_matrix_fact_is_cited"
    ]["two_target_cells_are_always_invalid"] is True
    assert payload["hard_machine_contract"][
        "minimum_chinese_characters_per_prose_field"
    ] == 40
    assert payload["hard_machine_contract"]["required_identification_fields"] == [
        "single_component_counterfactual",
        "negative_control",
        "sensitivity_control",
        "orthogonal_diagnostic",
        "independent_analysis_unit",
        "result_blind_decision_rule",
        "resource_bounded_minimal_diagnostic",
    ]
    assert evidence_index[
        "hard_cross_lineage_comparable_system_whitelist"
    ] == system_names
    assert evidence_index["minimum_matrix_target_system_count"] == 3
    assert evidence_index["minimum_fully_observed_lineages_per_matrix_target"] == 2
    matrix_fact_ids = {
        fact_id
        for fact_id, fact in facts.items()
        if fact.fact_kind == "cross_lineage_effect_matrix"
    }
    assert matrix_fact_ids
    for system_name in system_names:
        required = evidence_index["required_matrix_facts_by_system"][system_name]
        profile_fact = facts[required["profile_fact_id"]]
        effect_facts = [
            facts[item["fact_id"]]
            for item in required["fully_observed_system_effects"]
        ]
        assert profile_fact.fact_kind == "data_profile"
        assert profile_fact.value["system_name"] == system_name
        assert len(effect_facts) == 2
        assert all(fact.fact_kind == "system_effect" for fact in effect_facts)
        assert all(
            fact.value["system_name"] == system_name for fact in effect_facts
        )
        assert set(required["cross_lineage_matrix_fact_ids"]) == matrix_fact_ids
    assert "抄号表" in messages[0]["content"]
    assert "两项在本轮无条件非法" in messages[0]["content"]


def _catalog() -> list[dict[str, Any]]:
    return [
        {
            "title": f"真实检索论文{index}",
            "publication_date": "2025-01-01",
            "doi": f"10.1000/{index}",
            "url": f"https://example.test/{index}",
            "abstract": "A retrieved abstract about equation discovery limits.",
        }
        for index in range(1, 5)
    ]


def _method_binding() -> SystemPlanMethodSkillSelectionBinding:
    content = (
        "---\nname: sparse-dynamics-identification\n"
        "description: 适用于稀疏动力学识别中的反事实和对照审查。\n---\n"
        "先核对证据范围，再冻结单一组件反事实，并设置负对照与正交诊断。"
    )
    skill = AvailableMethodSkill(
        skill_id="sparse-dynamics-identification",
        description="适用于稀疏动力学识别中的反事实、负对照和正交诊断审查。",
        source_relative_path="skills/sparse-dynamics-identification/SKILL.md",
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        content=content,
    )
    selection = SystemPlanMethodSkillSelection(
        task_classification="当前任务属于稀疏动力学方程识别的证据约束研究机会发现。",
        selected_skill_ids=(skill.skill_id,),
        rejected_skill_ids=(),
        selection_rationale=(
            "该技能直接覆盖单组件反事实、负对照、正交诊断与结果盲裁决，"
            "并能防止从联合变化直接推断单一机制。"
        ),
        planned_reasoning_stages=(
            "先核对冻结事实的来源和适用范围。",
            "再识别尚未解决且能够测量的矛盾。",
            "随后定义只改变一个组件的反事实。",
            "同时配置负对照与敏感性对照。",
            "再使用独立系统作为统计分析单位。",
            "最后执行资源上界与最近文献审查。",
        ),
        auditable_reasoning_summary=(
            "冻结事实先于任何机制解释。",
            "系统名称不能替代直接测量证据。",
            "联合变化不能归因到单一组件。",
            "正负零三类结果都必须可解释。",
            "技能内容不是科研事实或实验结果。",
        ),
        non_evidence_boundary=(
            "技能和推理过程只约束研究方法，不构成任何事实、实验结果或机制证据，"
            "也不能替代真实文献和冻结数据。"
        ),
    )
    return SystemPlanMethodSkillSelectionBinding(
        selection_artifact_hash="a" * 64,
        selection=selection,
        selected_skills=(skill,),
    )


def _map() -> dict[str, Any]:
    opportunities: list[dict[str, Any]] = []
    for index in range(1, 8):
        evidence_fact_ids = [
            "E014",
            "E015",
            "E004",
            "E005",
            ("E001", "E002", "E003", "E006", "E007", "E008", "E009")[
                index - 1
            ],
        ]
        opportunities.append(
            {
                "cell_id": f"O{index:02d}",
                "evidence_fact_ids": evidence_fact_ids,
                "literature_indices": [1, 2, 3],
                "unresolved_contradiction": (
                    f"第{index}格的冻结观测与现有解释之间仍有无法由总体分数消除的证据矛盾。"
                ),
                "operational_construct": (
                    "该构念由同一系统内干预前后的可重复差值定义，并与其他统计量分开记录。"
                ),
                "mechanism_preconditions": [
                    "目标系统保留原始状态变量与时间顺序。",
                    "干预前后使用完全一致的冻结数据切分。",
                ],
                "eligible_target_systems": ["eligible-a", "eligible-b"],
                "manipulable_factor": (
                    "只改变一个预注册机制因素并冻结其余全部执行条件。"
                ),
                "measurable_outcome": (
                    "记录独立系统层面的方向性变化和对应正交诊断。"
                ),
                "alternative_explanation": (
                    "观测变化可能完全来自实现差异而不是目标机制。"
                ),
                "single_component_counterfactual": (
                    "处理臂只启用一个预注册因素，对照臂关闭该因素，数据、代码路径、预算与随机种子全部冻结一致。"
                ),
                "negative_control": (
                    "使用不改变目标因素的伪操作作为负对照，并记录它是否复现与处理臂相同的实现扰动读数。"
                ),
                "sensitivity_control": (
                    "在结果揭盲前固定三个扰动强度重复同一比较，只报告方向是否保持而不事后选择强度。"
                ),
                "orthogonal_diagnostic": (
                    "另行记录不参与主损失计算的结构诊断量，用它检验目标因素是否沿预声明路径发生变化。"
                ),
                "independent_analysis_unit": (
                    "独立分析单位为系统，条件与种子只作为系统内重复而不扩充独立样本量。"
                ),
                "result_blind_decision_rule": (
                    "处理臂改变且两类对照稳定时支持目标解释，负对照同向变化时支持替代解释，其余结果判为无法区分。"
                ),
                "resource_bounded_minimal_diagnostic": (
                    "每个正式单元只执行一对固定配置且不搜索超参数，时间上界三百秒、内存上界四千零九十六兆字节。"
                ),
                "discriminating_observation": (
                    "只有目标干预改变主要结局而语义保持对照和实现对照均不改变时才区分机制。"
                ),
                "expected_directional_pattern": (
                    "主要结局只在目标干预下沿预注册方向变化，并在两个正交对照下保持稳定。"
                ),
                "refuting_observation": (
                    "若目标干预与实现对照产生同方向变化，或主要结局保持不变，则目标机制被反驳。"
                ),
                "why_not_component_composition": (
                    "判断依据是可独立操纵和反驳的关系，而不是已有算法模块组合后的总分。"
                ),
                "feasibility_risk": (
                    "冻结样本可能不足以稳定估计独立系统层面的方向性差异。"
                ),
                "method_application_trace": {
                    "verified_fact_ids": evidence_fact_ids,
                    "evidence_scope_audit": (
                        "逐项核对事实范围后，只保留能够归因到所列目标系统和冻结候选的观测。"
                    ),
                    "changed_component": (
                        "唯一改变预注册的目标机制因素，不同时改变模型结构或数据切分。"
                    ),
                    "frozen_components": [
                        "冻结公开数据与样本切分。",
                        "冻结候选代码路径与随机种子。",
                        "冻结预算、评价指标和停止规则。",
                    ],
                    "negative_control_audit": (
                        "负对照只复现实现扰动而不触发目标因素，用于识别实现差异这一替代解释。"
                    ),
                    "orthogonal_diagnostic_audit": (
                        "正交诊断不参与主损失计算，并沿预声明机制路径记录独立结构读数。"
                    ),
                    "independent_unit_audit": (
                        "统计推断以系统为独立单位，条件和种子仅作为系统内部的重复观测。"
                    ),
                    "target_mechanism_outcome": (
                        "只有处理臂按预声明方向改变且两个对照稳定时，结果才支持目标机制解释。"
                    ),
                    "alternative_explanation_outcome": (
                        "若负对照或实现对照出现同向改变，则结果支持实现扰动这一替代解释。"
                    ),
                    "indeterminate_outcome": (
                        "若处理臂与对照均无稳定差异或诊断互相冲突，则明确判定为无法区分。"
                    ),
                    "resource_bound_audit": (
                        "每个正式单元只运行一对冻结配置，不搜索参数并遵守三百秒和内存上界。"
                    ),
                    "closest_prior_reference_indices": [1, 2, 3],
                    "closest_prior_gap_audit": (
                        "逐篇比较三项近邻工作后，只保留其未提供同一单组件干预与三结果裁决的缺口。"
                    ),
                },
            }
        )
    return {"opportunities": opportunities}


def _review(
    *,
    ready: bool = True,
    cell_count: int = 7,
    accepted_count: int | None = None,
) -> dict[str, Any]:
    assessments: list[dict[str, Any]] = []
    accepted = (
        min(accepted_count if accepted_count is not None else 5, cell_count)
        if ready
        else 0
    )
    for index in range(1, cell_count + 1):
        passes = index <= accepted
        assessments.append(
            {
                "cell_id": f"O{index:02d}",
                "supporting_fact_ids": ["E014", "E015", "E004", "E005"],
                "supporting_literature_indices": [1, 2, 3],
                "evidence_grounded": passes,
                "prerequisite_matches_target": passes,
                "intervention_preserves_semantics": passes,
                "alternative_is_distinguishable": passes,
                "feasible_under_frozen_contract": passes,
                "gap_not_covered_by_catalog": passes,
                "generalizable_scientific_question": passes,
                "critical_findings": (
                    []
                    if passes
                    else ["该机会的证据仍不足以排除实现差异这一替代解释。"]
                ),
            }
        )
    return {
        "schema_version": "research-opportunity-map-review-v3",
        "assessments": assessments,
        "accepted_cell_ids": [f"O{index:02d}" for index in range(1, accepted + 1)],
        "review_summary": (
            "逐格审查严格核对事实、机制前提、干预语义、替代解释、冻结预算与完整文献目录。"
        ),
        "map_ready": ready,
    }


def test_positive_booleans_with_scientific_veto_are_conservatively_rejected() -> None:
    assessment = OpportunityCellAssessment(
        cell_id="O01",
        supporting_fact_ids=("E001",),
        supporting_literature_indices=(1,),
        evidence_grounded=True,
        prerequisite_matches_target=True,
        intervention_preserves_semantics=True,
        alternative_is_distinguishable=True,
        feasible_under_frozen_contract=True,
        gap_not_covered_by_catalog=True,
        generalizable_scientific_question=True,
        critical_findings=("仍存在足以否决该机会格的科学问题，应按保守规则拒绝。",),
    )
    assert assessment.qualifies() is False


class _Stub:
    def __init__(self, *payloads: dict[str, Any]) -> None:
        self.payloads = list(payloads)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        self.calls.append(kwargs)
        payload = self.payloads[len(self.calls) - 1]
        return LLMJsonCompletionResult(
            provider="qwen-dashscope",
            base_url="https://dashscope.example/compatible-mode/v1",
            model_name="qwen3.7-max",
            endpoint="https://dashscope.example/v1/chat/completions",
            response_text=json.dumps(payload, ensure_ascii=False),
            parsed_json=payload,
            usage={},
            temperature=float(kwargs["temperature"]),
            reasoning_text="系统逐项核对证据范围、反事实、对照与结果盲规则。" * 20,
            reasoning_transport="dashscope_enable_thinking",
        )


def test_envelope_excludes_ineligible_system_and_indexes_signed_facts() -> None:
    envelope = build_research_feasibility_envelope(_context())

    assert [item.system_name for item in envelope.eligible_systems] == [
        "eligible-a",
        "eligible-b",
    ]
    assert [item.system_name for item in envelope.excluded_systems] == ["excluded-c"]
    assert any(item.fact_kind == "system_effect" for item in envelope.evidence_facts)
    assert any(item.fact_kind == "gate_check" for item in envelope.evidence_facts)
    assert envelope.execution_semantics["synthetic_sentinel_budget"]["scope"] == (
        "small_synthetic_contract_sentinels_only"
    )
    assert envelope.execution_semantics["equation_output_rule"][
        "numeric_literals_are_free_symbols"
    ] is False
    assert len(envelope.envelope_hash) == 64


def test_accepted_map_is_chinese_model_authored_hash_bound_and_unapproved(
    tmp_path: Path,
) -> None:
    stub = _Stub(_map(), _review())

    artifact = run_system_plan_opportunity_map(
        lineage_id="lineage-opportunity",
        frozen_evidence_context=_context(),
        retrieved_catalog=_catalog(),
        output_dir=tmp_path,
        completion=stub,
    )

    assert len(artifact.accepted_cells) == 5
    assert artifact.authored_by_model is True
    assert artifact.hand_written_scientific_prose_count == 0
    assert artifact.execution_authorized is False
    assert artifact.is_scientific_evidence is False
    assert artifact.binding().opportunity_map_hash == artifact.artifact_hash
    assert (tmp_path / "system-plan-opportunity-map.json").is_file()
    assert (tmp_path / artifact.map_authorship_receipt_relative_path).is_file()
    assert (tmp_path / artifact.review_authorship_receipt_relative_path).is_file()
    prompt = json.dumps(stub.calls[0]["messages"], ensure_ascii=False)
    assert "不能提出算法、完整假设或研究计划" in prompt
    assert "excluded_systems" in prompt
    assert "第1格的冻结观测" not in prompt
    review_prompt = stub.calls[1]["messages"][0]["content"]
    assert stub.calls[0]["max_tokens"] == 18_000
    assert "可以七格全部拒绝" in review_prompt
    assert "不得因后续需要五个方向而放宽" in review_prompt


def test_one_strictly_accepted_cell_is_enough_for_later_divergence(
    tmp_path: Path,
) -> None:
    stub = _Stub(_map(), _review(accepted_count=1))

    artifact = run_system_plan_opportunity_map(
        lineage_id="lineage-one-accepted-opportunity",
        frozen_evidence_context=_context(),
        retrieved_catalog=_catalog(),
        output_dir=tmp_path,
        completion=stub,
    )

    assert [item.cell_id for item in artifact.accepted_cells] == ["O01"]
    assert artifact.review.map_ready is True


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("evidence_fact_ids", ["E014", "E999"], "不存在的证据事实"),
        ("literature_indices", [1, 2, 99], "不存在的检索目录"),
        ("eligible_target_systems", ["excluded-c"], "可研究系统集合"),
    ],
)
def test_invalid_model_binding_is_repaired_then_fails_closed(
    tmp_path: Path,
    field: str,
    value: list[Any],
    message: str,
) -> None:
    invalid = _map()
    invalid["opportunities"][0][field] = value
    if field == "evidence_fact_ids":
        invalid["opportunities"][0]["method_application_trace"][
            "verified_fact_ids"
        ] = value
    elif field == "literature_indices":
        invalid["opportunities"][0]["method_application_trace"][
            "closest_prior_reference_indices"
        ] = value
    stub = _Stub(invalid, invalid)

    with pytest.raises(SystemPlanOpportunityMapError, match=message):
        run_system_plan_opportunity_map(
            lineage_id="lineage-invalid-map",
            frozen_evidence_context=_context(),
            retrieved_catalog=_catalog(),
            output_dir=tmp_path,
            completion=stub,
            max_attempts=1,
        )
    assert len(stub.calls) == 2
    assert not (tmp_path / "system-plan-opportunity-map.json").exists()


def test_all_candidate_failure_counts_cannot_be_attributed_to_named_systems(
    tmp_path: Path,
) -> None:
    invalid = _map()
    invalid["opportunities"][0]["evidence_fact_ids"] = [
        "E013",
        "E014",
        "E004",
    ]
    invalid["opportunities"][0]["method_application_trace"][
        "verified_fact_ids"
    ] = ["E013", "E014", "E004"]
    invalid["opportunities"][0]["eligible_target_systems"] = ["eligible-a"]
    stub = _Stub(invalid, invalid)

    with pytest.raises(SystemPlanOpportunityMapError, match="全候选/全阶段"):
        run_system_plan_opportunity_map(
            lineage_id="lineage-invalid-scope-join",
            frozen_evidence_context=_context(),
            retrieved_catalog=_catalog(),
            output_dir=tmp_path,
            completion=stub,
            max_attempts=1,
        )
    assert not (tmp_path / "system-plan-opportunity-map.json").exists()


def test_duplicate_evidence_target_pair_is_stably_removed_before_review(
    tmp_path: Path,
) -> None:
    invalid = _map()
    invalid["opportunities"][1]["evidence_fact_ids"] = list(
        invalid["opportunities"][0]["evidence_fact_ids"]
    )
    invalid["opportunities"][1]["method_application_trace"][
        "verified_fact_ids"
    ] = list(invalid["opportunities"][0]["evidence_fact_ids"])
    stub = _Stub(invalid, _review(cell_count=6))

    artifact = run_system_plan_opportunity_map(
        lineage_id="lineage-duplicate-opportunities",
        frozen_evidence_context=_context(),
        retrieved_catalog=_catalog(),
        output_dir=tmp_path,
        completion=stub,
        max_attempts=1,
    )

    assert len(artifact.opportunity_map.opportunities) == 6
    assert artifact.removed_duplicate_cell_ids == ("O02",)
    assert artifact.deterministic_normalization_rule.startswith("first_cell")


def test_independent_reviewer_may_reject_every_opportunity(tmp_path: Path) -> None:
    stub = _Stub(_map(), _review(ready=False))

    with pytest.raises(SystemPlanOpportunityMapError, match="至少一个"):
        run_system_plan_opportunity_map(
            lineage_id="lineage-all-rejected",
            frozen_evidence_context=_context(),
            retrieved_catalog=_catalog(),
            output_dir=tmp_path,
            completion=stub,
            max_attempts=1,
        )
    assert not (tmp_path / "system-plan-opportunity-map.json").exists()


def test_hash_valid_rejected_receipts_resume_the_system_self_loop(
    tmp_path: Path,
) -> None:
    prior_root = tmp_path / "prior"
    rejected = _Stub(_map(), _review(ready=False))
    with pytest.raises(SystemPlanOpportunityMapError, match="至少一个"):
        run_system_plan_opportunity_map(
            lineage_id="lineage-rejected-receipts",
            frozen_evidence_context=_context(),
            retrieved_catalog=_catalog(),
            output_dir=prior_root,
            completion=rejected,
            max_attempts=1,
        )

    resumed = _Stub(_map(), _review())
    output_root = tmp_path / "resumed"
    artifact = run_system_plan_opportunity_map(
        lineage_id="lineage-rejected-receipts",
        frozen_evidence_context=_context(),
        retrieved_catalog=_catalog(),
        output_dir=output_root,
        completion=resumed,
        resume_author_receipt_path=(
            prior_root / "interactions" / "system-plan-opportunity-map-attempt-01.json"
        ),
        resume_review_receipt_path=(
            prior_root
            / "interactions"
            / "system-plan-opportunity-review-attempt-01.json"
        ),
        max_attempts=1,
    )

    assert artifact.review.map_ready is True
    prompt = json.dumps(resumed.calls[0]["messages"], ensure_ascii=False)
    assert "previous_system_authored_opportunity_map" in prompt
    assert "逐格审查严格核对事实" in prompt


def test_non_chinese_review_is_repaired_without_rewriting_map(tmp_path: Path) -> None:
    invalid_review = _review()
    invalid_review["review_summary"] = "Five cells pass all scientific gates."
    stub = _Stub(_map(), invalid_review, _review())

    artifact = run_system_plan_opportunity_map(
        lineage_id="lineage-review-repair",
        frozen_evidence_context=_context(),
        retrieved_catalog=_catalog(),
        output_dir=tmp_path,
        completion=stub,
        max_attempts=1,
    )

    assert artifact.review.map_ready is True
    assert len(stub.calls) == 3
    repair_prompt = json.dumps(stub.calls[2]["messages"], ensure_ascii=False)
    assert "previous_system_authored_opportunity_review" in repair_prompt
    assert "机会图评审不是中文" in repair_prompt
    assert "不得借修复改成通过" in repair_prompt


def test_reviewer_must_cite_the_cell_evidence_and_real_catalog(
    tmp_path: Path,
) -> None:
    invalid_review = _review()
    invalid_review["assessments"][0]["supporting_fact_ids"] = ["E999"]
    invalid_review["assessments"][0]["supporting_literature_indices"] = [4]
    stub = _Stub(_map(), invalid_review, _review())

    artifact = run_system_plan_opportunity_map(
        lineage_id="lineage-review-binding-repair",
        frozen_evidence_context=_context(),
        retrieved_catalog=_catalog(),
        output_dir=tmp_path,
        completion=stub,
        max_attempts=1,
    )

    assert artifact.review.map_ready is True
    repair_prompt = json.dumps(stub.calls[2]["messages"], ensure_ascii=False)
    assert "不存在的证据事实" in repair_prompt
    assert "没有引用该机会格自己的任何近邻文献" in repair_prompt


def test_reviewer_cannot_apply_synthetic_sentinel_budget_to_official_cells(
    tmp_path: Path,
) -> None:
    invalid_review = _review(accepted_count=1)
    invalid_review["assessments"][1]["critical_findings"].insert(
        0, "maximum_fit_seconds_per_sentinel=20，因此正式系统诊断必然超时。"
    )
    stub = _Stub(_map(), invalid_review, _review(accepted_count=1))

    artifact = run_system_plan_opportunity_map(
        lineage_id="lineage-review-budget-scope-repair",
        frozen_evidence_context=_context(),
        retrieved_catalog=_catalog(),
        output_dir=tmp_path,
        completion=stub,
        max_attempts=1,
    )

    assert [item.cell_id for item in artifact.accepted_cells] == ["O01"]
    repair_prompt = json.dumps(stub.calls[2]["messages"], ensure_ascii=False)
    assert "错把合成 sentinel 契约" in repair_prompt
    assert "300 秒/4096 MB" in repair_prompt


def test_author_cannot_apply_synthetic_sentinel_budget_to_official_cells(
    tmp_path: Path,
) -> None:
    invalid_map = _map()
    invalid_map["opportunities"][0]["feasibility_risk"] = (
        "20 秒 sentinel 预算不足，因此正式系统机会可能无法执行。"
    )
    stub = _Stub(invalid_map, _map(), _review(accepted_count=1))

    artifact = run_system_plan_opportunity_map(
        lineage_id="lineage-author-budget-scope-repair",
        frozen_evidence_context=_context(),
        retrieved_catalog=_catalog(),
        output_dir=tmp_path,
        completion=stub,
        max_attempts=2,
    )

    assert [item.cell_id for item in artifact.accepted_cells] == ["O01"]
    assert len(stub.calls) == 3
    repair_prompt = json.dumps(stub.calls[1]["messages"], ensure_ascii=False)
    assert "仅适用于小型合成 sentinel" in repair_prompt
    assert "O01.feasibility_risk" in repair_prompt
    initial_prompt = stub.calls[0]["messages"][0]["content"]
    assert "任何科研字段均不得使用 sentinel" in initial_prompt


def test_machine_invalid_review_can_be_repaired_from_hash_valid_receipts(
    tmp_path: Path,
) -> None:
    prior_root = tmp_path / "invalid-review"
    method_binding = _method_binding()
    invalid_review = _review(accepted_count=1)
    invalid_review["assessments"][1]["critical_findings"].insert(
        0, "maximum_predict_seconds_per_query=2，因此正式系统诊断必然超时。"
    )
    invalid_stub = _Stub(
        _map(), invalid_review, invalid_review, invalid_review
    )
    with pytest.raises(SystemPlanOpportunityMapError, match="至少一个"):
        run_system_plan_opportunity_map(
            lineage_id="lineage-invalid-review-receipt",
            frozen_evidence_context=_context(),
            retrieved_catalog=_catalog(),
            output_dir=prior_root,
            completion=invalid_stub,
            method_skill_selection=method_binding,
            max_attempts=1,
        )

    repaired_stub = _Stub(_review(accepted_count=1))
    output_root = tmp_path / "review-repaired"
    artifact = repair_system_plan_opportunity_review_from_receipts(
        lineage_id="lineage-invalid-review-receipt",
        frozen_evidence_context=_context(),
        retrieved_catalog=_catalog(),
        author_receipt_path=(
            prior_root / "interactions" / "system-plan-opportunity-map-attempt-01.json"
        ),
        invalid_review_receipt_path=(
            prior_root
            / "interactions"
            / "system-plan-opportunity-review-attempt-01.json"
        ),
        output_dir=output_root,
        review_completion=repaired_stub,
    )

    assert [item.cell_id for item in artifact.accepted_cells] == ["O01"]
    assert artifact.method_skill_selection == method_binding
    assert artifact.map_authorship_receipt_relative_path.startswith(
        "interactions/retained-"
    )
    assert (
        output_root / artifact.map_authorship_receipt_relative_path
    ).is_file()


def test_machine_repair_cannot_turn_a_false_scientific_gate_true(
    tmp_path: Path,
) -> None:
    invalid_review = _review(ready=False)
    invalid_review["assessments"][0]["supporting_fact_ids"] = ["E999"]
    flipped_review = _review(accepted_count=1)
    stub = _Stub(_map(), invalid_review, flipped_review, flipped_review)

    with pytest.raises(SystemPlanOpportunityMapError, match="false 改为 true"):
        run_system_plan_opportunity_map(
            lineage_id="lineage-monotonic-false-gate",
            frozen_evidence_context=_context(),
            retrieved_catalog=_catalog(),
            output_dir=tmp_path,
            completion=stub,
            max_attempts=1,
        )
    assert not (tmp_path / "system-plan-opportunity-map.json").exists()


def test_machine_repair_cannot_delete_scientific_veto_text(
    tmp_path: Path,
) -> None:
    invalid_review = _review()
    scientific_veto = "该构念仍由多组件共同变化所混杂，现有比较无法识别单一机制。"
    invalid_review["assessments"][0]["critical_findings"] = [scientific_veto]
    repaired_by_deletion = _review()
    stub = _Stub(
        _map(), invalid_review, repaired_by_deletion, repaired_by_deletion
    )

    with pytest.raises(SystemPlanOpportunityMapError, match="删除了既有科学否决理由"):
        run_system_plan_opportunity_map(
            lineage_id="lineage-monotonic-veto-text",
            frozen_evidence_context=_context(),
            retrieved_catalog=_catalog(),
            output_dir=tmp_path,
            completion=stub,
            max_attempts=1,
        )
    assert not (tmp_path / "system-plan-opportunity-map.json").exists()


def test_exact_invalid_scope_sentences_can_be_auditably_filtered(
    tmp_path: Path,
) -> None:
    prior_root = tmp_path / "scope-invalid-review"
    invalid_review = _review(accepted_count=1)
    invalid_sentence = (
        "fit_call_count=1，因此该正式系统机会无法完成必要的拟合诊断。"
    )
    invalid_review["assessments"][1]["critical_findings"] = [
        invalid_sentence,
        "该机会尚未给出能够区分目标机制与数值尺度效应的正交对照。",
    ]
    invalid_stub = _Stub(
        _map(), invalid_review, invalid_review, invalid_review
    )
    with pytest.raises(SystemPlanOpportunityMapError, match="至少一个"):
        run_system_plan_opportunity_map(
            lineage_id="lineage-scope-filter",
            frozen_evidence_context=_context(),
            retrieved_catalog=_catalog(),
            output_dir=prior_root,
            completion=invalid_stub,
            max_attempts=1,
        )

    output_root = tmp_path / "scope-filtered"
    source_review_hash = canonical_model_hash(invalid_review)
    artifact = finalize_system_plan_opportunity_review_from_receipts(
        lineage_id="lineage-scope-filter",
        frozen_evidence_context=_context(),
        retrieved_catalog=_catalog(),
        author_receipt_path=(
            prior_root / "interactions" / "system-plan-opportunity-map-attempt-01.json"
        ),
        review_receipt_path=(
            prior_root
            / "interactions"
            / "system-plan-opportunity-review-attempt-01.json"
        ),
        output_dir=output_root,
    )

    assert [item.cell_id for item in artifact.accepted_cells] == ["O01"]
    assert artifact.source_review_hash == source_review_hash
    assert len(artifact.removed_invalid_review_findings) == 1
    removed = artifact.removed_invalid_review_findings[0]
    assert removed.cell_id == "O02"
    assert removed.finding_index == 0
    assert removed.finding == invalid_sentence
    assert artifact.review.assessments[1].critical_findings == (
        "该机会尚未给出能够区分目标机制与数值尺度效应的正交对照。",
    )
