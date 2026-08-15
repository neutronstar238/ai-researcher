"""Fail-closed contracts for bounded, one-shot temporary content agents.

This module is intentionally independent from the official research lineage.  It
provides only the process layer needed by a stage main agent to delegate bounded
content tasks: an in-memory dispatch capability, content-addressed assignments and
results, terminal archive records, and a deterministic batch manifest.

Temporary-agent output is process metadata.  It cannot authorize delegation,
approval, execution, adjudication, evidence promotion, publication, or release.
Scientific callers must keep their existing evidence, independent-review, safety,
and human-approval gates after consuming any temporary-agent output.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import secrets
import threading
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import PurePosixPath
from typing import Literal, NoReturn

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from autoresearch.kernel.contracts import Sha256, StableId, canonical_sha256


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("temporary-agent timestamps must be timezone-aware UTC")
    return value.astimezone(timezone.utc)


def _require_unique(values: tuple[str, ...], *, label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"temporary-agent {label} values must be unique")


def _contains_chinese_text(value: object) -> bool:
    if isinstance(value, str):
        return any(
            "\u3400" <= character <= "\u9fff"
            or "\uf900" <= character <= "\ufaff"
            or character == "\u3007"
            for character in value
        )
    if isinstance(value, dict):
        return any(_contains_chinese_text(item) for item in value.values())
    if isinstance(value, list | tuple):
        return any(_contains_chinese_text(item) for item in value)
    return False


def _is_empty_json_container(value: object) -> bool:
    return isinstance(value, list | tuple | dict) and not value


class TemporaryAgentContractError(ValueError):
    """Raised when a temporary-agent process contract fails closed."""


class TemporaryAgentTaskKind(str, Enum):
    """The complete allowlist of tasks a temporary agent may perform."""

    EVIDENCE_MEMO = "evidence_memo"
    LITERATURE_COMPARISON = "literature_comparison"
    OPPORTUNITY_MEMO = "opportunity_memo"
    ADVERSARIAL_CRITIQUE = "adversarial_critique"
    CONTENT_CHECKLIST = "content_checklist"


class TemporaryAgentTerminalStatus(str, Enum):
    """Terminal outcome recorded before the runtime identity is discarded."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TemporaryAgentInputRef(_FrozenContract):
    """Digest-only reference to an input already admitted by the main stage."""

    artifact_id: StableId
    source_ref: str = Field(min_length=1)
    sha256: Sha256
    media_type: str = Field(default="application/json", min_length=1)


class TemporaryAgentSkillRef(_FrozenContract):
    """A read-only SKILL.md binding; method context is never scientific evidence."""

    skill_id: StableId
    source_ref: str = Field(min_length=1)
    content_sha256: Sha256
    import_policy: Literal["read_only_context"] = "read_only_context"
    is_scientific_evidence: Literal[False] = False


class _StageControllerBindingContent(_FrozenContract):
    schema_version: Literal["stage-controller-binding-v1"] = "stage-controller-binding-v1"
    lineage_id: StableId
    stage: StableId
    stage_attempt: int = Field(ge=1)
    controller_agent_id: StableId
    controller_role: Literal["main_agent"] = "main_agent"
    stage_input_hash: Sha256
    lease_token_hash: Sha256
    max_parallel_agents: int = Field(ge=1, le=32)
    claimed_at: datetime = Field(default_factory=_utc_now)

    @field_validator("claimed_at")
    @classmethod
    def _validate_claimed_at(cls, value: datetime) -> datetime:
        return _require_utc(value)


class StageControllerBinding(_StageControllerBindingContent):
    """Persistent identity of the one main agent allowed to dispatch this stage."""

    binding_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> StageControllerBinding:
        self.verify_integrity()
        return self

    def verify_integrity(self) -> None:
        """Recheck the content address, including after hostile in-memory mutation."""

        expected = canonical_sha256(self.model_dump(mode="json", exclude={"binding_hash"}))
        if self.binding_hash != expected:
            raise TemporaryAgentContractError("stage-controller binding hash mismatch")


