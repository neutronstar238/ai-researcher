from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from autoresearch.knowledge.raw_memory import RawMemoryStore
from autoresearch.literature.models import AcademicPaper
from autoresearch.llm.client import LLMJsonCompletionResult
from autoresearch.research.adaptive_autonomy_audit import (
    AdaptiveAutonomyAudit,
    audit_adaptive_research_autonomy,
)
from autoresearch.research.adaptive_exploration_runtime import (
    run_capability_adaptive_exploration,
)
from autoresearch.research.adaptive_promotion_verifier import (
    AdaptivePriorWorkComparison,
    AdaptivePromotionReviewDraft,
    AdaptivePromotionVerificationError,
    AdaptivePromotionVerifierArtifact,
)
from autoresearch.research.adaptive_skill_router import AdaptiveSkillSelectionDraft
from autoresearch.research.adaptive_sovereign_loop import (
    AdaptiveLoopRunStatus,
    ModelResearchActionDraft,
    PromotionDraft,
    ResearchOperator,
)

_REASONING = (
    "我先区分开放探索、机械晋级和独立科学审查三个阶段，再核对当前输入的来源、"
    "反例、判别性对照、资源边界与权限声明。摘要层比较只能排除当前可见材料中的"
    "直接重复，不能证明全文新颖性，更不能替代实验、人工范围审批或发表授权。"
) * 4


class _LiteratureClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, *, limit: int = 10) -> list[AcademicPaper]:
        self.calls.append((query, limit))
        return [
            AcademicPaper(
                title="Dynamic Zettelkasten Memory for LLM Agents",
                authors=["First Author"],
                abstract=(
                    "A memory system creates linked notes and updates derived "
                    "representations as new observations arrive."
                ),
                publication_date=date(2025, 2, 1),
                url="https://example.org/memory-a",
                source="openalex",
            ),
            AcademicPaper(
                title="Evaluating Long-Term Conversational Memory",
                authors=["Second Author"],
                abstract=(
                    "The benchmark measures temporal reasoning, updates, "
                    "abstention, and multi-session information integration."
                ),
                publication_date=date(2024, 10, 1),
                url="https://example.org/memory-b",
                source="openalex",
            ),
        ][:limit]


def _write_skill(skill_root: Path) -> None:
    directory = skill_root / "counterfactual-memory-review"
    directory.mkdir(parents=True)
    directory.joinpath("SKILL.md").write_text(
        """---
name: counterfactual-memory-review
description: 检查记忆机制的反例、混杂、对照和可证伪边界，不提供事实或科学结论。
---

# 记忆反例审查

把处理变量、基线、失败条件和替代解释分开检查；技能本身不是证据。
""",
        encoding="utf-8",
    )


def _action(step_index: int, operator: ResearchOperator) -> dict[str, Any]:
    values: dict[str, Any] = {
        "step_index": step_index,
        "branch_id": "branch_root",
        "operator": operator,
        "action_title_cn": "由主Agent自主选择的记忆研究动作",
        "action_body_cn": (
            "比较原始追加日志与可重建派生状态，主动寻找状态更新、错误继承和遗忘的反例。"
        ),
        "reason_for_choice_cn": "该动作比重复内部反思更可能减少关键不确定性。",
        "expected_information_gain_cn": "能够区分直接重复、相邻机制与仍待检验的组合。",
        "selected_skill_ids": [],
        "source_refs": [],
        "temporary_tasks": [],
    }
    if operator is ResearchOperator.RETRIEVE_EVIDENCE:
        values["action_body_cn"] = "检索记忆溯源、更新与反例方面的外部证据。"
        values["retrieval_query_terms"] = [
            "agent memory",
            "memory provenance",
            "memory update",
        ]
    if operator is ResearchOperator.PROMOTE_BRANCH:
        refs = [
            "https://example.org/memory-a",
            "https://example.org/memory-b",
        ]
        values["source_refs"] = refs
        values["promotion_draft"] = PromotionDraft(
            research_question_cn="双层主权记忆能否降低自主科研循环的错误状态继承？",
            hypothesis_cn="原始层不可变、派生层可失效重建将降低陈旧结论继续支配动作的概率。",
            mechanism_cn="原始事实与可变工作状态分离，使新证据能替换派生头而不删除历史。",
            falsifier_cn="若相同预算下错误继承率不降，或溯源完整率下降，则否定该假设。",
            decisive_test_cn="在注入陈旧结论与后续纠正的任务上做配对轨迹比较。",
            baseline_and_control_cn="基线使用单一可覆盖摘要；处理组只改变原始层与派生层分离。",
            novelty_boundary_cn="仅申请验证当前组合，不声称摘要检索已证明创新。",
            known_uncertainties_cn=["派生检索噪声可能抵消状态分层带来的收益。"],
            source_refs=refs,
            requested_cpu_count=2,
            requested_memory_mb=2_048,
            requested_walltime_seconds=300,
        ).model_dump(mode="json")
    return ModelResearchActionDraft(**values).model_dump(mode="json")


