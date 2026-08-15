from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from autoresearch.agents.temporary import (
    StageControllerBinding,
    StageDispatchCapability,
    TemporaryAgentArchiveRecord,
    TemporaryAgentAssignment,
    TemporaryAgentBatchManifest,
    TemporaryAgentContractError,
    TemporaryAgentInputRef,
    TemporaryAgentResultArtifact,
    TemporaryAgentSkillRef,
    TemporaryAgentTaskKind,
    TemporaryAgentTerminalStatus,
    issue_stage_controller,
)
from autoresearch.competition.model_authorship import ModelAuthorshipReceipt
from autoresearch.competition.temporary_qwen_pool import (
    TemporaryQwenBatchArtifact,
    TemporaryQwenBatchError,
    TemporaryQwenContentTask,
    TemporaryQwenPoolError,
    TemporaryQwenSkillContext,
    TemporaryQwenStagePhaseSession,
    TemporaryQwenTaskRecord,
    run_temporary_qwen_content_batch,
)
from autoresearch.llm.client import LLMClientError, LLMJsonCompletionResult

_HASH_A = "a" * 64
_NOW = datetime(2026, 8, 9, 9, 0, tzinfo=timezone.utc)
_SKILL_CONTENT = """# 临时内容核对技能

先核对显式输入范围，再逐项形成中文结构化检查结果。技能约束不是科学证据。
"""


def _controller(
    *, max_parallel_agents: int = 2
) -> tuple[StageControllerBinding, StageDispatchCapability]:
    return issue_stage_controller(
        lineage_id="lineage-temporary-pool",
        stage="research-plan",
        stage_attempt=1,
        controller_agent_id="stage-main-agent",
        stage_input_hash=_HASH_A,
        max_parallel_agents=max_parallel_agents,
        claimed_at=_NOW,
        lease_token="stage-main-token-0001",
    )


def _skill_context() -> TemporaryQwenSkillContext:
    digest = hashlib.sha256(_SKILL_CONTENT.encode("utf-8")).hexdigest()
    return TemporaryQwenSkillContext(
        skill_ref=TemporaryAgentSkillRef(
            skill_id="temporary-content-check",
            source_ref="skills/temporary-content-check/SKILL.md",
            content_sha256=digest,
        ),
        content=_SKILL_CONTENT,
    )


def _task(
    dispatch_id: str,
    temporary_agent_id: str,
    *,
    derived_memory_context: dict[str, Any] | None = None,
) -> TemporaryQwenContentTask:
    artifact_suffix = hashlib.sha256(dispatch_id.encode("utf-8")).hexdigest()[:8]
    return TemporaryQwenContentTask(
        dispatch_id=dispatch_id,
        temporary_agent_id=temporary_agent_id,
        parent_task_id="parent-content-batch",
        task_kind=TemporaryAgentTaskKind.CONTENT_CHECKLIST,
        task_instruction="只根据显式输入输出一份有界中文检查摘要。",
        input_refs=(
            TemporaryAgentInputRef(
                artifact_id=f"input-{artifact_suffix}",
                source_ref=f"inputs/{artifact_suffix}.json",
                sha256=_HASH_A,
            ),
        ),
        input_payload={"输入标记": f"输入-{dispatch_id}"},
        expected_output_schema={
            "type": "object",
            "required": ["诊断摘要"],
            "properties": {"诊断摘要": {"type": "string"}},
            "additionalProperties": False,
        },
        chinese_output_fields=("诊断摘要",),
        skill_contexts=(_skill_context(),),
        derived_memory_context=derived_memory_context,
        max_tokens=2_000,
        timeout_seconds=120,
    )


def _dispatch_from_call(kwargs: dict[str, Any]) -> str:
    task_payload = json.loads(kwargs["messages"][-1]["content"])
    return str(task_payload["派工编号"])


def _completion_result(
    kwargs: dict[str, Any],
    *,
    dispatch_id: str,
    reasoning_text: str | None,
    output_text: str | None = None,
) -> LLMJsonCompletionResult:
    payload = {"诊断摘要": output_text or f"派工 {dispatch_id} 已完成中文结构化核对。"}
    return LLMJsonCompletionResult(
        provider="qwen-dashscope",
        base_url="https://dashscope.example/compatible-mode/v1",
        model_name="qwen3.7-max",
        endpoint="https://dashscope.example/v1/chat/completions",
        response_text=json.dumps(payload, ensure_ascii=False),
        parsed_json=payload,
        usage={"reasoning_tokens": 400},
        temperature=float(kwargs["temperature"]),
        reasoning_text=reasoning_text,
        reasoning_transport="dashscope_enable_thinking",
    )


