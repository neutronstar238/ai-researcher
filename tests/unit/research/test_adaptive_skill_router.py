from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from autoresearch.knowledge.raw_memory import RawMemoryStore
from autoresearch.llm.client import LLMJsonCompletionResult
from autoresearch.research.adaptive_skill_router import (
    AdaptiveSkillRoutingError,
    AdaptiveSkillSelectionDraft,
    AdaptiveSkillSelectionDraftV1,
    RepositoryQwenSkillProvider,
    _skill_selection_response_schema,
    load_repository_skill_contexts,
)
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

_NOW = datetime(2026, 8, 10, 1, 2, 3, tzinfo=timezone.utc)
_SKILL_BODY = """---
name: generic-counterfactual-review
description: 用于检查反事实、替代解释、证伪条件与对照是否能够区分候选机制，而不提供具体科研答案。
---

# 通用反事实审查

本技能只规定检查方法，不给出假设、算法、实验结果或研究计划。
"""
_OTHER_SKILL_BODY = """---
name: source-triangulation
description: 用于比较多个可追溯来源的重合、差异、未知和反例边界，不替系统生成具体创新主张。
---

# 来源三角核验

本技能只规定来源核验方法，不构成事实或科学证据。
"""


def _write_skills(root: Path) -> None:
    first = root / "generic-counterfactual-review"
    second = root / "source-triangulation"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "SKILL.md").write_text(_SKILL_BODY, encoding="utf-8")
    (second / "SKILL.md").write_text(_OTHER_SKILL_BODY, encoding="utf-8")


def _store_and_seed(tmp_path: Path) -> tuple[RawMemoryStore, AdaptiveResearchSeed]:
    store = RawMemoryStore(tmp_path / "vault")
    seed = create_adaptive_research_seed(
        loop_id="adaptive_skill_test",
        project_id="adaptive_skill_test",
        objective_cn="自主寻找可证伪、可复核且不是简单组件拼接的研究方向。",
        scope_cn="只做开放探索和证据晋级准备，不执行正式实验或发表。",
        raw_memory_store=store,
        captured_at=_NOW,
    )
    return store, seed


def _routing_result(
    *,
    step_index: int,
    branch_id: str,
    selected: Sequence[str],
) -> LLMJsonCompletionResult:
    payload = AdaptiveSkillSelectionDraft(
        step_index=step_index,
        branch_id=branch_id,
        task_classification_cn=(
            "当前任务只是判断下一步探索需要哪些通用方法约束，并不生成研究答案。"
        ),
        selected_skill_ids=list(selected),
        selection_rationale_cn=(
            "根据当前分支需要辨别替代解释与证伪条件，选择对应技能；其余技能本轮没有直接用途。"
        ),
    ).model_dump(mode="json")
    return LLMJsonCompletionResult(
        provider="qwen-test",
        base_url="https://example.invalid/v1",
        model_name="qwen-test-model",
        endpoint="https://example.invalid/v1/chat/completions",
        response_text=json.dumps(payload, ensure_ascii=False),
        parsed_json=payload,
        usage={},
        temperature=0.1,
        reasoning_text="路由过程" * 110,
        reasoning_transport="dashscope_enable_thinking",
    )


def _base_action(
    *,
    step_index: int,
    branch_id: str,
    operator: ResearchOperator,
    selected_skill_ids: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "schema_version": "adaptive-research-action-draft-v3",
        "step_index": step_index,
        "branch_id": branch_id,
        "operator": operator.value,
        "action_title_cn": "检查当前研究分支",
        "action_body_cn": "系统自主检查当前分支的替代解释、未知量和下一步价值。",
        "retrieval_query_terms": [],
        "reason_for_choice_cn": "该动作能在不伪造证据的前提下提高后续探索的信息增益。",
        "expected_information_gain_cn": "预期明确哪些假设仍然无法区分以及下一轮应优先补充什么。",
        "working_hypothesis_cn": None,
        "selected_skill_ids": list(selected_skill_ids),
        "source_refs": [],
        "temporary_tasks": [],
        "promotion_draft": None,
        "scientific_content_generated_by_model": True,
        "human_authored_scientific_prose_count": 0,
        "is_scientific_evidence": False,
        "execution_authorized": False,
        "publication_authorized": False,
    }


