"""Task-aware semantic context compaction for autonomous model loops.

Only conversations belonging to already completed tasks are eligible for
semantic summarisation.  The active task is always carried byte-for-byte.  Raw
transcripts remain in sovereign local memory; a Qwen-authored merged summary is
only a rebuildable working-context projection.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from autoresearch.config.models import SystemConfig
from autoresearch.config.parser import ConfigParser
from autoresearch.kernel import SensitiveContentError, validate_persistable_content
from autoresearch.kernel.contracts import (
    KernelContract,
    Sha256,
    StableId,
    canonical_json,
    canonical_sha256,
)
from autoresearch.knowledge.raw_memory import (
    RawMemoryBinding,
    RawMemorySourceKind,
    RawMemoryStore,
)
from autoresearch.llm.client import (
    LLMJsonCompletionResult,
    resolve_thinking_configuration,
    run_llm_json_completion,
)
from autoresearch.llm.model_capabilities import (
    ModelContextBudget,
    OfficialModelCapability,
    build_model_context_budget,
    load_official_model_capability,
)

_CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class TaskContextError(RuntimeError):
    """Raised when active-task preservation or context provenance fails."""


JSONCompletion = Callable[..., LLMJsonCompletionResult]


def _normalize_messages(
    messages: Sequence[Mapping[str, str]],
) -> tuple[dict[str, str], ...]:
    normalized: list[dict[str, str]] = []
    for item in messages:
        role = item.get("role")
        content = item.get("content")
        if role not in {"system", "user", "assistant"} or not isinstance(content, str):
            raise TaskContextError("task context messages require text system/user/assistant roles")
        normalized.append({"role": role, "content": content})
    if not normalized:
        raise TaskContextError("task context cannot be empty")
    if sum(item["role"] == "system" for item in normalized) > 1:
        raise TaskContextError("a task context accepts at most one system message")
    return tuple(normalized)


def _require_provider_safe_messages(messages: Sequence[Mapping[str, str]]) -> None:
    """Fail before persistence/provider dispatch; never echo the matched literal."""

    try:
        validate_persistable_content({"messages": [dict(item) for item in messages]})
    except SensitiveContentError as exc:
        raise TaskContextError(
            "task context blocked sensitive content before provider dispatch"
        ) from exc


class PromptTokenCalibration(KernelContract):
    """One exact provider usage sample used only to improve pre-call estimation."""

    schema_version: Literal["prompt-token-calibration-v1"] = "prompt-token-calibration-v1"
    request_character_count: int = Field(ge=1)
    provider_prompt_tokens: int = Field(ge=1)
    source: Literal["provider_usage"] = "provider_usage"
    calibration_hash: Sha256

    @model_validator(mode="after")
    def _verify(self) -> PromptTokenCalibration:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"calibration_hash"}))
        if self.calibration_hash != expected:
            raise ValueError("prompt-token calibration hash mismatch")
        return self

    @classmethod
    def create(
        cls, *, messages: Sequence[Mapping[str, str]], provider_prompt_tokens: int
    ) -> PromptTokenCalibration:
        characters = _message_character_count(messages)
        payload = {
            "schema_version": "prompt-token-calibration-v1",
            "request_character_count": characters,
            "provider_prompt_tokens": provider_prompt_tokens,
            "source": "provider_usage",
        }
        payload["calibration_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)


class ContextTokenEstimate(KernelContract):
    """Transparent pre-call estimate; it never masquerades as provider usage."""

    schema_version: Literal["context-token-estimate-v1"] = "context-token-estimate-v1"
    estimated_input_tokens: int = Field(ge=1)
    character_count: int = Field(ge=1)
    message_count: int = Field(ge=1)
    method: Literal[
        "unicode_conservative_estimate",
        "provider_usage_calibrated_estimate",
    ]
    calibration_hashes: tuple[Sha256, ...] = ()
    estimate_hash: Sha256

    @model_validator(mode="after")
    def _verify(self) -> ContextTokenEstimate:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"estimate_hash"}))
        if self.estimate_hash != expected:
            raise ValueError("context token estimate hash mismatch")
        return self


class CompletedTaskConversation(KernelContract):
    """One finished task transcript captured before it can be summarized."""

    schema_version: Literal["completed-task-conversation-v1"] = "completed-task-conversation-v1"
    conversation_id: StableId
    task_group_id: StableId
    task_id: StableId
    task_sequence: int = Field(ge=1)
    task_status: Literal["completed"] = "completed"
    request_messages: tuple[dict[str, str], ...] = Field(min_length=1)
    response_text: str
    reasoning_text: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    raw_binding: RawMemoryBinding
    task_hash: Sha256

    @field_validator("conversation_id", "task_group_id", "task_id")
    @classmethod
    def _safe_ids(cls, value: str) -> str:
        if not _SAFE_ID_PATTERN.fullmatch(value):
            raise ValueError("conversation/task id is not a safe stable identifier")
        return value

    @model_validator(mode="after")
    def _verify_task(self) -> CompletedTaskConversation:
        _normalize_messages(self.request_messages)
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"task_hash"}))
        if self.task_hash != expected:
            raise ValueError("completed task conversation hash mismatch")
        return self


class ActiveTaskConversation(KernelContract):
    """The currently executing task, which may never enter the summary prompt."""

    schema_version: Literal["active-task-conversation-v1"] = "active-task-conversation-v1"
    conversation_id: StableId
    task_id: StableId
    task_sequence: int = Field(ge=1)
    task_status: Literal["active"] = "active"
    request_messages: tuple[dict[str, str], ...] = Field(min_length=1)
    task_hash: Sha256

    @field_validator("conversation_id", "task_id")
    @classmethod
    def _safe_ids(cls, value: str) -> str:
        if not _SAFE_ID_PATTERN.fullmatch(value):
            raise ValueError("conversation/task id is not a safe stable identifier")
        return value

    @model_validator(mode="after")
    def _verify_task(self) -> ActiveTaskConversation:
        _normalize_messages(self.request_messages)
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"task_hash"}))
        if self.task_hash != expected:
            raise ValueError("active task conversation hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        conversation_id: str,
        task_id: str,
        task_sequence: int,
        request_messages: Sequence[Mapping[str, str]],
    ) -> ActiveTaskConversation:
        payload = {
            "schema_version": "active-task-conversation-v1",
            "conversation_id": conversation_id,
            "task_id": task_id,
            "task_sequence": task_sequence,
            "task_status": "active",
            "request_messages": list(_normalize_messages(request_messages)),
        }
        payload["task_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)


class MergedCompletedTaskSummary(KernelContract):
    """Qwen-authored Chinese working memory for all summarized completed tasks."""

    completed_task_ids: tuple[StableId, ...] = Field(min_length=1)
    summary_cn: str = Field(min_length=20, max_length=100_000)
    unfinished_handoffs_cn: tuple[str, ...] = ()

    @field_validator("summary_cn")
    @classmethod
    def _require_chinese_summary(cls, value: str) -> str:
        if len(_CJK_PATTERN.findall(value)) < 20:
            raise ValueError("completed-task summary must be substantive Chinese text")
        return value

    @field_validator("unfinished_handoffs_cn")
    @classmethod
    def _require_chinese_handoffs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for item in value:
            if item and not _CJK_PATTERN.search(item):
                raise ValueError("summary handoffs must be Chinese when present")
        return value


class TaskContextPreparationArtifact(KernelContract):
    """Hash-bound proof of what was summarized and what was sent verbatim."""

    schema_version: Literal["task-context-preparation-v1"] = "task-context-preparation-v1"
    conversation_id: StableId
    active_task_id: StableId
    active_task_hash: Sha256
    active_task_messages_sha256: Sha256
    completed_task_ids: tuple[StableId, ...]
    completed_task_hashes: tuple[Sha256, ...]
    completed_raw_bindings: tuple[RawMemoryBinding, ...]
    capability: OfficialModelCapability
    budget: ModelContextBudget
    before_estimate: ContextTokenEstimate
    after_estimate: ContextTokenEstimate
    history_mode: Literal["raw_completed_tasks", "merged_semantic_summary"]
    compression_triggered: bool
    merged_summary: MergedCompletedTaskSummary | None = None
    summary_request_messages: tuple[dict[str, str], ...] | None = None
    summary_request_messages_sha256: Sha256 | None = None
    summary_response_text: str | None = None
    summary_response_sha256: Sha256 | None = None
    summary_model_name: str | None = None
    summary_raw_binding: RawMemoryBinding | None = None
    delivered_messages: tuple[dict[str, str], ...] = Field(min_length=1)
    delivered_messages_sha256: Sha256
    active_task_preserved_verbatim: Literal[True] = True
    active_task_excluded_from_summary: Literal[True] = True
    raw_completed_conversations_retained: Literal[True] = True
    summary_is_derived_non_evidence: Literal[True] = True
    created_at: datetime
    artifact_hash: Sha256
    output_path: str

    @model_validator(mode="after")
    def _verify_artifact(self) -> TaskContextPreparationArtifact:
        if self.delivered_messages_sha256 != canonical_sha256(
            {"messages": list(self.delivered_messages)}
        ):
            raise ValueError("delivered context hash mismatch")
        summary_fields = (
            self.merged_summary,
            self.summary_request_messages,
            self.summary_request_messages_sha256,
            self.summary_response_text,
            self.summary_response_sha256,
            self.summary_model_name,
            self.summary_raw_binding,
        )
        if self.compression_triggered != all(item is not None for item in summary_fields):
            raise ValueError("semantic-summary fields do not match compression state")
        if self.compression_triggered:
            assert self.merged_summary is not None
            assert self.summary_request_messages is not None
            assert self.summary_request_messages_sha256 is not None
            assert self.summary_response_text is not None
            assert self.summary_response_sha256 is not None
            if self.history_mode != "merged_semantic_summary":
                raise ValueError("compressed context does not use its merged summary")
            if self.merged_summary.completed_task_ids != self.completed_task_ids:
                raise ValueError("merged summary does not cover exactly the completed tasks")
            if self.active_task_id in self.merged_summary.completed_task_ids:
                raise ValueError("active task was included in completed-task summary")
            if self.summary_request_messages_sha256 != canonical_sha256(
                {"messages": list(self.summary_request_messages)}
            ):
                raise ValueError("summary request hash mismatch")
            if (
                self.summary_response_sha256
                != hashlib.sha256(self.summary_response_text.encode("utf-8")).hexdigest()
            ):
                raise ValueError("summary response hash mismatch")
        elif self.history_mode != "raw_completed_tasks":
            raise ValueError("uncompressed context must retain raw completed tasks")
        expected = canonical_sha256(
            self.model_dump(mode="json", exclude={"artifact_hash", "output_path"})
        )
        if self.artifact_hash != expected:
            raise ValueError("task context preparation artifact hash mismatch")
        return self


@dataclass(frozen=True)
class PreparedTaskContext:
    messages: list[dict[str, str]]
    artifact: TaskContextPreparationArtifact
    artifact_path: Path


def estimate_context_tokens(
    messages: Sequence[Mapping[str, str]],
    *,
    calibrations: Sequence[PromptTokenCalibration] = (),
) -> ContextTokenEstimate:
    """Estimate pre-call tokens while clearly distinguishing estimates from usage."""

    normalized = _normalize_messages(messages)
    characters = _message_character_count(normalized)
    if calibrations:
        rate = max(
            item.provider_prompt_tokens / item.request_character_count for item in calibrations
        )
        # A small fixed cushion covers chat-template drift without inventing a
        # pretend exact tokenizer.  The 20-percent context reserve remains separate.
        estimated = math.ceil(characters * rate * 1.05) + 12 * len(normalized) + 8
        method = "provider_usage_calibrated_estimate"
    else:
        # One Unicode scalar per token is a conservative cold-start approximation
        # for ordinary Chinese/English research prose.  It is replaced by exact
        # provider-usage calibration as soon as the first response is available.
        estimated = characters + 12 * len(normalized) + 8
        method = "unicode_conservative_estimate"
    payload = {
        "schema_version": "context-token-estimate-v1",
        "estimated_input_tokens": max(estimated, 1),
        "character_count": characters,
        "message_count": len(normalized),
        "method": method,
        "calibration_hashes": [item.calibration_hash for item in calibrations],
    }
    payload["estimate_hash"] = canonical_sha256(payload)
    return ContextTokenEstimate.model_validate(payload)


def capture_completed_task_conversation(
    *,
    raw_memory_store: RawMemoryStore,
    project_id: str,
    conversation_id: str,
    task_id: str,
    task_sequence: int,
    request_messages: Sequence[Mapping[str, str]],
    completion: LLMJsonCompletionResult,
    captured_at: datetime | None = None,
) -> CompletedTaskConversation:
    """Capture exact completed-task dialogue before any semantic compaction."""

    normalized = _normalize_messages(request_messages)
    transcript = {
        "schema_version": "completed-task-transcript-v1",
        "conversation_id": conversation_id,
        "task_id": task_id,
        "task_sequence": task_sequence,
        "task_status": "completed",
        "request_messages": list(normalized),
        "response_text": completion.response_text,
        "reasoning_text": completion.reasoning_text,
        "usage": completion.usage,
        "provider": completion.provider,
        "model_name": completion.model_name,
    }
    capture = raw_memory_store.capture_text(
        canonical_json(transcript),
        project_id=project_id,
        source_kind=RawMemorySourceKind.MODEL_TRANSCRIPT,
        source_label=f"已完成任务对话 {task_id}",
        source_ref=f"conversation:{conversation_id}:completed-task:{task_id}",
        original_name=f"{task_sequence:06d}-{task_id}.json",
        source_authorized=True,
        sensitive_content_reviewed=True,
        captured_at=captured_at,
    )
    payload = {
        "schema_version": "completed-task-conversation-v1",
        "conversation_id": conversation_id,
        "task_group_id": task_id,
        "task_id": task_id,
        "task_sequence": task_sequence,
        "task_status": "completed",
        "request_messages": list(normalized),
        "response_text": completion.response_text,
        "reasoning_text": completion.reasoning_text,
        "usage": completion.usage,
        "raw_binding": capture.binding(raw_memory_store.vault_root).model_dump(mode="json"),
    }
    payload["task_hash"] = canonical_sha256(payload)
    return CompletedTaskConversation.model_validate(payload)


def prepare_task_aware_context(
    *,
    active_task: ActiveTaskConversation,
    completed_tasks: Sequence[CompletedTaskConversation],
    capability: OfficialModelCapability,
    budget: ModelContextBudget,
    output_dir: Path | str,
    raw_memory_store: RawMemoryStore,
    project_id: str,
    summary_completion: JSONCompletion = run_llm_json_completion,
    summary_config_path: Path | str = Path("config.yaml"),
    summary_env_path: Path | str = Path(".env"),
    calibrations: Sequence[PromptTokenCalibration] = (),
    clock: datetime | None = None,
) -> PreparedTaskContext:
    """Keep the active task exact and semantically merge only finished tasks."""

    ordered = tuple(sorted(completed_tasks, key=lambda item: item.task_sequence))
    if any(item.conversation_id != active_task.conversation_id for item in ordered):
        raise TaskContextError("completed task belongs to another conversation")
    if any(item.task_sequence >= active_task.task_sequence for item in ordered):
        raise TaskContextError("only tasks completed before the active task may be summarized")
    task_ids = tuple(item.task_id for item in ordered)
    if len(task_ids) != len(set(task_ids)):
        raise TaskContextError("completed task ids must be unique")

    history_message = _raw_completed_history_message(ordered) if ordered else None
    before_messages = _insert_history_message(active_task.request_messages, history_message)
    before_estimate = estimate_context_tokens(before_messages, calibrations=calibrations)
    should_compress = bool(ordered) and (
        before_estimate.estimated_input_tokens >= budget.compression_trigger_tokens
    )
    merged_summary: MergedCompletedTaskSummary | None = None
    summary_messages: tuple[dict[str, str], ...] | None = None
    summary_result: LLMJsonCompletionResult | None = None
    summary_binding: RawMemoryBinding | None = None

    if should_compress:
        summary_messages = _completed_task_summary_messages(ordered)
        _require_provider_safe_messages(summary_messages)
        summary_estimate = estimate_context_tokens(summary_messages, calibrations=calibrations)
        if summary_estimate.estimated_input_tokens >= budget.hard_input_limit_tokens:
            raise TaskContextError(
                "completed-task history reached the official hard input limit before a "
                "semantic checkpoint; checkpoint more frequently"
            )
        summary_result = summary_completion(
            messages=list(summary_messages),
            config_path=summary_config_path,
            env_path=summary_env_path,
            max_tokens=min(16_384, capability.maximum_output_tokens_thinking),
            temperature=0.2,
            thinking_mode="enabled",
            thinking_budget=4_000,
            response_schema=MergedCompletedTaskSummary.model_json_schema(),
            response_schema_name="merged_completed_task_summary",
        )
        try:
            merged_summary = MergedCompletedTaskSummary.model_validate(summary_result.parsed_json)
        except ValueError as exc:
            raise TaskContextError("Qwen completed-task summary is invalid") from exc
        if merged_summary.completed_task_ids != task_ids:
            raise TaskContextError(
                "Qwen summary must cover all and only the completed tasks in order"
            )
        summary_capture = raw_memory_store.capture_text(
            summary_result.response_text,
            project_id=project_id,
            source_kind=RawMemorySourceKind.MODEL_TRANSCRIPT,
            source_label="已完成任务合并语义总结的原始模型响应",
            source_ref=(
                f"conversation:{active_task.conversation_id}:summary-before:{active_task.task_id}"
            ),
            original_name=f"summary-before-{active_task.task_sequence:06d}.json",
            source_authorized=True,
            sensitive_content_reviewed=True,
            captured_at=clock,
        )
        summary_binding = summary_capture.binding(raw_memory_store.vault_root)
        delivered = _insert_history_message(
            active_task.request_messages,
            _semantic_summary_history_message(merged_summary),
        )
        history_mode = "merged_semantic_summary"
    else:
        delivered = before_messages
        history_mode = "raw_completed_tasks"

    if not _contains_active_messages_verbatim(delivered, active_task.request_messages):
        raise TaskContextError("active task messages were changed during context preparation")
    after_estimate = estimate_context_tokens(delivered, calibrations=calibrations)
    if after_estimate.estimated_input_tokens >= budget.hard_input_limit_tokens:
        raise TaskContextError("active task does not fit the official hard input limit")
    if (
        should_compress
        and after_estimate.estimated_input_tokens >= budget.compression_trigger_tokens
    ):
        raise TaskContextError(
            "completed history was summarized but the unsummarized active task still "
            "occupies at least 80% of the official context"
        )

    now = (clock or datetime.now(timezone.utc)).astimezone(timezone.utc)
    payload: dict[str, Any] = {
        "schema_version": "task-context-preparation-v1",
        "conversation_id": active_task.conversation_id,
        "active_task_id": active_task.task_id,
        "active_task_hash": active_task.task_hash,
        "active_task_messages_sha256": canonical_sha256(
            {"messages": list(active_task.request_messages)}
        ),
        "completed_task_ids": list(task_ids),
        "completed_task_hashes": [item.task_hash for item in ordered],
        "completed_raw_bindings": [item.raw_binding.model_dump(mode="json") for item in ordered],
        "capability": capability.model_dump(mode="json"),
        "budget": budget.model_dump(mode="json"),
        "before_estimate": before_estimate.model_dump(mode="json"),
        "after_estimate": after_estimate.model_dump(mode="json"),
        "history_mode": history_mode,
        "compression_triggered": should_compress,
        "merged_summary": (
            merged_summary.model_dump(mode="json") if merged_summary is not None else None
        ),
        "summary_request_messages": (
            list(summary_messages) if summary_messages is not None else None
        ),
        "summary_request_messages_sha256": (
            canonical_sha256({"messages": list(summary_messages)})
            if summary_messages is not None
            else None
        ),
        "summary_response_text": summary_result.response_text if summary_result else None,
        "summary_response_sha256": (
            hashlib.sha256(summary_result.response_text.encode("utf-8")).hexdigest()
            if summary_result
            else None
        ),
        "summary_model_name": summary_result.model_name if summary_result else None,
        "summary_raw_binding": (
            summary_binding.model_dump(mode="json") if summary_binding is not None else None
        ),
        "delivered_messages": delivered,
        "delivered_messages_sha256": canonical_sha256({"messages": delivered}),
        "active_task_preserved_verbatim": True,
        "active_task_excluded_from_summary": True,
        "raw_completed_conversations_retained": True,
        "summary_is_derived_non_evidence": True,
        "created_at": now.isoformat().replace("+00:00", "Z"),
    }
    payload["artifact_hash"] = canonical_sha256(payload)
    root = Path(output_dir).resolve()
    path = root / "context-preparations" / f"{payload['artifact_hash']}.json"
    payload["output_path"] = path.as_posix()
    artifact = TaskContextPreparationArtifact.model_validate(payload)
    _write_once_json(path, artifact)
    return PreparedTaskContext(messages=delivered, artifact=artifact, artifact_path=path)


@dataclass(frozen=True)
class _PendingTaskCall:
    call_sequence: int
    request_messages: tuple[dict[str, str], ...]
    completion: LLMJsonCompletionResult
    raw_binding: RawMemoryBinding
    calibration: PromptTokenCalibration | None


class AutonomousTaskContextSession:
    """Conversation memory with explicit, non-overlapping task boundaries.

    A task becomes summarizable only after its ``with session.task(...)`` block
    exits successfully.  Every call made inside that block remains part of the
    active task, even when it is an author/reviewer/repair turn.  Failed tasks keep
    their append-only raw records but are never promoted into completed history.
    """

    def __init__(
        self,
        *,
        project_id: str,
        conversation_id: str,
        output_dir: Path | str,
        vault_root: Path | str = Path("autoresearch-vault"),
        completion: JSONCompletion = run_llm_json_completion,
        cache_dir: Path | str = Path(".cache/autoresearch/model-capabilities"),
    ) -> None:
        if not _SAFE_ID_PATTERN.fullmatch(project_id):
            raise TaskContextError("project id is not safe")
        if not _SAFE_ID_PATTERN.fullmatch(conversation_id):
            raise TaskContextError("conversation id is not safe")
        self.project_id = project_id
        self.conversation_id = conversation_id
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.raw_memory_store = RawMemoryStore(vault_root)
        self._completion = completion
        self._cache_dir = Path(cache_dir)
        self._lock = threading.RLock()
        self._active_task_id: str | None = None

    @contextmanager
    def task(self, task_id: str) -> Iterator[AutonomousTaskContextCompletion]:
        """Open one active task and promote its calls only on successful exit."""

        if not _SAFE_ID_PATTERN.fullmatch(task_id):
            raise TaskContextError("task id is not safe")
        with self._lock:
            if self._active_task_id is not None:
                raise TaskContextError("another task is already active in this conversation")
            completed = self._load_completed_tasks()
            if any(item.task_group_id == task_id for item in completed):
                raise TaskContextError("completed task group cannot be reopened")
            self._active_task_id = task_id
        scoped = AutonomousTaskContextCompletion(session=self, task_id=task_id)
        try:
            yield scoped
        except BaseException:
            scoped._abort()
            raise
        else:
            scoped._complete()
        finally:
            with self._lock:
                self._active_task_id = None

    def _completed_root(self) -> Path:
        return self.output_dir / "completed-tasks"

    def _load_completed_tasks(self) -> tuple[CompletedTaskConversation, ...]:
        root = self._completed_root()
        if not root.exists():
            return ()
        tasks = tuple(
            CompletedTaskConversation.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(root.glob("*.json"))
        )
        sequences = [item.task_sequence for item in tasks]
        if sequences != list(range(1, len(tasks) + 1)):
            raise TaskContextError("completed task journal is missing or reordered")
        for task in tasks:
            capture = self.raw_memory_store.load_record(
                task.raw_binding.record_relative_path,
                project_id=self.project_id,
            )
            if capture.binding(self.raw_memory_store.vault_root) != task.raw_binding:
                raise TaskContextError("completed task raw-memory binding changed")
        return tasks

    def _write_completed_task(self, task: CompletedTaskConversation) -> None:
        path = self._completed_root() / f"{task.task_sequence:06d}-{task.task_id}.json"
        _write_once_json(path, task)

    def _load_calibrations(self) -> tuple[PromptTokenCalibration, ...]:
        root = self.output_dir / "token-calibrations"
        if not root.exists():
            return ()
        return tuple(
            PromptTokenCalibration.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(root.glob("*.json"))
        )

    def _write_calibration(self, sequence: int, calibration: PromptTokenCalibration) -> None:
        path = self.output_dir / "token-calibrations" / f"{sequence:06d}.json"
        _write_once_json(path, calibration)


class AutonomousTaskContextCompletion:
    """Callable bound to one currently active autonomous task."""

    _autoresearch_provider_checkpoint_owner = False

    def __init__(self, *, session: AutonomousTaskContextSession, task_id: str) -> None:
        self._session = session
        self.task_id = task_id
        self._pending: dict[int, _PendingTaskCall] = {}
        self._next_call_sequence = 1
        self._closed = False
        self._lock = threading.RLock()

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        with self._lock:
            if self._closed:
                raise TaskContextError("active task completion scope is already closed")
            call_sequence = self._next_call_sequence
            self._next_call_sequence += 1
        source_messages = kwargs.get("messages")
        if not isinstance(source_messages, list):
            raise TaskContextError("context-managed completion requires a messages list")
        normalized_source = _normalize_messages(source_messages)
        _require_provider_safe_messages(normalized_source)
        config_path = Path(kwargs.get("config_path", Path("config.yaml")))
        env_path = Path(kwargs.get("env_path", Path(".env")))
        config = (
            ConfigParser().parse_file(config_path, model_type=SystemConfig)
            if config_path.is_file()
            else SystemConfig()
        )
        if not isinstance(config, SystemConfig):
            raise TaskContextError("context-managed completion could not load SystemConfig")
        llm = config.deployment.llm
        capability = load_official_model_capability(
            provider=llm.provider,
            model_name=llm.model_name,
            cache_dir=self._session._cache_dir,
        )
        thinking_mode, thinking_budget = resolve_thinking_configuration(
            provider=capability.provider,
            model_name=capability.model_name,
            thinking_mode=kwargs.get("thinking_mode"),
            thinking_budget=kwargs.get("thinking_budget"),
        )
        if thinking_mode is None:
            raise TaskContextError("official Qwen context requires an explicit thinking mode")
        official_output = (
            capability.maximum_output_tokens_thinking
            if thinking_mode == "enabled"
            else capability.maximum_output_tokens
        )
        configured_output = kwargs.get("max_tokens")
        requested_output = int(
            min(16_384, official_output) if configured_output is None else configured_output
        )
        budget = build_model_context_budget(
            capability,
            thinking_mode=thinking_mode,
            thinking_budget=thinking_budget,
            requested_output_tokens=requested_output,
        )
        with self._session._lock:
            if self._session._active_task_id != self.task_id:
                raise TaskContextError("completion is not bound to the active task")
            completed = self._session._load_completed_tasks()
            task_sequence = max((item.task_sequence for item in completed), default=0) + 1
            active = ActiveTaskConversation.create(
                conversation_id=self._session.conversation_id,
                task_id=self.task_id,
                task_sequence=task_sequence,
                request_messages=normalized_source,
            )
            prepared = prepare_task_aware_context(
                active_task=active,
                completed_tasks=completed,
                capability=capability,
                budget=budget,
                output_dir=self._session.output_dir,
                raw_memory_store=self._session.raw_memory_store,
                project_id=self._session.project_id,
                summary_completion=self._session._completion,
                summary_config_path=config_path,
                summary_env_path=env_path,
                calibrations=self._session._load_calibrations(),
            )
        _require_provider_safe_messages(prepared.messages)
        call_kwargs = dict(kwargs)
        call_kwargs["messages"] = prepared.messages
        call_kwargs["max_tokens"] = requested_output
        call_kwargs["thinking_mode"] = thinking_mode
        call_kwargs["thinking_budget"] = thinking_budget
        result = self._session._completion(**call_kwargs)
        raw_binding = self._capture_active_call(
            call_sequence=call_sequence,
            request_messages=normalized_source,
            completion=result,
        )
        calibration = _calibration_from_result(prepared.messages, result)
        with self._lock:
            if self._closed:
                raise TaskContextError("task closed while a model call was in flight")
            self._pending[call_sequence] = _PendingTaskCall(
                call_sequence=call_sequence,
                request_messages=normalized_source,
                completion=result,
                raw_binding=raw_binding,
                calibration=calibration,
            )
        return result.model_copy(
            update={
                "request_messages_sha256": prepared.artifact.delivered_messages_sha256,
                "source_messages_sha256": canonical_sha256({"messages": list(normalized_source)}),
                "context_preparation_hash": prepared.artifact.artifact_hash,
                "context_preparation_path": prepared.artifact_path.as_posix(),
            }
        )

    def _capture_active_call(
        self,
        *,
        call_sequence: int,
        request_messages: tuple[dict[str, str], ...],
        completion: LLMJsonCompletionResult,
    ) -> RawMemoryBinding:
        transcript = {
            "schema_version": "active-task-call-transcript-v1",
            "conversation_id": self._session.conversation_id,
            "task_group_id": self.task_id,
            "call_sequence": call_sequence,
            "task_status_at_capture": "active",
            "eligible_for_completed_history": False,
            "request_messages": list(request_messages),
            "response_text": completion.response_text,
            "reasoning_text": completion.reasoning_text,
            "usage": completion.usage,
            "provider": completion.provider,
            "model_name": completion.model_name,
        }
        transcript_text = canonical_json(transcript)
        fingerprint = hashlib.sha256(transcript_text.encode("utf-8")).hexdigest()
        capture = self._session.raw_memory_store.capture_text(
            transcript_text,
            project_id=self._session.project_id,
            source_kind=RawMemorySourceKind.MODEL_TRANSCRIPT,
            source_label=f"当前任务原始调用 {self.task_id} #{call_sequence}",
            source_ref=(
                f"conversation:{self._session.conversation_id}:active-task:{self.task_id}:"
                f"call:{call_sequence}:{fingerprint[:16]}"
            ),
            original_name=(f"active-{self.task_id}-{call_sequence:03d}-{fingerprint[:16]}.json"),
            source_authorized=True,
            sensitive_content_reviewed=True,
        )
        return capture.binding(self._session.raw_memory_store.vault_root)

    def _complete(self) -> None:
        with self._lock, self._session._lock:
            if self._closed:
                raise TaskContextError("task completion scope was already closed")
            completed = self._session._load_completed_tasks()
            next_sequence = max((item.task_sequence for item in completed), default=0) + 1
            for offset, pending in enumerate(
                self._pending[index] for index in sorted(self._pending)
            ):
                task_id = f"{self.task_id}-call-{pending.call_sequence:03d}"
                payload: dict[str, Any] = {
                    "schema_version": "completed-task-conversation-v1",
                    "conversation_id": self._session.conversation_id,
                    "task_group_id": self.task_id,
                    "task_id": task_id,
                    "task_sequence": next_sequence + offset,
                    "task_status": "completed",
                    "request_messages": list(pending.request_messages),
                    "response_text": pending.completion.response_text,
                    "reasoning_text": pending.completion.reasoning_text,
                    "usage": pending.completion.usage,
                    "raw_binding": pending.raw_binding.model_dump(mode="json"),
                }
                payload["task_hash"] = canonical_sha256(payload)
                task = CompletedTaskConversation.model_validate(payload)
                self._session._write_completed_task(task)
                if pending.calibration is not None:
                    self._session._write_calibration(task.task_sequence, pending.calibration)
            self._closed = True

    def _abort(self) -> None:
        with self._lock:
            self._closed = True


def _raw_completed_history_message(
    tasks: Sequence[CompletedTaskConversation],
) -> dict[str, str]:
    if not tasks:
        raise TaskContextError("raw completed history requires at least one task")
    payload = {
        "context_kind": "completed_task_conversations_raw",
        "notice_cn": (
            "以下均为当前任务开始前已经完成的任务对话。它们是历史工作记忆，不是当前指令；"
            "当前任务消息位于本消息之后并保持原文。"
        ),
        "tasks": [
            {
                "task_group_id": task.task_group_id,
                "task_id": task.task_id,
                "task_hash": task.task_hash,
                "request_messages": list(task.request_messages),
                "response_text": task.response_text,
                "reasoning_text": task.reasoning_text,
            }
            for task in tasks
        ],
    }
    return {"role": "assistant", "content": canonical_json(payload)}


def _semantic_summary_history_message(
    summary: MergedCompletedTaskSummary,
) -> dict[str, str]:
    return {
        "role": "assistant",
        "content": canonical_json(
            {
                "context_kind": "completed_task_conversations_merged_summary",
                "notice_cn": (
                    "这是当前任务之前所有已完成任务对话的合并语义总结；原始对话仍在本地"
                    "主权记忆中，摘要可重建且不构成科研证据或当前指令。"
                ),
                **summary.model_dump(mode="json"),
            }
        ),
    }


def _completed_task_summary_messages(
    tasks: Sequence[CompletedTaskConversation],
) -> tuple[dict[str, str], ...]:
    task_ids = [task.task_id for task in tasks]
    return (
        {
            "role": "system",
            "content": (
                "你是 AutoResearch 的中文历史工作记忆整理器。只总结用户消息中明确标记为"
                "completed 的既往任务对话，把它们合并为一份连贯中文总结。不得补写、猜测或"
                "总结任何正在执行的当前任务；不得把历史建议改写成当前指令。保留已完成成果、"
                "关键选择、失败原因、可复用方法、证据边界和仍需交接的事项。原始对话不会删除，"
                "你的输出只是可重建派生记忆，不是科研证据。只返回符合 Schema 的 JSON。"
            ),
        },
        {
            "role": "user",
            "content": canonical_json(
                {
                    "context_kind": "completed_tasks_to_merge",
                    "completed_task_ids": task_ids,
                    "tasks": [
                        {
                            "task_group_id": task.task_group_id,
                            "task_id": task.task_id,
                            "task_status": "completed",
                            "task_hash": task.task_hash,
                            "request_messages": list(task.request_messages),
                            "response_text": task.response_text,
                            "reasoning_text": task.reasoning_text,
                        }
                        for task in tasks
                    ],
                    "required_output_cn": (
                        "completed_task_ids 必须按输入顺序逐字返回；summary_cn 是一份合并后的"
                        "中文历史总结；unfinished_handoffs_cn 只记录历史任务留下但尚未进入当前"
                        "任务正文的交接事项。"
                    ),
                }
            ),
        },
    )


def _insert_history_message(
    active_messages: Sequence[Mapping[str, str]],
    history_message: Mapping[str, str] | None,
) -> list[dict[str, str]]:
    active = [dict(item) for item in _normalize_messages(active_messages)]
    if history_message is None:
        return active
    history = dict(history_message)
    insertion = 1 if active[0]["role"] == "system" else 0
    return [*active[:insertion], history, *active[insertion:]]


def _contains_active_messages_verbatim(
    delivered: Sequence[Mapping[str, str]],
    active: Sequence[Mapping[str, str]],
) -> bool:
    delivered_list = [dict(item) for item in delivered]
    active_list = [dict(item) for item in active]
    if len(active_list) > len(delivered_list):
        return False
    for start in range(len(delivered_list) - len(active_list) + 1):
        if delivered_list[start : start + len(active_list)] == active_list:
            return True
    # A history message is inserted immediately after a leading system message,
    # so the active list is split into exact prefix/suffix rather than contiguous.
    return (
        bool(active_list)
        and active_list[0].get("role") == "system"
        and delivered_list[:1] == active_list[:1]
        and delivered_list[2:] == active_list[1:]
    )


def _message_character_count(messages: Sequence[Mapping[str, str]]) -> int:
    return max(
        sum(
            len(str(item.get("role", ""))) + len(str(item.get("content", ""))) for item in messages
        ),
        1,
    )


def _calibration_from_result(
    messages: Sequence[Mapping[str, str]], result: LLMJsonCompletionResult
) -> PromptTokenCalibration | None:
    value = result.usage.get("prompt_tokens", result.usage.get("input_tokens"))
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return PromptTokenCalibration.create(
        messages=messages,
        provider_prompt_tokens=value,
    )


def _write_once_json(path: Path, model: KernelContract) -> None:
    payload = canonical_json(model).encode("utf-8") + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.read_bytes() != payload:
            raise TaskContextError(f"refusing to overwrite context artifact: {path}") from None
        return
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


__all__ = [
    "ActiveTaskConversation",
    "AutonomousTaskContextCompletion",
    "AutonomousTaskContextSession",
    "CompletedTaskConversation",
    "ContextTokenEstimate",
    "MergedCompletedTaskSummary",
    "PreparedTaskContext",
    "PromptTokenCalibration",
    "TaskContextError",
    "TaskContextPreparationArtifact",
    "capture_completed_task_conversation",
    "estimate_context_tokens",
    "prepare_task_aware_context",
]