class _ParallelCompletion:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.barrier = threading.Barrier(2)
        self.second_finished = threading.Event()
        self.lock = threading.Lock()
        self.calls: list[dict[str, Any]] = []
        self.completion_order: list[str] = []
        self.saw_all_assignments: list[bool] = []

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        dispatch_id = _dispatch_from_call(kwargs)
        assignment_files = list(
            self.output_dir.glob("temporary-agents/batches/*/assignments/*.json")
        )
        with self.lock:
            self.calls.append(kwargs)
            self.saw_all_assignments.append(len(assignment_files) == 2)
        self.barrier.wait(timeout=5)
        if dispatch_id == "dispatch-002":
            with self.lock:
                self.completion_order.append(dispatch_id)
            self.second_finished.set()
        else:
            if not self.second_finished.wait(timeout=5):
                raise AssertionError("second temporary completion never overlapped")
            with self.lock:
                self.completion_order.append(dispatch_id)
        return _completion_result(
            kwargs,
            dispatch_id=dispatch_id,
            reasoning_text="先核对输入边界，再检查结构、中文字段和权限约束。" * 12,
        )


class _ConfiguredCompletion:
    def __init__(
        self,
        *,
        short_reasoning_dispatch: str | None = None,
        english_output_dispatch: str | None = None,
    ) -> None:
        self.short_reasoning_dispatch = short_reasoning_dispatch
        self.english_output_dispatch = english_output_dispatch
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        self.calls.append(kwargs)
        dispatch_id = _dispatch_from_call(kwargs)
        reasoning = (
            ""
            if dispatch_id == self.short_reasoning_dispatch
            else "逐项核对输入、技能边界、输出结构和中文内容。" * 15
        )
        output_text = "English only." if dispatch_id == self.english_output_dispatch else None
        return _completion_result(
            kwargs,
            dispatch_id=dispatch_id,
            reasoning_text=reasoning,
            output_text=output_text,
        )


class _InvalidJsonOnceCompletion:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            raise LLMClientError(
                "LLM JSON completion was not valid JSON: Expecting ',' delimiter",
                response_text='{"诊断摘要":"科研内容保持不变" "缺少逗号":true}',
            )
        return _completion_result(
            kwargs,
            dispatch_id="dispatch-001",
            reasoning_text="仅修复上一响应的 JSON 标点，科研内容和字段含义保持不变。",
        )


def test_dreaming_navigation_is_an_independent_non_evidence_message(
    tmp_path: Path,
) -> None:
    controller, capability = _controller(max_parallel_agents=1)
    context = {
        "context_kind": "optional_rebuildable_dreaming_navigation",
        "recall_hash": "b" * 64,
        "epistemic_boundary_zh": "派生导航不是科学证据，结论必须回到原始制品。",
        "derived_context_is_evidence": False,
        "model_consumption_proven_by_this_receipt": False,
        "projections": [{"source_stage": "real-pilot", "summary": "仅导航"}],
    }
    completion = _ConfiguredCompletion()

    run_temporary_qwen_content_batch(
        batch_id="memory-message-order",
        controller=controller,
        capability=capability,
        tasks=(
            _task(
                "dispatch-memory",
                "temporary-agent-memory",
                derived_memory_context=context,
            ),
        ),
        output_dir=tmp_path,
        completion=completion,
        max_workers=1,
        clock=_NOW,
    )

    messages = completion.calls[0]["messages"]
    parsed = [json.loads(item["content"]) for item in messages[1:]]
    assert parsed[0]["上下文类型"] == "题目与显式输入"
    assert parsed[1]["上下文类型"] == "独立只读技能"
    assert parsed[2] == context
    assert parsed[2]["derived_context_is_evidence"] is False
    assert parsed[3]["派工编号"] == "dispatch-memory"


def _inside(root: Path, relative_path: str) -> Path:
    path = (root / Path(*PurePosixPath(relative_path).parts)).resolve()
    path.relative_to(root.resolve())
    return path