class _NeverEnvironment(ResearchActionEnvironment):
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
        raise AssertionError("conceptual-only test must not call the environment")


def test_qwen_router_injects_only_selected_skill_as_a_separate_message(
    tmp_path: Path,
) -> None:
    skills_root = tmp_path / "skills"
    _write_skills(skills_root)
    store, seed = _store_and_seed(tmp_path)
    snapshot = initialize_adaptive_research_loop(
        seed=seed,
        policy=AdaptiveLoopPolicy(policy_id="dynamic-skill-test"),
        raw_memory_store=store,
    )
    calls: list[list[dict[str, str]]] = []

    def completion(**kwargs: Any) -> LLMJsonCompletionResult:
        calls.append(kwargs["messages"])
        return _routing_result(
            step_index=1,
            branch_id="branch_root",
            selected=["generic-counterfactual-review"],
        )

    provider = RepositoryQwenSkillProvider(
        skill_root=skills_root,
        output_dir=tmp_path / "loop",
        raw_memory_store=store,
        completion=completion,
        clock=lambda: _NOW,
    )

    contexts = provider(seed, snapshot, snapshot.branches[0])

    assert [item.skill_id for item in contexts] == ["generic-counterfactual-review"]
    assert contexts[0].content == _SKILL_BODY
    assert _SKILL_BODY not in calls[0][0]["content"]
    assert _SKILL_BODY not in calls[0][1]["content"]
    catalog_payload = json.loads(calls[0][1]["content"])
    assert {item["skill_id"] for item in catalog_payload["available_skill_metadata"]} == {
        "generic-counterfactual-review",
        "source-triangulation",
    }
    assert provider.last_model_call_count == 1
    assert provider.required_model_calls(
        seed=seed,
        snapshot=snapshot,
        branch=snapshot.branches[0],
    ) == 0

    replayed = provider(seed, snapshot, snapshot.branches[0])
    assert replayed == contexts
    assert len(calls) == 1
    assert provider.last_model_call_count == 0


def test_visible_skill_routing_response_cannot_differ_from_parsed_payload(
    tmp_path: Path,
) -> None:
    skills_root = tmp_path / "skills"
    _write_skills(skills_root)
    store, seed = _store_and_seed(tmp_path)
    snapshot = initialize_adaptive_research_loop(
        seed=seed,
        policy=AdaptiveLoopPolicy(policy_id="skill-visible-binding"),
        raw_memory_store=store,
    )

    def completion(**_: Any) -> LLMJsonCompletionResult:
        result = _routing_result(
            step_index=1,
            branch_id="branch_root",
            selected=["generic-counterfactual-review"],
        )
        other = _routing_result(
            step_index=1,
            branch_id="branch_root",
            selected=[],
        )
        return result.model_copy(update={"response_text": other.response_text})

    provider = RepositoryQwenSkillProvider(
        skill_root=skills_root,
        output_dir=tmp_path / "loop",
        raw_memory_store=store,
        completion=completion,
        clock=lambda: _NOW,
    )

    with pytest.raises(AdaptiveSkillRoutingError, match="visible skill-routing"):
        provider(seed, snapshot, snapshot.branches[0])


