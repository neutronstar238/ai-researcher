from __future__ import annotations

import json
import pickle
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from autoresearch.agents import (
    StageControllerBinding,
    StageDispatchCapability,
    TemporaryAgentArchiveCoordinator,
    TemporaryAgentAssignment,
    TemporaryAgentContractError,
    TemporaryAgentInputRef,
    TemporaryAgentResultArtifact,
    TemporaryAgentSkillRef,
    TemporaryAgentTaskKind,
    TemporaryAgentTerminalStatus,
    issue_stage_controller,
)
from autoresearch.kernel.contracts import canonical_sha256

_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64
_NOW = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)


def _controller(
    *, max_parallel_agents: int = 3
) -> tuple[StageControllerBinding, StageDispatchCapability]:
    return issue_stage_controller(
        lineage_id="lineage-001",
        stage="research-plan",
        stage_attempt=1,
        controller_agent_id="main-agent",
        stage_input_hash=_HASH_A,
        max_parallel_agents=max_parallel_agents,
        claimed_at=_NOW,
        lease_token="main-only-token-0001",
    )


def _input_ref(*, artifact_id: str = "artifact.input.001") -> TemporaryAgentInputRef:
    return TemporaryAgentInputRef(
        artifact_id=artifact_id,
        source_ref="evidence/input.json",
        sha256=_HASH_B,
    )


def _skill_ref() -> TemporaryAgentSkillRef:
    return TemporaryAgentSkillRef(
        skill_id="sparse-dynamics-identification",
        source_ref="skills/sparse-dynamics-identification/SKILL.md",
        content_sha256=_HASH_C,
    )


def _assignment(
    *,
    dispatch_id: str = "dispatch-001",
    temporary_agent_id: str = "temporary-agent-001",
    max_parallel_agents: int = 3,
    minimum_reasoning_characters: int = 1,
) -> tuple[
    StageControllerBinding,
    StageDispatchCapability,
    TemporaryAgentAssignment,
]:
    controller, capability = _controller(max_parallel_agents=max_parallel_agents)
    assignment = TemporaryAgentAssignment.create(
        controller=controller,
        capability=capability,
        dispatch_id=dispatch_id,
        temporary_agent_id=temporary_agent_id,
        parent_task_id="task-plan-001",
        task_kind=TemporaryAgentTaskKind.EVIDENCE_MEMO,
        task_instruction="只根据给定证据输出有界中文诊断备忘录。",
        input_refs=(_input_ref(),),
        input_payload={"证据编号": ["E01", "E02"]},
        expected_output_schema={
            "type": "object",
            "required": ["诊断摘要"],
            "properties": {"诊断摘要": {"type": "string"}},
        },
        chinese_output_fields=("诊断摘要",),
        selected_skills=(_skill_ref(),),
        max_tokens=2_000,
        timeout_seconds=300,
        minimum_reasoning_characters=minimum_reasoning_characters,
    )
    return controller, capability, assignment


def _result(
    assignment: TemporaryAgentAssignment,
    *,
    summary: str = "该备忘录只整理给定证据，不形成审批、执行或发表结论。",
) -> TemporaryAgentResultArtifact:
    return TemporaryAgentResultArtifact.create(
        assignment=assignment,
        output_payload={"诊断摘要": summary},
        authorship_receipt_relative_path="interactions/model-call-01.json",
        authorship_receipt_hash=_HASH_A,
        model_name="qwen-test",
        reasoning_character_count=240,
        created_at=_NOW,
    )


def test_stage_controller_binding_is_hash_bound_and_hides_raw_token() -> None:
    binding, capability = _controller()

    capability.require_valid(binding)
    payload = binding.model_dump(mode="json")

    assert payload["controller_role"] == "main_agent"
    assert payload["binding_hash"] == canonical_sha256(
        {key: value for key, value in payload.items() if key != "binding_hash"}
    )
    assert "main-only-token-0001" not in binding.model_dump_json()
    assert "main-only-token-0001" not in repr(capability)


def test_dispatch_capability_is_memory_only_and_not_serializable() -> None:
    _binding, capability = _controller()

    with pytest.raises(TypeError, match="not serializable"):
        pickle.dumps(capability)
    with pytest.raises(TypeError):
        json.dumps(capability)


