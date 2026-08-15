"""Persistent coordinator for small, continual research-loop steps.

This module deliberately coordinates the existing scheduler, heartbeat, raw-memory,
task-context, and controlled-evolution contracts.  It does not implement a second
scientific executor.  A caller supplies the executor for one claimed task, and the
harness supplies durable queueing, leases, idempotent terminal transitions, and the
boundary between active and completed task context.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field, field_validator, model_validator

from autoresearch.experiments.promotion import promote_strategy_to_gray_release
from autoresearch.experiments.shadow import run_shadow_evaluation
from autoresearch.experiments.strategy_rollback import evaluate_strategy_rollback
from autoresearch.kernel.contracts import KernelContract, canonical_json, canonical_sha256
from autoresearch.knowledge.raw_memory import (
    RawMemoryBinding,
    RawMemoryCapture,
    RawMemoryStore,
)
from autoresearch.llm.client import LLMJsonCompletionResult
from autoresearch.llm.task_context import (
    ActiveTaskConversation,
    CompletedTaskConversation,
    capture_completed_task_conversation,
)
from autoresearch.runtime.heartbeat import write_runtime_heartbeat
from autoresearch.scheduler import LocalScheduler, queued_task

_GENESIS_HASH = "0" * 64
_DEFAULT_CLAIM_TTL_SECONDS = 900
_DEFAULT_LOCK_TIMEOUT_SECONDS = 10.0
_DEFAULT_STALE_LOCK_SECONDS = 300.0


class ContinualHarnessError(RuntimeError):
    """Base failure raised by the continual coordinator."""


class ContinualHarnessIntegrityError(ContinualHarnessError):
    """The append-only state journal is malformed or hash-inconsistent."""


class ContinualHarnessTransitionError(ContinualHarnessError):
    """A requested task transition is not valid for the durable current state."""


class ResearchGoalStatus(str, Enum):
    """Derived lifecycle status for a persistent research goal."""

    ACTIVE = "active"
    NEEDS_REFINEMENT = "needs_refinement"
    COMPLETED = "completed"


class ResearchTaskStatus(str, Enum):
    """Durable states for one research task."""

    QUEUED = "queued"
    CLAIMED = "claimed"
    FORMAT_REPAIR = "format_repair"
    OPERATIONAL_WAIT = "operational_wait"
    SCIENTIFIC_FAILED = "scientific_failed"
    COMPLETED = "completed"


class ResearchFailureKind(str, Enum):
    """Failures kept separate so formatting never becomes scientific evidence."""

    FORMAT = "format"
    OPERATIONAL = "operational"
    SCIENTIFIC = "scientific"


class EvolutionProposalStatus(str, Enum):
    """Only the fail-closed state is created automatically by this harness."""

    PENDING_SHADOW = "pending_shadow"


class HarnessEventType(str, Enum):
    """Append-only journal event types."""

    GOAL_ADDED = "goal_added"
    TASK_ENQUEUED = "task_enqueued"
    TASK_CLAIMED = "task_claimed"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"


class ResearchGoal(KernelContract):
    """One durable goal supplied to the autonomous research loop."""

    goal_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    objective_cn: str = Field(min_length=1, max_length=100_000)
    created_at: datetime
    status: ResearchGoalStatus = ResearchGoalStatus.ACTIVE


class ResearchTaskSeed(KernelContract):
    """Exact task input retained until and after execution."""

    goal_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    task_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    conversation_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    task_sequence: int = Field(ge=1)
    task_text_cn: str = Field(min_length=1, max_length=200_000)
    request_messages: tuple[dict[str, str], ...] = Field(min_length=1)
    enqueued_at: datetime
    execution_key: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def _validate_active_task_shape(self) -> ResearchTaskSeed:
        active = ActiveTaskConversation.create(
            conversation_id=self.conversation_id,
            task_id=self.task_id,
            task_sequence=self.task_sequence,
            request_messages=self.request_messages,
        )
        if active.request_messages != self.request_messages:
            raise ValueError("request_messages are not in canonical active-task form")
        expected = canonical_sha256(
            {
                "goal_id": self.goal_id,
                "task_id": self.task_id,
                "conversation_id": self.conversation_id,
            }
        )
        if self.execution_key != expected:
            raise ValueError("execution_key is not bound to goal/task/conversation")
        return self


class ResearchTaskClaim(KernelContract):
    """A time-bounded claim that must exist before any executor is called."""

    claim_id: str = Field(min_length=1, pattern=r"^claim_[a-f0-9]{32}$")
    worker_id: str = Field(min_length=1, max_length=256)
    task: ResearchTaskSeed
    claimed_at: datetime
    expires_at: datetime
    attempt: int = Field(ge=1)
    supersedes_claim_id: str | None = None

    @model_validator(mode="after")
    def _validate_lease(self) -> ResearchTaskClaim:
        if self.expires_at <= self.claimed_at:
            raise ValueError("claim expiry must be after claim time")
        return self


class ResearchTaskFailure(KernelContract):
    """Idempotent failure record for exactly one claim."""

    claim_id: str
    task_id: str
    kind: ResearchFailureKind
    message_cn: str = Field(min_length=1, max_length=100_000)
    occurred_at: datetime
    counts_as_scientific_failure: bool
    retry_after: datetime | None = None

    @model_validator(mode="after")
    def _bind_failure_semantics(self) -> ResearchTaskFailure:
        expected = self.kind is ResearchFailureKind.SCIENTIFIC
        if self.counts_as_scientific_failure is not expected:
            raise ValueError("failure kind and scientific-failure flag disagree")
        if self.kind is not ResearchFailureKind.OPERATIONAL and self.retry_after is not None:
            raise ValueError("only an operational failure may carry retry_after")
        return self


class VerifiedArtifactBinding(KernelContract):
    """Exact raw-memory binding for one externally verified task artifact."""

    artifact_kind: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9._-]*$")
    source_relative_path: str = Field(min_length=1, max_length=2048)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    raw_binding: RawMemoryBinding

    @field_validator("source_relative_path")
    @classmethod
    def _safe_relative_path(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or value.startswith(("/", "\\")):
            raise ValueError("artifact source path must be a safe relative path")
        return path.as_posix()

    @model_validator(mode="after")
    def _bind_source_bytes(self) -> VerifiedArtifactBinding:
        if self.source_sha256 != self.raw_binding.payload_sha256:
            raise ValueError("artifact source hash differs from raw-memory payload")
        return self


class VerifiedModelReceiptProjection(KernelContract):
    """Credential-free projection of one already verified model-authorship receipt."""

    receipt_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    receipt_artifact: VerifiedArtifactBinding
    messages: tuple[dict[str, str], ...] = Field(min_length=1)
    messages_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    provider: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    endpoint: str = Field(min_length=1)
    response_text: str
    response_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    parsed_payload: dict[str, Any]
    parsed_payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    usage: dict[str, Any]
    reasoning_content: str | None = None
    reasoning_transport: str = Field(min_length=1)

    @model_validator(mode="after")
    def _verify_projection(self) -> VerifiedModelReceiptProjection:
        if self.receipt_artifact.artifact_kind != "model_authorship_receipt":
            raise ValueError("final model receipt requires a model_authorship_receipt artifact")
        normalized = ActiveTaskConversation.create(
            conversation_id="receipt-projection",
            task_id="receipt-projection",
            task_sequence=1,
            request_messages=self.messages,
        )
        if normalized.request_messages != self.messages:
            raise ValueError("model receipt messages are not canonical")
        if self.messages_sha256 != canonical_sha256({"messages": list(self.messages)}):
            raise ValueError("model receipt messages hash mismatch")
        if self.response_sha256 != hashlib.sha256(self.response_text.encode("utf-8")).hexdigest():
            raise ValueError("model receipt response hash mismatch")
        if self.parsed_payload_sha256 != canonical_sha256(self.parsed_payload):
            raise ValueError("model receipt parsed payload hash mismatch")
        return self


class ArtifactCompletionEnvelope(KernelContract):
    """Verified multi-artifact success from an existing non-LLM stage executor."""

    schema_version: Literal["artifact-completion-envelope-v1"] = "artifact-completion-envelope-v1"
    final_model_receipt: VerifiedModelReceiptProjection
    artifacts: tuple[VerifiedArtifactBinding, ...] = Field(min_length=1)
    stage_report: dict[str, Any]
    completed_at: datetime
    envelope_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def _verify_envelope(self) -> ArtifactCompletionEnvelope:
        record_ids = tuple(item.raw_binding.record_id for item in self.artifacts)
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("artifact completion contains duplicate raw records")
        final_id = self.final_model_receipt.receipt_artifact.raw_binding.record_id
        if final_id not in record_ids:
            raise ValueError("final model receipt is absent from completion artifacts")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"envelope_hash"}))
        if self.envelope_hash != expected:
            raise ValueError("artifact completion envelope hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        final_model_receipt: VerifiedModelReceiptProjection,
        artifacts: Sequence[VerifiedArtifactBinding],
        stage_report: Mapping[str, Any],
        completed_at: datetime,
    ) -> ArtifactCompletionEnvelope:
        payload = {
            "schema_version": "artifact-completion-envelope-v1",
            "final_model_receipt": final_model_receipt.model_dump(mode="json"),
            "artifacts": [item.model_dump(mode="json") for item in artifacts],
            "stage_report": dict(stage_report),
            "completed_at": _normalize_datetime(completed_at).isoformat().replace("+00:00", "Z"),
        }
        payload["envelope_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)


class ExistingEvolutionBindings(KernelContract):
    """References to existing guarded evolution APIs; no automatic invocation."""

    shadow_evaluation: str
    gray_promotion: str
    automatic_rollback: str


_EVOLUTION_BINDINGS = ExistingEvolutionBindings(
    shadow_evaluation=(f"{run_shadow_evaluation.__module__}.{run_shadow_evaluation.__name__}"),
    gray_promotion=(
        f"{promote_strategy_to_gray_release.__module__}."
        f"{promote_strategy_to_gray_release.__name__}"
    ),
    automatic_rollback=(
        f"{evaluate_strategy_rollback.__module__}.{evaluate_strategy_rollback.__name__}"
    ),
)


class LocalRefinementProposal(KernelContract):
    """Task-local proposal that cannot bypass shadow or mutate protected policy."""

    proposal_id: str = Field(min_length=1, pattern=r"^proposal_[a-f0-9]{64}$")
    goal_id: str
    task_id: str
    source_claim_id: str
    failure_message_cn: str
    allowed_change_scope: Literal["task_local_method_or_strategy"] = "task_local_method_or_strategy"
    protected_scopes: tuple[str, ...] = (
        "safety_policy",
        "permission_policy",
        "citation_policy",
        "publication_policy",
    )
    policy_mutation_allowed: Literal[False] = False
    status: Literal[EvolutionProposalStatus.PENDING_SHADOW] = EvolutionProposalStatus.PENDING_SHADOW
    bindings: ExistingEvolutionBindings = _EVOLUTION_BINDINGS
    pending_reason_cn: str = (
        "失败记录不足以安全构造策略卡、回放样例、金集结果和人工批准；候选仅登记，"
        "必须由现有影子评估、晋级与回滚流程继续处理。"
    )
    created_at: datetime


class ResearchTaskRecord(KernelContract):
    """Current state reconstructed from the append-only event journal."""

    task: ResearchTaskSeed
    status: ResearchTaskStatus
    claim: ResearchTaskClaim | None = None
    completed_conversation: CompletedTaskConversation | None = None
    artifact_completion: ArtifactCompletionEnvelope | None = None
    last_failure: ResearchTaskFailure | None = None
    refinement_proposal: LocalRefinementProposal | None = None
    claim_count: int = 0
    format_failure_count: int = 0


class ContinualResearchSnapshot(KernelContract):
    """Deterministic projection rebuilt from all valid journal events."""

    goals: tuple[ResearchGoal, ...]
    tasks: tuple[ResearchTaskRecord, ...]
    proposals: tuple[LocalRefinementProposal, ...]
    event_count: int
    journal_head_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ContinualResearchJournalEvent(KernelContract):
    """One hash-chained append-only state transition."""

    schema_version: Literal["continual-research-event-v1"] = "continual-research-event-v1"
    sequence: int = Field(ge=1)
    event_id: str = Field(min_length=1)
    event_type: HarnessEventType
    occurred_at: datetime
    payload: dict[str, Any]
    previous_event_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    event_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def _verify_event_hash(self) -> ContinualResearchJournalEvent:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"event_sha256"}))
        if self.event_sha256 != expected:
            raise ValueError("journal event hash mismatch")
        return self


@dataclass(frozen=True)
class TaskExecutionResult:
    """Typed handoff returned by an existing scientific executor."""

    completion: LLMJsonCompletionResult | None = None
    artifact_completion: ArtifactCompletionEnvelope | None = None
    failure_kind: ResearchFailureKind | None = None
    failure_message_cn: str | None = None
    retry_after: datetime | None = None

    def __post_init__(self) -> None:
        successes = sum(item is not None for item in (self.completion, self.artifact_completion))
        failure = self.failure_kind is not None and bool(
            self.failure_message_cn and self.failure_message_cn.strip()
        )
        if successes + int(failure) != 1:
            raise ValueError("execution result must contain exactly one success or failure")
        if (
            self.failure_kind is not ResearchFailureKind.OPERATIONAL
            and self.retry_after is not None
        ):
            raise ValueError("only operational execution failure may carry retry_after")

    @classmethod
    def succeeded(cls, completion: LLMJsonCompletionResult) -> TaskExecutionResult:
        return cls(completion=completion)

    @classmethod
    def succeeded_with_artifacts(
        cls,
        completion: ArtifactCompletionEnvelope,
    ) -> TaskExecutionResult:
        return cls(artifact_completion=completion)

    @classmethod
    def failed(
        cls,
        kind: ResearchFailureKind,
        message_cn: str,
        *,
        retry_after: datetime | None = None,
    ) -> TaskExecutionResult:
        return cls(
            failure_kind=kind,
            failure_message_cn=message_cn,
            retry_after=retry_after,
        )


TaskExecutor = Callable[[ResearchTaskClaim], TaskExecutionResult]


class ContinualResearchHarness:
    """Durable goal/task coordinator layered over existing project capabilities."""

    def __init__(
        self,
        *,
        journal_path: Path | str,
        heartbeat_path: Path | str,
        vault_root: Path | str,
        project_id: str,
        conversation_id: str,
        claim_ttl_seconds: int = _DEFAULT_CLAIM_TTL_SECONDS,
        max_format_repair_attempts: int = 3,
        lock_timeout_seconds: float = _DEFAULT_LOCK_TIMEOUT_SECONDS,
    ) -> None:
        self.journal_path = Path(journal_path)
        self.heartbeat_path = Path(heartbeat_path)
        self.raw_memory_store = RawMemoryStore(vault_root)
        self.project_id = project_id
        self.conversation_id = conversation_id
        self.claim_ttl_seconds = max(int(claim_ttl_seconds), 1)
        self.max_format_repair_attempts = max(int(max_format_repair_attempts), 0)
        self.lock_timeout_seconds = max(float(lock_timeout_seconds), 0.01)
        # Replaying on construction fails closed before this object can coordinate work.
        self.snapshot()

    def ensure_goal(
        self,
        *,
        goal_id: str,
        objective_cn: str,
        created_at: datetime | None = None,
    ) -> ResearchGoal:
        """Persist a goal once; an incompatible duplicate is rejected."""

        now = _normalize_datetime(created_at)
        candidate = ResearchGoal(
            goal_id=goal_id,
            objective_cn=objective_cn.strip(),
            created_at=now,
        )
        with self._locked():
            snapshot = self.snapshot()
            existing = _goal_from_snapshot(snapshot, goal_id)
            if existing is not None:
                if existing.objective_cn != candidate.objective_cn:
                    raise ContinualHarnessTransitionError(
                        f"goal {goal_id!r} already exists with another objective"
                    )
                return existing
            self._append_event_unlocked(
                event_id=f"goal:{goal_id}",
                event_type=HarnessEventType.GOAL_ADDED,
                payload=candidate.model_dump(mode="json"),
                occurred_at=now,
            )
        return candidate

    def enqueue_task(
        self,
        *,
        goal_id: str,
        task_id: str,
        task_text_cn: str,
        request_messages: Sequence[Mapping[str, str]] | None = None,
        enqueued_at: datetime | None = None,
    ) -> ResearchTaskSeed:
        """Append a task with its exact current input; never summarize it here."""

        now = _normalize_datetime(enqueued_at)
        with self._locked():
            snapshot = self.snapshot()
            if _goal_from_snapshot(snapshot, goal_id) is None:
                raise ContinualHarnessTransitionError(f"unknown goal: {goal_id}")
            existing = _task_from_snapshot(snapshot, task_id)
            normalized_messages = request_messages or ({"role": "user", "content": task_text_cn},)
            task_sequence = 1 + max(
                (record.task.task_sequence for record in snapshot.tasks),
                default=0,
            )
            active = ActiveTaskConversation.create(
                conversation_id=self.conversation_id,
                task_id=task_id,
                task_sequence=task_sequence,
                request_messages=normalized_messages,
            )
            candidate = ResearchTaskSeed(
                goal_id=goal_id,
                task_id=task_id,
                conversation_id=self.conversation_id,
                task_sequence=task_sequence,
                task_text_cn=task_text_cn.strip(),
                request_messages=active.request_messages,
                enqueued_at=now,
                execution_key=canonical_sha256(
                    {
                        "goal_id": goal_id,
                        "task_id": task_id,
                        "conversation_id": self.conversation_id,
                    }
                ),
            )
            if existing is not None:
                comparable = existing.task.model_copy(
                    update={"task_sequence": candidate.task_sequence, "enqueued_at": now}
                )
                candidate_comparable = candidate.model_copy(
                    update={
                        "task_sequence": comparable.task_sequence,
                        "enqueued_at": comparable.enqueued_at,
                    }
                )
                if comparable != candidate_comparable:
                    raise ContinualHarnessTransitionError(
                        f"task {task_id!r} already exists with another input"
                    )
                return existing.task
            self._append_event_unlocked(
                event_id=f"task:{task_id}",
                event_type=HarnessEventType.TASK_ENQUEUED,
                payload=candidate.model_dump(mode="json"),
                occurred_at=now,
            )
        return candidate

    def claim_next(
        self,
        *,
        worker_id: str,
        claimed_at: datetime | None = None,
    ) -> ResearchTaskClaim | None:
        """Claim the next eligible task before execution, with lease recovery."""

        now = _normalize_datetime(claimed_at)
        with self._locked():
            snapshot = self.snapshot()
            for record in snapshot.tasks:
                claim = record.claim
                if (
                    record.status is ResearchTaskStatus.CLAIMED
                    and claim is not None
                    and claim.worker_id == worker_id
                    and claim.expires_at > now
                ):
                    return claim
            eligible = [record for record in snapshot.tasks if self._is_claimable(record, now=now)]
            if not eligible:
                return None
            record = min(
                eligible,
                key=lambda item: (item.task.task_sequence, item.task.task_id),
            )
            previous_claim = record.claim
            claim = ResearchTaskClaim(
                claim_id=f"claim_{uuid4().hex}",
                worker_id=worker_id.strip(),
                task=record.task,
                claimed_at=now,
                expires_at=now + timedelta(seconds=self.claim_ttl_seconds),
                attempt=record.claim_count + 1,
                supersedes_claim_id=(
                    previous_claim.claim_id if previous_claim is not None else None
                ),
            )
            self._append_event_unlocked(
                event_id=claim.claim_id,
                event_type=HarnessEventType.TASK_CLAIMED,
                payload=claim.model_dump(mode="json"),
                occurred_at=now,
            )
        self._heartbeat(
            run_id=claim.task.goal_id,
            stage="task_claimed",
            progress=f"{claim.task.task_id}:{claim.attempt}",
            message=f"已认领任务 {claim.task.task_id}",
        )
        return claim

    def complete_task(
        self,
        *,
        claim: ResearchTaskClaim,
        completion: LLMJsonCompletionResult,
        completed_at: datetime | None = None,
    ) -> CompletedTaskConversation:
        """Capture exact completed dialogue, then append one terminal event."""

        now = _normalize_datetime(completed_at)
        with self._locked():
            snapshot = self.snapshot()
            record = _require_task(snapshot, claim.task.task_id)
            if record.completed_conversation is not None:
                if record.claim is None or record.claim.claim_id != claim.claim_id:
                    raise ContinualHarnessTransitionError("task was completed by another claim")
                if record.artifact_completion is not None:
                    raise ContinualHarnessTransitionError(
                        "task already completed with an artifact envelope"
                    )
                return record.completed_conversation
            self._require_current_claim(record, claim)
            captured = capture_completed_task_conversation(
                raw_memory_store=self.raw_memory_store,
                project_id=self.project_id,
                conversation_id=record.task.conversation_id,
                task_id=record.task.task_id,
                task_sequence=record.task.task_sequence,
                request_messages=record.task.request_messages,
                completion=completion,
                # Stable per claim, so a repeated terminal call is content-identical.
                captured_at=claim.claimed_at,
            )
            self._append_event_unlocked(
                event_id=f"complete:{claim.claim_id}",
                event_type=HarnessEventType.TASK_COMPLETED,
                payload={
                    "claim_id": claim.claim_id,
                    "task_id": record.task.task_id,
                    "completed_conversation": captured.model_dump(mode="json"),
                    "artifact_completion": None,
                },
                occurred_at=now,
            )
        self._heartbeat(
            run_id=claim.task.goal_id,
            stage="task_completed",
            progress=f"{claim.task.task_id}:{captured.task_hash}",
            message=f"任务 {claim.task.task_id} 已完成并写入原始记忆",
            artifact_refs=(captured.raw_binding.record_relative_path,),
        )
        return captured

    def complete_artifact_task(
        self,
        *,
        claim: ResearchTaskClaim,
        completion: ArtifactCompletionEnvelope,
        completed_at: datetime | None = None,
    ) -> CompletedTaskConversation:
        """Complete a multi-artifact task from exact verified raw-memory bindings."""

        now = _normalize_datetime(completed_at)
        with self._locked():
            snapshot = self.snapshot()
            record = _require_task(snapshot, claim.task.task_id)
            if record.completed_conversation is not None:
                if record.claim is None or record.claim.claim_id != claim.claim_id:
                    raise ContinualHarnessTransitionError("task was completed by another claim")
                existing = record.artifact_completion
                if existing is None or existing.envelope_hash != completion.envelope_hash:
                    raise ContinualHarnessTransitionError(
                        "claim already has a different completion result"
                    )
                return record.completed_conversation
            self._require_current_claim(record, claim)
            for artifact in completion.artifacts:
                self._verify_artifact_binding(artifact)
            self._verify_model_receipt_projection(completion.final_model_receipt)
            captured = _completed_conversation_from_artifact(
                task=record.task,
                completion=completion,
            )
            self._append_event_unlocked(
                event_id=f"complete:{claim.claim_id}",
                event_type=HarnessEventType.TASK_COMPLETED,
                payload={
                    "claim_id": claim.claim_id,
                    "task_id": record.task.task_id,
                    "completed_conversation": captured.model_dump(mode="json"),
                    "artifact_completion": completion.model_dump(mode="json"),
                },
                occurred_at=now,
            )
        artifact_refs = tuple(
            item.raw_binding.record_relative_path for item in completion.artifacts
        )
        self._heartbeat(
            run_id=claim.task.goal_id,
            stage="artifact_task_completed",
            progress=f"{claim.task.task_id}:{completion.envelope_hash}",
            message=f"任务 {claim.task.task_id} 的已验证制品已写入原始记忆",
            artifact_refs=artifact_refs,
        )
        return captured

    def fail_task(
        self,
        *,
        claim: ResearchTaskClaim,
        kind: ResearchFailureKind,
        message_cn: str,
        failed_at: datetime | None = None,
        retry_after: datetime | None = None,
    ) -> ResearchTaskFailure:
        """Append a format or scientific failure without conflating the two."""

        now = _normalize_datetime(failed_at)
        with self._locked():
            snapshot = self.snapshot()
            record = _require_task(snapshot, claim.task.task_id)
            if record.last_failure is not None and record.last_failure.claim_id == claim.claim_id:
                normalized_retry = (
                    _normalize_datetime(retry_after) if retry_after is not None else None
                )
                expected = (kind, message_cn.strip(), normalized_retry)
                actual = (
                    record.last_failure.kind,
                    record.last_failure.message_cn,
                    record.last_failure.retry_after,
                )
                if actual != expected:
                    raise ContinualHarnessTransitionError(
                        "claim already has a different failure result"
                    )
                return record.last_failure
            self._require_current_claim(record, claim)
            failure = ResearchTaskFailure(
                claim_id=claim.claim_id,
                task_id=record.task.task_id,
                kind=kind,
                message_cn=message_cn.strip(),
                occurred_at=now,
                counts_as_scientific_failure=kind is ResearchFailureKind.SCIENTIFIC,
                retry_after=(_normalize_datetime(retry_after) if retry_after is not None else None),
            )
            proposal = (
                _refinement_proposal(record.task, failure, created_at=now)
                if kind is ResearchFailureKind.SCIENTIFIC
                else None
            )
            self._append_event_unlocked(
                event_id=f"fail:{claim.claim_id}",
                event_type=HarnessEventType.TASK_FAILED,
                payload={
                    "failure": failure.model_dump(mode="json"),
                    "refinement_proposal": (
                        proposal.model_dump(mode="json") if proposal is not None else None
                    ),
                },
                occurred_at=now,
            )
        stage = {
            ResearchFailureKind.FORMAT: "format_repair",
            ResearchFailureKind.OPERATIONAL: "operational_wait",
            ResearchFailureKind.SCIENTIFIC: "scientific_failure",
        }[failure.kind]
        self._heartbeat(
            run_id=claim.task.goal_id,
            stage=stage,
            progress=f"{claim.task.task_id}:{claim.claim_id}",
            message=failure.message_cn,
        )
        return failure

    def run_once(
        self,
        *,
        worker_id: str,
        executor: TaskExecutor,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Run one externally implemented executor step after a durable claim."""

        timestamp = _normalize_datetime(now)
        claim = self.claim_next(worker_id=worker_id, claimed_at=timestamp)
        if claim is None:
            self._heartbeat(
                run_id=self.project_id,
                stage="queue_idle",
                progress="no_claimable_task",
                message="当前没有可认领任务",
            )
            return {"status": "idle"}
        result = executor(claim)
        if result.completion is not None:
            completed = self.complete_task(
                claim=claim,
                completion=result.completion,
                completed_at=timestamp,
            )
            return {
                "status": ResearchTaskStatus.COMPLETED.value,
                "task_id": claim.task.task_id,
                "task_hash": completed.task_hash,
                "execution_key": claim.task.execution_key,
            }
        if result.artifact_completion is not None:
            completed = self.complete_artifact_task(
                claim=claim,
                completion=result.artifact_completion,
                completed_at=timestamp,
            )
            return {
                "status": ResearchTaskStatus.COMPLETED.value,
                "task_id": claim.task.task_id,
                "task_hash": completed.task_hash,
                "artifact_envelope_hash": result.artifact_completion.envelope_hash,
                "execution_key": claim.task.execution_key,
            }
        assert result.failure_kind is not None
        assert result.failure_message_cn is not None
        failure = self.fail_task(
            claim=claim,
            kind=result.failure_kind,
            message_cn=result.failure_message_cn,
            failed_at=timestamp,
            retry_after=result.retry_after,
        )
        return {
            "status": {
                ResearchFailureKind.FORMAT: ResearchTaskStatus.FORMAT_REPAIR.value,
                ResearchFailureKind.OPERATIONAL: (ResearchTaskStatus.OPERATIONAL_WAIT.value),
                ResearchFailureKind.SCIENTIFIC: (ResearchTaskStatus.SCIENTIFIC_FAILED.value),
            }[failure.kind],
            "task_id": claim.task.task_id,
            "failure_kind": failure.kind.value,
            "execution_key": claim.task.execution_key,
        }

    def schedule_once(
        self,
        *,
        scheduler: LocalScheduler,
        scheduler_task_id: str,
        worker_id: str,
        executor: TaskExecutor,
        run_at: datetime | None = None,
    ) -> None:
        """Register one existing-scheduler step over the persistent queue."""

        timestamp = _normalize_datetime(run_at)
        scheduler.add_task(
            queued_task(
                task_id=scheduler_task_id,
                name="continual research queue step",
                queued_at=timestamp,
                action=lambda: self.run_once(
                    worker_id=worker_id,
                    executor=executor,
                    # The due time selects scheduling; the lease must start at
                    # actual execution, which may be later after process resume.
                    now=None,
                ),
            )
        )

    def snapshot(self) -> ContinualResearchSnapshot:
        """Rebuild current state from the verified append-only journal."""

        return _replay(self._load_events())

    def list_tasks(self) -> tuple[ResearchTaskRecord, ...]:
        """Return the persistent task queue in stable sequence order."""

        return self.snapshot().tasks

    def get_task(self, task_id: str) -> ResearchTaskRecord:
        """Return one reconstructed task record."""

        return _require_task(self.snapshot(), task_id)

    def completed_task_records(self) -> tuple[CompletedTaskConversation, ...]:
        """Expose only completed records to the existing task-context compressor."""

        return tuple(
            record.completed_conversation
            for record in self.snapshot().tasks
            if record.status is ResearchTaskStatus.COMPLETED
            and record.completed_conversation is not None
        )

    def _is_claimable(self, record: ResearchTaskRecord, *, now: datetime) -> bool:
        if record.status is ResearchTaskStatus.QUEUED:
            return True
        if record.status is ResearchTaskStatus.FORMAT_REPAIR:
            return record.format_failure_count < self.max_format_repair_attempts
        if record.status is ResearchTaskStatus.OPERATIONAL_WAIT:
            return (
                record.last_failure is not None
                and record.last_failure.kind is ResearchFailureKind.OPERATIONAL
                and record.last_failure.retry_after is not None
                and record.last_failure.retry_after <= now
            )
        return (
            record.status is ResearchTaskStatus.CLAIMED
            and record.claim is not None
            and record.claim.expires_at <= now
        )

    @staticmethod
    def _require_current_claim(
        record: ResearchTaskRecord,
        claim: ResearchTaskClaim,
    ) -> None:
        if (
            record.status is not ResearchTaskStatus.CLAIMED
            or record.claim is None
            or record.claim.claim_id != claim.claim_id
        ):
            raise ContinualHarnessTransitionError("claim is stale or not current")

    def _verify_artifact_binding(
        self,
        artifact: VerifiedArtifactBinding,
    ) -> RawMemoryCapture:
        capture = self.raw_memory_store.load_record(
            artifact.raw_binding.record_relative_path,
            project_id=self.project_id,
        )
        if capture.binding(self.raw_memory_store.vault_root) != artifact.raw_binding:
            raise ContinualHarnessIntegrityError(
                f"artifact raw-memory binding changed: {artifact.source_relative_path}"
            )
        return capture

    def _verify_model_receipt_projection(
        self,
        receipt: VerifiedModelReceiptProjection,
    ) -> None:
        capture = self._verify_artifact_binding(receipt.receipt_artifact)
        try:
            payload = json.loads(capture.blob_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContinualHarnessIntegrityError(
                "final model receipt raw bytes are not valid JSON"
            ) from exc
        expected = {
            "receipt_hash": receipt.receipt_hash,
            "messages": list(receipt.messages),
            "messages_sha256": receipt.messages_sha256,
            "provider": receipt.provider,
            "base_url": receipt.base_url,
            "model_name": receipt.model_name,
            "endpoint": receipt.endpoint,
            "response_text": receipt.response_text,
            "response_sha256": receipt.response_sha256,
            "parsed_payload": receipt.parsed_payload,
            "parsed_payload_sha256": receipt.parsed_payload_sha256,
            "usage": receipt.usage,
            "reasoning_content": receipt.reasoning_content,
            "reasoning_transport": receipt.reasoning_transport,
        }
        changed = tuple(key for key, value in expected.items() if payload.get(key) != value)
        if changed:
            raise ContinualHarnessIntegrityError(
                f"final model receipt projection differs from raw bytes: {changed}"
            )

    def _heartbeat(
        self,
        *,
        run_id: str,
        stage: str,
        progress: str,
        message: str,
        artifact_refs: tuple[str, ...] = (),
    ) -> None:
        write_runtime_heartbeat(
            state_path=self.heartbeat_path,
            run_id=run_id,
            stage=stage,
            progress=progress,
            message=message,
            artifact_refs=artifact_refs,
        )

    def _load_events(self) -> list[ContinualResearchJournalEvent]:
        if not self.journal_path.exists():
            return []
        events: list[ContinualResearchJournalEvent] = []
        try:
            lines = self.journal_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise ContinualHarnessIntegrityError("cannot read continual journal") from exc
        previous_hash = _GENESIS_HASH
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                raise ContinualHarnessIntegrityError(
                    f"blank continual journal line at {line_number}"
                )
            try:
                event = ContinualResearchJournalEvent.model_validate_json(line)
            except ValueError as exc:
                raise ContinualHarnessIntegrityError(
                    f"invalid continual journal line {line_number}"
                ) from exc
            if event.sequence != line_number:
                raise ContinualHarnessIntegrityError("continual journal sequence gap")
            if event.previous_event_sha256 != previous_hash:
                raise ContinualHarnessIntegrityError("continual journal hash chain mismatch")
            previous_hash = event.event_sha256
            events.append(event)
        if len({event.event_id for event in events}) != len(events):
            raise ContinualHarnessIntegrityError("duplicate continual journal event_id")
        return events

    def _append_event_unlocked(
        self,
        *,
        event_id: str,
        event_type: HarnessEventType,
        payload: dict[str, Any],
        occurred_at: datetime,
    ) -> ContinualResearchJournalEvent:
        events = self._load_events()
        if any(event.event_id == event_id for event in events):
            raise ContinualHarnessTransitionError(f"duplicate event_id: {event_id}")
        event_payload = {
            "schema_version": "continual-research-event-v1",
            "sequence": len(events) + 1,
            "event_id": event_id,
            "event_type": event_type.value,
            "occurred_at": _normalize_datetime(occurred_at).isoformat().replace("+00:00", "Z"),
            "payload": payload,
            "previous_event_sha256": (events[-1].event_sha256 if events else _GENESIS_HASH),
        }
        event_payload["event_sha256"] = canonical_sha256(event_payload)
        event = ContinualResearchJournalEvent.model_validate(event_payload)
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        encoded = (canonical_json(event) + "\n").encode("utf-8")
        descriptor = os.open(
            self.journal_path,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o600,
        )
        try:
            os.write(descriptor, encoded)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return event

    @contextmanager
    def _locked(self) -> Iterator[None]:
        lock_path = self.journal_path.with_suffix(self.journal_path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.lock_timeout_seconds
        descriptor: int | None = None
        while descriptor is None:
            try:
                descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
                os.fsync(descriptor)
            except FileExistsError as exc:
                if _lock_is_stale(lock_path):
                    with suppress(FileNotFoundError):
                        lock_path.unlink()
                    continue
                if time.monotonic() >= deadline:
                    raise ContinualHarnessTransitionError(
                        "timed out acquiring continual journal lock"
                    ) from exc
                time.sleep(0.01)
        try:
            yield
        finally:
            if descriptor is not None:
                os.close(descriptor)
            with suppress(FileNotFoundError):
                lock_path.unlink()


def _replay(events: Sequence[ContinualResearchJournalEvent]) -> ContinualResearchSnapshot:
    goals: dict[str, ResearchGoal] = {}
    tasks: dict[str, ResearchTaskRecord] = {}
    proposals: dict[str, LocalRefinementProposal] = {}
    for event in events:
        if event.event_type is HarnessEventType.GOAL_ADDED:
            goal = ResearchGoal.model_validate(event.payload)
            if goal.goal_id in goals:
                raise ContinualHarnessIntegrityError("journal adds one goal twice")
            goals[goal.goal_id] = goal
            continue
        if event.event_type is HarnessEventType.TASK_ENQUEUED:
            task = ResearchTaskSeed.model_validate(event.payload)
            if task.goal_id not in goals or task.task_id in tasks:
                raise ContinualHarnessIntegrityError("invalid task enqueue relationship")
            tasks[task.task_id] = ResearchTaskRecord(
                task=task,
                status=ResearchTaskStatus.QUEUED,
            )
            continue
        if event.event_type is HarnessEventType.TASK_CLAIMED:
            claim = ResearchTaskClaim.model_validate(event.payload)
            record = _require_replay_task(tasks, claim.task.task_id)
            if claim.task != record.task:
                raise ContinualHarnessIntegrityError("claim task payload changed")
            if record.status in {
                ResearchTaskStatus.COMPLETED,
                ResearchTaskStatus.SCIENTIFIC_FAILED,
            }:
                raise ContinualHarnessIntegrityError("terminal task was reclaimed")
            if record.status is ResearchTaskStatus.OPERATIONAL_WAIT and (
                record.last_failure is None
                or record.last_failure.retry_after is None
                or claim.claimed_at < record.last_failure.retry_after
            ):
                raise ContinualHarnessIntegrityError(
                    "operational task was reclaimed before retry_after"
                )
            tasks[claim.task.task_id] = record.model_copy(
                update={
                    "status": ResearchTaskStatus.CLAIMED,
                    "claim": claim,
                    "claim_count": record.claim_count + 1,
                }
            )
            continue
        if event.event_type is HarnessEventType.TASK_COMPLETED:
            task_id = _required_payload_text(event.payload, "task_id")
            claim_id = _required_payload_text(event.payload, "claim_id")
            record = _require_replay_task(tasks, task_id)
            if (
                record.status is not ResearchTaskStatus.CLAIMED
                or record.claim is None
                or record.claim.claim_id != claim_id
            ):
                raise ContinualHarnessIntegrityError("completion does not match current claim")
            completed = CompletedTaskConversation.model_validate(
                event.payload.get("completed_conversation")
            )
            artifact_payload = event.payload.get("artifact_completion")
            artifact_completion = (
                ArtifactCompletionEnvelope.model_validate(artifact_payload)
                if artifact_payload is not None
                else None
            )
            if completed.task_id != task_id:
                raise ContinualHarnessIntegrityError("completion task_id mismatch")
            if (
                artifact_completion is not None
                and completed.raw_binding
                != artifact_completion.final_model_receipt.receipt_artifact.raw_binding
            ):
                raise ContinualHarnessIntegrityError(
                    "completed conversation is not bound to the final model receipt"
                )
            tasks[task_id] = record.model_copy(
                update={
                    "status": ResearchTaskStatus.COMPLETED,
                    "completed_conversation": completed,
                    "artifact_completion": artifact_completion,
                }
            )
            continue
        if event.event_type is HarnessEventType.TASK_FAILED:
            failure = ResearchTaskFailure.model_validate(event.payload.get("failure"))
            record = _require_replay_task(tasks, failure.task_id)
            if (
                record.status is not ResearchTaskStatus.CLAIMED
                or record.claim is None
                or record.claim.claim_id != failure.claim_id
            ):
                raise ContinualHarnessIntegrityError("failure does not match current claim")
            proposal_payload = event.payload.get("refinement_proposal")
            proposal = (
                LocalRefinementProposal.model_validate(proposal_payload)
                if proposal_payload is not None
                else None
            )
            if (failure.kind is ResearchFailureKind.SCIENTIFIC) != (proposal is not None):
                raise ContinualHarnessIntegrityError(
                    "only scientific failure may create a refinement proposal"
                )
            if proposal is not None:
                proposals[proposal.proposal_id] = proposal
            tasks[failure.task_id] = record.model_copy(
                update={
                    "status": (
                        ResearchTaskStatus.SCIENTIFIC_FAILED
                        if failure.kind is ResearchFailureKind.SCIENTIFIC
                        else (
                            ResearchTaskStatus.OPERATIONAL_WAIT
                            if failure.kind is ResearchFailureKind.OPERATIONAL
                            else ResearchTaskStatus.FORMAT_REPAIR
                        )
                    ),
                    "last_failure": failure,
                    "refinement_proposal": proposal,
                    "format_failure_count": record.format_failure_count
                    + (1 if failure.kind is ResearchFailureKind.FORMAT else 0),
                }
            )

    task_values = tuple(
        sorted(tasks.values(), key=lambda item: (item.task.task_sequence, item.task.task_id))
    )
    for goal_id, goal in tuple(goals.items()):
        goal_tasks = [record for record in task_values if record.task.goal_id == goal_id]
        if goal_tasks and all(
            record.status is ResearchTaskStatus.COMPLETED for record in goal_tasks
        ):
            status = ResearchGoalStatus.COMPLETED
        elif any(record.status is ResearchTaskStatus.SCIENTIFIC_FAILED for record in goal_tasks):
            status = ResearchGoalStatus.NEEDS_REFINEMENT
        else:
            status = ResearchGoalStatus.ACTIVE
        goals[goal_id] = goal.model_copy(update={"status": status})
    return ContinualResearchSnapshot(
        goals=tuple(sorted(goals.values(), key=lambda item: item.goal_id)),
        tasks=task_values,
        proposals=tuple(sorted(proposals.values(), key=lambda item: item.proposal_id)),
        event_count=len(events),
        journal_head_sha256=events[-1].event_sha256 if events else _GENESIS_HASH,
    )


def _completed_conversation_from_artifact(
    *,
    task: ResearchTaskSeed,
    completion: ArtifactCompletionEnvelope,
) -> CompletedTaskConversation:
    """Project an exact final model receipt into the existing context contract."""

    receipt = completion.final_model_receipt
    payload: dict[str, Any] = {
        "schema_version": "completed-task-conversation-v1",
        "conversation_id": task.conversation_id,
        "task_group_id": task.task_id,
        "task_id": task.task_id,
        "task_sequence": task.task_sequence,
        "task_status": "completed",
        "request_messages": list(receipt.messages),
        "response_text": receipt.response_text,
        "reasoning_text": receipt.reasoning_content,
        "usage": receipt.usage,
        "raw_binding": receipt.receipt_artifact.raw_binding.model_dump(mode="json"),
    }
    payload["task_hash"] = canonical_sha256(payload)
    return CompletedTaskConversation.model_validate(payload)


def _refinement_proposal(
    task: ResearchTaskSeed,
    failure: ResearchTaskFailure,
    *,
    created_at: datetime,
) -> LocalRefinementProposal:
    proposal_hash = canonical_sha256(
        {
            "goal_id": task.goal_id,
            "task_id": task.task_id,
            "claim_id": failure.claim_id,
            "failure_kind": failure.kind.value,
            "failure_message_cn": failure.message_cn,
        }
    )
    return LocalRefinementProposal(
        proposal_id=f"proposal_{proposal_hash}",
        goal_id=task.goal_id,
        task_id=task.task_id,
        source_claim_id=failure.claim_id,
        failure_message_cn=failure.message_cn,
        created_at=created_at,
    )


def _goal_from_snapshot(
    snapshot: ContinualResearchSnapshot,
    goal_id: str,
) -> ResearchGoal | None:
    return next((goal for goal in snapshot.goals if goal.goal_id == goal_id), None)


def _task_from_snapshot(
    snapshot: ContinualResearchSnapshot,
    task_id: str,
) -> ResearchTaskRecord | None:
    return next((record for record in snapshot.tasks if record.task.task_id == task_id), None)


def _require_task(
    snapshot: ContinualResearchSnapshot,
    task_id: str,
) -> ResearchTaskRecord:
    record = _task_from_snapshot(snapshot, task_id)
    if record is None:
        raise ContinualHarnessTransitionError(f"unknown task: {task_id}")
    return record


def _require_replay_task(
    tasks: dict[str, ResearchTaskRecord],
    task_id: str,
) -> ResearchTaskRecord:
    try:
        return tasks[task_id]
    except KeyError as exc:
        raise ContinualHarnessIntegrityError(f"journal references unknown task: {task_id}") from exc


def _required_payload_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ContinualHarnessIntegrityError(f"journal payload lacks {key}")
    return value


def _normalize_datetime(value: datetime | None) -> datetime:
    timestamp = value or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return timestamp.astimezone(timezone.utc)


def _lock_is_stale(lock_path: Path) -> bool:
    try:
        age = time.time() - lock_path.stat().st_mtime
    except FileNotFoundError:
        return False
    return age >= _DEFAULT_STALE_LOCK_SECONDS
