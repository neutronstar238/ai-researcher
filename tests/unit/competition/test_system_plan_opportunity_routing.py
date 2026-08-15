from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.system_plan_component_atoms import (
    SystemPlanComponentAtom,
    SystemPlanComponentAtomBinding,
)
from autoresearch.competition.system_plan_methodology import (
    AvailableMethodSkill,
    SystemPlanMethodSkillSelection,
    SystemPlanMethodSkillSelectionBinding,
)
from autoresearch.competition.system_plan_opportunity_map import (
    CrossLineageSystemEffectMatrix,
    EvidenceFact,
    ExploratoryProfileEffectAssociationPanel,
    ResearchFeasibilityEnvelope,
)
from autoresearch.competition.system_plan_opportunity_routing import (
    OpportunityWorkerRoutePortfolio,
    SystemPlanOpportunityRoutingError,
    build_compact_opportunity_routing_context,
    run_system_plan_opportunity_routing,
)
from autoresearch.llm.client import LLMJsonCompletionResult

SYSTEM_NAMES = tuple(f"system-{index}" for index in range(1, 8))
LINEAGE_A = "signed-lineage-a"
LINEAGE_B = "signed-lineage-b"
QUOTES = (
    "候选组件片段甲一",
    "候选组件片段乙二",
    "候选组件片段丙三",
    "候选组件片段丁四",
    "候选组件片段戊五",
    "候选组件片段己六",
    "候选组件片段庚七",
)


def _method_binding() -> SystemPlanMethodSkillSelectionBinding:
    content = (
        "---\nname: placeholder-method\n---\n"
        "本技能只规定先核对证据范围，再执行单组件核查、负对照、正交诊断和资源审计。"
    )
    skill = AvailableMethodSkill(
        skill_id="placeholder-method",
        description="面向占位测试任务的证据核对、单组件派工和结果盲审计方法。",
        source_relative_path="skills/placeholder-method/SKILL.md",
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        content=content,
    )
    selection = SystemPlanMethodSkillSelection(
        task_classification="当前阶段只进行证据约束的临时工作派工，不生成任何具体科研结论。",
        selected_skill_ids=(skill.skill_id,),
        rejected_skill_ids=(),
        selection_rationale="该占位技能明确要求核对事实、单组件边界和非证据属性，适合机械路由测试。",
        planned_reasoning_stages=(
            "先核对候选摘要来源。",
            "再核对目标系统白名单。",
            "随后核对逐系统事实编号。",
            "接着核对跨谱系矩阵范围。",
            "然后核对真实文献编号。",
            "最后冻结临时派工边界。",
        ),
        auditable_reasoning_summary=(
            "本步骤只产生派工。",
            "证据编号必须完整。",
            "候选引文必须逐字。",
            "技能不构成事实。",
            "派工不授权执行。",
        ),
        non_evidence_boundary="技能和推理内容只约束派工方法，不构成科研证据、实验结果或已成立结论。",
    )
    return SystemPlanMethodSkillSelectionBinding(
        selection_artifact_hash="e" * 64,
        selection=selection,
        selected_skills=(skill,),
    )