def test_wrong_or_revoked_main_agent_token_is_rejected() -> None:
    first_binding, first_capability = _controller()
    second_binding, second_capability = issue_stage_controller(
        lineage_id="lineage-002",
        stage="research-plan",
        stage_attempt=1,
        controller_agent_id="other-main-agent",
        stage_input_hash=_HASH_A,
        max_parallel_agents=2,
        claimed_at=_NOW,
        lease_token="another-main-token-02",
    )

    with pytest.raises(TemporaryAgentContractError, match="another controller"):
        second_capability.require_valid(first_binding)

    first_capability.revoke()
    assert not first_capability.active
    with pytest.raises(TemporaryAgentContractError, match="revoked"):
        first_capability.require_valid(first_binding)
    second_capability.require_valid(second_binding)


def test_controller_binding_tamper_fails_hash_validation() -> None:
    binding, _capability = _controller()
    payload = binding.model_dump(mode="json")
    payload["stage"] = "experiment"

    with pytest.raises(ValidationError, match="binding hash mismatch"):
        StageControllerBinding.model_validate(payload)


def test_assignment_binds_inputs_schema_skills_and_all_denied_authorities() -> None:
    controller, _capability, assignment = _assignment()

    assert assignment.controller_binding_hash == controller.binding_hash
    assert assignment.controller_agent_id == controller.controller_agent_id
    assert assignment.input_bundle_sha256 == canonical_sha256(
        {
            "input_refs": [item.model_dump(mode="json") for item in assignment.input_refs],
            "input_payload": assignment.input_payload,
        }
    )
    assert assignment.output_schema_sha256 == canonical_sha256(assignment.expected_output_schema)
    assert assignment.output_language == "zh-CN"
    assert assignment.max_delegation_depth == 1
    assert assignment.allowed_tools == ()
    assert not assignment.can_delegate
    assert not assignment.can_approve
    assert not assignment.can_execute
    assert not assignment.can_adjudicate
    assert not assignment.can_publish
    assert not assignment.can_release
    assert not assignment.can_promote_evidence
    assert not assignment.is_scientific_evidence


def test_assignment_rejects_tool_or_gate_authority_and_hash_tamper() -> None:
    _controller_binding, _capability, assignment = _assignment()

    for field, value in (
        ("can_delegate", True),
        ("can_approve", True),
        ("can_execute", True),
        ("can_adjudicate", True),
        ("can_publish", True),
        ("can_release", True),
        ("can_promote_evidence", True),
        ("allowed_tools", ["shell"]),
    ):
        payload = assignment.model_dump(mode="json")
        payload[field] = value
        with pytest.raises(ValidationError):
            TemporaryAgentAssignment.model_validate(payload)

    changed_input = assignment.model_dump(mode="json")
    changed_input["input_payload"] = {"证据编号": ["E99"]}
    with pytest.raises(ValidationError, match="input hash mismatch"):
        TemporaryAgentAssignment.model_validate(changed_input)

    english_instruction = assignment.model_dump(mode="json")
    english_instruction["task_instruction"] = "Write an evidence memo."
    english_instruction["assignment_hash"] = canonical_sha256(
        {key: value for key, value in english_instruction.items() if key != "assignment_hash"}
    )
    with pytest.raises(ValidationError, match="instruction must be Chinese"):
        TemporaryAgentAssignment.model_validate(english_instruction)


def test_result_requires_bounded_reasoning_and_safe_receipt_path() -> None:
    _controller_binding, _capability, assignment = _assignment(minimum_reasoning_characters=200)

    with pytest.raises(TemporaryAgentContractError, match="reasoning is shorter"):
        TemporaryAgentResultArtifact.create(
            assignment=assignment,
            output_payload={"诊断摘要": "仅为测试。"},
            authorship_receipt_relative_path="interactions/call.json",
            authorship_receipt_hash=_HASH_A,
            model_name="qwen-test",
            reasoning_character_count=199,
        )

    with pytest.raises(ValidationError, match="inside the task archive"):
        TemporaryAgentResultArtifact.create(
            assignment=assignment,
            output_payload={"诊断摘要": "仅为测试。"},
            authorship_receipt_relative_path="../outside.json",
            authorship_receipt_hash=_HASH_A,
            model_name="qwen-test",
            reasoning_character_count=240,
        )

    with pytest.raises(ValidationError, match="inside the task archive"):
        TemporaryAgentResultArtifact.create(
            assignment=assignment,
            output_payload={"诊断摘要": "仅为测试。"},
            authorship_receipt_relative_path="C:\\outside.json",
            authorship_receipt_hash=_HASH_A,
            model_name="qwen-test",
            reasoning_character_count=240,
        )


