from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.knowledge.raw_memory import RawMemorySourceKind, RawMemoryStore
from autoresearch.llm.client import LLMJsonCompletionResult
from autoresearch.research.adaptive_autonomy_audit import (
    audit_adaptive_research_autonomy,
)
from autoresearch.research.adaptive_loop_benchmark import AdaptiveLoopBenchmarkArm
from autoresearch.research.adaptive_loop_benchmark_arm_adapters import (
    FIXED_BENCHMARK_OPERATOR_SEQUENCE,
    AdaptiveLoopBenchmarkArmError,
    BenchmarkArmRuntimePlan,
    audit_benchmark_arm_realization,
    build_benchmark_arm_adapter,
    build_benchmark_arm_runtime_plan,
    build_benchmark_arm_runtime_plans,
    validate_primary_contrast_runtime_plans,
)
from autoresearch.research.adaptive_sovereign_loop import (
    AdaptiveLoopEvent,
    AdaptiveLoopPolicy,
    AdaptiveResearchLoopError,
    AdaptiveResearchLoopSnapshot,
    AdaptiveResearchSeed,
    ExternalResearchFeedback,
    LoopSkillContext,
    ModelResearchActionDraft,
    ResearchOperator,
    TemporaryAgentBatchOutcome,
    TemporaryAgentContribution,
    TemporaryResearchTask,
    initialize_adaptive_research_loop,
    run_adaptive_research_loop,
)

_NOW = datetime(2026, 8, 10, 8, 0, 0, tzinfo=timezone.utc)
_REASONING = (
    "我先核对本轮机器公开的算子目录、现有分支、先前反馈和预算，再选择能够减少关键不确定性"
    "的动作。当前动作只产生待审计的探索内容，不构成实验结果、创新证明、执行授权或发表授权。"
    "如果目录只公开一个算子，我仍只围绕该动作生成中文科研内容，并明确保留失败可能；如果目录"
    "开放多个算子，我会比较信息增益后自主选择，但不会依赖任何隐藏评分或人工给定的研究结论。"
) * 2


def _seed(
    root: Path,
    *,
    loop_id: str,
) -> tuple[RawMemoryStore, AdaptiveResearchSeed]:
    store = RawMemoryStore(root / "vault")
    project_id = f"project_{loop_id.replace('-', '_')}"
    capture = store.capture_text(
        "用户仅给出研究目标：检验自主科研循环能力，不提供假设、方法或研究计划。",
        project_id=project_id,
        source_kind=RawMemorySourceKind.USER_TEXT,
        source_label="用户研究目标",
        source_ref=f"user:{loop_id}",
        original_name="research-seed.txt",
        source_authorized=True,
        sensitive_content_reviewed=True,
        captured_at=_NOW,
    )
    return store, AdaptiveResearchSeed(
        loop_id=loop_id,
        project_id=project_id,
        objective_cn="自主检验科研循环在迟到信息与冲突证据下的适应能力。",
        scope_cn="仅运行本地确定性测试，不执行正式实验，也不授权发布。",
        raw_seed_binding=capture.binding(store.vault_root),
    )


def _policy(*, max_steps: int) -> AdaptiveLoopPolicy:
    return AdaptiveLoopPolicy(
        policy_id="benchmark-arm-adapter-test",
        max_steps=max_steps,
        max_model_calls=max_steps,
        max_external_actions=8,
        max_temporary_agents=7,
        max_active_branches=12,
        max_consecutive_stalls=50,
        maximum_skill_contexts=5,
    )