def _matrix() -> CrossLineageSystemEffectMatrix:
    summaries = {
        LINEAGE_A: "签名候选摘要甲：" + "；".join(QUOTES[:4]) + "。",
        LINEAGE_B: "签名候选摘要乙：" + "；".join(QUOTES[4:]) + "。",
    }
    candidates = []
    for index, (lineage_id, package_hash, candidate_id) in enumerate(
        (
            (LINEAGE_A, "a" * 64, "candidate-a"),
            (LINEAGE_B, "b" * 64, "candidate-b"),
        ),
        1,
    ):
        candidates.append(
            {
                "lineage_id": lineage_id,
                "package_hash": package_hash,
                "selected_candidate_id": candidate_id,
                "selected_candidate_summary": summaries[lineage_id],
                "plan_hash": "1" * 64,
                "development_panel_hash": "2" * 64,
                "runner_sha256": "3" * 64,
                "runtime_environment_hash": "4" * 64,
                "conditions": ["clean", "snr_20"],
                "search_freeze_receipt_issued": index == 1,
            }
        )
    coverage = []
    rows = []
    for system_index, system_name in enumerate(SYSTEM_NAMES, 1):
        observations = []
        for lineage_index, (lineage_id, package_hash, candidate_id) in enumerate(
            (
                (LINEAGE_A, "a" * 64, "candidate-a"),
                (LINEAGE_B, "b" * 64, "candidate-b"),
            ),
            1,
        ):
            observation = {
                "lineage_id": lineage_id,
                "package_hash": package_hash,
                "selected_candidate_id": candidate_id,
                "system_name": system_name,
                "data_type": "ode",
                "candidate_median_loss": round(
                    0.1 * system_index + 0.01 * lineage_index, 6
                ),
                "baseline_median_loss": 1.0,
                "paired_log_effect": round(
                    0.01 * system_index * lineage_index, 6
                ),
                "candidate_cell_count": 6,
                "candidate_success_count": 6,
                "baseline_available": True,
                "fully_observed_pair": True,
            }
            coverage.append(observation)
            observations.append(observation)
        rows.append(
            {
                "system_name": system_name,
                "data_type": "ode",
                "observations": observations,
            }
        )
    payload: dict[str, Any] = {
        "schema_version": "cross-lineage-system-effect-matrix-v1",
        "candidates": candidates,
        "coverage_ledger": coverage,
        "comparable_system_rows": rows,
        "comparability_rule": (
            "same_plan_panel_runner_runtime_conditions_and_fully_observed_candidate_cells"
        ),
        "candidate_differences_jointly_confounded": True,
        "component_attribution_authorized": False,
        "confirmatory_use_requires_model_authored_component_ablation": True,
    }
    payload["matrix_hash"] = canonical_model_hash(payload)
    return CrossLineageSystemEffectMatrix.model_validate(payload)


def _association_fact(fact_id: str) -> EvidenceFact:
    feature_values = [float(index) for index in range(1, 8)]
    effect_values = [round(index / 100, 6) for index in range(1, 8)]
    within = {
        "data_type": "ode",
        "system_names": list(SYSTEM_NAMES),
        "feature_values": feature_values,
        "paired_log_effects": effect_values,
        "spearman_rho": 1.0,
        "leave_one_system_out_rhos": [1.0] * 7,
        "leave_one_system_out_minimum": 1.0,
        "leave_one_system_out_maximum": 1.0,
        "leave_one_system_out_sign_consistent": True,
    }
    association = {
        "feature_name": "placeholder_feature",
        "system_names": list(SYSTEM_NAMES),
        "data_types": ["ode"] * 7,
        "feature_values": feature_values,
        "paired_log_effects": effect_values,
        "spearman_rho": 1.0,
        "leave_one_system_out_rhos": [1.0] * 7,
        "leave_one_system_out_minimum": 1.0,
        "leave_one_system_out_maximum": 1.0,
        "leave_one_system_out_sign_consistent": True,
        "within_data_type_associations": [within],
        "overall_data_type_confounding_not_ruled_out": True,
    }
    panel_payload: dict[str, Any] = {
        "schema_version": "exploratory-profile-effect-association-panel-v1",
        "source_lineage_id": LINEAGE_A,
        "source_package_hash": "a" * 64,
        "source_profile_hashes": dict.fromkeys(SYSTEM_NAMES, "c" * 64),
        "source_effect_coverage_rule": (
            "candidate_success_count_equals_candidate_cell_count_and_baseline_available"
        ),
        "excluded_incomplete_systems": [],
        "effect_field": "paired_log_effect",
        "predeclared_feature_names": ["placeholder_feature"],
        "associations": [association],
        "exploratory_only": True,
        "causal_interpretation_authorized": False,
        "multiple_comparisons_adjusted": False,
        "confirmatory_use_requires_new_preregistered_test": True,
    }
    panel_payload["panel_hash"] = canonical_model_hash(panel_payload)
    panel = ExploratoryProfileEffectAssociationPanel.model_validate(panel_payload)
    return EvidenceFact(
        fact_id=fact_id,
        fact_kind="profile_effect_association",
        scope="retained_selected_candidate_exploratory_profile_association",
        source_locator="retained.association",
        value=panel.model_dump(mode="json"),
    )