def test_result_requires_the_declared_chinese_output_fields() -> None:
    _controller_binding, _capability, assignment = _assignment()

    with pytest.raises(TemporaryAgentContractError, match="omits required Chinese"):
        TemporaryAgentResultArtifact.create(
            assignment=assignment,
            output_payload={"其他字段": "中文但字段错误。"},
            authorship_receipt_relative_path="interactions/call.json",
            authorship_receipt_hash=_HASH_A,
            model_name="qwen-test",
            reasoning_character_count=240,
        )
    with pytest.raises(TemporaryAgentContractError, match="contain Chinese text"):
        TemporaryAgentResultArtifact.create(
            assignment=assignment,
            output_payload={"诊断摘要": "English only."},
            authorship_receipt_relative_path="interactions/call.json",
            authorship_receipt_hash=_HASH_A,
            model_name="qwen-test",
            reasoning_character_count=240,
        )


def test_result_is_hash_bound_and_cannot_claim_any_gate_authority() -> None:
    _controller_binding, _capability, assignment = _assignment()
    result = _result(assignment)

    assert result.output_payload_sha256 == canonical_sha256(result.output_payload)
    assert result.authored_by_model
    assert result.hand_written_scientific_prose_count == 0
    assert not result.reasoning_is_evidence
    assert not result.is_scientific_evidence
    assert not result.delegation_authorized
    assert not result.approval_authorized
    assert not result.execution_authorized
    assert not result.adjudication_authorized
    assert not result.publication_authorized
    assert not result.release_authorized
    assert not result.evidence_promotion_authorized

    tampered = result.model_dump(mode="json")
    tampered["output_payload"] = {"诊断摘要": "被篡改的内容。"}
    with pytest.raises(ValidationError, match="output hash mismatch"):
        TemporaryAgentResultArtifact.model_validate(tampered)


def test_coordinator_archives_identity_but_retains_result_and_receipt() -> None:
    controller, capability, assignment = _assignment()
    coordinator = TemporaryAgentArchiveCoordinator(controller)
    result = _result(assignment)

    coordinator.dispatch(assignment, capability=capability)
    assert coordinator.active_agent_ids == (assignment.temporary_agent_id,)
    coordinator.record_result(result, capability=capability)
    archive = coordinator.archive(
        assignment.dispatch_id,
        terminal_status=TemporaryAgentTerminalStatus.SUCCEEDED,
        capability=capability,
        archived_at=_NOW,
    )

    assert coordinator.active_agent_ids == ()
    assert archive.runtime_identity_inactive
    assert archive.runtime_identity_removed
    assert archive.output_retained
    assert archive.result_hash == result.result_hash
    assert archive.authorship_receipt_hash == result.authorship_receipt_hash
    assert not archive.delegation_capability_was_granted
    assert not archive.approval_authorized
    assert not archive.execution_authorized


def test_coordinator_rechecks_hashes_and_keeps_defensive_result_snapshot() -> None:
    controller, capability, assignment = _assignment()
    assignment.input_payload["证据编号"] = ["E99"]
    coordinator = TemporaryAgentArchiveCoordinator(controller)

    with pytest.raises(TemporaryAgentContractError, match="assignment hash mismatch"):
        coordinator.dispatch(assignment, capability=capability)

    controller, capability, assignment = _assignment()
    coordinator = TemporaryAgentArchiveCoordinator(controller)
    result = _result(assignment)
    coordinator.dispatch(assignment, capability=capability)
    coordinator.record_result(result, capability=capability)
    result.output_payload["诊断摘要"] = "调用方事后篡改。"
    coordinator.archive(
        assignment.dispatch_id,
        terminal_status=TemporaryAgentTerminalStatus.SUCCEEDED,
        capability=capability,
    )

    assert coordinator.stable_outputs() == (
        {"诊断摘要": "该备忘录只整理给定证据，不形成审批、执行或发表结论。"},
    )