def _skill() -> LoopSkillContext:
    content = "反事实方法技能：先明确可证伪机制，再比较最小变化的判别性对照。"
    return LoopSkillContext(
        skill_id="skill_counterfactual_design",
        source_ref="skills/counterfactual-design/SKILL.md",
        content=content,
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


def _skill_provider(*_: Any) -> Sequence[LoopSkillContext]:
    return [_skill()]


def _task_payload(messages: Sequence[dict[str, str]]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for message in messages:
        if message["role"] != "user":
            continue
        try:
            payload = json.loads(message["content"])
        except json.JSONDecodeError:
            continue
        if payload.get("context_kind") == "adaptive_research_next_action":
            candidates.append(payload)
    assert len(candidates) == 1
    return candidates[0]


def _completion_result(payload: dict[str, Any]) -> LLMJsonCompletionResult:
    return LLMJsonCompletionResult(
        provider="dashscope",
        base_url="https://dashscope.example/v1",
        model_name="qwen3-max",
        endpoint="https://dashscope.example/v1/chat/completions",
        response_text=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        parsed_json=payload,
        usage={"prompt_tokens": 100, "completion_tokens": 200},
        temperature=0.7,
        reasoning_text=_REASONING,
        reasoning_transport="dashscope_enable_thinking",
    )


class _CatalogCompletion:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        messages = kwargs["messages"]
        self.calls.append(messages)
        task = _task_payload(messages)
        available = list(task["available_operators"])
        operator = (
            ResearchOperator(available[0])
            if len(available) == 1
            else ResearchOperator.STOP_EXPLORATION
        )
        payload = {
            "schema_version": "adaptive-research-action-draft-v3",
            "step_index": task["step_index"],
            "branch_id": task["selected_branch"]["branch_id"],
            "operator": operator.value,
            "action_title_cn": "模型自主生成的下一研究动作",
            "action_body_cn": "围绕当前不确定性形成可检查的探索内容，并保留失败可能。",
            "retrieval_query_terms": [],
            "reason_for_choice_cn": "该动作符合本轮可用能力，并能继续缩小机制空间。",
            "expected_information_gain_cn": "预期暴露当前假设的限制或形成后续判别线索。",
            "selected_skill_ids": list(task["available_skill_ids"]),
            "source_refs": [],
            "temporary_tasks": [],
            "scientific_content_generated_by_model": True,
            "human_authored_scientific_prose_count": 0,
            "is_scientific_evidence": False,
            "execution_authorized": False,
            "publication_authorized": False,
        }
        return _completion_result(payload)


class _DreamCapableEnvironment:
    def supported_operators(self) -> frozenset[ResearchOperator]:
        return frozenset({ResearchOperator.CONSOLIDATE_DREAMING})

    def execute(
        self,
        *,
        proposal: ModelResearchActionDraft,
        **_: Any,
    ) -> ExternalResearchFeedback:
        raise AssertionError(f"test completion unexpectedly executed {proposal.operator}")


class _UnusedDispatcher:
    def dispatch(
        self,
        *,
        tasks: Sequence[TemporaryResearchTask],
        **_: Any,
    ) -> TemporaryAgentBatchOutcome:
        raise AssertionError(f"test completion unexpectedly dispatched {len(tasks)} tasks")


def _run_arm(
    root: Path,
    arm: AdaptiveLoopBenchmarkArm,
    *,
    inject_skills: bool | None = None,
) -> tuple[RawMemoryStore, AdaptiveResearchLoopSnapshot, _CatalogCompletion]:
    plan = build_benchmark_arm_runtime_plan(arm)
    max_steps = plan.turn_count if plan.operator_topology_fixed else 1
    store, seed = _seed(root, loop_id=f"arm-{arm.value}")
    completion = _CatalogCompletion()
    skills_enabled = plan.dynamic_skills_enabled if inject_skills is None else inject_skills
    snapshot = run_adaptive_research_loop(
        seed=seed,
        policy=_policy(max_steps=max_steps),
        raw_memory_store=store,
        output_dir=root / "loop",
        environment=_DreamCapableEnvironment(),
        operator_catalog_provider=build_benchmark_arm_adapter(arm),
        temporary_dispatcher=(_UnusedDispatcher() if plan.temporary_dispatch_enabled else None),
        skill_provider=_skill_provider if skills_enabled else None,
        completion=completion,
        clock=lambda: _NOW,
    )
    return store, snapshot, completion


def _replace_first_event(
    snapshot: AdaptiveResearchLoopSnapshot,
    **updates: Any,
) -> AdaptiveResearchLoopSnapshot:
    event_payload = snapshot.events[0].model_dump(mode="json", exclude={"event_hash"})
    event_payload.update(updates)
    replacement = AdaptiveLoopEvent.create(**event_payload)
    events = [replacement, *snapshot.events[1:]]
    snapshot_payload = snapshot.model_dump(mode="json", exclude={"snapshot_hash"})
    snapshot_payload["events"] = [item.model_dump(mode="json") for item in events]
    if replacement.temporary_batch is not None:
        snapshot_payload["temporary_agent_count"] = len(replacement.temporary_batch.contributions)
    return AdaptiveResearchLoopSnapshot.create(**snapshot_payload)


def test_runtime_plans_are_exact_parent_derivations_and_content_addressed() -> None:
    plans = build_benchmark_arm_runtime_plans()
    by_arm = {item.arm: item for item in plans}

    assert len(plans) == 4
    assert by_arm[AdaptiveLoopBenchmarkArm.FIXED_PIPELINE].fixed_operator_sequence == list(
        FIXED_BENCHMARK_OPERATOR_SEQUENCE
    )
    assert by_arm[AdaptiveLoopBenchmarkArm.LINEAR_MODEL_LOOP].fixed_operator_sequence == list(
        FIXED_BENCHMARK_OPERATOR_SEQUENCE
    )
    assert not by_arm[AdaptiveLoopBenchmarkArm.FIXED_PIPELINE].dynamic_skills_enabled
    assert by_arm[AdaptiveLoopBenchmarkArm.LINEAR_MODEL_LOOP].dynamic_skills_enabled
    assert by_arm[
        AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY
    ].non_intervention_configuration_hash == (
        by_arm[AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN].non_intervention_configuration_hash
    )
    validate_primary_contrast_runtime_plans(
        by_arm[AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY],
        by_arm[AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN],
    )
    for plan in plans:
        assert plan.plan_hash == canonical_sha256(
            plan.model_dump(mode="json", exclude={"plan_hash"})
        )
        assert plan.audit_raw_receipts_retained


def test_runtime_plan_rejects_rehashed_sequence_and_configuration_tampering() -> None:
    fixed = build_benchmark_arm_runtime_plan(AdaptiveLoopBenchmarkArm.FIXED_PIPELINE)
    payload = fixed.model_dump(mode="json", exclude={"plan_hash"})
    payload["fixed_operator_sequence"][0:2] = reversed(payload["fixed_operator_sequence"][0:2])
    with pytest.raises(ValidationError, match="differs from the frozen parent arm"):
        BenchmarkArmRuntimePlan.model_validate({**payload, "plan_hash": canonical_sha256(payload)})

    sovereign = build_benchmark_arm_runtime_plan(AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN)
    changed = sovereign.model_copy(update={"temporary_dispatch_enabled": False})
    derived = build_benchmark_arm_runtime_plan(AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY)
    with pytest.raises(AdaptiveLoopBenchmarkArmError, match="invalid runtime plan"):
        validate_primary_contrast_runtime_plans(derived, changed)


def test_deletion_only_hook_rejects_added_operator_before_model_call(
    tmp_path: Path,
) -> None:
    store, seed = _seed(tmp_path, loop_id="hook-addition")
    completion = _CatalogCompletion()

    def add_operator(
        *,
        mechanically_available_operator_ids: Sequence[str],
        **_: Any,
    ) -> Sequence[str]:
        return [*mechanically_available_operator_ids, "made_up_operator"]

    with pytest.raises(AdaptiveResearchLoopError, match="only remove"):
        run_adaptive_research_loop(
            seed=seed,
            policy=_policy(max_steps=1),
            raw_memory_store=store,
            output_dir=tmp_path / "loop",
            environment=_DreamCapableEnvironment(),
            operator_catalog_provider=add_operator,
            completion=completion,
            clock=lambda: _NOW,
        )
    assert not completion.calls


def test_default_no_hook_is_byte_and_behavior_compatible_with_identity_hook(
    tmp_path: Path,
) -> None:
    plain_store, plain_seed = _seed(tmp_path / "plain", loop_id="hook-default")
    identity_store, identity_seed = _seed(tmp_path / "identity", loop_id="hook-default")
    plain_completion = _CatalogCompletion()
    identity_completion = _CatalogCompletion()

    plain = run_adaptive_research_loop(
        seed=plain_seed,
        policy=_policy(max_steps=1),
        raw_memory_store=plain_store,
        output_dir=tmp_path / "plain" / "loop",
        environment=_DreamCapableEnvironment(),
        temporary_dispatcher=_UnusedDispatcher(),
        skill_provider=_skill_provider,
        completion=plain_completion,
        clock=lambda: _NOW,
    )

    def identity(
        *,
        mechanically_available_operator_ids: Sequence[str],
        **_: Any,
    ) -> Sequence[str]:
        return mechanically_available_operator_ids

    identity_snapshot = run_adaptive_research_loop(
        seed=identity_seed,
        policy=_policy(max_steps=1),
        raw_memory_store=identity_store,
        output_dir=tmp_path / "identity" / "loop",
        environment=_DreamCapableEnvironment(),
        operator_catalog_provider=identity,
        temporary_dispatcher=_UnusedDispatcher(),
        skill_provider=_skill_provider,
        completion=identity_completion,
        clock=lambda: _NOW,
    )

    assert plain == identity_snapshot
    assert plain_completion.calls == identity_completion.calls


def test_fixed_pipeline_realizes_twelve_single_operator_turns_and_is_not_autonomy(
    tmp_path: Path,
) -> None:
    store, snapshot, completion = _run_arm(
        tmp_path,
        AdaptiveLoopBenchmarkArm.FIXED_PIPELINE,
    )
    plan = build_benchmark_arm_runtime_plan(AdaptiveLoopBenchmarkArm.FIXED_PIPELINE)
    audit = audit_benchmark_arm_realization(plan=plan, snapshot=snapshot)

    assert audit.capability_matrix_realized
    assert audit.observed_turn_count == 12
    assert [item.selected_operator for item in audit.turn_evidence] == list(
        FIXED_BENCHMARK_OPERATOR_SEQUENCE
    )
    assert all(len(item.available_operator_ids) == 1 for item in audit.turn_evidence)
    assert not audit.scientific_result_generated
    forbidden = {item.value for item in AdaptiveLoopBenchmarkArm}
    for messages in completion.calls:
        serialized = json.dumps(messages, ensure_ascii=False)
        assert forbidden.isdisjoint(serialized.split('"'))

    final_path = next(
        (tmp_path / "loop" / "snapshots").glob(f"step-0012-{snapshot.snapshot_hash}.json")
    )
    autonomy = audit_adaptive_research_autonomy(
        final_path,
        raw_memory_store=store,
    )
    assert not autonomy.controller_self_loop_verified
    assert any("两个以上可选算子" in item for item in autonomy.findings_cn)


def test_fixed_adapter_rejects_step_outside_frozen_twelve_turns(tmp_path: Path) -> None:
    store, seed = _seed(tmp_path, loop_id="fixed-step-tamper")
    snapshot = initialize_adaptive_research_loop(
        seed=seed,
        policy=_policy(max_steps=12),
        raw_memory_store=store,
    ).model_copy(update={"next_step_index": 13})
    adapter = build_benchmark_arm_adapter(AdaptiveLoopBenchmarkArm.FIXED_PIPELINE)

    with pytest.raises(AdaptiveLoopBenchmarkArmError, match="outside"):
        adapter(
            seed=seed,
            snapshot=snapshot,
            branch=snapshot.branches[0],
            mechanically_available_operator_ids=[
                item.value for item in FIXED_BENCHMARK_OPERATOR_SEQUENCE
            ],
        )


def test_a1_skill_injection_and_a2_temporary_batch_fail_replay_audit(
    tmp_path: Path,
) -> None:
    _, a1_snapshot, _ = _run_arm(
        tmp_path / "a1",
        AdaptiveLoopBenchmarkArm.FIXED_PIPELINE,
        inject_skills=True,
    )
    a1_audit = audit_benchmark_arm_realization(
        plan=build_benchmark_arm_runtime_plan(AdaptiveLoopBenchmarkArm.FIXED_PIPELINE),
        snapshot=a1_snapshot,
    )
    assert not a1_audit.capability_matrix_realized
    assert any("注入了Skill消息" in item for item in a1_audit.findings_cn)

    _, a2_snapshot, _ = _run_arm(
        tmp_path / "a2",
        AdaptiveLoopBenchmarkArm.LINEAR_MODEL_LOOP,
    )
    clean_a2 = audit_benchmark_arm_realization(
        plan=build_benchmark_arm_runtime_plan(AdaptiveLoopBenchmarkArm.LINEAR_MODEL_LOOP),
        snapshot=a2_snapshot,
    )
    assert clean_a2.capability_matrix_realized
    temporary_batch = TemporaryAgentBatchOutcome.create(
        batch_id="illicit-temporary-batch",
        contributions=[
            TemporaryAgentContribution(
                dispatch_id="illicit-dispatch",
                result_hash="1" * 64,
                archive_hash="2" * 64,
                summary_cn="这是一条不应出现在固定线性臂中的临时代理输出。",
            )
        ],
    )
    tampered = _replace_first_event(a2_snapshot, temporary_batch=temporary_batch)
    tampered_audit = audit_benchmark_arm_realization(
        plan=build_benchmark_arm_runtime_plan(AdaptiveLoopBenchmarkArm.LINEAR_MODEL_LOOP),
        snapshot=tampered,
    )
    assert not tampered_audit.capability_matrix_realized
    assert tampered_audit.temporary_batch_count == 1
    assert any("调用了临时Agent" in item for item in tampered_audit.findings_cn)


def test_a3_a4_realize_same_open_capabilities_except_sovereign_recall(
    tmp_path: Path,
) -> None:
    _, a3_snapshot, _ = _run_arm(
        tmp_path / "a3",
        AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY,
    )
    _, a4_snapshot, _ = _run_arm(
        tmp_path / "a4",
        AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN,
    )
    a3_audit = audit_benchmark_arm_realization(
        plan=build_benchmark_arm_runtime_plan(AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY),
        snapshot=a3_snapshot,
    )
    a4_audit = audit_benchmark_arm_realization(
        plan=build_benchmark_arm_runtime_plan(AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN),
        snapshot=a4_snapshot,
    )

    assert a3_audit.capability_matrix_realized
    assert a4_audit.capability_matrix_realized
    a3_catalog = set(a3_audit.turn_evidence[0].available_operator_ids)
    a4_catalog = set(a4_audit.turn_evidence[0].available_operator_ids)
    assert a4_catalog - a3_catalog == {ResearchOperator.CONSOLIDATE_DREAMING.value}
    assert a3_catalog - a4_catalog == set()
    assert a4_audit.dreaming_operator_count == 0
    assert not a4_audit.actual_sovereign_recall_use_verified


def test_a3_rejects_any_sovereign_selection_artifact(
    tmp_path: Path,
) -> None:
    _, snapshot, _ = _run_arm(
        tmp_path,
        AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY,
    )
    artifact_root = tmp_path / "artifacts"
    rogue = artifact_root / "rogue" / "sovereign-recall-selection.json"
    rogue.parent.mkdir(parents=True)
    rogue.write_text("{}\n", encoding="utf-8")
    audit = audit_benchmark_arm_realization(
        plan=build_benchmark_arm_runtime_plan(AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY),
        snapshot=snapshot,
        artifact_root=artifact_root,
    )

    assert not audit.capability_matrix_realized
    assert audit.sovereign_selection_artifact_count == 1
    assert audit.orphan_sovereign_selection_paths == ["rogue/sovereign-recall-selection.json"]
    assert any("主权召回选择制品" in item for item in audit.findings_cn)