def _envelope() -> ResearchFeasibilityEnvelope:
    matrix = _matrix()
    facts: list[EvidenceFact] = []
    profile_ids: dict[str, str] = {}
    for system_index, system_name in enumerate(SYSTEM_NAMES, 1):
        fact_id = f"E{system_index:03d}"
        profile_ids[system_name] = fact_id
        facts.append(
            EvidenceFact(
                fact_id=fact_id,
                fact_kind="data_profile",
                scope="public_development_data_profile",
                source_locator=f"profiles.{system_name}",
                value={
                    "system_name": system_name,
                    "data_type": "ode",
                    "mechanical_placeholder": "甲" * (
                        210_000 if system_index == 1 else 1
                    ),
                },
            )
        )
    next_id = len(facts) + 1
    by_matrix_key = {
        (item.system_name, item.lineage_id): item
        for item in matrix.coverage_ledger
    }
    for lineage_id in (LINEAGE_A, LINEAGE_B):
        for system_name in SYSTEM_NAMES:
            observation = by_matrix_key[(system_name, lineage_id)]
            facts.append(
                EvidenceFact(
                    fact_id=f"E{next_id:03d}",
                    fact_kind="system_effect",
                    scope="retained_selected_candidate_full_evaluation",
                    source_locator=f"effects.{lineage_id}.{system_name}",
                    value={
                        "system_name": system_name,
                        "data_type": "ode",
                        "lineage_id": lineage_id,
                        "package_hash": observation.package_hash,
                        "selected_candidate_id": (
                            observation.selected_candidate_id
                        ),
                        "paired_log_effect": observation.paired_log_effect,
                        "candidate_cell_count": observation.candidate_cell_count,
                        "candidate_success_count": (
                            observation.candidate_success_count
                        ),
                        "baseline_available": True,
                    },
                )
            )
            next_id += 1
    facts.append(_association_fact(f"E{next_id:03d}"))
    next_id += 1
    facts.append(
        EvidenceFact(
            fact_id=f"E{next_id:03d}",
            fact_kind="cross_lineage_effect_matrix",
            scope="retained_selected_candidates_cross_lineage_full_evaluation",
            source_locator="retained.cross_lineage_matrix",
            value=matrix.model_dump(mode="json"),
        )
    )
    payload: dict[str, Any] = {
        "schema_version": "research-feasibility-envelope-v2",
        "source_context_hash": "d" * 64,
        "eligible_systems": [
            {"system_name": name, "data_type": "ode"} for name in SYSTEM_NAMES
        ],
        "excluded_systems": [],
        "conditions": ["clean", "snr_20"],
        "seeds": [101, 211, 307],
        "contract_gate": {"network_default_deny": True},
        "estimand": {"independent_unit": "system"},
        "search_budget": {
            "maximum_seconds_per_cell": 300,
            "maximum_memory_mb_per_cell": 4096,
        },
        "stage_breadth": {"pilot_system_count": 5},
        "execution_semantics": {
            "official_development_cell_budget": {
                "maximum_seconds_per_cell": 300,
                "maximum_memory_mb_per_cell": 4096,
            }
        },
        "evidence_facts": [item.model_dump(mode="json") for item in facts],
    }
    payload["envelope_hash"] = canonical_model_hash(payload)
    return ResearchFeasibilityEnvelope.model_validate(payload)