def test_successful_archive_requires_result_and_main_agent_token() -> None:
    controller, capability, assignment = _assignment()
    coordinator = TemporaryAgentArchiveCoordinator(controller)
    coordinator.dispatch(assignment, capability=capability)

    with pytest.raises(TemporaryAgentContractError, match="retained result"):
        coordinator.archive(
            assignment.dispatch_id,
            terminal_status=TemporaryAgentTerminalStatus.SUCCEEDED,
            capability=capability,
        )

    other_binding, other_capability = _controller()
    assert other_binding.binding_hash == controller.binding_hash
    other_capability.revoke()
    with pytest.raises(TemporaryAgentContractError, match="revoked"):
        coordinator.archive(
            assignment.dispatch_id,
            terminal_status=TemporaryAgentTerminalStatus.FAILED,
            capability=other_capability,
        )


def test_parallelism_limit_and_runtime_identity_reuse_are_refused() -> None:
    controller, capability, first = _assignment(max_parallel_agents=1)
    second = TemporaryAgentAssignment.create(
        controller=controller,
        capability=capability,
        dispatch_id="dispatch-002",
        temporary_agent_id="temporary-agent-002",
        parent_task_id="task-plan-001",
        task_kind=TemporaryAgentTaskKind.CONTENT_CHECKLIST,
        task_instruction="输出中文内容检查清单。",
        input_refs=(_input_ref(artifact_id="artifact.input.002"),),
        input_payload={"检查对象": "候选备忘录"},
        expected_output_schema={"type": "object", "required": ["检查项"]},
        chinese_output_fields=("检查项",),
        selected_skills=(_skill_ref(),),
        max_tokens=1_000,
        timeout_seconds=120,
    )
    coordinator = TemporaryAgentArchiveCoordinator(controller)
    coordinator.dispatch(first, capability=capability)

    with pytest.raises(TemporaryAgentContractError, match="parallelism"):
        coordinator.dispatch(second, capability=capability)

    coordinator.archive(
        first.dispatch_id,
        terminal_status=TemporaryAgentTerminalStatus.CANCELLED,
        capability=capability,
    )
    coordinator.dispatch(second, capability=capability)

    reused_identity_payload = second.model_dump(mode="json")
    reused_identity_payload["dispatch_id"] = "dispatch-003"
    reused_identity_payload["temporary_agent_id"] = first.temporary_agent_id
    reused_identity_payload["assignment_hash"] = canonical_sha256(
        {key: value for key, value in reused_identity_payload.items() if key != "assignment_hash"}
    )
    reused_identity = TemporaryAgentAssignment.model_validate(reused_identity_payload)
    coordinator.archive(
        second.dispatch_id,
        terminal_status=TemporaryAgentTerminalStatus.BLOCKED,
        capability=capability,
    )
    with pytest.raises(TemporaryAgentContractError, match="already used"):
        coordinator.dispatch(reused_identity, capability=capability)


