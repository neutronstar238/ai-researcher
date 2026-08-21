"""Evidence-first one-command research loop for a specified direction.

The order is intentionally scientific rather than document-first:

``broad live retrieval -> evidence-grounded focus selection -> targeted live retrieval
-> merged verified bibliography -> evidence-aware Skill routing -> candidate hypotheses
-> compatible real pilot -> evidence feedback -> independent objective review
-> detailed Chinese plan -> independent scientific review``.

Only registered experiment adapters may execute.  The current registry contains
one bounded prime-gap information-theory pilot.  An unsupported direction is
reported as unsupported; this module never manufactures a simulated result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from autoresearch.agents.temporary import (
    TemporaryAgentInputRef,
    TemporaryAgentSkillRef,
    issue_stage_controller,
)
from autoresearch.competition.contest_adapter_semantics import (
    assess_adapter_semantic_compatibility,
)
from autoresearch.competition.contest_direct_plan import (
    ContestDirectPlanArtifact,
    generate_contest_direct_plan,
    load_contest_direct_plan,
)
from autoresearch.competition.contest_direct_plan_cli import discover_contest_method_skills
from autoresearch.competition.contest_direct_plan_render import (
    ContestDirectPlanArtifacts,
    materialize_contest_direct_plan,
)
from autoresearch.competition.contest_direct_plan_revision import (
    ContestDirectPlanNumberGuardError,
    ContestDirectPlanRevisionArtifact,
    revise_contest_direct_plan,
)
from autoresearch.competition.contest_direct_plan_scientific_review import (
    ContestDirectPlanScientificReviewArtifact,
    load_contest_direct_plan_scientific_review,
    review_contest_direct_plan_science,
)
from autoresearch.competition.contest_direct_skill_router import (
    ContestDirectLiteratureEvidenceContext,
    ContestDirectSkillRoutingArtifact,
    ContestDirectSkillRoutingError,
    load_contest_direct_skill_routing,
    route_contest_direct_plan_skills,
)
from autoresearch.competition.contest_direction_context_runtime import (
    ContestDirectionContextRuntime,
)
from autoresearch.competition.contest_direction_focus_literature import (
    ContestDirectionFocusArtifact,
    ContestDirectionTargetedRetrievalBinding,
    load_contest_direction_focus_selection,
    load_contest_direction_targeted_retrieval,
    run_contest_direction_focus_selection,
    run_contest_direction_targeted_retrieval,
)
from autoresearch.competition.contest_direction_gap_repair_retrieval import (
    ContestDirectionGapRepairArtifact,
    build_contest_direction_gap_repair_plan_from_projection,
    load_contest_direction_gap_repair,
    retrieve_contest_direction_gap_repair,
)
from autoresearch.competition.contest_direction_layered_literature import (
    ContestDirectionLayeredLiteratureArtifact,
    build_contest_direction_layered_literature,
    load_contest_direction_layered_literature,
)
from autoresearch.competition.contest_direction_literature import (
    ContestDirectionLiteratureArtifact,
    retrieve_contest_direction_literature,
)
from autoresearch.competition.contest_direction_memory import (
    ContestDirectionMemoryBridge,
    MemoryRecallResult,
    optional_dreaming_context_hash,
)
from autoresearch.competition.contest_direction_merged_literature import (
    ContestDirectionMergedLiteratureArtifact,
    load_contest_direction_merged_literature,
    merge_contest_direction_literature,
)
from autoresearch.competition.contest_direction_plan_cli import (
    _FINALIST_STATUS_CONTEXT_RESERVE,
    _MAX_PLANNING_LITERATURE_CHARACTERS,
    _arxiv_status_url,
    _lexical_tokens,
    _planning_budget_identity,
    _planning_work_family_suppressions,
    _select_planning_literature,  # noqa: F401 - retained test/public compatibility seam
    _select_planning_literature_with_status,  # noqa: F401 - compatibility seam
    _verify_arxiv_finalist,
    _verify_plan_references,
    _verify_rendered_pdf,
)
from autoresearch.competition.contest_direction_stage_checkpoint import (
    provider_checkpoint_accounting,
    provider_checkpoint_count,
    record_completed_stage,
    replayable_literature_searchers,
    replayable_paper_verifier,
    research_loop_source_checkpoint_accounting,
)
from autoresearch.competition.contest_plan_embedded_evidence import (
    build_contest_plan_embedded_evidence,
)
from autoresearch.competition.contest_planning_literature_coverage import (
    PlanningLiteratureCandidate,
    PlanningLiteratureCoverageError,
    PlanningLiteratureCoverageReceipt,
    PlanningLiteratureRole,
    PlanningLiteratureRoleQuery,
    load_planning_literature_coverage_receipt,
    role_query_from_boolean,
    select_planning_literature,
)
from autoresearch.competition.contest_planning_literature_gap_repair import (
    PlanningLiteratureGapDiagnosisReceipt,
    PlanningLiteratureGapRepairEvidenceInput,
    PlanningLiteratureGapRepairProjection,
    diagnose_planning_literature_gap,
    load_planning_literature_gap_diagnosis,
    load_planning_literature_gap_repair_projection,
    write_planning_literature_gap_diagnosis,
    write_planning_literature_gap_repair_projection,
)
from autoresearch.competition.contest_planning_literature_gap_repair_runner import (
    PlanningLiteratureGapRepairResponseError,
    PlanningLiteratureGapRepairResponseReceipt,
    gap_repair_failure_is_revisable,
    load_planning_literature_gap_repair_response,
    planning_literature_gap_repair_stage_input_hash,
    run_planning_literature_gap_repair_query,
)
from autoresearch.competition.contest_planning_literature_quality import (
    assess_planning_literature_quality,
)
from autoresearch.competition.contest_prime_preexperiment import (
    ContestPrimePreexperimentArtifact,
    load_contest_prime_preexperiment,
    run_contest_prime_preexperiment,
)
from autoresearch.competition.contest_reference_policy import (
    MAX_RESEARCH_PLAN_REFERENCES,
    MIN_RESEARCH_PLAN_REFERENCES,
    build_postpilot_reference_catalog,
)
from autoresearch.competition.contest_research_objective_stage import (
    ContestResearchObjectiveStageArtifact,
)
from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.model_authorship import ModelAuthorshipReceipt
from autoresearch.competition.temporary_qwen_pool import TemporaryQwenSkillContext
from autoresearch.literature.clients import (
    ArxivClient,
    OpenAlexClient,
    SemanticScholarClient,
    semantic_scholar_enabled,
)
from autoresearch.literature.doi_verification import verify_reference_records
from autoresearch.literature.models import AcademicPaper
from autoresearch.llm.client import LLMJsonCompletionResult

_DEFAULT_OUTPUT = Path("runs/contest-delivery/specified-direction-research-loop")
_DEFAULT_SKILLS_ROOT = Path("skills")
_DEFAULT_RESULTS_PER_SEARCH = 20
_ADAPTER_ID = "prime-gap-information-theory-v1"
_REQUIRED_SKILL_ID = "prime-structure-computational-number-theory"
_SCIENCE125_Q001_EN = "What makes prime numbers so special?"
_SCIENCE125_Q001_ZH = "素数为何如此特别？"
_SCIENCE125_Q001_BATCH_DIRECTION = (
    f"{_SCIENCE125_Q001_ZH}\n"
    f"原始英文问题：{_SCIENCE125_Q001_EN}\n"
    "来源：《125 Questions: Exploration and Discovery》第1题（数学科学）。"
)
_PRIME_NULL_MODELS = frozenset(
    {
        "local_block_permutation",
        "global_permutation",
        "residue_path_conditioned_permutation",
        "wheel_210",
    }
)
_GENERIC_PLANNING_OBJECT_TERMS = frozenset(
    {
        "generic",
        "model",
        "models",
        "system",
        "systems",
        "method",
        "methods",
    }
)
_GENERIC_PLANNING_OBJECT_PHRASES = frozenset(
    {"模型", "系统", "方法", "generic model", "generic system", "generic method"}
)
_LOOP_REQUIREMENTS = (
    "先用不含任何Skill正文或元数据的通用查询做真实学术检索",
    "Skill只在真实检索后依据方向与文献证据选择，Skill是方法论而非事实证据",
    "生成多个可证伪候选假设，并仅对有真实执行适配器的候选运行探索性预实验",
    "根据真实预实验支持、否决或不确定结果收窄或有界重想研究目标",
    "独立目标评审发生在预实验之后，随后生成详细中文研究计划",
    "最终独立科学评审只旁路评价，不删除或改写最终计划",
    "预实验不是正式实验、数学证明或论文；所有数字必须来自已核验证据",
)
# 反馈修订阶段的结果边界要求（与 mainline 的 P-20260816-022 修复一致，并补 live 暴露的两条）：
# - 数字边界：模型曾引入验证输入中不存在的数字（如 10^9、2310）而被数字守卫拒绝。
# - 替代解释：数字守卫要求 Results 必须给出至少一种替代解释。
# - 数据规模一致性：live 暴露修订把 technical_details/target 改成 10^9 却漏改 datasets（仍 10^8）。
# - 禁止无文献支撑机制归因：live 暴露修订把微弱残差归因到「高阶 Hardy-Littlewood k-tuple」等锁定文献不支持的机制。
_REVISION_RESULT_REQUIREMENTS = (
    "除所给指标与日志中已经出现的数值外，正文不得引入任何新数字；"
    "如需引用轮筛周期长度等常数，只写其名称（如 wheel-210），不得写出其数值",
    "当预实验结果不支持主假设或效应微弱时，Results 必须明确写出至少一种替代解释"
    "（如更强的模算术约束、有限样本波动、非平稳密度梯度等），并如实收窄结论。",
    "Datasets/Source/Target 与 Technical Details、Methods、Experiments 中的数据规模必须完全一致；"
    "若正式实验要扩大区间（如从 10^8 扩到 10^9），必须同步更新 Datasets 与 Technical Details"
    "中所有出现的区间上界，不得只改一处。",
    "结果与局限性部分绝对禁止出现任何命名的数学猜想或机制名称——包括但不限于 "
    "Hardy-Littlewood、黎曼、Cramér、k-tuple、二级项、猜想——即使以「可能是」「不能排除」"
    "的方式提及也禁止。解释微小残差时只能用描述性表述（如「更高阶模算术约束，如 wheel-2310」"
    "「有限样本偏差」「区间伪影」「并列处理偏差」），并明确这些只是有待检验的假设、而非已证实机制。",
)
_ADAPTER_DESCRIPTOR: dict[str, Any] = {
    "adapter_id": _ADAPTER_ID,
    "scientific_object": "consecutive_integer_primes",
    "observable": "ordered_consecutive_prime_gaps",
    "supported_metrics": ["tie_aware_normalized_permutation_entropy_m5"],
    "supported_nulls": sorted(_PRIME_NULL_MODELS),
    "description": (
        "在冻结有限整数区间上生成连续素数有序间隙，计算含并列处理的五阶排列熵，"
        "并与局部、全局、残基路径条件及wheel-210零模型比较。"
    ),
    "study_phase": "exploratory_pilot",
    "runner": "contest_prime_preexperiment.run_contest_prime_preexperiment",
    "execution_boundary_zh": (
        "仅分析确定性分段筛生成的连续整数素数及其有序相邻间隙；"
        "主指标为含并列处理的五阶排列熵，并与已注册零模型比较。"
        "它不能执行任意数论、解析证明、黎曼猜想或非素数间隙实验。"
    ),
}

PreexperimentPolicy = Literal["required", "if_supported"]

_LITERATURE_PROTOCOL = "two_stage_literature_v5"
_INPUT_SCHEMA = "contest-direction-research-loop-input-v2"
_SOURCE_ACCOUNTING_PROTOCOL = "physical-source-http-attempt-ledger-v1"
_DELIVERY_SCHEMA = "contest-direction-research-loop-delivery-v2"
_SCIENTIFIC_BLOCK_SCHEMA = "contest-direction-scientific-review-block-v1"
_SCIENTIFIC_BLOCK_RECEIPT = "scientific-review-blocked-receipt.json"
_SCIENTIFIC_COMPLETION_STATUS = {
    "pass": "completed",
    "minor_revision": "completed_with_minor_issues",
}
_SCIENTIFIC_BLOCKING_RECOMMENDATIONS = frozenset({"major_revision", "reject", "unclear"})
_CATALOG_CONTEXT_INDEX = re.compile(r"^\[(?P<index>[1-9][0-9]*)\](?P<suffix>\s+record_id=)")
_OUTER_MODEL_STAGES = (
    "broad-literature-query",
    "focus-selection",
    "targeted-literature-query",
    "planning-literature-gap-repair-query",
    "skill-routing",
    "hypothesis-brainstorm",
    "provisional-plan",
    "postpilot-objective-review",
    "final-plan-revision",
    "independent-scientific-review",
)

_PlanningLiteratureArtifact = (
    ContestDirectionMergedLiteratureArtifact | ContestDirectionLayeredLiteratureArtifact
)


@dataclass(frozen=True)
class _TwoStageLiteratureState:
    broad: ContestDirectionLiteratureArtifact
    broad_path: Path
    focus: ContestDirectionFocusArtifact
    focus_path: Path
    targeted_binding: ContestDirectionTargetedRetrievalBinding
    targeted_binding_path: Path
    targeted: ContestDirectionLiteratureArtifact
    targeted_path: Path
    merged: _PlanningLiteratureArtifact
    merged_path: Path
    planning_catalog: tuple[dict[str, Any], ...]
    planning_context: tuple[str, ...]
    excluded_records: list[dict[str, str]]
    finalist_status_path: Path
    finalist_status_payload: dict[str, Any]
    planning_coverage_path: Path
    planning_coverage: PlanningLiteratureCoverageReceipt
    planning_lock_path: Path
    planning_lock_payload: dict[str, Any]
    base_merged: ContestDirectionMergedLiteratureArtifact | None = None
    base_merged_path: Path | None = None
    effective_role_queries: tuple[PlanningLiteratureRoleQuery, ...] = ()
    r1_planning_coverage_path: Path | None = None
    r1_planning_coverage: PlanningLiteratureCoverageReceipt | None = None
    r2_planning_coverage_path: Path | None = None
    r2_planning_coverage: PlanningLiteratureCoverageReceipt | None = None
    gap_diagnosis_path: Path | None = None
    gap_diagnosis: PlanningLiteratureGapDiagnosisReceipt | None = None
    gap_response_path: Path | None = None
    gap_response: PlanningLiteratureGapRepairResponseReceipt | None = None
    gap_projection_path: Path | None = None
    gap_projection: PlanningLiteratureGapRepairProjection | None = None
    gap_retrieval_path: Path | None = None
    gap_retrieval: ContestDirectionGapRepairArtifact | None = None


@dataclass(frozen=True)
class _BoundedGapRepairState:
    diagnosis: PlanningLiteratureGapDiagnosisReceipt
    diagnosis_path: Path
    response: PlanningLiteratureGapRepairResponseReceipt
    response_path: Path
    projection: PlanningLiteratureGapRepairProjection
    projection_path: Path
    retrieval: ContestDirectionGapRepairArtifact
    retrieval_path: Path
    layered: ContestDirectionLayeredLiteratureArtifact
    layered_path: Path


class ContestDirectionResearchLoopError(RuntimeError):
    """Raised when the evidence-first direction loop cannot truthfully continue."""


def run_contest_direction_research_loop(
    *,
    direction: str,
    output_dir: Path | str = _DEFAULT_OUTPUT,
    source_direction_delivery: Path | str | None = None,
    resume_existing: bool = False,
    preexperiment_policy: PreexperimentPolicy = "required",
    skills_root: Path | str = _DEFAULT_SKILLS_ROOT,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    context_vault_root: Path | str = Path("autoresearch-vault"),
    context_capability_cache_dir: Path | str = Path(".cache/autoresearch/model-capabilities"),
    context_completion: Callable[..., LLMJsonCompletionResult] | None = None,
    dreaming_recall_enabled: bool = True,
    max_results_per_search: int = _DEFAULT_RESULTS_PER_SEARCH,
    retrieval_max_tokens: int = 768,
    skill_routing_max_tokens: int = 1_024,
    brainstorm_max_tokens: int = 3_000,
    feedback_max_tokens: int = 3_500,
    objective_review_max_tokens: int = 4_000,
    plan_max_tokens: int = 14_000,
    scientific_review_max_tokens: int = 8_000,
    timeout_seconds: int = 900,
    thinking_budget: int = 3_000,
    render_timeout_seconds: int = 180,
    literature_runner: Callable[..., ContestDirectionLiteratureArtifact] = (
        retrieve_contest_direction_literature
    ),
    literature_searchers: Mapping[str, Callable[..., Sequence[AcademicPaper]]] | None = None,
    focus_selection_runner: Callable[..., ContestDirectionFocusArtifact] = (
        run_contest_direction_focus_selection
    ),
    targeted_retrieval_runner: Callable[
        ..., ContestDirectionTargetedRetrievalBinding
    ] = run_contest_direction_targeted_retrieval,
    merged_literature_builder: Callable[
        ..., ContestDirectionMergedLiteratureArtifact
    ] = merge_contest_direction_literature,
    skill_router: Callable[..., ContestDirectSkillRoutingArtifact] = (
        route_contest_direct_plan_skills
    ),
    hypothesis_stage_runner: Callable[..., Any] | None = None,
    postpilot_stage_runner: Callable[..., Any] | None = None,
    preexperiment_runner: Callable[..., ContestPrimePreexperimentArtifact] = (
        run_contest_prime_preexperiment
    ),
    preexperiment_loader: Callable[..., ContestPrimePreexperimentArtifact] = (
        load_contest_prime_preexperiment
    ),
    plan_generator: Callable[..., ContestDirectPlanArtifact] = generate_contest_direct_plan,
    plan_revision_runner: Callable[..., ContestDirectPlanRevisionArtifact] = (
        revise_contest_direct_plan
    ),
    plan_materializer: Callable[..., ContestDirectPlanArtifacts] = (
        materialize_contest_direct_plan
    ),
    scientific_review_runner: Callable[..., ContestDirectPlanScientificReviewArtifact] = (
        review_contest_direct_plan_science
    ),
    arxiv_status_verifier: Callable[[AcademicPaper], AcademicPaper] | None = None,
) -> dict[str, Any]:
    """Run one evidence-first direction-to-reviewed-plan loop.

    Dependency callables are Python test seams, not CLI-selectable scientific
    backends.  Production execution uses the repository defaults above.
    """

    clean_direction = direction.strip()
    if not clean_direction:
        raise ContestDirectionResearchLoopError("specified direction must not be blank")
    if preexperiment_policy not in {"required", "if_supported"}:
        raise ContestDirectionResearchLoopError("unsupported preexperiment policy")
    if resume_existing and source_direction_delivery is not None:
        raise ContestDirectionResearchLoopError(
            "resume_existing cannot be combined with source_direction_delivery"
        )
    if source_direction_delivery is not None:
        raise ContestDirectionResearchLoopError(
            "two-stage literature protocol requires a fresh run; a legacy single-retrieval "
            "delivery cannot be relabelled as broad + focus + targeted evidence"
        )
    if (
        min(
            max_results_per_search,
            retrieval_max_tokens,
            skill_routing_max_tokens,
            brainstorm_max_tokens,
            feedback_max_tokens,
            objective_review_max_tokens,
            plan_max_tokens,
            scientific_review_max_tokens,
            timeout_seconds,
            thinking_budget,
            render_timeout_seconds,
        )
        < 1
    ):
        raise ContestDirectionResearchLoopError("budgets and timeouts must be positive")

    root = Path(output_dir).expanduser().resolve()
    if resume_existing:
        return _resume_existing_direction_research_loop(
            direction=clean_direction,
            root=root,
            skills_root=skills_root,
            config_path=config_path,
            env_path=env_path,
            feedback_max_tokens=feedback_max_tokens,
            objective_review_max_tokens=objective_review_max_tokens,
            plan_max_tokens=plan_max_tokens,
            scientific_review_max_tokens=scientific_review_max_tokens,
            timeout_seconds=timeout_seconds,
            thinking_budget=thinking_budget,
            render_timeout_seconds=render_timeout_seconds,
            context_vault_root=context_vault_root,
            context_capability_cache_dir=context_capability_cache_dir,
            context_completion=context_completion,
            dreaming_recall_enabled=dreaming_recall_enabled,
            max_results_per_search=max_results_per_search,
            retrieval_max_tokens=retrieval_max_tokens,
            skill_routing_max_tokens=skill_routing_max_tokens,
            brainstorm_max_tokens=brainstorm_max_tokens,
            literature_runner=literature_runner,
            literature_searchers=literature_searchers,
            focus_selection_runner=focus_selection_runner,
            targeted_retrieval_runner=targeted_retrieval_runner,
            merged_literature_builder=merged_literature_builder,
            skill_router=skill_router,
            hypothesis_stage_runner=hypothesis_stage_runner,
            preexperiment_runner=preexperiment_runner,
            plan_generator=plan_generator,
            arxiv_status_verifier=arxiv_status_verifier,
            postpilot_stage_runner=postpilot_stage_runner,
            plan_revision_runner=plan_revision_runner,
            plan_materializer=plan_materializer,
            scientific_review_runner=scientific_review_runner,
            preexperiment_loader=preexperiment_loader,
        )
    _prepare_empty_output(root)
    direction_payload: dict[str, Any] = {
        "schema_version": _INPUT_SCHEMA,
        "input_mode": "specified_direction",
        "direction": clean_direction,
        "literature_protocol": _LITERATURE_PROTOCOL,
        "requirements": list(_LOOP_REQUIREMENTS),
        "preexperiment_policy": preexperiment_policy,
        "source_accounting_protocol": _SOURCE_ACCOUNTING_PROTOCOL,
    }
    direction_payload["input_hash"] = canonical_model_hash(direction_payload)
    direction_id = f"direction-loop-{direction_payload['input_hash'][:20]}"
    direction_payload["direction_id"] = direction_id
    direction_input_path = root / "direction-input.json"
    _write_new_json(direction_input_path, direction_payload)
    context_runtime = ContestDirectionContextRuntime(
        direction_id=direction_id,
        output_dir=root / "context-memory",
        vault_root=context_vault_root,
        capability_cache_dir=context_capability_cache_dir,
        **({"completion": context_completion} if context_completion is not None else {}),
    )
    context_runtime.verify_official_capability(config_path=config_path)
    memory_bridge = _start_memory_bridge(
        root=root,
        direction_id=direction_id,
        vault_root=context_vault_root,
        context_runtime=context_runtime,
    )
    memory_stages: dict[str, dict[str, Any]] = {}
    memory_recalls: dict[str, dict[str, Any]] = {}
    shared_searchers, shared_status_verifier = _shared_literature_boundaries(
        literature_searchers=literature_searchers,
        arxiv_status_verifier=arxiv_status_verifier,
    )
    literature_state = _prepare_two_stage_literature(
        parent_direction=clean_direction,
        direction_input_hash=str(direction_payload["input_hash"]),
        root=root,
        context_runtime=context_runtime,
        memory_bridge=memory_bridge,
        memory_stages=memory_stages,
        config_path=config_path,
        env_path=env_path,
        timeout_seconds=timeout_seconds,
        max_results_per_search=max_results_per_search,
        retrieval_max_tokens=retrieval_max_tokens,
        shared_searchers=shared_searchers,
        shared_status_verifier=shared_status_verifier,
        literature_runner=literature_runner,
        focus_selection_runner=focus_selection_runner,
        targeted_retrieval_runner=targeted_retrieval_runner,
        merged_literature_builder=merged_literature_builder,
        resume=False,
    )
    source_accounting: dict[str, Any] | None = None
    literature = literature_state.merged
    literature_path = literature_state.merged_path
    planning_catalog = literature_state.planning_catalog
    planning_literature_context = literature_state.planning_context
    excluded_records = literature_state.excluded_records
    finalist_status_path = literature_state.finalist_status_path
    finalist_status_payload = literature_state.finalist_status_payload
    scientific_direction = literature_state.focus.focused_direction_cn

    skill_catalog, skill_bodies = discover_contest_method_skills(skills_root)
    routing_path = root / "skill-routing.json"
    literature_evidence_context = _skill_routing_two_stage_literature_evidence(
        literature,
        planning_catalog,
        queries=_focused_planning_queries(
            literature_state.focus,
            literature_state.targeted,
            role_queries=literature_state.effective_role_queries,
        ),
        priority_queries=_focused_planning_priority_queries(
            literature_state.focus,
            literature_state.targeted,
            role_queries=literature_state.effective_role_queries,
        ),
        priority_query_groups=_focused_planning_priority_query_groups(
            literature_state.focus,
            literature_state.targeted,
            role_queries=literature_state.effective_role_queries,
        ),
    )
    reasoning_literature_catalog = _catalog_subset_by_record_ids(
        planning_catalog,
        getattr(literature_evidence_context, "record_ids", ())
        or tuple(str(item.get("record_id") or "") for item in planning_catalog),
    )
    routing_kwargs: dict[str, Any] = {
        "question": scientific_direction,
        "requirements": _LOOP_REQUIREMENTS,
        "skill_catalog": skill_catalog,
        "config_path": config_path,
        "env_path": env_path,
        "output_path": routing_path,
        "timeout_seconds": timeout_seconds,
        "max_tokens": skill_routing_max_tokens,
    }
    # The evidence-aware router keeps its old three-message API compatible; the
    # optional fourth message is supplied only by this evidence-first loop.
    routing_kwargs["literature_evidence_context"] = literature_evidence_context
    routing_stage_input_hash = canonical_model_hash(
        {
            "direction_input_hash": direction_payload["input_hash"],
            "broad_literature_artifact_hash": literature_state.broad.artifact_hash,
            "focus_artifact_hash": literature_state.focus.artifact_hash,
            "targeted_literature_artifact_hash": literature_state.targeted.artifact_hash,
            "merged_literature_artifact_hash": literature.artifact_hash,
            "planning_literature_artifact_hash": literature_state.planning_lock_payload[
                "artifact_hash"
            ],
            "planning_catalog_hash": canonical_model_hash({"catalog": list(planning_catalog)}),
            "literature_evidence_context_hash": canonical_model_hash(
                literature_evidence_context.model_dump(mode="json")
            ),
            "skill_catalog": [item.model_dump(mode="json") for item in skill_catalog],
        }
    )
    with context_runtime.checkpointed_stage(
        "skill-routing",
        input_hash=routing_stage_input_hash,
        checkpoint_root=root,
    ) as context_completion:
        routing_kwargs["llm_call"] = context_completion
        routing = skill_router(**routing_kwargs)
    if (
        routing.schema_version != "contest-direct-skill-routing-v3"
        or routing.literature_retrieval_artifact_hash is not None
        or routing.literature_evidence_context != literature_evidence_context
        or routing.merged_literature_artifact_hash != literature.artifact_hash
        or routing.skill_bodies_visible_to_selector
    ):
        raise ContestDirectionResearchLoopError(
            "Skill routing is not strictly bound to the two-stage merged evidence"
        )
    selected_skills = _load_selected_skills(routing, skill_bodies)
    skill_manifest_path = root / "selected-method-skills.json"
    _write_selected_skill_manifest(
        skill_manifest_path,
        routing_path=routing_path,
        routing=routing,
        selected_skills=selected_skills,
        merged_literature=literature,
        planning_literature_artifact_hash=literature_state.planning_lock_payload["artifact_hash"],
    )
    record_completed_stage(
        root=root,
        ordinal=5,
        stage_name="skill-routing",
        stage_input_hash=routing_stage_input_hash,
        artifacts=(routing_path, skill_manifest_path),
    )
    memory_stages["skill-routing"] = _capture_stage_memory(
        memory_bridge,
        stage="skill-routing",
        artifact_paths=(routing_path, skill_manifest_path),
    )
    skill_contexts = tuple(_temporary_skill_context(item) for item in selected_skills)

    if hypothesis_stage_runner is None or postpilot_stage_runner is None:
        hypothesis_stage_runner, postpilot_stage_runner = _load_stage_runners()

    direction_ref = TemporaryAgentInputRef(
        artifact_id=literature_state.focus.selected_focus_id,
        source_ref=literature_state.focus_path.as_posix(),
        sha256=_sha256_file(literature_state.focus_path),
    )
    hypothesis_stage_input_hash = canonical_model_hash(
        {
            "direction_input_hash": direction_payload["input_hash"],
            "merged_literature_artifact_hash": literature.artifact_hash,
            "planning_catalog_hash": canonical_model_hash({"catalog": list(planning_catalog)}),
            "skill_routing_artifact_hash": routing.artifact_hash,
            "selected_skill_hashes": routing.selected_skill_hashes,
            "executable_adapters": [_ADAPTER_DESCRIPTOR],
        }
    )
    hypothesis_controller, hypothesis_capability = issue_stage_controller(
        lineage_id=direction_id,
        stage="direction-hypothesis-brainstorm",
        stage_attempt=1,
        controller_agent_id="contest-direction-research-loop-main-agent",
        stage_input_hash=hypothesis_stage_input_hash,
        max_parallel_agents=3,
    )
    hypothesis_root = root / "hypothesis-stage"
    with context_runtime.checkpointed_stage(
        "hypothesis-brainstorm",
        input_hash=hypothesis_stage_input_hash,
        checkpoint_root=root,
    ) as context_completion:
        hypotheses = hypothesis_stage_runner(
            direction=scientific_direction,
            requirements="\n".join(_LOOP_REQUIREMENTS),
            direction_ref=direction_ref,
            parent_task_id=f"{direction_id}-research-loop",
            controller=hypothesis_controller,
            capability=hypothesis_capability,
            output_dir=hypothesis_root,
            selected_skill_contexts=skill_contexts,
            retrieved_literature_catalog=reasoning_literature_catalog,
            executable_adapters=(_ADAPTER_DESCRIPTOR,),
            completion=context_completion,
            config_path=config_path,
            env_path=env_path,
            max_tokens_per_agent=brainstorm_max_tokens,
            timeout_seconds=timeout_seconds,
            thinking_budget=thinking_budget,
            temperature=0.35,
        )
    if hypothesis_capability.active:
        raise ContestDirectionResearchLoopError(
            "hypothesis brainstorm capability remained active after archival"
        )
    hypothesis_path = _artifact_path(hypothesis_root, hypotheses)
    record_completed_stage(
        root=root,
        ordinal=6,
        stage_name="hypothesis-brainstorm",
        stage_input_hash=hypothesis_stage_input_hash,
        artifacts=(hypothesis_path,),
    )
    memory_stages["hypothesis-brainstorm"] = _capture_stage_memory(
        memory_bridge,
        stage="hypothesis-brainstorm",
        artifact_paths=(hypothesis_root,),
    )
    selected_candidate = _select_executable_candidate(
        hypotheses,
        direction=scientific_direction,
        selected_skill_ids=routing.selected_skill_ids,
    )
    adapter_receipt_path = root / "preexperiment-adapter-selection.json"
    adapter_receipt = _adapter_selection_payload(
        direction=scientific_direction,
        routing=routing,
        literature=literature,
        hypotheses=hypotheses,
        selected_candidate=selected_candidate,
    )
    _write_new_json(adapter_receipt_path, adapter_receipt)
    if selected_candidate is None:
        return _finish_without_adapter(
            root=root,
            policy=preexperiment_policy,
            direction=scientific_direction,
            parent_direction=clean_direction,
            source_accounting=source_accounting,
            direction_input_path=direction_input_path,
            literature_path=literature_path,
            finalist_status_path=finalist_status_path,
            finalist_status_payload=finalist_status_payload,
            routing_path=routing_path,
            skill_manifest_path=skill_manifest_path,
            hypothesis_path=hypothesis_path,
            adapter_receipt_path=adapter_receipt_path,
            routing=routing,
            literature=literature,
            literature_state=literature_state,
            hypotheses=hypotheses,
            memory_summary=_memory_delivery_summary(
                stages=memory_stages,
                recalls=memory_recalls,
            ),
        )

    provisional_path = root / "internal" / "provisional-pilot-base-plan.json"
    provisional_stage_input_hash = canonical_model_hash(
        {
            "direction_input_hash": direction_payload["input_hash"],
            "merged_literature_artifact_hash": literature.artifact_hash,
            "skill_routing_artifact_hash": routing.artifact_hash,
            "hypothesis_artifact_hash": _artifact_hash(hypotheses),
            "selected_candidate": selected_candidate,
        }
    )
    with context_runtime.checkpointed_stage(
        "provisional-plan",
        input_hash=provisional_stage_input_hash,
        checkpoint_root=root,
    ) as context_completion:
        provisional = plan_generator(
            scientific_problem=scientific_direction,
            literature_context=planning_literature_context,
            preexperiment_context=None,
            method_skills=tuple(item["content"] for item in selected_skills),
            temporary_agent_context={
                "context_kind": "selected_executable_candidate_before_pilot",
                "candidate": selected_candidate,
                "boundary_zh": (
                    "这是供真实pilot与后续证据修订使用的内部临时基线，不是最终研究计划，"
                    "尚无预实验结果，不得虚构观察。"
                ),
            },
            config_path=config_path,
            env_path=env_path,
            output_path=provisional_path,
            timeout_seconds=timeout_seconds,
            max_tokens=plan_max_tokens,
            thinking_mode="disabled",
            thinking_budget=None,
            temperature=0.2,
            llm_call=context_completion,
        )
    if provisional.generation_calls != 1 or provisional.preexperiment_context_status != (
        "not_provided"
    ):
        raise ContestDirectionResearchLoopError(
            "internal provisional plan must be a single no-preexperiment model call"
        )
    _verify_plan_references(
        provisional,
        literature_context=planning_literature_context,
        minimum_references=MIN_RESEARCH_PLAN_REFERENCES,
        maximum_references=MAX_RESEARCH_PLAN_REFERENCES,
    )
    record_completed_stage(
        root=root,
        ordinal=7,
        stage_name="provisional-plan",
        stage_input_hash=provisional_stage_input_hash,
        artifacts=(provisional_path,),
    )
    memory_stages["provisional-plan"] = _capture_stage_memory(
        memory_bridge,
        stage="provisional-plan",
        artifact_paths=(provisional_path,),
    )

    pilot_brief_path = root / "preexperiment" / "pilot-brief.json"
    pilot_brief = _pilot_brief_payload(
        direction=scientific_direction,
        direction_input_hash=direction_payload["input_hash"],
        literature=literature,
        routing=routing,
        hypotheses=hypotheses,
        selected_candidate=selected_candidate,
        provisional_plan=provisional,
    )
    _write_new_json(pilot_brief_path, pilot_brief)
    pilot_root = root / "preexperiment" / _ADAPTER_ID
    generated_pilot = preexperiment_runner(
        output_dir=pilot_root,
        source_plan_path=pilot_brief_path,
    )
    pilot_path = pilot_root / "prime-preexperiment.json"
    pilot = preexperiment_loader(pilot_path, verify_files=True)
    _verify_prime_pilot(
        pilot,
        generated=generated_pilot,
        source_snapshot_sha256=_sha256_file(pilot_brief_path),
    )
    final_reference_catalog = build_postpilot_reference_catalog(
        planning_literature_context,
        getattr(pilot, "references", ()),
    )
    pilot_stage_input_hash = canonical_model_hash(
        {
            "pilot_brief_sha256": _sha256_file(pilot_brief_path),
            "adapter_id": _ADAPTER_ID,
        }
    )
    record_completed_stage(
        root=root,
        ordinal=8,
        stage_name="real-pilot",
        stage_input_hash=pilot_stage_input_hash,
        artifacts=(pilot_brief_path, pilot_path),
    )
    memory_stages["real-pilot"] = _capture_stage_memory(
        memory_bridge,
        stage="real-pilot",
        artifact_paths=(pilot_brief_path, pilot_root),
    )

    postpilot_memory_context, memory_recalls["postpilot-objective-review"] = _recall_stage_memory(
        memory_bridge,
        consumer_stage="postpilot-objective-review",
        source_stages=(
            "broad-literature-query",
            "focus-selection",
            "targeted-literature-query",
            "planning-literature-lock",
            "skill-routing",
            "hypothesis-brainstorm",
            "provisional-plan",
            "real-pilot",
        ),
        requested=dreaming_recall_enabled,
    )
    postpilot_stage_input_hash = _memory_bound_input_hash(
        {
            "direction_input_hash": direction_payload["input_hash"],
            "hypothesis_artifact_hash": _artifact_hash(hypotheses),
            "selected_candidate_id": selected_candidate.get("candidate_id"),
            "pilot_brief_sha256": _sha256_file(pilot_brief_path),
            "preexperiment_artifact_hash": pilot.artifact_hash,
            "skill_routing_artifact_hash": routing.artifact_hash,
            "merged_literature_artifact_hash": literature.artifact_hash,
        },
        postpilot_memory_context,
    )
    postpilot_controller, postpilot_capability = issue_stage_controller(
        lineage_id=direction_id,
        stage="direction-postpilot-objective-review",
        stage_attempt=1,
        controller_agent_id="contest-direction-research-loop-main-agent",
        stage_input_hash=postpilot_stage_input_hash,
        max_parallel_agents=1,
    )
    postpilot_root = root / "postpilot-stage"
    with context_runtime.checkpointed_stage(
        "postpilot-objective-review",
        input_hash=postpilot_stage_input_hash,
        checkpoint_root=root,
    ) as context_completion:
        postpilot = postpilot_stage_runner(
            direction=scientific_direction,
            requirements="\n".join(_LOOP_REQUIREMENTS),
            direction_ref=direction_ref,
            parent_task_id=f"{direction_id}-research-loop",
            controller=postpilot_controller,
            capability=postpilot_capability,
            output_dir=postpilot_root,
            brainstorm_artifact_path=hypothesis_path,
            pilot_brief_path=pilot_brief_path,
            preexperiment_artifact_path=pilot_path,
            selected_skill_contexts=skill_contexts,
            retrieved_literature_catalog=reasoning_literature_catalog,
            derived_memory_context=postpilot_memory_context,
            completion=context_completion,
            config_path=config_path,
            env_path=env_path,
            max_tokens=max(feedback_max_tokens, objective_review_max_tokens),
            timeout_seconds=timeout_seconds,
            thinking_budget=thinking_budget,
            temperature=0.2,
        )
    if postpilot_capability.active:
        raise ContestDirectionResearchLoopError(
            "postpilot objective-review capability remained active after archival"
        )
    postpilot_path = _artifact_path(postpilot_root, postpilot)
    record_completed_stage(
        root=root,
        ordinal=9,
        stage_name="postpilot-objective-review",
        stage_input_hash=postpilot_stage_input_hash,
        artifacts=(postpilot_path, pilot_path),
    )
    memory_stages["postpilot-objective-review"] = _capture_stage_memory(
        memory_bridge,
        stage="postpilot-objective-review",
        artifact_paths=(postpilot_root,),
    )
    postpilot_context = _postpilot_plan_context(postpilot)

    plan_path = root / "system-authored-revised-research-plan.json"
    revision_requirements = (
        *_LOOP_REQUIREMENTS,
        *_REVISION_RESULT_REQUIREMENTS,
        "内部 provisional 只作证据修订基线，不得当作最终计划或已完成研究。",
        "以下是预实验后的独立目标评审上下文（模型判断，不是额外实验事实）："
        + json.dumps(postpilot_context, ensure_ascii=False, sort_keys=True),
    )
    revision_memory_context, memory_recalls["final-plan-revision"] = _recall_stage_memory(
        memory_bridge,
        consumer_stage="final-plan-revision",
        source_stages=(
            "broad-literature-query",
            "focus-selection",
            "targeted-literature-query",
            "planning-literature-lock",
            "skill-routing",
            "hypothesis-brainstorm",
            "provisional-plan",
            "real-pilot",
            "postpilot-objective-review",
        ),
        requested=dreaming_recall_enabled,
    )
    revision_stage_input_hash = _memory_bound_input_hash(
        {
            "provisional_plan_artifact_hash": provisional.artifact_hash,
            "preexperiment_artifact_hash": pilot.artifact_hash,
            "postpilot_objective_artifact_hash": _artifact_hash(postpilot),
            "reference_catalog": list(final_reference_catalog),
            "selected_skill_hashes": routing.selected_skill_hashes,
        },
        revision_memory_context,
    )
    with context_runtime.checkpointed_stage(
        "final-plan-revision",
        input_hash=revision_stage_input_hash,
        checkpoint_root=root,
    ) as context_completion:
        plan = plan_revision_runner(
            original_plan=provisional,
            scientific_problem=scientific_direction,
            requirements=revision_requirements,
            selected_skill_contexts=tuple(
                {"skill_id": item["skill_id"], "content": item["content"]}
                for item in selected_skills
            ),
            reference_catalog=final_reference_catalog,
            preexperiment_artifact=pilot_path,
            preexperiment_metrics=None,
            preexperiment_root=pilot_root,
            derived_memory_context=revision_memory_context,
            output_dir=root / "revision",
            output_path=plan_path,
            config_path=config_path,
            env_path=env_path,
            timeout_seconds=timeout_seconds,
            max_tokens=plan_max_tokens,
            temperature=0.2,
            llm_call=context_completion,
        )
    if plan.generation_calls != 1:
        raise ContestDirectionResearchLoopError(
            "final detailed plan must use exactly one evidence-bound revision call"
        )
    _verify_plan_references(
        plan,
        literature_context=final_reference_catalog,
        minimum_references=MIN_RESEARCH_PLAN_REFERENCES,
        maximum_references=MAX_RESEARCH_PLAN_REFERENCES,
    )
    if "预实验" not in plan.plan.results:
        raise ContestDirectionResearchLoopError(
            "detailed plan did not distinguish the executed preexperiment"
        )
    record_completed_stage(
        root=root,
        ordinal=10,
        stage_name="final-plan-revision",
        stage_input_hash=revision_stage_input_hash,
        artifacts=(plan_path,),
    )
    memory_stages["final-plan-revision"] = _capture_stage_memory(
        memory_bridge,
        stage="final-plan-revision",
        artifact_paths=(root / "revision", plan_path),
    )

    render_payload = plan.flat_payload()
    embedded_evidence = build_contest_plan_embedded_evidence(
        pilot,
        artifact_path=pilot_path,
        preexperiment_root=pilot_root,
    )
    if embedded_evidence is not None:
        render_payload["embedded_evidence"] = embedded_evidence.payload
    render_payload.update(
        {
            "document_type": "含真实探索性预实验结果的科学假设与研究计划",
            "status": "generated_after_verified_preexperiment_and_objective_review",
            "specified_direction": clean_direction,
            "focused_direction": scientific_direction,
            "generation": {
                "provider": plan.provider,
                "model_name": plan.model_name,
                "generation_calls": plan.generation_calls,
                "input_hash": plan.input_hash,
                "model_response_hash": plan.model_response_hash,
                "artifact_hash": plan.artifact_hash,
                "provisional_plan_artifact_hash": provisional.artifact_hash,
                "final_revision_id": plan.revision_id,
            },
            "preexperiment": {
                "adapter_id": _ADAPTER_ID,
                "run_id": pilot.run_id,
                "artifact_hash": pilot.artifact_hash,
                "metrics_sha256": pilot.metrics_sha256,
                "manifest_sha256": pilot.manifest_sha256,
                "study_phase": pilot.study_phase,
                "formal_experiment_executed": False,
                "mathematical_proof_claimed": False,
            },
            "postpilot_objective": {
                "artifact_path": postpilot_path.as_posix(),
                "artifact_hash": _artifact_hash(postpilot),
            },
        }
    )
    rendered = plan_materializer(
        payload=render_payload,
        output_dir=root / "plan",
        evidence_bindings=(
            embedded_evidence.manifest_bindings if embedded_evidence is not None else ()
        ),
        overwrite=False,
        timeout_seconds=render_timeout_seconds,
    )
    page_count, page_count_method = _verify_rendered_pdf(rendered)
    render_stage_input_hash = canonical_model_hash(
        {
            "final_plan_artifact_hash": plan.artifact_hash,
            "rendered_source_payload_sha256": rendered.source_payload_sha256,
        }
    )
    record_completed_stage(
        root=root,
        ordinal=11,
        stage_name="render-plan",
        stage_input_hash=render_stage_input_hash,
        artifacts=(
            rendered.json_path,
            rendered.markdown_path,
            rendered.tex_path,
            rendered.pdf_path,
            rendered.manifest_path,
            *((rendered.source_path,) if rendered.source_path is not None else ()),
        ),
    )
    memory_stages["render-plan"] = _capture_stage_memory(
        memory_bridge,
        stage="render-plan",
        artifact_paths=(root / "plan",),
    )

    review_root = root / "independent-scientific-review"
    review_memory_context, memory_recalls["independent-scientific-review"] = _recall_stage_memory(
        memory_bridge,
        consumer_stage="independent-scientific-review",
        source_stages=(
            "broad-literature-query",
            "focus-selection",
            "targeted-literature-query",
            "planning-literature-lock",
            "skill-routing",
            "hypothesis-brainstorm",
            "provisional-plan",
            "real-pilot",
            "postpilot-objective-review",
            "final-plan-revision",
            "render-plan",
        ),
        requested=dreaming_recall_enabled,
    )
    scientific_review_stage_input_hash = _memory_bound_input_hash(
        {
            "final_plan_artifact_hash": plan.artifact_hash,
            "rendered_source_payload_sha256": rendered.source_payload_sha256,
            "preexperiment_artifact_hash": pilot.artifact_hash,
            "reference_catalog": list(final_reference_catalog),
            "selected_skill_hashes": routing.selected_skill_hashes,
        },
        review_memory_context,
    )
    with context_runtime.checkpointed_stage(
        "independent-scientific-review",
        input_hash=scientific_review_stage_input_hash,
        checkpoint_root=root,
    ) as context_completion:
        final_review = scientific_review_runner(
            final_plan=rendered.json_path,
            preexperiment_artifact=pilot_path,
            reference_catalog=final_reference_catalog,
            selected_skill_contexts=tuple(
                {
                    "name": item["skill_id"],
                    "content": item["content"],
                }
                for item in selected_skills
            ),
            preexperiment_metrics=None,
            preexperiment_root=pilot_root,
            derived_memory_context=review_memory_context,
            output_dir=review_root,
            config_path=config_path,
            env_path=env_path,
            timeout_seconds=timeout_seconds,
            max_tokens=scientific_review_max_tokens,
            temperature=0.2,
            require_exact_reference_catalog=True,
            llm_call=context_completion,
        )
    if final_review.generation_calls != 1 or final_review.plan_rewrite_performed:
        raise ContestDirectionResearchLoopError(
            "final review must be one independent non-rewriting model call"
        )
    scientific_review_path = review_root / "system-plan-scientific-review.json"
    record_completed_stage(
        root=root,
        ordinal=12,
        stage_name="independent-scientific-review",
        stage_input_hash=scientific_review_stage_input_hash,
        artifacts=(scientific_review_path,),
    )
    memory_stages["independent-scientific-review"] = _capture_stage_memory(
        memory_bridge,
        stage="independent-scientific-review",
        artifact_paths=(review_root,),
    )
    _enforce_scientific_review_delivery_gate(
        root=root,
        direction=clean_direction,
        focused_direction=literature_state.focus.focused_direction_cn,
        final_review=final_review,
        review_path=scientific_review_path,
    )

    report = _completed_report(
        root=root,
        direction=clean_direction,
        literature_state=literature_state,
        source_accounting=source_accounting,
        direction_input_path=direction_input_path,
        literature=literature,
        finalist_status_path=finalist_status_path,
        finalist_status_payload=finalist_status_payload,
        excluded_records=excluded_records,
        routing=routing,
        routing_path=routing_path,
        skill_manifest_path=skill_manifest_path,
        hypotheses=hypotheses,
        hypothesis_path=hypothesis_path,
        adapter_receipt_path=adapter_receipt_path,
        pilot_brief_path=pilot_brief_path,
        pilot=pilot,
        pilot_path=pilot_path,
        postpilot=postpilot,
        postpilot_path=postpilot_path,
        provisional=provisional,
        provisional_path=provisional_path,
        plan=plan,
        plan_path=plan_path,
        rendered=rendered,
        page_count=page_count,
        page_count_method=page_count_method,
        final_review=final_review,
        review_root=review_root,
    )
    report["memory"] = _memory_delivery_summary(
        stages=memory_stages,
        recalls=memory_recalls,
    )
    report_path = root / "delivery-report.json"
    _write_new_json(report_path, report)
    returned = dict(report)
    returned["delivery_report_path"] = report_path.as_posix()
    returned["delivery_report_sha256"] = _sha256_file(report_path)
    return returned


def _load_stage_runners() -> tuple[Callable[..., Any], Callable[..., Any]]:
    """Import the two stage siblings lazily so unit seams remain lightweight."""

    from autoresearch.competition.contest_direction_hypothesis_stage import (
        run_contest_direction_hypothesis_brainstorm,
        run_contest_postpilot_objective_review,
    )

    return (
        run_contest_direction_hypothesis_brainstorm,
        run_contest_postpilot_objective_review,
    )


def _shared_literature_boundaries(
    *,
    literature_searchers: Mapping[str, Callable[..., Sequence[AcademicPaper]]] | None,
    arxiv_status_verifier: Callable[[AcademicPaper], AcademicPaper] | None,
) -> tuple[
    dict[str, Callable[..., Sequence[AcademicPaper]]],
    Callable[[AcademicPaper], AcademicPaper] | None,
]:
    """Create each live client once so both searches and finalist checks share limiters."""

    if literature_searchers is None:
        arxiv = ArxivClient()
        openalex = OpenAlexClient()
        searchers: dict[str, Callable[..., Sequence[AcademicPaper]]] = {
            "arxiv": arxiv.search,
            "openalex": openalex.search,
        }
        if semantic_scholar_enabled():
            semantic_scholar = SemanticScholarClient()
            searchers["semantic_scholar"] = semantic_scholar.search
        return searchers, arxiv_status_verifier or arxiv.verify_status

    searchers = dict(literature_searchers)
    if not searchers:
        raise ContestDirectionResearchLoopError("literature searchers must not be empty")
    if arxiv_status_verifier is not None:
        return searchers, arxiv_status_verifier
    arxiv_searcher = searchers.get("arxiv")
    owner = getattr(arxiv_searcher, "__self__", None)
    return searchers, (owner.verify_status if isinstance(owner, ArxivClient) else None)


def _prepare_two_stage_literature(
    *,
    parent_direction: str,
    direction_input_hash: str,
    root: Path,
    context_runtime: ContestDirectionContextRuntime,
    memory_bridge: ContestDirectionMemoryBridge | None,
    memory_stages: dict[str, dict[str, Any]],
    config_path: Path | str,
    env_path: Path | str,
    timeout_seconds: int,
    max_results_per_search: int,
    retrieval_max_tokens: int,
    shared_searchers: Mapping[str, Callable[..., Sequence[AcademicPaper]]],
    shared_status_verifier: Callable[[AcademicPaper], AcademicPaper] | None,
    literature_runner: Callable[..., ContestDirectionLiteratureArtifact],
    focus_selection_runner: Callable[..., ContestDirectionFocusArtifact],
    targeted_retrieval_runner: Callable[..., ContestDirectionTargetedRetrievalBinding],
    merged_literature_builder: Callable[..., ContestDirectionMergedLiteratureArtifact],
    resume: bool,
) -> _TwoStageLiteratureState:
    """Run or strictly resume the two distinct searches and program bibliography lock."""

    literature_root = root / "literature"
    broad_root = literature_root / "broad"
    refinement_root = literature_root / "refinement"
    broad_path = broad_root / "direction-literature.json"
    focus_path = refinement_root / "direction-focus.json"
    targeted_path = refinement_root / "targeted-literature.json"
    targeted_binding_path = refinement_root / "direction-targeted-retrieval.json"
    merged_path = literature_root / "merged-literature.json"
    finalist_status_path = literature_root / "finalist-status-verification.json"
    r1_planning_coverage_path = literature_root / "planning-literature-coverage-r1.json"
    r2_planning_coverage_path = literature_root / "planning-literature-coverage-r2.json"
    planning_coverage_path = literature_root / "planning-literature-coverage.json"
    planning_lock_path = literature_root / "planning-literature.json"

    broad_stage_input_hash = canonical_model_hash(
        {
            "literature_protocol": _LITERATURE_PROTOCOL,
            "direction_input_hash": direction_input_hash,
            "direction": parent_direction,
            "requirements": list(_LOOP_REQUIREMENTS),
            "selected_method_skills": {},
            "max_results_per_search": max_results_per_search,
        }
    )
    if resume and broad_path.is_file():
        broad = ContestDirectionLiteratureArtifact.model_validate_json(
            broad_path.read_text(encoding="utf-8")
        )
    else:
        with context_runtime.checkpointed_stage(
            "broad-literature-query",
            input_hash=broad_stage_input_hash,
            checkpoint_root=root,
        ) as completion:
            broad = literature_runner(
                direction=parent_direction,
                searchers=replayable_literature_searchers(
                    root=broad_root,
                    searchers=shared_searchers,
                ),
                requirements=_LOOP_REQUIREMENTS,
                selected_method_skills={},
                config_path=config_path,
                env_path=env_path,
                output_path=broad_path,
                timeout_seconds=timeout_seconds,
                max_tokens=retrieval_max_tokens,
                max_results_per_search=max_results_per_search,
                llm_call=completion,
            )
    if broad.direction != parent_direction or broad.method_skills:
        raise ContestDirectionResearchLoopError(
            "broad retrieval must bind the parent direction and receive no Skill content"
        )
    record_completed_stage(
        root=root,
        ordinal=1,
        stage_name="broad-literature-query",
        stage_input_hash=broad_stage_input_hash,
        artifacts=(broad_path,),
    )
    memory_stages["broad-literature-query"] = _capture_stage_memory(
        memory_bridge,
        stage="broad-literature-query",
        artifact_paths=(broad_path,),
    )

    focus_stage_input_hash = canonical_model_hash(
        {
            "literature_protocol": _LITERATURE_PROTOCOL,
            "direction_input_hash": direction_input_hash,
            "broad_literature_artifact_hash": broad.artifact_hash,
            "broad_literature_catalog_hash": broad.literature_catalog_hash,
            "requirements": list(_LOOP_REQUIREMENTS),
            "executable_adapter_capabilities": [_ADAPTER_DESCRIPTOR],
            "shortlist_publication_status_verification_requested": (
                shared_status_verifier is not None
            ),
        }
    )
    if resume and focus_path.is_file():
        focus = load_contest_direction_focus_selection(
            focus_path,
            broad_literature=broad,
            executable_adapter_capabilities=(_ADAPTER_DESCRIPTOR,),
            require_publication_status_verification=(shared_status_verifier is not None),
        )
    else:
        with context_runtime.checkpointed_stage(
            "focus-selection",
            input_hash=focus_stage_input_hash,
            checkpoint_root=root,
        ) as completion:
            focus = focus_selection_runner(
                direction=parent_direction,
                broad_literature=broad,
                output_dir=refinement_root,
                requirements=_LOOP_REQUIREMENTS,
                executable_adapter_capabilities=(_ADAPTER_DESCRIPTOR,),
                publication_status_verifier=(
                    replayable_paper_verifier(
                        root=root,
                        verifier_name="arxiv-focus-status",
                        verifier=shared_status_verifier,
                    )
                    if shared_status_verifier is not None
                    else None
                ),
                config_path=config_path,
                env_path=env_path,
                timeout_seconds=timeout_seconds,
                brainstorm_max_tokens=max(1_600, retrieval_max_tokens * 4),
                selection_max_tokens=max(800, retrieval_max_tokens * 2),
                completion=completion,
            )
    focus_artifacts = _required_existing_paths(
        focus_path,
        refinement_root / "direction-focus-brainstorm-response.json",
        refinement_root / "direction-focus-selection-response.json",
    )
    record_completed_stage(
        root=root,
        ordinal=2,
        stage_name="focus-selection",
        stage_input_hash=focus_stage_input_hash,
        artifacts=focus_artifacts,
    )
    memory_stages["focus-selection"] = _capture_stage_memory(
        memory_bridge,
        stage="focus-selection",
        artifact_paths=focus_artifacts,
    )

    targeted_stage_input_hash = canonical_model_hash(
        {
            "literature_protocol": _LITERATURE_PROTOCOL,
            "focus_artifact_hash": focus.artifact_hash,
            "selected_focus_id": focus.selected_focus_id,
            "focused_direction_cn": focus.focused_direction_cn,
            "max_results_per_search": max_results_per_search,
        }
    )
    if resume and targeted_binding_path.is_file():
        targeted_binding = load_contest_direction_targeted_retrieval(
            targeted_binding_path,
            focus=focus,
        )
    else:
        with context_runtime.checkpointed_stage(
            "targeted-literature-query",
            input_hash=targeted_stage_input_hash,
            checkpoint_root=root,
        ) as completion:
            targeted_binding = targeted_retrieval_runner(
                focus=focus,
                output_dir=refinement_root,
                searchers=shared_searchers,
                config_path=config_path,
                env_path=env_path,
                timeout_seconds=timeout_seconds,
                max_tokens=max(1_200, retrieval_max_tokens),
                max_results_per_search=max_results_per_search,
                completion=completion,
            )
    targeted = ContestDirectionLiteratureArtifact.model_validate_json(
        targeted_path.read_text(encoding="utf-8")
    )
    targeted_artifacts = _required_existing_paths(
        targeted_path,
        targeted_binding_path,
        refinement_root / "targeted-query-response.json",
    )
    record_completed_stage(
        root=root,
        ordinal=3,
        stage_name="targeted-literature-query",
        stage_input_hash=targeted_stage_input_hash,
        artifacts=targeted_artifacts,
    )
    memory_stages["targeted-literature-query"] = _capture_stage_memory(
        memory_bridge,
        stage="targeted-literature-query",
        artifact_paths=targeted_artifacts,
    )

    if resume and merged_path.is_file():
        base_merged = load_contest_direction_merged_literature(
            merged_path,
            broad_literature_path=broad_path,
            focus_path=focus_path,
            targeted_binding_path=targeted_binding_path,
            targeted_literature_path=targeted_path,
            executable_adapter_capabilities=(_ADAPTER_DESCRIPTOR,),
        )
    else:
        base_merged = merged_literature_builder(
            broad_literature=broad,
            focus=focus,
            targeted_binding=targeted_binding,
            targeted_literature=targeted,
            output_path=merged_path,
        )
    base_catalog, base_context, base_excluded_records = _eligible_merged_literature(
        base_merged,
        targeted_literature=targeted,
    )
    r1_role_queries = _planning_coverage_role_queries(targeted)
    r1_coverage = _coverage_receipt(
        base_catalog,
        base_context,
        role_queries=r1_role_queries,
    )
    _persist_exact_coverage_receipt(
        r1_planning_coverage_path,
        r1_coverage,
    )
    gap_state: _BoundedGapRepairState | None = None
    r2_coverage: PlanningLiteratureCoverageReceipt | None = None
    if r1_coverage.passed:
        merged: _PlanningLiteratureArtifact = base_merged
        effective_merged_path = merged_path
        retrieval_catalog = base_catalog
        literature_context = base_context
        excluded_records = base_excluded_records
        role_queries = r1_role_queries
    else:
        gap_state = _prepare_bounded_gap_repair(
            root=root,
            base_merged=base_merged,
            base_merged_path=merged_path,
            focus=focus,
            r1_coverage=r1_coverage,
            context_runtime=context_runtime,
            config_path=config_path,
            env_path=env_path,
            timeout_seconds=timeout_seconds,
            retrieval_max_tokens=retrieval_max_tokens,
            max_results_per_search=max_results_per_search,
            shared_searchers=shared_searchers,
        )
        merged = gap_state.layered
        effective_merged_path = gap_state.layered_path
        role_queries = gap_state.projection.r2_role_queries
        retrieval_catalog, literature_context, excluded_records = _eligible_merged_literature(
            merged,
            targeted_literature=targeted,
            base_merged_literature=base_merged,
        )
        r2_coverage = _coverage_receipt(
            retrieval_catalog,
            literature_context,
            role_queries=role_queries,
            method_focus_basis_queries=r1_coverage.method_focus_basis_queries,
        )
        _persist_exact_coverage_receipt(r2_planning_coverage_path, r2_coverage)
        if not r2_coverage.passed:
            _persist_exact_coverage_receipt(planning_coverage_path, r2_coverage)
            detail = ", ".join(r2_coverage.failure_reasons) or "unknown coverage failure"
            raise ContestDirectionResearchLoopError(
                f"planning literature coverage failed after the one allowed repair: {detail}"
            )
    if resume and finalist_status_path.is_file():
        finalist_status_payload = _load_finalist_status_verification(finalist_status_path)
        replay_catalog, replay_context = _apply_finalist_status_verification(
            retrieval_catalog,
            literature_context,
            finalist_status_payload,
        )
        planning_coverage = _coverage_select(
            replay_catalog,
            replay_context,
            role_queries=role_queries,
            method_focus_basis_queries=r1_coverage.method_focus_basis_queries,
        )
        planning_catalog, planning_context = _coverage_selected_subset(
            replay_catalog,
            replay_context,
            planning_coverage,
        )
        selection_catalog = replay_catalog
    else:
        verifier = (
            replayable_paper_verifier(
                root=root,
                verifier_name="arxiv-finalist-status",
                verifier=shared_status_verifier,
            )
            if shared_status_verifier is not None
            else None
        )
        (
            planning_catalog,
            planning_context,
            planning_coverage,
            status_records,
        ) = _select_planning_literature_with_coverage_and_status(
            retrieval_catalog,
            literature_context,
            role_queries=role_queries,
            method_focus_basis_queries=r1_coverage.method_focus_basis_queries,
            arxiv_status_verifier=verifier,
        )
        finalist_status_payload = _write_finalist_status_verification(
            finalist_status_path,
            records=status_records,
        )
        replay_catalog, replay_context = _apply_finalist_status_verification(
            retrieval_catalog,
            literature_context,
            finalist_status_payload,
        )
        replay_coverage = _coverage_select(
            replay_catalog,
            replay_context,
            role_queries=role_queries,
            method_focus_basis_queries=r1_coverage.method_focus_basis_queries,
        )
        replay_planning_catalog, replay_planning_context = _coverage_selected_subset(
            replay_catalog,
            replay_context,
            replay_coverage,
        )
        if (
            replay_planning_catalog != planning_catalog
            or replay_planning_context != planning_context
        ):
            raise ContestDirectionResearchLoopError(
                "fresh finalist status receipt does not replay the final planning selection"
            )
        planning_catalog = replay_planning_catalog
        planning_context = replay_planning_context
        planning_coverage = replay_coverage
        selection_catalog = replay_catalog
    if len(planning_catalog) < MIN_RESEARCH_PLAN_REFERENCES:
        raise ContestDirectionResearchLoopError(
            "two-stage retrieval did not yield the required 5–10 complete references"
        )
    if _doi_verification_enabled():
        _record_finalist_doi_verification(
            literature_root / "finalist-doi-verification.json",
            planning_catalog,
            resume=resume,
        )
    _persist_exact_coverage_receipt(planning_coverage_path, planning_coverage)
    planning_lock_payload = _load_or_write_planning_literature_lock(
        planning_lock_path,
        merged=merged,
        base_merged=base_merged,
        focus=focus,
        targeted_binding=targeted_binding,
        candidate_catalog=selection_catalog,
        planning_catalog=planning_catalog,
        planning_context=planning_context,
        finalist_status_payload=finalist_status_payload,
        r1_planning_coverage=r1_coverage,
        r2_planning_coverage=r2_coverage,
        planning_coverage=planning_coverage,
        gap_state=gap_state,
        require_existing=resume and planning_lock_path.is_file(),
    )
    planning_stage_input_hash = canonical_model_hash(
        {
            "merged_literature_artifact_hash": merged.artifact_hash,
            "merged_literature_catalog_hash": merged.merged_catalog_hash,
            "finalist_status_artifact_hash": finalist_status_payload["artifact_hash"],
            "planning_coverage_receipt_hash": planning_coverage.receipt_hash,
            "planning_literature_artifact_hash": planning_lock_payload["artifact_hash"],
        }
    )
    gap_artifacts = (
        (
            gap_state.diagnosis_path,
            gap_state.response_path,
            gap_state.projection_path,
            gap_state.retrieval_path,
            gap_state.layered_path,
            r2_planning_coverage_path,
        )
        if gap_state is not None
        else ()
    )
    planning_artifacts = (
        merged_path,
        r1_planning_coverage_path,
        *gap_artifacts,
        finalist_status_path,
        planning_coverage_path,
        planning_lock_path,
    )
    record_completed_stage(
        root=root,
        ordinal=4,
        stage_name="planning-literature-lock",
        stage_input_hash=planning_stage_input_hash,
        artifacts=planning_artifacts,
    )
    memory_stages["planning-literature-lock"] = _capture_stage_memory(
        memory_bridge,
        stage="planning-literature-lock",
        artifact_paths=planning_artifacts,
    )
    return _TwoStageLiteratureState(
        broad=broad,
        broad_path=broad_path,
        focus=focus,
        focus_path=focus_path,
        targeted_binding=targeted_binding,
        targeted_binding_path=targeted_binding_path,
        targeted=targeted,
        targeted_path=targeted_path,
        merged=merged,
        merged_path=effective_merged_path,
        planning_catalog=tuple(dict(item) for item in planning_catalog),
        planning_context=tuple(planning_context),
        excluded_records=excluded_records,
        finalist_status_path=finalist_status_path,
        finalist_status_payload=finalist_status_payload,
        planning_coverage_path=planning_coverage_path,
        planning_coverage=planning_coverage,
        planning_lock_path=planning_lock_path,
        planning_lock_payload=planning_lock_payload,
        base_merged=base_merged,
        base_merged_path=merged_path,
        effective_role_queries=tuple(role_queries),
        r1_planning_coverage_path=r1_planning_coverage_path,
        r1_planning_coverage=r1_coverage,
        r2_planning_coverage_path=(r2_planning_coverage_path if gap_state is not None else None),
        r2_planning_coverage=r2_coverage,
        gap_diagnosis_path=(gap_state.diagnosis_path if gap_state is not None else None),
        gap_diagnosis=(gap_state.diagnosis if gap_state is not None else None),
        gap_response_path=(gap_state.response_path if gap_state is not None else None),
        gap_response=(gap_state.response if gap_state is not None else None),
        gap_projection_path=(gap_state.projection_path if gap_state is not None else None),
        gap_projection=(gap_state.projection if gap_state is not None else None),
        gap_retrieval_path=(gap_state.retrieval_path if gap_state is not None else None),
        gap_retrieval=(gap_state.retrieval if gap_state is not None else None),
    )


def _required_existing_paths(*paths: Path) -> tuple[Path, ...]:
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise ContestDirectionResearchLoopError(
            "two-stage literature runner omitted required artifact(s): "
            + ", ".join(path.as_posix() for path in missing)
        )
    return tuple(paths)


def _prepare_bounded_gap_repair(
    *,
    root: Path,
    base_merged: ContestDirectionMergedLiteratureArtifact,
    base_merged_path: Path,
    focus: ContestDirectionFocusArtifact,
    r1_coverage: PlanningLiteratureCoverageReceipt,
    context_runtime: ContestDirectionContextRuntime,
    config_path: Path | str,
    env_path: Path | str,
    timeout_seconds: int,
    retrieval_max_tokens: int,
    max_results_per_search: int,
    shared_searchers: Mapping[str, Callable[..., Sequence[AcademicPaper]]],
) -> _BoundedGapRepairState:
    """Run or replay the one allowed evidence-bound coverage-gap repair round."""

    gap_root = root / "literature" / "gap-repair"
    diagnosis_path = gap_root / "gap-diagnosis.json"
    response_path = gap_root / "gap-query-response.json"
    projection_path = gap_root / "gap-query-projection.json"
    retrieval_path = gap_root / "gap-repair-literature.json"
    layered_path = root / "literature" / "layered-literature.json"

    rederived_diagnosis = diagnose_planning_literature_gap(r1_coverage)
    if diagnosis_path.is_file():
        diagnosis = load_planning_literature_gap_diagnosis(diagnosis_path)
        if diagnosis != rederived_diagnosis:
            raise ContestDirectionResearchLoopError(
                "persisted literature-gap diagnosis differs from the failed R1 coverage"
            )
    else:
        diagnosis = rederived_diagnosis
        write_planning_literature_gap_diagnosis(diagnosis_path, diagnosis)
    if not diagnosis.supplemental_retrieval_allowed or not diagnosis.repairable_roles:
        detail = ", ".join(diagnosis.non_retrieval_blockers) or "unrepairable coverage gap"
        raise ContestDirectionResearchLoopError(
            f"planning literature gap cannot be repaired by bounded retrieval: {detail}"
        )

    evidence_inputs = _planning_gap_repair_evidence_inputs(focus)
    if response_path.is_file():

        def unexpected_completion(**_kwargs: Any) -> LLMJsonCompletionResult:
            raise AssertionError("persisted gap-query response must replay locally")

        response = run_planning_literature_gap_repair_query(
            diagnosis=diagnosis,
            evidence_inputs=evidence_inputs,
            output_path=response_path,
            completion=unexpected_completion,
        )
    else:
        stage_input_hash = planning_literature_gap_repair_stage_input_hash(
            diagnosis,
            evidence_inputs,
        )
        try:
            with context_runtime.checkpointed_stage(
                "planning-literature-gap-repair-query",
                input_hash=stage_input_hash,
                checkpoint_root=root,
            ) as completion:
                response = run_planning_literature_gap_repair_query(
                    diagnosis=diagnosis,
                    evidence_inputs=evidence_inputs,
                    config_path=config_path,
                    env_path=env_path,
                    timeout_seconds=timeout_seconds,
                    max_tokens=retrieval_max_tokens,
                    completion=completion,
                    output_path=response_path,
                )
        except PlanningLiteratureGapRepairResponseError as first_exc:
            if not gap_repair_failure_is_revisable(first_exc):
                raise
            # One bounded revision: re-ask once with the exact rejection reason and
            # the strong-counterevidence-term requirement in a fresh checkpointed
            # stage (its input hash binds the revision reason).
            revision_reason = str(first_exc)
            revision_hash = planning_literature_gap_repair_stage_input_hash(
                diagnosis,
                evidence_inputs,
                revision_failure_reason=revision_reason,
            )
            with context_runtime.checkpointed_stage(
                "planning-literature-gap-repair-query",
                input_hash=revision_hash,
                checkpoint_root=root,
            ) as revision_completion:
                response = run_planning_literature_gap_repair_query(
                    diagnosis=diagnosis,
                    evidence_inputs=evidence_inputs,
                    config_path=config_path,
                    env_path=env_path,
                    timeout_seconds=timeout_seconds,
                    max_tokens=retrieval_max_tokens,
                    completion=revision_completion,
                    output_path=response_path,
                    revision_failure_reason=revision_reason,
                )
    if projection_path.is_file():
        projection = load_planning_literature_gap_repair_projection(projection_path)
        if projection != response.projection:
            raise ContestDirectionResearchLoopError(
                "persisted gap-query projection differs from its provider response"
            )
    else:
        projection = response.projection
        write_planning_literature_gap_repair_projection(projection_path, projection)

    plan = build_contest_direction_gap_repair_plan_from_projection(
        base_merged_artifact_hash=base_merged.artifact_hash,
        base_merged_catalog_hash=base_merged.merged_catalog_hash,
        projection=projection,
    )
    if retrieval_path.is_file():
        retrieval = load_contest_direction_gap_repair(
            retrieval_path,
            expected_plan=plan,
        )
    else:
        retrieval = retrieve_contest_direction_gap_repair(
            plan=plan,
            searchers=replayable_literature_searchers(
                root=gap_root,
                searchers=shared_searchers,
            ),
            max_results_per_search=max_results_per_search,
            output_path=retrieval_path,
        )
    if layered_path.is_file():
        layered = load_contest_direction_layered_literature(
            layered_path,
            base_merged_path=base_merged_path,
            repair_artifact_paths=(retrieval_path,),
        )
    else:
        layered = build_contest_direction_layered_literature(
            base_merged=base_merged,
            repair_artifacts=(retrieval,),
            output_path=layered_path,
        )
    return _BoundedGapRepairState(
        diagnosis=diagnosis,
        diagnosis_path=diagnosis_path,
        response=response,
        response_path=response_path,
        projection=projection,
        projection_path=projection_path,
        retrieval=retrieval,
        retrieval_path=retrieval_path,
        layered=layered,
        layered_path=layered_path,
    )


def _load_bounded_gap_repair(
    *,
    root: Path,
    base_merged: ContestDirectionMergedLiteratureArtifact,
    base_merged_path: Path,
    r1_coverage: PlanningLiteratureCoverageReceipt,
) -> _BoundedGapRepairState:
    """Re-derive a completed bounded repair chain without provider or source calls."""

    gap_root = root / "literature" / "gap-repair"
    diagnosis_path = gap_root / "gap-diagnosis.json"
    response_path = gap_root / "gap-query-response.json"
    projection_path = gap_root / "gap-query-projection.json"
    retrieval_path = gap_root / "gap-repair-literature.json"
    layered_path = root / "literature" / "layered-literature.json"
    diagnosis = load_planning_literature_gap_diagnosis(diagnosis_path)
    if diagnosis != diagnose_planning_literature_gap(r1_coverage):
        raise ContestDirectionResearchLoopError(
            "completed gap diagnosis differs from rederived R1 coverage"
        )
    response = load_planning_literature_gap_repair_response(response_path)
    projection = load_planning_literature_gap_repair_projection(projection_path)
    if response.projection != projection or projection.diagnosis != diagnosis:
        raise ContestDirectionResearchLoopError(
            "completed gap-query response/projection lineage is inconsistent"
        )
    plan = build_contest_direction_gap_repair_plan_from_projection(
        base_merged_artifact_hash=base_merged.artifact_hash,
        base_merged_catalog_hash=base_merged.merged_catalog_hash,
        projection=projection,
    )
    retrieval = load_contest_direction_gap_repair(
        retrieval_path,
        expected_plan=plan,
    )
    layered = load_contest_direction_layered_literature(
        layered_path,
        base_merged_path=base_merged_path,
        repair_artifact_paths=(retrieval_path,),
    )
    return _BoundedGapRepairState(
        diagnosis=diagnosis,
        diagnosis_path=diagnosis_path,
        response=response,
        response_path=response_path,
        projection=projection,
        projection_path=projection_path,
        retrieval=retrieval,
        retrieval_path=retrieval_path,
        layered=layered,
        layered_path=layered_path,
    )


def _planning_gap_repair_evidence_inputs(
    focus: ContestDirectionFocusArtifact,
) -> tuple[PlanningLiteratureGapRepairEvidenceInput, ...]:
    """Expose only hash-bound focus evidence already selected from broad retrieval."""

    return tuple(
        PlanningLiteratureGapRepairEvidenceInput.create(
            source_scope="focus",
            source_artifact_hash=focus.artifact_hash,
            record_id=item.record_id,
            title=item.title,
            abstract=item.abstract,
        )
        for item in focus.focus_evidence
    )


def _persist_exact_coverage_receipt(
    path: Path,
    receipt: PlanningLiteratureCoverageReceipt,
) -> None:
    """Persist one deterministic receipt or reject a conflicting replay."""

    payload = receipt.model_dump(mode="json")
    if path.is_file():
        if _read_json(path) != payload:
            raise ContestDirectionResearchLoopError(
                "planning literature coverage differs from its rederived receipt"
            )
        return
    _write_new_json(path, payload)


def _focused_planning_queries(
    focus: ContestDirectionFocusArtifact | Any,
    targeted: ContestDirectionLiteratureArtifact | Any,
    *,
    role_queries: Sequence[PlanningLiteratureRoleQuery] = (),
) -> tuple[str, ...]:
    """Rank only against the selected focus and its evidence-seeking queries."""

    selected = focus.selected_candidate
    targeted_queries = (
        tuple(item.raw_query for item in role_queries) if role_queries else tuple(targeted.queries)
    )
    return tuple(
        dict.fromkeys(
            item.strip()
            for item in (
                focus.focused_direction_cn,
                *selected.nearest_work_queries,
                *selected.methods_baselines_queries,
                *targeted_queries,
                *selected.counterevidence_queries,
            )
            if item.strip()
        )
    )


def _focused_planning_priority_queries(
    focus: ContestDirectionFocusArtifact | Any,
    targeted: ContestDirectionLiteratureArtifact | Any | None = None,
    *,
    role_queries: Sequence[PlanningLiteratureRoleQuery] = (),
) -> tuple[str, ...]:
    """Prefer nearest-work and method/baseline evidence without imposing quotas.

    The targeted-query stage expands those two model-authored intents into the
    first two search queries (nearest work, then methods/baselines).  Including
    those expansions lets symbolic-dynamics papers match even when the provisional
    focus used the narrower phrase ``permutation entropy``.
    """

    selected = focus.selected_candidate
    expanded_queries = (
        tuple(item.raw_query for item in role_queries[:2])
        if role_queries
        else tuple(targeted.queries[:2])
        if targeted is not None
        else ()
    )
    return tuple(
        dict.fromkeys(
            item.strip()
            for item in (
                *selected.nearest_work_queries,
                *selected.methods_baselines_queries,
                *expanded_queries,
            )
            if item.strip()
        )
    )


def _focused_planning_priority_query_groups(
    focus: ContestDirectionFocusArtifact | Any,
    targeted: ContestDirectionLiteratureArtifact | Any | None = None,
    *,
    role_queries: Sequence[PlanningLiteratureRoleQuery] = (),
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Keep nearest-work and method intents distinct for soft bridge scoring."""

    selected = focus.selected_candidate
    targeted_queries = (
        tuple(item.raw_query for item in role_queries)
        if role_queries
        else tuple(targeted.queries)
        if targeted is not None
        else ()
    )
    nearest_expansion = targeted_queries[:1]
    method_expansion = targeted_queries[1:2]
    return (
        tuple(dict.fromkeys((*selected.nearest_work_queries, *nearest_expansion))),
        tuple(dict.fromkeys((*selected.methods_baselines_queries, *method_expansion))),
    )