def _catalog() -> list[dict[str, Any]]:
    return [
        {
            "retrieval_index": index,
            "title": f"Placeholder prior work {index}",
            "abstract": (f"Placeholder catalog abstract {index}. " * 80),
            "doi": f"10.1000/placeholder-{index}",
            "url": f"https://example.org/paper-{index}",
        }
        for index in range(6)
    ]


def _selected_references() -> list[dict[str, Any]]:
    catalog = _catalog()
    return [
        {
            "retrieval_index": index,
            "title": catalog[index]["title"],
            "doi": catalog[index]["doi"],
            "url": catalog[index]["url"],
            "relevance_to_plan": "该文献提供可核查的方法背景与对比边界。",
        }
        for index in (0, 2, 3, 4, 5)
    ]


def _component_binding(
    envelope: ResearchFeasibilityEnvelope,
    method_binding: SystemPlanMethodSkillSelectionBinding | None = None,
) -> SystemPlanComponentAtomBinding:
    method_binding = method_binding or _method_binding()
    matrix = _matrix()
    summary_hashes = {
        item.lineage_id: hashlib.sha256(
            item.selected_candidate_summary.encode("utf-8")
        ).hexdigest()
        for item in matrix.candidates
    }
    atoms = []
    names = "甲乙丙丁戊己庚"
    for index, source_clause in enumerate(QUOTES):
        lineage_id = LINEAGE_A if index < 4 else LINEAGE_B
        atoms.append(
            SystemPlanComponentAtom(
                atom_id=f"A{index + 1:03d}",
                source_lineage_id=lineage_id,
                source_summary_sha256=summary_hashes[lineage_id],
                source_clause_id=f"SC{index + 1:03d}",
                source_clause=source_clause,
                technical_identifier=source_clause,
                label_zh=f"占位组件{names[index]}",
                applicable_data_types=("ode",),
                rationale_zh=(
                    "该条目只标识一个可独立核查的占位技术组件，并保留完整来源与"
                    "常微分方程适用边界，不在目录阶段形成效果结论。"
                ),
            )
        )
    payload: dict[str, Any] = {
        "schema_version": "system-plan-component-atom-binding-v1",
        "component_atom_artifact_hash": "f" * 64,
        "feasibility_envelope_hash": envelope.envelope_hash,
        "source_clause_catalog_hash": "c" * 64,
        "method_skill_selection_artifact_hash": (
            method_binding.selection_artifact_hash
        ),
        "atoms": [item.model_dump(mode="json") for item in atoms],
        "independent_review_hash": "d" * 64,
        "is_scientific_evidence": False,
        "execution_authorized": False,
    }
    payload["binding_hash"] = canonical_model_hash(payload)
    return SystemPlanComponentAtomBinding.model_validate(payload)


