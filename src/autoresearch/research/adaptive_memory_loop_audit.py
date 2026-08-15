"""Replay proof that sovereign raw recall re-entered a later model turn."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

from pydantic import Field, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    Sha256,
    StableId,
    canonical_json,
    canonical_sha256,
)
from autoresearch.knowledge.raw_memory import RawMemoryBinding, RawMemoryStore
from autoresearch.research.adaptive_sovereign_loop import (
    AdaptiveResearchLoopError,
    AdaptiveResearchLoopSnapshot,
    ResearchOperator,
    load_adaptive_research_loop_snapshot,
)
from autoresearch.research.adaptive_sovereign_recall import (
    SovereignRawRecallEngine,
    SovereignRecallSelection,
    recall_findings_cn,
)

_RECENT_EVENT_WINDOW = 8


class AdaptiveMemoryLoopAuditError(AdaptiveResearchLoopError):
    """Raised when retained memory-loop evidence is missing or ambiguous."""


class AdaptiveMemoryTransportEvidence(KernelContract):
    """One Dreaming selection and its exact exposure to the next action model."""

    dreaming_step_index: int = Field(ge=1)
    next_step_index: int = Field(ge=2)
    branch_id: StableId
    selection_relative_path: str = Field(min_length=1, max_length=1_024)
    selection_hash: Sha256
    selection_snapshot_hash: Sha256
    candidate_record_count: int = Field(ge=1)
    selected_record_ids: list[StableId] = Field(min_length=1, max_length=12)
    selected_record_count: int = Field(ge=1, le=12)
    selected_older_than_eight_events_count: int = Field(ge=0, le=12)
    privacy_excluded_record_count: int = Field(ge=0)
    all_selected_raw_bindings_replayed: bool
    dreaming_feedback_matches_selection: bool
    selection_artifact_bound_to_feedback: bool
    exact_feedback_exposed_to_next_model: bool
    next_action_model_authored: bool
    no_post_start_human_scientific_prose: bool
    is_scientific_evidence: Literal[False] = False

    @model_validator(mode="after")
    def _validate_counts(self) -> AdaptiveMemoryTransportEvidence:
        if self.selected_record_count != len(self.selected_record_ids):
            raise ValueError("memory transport selected-record count mismatch")
        if len(self.selected_record_ids) != len(set(self.selected_record_ids)):
            raise ValueError("memory transport repeats a selected record")
        if self.next_step_index != self.dreaming_step_index + 1:
            raise ValueError("memory transport must inspect the immediate next turn")
        return self


class AdaptiveMemoryLoopAuditContent(KernelContract):
    """Scope-limited proof of memory transport, never proof of scientific benefit."""

    schema_version: Literal["adaptive-memory-loop-audit-v2"] = (
        "adaptive-memory-loop-audit-v2"
    )
    loop_id: StableId
    project_id: StableId
    final_snapshot_hash: Sha256
    dreaming_event_count: int = Field(ge=0)
    completed_memory_transport_count: int = Field(ge=0)
    transport_evidence: list[AdaptiveMemoryTransportEvidence] = Field(max_length=500)
    older_than_recent_event_window_recalled: bool
    exact_recall_exposed_to_later_model: bool
    controller_memory_transport_verified: bool
    findings_cn: list[str] = Field(default_factory=list, max_length=32)
    causal_memory_benefit_verified: Literal[False] = False
    scientific_correctness_verified: Literal[False] = False
    innovation_verified: Literal[False] = False
    execution_authorized: Literal[False] = False
    publication_authorized: Literal[False] = False

    @model_validator(mode="after")
    def _validate_verdict(self) -> AdaptiveMemoryLoopAuditContent:
        if self.completed_memory_transport_count != len(self.transport_evidence):
            raise ValueError("memory transport evidence count mismatch")
        expected_full_history = any(
            item.selected_older_than_eight_events_count > 0
            for item in self.transport_evidence
        )
        if self.older_than_recent_event_window_recalled != expected_full_history:
            raise ValueError("older-event recall verdict mismatch")
        expected_exposure = bool(self.transport_evidence) and all(
            item.exact_feedback_exposed_to_next_model
            for item in self.transport_evidence
        )
        if self.exact_recall_exposed_to_later_model != expected_exposure:
            raise ValueError("memory exposure verdict mismatch")
        expected_transport = (
            self.dreaming_event_count == len(self.transport_evidence)
            and expected_full_history
            and expected_exposure
            and all(
                item.all_selected_raw_bindings_replayed
                and item.dreaming_feedback_matches_selection
                and item.selection_artifact_bound_to_feedback
                and item.next_action_model_authored
                and item.no_post_start_human_scientific_prose
                for item in self.transport_evidence
            )
            and not self.findings_cn
        )
        if self.controller_memory_transport_verified != expected_transport:
            raise ValueError("controller memory-transport verdict mismatch")
        return self


class AdaptiveMemoryLoopAudit(AdaptiveMemoryLoopAuditContent):
    audit_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> AdaptiveMemoryLoopAudit:
        expected = canonical_sha256(
            self.model_dump(mode="json", exclude={"audit_hash"})
        )
        if self.audit_hash != expected:
            raise ValueError("memory-loop audit hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveMemoryLoopAudit:
        content = AdaptiveMemoryLoopAuditContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, audit_hash=canonical_sha256(payload))


def audit_adaptive_memory_loop(
    snapshot_path: Path | str,
    *,
    raw_memory_store: RawMemoryStore,
    output_path: Path | str | None = None,
) -> AdaptiveMemoryLoopAudit:
    """Verify exact raw recall -> Dreaming feedback -> next model prompt transport."""

    final_path = Path(snapshot_path).resolve()
    final = load_adaptive_research_loop_snapshot(
        final_path,
        raw_memory_store=raw_memory_store,
    )
    run_root = final_path.parent.parent
    dreaming_indices = [
        index
        for index, event in enumerate(final.events)
        if event.interaction.proposal.operator
        is ResearchOperator.CONSOLIDATE_DREAMING
    ]
    evidence: list[AdaptiveMemoryTransportEvidence] = []
    findings: list[str] = []
    for event_index in dreaming_indices:
        if event_index + 1 >= len(final.events):
            findings.append(
                f"第{final.events[event_index].step_index}轮Dreaming之后没有下一次模型调用。"
            )
            continue
        evidence.append(
            _audit_memory_transition(
                final=final,
                event_index=event_index,
                run_root=run_root,
                raw_memory_store=raw_memory_store,
            )
        )
    if not dreaming_indices:
        findings.append("轨迹中没有由主Agent选择的Dreaming动作。")
    if evidence and not any(
        item.selected_older_than_eight_events_count > 0 for item in evidence
    ):
        findings.append("Dreaming尚未召回离开最近八轮短期窗口的历史记录。")
    for item in evidence:
        if not item.all_selected_raw_bindings_replayed:
            findings.append(f"第{item.dreaming_step_index}轮原始记忆绑定无法完整重放。")
        if not item.dreaming_feedback_matches_selection:
            findings.append(f"第{item.dreaming_step_index}轮反馈不等于确定性召回结果。")
        if not item.selection_artifact_bound_to_feedback:
            findings.append(f"第{item.dreaming_step_index}轮反馈未绑定召回制品。")
        if not item.exact_feedback_exposed_to_next_model:
            findings.append(f"第{item.next_step_index}轮模型未收到上一轮完整召回反馈。")
        if not item.next_action_model_authored:
            findings.append(f"第{item.next_step_index}轮动作缺少模型作者声明。")
        if not item.no_post_start_human_scientific_prose:
            findings.append(f"第{item.next_step_index}轮含启动后人工科研散文。")
    full_history = any(
        item.selected_older_than_eight_events_count > 0 for item in evidence
    )
    exact_exposure = bool(evidence) and all(
        item.exact_feedback_exposed_to_next_model for item in evidence
    )
    verified = (
        len(dreaming_indices) == len(evidence)
        and full_history
        and exact_exposure
        and all(
            item.all_selected_raw_bindings_replayed
            and item.dreaming_feedback_matches_selection
            and item.selection_artifact_bound_to_feedback
            and item.next_action_model_authored
            and item.no_post_start_human_scientific_prose
            for item in evidence
        )
        and not findings
    )
    audit = AdaptiveMemoryLoopAudit.create(
        loop_id=final.seed.loop_id,
        project_id=final.seed.project_id,
        final_snapshot_hash=final.snapshot_hash,
        dreaming_event_count=len(dreaming_indices),
        completed_memory_transport_count=len(evidence),
        transport_evidence=evidence,
        older_than_recent_event_window_recalled=full_history,
        exact_recall_exposed_to_later_model=exact_exposure,
        controller_memory_transport_verified=verified,
        findings_cn=findings,
    )
    if output_path is not None:
        _write_once(
            Path(output_path),
            (canonical_json(audit) + "\n").encode("utf-8"),
        )
    return audit


def _audit_memory_transition(
    *,
    final: AdaptiveResearchLoopSnapshot,
    event_index: int,
    run_root: Path,
    raw_memory_store: RawMemoryStore,
) -> AdaptiveMemoryTransportEvidence:
    event = final.events[event_index]
    next_event = final.events[event_index + 1]
    relative_path = _selection_relative_path(event.feedback.artifact_refs)
    selection_path = (run_root / relative_path).resolve()
    if not selection_path.is_relative_to(run_root.resolve()):
        raise AdaptiveMemoryLoopAuditError("memory selection path escapes run root")
    selection = SovereignRecallSelection.model_validate_json(
        selection_path.read_bytes()
    )
    if selection.loop_id != final.seed.loop_id or selection.project_id != final.seed.project_id:
        raise AdaptiveMemoryLoopAuditError("memory selection belongs to another loop")
    proposal = event.interaction.proposal
    if (
        selection.step_index != event.step_index
        or selection.branch_id != event.branch_id
        or selection.proposal_hash != canonical_sha256(proposal)
    ):
        raise AdaptiveMemoryLoopAuditError("memory selection action binding mismatch")
    predecessor_path = run_root / "snapshots" / (
        f"step-{event.step_index - 1:04d}-{selection.snapshot_hash}.json"
    )
    predecessor = load_adaptive_research_loop_snapshot(
        predecessor_path,
        raw_memory_store=raw_memory_store,
    )
    if predecessor.events != final.events[:event_index]:
        raise AdaptiveMemoryLoopAuditError("memory selection predecessor is not exact prefix")
    replayed_selection = SovereignRawRecallEngine(
        raw_memory_store=raw_memory_store,
        maximum_selected_records=selection.maximum_selected_records,
        maximum_excerpt_characters=selection.maximum_excerpt_characters,
        maximum_total_excerpt_characters=(
            selection.maximum_total_excerpt_characters
        ),
    ).recall(
        snapshot=predecessor,
        proposal=proposal,
    )
    if replayed_selection != selection:
        raise AdaptiveMemoryLoopAuditError(
            "memory selection does not replay from its predecessor and raw bytes"
        )
    selected_bindings = [item.binding for item in selection.selected_excerpts]
    raw_replayed = all(
        _binding_replays(
            binding,
            store=raw_memory_store,
            project_id=final.seed.project_id,
        )
        for binding in selected_bindings
    )
    expected_findings = recall_findings_cn(selection)
    feedback_matches = event.feedback.findings_cn == expected_findings
    artifact_bound = (
        f"artifact:{selection.selection_hash}" in event.feedback.artifact_refs
    )
    next_task = _task_payload(next_event.interaction.messages)
    recent = next_task.get("recent_external_feedback")
    exposed = isinstance(recent, list) and any(
        isinstance(item, dict)
        and item.get("step_index") == event.step_index
        and item.get("feedback_summary_cn") == event.feedback.summary_cn
        and item.get("feedback_findings_cn") == expected_findings
        for item in recent
    )
    recent_record_ids = _recent_event_record_ids(predecessor)
    old_count = sum(
        binding.record_id != predecessor.seed.raw_seed_binding.record_id
        and binding.record_id not in recent_record_ids
        for binding in selected_bindings
    )
    return AdaptiveMemoryTransportEvidence(
        dreaming_step_index=event.step_index,
        next_step_index=next_event.step_index,
        branch_id=event.branch_id,
        selection_relative_path=relative_path.as_posix(),
        selection_hash=selection.selection_hash,
        selection_snapshot_hash=selection.snapshot_hash,
        candidate_record_count=selection.candidate_record_count,
        selected_record_ids=[binding.record_id for binding in selected_bindings],
        selected_record_count=len(selected_bindings),
        selected_older_than_eight_events_count=old_count,
        privacy_excluded_record_count=selection.privacy_excluded_record_count,
        all_selected_raw_bindings_replayed=raw_replayed,
        dreaming_feedback_matches_selection=feedback_matches,
        selection_artifact_bound_to_feedback=artifact_bound,
        exact_feedback_exposed_to_next_model=exposed,
        next_action_model_authored=(
            next_event.interaction.proposal.scientific_content_generated_by_model
            and next_event.scientific_content_authored_by_model
        ),
        no_post_start_human_scientific_prose=(
            next_event.interaction.hand_written_scientific_prose_count
            + next_event.interaction.proposal.human_authored_scientific_prose_count
            + next_event.orchestrator_scientific_prose_count
            == 0
        ),
    )


def _selection_relative_path(artifact_refs: Sequence[str]) -> PurePosixPath:
    matches = [
        reference.removeprefix("artifact-path:")
        for reference in artifact_refs
        if reference.startswith("artifact-path:")
        and reference.endswith("sovereign-recall-selection.json")
    ]
    if len(matches) != 1:
        raise AdaptiveMemoryLoopAuditError(
            "Dreaming feedback must bind exactly one sovereign recall selection"
        )
    value = matches[0].replace("\\", "/")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or ":" in value:
        raise AdaptiveMemoryLoopAuditError("memory selection reference is unsafe")
    return path


def _binding_replays(
    binding: RawMemoryBinding,
    *,
    store: RawMemoryStore,
    project_id: str,
) -> bool:
    capture = store.load_record(
        binding.record_relative_path,
        project_id=project_id,
    )
    return capture.binding(store.vault_root) == binding


def _recent_event_record_ids(snapshot: AdaptiveResearchLoopSnapshot) -> set[str]:
    record_ids: set[str] = set()
    for event in snapshot.events[-_RECENT_EVENT_WINDOW:]:
        record_ids.update(
            context.raw_binding.record_id
            for context in event.interaction.external_turn_contexts
        )
        record_ids.add(event.interaction.response_binding.record_id)
        record_ids.update(
            attempt.response_binding.record_id
            for attempt in event.interaction.rejected_attempts
        )
        record_ids.add(event.event_payload_binding.record_id)
    return record_ids


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
    raise AdaptiveMemoryLoopAuditError("next action task payload is absent")


def _write_once(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
    except FileExistsError:
        if path.read_bytes() != payload:
            raise AdaptiveMemoryLoopAuditError(
                f"immutable memory-loop audit changed: {path}"
            ) from None


__all__ = [
    "AdaptiveMemoryLoopAudit",
    "AdaptiveMemoryLoopAuditError",
    "AdaptiveMemoryTransportEvidence",
    "audit_adaptive_memory_loop",
]