def _planning_coverage_role_queries(
    targeted: ContestDirectionLiteratureArtifact | Any,
) -> tuple[PlanningLiteratureRoleQuery, ...]:
    """Bind the four targeted-query positions to planning evidence roles."""

    logical_queries = tuple(str(item).strip() for item in targeted.queries)
    roles = (
        PlanningLiteratureRole.DIRECT_CORE,
        PlanningLiteratureRole.METHOD_FOUNDATION,
        PlanningLiteratureRole.MECHANISM_OR_NULL,
        PlanningLiteratureRole.COUNTEREVIDENCE,
    )
    if len(logical_queries) != len(roles) or any(not item for item in logical_queries):
        raise ContestDirectionResearchLoopError(
            "targeted retrieval must provide exactly four non-blank role queries"
        )
    queries: list[PlanningLiteratureRoleQuery] = []
    try:
        for index, (role, query) in enumerate(zip(roles, logical_queries, strict=True), start=1):
            parsed = role_query_from_boolean(
                role,
                f"targeted-role-q{index}",
                query,
            )
            if len(parsed.must_groups) < 2:
                raise PlanningLiteratureCoverageError(
                    f"{role.value} query lacks an object/evidence AND structure"
                )
            queries.append(parsed)
        core_object_group = queries[0].must_groups[0]
        if any(_is_generic_planning_object_term(item) for item in core_object_group):
            raise PlanningLiteratureCoverageError(
                "direct core object group uses a generic model/system/method term"
            )
        for role_query in (queries[2], queries[3]):
            if core_object_group not in role_query.must_groups:
                raise PlanningLiteratureCoverageError(
                    f"{role_query.role.value} query does not reuse the direct core object group"
                )
    except (PlanningLiteratureCoverageError, ValueError) as exc:
        raise ContestDirectionResearchLoopError(
            f"targeted role-query contract is invalid: {exc}"
        ) from exc
    return tuple(queries)


