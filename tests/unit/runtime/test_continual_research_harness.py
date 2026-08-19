import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from autoresearch.competition.model_authorship import record_model_authorship_receipt
from autoresearch.knowledge.raw_memory import RawMemorySourceKind
from autoresearch.llm.client import LLMJsonCompletionResult
from autoresearch.llm.task_context import CompletedTaskConversation
from autoresearch.observability.audit import AuditLog
from autoresearch.runtime.continual_research_harness import (
    ArtifactCompletionEnvelope,
    ContinualHarnessIntegrityError,
    ContinualHarnessTransitionError,
    ContinualResearchHarness,
    EvolutionProposalStatus,
    ResearchFailureKind,
    ResearchGoalStatus,
    ResearchTaskStatus,
    TaskExecutionResult,
    VerifiedArtifactBinding,
    VerifiedModelReceiptProjection,
)
from autoresearch.runtime.heartbeat import load_runtime_heartbeats
from autoresearch.scheduler import LocalScheduler, ScheduledRunStatus
from autoresearch.schemas import file_hash

NOW = datetime(2026, 8, 11, 4, 0, tzinfo=timezone.utc)


def _completion(answer: str) -> LLMJsonCompletionResult:
    parsed = {"answer_cn": answer}
    return LLMJsonCompletionResult(
        provider="qwen-dashscope",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_name="qwen3.7-max",
        endpoint="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        response_text=json.dumps(parsed, ensure_ascii=False),
        parsed_json=parsed,
        usage={"prompt_tokens": 31, "completion_tokens": 12},
        temperature=0.2,
        reasoning_text="模型自主完成了当前科研任务，并保留了可审计的中文推理记录。" * 3,
        reasoning_transport="dashscope_enable_thinking",
    )


def _harness(
    tmp_path: Path,
    *,
    ttl: int = 60,
    max_format_repairs: int = 3,
) -> ContinualResearchHarness:
    return ContinualResearchHarness(
        journal_path=tmp_path / "state" / "continual.jsonl",
        heartbeat_path=tmp_path / "state" / "heartbeat.json",
        vault_root=tmp_path / "vault",
        project_id="project-cn",
        conversation_id="conversation-cn",
        claim_ttl_seconds=ttl,
        max_format_repair_attempts=max_format_repairs,
    )


def _seed_goal(harness: ContinualResearchHarness) -> None:
    harness.ensure_goal(
        goal_id="goal-1",
        objective_cn="系统自主形成研究计划、完成预实验并根据证据继续推进。",
        created_at=NOW,
    )


