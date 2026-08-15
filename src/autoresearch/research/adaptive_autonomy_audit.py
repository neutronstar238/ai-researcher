"""Mechanical evidence that an adaptive run selected its own research actions.

This audit is intentionally narrow.  It can distinguish a model-selected loop
from a fixed operator script or post-start human prompting; it cannot establish
that the selected science is correct, innovative, or publication ready.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import Field, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    Sha256,
    StableId,
    canonical_json,
    canonical_sha256,
)
from autoresearch.knowledge.raw_memory import RawMemoryStore
from autoresearch.research.adaptive_sovereign_loop import (
    AdaptiveResearchLoopError,
    AdaptiveResearchLoopSnapshot,
    ModelResearchActionDraft,
    ResearchOperator,
    load_adaptive_research_loop_snapshot,
)

_FORCING_KEYS = frozenset(
    {
        "required_operator",
        "forced_operator",
        "next_operator",
        "operator_to_use",
        "预定下一算子",
        "强制算子",
    }
)
_MACHINE_CONTEXT_KINDS = frozenset(
    {
        "adaptive_research_action_contract_repair",
        "adaptive_research_next_action",
        "selected_project_method_skill",
    }
)
_EXTERNAL_FORCING_PHRASES = (
    "必须选择",
    "强制选择",
    "指定算子",
    "禁止改选",
    "下一算子必须",
    "must choose",
    "must select",
    "required operator",
    "forced operator",
)


class AdaptiveAutonomyAuditError(AdaptiveResearchLoopError):
    """Raised when a retained run cannot be audited without guessing."""


class AdaptiveAutonomyTurnEvidence(KernelContract):
    """Per-turn evidence for who chose the operator and what context they saw."""

    step_index: int = Field(ge=1)
    operator: ResearchOperator
    provider_request_attempt_count: int = Field(ge=1, le=3)
    available_operator_count: int = Field(ge=0)
    selected_operator_was_available: bool
    prompt_forcing_key_count: int = Field(ge=0)
    machine_generated_user_context_only: bool
    prior_feedback_reinjected: bool | None = None
    visible_response_matches_proposal: bool
    reasoning_bytes_match_receipt: bool
    declared_qwen_model_identity: bool
    provider_transport_independently_anchored: Literal[False] = False
    skills_in_separate_messages: bool
    model_authored_scientific_content: bool
    human_scientific_prose_count: int = Field(ge=0)


class AdaptiveAutonomyAuditContent(KernelContract):
    """Scope-limited proof of controller autonomy, not scientific autonomy."""

    schema_version: Literal["adaptive-autonomy-audit-v2"] = (
        "adaptive-autonomy-audit-v2"
    )
    loop_id: StableId
    project_id: StableId
    snapshot_hash: Sha256
    turn_evidence: list[AdaptiveAutonomyTurnEvidence] = Field(
        min_length=1,
        max_length=500,
    )
    autonomous_turn_count: int = Field(ge=0)
    unique_operator_count: int = Field(ge=0)
    action_model_call_count: int = Field(ge=0)
    skill_routing_model_call_count: int = Field(ge=0)
    temporary_agent_count: int = Field(ge=0)
    external_action_count: int = Field(ge=0)
    one_initial_user_seed: bool
    seed_contains_no_hypothesis_method_or_plan: bool
    post_start_human_scientific_message_count: int = Field(ge=0)
    exact_raw_memory_replayed: bool
    previous_feedback_exposure_rate: float = Field(ge=0.0, le=1.0)
    model_selected_every_operator: bool
    controller_self_loop_verified: bool
    findings_cn: list[str] = Field(default_factory=list, max_length=64)
    scientific_correctness_verified: Literal[False] = False
    innovation_verified: Literal[False] = False
    formal_execution_authorized: Literal[False] = False
    publication_authorized: Literal[False] = False

    @model_validator(mode="after")
    def _cross_validate(self) -> AdaptiveAutonomyAuditContent:
        if self.autonomous_turn_count != len(self.turn_evidence):
            raise ValueError("autonomy turn count mismatch")
        if self.unique_operator_count != len(
            {turn.operator for turn in self.turn_evidence}
        ):
            raise ValueError("autonomy unique-operator count mismatch")
        if self.action_model_call_count != sum(
            turn.provider_request_attempt_count for turn in self.turn_evidence
        ):
            raise ValueError("autonomy action provider-call count mismatch")
        expected_selected = all(
            turn.available_operator_count >= 2
            and turn.selected_operator_was_available
            and turn.prompt_forcing_key_count == 0
            and turn.machine_generated_user_context_only
            and turn.visible_response_matches_proposal
            and turn.reasoning_bytes_match_receipt
            and turn.declared_qwen_model_identity
            and turn.provider_transport_independently_anchored
            and turn.skills_in_separate_messages
            and turn.model_authored_scientific_content
            and turn.human_scientific_prose_count == 0
            for turn in self.turn_evidence
        )
        if self.model_selected_every_operator != expected_selected:
            raise ValueError("model-selected operator flag mismatch")
        feedback_turns = [
            turn.prior_feedback_reinjected
            for turn in self.turn_evidence
            if turn.prior_feedback_reinjected is not None
        ]
        expected_rate = (
            sum(bool(item) for item in feedback_turns) / len(feedback_turns)
            if feedback_turns
            else 1.0
        )
        if abs(self.previous_feedback_exposure_rate - expected_rate) > 1e-12:
            raise ValueError("feedback exposure rate mismatch")
        expected_loop = (
            len(self.turn_evidence) >= 2
            and self.one_initial_user_seed
            and self.seed_contains_no_hypothesis_method_or_plan
            and self.post_start_human_scientific_message_count == 0
            and self.exact_raw_memory_replayed
            and self.previous_feedback_exposure_rate == 1.0
            and self.model_selected_every_operator
            and not self.findings_cn
        )
        if self.controller_self_loop_verified != expected_loop:
            raise ValueError("controller self-loop verdict mismatch")
        return self


class AdaptiveAutonomyAudit(AdaptiveAutonomyAuditContent):
    """Content-addressed audit suitable for replay and ablation comparison."""

    audit_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> AdaptiveAutonomyAudit:
        expected = canonical_sha256(
            self.model_dump(mode="json", exclude={"audit_hash"})
        )
        if self.audit_hash != expected:
            raise ValueError("adaptive autonomy audit hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveAutonomyAudit:
        content = AdaptiveAutonomyAuditContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, audit_hash=canonical_sha256(payload))


def audit_adaptive_research_autonomy(
    snapshot_path: Path | str,
    *,
    raw_memory_store: RawMemoryStore,
    output_path: Path | str | None = None,
) -> AdaptiveAutonomyAudit:
    """Replay one final snapshot and audit controller-level self-loop claims."""

    snapshot = load_adaptive_research_loop_snapshot(
        snapshot_path,
        raw_memory_store=raw_memory_store,
    )
    turns = [
        _audit_turn(
            snapshot=snapshot,
            event_index=index,
            raw_memory_store=raw_memory_store,
        )
        for index in range(len(snapshot.events))
    ]
    findings: list[str] = []
    if len(turns) < 2:
        findings.append("当前轨迹不足两轮，不能证明控制器形成了自循环。")
    if any(turn.available_operator_count < 2 for turn in turns):
        findings.append("至少一轮没有两个以上可选算子，无法排除单路径脚本。")
    if any(turn.prompt_forcing_key_count for turn in turns):
        findings.append("至少一轮上下文含强制下一算子的控制字段。")
    if any(not turn.machine_generated_user_context_only for turn in turns):
        findings.append(
            "至少一轮含尚未经独立环境谱系证明的外部上下文，或出现无法归类的后置消息。"
        )
    if any(not turn.visible_response_matches_proposal for turn in turns):
        findings.append("至少一轮持久化可见响应与执行的结构化动作不一致。")
    if any(not turn.reasoning_bytes_match_receipt for turn in turns):
        findings.append("至少一轮有界思考字节与回执长度不一致。")
    if any(not turn.declared_qwen_model_identity for turn in turns):
        findings.append("至少一轮动作的自报模型名称不是Qwen。")
    if any(not turn.provider_transport_independently_anchored for turn in turns):
        findings.append(
            "动作回执尚无独立传输锚，provider/model字符串不能单独证明真实Qwen调用。"
        )
    if any(not turn.skills_in_separate_messages for turn in turns):
        findings.append("至少一轮把方法技能混入主系统提示词或消息结构不明。")
    if any(not turn.model_authored_scientific_content for turn in turns):
        findings.append("至少一轮缺少模型生成科研内容的结构化声明。")
    if any(turn.human_scientific_prose_count for turn in turns):
        findings.append("至少一轮记录了启动后的人工计划、假设或方法散文。")
    feedback_turns = [
        turn.prior_feedback_reinjected
        for turn in turns
        if turn.prior_feedback_reinjected is not None
    ]
    feedback_rate = (
        sum(bool(item) for item in feedback_turns) / len(feedback_turns)
        if feedback_turns
        else 1.0
    )
    if feedback_rate < 1.0:
        findings.append("至少一轮没有收到上一轮外部或编排反馈。")
    seed_clean = (
        snapshot.seed.supplied_hypothesis is None
        and snapshot.seed.supplied_method is None
        and snapshot.seed.supplied_research_plan is None
        and snapshot.seed.human_authored_scientific_prose_count == 0
    )
    model_selected = all(
        turn.available_operator_count >= 2
        and turn.selected_operator_was_available
        and turn.prompt_forcing_key_count == 0
        and turn.machine_generated_user_context_only
        and turn.visible_response_matches_proposal
        and turn.reasoning_bytes_match_receipt
        and turn.declared_qwen_model_identity
        and turn.provider_transport_independently_anchored
        and turn.skills_in_separate_messages
        and turn.model_authored_scientific_content
        and turn.human_scientific_prose_count == 0
        for turn in turns
    )
    audit = AdaptiveAutonomyAudit.create(
        loop_id=snapshot.seed.loop_id,
        project_id=snapshot.seed.project_id,
        snapshot_hash=snapshot.snapshot_hash,
        turn_evidence=turns,
        autonomous_turn_count=len(turns),
        unique_operator_count=len({turn.operator for turn in turns}),
        action_model_call_count=sum(
            turn.provider_request_attempt_count for turn in turns
        ),
        skill_routing_model_call_count=snapshot.skill_routing_model_call_count,
        temporary_agent_count=snapshot.temporary_agent_count,
        external_action_count=snapshot.external_action_count,
        one_initial_user_seed=True,
        seed_contains_no_hypothesis_method_or_plan=seed_clean,
        post_start_human_scientific_message_count=0,
        exact_raw_memory_replayed=True,
        previous_feedback_exposure_rate=feedback_rate,
        model_selected_every_operator=model_selected,
        controller_self_loop_verified=(
            len(turns) >= 2
            and seed_clean
            and feedback_rate == 1.0
            and model_selected
            and not findings
        ),
        findings_cn=findings,
    )
    if output_path is not None:
        _write_once(
            Path(output_path),
            (canonical_json(audit) + "\n").encode("utf-8"),
        )
    return audit


def _audit_turn(
    *,
    snapshot: AdaptiveResearchLoopSnapshot,
    event_index: int,
    raw_memory_store: RawMemoryStore,
) -> AdaptiveAutonomyTurnEvidence:
    event = snapshot.events[event_index]
    interaction = event.interaction
    task_payload = _task_payload(interaction.messages)
    available = task_payload.get("available_operators")
    if not isinstance(available, dict):
        raise AdaptiveAutonomyAuditError("adaptive turn lacks an operator catalogue")
    user_context_kinds: list[str] = []
    user_payloads: list[dict[str, Any]] = []
    skills_separate = True
    system_text = interaction.messages[0]["content"]
    for message in interaction.messages:
        if message["role"] != "user":
            continue
        try:
            payload = json.loads(message["content"])
        except json.JSONDecodeError:
            user_context_kinds.append("unparsed")
            continue
        context_kind = str(payload.get("context_kind") or "")
        user_context_kinds.append(context_kind)
        user_payloads.append(payload)
        if context_kind == "selected_project_method_skill":
            skill_content = str(payload.get("skill_content") or "")
            if not skill_content or skill_content in system_text:
                skills_separate = False
    response_capture = raw_memory_store.load_record(
        interaction.response_binding.record_relative_path,
        project_id=snapshot.seed.project_id,
    )
    reasoning_capture = raw_memory_store.load_record(
        interaction.reasoning_binding.record_relative_path,
        project_id=snapshot.seed.project_id,
    )
    try:
        visible_action = ModelResearchActionDraft.model_validate_json(
            response_capture.blob_path.read_bytes()
        )
    except ValueError:
        visible_matches = False
    else:
        visible_matches = visible_action == interaction.proposal
    reasoning_text = reasoning_capture.blob_path.read_text(encoding="utf-8").strip()
    prior_feedback = None
    if event_index:
        previous = snapshot.events[event_index - 1]
        recent = task_payload.get("recent_external_feedback")
        prior_feedback = isinstance(recent, list) and any(
            isinstance(item, dict)
            and item.get("step_index") == previous.step_index
            and item.get("feedback_status") == previous.feedback.status.value
            and item.get("feedback_summary_cn") == previous.feedback.summary_cn
            for item in recent
        )
    return AdaptiveAutonomyTurnEvidence(
        step_index=event.step_index,
        operator=interaction.proposal.operator,
        provider_request_attempt_count=len(interaction.model_call_registrations),
        available_operator_count=len(available),
        selected_operator_was_available=(
            interaction.proposal.operator.value in available
        ),
        prompt_forcing_key_count=(
            sum(_count_forcing_keys(payload) for payload in user_payloads)
            + sum(
                _count_external_forcing(payload)
                for payload in user_payloads
                if payload.get("context_kind")
                == "adaptive_external_turn_context"
            )
        ),
        machine_generated_user_context_only=(
            bool(user_context_kinds)
            and all(kind in _MACHINE_CONTEXT_KINDS for kind in user_context_kinds)
        ),
        prior_feedback_reinjected=prior_feedback,
        visible_response_matches_proposal=visible_matches,
        reasoning_bytes_match_receipt=(
            len(reasoning_text) == interaction.reasoning_character_count
        ),
        declared_qwen_model_identity=(
            "qwen"
            in f"{interaction.provider} {interaction.model_name}".casefold()
        ),
        skills_in_separate_messages=skills_separate,
        model_authored_scientific_content=(
            interaction.proposal.scientific_content_generated_by_model
            and event.scientific_content_authored_by_model
        ),
        human_scientific_prose_count=(
            interaction.hand_written_scientific_prose_count
            + interaction.proposal.human_authored_scientific_prose_count
            + event.orchestrator_scientific_prose_count
        ),
    )


def _task_payload(
    messages: Sequence[Mapping[Literal["role", "content"], str]],
) -> dict[str, Any]:
    for message in reversed(messages):
        if message["role"] != "user":
            continue
        try:
            payload = json.loads(message["content"])
        except json.JSONDecodeError:
            continue
        if (
            isinstance(payload, dict)
            and payload.get("context_kind") == "adaptive_research_next_action"
        ):
            return cast(dict[str, Any], payload)
    raise AdaptiveAutonomyAuditError("adaptive action task payload is absent")


def _count_forcing_keys(value: Any) -> int:
    if isinstance(value, dict):
        return sum(
            int(str(key).casefold() in _FORCING_KEYS)
            + _count_forcing_keys(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return sum(_count_forcing_keys(item) for item in value)
    return 0


def _count_external_forcing(payload: Mapping[str, Any]) -> int:
    """Detect imperative operator steering in untrusted external observations."""

    content = str(payload.get("content_cn") or "").casefold()
    return sum(content.count(phrase) for phrase in _EXTERNAL_FORCING_PHRASES)


def _write_once(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
    except FileExistsError:
        if path.read_bytes() != payload:
            raise AdaptiveAutonomyAuditError(
                f"immutable autonomy audit changed: {path}"
            ) from None


__all__ = [
    "AdaptiveAutonomyAudit",
    "AdaptiveAutonomyAuditError",
    "AdaptiveAutonomyTurnEvidence",
    "audit_adaptive_research_autonomy",
]