def _portfolio_payload(
    envelope: ResearchFeasibilityEnvelope,
    component_binding: SystemPlanComponentAtomBinding | None = None,
) -> dict[str, Any]:
    component_binding = component_binding or _component_binding(envelope)
    context = build_compact_opportunity_routing_context(
        feasibility_envelope=envelope,
        retrieved_catalog=_catalog(),
        selected_references=_selected_references(),
        component_atom_binding=component_binding,
    )
    evidence_by_system = {
        item.system_name: set(item.required_fact_ids)
        for item in context.target_evidence_index
    }
    target_sets = (
        SYSTEM_NAMES[0:3],
        (SYSTEM_NAMES[0], SYSTEM_NAMES[1], SYSTEM_NAMES[3]),
        (SYSTEM_NAMES[0], SYSTEM_NAMES[1], SYSTEM_NAMES[4]),
        (SYSTEM_NAMES[0], SYSTEM_NAMES[1], SYSTEM_NAMES[5]),
        (SYSTEM_NAMES[0], SYSTEM_NAMES[1], SYSTEM_NAMES[6]),
        (SYSTEM_NAMES[0], SYSTEM_NAMES[2], SYSTEM_NAMES[3]),
        (SYSTEM_NAMES[0], SYSTEM_NAMES[2], SYSTEM_NAMES[4]),
    )
    literature_sets = (
        (1, 2, 3),
        (2, 3, 4),
        (3, 4, 5),
        (1, 4, 5),
        (1, 2, 5),
        (1, 3, 5),
        (2, 4, 5),
    )
    component_names = "甲乙丙丁戊己庚"
    routes = []
    for index, targets in enumerate(target_sets):
        evidence = sorted(
            set().union(*(evidence_by_system[target] for target in targets))
        )
        routes.append(
            {
                "schema_version": "opportunity-worker-route-v4",
                "cell_id": f"O{index + 1:02d}",
                "target_systems": list(targets),
                "evidence_fact_ids": evidence,
                "literature_indices": list(literature_sets[index]),
                "component_atom_id": f"A{index + 1:03d}",
                "single_component_assignment": (
                    f"待核查组件：占位组件{component_names[index]}"
                    f"（A{index + 1:03d}）。核查边界：仅核查这一冻结组件；"
                    "其余组件、数据、条件、随机种子、预算与评分规则保持不变；"
                    "不得从本路由推断效果、机制或系统性质。"
                ),
                "assignment_rationale": {
                    "schema_version": "mechanical-assignment-rationale-v1",
                    "rationale_kind": "冻结事实覆盖与独立核查",
                    "fact_categories": [
                        "数据画像事实",
                        "完整系统效果事实",
                        "跨谱系效果矩阵事实",
                    ],
                    "coverage_scope": "本路全部目标的必需冻结事实",
                    "literature_scope": "本路三篇入选文献",
                    "independent_check_required": True,
                    "scientific_inference_authorized": False,
                    "system_property_inference_authorized": False,
                    "mechanism_inference_authorized": False,
                    "performance_inference_authorized": False,
                },
            }
        )
    return {
        "schema_version": "opportunity-worker-route-portfolio-v4",
        "target_system_whitelist": list(context.target_system_whitelist),
        "routes": routes,
    }


class _Stub:
    def __init__(
        self,
        payload: dict[str, Any],
        *,
        reasoning_text: str | None = None,
    ) -> None:
        self.payload = payload
        self.reasoning_text = reasoning_text or (
            "先核对紧凑候选摘要和矩阵系统，再逐目标复制画像与两个完整谱系效果事实，"
            "随后核对文献编号、冻结预算、原文片段和单组件边界，最后检查七条结构签名。"
            * 4
        )
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        self.calls.append(kwargs)
        return LLMJsonCompletionResult(
            provider="qwen-dashscope",
            base_url="https://dashscope.example/compatible-mode/v1",
            model_name="qwen3.7-max",
            endpoint="https://dashscope.example/v1/chat/completions",
            response_text=json.dumps(self.payload, ensure_ascii=False),
            parsed_json=copy.deepcopy(self.payload),
            usage={"reasoning_tokens": 800},
            temperature=float(kwargs["temperature"]),
            reasoning_text=self.reasoning_text,
            reasoning_transport="dashscope_enable_thinking",
        )