def _is_generic_planning_object_term(value: str) -> bool:
    normalized = " ".join(value.casefold().split())
    if normalized in _GENERIC_PLANNING_OBJECT_PHRASES:
        return True
    tokens = _lexical_tokens(normalized)
    return bool(tokens) and tokens.issubset(_GENERIC_PLANNING_OBJECT_TERMS)


def _planning_coverage_candidate(
    item: Mapping[str, Any],
    context: str,
) -> PlanningLiteratureCandidate:
    quality = assess_planning_literature_quality(item)
    status = quality.publication_status_claim
    retrieval_queries = item.get("retrieval_queries")
    if not isinstance(retrieval_queries, Sequence) or isinstance(
        retrieval_queries, str | bytes | bytearray
    ):
        retrieval_queries = ()
    source_stages = item.get("source_stages")
    if not isinstance(source_stages, Sequence) or isinstance(
        source_stages, str | bytes | bytearray
    ):
        source_stages = ()
    reserve = 0
    if status == "preprint" and "arxiv" in _retrieval_sources_for_coverage(item):
        reserve = _FINALIST_STATUS_CONTEXT_RESERVE
    return PlanningLiteratureCandidate(
        record_id=str(item.get("record_id") or ""),
        title=str(item.get("title") or ""),
        abstract=str(item.get("abstract") or "") or None,
        anchor_id=canonical_model_hash(
            {"planning_budget_identity": _planning_budget_identity(item)}
        ),
        retrieval_queries=tuple(str(query) for query in retrieval_queries),
        source_stages=tuple(str(stage) for stage in source_stages),
        citation_count=quality.usable_citation_count,
        quality_score=quality.quality_score,
        context_characters=(
            len(json.dumps(dict(item), ensure_ascii=False, sort_keys=True)) + len(context) + reserve
        ),
    )


def _retrieval_sources_for_coverage(item: Mapping[str, Any]) -> frozenset[str]:
    return frozenset(
        source.strip().casefold()
        for source in str(item.get("retrieved_from") or "").split(",")
        if source.strip()
    )


def _coverage_select(
    catalog: Sequence[Mapping[str, Any]],
    contexts: Sequence[str],
    *,
    role_queries: Sequence[PlanningLiteratureRoleQuery],
    method_focus_basis_queries: Sequence[PlanningLiteratureRoleQuery] | None = None,
) -> PlanningLiteratureCoverageReceipt:
    receipt = _coverage_receipt(
        catalog,
        contexts,
        role_queries=role_queries,
        method_focus_basis_queries=method_focus_basis_queries,
    )
    try:
        return receipt.require_pass()
    except PlanningLiteratureCoverageError as exc:
        raise ContestDirectionResearchLoopError(str(exc)) from exc


def _coverage_receipt(
    catalog: Sequence[Mapping[str, Any]],
    contexts: Sequence[str],
    *,
    role_queries: Sequence[PlanningLiteratureRoleQuery],
    method_focus_basis_queries: Sequence[PlanningLiteratureRoleQuery] | None = None,
) -> PlanningLiteratureCoverageReceipt:
    """Return a replayable pass or failure receipt without hiding the failure."""

    if len(catalog) != len(contexts):
        raise ContestDirectionResearchLoopError(
            "planning coverage candidate catalog and context differ in size"
        )
    required_anchor_eligible_record_ids = tuple(
        str(item.get("record_id") or "")
        for item in catalog
        if assess_planning_literature_quality(item).required_anchor_eligible
    )
    receipt = select_planning_literature(
        tuple(
            _planning_coverage_candidate(item, context)
            for item, context in zip(catalog, contexts, strict=True)
        ),
        role_queries,
        maximum_records=MAX_RESEARCH_PLAN_REFERENCES,
        maximum_total_context_characters=_MAX_PLANNING_LITERATURE_CHARACTERS,
        required_anchor_eligible_record_ids=required_anchor_eligible_record_ids,
        method_focus_basis_queries=method_focus_basis_queries,
    )
    return receipt


def _coverage_selected_subset(
    catalog: Sequence[Mapping[str, Any]],
    contexts: Sequence[str],
    receipt: PlanningLiteratureCoverageReceipt,
) -> tuple[tuple[dict[str, Any], ...], tuple[str, ...]]:
    by_id = {
        str(item.get("record_id") or ""): (dict(item), context)
        for item, context in zip(catalog, contexts, strict=True)
    }
    try:
        selected = tuple(by_id[record_id] for record_id in receipt.selected_record_ids)
    except KeyError as exc:
        raise ContestDirectionResearchLoopError(
            "planning coverage selected a record outside the candidate catalog"
        ) from exc
    selected_catalog = tuple(item for item, _context in selected)
    selected_contexts = _renumber_locked_planning_contexts(
        selected_catalog,
        tuple(context for _item, context in selected),
    )
    return selected_catalog, selected_contexts


def _renumber_locked_planning_contexts(
    catalog: Sequence[Mapping[str, Any]],
    contexts: Sequence[str],
) -> tuple[str, ...]:
    """Replace inherited full-catalog indices with the immutable lock order."""

    if len(catalog) != len(contexts):
        raise ContestDirectionResearchLoopError(
            "planning catalog and context differ while assigning locked indices"
        )
    locked: list[str] = []
    for locked_index, (item, context) in enumerate(
        zip(catalog, contexts, strict=True),
        start=1,
    ):
        first_line, separator, remainder = context.partition("\n")
        match = _CATALOG_CONTEXT_INDEX.match(first_line)
        if match is None:
            locked.append(context)
            continue
        record_id = str(item.get("record_id") or "")
        if first_line[match.end() :].strip() != record_id:
            raise ContestDirectionResearchLoopError(
                "planning context record identity differs from the selected catalog"
            )
        rewritten_first_line = _CATALOG_CONTEXT_INDEX.sub(
            f"[{locked_index}]\\g<suffix>",
            first_line,
            count=1,
        )
        locked.append(rewritten_first_line + (separator + remainder if separator else ""))
    return tuple(locked)


def _select_planning_literature_with_coverage_and_status(
    catalog: Sequence[Mapping[str, Any]],
    contexts: Sequence[str],
    *,
    role_queries: Sequence[PlanningLiteratureRoleQuery],
    method_focus_basis_queries: Sequence[PlanningLiteratureRoleQuery] | None = None,
    arxiv_status_verifier: Callable[[AcademicPaper], AcademicPaper] | None,
) -> tuple[
    tuple[dict[str, Any], ...],
    tuple[str, ...],
    PlanningLiteratureCoverageReceipt,
    list[dict[str, Any]],
]:
    """Fill role quotas, verify only finalists, and replace invalid finalists."""

    working_catalog = tuple(dict(item) for item in catalog)
    working_contexts = tuple(contexts)
    verified_records: dict[str, dict[str, Any]] = {}
    verified_contexts: dict[str, str] = {}
    status_receipts: dict[str, dict[str, Any]] = {}
    maximum_rounds = max(1, len(working_catalog) * 2)
    for _round in range(maximum_rounds):
        projected_catalog = tuple(
            verified_records.get(str(item.get("record_id") or ""), dict(item))
            for item in working_catalog
        )
        projected_contexts = tuple(
            verified_contexts.get(str(item.get("record_id") or ""), context)
            for item, context in zip(working_catalog, working_contexts, strict=True)
        )
        coverage = _coverage_select(
            projected_catalog,
            projected_contexts,
            role_queries=role_queries,
            method_focus_basis_queries=method_focus_basis_queries,
        )
        selected_catalog, selected_contexts = _coverage_selected_subset(
            projected_catalog,
            projected_contexts,
            coverage,
        )
        unseen = False
        invalid_ids: set[str] = set()
        for record, context in zip(selected_catalog, selected_contexts, strict=True):
            record_id = str(record.get("record_id") or "")
            if record_id not in status_receipts:
                unseen = True
                verified, verified_context, status = _verify_arxiv_finalist(
                    dict(record),
                    context,
                    verifier=arxiv_status_verifier,
                )
                verified_records[record_id] = verified
                verified_contexts[record_id] = verified_context
                status_receipts[record_id] = status
            if str(
                verified_records[record_id].get("publication_status") or "unknown"
            ).casefold() in {
                "withdrawn",
                "retracted",
            }:
                invalid_ids.add(record_id)
        if invalid_ids:
            kept = tuple(
                (item, context)
                for item, context in zip(working_catalog, working_contexts, strict=True)
                if str(item.get("record_id") or "") not in invalid_ids
            )
            working_catalog = tuple(item for item, _context in kept)
            working_contexts = tuple(context for _item, context in kept)
            continue
        if unseen:
            continue
        final_catalog, final_contexts = _coverage_selected_subset(
            projected_catalog,
            projected_contexts,
            coverage,
        )
        if len(final_catalog) < MIN_RESEARCH_PLAN_REFERENCES:
            raise ContestDirectionResearchLoopError(
                "planning coverage produced fewer than the required references"
            )
        return final_catalog, final_contexts, coverage, list(status_receipts.values())
    raise ContestDirectionResearchLoopError(
        "planning literature coverage/status selection did not converge"
    )


def _eligible_merged_literature(
    artifact: _PlanningLiteratureArtifact,
    *,
    targeted_literature: ContestDirectionLiteratureArtifact | None = None,
    base_merged_literature: ContestDirectionMergedLiteratureArtifact | None = None,
) -> tuple[tuple[dict[str, Any], ...], tuple[str, ...], list[dict[str, str]]]:
    """Apply the existing truth gates to a merged catalog without changing lineage."""

    targeted_logical_queries = (
        {
            fetch.fetch_id: targeted_literature.queries[fetch.query_index - 1]
            for fetch in targeted_literature.fetches
        }
        if targeted_literature is not None
        else {}
    )
    projected_by_id = {
        str(item.get("record_id")): dict(item) for item in artifact.objective_retrieval_catalog()
    }
    contexts_by_id = dict(
        zip(artifact.record_ids, artifact.objective_literature_catalog(), strict=True)
    )
    eligible: list[dict[str, Any]] = []
    contexts: list[str] = []
    excluded: list[dict[str, str]] = []
    base_records_by_id = {
        item.record_id: item
        for item in (
            base_merged_literature.records
            if base_merged_literature is not None
            else artifact.records
            if isinstance(artifact, ContestDirectionMergedLiteratureArtifact)
            else ()
        )
    }
    layered_bindings = (
        {item.layered_record_id: item for item in artifact.record_bindings}
        if isinstance(artifact, ContestDirectionLayeredLiteratureArtifact)
        else {}
    )
    for record in artifact.records:
        item = projected_by_id.get(record.record_id)
        reasons: list[str] = []
        if record.publication_status in {"withdrawn", "retracted"}:
            reasons.append(f"publication_status_{record.publication_status}")
        if item is None:
            reasons.append("missing_url_or_doi")
        else:
            if not str(item.get("abstract") or "").strip():
                reasons.append("missing_abstract")
            source_url = str(item.get("source_url") or item.get("url") or "").strip()
            if not source_url.lower().startswith(("https://", "http://")):
                reasons.append("missing_real_url_or_doi")
            if not str(item.get("retrieved_from") or "").strip():
                reasons.append("missing_retrieval_source")
            if not _is_aware_timestamp(str(item.get("retrieved_at") or "")):
                reasons.append("missing_or_naive_retrieval_time")
        if reasons:
            excluded.append({"record_id": record.record_id, "reason": ",".join(reasons)})
            continue
        assert item is not None
        projected = dict(item)
        retrieval_queries: list[str] = []
        if isinstance(artifact, ContestDirectionMergedLiteratureArtifact):
            retrieval_queries.extend(
                targeted_logical_queries.get(retrieval.fetch_id, retrieval.query)
                for retrieval in record.retrievals
                if retrieval.stage == "targeted_direction"
            )
        else:
            binding = layered_bindings.get(record.record_id)
            if binding is None:
                raise ContestDirectionResearchLoopError(
                    "layered literature record is missing its query-lineage binding"
                )
            for base_record_id in binding.base_record_ids:
                base_record = base_records_by_id.get(base_record_id)
                if base_record is None:
                    raise ContestDirectionResearchLoopError(
                        "layered literature points outside the immutable R1 base"
                    )
                retrieval_queries.extend(
                    targeted_logical_queries.get(retrieval.fetch_id, retrieval.query)
                    for retrieval in base_record.retrievals
                    if retrieval.stage == "targeted_direction"
                )
            retrieval_queries.extend(
                item.logical_query
                for item in binding.round_query_lineage
                if item.logical_query is not None
            )
        projected["retrieval_queries"] = list(dict.fromkeys(retrieval_queries))
        projected["source_stages"] = list(
            dict.fromkeys(retrieval.stage for retrieval in record.retrievals)
        )
        eligible.append(projected)
        contexts.append(contexts_by_id[record.record_id])
    if not eligible:
        raise ContestDirectionResearchLoopError(
            "merged broad + targeted retrieval produced no complete real literature record"
        )
    return tuple(eligible), tuple(contexts), excluded