def test_persistent_claim_complete_is_idempotent_and_only_completed_enters_context(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    _seed_goal(harness)
    first = harness.enqueue_task(
        goal_id="goal-1",
        task_id="task-1",
        task_text_cn="形成候选假设并给出可检验预测。",
        request_messages=(
            {"role": "system", "content": "你是当前科研主 Agent。"},
            {"role": "user", "content": "形成候选假设并给出可检验预测。"},
        ),
        enqueued_at=NOW,
    )
    harness.enqueue_task(
        goal_id="goal-1",
        task_id="task-2",
        task_text_cn="在第一项完成后设计预实验。",
        enqueued_at=NOW + timedelta(seconds=1),
    )

    claim = harness.claim_next(worker_id="main-agent", claimed_at=NOW + timedelta(seconds=2))
    assert claim is not None
    assert claim.task == first
    assert "形成候选假设" in claim.task.request_messages[-1]["content"]
    assert harness.completed_task_records() == ()

    before_repeat_claim = harness.snapshot().event_count
    same_claim = harness.claim_next(worker_id="main-agent", claimed_at=NOW + timedelta(seconds=3))
    assert same_claim == claim
    assert harness.snapshot().event_count == before_repeat_claim

    completed = harness.complete_task(
        claim=claim,
        completion=_completion("候选假设已经形成。"),
        completed_at=NOW + timedelta(seconds=4),
    )
    event_count = harness.snapshot().event_count
    assert (
        harness.complete_task(
            claim=claim,
            completion=_completion("候选假设已经形成。"),
            completed_at=NOW + timedelta(seconds=5),
        )
        == completed
    )
    assert harness.snapshot().event_count == event_count

    reloaded = _harness(tmp_path)
    records = reloaded.completed_task_records()
    assert records == (completed,)
    assert isinstance(records[0], CompletedTaskConversation)
    assert records[0].task_id == "task-1"
    assert "task-2" not in {record.task_id for record in records}
    reloaded.raw_memory_store.load_record(
        records[0].raw_binding.record_relative_path,
        project_id="project-cn",
    )
    assert reloaded.get_task("task-1").status is ResearchTaskStatus.COMPLETED
    assert reloaded.get_task("task-2").status is ResearchTaskStatus.QUEUED


def test_format_failure_retries_without_scientific_proposal_and_scientific_failure_waits(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path, max_format_repairs=1)
    _seed_goal(harness)
    harness.enqueue_task(
        goal_id="goal-1",
        task_id="format-task",
        task_text_cn="输出结构化的中文研究步骤。",
        enqueued_at=NOW,
    )
    harness.enqueue_task(
        goal_id="goal-1",
        task_id="science-task",
        task_text_cn="检验机制假设是否与预实验冲突。",
        enqueued_at=NOW + timedelta(seconds=1),
    )

    format_claim = harness.claim_next(worker_id="worker-a", claimed_at=NOW)
    assert format_claim is not None
    format_failure = harness.fail_task(
        claim=format_claim,
        kind=ResearchFailureKind.FORMAT,
        message_cn="模型内容可用，但 JSON 尾部多出一个分隔符，需要格式修复。",
        failed_at=NOW + timedelta(seconds=1),
    )
    event_count = harness.snapshot().event_count
    assert (
        harness.fail_task(
            claim=format_claim,
            kind=ResearchFailureKind.FORMAT,
            message_cn="模型内容可用，但 JSON 尾部多出一个分隔符，需要格式修复。",
            failed_at=NOW + timedelta(seconds=2),
        )
        == format_failure
    )
    assert harness.snapshot().event_count == event_count
    format_record = harness.get_task("format-task")
    assert format_record.status is ResearchTaskStatus.FORMAT_REPAIR
    assert format_record.last_failure is not None
    assert format_record.last_failure.counts_as_scientific_failure is False
    assert format_record.refinement_proposal is None

    science_claim = harness.claim_next(worker_id="worker-b", claimed_at=NOW + timedelta(seconds=3))
    assert science_claim is not None
    assert science_claim.task.task_id == "science-task"
    harness.fail_task(
        claim=science_claim,
        kind=ResearchFailureKind.SCIENTIFIC,
        message_cn="预实验反驳当前机制，需局部改写方法并重新做影子验证。",
        failed_at=NOW + timedelta(seconds=4),
    )
    science_record = harness.get_task("science-task")
    proposal = science_record.refinement_proposal
    assert science_record.status is ResearchTaskStatus.SCIENTIFIC_FAILED
    assert proposal is not None
    assert proposal.status == EvolutionProposalStatus.PENDING_SHADOW
    assert proposal.policy_mutation_allowed is False
    assert set(proposal.protected_scopes) == {
        "safety_policy",
        "permission_policy",
        "citation_policy",
        "publication_policy",
    }
    assert proposal.bindings.shadow_evaluation.endswith(".run_shadow_evaluation")
    assert proposal.bindings.gray_promotion.endswith(".promote_strategy_to_gray_release")
    assert proposal.bindings.automatic_rollback.endswith(".evaluate_strategy_rollback")
    assert harness.snapshot().goals[0].status is ResearchGoalStatus.NEEDS_REFINEMENT
    assert harness.completed_task_records() == ()


def test_expired_claim_recovers_with_stable_execution_key_and_rejects_stale_terminal(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path, ttl=30)
    _seed_goal(harness)
    harness.enqueue_task(
        goal_id="goal-1",
        task_id="recover-task",
        task_text_cn="运行可幂等恢复的预实验。",
        enqueued_at=NOW,
    )
    first = harness.claim_next(worker_id="worker-a", claimed_at=NOW)
    assert first is not None
    recovered = harness.claim_next(worker_id="worker-b", claimed_at=NOW + timedelta(seconds=31))
    assert recovered is not None
    assert recovered.claim_id != first.claim_id
    assert recovered.supersedes_claim_id == first.claim_id
    assert recovered.task.execution_key == first.task.execution_key

    with pytest.raises(ContinualHarnessTransitionError, match="stale"):
        harness.complete_task(
            claim=first,
            completion=_completion("迟到结果"),
            completed_at=NOW + timedelta(seconds=32),
        )
    harness.complete_task(
        claim=recovered,
        completion=_completion("恢复后结果"),
        completed_at=NOW + timedelta(seconds=33),
    )
    assert harness.get_task("recover-task").status is ResearchTaskStatus.COMPLETED


def test_existing_scheduler_runs_one_claimed_step_and_existing_heartbeat_records_it(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    _seed_goal(harness)
    harness.enqueue_task(
        goal_id="goal-1",
        task_id="scheduled-task",
        task_text_cn="由现有调度器触发一次自主科研步骤。",
        enqueued_at=NOW,
    )
    scheduler = LocalScheduler(audit_log=AuditLog(tmp_path / "audit" / "audit.jsonl"))
    seen_claims = []

    def execute(claim):
        seen_claims.append(claim)
        assert harness.get_task(claim.task.task_id).status is ResearchTaskStatus.CLAIMED
        return TaskExecutionResult.succeeded(_completion("调度任务完成。"))

    harness.schedule_once(
        scheduler=scheduler,
        scheduler_task_id="continual-step-1",
        worker_id="main-agent",
        executor=execute,
        run_at=NOW,
    )
    runs = scheduler.run_due(now=NOW)
    assert len(runs) == 1
    assert runs[0].status is ScheduledRunStatus.SUCCESS
    assert runs[0].metadata["status"] == ResearchTaskStatus.COMPLETED.value
    assert len(seen_claims) == 1
    assert harness.get_task("scheduled-task").status is ResearchTaskStatus.COMPLETED
    stages = {event.stage for event in load_runtime_heartbeats(harness.heartbeat_path)}
    assert {"task_claimed", "task_completed"}.issubset(stages)


def test_artifact_completion_uses_exact_receipt_and_registers_all_raw_bindings(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    _seed_goal(harness)
    harness.enqueue_task(
        goal_id="goal-1",
        task_id="artifact-task",
        task_text_cn="调用既有多制品计划阶段。",
        enqueued_at=NOW,
    )
    claim = harness.claim_next(worker_id="worker", claimed_at=NOW)
    assert claim is not None

    receipt_messages = (
        {"role": "system", "content": "由配置模型自主撰写计划。"},
        {"role": "user", "content": "以下是冻结证据。"},
    )
    completion = _completion("系统计划已形成。")
    receipt = record_model_authorship_receipt(
        artifact_kind="research_plan",
        interaction_id="final-plan",
        attempt=1,
        messages=receipt_messages,
        completion=completion,
        output_dir=tmp_path / "lineage",
        clock=NOW,
    )
    receipt_path = Path(receipt.output_path)
    receipt_capture = harness.raw_memory_store.capture_file(
        receipt_path,
        project_id="project-cn",
        source_kind=RawMemorySourceKind.MODEL_TRANSCRIPT,
        source_label="最终计划模型回执",
        source_ref="lineage:plan:receipt",
        media_type="application/json",
        source_authorized=True,
        sensitive_content_reviewed=True,
        captured_at=NOW,
    )
    receipt_binding = VerifiedArtifactBinding(
        artifact_kind="model_authorship_receipt",
        source_relative_path="interactions/final-plan.json",
        source_sha256=file_hash(receipt_path),
        raw_binding=receipt_capture.binding(harness.raw_memory_store.vault_root),
    )
    plan_path = tmp_path / "lineage" / "plan.json"
    plan_path.write_text('{"title":"系统计划"}\n', encoding="utf-8")
    plan_capture = harness.raw_memory_store.capture_file(
        plan_path,
        project_id="project-cn",
        source_kind=RawMemorySourceKind.LOCAL_FILE,
        source_label="最终计划制品",
        source_ref="lineage:plan:artifact",
        media_type="application/json",
        source_authorized=True,
        sensitive_content_reviewed=True,
        captured_at=NOW,
    )
    plan_binding = VerifiedArtifactBinding(
        artifact_kind="official_research_plan",
        source_relative_path="plan.json",
        source_sha256=file_hash(plan_path),
        raw_binding=plan_capture.binding(harness.raw_memory_store.vault_root),
    )
    projection = VerifiedModelReceiptProjection(
        receipt_hash=receipt.receipt_hash,
        receipt_artifact=receipt_binding,
        messages=receipt.messages,
        messages_sha256=receipt.messages_sha256,
        provider=receipt.provider,
        base_url=receipt.base_url,
        model_name=receipt.model_name,
        endpoint=receipt.endpoint,
        response_text=receipt.response_text,
        response_sha256=receipt.response_sha256,
        parsed_payload=receipt.parsed_payload,
        parsed_payload_sha256=receipt.parsed_payload_sha256,
        usage=receipt.usage,
        reasoning_content=receipt.reasoning_content,
        reasoning_transport=receipt.reasoning_transport,
    )
    envelope = ArtifactCompletionEnvelope.create(
        final_model_receipt=projection,
        artifacts=(receipt_binding, plan_binding),
        stage_report={"stage": "plan", "lineage_id": "lineage"},
        completed_at=NOW,
    )

    completed = harness.complete_artifact_task(
        claim=claim,
        completion=envelope,
        completed_at=NOW,
    )
    assert completed.request_messages == receipt.messages
    assert completed.request_messages != claim.task.request_messages
    assert completed.raw_binding == receipt_binding.raw_binding
    reloaded = _harness(tmp_path)
    record = reloaded.get_task("artifact-task")
    assert record.status is ResearchTaskStatus.COMPLETED
    assert record.artifact_completion == envelope
    assert reloaded.completed_task_records() == (completed,)

    changed_projection = projection.model_copy(update={"provider": "伪造-provider"})
    changed = ArtifactCompletionEnvelope.create(
        final_model_receipt=changed_projection,
        artifacts=(receipt_binding, plan_binding),
        stage_report={"stage": "plan", "lineage_id": "lineage"},
        completed_at=NOW,
    )
    with pytest.raises(ContinualHarnessTransitionError, match="different completion"):
        reloaded.complete_artifact_task(
            claim=claim,
            completion=changed,
            completed_at=NOW,
        )


def test_operational_failure_never_creates_proposal_and_waits_until_retry_time(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    _seed_goal(harness)
    harness.enqueue_task(
        goal_id="goal-1",
        task_id="operational-task",
        task_text_cn="等待外部锁或网络恢复。",
        enqueued_at=NOW,
    )
    claim = harness.claim_next(worker_id="worker-a", claimed_at=NOW)
    assert claim is not None
    retry_at = NOW + timedelta(minutes=1)
    failure = harness.fail_task(
        claim=claim,
        kind=ResearchFailureKind.OPERATIONAL,
        message_cn="同谱系锁仍被真实运行持有。",
        failed_at=NOW,
        retry_after=retry_at,
    )
    record = harness.get_task("operational-task")
    assert failure.counts_as_scientific_failure is False
    assert record.status is ResearchTaskStatus.OPERATIONAL_WAIT
    assert record.refinement_proposal is None
    assert harness.snapshot().proposals == ()
    assert (
        harness.claim_next(
            worker_id="worker-b",
            claimed_at=NOW + timedelta(seconds=59),
        )
        is None
    )
    recovered = harness.claim_next(worker_id="worker-b", claimed_at=retry_at)
    assert recovered is not None
    assert recovered.supersedes_claim_id == claim.claim_id


def test_tampered_append_only_journal_fails_closed(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    _seed_goal(harness)
    journal = harness.journal_path
    lines = journal.read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[0])
    payload["payload"]["objective_cn"] = "篡改后的目标"
    lines[0] = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    journal.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ContinualHarnessIntegrityError, match="invalid continual journal"):
        _harness(tmp_path)
