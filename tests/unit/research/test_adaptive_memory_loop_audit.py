from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from autoresearch.kernel.contracts import canonical_json
from autoresearch.knowledge.raw_memory import RawMemoryStore
from autoresearch.llm.client import LLMJsonCompletionResult
from autoresearch.research.adaptive_capabilities import (
    AdaptiveResearchCapabilityEnvironment,
)
from autoresearch.research.adaptive_memory_loop_audit import (
    AdaptiveMemoryLoopAudit,
    AdaptiveMemoryLoopAuditError,
    audit_adaptive_memory_loop,
)
from autoresearch.research.adaptive_sovereign_loop import (
    AdaptiveLoopPolicy,
    AdaptiveResearchLoopError,
    ResearchOperator,
    create_adaptive_research_seed,
    run_adaptive_research_loop,
)
from autoresearch.research.adaptive_sovereign_recall import SovereignRecallSelection

_NOW = datetime(2026, 8, 10, 3, 0, tzinfo=timezone.utc)
_REASONING = (
    "我检查当前分支、完整的最近反馈、剩余预算和所有可选算子，再自主选择下一动作。"
    "未验证的原始记忆只能用于提出下一步，不能被当作正确事实、创新证明或实验结果。"
    "如果关键早期记录已离开短期窗口，应由Dreaming召回，再由后续轮次决定是否核查。"
) * 3


class _MemorySequenceCompletion:
    def __init__(self) -> None:
        self.calls = 0
        self.next_turn_saw_recall = False

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        messages = kwargs["messages"]
        task = json.loads(messages[-1]["content"])
        step = int(task["step_index"])
        self.calls += 1
        operator = (
            ResearchOperator.CONSOLIDATE_DREAMING
            if step == 10
            else ResearchOperator.DECOMPOSE_UNCERTAINTY
        )
        if step == 1:
            body = (
                "早期观察记录罕见校准代码ZETA：传感器预热顺序可能改变空结果，"
                "后续必须重新核对，当前不把它当作事实。"
            )
        elif step == 10:
            body = (
                "从完整原始记忆中召回罕见校准代码ZETA及其来源，"
                "即使它已经离开最近八轮上下文也不要凭空补写。"
            )
        elif step == 11:
            recent = task["recent_external_feedback"]
            recalled = next(
                exposure
                for item in recent
                for exposure in item["memory_exposures"]
                if (
                    "罕见校准代码ZETA" in exposure["excerpt_text"]
                    and exposure["record_id"].startswith("rawmem_")
                    and len(exposure["payload_sha256"]) == 64
                    and len(exposure["selection_hash"]) == 64
                )
            )
            self.next_turn_saw_recall = True
            body = (
                "已看到系统召回的ZETA原始片段及哈希；下一步只把它作为待核线索，"
                "分解预热顺序与空结果之间的可证伪关系。"
            )
        else:
            body = f"第{step}轮继续拆分不同未知量，不重复早期ZETA字节。"
        payload = {
            "schema_version": "adaptive-research-action-draft-v3",
            "step_index": step,
            "branch_id": task["selected_branch"]["branch_id"],
            "operator": operator.value,
            "action_title_cn": f"第{step}轮自主科研动作",
            "action_body_cn": body,
            "retrieval_query_terms": [],
            "reason_for_choice_cn": "该动作在当前预算内最有可能减少一个关键未知量。",
            "expected_information_gain_cn": "能够暴露旧线索是否仍值得进一步核验。",
            "selected_skill_ids": [],
            "source_refs": [],
            "temporary_tasks": [],
            "scientific_content_generated_by_model": True,
            "human_authored_scientific_prose_count": 0,
            "is_scientific_evidence": False,
            "execution_authorized": False,
            "publication_authorized": False,
        }
        if step == 11:
            payload["schema_version"] = "adaptive-research-action-draft-v3"
            payload["memory_consumption_claims"] = [
                {
                    "schema_version": "adaptive-model-memory-consumption-claim-v1",
                    "dreaming_step_index": 10,
                    "selection_hash": recalled["selection_hash"],
                    "record_id": recalled["record_id"],
                    "payload_sha256": recalled["payload_sha256"],
                    "excerpt_sha256": recalled["excerpt_sha256"],
                    "fact_cn": "罕见校准代码ZETA",
                    "application_cn": "将该早期线索重新纳入预热顺序与空结果的判别设计。",
                    "model_declared_consumption_only": True,
                    "establishes_causal_memory_benefit": False,
                    "is_scientific_evidence": False,
                }
            ]
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