def test_parallel_batch_separates_messages_and_persists_stable_artifacts(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "run"
    controller, capability = _controller()
    completion = _ParallelCompletion(output_dir)

    artifact = run_temporary_qwen_content_batch(
        batch_id="temporary-batch-001",
        controller=controller,
        capability=capability,
        tasks=(
            _task("dispatch-002", "temporary-agent-002"),
            _task("dispatch-001", "temporary-agent-001"),
        ),
        output_dir=output_dir,
        completion=completion,
        max_workers=2,
        clock=_NOW,
    )

    assert completion.completion_order == ["dispatch-002", "dispatch-001"]
    assert completion.saw_all_assignments == [True, True]
    assert [item.dispatch_id for item in artifact.task_records] == [
        "dispatch-001",
        "dispatch-002",
    ]
    assert [item.dispatch_id for item in artifact.stable_outputs] == [
        "dispatch-001",
        "dispatch-002",
    ]
    assert artifact.succeeded_count == 2
    assert artifact.failed_count == 0
    assert not capability.active

    for call in completion.calls:
        messages = call["messages"]
        assert [item["role"] for item in messages] == [
            "system",
            "user",
            "user",
            "user",
        ]
        assert _SKILL_CONTENT not in messages[0]["content"]
        assert json.loads(messages[1]["content"])["上下文类型"] == "题目与显式输入"
        assert _SKILL_CONTENT not in messages[1]["content"]
        assert json.loads(messages[2]["content"])["技能正文"] == _SKILL_CONTENT
        assert _SKILL_CONTENT not in messages[3]["content"]
        assert "短任务输入" in messages[3]["content"]
        assert call["thinking_mode"] == "enabled"
        assert call["thinking_budget"] == 4_000
        assert call["response_schema"]["required"] == ["诊断摘要"]
        assert "capability" not in call

    persisted_artifact = TemporaryQwenBatchArtifact.model_validate_json(
        _inside(output_dir, artifact.output_relative_path).read_text(encoding="utf-8")
    )
    manifest = TemporaryAgentBatchManifest.model_validate_json(
        _inside(output_dir, artifact.manifest_relative_path).read_text(encoding="utf-8")
    )
    assert persisted_artifact.artifact_hash == artifact.artifact_hash
    assert manifest.batch_hash == artifact.manifest_hash
    assert manifest.all_runtime_identities_inactive

    for record in artifact.task_records:
        assignment = TemporaryAgentAssignment.model_validate_json(
            _inside(output_dir, record.assignment_relative_path).read_text(encoding="utf-8")
        )
        result = TemporaryAgentResultArtifact.model_validate_json(
            _inside(output_dir, str(record.result_relative_path)).read_text(encoding="utf-8")
        )
        archive = TemporaryAgentArchiveRecord.model_validate_json(
            _inside(output_dir, record.archive_relative_path).read_text(encoding="utf-8")
        )
        receipt = ModelAuthorshipReceipt.model_validate_json(
            _inside(
                output_dir,
                str(record.authorship_receipt_relative_path),
            ).read_text(encoding="utf-8")
        )
        persisted_record = TemporaryQwenTaskRecord.model_validate_json(
            _inside(output_dir, record.record_relative_path).read_text(encoding="utf-8")
        )
        assert assignment.assignment_hash == record.assignment_hash
        assert result.result_hash == record.result_hash
        assert archive.archive_hash == record.archive_hash
        assert archive.runtime_identity_inactive
        assert archive.output_retained
        assert receipt.artifact_kind == "temporary_content_output"
        assert len(str(receipt.reasoning_content)) >= 200
        assert persisted_record.record_hash == record.record_hash


def test_invalid_json_gets_local_format_only_retry(tmp_path: Path) -> None:
    output_dir = tmp_path / "format-repair"
    controller, capability = _controller(max_parallel_agents=1)
    completion = _InvalidJsonOnceCompletion()

    artifact = run_temporary_qwen_content_batch(
        batch_id="temporary-format-repair",
        controller=controller,
        capability=capability,
        tasks=(_task("dispatch-001", "temporary-agent-001"),),
        output_dir=output_dir,
        completion=completion,
        max_workers=1,
        clock=_NOW,
    )

    assert artifact.succeeded_count == 1
    assert artifact.failed_count == 0
    assert len(completion.calls) == 2
    repair_messages = completion.calls[1]["messages"]
    assert [item["role"] for item in repair_messages[-2:]] == [
        "assistant",
        "user",
    ]
    assert "只修复 JSON" in repair_messages[-1]["content"]
    record = artifact.task_records[0]
    receipt = ModelAuthorshipReceipt.model_validate_json(
        _inside(output_dir, str(record.authorship_receipt_relative_path)).read_text(
            encoding="utf-8"
        )
    )
    assert receipt.attempt == 2
    assert receipt.messages == tuple(repair_messages)


def test_only_live_main_agent_capability_can_start_a_batch(tmp_path: Path) -> None:
    controller, capability = _controller(max_parallel_agents=1)
    capability.revoke()
    completion = _ConfiguredCompletion()
    output_dir = tmp_path / "run"

    with pytest.raises(TemporaryAgentContractError, match="revoked"):
        run_temporary_qwen_content_batch(
            batch_id="temporary-batch-revoked",
            controller=controller,
            capability=capability,
            tasks=(_task("dispatch-001", "temporary-agent-001"),),
            output_dir=output_dir,
            completion=completion,
            clock=_NOW,
        )

    assert completion.calls == []
    assert not output_dir.exists()


def test_short_reasoning_fails_after_every_identity_is_archived(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "run"
    controller, capability = _controller()
    completion = _ConfiguredCompletion(short_reasoning_dispatch="dispatch-002")

    with pytest.raises(TemporaryQwenBatchError) as caught:
        run_temporary_qwen_content_batch(
            batch_id="temporary-batch-failed",
            controller=controller,
            capability=capability,
            tasks=(
                _task("dispatch-002", "temporary-agent-002"),
                _task("dispatch-001", "temporary-agent-001"),
            ),
            output_dir=output_dir,
            completion=completion,
            max_workers=2,
            clock=_NOW,
        )

    artifact = caught.value.artifact
    assert artifact.succeeded_count == 1
    assert artifact.failed_count == 1
    assert [item.dispatch_id for item in artifact.stable_outputs] == ["dispatch-001"]
    assert not capability.active
    failed_record = next(
        item
        for item in artifact.task_records
        if item.terminal_status is TemporaryAgentTerminalStatus.FAILED
    )
    assert failed_record.dispatch_id == "dispatch-002"
    assert failed_record.result_relative_path is None
    assert failed_record.authorship_receipt_relative_path is not None
    assert "reasoning_content" in str(failed_record.failure_message)
    failed_receipt = ModelAuthorshipReceipt.model_validate_json(
        _inside(
            output_dir,
            failed_record.authorship_receipt_relative_path,
        ).read_text(encoding="utf-8")
    )
    failed_archive = TemporaryAgentArchiveRecord.model_validate_json(
        _inside(output_dir, failed_record.archive_relative_path).read_text(encoding="utf-8")
    )
    manifest = TemporaryAgentBatchManifest.model_validate_json(
        _inside(output_dir, artifact.manifest_relative_path).read_text(encoding="utf-8")
    )
    assert failed_receipt.reasoning_content == ""
    assert failed_archive.terminal_status is TemporaryAgentTerminalStatus.FAILED
    assert failed_archive.runtime_identity_inactive
    assert failed_archive.output_retained
    assert manifest.failed_count == 1
    assert manifest.all_assignments_archived
    assert manifest.all_runtime_identities_inactive
    assert _inside(output_dir, artifact.output_relative_path).is_file()
    assert len(list(output_dir.glob("temporary-agents/batches/*/results/*.json"))) == 1
    assert len(list(output_dir.glob("temporary-agents/batches/*/archives/*.json"))) == 2


def test_non_chinese_output_fails_closed_but_keeps_receipt(tmp_path: Path) -> None:
    output_dir = tmp_path / "run"
    controller, capability = _controller(max_parallel_agents=1)
    completion = _ConfiguredCompletion(english_output_dispatch="dispatch-001")

    with pytest.raises(TemporaryQwenBatchError) as caught:
        run_temporary_qwen_content_batch(
            batch_id="temporary-batch-english",
            controller=controller,
            capability=capability,
            tasks=(_task("dispatch-001", "temporary-agent-001"),),
            output_dir=output_dir,
            completion=completion,
            clock=_NOW,
        )

    record = caught.value.artifact.task_records[0]
    assert record.terminal_status is TemporaryAgentTerminalStatus.FAILED
    assert record.authorship_receipt_relative_path is not None
    assert record.result_relative_path is None
    assert "Chinese text" in str(record.failure_message)
    assert not capability.active


def test_finite_phase_session_retains_then_finalizes_one_capability(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "run"
    controller, capability = _controller(max_parallel_agents=1)
    completion = _ConfiguredCompletion()
    with TemporaryQwenStagePhaseSession(
        sequence_id="two-phase-test-sequence",
        controller=controller,
        capability=capability,
        phase_ids=("author-phase", "review-phase"),
        created_at=_NOW,
    ) as session:
        run_temporary_qwen_content_batch(
            batch_id="phase-author-batch",
            controller=controller,
            capability=capability,
            tasks=(_task("author-dispatch", "temporary-author"),),
            output_dir=output_dir,
            completion=completion,
            clock=_NOW,
            phase_session=session,
            phase_id="author-phase",
        )
        author_manifest = session.phase_manifest("author-phase")
        assert capability.active
        assert author_manifest.capability_retained_for_next_phase
        assert not author_manifest.capability_finalized
        assert not author_manifest.phase_sequence_completed
        assert not author_manifest.research_stage_completion_claimed

        run_temporary_qwen_content_batch(
            batch_id="phase-review-batch",
            controller=controller,
            capability=capability,
            tasks=(_task("review-dispatch", "temporary-reviewer"),),
            output_dir=output_dir,
            completion=completion,
            clock=_NOW,
            phase_session=session,
            phase_id="review-phase",
        )
        reviewer_manifest = session.phase_manifest("review-phase")
        assert not capability.active
        assert reviewer_manifest.capability_finalized
        assert reviewer_manifest.phase_sequence_completed
        assert not reviewer_manifest.research_stage_completion_claimed

    with pytest.raises(TemporaryAgentContractError, match="revoked"):
        run_temporary_qwen_content_batch(
            batch_id="phase-illegal-reuse",
            controller=controller,
            capability=capability,
            tasks=(_task("reuse-dispatch", "temporary-reuse"),),
            output_dir=output_dir,
            completion=completion,
            clock=_NOW,
        )


def test_cross_phase_capability_swap_revokes_original_session(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "run"
    controller, capability = _controller(max_parallel_agents=1)
    other_controller, other_capability = issue_stage_controller(
        lineage_id=controller.lineage_id,
        stage=controller.stage,
        stage_attempt=2,
        controller_agent_id=controller.controller_agent_id,
        stage_input_hash=_HASH_A,
        max_parallel_agents=1,
        claimed_at=_NOW,
        lease_token="another-stage-main-token",
    )
    completion = _ConfiguredCompletion()
    session = TemporaryQwenStagePhaseSession(
        sequence_id="capability-swap-sequence",
        controller=controller,
        capability=capability,
        phase_ids=("author-phase", "review-phase"),
        created_at=_NOW,
    )
    run_temporary_qwen_content_batch(
        batch_id="swap-author-batch",
        controller=controller,
        capability=capability,
        tasks=(_task("author-dispatch", "temporary-author"),),
        output_dir=output_dir,
        completion=completion,
        clock=_NOW,
        phase_session=session,
        phase_id="author-phase",
    )

    with pytest.raises(TemporaryQwenPoolError, match="different capability"):
        run_temporary_qwen_content_batch(
            batch_id="swap-review-batch",
            controller=other_controller,
            capability=other_capability,
            tasks=(_task("review-dispatch", "temporary-reviewer"),),
            output_dir=output_dir,
            completion=completion,
            clock=_NOW,
            phase_session=session,
            phase_id="review-phase",
        )

    assert session.closed
    assert not capability.active
    assert other_capability.active
    assert len(completion.calls) == 1


def test_cross_phase_controller_swap_revokes_original_session(
    tmp_path: Path,
) -> None:
    controller, capability = _controller(max_parallel_agents=1)
    other_controller, _ = issue_stage_controller(
        lineage_id=controller.lineage_id,
        stage=controller.stage,
        stage_attempt=2,
        controller_agent_id=controller.controller_agent_id,
        stage_input_hash=_HASH_A,
        max_parallel_agents=1,
        claimed_at=_NOW,
        lease_token="controller-swap-stage-token",
    )
    completion = _ConfiguredCompletion()
    session = TemporaryQwenStagePhaseSession(
        sequence_id="controller-swap-sequence",
        controller=controller,
        capability=capability,
        phase_ids=("author-phase", "review-phase"),
        created_at=_NOW,
    )
    run_temporary_qwen_content_batch(
        batch_id="controller-author-batch",
        controller=controller,
        capability=capability,
        tasks=(_task("author-dispatch", "temporary-author"),),
        output_dir=tmp_path / "run",
        completion=completion,
        clock=_NOW,
        phase_session=session,
        phase_id="author-phase",
    )

    with pytest.raises(TemporaryQwenPoolError, match="different controller"):
        run_temporary_qwen_content_batch(
            batch_id="controller-review-batch",
            controller=other_controller,
            capability=capability,
            tasks=(_task("review-dispatch", "temporary-reviewer"),),
            output_dir=tmp_path / "run",
            completion=completion,
            clock=_NOW,
            phase_session=session,
            phase_id="review-phase",
        )

    assert session.closed
    assert not capability.active
    assert len(completion.calls) == 1


def test_phase_session_rejects_non_owner_thread_and_owner_revokes() -> None:
    controller, capability = _controller(max_parallel_agents=1)
    session = TemporaryQwenStagePhaseSession(
        sequence_id="owner-thread-sequence",
        controller=controller,
        capability=capability,
        phase_ids=("author-phase", "review-phase"),
        created_at=_NOW,
    )
    failures: list[Exception] = []

    def hostile_thread() -> None:
        try:
            session.begin_phase(
                phase_id="author-phase",
                controller=controller,
                capability=capability,
                output_dir=Path("."),
            )
        except Exception as exc:
            failures.append(exc)

    thread = threading.Thread(target=hostile_thread)
    thread.start()
    thread.join(timeout=5)

    assert len(failures) == 1
    assert isinstance(failures[0], TemporaryQwenPoolError)
    assert "owner thread" in str(failures[0])
    assert capability.active
    session.abort()
    assert not capability.active


def test_hostile_ids_cannot_escape_output_dir(tmp_path: Path) -> None:
    output_dir = tmp_path / "run"
    controller, capability = _controller(max_parallel_agents=1)
    completion = _ConfiguredCompletion()

    artifact = run_temporary_qwen_content_batch(
        batch_id="batch/../../outside",
        controller=controller,
        capability=capability,
        tasks=(
            _task(
                "dispatch/../../outside",
                "temporary-agent/../../outside",
            ),
        ),
        output_dir=output_dir,
        completion=completion,
        clock=_NOW,
    )

    paths = [
        artifact.output_relative_path,
        artifact.manifest_relative_path,
        artifact.task_records[0].assignment_relative_path,
        str(artifact.task_records[0].result_relative_path),
        artifact.task_records[0].archive_relative_path,
        artifact.task_records[0].record_relative_path,
        str(artifact.task_records[0].authorship_receipt_relative_path),
    ]
    for relative_path in paths:
        assert ".." not in PurePosixPath(relative_path).parts
        assert _inside(output_dir, relative_path).is_file()
    assert not (tmp_path / "outside").exists()


def test_batch_and_task_indexes_reject_hash_tamper(tmp_path: Path) -> None:
    controller, capability = _controller(max_parallel_agents=1)
    artifact = run_temporary_qwen_content_batch(
        batch_id="temporary-batch-integrity",
        controller=controller,
        capability=capability,
        tasks=(_task("dispatch-001", "temporary-agent-001"),),
        output_dir=tmp_path / "run",
        completion=_ConfiguredCompletion(),
        clock=_NOW,
    )

    changed_output = artifact.model_dump(mode="json")
    changed_output["stable_outputs"][0]["output_payload"] = {"诊断摘要": "被篡改的中文输出。"}
    with pytest.raises(TemporaryQwenPoolError, match="output hash mismatch"):
        TemporaryQwenBatchArtifact.model_validate(changed_output)

    changed_record = artifact.task_records[0].model_dump(mode="json")
    changed_record["archive_hash"] = "b" * 64
    with pytest.raises(TemporaryQwenPoolError, match="record hash mismatch"):
        TemporaryQwenTaskRecord.model_validate(changed_record)


def test_temporary_qwen_content_batch_accepts_explicit_zero_skill_task(
    tmp_path: Path,
) -> None:
    controller, capability = _controller(max_parallel_agents=1)
    task = _task("dispatch-zero-skill", "temporary-zero-skill").model_copy(
        update={"skill_contexts": ()}
    )

    artifact = run_temporary_qwen_content_batch(
        batch_id="batch-zero-skill",
        controller=controller,
        capability=capability,
        tasks=(task,),
        output_dir=tmp_path,
        completion=_ConfiguredCompletion(),
        max_workers=1,
        clock=_NOW,
    )

    assert artifact.succeeded_count == 1
    assert artifact.failed_count == 0
    assert not capability.active
