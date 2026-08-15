from __future__ import annotations

import os
from pathlib import Path

import pytest

from autoresearch.knowledge.raw_memory import RawMemoryStore
from autoresearch.research.adaptive_capabilities import (
    AdaptiveLiteratureRetrievalArtifact,
    AdaptiveResearchCapabilityEnvironment,
)
from autoresearch.research.adaptive_skill_router import RepositoryQwenSkillProvider
from autoresearch.research.adaptive_sovereign_loop import (
    AdaptiveLoopPolicy,
    AdaptiveLoopRunStatus,
    AdaptiveResearchLoopSnapshot,
    AdaptiveResearchSeed,
    ExternalResearchFeedback,
    ModelResearchActionDraft,
    ResearchActionEnvironment,
    ResearchOperator,
    create_adaptive_research_seed,
    initialize_adaptive_research_loop,
    run_adaptive_research_loop,
)


class _ConceptualOnlyEnvironment(ResearchActionEnvironment):
    def supported_operators(self) -> frozenset[ResearchOperator]:
        return frozenset()

    def execute(
        self,
        *,
        seed: AdaptiveResearchSeed,
        snapshot: AdaptiveResearchLoopSnapshot,
        proposal: ModelResearchActionDraft,
    ) -> ExternalResearchFeedback:
        del seed, snapshot, proposal
        raise AssertionError("the live conceptual smoke has no external-action budget")


def test_real_qwen_selects_skills_and_runs_without_intermediate_user_prompts(
    tmp_path: Path,
) -> None:
    if os.getenv("RUN_LIVE_ADAPTIVE_LOOP") != "1":
        pytest.skip("set RUN_LIVE_ADAPTIVE_LOOP=1 for the bounded provider smoke")

    store = RawMemoryStore(tmp_path / "autoresearch-vault")
    seed = create_adaptive_research_seed(
        loop_id="live_adaptive_qwen_smoke",
        project_id="live_adaptive_qwen_smoke",
        objective_cn=(
            "自主探索一种能让科研Agent长期保留原始记忆、同时避免错误派生记忆反复污染"
            "后续推理的通用可证伪研究问题。"
        ),
        scope_cn=(
            "本次只允许形成和批判未验证假设，不联网、不运行实验、不声称创新、" "不申请执行或发表。"
        ),
        raw_memory_store=store,
    )
    output_dir = tmp_path / "adaptive-loop"
    skill_provider = RepositoryQwenSkillProvider(
        skill_root=Path("skills"),
        output_dir=output_dir,
        raw_memory_store=store,
        maximum_selected_skills=3,
        thinking_budget=2_000,
    )

    result = run_adaptive_research_loop(
        seed=seed,
        policy=AdaptiveLoopPolicy(
            policy_id="live-conceptual-two-turn-smoke",
            max_steps=2,
            max_model_calls=4,
            max_external_actions=0,
            max_temporary_agents=0,
            thinking_budget=2_000,
        ),
        raw_memory_store=store,
        output_dir=output_dir,
        environment=_ConceptualOnlyEnvironment(),
        skill_provider=skill_provider,
    )

    assert len(result.events) == 2
    assert result.status is AdaptiveLoopRunStatus.PAUSED_BUDGET
    assert result.model_call_count == len(result.events) * 2
    assert result.skill_routing_model_call_count == len(result.events)
    assert all("qwen" in event.interaction.model_name.casefold() for event in result.events)
    assert all(event.interaction.reasoning_character_count >= 200 for event in result.events)
    assert all(
        event.interaction.proposal.human_authored_scientific_prose_count == 0
        for event in result.events
    )
    assert all(not event.interaction.proposal.execution_authorized for event in result.events)
    assert all(not event.interaction.proposal.publication_authorized for event in result.events)
    assert list((output_dir / "skill-routing").glob("step-*/adaptive-skill-routing.json"))


def test_real_literature_sources_enter_sovereign_memory_before_feedback(
    tmp_path: Path,
) -> None:
    if os.getenv("RUN_LIVE_ADAPTIVE_RETRIEVAL") != "1":
        pytest.skip("set RUN_LIVE_ADAPTIVE_RETRIEVAL=1 for the live source smoke")

    store = RawMemoryStore(tmp_path / "autoresearch-vault")
    seed = create_adaptive_research_seed(
        loop_id="live_adaptive_retrieval_smoke",
        project_id="live_adaptive_retrieval_smoke",
        objective_cn="检索 agent memory state trajectory 的近期直接先前工作。",
        scope_cn="只保留公开文献元数据与摘要，不将检索结果冒充全文证据。",
        raw_memory_store=store,
    )
    snapshot = initialize_adaptive_research_loop(
        seed=seed,
        policy=AdaptiveLoopPolicy(
            policy_id="live-adaptive-retrieval-smoke",
            max_steps=1,
            max_model_calls=1,
            max_external_actions=1,
            max_temporary_agents=0,
        ),
        raw_memory_store=store,
    )
    proposal = ModelResearchActionDraft(
        step_index=1,
        branch_id="branch_root",
        operator=ResearchOperator.RETRIEVE_EVIDENCE,
        action_title_cn="检索 agent memory state trajectory 的直接先前工作",
        action_body_cn="查询状态轨迹、修订与遗忘方面的直接先前工作。",
        retrieval_query_terms=[
            "agent memory",
            "trajectory update",
            "forgetting benchmark",
        ],
        reason_for_choice_cn="真实来源比继续内部猜测更能识别直接重复和证据缺口。",
        expected_information_gain_cn="获得可追溯论文元数据、摘要和失败来源记录。",
    )
    output_dir = tmp_path / "adaptive-retrieval"
    environment = AdaptiveResearchCapabilityEnvironment(
        output_dir=output_dir,
        raw_memory_store=store,
        max_results_per_source=2,
    )

    feedback = environment.execute(
        seed=seed,
        snapshot=snapshot,
        proposal=proposal,
    )

    artifact_path = (
        output_dir
        / "capabilities"
        / "step-0001"
        / "retrieval"
        / "adaptive-literature-retrieval.json"
    )
    artifact = AdaptiveLiteratureRetrievalArtifact.model_validate_json(artifact_path.read_bytes())
    assert any(item.succeeded for item in artifact.fetches)
    assert artifact.papers
    assert feedback.source_refs == [paper.source_ref for paper in artifact.papers]
    capture = store.load_record(
        artifact.normalized_catalog_binding.record_relative_path,
        project_id=seed.project_id,
    )
    assert capture.binding(store.vault_root) == artifact.normalized_catalog_binding
    assert artifact.full_text_verified is False
    assert feedback.is_scientific_evidence is False