class StageDispatchCapability:
    """Unserializable in-memory bearer capability held only by the stage main agent."""

    __slots__ = ("_active", "_binding_hash", "_lease_token", "_lock")

    def __init__(self, *, binding_hash: str, lease_token: str) -> None:
        self._binding_hash = binding_hash
        self._lease_token = lease_token
        self._active = True
        self._lock = threading.Lock()

    @property
    def active(self) -> bool:
        """Whether this exact in-memory capability may still authorize dispatch."""

        with self._lock:
            return self._active

    def require_valid(self, binding: StageControllerBinding) -> None:
        """Fail unless this live token is bound to the exact persistent controller."""

        binding.verify_integrity()
        with self._lock:
            if not self._active:
                raise TemporaryAgentContractError("stage dispatch capability has been revoked")
            if not hmac.compare_digest(self._binding_hash, binding.binding_hash):
                raise TemporaryAgentContractError(
                    "stage dispatch capability belongs to another controller binding"
                )
            if not hmac.compare_digest(_sha256_text(self._lease_token), binding.lease_token_hash):
                raise TemporaryAgentContractError("stage dispatch lease token mismatch")

    def revoke(self) -> None:
        """Permanently disable this in-memory capability."""

        with self._lock:
            self._active = False
            self._lease_token = ""

    def __getstate__(self) -> None:
        raise TypeError("stage dispatch capabilities are in-memory and not serializable")

    def __reduce__(self) -> NoReturn:
        raise TypeError("stage dispatch capabilities are in-memory and not serializable")

    def __repr__(self) -> str:
        return (
            "StageDispatchCapability("
            f"binding_hash={self._binding_hash!r}, active={self.active!r}, token=<hidden>)"
        )


def issue_stage_controller(
    *,
    lineage_id: str,
    stage: str,
    stage_attempt: int,
    controller_agent_id: str,
    stage_input_hash: str,
    max_parallel_agents: int,
    claimed_at: datetime | None = None,
    lease_token: str | None = None,
) -> tuple[StageControllerBinding, StageDispatchCapability]:
    """Issue one hash-bound controller record and its non-persistent bearer token."""

    raw_token = lease_token or secrets.token_urlsafe(32)
    if len(raw_token) < 16:
        raise TemporaryAgentContractError(
            "stage dispatch lease token must contain at least 16 characters"
        )
    content = _StageControllerBindingContent(
        lineage_id=lineage_id,
        stage=stage,
        stage_attempt=stage_attempt,
        controller_agent_id=controller_agent_id,
        stage_input_hash=stage_input_hash,
        lease_token_hash=_sha256_text(raw_token),
        max_parallel_agents=max_parallel_agents,
        claimed_at=claimed_at or _utc_now(),
    )
    payload = content.model_dump(mode="json")
    binding = StageControllerBinding(
        **payload,
        binding_hash=canonical_sha256(payload),
    )
    return binding, StageDispatchCapability(
        binding_hash=binding.binding_hash,
        lease_token=raw_token,
    )


class _TemporaryAgentAssignmentContent(_FrozenContract):
    schema_version: Literal["temporary-agent-assignment-v1"] = "temporary-agent-assignment-v1"
    dispatch_id: StableId
    temporary_agent_id: StableId
    parent_task_id: StableId
    controller_binding_hash: Sha256
    controller_agent_id: StableId
    lineage_id: StableId
    stage: StableId
    task_kind: TemporaryAgentTaskKind
    task_instruction: str = Field(min_length=1)
    input_refs: tuple[TemporaryAgentInputRef, ...] = Field(min_length=1)
    input_payload: dict[str, JsonValue]
    input_bundle_sha256: Sha256
    expected_output_schema: dict[str, JsonValue] = Field(min_length=1)
    output_schema_sha256: Sha256
    chinese_output_fields: tuple[str, ...] = Field(min_length=1)
    selected_skills: tuple[TemporaryAgentSkillRef, ...] = Field(
        default_factory=tuple,
        max_length=8,
    )
    output_language: Literal["zh-CN"] = "zh-CN"
    reasoning_required: Literal[True] = True
    minimum_reasoning_characters: int = Field(default=1, ge=1, le=100_000)
    max_tokens: int = Field(ge=1, le=100_000)
    timeout_seconds: int = Field(ge=1, le=3600)
    max_attempts: int = Field(default=1, ge=1, le=3)
    max_delegation_depth: Literal[1] = 1
    can_delegate: Literal[False] = False
    can_approve: Literal[False] = False
    can_execute: Literal[False] = False
    can_adjudicate: Literal[False] = False
    can_publish: Literal[False] = False
    can_release: Literal[False] = False
    can_promote_evidence: Literal[False] = False
    allowed_tools: tuple[str, ...] = ()
    runtime_identity_ephemeral: Literal[True] = True
    output_retention_required: Literal[True] = True
    is_scientific_evidence: Literal[False] = False

    @model_validator(mode="after")
    def _validate_boundaries(self) -> _TemporaryAgentAssignmentContent:
        if self.temporary_agent_id == self.controller_agent_id:
            raise TemporaryAgentContractError(
                "temporary runtime identity cannot equal the stage main agent"
            )
        if not _contains_chinese_text(self.task_instruction):
            raise TemporaryAgentContractError("temporary-agent task instruction must be Chinese")
        _require_unique(
            tuple(item.artifact_id for item in self.input_refs),
            label="input artifact",
        )
        _require_unique(
            tuple(item.skill_id for item in self.selected_skills),
            label="skill",
        )
        _require_unique(self.chinese_output_fields, label="Chinese output field")
        required_fields = self.expected_output_schema.get("required")
        if not isinstance(required_fields, list) or any(
            not isinstance(item, str) for item in required_fields
        ):
            raise TemporaryAgentContractError(
                "temporary-agent output schema requires a string field list"
            )
        missing_chinese_fields = set(self.chinese_output_fields).difference(required_fields)
        if missing_chinese_fields:
            raise TemporaryAgentContractError(
                "Chinese output fields must be required by the output schema"
            )
        if self.allowed_tools:
            raise TemporaryAgentContractError(
                "temporary content agents cannot receive tool permissions"
            )
        expected_input_hash = canonical_sha256(
            {
                "input_refs": [item.model_dump(mode="json") for item in self.input_refs],
                "input_payload": self.input_payload,
            }
        )
        if self.input_bundle_sha256 != expected_input_hash:
            raise TemporaryAgentContractError("temporary-agent input hash mismatch")
        if self.output_schema_sha256 != canonical_sha256(self.expected_output_schema):
            raise TemporaryAgentContractError("temporary-agent output-schema hash mismatch")
        return self