def test_main_qwen_routes_seven_hash_bound_temporary_workers(
    tmp_path: Path,
) -> None:
    envelope = _envelope()
    stub = _Stub(_portfolio_payload(envelope))

    artifact = run_system_plan_opportunity_routing(
        lineage_id="routing-lineage",
        feasibility_envelope=envelope,
        retrieved_catalog=_catalog(),
        selected_references=_selected_references(),
        component_atom_binding=_component_binding(envelope),
        method_skill_selection=_method_binding(),
        output_dir=tmp_path / "run",
        completion=stub,
        max_attempts=1,
    )

    assert len(artifact.portfolio.routes) == 7
    assert artifact.authored_by_model is True
    assert artifact.hand_written_scientific_prose_count == 0
    assert artifact.is_scientific_evidence is False
    assert artifact.execution_authorized is False
    assert artifact.provider_receipt.reasoning_is_evidence is False
    assert all(
        route.assignment_rationale.rationale_kind == "冻结事实覆盖与独立核查"
        and route.assignment_rationale.scientific_inference_authorized is False
        and route.assignment_rationale.system_property_inference_authorized
        is False
        and route.assignment_rationale.mechanism_inference_authorized is False
        and route.assignment_rationale.performance_inference_authorized is False
        for route in artifact.portfolio.routes
    )
    assert (tmp_path / "run" / "system-plan-opportunity-routing.json").is_file()
    assert (
        tmp_path / "run" / artifact.provider_receipt_relative_path
    ).is_file()
    assert stub.calls[0]["thinking_mode"] == "enabled"
    assert stub.calls[0]["thinking_budget"] == 4_000
    messages = stub.calls[0]["messages"]
    assert len(messages) == 3
    assert "不得从系统名称推断动力学、物理、方程、系统性质或性能机制" in (
        messages[0]["content"]
    )
    assert json.loads(messages[1]["content"])["context_kind"] == (
        "selected_project_method_skills"
    )
    bindings = artifact.worker_bindings()
    assert [item.route.cell_id for item in bindings] == [
        f"O{index:02d}" for index in range(1, 8)
    ]
    assert all(item.is_scientific_evidence is False for item in bindings)
    assert all(item.execution_authorized is False for item in bindings)
    assert [item.component_source.atom_id for item in bindings] == [
        f"A{index:03d}" for index in range(1, 8)
    ]
    assert all(
        len(
            {
                str(fact.value.get("lineage_id"))
                for fact in item.evidence_facts
                if fact.fact_kind == "system_effect"
                and isinstance(fact.value, dict)
                and fact.value.get("lineage_id")
            }
        )
        >= 2
        for item in bindings
    )


def test_main_qwen_prompt_is_far_smaller_than_full_envelope(
    tmp_path: Path,
) -> None:
    envelope = _envelope()
    stub = _Stub(_portfolio_payload(envelope))

    run_system_plan_opportunity_routing(
        lineage_id="compact-routing-lineage",
        feasibility_envelope=envelope,
        retrieved_catalog=_catalog(),
        selected_references=_selected_references(),
        component_atom_binding=_component_binding(envelope),
        method_skill_selection=_method_binding(),
        output_dir=tmp_path / "run",
        completion=stub,
        max_attempts=1,
    )

    messages = stub.calls[0]["messages"]
    prompt_text = "".join(item["content"] for item in messages)
    envelope_text = json.dumps(
        envelope.model_dump(mode="json"), ensure_ascii=False
    )
    assert len(envelope_text) > 200_000
    assert len(prompt_text) < 30_000
    assert "甲" * 1_000 not in prompt_text
    compact_payload = json.loads(messages[2]["content"])["routing_context"]
    assert compact_payload["component_atom_binding"]["atoms"]
    assert "comparable_systems" not in compact_payload
    assert len(compact_payload["comparable_systems_hash"]) == 64
    assert compact_payload["target_evidence_index"]
    assert compact_payload["association_numeric_entries"] == []
    assert compact_payload["literature_catalog"][0]["abstract_excerpt"]
    assert compact_payload["literature_catalog"][0]["retrieval_index"] == 0
    assert compact_payload["literature_catalog"][1]["retrieval_index"] == 2
    assert compact_payload["frozen_budget"]["search_budget"]


