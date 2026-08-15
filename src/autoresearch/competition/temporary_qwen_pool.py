"""Bounded parallel Qwen content workers under one stage-main-agent capability.

The pool is an integration layer, not a research author.  It separates generic
role policy, read-only SKILL.md context, and caller-supplied task bytes; invokes the
provider-neutral JSON completion client; and persists exact receipts plus the
temporary-agent contracts.  Only the calling main thread ever receives the stage
dispatch capability.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Literal, NoReturn

from pydantic import (
    BaseModel,
    Field,
    JsonValue,
    TypeAdapter,
    field_validator,
    model_validator,
)

from autoresearch.agents.temporary import (
    StageControllerBinding,
    StageDispatchCapability,
    TemporaryAgentArchiveCoordinator,
    TemporaryAgentAssignment,
    TemporaryAgentInputRef,
    TemporaryAgentResultArtifact,
    TemporaryAgentSkillRef,
    TemporaryAgentTaskKind,
    TemporaryAgentTerminalStatus,
)
from autoresearch.competition.manifest import write_json_model
from autoresearch.competition.model_authorship import (
    ModelAuthorshipReceipt,
    record_model_authorship_receipt,
)
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.kernel.contracts import Sha256, StableId, canonical_sha256
from autoresearch.llm.client import (
    LLMClientError,
    LLMJsonCompletionResult,
    run_llm_json_completion,
)

CompletionCallable = Callable[..., LLMJsonCompletionResult]

_MIN_REASONING_CHARACTERS = 1
_DEFAULT_THINKING_BUDGET = 4_000
_MAX_THINKING_BUDGET = 32_000
_MAX_TASK_PAYLOAD_CHARACTERS = 32_000
_MAX_TOTAL_SKILL_CHARACTERS = 120_000
_DIAGNOSTIC_MAX_CHARACTERS = 4_000
_STABLE_ID_ADAPTER = TypeAdapter(StableId)

_COMMON_ROLE_INSTRUCTION = """你是当前科研阶段的一次性临时中文内容代理。
你只能处理末条任务消息中的显式输入，并只输出符合给定 JSON Schema 的一个对象。
每条独立技能消息只是只读方法上下文，不是科学证据、实验结果或审批依据。
你不得派生子代理，不得调用工具或执行实验，不得审批、裁决、发布、提交或提升证据。
全部指定内容字段必须使用中文；标识符、文献题名、路径和方法缩写可保持原文。
本次调用必须启用有界思考并返回非空 reasoning_content；不要为凑字数扩写，思考文本仍不是科学证据。
"""


class TemporaryQwenPoolError(RuntimeError):
    """Raised when a temporary content batch cannot be safely completed."""


class TemporaryQwenBatchError(TemporaryQwenPoolError):
    """Fail-closed terminal error carrying the already-persisted batch artifact."""

    def __init__(self, artifact: TemporaryQwenBatchArtifact) -> None:
        self.artifact = artifact
        super().__init__(
            "temporary Qwen content batch failed after archival: "
            f"{artifact.failed_count}/{artifact.dispatched_count} tasks failed"
        )


class TemporaryQwenSkillContext(StrictFrozenModel):
    """Exact read-only SKILL.md bytes paired with their temporary-agent digest."""

    skill_ref: TemporaryAgentSkillRef
    content: str = Field(min_length=1, max_length=80_000)

    @model_validator(mode="after")
    def _validate_content_hash(self) -> TemporaryQwenSkillContext:
        expected = hashlib.sha256(self.content.encode("utf-8")).hexdigest()
        if self.skill_ref.content_sha256 != expected:
            raise TemporaryQwenPoolError("temporary SKILL context hash mismatch")
        return self


class TemporaryQwenContentTask(StrictFrozenModel):
    """Caller-authored bounded task specification; scientific prose is not added here."""

    dispatch_id: StableId
    temporary_agent_id: StableId
    parent_task_id: StableId
    task_kind: TemporaryAgentTaskKind
    task_instruction: str = Field(min_length=1, max_length=4_000)
    input_refs: tuple[TemporaryAgentInputRef, ...] = Field(min_length=1, max_length=32)
    input_payload: dict[str, JsonValue]
    expected_output_schema: dict[str, JsonValue] = Field(min_length=1)
    chinese_output_fields: tuple[str, ...] = Field(min_length=1, max_length=64)
    skill_contexts: tuple[TemporaryQwenSkillContext, ...] = Field(
        default_factory=tuple,
        max_length=8,
    )
    derived_memory_context: dict[str, JsonValue] | None = None
    max_tokens: int = Field(ge=1, le=100_000)
    timeout_seconds: int = Field(ge=1, le=3_600)
    max_attempts: int = Field(default=3, ge=1, le=3)
    minimum_reasoning_characters: int = Field(
        default=_MIN_REASONING_CHARACTERS,
        ge=_MIN_REASONING_CHARACTERS,
        le=100_000,
    )

    @model_validator(mode="after")
    def _validate_bounds(self) -> TemporaryQwenContentTask:
        skill_ids = [item.skill_ref.skill_id for item in self.skill_contexts]
        if len(skill_ids) != len(set(skill_ids)):
            raise TemporaryQwenPoolError("temporary task repeats a SKILL context")
        if sum(len(item.content) for item in self.skill_contexts) > (_MAX_TOTAL_SKILL_CHARACTERS):
            raise TemporaryQwenPoolError("temporary SKILL context bundle is too large")
        if self.derived_memory_context is not None and (
            self.derived_memory_context.get("context_kind")
            != "optional_rebuildable_dreaming_navigation"
            or self.derived_memory_context.get("derived_context_is_evidence") is not False
            or self.derived_memory_context.get("model_consumption_proven_by_this_receipt")
            is not False
        ):
            raise TemporaryQwenPoolError(
                "temporary Dreaming context lacks its non-evidence boundary"
            )
        payload_size = len(
            json.dumps(
                {
                    "task_instruction": self.task_instruction,
                    "input_refs": [item.model_dump(mode="json") for item in self.input_refs],
                    "input_payload": self.input_payload,
                    "derived_memory_context": self.derived_memory_context,
                    "expected_output_schema": self.expected_output_schema,
                    "chinese_output_fields": self.chinese_output_fields,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        if payload_size > _MAX_TASK_PAYLOAD_CHARACTERS:
            raise TemporaryQwenPoolError("temporary task payload is too large")
        return self


class TemporaryQwenStableOutput(StrictFrozenModel):
    """One successful model output in deterministic dispatch order."""

    dispatch_id: StableId
    result_hash: Sha256
    output_payload: dict[str, JsonValue] = Field(min_length=1)
    output_payload_sha256: Sha256

    @model_validator(mode="after")
    def _validate_output_hash(self) -> TemporaryQwenStableOutput:
        if self.output_payload_sha256 != canonical_sha256(self.output_payload):
            raise TemporaryQwenPoolError("stable temporary output hash mismatch")
        return self


class TemporaryQwenTaskRecord(StrictFrozenModel):
    """Persistent diagnostic index for one assignment/result/archive lifecycle."""

    schema_version: Literal["temporary-qwen-task-record-v1"] = "temporary-qwen-task-record-v1"
    dispatch_id: StableId
    temporary_agent_id: StableId
    terminal_status: TemporaryAgentTerminalStatus
    assignment_relative_path: str
    assignment_hash: Sha256
    result_relative_path: str | None = None
    result_hash: Sha256 | None = None
    authorship_receipt_relative_path: str | None = None
    authorship_receipt_hash: Sha256 | None = None
    archive_relative_path: str
    archive_hash: Sha256
    failure_type: str | None = Field(default=None, min_length=1, max_length=256)
    failure_message: str | None = Field(
        default=None,
        min_length=1,
        max_length=_DIAGNOSTIC_MAX_CHARACTERS,
    )
    record_relative_path: str
    record_hash: Sha256

    @field_validator(
        "assignment_relative_path",
        "result_relative_path",
        "authorship_receipt_relative_path",
        "archive_relative_path",
        "record_relative_path",
    )
    @classmethod
    def _validate_paths(cls, value: str | None) -> str | None:
        return _validate_relative_path(value) if value is not None else None

    @model_validator(mode="after")
    def _validate_record(self) -> TemporaryQwenTaskRecord:
        if self.terminal_status not in {
            TemporaryAgentTerminalStatus.SUCCEEDED,
            TemporaryAgentTerminalStatus.FAILED,
        }:
            raise TemporaryQwenPoolError("temporary Qwen tasks must end as succeeded or failed")
        if (self.result_relative_path is None) != (self.result_hash is None):
            raise TemporaryQwenPoolError("temporary result path/hash presence mismatch")
        if (self.authorship_receipt_relative_path is None) != (
            self.authorship_receipt_hash is None
        ):
            raise TemporaryQwenPoolError("temporary authorship receipt path/hash presence mismatch")
        failed = self.terminal_status is TemporaryAgentTerminalStatus.FAILED
        if failed != (self.failure_type is not None):
            raise TemporaryQwenPoolError("temporary failure type presence mismatch")
        if failed != (self.failure_message is not None):
            raise TemporaryQwenPoolError("temporary failure message presence mismatch")
        if not failed and (self.result_hash is None or self.authorship_receipt_hash is None):
            raise TemporaryQwenPoolError(
                "successful temporary task lacks retained result or receipt"
            )
        if self.result_hash is not None and self.authorship_receipt_hash is None:
            raise TemporaryQwenPoolError("temporary result lacks its authorship receipt binding")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"record_hash"}))
        if self.record_hash != expected:
            raise TemporaryQwenPoolError("temporary task record hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> TemporaryQwenTaskRecord:
        payload = dict(values)
        payload["record_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)


class TemporaryQwenBatchArtifact(StrictFrozenModel):
    """Content-addressed terminal index for a completely archived content batch."""

    schema_version: Literal["temporary-qwen-batch-artifact-v1"] = "temporary-qwen-batch-artifact-v1"
    batch_id: StableId
    lineage_id: StableId
    stage: StableId
    controller_binding_hash: Sha256
    task_records: tuple[TemporaryQwenTaskRecord, ...] = Field(min_length=1)
    stable_outputs: tuple[TemporaryQwenStableOutput, ...]
    stable_outputs_sha256: Sha256
    manifest_relative_path: str
    manifest_hash: Sha256
    manifest_stable_merged_output_sha256: Sha256
    dispatched_count: int = Field(ge=1)
    succeeded_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    all_assignments_archived: Literal[True] = True
    all_runtime_identities_inactive: Literal[True] = True
    outputs_retained: Literal[True] = True
    evidence_gate_bypassed: Literal[False] = False
    approval_gate_bypassed: Literal[False] = False
    safety_gate_bypassed: Literal[False] = False
    independent_review_bypassed: Literal[False] = False
    output_relative_path: str
    created_at: datetime
    artifact_hash: Sha256

    @field_validator("manifest_relative_path", "output_relative_path")
    @classmethod
    def _validate_paths(cls, value: str) -> str:
        return _validate_relative_path(value)

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def _validate_artifact(self) -> TemporaryQwenBatchArtifact:
        stable_records = tuple(sorted(self.task_records, key=lambda item: item.dispatch_id))
        if self.task_records != stable_records:
            raise TemporaryQwenPoolError("temporary task records must use stable dispatch order")
        record_ids = [item.dispatch_id for item in self.task_records]
        if len(record_ids) != len(set(record_ids)):
            raise TemporaryQwenPoolError("temporary batch repeats a dispatch id")
        succeeded = tuple(
            item
            for item in self.task_records
            if item.terminal_status is TemporaryAgentTerminalStatus.SUCCEEDED
        )
        if self.dispatched_count != len(self.task_records):
            raise TemporaryQwenPoolError("temporary dispatched count mismatch")
        if self.succeeded_count != len(succeeded):
            raise TemporaryQwenPoolError("temporary succeeded count mismatch")
        if self.failed_count != self.dispatched_count - self.succeeded_count:
            raise TemporaryQwenPoolError("temporary failed count mismatch")
        if [item.dispatch_id for item in self.stable_outputs] != [
            item.dispatch_id for item in succeeded
        ]:
            raise TemporaryQwenPoolError("stable outputs do not match successful dispatch order")
        for output, record in zip(self.stable_outputs, succeeded, strict=True):
            if output.result_hash != record.result_hash:
                raise TemporaryQwenPoolError("stable output result binding mismatch")
        expected_outputs_hash = canonical_sha256(
            [item.model_dump(mode="json") for item in self.stable_outputs]
        )
        if self.stable_outputs_sha256 != expected_outputs_hash:
            raise TemporaryQwenPoolError("stable output bundle hash mismatch")
        expected_manifest_output_hash = canonical_sha256(
            [
                {
                    "dispatch_id": item.dispatch_id,
                    "output_payload_sha256": item.output_payload_sha256,
                }
                for item in self.stable_outputs
            ]
        )
        if self.manifest_stable_merged_output_sha256 != expected_manifest_output_hash:
            raise TemporaryQwenPoolError(
                "batch artifact differs from the temporary manifest output hash"
            )
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"artifact_hash"}))
        if self.artifact_hash != expected:
            raise TemporaryQwenPoolError("temporary Qwen batch artifact hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> TemporaryQwenBatchArtifact:
        payload = dict(values)
        unhashed = cls.model_construct(**payload, artifact_hash="0" * 64)
        payload["artifact_hash"] = canonical_sha256(
            unhashed.model_dump(mode="json", exclude={"artifact_hash"})
        )
        return cls.model_validate(payload)


class TemporaryQwenStagePhaseBinding(StrictFrozenModel):
    """Persistent owner/controller/phase identity for one finite stage sequence."""

    schema_version: Literal["temporary-qwen-stage-phase-binding-v1"] = (
        "temporary-qwen-stage-phase-binding-v1"
    )
    sequence_id: StableId
    controller_binding_hash: Sha256
    controller_agent_id: StableId
    lineage_id: StableId
    stage: StableId
    phase_ids: tuple[StableId, ...] = Field(min_length=2, max_length=16)
    owner_thread_id: int = Field(ge=1)
    created_at: datetime
    binding_hash: Sha256

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def _validate_binding(self) -> TemporaryQwenStagePhaseBinding:
        if len(self.phase_ids) != len(set(self.phase_ids)):
            raise TemporaryQwenPoolError("temporary stage phase ids must be unique")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"binding_hash"}))
        if self.binding_hash != expected:
            raise TemporaryQwenPoolError("temporary stage phase binding hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        sequence_id: str,
        controller: StageControllerBinding,
        phase_ids: tuple[str, ...],
        owner_thread_id: int,
        created_at: datetime,
    ) -> TemporaryQwenStagePhaseBinding:
        payload: dict[str, Any] = {
            "schema_version": "temporary-qwen-stage-phase-binding-v1",
            "sequence_id": sequence_id,
            "controller_binding_hash": controller.binding_hash,
            "controller_agent_id": controller.controller_agent_id,
            "lineage_id": controller.lineage_id,
            "stage": controller.stage,
            "phase_ids": phase_ids,
            "owner_thread_id": owner_thread_id,
            "created_at": created_at,
        }
        unhashed = cls.model_construct(**payload, binding_hash="0" * 64)
        payload["binding_hash"] = canonical_sha256(
            unhashed.model_dump(mode="json", exclude={"binding_hash"})
        )
        return cls.model_validate(payload)


class TemporaryQwenPhaseManifest(StrictFrozenModel):
    """Explicitly phase-scoped wrapper around one terminal temporary batch."""

    schema_version: Literal["temporary-qwen-phase-manifest-v1"] = "temporary-qwen-phase-manifest-v1"
    phase_sequence_binding: TemporaryQwenStagePhaseBinding
    phase_id: StableId
    phase_index: int = Field(ge=1)
    phase_count: int = Field(ge=2)
    phase_status: Literal["succeeded", "failed"]
    batch_artifact_relative_path: str
    batch_artifact_hash: Sha256
    is_planned_final_phase: bool
    capability_retained_for_next_phase: bool
    capability_finalized: bool
    next_phase_id: StableId | None = None
    phase_sequence_completed: bool
    research_stage_completion_claimed: Literal[False] = False
    output_relative_path: str
    created_at: datetime
    manifest_hash: Sha256

    @field_validator("batch_artifact_relative_path", "output_relative_path")
    @classmethod
    def _validate_paths(cls, value: str) -> str:
        return _validate_relative_path(value)

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def _validate_manifest(self) -> TemporaryQwenPhaseManifest:
        if self.phase_count != len(self.phase_sequence_binding.phase_ids):
            raise TemporaryQwenPoolError("temporary phase count mismatch")
        if self.phase_index > self.phase_count:
            raise TemporaryQwenPoolError("temporary phase index exceeds sequence")
        if self.phase_sequence_binding.phase_ids[self.phase_index - 1] != self.phase_id:
            raise TemporaryQwenPoolError("temporary phase id/order mismatch")
        expected_final = self.phase_index == self.phase_count
        if self.is_planned_final_phase != expected_final:
            raise TemporaryQwenPoolError("temporary planned-final marker mismatch")
        successful_nonfinal = self.phase_status == "succeeded" and not expected_final
        if self.capability_retained_for_next_phase != successful_nonfinal:
            raise TemporaryQwenPoolError("temporary capability retention mismatch")
        if self.capability_finalized == successful_nonfinal:
            raise TemporaryQwenPoolError("temporary capability finality mismatch")
        expected_next = (
            self.phase_sequence_binding.phase_ids[self.phase_index] if successful_nonfinal else None
        )
        if self.next_phase_id != expected_next:
            raise TemporaryQwenPoolError("temporary next phase mismatch")
        expected_completed = self.phase_status == "succeeded" and expected_final
        if self.phase_sequence_completed != expected_completed:
            raise TemporaryQwenPoolError("temporary phase completion mismatch")
        expected_hash = canonical_sha256(self.model_dump(mode="json", exclude={"manifest_hash"}))
        if self.manifest_hash != expected_hash:
            raise TemporaryQwenPoolError("temporary phase manifest hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> TemporaryQwenPhaseManifest:
        payload = dict(values)
        unhashed = cls.model_construct(**payload, manifest_hash="0" * 64)
        payload["manifest_hash"] = canonical_sha256(
            unhashed.model_dump(mode="json", exclude={"manifest_hash"})
        )
        return cls.model_validate(payload)


_ACTIVE_PHASE_SESSIONS: dict[int, str] = {}
_ACTIVE_PHASE_SESSIONS_LOCK = threading.Lock()


class TemporaryQwenStagePhaseSession:
    """Owner-thread-only finite state machine for sequential stage batches.

    The same capability object and controller binding must be presented for every
    phase.  Phase ids are fixed at construction; a successful non-final phase may
    retain the capability exactly until the next declared phase.  The planned
    final phase, any failed phase, and every context-manager abort revoke it.
    """

    __slots__ = (
        "_active_phase",
        "_binding",
        "_capability",
        "_closed",
        "_controller_binding_hash",
        "_lock",
        "_manifests",
        "_next_index",
        "_output_root",
        "_owner_thread_id",
        "_registry_key",
    )

    def __init__(
        self,
        *,
        sequence_id: str,
        controller: StageControllerBinding,
        capability: StageDispatchCapability,
        phase_ids: tuple[str, ...],
        created_at: datetime | None = None,
    ) -> None:
        capability.require_valid(controller)
        owner_thread_id = threading.get_ident()
        now = _require_utc(created_at or datetime.now(timezone.utc))
        binding = TemporaryQwenStagePhaseBinding.create(
            sequence_id=sequence_id,
            controller=controller,
            phase_ids=phase_ids,
            owner_thread_id=owner_thread_id,
            created_at=now,
        )
        registry_key = id(capability)
        with _ACTIVE_PHASE_SESSIONS_LOCK:
            if registry_key in _ACTIVE_PHASE_SESSIONS:
                raise TemporaryQwenPoolError(
                    "stage dispatch capability already belongs to a phase session"
                )
            _ACTIVE_PHASE_SESSIONS[registry_key] = binding.binding_hash
        self._binding = binding
        self._capability = capability
        self._controller_binding_hash = controller.binding_hash
        self._owner_thread_id = owner_thread_id
        self._registry_key = registry_key
        self._next_index = 0
        self._active_phase: str | None = None
        self._output_root: Path | None = None
        self._manifests: dict[str, TemporaryQwenPhaseManifest] = {}
        self._closed = False
        self._lock = threading.RLock()

    @property
    def binding(self) -> TemporaryQwenStagePhaseBinding:
        return self._binding

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def __enter__(self) -> TemporaryQwenStagePhaseSession:
        self._require_owner()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> Literal[False]:
        if not self.closed:
            self.abort()
            if exc_type is None:
                raise TemporaryQwenPoolError(
                    "temporary phase session exited before its final phase"
                )
        return False

    def __getstate__(self) -> NoReturn:
        raise TypeError("temporary stage phase sessions are not serializable")

    def __reduce__(self) -> NoReturn:
        raise TypeError("temporary stage phase sessions are not serializable")

    def begin_phase(
        self,
        *,
        phase_id: str,
        controller: StageControllerBinding,
        capability: StageDispatchCapability,
        output_dir: Path | str,
    ) -> None:
        """Enter exactly the next declared phase on the owner thread."""

        with self._lock:
            self._require_owner()
            self._require_open()
            if capability is not self._capability:
                raise TemporaryQwenPoolError(
                    "temporary phase received a different capability object"
                )
            if controller.binding_hash != self._controller_binding_hash:
                raise TemporaryQwenPoolError(
                    "temporary phase received a different controller binding"
                )
            capability.require_valid(controller)
            if self._active_phase is not None:
                raise TemporaryQwenPoolError("a temporary phase is already active")
            expected = self._binding.phase_ids[self._next_index]
            if phase_id != expected:
                raise TemporaryQwenPoolError(
                    f"temporary phase order mismatch: expected {expected}, got {phase_id}"
                )
            output_root = Path(output_dir).resolve()
            if self._output_root is None:
                self._output_root = output_root
            elif output_root != self._output_root:
                raise TemporaryQwenPoolError("temporary phases must share one output directory")
            self._active_phase = phase_id

    def finish_phase(
        self,
        *,
        phase_id: str,
        controller: StageControllerBinding,
        capability: StageDispatchCapability,
        batch_artifact: TemporaryQwenBatchArtifact,
        succeeded: bool,
        created_at: datetime,
    ) -> TemporaryQwenPhaseManifest:
        """Persist phase finality, retaining capability only for a declared next phase."""

        with self._lock:
            self._require_owner()
            self._require_open()
            if self._active_phase != phase_id:
                raise TemporaryQwenPoolError("temporary phase is not active")
            if capability is not self._capability:
                raise TemporaryQwenPoolError(
                    "temporary phase finalization changed capability object"
                )
            if controller.binding_hash != self._controller_binding_hash:
                raise TemporaryQwenPoolError(
                    "temporary phase finalization changed controller binding"
                )
            capability.require_valid(controller)
            if batch_artifact.controller_binding_hash != controller.binding_hash:
                raise TemporaryQwenPoolError("temporary phase batch belongs to another controller")
            if succeeded != (batch_artifact.failed_count == 0):
                raise TemporaryQwenPoolError("temporary phase success marker mismatch")
            phase_index = self._next_index + 1
            phase_count = len(self._binding.phase_ids)
            planned_final = phase_index == phase_count
            finalize = not succeeded or planned_final
            if finalize:
                capability.revoke()
            output_root = self._output_root
            if output_root is None:
                capability.revoke()
                raise TemporaryQwenPoolError("temporary phase output root is absent")
            batch_path = _resolve_inside(
                output_root,
                batch_artifact.output_relative_path,
            )
            if not batch_path.is_file():
                capability.revoke()
                raise TemporaryQwenPoolError("temporary phase batch artifact was not persisted")
            sequence_root = PurePosixPath(
                "temporary-agents",
                "stage-phases",
                f"sequence-{self._binding.binding_hash[:24]}",
            )
            output_relative_path = (
                sequence_root / f"{phase_index:02d}-{_short_digest(phase_id, length=24)}.json"
            ).as_posix()
            manifest = TemporaryQwenPhaseManifest.create(
                schema_version="temporary-qwen-phase-manifest-v1",
                phase_sequence_binding=self._binding,
                phase_id=phase_id,
                phase_index=phase_index,
                phase_count=phase_count,
                phase_status="succeeded" if succeeded else "failed",
                batch_artifact_relative_path=batch_artifact.output_relative_path,
                batch_artifact_hash=batch_artifact.artifact_hash,
                is_planned_final_phase=planned_final,
                capability_retained_for_next_phase=(succeeded and not planned_final),
                capability_finalized=finalize,
                next_phase_id=(
                    self._binding.phase_ids[phase_index]
                    if succeeded and not planned_final
                    else None
                ),
                phase_sequence_completed=succeeded and planned_final,
                research_stage_completion_claimed=False,
                output_relative_path=output_relative_path,
                created_at=created_at,
            )
            try:
                _write_immutable_json(output_root, output_relative_path, manifest)
            except Exception:
                capability.revoke()
                self._close()
                raise
            self._manifests[phase_id] = manifest
            self._active_phase = None
            self._next_index += 1
            if finalize:
                self._close()
            return manifest

    def phase_manifest(self, phase_id: str) -> TemporaryQwenPhaseManifest:
        self._require_owner()
        try:
            return self._manifests[phase_id]
        except KeyError as exc:
            raise TemporaryQwenPoolError(
                f"temporary phase manifest is unavailable: {phase_id}"
            ) from exc

    def abort(self) -> None:
        """Fail closed and permanently revoke the stage capability."""

        with self._lock:
            self._require_owner()
            if self._closed:
                return
            self._capability.revoke()
            self._active_phase = None
            self._close()

    def _require_owner(self) -> None:
        if threading.get_ident() != self._owner_thread_id:
            raise TemporaryQwenPoolError("temporary phase session may only run on its owner thread")

    def _require_open(self) -> None:
        if self._closed:
            raise TemporaryQwenPoolError("temporary phase session is closed")
        if self._next_index >= len(self._binding.phase_ids):
            raise TemporaryQwenPoolError("temporary phase sequence is exhausted")

    def _close(self) -> None:
        self._closed = True
        with _ACTIVE_PHASE_SESSIONS_LOCK:
            current = _ACTIVE_PHASE_SESSIONS.get(self._registry_key)
            if current == self._binding.binding_hash:
                del _ACTIVE_PHASE_SESSIONS[self._registry_key]


@dataclass(frozen=True)
class _CompletionOutcome:
    dispatch_id: str
    result: TemporaryAgentResultArtifact | None
    receipt: ModelAuthorshipReceipt | None
    failure_type: str | None
    failure_message: str | None


def run_temporary_qwen_content_batch(
    *,
    batch_id: str,
    controller: StageControllerBinding,
    capability: StageDispatchCapability,
    tasks: Sequence[TemporaryQwenContentTask],
    output_dir: Path | str,
    completion: CompletionCallable = run_llm_json_completion,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    max_workers: int | None = None,
    thinking_budget: int = _DEFAULT_THINKING_BUDGET,
    temperature: float = 0.2,
    clock: datetime | None = None,
    phase_session: TemporaryQwenStagePhaseSession | None = None,
    phase_id: str | None = None,
) -> TemporaryQwenBatchArtifact:
    """Run a standalone batch or one declared phase of a finite stage session."""

    try:
        if (phase_session is None) != (phase_id is None):
            raise TemporaryQwenPoolError(
                "temporary phase_session and phase_id must be supplied together"
            )
        if phase_session is not None and phase_id is not None:
            phase_session.begin_phase(
                phase_id=phase_id,
                controller=controller,
                capability=capability,
                output_dir=output_dir,
            )
        return _run_temporary_qwen_content_batch(
            batch_id=batch_id,
            controller=controller,
            capability=capability,
            tasks=tasks,
            output_dir=output_dir,
            completion=completion,
            config_path=config_path,
            env_path=env_path,
            max_workers=max_workers,
            thinking_budget=thinking_budget,
            temperature=temperature,
            clock=clock,
            phase_session=phase_session,
            phase_id=phase_id,
        )
    except Exception:
        if phase_session is not None and not phase_session.closed:
            phase_session.abort()
        raise


def _run_temporary_qwen_content_batch(
    *,
    batch_id: str,
    controller: StageControllerBinding,
    capability: StageDispatchCapability,
    tasks: Sequence[TemporaryQwenContentTask],
    output_dir: Path | str,
    completion: CompletionCallable = run_llm_json_completion,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    max_workers: int | None = None,
    thinking_budget: int = _DEFAULT_THINKING_BUDGET,
    temperature: float = 0.2,
    clock: datetime | None = None,
    phase_session: TemporaryQwenStagePhaseSession | None,
    phase_id: str | None,
) -> TemporaryQwenBatchArtifact:
    """Run one fully archived, stable, provider-neutral temporary content batch.

    All assignments are created and registered before any worker starts.  Worker
    threads receive only immutable task bytes; the main thread alone retains the
    capability and performs result registration and archival.
    """

    capability.require_valid(controller)
    validated_batch_id = _STABLE_ID_ADAPTER.validate_python(batch_id)
    ordered_tasks = tuple(sorted(tasks, key=lambda item: item.dispatch_id))
    _validate_batch_preflight(
        tasks=ordered_tasks,
        controller=controller,
        max_workers=max_workers,
        thinking_budget=thinking_budget,
        temperature=temperature,
    )
    now = _require_utc(clock or datetime.now(timezone.utc))
    worker_count = max_workers or min(len(ordered_tasks), controller.max_parallel_agents)
    output_root = Path(output_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    batch_root = _batch_relative_root(validated_batch_id)
    _prepare_output_layout(output_root, batch_root)

    assignments: dict[str, TemporaryAgentAssignment] = {}
    assignment_paths: dict[str, str] = {}
    result_paths: dict[str, str] = {}
    archive_paths: dict[str, str] = {}
    record_paths: dict[str, str] = {}
    interaction_ids: dict[str, str] = {}
    for index, task in enumerate(ordered_tasks, start=1):
        assignment = TemporaryAgentAssignment.create(
            controller=controller,
            capability=capability,
            dispatch_id=task.dispatch_id,
            temporary_agent_id=task.temporary_agent_id,
            parent_task_id=task.parent_task_id,
            task_kind=task.task_kind,
            task_instruction=task.task_instruction,
            input_refs=task.input_refs,
            input_payload=task.input_payload,
            expected_output_schema=task.expected_output_schema,
            chinese_output_fields=task.chinese_output_fields,
            selected_skills=tuple(item.skill_ref for item in task.skill_contexts),
            max_tokens=task.max_tokens,
            timeout_seconds=task.timeout_seconds,
            max_attempts=task.max_attempts,
            minimum_reasoning_characters=task.minimum_reasoning_characters,
        )
        assignments[task.dispatch_id] = assignment
        stem = f"{index:04d}-{_short_digest(task.dispatch_id)}"
        assignment_paths[task.dispatch_id] = (
            batch_root / "assignments" / f"{stem}.json"
        ).as_posix()
        result_paths[task.dispatch_id] = (batch_root / "results" / f"{stem}.json").as_posix()
        archive_paths[task.dispatch_id] = (batch_root / "archives" / f"{stem}.json").as_posix()
        record_paths[task.dispatch_id] = (batch_root / "task-records" / f"{stem}.json").as_posix()
        interaction_ids[task.dispatch_id] = (
            f"temporary-content-{_short_digest(validated_batch_id)}-"
            f"{index:04d}-{_short_digest(task.dispatch_id)}"
        )

    coordinator = TemporaryAgentArchiveCoordinator(controller)
    try:
        for task in ordered_tasks:
            _write_immutable_json(
                output_root,
                assignment_paths[task.dispatch_id],
                assignments[task.dispatch_id],
            )
        for task in ordered_tasks:
            coordinator.dispatch(assignments[task.dispatch_id], capability=capability)
        return _complete_dispatched_batch(
            validated_batch_id=validated_batch_id,
            controller=controller,
            capability=capability,
            ordered_tasks=ordered_tasks,
            output_root=output_root,
            batch_root=batch_root,
            coordinator=coordinator,
            assignments=assignments,
            assignment_paths=assignment_paths,
            result_paths=result_paths,
            archive_paths=archive_paths,
            record_paths=record_paths,
            interaction_ids=interaction_ids,
            completion=completion,
            config_path=config_path,
            env_path=env_path,
            thinking_budget=thinking_budget,
            temperature=temperature,
            worker_count=worker_count,
            now=now,
            phase_session=phase_session,
            phase_id=phase_id,
        )
    except Exception as exc:
        _emergency_archive_active_assignments(
            coordinator=coordinator,
            capability=capability,
            assignments=assignments,
            assignment_paths=assignment_paths,
            archive_paths=archive_paths,
            record_paths=record_paths,
            output_root=output_root,
            archived_at=now,
            cause=exc,
            finalize_capability=phase_session is None,
        )
        raise


def _complete_dispatched_batch(
    *,
    validated_batch_id: str,
    controller: StageControllerBinding,
    capability: StageDispatchCapability,
    ordered_tasks: tuple[TemporaryQwenContentTask, ...],
    output_root: Path,
    batch_root: PurePosixPath,
    coordinator: TemporaryAgentArchiveCoordinator,
    assignments: dict[str, TemporaryAgentAssignment],
    assignment_paths: dict[str, str],
    result_paths: dict[str, str],
    archive_paths: dict[str, str],
    record_paths: dict[str, str],
    interaction_ids: dict[str, str],
    completion: CompletionCallable,
    config_path: Path | str,
    env_path: Path | str,
    thinking_budget: int,
    temperature: float,
    worker_count: int,
    now: datetime,
    phase_session: TemporaryQwenStagePhaseSession | None,
    phase_id: str | None,
) -> TemporaryQwenBatchArtifact:
    records: dict[str, TemporaryQwenTaskRecord] = {}
    accepted_results: dict[str, TemporaryAgentResultArtifact] = {}
    futures: dict[Future[_CompletionOutcome], str] = {}
    with ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="temporary-qwen-content",
    ) as executor:
        for task in ordered_tasks:
            assignment = assignments[task.dispatch_id]
            future = executor.submit(
                _complete_one_task,
                task=task,
                assignment=assignment,
                interaction_id=interaction_ids[task.dispatch_id],
                output_root=output_root,
                completion=completion,
                config_path=config_path,
                env_path=env_path,
                thinking_budget=thinking_budget,
                temperature=temperature,
                clock=now,
            )
            futures[future] = task.dispatch_id
        for future in as_completed(futures):
            dispatch_id = futures[future]
            outcome = future.result()
            record, accepted_result = _finalize_task(
                outcome=outcome,
                assignment=assignments[dispatch_id],
                coordinator=coordinator,
                capability=capability,
                output_root=output_root,
                assignment_relative_path=assignment_paths[dispatch_id],
                result_relative_path=result_paths[dispatch_id],
                archive_relative_path=archive_paths[dispatch_id],
                record_relative_path=record_paths[dispatch_id],
                archived_at=now,
            )
            records[dispatch_id] = record
            if accepted_result is not None:
                accepted_results[dispatch_id] = accepted_result

    manifest_relative_path = (batch_root / "batch-manifest.json").as_posix()
    if phase_session is None:
        manifest = coordinator.build_manifest(
            batch_id=validated_batch_id,
            capability=capability,
            created_at=now,
        )
    else:
        manifest = coordinator.build_intermediate_manifest(
            batch_id=validated_batch_id,
            capability=capability,
            created_at=now,
        )
    _write_immutable_json(output_root, manifest_relative_path, manifest)
    stable_outputs = tuple(
        TemporaryQwenStableOutput(
            dispatch_id=record.dispatch_id,
            result_hash=accepted_results[record.dispatch_id].result_hash,
            output_payload=accepted_results[record.dispatch_id].output_payload,
            output_payload_sha256=(accepted_results[record.dispatch_id].output_payload_sha256),
        )
        for record in sorted(records.values(), key=lambda item: item.dispatch_id)
        if record.terminal_status is TemporaryAgentTerminalStatus.SUCCEEDED
    )
    output_relative_path = (batch_root / "batch-artifact.json").as_posix()
    artifact = TemporaryQwenBatchArtifact.create(
        schema_version="temporary-qwen-batch-artifact-v1",
        batch_id=validated_batch_id,
        lineage_id=controller.lineage_id,
        stage=controller.stage,
        controller_binding_hash=controller.binding_hash,
        task_records=tuple(sorted(records.values(), key=lambda item: item.dispatch_id)),
        stable_outputs=stable_outputs,
        stable_outputs_sha256=canonical_sha256(
            [item.model_dump(mode="json") for item in stable_outputs]
        ),
        manifest_relative_path=manifest_relative_path,
        manifest_hash=manifest.batch_hash,
        manifest_stable_merged_output_sha256=(manifest.stable_merged_output_sha256),
        dispatched_count=manifest.dispatched_count,
        succeeded_count=manifest.succeeded_count,
        failed_count=manifest.failed_count,
        output_relative_path=output_relative_path,
        created_at=now,
    )
    _write_immutable_json(output_root, output_relative_path, artifact)
    if phase_session is not None:
        if phase_id is None:  # pragma: no cover - guarded by the public wrapper
            raise TemporaryQwenPoolError("temporary phase id is absent")
        phase_session.finish_phase(
            phase_id=phase_id,
            controller=controller,
            capability=capability,
            batch_artifact=artifact,
            succeeded=artifact.failed_count == 0,
            created_at=now,
        )
    if artifact.failed_count:
        raise TemporaryQwenBatchError(artifact)
    return artifact


def _emergency_archive_active_assignments(
    *,
    coordinator: TemporaryAgentArchiveCoordinator,
    capability: StageDispatchCapability,
    assignments: dict[str, TemporaryAgentAssignment],
    assignment_paths: dict[str, str],
    archive_paths: dict[str, str],
    record_paths: dict[str, str],
    output_root: Path,
    archived_at: datetime,
    cause: Exception,
    finalize_capability: bool,
) -> None:
    """Best-effort persistence recovery before the outer phase revokes authority."""

    active_agent_ids = set(coordinator.active_agent_ids)
    failure_type, failure_message = _diagnostic(cause)
    cleanup_failures: list[str] = []
    for dispatch_id, assignment in sorted(assignments.items()):
        archive = None
        try:
            if assignment.temporary_agent_id in active_agent_ids:
                archive = coordinator.archive(
                    dispatch_id,
                    terminal_status=TemporaryAgentTerminalStatus.FAILED,
                    capability=capability,
                    archived_at=archived_at,
                )
            else:
                archive = coordinator.archive_record(dispatch_id)
        except Exception as exc:
            cleanup_failures.append(f"{dispatch_id}:archive:{type(exc).__name__}:{str(exc)[:500]}")
            continue
        try:
            _write_immutable_json(
                output_root,
                archive_paths[dispatch_id],
                archive,
            )
            record_path = _resolve_inside(output_root, record_paths[dispatch_id])
            if (
                not record_path.exists()
                and archive.terminal_status is TemporaryAgentTerminalStatus.FAILED
            ):
                record = TemporaryQwenTaskRecord.create(
                    schema_version="temporary-qwen-task-record-v1",
                    dispatch_id=dispatch_id,
                    temporary_agent_id=assignment.temporary_agent_id,
                    terminal_status=TemporaryAgentTerminalStatus.FAILED,
                    assignment_relative_path=assignment_paths[dispatch_id],
                    assignment_hash=assignment.assignment_hash,
                    result_relative_path=None,
                    result_hash=None,
                    authorship_receipt_relative_path=None,
                    authorship_receipt_hash=None,
                    archive_relative_path=archive_paths[dispatch_id],
                    archive_hash=archive.archive_hash,
                    failure_type=failure_type,
                    failure_message=failure_message,
                    record_relative_path=record_paths[dispatch_id],
                )
                _write_immutable_json(output_root, record_paths[dispatch_id], record)
        except Exception as exc:
            cleanup_failures.append(f"{dispatch_id}:persist:{type(exc).__name__}:{str(exc)[:500]}")
    if cleanup_failures:
        diagnostic_payload: dict[str, Any] = {
            "schema_version": "temporary-qwen-emergency-cleanup-v1",
            "controller_binding_hash": coordinator.controller.binding_hash,
            "cause_type": failure_type,
            "cause_message": failure_message,
            "cleanup_failures": cleanup_failures,
            "created_at": archived_at.isoformat(),
        }
        diagnostic_payload["diagnostic_hash"] = canonical_sha256(diagnostic_payload)
        diagnostic_path = (
            PurePosixPath("temporary-agents", "emergency")
            / f"{canonical_sha256(diagnostic_payload)[:24]}.json"
        ).as_posix()
        with suppress(Exception):
            _write_immutable_json(output_root, diagnostic_path, diagnostic_payload)
    if finalize_capability:
        capability.revoke()


def _complete_one_task(
    *,
    task: TemporaryQwenContentTask,
    assignment: TemporaryAgentAssignment,
    interaction_id: str,
    output_root: Path,
    completion: CompletionCallable,
    config_path: Path | str,
    env_path: Path | str,
    thinking_budget: int,
    temperature: float,
    clock: datetime,
) -> _CompletionOutcome:
    messages = _task_messages(task=task, assignment=assignment)
    receipt: ModelAuthorshipReceipt | None = None
    try:
        completion_result: LLMJsonCompletionResult | None = None
        final_attempt = 0
        for attempt_index in range(1, assignment.max_attempts + 1):
            try:
                completion_result = completion(
                    messages=messages,
                    config_path=config_path,
                    env_path=env_path,
                    timeout_seconds=assignment.timeout_seconds,
                    max_tokens=assignment.max_tokens,
                    temperature=temperature,
                    thinking_mode="enabled",
                    thinking_budget=thinking_budget,
                    response_schema=copy.deepcopy(assignment.expected_output_schema),
                    response_schema_name=(
                        f"temporary_content_{_short_digest(assignment.dispatch_id)}"
                    ),
                )
                final_attempt = attempt_index
                break
            except LLMClientError as exc:
                raw_response = exc.response_text
                repairable = raw_response is not None and (
                    "not valid JSON" in str(exc) or "top-level value is not an object" in str(exc)
                )
                if not repairable or attempt_index >= assignment.max_attempts:
                    raise
                assert raw_response is not None
                messages = [
                    *messages,
                    {"role": "assistant", "content": raw_response},
                    {
                        "role": "user",
                        "content": (
                            "上一响应只有 JSON 语法或顶层类型错误。保持任务输入、科研判断、"
                            "字段含义和数值逐字不变，只修复 JSON 标点、引号、括号或对象外壳；"
                            "不得借格式修复新增、删除或改写科学内容。只返回修复后的一个 JSON 对象。"
                        ),
                    },
                ]
        if completion_result is None:  # pragma: no cover - loop exits or raises
            raise TemporaryQwenPoolError("临时 Qwen 未返回可用响应")
        receipt = record_model_authorship_receipt(
            artifact_kind="temporary_content_output",
            interaction_id=interaction_id,
            attempt=final_attempt,
            messages=messages,
            completion=completion_result,
            output_dir=output_root,
            clock=clock,
        )
        if completion_result.reasoning_transport == "absent":
            raise TemporaryQwenPoolError("Qwen 调用未记录已启用的 reasoning transport")
        reasoning = str(completion_result.reasoning_text or "").strip()
        if len(reasoning) < assignment.minimum_reasoning_characters:
            raise TemporaryQwenPoolError("Qwen reasoning_content 为空")
        if not _contains_chinese(reasoning):
            raise TemporaryQwenPoolError("Qwen reasoning_content 未包含可审计的中文推理")
        receipt_relative_path = _relative_to_output(
            output_root,
            Path(receipt.output_path),
        )
        result = TemporaryAgentResultArtifact.create(
            assignment=assignment,
            output_payload=completion_result.parsed_json,
            authorship_receipt_relative_path=receipt_relative_path,
            authorship_receipt_hash=receipt.receipt_hash,
            model_name=completion_result.model_name,
            reasoning_character_count=len(reasoning),
            created_at=clock,
        )
        return _CompletionOutcome(
            dispatch_id=assignment.dispatch_id,
            result=result,
            receipt=receipt,
            failure_type=None,
            failure_message=None,
        )
    except Exception as exc:
        failure_type, failure_message = _diagnostic(exc)
        return _CompletionOutcome(
            dispatch_id=assignment.dispatch_id,
            result=None,
            receipt=receipt,
            failure_type=failure_type,
            failure_message=failure_message,
        )


def _finalize_task(
    *,
    outcome: _CompletionOutcome,
    assignment: TemporaryAgentAssignment,
    coordinator: TemporaryAgentArchiveCoordinator,
    capability: StageDispatchCapability,
    output_root: Path,
    assignment_relative_path: str,
    result_relative_path: str,
    archive_relative_path: str,
    record_relative_path: str,
    archived_at: datetime,
) -> tuple[TemporaryQwenTaskRecord, TemporaryAgentResultArtifact | None]:
    terminal_status = TemporaryAgentTerminalStatus.FAILED
    accepted_result: TemporaryAgentResultArtifact | None = None
    persisted_result_path: str | None = None
    failure_type = outcome.failure_type
    failure_message = outcome.failure_message
    if outcome.result is not None:
        try:
            _write_immutable_json(output_root, result_relative_path, outcome.result)
            coordinator.record_result(outcome.result, capability=capability)
            accepted_result = outcome.result
            persisted_result_path = result_relative_path
            terminal_status = TemporaryAgentTerminalStatus.SUCCEEDED
        except Exception as exc:
            failure_type, failure_message = _diagnostic(exc)
    archive = coordinator.archive(
        assignment.dispatch_id,
        terminal_status=terminal_status,
        capability=capability,
        archived_at=archived_at,
    )
    _write_immutable_json(output_root, archive_relative_path, archive)
    receipt_relative_path = (
        _relative_to_output(output_root, Path(outcome.receipt.output_path))
        if outcome.receipt is not None
        else None
    )
    record = TemporaryQwenTaskRecord.create(
        schema_version="temporary-qwen-task-record-v1",
        dispatch_id=assignment.dispatch_id,
        temporary_agent_id=assignment.temporary_agent_id,
        terminal_status=terminal_status,
        assignment_relative_path=assignment_relative_path,
        assignment_hash=assignment.assignment_hash,
        result_relative_path=persisted_result_path,
        result_hash=(accepted_result.result_hash if accepted_result else None),
        authorship_receipt_relative_path=receipt_relative_path,
        authorship_receipt_hash=(outcome.receipt.receipt_hash if outcome.receipt else None),
        archive_relative_path=archive_relative_path,
        archive_hash=archive.archive_hash,
        failure_type=failure_type,
        failure_message=failure_message,
        record_relative_path=record_relative_path,
    )
    _write_immutable_json(output_root, record_relative_path, record)
    return record, accepted_result


def _task_messages(
    *,
    task: TemporaryQwenContentTask,
    assignment: TemporaryAgentAssignment,
) -> list[dict[str, str]]:
    messages = [
        {"role": "system", "content": _COMMON_ROLE_INSTRUCTION},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "上下文类型": "题目与显式输入",
                    "输入引用": [item.model_dump(mode="json") for item in assignment.input_refs],
                    "短任务输入": assignment.input_payload,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        },
    ]
    for skill_context in task.skill_contexts:
        messages.append(
            {
                # The agent sees its question/input before project Skills. Skills are
                # independent, read-only context rather than additions to identity.
                "role": "user",
                "content": json.dumps(
                    {
                        "上下文类型": "独立只读技能",
                        "技能编号": skill_context.skill_ref.skill_id,
                        "技能来源": skill_context.skill_ref.source_ref,
                        "技能内容哈希": skill_context.skill_ref.content_sha256,
                        "技能是科学证据": False,
                        "技能正文": skill_context.content,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
        )
    if task.derived_memory_context is not None:
        messages.append(
            {
                "role": "user",
                "content": json.dumps(
                    task.derived_memory_context,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
        )
    messages.append(
        {
            "role": "user",
            "content": json.dumps(
                {
                    "派工编号": assignment.dispatch_id,
                    "任务类型": assignment.task_kind.value,
                    "任务指令": assignment.task_instruction,
                    "输入引用": [item.model_dump(mode="json") for item in assignment.input_refs],
                    "短任务输入": assignment.input_payload,
                    "预期输出Schema": assignment.expected_output_schema,
                    "必须为中文的字段": assignment.chinese_output_fields,
                    "输出语言": assignment.output_language,
                    "最低推理字符数": assignment.minimum_reasoning_characters,
                    "权限边界": {
                        "可再派工": False,
                        "可审批": False,
                        "可执行": False,
                        "可裁决": False,
                        "可发布": False,
                        "可提升证据": False,
                    },
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        }
    )
    return messages


def _validate_batch_preflight(
    *,
    tasks: tuple[TemporaryQwenContentTask, ...],
    controller: StageControllerBinding,
    max_workers: int | None,
    thinking_budget: int,
    temperature: float,
) -> None:
    if not tasks:
        raise TemporaryQwenPoolError("temporary Qwen content batch cannot be empty")
    if len(tasks) > controller.max_parallel_agents:
        raise TemporaryQwenPoolError(
            "all temporary assignments must fit the controller parallel limit"
        )
    dispatch_ids = [item.dispatch_id for item in tasks]
    runtime_ids = [item.temporary_agent_id for item in tasks]
    if len(dispatch_ids) != len(set(dispatch_ids)):
        raise TemporaryQwenPoolError("temporary batch repeats a dispatch id")
    if len(runtime_ids) != len(set(runtime_ids)):
        raise TemporaryQwenPoolError("temporary batch repeats a runtime identity")
    if max_workers is not None and (
        max_workers < 1 or max_workers > len(tasks) or max_workers > controller.max_parallel_agents
    ):
        raise TemporaryQwenPoolError("temporary max_workers exceeds batch bounds")
    if not _MIN_REASONING_CHARACTERS <= thinking_budget <= _MAX_THINKING_BUDGET:
        raise TemporaryQwenPoolError("temporary thinking budget is outside bounds")
    if not 0.0 <= temperature <= 2.0:
        raise TemporaryQwenPoolError("temporary completion temperature is invalid")


def _prepare_output_layout(output_root: Path, batch_root: PurePosixPath) -> None:
    for relative in (
        PurePosixPath("interactions"),
        batch_root / "assignments",
        batch_root / "results",
        batch_root / "archives",
        batch_root / "task-records",
    ):
        target = _resolve_inside(output_root, relative.as_posix())
        target.mkdir(parents=True, exist_ok=True)
        if not target.is_dir():
            raise TemporaryQwenPoolError(
                f"temporary output directory is unavailable: {relative.as_posix()}"
            )


def _write_immutable_json(
    output_root: Path,
    relative_path: str,
    model: BaseModel | dict[str, Any],
) -> Path:
    target = _resolve_inside(output_root, relative_path)
    payload = model.model_dump(mode="json") if isinstance(model, BaseModel) else model
    if target.exists():
        if not target.is_file():
            raise TemporaryQwenPoolError(f"temporary artifact path is not a file: {relative_path}")
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError) as exc:
            raise TemporaryQwenPoolError(
                f"existing temporary artifact is unreadable: {relative_path}"
            ) from exc
        if existing != payload:
            raise TemporaryQwenPoolError(
                f"refusing to overwrite different temporary artifact: {relative_path}"
            )
        return target
    return write_json_model(target, payload)


def _relative_to_output(output_root: Path, path: Path) -> str:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(output_root)
    except ValueError as exc:
        raise TemporaryQwenPoolError("temporary artifact path escapes output_dir") from exc
    return _validate_relative_path(relative.as_posix())


def _resolve_inside(output_root: Path, relative_path: str) -> Path:
    safe_relative = _validate_relative_path(relative_path)
    path = (output_root / Path(*PurePosixPath(safe_relative).parts)).resolve()
    try:
        path.relative_to(output_root)
    except ValueError as exc:
        raise TemporaryQwenPoolError("temporary artifact path escapes output_dir") from exc
    return path


def _validate_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or path.is_absolute()
        or path == PurePosixPath(".")
        or ".." in path.parts
        or "\x00" in normalized
        or any(":" in part for part in path.parts)
    ):
        raise TemporaryQwenPoolError("temporary artifact paths must stay relative to output_dir")
    return path.as_posix()


def _batch_relative_root(batch_id: str) -> PurePosixPath:
    return PurePosixPath(
        "temporary-agents",
        "batches",
        f"batch-{_short_digest(batch_id, length=24)}",
    )


def _short_digest(value: str, *, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise TemporaryQwenPoolError("temporary batch timestamps must be UTC")
    return value.astimezone(timezone.utc)


def _contains_chinese(value: str) -> bool:
    return any(
        "\u3400" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
        or character == "\u3007"
        for character in value
    )


def _diagnostic(exc: Exception) -> tuple[str, str]:
    failure_type = type(exc).__name__[:256] or "Exception"
    detail = str(exc).strip() or "未提供异常详情"
    message = f"临时内容任务失败：{detail}"
    return failure_type, message[:_DIAGNOSTIC_MAX_CHARACTERS]


__all__ = [
    "CompletionCallable",
    "TemporaryQwenBatchArtifact",
    "TemporaryQwenBatchError",
    "TemporaryQwenContentTask",
    "TemporaryQwenPoolError",
    "TemporaryQwenSkillContext",
    "TemporaryQwenPhaseManifest",
    "TemporaryQwenStagePhaseBinding",
    "TemporaryQwenStagePhaseSession",
    "TemporaryQwenStableOutput",
    "TemporaryQwenTaskRecord",
    "run_temporary_qwen_content_batch",
]