class TemporaryAgentAssignment(_TemporaryAgentAssignmentContent):
    """One immutable, content-only task issued by the current stage main agent."""

    assignment_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> TemporaryAgentAssignment:
        self.verify_integrity()
        return self

    def verify_integrity(self) -> None:
        """Recheck the assignment hash before every coordinator ingress."""

        expected = canonical_sha256(self.model_dump(mode="json", exclude={"assignment_hash"}))
        if self.assignment_hash != expected:
            raise TemporaryAgentContractError("temporary-agent assignment hash mismatch")

    @classmethod
    def create(
        cls,
        *,
        controller: StageControllerBinding,
        capability: StageDispatchCapability,
        dispatch_id: str,
        temporary_agent_id: str,
        parent_task_id: str,
        task_kind: TemporaryAgentTaskKind,
        task_instruction: str,
        input_refs: tuple[TemporaryAgentInputRef, ...],
        input_payload: dict[str, JsonValue],
        expected_output_schema: dict[str, JsonValue],
        chinese_output_fields: tuple[str, ...],
        selected_skills: tuple[TemporaryAgentSkillRef, ...],
        max_tokens: int,
        timeout_seconds: int,
        max_attempts: int = 1,
        minimum_reasoning_characters: int = 1,
    ) -> TemporaryAgentAssignment:
        """Create an assignment only after validating the main-agent bearer token."""

        capability.require_valid(controller)
        input_hash = canonical_sha256(
            {
                "input_refs": [item.model_dump(mode="json") for item in input_refs],
                "input_payload": input_payload,
            }
        )
        content = _TemporaryAgentAssignmentContent(
            dispatch_id=dispatch_id,
            temporary_agent_id=temporary_agent_id,
            parent_task_id=parent_task_id,
            controller_binding_hash=controller.binding_hash,
            controller_agent_id=controller.controller_agent_id,
            lineage_id=controller.lineage_id,
            stage=controller.stage,
            task_kind=task_kind,
            task_instruction=task_instruction,
            input_refs=input_refs,
            input_payload=input_payload,
            input_bundle_sha256=input_hash,
            expected_output_schema=expected_output_schema,
            output_schema_sha256=canonical_sha256(expected_output_schema),
            chinese_output_fields=chinese_output_fields,
            selected_skills=selected_skills,
            minimum_reasoning_characters=minimum_reasoning_characters,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
        )
        payload = content.model_dump(mode="json")
        return cls(**payload, assignment_hash=canonical_sha256(payload))