def test_batch_manifest_requires_all_archived_and_stably_merges_outputs() -> None:
    controller, capability = _controller(max_parallel_agents=2)
    first = TemporaryAgentAssignment.create(
        controller=controller,
        capability=capability,
        dispatch_id="dispatch-002",
        temporary_agent_id="temporary-agent-002",
        parent_task_id="task-plan-001",
        task_kind=TemporaryAgentTaskKind.OPPORTUNITY_MEMO,
        task_instruction="输出第二份中文备忘录。",
        input_refs=(_input_ref(artifact_id="artifact.input.002"),),
        input_payload={"分组": 2},
        expected_output_schema={"type": "object", "required": ["诊断摘要"]},
        chinese_output_fields=("诊断摘要",),
        selected_skills=(_skill_ref(),),
        max_tokens=2_000,
        timeout_seconds=300,
    )
    second = TemporaryAgentAssignment.create(
        controller=controller,
        capability=capability,
        dispatch_id="dispatch-001",
        temporary_agent_id="temporary-agent-001",
        parent_task_id="task-plan-001",
        task_kind=TemporaryAgentTaskKind.OPPORTUNITY_MEMO,
        task_instruction="输出第一份中文备忘录。",
        input_refs=(_input_ref(),),
        input_payload={"分组": 1},
        expected_output_schema={"type": "object", "required": ["诊断摘要"]},
        chinese_output_fields=("诊断摘要",),
        selected_skills=(_skill_ref(),),
        max_tokens=2_000,
        timeout_seconds=300,
    )
    coordinator = TemporaryAgentArchiveCoordinator(controller)
    coordinator.dispatch(first, capability=capability)
    coordinator.dispatch(second, capability=capability)
    coordinator.record_result(_result(first, summary="第二份模型输出。"), capability=capability)
    coordinator.record_result(_result(second, summary="第一份模型输出。"), capability=capability)

    with pytest.raises(TemporaryAgentContractError, match="active runtime"):
        coordinator.build_manifest(batch_id="batch-001", capability=capability)

    coordinator.archive(
        first.dispatch_id,
        terminal_status=TemporaryAgentTerminalStatus.SUCCEEDED,
        capability=capability,
    )
    coordinator.archive(
        second.dispatch_id,
        terminal_status=TemporaryAgentTerminalStatus.SUCCEEDED,
        capability=capability,
    )
    assert coordinator.stable_outputs() == (
        {"诊断摘要": "第一份模型输出。"},
        {"诊断摘要": "第二份模型输出。"},
    )

    manifest = coordinator.build_manifest(
        batch_id="batch-001",
        capability=capability,
        created_at=_NOW,
    )

    assert [entry.dispatch_id for entry in manifest.entries] == [
        "dispatch-001",
        "dispatch-002",
    ]
    assert manifest.dispatched_count == 2
    assert manifest.succeeded_count == 2
    assert manifest.failed_count == 0
    assert manifest.all_assignments_archived
    assert manifest.all_runtime_identities_inactive
    assert manifest.outputs_retained
    assert not manifest.evidence_gate_bypassed
    assert not manifest.approval_gate_bypassed
    assert not manifest.safety_gate_bypassed
    assert not manifest.independent_review_bypassed
    assert not capability.active


def test_failed_agent_is_archived_without_inventing_valid_output() -> None:
    controller, capability, assignment = _assignment()
    coordinator = TemporaryAgentArchiveCoordinator(controller)
    coordinator.dispatch(assignment, capability=capability)
    archive = coordinator.archive(
        assignment.dispatch_id,
        terminal_status=TemporaryAgentTerminalStatus.FAILED,
        capability=capability,
    )
    manifest = coordinator.build_manifest(
        batch_id="batch-failed",
        capability=capability,
    )

    assert archive.result_hash is None
    assert archive.authorship_receipt_hash is None
    assert archive.output_retained
    assert manifest.failed_count == 1
    assert manifest.succeeded_count == 0
    assert coordinator.stable_outputs() == ()


def test_manifest_hash_tamper_is_rejected_and_closed_batch_cannot_dispatch() -> None:
    controller, capability, assignment = _assignment()
    coordinator = TemporaryAgentArchiveCoordinator(controller)
    coordinator.dispatch(assignment, capability=capability)
    result = _result(assignment)
    coordinator.record_result(result, capability=capability)
    coordinator.archive(
        assignment.dispatch_id,
        terminal_status=TemporaryAgentTerminalStatus.SUCCEEDED,
        capability=capability,
    )
    manifest = coordinator.build_manifest(
        batch_id="batch-001",
        capability=capability,
    )

    tampered = manifest.model_dump(mode="json")
    tampered["succeeded_count"] = 0
    with pytest.raises(ValidationError, match="success count mismatch"):
        type(manifest).model_validate(tampered)

    with pytest.raises(TemporaryAgentContractError, match="closed"):
        coordinator.dispatch(assignment, capability=capability)


def test_temporary_assignment_may_explicitly_use_no_skill_context() -> None:
    controller, capability = _controller()
    assignment = TemporaryAgentAssignment.create(
        controller=controller,
        capability=capability,
        dispatch_id="dispatch-zero-skill",
        temporary_agent_id="temporary-zero-skill",
        parent_task_id="parent-zero-skill",
        task_kind=TemporaryAgentTaskKind.ADVERSARIAL_CRITIQUE,
        task_instruction="只根据给定输入寻找反例，不加载任何不相关方法技能。",
        input_refs=(_input_ref(),),
        input_payload={"问题": "当前机制可能在哪些条件下失败？"},
        expected_output_schema={
            "type": "object",
            "properties": {"结论": {"type": "string"}},
            "required": ["结论"],
            "additionalProperties": False,
        },
        chinese_output_fields=("结论",),
        selected_skills=(),
        max_tokens=512,
        timeout_seconds=30,
    )

    assert assignment.selected_skills == ()