class _LoopCompletion:
    def __init__(
        self,
        *,
        reject_promotion: bool = False,
        review_provider: str = "dashscope-qwen",
    ) -> None:
        self.reject_promotion = reject_promotion
        self.review_provider = review_provider
        self.action_calls = 0
        self.review_calls = 0

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        schema_name = kwargs["response_schema_name"]
        messages = kwargs["messages"]
        if schema_name == "adaptive_skill_selection":
            context = json.loads(messages[1]["content"])
            payload = AdaptiveSkillSelectionDraft(
                step_index=context["step_index"],
                branch_id=context["branch_id"],
                task_classification_cn="当前动作属于通用记忆研究编排，不需要强行选择学科技能。",
                selected_skill_ids=[],
                selection_rationale_cn=(
                    "现阶段先让主Agent基于检索反馈自主决定动作，避免无关技能收窄创新空间。"
                ),
            ).model_dump(mode="json")
            return _result(payload)
        if schema_name == "adaptive_research_action":
            self.action_calls += 1
            if self.action_calls == 1:
                return _result(_action(1, ResearchOperator.RETRIEVE_EVIDENCE))
            if self.action_calls == 2:
                return _result(_action(2, ResearchOperator.PROMOTE_BRANCH))
            return _result(_action(3, ResearchOperator.STOP_EXPLORATION))
        if schema_name == "adaptive_promotion_review":
            self.review_calls += 1
            context = json.loads(messages[1]["content"])
            papers = context["逐字保留的检索记录"]
            comparisons = [
                AdaptivePriorWorkComparison(
                    source_ref=paper["source_ref"],
                    overlap_cn="该工作同样处理长期记忆组织或状态更新问题。",
                    difference_cn="当前摘要未直接给出原始不可变层与可失效派生头的配对轨迹检验。",
                    direct_method_copy=(self.reject_promotion and index == 0),
                    insufficient_abstract=False,
                )
                for index, paper in enumerate(papers)
            ]
            payload = AdaptivePromotionReviewDraft(
                question_hypothesis_mechanism_coherent=True,
                decisive_test_targets_falsifier=True,
                falsifier_is_operational=True,
                control_is_discriminating=True,
                resource_scope_feasible=True,
                prior_work_comparisons=comparisons,
                findings_cn=(
                    ["第一项先前工作与候选机制直接重复，当前方向不得晋级。"]
                    if self.reject_promotion
                    else []
                ),
            ).model_dump(mode="json")
            return _result(payload, provider=self.review_provider)
        raise AssertionError(f"unexpected schema: {schema_name}")


def _result(
    payload: dict[str, Any],
    *,
    provider: str = "dashscope-qwen",
) -> LLMJsonCompletionResult:
    return LLMJsonCompletionResult(
        provider=provider,
        base_url="https://example.invalid/v1",
        model_name=("qwen3.7-test" if "qwen" in provider.casefold() else "other-model"),
        endpoint="https://example.invalid/v1/chat/completions",
        response_text=json.dumps(payload, ensure_ascii=False),
        parsed_json=payload,
        usage={},
        temperature=0.1,
        reasoning_text=_REASONING,
        reasoning_transport="dashscope_enable_thinking",
    )