class _TemporaryAgentResultArtifactContent(_FrozenContract):
    schema_version: Literal["temporary-agent-result-v1"] = "temporary-agent-result-v1"
    dispatch_id: StableId
    temporary_agent_id: StableId
    assignment_hash: Sha256
    input_bundle_sha256: Sha256
    output_schema_sha256: Sha256
    output_payload: dict[str, JsonValue] = Field(min_length=1)
    output_payload_sha256: Sha256
    authorship_receipt_relative_path: str = Field(min_length=1)
    authorship_receipt_hash: Sha256
    model_name: str = Field(min_length=1)
    reasoning_character_count: int = Field(ge=0)
    reasoning_is_evidence: Literal[False] = False
    authored_by_model: Literal[True] = True
    hand_written_scientific_prose_count: Literal[0] = 0
    is_scientific_evidence: Literal[False] = False
    delegation_authorized: Literal[False] = False
    approval_authorized: Literal[False] = False
    execution_authorized: Literal[False] = False
    adjudication_authorized: Literal[False] = False
    publication_authorized: Literal[False] = False
    release_authorized: Literal[False] = False
    evidence_promotion_authorized: Literal[False] = False
    created_at: datetime = Field(default_factory=_utc_now)

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @field_validator("authorship_receipt_relative_path")
    @classmethod
    def _validate_receipt_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        path = PurePosixPath(normalized)
        if (
            path.is_absolute()
            or path == PurePosixPath(".")
            or ".." in path.parts
            or "\x00" in normalized
            or any(":" in part for part in path.parts)
        ):
            raise ValueError("authorship receipt must remain inside the task archive")
        return path.as_posix()

    @model_validator(mode="after")
    def _validate_output_hash(self) -> _TemporaryAgentResultArtifactContent:
        if self.output_payload_sha256 != canonical_sha256(self.output_payload):
            raise TemporaryAgentContractError("temporary-agent output hash mismatch")
        return self


class TemporaryAgentResultArtifact(_TemporaryAgentResultArtifactContent):
    """Exact model-derived output plus its immutable provider receipt binding."""

    result_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> TemporaryAgentResultArtifact:
        self.verify_integrity()
        return self

    def verify_integrity(self) -> None:
        """Recheck exact output and receipt bindings before archival."""

        expected = canonical_sha256(self.model_dump(mode="json", exclude={"result_hash"}))
        if self.result_hash != expected:
            raise TemporaryAgentContractError("temporary-agent result hash mismatch")

    @classmethod
    def create(
        cls,
        *,
        assignment: TemporaryAgentAssignment,
        output_payload: dict[str, JsonValue],
        authorship_receipt_relative_path: str,
        authorship_receipt_hash: str,
        model_name: str,
        reasoning_character_count: int,
        created_at: datetime | None = None,
    ) -> TemporaryAgentResultArtifact:
        """Bind one exact parsed model response to its assignment and receipt."""

        assignment.verify_integrity()
        if reasoning_character_count < assignment.minimum_reasoning_characters:
            raise TemporaryAgentContractError(
                "temporary-agent reasoning is shorter than the assignment contract"
            )
        for field in assignment.chinese_output_fields:
            if field not in output_payload:
                raise TemporaryAgentContractError(
                    f"temporary-agent output omits required Chinese field: {field}"
                )
            if not _is_empty_json_container(output_payload[field]) and not _contains_chinese_text(
                output_payload[field]
            ):
                raise TemporaryAgentContractError(
                    f"temporary-agent output field must contain Chinese text: {field}"
                )
        content = _TemporaryAgentResultArtifactContent(
            dispatch_id=assignment.dispatch_id,
            temporary_agent_id=assignment.temporary_agent_id,
            assignment_hash=assignment.assignment_hash,
            input_bundle_sha256=assignment.input_bundle_sha256,
            output_schema_sha256=assignment.output_schema_sha256,
            output_payload=output_payload,
            output_payload_sha256=canonical_sha256(output_payload),
            authorship_receipt_relative_path=authorship_receipt_relative_path,
            authorship_receipt_hash=authorship_receipt_hash,
            model_name=model_name,
            reasoning_character_count=reasoning_character_count,
            created_at=created_at or _utc_now(),
        )
        payload = content.model_dump(mode="json")
        return cls(**payload, result_hash=canonical_sha256(payload))