def _run_invalid(
    *,
    tmp_path: Path,
    payload: dict[str, Any],
    match: str,
    reasoning_text: str | None = None,
    component_binding: SystemPlanComponentAtomBinding | None = None,
) -> None:
    envelope = _envelope()
    component_binding = component_binding or _component_binding(envelope)
    stub = _Stub(payload, reasoning_text=reasoning_text)
    with pytest.raises(SystemPlanOpportunityRoutingError, match=match):
        run_system_plan_opportunity_routing(
            lineage_id="invalid-routing-lineage",
            feasibility_envelope=envelope,
            retrieved_catalog=_catalog(),
            selected_references=_selected_references(),
            component_atom_binding=component_binding,
            method_skill_selection=_method_binding(),
            output_dir=tmp_path / "run",
            completion=stub,
            max_attempts=1,
        )


def test_repeated_route_signatures_fail_closed(tmp_path: Path) -> None:
    envelope = _envelope()
    payload = _portfolio_payload(envelope)
    payload["routes"][1] = copy.deepcopy(payload["routes"][0])
    payload["routes"][1]["cell_id"] = "O02"

    _run_invalid(
        tmp_path=tmp_path,
        payload=payload,
        match="原子组件与目标集合组合",
    )


def test_full_whitelist_route_fails_closed() -> None:
    payload = _portfolio_payload(_envelope())
    payload["target_system_whitelist"] = list(SYSTEM_NAMES[:4])
    payload["routes"][0]["target_systems"] = list(SYSTEM_NAMES[:4])

    with pytest.raises(SystemPlanOpportunityRoutingError, match="完整目标白名单"):
        OpportunityWorkerRoutePortfolio.model_validate(payload)


def test_unknown_component_atom_fails_closed(tmp_path: Path) -> None:
    envelope = _envelope()
    payload = _portfolio_payload(envelope)
    payload["routes"][0]["component_atom_id"] = "A999"

    _run_invalid(tmp_path=tmp_path, payload=payload, match="未知 atom")


def test_missing_required_fact_fails_closed(tmp_path: Path) -> None:
    envelope = _envelope()
    payload = _portfolio_payload(envelope)
    payload["routes"][0]["evidence_fact_ids"].pop(0)

    _run_invalid(tmp_path=tmp_path, payload=payload, match="缺少必需事实编号")


def test_repeated_literature_index_fails_closed(tmp_path: Path) -> None:
    envelope = _envelope()
    payload = _portfolio_payload(envelope)
    payload["routes"][0]["literature_indices"] = [1, 1, 2]

    _run_invalid(tmp_path=tmp_path, payload=payload, match="文献编号不得重复")


def test_short_qwen_reasoning_fails_closed(tmp_path: Path) -> None:
    envelope = _envelope()

    _run_invalid(
        tmp_path=tmp_path,
        payload=_portfolio_payload(envelope),
        match="至少二百字符",
        reasoning_text="简短推理。",
    )
    assert (
        tmp_path
        / "run"
        / "interactions"
        / "system-plan-opportunity-routing-attempt-01.json"
    ).is_file()


def test_non_chinese_worker_assignment_fails_closed(tmp_path: Path) -> None:
    envelope = _envelope()
    payload = _portfolio_payload(envelope)
    payload["routes"][0]["single_component_assignment"] = (
        "This worker assignment checks one component without any conclusion."
    )

    _run_invalid(tmp_path=tmp_path, payload=payload, match="不是中文")


def test_assignment_must_bind_one_chinese_component_label(tmp_path: Path) -> None:
    envelope = _envelope()
    payload = _portfolio_payload(envelope)
    payload["routes"][0]["single_component_assignment"] = (
        "待核查组件：伪造组件（A001）。核查边界：仅核查这个组件，其余步骤冻结。"
    )

    _run_invalid(tmp_path=tmp_path, payload=payload, match="确定性机械边界")


def test_v29_free_text_scientific_rationale_fails_closed(
    tmp_path: Path,
) -> None:
    envelope = _envelope()
    payload = _portfolio_payload(envelope)
    payload["routes"][6]["assignment_rationale"] = (
        "这四个ODE系统涵盖振荡、衰减和混沌特性，适合独立核查内部验证集"
        "划分对不同动力学类型的泛化影响，冻结其余组件可验证验证策略的鲁棒性边界。"
    )

    _run_invalid(
        tmp_path=tmp_path,
        payload=payload,
        match="assignment_rationale",
    )


