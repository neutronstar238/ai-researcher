from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import pytest
from pydantic import ValidationError

from autoresearch.competition import system_plan_prospective_atoms as prospective_atoms
from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.plan_literature_survey import (
    PlanLiteratureSurveyArtifact,
)
from autoresearch.competition.system_plan_component_atoms import (
    SystemPlanComponentAtom,
    SystemPlanComponentAtomBinding,
    SystemPlanComponentAtomPortfolio,
    SystemPlanComponentAtomReviewPortfolio,
)
from autoresearch.competition.system_plan_methodology import (
    AvailableMethodSkill,
    SystemPlanMethodSkillSelection,
    SystemPlanMethodSkillSelectionBinding,
)
from autoresearch.competition.system_plan_opportunity_map import (
    CrossLineageSystemEffectMatrix,
    EvidenceFact,
    ResearchFeasibilityEnvelope,
)
from autoresearch.competition.system_plan_prospective_atoms import (
    ComponentExperimentBindingV2,
    ProspectiveAtomContext,
    ProspectiveAtomPortfolio,
    ProspectiveAtomReviewPortfolio,
    ProspectiveModelAttempt,
    SystemPlanProspectiveAtomArtifact,
    SystemPlanProspectiveAtomError,
    build_component_experiment_binding,
    build_prospective_atom_context,
    build_prospective_execution_interface_contract,
    prospective_atom_portfolio_findings,
    prospective_atom_review_findings,
    run_system_plan_prospective_atoms,
)
from autoresearch.llm.client import LLMJsonCompletionResult

LINEAGE_ID = "prospective-lineage"
SOURCE_LINEAGES = ("signed-lineage-a", "signed-lineage-b")
SYSTEM_NAMES = (
    "sealed-target-alpha",
    "sealed-target-beta",
    "sealed-target-gamma",
)
FIXED_CLOCK = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
FROZEN_DIMENSIONS = (
    "输入数据",
    "实验条件",
    "随机种子",
    "估计目标",
    "基线方法",
    "评估指标",
    "公开接口",
    "资源上限",
    "基线组件之外的候选行为",
)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _method_binding() -> SystemPlanMethodSkillSelectionBinding:
    content = (
        "---\nname: prospective-atom-audit\n---\n"
        "本技能要求逐篇核对完整摘要、排除既有方法直接复制、冻结单因子实验边界，"
        "并检查匿名目标、公开接口、资源预算和可反驳条件。"
    )
    skill = AvailableMethodSkill(
        skill_id="prospective-atom-audit",
        description="用于前瞻单组件候选的完整摘要比较、边界冻结与独立审查。",
        source_relative_path="skills/prospective-atom-audit/SKILL.md",
        content_sha256=_sha256(content),
        content=content,
    )
    selection = SystemPlanMethodSkillSelection(
        task_classification="当前任务只生成文献支持的前瞻单组件候选，不产生科研结论或执行授权。",
        selected_skill_ids=(skill.skill_id,),
        rejected_skill_ids=(),
        selection_rationale="该方法技能覆盖完整摘要核查、单因子边界、接口预算和独立审查，适合当前任务。",
        planned_reasoning_stages=(
            "先核对完整摘要及其来源哈希。",
            "再比较候选与每篇既有工作的关系。",
            "随后冻结单因子处理和对照边界。",
            "接着核查匿名目标与事实范围。",
            "然后核查公开接口和资源预算。",
            "最后由独立审查者给出机械合取结论。",
        ),
        auditable_reasoning_summary=(
            "摘要不得截断。",
            "既有方法不得伪装成创新。",
            "目标名称不得泄漏。",
            "接口与预算不得越界。",
            "候选不得成为科学证据。",
        ),
        non_evidence_boundary="技能只约束提出候选和独立审查的方法，不构成科研事实、实验结果或创新证明。",
    )
    return SystemPlanMethodSkillSelectionBinding(
        selection_artifact_hash="c" * 64,
        selection=selection,
        selected_skills=(skill,),
    )


def _survey(*, oversized_abstract: bool = False) -> PlanLiteratureSurveyArtifact:
    abstracts = [
        (
            "A controlled estimator separates one numerical intervention from all "
            "other fixed choices and reports failure-sensitive comparisons. "
            "The study emphasizes exact provenance, bounded compute, and explicit "
            "counterfactual controls across multiple dynamical benchmarks. "
            "Its limitations include sensitivity to a fixed preprocessing rule and "
            "the absence of component-level causal evidence outside ablations. "
            "Every retrieved sentence remains available for later independent review."
        ),
        (
            "A robust identification procedure uses a constrained feature transform "
            "under a fixed public prediction interface. The evaluation holds seeds, "
            "metrics, data, and baselines constant while varying one implementation "
            "choice. The authors caution that method composition prevents attribution "
            "unless a dedicated single-factor intervention is executed."
        ),
        (
            "An audit of scientific agents finds that literature-derived hypotheses "
            "must remain candidates until executable contrasts produce signed results. "
            "Exact abstract spans and complete comparison against selected prior work "
            "reduce unsupported novelty claims but cannot verify publication novelty."
        ),
    ]
    if oversized_abstract:
        abstracts[0] = "完整摘要内容用于提示大小失败关闭。" * 8_000
    catalog = [
        {
            "retrieval_index": index,
            "title": f"Prior Work {index + 1}",
            "doi": f"10.1000/prospective.{index + 1}",
            "url": f"https://example.org/paper/{index + 1}",
            "source": "openalex",
            "abstract": abstract,
        }
        for index, abstract in enumerate(abstracts)
    ]
    selected = [
        {
            "retrieval_index": item["retrieval_index"],
            "title": item["title"],
            "doi": item["doi"],
            "url": item["url"],
            "relevance_to_plan": "该摘要用于约束单组件干预、证据范围和既有方法排除。",
        }
        for item in catalog
    ]
    payload: dict[str, Any] = {
        "schema_version": "plan-literature-survey-v1",
        "lineage_id": LINEAGE_ID,
        "focus_sha256": "f" * 64,
        "queries": ["single component intervention"],
        "query_authorship_receipt_relative_path": "interactions/query.json",
        "query_authorship_receipt_hash": "1" * 64,
        "retrieved_catalog": catalog,
        "selected_references": selected,
        "selection_authorship_receipt_relative_path": "interactions/select.json",
        "selection_authorship_receipt_hash": "2" * 64,
        "surveyed_before_authoring": True,
        "created_at": FIXED_CLOCK.isoformat().replace("+00:00", "Z"),
    }
    payload["survey_hash"] = canonical_model_hash(payload)
    payload["output_path"] = "plan-literature-survey.json"
    return PlanLiteratureSurveyArtifact.model_validate(payload)