def _run(tmp_path: Path, completion: _LoopCompletion) -> Any:
    skill_root = tmp_path / "skills"
    _write_skill(skill_root)
    return run_capability_adaptive_exploration(
        loop_id="adaptive-promotion-test",
        project_id="adaptive_promotion_test",
        objective_cn="自主发现可证伪的长期记忆状态更新机制。",
        scope_cn="允许检索和开放探索；晋级后等待人工，不执行实验或发表。",
        output_dir=tmp_path / "run",
        vault_root=tmp_path / "vault",
        skill_root=skill_root,
        max_steps=3,
        max_external_actions=3,
        max_temporary_agents=0,
        completion=completion,
        literature_clients={"openalex": _LiteratureClient()},
    )


def test_one_seed_retrieves_then_independently_verifies_promotion(
    tmp_path: Path,
) -> None:
    completion = _LoopCompletion()

    snapshot = _run(tmp_path, completion)

    assert snapshot.status is AdaptiveLoopRunStatus.PAUSED_HUMAN_SCOPE
    assert [event.interaction.proposal.operator for event in snapshot.events] == [
        ResearchOperator.RETRIEVE_EVIDENCE,
        ResearchOperator.PROMOTE_BRANCH,
    ]
    assert completion.action_calls == 2
    assert completion.review_calls == 1
    verification = snapshot.events[-1].formal_verification
    assert verification is not None and verification.passed
    assert verification.innovation_verified is False
    assert snapshot.formal_execution_authorized is False
    artifact_path = (
        tmp_path / "run" / "verification" / "step-0002" / "adaptive-promotion-verification.json"
    )
    artifact = AdaptivePromotionVerifierArtifact.model_validate_json(artifact_path.read_bytes())
    assert artifact.verification == verification
    assert len(artifact.selected_papers) == 2
    assert artifact.scientific_evidence_established is False
    final_snapshot_path = next((tmp_path / "run" / "snapshots").glob("step-0002-*.json"))
    audit_path = tmp_path / "run" / "audit" / "adaptive-autonomy-audit.json"
    audit = audit_adaptive_research_autonomy(
        final_snapshot_path,
        raw_memory_store=RawMemoryStore(tmp_path / "vault"),
        output_path=audit_path,
    )
    assert not audit.controller_self_loop_verified
    assert not audit.model_selected_every_operator
    assert all(item.declared_qwen_model_identity for item in audit.turn_evidence)
    assert all(not item.provider_transport_independently_anchored for item in audit.turn_evidence)
    assert any("独立传输锚" in item for item in audit.findings_cn)
    assert audit.post_start_human_scientific_message_count == 0
    assert audit.previous_feedback_exposure_rate == 1.0
    assert audit.scientific_correctness_verified is False
    assert AdaptiveAutonomyAudit.model_validate_json(audit_path.read_bytes()) == audit


def test_independent_decline_returns_feedback_then_main_agent_can_stop(
    tmp_path: Path,
) -> None:
    completion = _LoopCompletion(reject_promotion=True)

    snapshot = _run(tmp_path, completion)

    assert snapshot.status is AdaptiveLoopRunStatus.STOPPED_BY_MODEL
    assert completion.action_calls == 3
    declined = snapshot.events[1].formal_verification
    assert declined is not None and not declined.passed
    assert "直接重复" in declined.findings_cn[0]
    assert snapshot.events[2].interaction.proposal.operator is (ResearchOperator.STOP_EXPLORATION)


def test_non_qwen_independent_reviewer_fails_closed(tmp_path: Path) -> None:
    completion = _LoopCompletion(review_provider="untrusted-provider")

    with pytest.raises(
        AdaptivePromotionVerificationError,
        match="not the configured Qwen model",
    ):
        _run(tmp_path, completion)
