from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from autoresearch.knowledge.raw_memory import (
    RawMemoryIntegrityError,
    RawMemorySourceKind,
    RawMemoryStore,
)
from autoresearch.llm.client import LLMJsonCompletionResult
from autoresearch.research.adaptive_sovereign_loop import (
    AdaptiveLoopPolicy,
    AdaptiveResearchLoopSnapshot,
    AdaptiveResearchSeed,
    ExternalResearchFeedback,
    ModelResearchActionDraft,
    ResearchActionEnvironment,
    ResearchOperator,
    create_adaptive_research_seed,
    run_adaptive_research_loop,
)
from autoresearch.research.adaptive_sovereign_recall import (
    SovereignRawRecallEngine,
    SovereignRecallSelection,
    recall_findings_cn,
)

_NOW = datetime(2026, 8, 10, 2, 0, 0, tzinfo=timezone.utc)
_REASONING = (
    "我只根据当前目标、已有反馈和可用算子形成下一动作，不把未验证内容当作证据。"
    "本轮需要保留失败可能、来源边界和资源限制，并让后续外部反馈能够否定当前判断。"
    "如果历史信息已经离开短期上下文，也不能假设它不存在，而应通过受限记忆能力重新核对。"
) * 3


def test_relevance_scores_are_stable_across_python_hash_seeds() -> None:
    script = (
        "from autoresearch.research.adaptive_sovereign_recall import "
        "_relevance_scores,_tokens; import json; "
        "payloads={f'd{i}':' '.join(f't{j}' for j in range(1,201) "
        "if (j+i)%(i%17+2)!=0) for i in range(1,80)}; "
        "query=' '.join(f't{j}' for j in range(1,201)); "
        "print(json.dumps(_relevance_scores(payloads,query=query,"
        "query_tokens=_tokens(query)),sort_keys=True))"
    )
    outputs: list[bytes] = []
    for hash_seed in ("1", "2", "5", "8"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = hash_seed
        environment["PYTHONPATH"] = "src"
        outputs.append(
            subprocess.check_output(
                [sys.executable, "-c", script],
                cwd=Path.cwd(),
                env=environment,
            )
        )

    assert len(set(outputs)) == 1


class _NoExternalEnvironment(ResearchActionEnvironment):
    def supported_operators(self) -> frozenset[ResearchOperator]:
        return frozenset()

    def execute(self, **_: Any) -> ExternalResearchFeedback:
        raise AssertionError("no external operator should be selected")


class _NineTurnCompletion:
    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        task = json.loads(kwargs["messages"][-1]["content"])
        step = int(task["step_index"])
        body = (
            "罕见校准代码ZETA说明早期零响应来自传感器预热，而不是机制失效；"
            "该陈述仍需后续来源核验。"
            if step == 1
            else f"第{step}轮继续拆解其他不确定性，不重复早期校准结论。"
        )
        payload = {
            "schema_version": "adaptive-research-action-draft-v3",
            "step_index": step,
            "branch_id": task["selected_branch"]["branch_id"],
            "operator": ResearchOperator.DECOMPOSE_UNCERTAINTY.value,
            "action_title_cn": f"第{step}轮自主拆解未知量",
            "action_body_cn": body,
            "retrieval_query_terms": [],
            "reason_for_choice_cn": "拆解未知量可以避免在证据不足时过早晋级。",
            "expected_information_gain_cn": "形成下一轮可由外部信息区分的待检验条件。",
            "working_hypothesis_cn": None,
            "selected_skill_ids": [],
            "source_refs": [],
            "temporary_tasks": [],
            "promotion_draft": None,
            "scientific_content_generated_by_model": True,
            "human_authored_scientific_prose_count": 0,
            "is_scientific_evidence": False,
            "execution_authorized": False,
            "publication_authorized": False,
        }
        return LLMJsonCompletionResult(
            provider="dashscope",
            base_url="https://dashscope.example/v1",
            model_name="qwen3-max",
            endpoint="https://dashscope.example/v1/chat/completions",
            response_text=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            parsed_json=payload,
            usage={"prompt_tokens": 100, "completion_tokens": 100},
            temperature=0.2,
            reasoning_text=_REASONING,
            reasoning_transport="dashscope_enable_thinking",
        )


def _nine_turn_snapshot(
    tmp_path: Path,
) -> tuple[RawMemoryStore, AdaptiveResearchSeed, AdaptiveResearchLoopSnapshot]:
    store = RawMemoryStore(tmp_path / "vault")
    seed = create_adaptive_research_seed(
        loop_id="sovereign-recall-test",
        project_id="sovereign_recall_test",
        objective_cn="自主判断长期历史中的校准信息何时会重新变得关键。",
        scope_cn="只进行开放探索和本地记忆召回，不执行实验或发表。",
        raw_memory_store=store,
        captured_at=_NOW,
    )
    snapshot = run_adaptive_research_loop(
        seed=seed,
        policy=AdaptiveLoopPolicy(
            policy_id="sovereign-recall-test-policy",
            max_steps=9,
            max_model_calls=9,
            max_external_actions=0,
            max_temporary_agents=0,
            max_consecutive_stalls=20,
        ),
        raw_memory_store=store,
        output_dir=tmp_path / "run",
        environment=_NoExternalEnvironment(),
        completion=_NineTurnCompletion(),
        clock=lambda: _NOW,
    )
    assert len(snapshot.events) == 9
    return store, seed, snapshot


def _recall_proposal(snapshot: AdaptiveResearchLoopSnapshot) -> ModelResearchActionDraft:
    return ModelResearchActionDraft(
        step_index=snapshot.next_step_index,
        branch_id="branch_root",
        operator=ResearchOperator.CONSOLIDATE_DREAMING,
        action_title_cn="重新召回早期校准记录",
        action_body_cn="查找罕见校准代码ZETA及其关于传感器预热的原始记录。",
        reason_for_choice_cn="该早期信息已经离开最近事件窗口但可能决定当前解释。",
        expected_information_gain_cn="若能恢复原始记录，就能判断当前零响应是否被错误解释。",
    )


def test_recall_restores_first_record_after_more_than_eight_events(
    tmp_path: Path,
) -> None:
    store, _, snapshot = _nine_turn_snapshot(tmp_path)
    first_response = snapshot.events[0].interaction.response_binding
    first_capture = store.load_record(
        first_response.record_relative_path,
        project_id=snapshot.seed.project_id,
    )
    original_bytes = first_capture.blob_path.read_bytes()
    engine = SovereignRawRecallEngine(
        raw_memory_store=store,
        maximum_selected_records=4,
    )

    first = engine.recall(
        snapshot=snapshot,
        proposal=_recall_proposal(snapshot),
        output_path=tmp_path / "recall.json",
    )
    second = engine.recall(
        snapshot=snapshot,
        proposal=_recall_proposal(snapshot),
    )

    selected_ids = [item.binding.record_id for item in first.selected_excerpts]
    assert first_response.record_id in selected_ids
    assert any("罕见校准代码ZETA" in item.excerpt_text for item in first.selected_excerpts)
    assert first.selection_hash == second.selection_hash
    assert first_capture.blob_path.read_bytes() == original_bytes
    assert first.raw_records_mutated is False
    assert first.derived_and_rebuildable is True
    assert first.scientific_evidence_established is False
    assert first.execution_authorized is False
    assert first.publication_authorized is False
    assert (
        SovereignRecallSelection.model_validate_json((tmp_path / "recall.json").read_bytes())
        == first
    )
    findings = recall_findings_cn(first)
    assert first_response.record_id in "\n".join(findings)
    assert "不能直接作为科学证据" in findings[-1]


def test_recall_excludes_all_extra_bindings_even_with_canonical_source_refs(
    tmp_path: Path,
) -> None:
    store, _, snapshot = _nine_turn_snapshot(tmp_path)
    original = store.capture_text(
        "ORBIT校准结论：早期版本认为增益为正。",
        project_id=snapshot.seed.project_id,
        source_kind=RawMemorySourceKind.MODEL_TRANSCRIPT,
        source_label="旧版校准输出",
        source_ref="adaptive-loop:sovereign-recall-test:step:20:attempt:1:response",
        original_name="orbit-old.txt",
        source_authorized=True,
        sensitive_content_reviewed=True,
        captured_at=_NOW + timedelta(minutes=1),
    )
    correction = store.capture_text(
        "ORBIT校准纠正：新版审计确认增益为零，旧版结论已被取代。",
        project_id=snapshot.seed.project_id,
        source_kind=RawMemorySourceKind.MODEL_TRANSCRIPT,
        source_label="新版校准纠正",
        source_ref="adaptive-loop:sovereign-recall-test:step:20:attempt:2:response",
        original_name="orbit-correction.txt",
        source_authorized=True,
        sensitive_content_reviewed=True,
        captured_at=_NOW + timedelta(minutes=2),
        supersedes_record_id=original.record.record_id,
    )
    private = store.capture_text(
        "本地附件中的ORBIT私人记录不得自动发送给外部模型。",
        project_id=snapshot.seed.project_id,
        source_kind=RawMemorySourceKind.USER_ATTACHMENT,
        source_label="私人附件",
        source_ref="attachment:orbit-private",
        original_name="orbit-private.txt",
        source_authorized=True,
        sensitive_content_reviewed=True,
        captured_at=_NOW + timedelta(minutes=3),
    )
    never_exposed_tool = store.capture_text(
        "本地工具缓存的ORBIT隐藏参数未曾进入控制器上下文。",
        project_id=snapshot.seed.project_id,
        source_kind=RawMemorySourceKind.TOOL_OUTPUT,
        source_label="未授权复用的本地工具缓存",
        source_ref="tool:orbit:private-cache",
        original_name="orbit-private-cache.txt",
        source_authorized=True,
        sensitive_content_reviewed=True,
        captured_at=_NOW + timedelta(minutes=4),
    )
    proposal = _recall_proposal(snapshot).model_copy(
        update={
            "action_title_cn": "核对ORBIT校准纠错链",
            "action_body_cn": "召回ORBIT旧版结论及其新版纠正，不要只保留一个端点。",
        }
    )
    selection = SovereignRawRecallEngine(
        raw_memory_store=store,
        maximum_selected_records=6,
    ).recall(
        snapshot=snapshot,
        proposal=proposal,
        extra_bindings=[
            original.binding(store.vault_root),
            correction.binding(store.vault_root),
            private.binding(store.vault_root),
            never_exposed_tool.binding(store.vault_root),
        ],
    )

    selected_ids = {item.binding.record_id for item in selection.selected_excerpts}
    assert original.record.record_id not in selected_ids
    assert correction.record.record_id not in selected_ids
    assert private.record.record_id not in selected_ids
    assert never_exposed_tool.record.record_id not in selected_ids
    assert selection.privacy_excluded_record_count == 4
    assert selection.correction_chain_closed is True


def test_recall_fails_closed_when_bound_raw_payload_is_tampered(tmp_path: Path) -> None:
    store, _, snapshot = _nine_turn_snapshot(tmp_path)
    first_binding = snapshot.events[0].interaction.response_binding
    capture = store.load_record(
        first_binding.record_relative_path,
        project_id=snapshot.seed.project_id,
    )
    capture.blob_path.write_bytes(b"tampered")

    with pytest.raises(RawMemoryIntegrityError, match="payload|raw-memory"):
        SovereignRawRecallEngine(raw_memory_store=store).recall(
            snapshot=snapshot,
            proposal=_recall_proposal(snapshot),
        )