def test_qwen_router_may_select_no_skill_without_forcing_a_method(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    _write_skills(skills_root)
    store, seed = _store_and_seed(tmp_path)
    snapshot = initialize_adaptive_research_loop(
        seed=seed,
        policy=AdaptiveLoopPolicy(policy_id="zero-skill-test"),
        raw_memory_store=store,
    )

    provider = RepositoryQwenSkillProvider(
        skill_root=skills_root,
        output_dir=tmp_path / "loop",
        raw_memory_store=store,
        completion=lambda **_: _routing_result(
            step_index=1,
            branch_id="branch_root",
            selected=[],
        ),
        clock=lambda: _NOW,
    )

    assert provider(seed, snapshot, snapshot.branches[0]) == []


def test_current_skill_schema_has_one_authoritative_selection_field(
    tmp_path: Path,
) -> None:
    skills_root = tmp_path / "skills"
    _write_skills(skills_root)
    catalog_provider = RepositoryQwenSkillProvider(
        skill_root=skills_root,
        output_dir=tmp_path / "loop",
        raw_memory_store=RawMemoryStore(tmp_path / "vault"),
        completion=lambda **_: pytest.fail("schema inspection must not call the model"),
    )
    catalog = [item.metadata for item in catalog_provider._skills]

    schema = _skill_selection_response_schema(catalog, maximum_selected_skills=1)

    assert "no_skill_required" not in schema["properties"]
    assert schema["properties"]["schema_version"]["const"] == (
        "adaptive-skill-selection-v2"
    )
    assert schema["properties"]["selected_skill_ids"]["maxItems"] == 1
    assert "uniqueItems" not in schema["properties"]["selected_skill_ids"]
    assert set(schema["properties"]["selected_skill_ids"]["items"]["enum"]) == {
        "generic-counterfactual-review",
        "source-triangulation",
    }
    assert {"schema_version", "selected_skill_ids"}.issubset(schema["required"])


def test_legacy_negative_polarity_shape_is_readable_but_still_fail_closed() -> None:
    common = {
        "step_index": 1,
        "branch_id": "branch_root",
        "task_classification_cn": "当前任务只是判断下一步探索需要哪些通用方法约束，并不生成研究答案。",
        "selected_skill_ids": [],
        "selection_rationale_cn": "当前阶段无需加载专门方法技能，因此保留空选择并让后续循环继续自主判断。",
    }

    retained = AdaptiveSkillSelectionDraftV1(
        **common,
        no_skill_required=True,
    )
    current = AdaptiveSkillSelectionDraft(**common)

    assert retained.schema_version == "adaptive-skill-selection-v1"
    assert current.schema_version == "adaptive-skill-selection-v2"
    with pytest.raises(ValueError, match="no_skill_required"):
        AdaptiveSkillSelectionDraftV1(**common, no_skill_required=False)


def test_qwen_router_rejects_an_unknown_skill_selection(
    tmp_path: Path,
) -> None:
    skills_root = tmp_path / "skills"
    _write_skills(skills_root)
    store, seed = _store_and_seed(tmp_path)
    snapshot = initialize_adaptive_research_loop(
        seed=seed,
        policy=AdaptiveLoopPolicy(policy_id="bad-skill-partition"),
        raw_memory_store=store,
    )
    provider = RepositoryQwenSkillProvider(
        skill_root=skills_root,
        output_dir=tmp_path / "loop",
        raw_memory_store=store,
        completion=lambda **_: _routing_result(
            step_index=1,
            branch_id="branch_root",
            selected=["invented-discipline-skill"],
        ),
        clock=lambda: _NOW,
    )

    with pytest.raises(AdaptiveSkillRoutingError, match="unknown skills"):
        provider(seed, snapshot, snapshot.branches[0])


def test_replay_rejects_skill_bytes_changed_after_selection(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    _write_skills(skills_root)
    store, seed = _store_and_seed(tmp_path)
    snapshot = initialize_adaptive_research_loop(
        seed=seed,
        policy=AdaptiveLoopPolicy(policy_id="skill-byte-replay"),
        raw_memory_store=store,
    )
    first = RepositoryQwenSkillProvider(
        skill_root=skills_root,
        output_dir=tmp_path / "loop",
        raw_memory_store=store,
        completion=lambda **_: _routing_result(
            step_index=1,
            branch_id="branch_root",
            selected=["generic-counterfactual-review"],
        ),
        clock=lambda: _NOW,
    )
    first(seed, snapshot, snapshot.branches[0])
    changed = _SKILL_BODY + "\n新增且未经路由绑定的方法内容。\n"
    (skills_root / "generic-counterfactual-review" / "SKILL.md").write_text(
        changed,
        encoding="utf-8",
    )
    second = RepositoryQwenSkillProvider(
        skill_root=skills_root,
        output_dir=tmp_path / "loop",
        raw_memory_store=store,
        completion=lambda **_: pytest.fail("replay must not call the model"),
        clock=lambda: _NOW,
    )

    with pytest.raises(AdaptiveSkillRoutingError, match="skills changed"):
        second(seed, snapshot, snapshot.branches[0])


def test_dynamic_router_and_action_calls_share_one_global_model_budget(
    tmp_path: Path,
) -> None:
    skills_root = tmp_path / "skills"
    _write_skills(skills_root)
    store, seed = _store_and_seed(tmp_path)

    def routing_completion(**kwargs: Any) -> LLMJsonCompletionResult:
        payload = json.loads(kwargs["messages"][1]["content"])
        return _routing_result(
            step_index=payload["step_index"],
            branch_id=payload["branch_id"],
            selected=["generic-counterfactual-review"],
        )

    provider = RepositoryQwenSkillProvider(
        skill_root=skills_root,
        output_dir=tmp_path / "loop",
        raw_memory_store=store,
        completion=routing_completion,
        clock=lambda: _NOW,
    )
    operators = iter(
        [ResearchOperator.ADVERSARIAL_CRITIQUE, ResearchOperator.STOP_EXPLORATION]
    )

    def action_completion(**kwargs: Any) -> LLMJsonCompletionResult:
        task = json.loads(kwargs["messages"][-1]["content"])
        payload = _base_action(
            step_index=task["step_index"],
            branch_id=task["selected_branch"]["branch_id"],
            operator=next(operators),
            selected_skill_ids=["generic-counterfactual-review"],
        )
        return LLMJsonCompletionResult(
            provider="qwen-test",
            base_url="https://example.invalid/v1",
            model_name="qwen-test-model",
            endpoint="https://example.invalid/v1/chat/completions",
            response_text=json.dumps(payload, ensure_ascii=False),
            parsed_json=payload,
            usage={},
            temperature=0.7,
            reasoning_text="自主动作推理" * 100,
            reasoning_transport="dashscope_enable_thinking",
        )

    result = run_adaptive_research_loop(
        seed=seed,
        policy=AdaptiveLoopPolicy(
            policy_id="shared-model-budget",
            max_steps=2,
            max_model_calls=4,
            max_external_actions=0,
            max_temporary_agents=0,
        ),
        raw_memory_store=store,
        output_dir=tmp_path / "loop",
        environment=_NeverEnvironment(),
        skill_provider=provider,
        completion=action_completion,
        clock=lambda: _NOW,
    )

    assert result.status is AdaptiveLoopRunStatus.STOPPED_BY_MODEL
    assert len(result.events) == 2
    assert result.model_call_count == 4
    assert all(
        json.loads(event.interaction.messages[1]["content"])["skill_content"]
        == _SKILL_BODY
        for event in result.events
    )
    assert all(
        _SKILL_BODY not in event.interaction.messages[0]["content"]
        for event in result.events
    )


def test_budget_guard_does_not_start_skill_routing_without_room_for_action(
    tmp_path: Path,
) -> None:
    skills_root = tmp_path / "skills"
    _write_skills(skills_root)
    store, seed = _store_and_seed(tmp_path)
    called = False

    def completion(**_: Any) -> LLMJsonCompletionResult:
        nonlocal called
        called = True
        return _routing_result(
            step_index=1,
            branch_id="branch_root",
            selected=[],
        )

    provider = RepositoryQwenSkillProvider(
        skill_root=skills_root,
        output_dir=tmp_path / "loop",
        raw_memory_store=store,
        completion=completion,
        clock=lambda: _NOW,
    )
    result = run_adaptive_research_loop(
        seed=seed,
        policy=AdaptiveLoopPolicy(
            policy_id="insufficient-shared-budget",
            max_steps=2,
            max_model_calls=1,
            max_external_actions=0,
            max_temporary_agents=0,
        ),
        raw_memory_store=store,
        output_dir=tmp_path / "loop",
        environment=_NeverEnvironment(),
        skill_provider=provider,
        completion=lambda **_: pytest.fail("action model must not be called"),
        clock=lambda: _NOW,
    )

    assert result.status is AdaptiveLoopRunStatus.PAUSED_BUDGET
    assert result.events == []
    assert called is False


def test_exact_skill_subset_loader_preserves_zero_or_selected_route(
    tmp_path: Path,
) -> None:
    skills_root = tmp_path / "skills"
    _write_skills(skills_root)

    assert load_repository_skill_contexts(skills_root, []) == []
    selected = load_repository_skill_contexts(
        skills_root,
        ["source-triangulation"],
    )

    assert [item.skill_id for item in selected] == ["source-triangulation"]
    assert selected[0].content == _OTHER_SKILL_BODY
    with pytest.raises(AdaptiveSkillRoutingError, match="unknown skills"):
        load_repository_skill_contexts(skills_root, ["invented-skill"])