def test_mechanical_rationale_rejects_any_extra_scientific_claim(
    tmp_path: Path,
) -> None:
    envelope = _envelope()
    payload = _portfolio_payload(envelope)
    payload["routes"][0]["assignment_rationale"]["scientific_claim"] = (
        "目标具有特殊动力学性质。"
    )

    _run_invalid(
        tmp_path=tmp_path,
        payload=payload,
        match="scientific_claim",
    )


def test_old_v29_route_schema_fails_closed() -> None:
    payload = _portfolio_payload(_envelope())
    payload["schema_version"] = "opportunity-worker-route-portfolio-v3"
    for route in payload["routes"]:
        route.pop("schema_version")
        route["assignment_rationale"] = (
            "这三个ODE系统涵盖不同动力学特性，适合独立核查组件影响。"
        )

    with pytest.raises((ValueError, SystemPlanOpportunityRoutingError)):
        OpportunityWorkerRoutePortfolio.model_validate(payload)


def test_component_assignment_cannot_append_mechanism_claim(
    tmp_path: Path,
) -> None:
    envelope = _envelope()
    payload = _portfolio_payload(envelope)
    payload["routes"][0]["single_component_assignment"] += (
        "该组件预计会改善混沌系统的性能。"
    )

    _run_invalid(tmp_path=tmp_path, payload=payload, match="确定性机械边界")


def test_explicit_pde_component_cannot_route_to_ode_targets(tmp_path: Path) -> None:
    envelope = _envelope()
    binding_payload = _component_binding(envelope).model_dump(mode="json")
    binding_payload["atoms"][0]["applicable_data_types"] = ["pde"]
    binding_payload.pop("binding_hash")
    binding_payload["binding_hash"] = canonical_model_hash(binding_payload)
    binding = SystemPlanComponentAtomBinding.model_validate(binding_payload)
    payload = _portfolio_payload(envelope, binding)

    _run_invalid(
        tmp_path=tmp_path,
        payload=payload,
        match="超出冻结 atom 适用范围",
        component_binding=binding,
    )


def test_same_atom_with_different_target_sets_is_allowed() -> None:
    envelope = _envelope()
    payload = _portfolio_payload(envelope)
    payload["routes"][1]["component_atom_id"] = "A001"
    payload["routes"][1]["single_component_assignment"] = (
        "待核查组件：占位组件甲（A001）。核查边界：仅核查这一冻结组件；"
        "其余组件、数据、条件、随机种子、预算与评分规则保持不变；"
        "不得从本路由推断效果、机制或系统性质。"
    )

    portfolio = OpportunityWorkerRoutePortfolio.model_validate(payload)

    assert (
        portfolio.routes[0].component_atom_id
        == portfolio.routes[1].component_atom_id
    )
    assert portfolio.routes[0].target_systems != portfolio.routes[1].target_systems


def test_retry_feedback_aggregates_all_invalid_chinese_routes(tmp_path: Path) -> None:
    envelope = _envelope()
    payload = _portfolio_payload(envelope)
    for index in range(5):
        payload["routes"][index]["single_component_assignment"] = (
            "This assignment is intentionally invalid English prose."
        )
    stub = _Stub(payload)

    with pytest.raises(SystemPlanOpportunityRoutingError) as exc_info:
        run_system_plan_opportunity_routing(
            lineage_id="aggregate-feedback-lineage",
            feasibility_envelope=envelope,
            retrieved_catalog=_catalog(),
            selected_references=_selected_references(),
            component_atom_binding=_component_binding(envelope),
            method_skill_selection=_method_binding(),
            output_dir=tmp_path / "run",
            completion=stub,
            max_attempts=1,
        )

    message = str(exc_info.value)
    assert "routes[0]" in message
    assert "routes[4]" in message