class _TemporaryAgentArchiveRecordContent(_FrozenContract):
    schema_version: Literal["temporary-agent-archive-v1"] = "temporary-agent-archive-v1"
    dispatch_id: StableId
    temporary_agent_id: StableId
    controller_binding_hash: Sha256
    assignment_hash: Sha256
    terminal_status: TemporaryAgentTerminalStatus
    result_hash: Sha256 | None = None
    authorship_receipt_hash: Sha256 | None = None
    runtime_identity_inactive: Literal[True] = True
    runtime_identity_removed: Literal[True] = True
    output_retained: Literal[True] = True
    output_retention_required: Literal[True] = True
    delegation_capability_was_granted: Literal[False] = False
    approval_authorized: Literal[False] = False
    execution_authorized: Literal[False] = False
    adjudication_authorized: Literal[False] = False
    publication_authorized: Literal[False] = False
    release_authorized: Literal[False] = False
    evidence_promotion_authorized: Literal[False] = False
    archived_at: datetime = Field(default_factory=_utc_now)

    @field_validator("archived_at")
    @classmethod
    def _validate_archived_at(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def _validate_terminal_binding(self) -> _TemporaryAgentArchiveRecordContent:
        if self.terminal_status is TemporaryAgentTerminalStatus.SUCCEEDED and (
            self.result_hash is None or self.authorship_receipt_hash is None
        ):
            raise TemporaryAgentContractError(
                "a successful temporary agent requires a retained result and receipt"
            )
        if (self.result_hash is None) != (self.authorship_receipt_hash is None):
            raise TemporaryAgentContractError(
                "temporary result and authorship receipt must be retained together"
            )
        return self


class TemporaryAgentArchiveRecord(_TemporaryAgentArchiveRecordContent):
    """Terminal proof that runtime identity vanished while task bytes were retained."""

    archive_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> TemporaryAgentArchiveRecord:
        self.verify_integrity()
        return self

    def verify_integrity(self) -> None:
        """Recheck terminal state and retained-artifact bindings."""

        expected = canonical_sha256(self.model_dump(mode="json", exclude={"archive_hash"}))
        if self.archive_hash != expected:
            raise TemporaryAgentContractError("temporary-agent archive hash mismatch")

    @classmethod
    def create(
        cls,
        *,
        controller: StageControllerBinding,
        capability: StageDispatchCapability,
        assignment: TemporaryAgentAssignment,
        terminal_status: TemporaryAgentTerminalStatus,
        result: TemporaryAgentResultArtifact | None,
        archived_at: datetime | None = None,
    ) -> TemporaryAgentArchiveRecord:
        """Create an archive record without deleting any assignment or result bytes."""

        capability.require_valid(controller)
        assignment.verify_integrity()
        if assignment.controller_binding_hash != controller.binding_hash:
            raise TemporaryAgentContractError(
                "temporary assignment belongs to another stage controller"
            )
        if terminal_status is TemporaryAgentTerminalStatus.SUCCEEDED and result is None:
            raise TemporaryAgentContractError(
                "a successful temporary agent requires a retained result and receipt"
            )
        if result is not None:
            _require_result_matches_assignment(result, assignment)
        content = _TemporaryAgentArchiveRecordContent(
            dispatch_id=assignment.dispatch_id,
            temporary_agent_id=assignment.temporary_agent_id,
            controller_binding_hash=controller.binding_hash,
            assignment_hash=assignment.assignment_hash,
            terminal_status=terminal_status,
            result_hash=result.result_hash if result is not None else None,
            authorship_receipt_hash=(
                result.authorship_receipt_hash if result is not None else None
            ),
            archived_at=archived_at or _utc_now(),
        )
        payload = content.model_dump(mode="json")
        return cls(**payload, archive_hash=canonical_sha256(payload))


class TemporaryAgentBatchEntry(_FrozenContract):
    """One stable dispatch/result/archive binding inside a batch manifest."""

    dispatch_id: StableId
    temporary_agent_id: StableId
    assignment_hash: Sha256
    terminal_status: TemporaryAgentTerminalStatus
    result_hash: Sha256 | None = None
    output_payload_sha256: Sha256 | None = None
    archive_hash: Sha256

    @model_validator(mode="after")
    def _validate_result_fields(self) -> TemporaryAgentBatchEntry:
        if (self.result_hash is None) != (self.output_payload_sha256 is None):
            raise TemporaryAgentContractError(
                "batch result hash and output hash must be present together"
            )
        if (
            self.terminal_status is TemporaryAgentTerminalStatus.SUCCEEDED
            and self.result_hash is None
        ):
            raise TemporaryAgentContractError("successful batch entries require a retained result")
        return self


class _TemporaryAgentBatchManifestContent(_FrozenContract):
    schema_version: Literal["temporary-agent-batch-manifest-v1"] = (
        "temporary-agent-batch-manifest-v1"
    )
    batch_id: StableId
    lineage_id: StableId
    stage: StableId
    controller_binding_hash: Sha256
    entries: tuple[TemporaryAgentBatchEntry, ...] = Field(min_length=1)
    dispatched_count: int = Field(ge=1)
    succeeded_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    cancelled_count: int = Field(ge=0)
    blocked_count: int = Field(ge=0)
    stable_merged_output_sha256: Sha256
    all_assignments_archived: Literal[True] = True
    all_runtime_identities_inactive: Literal[True] = True
    outputs_retained: Literal[True] = True
    evidence_gate_bypassed: Literal[False] = False
    approval_gate_bypassed: Literal[False] = False
    safety_gate_bypassed: Literal[False] = False
    independent_review_bypassed: Literal[False] = False
    created_at: datetime = Field(default_factory=_utc_now)

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def _validate_batch(self) -> _TemporaryAgentBatchManifestContent:
        stable_entries = tuple(sorted(self.entries, key=lambda item: item.dispatch_id))
        if self.entries != stable_entries:
            raise TemporaryAgentContractError(
                "temporary-agent batch entries must use stable dispatch order"
            )
        _require_unique(tuple(item.dispatch_id for item in self.entries), label="dispatch")
        _require_unique(
            tuple(item.temporary_agent_id for item in self.entries),
            label="runtime identity",
        )
        expected_counts = {
            status: sum(item.terminal_status is status for item in self.entries)
            for status in TemporaryAgentTerminalStatus
        }
        if self.dispatched_count != len(self.entries):
            raise TemporaryAgentContractError("temporary-agent batch count mismatch")
        if self.succeeded_count != expected_counts[TemporaryAgentTerminalStatus.SUCCEEDED]:
            raise TemporaryAgentContractError("temporary-agent success count mismatch")
        if self.failed_count != expected_counts[TemporaryAgentTerminalStatus.FAILED]:
            raise TemporaryAgentContractError("temporary-agent failure count mismatch")
        if self.cancelled_count != expected_counts[TemporaryAgentTerminalStatus.CANCELLED]:
            raise TemporaryAgentContractError("temporary-agent cancellation count mismatch")
        if self.blocked_count != expected_counts[TemporaryAgentTerminalStatus.BLOCKED]:
            raise TemporaryAgentContractError("temporary-agent blocked count mismatch")
        expected_output_hash = canonical_sha256(
            [
                {
                    "dispatch_id": item.dispatch_id,
                    "output_payload_sha256": item.output_payload_sha256,
                }
                for item in self.entries
                if item.terminal_status is TemporaryAgentTerminalStatus.SUCCEEDED
            ]
        )
        if self.stable_merged_output_sha256 != expected_output_hash:
            raise TemporaryAgentContractError("temporary-agent stable output hash mismatch")
        return self


class TemporaryAgentBatchManifest(_TemporaryAgentBatchManifestContent):
    """Stable terminal summary for a set of parallel one-shot content agents."""

    batch_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> TemporaryAgentBatchManifest:
        self.verify_integrity()
        return self

    def verify_integrity(self) -> None:
        """Recheck the stable batch address before downstream consumption."""

        expected = canonical_sha256(self.model_dump(mode="json", exclude={"batch_hash"}))
        if self.batch_hash != expected:
            raise TemporaryAgentContractError("temporary-agent batch hash mismatch")


class TemporaryAgentArchiveCoordinator:
    """Thread-safe in-memory coordinator for stable dispatch and terminal archiving.

    The coordinator never invokes a model and never authors task content.  Callers
    persist the returned immutable models using their existing artifact store.
    """

    def __init__(self, controller: StageControllerBinding) -> None:
        self.controller = controller
        self._assignments: dict[str, TemporaryAgentAssignment] = {}
        self._results: dict[str, TemporaryAgentResultArtifact] = {}
        self._archives: dict[str, TemporaryAgentArchiveRecord] = {}
        self._active_agent_ids: set[str] = set()
        self._closed = False
        self._lock = threading.RLock()

    @property
    def active_agent_ids(self) -> tuple[str, ...]:
        """Return active ephemeral runtime identities in deterministic order."""

        with self._lock:
            return tuple(sorted(self._active_agent_ids))

    def archive_record(self, dispatch_id: str) -> TemporaryAgentArchiveRecord:
        """Return a detached immutable archive record for persistence recovery."""

        with self._lock:
            try:
                archive = self._archives[dispatch_id]
            except KeyError as exc:
                raise TemporaryAgentContractError(
                    f"temporary dispatch is not archived: {dispatch_id}"
                ) from exc
            return TemporaryAgentArchiveRecord.model_validate(archive.model_dump(mode="json"))

    def dispatch(
        self,
        assignment: TemporaryAgentAssignment,
        *,
        capability: StageDispatchCapability,
    ) -> None:
        """Register one bounded assignment after checking main-agent authority."""

        with self._lock:
            self._require_open(capability)
            assignment.verify_integrity()
            assignment_snapshot = TemporaryAgentAssignment.model_validate(
                assignment.model_dump(mode="json")
            )
            if len(self._active_agent_ids) >= self.controller.max_parallel_agents:
                raise TemporaryAgentContractError(
                    "temporary-agent parallelism exceeds the controller contract"
                )
            if assignment_snapshot.controller_binding_hash != self.controller.binding_hash:
                raise TemporaryAgentContractError(
                    "temporary assignment belongs to another controller"
                )
            if (
                assignment_snapshot.lineage_id != self.controller.lineage_id
                or assignment_snapshot.stage != self.controller.stage
            ):
                raise TemporaryAgentContractError(
                    "temporary assignment escapes the current lineage stage"
                )
            if assignment_snapshot.dispatch_id in self._assignments:
                raise TemporaryAgentContractError(
                    "temporary dispatch already exists: " f"{assignment_snapshot.dispatch_id}"
                )
            if any(
                item.temporary_agent_id == assignment_snapshot.temporary_agent_id
                for item in self._assignments.values()
            ):
                raise TemporaryAgentContractError(
                    "temporary runtime identity is already used in this batch"
                )
            self._assignments[assignment_snapshot.dispatch_id] = assignment_snapshot
            self._active_agent_ids.add(assignment_snapshot.temporary_agent_id)

    def record_result(
        self,
        result: TemporaryAgentResultArtifact,
        *,
        capability: StageDispatchCapability,
    ) -> None:
        """Attach one structurally valid result while the runtime identity is active."""

        with self._lock:
            self._require_open(capability)
            result.verify_integrity()
            result_snapshot = TemporaryAgentResultArtifact.model_validate(
                result.model_dump(mode="json")
            )
            assignment = self._assignment_for(result_snapshot.dispatch_id)
            if result_snapshot.dispatch_id in self._archives:
                raise TemporaryAgentContractError(
                    "cannot attach a result after temporary-agent archival"
                )
            if result_snapshot.dispatch_id in self._results:
                raise TemporaryAgentContractError("temporary-agent result is already recorded")
            if assignment.temporary_agent_id not in self._active_agent_ids:
                raise TemporaryAgentContractError("temporary runtime identity is no longer active")
            _require_result_matches_assignment(result_snapshot, assignment)
            self._results[result_snapshot.dispatch_id] = result_snapshot

    def archive(
        self,
        dispatch_id: str,
        *,
        terminal_status: TemporaryAgentTerminalStatus,
        capability: StageDispatchCapability,
        archived_at: datetime | None = None,
    ) -> TemporaryAgentArchiveRecord:
        """Remove the runtime identity and retain immutable assignment/result bindings."""

        with self._lock:
            self._require_open(capability)
            assignment = self._assignment_for(dispatch_id)
            if dispatch_id in self._archives:
                raise TemporaryAgentContractError("temporary agent is already archived")
            result = self._results.get(dispatch_id)
            archive = TemporaryAgentArchiveRecord.create(
                controller=self.controller,
                capability=capability,
                assignment=assignment,
                terminal_status=terminal_status,
                result=result,
                archived_at=archived_at,
            )
            self._active_agent_ids.discard(assignment.temporary_agent_id)
            self._archives[dispatch_id] = archive
            return archive

    def stable_outputs(self) -> tuple[dict[str, JsonValue], ...]:
        """Return successful outputs in dispatch order without writing merge prose."""

        with self._lock:
            outputs = [
                self._results[dispatch_id].output_payload
                for dispatch_id, archive in sorted(self._archives.items())
                if archive.terminal_status is TemporaryAgentTerminalStatus.SUCCEEDED
            ]
            return tuple(copy.deepcopy(outputs))

    def build_manifest(
        self,
        *,
        batch_id: str,
        capability: StageDispatchCapability,
        created_at: datetime | None = None,
    ) -> TemporaryAgentBatchManifest:
        """Seal the batch only after every runtime identity has been archived."""

        return self._build_manifest(
            batch_id=batch_id,
            capability=capability,
            created_at=created_at,
            finalize_capability=True,
        )

    def build_intermediate_manifest(
        self,
        *,
        batch_id: str,
        capability: StageDispatchCapability,
        created_at: datetime | None = None,
    ) -> TemporaryAgentBatchManifest:
        """Seal one phase batch while its main-agent stage session remains open.

        Callers must pair this with an explicit finite phase state machine.  The
        returned manifest proves only that this batch is terminal; it does not
        claim that the enclosing research stage or its capability is complete.
        """

        return self._build_manifest(
            batch_id=batch_id,
            capability=capability,
            created_at=created_at,
            finalize_capability=False,
        )

    def _build_manifest(
        self,
        *,
        batch_id: str,
        capability: StageDispatchCapability,
        created_at: datetime | None,
        finalize_capability: bool,
    ) -> TemporaryAgentBatchManifest:
        """Build one terminal batch manifest with explicit capability finality."""

        with self._lock:
            self._require_open(capability)
            if not self._assignments:
                raise TemporaryAgentContractError("temporary-agent batch cannot be empty")
            if self._active_agent_ids:
                raise TemporaryAgentContractError(
                    "temporary-agent batch still has active runtime identities"
                )
            if set(self._archives) != set(self._assignments):
                raise TemporaryAgentContractError(
                    "temporary-agent batch contains unarchived assignments"
                )
            entries = tuple(
                self._batch_entry(dispatch_id) for dispatch_id in sorted(self._assignments)
            )
            counts = {
                status: sum(item.terminal_status is status for item in entries)
                for status in TemporaryAgentTerminalStatus
            }
            output_hash = canonical_sha256(
                [
                    {
                        "dispatch_id": item.dispatch_id,
                        "output_payload_sha256": item.output_payload_sha256,
                    }
                    for item in entries
                    if item.terminal_status is TemporaryAgentTerminalStatus.SUCCEEDED
                ]
            )
            content = _TemporaryAgentBatchManifestContent(
                batch_id=batch_id,
                lineage_id=self.controller.lineage_id,
                stage=self.controller.stage,
                controller_binding_hash=self.controller.binding_hash,
                entries=entries,
                dispatched_count=len(entries),
                succeeded_count=counts[TemporaryAgentTerminalStatus.SUCCEEDED],
                failed_count=counts[TemporaryAgentTerminalStatus.FAILED],
                cancelled_count=counts[TemporaryAgentTerminalStatus.CANCELLED],
                blocked_count=counts[TemporaryAgentTerminalStatus.BLOCKED],
                stable_merged_output_sha256=output_hash,
                created_at=created_at or _utc_now(),
            )
            payload = content.model_dump(mode="json")
            manifest = TemporaryAgentBatchManifest(
                **payload,
                batch_hash=canonical_sha256(payload),
            )
            self._closed = True
            if finalize_capability:
                capability.revoke()
            return manifest

    def _batch_entry(self, dispatch_id: str) -> TemporaryAgentBatchEntry:
        assignment = self._assignments[dispatch_id]
        archive = self._archives[dispatch_id]
        result = self._results.get(dispatch_id)
        return TemporaryAgentBatchEntry(
            dispatch_id=dispatch_id,
            temporary_agent_id=assignment.temporary_agent_id,
            assignment_hash=assignment.assignment_hash,
            terminal_status=archive.terminal_status,
            result_hash=result.result_hash if result is not None else None,
            output_payload_sha256=(result.output_payload_sha256 if result is not None else None),
            archive_hash=archive.archive_hash,
        )

    def _assignment_for(self, dispatch_id: str) -> TemporaryAgentAssignment:
        try:
            return self._assignments[dispatch_id]
        except KeyError as exc:
            raise TemporaryAgentContractError(
                f"temporary dispatch is not registered: {dispatch_id}"
            ) from exc

    def _require_open(self, capability: StageDispatchCapability) -> None:
        if self._closed:
            raise TemporaryAgentContractError("temporary-agent batch is closed")
        capability.require_valid(self.controller)


def _require_result_matches_assignment(
    result: TemporaryAgentResultArtifact,
    assignment: TemporaryAgentAssignment,
) -> None:
    result.verify_integrity()
    assignment.verify_integrity()
    if (
        result.dispatch_id != assignment.dispatch_id
        or result.temporary_agent_id != assignment.temporary_agent_id
        or result.assignment_hash != assignment.assignment_hash
        or result.input_bundle_sha256 != assignment.input_bundle_sha256
        or result.output_schema_sha256 != assignment.output_schema_sha256
    ):
        raise TemporaryAgentContractError(
            "temporary-agent result does not bind the exact assignment"
        )
    if result.reasoning_character_count < assignment.minimum_reasoning_characters:
        raise TemporaryAgentContractError(
            "temporary-agent result violates the reasoning-length contract"
        )


__all__ = [
    "StageControllerBinding",
    "StageDispatchCapability",
    "TemporaryAgentArchiveCoordinator",
    "TemporaryAgentArchiveRecord",
    "TemporaryAgentAssignment",
    "TemporaryAgentBatchEntry",
    "TemporaryAgentBatchManifest",
    "TemporaryAgentContractError",
    "TemporaryAgentInputRef",
    "TemporaryAgentResultArtifact",
    "TemporaryAgentSkillRef",
    "TemporaryAgentTaskKind",
    "TemporaryAgentTerminalStatus",
    "issue_stage_controller",
]