def _is_aware_timestamp(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _load_or_write_planning_literature_lock(
    path: Path,
    *,
    merged: _PlanningLiteratureArtifact,
    base_merged: ContestDirectionMergedLiteratureArtifact,
    focus: ContestDirectionFocusArtifact,
    targeted_binding: ContestDirectionTargetedRetrievalBinding,
    candidate_catalog: Sequence[Mapping[str, Any]],
    planning_catalog: Sequence[Mapping[str, Any]],
    planning_context: Sequence[str],
    finalist_status_payload: Mapping[str, Any],
    r1_planning_coverage: PlanningLiteratureCoverageReceipt,
    r2_planning_coverage: PlanningLiteratureCoverageReceipt | None,
    planning_coverage: PlanningLiteratureCoverageReceipt,
    gap_state: _BoundedGapRepairState | None,
    require_existing: bool,
) -> dict[str, Any]:
    if gap_state is None:
        if not r1_planning_coverage.passed or merged != base_merged:
            raise ContestDirectionResearchLoopError(
                "zero-round planning lock must use the passing immutable R1 evidence"
            )
    elif r1_planning_coverage.passed or r2_planning_coverage is None or merged != gap_state.layered:
        raise ContestDirectionResearchLoopError(
            "one-round planning lock must bind failed R1, R2, and layered evidence"
        )
    gap_chain: dict[str, Any] = {
        "repair_round_count": 1 if gap_state is not None else 0,
        "gap_diagnosis_hash": (
            gap_state.diagnosis.diagnosis_hash if gap_state is not None else None
        ),
        "gap_query_response_receipt_hash": (
            gap_state.response.receipt_hash if gap_state is not None else None
        ),
        "gap_query_projection_hash": (
            gap_state.projection.projection_hash if gap_state is not None else None
        ),
        "gap_retrieval_artifact_hash": (
            gap_state.retrieval.artifact_hash if gap_state is not None else None
        ),
        "gap_retrieval_catalog_hash": (
            gap_state.retrieval.repair_catalog_hash if gap_state is not None else None
        ),
        "layered_literature_artifact_hash": (
            gap_state.layered.artifact_hash if gap_state is not None else None
        ),
        "r2_pre_status_coverage_receipt_hash": (
            r2_planning_coverage.receipt_hash if r2_planning_coverage is not None else None
        ),
    }
    quality_assessments = tuple(
        assess_planning_literature_quality(item) for item in candidate_catalog
    )
    payload: dict[str, Any] = {
        "schema_version": "contest-direction-planning-literature-v5",
        "literature_protocol": _LITERATURE_PROTOCOL,
        "broad_literature_artifact_hash": merged.broad_literature_artifact_hash,
        "focus_artifact_hash": focus.artifact_hash,
        "selected_focus_id": focus.selected_focus_id,
        "focused_direction_cn": focus.focused_direction_cn,
        "targeted_retrieval_binding_hash": targeted_binding.artifact_hash,
        "targeted_literature_artifact_hash": merged.targeted_literature_artifact_hash,
        "base_merged_literature_artifact_hash": base_merged.artifact_hash,
        "base_merged_literature_catalog_hash": base_merged.merged_catalog_hash,
        "merged_literature_artifact_hash": merged.artifact_hash,
        "merged_literature_catalog_hash": merged.merged_catalog_hash,
        "gap_repair_chain": gap_chain,
        "gap_repair_chain_hash": canonical_model_hash(gap_chain),
        "selection_bounds": {
            "minimum": MIN_RESEARCH_PLAN_REFERENCES,
            "maximum": MAX_RESEARCH_PLAN_REFERENCES,
        },
        "selected_record_ids": [str(item.get("record_id")) for item in planning_catalog],
        "work_family_duplicate_suppressions": list(
            _planning_work_family_suppressions(candidate_catalog, planning_catalog)
        ),
        "candidate_quality_assessments": [
            item.model_dump(mode="json") for item in quality_assessments
        ],
        "candidate_quality_assessments_hash": canonical_model_hash(
            {"assessments": [item.model_dump(mode="json") for item in quality_assessments]}
        ),
        "planning_catalog": [dict(item) for item in planning_catalog],
        "planning_catalog_hash": canonical_model_hash(
            {"catalog": [dict(item) for item in planning_catalog]}
        ),
        "planning_context_hash": canonical_model_hash({"context": list(planning_context)}),
        "finalist_status_artifact_hash": finalist_status_payload["artifact_hash"],
        "r1_planning_coverage_schema_version": r1_planning_coverage.schema_version,
        "r1_planning_coverage_receipt_hash": r1_planning_coverage.receipt_hash,
        "planning_coverage_schema_version": planning_coverage.schema_version,
        "planning_coverage_receipt_hash": planning_coverage.receipt_hash,
        "planning_coverage_thresholds": planning_coverage.thresholds.model_dump(mode="json"),
        "planning_coverage_selected_role_counts": (
            planning_coverage.selected_role_counts.model_dump(mode="json")
        ),
        "planning_coverage_role_query_ids": [
            item.query_id for item in planning_coverage.role_queries
        ],
        "planning_coverage_method_focus_basis_query_ids": [
            item.query_id for item in planning_coverage.method_focus_basis_queries
        ],
        "planning_coverage_eligible_role_family_counts": (
            planning_coverage.eligible_role_family_counts.model_dump(mode="json")
        ),
        "planning_coverage_anchor_assignments": [
            item.model_dump(mode="json") for item in planning_coverage.anchor_assignments
        ],
        "selection_semantics": (
            "immutable_method_focus_bridge_then_complete_role_match_before_"
            "provider_neutral_publication_quality_and_bounded_bibliometrics_"
            "published_repository_only_records_excluded_from_required_anchors_"
            "exact_metadata_identity_preserved_five_independent_anchors_then_"
            "quality_limited_supplements_with_at_most_one_bounded_gap_repair"
        ),
    }
    payload["artifact_hash"] = canonical_model_hash(payload)
    if path.is_file():
        existing = _read_json(path)
        if existing != payload:
            raise ContestDirectionResearchLoopError(
                "planning literature lock differs from rederived two-stage selection"
            )
        return existing
    if require_existing:
        raise ContestDirectionResearchLoopError("resume planning literature lock is missing")
    _write_new_json(path, payload)
    return payload


def _load_completed_two_stage_literature(root: Path) -> _TwoStageLiteratureState:
    """Re-derive a completed two-stage chain locally before accepting fast resume."""

    literature_root = root / "literature"
    broad_path = literature_root / "broad" / "direction-literature.json"
    refinement_root = literature_root / "refinement"
    focus_path = refinement_root / "direction-focus.json"
    targeted_path = refinement_root / "targeted-literature.json"
    targeted_binding_path = refinement_root / "direction-targeted-retrieval.json"
    merged_path = literature_root / "merged-literature.json"
    r1_planning_coverage_path = literature_root / "planning-literature-coverage-r1.json"
    r2_planning_coverage_path = literature_root / "planning-literature-coverage-r2.json"
    finalist_status_path = literature_root / "finalist-status-verification.json"
    planning_coverage_path = literature_root / "planning-literature-coverage.json"
    planning_lock_path = literature_root / "planning-literature.json"
    try:
        broad = ContestDirectionLiteratureArtifact.model_validate_json(
            broad_path.read_text(encoding="utf-8")
        )
        focus = load_contest_direction_focus_selection(
            focus_path,
            broad_literature=broad,
            executable_adapter_capabilities=(_ADAPTER_DESCRIPTOR,),
            require_publication_status_verification=False,
        )
        targeted_binding = load_contest_direction_targeted_retrieval(
            targeted_binding_path,
            focus=focus,
        )
        targeted = ContestDirectionLiteratureArtifact.model_validate_json(
            targeted_path.read_text(encoding="utf-8")
        )
        base_merged = load_contest_direction_merged_literature(
            merged_path,
            broad_literature_path=broad_path,
            focus_path=focus_path,
            targeted_binding_path=targeted_binding_path,
            targeted_literature_path=targeted_path,
            executable_adapter_capabilities=(_ADAPTER_DESCRIPTOR,),
        )
    except Exception as exc:
        raise ContestDirectionResearchLoopError(
            "completed two-stage literature lineage is invalid"
        ) from exc
    base_catalog, base_context, base_excluded_records = _eligible_merged_literature(
        base_merged,
        targeted_literature=targeted,
    )
    r1_role_queries = _planning_coverage_role_queries(targeted)
    r1_coverage = _coverage_receipt(
        base_catalog,
        base_context,
        role_queries=r1_role_queries,
    )
    persisted_r1 = load_planning_literature_coverage_receipt(r1_planning_coverage_path)
    if persisted_r1 != r1_coverage:
        raise ContestDirectionResearchLoopError(
            "completed R1 planning coverage differs from rederived selection"
        )
    gap_state: _BoundedGapRepairState | None = None
    r2_coverage: PlanningLiteratureCoverageReceipt | None = None
    if r1_coverage.passed:
        merged: _PlanningLiteratureArtifact = base_merged
        effective_merged_path = merged_path
        retrieval_catalog = base_catalog
        literature_context = base_context
        excluded_records = base_excluded_records
        role_queries = r1_role_queries
    else:
        gap_state = _load_bounded_gap_repair(
            root=root,
            base_merged=base_merged,
            base_merged_path=merged_path,
            r1_coverage=r1_coverage,
        )
        merged = gap_state.layered
        effective_merged_path = gap_state.layered_path
        role_queries = gap_state.projection.r2_role_queries
        retrieval_catalog, literature_context, excluded_records = _eligible_merged_literature(
            merged,
            targeted_literature=targeted,
            base_merged_literature=base_merged,
        )
        r2_coverage = _coverage_receipt(
            retrieval_catalog,
            literature_context,
            role_queries=role_queries,
            method_focus_basis_queries=r1_coverage.method_focus_basis_queries,
        )
        persisted_r2 = load_planning_literature_coverage_receipt(r2_planning_coverage_path)
        if persisted_r2 != r2_coverage or not r2_coverage.passed:
            raise ContestDirectionResearchLoopError(
                "completed R2 planning coverage differs from its passing rederivation"
            )
    finalist_status_payload = _load_finalist_status_verification(finalist_status_path)
    replay_catalog, replay_context = _apply_finalist_status_verification(
        retrieval_catalog,
        literature_context,
        finalist_status_payload,
    )
    planning_coverage = _coverage_select(
        replay_catalog,
        replay_context,
        role_queries=role_queries,
        method_focus_basis_queries=r1_coverage.method_focus_basis_queries,
    )
    planning_catalog, planning_context = _coverage_selected_subset(
        replay_catalog,
        replay_context,
        planning_coverage,
    )
    persisted_coverage = load_planning_literature_coverage_receipt(planning_coverage_path)
    if persisted_coverage != planning_coverage:
        raise ContestDirectionResearchLoopError(
            "completed planning literature coverage differs from rederived selection"
        )
    planning_lock_payload = _load_or_write_planning_literature_lock(
        planning_lock_path,
        merged=merged,
        base_merged=base_merged,
        focus=focus,
        targeted_binding=targeted_binding,
        candidate_catalog=replay_catalog,
        planning_catalog=planning_catalog,
        planning_context=planning_context,
        finalist_status_payload=finalist_status_payload,
        r1_planning_coverage=r1_coverage,
        r2_planning_coverage=r2_coverage,
        planning_coverage=planning_coverage,
        gap_state=gap_state,
        require_existing=True,
    )
    return _TwoStageLiteratureState(
        broad=broad,
        broad_path=broad_path,
        focus=focus,
        focus_path=focus_path,
        targeted_binding=targeted_binding,
        targeted_binding_path=targeted_binding_path,
        targeted=targeted,
        targeted_path=targeted_path,
        merged=merged,
        merged_path=effective_merged_path,
        planning_catalog=tuple(dict(item) for item in planning_catalog),
        planning_context=tuple(planning_context),
        excluded_records=excluded_records,
        finalist_status_path=finalist_status_path,
        finalist_status_payload=finalist_status_payload,
        planning_coverage_path=planning_coverage_path,
        planning_coverage=planning_coverage,
        planning_lock_path=planning_lock_path,
        planning_lock_payload=planning_lock_payload,
        base_merged=base_merged,
        base_merged_path=merged_path,
        effective_role_queries=tuple(role_queries),
        r1_planning_coverage_path=r1_planning_coverage_path,
        r1_planning_coverage=r1_coverage,
        r2_planning_coverage_path=(r2_planning_coverage_path if gap_state is not None else None),
        r2_planning_coverage=r2_coverage,
        gap_diagnosis_path=(gap_state.diagnosis_path if gap_state is not None else None),
        gap_diagnosis=(gap_state.diagnosis if gap_state is not None else None),
        gap_response_path=(gap_state.response_path if gap_state is not None else None),
        gap_response=(gap_state.response if gap_state is not None else None),
        gap_projection_path=(gap_state.projection_path if gap_state is not None else None),
        gap_projection=(gap_state.projection if gap_state is not None else None),
        gap_retrieval_path=(gap_state.retrieval_path if gap_state is not None else None),
        gap_retrieval=(gap_state.retrieval if gap_state is not None else None),
    )


def _start_memory_bridge(
    *,
    root: Path,
    direction_id: str,
    vault_root: Path | str,
    context_runtime: ContestDirectionContextRuntime,
) -> ContestDirectionMemoryBridge | None:
    """Start the existing sovereign-memory sidecar without governing delivery."""

    try:
        session = getattr(context_runtime, "session", None)
        raw_store = getattr(session, "raw_memory_store", None)
        kwargs: dict[str, Any] = {}
        if raw_store is not None:
            kwargs["raw_memory_store"] = raw_store
        return ContestDirectionMemoryBridge(
            output_root=root,
            project_id=direction_id,
            vault_root=vault_root,
            **kwargs,
        )
    except Exception as exc:  # memory is a best-effort delivery sidecar
        del exc
        return None


def _capture_stage_memory(
    bridge: ContestDirectionMemoryBridge | None,
    *,
    stage: str,
    artifact_paths: Sequence[Path],
) -> dict[str, Any]:
    """Capture a completed stage, degrading to a reportable non-blocking status."""

    if bridge is None:
        return {
            "status": "unavailable",
            "receipt_persisted": False,
            "raw_artifact_count": 0,
            "derived_context_is_evidence": False,
            "delivery_blocked_by_memory": False,
            "errors": ["memory bridge unavailable"],
        }
    try:
        result = bridge.capture_completed_stage(
            stage=stage,
            artifact_paths=tuple(artifact_paths),
        )
        receipt = result.receipt
        return {
            "status": receipt.status,
            "receipt_persisted": result.receipt_path is not None,
            "receipt_path": (
                result.receipt_path.as_posix() if result.receipt_path is not None else None
            ),
            "receipt_hash": receipt.receipt_hash,
            "raw_artifact_count": len(receipt.artifacts),
            "dreaming_projection_id": receipt.dreaming_projection_id,
            "dreaming_projection_hash": receipt.dreaming_projection_hash,
            "derived_context_is_evidence": False,
            "delivery_blocked_by_memory": False,
            "errors": list(receipt.errors),
        }
    except Exception as exc:  # completed scientific artifacts remain authoritative
        return {
            "status": "unavailable",
            "receipt_persisted": False,
            "raw_artifact_count": 0,
            "derived_context_is_evidence": False,
            "delivery_blocked_by_memory": False,
            "errors": [f"stage memory capture failed ({type(exc).__name__})"],
        }


def _recall_stage_memory(
    bridge: ContestDirectionMemoryBridge | None,
    *,
    consumer_stage: str,
    source_stages: Sequence[str],
    requested: bool,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Recall a rebuildable navigation view or return no model context."""

    if bridge is None:
        return None, {
            "status": "unavailable" if requested else "not_requested",
            "requested": requested,
            "receipt_persisted": False,
            "selected_projection_count": 0,
            "derived_context_is_evidence": False,
            "model_consumption_proven_by_receipt": False,
            "delivery_blocked_by_memory": False,
            "errors": ["memory bridge unavailable"] if requested else [],
        }
    try:
        result: MemoryRecallResult = bridge.recall_optional_context(
            consumer_stage=consumer_stage,
            source_stages=tuple(source_stages),
            requested=requested,
        )
        receipt = result.receipt
        # An unpersisted selection cannot be reconstructed during resume, so it
        # is deliberately withheld from the provider even if held in memory.
        context = result.context if result.receipt_path is not None else None
        return context, {
            "status": receipt.status,
            "requested": requested,
            "receipt_persisted": result.receipt_path is not None,
            "receipt_path": (
                result.receipt_path.as_posix() if result.receipt_path is not None else None
            ),
            "recall_hash": receipt.recall_hash,
            "selected_projection_count": len(receipt.selected),
            "context_injected_into_model_stage": context is not None,
            "derived_context_is_evidence": False,
            "model_consumption_proven_by_receipt": False,
            "delivery_blocked_by_memory": False,
            "errors": list(receipt.errors),
        }
    except Exception as exc:  # optional recall cannot block scientific delivery
        return None, {
            "status": "unavailable" if requested else "not_requested",
            "requested": requested,
            "receipt_persisted": False,
            "selected_projection_count": 0,
            "context_injected_into_model_stage": False,
            "derived_context_is_evidence": False,
            "model_consumption_proven_by_receipt": False,
            "delivery_blocked_by_memory": False,
            "errors": [f"memory recall failed ({type(exc).__name__})"],
        }


def _revision_guard_retry_requirement(reason: str) -> str:
    """One Chinese retry requirement tailored to the exact guard rejection."""

    parts = [
        "上一次修订被程序数字守卫拒绝（",
        reason,
        "）。重写时正文所有数值必须逐字来自本次输入中已经出现的预实验 artifact、"
        "metrics、日志或原计划；禁止任何派生数值（比值、倍数、百分比、轮筛周期积、"
        "改写数量级范围或正负符号），需要定量比较时只引用证据中已有的数值并配合"
        "定性强弱词表述。",
    ]
    lowered = reason.casefold()
    if "alternative explanation" in lowered:
        parts.append(
            "Results 中必须明确写出至少一种替代解释，并使用“替代解释”或“另一种解释”"
            "字样开头（例如“替代解释：局部筛结构同样可以解释该差异”）。"
        )
    if "quote at least one verified" in lowered:
        parts.append(
            "Results 中必须至少引用一个已核验的预实验数值（使用 [[pilot:字段路径]] 占位符）。"
        )
    return "".join(parts)


def _memory_bound_input_hash(
    payload: Mapping[str, Any],
    context: dict[str, Any] | None,
) -> str:
    """Bind only an actually supplied optional context into a stage checkpoint."""

    bound = dict(payload)
    context_hash = optional_dreaming_context_hash(context)
    if context_hash is not None:
        bound["optional_dreaming_context_sha256"] = context_hash
    return canonical_model_hash(bound)


def _reuse_preexisting_stage_input_hash(
    *,
    root: Path,
    ordinal: int,
    stage_name: str,
    computed_hash: str,
    artifact_preexisting: bool,
) -> str:
    """Keep an already-executed stage replayable if an optional recall vanished."""

    if not artifact_preexisting:
        return computed_hash
    path = root / "checkpoints" / "completed-stages" / f"{ordinal:02d}-{stage_name}.json"
    if not path.is_file():
        return computed_hash
    payload = _read_json(path)
    expected = canonical_model_hash(
        {key: value for key, value in payload.items() if key != "checkpoint_hash"}
    )
    recorded = str(payload.get("stage_input_hash") or "")
    if (
        payload.get("schema_version") != "contest-direction-stage-checkpoint-v1"
        or payload.get("ordinal") != ordinal
        or payload.get("stage_name") != stage_name
        or payload.get("checkpoint_hash") != expected
        or not _is_sha256(recorded)
    ):
        raise ContestDirectionResearchLoopError(
            f"preexisting completed-stage checkpoint is invalid: {stage_name}"
        )
    return recorded


def _memory_delivery_summary(
    *,
    stages: Mapping[str, Mapping[str, Any]],
    recalls: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": "contest-direction-memory-delivery-v1",
        "mode": "best_effort_raw_memory_plus_rebuildable_dreaming",
        "completed_stage_captures": {key: dict(value) for key, value in stages.items()},
        "optional_model_recalls": {key: dict(value) for key, value in recalls.items()},
        "raw_artifacts_remain_authoritative": True,
        "dreaming_context_is_scientific_evidence": False,
        "memory_can_block_scientific_delivery": False,
    }


def _reverify_existing_memory_receipts(
    *,
    root: Path,
    report: Mapping[str, Any],
    vault_root: Path | str,
) -> dict[str, Any]:
    """Strictly replay existing receipt bindings without capturing them again."""

    memory = report.get("memory")
    captures = memory.get("completed_stage_captures") if isinstance(memory, Mapping) else None
    if not isinstance(captures, Mapping):
        return {
            "status": "not_present",
            "receipt_replay_count": 0,
            "new_capture_count": 0,
            "delivery_blocked_by_memory": False,
        }
    errors: list[str] = []
    replayed = 0
    try:
        direction_input = _read_json(root / "direction-input.json")
        project_id = str(direction_input.get("direction_id") or "")
        bridge = ContestDirectionMemoryBridge(
            output_root=root,
            project_id=project_id,
            vault_root=vault_root,
        )
        for stage, item in captures.items():
            if not isinstance(stage, str) or not isinstance(item, Mapping):
                continue
            if item.get("receipt_persisted") is not True:
                continue
            try:
                bridge.load_stage_receipt(stage)
                replayed += 1
            except Exception as exc:
                errors.append(f"receipt replay {stage} failed ({type(exc).__name__})")
    except Exception as exc:
        errors.append(f"memory replay startup failed ({type(exc).__name__})")
    return {
        "status": "verified" if not errors else "degraded",
        "receipt_replay_count": replayed,
        "new_capture_count": 0,
        "delivery_blocked_by_memory": False,
        "errors": errors,
    }


def _resume_existing_direction_research_loop(
    *,
    direction: str,
    root: Path,
    skills_root: Path | str,
    config_path: Path | str,
    env_path: Path | str,
    feedback_max_tokens: int,
    objective_review_max_tokens: int,
    plan_max_tokens: int,
    scientific_review_max_tokens: int,
    timeout_seconds: int,
    thinking_budget: int,
    render_timeout_seconds: int,
    context_vault_root: Path | str,
    context_capability_cache_dir: Path | str,
    context_completion: Callable[..., LLMJsonCompletionResult] | None,
    dreaming_recall_enabled: bool,
    max_results_per_search: int,
    retrieval_max_tokens: int,
    skill_routing_max_tokens: int,
    brainstorm_max_tokens: int,
    literature_runner: Callable[..., ContestDirectionLiteratureArtifact],
    literature_searchers: Mapping[str, Callable[..., Sequence[AcademicPaper]]] | None,
    focus_selection_runner: Callable[..., ContestDirectionFocusArtifact],
    targeted_retrieval_runner: Callable[..., ContestDirectionTargetedRetrievalBinding],
    merged_literature_builder: Callable[..., ContestDirectionMergedLiteratureArtifact],
    skill_router: Callable[..., ContestDirectSkillRoutingArtifact],
    hypothesis_stage_runner: Callable[..., Any] | None,
    preexperiment_runner: Callable[..., ContestPrimePreexperimentArtifact],
    plan_generator: Callable[..., ContestDirectPlanArtifact],
    arxiv_status_verifier: Callable[[AcademicPaper], AcademicPaper] | None,
    postpilot_stage_runner: Callable[..., Any] | None,
    plan_revision_runner: Callable[..., ContestDirectPlanRevisionArtifact],
    plan_materializer: Callable[..., ContestDirectPlanArtifacts],
    scientific_review_runner: Callable[..., ContestDirectPlanScientificReviewArtifact],
    preexperiment_loader: Callable[..., ContestPrimePreexperimentArtifact],
) -> dict[str, Any]:
    """Verify every checkpoint byte and continue from the first missing stage."""

    if not root.is_dir():
        raise ContestDirectionResearchLoopError(f"resume output directory does not exist: {root}")
    direction_input_path = root / "direction-input.json"
    direction_payload = _read_json(direction_input_path)
    base_input = {
        key: value
        for key, value in direction_payload.items()
        if key not in {"input_hash", "direction_id"}
    }
    if direction_payload.get("schema_version") != _INPUT_SCHEMA:
        raise ContestDirectionResearchLoopError(
            "legacy direction-loop artifacts cannot satisfy the two-stage literature "
            "protocol; start a fresh run in a new empty output directory"
        )
    if direction_payload.get("literature_protocol") != _LITERATURE_PROTOCOL:
        raise ContestDirectionResearchLoopError(
            "legacy literature protocol cannot be resumed under the current quality and "
            "planning-lock semantics; start a fresh run in a new empty output directory"
        )
    source_accounting_protocol = direction_payload.get("source_accounting_protocol")
    if source_accounting_protocol not in {None, _SOURCE_ACCOUNTING_PROTOCOL}:
        raise ContestDirectionResearchLoopError(
            "resume source-accounting protocol marker is invalid"
        )
    if direction_payload.get("direction") != direction or direction_payload.get(
        "input_hash"
    ) != canonical_model_hash(base_input):
        raise ContestDirectionResearchLoopError("resume direction checkpoint is invalid")
    direction_id = str(direction_payload.get("direction_id") or "")
    if direction_id != f"direction-loop-{str(direction_payload['input_hash'])[:20]}":
        raise ContestDirectionResearchLoopError("resume direction ID mismatch")

    no_adapter_terminal = _resume_no_adapter_terminal(
        root=root,
        direction=direction,
        vault_root=context_vault_root,
    )
    if no_adapter_terminal is not None:
        return no_adapter_terminal

    if (root / "delivery-report.json").exists():
        report = _read_json(root / "delivery-report.json")
        if (
            report.get("schema_version") != _DELIVERY_SCHEMA
            or report.get("literature_protocol") != _LITERATURE_PROTOCOL
        ):
            raise ContestDirectionResearchLoopError("existing delivery report is not completed")
        if report.get("direction") != direction:
            raise ContestDirectionResearchLoopError(
                "completed delivery report belongs to another direction"
            )
        _verify_persisted_source_checkpoint_accounting(
            root=root,
            persisted=report.get("source_accounting"),
        )
        completed_literature = _load_completed_two_stage_literature(root)
        if report.get("focused_direction") != completed_literature.focus.focused_direction_cn:
            raise ContestDirectionResearchLoopError(
                "completed report focused direction differs from the focus artifact"
            )
        completed_review = load_contest_direct_plan_scientific_review(
            root / "independent-scientific-review" / "system-plan-scientific-review.json",
            verify_files=True,
        )
        _verify_completed_scientific_delivery_gate(
            root=root,
            report=report,
            final_review=completed_review,
        )
        _verify_source_inventory(root, report)
        returned = dict(report)
        returned["delivery_report_path"] = (root / "delivery-report.json").as_posix()
        returned["delivery_report_sha256"] = _sha256_file(root / "delivery-report.json")
        returned["resume_action"] = "already_complete_no_model_call"
        returned["memory_resume"] = _reverify_existing_memory_receipts(
            root=root,
            report=report,
            vault_root=context_vault_root,
        )
        return returned
    _raise_if_existing_scientific_review_block(root=root, direction=direction)
    literature_preexisting = {
        "broad": (root / "literature" / "broad" / "direction-literature.json").is_file(),
        "focus": (root / "literature" / "refinement" / "direction-focus.json").is_file(),
        "targeted": (
            root / "literature" / "refinement" / "direction-targeted-retrieval.json"
        ).is_file(),
    }
    gap_provider_escrow_before = provider_checkpoint_count(
        root,
        stage_name="planning-literature-gap-repair-query",
    )
    context_runtime = ContestDirectionContextRuntime(
        direction_id=direction_id,
        output_dir=root / "context-memory",
        vault_root=context_vault_root,
        capability_cache_dir=context_capability_cache_dir,
        **({"completion": context_completion} if context_completion is not None else {}),
    )
    context_runtime.verify_official_capability(config_path=config_path)
    memory_bridge = _start_memory_bridge(
        root=root,
        direction_id=direction_id,
        vault_root=context_vault_root,
        context_runtime=context_runtime,
    )
    memory_stages: dict[str, dict[str, Any]] = {}
    memory_recalls: dict[str, dict[str, Any]] = {}
    shared_searchers, shared_status_verifier = _shared_literature_boundaries(
        literature_searchers=literature_searchers,
        arxiv_status_verifier=arxiv_status_verifier,
    )
    literature_state = _prepare_two_stage_literature(
        parent_direction=direction,
        direction_input_hash=str(direction_payload["input_hash"]),
        root=root,
        context_runtime=context_runtime,
        memory_bridge=memory_bridge,
        memory_stages=memory_stages,
        config_path=config_path,
        env_path=env_path,
        timeout_seconds=timeout_seconds,
        max_results_per_search=max_results_per_search,
        retrieval_max_tokens=retrieval_max_tokens,
        shared_searchers=shared_searchers,
        shared_status_verifier=shared_status_verifier,
        literature_runner=literature_runner,
        focus_selection_runner=focus_selection_runner,
        targeted_retrieval_runner=targeted_retrieval_runner,
        merged_literature_builder=merged_literature_builder,
        resume=True,
    )
    gap_provider_escrow_after = provider_checkpoint_count(
        root,
        stage_name="planning-literature-gap-repair-query",
    )
    current_gap_repair_provider_calls = gap_provider_escrow_after - gap_provider_escrow_before
    if current_gap_repair_provider_calls not in {0, 1}:
        raise ContestDirectionResearchLoopError(
            "bounded gap-repair resume created an invalid provider-call count"
        )
    literature = literature_state.merged
    planning_catalog = literature_state.planning_catalog
    planning_literature_context = literature_state.planning_context
    excluded_records = literature_state.excluded_records
    finalist_status_path = literature_state.finalist_status_path
    finalist_status_payload = literature_state.finalist_status_payload
    scientific_direction = literature_state.focus.focused_direction_cn

    skill_catalog, skill_bodies = discover_contest_method_skills(skills_root)
    routing_path = root / "skill-routing.json"
    routing_preexisting = routing_path.is_file()
    literature_evidence_context = _skill_routing_two_stage_literature_evidence(
        literature,
        planning_catalog,
        queries=_focused_planning_queries(
            literature_state.focus,
            literature_state.targeted,
            role_queries=literature_state.effective_role_queries,
        ),
        priority_queries=_focused_planning_priority_queries(
            literature_state.focus,
            literature_state.targeted,
            role_queries=literature_state.effective_role_queries,
        ),
        priority_query_groups=_focused_planning_priority_query_groups(
            literature_state.focus,
            literature_state.targeted,
            role_queries=literature_state.effective_role_queries,
        ),
    )
    reasoning_literature_catalog = _catalog_subset_by_record_ids(
        planning_catalog,
        getattr(literature_evidence_context, "record_ids", ())
        or tuple(str(item.get("record_id") or "") for item in planning_catalog),
    )
    routing_stage_input_hash = canonical_model_hash(
        {
            "direction_input_hash": direction_payload["input_hash"],
            "broad_literature_artifact_hash": literature_state.broad.artifact_hash,
            "focus_artifact_hash": literature_state.focus.artifact_hash,
            "targeted_literature_artifact_hash": literature_state.targeted.artifact_hash,
            "merged_literature_artifact_hash": literature.artifact_hash,
            "planning_literature_artifact_hash": literature_state.planning_lock_payload[
                "artifact_hash"
            ],
            "planning_catalog_hash": canonical_model_hash({"catalog": list(planning_catalog)}),
            "literature_evidence_context_hash": canonical_model_hash(
                literature_evidence_context.model_dump(mode="json")
            ),
            "skill_catalog": [item.model_dump(mode="json") for item in skill_catalog],
        }
    )
    if routing_path.is_file():
        try:
            routing = load_contest_direct_skill_routing(routing_path)
        except Exception as exc:
            raise ContestDirectionResearchLoopError("resume Skill routing is invalid") from exc
    else:
        routing_kwargs: dict[str, Any] = {
            "question": scientific_direction,
            "requirements": _LOOP_REQUIREMENTS,
            "skill_catalog": skill_catalog,
            "literature_evidence_context": literature_evidence_context,
            "config_path": config_path,
            "env_path": env_path,
            "output_path": routing_path,
            "timeout_seconds": timeout_seconds,
            "max_tokens": skill_routing_max_tokens,
        }
        with context_runtime.checkpointed_stage(
            "skill-routing",
            input_hash=routing_stage_input_hash,
            checkpoint_root=root,
        ) as completion:
            routing_kwargs["llm_call"] = completion
            routing = skill_router(**routing_kwargs)
    if (
        routing.schema_version != "contest-direct-skill-routing-v3"
        or routing.literature_retrieval_artifact_hash is not None
        or routing.literature_evidence_context != literature_evidence_context
        or routing.merged_literature_artifact_hash != literature.artifact_hash
        or routing.skill_bodies_visible_to_selector
    ):
        raise ContestDirectionResearchLoopError(
            "resume Skill routing is not bound to post-retrieval evidence"
        )
    selected_skills = _load_selected_skills(routing, skill_bodies)
    skill_manifest_path = root / "selected-method-skills.json"
    if not skill_manifest_path.is_file():
        _write_selected_skill_manifest(
            skill_manifest_path,
            routing_path=routing_path,
            routing=routing,
            selected_skills=selected_skills,
            merged_literature=literature,
            planning_literature_artifact_hash=literature_state.planning_lock_payload[
                "artifact_hash"
            ],
        )
    skill_manifest = _read_json(skill_manifest_path)
    if skill_manifest.get("manifest_hash") != canonical_model_hash(
        {key: value for key, value in skill_manifest.items() if key != "manifest_hash"}
    ):
        raise ContestDirectionResearchLoopError("resume selected Skill manifest hash mismatch")
    if (
        skill_manifest.get("routing_artifact_hash") != routing.artifact_hash
        or skill_manifest.get("merged_literature_artifact_hash") != literature.artifact_hash
        or skill_manifest.get("planning_literature_artifact_hash")
        != literature_state.planning_lock_payload["artifact_hash"]
        or [item.get("skill_id") for item in skill_manifest.get("skills", [])]
        != list(routing.selected_skill_ids)
    ):
        raise ContestDirectionResearchLoopError("resume selected Skill manifest binding mismatch")
    record_completed_stage(
        root=root,
        ordinal=5,
        stage_name="skill-routing",
        stage_input_hash=routing_stage_input_hash,
        artifacts=(routing_path, skill_manifest_path),
    )
    memory_stages["skill-routing"] = _capture_stage_memory(
        memory_bridge,
        stage="skill-routing",
        artifact_paths=(routing_path, skill_manifest_path),
    )
    skill_contexts = tuple(_temporary_skill_context(item) for item in selected_skills)

    from autoresearch.competition.contest_direction_hypothesis_stage import (
        load_contest_direction_hypothesis_brainstorm,
        load_contest_postpilot_objective_review,
        run_contest_direction_hypothesis_brainstorm,
        run_contest_postpilot_objective_review,
    )

    direction_ref = TemporaryAgentInputRef(
        artifact_id=literature_state.focus.selected_focus_id,
        source_ref=literature_state.focus_path.as_posix(),
        sha256=_sha256_file(literature_state.focus_path),
    )
    hypothesis_stage_input_hash = canonical_model_hash(
        {
            "direction_input_hash": direction_payload["input_hash"],
            "merged_literature_artifact_hash": literature.artifact_hash,
            "planning_catalog_hash": canonical_model_hash({"catalog": list(planning_catalog)}),
            "skill_routing_artifact_hash": routing.artifact_hash,
            "selected_skill_hashes": routing.selected_skill_hashes,
            "executable_adapters": [_ADAPTER_DESCRIPTOR],
        }
    )
    hypothesis_root = root / "hypothesis-stage"
    hypothesis_path = hypothesis_root / "direction-hypothesis-brainstorm.json"
    hypothesis_preexisting = hypothesis_path.is_file()
    if hypothesis_path.is_file():
        try:
            hypotheses = load_contest_direction_hypothesis_brainstorm(
                hypothesis_path,
                verify_batch_files=True,
            )
        except Exception as exc:
            raise ContestDirectionResearchLoopError(
                "resume hypothesis checkpoint is invalid"
            ) from exc
    else:
        _quarantine_partial_output(root, hypothesis_root, hypothesis_stage_input_hash)
        controller, capability = issue_stage_controller(
            lineage_id=direction_id,
            stage="direction-hypothesis-brainstorm",
            stage_attempt=1,
            controller_agent_id="contest-direction-research-loop-main-agent",
            stage_input_hash=hypothesis_stage_input_hash,
            max_parallel_agents=3,
        )
        runner = hypothesis_stage_runner or run_contest_direction_hypothesis_brainstorm
        with context_runtime.checkpointed_stage(
            "hypothesis-brainstorm",
            input_hash=hypothesis_stage_input_hash,
            checkpoint_root=root,
        ) as completion:
            hypotheses = runner(
                direction=scientific_direction,
                requirements="\n".join(_LOOP_REQUIREMENTS),
                direction_ref=direction_ref,
                parent_task_id=f"{direction_id}-research-loop",
                controller=controller,
                capability=capability,
                output_dir=hypothesis_root,
                selected_skill_contexts=skill_contexts,
                retrieved_literature_catalog=reasoning_literature_catalog,
                executable_adapters=(_ADAPTER_DESCRIPTOR,),
                completion=completion,
                config_path=config_path,
                env_path=env_path,
                max_tokens_per_agent=brainstorm_max_tokens,
                timeout_seconds=timeout_seconds,
                thinking_budget=thinking_budget,
                temperature=0.35,
            )
        if capability.active:
            raise ContestDirectionResearchLoopError("resumed hypothesis capability remained active")
    if hypotheses.direction != scientific_direction:
        raise ContestDirectionResearchLoopError("resume hypothesis direction mismatch")
    record_completed_stage(
        root=root,
        ordinal=6,
        stage_name="hypothesis-brainstorm",
        stage_input_hash=hypothesis_stage_input_hash,
        artifacts=(hypothesis_path,),
    )
    memory_stages["hypothesis-brainstorm"] = _capture_stage_memory(
        memory_bridge,
        stage="hypothesis-brainstorm",
        artifact_paths=(hypothesis_root,),
    )

    selected_candidate = _select_executable_candidate(
        hypotheses,
        direction=scientific_direction,
        selected_skill_ids=routing.selected_skill_ids,
    )
    adapter_receipt_path, adapter_receipt = _resume_adapter_selection(
        root=root,
        direction=scientific_direction,
        routing=routing,
        literature=literature,
        hypotheses=hypotheses,
        selected_candidate=selected_candidate,
    )
    if selected_candidate is None:  # defensive narrowing after receipt verification
        raise ContestDirectionResearchLoopError("resume adapter selected no executable candidate")

    provisional_path = root / "internal" / "provisional-pilot-base-plan.json"
    provisional_preexisting = provisional_path.is_file()
    provisional_stage_input_hash = canonical_model_hash(
        {
            "direction_input_hash": direction_payload["input_hash"],
            "merged_literature_artifact_hash": literature.artifact_hash,
            "skill_routing_artifact_hash": routing.artifact_hash,
            "hypothesis_artifact_hash": _artifact_hash(hypotheses),
            "selected_candidate": selected_candidate,
        }
    )
    if provisional_path.is_file():
        try:
            provisional = load_contest_direct_plan(provisional_path)
        except Exception as exc:
            raise ContestDirectionResearchLoopError(
                "resume provisional plan checkpoint is invalid"
            ) from exc
    else:
        with context_runtime.checkpointed_stage(
            "provisional-plan",
            input_hash=provisional_stage_input_hash,
            checkpoint_root=root,
        ) as completion:
            provisional = plan_generator(
                scientific_problem=scientific_direction,
                literature_context=planning_literature_context,
                preexperiment_context=None,
                method_skills=tuple(item["content"] for item in selected_skills),
                temporary_agent_context={
                    "context_kind": "selected_executable_candidate_before_pilot",
                    "candidate": selected_candidate,
                    "boundary_zh": "内部pilot基线；尚无预实验结果，不得虚构观察。",
                },
                config_path=config_path,
                env_path=env_path,
                output_path=provisional_path,
                timeout_seconds=timeout_seconds,
                max_tokens=plan_max_tokens,
                thinking_mode="disabled",
                thinking_budget=None,
                temperature=0.2,
                llm_call=completion,
            )
    _verify_plan_references(
        provisional,
        literature_context=planning_literature_context,
        minimum_references=MIN_RESEARCH_PLAN_REFERENCES,
        maximum_references=MAX_RESEARCH_PLAN_REFERENCES,
    )
    record_completed_stage(
        root=root,
        ordinal=7,
        stage_name="provisional-plan",
        stage_input_hash=provisional_stage_input_hash,
        artifacts=(provisional_path,),
    )
    memory_stages["provisional-plan"] = _capture_stage_memory(
        memory_bridge,
        stage="provisional-plan",
        artifact_paths=(provisional_path,),
    )

    pilot_brief_path = root / "preexperiment" / "pilot-brief.json"
    if not pilot_brief_path.is_file():
        _write_new_json(
            pilot_brief_path,
            _pilot_brief_payload(
                direction=scientific_direction,
                direction_input_hash=direction_payload["input_hash"],
                literature=literature,
                routing=routing,
                hypotheses=hypotheses,
                selected_candidate=selected_candidate,
                provisional_plan=provisional,
            ),
        )
    pilot_brief = _read_json(pilot_brief_path)
    if pilot_brief.get("artifact_hash") != canonical_model_hash(
        {key: value for key, value in pilot_brief.items() if key != "artifact_hash"}
    ):
        raise ContestDirectionResearchLoopError("resume pilot brief hash mismatch")
    if (
        pilot_brief.get("direction") != scientific_direction
        or pilot_brief.get("merged_literature_artifact_hash") != literature.artifact_hash
        or pilot_brief.get("skill_routing_artifact_hash") != routing.artifact_hash
        or pilot_brief.get("hypothesis_artifact_hash") != _artifact_hash(hypotheses)
        or pilot_brief.get("provisional_plan_artifact_hash") != provisional.artifact_hash
        or (pilot_brief.get("selected_candidate") or {}).get("candidate_id")
        != selected_candidate.get("candidate_id")
    ):
        raise ContestDirectionResearchLoopError("resume pilot brief lineage mismatch")
    pilot_root = root / "preexperiment" / _ADAPTER_ID
    pilot_path = pilot_root / "prime-preexperiment.json"
    if pilot_path.is_file():
        pilot = preexperiment_loader(pilot_path, verify_files=True)
        generated_pilot = pilot
    else:
        _quarantine_partial_output(root, pilot_root, _sha256_file(pilot_brief_path))
        generated_pilot = preexperiment_runner(
            output_dir=pilot_root,
            source_plan_path=pilot_brief_path,
        )
        pilot = preexperiment_loader(pilot_path, verify_files=True)
    _verify_prime_pilot(
        pilot,
        generated=generated_pilot,
        source_snapshot_sha256=_sha256_file(pilot_brief_path),
    )
    final_reference_catalog = build_postpilot_reference_catalog(
        planning_literature_context,
        getattr(pilot, "references", ()),
    )
    pilot_stage_input_hash = canonical_model_hash(
        {
            "pilot_brief_sha256": _sha256_file(pilot_brief_path),
            "adapter_id": _ADAPTER_ID,
        }
    )
    record_completed_stage(
        root=root,
        ordinal=8,
        stage_name="real-pilot",
        stage_input_hash=pilot_stage_input_hash,
        artifacts=(pilot_brief_path, pilot_path),
    )
    memory_stages["real-pilot"] = _capture_stage_memory(
        memory_bridge,
        stage="real-pilot",
        artifact_paths=(pilot_brief_path, pilot_root),
    )

    postpilot_root = root / "postpilot-stage"
    postpilot_path = postpilot_root / "postpilot-objective-review.json"
    postpilot_preexisting = postpilot_path.is_file()
    postpilot_recall_preexisting = (
        root / "memory" / "recalls" / "postpilot-objective-review.json"
    ).is_file()
    postpilot_memory_context, memory_recalls["postpilot-objective-review"] = _recall_stage_memory(
        memory_bridge,
        consumer_stage="postpilot-objective-review",
        source_stages=(
            "broad-literature-query",
            "focus-selection",
            "targeted-literature-query",
            "planning-literature-lock",
            "skill-routing",
            "hypothesis-brainstorm",
            "provisional-plan",
            "real-pilot",
        ),
        requested=(
            dreaming_recall_enabled and (not postpilot_preexisting or postpilot_recall_preexisting)
        ),
    )
    stage_hash = _memory_bound_input_hash(
        {
            "direction_input_hash": direction_payload["input_hash"],
            "hypothesis_artifact_hash": _artifact_hash(hypotheses),
            "selected_candidate_id": selected_candidate.get("candidate_id"),
            "pilot_brief_sha256": _sha256_file(pilot_brief_path),
            "preexperiment_artifact_hash": pilot.artifact_hash,
            "skill_routing_artifact_hash": routing.artifact_hash,
            "merged_literature_artifact_hash": literature.artifact_hash,
        },
        postpilot_memory_context,
    )
    stage_hash = _reuse_preexisting_stage_input_hash(
        root=root,
        ordinal=9,
        stage_name="postpilot-objective-review",
        computed_hash=stage_hash,
        artifact_preexisting=postpilot_preexisting,
    )
    if postpilot_preexisting:
        postpilot = load_contest_postpilot_objective_review(
            postpilot_path,
            verify_inputs=True,
        )
    else:
        _quarantine_partial_output(root, postpilot_root, stage_hash)
        if postpilot_stage_runner is None:
            postpilot_stage_runner = run_contest_postpilot_objective_review
        controller, capability = issue_stage_controller(
            lineage_id=direction_id,
            stage="direction-postpilot-objective-review",
            stage_attempt=1,
            controller_agent_id="contest-direction-research-loop-main-agent",
            stage_input_hash=stage_hash,
            max_parallel_agents=1,
        )
        with context_runtime.checkpointed_stage(
            "postpilot-objective-review",
            input_hash=stage_hash,
            checkpoint_root=root,
        ) as context_completion:
            postpilot = postpilot_stage_runner(
                direction=scientific_direction,
                requirements="\n".join(_LOOP_REQUIREMENTS),
                direction_ref=direction_ref,
                parent_task_id=f"{direction_id}-research-loop",
                controller=controller,
                capability=capability,
                output_dir=postpilot_root,
                brainstorm_artifact_path=hypothesis_path,
                pilot_brief_path=pilot_brief_path,
                preexperiment_artifact_path=pilot_path,
                selected_skill_contexts=skill_contexts,
                retrieved_literature_catalog=reasoning_literature_catalog,
                derived_memory_context=postpilot_memory_context,
                completion=context_completion,
                config_path=config_path,
                env_path=env_path,
                max_tokens=max(feedback_max_tokens, objective_review_max_tokens),
                timeout_seconds=timeout_seconds,
                thinking_budget=thinking_budget,
                temperature=0.2,
            )
        if capability.active:
            raise ContestDirectionResearchLoopError("resumed postpilot capability remained active")
    record_completed_stage(
        root=root,
        ordinal=9,
        stage_name="postpilot-objective-review",
        stage_input_hash=stage_hash,
        artifacts=(postpilot_path, pilot_path),
    )
    memory_stages["postpilot-objective-review"] = _capture_stage_memory(
        memory_bridge,
        stage="postpilot-objective-review",
        artifact_paths=(postpilot_root,),
    )
    postpilot_context = _postpilot_plan_context(postpilot)

    plan_path = root / "system-authored-revised-research-plan.json"
    plan_preexisting = plan_path.is_file()
    revision_recall_preexisting = (
        root / "memory" / "recalls" / "final-plan-revision.json"
    ).is_file()
    revision_replay = (
        None if plan_preexisting else _load_preserved_revision_replay(root / "revision")
    )
    revision_memory_context, memory_recalls["final-plan-revision"] = _recall_stage_memory(
        memory_bridge,
        consumer_stage="final-plan-revision",
        source_stages=(
            "broad-literature-query",
            "focus-selection",
            "targeted-literature-query",
            "planning-literature-lock",
            "skill-routing",
            "hypothesis-brainstorm",
            "provisional-plan",
            "real-pilot",
            "postpilot-objective-review",
        ),
        requested=(
            dreaming_recall_enabled
            and (revision_recall_preexisting or (not plan_preexisting and revision_replay is None))
        ),
    )
    base_revision_requirements = (
        *_LOOP_REQUIREMENTS,
        *_REVISION_RESULT_REQUIREMENTS,
        "内部 provisional 只作证据修订基线，不得当作最终计划或已完成研究。",
        "以下是预实验后的独立目标评审上下文（模型判断，不是额外实验事实）："
        + json.dumps(postpilot_context, ensure_ascii=False, sort_keys=True),
    )
    revision_stage_input_hash = _memory_bound_input_hash(
        {
            "provisional_plan_artifact_hash": provisional.artifact_hash,
            "preexperiment_artifact_hash": pilot.artifact_hash,
            "postpilot_objective_artifact_hash": _artifact_hash(postpilot),
            "reference_catalog": list(final_reference_catalog),
            "selected_skill_hashes": routing.selected_skill_hashes,
            "revision_requirements": list(base_revision_requirements),
        },
        revision_memory_context,
    )
    revision_stage_input_hash = _reuse_preexisting_stage_input_hash(
        root=root,
        ordinal=10,
        stage_name="final-plan-revision",
        computed_hash=revision_stage_input_hash,
        artifact_preexisting=plan_preexisting,
    )
    revision_replay_used = False
    if plan_preexisting:
        try:
            plan = ContestDirectPlanRevisionArtifact.model_validate_json(
                plan_path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise ContestDirectionResearchLoopError(
                "resume final revision artifact is invalid"
            ) from exc
        _verify_revision_sidecars(root / "revision", plan)
    else:
        # 数字守卫拒绝属于模型输出质量问题：把拒绝原因追加为一条新要求、抖动温度
        # 后重试（重放响应与全新检查点阶段统一走同一循环）；证据绑定类失败不重试。
        revision_requirements: tuple[str, ...] = base_revision_requirements
        guard_reason: str | None = None
        revised_plan: ContestDirectPlanRevisionArtifact | None = None
        for attempt_index, temperature in enumerate((0.2, 0.4, 0.6), start=1):
            attempt_hash = (
                revision_stage_input_hash
                if attempt_index == 1
                else _memory_bound_input_hash(
                    {
                        "provisional_plan_artifact_hash": provisional.artifact_hash,
                        "preexperiment_artifact_hash": pilot.artifact_hash,
                        "postpilot_objective_artifact_hash": _artifact_hash(postpilot),
                        "reference_catalog": list(final_reference_catalog),
                        "selected_skill_hashes": routing.selected_skill_hashes,
                        "revision_requirements": list(revision_requirements),
                    },
                    revision_memory_context,
                )
            )
            try:
                if attempt_index == 1 and revision_replay is not None:
                    revision_replay_used = True
                    revised_plan = plan_revision_runner(
                        original_plan=provisional,
                        scientific_problem=scientific_direction,
                        requirements=revision_requirements,
                        selected_skill_contexts=tuple(
                            {"skill_id": item["skill_id"], "content": item["content"]}
                            for item in selected_skills
                        ),
                        reference_catalog=final_reference_catalog,
                        preexperiment_artifact=pilot_path,
                        preexperiment_metrics=None,
                        preexperiment_root=pilot_root,
                        derived_memory_context=revision_memory_context,
                        output_dir=root / "revision",
                        output_path=plan_path,
                        config_path=config_path,
                        env_path=env_path,
                        timeout_seconds=timeout_seconds,
                        max_tokens=plan_max_tokens,
                        temperature=temperature,
                        llm_call=revision_replay,
                    )
                else:
                    with context_runtime.checkpointed_stage(
                        "final-plan-revision",
                        input_hash=attempt_hash,
                        checkpoint_root=root,
                    ) as context_completion:
                        revised_plan = plan_revision_runner(
                            original_plan=provisional,
                            scientific_problem=scientific_direction,
                            requirements=revision_requirements,
                            selected_skill_contexts=tuple(
                                {"skill_id": item["skill_id"], "content": item["content"]}
                                for item in selected_skills
                            ),
                            reference_catalog=final_reference_catalog,
                            preexperiment_artifact=pilot_path,
                            preexperiment_metrics=None,
                            preexperiment_root=pilot_root,
                            derived_memory_context=revision_memory_context,
                            output_dir=root / "revision",
                            output_path=plan_path,
                            config_path=config_path,
                            env_path=env_path,
                            timeout_seconds=timeout_seconds,
                            max_tokens=plan_max_tokens,
                            temperature=temperature,
                            llm_call=context_completion,
                        )
                break
            except ContestDirectPlanNumberGuardError as exc:
                guard_reason = str(exc)
                if attempt_index >= 3:
                    raise
                revision_requirements = (
                    *revision_requirements,
                    _revision_guard_retry_requirement(guard_reason or ""),
                )
        if revised_plan is None:  # pragma: no cover - exhaustion re-raises the guard error
            raise ContestDirectionResearchLoopError(
                "final plan revision produced no artifact"
            )
        plan = revised_plan
    _verify_plan_references(
        plan,
        literature_context=final_reference_catalog,
        minimum_references=MIN_RESEARCH_PLAN_REFERENCES,
        maximum_references=MAX_RESEARCH_PLAN_REFERENCES,
    )
    record_completed_stage(
        root=root,
        ordinal=10,
        stage_name="final-plan-revision",
        stage_input_hash=revision_stage_input_hash,
        artifacts=(plan_path,),
    )
    memory_stages["final-plan-revision"] = _capture_stage_memory(
        memory_bridge,
        stage="final-plan-revision",
        artifact_paths=(root / "revision", plan_path),
    )

    plan_root = root / "plan"
    if (plan_root / "research-plan.json").is_file():
        rendered = _load_rendered_plan(plan_root)
    else:
        render_payload = plan.flat_payload()
        embedded_evidence = build_contest_plan_embedded_evidence(
            pilot,
            artifact_path=pilot_path,
            preexperiment_root=pilot_root,
        )
        if embedded_evidence is not None:
            render_payload["embedded_evidence"] = embedded_evidence.payload
        render_payload.update(
            {
                "document_type": "含真实探索性预实验结果的科学假设与研究计划",
                "status": "generated_after_verified_preexperiment_and_objective_review",
                "specified_direction": direction,
                "focused_direction": scientific_direction,
                "generation": {
                    "provider": plan.provider,
                    "model_name": plan.model_name,
                    "generation_calls": plan.generation_calls,
                    "input_hash": plan.input_hash,
                    "model_response_hash": plan.model_response_hash,
                    "artifact_hash": plan.artifact_hash,
                    "provisional_plan_artifact_hash": provisional.artifact_hash,
                    "final_revision_id": plan.revision_id,
                },
                "preexperiment": {
                    "adapter_id": _ADAPTER_ID,
                    "run_id": pilot.run_id,
                    "artifact_hash": pilot.artifact_hash,
                    "metrics_sha256": pilot.metrics_sha256,
                    "manifest_sha256": pilot.manifest_sha256,
                    "study_phase": pilot.study_phase,
                    "formal_experiment_executed": False,
                    "mathematical_proof_claimed": False,
                },
                "postpilot_objective": {
                    "artifact_path": postpilot_path.as_posix(),
                    "artifact_hash": _artifact_hash(postpilot),
                },
            }
        )
        rendered = plan_materializer(
            payload=render_payload,
            output_dir=plan_root,
            evidence_bindings=(
                embedded_evidence.manifest_bindings if embedded_evidence is not None else ()
            ),
            overwrite=False,
            timeout_seconds=render_timeout_seconds,
        )
    page_count, page_count_method = _verify_rendered_pdf(rendered)
    render_stage_input_hash = canonical_model_hash(
        {
            "final_plan_artifact_hash": plan.artifact_hash,
            "rendered_source_payload_sha256": rendered.source_payload_sha256,
        }
    )
    record_completed_stage(
        root=root,
        ordinal=11,
        stage_name="render-plan",
        stage_input_hash=render_stage_input_hash,
        artifacts=(
            rendered.json_path,
            rendered.markdown_path,
            rendered.tex_path,
            rendered.pdf_path,
            rendered.manifest_path,
            *((rendered.source_path,) if rendered.source_path is not None else ()),
        ),
    )
    memory_stages["render-plan"] = _capture_stage_memory(
        memory_bridge,
        stage="render-plan",
        artifact_paths=(plan_root,),
    )

    review_root = root / "independent-scientific-review"
    review_path = review_root / "system-plan-scientific-review.json"
    review_preexisting = review_path.is_file()
    review_recall_preexisting = (
        root / "memory" / "recalls" / "independent-scientific-review.json"
    ).is_file()
    review_memory_context, memory_recalls["independent-scientific-review"] = _recall_stage_memory(
        memory_bridge,
        consumer_stage="independent-scientific-review",
        source_stages=(
            "broad-literature-query",
            "focus-selection",
            "targeted-literature-query",
            "planning-literature-lock",
            "skill-routing",
            "hypothesis-brainstorm",
            "provisional-plan",
            "real-pilot",
            "postpilot-objective-review",
            "final-plan-revision",
            "render-plan",
        ),
        requested=(
            dreaming_recall_enabled and (not review_preexisting or review_recall_preexisting)
        ),
    )
    review_stage_input_hash = _memory_bound_input_hash(
        {
            "final_plan_artifact_hash": plan.artifact_hash,
            "rendered_source_payload_sha256": rendered.source_payload_sha256,
            "preexperiment_artifact_hash": pilot.artifact_hash,
            "reference_catalog": list(final_reference_catalog),
            "selected_skill_hashes": routing.selected_skill_hashes,
        },
        review_memory_context,
    )
    review_stage_input_hash = _reuse_preexisting_stage_input_hash(
        root=root,
        ordinal=12,
        stage_name="independent-scientific-review",
        computed_hash=review_stage_input_hash,
        artifact_preexisting=review_preexisting,
    )
    if review_preexisting:
        final_review = load_contest_direct_plan_scientific_review(
            review_path,
            verify_files=True,
        )
    else:
        with context_runtime.checkpointed_stage(
            "independent-scientific-review",
            input_hash=review_stage_input_hash,
            checkpoint_root=root,
        ) as context_completion:
            final_review = scientific_review_runner(
                final_plan=rendered.json_path,
                preexperiment_artifact=pilot_path,
                reference_catalog=final_reference_catalog,
                selected_skill_contexts=tuple(
                    {"name": item["skill_id"], "content": item["content"]}
                    for item in selected_skills
                ),
                preexperiment_metrics=None,
                preexperiment_root=pilot_root,
                derived_memory_context=review_memory_context,
                output_dir=review_root,
                config_path=config_path,
                env_path=env_path,
                timeout_seconds=timeout_seconds,
                max_tokens=scientific_review_max_tokens,
                temperature=0.2,
                require_exact_reference_catalog=True,
                llm_call=context_completion,
            )

    record_completed_stage(
        root=root,
        ordinal=12,
        stage_name="independent-scientific-review",
        stage_input_hash=review_stage_input_hash,
        artifacts=(review_path,),
    )
    memory_stages["independent-scientific-review"] = _capture_stage_memory(
        memory_bridge,
        stage="independent-scientific-review",
        artifact_paths=(review_root,),
    )
    _enforce_scientific_review_delivery_gate(
        root=root,
        direction=direction,
        focused_direction=literature_state.focus.focused_direction_cn,
        final_review=final_review,
        review_path=review_path,
    )
    current_scientific_model_calls = (
        (0 if literature_preexisting["broad"] else literature_state.broad.query_model_calls)
        + (
            0
            if literature_preexisting["focus"]
            else literature_state.focus.model_call_count_at_creation
        )
        + (0 if literature_preexisting["targeted"] else literature_state.targeted.query_model_calls)
        + current_gap_repair_provider_calls
        + (0 if routing_preexisting else routing.model_calls)
        + (0 if hypothesis_preexisting else _model_call_count(hypotheses))
        + (0 if provisional_preexisting else provisional.generation_calls)
        + (0 if postpilot_preexisting else _model_call_count(postpilot))
        + (0 if plan_preexisting or revision_replay_used else plan.generation_calls)
        + (0 if review_preexisting else final_review.generation_calls)
    )
    resume_accounting = {
        "checkpoint_resume": True,
        "source_delivery_path": root.as_posix(),
        "current_scientific_model_calls": current_scientific_model_calls,
        "historical_failed_plan_author_calls": 0,
        "historical_postprovider_validation_failures": (1 if revision_replay_used else 0),
        "preserved_revision_replayed_locally": revision_replay_used,
        "current_postpilot_provider_calls": (
            0 if postpilot_preexisting else _model_call_count(postpilot)
        ),
        "current_gap_repair_provider_calls": current_gap_repair_provider_calls,
        "current_revision_provider_calls": (
            0 if plan_preexisting or revision_replay_used else plan.generation_calls
        ),
        "current_final_review_provider_calls": (
            0 if review_preexisting else final_review.generation_calls
        ),
        "source_model_call_accounting": {
            "broad_retrieval_query_calls": literature_state.broad.query_model_calls,
            "focus_brainstorm_and_selection_calls": (
                literature_state.focus.model_call_count_at_creation
            ),
            "targeted_retrieval_query_calls": literature_state.targeted.query_model_calls,
            "planning_literature_gap_repair_calls": (
                literature_state.gap_response.model_calls
                if literature_state.gap_response is not None
                else 0
            ),
            "literature_aware_skill_routing_calls": routing.model_calls,
            "hypothesis_brainstorm_calls": _model_call_count(hypotheses),
            "internal_provisional_plan_calls": provisional.generation_calls,
            "failed_postpilot_calls_before_provider_invocation": 0,
            "postpilot_objective_review_calls": (
                _model_call_count(postpilot) if postpilot_preexisting else 0
            ),
            "final_revision_provider_calls": (
                plan.generation_calls if plan_preexisting or revision_replay_used else 0
            ),
            "final_revision_postprovider_validation_failures": (1 if revision_replay_used else 0),
            "final_independent_scientific_review_calls": (
                final_review.generation_calls if review_preexisting else 0
            ),
        },
    }
    report = _completed_report(
        root=root,
        direction=direction,
        literature_state=literature_state,
        source_accounting=resume_accounting,
        direction_input_path=direction_input_path,
        literature=literature,
        finalist_status_path=finalist_status_path,
        finalist_status_payload=finalist_status_payload,
        excluded_records=excluded_records,
        routing=routing,
        routing_path=routing_path,
        skill_manifest_path=skill_manifest_path,
        hypotheses=hypotheses,
        hypothesis_path=hypothesis_path,
        adapter_receipt_path=adapter_receipt_path,
        pilot_brief_path=pilot_brief_path,
        pilot=pilot,
        pilot_path=pilot_path,
        postpilot=postpilot,
        postpilot_path=postpilot_path,
        provisional=provisional,
        provisional_path=provisional_path,
        plan=plan,
        plan_path=plan_path,
        rendered=rendered,
        page_count=page_count,
        page_count_method=page_count_method,
        final_review=final_review,
        review_root=review_root,
    )
    report["memory"] = _memory_delivery_summary(
        stages=memory_stages,
        recalls=memory_recalls,
    )
    report["resume"] = {
        "resumed_existing_checkpoint": True,
        "all_preexisting_artifacts_rehashed": True,
        "broad_retrieval_rerun": not literature_preexisting["broad"],
        "focus_selection_rerun": not literature_preexisting["focus"],
        "targeted_retrieval_rerun": not literature_preexisting["targeted"],
        "skill_routing_rerun": not routing_preexisting,
        "hypothesis_brainstorm_rerun": not hypothesis_preexisting,
        "provisional_plan_rerun": not provisional_preexisting,
        "preexperiment_rerun": False,
    }
    report_path = root / "delivery-report.json"
    _write_new_json(report_path, report)
    returned = dict(report)
    returned["delivery_report_path"] = report_path.as_posix()
    returned["delivery_report_sha256"] = _sha256_file(report_path)
    return returned


def _delivery_source_checkpoint_accounting(
    *,
    root: Path,
    provenance: Mapping[str, Any] | None,
) -> dict[str, Any]:
    accounting = research_loop_source_checkpoint_accounting(root)
    merged = dict(provenance or {})
    for key, value in accounting.items():
        if key in merged and merged[key] != value:
            raise ContestDirectionResearchLoopError(
                f"source provenance conflicts with checkpoint accounting: {key}"
            )
        merged[key] = value
    return merged


def _verify_persisted_source_checkpoint_accounting(
    *,
    root: Path,
    persisted: object,
) -> None:
    direction_input = _read_json(root / "direction-input.json")
    protocol = direction_input.get("source_accounting_protocol")
    if protocol not in {None, _SOURCE_ACCOUNTING_PROTOCOL}:
        raise ContestDirectionResearchLoopError("source-accounting protocol marker is invalid")
    required = protocol == _SOURCE_ACCOUNTING_PROTOCOL
    if persisted is None:
        if required:
            raise ContestDirectionResearchLoopError(
                "current source-accounting protocol requires a complete report ledger"
            )
        return
    if not isinstance(persisted, Mapping):
        raise ContestDirectionResearchLoopError("source checkpoint accounting is invalid")
    current = research_loop_source_checkpoint_accounting(root)
    present = {key for key in current if key in persisted}
    if not present:
        if required:
            raise ContestDirectionResearchLoopError(
                "current source-accounting report ledger is missing"
            )
        return
    if present != set(current) or any(
        persisted.get(key) != value for key, value in current.items()
    ):
        raise ContestDirectionResearchLoopError(
            "source checkpoint accounting differs from verified local checkpoints"
        )


def _resume_no_adapter_terminal(
    *,
    root: Path,
    direction: str,
    vault_root: Path | str,
) -> dict[str, Any] | None:
    delivery_path = root / "delivery-report.json"
    blocked_path = root / "blocked-receipt.json"
    candidates = tuple(path for path in (delivery_path, blocked_path) if path.is_file())
    if not candidates:
        return None
    if len(candidates) != 1:
        raise ContestDirectionResearchLoopError(
            "no-adapter terminal has conflicting delivery and blocked receipts"
        )
    report_path = candidates[0]
    report = _read_json(report_path)
    expected_status = (
        "completed_without_preexperiment_no_compatible_adapter"
        if report_path == delivery_path
        else "blocked_no_compatible_real_preexperiment_adapter"
    )
    if report.get("status") != expected_status:
        if report_path == delivery_path:
            return None
        raise ContestDirectionResearchLoopError(
            "existing blocked receipt is not a no-adapter terminal"
        )
    if report.get("report_hash") != canonical_model_hash(
        {key: value for key, value in report.items() if key != "report_hash"}
    ):
        raise ContestDirectionResearchLoopError("no-adapter terminal report hash mismatch")
    if (
        report.get("schema_version") != _DELIVERY_SCHEMA
        or report.get("literature_protocol") != _LITERATURE_PROTOCOL
        or report.get("direction") != direction
        or report.get("preexperiment_executed") is not False
        or report.get("formal_experiment_executed") is not False
        or report.get("paper_claimed") is not False
    ):
        raise ContestDirectionResearchLoopError(
            "no-adapter terminal report identity or evidence boundary is invalid"
        )
    _verify_persisted_source_checkpoint_accounting(
        root=root,
        persisted=report.get("source_accounting"),
    )
    literature_state = _load_completed_two_stage_literature(root)
    focused_direction = literature_state.focus.focused_direction_cn
    if report.get("focused_direction") != focused_direction:
        raise ContestDirectionResearchLoopError(
            "no-adapter terminal focused direction differs from verified literature"
        )
    routing_path = root / "skill-routing.json"
    routing = load_contest_direct_skill_routing(routing_path)
    from autoresearch.competition.contest_direction_hypothesis_stage import (
        load_contest_direction_hypothesis_brainstorm,
    )

    hypothesis_path = root / "hypothesis-stage" / "direction-hypothesis-brainstorm.json"
    hypotheses = load_contest_direction_hypothesis_brainstorm(
        hypothesis_path,
        verify_batch_files=True,
    )
    if hypotheses.direction != focused_direction:
        raise ContestDirectionResearchLoopError("no-adapter terminal hypothesis direction mismatch")
    selected_candidate = _select_executable_candidate(
        hypotheses,
        direction=focused_direction,
        selected_skill_ids=routing.selected_skill_ids,
    )
    if selected_candidate is not None:
        raise ContestDirectionResearchLoopError(
            "no-adapter terminal conflicts with an executable candidate"
        )
    adapter_path = root / "preexperiment-adapter-selection.json"
    adapter_receipt = _read_json(adapter_path)
    expected_adapter = _adapter_selection_payload(
        direction=focused_direction,
        routing=routing,
        literature=literature_state.merged,
        hypotheses=hypotheses,
        selected_candidate=None,
    )
    if adapter_receipt != expected_adapter:
        raise ContestDirectionResearchLoopError(
            "no-adapter terminal adapter receipt differs from verified upstream artifacts"
        )
    skill_manifest_path = root / "selected-method-skills.json"
    expected_artifacts = {
        "direction_input": _file_binding(root / "direction-input.json"),
        **_two_stage_literature_artifact_bindings(literature_state),
        "finalist_status_verification": {
            **_file_binding(literature_state.finalist_status_path),
            "artifact_hash": literature_state.finalist_status_payload["artifact_hash"],
        },
        "skill_routing": _file_binding(routing_path),
        "selected_method_skills": _file_binding(skill_manifest_path),
        "hypotheses": _file_binding(hypothesis_path),
        "adapter_selection": _file_binding(adapter_path),
    }
    if report.get("artifacts") != expected_artifacts:
        raise ContestDirectionResearchLoopError(
            "no-adapter terminal artifacts differ from verified local files"
        )
    gap_repair_calls = (
        literature_state.gap_response.model_calls
        if literature_state.gap_response is not None
        else 0
    )
    retrieval_calls = (
        literature_state.broad.query_model_calls
        + literature_state.focus.model_call_count_at_creation
        + literature_state.targeted.query_model_calls
        + gap_repair_calls
    )
    total_calls = retrieval_calls + routing.model_calls + _model_call_count(hypotheses)
    legacy_expected_accounting = {
        "retrieval_query_calls": retrieval_calls,
        "broad_retrieval_query_calls": literature_state.broad.query_model_calls,
        "focus_brainstorm_and_selection_calls": (
            literature_state.focus.model_call_count_at_creation
        ),
        "targeted_retrieval_query_calls": literature_state.targeted.query_model_calls,
        "planning_literature_gap_repair_calls": gap_repair_calls,
        "skill_routing_calls": routing.model_calls,
        "hypothesis_brainstorm_calls": _model_call_count(hypotheses),
        "postpilot_feedback_calls": 0,
        "objective_review_calls": 0,
        "plan_author_calls": 0,
        "final_scientific_review_calls": 0,
        "this_loop_observed_provider_request_attempts": total_calls,
        "historical_source_provider_request_attempts": 0,
        "total_provenance_provider_request_attempts": total_calls,
    }
    current_expected_accounting = {
        **legacy_expected_accounting,
        **_no_adapter_physical_accounting(root),
    }
    persisted_accounting = report.get("model_call_accounting")
    if (
        persisted_accounting != legacy_expected_accounting
        and persisted_accounting != current_expected_accounting
    ):
        raise ContestDirectionResearchLoopError(
            "no-adapter terminal model-call accounting is invalid"
        )
    expected_literature = {
        "retrieval_semantics": literature_state.merged.retrieval_semantics,
        "selected_focus_id": literature_state.focus.selected_focus_id,
        "planning_reference_count": len(literature_state.planning_catalog),
        "finalist_status_verification_artifact_hash": (
            literature_state.finalist_status_payload["artifact_hash"]
        ),
        "finalist_status_verification_count": (
            literature_state.finalist_status_payload["verification_count"]
        ),
        "finalist_status_excluded_records": [
            {
                "record_id": item.get("record_id"),
                "verified_status": item.get("verified_status"),
                "outcome": item.get("outcome"),
            }
            for item in literature_state.finalist_status_payload["records"]
            if item.get("outcome") == "excluded_from_positive_planning"
        ],
    }
    if report.get("literature") != expected_literature:
        raise ContestDirectionResearchLoopError("no-adapter terminal literature summary is invalid")
    if report_path == blocked_path:
        raise ContestDirectionResearchLoopError(
            "no compatible real preexperiment adapter remains blocked; "
            "verified locally with no repeated model call"
        )
    returned = dict(report)
    returned["delivery_report_path"] = delivery_path.as_posix()
    returned["delivery_report_sha256"] = _sha256_file(delivery_path)
    returned["resume_action"] = "already_complete_no_model_call"
    returned["memory_resume"] = _reverify_existing_memory_receipts(
        root=root,
        report=report,
        vault_root=vault_root,
    )
    return returned


def _load_verified_source_literature(
    source: Path,
    *,
    direction: str,
) -> tuple[ContestDirectionLiteratureArtifact, Path, dict[str, Any]]:
    """Replay a complete earlier delivery but reuse only its generic literature.

    A source whose query model saw any Skill is deliberately rejected.  The old
    Skill-first direction delivery is therefore not silently relabelled as a
    generic-retrieval run.
    """

    root = source.expanduser().resolve()
    report_path = root / "delivery-report.json"
    report = _read_json(report_path)
    if report.get("schema_version") != "contest-direction-plan-delivery-v1":
        raise ContestDirectionResearchLoopError("unsupported source direction delivery schema")
    if report.get("status") != "completed" or report.get("direction") != direction:
        raise ContestDirectionResearchLoopError(
            "source direction delivery is incomplete or belongs to another direction"
        )
    _verify_source_inventory(root, report)
    main = report.get("main_artifacts")
    if not isinstance(main, Mapping):
        raise ContestDirectionResearchLoopError("source delivery lacks main_artifacts")

    literature_path = _bound_main_path(root, main, "literature")
    routing_path = _bound_main_path(root, main, "skill_routing")
    objective_path = _bound_main_path(root, main, "research_objective")
    plan_path = _bound_main_path(root, main, "system_authored_plan")
    skill_manifest_path = _bound_main_path(root, main, "selected_method_skills")
    try:
        literature = ContestDirectionLiteratureArtifact.model_validate_json(
            literature_path.read_text(encoding="utf-8")
        )
        routing = load_contest_direct_skill_routing(routing_path)
        objective = ContestResearchObjectiveStageArtifact.model_validate_json(
            objective_path.read_text(encoding="utf-8")
        )
        plan = load_contest_direct_plan(plan_path)
    except Exception as exc:
        raise ContestDirectionResearchLoopError(
            f"source delivery contains an invalid hash-bound artifact: {exc}"
        ) from exc
    _verify_main_artifact_identity(main, "literature", literature.artifact_hash)
    _verify_main_artifact_identity(main, "skill_routing", routing.artifact_hash)
    _verify_main_artifact_identity(main, "research_objective", objective.artifact_hash)
    _verify_main_artifact_identity(main, "system_authored_plan", plan.artifact_hash)
    _verify_source_skill_manifest(skill_manifest_path, routing=routing)
    if literature.direction != direction:
        raise ContestDirectionResearchLoopError("source literature direction mismatch")
    if literature.method_skills:
        raise ContestDirectionResearchLoopError(
            "source literature is Skill-influenced; generic no-Skill retrieval is required"
        )

    accounting = report.get("model_call_accounting")
    if isinstance(accounting, Mapping):
        observed = _nonnegative_int(
            accounting.get("observed_provider_request_attempts"),
            label="source observed provider attempts",
        )
        failed_plan_calls = _nonnegative_int(
            accounting.get("failed_plan_author_calls", 0),
            label="source failed plan author calls",
        )
        preserved = dict(accounting)
    else:
        observed = _nonnegative_int(
            report.get("model_calls"),
            label="source model calls",
        )
        failed_plan_calls = 0
        preserved = {"observed_provider_request_attempts": observed}
    return (
        literature,
        literature_path,
        {
            "source_delivery_path": root.as_posix(),
            "source_delivery_report": _file_binding(report_path),
            "reused_artifact": "generic_real_literature_only",
            "historical_observed_provider_request_attempts": observed,
            "historical_failed_plan_author_calls": failed_plan_calls,
            "source_model_call_accounting": preserved,
        },
    )


_DOI_VERIFICATION_SCHEMA = "contest-direction-finalist-doi-verification-v1"


def _doi_verification_enabled() -> bool:
    """Return whether finalist Crossref DOI verification should run.

    Off by default: the references already come from ArXiv/OpenAlex with real
    identifiers, and the extra Crossref round-trip is an opt-in evidence
    enrichment for deployments that want a title-consistency audit per finalist.
    """

    explicit = os.getenv("AUTORESEARCH_ENABLE_DOI_VERIFICATION")
    return bool(explicit and explicit.strip().lower() in {"1", "true", "yes", "on"})


def _record_finalist_doi_verification(
    path: Path,
    catalog: Sequence[Mapping[str, Any]],
    *,
    resume: bool,
    timeout_seconds: int = 20,
) -> dict[str, Any]:
    """Verify finalist DOIs and persist a non-blocking audit receipt.

    This is an evidence enrichment, not an eligibility gate: a Crossref
    transport error degrades to a per-DOI ``error`` status and never aborts the
    direction loop.  On resume the existing receipt is reused instead of
    re-issuing Crossref requests, matching the finalist-status receipt policy.
    """

    if resume and path.is_file():
        payload = _read_json(path)
        if payload.get("schema_version") == _DOI_VERIFICATION_SCHEMA:
            return payload
    receipt = verify_reference_records(catalog, timeout_seconds=timeout_seconds)
    payload = receipt.to_dict()
    payload["schema_version"] = _DOI_VERIFICATION_SCHEMA
    payload["catalog_record_ids"] = [
        str(item.get("record_id") or "") for item in catalog
    ]
    payload["verification_count"] = len(receipt.verified)
    payload["artifact_hash"] = canonical_model_hash(payload)
    _write_new_json(path, payload)
    return payload


def _write_finalist_status_verification(
    path: Path,
    *,
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    normalized_records = [dict(item) for item in records]
    payload: dict[str, Any] = {
        "schema_version": "contest-direction-finalist-status-verification-v1",
        "scope": "shortlisted_arxiv_records_only",
        "all_candidate_status_requests_forbidden": True,
        "verification_count": sum(
            item.get("verification_attempted") is True for item in normalized_records
        ),
        "records": normalized_records,
    }
    payload["artifact_hash"] = canonical_model_hash(payload)
    _write_new_json(path, payload)
    return payload


def _load_finalist_status_verification(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    records = payload.get("records")
    if (
        payload.get("schema_version") != "contest-direction-finalist-status-verification-v1"
        or payload.get("scope") != "shortlisted_arxiv_records_only"
        or payload.get("all_candidate_status_requests_forbidden") is not True
        or not isinstance(records, list)
        or not all(isinstance(item, Mapping) for item in records)
    ):
        raise ContestDirectionResearchLoopError(
            "resume finalist status verification receipt is invalid"
        )
    expected_hash = canonical_model_hash(
        {key: value for key, value in payload.items() if key != "artifact_hash"}
    )
    if payload.get("artifact_hash") != expected_hash:
        raise ContestDirectionResearchLoopError("resume finalist status verification hash mismatch")
    attempted_count = sum(
        item.get("verification_attempted") is True for item in records if isinstance(item, Mapping)
    )
    if payload.get("verification_count") != attempted_count:
        raise ContestDirectionResearchLoopError(
            "resume finalist status verification count mismatch"
        )
    return payload


def _apply_finalist_status_verification(
    eligible_catalog: Sequence[Mapping[str, Any]],
    literature_context: Sequence[str],
    receipt: Mapping[str, Any],
) -> tuple[tuple[dict[str, Any], ...], tuple[str, ...]]:
    """Replay finalist statuses without making another source request."""

    if len(eligible_catalog) != len(literature_context):
        raise ContestDirectionResearchLoopError(
            "eligible literature and context differ before status replay"
        )
    by_id = {str(item.get("record_id") or ""): item for item in eligible_catalog}
    receipt_records = receipt.get("records")
    if not isinstance(receipt_records, list):
        raise ContestDirectionResearchLoopError("finalist status receipt records are invalid")
    seen: set[str] = set()
    updated: dict[str, dict[str, Any]] = {}
    context_suffixes: dict[str, str] = {}
    for raw in receipt_records:
        if not isinstance(raw, Mapping):
            raise ContestDirectionResearchLoopError("finalist status receipt entry is invalid")
        record_id = str(raw.get("record_id") or "")
        if not record_id or record_id in seen or record_id not in by_id:
            raise ContestDirectionResearchLoopError(
                "finalist status receipt record binding mismatch"
            )
        seen.add(record_id)
        source_url = str(by_id[record_id].get("source_url") or by_id[record_id].get("url") or "")
        accepted_source_urls = {source_url}
        legacy_arxiv_status_url = _arxiv_status_url(by_id[record_id])
        if legacy_arxiv_status_url is not None:
            accepted_source_urls.add(legacy_arxiv_status_url)
        if str(raw.get("source_url") or "") not in accepted_source_urls:
            raise ContestDirectionResearchLoopError("finalist status receipt source URL mismatch")
        original_status = str(by_id[record_id].get("publication_status") or "unknown")
        if str(raw.get("original_status") or "unknown") != original_status:
            raise ContestDirectionResearchLoopError(
                "finalist status receipt original status mismatch"
            )
        if not isinstance(raw.get("verification_attempted"), bool):
            raise ContestDirectionResearchLoopError(
                "finalist status receipt attempted flag is invalid"
            )
        record = dict(by_id[record_id])
        if raw.get("verification_attempted") is True:
            verified_status = str(raw.get("verified_status") or "")
            if verified_status not in {
                "unknown",
                "preprint",
                "published",
                "withdrawn",
                "retracted",
            }:
                raise ContestDirectionResearchLoopError(
                    "finalist status receipt verified status is invalid"
                )
            if raw.get("outcome") == "verification_failed_preserved_as_non_authoritative":
                if verified_status != original_status or not str(raw.get("error") or ""):
                    raise ContestDirectionResearchLoopError(
                        "failed finalist status receipt is internally inconsistent"
                    )
                updated[record_id] = record
                continue
            if raw.get("outcome") == "verification_failed_transport_preserved":
                if verified_status != original_status or not str(raw.get("error") or ""):
                    raise ContestDirectionResearchLoopError(
                        "transport-failed finalist status receipt is internally inconsistent"
                    )
                updated[record_id] = record
                continue
            expected_outcome = (
                "excluded_from_positive_planning"
                if verified_status in {"withdrawn", "retracted"}
                else "eligible_after_verification"
            )
            if raw.get("outcome") == "verification_served_from_cache":
                if not str(raw.get("error") or "") or not isinstance(
                    raw.get("cache_key"), str
                ):
                    raise ContestDirectionResearchLoopError(
                        "cache-served finalist status receipt is internally inconsistent"
                    )
            elif raw.get("outcome") != expected_outcome:
                raise ContestDirectionResearchLoopError(
                    "finalist status receipt outcome disagrees with verified status"
                )
            record.update(
                {
                    "publication_status": verified_status,
                    "status_source": raw.get("status_source"),
                    "status_as_of": raw.get("status_as_of"),
                }
            )
            cache_key_text = (
                str(raw.get("cache_key") or "")[:12] + "…"
                if raw.get("outcome") == "verification_served_from_cache"
                else ""
            )
            context_suffixes[record_id] = (
                "最终候选状态复核（不改变原检索record_sha256）："
                f"{verified_status}；来源={raw.get('status_source') or 'unknown'}；"
                f"截至={raw.get('status_as_of') or 'unknown'}"
                + (f"；复核方式=跨运行缓存（cache_key={cache_key_text}）" if cache_key_text else "")
            )
        updated[record_id] = record

    replay_catalog: list[dict[str, Any]] = []
    replay_context: list[str] = []
    for item, context in zip(eligible_catalog, literature_context, strict=True):
        record_id = str(item.get("record_id") or "")
        record = updated.get(record_id, dict(item))
        if str(record.get("publication_status") or "unknown").casefold() in {
            "withdrawn",
            "retracted",
        }:
            continue
        suffix = context_suffixes.get(record_id)
        replay_catalog.append(record)
        replay_context.append(f"{context}\n{suffix}" if suffix else context)
    if not replay_catalog:
        raise ContestDirectionResearchLoopError(
            "no planning paper remains after finalist status receipt replay"
        )
    return tuple(replay_catalog), tuple(replay_context)


def _verify_source_inventory(root: Path, report: Mapping[str, Any]) -> None:
    inventory = report.get("file_inventory")
    if not isinstance(inventory, list) or not inventory:
        raise ContestDirectionResearchLoopError("source delivery file inventory is absent")
    expected_hash = report.get("file_inventory_hash")
    if expected_hash != canonical_model_hash({"files": inventory}):
        raise ContestDirectionResearchLoopError("source delivery inventory hash mismatch")
    for item in inventory:
        if not isinstance(item, Mapping):
            raise ContestDirectionResearchLoopError("source inventory entry is not an object")
        relative = str(item.get("relative_path") or "")
        path = _inside(root, relative)
        _verify_file_binding(path, item)


def _bound_main_path(root: Path, main: Mapping[str, Any], key: str) -> Path:
    binding = main.get(key)
    if not isinstance(binding, Mapping):
        raise ContestDirectionResearchLoopError(f"source main artifact is absent: {key}")
    path_text = str(binding.get("path") or "")
    if not path_text:
        raise ContestDirectionResearchLoopError(f"source main artifact path is absent: {key}")
    path = Path(path_text).expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ContestDirectionResearchLoopError(
            f"source main artifact escapes delivery root: {key}"
        ) from exc
    _verify_file_binding(path, binding)
    return path


def _verify_main_artifact_identity(main: Mapping[str, Any], key: str, actual: str) -> None:
    binding = main.get(key)
    if not isinstance(binding, Mapping) or binding.get("artifact_hash") != actual:
        raise ContestDirectionResearchLoopError(f"source main artifact identity mismatch: {key}")


def _verify_source_skill_manifest(
    path: Path,
    *,
    routing: ContestDirectSkillRoutingArtifact,
) -> None:
    manifest = _read_json(path)
    records = manifest.get("skills")
    if not isinstance(records, list):
        raise ContestDirectionResearchLoopError("source selected Skill manifest is invalid")
    expected_ids: list[str] = []
    expected_hashes: dict[str, str] = {}
    for record in records:
        if not isinstance(record, Mapping):
            raise ContestDirectionResearchLoopError("source selected Skill entry is invalid")
        skill_id = str(record.get("skill_id") or "")
        digest = str(record.get("content_sha256") or "")
        skill_path = Path(str(record.get("path") or "")).expanduser().resolve()
        if (
            not skill_id
            or not skill_path.is_file()
            or hashlib.sha256(skill_path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
            != digest
        ):
            raise ContestDirectionResearchLoopError(
                f"source selected Skill bytes/hash mismatch: {skill_id or '<blank>'}"
            )
        expected_ids.append(skill_id)
        expected_hashes[skill_id] = digest
    if tuple(expected_ids) != routing.selected_skill_ids:
        raise ContestDirectionResearchLoopError("source Skill selection order mismatch")
    if expected_hashes != routing.selected_skill_hashes:
        raise ContestDirectionResearchLoopError("source Skill selection hash mismatch")
    if manifest.get("routing_artifact_hash") != routing.artifact_hash:
        raise ContestDirectionResearchLoopError("source Skill routing binding mismatch")


def _skill_routing_literature_evidence(
    literature: ContestDirectionLiteratureArtifact,
    catalog: Sequence[Mapping[str, Any]],
) -> ContestDirectLiteratureEvidenceContext:
    """Project whole retrieved records for routing without exposing Skill bodies."""

    record_ids = tuple(str(item.get("record_id") or "") for item in catalog)
    for count in range(len(record_ids), 0, -1):
        try:
            return ContestDirectLiteratureEvidenceContext.from_retrieval_artifact(
                literature,
                record_ids=record_ids[:count],
            )
        except (ContestDirectSkillRoutingError, ValueError) as exc:
            if "14 KiB" not in str(exc):
                raise
    raise ContestDirectionResearchLoopError(
        "no complete retrieved literature record fits the Skill-routing evidence budget"
    )


def _skill_routing_two_stage_literature_evidence(
    literature: _PlanningLiteratureArtifact,
    catalog: Sequence[Mapping[str, Any]],
    *,
    queries: Sequence[str] = (),
    priority_queries: Sequence[str] = (),
    priority_query_groups: Sequence[Sequence[str]] = (),
) -> ContestDirectLiteratureEvidenceContext:
    """Select complementary whole records, not a planning-order prefix.

    The 14 KiB contract is tested with the router's canonical constructor after
    every addition.  Focused nearest-work/method overlap drives relevance while
    marginal query-token and document novelty keep redundant background papers
    from consuming the entire reasoning context.  These are soft scores, not
    category quotas.
    """

    if not catalog:
        raise ContestDirectionResearchLoopError("planning literature catalog is empty")
    query_tokens = frozenset().union(*(_lexical_tokens(query) for query in queries))
    priority_tokens = frozenset().union(*(_lexical_tokens(query) for query in priority_queries))
    priority_group_themes = tuple(
        tuple(_lexical_tokens(query) for query in group if _lexical_tokens(query))
        for group in priority_query_groups
        if group
    )
    document_tokens = tuple(
        _lexical_tokens(" ".join((str(item.get("title") or ""), str(item.get("abstract") or ""))))
        for item in catalog
    )
    title_tokens = tuple(_lexical_tokens(str(item.get("title") or "")) for item in catalog)
    relevance_scores = tuple(
        _skill_reasoning_relevance_score(
            document=tokens,
            title=title,
            query_tokens=query_tokens,
            priority_tokens=priority_tokens,
            priority_group_themes=priority_group_themes,
        )
        for tokens, title in zip(document_tokens, title_tokens, strict=True)
    )
    maximum_relevance = max(relevance_scores, default=1.0) or 1.0
    selected_indices: list[int] = []
    selected_context: ContestDirectLiteratureEvidenceContext | None = None
    covered_priority_tokens: set[str] = set()
    remaining = set(range(len(catalog)))
    while remaining:
        ranked = sorted(
            remaining,
            key=lambda candidate: (
                (0.54 * relevance_scores[candidate] / maximum_relevance)
                + (
                    0.19
                    * len((document_tokens[candidate] & priority_tokens) - covered_priority_tokens)
                    / max(1, len(priority_tokens))
                )
                + (
                    0.24
                    * _skill_reasoning_document_novelty(
                        candidate, document_tokens, selected_indices
                    )
                )
                + (
                    0.03
                    if "targeted"
                    in {
                        str(stage).casefold()
                        for stage in catalog[candidate].get("source_stages") or ()
                    }
                    else 0.0
                ),
                -candidate,
            ),
            reverse=True,
        )
        admitted = False
        for candidate in ranked:
            remaining.remove(candidate)
            trial_indices = (*selected_indices, candidate)
            trial_ids = tuple(str(catalog[index].get("record_id") or "") for index in trial_indices)
            try:
                trial_context = ContestDirectLiteratureEvidenceContext.from_two_stage_artifact(
                    literature,
                    record_ids=trial_ids,
                )
            except (ContestDirectSkillRoutingError, ValueError) as exc:
                if "14 KiB" not in str(exc):
                    raise
                continue
            selected_indices.append(candidate)
            selected_context = trial_context
            covered_priority_tokens.update(document_tokens[candidate] & priority_tokens)
            admitted = True
            break
        if not admitted:
            break
    if selected_context is not None:
        return selected_context
    raise ContestDirectionResearchLoopError(
        "no complete merged literature record fits the Skill-routing evidence budget"
    )


def _skill_reasoning_relevance_score(
    *,
    document: frozenset[str],
    title: frozenset[str],
    query_tokens: frozenset[str],
    priority_tokens: frozenset[str],
    priority_group_themes: Sequence[Sequence[frozenset[str]]],
) -> float:
    general_overlap = document & query_tokens
    priority_overlap = document & priority_tokens
    bridge = min(
        (
            max(len(document & theme_tokens) / max(1, len(theme_tokens)) for theme_tokens in group)
            for group in priority_group_themes
            if group
        ),
        default=0.0,
    )
    return (
        (0.30 * len(general_overlap) / max(1, len(query_tokens)))
        + (0.30 * len(priority_overlap) / max(1, len(priority_tokens)))
        + (0.10 * len(title & priority_tokens) / max(1, len(priority_tokens)))
        + (0.30 * bridge)
    )


def _skill_reasoning_document_novelty(
    candidate: int,
    document_tokens: Sequence[frozenset[str]],
    selected_indices: Sequence[int],
) -> float:
    if not selected_indices:
        return 1.0
    candidate_tokens = document_tokens[candidate]
    maximum_similarity = max(
        len(candidate_tokens & document_tokens[index])
        / max(1, len(candidate_tokens | document_tokens[index]))
        for index in selected_indices
    )
    return 1.0 - maximum_similarity


def _catalog_subset_by_record_ids(
    catalog: Sequence[Mapping[str, Any]],
    record_ids: Sequence[str],
) -> tuple[dict[str, Any], ...]:
    """Reuse the exact whole-record Skill subset for hypothesis reasoning."""

    by_id = {str(item.get("record_id") or ""): dict(item) for item in catalog}
    selected: list[dict[str, Any]] = []
    for record_id in record_ids:
        item = by_id.get(record_id)
        if item is None:
            raise ContestDirectionResearchLoopError(
                "Skill literature subset escaped the planning lock"
            )
        selected.append(item)
    if not selected:
        raise ContestDirectionResearchLoopError("reasoning literature subset is empty")
    return tuple(selected)


def _load_selected_skills(
    routing: ContestDirectSkillRoutingArtifact,
    bodies: Mapping[str, tuple[Path, str]],
) -> tuple[dict[str, Any], ...]:
    selected: list[dict[str, Any]] = []
    for skill_id in routing.selected_skill_ids:
        if skill_id not in bodies:
            raise ContestDirectionResearchLoopError(
                f"router selected unavailable Skill: {skill_id}"
            )
        path, content = bodies[skill_id]
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if routing.selected_skill_hashes.get(skill_id) != digest:
            raise ContestDirectionResearchLoopError(
                f"selected Skill changed after routing: {skill_id}"
            )
        if hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest() != digest:
            raise ContestDirectionResearchLoopError(
                f"selected Skill file bytes changed after routing: {skill_id}"
            )
        selected.append(
            {
                "skill_id": skill_id,
                "path": path.resolve(),
                "content": content,
                "content_sha256": digest,
            }
        )
    return tuple(selected)


def _write_selected_skill_manifest(
    path: Path,
    *,
    routing_path: Path,
    routing: ContestDirectSkillRoutingArtifact,
    selected_skills: Sequence[Mapping[str, Any]],
    merged_literature: _PlanningLiteratureArtifact,
    planning_literature_artifact_hash: str,
) -> None:
    payload: dict[str, Any] = {
        "schema_version": "contest-direction-evidence-routed-skills-v2",
        "routing_artifact_path": routing_path.as_posix(),
        "routing_artifact_hash": routing.artifact_hash,
        "literature_protocol": _LITERATURE_PROTOCOL,
        "broad_literature_artifact_hash": (merged_literature.broad_literature_artifact_hash),
        "focus_artifact_hash": merged_literature.focus_artifact_hash,
        "selected_focus_id": merged_literature.selected_focus_id,
        "targeted_retrieval_binding_hash": (merged_literature.targeted_retrieval_binding_hash),
        "targeted_literature_artifact_hash": (merged_literature.targeted_literature_artifact_hash),
        "merged_literature_artifact_hash": merged_literature.artifact_hash,
        "merged_literature_catalog_hash": merged_literature.merged_catalog_hash,
        "planning_literature_artifact_hash": planning_literature_artifact_hash,
        "literature_visible_before_skill_metadata": True,
        "skill_bodies_visible_to_selector": False,
        "skills": [
            {
                "skill_id": item["skill_id"],
                "path": Path(item["path"]).as_posix(),
                "content_sha256": item["content_sha256"],
            }
            for item in selected_skills
        ],
    }
    payload["manifest_hash"] = canonical_model_hash(payload)
    _write_new_json(path, payload)


def _temporary_skill_context(item: Mapping[str, Any]) -> TemporaryQwenSkillContext:
    return TemporaryQwenSkillContext(
        skill_ref=TemporaryAgentSkillRef(
            skill_id=str(item["skill_id"]),
            source_ref=Path(item["path"]).as_posix(),
            content_sha256=str(item["content_sha256"]),
        ),
        content=str(item["content"]),
    )


def _select_executable_candidate(
    hypotheses: Any,
    *,
    direction: str,
    selected_skill_ids: Sequence[str],
) -> dict[str, Any] | None:
    """Select the first stable candidate that exactly fits an installed adapter.

    This is feasibility routing, not a scientific ranker.  It neither predicts
    support nor prefers a scientifically attractive conclusion.
    """

    if _REQUIRED_SKILL_ID not in selected_skill_ids:
        return None
    if not _direction_fits_prime_gap_adapter(direction):
        return None
    for candidate in _candidate_payloads(hypotheses):
        if _candidate_fits_prime_gap_adapter(candidate, direction=direction):
            return candidate
    return None


def _candidate_payloads(hypotheses: Any) -> tuple[dict[str, Any], ...]:
    raw = getattr(hypotheses, "candidates", None)
    if raw is None and isinstance(hypotheses, Mapping):
        raw = hypotheses.get("candidates")
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes | bytearray):
        raise ContestDirectionResearchLoopError("hypothesis stage returned no candidate list")
    candidates: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, Mapping):
            payload = dict(item)
        else:
            dump = getattr(item, "model_dump", None)
            if not callable(dump):
                raise ContestDirectionResearchLoopError(
                    "hypothesis candidate is not a structured object"
                )
            payload = dump(mode="json")
        if not isinstance(payload, dict):
            raise ContestDirectionResearchLoopError("hypothesis candidate payload is invalid")
        candidates.append(payload)
    return tuple(candidates)


def _direction_fits_prime_gap_adapter(direction: str) -> bool:
    normalized = direction.casefold()
    if any(
        marker in normalized
        for marker in (
            "蛋白",
            "protein",
            "基因",
            "genetic",
            "genomic",
            "dna",
            "rna",
        )
    ):
        return False
    prime = any(marker in normalized for marker in ("素数", "质数", "prime"))
    gap = any(marker in normalized for marker in ("间隙", "间隔", "gap"))
    information = any(
        marker in normalized
        for marker in (
            "信息",
            "熵",
            "entropy",
            "ordinal",
            "排列",
            "permutation",
            "顺序结构",
        )
    )
    if not (prime and gap and information):
        return False
    return assess_adapter_semantic_compatibility(
        _ADAPTER_DESCRIPTOR,
        scope_texts=(direction,),
    ).compatible


def _is_canonical_science125_q001_direction(direction: str) -> bool:
    """Recognize only the frozen broad parent question, never an arbitrary prime prompt."""

    normalized = "\n".join(line.strip() for line in direction.strip().splitlines())
    return normalized in {
        _SCIENCE125_Q001_EN,
        _SCIENCE125_Q001_ZH,
        _SCIENCE125_Q001_BATCH_DIRECTION,
    }


def _candidate_fits_prime_gap_adapter(
    candidate: Mapping[str, Any], *, direction: str | None = None
) -> bool:
    return assess_adapter_semantic_compatibility(
        _ADAPTER_DESCRIPTOR,
        scope_texts=((direction,) if direction is not None else ()),
        candidate=candidate,
    ).compatible


def _adapter_selection_payload(
    *,
    direction: str,
    routing: ContestDirectSkillRoutingArtifact,
    literature: ContestDirectionMergedLiteratureArtifact | Any,
    hypotheses: Any,
    selected_candidate: Mapping[str, Any] | None,
) -> dict[str, Any]:
    candidates = _candidate_payloads(hypotheses)
    direction_compatible = _direction_fits_prime_gap_adapter(direction)
    required_skill_selected = _REQUIRED_SKILL_ID in routing.selected_skill_ids
    selection_supported = (
        selected_candidate is not None
        and direction_compatible
        and required_skill_selected
        and _candidate_fits_prime_gap_adapter(selected_candidate, direction=direction)
    )
    compatibility = [
        {
            "candidate_id": item.get("candidate_id"),
            "adapter_id": item.get("adapter_id") or item.get("pilot_adapter_id"),
            "compatible": _candidate_fits_prime_gap_adapter(item, direction=direction),
        }
        for item in candidates
    ]
    payload: dict[str, Any] = {
        "schema_version": "contest-preexperiment-adapter-selection-v2",
        "direction": direction,
        "direction_compatible": direction_compatible,
        "direction_compatibility_basis": (
            "canonical_science125_q001_broad_parent"
            if _is_canonical_science125_q001_direction(direction)
            else (
                "explicit_prime_gap_information_direction"
                if direction_compatible
                else "incompatible"
            )
        ),
        "required_skill_id": _REQUIRED_SKILL_ID,
        "required_skill_selected": required_skill_selected,
        "adapter_descriptor": _ADAPTER_DESCRIPTOR,
        "literature_protocol": _LITERATURE_PROTOCOL,
        "merged_literature_artifact_hash": literature.artifact_hash,
        "skill_routing_artifact_hash": routing.artifact_hash,
        "hypothesis_artifact_hash": _artifact_hash(hypotheses),
        "candidate_compatibility": compatibility,
        "selection_rule": (
            "required_skill_and_direction_scope_then_stable_first_exactly_compatible_candidate; "
            "feasibility_only; no scientific-outcome ranking"
        ),
        "selected_candidate_id": (
            selected_candidate.get("candidate_id")
            if selection_supported and selected_candidate is not None
            else None
        ),
        "selected_adapter_id": _ADAPTER_ID if selection_supported else None,
        "status": "supported" if selection_supported else "no_compatible_adapter",
    }
    payload["artifact_hash"] = canonical_model_hash(payload)
    return payload


def _resume_adapter_selection(
    *,
    root: Path,
    direction: str,
    routing: ContestDirectSkillRoutingArtifact,
    literature: ContestDirectionMergedLiteratureArtifact | Any,
    hypotheses: Any,
    selected_candidate: Mapping[str, Any] | None,
) -> tuple[Path, dict[str, Any]]:
    """Load an adapter receipt or append one narrow, forensic reassessment.

    The original receipt is immutable.  Reassessment is allowed only for the
    frozen Science 125 question 1 broad parent when today's Skill and exact
    candidate gates pass against the same persisted upstream artifacts.
    """

    original_path = root / "preexperiment-adapter-selection.json"
    expected = _adapter_selection_payload(
        direction=direction,
        routing=routing,
        literature=literature,
        hypotheses=hypotheses,
        selected_candidate=selected_candidate,
    )
    if not original_path.is_file():
        _write_new_json(original_path, expected)
        return original_path, expected

    original = _read_json(original_path)
    _verify_adapter_receipt_hash(original, label="resume adapter receipt")
    if _adapter_receipt_selects(original, selected_candidate):
        return original_path, original

    raise ContestDirectionResearchLoopError("resume adapter/candidate binding mismatch")


def _verify_adapter_receipt_hash(receipt: Mapping[str, Any], *, label: str) -> None:
    if receipt.get("artifact_hash") != canonical_model_hash(
        {key: value for key, value in receipt.items() if key != "artifact_hash"}
    ):
        raise ContestDirectionResearchLoopError(f"{label} hash mismatch")


def _adapter_receipt_selects(
    receipt: Mapping[str, Any], selected_candidate: Mapping[str, Any] | None
) -> bool:
    return (
        selected_candidate is not None
        and receipt.get("status") == "supported"
        and receipt.get("selected_candidate_id") == selected_candidate.get("candidate_id")
    )


def _pilot_brief_payload(
    *,
    direction: str,
    direction_input_hash: str,
    literature: ContestDirectionMergedLiteratureArtifact | Any,
    routing: ContestDirectSkillRoutingArtifact,
    hypotheses: Any,
    selected_candidate: Mapping[str, Any],
    provisional_plan: ContestDirectPlanArtifact | None = None,
) -> dict[str, Any]:
    frozen_parameters = {
        "intervals": [
            [1_000_000, 2_000_000],
            [5_000_000, 6_000_000],
            [10_000_000, 11_000_000],
            [20_000_000, 21_000_000],
            [50_000_000, 51_000_000],
        ],
        "null_draws": 199,
        "ordinal_dimension": 5,
        "ordinal_delay": 1,
        "seed": 20_260_811,
        "primary_null_model": "residue_path_conditioned_permutation",
        "sensitivity_null_models": ["local_block_permutation", "wheel_210"],
    }
    decision_rule = {
        "support_and_narrow": (
            "primary conditioned null and sensitivity analyses retain a directionally "
            "consistent, detectable entropy departure on the five fixed intervals"
        ),
        "not_supported_rethink": (
            "the apparent departure vanishes or reverses under the stronger conditioned/local "
            "nulls; reject the broad ordering claim and rethink within observed constraints"
        ),
        "inconclusive_rethink": (
            "null families disagree, effects are unstable, or the fixed-interval pilot cannot "
            "distinguish the candidate from its alternatives"
        ),
    }
    payload: dict[str, Any] = {
        "schema_version": "contest-prime-gap-pilot-brief-v2",
        "direction": direction,
        "direction_input_hash": direction_input_hash,
        "adapter_descriptor": _ADAPTER_DESCRIPTOR,
        "selected_candidate": dict(selected_candidate),
        "frozen_parameters_projection": frozen_parameters,
        "decision_rule": decision_rule,
        "literature_protocol": _LITERATURE_PROTOCOL,
        "merged_literature_artifact_hash": literature.artifact_hash,
        "skill_routing_artifact_hash": routing.artifact_hash,
        "hypothesis_artifact_hash": _artifact_hash(hypotheses),
        "provisional_plan_artifact_hash": (
            provisional_plan.artifact_hash if provisional_plan is not None else None
        ),
        "protocol_delta": {
            "candidate_authored_by_model": True,
            "adapter_and_parameters_selected_by_program_compatibility": True,
            "runner_uses_registered_frozen_protocol_not_model_generated_code": True,
            "source_plan_path_role": "hash_bound_input_snapshot_only",
            "source_plan_compiled_or_executed": False,
            "formal_experiment": False,
        },
    }
    payload["artifact_hash"] = canonical_model_hash(payload)
    return payload


def _verify_prime_pilot(
    pilot: ContestPrimePreexperimentArtifact,
    *,
    generated: ContestPrimePreexperimentArtifact,
    source_snapshot_sha256: str,
) -> None:
    if pilot.artifact_hash != generated.artifact_hash or pilot.run_id != generated.run_id:
        raise ContestDirectionResearchLoopError(
            "persisted prime pilot differs from the runner return value"
        )
    if pilot.status != "completed" or pilot.study_phase != "exploratory_pilot":
        raise ContestDirectionResearchLoopError("prime adapter did not complete its pilot")
    if pilot.source_plan_sha256 != source_snapshot_sha256:
        raise ContestDirectionResearchLoopError("prime pilot input snapshot hash mismatch")
    if pilot.formal_experiment_executed or pilot.mathematical_proof_claimed:
        raise ContestDirectionResearchLoopError("prime pilot overstates its evidence scope")


def _two_stage_literature_artifact_bindings(
    literature_state: _TwoStageLiteratureState | Any,
) -> dict[str, Any]:
    """Bind the complete base/effective planning-literature lineage."""

    base_merged = getattr(literature_state, "base_merged", None) or literature_state.merged
    base_merged_path = (
        getattr(literature_state, "base_merged_path", None) or literature_state.merged_path
    )
    artifacts: dict[str, Any] = {
        "broad_literature": {
            **_file_binding(literature_state.broad_path),
            "artifact_hash": literature_state.broad.artifact_hash,
        },
        "direction_focus": {
            **_file_binding(literature_state.focus_path),
            "artifact_hash": literature_state.focus.artifact_hash,
            "selected_focus_id": literature_state.focus.selected_focus_id,
        },
        "targeted_literature": {
            **_file_binding(literature_state.targeted_path),
            "artifact_hash": literature_state.targeted.artifact_hash,
        },
        "targeted_retrieval_binding": {
            **_file_binding(literature_state.targeted_binding_path),
            "artifact_hash": literature_state.targeted_binding.artifact_hash,
        },
        "base_merged_literature": {
            **_file_binding(base_merged_path),
            "artifact_hash": base_merged.artifact_hash,
        },
        "effective_merged_literature": {
            **_file_binding(literature_state.merged_path),
            "artifact_hash": literature_state.merged.artifact_hash,
        },
        "merged_literature": {
            **_file_binding(literature_state.merged_path),
            "artifact_hash": literature_state.merged.artifact_hash,
        },
        "planning_literature": {
            **_file_binding(literature_state.planning_lock_path),
            "artifact_hash": literature_state.planning_lock_payload["artifact_hash"],
        },
        "planning_literature_coverage": {
            **_file_binding(literature_state.planning_coverage_path),
            "receipt_hash": literature_state.planning_coverage.receipt_hash,
        },
    }
    r1_coverage = getattr(literature_state, "r1_planning_coverage", None)
    r1_coverage_path = getattr(literature_state, "r1_planning_coverage_path", None)
    if (r1_coverage is None) != (r1_coverage_path is None):
        raise ContestDirectionResearchLoopError(
            "R1 planning coverage artifact binding is incomplete"
        )
    if r1_coverage is not None and r1_coverage_path is not None:
        artifacts["planning_literature_coverage_r1"] = {
            **_file_binding(r1_coverage_path),
            "receipt_hash": r1_coverage.receipt_hash,
        }
    r2_coverage = getattr(literature_state, "r2_planning_coverage", None)
    r2_coverage_path = getattr(literature_state, "r2_planning_coverage_path", None)
    if (r2_coverage is None) != (r2_coverage_path is None):
        raise ContestDirectionResearchLoopError(
            "R2 planning coverage artifact binding is incomplete"
        )
    if r2_coverage is not None and r2_coverage_path is not None:
        artifacts["planning_literature_coverage_r2"] = {
            **_file_binding(r2_coverage_path),
            "receipt_hash": r2_coverage.receipt_hash,
        }

    gap_fields = (
        ("gap_diagnosis", "gap_diagnosis_path"),
        ("gap_response", "gap_response_path"),
        ("gap_projection", "gap_projection_path"),
        ("gap_retrieval", "gap_retrieval_path"),
    )
    gap_values = tuple(
        (getattr(literature_state, value_name, None), getattr(literature_state, path_name, None))
        for value_name, path_name in gap_fields
    )
    gap_present = tuple(value is not None or path is not None for value, path in gap_values)
    if any(gap_present) and not all(
        value is not None and path is not None for value, path in gap_values
    ):
        raise ContestDirectionResearchLoopError("bounded gap-repair artifact chain is incomplete")
    if not any(gap_present) and (r2_coverage is not None or r2_coverage_path is not None):
        raise ContestDirectionResearchLoopError(
            "zero-round literature lineage cannot carry R2 planning coverage"
        )
    if all(value is not None and path is not None for value, path in gap_values):
        if r2_coverage is None or r2_coverage_path is None:
            raise ContestDirectionResearchLoopError(
                "bounded gap-repair artifact chain lacks R2 planning coverage"
            )
        diagnosis, diagnosis_path = gap_values[0]
        response, response_path = gap_values[1]
        projection, projection_path = gap_values[2]
        retrieval, retrieval_path = gap_values[3]
        if (
            diagnosis is None
            or diagnosis_path is None
            or response is None
            or response_path is None
            or projection is None
            or projection_path is None
            or retrieval is None
            or retrieval_path is None
        ):
            raise ContestDirectionResearchLoopError(
                "bounded gap-repair artifact chain is incomplete"
            )
        artifacts.update(
            {
                "layered_literature": {
                    **_file_binding(literature_state.merged_path),
                    "artifact_hash": literature_state.merged.artifact_hash,
                },
                "planning_literature_gap_diagnosis": {
                    **_file_binding(diagnosis_path),
                    "diagnosis_hash": diagnosis.diagnosis_hash,
                },
                "planning_literature_gap_query_response": {
                    **_file_binding(response_path),
                    "receipt_hash": response.receipt_hash,
                },
                "planning_literature_gap_query_projection": {
                    **_file_binding(projection_path),
                    "projection_hash": projection.projection_hash,
                },
                "planning_literature_gap_retrieval": {
                    **_file_binding(retrieval_path),
                    "artifact_hash": retrieval.artifact_hash,
                },
            }
        )
    return artifacts


def _no_adapter_physical_accounting(root: Path) -> dict[str, Any]:
    accounting_by_stage = {
        stage: provider_checkpoint_accounting(root, stage_name=stage)
        for stage in _OUTER_MODEL_STAGES
    }
    attempts_by_stage = {
        stage: counts["attempt_count"] for stage, counts in accounting_by_stage.items()
    }
    return {
        "physical_provider_attempts_by_stage": attempts_by_stage,
        "provider_checkpoint_accounting_by_stage": accounting_by_stage,
        "physical_provider_attempt_total": sum(attempts_by_stage.values()),
        "physical_provider_attempt_semantics": (
            "lifetime_durable_attempt_reservations_deduplicated_by_canonical_stage_owner"
        ),
        "legacy_provider_request_attempt_fields_semantics": (
            "logical_scientific_model_calls_v1_compatibility"
        ),
    }


def _finish_without_adapter(
    *,
    root: Path,
    policy: PreexperimentPolicy,
    direction: str,
    parent_direction: str | None = None,
    source_accounting: Mapping[str, Any] | None,
    direction_input_path: Path,
    literature_path: Path,
    finalist_status_path: Path,
    finalist_status_payload: Mapping[str, Any],
    routing_path: Path,
    skill_manifest_path: Path,
    hypothesis_path: Path,
    adapter_receipt_path: Path,
    routing: ContestDirectSkillRoutingArtifact,
    literature: ContestDirectionMergedLiteratureArtifact | Any,
    hypotheses: Any,
    literature_state: _TwoStageLiteratureState | None = None,
    memory_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    status = (
        "blocked_no_compatible_real_preexperiment_adapter"
        if policy == "required"
        else "completed_without_preexperiment_no_compatible_adapter"
    )
    gap_repair_calls = (
        literature_state.gap_response.model_calls
        if literature_state is not None and literature_state.gap_response is not None
        else 0
    )
    retrieval_calls = (
        literature_state.broad.query_model_calls
        + literature_state.focus.model_call_count_at_creation
        + literature_state.targeted.query_model_calls
        + gap_repair_calls
        if literature_state is not None
        else _nonnegative_int(
            getattr(literature, "query_model_calls", 0),
            label="retrieval query calls",
        )
    )
    literature_artifacts: dict[str, Any]
    if literature_state is None:
        literature_artifacts = {"literature": _file_binding(literature_path)}
    else:
        literature_artifacts = _two_stage_literature_artifact_bindings(literature_state)
    scientific_call_total = retrieval_calls + routing.model_calls + _model_call_count(hypotheses)
    this_loop_calls = (
        _nonnegative_int(
            source_accounting.get("current_scientific_model_calls", 0),
            label="current scientific model calls",
        )
        if source_accounting is not None
        else scientific_call_total
    )
    if this_loop_calls > scientific_call_total:
        raise ContestDirectionResearchLoopError(
            "current scientific model calls exceed total provenance calls"
        )
    physical_accounting = (
        _no_adapter_physical_accounting(root) if literature_state is not None else {}
    )
    delivery_source_accounting = (
        _delivery_source_checkpoint_accounting(root=root, provenance=source_accounting)
        if literature_state is not None
        else (dict(source_accounting) if source_accounting else None)
    )
    report: dict[str, Any] = {
        "schema_version": _DELIVERY_SCHEMA
        if literature_state is not None
        else ("contest-direction-research-loop-delivery-v1"),
        "status": status,
        "direction": parent_direction or direction,
        "focused_direction": direction if literature_state is not None else None,
        "literature_protocol": (_LITERATURE_PROTOCOL if literature_state is not None else None),
        "preexperiment_policy": policy,
        "preexperiment_executed": False,
        "formal_experiment_executed": False,
        "paper_claimed": False,
        "memory": dict(memory_summary) if memory_summary is not None else None,
        "reason": (
            "No candidate matched an installed real adapter by Skill, scientific object, "
            "observable, metric, and null-model coverage."
        ),
        "source_accounting": delivery_source_accounting,
        "model_call_accounting": {
            "retrieval_query_calls": retrieval_calls,
            "broad_retrieval_query_calls": (
                literature_state.broad.query_model_calls if literature_state is not None else None
            ),
            "focus_brainstorm_and_selection_calls": (
                literature_state.focus.model_call_count_at_creation
                if literature_state is not None
                else None
            ),
            "targeted_retrieval_query_calls": (
                literature_state.targeted.query_model_calls
                if literature_state is not None
                else None
            ),
            "planning_literature_gap_repair_calls": gap_repair_calls,
            "skill_routing_calls": routing.model_calls,
            "hypothesis_brainstorm_calls": _model_call_count(hypotheses),
            "postpilot_feedback_calls": 0,
            "objective_review_calls": 0,
            "plan_author_calls": 0,
            "final_scientific_review_calls": 0,
            "this_loop_observed_provider_request_attempts": this_loop_calls,
            "historical_source_provider_request_attempts": (
                scientific_call_total - this_loop_calls
            ),
            "total_provenance_provider_request_attempts": scientific_call_total,
            **physical_accounting,
        },
        "artifacts": {
            "direction_input": _file_binding(direction_input_path),
            **literature_artifacts,
            "finalist_status_verification": {
                **_file_binding(finalist_status_path),
                "artifact_hash": finalist_status_payload["artifact_hash"],
            },
            "skill_routing": _file_binding(routing_path),
            "selected_method_skills": _file_binding(skill_manifest_path),
            "hypotheses": _file_binding(hypothesis_path),
            "adapter_selection": _file_binding(adapter_receipt_path),
        },
        "literature": {
            "retrieval_semantics": (
                literature_state.merged.retrieval_semantics
                if literature_state is not None
                else "legacy_single_retrieval"
            ),
            "selected_focus_id": (
                literature_state.focus.selected_focus_id if literature_state is not None else None
            ),
            "planning_reference_count": (
                len(literature_state.planning_catalog) if literature_state is not None else None
            ),
            "finalist_status_verification_artifact_hash": finalist_status_payload["artifact_hash"],
            "finalist_status_verification_count": finalist_status_payload["verification_count"],
            "finalist_status_excluded_records": [
                {
                    "record_id": item.get("record_id"),
                    "verified_status": item.get("verified_status"),
                    "outcome": item.get("outcome"),
                }
                for item in finalist_status_payload["records"]
                if item.get("outcome") == "excluded_from_positive_planning"
            ],
        },
    }
    report["report_hash"] = canonical_model_hash(report)
    report_path = root / (
        "blocked-receipt.json" if policy == "required" else "delivery-report.json"
    )
    _write_new_json(report_path, report)
    if policy == "required":
        raise ContestDirectionResearchLoopError(
            f"no compatible real preexperiment adapter; blocked receipt: {report_path}"
        )
    returned = dict(report)
    returned["delivery_report_path"] = report_path.as_posix()
    returned["delivery_report_sha256"] = _sha256_file(report_path)
    return returned


def _postpilot_plan_context(postpilot: Any) -> dict[str, Any]:
    for name in ("plan_context_payload", "plan_context", "to_plan_context"):
        method = getattr(postpilot, name, None)
        if callable(method):
            payload = method()
            if isinstance(payload, Mapping):
                projected = dict(payload)
                # Byte-provenance summaries are independently verified by the
                # orchestrator; they are not scientific review content.  Keeping
                # them out also lets a newly computed legacy-compatibility hash
                # replay the exact already-paid revision prompt.
                projected.pop("verified_inputs_bundle_sha256", None)
                return projected
    if isinstance(postpilot, Mapping):
        payload = postpilot.get("plan_context") or postpilot.get("review") or postpilot
        if isinstance(payload, Mapping):
            return dict(payload)
    review = getattr(postpilot, "review", None)
    if review is not None:
        dump = getattr(review, "model_dump", None)
        if callable(dump):
            payload = dump(mode="json")
            if isinstance(payload, dict):
                return payload
    raise ContestDirectionResearchLoopError("postpilot objective stage lacks plan context")


def _artifact_plan_context(artifact: Any) -> dict[str, Any]:
    for name in ("plan_context_payload", "plan_context", "to_plan_context"):
        method = getattr(artifact, name, None)
        if callable(method):
            payload = method()
            if isinstance(payload, Mapping):
                return dict(payload)
    return {
        "artifact_hash": _artifact_hash(artifact),
        "candidates": list(_candidate_payloads(artifact)),
    }


def _artifact_hash(artifact: Any) -> str:
    value = getattr(artifact, "artifact_hash", None)
    if value is None and isinstance(artifact, Mapping):
        value = artifact.get("artifact_hash")
    digest = str(value or "")
    if not _is_sha256(digest):
        raise ContestDirectionResearchLoopError("stage artifact lacks a valid artifact_hash")
    return digest


def _artifact_path(root: Path, artifact: Any) -> Path:
    for name in (
        "artifact_relative_path",
        "output_relative_path",
        "artifact_path",
        "output_path",
    ):
        value = getattr(artifact, name, None)
        if value is None and isinstance(artifact, Mapping):
            value = artifact.get(name)
        if value:
            candidate = Path(str(value))
            path = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
            try:
                path.relative_to(root)
            except ValueError as exc:
                raise ContestDirectionResearchLoopError(
                    f"stage artifact escapes output root: {path}"
                ) from exc
            if not path.is_file():
                raise ContestDirectionResearchLoopError(f"stage artifact was not persisted: {path}")
            payload = _read_json(path)
            if payload.get("artifact_hash") != _artifact_hash(artifact):
                raise ContestDirectionResearchLoopError(
                    f"persisted stage artifact identity mismatch: {path}"
                )
            return path
    raise ContestDirectionResearchLoopError("stage artifact does not expose its persisted path")


def _model_call_count(artifact: Any) -> int:
    for name in ("model_call_count", "generation_calls", "model_calls"):
        value = getattr(artifact, name, None)
        if value is None and isinstance(artifact, Mapping):
            value = artifact.get(name)
        if value is not None:
            return _nonnegative_int(value, label=f"{name} on stage artifact")
    batch = getattr(artifact, "batch", None)
    if batch is not None:
        return _nonnegative_int(
            getattr(batch, "dispatched_count", None),
            label="temporary stage dispatched count",
        )
    raise ContestDirectionResearchLoopError("stage artifact lacks model-call accounting")


def _postpilot_call_breakdown(postpilot: Any) -> tuple[int, int]:
    feedback = getattr(postpilot, "feedback_model_call_count", None)
    review = getattr(postpilot, "objective_review_model_call_count", None)
    if isinstance(postpilot, Mapping):
        feedback = postpilot.get("feedback_model_call_count", feedback)
        review = postpilot.get("objective_review_model_call_count", review)
    if feedback is not None and review is not None:
        return (
            _nonnegative_int(feedback, label="postpilot feedback calls"),
            _nonnegative_int(review, label="postpilot objective-review calls"),
        )
    total = _model_call_count(postpilot)
    if total != 1:
        raise ContestDirectionResearchLoopError(
            "postpilot stage must contain exactly one evidence-aware independent review call"
        )
    # Scientific feedback and retain/narrow/terminate adjudication are one model
    # decision.  Reporting a second call would double-count the same response.
    return 0, 1


def _scientific_completion_status(recommendation: str) -> str | None:
    return _SCIENTIFIC_COMPLETION_STATUS.get(recommendation)


def _scientific_review_recommendation(
    final_review: ContestDirectPlanScientificReviewArtifact | Any,
) -> str:
    recommendation = str(getattr(final_review.review, "recommendation", "") or "")
    if recommendation not in {
        *_SCIENTIFIC_COMPLETION_STATUS,
        *_SCIENTIFIC_BLOCKING_RECOMMENDATIONS,
    }:
        raise ContestDirectionResearchLoopError(
            "independent scientific review has an unsupported recommendation"
        )
    return recommendation


def _scientific_block_receipt_payload(
    *,
    direction: str,
    focused_direction: str,
    final_review: ContestDirectPlanScientificReviewArtifact | Any,
    review_path: Path,
) -> dict[str, Any]:
    recommendation = _scientific_review_recommendation(final_review)
    if recommendation not in _SCIENTIFIC_BLOCKING_RECOMMENDATIONS:
        raise ContestDirectionResearchLoopError(
            "a nonblocking scientific recommendation cannot create a blocked receipt"
        )
    review = final_review.review
    payload: dict[str, Any] = {
        "schema_version": _SCIENTIFIC_BLOCK_SCHEMA,
        "status": "blocked_by_independent_scientific_review",
        "direction": direction,
        "focused_direction": focused_direction,
        "literature_protocol": _LITERATURE_PROTOCOL,
        "recommendation": recommendation,
        "recommendation_text": str(
            getattr(review, "recommendation_text", recommendation) or recommendation
        ),
        "reason": (
            "The independent non-rewriting scientific review did not authorize final "
            "delivery. The review and rendered plan are preserved; no automatic revision "
            "or review loop was started."
        ),
        "review_artifact": {
            **_file_binding(review_path),
            "artifact_hash": final_review.artifact_hash,
        },
        "delivery_report_created": False,
        "automatic_revision_performed": False,
        "rendered_plan_preserved": True,
    }
    payload["receipt_hash"] = canonical_model_hash(payload)
    return payload


def _write_or_verify_scientific_block_receipt(
    path: Path,
    payload: Mapping[str, Any],
) -> None:
    if not path.exists():
        _write_new_json(path, payload)
        return
    existing = _read_json(path)
    if existing != dict(payload):
        raise ContestDirectionResearchLoopError(
            "existing scientific review blocked receipt differs from the verified review"
        )


def _enforce_scientific_review_delivery_gate(
    *,
    root: Path,
    direction: str,
    focused_direction: str,
    final_review: ContestDirectPlanScientificReviewArtifact | Any,
    review_path: Path,
) -> None:
    recommendation = _scientific_review_recommendation(final_review)
    if _scientific_completion_status(recommendation) is not None:
        if (root / _SCIENTIFIC_BLOCK_RECEIPT).exists():
            raise ContestDirectionResearchLoopError(
                "nonblocking review conflicts with an existing scientific block receipt"
            )
        return
    if (root / "delivery-report.json").exists():
        raise ContestDirectionResearchLoopError(
            "blocking scientific review conflicts with an existing delivery report"
        )
    receipt_path = root / _SCIENTIFIC_BLOCK_RECEIPT
    receipt = _scientific_block_receipt_payload(
        direction=direction,
        focused_direction=focused_direction,
        final_review=final_review,
        review_path=review_path,
    )
    _write_or_verify_scientific_block_receipt(receipt_path, receipt)
    raise ContestDirectionResearchLoopError(
        "independent scientific review blocked final delivery "
        f"({recommendation}); receipt: {receipt_path}"
    )


def _raise_if_existing_scientific_review_block(*, root: Path, direction: str) -> None:
    receipt_path = root / _SCIENTIFIC_BLOCK_RECEIPT
    if not receipt_path.exists():
        return
    receipt = _read_json(receipt_path)
    literature_state = _load_completed_two_stage_literature(root)
    review_path = root / "independent-scientific-review" / "system-plan-scientific-review.json"
    final_review = load_contest_direct_plan_scientific_review(review_path, verify_files=True)
    expected = _scientific_block_receipt_payload(
        direction=direction,
        focused_direction=literature_state.focus.focused_direction_cn,
        final_review=final_review,
        review_path=review_path,
    )
    if receipt != expected:
        raise ContestDirectionResearchLoopError(
            "existing scientific review blocked receipt is invalid or stale"
        )
    raise ContestDirectionResearchLoopError(
        "independent scientific review remains blocked; no model call was repeated; "
        f"receipt: {receipt_path}"
    )


def _verify_completed_scientific_delivery_gate(
    *,
    root: Path,
    report: Mapping[str, Any],
    final_review: ContestDirectPlanScientificReviewArtifact | Any,
) -> None:
    if (root / _SCIENTIFIC_BLOCK_RECEIPT).exists():
        raise ContestDirectionResearchLoopError(
            "completed delivery conflicts with a scientific review blocked receipt"
        )
    recommendation = _scientific_review_recommendation(final_review)
    expected_status = _scientific_completion_status(recommendation)
    if expected_status is None:
        raise ContestDirectionResearchLoopError(
            "completed delivery is forbidden by its independent scientific review"
        )
    if report.get("status") != expected_status:
        raise ContestDirectionResearchLoopError(
            "completed delivery status disagrees with its scientific review recommendation"
        )
    review_summary = report.get("independent_scientific_review")
    if (
        not isinstance(review_summary, Mapping)
        or review_summary.get("recommendation") != recommendation
    ):
        raise ContestDirectionResearchLoopError(
            "completed delivery report does not bind its scientific review recommendation"
        )


def _completed_report(
    *,
    root: Path,
    direction: str,
    literature_state: _TwoStageLiteratureState,
    source_accounting: Mapping[str, Any] | None,
    direction_input_path: Path,
    literature: _PlanningLiteratureArtifact,
    finalist_status_path: Path,
    finalist_status_payload: Mapping[str, Any],
    excluded_records: Sequence[Mapping[str, Any]],
    routing: ContestDirectSkillRoutingArtifact,
    routing_path: Path,
    skill_manifest_path: Path,
    hypotheses: Any,
    hypothesis_path: Path,
    adapter_receipt_path: Path,
    pilot_brief_path: Path,
    pilot: ContestPrimePreexperimentArtifact,
    pilot_path: Path,
    postpilot: Any,
    postpilot_path: Path,
    provisional: ContestDirectPlanArtifact,
    provisional_path: Path,
    plan: ContestDirectPlanRevisionArtifact,
    plan_path: Path,
    rendered: ContestDirectPlanArtifacts,
    page_count: int,
    page_count_method: str,
    final_review: ContestDirectPlanScientificReviewArtifact,
    review_root: Path,
) -> dict[str, Any]:
    recommendation = _scientific_review_recommendation(final_review)
    completion_status = _scientific_completion_status(recommendation)
    if completion_status is None:
        raise ContestDirectionResearchLoopError(
            "blocking independent scientific review cannot produce a completed report"
        )
    delivery_source_accounting = _delivery_source_checkpoint_accounting(
        root=root,
        provenance=source_accounting,
    )
    feedback_calls, objective_review_calls = _postpilot_call_breakdown(postpilot)
    hypothesis_calls = _model_call_count(hypotheses)
    checkpoint_resume = bool(source_accounting and source_accounting.get("checkpoint_resume"))
    scientific_stage_calls = {
        "broad-literature-query": literature_state.broad.query_model_calls,
        "focus-selection": literature_state.focus.model_call_count_at_creation,
        "targeted-literature-query": literature_state.targeted.query_model_calls,
        "planning-literature-gap-repair-query": (
            literature_state.gap_response.model_calls
            if literature_state.gap_response is not None
            else 0
        ),
        "skill-routing": routing.model_calls,
        "hypothesis-brainstorm": hypothesis_calls,
        "provisional-plan": provisional.generation_calls,
        "postpilot-objective-review": _model_call_count(postpilot),
        "final-plan-revision": plan.generation_calls,
        "independent-scientific-review": final_review.generation_calls,
    }
    planning_targeted_record_ids = {
        str(item.get("record_id") or "")
        for item in literature_state.planning_catalog
        if "targeted_direction" in {str(stage) for stage in (item.get("source_stages") or ())}
    }
    routing_record_ids = set(getattr(routing, "literature_evidence_record_ids", ()) or ())
    hypothesis_targeted_reference_indices = sorted(
        {
            index
            for candidate in _candidate_payloads(hypotheses)
            for index in candidate.get("reference_indices", ())
            if isinstance(index, int)
            and 1 <= index <= len(literature_state.planning_catalog)
            and str(literature_state.planning_catalog[index - 1].get("record_id") or "")
            in planning_targeted_record_ids
        }
    )
    scientific_call_total = sum(scientific_stage_calls.values())
    this_loop_calls = (
        _nonnegative_int(
            source_accounting.get("current_scientific_model_calls", 0),
            label="current resumed scientific model calls",
        )
        if checkpoint_resume and source_accounting is not None
        else scientific_call_total
    )
    if this_loop_calls > scientific_call_total:
        raise ContestDirectionResearchLoopError(
            "current resumed scientific calls exceed total provenance calls"
        )
    historical_calls = scientific_call_total - this_loop_calls
    provider_accounting_by_stage = {
        stage: provider_checkpoint_accounting(root, stage_name=stage)
        for stage in _OUTER_MODEL_STAGES
    }
    provider_attempts_by_stage = {
        stage: counts["attempt_count"] for stage, counts in provider_accounting_by_stage.items()
    }
    outer_escrow_by_stage = {
        stage: counts["completed_count"] for stage, counts in provider_accounting_by_stage.items()
    }
    context_compaction_calls = sum(
        max(0, outer_escrow_by_stage[stage] - scientific_stage_calls.get(stage, 0))
        for stage in _OUTER_MODEL_STAGES
    )
    physical_provider_attempt_total = sum(provider_attempts_by_stage.values())
    if physical_provider_attempt_total < scientific_call_total:
        raise ContestDirectionResearchLoopError(
            "physical provider attempt checkpoints undercount scientific model calls"
        )
    review_path = review_root / "system-plan-scientific-review.json"
    artifacts = {
        "direction_input": _file_binding(direction_input_path),
        **_two_stage_literature_artifact_bindings(literature_state),
        "finalist_status_verification": {
            **_file_binding(finalist_status_path),
            "artifact_hash": finalist_status_payload["artifact_hash"],
        },
        "skill_routing": {**_file_binding(routing_path), "artifact_hash": routing.artifact_hash},
        "selected_method_skills": _file_binding(skill_manifest_path),
        "hypothesis_brainstorm": {
            **_file_binding(hypothesis_path),
            "artifact_hash": _artifact_hash(hypotheses),
        },
        "adapter_selection": _file_binding(adapter_receipt_path),
        "internal_provisional_plan": {
            **_file_binding(provisional_path),
            "artifact_hash": provisional.artifact_hash,
            "delivery_status": "internal_not_final_not_rendered",
        },
        "pilot_brief": _file_binding(pilot_brief_path),
        "prime_preexperiment": {
            **_file_binding(pilot_path),
            "artifact_hash": pilot.artifact_hash,
            "run_id": pilot.run_id,
        },
        "postpilot_objective": {
            **_file_binding(postpilot_path),
            "artifact_hash": _artifact_hash(postpilot),
        },
        "final_revised_plan_artifact": {
            **_file_binding(plan_path),
            "artifact_hash": plan.artifact_hash,
            "revision_id": plan.revision_id,
        },
        "rendered_plan": {
            "json": _file_binding(rendered.json_path),
            **(
                {"internal_source": _file_binding(rendered.source_path)}
                if rendered.source_path is not None
                else {}
            ),
            "markdown": _file_binding(rendered.markdown_path),
            "tex": _file_binding(rendered.tex_path),
            "pdf": _file_binding(rendered.pdf_path),
            "manifest": _file_binding(rendered.manifest_path),
        },
        "independent_scientific_review": {
            **_file_binding(review_path),
            "artifact_hash": final_review.artifact_hash,
        },
    }
    inventory = _file_inventory(root)
    return {
        "schema_version": _DELIVERY_SCHEMA,
        "status": completion_status,
        "completed_with_minor_scientific_issues": recommendation == "minor_revision",
        "direction": direction,
        "focused_direction": literature_state.focus.focused_direction_cn,
        "literature_protocol": _LITERATURE_PROTOCOL,
        "scientific_order": [
            "broad_real_literature_retrieval_without_skills",
            "evidence_grounded_focus_selection_without_skills",
            "focused_targeted_real_literature_retrieval_without_skills",
            "coverage_gap_diagnosis_and_at_most_one_bounded_retrieval_repair",
            "merged_verified_role_covered_5_to_10_reference_lock",
            "literature_evidence_aware_skill_routing",
            "parallel_candidate_hypothesis_brainstorm",
            "internal_provisional_candidate_baseline_not_delivered",
            "registered_real_preexperiment",
            "evidence_feedback_and_independent_postpilot_objective_review",
            "one_evidence_guarded_final_plan_revision",
            "final_plan_materialization",
            "independent_nonrewriting_scientific_review",
        ],
        "source_accounting": delivery_source_accounting,
        "model_call_accounting": {
            "broad_retrieval_query_calls": literature_state.broad.query_model_calls,
            "focus_brainstorm_and_selection_calls": (
                literature_state.focus.model_call_count_at_creation
            ),
            "targeted_retrieval_query_calls": literature_state.targeted.query_model_calls,
            "planning_literature_gap_repair_calls": (
                literature_state.gap_response.model_calls
                if literature_state.gap_response is not None
                else 0
            ),
            "literature_aware_skill_routing_calls": routing.model_calls,
            "hypothesis_brainstorm_calls": hypothesis_calls,
            "internal_provisional_plan_calls": provisional.generation_calls,
            "postpilot_evidence_feedback_calls": feedback_calls,
            "postpilot_independent_objective_review_calls": objective_review_calls,
            "postpilot_feedback_integrated_in_objective_review": True,
            "final_evidence_guarded_revision_calls": plan.generation_calls,
            "final_independent_scientific_review_calls": final_review.generation_calls,
            "scientific_model_calls_by_stage": scientific_stage_calls,
            "scientific_model_call_total": scientific_call_total,
            "physical_provider_attempts_by_stage": provider_attempts_by_stage,
            "provider_checkpoint_accounting_by_stage": provider_accounting_by_stage,
            "physical_provider_attempt_total": physical_provider_attempt_total,
            "physical_provider_attempt_semantics": (
                "lifetime_durable_attempt_reservations_deduplicated_by_canonical_stage_owner"
            ),
            "outer_provider_escrow_count_by_stage": outer_escrow_by_stage,
            "outer_provider_escrow_count": sum(outer_escrow_by_stage.values()),
            "context_compaction_calls": context_compaction_calls,
            "legacy_provider_request_attempt_fields_semantics": (
                "logical_scientific_model_calls_v1_compatibility"
            ),
            "this_loop_observed_provider_request_attempts": this_loop_calls,
            "historical_source_provider_request_attempts": historical_calls,
            "total_provenance_provider_request_attempts": scientific_call_total,
            "historical_failed_plan_author_calls": (
                source_accounting.get("historical_failed_plan_author_calls", 0)
                if source_accounting
                else 0
            ),
        },
        "stage_execution": {
            "broad_real_literature_retrieval_without_skills": {
                "stage_attempts": 1,
                "provider_request_attempts": provider_attempts_by_stage["broad-literature-query"],
                "successful_stage_outputs": 1,
                "failed_stage_outputs": 0,
                "status": "completed",
            },
            "evidence_grounded_focus_selection_without_skills": {
                "stage_attempts": 1,
                "provider_request_attempts": provider_attempts_by_stage["focus-selection"],
                "successful_stage_outputs": 1,
                "failed_stage_outputs": 0,
                "status": "completed",
            },
            "focused_targeted_real_literature_retrieval_without_skills": {
                "stage_attempts": 1,
                "provider_request_attempts": provider_attempts_by_stage[
                    "targeted-literature-query"
                ],
                "successful_stage_outputs": 1,
                "failed_stage_outputs": 0,
                "status": "completed",
            },
            "coverage_gap_diagnosis_and_bounded_retrieval_repair": {
                "stage_attempts": 1,
                "provider_request_attempts": provider_attempts_by_stage[
                    "planning-literature-gap-repair-query"
                ],
                "successful_stage_outputs": (
                    1 if literature_state.gap_retrieval is not None else 0
                ),
                "failed_stage_outputs": 0,
                "status": (
                    "completed_one_bounded_repair"
                    if literature_state.gap_retrieval is not None
                    else "not_needed_r1_coverage_passed"
                ),
            },
            "merged_verified_5_to_10_reference_lock": {
                "stage_attempts": 1,
                "provider_request_attempts": 0,
                "successful_stage_outputs": 1,
                "failed_stage_outputs": 0,
                "status": "completed_program_selection",
            },
            "literature_evidence_aware_skill_routing": {
                "stage_attempts": 1,
                "provider_request_attempts": provider_attempts_by_stage["skill-routing"],
                "successful_stage_outputs": 1,
                "failed_stage_outputs": 0,
                "status": "completed",
            },
            "parallel_candidate_hypothesis_brainstorm": {
                "stage_attempts": hypothesis_calls,
                "provider_request_attempts": provider_attempts_by_stage["hypothesis-brainstorm"],
                "successful_stage_outputs": len(_candidate_payloads(hypotheses)),
                "failed_stage_outputs": max(
                    0,
                    hypothesis_calls - len(_candidate_payloads(hypotheses)),
                ),
                "status": "completed",
            },
            "internal_provisional_candidate_baseline": {
                "stage_attempts": 1,
                "provider_request_attempts": provider_attempts_by_stage["provisional-plan"],
                "successful_stage_outputs": 1,
                "failed_stage_outputs": 0,
                "status": "completed_internal_not_delivered",
            },
            "registered_real_preexperiment": {
                "stage_attempts": 1,
                "provider_request_attempts": 0,
                "successful_stage_outputs": 1,
                "failed_stage_outputs": 0,
                "status": "completed_real_exploratory_pilot",
            },
            "postpilot_objective_review": {
                "stage_attempts": 1,
                "provider_request_attempts": provider_attempts_by_stage[
                    "postpilot-objective-review"
                ],
                "successful_stage_outputs": 1,
                "failed_stage_outputs": 0,
                "status": "completed",
            },
            "evidence_guarded_final_plan_revision": {
                "stage_attempts": 1,
                "provider_request_attempts": provider_attempts_by_stage["final-plan-revision"],
                "successful_stage_outputs": 1,
                "failed_stage_outputs": 0,
                "postprovider_validation_failures_recovered": (
                    source_accounting.get("historical_postprovider_validation_failures", 0)
                    if source_accounting
                    else 0
                ),
                "preserved_response_replayed_locally": bool(
                    source_accounting
                    and source_accounting.get("preserved_revision_replayed_locally")
                ),
                "status": "completed",
            },
            "final_plan_materialization": {
                "stage_attempts": 1,
                "provider_request_attempts": 0,
                "successful_stage_outputs": 1,
                "failed_stage_outputs": 0,
                "status": "completed",
            },
            "independent_nonrewriting_scientific_review": {
                "stage_attempts": 1,
                "provider_request_attempts": provider_attempts_by_stage[
                    "independent-scientific-review"
                ],
                "successful_stage_outputs": 1,
                "failed_stage_outputs": 0,
                "status": (
                    "completed_with_minor_issues"
                    if recommendation == "minor_revision"
                    else "completed"
                ),
                "recommendation": recommendation,
            },
        },
        "literature": {
            "retrieval_semantics": literature.retrieval_semantics,
            "broad_artifact_hash": literature_state.broad.artifact_hash,
            "broad_catalog_hash": literature_state.broad.literature_catalog_hash,
            "broad_query_generated_without_skills": not bool(literature_state.broad.method_skills),
            "broad_retrieved_record_count": len(literature_state.broad.retrieved_records),
            "focus_artifact_hash": literature_state.focus.artifact_hash,
            "selected_focus_id": literature_state.focus.selected_focus_id,
            "focused_direction_cn": literature_state.focus.focused_direction_cn,
            "targeted_binding_hash": literature_state.targeted_binding.artifact_hash,
            "targeted_artifact_hash": literature_state.targeted.artifact_hash,
            "targeted_catalog_hash": literature_state.targeted.literature_catalog_hash,
            "targeted_query_generated_without_skills": not bool(
                literature_state.targeted.method_skills
            ),
            "targeted_retrieved_record_count": len(literature_state.targeted.retrieved_records),
            "merged_artifact_hash": literature.artifact_hash,
            "merged_catalog_hash": literature.merged_catalog_hash,
            "merged_record_count": getattr(
                literature,
                "merged_record_count",
                len(getattr(literature, "records", ())),
            ),
            "cross_stage_deduplicated_count": (
                literature_state.base_merged.cross_stage_deduplicated_count
                if literature_state.base_merged is not None
                else getattr(literature, "cross_stage_deduplicated_count", 0)
            ),
            "cross_layer_deduplicated_count": getattr(
                literature,
                "cross_layer_deduplicated_count",
                0,
            ),
            "gap_repair_round_count": 1 if literature_state.gap_retrieval is not None else 0,
            "planning_literature_artifact_hash": literature_state.planning_lock_payload[
                "artifact_hash"
            ],
            "r1_planning_coverage_receipt_hash": (
                literature_state.r1_planning_coverage.receipt_hash
                if literature_state.r1_planning_coverage is not None
                else None
            ),
            "r1_planning_coverage_passed": (
                literature_state.r1_planning_coverage.passed
                if literature_state.r1_planning_coverage is not None
                else None
            ),
            "gap_repair_roles": (
                [item.value for item in literature_state.gap_diagnosis.repairable_roles]
                if literature_state.gap_diagnosis is not None
                else []
            ),
            "gap_repair_response_receipt_hash": (
                literature_state.gap_response.receipt_hash
                if literature_state.gap_response is not None
                else None
            ),
            "gap_repair_retrieval_artifact_hash": (
                literature_state.gap_retrieval.artifact_hash
                if literature_state.gap_retrieval is not None
                else None
            ),
            "planning_reference_count": len(literature_state.planning_catalog),
            "planning_coverage_receipt_hash": (literature_state.planning_coverage.receipt_hash),
            "planning_coverage_passed": literature_state.planning_coverage.passed,
            "planning_coverage_role_counts": (
                literature_state.planning_coverage.selected_role_counts.model_dump(mode="json")
            ),
            "planning_coverage_thresholds": (
                literature_state.planning_coverage.thresholds.model_dump(mode="json")
            ),
            "planning_targeted_origin_record_count": len(planning_targeted_record_ids),
            "skill_routing_record_count": len(routing_record_ids),
            "skill_routing_targeted_origin_record_count": len(
                planning_targeted_record_ids & routing_record_ids
            ),
            "hypothesis_targeted_reference_indices": (hypothesis_targeted_reference_indices),
            "hypothesis_targeted_reference_count": len(hypothesis_targeted_reference_indices),
            "targeted_contribution_boundary": (
                "observational provenance counts only; no mechanical source-stage quota and "
                "no novelty claim without scientific nearest-work comparison"
            ),
            "excluded_records": list(excluded_records),
            "finalist_status_verification_artifact_hash": finalist_status_payload["artifact_hash"],
            "finalist_status_verification_count": finalist_status_payload["verification_count"],
            "finalist_status_excluded_count": sum(
                item.get("outcome") == "excluded_from_positive_planning"
                for item in finalist_status_payload["records"]
            ),
            "finalist_status_excluded_records": [
                {
                    "record_id": item.get("record_id"),
                    "verified_status": item.get("verified_status"),
                    "outcome": item.get("outcome"),
                }
                for item in finalist_status_payload["records"]
                if item.get("outcome") == "excluded_from_positive_planning"
            ],
            "finalist_status_requests_scope": "shortlisted_arxiv_records_only",
            "resume_status_network_requests": 0 if checkpoint_resume else None,
        },
        "skills": {
            "selected_skill_ids": list(routing.selected_skill_ids),
            "literature_evidence_visible_before_metadata": True,
            "skill_bodies_visible_to_selector": False,
        },
        "preexperiment": {
            "adapter_id": _ADAPTER_ID,
            "run_id": pilot.run_id,
            "artifact_hash": pilot.artifact_hash,
            "study_phase": pilot.study_phase,
            "real_execution": True,
            "source_plan_path_role": "pilot_brief_snapshot_only",
            "source_plan_compiled_or_executed": False,
            "formal_experiment_executed": False,
            "mathematical_proof_claimed": False,
        },
        "plan": {
            "internal_provisional_plan_delivered": False,
            "final_revision_id": plan.revision_id,
            "final_artifact_hash": plan.artifact_hash,
            "contains_verified_preexperiment": True,
            "paper_claimed": False,
        },
        "pdf": {
            "path": rendered.pdf_path.resolve().as_posix(),
            "verified_page_count": page_count,
            "page_count_method": page_count_method,
            "maximum_allowed_pages": 20,
        },
        "independent_scientific_review": {
            "artifact_hash": final_review.artifact_hash,
            "recommendation": recommendation,
            "generation_calls": final_review.generation_calls,
            "plan_rewrite_performed": False,
            "independence_scope": final_review.independence_scope,
            "delivery_gate_disposition": (
                "completed_with_minor_issues" if recommendation == "minor_revision" else "completed"
            ),
            "minor_issues_explicitly_retained": recommendation == "minor_revision",
        },
        "artifacts": artifacts,
        "file_inventory": inventory,
        "file_inventory_hash": canonical_model_hash({"files": inventory}),
        "preexperiment_executed": True,
        "formal_experiment_executed": False,
        "paper_claimed": False,
    }


def _file_inventory(root: Path) -> list[dict[str, Any]]:
    report_paths = {
        (root / "delivery-report.json").resolve(),
        (root / "blocked-receipt.json").resolve(),
    }
    memory_root = (root / "memory").resolve()
    records: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        resolved = path.resolve()
        if (
            not resolved.is_file()
            or resolved in report_paths
            or resolved == memory_root
            or memory_root in resolved.parents
        ):
            continue
        records.append(
            {
                "relative_path": resolved.relative_to(root).as_posix(),
                **_file_binding(resolved),
            }
        )
    return records


def _verify_revision_sidecars(
    revision_root: Path,
    plan: ContestDirectPlanRevisionArtifact,
) -> None:
    response = _inside(revision_root, plan.raw_response_relative_path)
    if _sha256_file(response) != plan.model_response_hash:
        raise ContestDirectionResearchLoopError("resume revision response hash mismatch")
    receipt_path = _inside(revision_root, plan.authorship_receipt_relative_path)
    receipt = _read_json(receipt_path)
    if receipt.get("receipt_hash") != plan.authorship_receipt_hash:
        raise ContestDirectionResearchLoopError("resume revision receipt hash mismatch")


def _load_preserved_revision_replay(
    revision_root: Path,
) -> Callable[..., LLMJsonCompletionResult] | None:
    """Return a hash-checked local replay for one already-paid revision response.

    A provider response may be durably recorded before the downstream scientific
    number guard accepts it.  On checkpoint resume, those bytes are the one allowed
    revision call: invoking the provider again would both spend tokens and silently
    turn a one-shot stage into a retry loop.  This loader therefore reconstructs the
    completion strictly from its immutable authorship receipt and refuses ambiguous
    or partial sidecars.
    """

    response_root = revision_root / "responses"
    receipt_root = revision_root / "interactions"
    responses = sorted(response_root.glob("*.txt")) if response_root.is_dir() else []
    receipts = sorted(receipt_root.glob("*.json")) if receipt_root.is_dir() else []
    if not responses and not receipts:
        return None
    if len(responses) != 1 or len(receipts) != 1:
        # The bounded revision may legitimately persist more than one
        # guard-rejected attempt.  An ambiguous sidecar set is left for the
        # checkpointed stage (which replays by stage hash or makes one fresh
        # call) instead of fabricating a replay.
        return None
    response_path = responses[0].resolve()
    receipt_path = receipts[0].resolve()
    try:
        receipt = ModelAuthorshipReceipt.model_validate_json(
            receipt_path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise ContestDirectionResearchLoopError(
            "resume preserved revision receipt is invalid"
        ) from exc
    if (
        receipt.artifact_kind != "research_plan"
        or receipt.attempt != 1
        or receipt.interaction_id != response_path.stem
        or receipt_path.stem != receipt.interaction_id
    ):
        raise ContestDirectionResearchLoopError(
            "resume preserved revision is not the unique first research-plan attempt"
        )
    response_bytes = response_path.read_bytes()
    if hashlib.sha256(
        response_bytes
    ).hexdigest() != receipt.response_sha256 or response_bytes != receipt.response_text.encode(
        "utf-8"
    ):
        raise ContestDirectionResearchLoopError(
            "resume preserved revision response differs from its authorship receipt"
        )

    context_kwargs: dict[str, Any] = {}
    if receipt.context_preparation_hash is not None:
        assert receipt.delivered_messages_sha256 is not None
        assert receipt.context_preparation_relative_path is not None
        context_path = _inside(revision_root, receipt.context_preparation_relative_path)
        from autoresearch.llm.task_context import TaskContextPreparationArtifact

        try:
            context_artifact = TaskContextPreparationArtifact.model_validate_json(
                context_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise ContestDirectionResearchLoopError(
                "resume preserved revision context preparation is invalid"
            ) from exc
        if (
            context_artifact.artifact_hash != receipt.context_preparation_hash
            or context_artifact.active_task_messages_sha256 != receipt.messages_sha256
            or context_artifact.delivered_messages_sha256 != receipt.delivered_messages_sha256
        ):
            raise ContestDirectionResearchLoopError(
                "resume preserved revision context preparation binding mismatch"
            )
        context_kwargs = {
            "request_messages_sha256": receipt.delivered_messages_sha256,
            "source_messages_sha256": receipt.messages_sha256,
            "context_preparation_hash": receipt.context_preparation_hash,
            "context_preparation_path": context_path.as_posix(),
        }
    completion = LLMJsonCompletionResult(
        provider=receipt.provider,
        base_url=receipt.base_url,
        model_name=receipt.model_name,
        endpoint=receipt.endpoint,
        response_text=receipt.response_text,
        parsed_json=receipt.parsed_payload,
        transport_normalization=receipt.transport_normalization,
        normalization_suffix=receipt.normalization_suffix,
        usage=receipt.usage,
        temperature=receipt.temperature,
        reasoning_text=receipt.reasoning_content,
        reasoning_transport=receipt.reasoning_transport,
        **context_kwargs,
    )

    def replay(**kwargs: Any) -> LLMJsonCompletionResult:
        messages = kwargs.get("messages")
        if not isinstance(messages, Sequence) or isinstance(messages, str | bytes):
            raise ContestDirectionResearchLoopError(
                "local revision replay did not receive the reconstructed message sequence"
            )
        try:
            normalized_messages = [dict(item) for item in messages]
        except (TypeError, ValueError) as exc:
            raise ContestDirectionResearchLoopError(
                "local revision replay received malformed messages"
            ) from exc
        if canonical_model_hash({"messages": normalized_messages}) != receipt.messages_sha256:
            raise ContestDirectionResearchLoopError(
                "local revision replay inputs differ from the preserved provider call"
            )
        return completion

    return replay


def _load_rendered_plan(root: Path) -> ContestDirectPlanArtifacts:
    manifest_path = root / "research-plan-manifest.json"
    manifest = _read_json(manifest_path)
    if (
        manifest.get("schema_version") != "contest-direct-plan-render-v3"
        or manifest.get("compile_status") != "compiled"
        or manifest.get("pdf_text_verified") is not True
    ):
        raise ContestDirectionResearchLoopError(
            "resume rendered plan is not a self-contained v3 delivery; "
            "rematerialization is required"
        )
    names = {
        "json": root / "research-plan.json",
        "markdown": root / "research-plan.md",
        "tex": root / "research-plan.tex",
        "pdf": root / "research-plan.pdf",
    }
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise ContestDirectionResearchLoopError("resume render manifest lacks artifacts")
    for key, path in names.items():
        binding = artifacts.get(key)
        if not isinstance(binding, Mapping):
            raise ContestDirectionResearchLoopError(f"resume render manifest lacks {key} binding")
        if binding.get("filename") != path.name:
            raise ContestDirectionResearchLoopError(f"resume render filename mismatch: {key}")
        _verify_file_binding(path, binding)
    source_path: Path | None = None
    source_binding = artifacts.get("source")
    if not isinstance(source_binding, Mapping):
        raise ContestDirectionResearchLoopError(
            "resume self-contained render lacks private source binding"
        )
    source_path = root / "_private" / "research-plan-source.json"
    if source_binding.get("filename") != "_private/research-plan-source.json":
        raise ContestDirectionResearchLoopError("resume render filename mismatch: source")
    _verify_file_binding(source_path, source_binding)
    public_payload = _read_json(names["json"])
    expected_public_hash = canonical_model_hash(public_payload)
    recorded_public_hash = manifest.get("public_payload_sha256")
    if recorded_public_hash is not None and recorded_public_hash != expected_public_hash:
        raise ContestDirectionResearchLoopError("resume rendered public payload hash mismatch")
    source_payload = _read_json(source_path)
    expected_source_hash = canonical_model_hash(source_payload)
    if manifest.get("source_payload_sha256") != expected_source_hash:
        raise ContestDirectionResearchLoopError("resume rendered source payload hash mismatch")
    page_count = manifest.get("page_count")
    if page_count is not None and (
        isinstance(page_count, bool) or not isinstance(page_count, int) or page_count < 1
    ):
        raise ContestDirectionResearchLoopError("resume rendered page count is invalid")
    return ContestDirectPlanArtifacts(
        output_dir=root,
        json_path=names["json"],
        markdown_path=names["markdown"],
        tex_path=names["tex"],
        pdf_path=names["pdf"],
        manifest_path=manifest_path,
        source_payload_sha256=expected_source_hash,
        page_count=page_count,
        pdf_text_verified=True,
        source_path=source_path,
    )


def _prepare_empty_output(path: Path) -> None:
    if path.exists():
        if not path.is_dir() or any(path.iterdir()):
            raise ContestDirectionResearchLoopError(
                f"output directory must be new or empty: {path}"
            )
    else:
        path.mkdir(parents=True, exist_ok=False)


def _quarantine_partial_output(root: Path, path: Path, stage_hash: str) -> Path | None:
    """Move an incomplete derived stage aside so escrowed calls can rematerialize.

    Nothing is deleted.  The interrupted bytes remain under the run's checkpoint
    tree for diagnosis, while the scientific runner receives the empty output
    directory contract it already enforces.
    """

    run_root = root.resolve()
    stage_root = path.resolve()
    try:
        relative = stage_root.relative_to(run_root)
    except ValueError as exc:
        raise ContestDirectionResearchLoopError(
            "partial stage output escapes the research-loop root"
        ) from exc
    if not stage_root.exists() or (stage_root.is_dir() and not any(stage_root.iterdir())):
        return None
    if not stage_root.is_dir():
        raise ContestDirectionResearchLoopError("partial stage output is not a directory")
    quarantine_root = run_root / "checkpoints" / "interrupted-stage-outputs"
    quarantine_root.mkdir(parents=True, exist_ok=True)
    stem = "-".join(relative.parts).replace("_", "-") or "stage"
    for sequence in range(1, 10_000):
        destination = quarantine_root / f"{stem}-{stage_hash[:16]}-{sequence:04d}"
        if not destination.exists():
            stage_root.replace(destination)
            return destination
    raise ContestDirectionResearchLoopError("too many interrupted stage-output quarantines")


def _artifact_json_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        payload = dump(mode="json")
        if isinstance(payload, dict):
            return payload
    raise ContestDirectionResearchLoopError("value is not a structured artifact")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContestDirectionResearchLoopError(f"invalid JSON artifact {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContestDirectionResearchLoopError(f"JSON artifact is not an object: {path}")
    return payload


def _write_new_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
    except FileExistsError as exc:
        raise ContestDirectionResearchLoopError(
            f"refusing to overwrite loop artifact: {path}"
        ) from exc


def _inside(root: Path, relative: str) -> Path:
    candidate = (root / Path(*PurePosixPath(relative).parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ContestDirectionResearchLoopError(
            f"artifact escapes delivery root: {relative}"
        ) from exc
    return candidate


def _file_binding(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ContestDirectionResearchLoopError(f"bound file does not exist: {resolved}")
    return {
        "path": resolved.as_posix(),
        "sha256": _sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def _verify_file_binding(path: Path, binding: Mapping[str, Any]) -> None:
    actual = _file_binding(path)
    if binding.get("sha256") != actual["sha256"]:
        raise ContestDirectionResearchLoopError(f"bound file hash mismatch: {path}")
    recorded_size = binding.get("size_bytes", binding.get("bytes"))
    if recorded_size != actual["size_bytes"]:
        raise ContestDirectionResearchLoopError(f"bound file size mismatch: {path}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _nonnegative_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContestDirectionResearchLoopError(f"{label} must be a nonnegative integer")
    return int(value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "指定方向经无Skill广泛真实检索、证据聚焦、无Skill定向真实检索、"
            "5–10条书目锁定、文献感知Skill路由、候选假设、真实预实验、证据反馈、"
            "独立目标评审、详细计划与最终独立科学评审形成闭环。"
        )
    )
    parser.add_argument("--direction", required=True)
    parser.add_argument("--output-dir", type=Path, default=_DEFAULT_OUTPUT)
    parser.add_argument(
        "--resume-existing",
        action="store_true",
        help="严格重验同一输出目录的checkpoint，并从首个缺失阶段继续；不覆盖已有制品。",
    )
    parser.add_argument(
        "--source-direction-delivery",
        type=Path,
        default=None,
        help=(
            "已停用的旧单检索复用参数；两阶段协议会明确拒绝它。"
            "请使用新的空输出目录fresh运行，或对同一v2目录使用--resume-existing。"
        ),
    )
    parser.add_argument(
        "--preexperiment-policy",
        choices=("required", "if-supported"),
        default="required",
    )
    parser.add_argument("--skills-root", type=Path, default=_DEFAULT_SKILLS_ROOT)
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument(
        "--disable-dreaming-recall",
        action="store_true",
        help=("关闭后续模型阶段对可重建Dreaming导航的可选读取；已完成制品仍会尽力进入OB原始记忆。"),
    )
    parser.add_argument(
        "--max-results-per-search",
        type=int,
        default=_DEFAULT_RESULTS_PER_SEARCH,
        help=(
            "每条查询在每个数据源的一次 API 请求中返回的候选上限（默认 20）；"
            "扩大候选池，但不增加查询数×数据源数的请求次数。"
        ),
    )
    parser.add_argument("--retrieval-max-tokens", type=int, default=768)
    parser.add_argument("--skill-routing-max-tokens", type=int, default=1_024)
    parser.add_argument("--brainstorm-max-tokens", type=int, default=3_000)
    parser.add_argument("--feedback-max-tokens", type=int, default=3_500)
    parser.add_argument("--objective-review-max-tokens", type=int, default=4_000)
    parser.add_argument("--plan-max-tokens", type=int, default=14_000)
    parser.add_argument("--scientific-review-max-tokens", type=int, default=8_000)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--thinking-budget", type=int, default=3_000)
    parser.add_argument("--render-timeout-seconds", type=int, default=180)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_contest_direction_research_loop(
        direction=args.direction,
        output_dir=args.output_dir,
        resume_existing=args.resume_existing,
        source_direction_delivery=args.source_direction_delivery,
        preexperiment_policy=args.preexperiment_policy.replace("-", "_"),
        skills_root=args.skills_root,
        config_path=args.config,
        env_path=args.env,
        dreaming_recall_enabled=not args.disable_dreaming_recall,
        max_results_per_search=args.max_results_per_search,
        retrieval_max_tokens=args.retrieval_max_tokens,
        skill_routing_max_tokens=args.skill_routing_max_tokens,
        brainstorm_max_tokens=args.brainstorm_max_tokens,
        feedback_max_tokens=args.feedback_max_tokens,
        objective_review_max_tokens=args.objective_review_max_tokens,
        plan_max_tokens=args.plan_max_tokens,
        scientific_review_max_tokens=args.scientific_review_max_tokens,
        timeout_seconds=args.timeout_seconds,
        thinking_budget=args.thinking_budget,
        render_timeout_seconds=args.render_timeout_seconds,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by module smoke
    raise SystemExit(main())


__all__ = [
    "ContestDirectionResearchLoopError",
    "main",
    "run_contest_direction_research_loop",
]