def _run_memory_transport(
    tmp_path: Path,
    *,
    max_steps: int = 11,
) -> tuple[Path, RawMemoryStore]:
    store = RawMemoryStore(tmp_path / "vault")
    seed = create_adaptive_research_seed(
        loop_id="memory-loop-audit-test",
        project_id="memory_loop_audit_test",
        objective_cn="自主核对长期原始记忆是否真的重新进入后续科研决策。",
        scope_cn="只允许概念探索与Dreaming，不执行实验、不审批、不发表。",
        raw_memory_store=store,
        captured_at=_NOW,
    )
    output_dir = tmp_path / "run"
    completion = _MemorySequenceCompletion()
    final = run_adaptive_research_loop(
        seed=seed,
        policy=AdaptiveLoopPolicy(
            policy_id="memory-loop-audit-policy",
            max_steps=max_steps,
            max_model_calls=max_steps,
            max_external_actions=1,
            max_temporary_agents=0,
        ),
        raw_memory_store=store,
        output_dir=output_dir,
        environment=AdaptiveResearchCapabilityEnvironment(
            output_dir=output_dir,
            raw_memory_store=store,
            literature_clients={"unused": object()},
            clock=lambda: _NOW,
        ),
        completion=completion,
        clock=lambda: _NOW,
    )
    assert completion.calls == max_steps
    assert completion.next_turn_saw_recall is (max_steps >= 11)
    final_path = (
        output_dir
        / "snapshots"
        / (f"step-{final.next_step_index - 1:04d}-{final.snapshot_hash}.json")
    )
    return final_path, store


def test_audit_proves_old_raw_memory_reentered_the_next_model_turn(
    tmp_path: Path,
) -> None:
    final_path, store = _run_memory_transport(tmp_path)
    output_path = tmp_path / "run" / "adaptive-memory-loop-audit.json"
    audit = audit_adaptive_memory_loop(
        final_path,
        raw_memory_store=store,
        output_path=output_path,
    )

    assert audit.dreaming_event_count == 1
    assert audit.completed_memory_transport_count == 1
    assert audit.older_than_recent_event_window_recalled
    assert audit.exact_recall_exposed_to_later_model
    assert audit.controller_memory_transport_verified
    assert audit.transport_evidence[0].selected_older_than_eight_events_count >= 1
    assert not audit.causal_memory_benefit_verified
    assert not audit.scientific_correctness_verified
    assert AdaptiveMemoryLoopAudit.model_validate_json(output_path.read_bytes()) == audit


def test_audit_rejects_selection_artifact_path_substitution(tmp_path: Path) -> None:
    final_path, store = _run_memory_transport(tmp_path)
    final_payload = json.loads(final_path.read_text(encoding="utf-8"))
    dreaming = final_payload["events"][9]
    dreaming["feedback"]["artifact_refs"] = [
        item
        for item in dreaming["feedback"]["artifact_refs"]
        if not item.endswith("sovereign-recall-selection.json")
    ]
    # The final snapshot is content-addressed, so a direct edit is rejected before
    # the audit can infer or search for a replacement selection.
    final_path.write_text(
        json.dumps(final_payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )

    with pytest.raises(AdaptiveResearchLoopError, match="feedback hash mismatch"):
        audit_adaptive_memory_loop(final_path, raw_memory_store=store)


def test_audit_refuses_dreaming_without_a_later_model_turn(tmp_path: Path) -> None:
    final_path, store = _run_memory_transport(tmp_path, max_steps=10)
    audit = audit_adaptive_memory_loop(final_path, raw_memory_store=store)

    assert audit.dreaming_event_count == 1
    assert audit.completed_memory_transport_count == 0
    assert not audit.controller_memory_transport_verified
    assert any("没有下一次模型调用" in finding for finding in audit.findings_cn)
    assert audit.causal_memory_benefit_verified is False
    assert audit.innovation_verified is False


def test_memory_audit_rejects_rehashed_excerpt_absent_from_raw_record(
    tmp_path: Path,
) -> None:
    final_path, store = _run_memory_transport(tmp_path)
    final_payload = json.loads(final_path.read_text(encoding="utf-8"))
    artifact_ref = next(
        item
        for item in final_payload["events"][9]["feedback"]["artifact_refs"]
        if item.startswith("artifact-path:") and item.endswith("sovereign-recall-selection.json")
    )
    selection_path = final_path.parent.parent / artifact_ref.removeprefix("artifact-path:")
    selection_payload = json.loads(selection_path.read_text(encoding="utf-8"))
    excerpt = selection_payload["selected_excerpts"][0]
    excerpt["excerpt_text"] = "这段伪造片段从未存在于绑定的原始记忆字节中。"
    excerpt["excerpt_sha256"] = hashlib.sha256(excerpt["excerpt_text"].encode("utf-8")).hexdigest()
    excerpt["payload_character_count"] = len(excerpt["excerpt_text"])
    excerpt["excerpt_truncated"] = False
    forged = SovereignRecallSelection.create(
        **{key: value for key, value in selection_payload.items() if key != "selection_hash"}
    )
    selection_path.write_bytes((canonical_json(forged) + "\n").encode("utf-8"))

    with pytest.raises(
        AdaptiveMemoryLoopAuditError,
        match="does not replay",
    ):
        audit_adaptive_memory_loop(final_path, raw_memory_store=store)