def _matrix() -> CrossLineageSystemEffectMatrix:
    candidates = []
    for index, lineage_id in enumerate(SOURCE_LINEAGES):
        candidates.append(
            {
                "lineage_id": lineage_id,
                "package_hash": str(index + 1) * 64,
                "selected_candidate_id": f"candidate-{index + 1}",
                "selected_candidate_summary": (
                    "bounded estimator; fixed derivative interface; guarded feature rule"
                ),
                "plan_hash": "a" * 64,
                "development_panel_hash": "b" * 64,
                "runner_sha256": "c" * 64,
                "runtime_environment_hash": "d" * 64,
                "conditions": ["clean"],
                "search_freeze_receipt_issued": False,
            }
        )
    coverage: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for system_index, system_name in enumerate(SYSTEM_NAMES, 1):
        observations = []
        for lineage_index, candidate in enumerate(candidates, 1):
            observation = {
                "lineage_id": candidate["lineage_id"],
                "package_hash": candidate["package_hash"],
                "selected_candidate_id": candidate["selected_candidate_id"],
                "system_name": system_name,
                "data_type": "ode",
                "candidate_median_loss": 0.1 * system_index * lineage_index,
                "baseline_median_loss": 1.0,
                "paired_log_effect": 0.01 * system_index * lineage_index,
                "candidate_cell_count": 3,
                "candidate_success_count": 3,
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


def _envelope() -> ResearchFeasibilityEnvelope:
    matrix = _matrix()
    facts: list[EvidenceFact] = []
    for system_index, system_name in enumerate(SYSTEM_NAMES, 1):
        facts.append(
            EvidenceFact(
                fact_id=f"E{system_index:03d}",
                fact_kind="data_profile",
                scope="public_development_data_profile",
                source_locator=f"profile.{system_index}",
                value={"system_name": system_name, "observation_count": 120},
            )
        )
    next_fact = 4
    for system_name in SYSTEM_NAMES:
        row = next(
            item for item in matrix.comparable_system_rows if item.system_name == system_name
        )
        for observation in row.observations:
            facts.append(
                EvidenceFact(
                    fact_id=f"E{next_fact:03d}",
                    fact_kind="system_effect",
                    scope="retained_selected_candidate_full_evaluation",
                    source_locator=(f"effect.{system_name}.{observation.lineage_id}"),
                    value={
                        "system_name": system_name,
                        "lineage_id": observation.lineage_id,
                        "selected_candidate_id": observation.selected_candidate_id,
                        "package_hash": observation.package_hash,
                        "baseline_available": observation.baseline_available,
                        "candidate_cell_count": observation.candidate_cell_count,
                        "candidate_success_count": observation.candidate_success_count,
                        "paired_log_effect": observation.paired_log_effect,
                    },
                )
            )
            next_fact += 1
    facts.append(
        EvidenceFact(
            fact_id="E010",
            fact_kind="cross_lineage_effect_matrix",
            scope="retained_selected_candidates_cross_lineage_full_evaluation",
            source_locator="retained.cross_lineage_matrix",
            value=matrix.model_dump(mode="json"),
        )
    )
    payload: dict[str, Any] = {
        "schema_version": "research-feasibility-envelope-v2",
        "source_context_hash": "e" * 64,
        "eligible_systems": [{"system_name": item, "data_type": "ode"} for item in SYSTEM_NAMES],
        "excluded_systems": [],
        "conditions": ["clean"],
        "seeds": [101, 202],
        "contract_gate": {"network_default_deny": True},
        "estimand": {"independent_unit": "system"},
        "search_budget": {"maximum_seconds_per_cell": 300},
        "stage_breadth": {"pilot_system_count": 3},
        "execution_semantics": {
            "sandbox_required": True,
            "official_development_cell_budget": {
                "scope": "one target-condition-seed cell",
                "maximum_seconds_per_cell": 300,
                "maximum_memory_mb_per_cell": 4_096,
                "maximum_cpu_cores_per_cell": 2,
            },
        },
        "evidence_facts": [item.model_dump(mode="json") for item in facts],
    }
    payload["envelope_hash"] = canonical_model_hash(payload)
    return ResearchFeasibilityEnvelope.model_validate(payload)


def _observed_binding(envelope: ResearchFeasibilityEnvelope) -> SystemPlanComponentAtomBinding:
    atoms = []
    labels = ("稳健变换", "阈值控制", "导数估计", "特征筛选", "损失加权", "缓存约束", "条件保护")
    for index, label in enumerate(labels, 1):
        source_clause = f"observed technical component {index}"
        if index == 1:
            source_clause += f" on {SYSTEM_NAMES[0]} described beside Prior Work 1"
        atoms.append(
            SystemPlanComponentAtom(
                atom_id=f"A{index:03d}",
                source_lineage_id=SOURCE_LINEAGES[index % 2],
                source_summary_sha256=str((index % 9) + 1) * 64,
                source_clause_id=f"SC{index:03d}",
                source_clause=source_clause,
                technical_identifier=f"component_{index}",
                label_zh=label,
                applicable_data_types=("ode",),
                rationale_zh=(
                    "该组件只记录于已签名候选摘要，作为前瞻处理的观察基线，不构成单组件因果证据或结果。"
                ),
            )
        )
    payload: dict[str, Any] = {
        "schema_version": "system-plan-component-atom-binding-v1",
        "component_atom_artifact_hash": "a" * 64,
        "feasibility_envelope_hash": envelope.envelope_hash,
        "source_clause_catalog_hash": "b" * 64,
        "method_skill_selection_artifact_hash": "c" * 64,
        "atoms": [item.model_dump(mode="json") for item in atoms],
        "independent_review_hash": "d" * 64,
        "is_scientific_evidence": False,
        "execution_authorized": False,
    }
    payload["binding_hash"] = canonical_model_hash(payload)
    return SystemPlanComponentAtomBinding.model_validate(payload)


def _inputs() -> (
    tuple[
        PlanLiteratureSurveyArtifact,
        ResearchFeasibilityEnvelope,
        SystemPlanComponentAtomBinding,
    ]
):
    survey = _survey()
    envelope = _envelope()
    return survey, envelope, _observed_binding(envelope)


def _context_and_aliases() -> (
    tuple[
        PlanLiteratureSurveyArtifact,
        ResearchFeasibilityEnvelope,
        SystemPlanComponentAtomBinding,
        ProspectiveAtomContext,
    ]
):
    survey, envelope, observed = _inputs()
    interface = build_prospective_execution_interface_contract(envelope)
    context = build_prospective_atom_context(
        survey=survey,
        feasibility_envelope=envelope,
        observed_component_binding=observed,
        method_skill_selection=_method_binding(),
        interface_contract=interface,
    )
    return survey, envelope, observed, context


def _author_payload(
    context: ProspectiveAtomContext,
    observed: SystemPlanComponentAtomBinding,
) -> dict[str, Any]:
    selected_type = context.anonymous_targets[0].data_type
    selected_targets = tuple(
        item for item in context.anonymous_targets if item.data_type == selected_type
    )[:3]
    if len(selected_targets) != 3:
        raise AssertionError("test fixture needs three same-type anonymous targets")
    target_keys = tuple(item.target_key for item in selected_targets)
    fact_ids = sorted(
        {fact_id for target in selected_targets for fact_id in target.required_fact_ids}
    )
    supports = []
    for record, role in zip(context.selected_abstracts[:2], ("问题动机", "已知局限"), strict=True):
        span = record.abstract_text[:120].strip()
        supports.append(
            {
                "reference_index": record.reference_index,
                "retrieval_index": record.retrieval_index,
                "source_record_hash": record.source_record_hash,
                "abstract_sha256": record.abstract_sha256,
                "exact_support_span": span,
                "support_span_sha256": _sha256(span),
                "support_role": role,
            }
        )
    baseline = next(item for item in observed.atoms if selected_type in item.applicable_data_types)
    return {
        "schema_version": "prospective-atom-portfolio-v1",
        "atoms": [
            {
                "atom_id": "P001",
                "origin_kind": "prospective_literature_derived",
                "baseline_observed_atom_id": baseline.atom_id,
                "baseline_observed_atom_hash": canonical_model_hash(baseline),
                "label_zh": "受约束的单组件替换",
                "change_mode": "替换",
                "control_level_zh": (
                    "对照水平保持观察基线组件及其公开调用方式不变，并冻结其余全部实验条件。"
                ),
                "intervention_level_zh": (
                    "处理水平仅用受约束变换替换该观察基线组件，不改变任何其他候选行为。"
                ),
                "single_factor_rationale_zh": (
                    "该设计把唯一可操纵因素限定为一个观察基线组件的实现形式，因此处理组与对照组的差别可被明确定位。"
                ),
                "literature_synthesis_zh": (
                    "所选摘要共同强调单因子对照、固定接口、资源边界与完整来源核查，但这些内容只构成提出候选的动机。"
                ),
                "delta_from_prior_work_zh": (
                    "本候选只迁移受约束对照原则，在冻结目标和接口下检验一个观察组件，不把摘要描述的方法本身重新命名为新方法。"
                ),
                "falsifiable_single_factor_contrast_zh": (
                    "若处理水平相对对照水平在预先冻结的独立目标上没有稳定差异，则该单组件候选应被否定而不是追加解释。"
                ),
                "implementation_anchor": "bounded_component_transform",
                "public_hooks": ["fit_equations"],
                "target_keys": list(target_keys),
                "applicable_data_types": [selected_type],
                "supporting_fact_ids": fact_ids,
                "literature_supports": supports,
                "frozen_dimensions": list(FROZEN_DIMENSIONS),
                "resource_request": {
                    "seconds_per_cell": 120,
                    "memory_mb_per_cell": 2_048,
                    "cpu_cores_per_cell": 1,
                    "public_fit_calls_per_cell": 1,
                },
                "single_factor_intervention": True,
                "candidate_differences_jointly_confounded": True,
                "is_scientific_evidence": False,
                "innovation_verified": False,
                "execution_authorized": False,
            }
        ],
    }


def _review_payload(
    author_payload: dict[str, Any], context: ProspectiveAtomContext
) -> dict[str, Any]:
    portfolio = ProspectiveAtomPortfolio.model_validate(author_payload)
    reviews = []
    for atom in portfolio.atoms:
        comparisons = []
        for record in context.selected_abstracts:
            comparisons.append(
                {
                    "reference_index": record.reference_index,
                    "abstract_sha256": record.abstract_sha256,
                    "overlap_zh": "该摘要与候选都要求冻结其他变量并保留可核验的单因子对照边界。",
                    "difference_zh": "候选没有逐字采用摘要中的完整方法，而是把原则约束到一个观察组件的处理。",
                    "residual_risk_zh": "仅凭摘要仍不能证明可发表新颖性，必须经过执行结果与更完整的先验检索。",
                    "direct_method_copy": False,
                    "abstract_insufficient": False,
                }
            )
        reviews.append(
            {
                "atom_id": atom.atom_id,
                "atom_hash": canonical_model_hash(atom),
                "prior_work_comparisons": comparisons,
                "single_component_identifiable": True,
                "abstract_support_exact": True,
                "facts_support_scope": True,
                "no_system_name_inference": True,
                "target_type_valid": True,
                "interface_valid": True,
                "budget_valid": True,
                "not_direct_prior_method_copy": True,
                "falsifiable_counterfactual": True,
                "accepted": True,
                "findings_zh": [],
            }
        )
    return {
        "schema_version": "prospective-atom-review-portfolio-v1",
        "reviews": reviews,
    }


class _StubSequence:
    def __init__(
        self,
        payloads: list[dict[str, Any]],
        *,
        provider: str = "qwen-dashscope",
        model_name: str = "qwen3.7-max",
        reasoning: str | None = None,
        reasoning_transport: Literal[
            "absent",
            "dashscope_enable_thinking",
            "anthropic_thinking_block",
        ] = "dashscope_enable_thinking",
    ) -> None:
        self.payloads = [copy.deepcopy(item) for item in payloads]
        self.provider = provider
        self.model_name = model_name
        self.reasoning = (
            reasoning
            if reasoning is not None
            else (
                "先核对每篇完整摘要的来源哈希和逐字支持片段，再比较候选处理是否复制既有方法；"
                "随后逐项核查观察基线绑定、单因子差异、匿名目标、冻结事实、数据类型、公开接口、"
                "资源上限和可反驳条件；最后确认所有科研陈述仍是未执行候选，不能作为证据或创新结论。"
                * 3
            )
        )
        self.reasoning_transport = reasoning_transport
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        self.calls.append(kwargs)
        payload = self.payloads.pop(0)
        return LLMJsonCompletionResult(
            provider=self.provider,
            base_url="https://dashscope.example/compatible-mode/v1",
            model_name=self.model_name,
            endpoint="https://dashscope.example/v1/chat/completions",
            response_text=json.dumps(payload, ensure_ascii=False),
            parsed_json=copy.deepcopy(payload),
            usage={"reasoning_tokens": 800},
            temperature=float(kwargs["temperature"]),
            reasoning_text=self.reasoning,
            reasoning_transport=self.reasoning_transport,
        )


class _ReviewerTransportFailureThenSuccess:
    def __init__(self, success_payload: dict[str, Any]) -> None:
        self.success = _StubSequence([success_payload])
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            raise RuntimeError("temporary reviewer transport failure")
        return self.success(**kwargs)


class _AuthorTransportFailureThenSuccess:
    def __init__(self, success_payload: dict[str, Any]) -> None:
        self.success = _StubSequence([success_payload])
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            raise RuntimeError("temporary author transport failure")
        return self.success(**kwargs)


def _run_valid(
    tmp_path: Path,
    *,
    clock: datetime = FIXED_CLOCK,
) -> SystemPlanProspectiveAtomArtifact:
    survey, envelope, observed, context = _context_and_aliases()
    author_payload = _author_payload(context, observed)
    return run_system_plan_prospective_atoms(
        lineage_id=LINEAGE_ID,
        literature_survey=survey,
        feasibility_envelope=envelope,
        observed_component_binding=observed,
        method_skill_selection=_method_binding(),
        interface_contract=build_prospective_execution_interface_contract(envelope),
        output_dir=tmp_path,
        author_completion=_StubSequence([author_payload]),
        reviewer_completion=_StubSequence([_review_payload(author_payload, context)]),
        max_rounds=1,
        clock=clock,
    )


def test_full_abstract_qwen_loop_is_anonymous_hash_bound_and_non_evidence(
    tmp_path: Path,
) -> None:
    survey, envelope, observed, context = _context_and_aliases()
    author_payload = _author_payload(context, observed)
    author = _StubSequence([author_payload])
    reviewer = _StubSequence([_review_payload(author_payload, context)])

    artifact = run_system_plan_prospective_atoms(
        lineage_id=LINEAGE_ID,
        literature_survey=survey,
        feasibility_envelope=envelope,
        observed_component_binding=observed,
        method_skill_selection=_method_binding(),
        interface_contract=build_prospective_execution_interface_contract(envelope),
        output_dir=tmp_path,
        author_completion=author,
        reviewer_completion=reviewer,
        max_rounds=1,
        clock=FIXED_CLOCK,
    )

    assert (
        artifact.context.selected_abstracts[0].abstract_text
        == (survey.retrieved_catalog[0]["abstract"])
    )
    assert len(artifact.context.selected_abstracts[0].abstract_text) > 360
    assert artifact.final_portfolio.atoms[0].origin_kind == ("prospective_literature_derived")
    assert artifact.is_scientific_evidence is False
    assert artifact.innovation_verified is False
    assert artifact.execution_authorized is False
    assert artifact.hand_written_scientific_prose_count == 0
    assert (tmp_path / "system-plan-prospective-atoms.json").is_file()
    assert len(list((tmp_path / "interactions").glob("*.json"))) == 2
    assert len(list((tmp_path / "prospective-attempts").glob("*.json"))) == 2
    skill_binding = _method_binding()
    for stub in (author, reviewer):
        assert stub.calls[0]["thinking_mode"] == "enabled"
        assert stub.calls[0]["thinking_budget"] == 4_000
        skill_message = json.loads(stub.calls[0]["messages"][1]["content"])
        assert skill_message["context_kind"] == "selected_project_method_skills"
        assert skill_message["selection_artifact_hash"] == (skill_binding.selection_artifact_hash)
        assert skill_message["selected_method_skills"] == [
            item.model_dump(mode="json") for item in skill_binding.selected_skills
        ]
        assert (
            skill_binding.selected_skills[0].content
            not in (stub.calls[0]["messages"][0]["content"])
        )
        serialized = json.dumps(stub.calls[0]["messages"], ensure_ascii=False)
        assert all(system_name not in serialized for system_name in SYSTEM_NAMES)
        assert all(str(item["title"]) not in serialized for item in survey.selected_references)
    assert all(item.system_name in SYSTEM_NAMES for item in artifact.target_aliases)
    context_json = json.dumps(artifact.context.model_dump(mode="json"))
    assert all(system_name not in context_json for system_name in SYSTEM_NAMES)
    binding = artifact.binding()
    identity = binding.intervention_identities[0]
    assert identity.atom_id == artifact.final_portfolio.atoms[0].atom_id
    assert identity.intervention_hash == canonical_model_hash(artifact.final_portfolio.atoms[0])
    assert binding.method_skill_selection_artifact_hash == (skill_binding.selection_artifact_hash)
    assert binding.innovation_verified is False
    assert binding.execution_authorized is False
    combined = build_component_experiment_binding(observed, binding)
    assert isinstance(combined, ComponentExperimentBindingV2)
    assert combined.observed_components.atoms[0].atom_id == "A001"
    assert combined.prospective_components.atoms[0].atom_id == "P001"


def test_selected_reference_must_strictly_join_full_catalog() -> None:
    survey, envelope, observed = _inputs()
    selected = [dict(item) for item in survey.selected_references]
    selected[0]["title"] = selected[1]["title"]
    invalid_survey = survey.model_copy(update={"selected_references": tuple(selected)})

    with pytest.raises(SystemPlanProspectiveAtomError, match="title 与目录不符"):
        build_prospective_atom_context(
            survey=invalid_survey,
            feasibility_envelope=envelope,
            observed_component_binding=observed,
            method_skill_selection=_method_binding(),
            interface_contract=build_prospective_execution_interface_contract(envelope),
        )


def test_full_abstract_hash_cannot_be_tampered() -> None:
    _, _, _, context = _context_and_aliases()
    payload = context.model_dump(mode="json")
    payload["selected_abstracts"][0]["abstract_text"] += " tampered"

    with pytest.raises((ValidationError, SystemPlanProspectiveAtomError), match="摘要哈希"):
        ProspectiveAtomContext.model_validate(payload)


def test_title_cannot_substitute_for_exact_abstract_support(tmp_path: Path) -> None:
    survey, _, observed, context = _context_and_aliases()
    payload = _author_payload(context, observed)
    title = str(survey.selected_references[0]["title"])
    support = payload["atoms"][0]["literature_supports"][0]
    support["exact_support_span"] = title
    support["support_span_sha256"] = _sha256(title)
    portfolio = ProspectiveAtomPortfolio.model_validate(payload)

    findings = prospective_atom_portfolio_findings(
        portfolio=portfolio,
        context=context,
        target_aliases=_run_valid(tmp_path / "aliases").target_aliases,
        observed_component_binding=observed,
        literature_survey=survey,
    )

    assert any("不是完整摘要逐字子串" in item for item in findings)


def test_qwen_selects_exact_span_while_orchestrator_derives_sha_bindings(
    tmp_path: Path,
) -> None:
    survey, envelope, observed, context = _context_and_aliases()
    complete = _author_payload(context, observed)
    raw_author = copy.deepcopy(complete)
    for atom in raw_author["atoms"]:
        atom.pop("baseline_observed_atom_hash")
        atom["applicable_data_types"] = []
        atom["supporting_fact_ids"] = []
        for support in atom["literature_supports"]:
            support.pop("retrieval_index")
            support.pop("source_record_hash")
            support.pop("abstract_sha256")
            support.pop("support_span_sha256")
        atom["literature_supports"].append(copy.deepcopy(atom["literature_supports"][0]))

    artifact = run_system_plan_prospective_atoms(
        lineage_id=LINEAGE_ID,
        literature_survey=survey,
        feasibility_envelope=envelope,
        observed_component_binding=observed,
        method_skill_selection=_method_binding(),
        interface_contract=build_prospective_execution_interface_contract(envelope),
        output_dir=tmp_path,
        author_completion=_StubSequence([raw_author]),
        reviewer_completion=_StubSequence([_review_payload(complete, context)]),
        max_rounds=1,
        clock=FIXED_CLOCK,
    )

    raw_support = artifact.rounds[0].author_receipt.parsed_payload["atoms"][0][
        "literature_supports"
    ][0]
    bound_support = artifact.final_portfolio.atoms[0].literature_supports[0]
    assert "support_span_sha256" not in raw_support
    assert (
        "baseline_observed_atom_hash"
        not in (artifact.rounds[0].author_receipt.parsed_payload["atoms"][0])
    )
    assert (
        artifact.final_portfolio.atoms[0].baseline_observed_atom_hash
        == (complete["atoms"][0]["baseline_observed_atom_hash"])
    )
    assert bound_support.support_span_sha256 == _sha256(bound_support.exact_support_span)
    assert bound_support.abstract_sha256 == context.selected_abstracts[0].abstract_sha256
    assert len(artifact.final_portfolio.atoms[0].literature_supports) == 2
    assert artifact.rounds[0].author_receipt.parsed_payload["atoms"][0]["supporting_fact_ids"] == []
    assert artifact.final_portfolio.atoms[0].supporting_fact_ids == tuple(
        complete["atoms"][0]["supporting_fact_ids"]
    )
    assert artifact.final_portfolio.atoms[0].applicable_data_types == tuple(
        complete["atoms"][0]["applicable_data_types"]
    )


def test_transport_damaged_dash_is_recovered_but_paraphrase_is_rejected() -> None:
    abstract = (
        "The source uses sparse regression with sparsity–promoting estimators "
        "to recover a governing equation under noise."
    )
    damaged = (
        "sparse regression with sparsity\ufffdCpromoting estimators to recover a "
        "governing equation"
    )
    assert prospective_atoms._repair_transport_damaged_exact_span(
        damaged,
        abstract_text=abstract,
    ) == ("sparse regression with sparsity–promoting estimators to recover a " "governing equation")
    assert (
        prospective_atoms._repair_transport_damaged_exact_span(
            "模型改写后的结论完全不是摘要中的逐字证据片段",
            abstract_text=abstract,
        )
        is None
    )


def test_portfolio_allows_shared_public_implementation_anchor() -> None:
    _, _, observed, context = _context_and_aliases()
    response = _author_payload(context, observed)
    second = copy.deepcopy(response["atoms"][0])
    second["atom_id"] = "P002"
    response["atoms"].append(second)
    portfolio = ProspectiveAtomPortfolio.model_validate(response)
    assert portfolio.atoms[0].implementation_anchor == portfolio.atoms[1].implementation_anchor


def test_one_exact_support_is_allowed_because_review_compares_all_abstracts() -> None:
    _, _, observed, context = _context_and_aliases()
    response = _author_payload(context, observed)
    response["atoms"][0]["literature_supports"] = response["atoms"][0]["literature_supports"][:1]
    portfolio = ProspectiveAtomPortfolio.model_validate(response)
    assert len(portfolio.atoms[0].literature_supports) == 1


@pytest.mark.parametrize("role", ["方法参照", "方法基础", "技术背景"])
def test_natural_chinese_support_role_is_not_a_closed_enum(role: str) -> None:
    _, _, observed, context = _context_and_aliases()
    response = _author_payload(context, observed)
    response["atoms"][0]["literature_supports"][0]["support_role"] = role
    portfolio = ProspectiveAtomPortfolio.model_validate(response)
    assert portfolio.atoms[0].literature_supports[0].support_role == role


def test_short_clear_chinese_and_missing_model_hashes_are_derived(
    tmp_path: Path,
) -> None:
    survey, envelope, observed, context = _context_and_aliases()
    complete_author = _author_payload(context, observed)
    raw_author = copy.deepcopy(complete_author)
    atom = raw_author["atoms"][0]
    atom.pop("baseline_observed_atom_hash")
    atom["control_level_zh"] = "保持谱导数基线"
    atom["intervention_level_zh"] = "替换为积分残差"
    atom["single_factor_rationale_zh"] = "只改变残差形式"
    atom["literature_synthesis_zh"] = "摘要支持此对照"
    atom["delta_from_prior_work_zh"] = "只检验未执行组合"
    atom["falsifiable_single_factor_contrast_zh"] = "无改善即否定"
    atom["literature_supports"][0]["support_role"] = "方法基础"
    for support in atom["literature_supports"]:
        for field_name in (
            "retrieval_index",
            "source_record_hash",
            "abstract_sha256",
            "support_span_sha256",
        ):
            support.pop(field_name)

    raw_review = _review_payload(complete_author, context)
    review = raw_review["reviews"][0]
    review.pop("atom_hash")
    review.pop("not_direct_prior_method_copy")
    review.pop("accepted")
    for comparison in review["prior_work_comparisons"]:
        comparison.pop("abstract_sha256")
        comparison["overlap_zh"] = "无直接重叠。"
        comparison["difference_zh"] = "对照不同。"
        comparison["residual_risk_zh"] = "仍需实验。"

    artifact = run_system_plan_prospective_atoms(
        lineage_id=LINEAGE_ID,
        literature_survey=survey,
        feasibility_envelope=envelope,
        observed_component_binding=observed,
        method_skill_selection=_method_binding(),
        interface_contract=build_prospective_execution_interface_contract(envelope),
        output_dir=tmp_path,
        author_completion=_StubSequence([raw_author], reasoning="已逐项核对。"),
        reviewer_completion=_StubSequence([raw_review], reasoning="逐篇核对完成。"),
        max_rounds=1,
        clock=FIXED_CLOCK,
    )

    final_atom = artifact.final_portfolio.atoms[0]
    final_review = artifact.final_review.reviews[0]
    assert final_atom.control_level_zh == "保持谱导数基线"
    assert final_atom.literature_supports[0].support_role == "方法基础"
    assert final_atom.baseline_observed_atom_hash == canonical_model_hash(
        next(
            item for item in observed.atoms if item.atom_id == final_atom.baseline_observed_atom_id
        )
    )
    assert final_review.accepted is True
    assert final_review.not_direct_prior_method_copy is True
    assert final_review.prior_work_comparisons[0].overlap_zh == "无直接重叠。"
    assert final_review.prior_work_comparisons[0].abstract_sha256 == (
        context.selected_abstracts[0].abstract_sha256
    )


def test_chinese_label_may_retain_standard_algorithm_identifiers() -> None:
    _, _, observed, context = _context_and_aliases()
    response = _author_payload(context, observed)
    response["atoms"][0]["label_zh"] = "LASSO优化器替代STRidge"
    portfolio = ProspectiveAtomPortfolio.model_validate(response)
    assert portfolio.atoms[0].label_zh == "LASSO优化器替代STRidge"

    response["atoms"][0]["label_zh"] = "English Method Without Chinese"
    with pytest.raises(SystemPlanProspectiveAtomError, match="label_zh"):
        ProspectiveAtomPortfolio.model_validate(response)


@pytest.mark.parametrize("value", [" ", "。", "123"])
def test_relaxed_length_still_requires_actual_chinese(value: str) -> None:
    _, _, observed, context = _context_and_aliases()
    response = _author_payload(context, observed)
    response["atoms"][0]["control_level_zh"] = value
    with pytest.raises((ValidationError, SystemPlanProspectiveAtomError)):
        ProspectiveAtomPortfolio.model_validate(response)


def test_target_fact_type_interface_and_budget_gates_reject_mutations(
    tmp_path: Path,
) -> None:
    survey, envelope, observed, context = _context_and_aliases()
    valid = _author_payload(context, observed)
    mutations: list[tuple[str, Any]] = [
        (
            "未知匿名目标",
            lambda payload: payload["atoms"][0].update({"target_keys": ["T001", "T002", "T999"]}),
        ),
        (
            "资源请求超过",
            lambda payload: payload["atoms"][0]["resource_request"].update(
                {"seconds_per_cell": 301}
            ),
        ),
    ]
    for expected, mutate in mutations:
        payload = copy.deepcopy(valid)
        mutate(payload)
        reviewer = _StubSequence([_review_payload(valid, context)])
        with pytest.raises(SystemPlanProspectiveAtomError, match=expected):
            run_system_plan_prospective_atoms(
                lineage_id=LINEAGE_ID,
                literature_survey=survey,
                feasibility_envelope=envelope,
                observed_component_binding=observed,
                method_skill_selection=_method_binding(),
                interface_contract=build_prospective_execution_interface_contract(envelope),
                output_dir=tmp_path / expected,
                author_completion=_StubSequence([payload]),
                reviewer_completion=reviewer,
                max_rounds=1,
                clock=FIXED_CLOCK,
            )
        assert reviewer.calls == []

    bad_interface = build_prospective_execution_interface_contract(
        envelope, public_hooks=("predict_derivative",)
    )
    payload = copy.deepcopy(valid)
    payload["atoms"][0]["public_hooks"] = ["fit_equations"]
    with pytest.raises(SystemPlanProspectiveAtomError, match="合同外公开接口"):
        run_system_plan_prospective_atoms(
            lineage_id=LINEAGE_ID,
            literature_survey=survey,
            feasibility_envelope=envelope,
            observed_component_binding=observed,
            method_skill_selection=_method_binding(),
            interface_contract=bad_interface,
            output_dir=tmp_path / "interface",
            author_completion=_StubSequence([payload]),
            reviewer_completion=_StubSequence([_review_payload(valid, context)]),
            max_rounds=1,
            clock=FIXED_CLOCK,
        )


def test_real_target_or_title_leak_is_rejected_before_review(tmp_path: Path) -> None:
    survey, envelope, observed, context = _context_and_aliases()
    payload = _author_payload(context, observed)
    payload["atoms"][0]["delta_from_prior_work_zh"] += (
        f"真实目标为{SYSTEM_NAMES[0]}，题名为{survey.selected_references[0]['title']}。"
    )
    # Bypass the prose language guard so this test reaches the explicit privacy gate.
    portfolio = ProspectiveAtomPortfolio.model_construct(
        atoms=(
            ProspectiveAtomPortfolio.model_validate(_author_payload(context, observed))
            .atoms[0]
            .model_copy(
                update={"delta_from_prior_work_zh": payload["atoms"][0]["delta_from_prior_work_zh"]}
            ),
        )
    )
    valid_artifact = _run_valid(tmp_path / "aliases")
    findings = prospective_atom_portfolio_findings(
        portfolio=portfolio,
        context=context,
        target_aliases=valid_artifact.target_aliases,
        observed_component_binding=observed,
        literature_survey=survey,
    )
    assert any("泄漏真实系统名" in item for item in findings)
    assert any("复述论文题名" in item for item in findings)


def test_reviewer_must_compare_every_selected_abstract_in_order() -> None:
    _, _, observed, context = _context_and_aliases()
    author_payload = _author_payload(context, observed)
    review_payload = _review_payload(author_payload, context)
    comparisons = review_payload["reviews"][0]["prior_work_comparisons"]
    comparisons[2] = copy.deepcopy(comparisons[1])
    review = ProspectiveAtomReviewPortfolio.model_validate(review_payload)

    findings = prospective_atom_review_findings(
        review=review,
        portfolio=ProspectiveAtomPortfolio.model_validate(author_payload),
        context=context,
    )

    assert findings == ("P001 未按顺序比较全部真实入选摘要",)


def test_reviewer_order_is_normalized_without_rebinding_identity() -> None:
    _, _, observed, context = _context_and_aliases()
    author_payload = _author_payload(context, observed)
    second = copy.deepcopy(author_payload["atoms"][0])
    second["atom_id"] = "P002"
    author_payload["atoms"].append(second)
    portfolio = ProspectiveAtomPortfolio.model_validate(author_payload)
    raw_review = _review_payload(author_payload, context)
    raw_review["reviews"].reverse()
    for item in raw_review["reviews"]:
        item["prior_work_comparisons"].reverse()

    normalized = prospective_atoms._derive_reviewer_bindings(
        raw_review,
        portfolio=portfolio,
        context=context,
    )
    review = ProspectiveAtomReviewPortfolio.model_validate(normalized)

    assert tuple(item.atom_id for item in review.reviews) == ("P001", "P002")
    assert tuple(
        item.reference_index for item in review.reviews[0].prior_work_comparisons
    ) == tuple(item.reference_index for item in context.selected_abstracts)


def test_direct_prior_method_copy_cannot_be_accepted() -> None:
    _, _, observed, context = _context_and_aliases()
    author_payload = _author_payload(context, observed)
    review_payload = _review_payload(author_payload, context)
    review_payload["reviews"][0]["prior_work_comparisons"][0]["direct_method_copy"] = True

    with pytest.raises((ValidationError, SystemPlanProspectiveAtomError), match="既有方法排除门"):
        ProspectiveAtomReviewPortfolio.model_validate(review_payload)


def test_redundant_review_booleans_are_derived_not_retried() -> None:
    _, _, observed, context = _context_and_aliases()
    author_payload = _author_payload(context, observed)
    portfolio = ProspectiveAtomPortfolio.model_validate(author_payload)
    raw_review = _review_payload(author_payload, context)
    raw_item = raw_review["reviews"][0]
    raw_item["prior_work_comparisons"][0]["direct_method_copy"] = True
    raw_item["not_direct_prior_method_copy"] = True
    raw_item["accepted"] = True
    raw_item["findings_zh"] = []

    normalized = prospective_atoms._derive_reviewer_bindings(
        raw_review,
        portfolio=portfolio,
        context=context,
    )
    review = ProspectiveAtomReviewPortfolio.model_validate(normalized).reviews[0]

    assert review.not_direct_prior_method_copy is False
    assert review.accepted is False
    assert review.findings_zh == ("可能直接复制既有方法或摘要不足",)


@pytest.mark.parametrize(
    ("provider", "model_name", "reasoning", "transport", "expected"),
    [
        (
            "other-provider",
            "other-model",
            "充分推理" * 100,
            "dashscope_enable_thinking",
            "必须是 Qwen",
        ),
        (
            "qwen-dashscope",
            "qwen3.7-max",
            "",
            "dashscope_enable_thinking",
            "非空 reasoning_content",
        ),
        (
            "qwen-dashscope",
            "qwen3.7-max",
            "充分推理" * 100,
            "absent",
            "thinking 已开启",
        ),
    ],
)
def test_qwen_identity_reasoning_and_thinking_receipts_are_hard_gates(
    tmp_path: Path,
    provider: str,
    model_name: str,
    reasoning: str,
    transport: Literal[
        "absent",
        "dashscope_enable_thinking",
        "anthropic_thinking_block",
    ],
    expected: str,
) -> None:
    survey, envelope, observed, context = _context_and_aliases()
    payload = _author_payload(context, observed)
    reviewer = _StubSequence([_review_payload(payload, context)])

    with pytest.raises(SystemPlanProspectiveAtomError, match=expected):
        run_system_plan_prospective_atoms(
            lineage_id=LINEAGE_ID,
            literature_survey=survey,
            feasibility_envelope=envelope,
            observed_component_binding=observed,
            method_skill_selection=_method_binding(),
            interface_contract=build_prospective_execution_interface_contract(envelope),
            output_dir=tmp_path / expected,
            author_completion=_StubSequence(
                [payload],
                provider=provider,
                model_name=model_name,
                reasoning=reasoning,
                reasoning_transport=transport,
            ),
            reviewer_completion=reviewer,
            max_rounds=1,
            clock=FIXED_CLOCK,
        )
    assert reviewer.calls == []


def test_complete_abstract_prompt_is_rejected_instead_of_truncated() -> None:
    survey = _survey(oversized_abstract=True)
    envelope = _envelope()
    observed = _observed_binding(envelope)

    with pytest.raises(SystemPlanProspectiveAtomError, match="拒绝静默截断"):
        build_prospective_atom_context(
            survey=survey,
            feasibility_envelope=envelope,
            observed_component_binding=observed,
            method_skill_selection=_method_binding(),
            interface_contract=build_prospective_execution_interface_contract(envelope),
        )


def test_old_schema_and_true_safety_claims_fail_closed() -> None:
    _, _, observed, context = _context_and_aliases()
    payload = _author_payload(context, observed)
    payload["schema_version"] = "prospective-atom-portfolio-v0"
    with pytest.raises(ValidationError):
        ProspectiveAtomPortfolio.model_validate(payload)

    payload = _author_payload(context, observed)
    payload["atoms"][0]["innovation_verified"] = True
    with pytest.raises(ValidationError):
        ProspectiveAtomPortfolio.model_validate(payload)

    payload = _author_payload(context, observed)
    payload["atoms"][0]["execution_authorized"] = True
    with pytest.raises(ValidationError):
        ProspectiveAtomPortfolio.model_validate(payload)


def test_failed_author_attempt_is_hash_bound_before_later_success(
    tmp_path: Path,
) -> None:
    survey, envelope, observed, context = _context_and_aliases()
    valid = _author_payload(context, observed)
    invalid = copy.deepcopy(valid)
    invalid["atoms"][0]["resource_request"]["seconds_per_cell"] = 301
    author = _StubSequence([invalid, valid])
    reviewer = _StubSequence([_review_payload(valid, context)])

    artifact = run_system_plan_prospective_atoms(
        lineage_id=LINEAGE_ID,
        literature_survey=survey,
        feasibility_envelope=envelope,
        observed_component_binding=observed,
        method_skill_selection=_method_binding(),
        interface_contract=build_prospective_execution_interface_contract(envelope),
        output_dir=tmp_path,
        author_completion=author,
        reviewer_completion=reviewer,
        max_rounds=2,
        clock=FIXED_CLOCK,
    )

    assert [item.outcome for item in artifact.attempt_manifest] == [
        "author_rejected",
        "author_forwarded",
        "reviewer_accepted",
    ]
    assert artifact.rounds[0].round_index == 2
    assert artifact.attempt_manifest[0].failure_summary_zh
    assert artifact.attempt_manifest[0].receipt_hash == (
        artifact.attempt_manifest[0].receipt.receipt_hash
        if artifact.attempt_manifest[0].receipt is not None
        else None
    )
    assert artifact.rounds[0].author_feedback_zh == (
        artifact.attempt_manifest[0].failure_summary_zh
    )
    assert len(list((tmp_path / "prospective-attempts").glob("*.json"))) == 3
    persisted = SystemPlanProspectiveAtomArtifact.model_validate_json(
        (tmp_path / "system-plan-prospective-atoms.json").read_text(encoding="utf-8")
    )
    assert persisted == artifact


def test_reviewer_transport_failure_retries_same_author_without_rewrite(
    tmp_path: Path,
) -> None:
    survey, envelope, observed, context = _context_and_aliases()
    author_payload = _author_payload(context, observed)
    author = _StubSequence([author_payload])
    reviewer = _ReviewerTransportFailureThenSuccess(_review_payload(author_payload, context))

    artifact = run_system_plan_prospective_atoms(
        lineage_id=LINEAGE_ID,
        literature_survey=survey,
        feasibility_envelope=envelope,
        observed_component_binding=observed,
        method_skill_selection=_method_binding(),
        interface_contract=build_prospective_execution_interface_contract(envelope),
        output_dir=tmp_path,
        author_completion=author,
        reviewer_completion=reviewer,
        max_rounds=1,
        clock=FIXED_CLOCK,
    )

    assert len(author.calls) == 1
    assert len(reviewer.calls) == 2
    assert [item.outcome for item in artifact.attempt_manifest] == [
        "author_forwarded",
        "reviewer_call_failed",
        "reviewer_accepted",
    ]
    assert [item.stage_attempt_index for item in artifact.attempt_manifest] == [
        1,
        1,
        2,
    ]
    assert artifact.rounds[0].reviewer_attempt_index == 2
    assert artifact.rounds[0].reviewer_feedback_zh == (
        artifact.attempt_manifest[1].failure_summary_zh
    )
    assert artifact.final_portfolio.model_dump(mode="json") == author_payload


def test_author_transport_failure_retries_without_spending_scientific_round(
    tmp_path: Path,
) -> None:
    survey, envelope, observed, context = _context_and_aliases()
    author_payload = _author_payload(context, observed)
    author = _AuthorTransportFailureThenSuccess(author_payload)
    reviewer = _StubSequence([_review_payload(author_payload, context)])

    artifact = run_system_plan_prospective_atoms(
        lineage_id=LINEAGE_ID,
        literature_survey=survey,
        feasibility_envelope=envelope,
        observed_component_binding=observed,
        method_skill_selection=_method_binding(),
        interface_contract=build_prospective_execution_interface_contract(envelope),
        output_dir=tmp_path,
        author_completion=author,
        reviewer_completion=reviewer,
        max_rounds=1,
        clock=FIXED_CLOCK,
    )

    assert len(author.calls) == 2
    assert [item.outcome for item in artifact.attempt_manifest] == [
        "author_call_failed",
        "author_forwarded",
        "reviewer_accepted",
    ]
    assert [item.stage_attempt_index for item in artifact.attempt_manifest] == [
        1,
        2,
        1,
    ]
    assert artifact.rounds[0].round_index == 1


def test_identical_author_failure_triggers_no_progress_fuse(tmp_path: Path) -> None:
    survey, envelope, observed, context = _context_and_aliases()
    invalid = _author_payload(context, observed)
    invalid["atoms"][0]["resource_request"]["seconds_per_cell"] = 301
    author = _StubSequence([invalid, invalid, _author_payload(context, observed)])
    reviewer = _StubSequence([_review_payload(_author_payload(context, observed), context)])

    with pytest.raises(SystemPlanProspectiveAtomError, match="无进展熔断"):
        run_system_plan_prospective_atoms(
            lineage_id=LINEAGE_ID,
            literature_survey=survey,
            feasibility_envelope=envelope,
            observed_component_binding=observed,
            method_skill_selection=_method_binding(),
            interface_contract=build_prospective_execution_interface_contract(envelope),
            output_dir=tmp_path,
            author_completion=author,
            reviewer_completion=reviewer,
            max_rounds=3,
            clock=FIXED_CLOCK,
        )

    assert len(author.calls) == 2
    assert reviewer.calls == []
    attempt = ProspectiveModelAttempt.model_validate_json(
        (tmp_path / "prospective-attempts" / "02-author-01.json").read_text(encoding="utf-8")
    )
    assert attempt.no_progress_fuse_triggered is True
    assert any("无进展熔断" in item for item in attempt.failure_summary_zh)


def test_identical_reviewer_decline_triggers_no_progress_fuse(tmp_path: Path) -> None:
    survey, envelope, observed, context = _context_and_aliases()
    author_payload = _author_payload(context, observed)
    declined = _review_payload(author_payload, context)
    review = declined["reviews"][0]
    review["budget_valid"] = False
    review["accepted"] = False
    review["findings_zh"] = ["资源预算门未通过，不能接受该前瞻组件候选。"]
    author = _StubSequence([author_payload, author_payload, author_payload])
    reviewer = _StubSequence([declined, declined, _review_payload(author_payload, context)])

    with pytest.raises(SystemPlanProspectiveAtomError, match="无进展熔断"):
        run_system_plan_prospective_atoms(
            lineage_id=LINEAGE_ID,
            literature_survey=survey,
            feasibility_envelope=envelope,
            observed_component_binding=observed,
            method_skill_selection=_method_binding(),
            interface_contract=build_prospective_execution_interface_contract(envelope),
            output_dir=tmp_path,
            author_completion=author,
            reviewer_completion=reviewer,
            max_rounds=3,
            clock=FIXED_CLOCK,
        )

    assert len(author.calls) == 2
    assert len(reviewer.calls) == 2
    attempt = ProspectiveModelAttempt.model_validate_json(
        (tmp_path / "prospective-attempts" / "02-reviewer-01.json").read_text(encoding="utf-8")
    )
    assert attempt.no_progress_fuse_triggered is True


def test_v30_real_shape_keeps_five_full_abstracts_under_prompt_limit(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[3]
    v30_root = repository_root / "runs" / "manual-live" / "task2705-preregister-plan-smoke-v30"
    survey_path = v30_root / "plan-literature-survey.json"
    component_path = v30_root / "system-plan-component-atoms.json"
    if not survey_path.is_file() or not component_path.is_file():
        pytest.skip("v30 real-shape artifacts are not present in this checkout")
    survey = PlanLiteratureSurveyArtifact.model_validate_json(
        survey_path.read_text(encoding="utf-8")
    )
    raw_component = json.loads(component_path.read_text(encoding="utf-8"))
    envelope = ResearchFeasibilityEnvelope.model_validate(raw_component["feasibility_envelope"])
    method_binding = SystemPlanMethodSkillSelectionBinding.model_validate(
        raw_component["method_skill_selection"]
    )
    observed_portfolio = SystemPlanComponentAtomPortfolio.model_validate(
        raw_component["final_portfolio"]
    )
    observed_review = SystemPlanComponentAtomReviewPortfolio.model_validate(
        raw_component["final_review"]
    )
    binding_payload: dict[str, Any] = {
        "schema_version": "system-plan-component-atom-binding-v1",
        "component_atom_artifact_hash": raw_component["artifact_hash"],
        "feasibility_envelope_hash": envelope.envelope_hash,
        "source_clause_catalog_hash": raw_component["source_clause_catalog"]["catalog_hash"],
        "method_skill_selection_artifact_hash": (method_binding.selection_artifact_hash),
        "atoms": [item.model_dump(mode="json") for item in observed_portfolio.atoms],
        "independent_review_hash": canonical_model_hash(observed_review),
        "is_scientific_evidence": False,
        "execution_authorized": False,
    }
    binding_payload["binding_hash"] = canonical_model_hash(binding_payload)
    observed = SystemPlanComponentAtomBinding.model_validate(binding_payload)
    interface = build_prospective_execution_interface_contract(envelope)
    context = build_prospective_atom_context(
        survey=survey,
        feasibility_envelope=envelope,
        observed_component_binding=observed,
        method_skill_selection=method_binding,
        interface_contract=interface,
    )
    author_payload = _author_payload(context, observed)
    author = _StubSequence([author_payload])
    reviewer = _StubSequence([_review_payload(author_payload, context)])

    artifact = run_system_plan_prospective_atoms(
        lineage_id=survey.lineage_id,
        literature_survey=survey,
        feasibility_envelope=envelope,
        observed_component_binding=observed,
        method_skill_selection=method_binding,
        interface_contract=interface,
        output_dir=tmp_path,
        author_completion=author,
        reviewer_completion=reviewer,
        max_rounds=1,
        clock=FIXED_CLOCK,
    )

    def message_bytes(messages: list[dict[str, str]]) -> int:
        return len(
            json.dumps(
                messages,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )

    assert len(artifact.context.selected_abstracts) == 5
    assert [item.abstract_text for item in artifact.context.selected_abstracts] == [
        survey.retrieved_catalog[item.retrieval_index]["abstract"]
        for item in artifact.context.selected_abstracts
    ]
    assert artifact.context.context_payload_utf8_bytes > 0
    assert message_bytes(author.calls[0]["messages"]) <= 98_304
    assert message_bytes(reviewer.calls[0]["messages"]) <= 98_304


def test_artifact_is_write_once_but_identical_resume_is_allowed(tmp_path: Path) -> None:
    first = _run_valid(tmp_path)
    resumed = _run_valid(tmp_path)
    assert resumed == first

    with pytest.raises(SystemPlanProspectiveAtomError, match="拒绝覆盖不同"):
        _run_valid(tmp_path, clock=FIXED_CLOCK + timedelta(seconds=1))
