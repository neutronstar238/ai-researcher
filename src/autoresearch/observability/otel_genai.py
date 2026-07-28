"""Local, redacted OTLP/JSONL export for GenAI and evaluation telemetry."""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from enum import Enum, IntEnum
from pathlib import Path, PureWindowsPath
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import (
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
    model_validator,
)

from autoresearch.kernel.contracts import (
    KernelContract,
    Sha256,
    StableId,
    canonical_json,
    canonical_sha256,
)
from autoresearch.kernel.journal import validate_persistable_content

OTEL_SEMCONV_CORE_VERSION: Literal["1.43.0"] = "1.43.0"
OTEL_GENAI_SEMCONV_COMMIT: Literal["d74a9bbc419c67dd78ea4fcc26280381ef0bb9db"] = (
    "d74a9bbc419c67dd78ea4fcc26280381ef0bb9db"
)
OTLP_SPEC_VERSION: Literal["1.11.0"] = "1.11.0"
OTEL_SCOPE_NAME = "autoresearch.observability.genai"
OTEL_SCOPE_VERSION = "1"

TelemetryLabel = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:+-]*$",
    ),
]
TelemetryText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1024),
]
RelativeArtifactPath = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=512,
    ),
]

_CONTENT_ATTRIBUTE_KEYS = frozenset(
    {
        "gen_ai.system_instructions",
        "gen_ai.input.messages",
        "gen_ai.output.messages",
        "gen_ai.tool.definitions",
        "gen_ai.tool.call.arguments",
        "gen_ai.tool.call.result",
        "gen_ai.retrieval.query.text",
        "gen_ai.retrieval.documents",
        "gen_ai.memory.query.text",
        "gen_ai.memory.records",
        "gen_ai.evaluation.explanation",
        "exception.message",
        "exception.stacktrace",
    }
)
_SAFE_CUSTOM_ATTRIBUTE = re.compile(r"^autoresearch\.[a-z][a-z0-9_.]*$")
_EMAIL_PATTERN = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_BEARER_PATTERN = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)
_API_KEY_PATTERN = re.compile(r"\b(?:sk|rk|pk)[-_][A-Za-z0-9_-]{16,}\b")
_ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?:\b[A-Za-z]:[\\/]|(?:^|\s)/(?:home|Users|root|tmp|var)/|\\\\[^\\\s]+\\)"
)


class GenAITelemetryError(RuntimeError):
    """Raised when telemetry cannot be safely or truthfully exported."""


class GenAIOperation(str, Enum):
    """Current operation names from the pinned GenAI semantic conventions."""

    CHAT = "chat"
    TEXT_COMPLETION = "text_completion"
    GENERATE_CONTENT = "generate_content"
    EMBEDDINGS = "embeddings"
    CREATE_AGENT = "create_agent"
    INVOKE_AGENT = "invoke_agent"
    INVOKE_WORKFLOW = "invoke_workflow"
    EXECUTE_TOOL = "execute_tool"
    RETRIEVAL = "retrieval"
    CREATE_MEMORY_STORE = "create_memory_store"
    SEARCH_MEMORY = "search_memory"
    CREATE_MEMORY = "create_memory"
    UPDATE_MEMORY = "update_memory"
    UPSERT_MEMORY = "upsert_memory"
    DELETE_MEMORY = "delete_memory"
    DELETE_MEMORY_STORE = "delete_memory_store"


class OtelSpanKind(IntEnum):
    """OTLP SpanKind integer values used by this local exporter."""

    INTERNAL = 1
    CLIENT = 3


class OtelStatusCode(IntEnum):
    """OTLP StatusCode integer values."""

    UNSET = 0
    OK = 1
    ERROR = 2


class GenAIEvaluationEvent(KernelContract):
    """Digest-safe ``gen_ai.evaluation.result`` event."""

    event_id: StableId
    parent_span_id: StableId
    occurred_at: datetime
    evaluation_name: TelemetryLabel
    score_value: float | None = None
    score_label: TelemetryLabel | None = None
    explanation_hash: Sha256 | None = None
    response_id_hash: Sha256 | None = None
    error_type: TelemetryLabel | None = None

    @field_validator("occurred_at")
    @classmethod
    def _require_utc(cls, value: datetime) -> datetime:
        return _utc(value, "evaluation event timestamp")

    @model_validator(mode="after")
    def _require_score_or_error(self) -> GenAIEvaluationEvent:
        if self.score_value is None and self.score_label is None and self.error_type is None:
            raise ValueError("evaluation event requires a score or error type")
        return self


class GenAISpan(KernelContract):
    """Typed GenAI span; raw content is always separated before OTLP export."""

    span_id: StableId
    parent_span_id: StableId | None = None
    operation: GenAIOperation
    kind: OtelSpanKind = OtelSpanKind.INTERNAL
    started_at: datetime
    ended_at: datetime
    status_code: OtelStatusCode = OtelStatusCode.UNSET
    provider_name: TelemetryLabel | None = None
    request_model: TelemetryLabel | None = None
    response_model: TelemetryLabel | None = None
    agent_name: TelemetryLabel | None = None
    agent_version: TelemetryLabel | None = None
    workflow_name: TelemetryLabel | None = None
    tool_name: TelemetryLabel | None = None
    tool_type: TelemetryLabel | None = None
    data_source_hash: Sha256 | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    reasoning_output_tokens: int | None = Field(default=None, ge=0)
    error_type: TelemetryLabel | None = None
    attributes: dict[str, JsonValue] = Field(default_factory=dict)
    content: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("started_at", "ended_at")
    @classmethod
    def _require_utc(cls, value: datetime) -> datetime:
        return _utc(value, "span timestamp")

    @field_validator("attributes")
    @classmethod
    def _validate_custom_attributes(
        cls,
        value: dict[str, JsonValue],
    ) -> dict[str, JsonValue]:
        for key in value:
            if not _SAFE_CUSTOM_ATTRIBUTE.fullmatch(key):
                raise ValueError("custom telemetry attributes must use the autoresearch namespace")
            if key in _CONTENT_ATTRIBUTE_KEYS or _looks_like_content_key(key):
                raise ValueError("content-like values belong in the content field")
        return dict(sorted(value.items()))

    @field_validator("content")
    @classmethod
    def _validate_content_keys(
        cls,
        value: dict[str, JsonValue],
    ) -> dict[str, JsonValue]:
        for key in value:
            if not (key in _CONTENT_ATTRIBUTE_KEYS or key.startswith("autoresearch.content.")):
                raise ValueError("raw span content must use a recognized content attribute")
        return dict(sorted(value.items()))

    @model_validator(mode="after")
    def _validate_span(self) -> GenAISpan:
        if self.ended_at < self.started_at:
            raise ValueError("span end cannot precede start")
        if self.status_code == OtelStatusCode.ERROR and self.error_type is None:
            raise ValueError("error span requires a low-cardinality error type")
        if self.status_code != OtelStatusCode.ERROR and self.error_type is not None:
            raise ValueError("only an error span may carry error_type")
        if self.kind == OtelSpanKind.CLIENT and self.provider_name is None:
            raise ValueError("client GenAI span requires provider_name")
        if (
            self.operation
            in {
                GenAIOperation.CHAT,
                GenAIOperation.TEXT_COMPLETION,
                GenAIOperation.GENERATE_CONTENT,
                GenAIOperation.EMBEDDINGS,
            }
            and self.request_model is None
        ):
            raise ValueError("inference span requires request_model")
        if self.operation == GenAIOperation.EXECUTE_TOOL and self.tool_name is None:
            raise ValueError("execute_tool span requires tool_name")
        if self.reasoning_output_tokens is not None and (
            self.output_tokens is None or self.reasoning_output_tokens > self.output_tokens
        ):
            raise ValueError("reasoning tokens must be included in output tokens")
        return self

    @property
    def span_name(self) -> str:
        """Return the low-cardinality name prescribed by the pinned conventions."""

        if self.operation == GenAIOperation.EXECUTE_TOOL:
            return f"execute_tool {self.tool_name}"
        if self.operation in {
            GenAIOperation.CHAT,
            GenAIOperation.TEXT_COMPLETION,
            GenAIOperation.GENERATE_CONTENT,
            GenAIOperation.EMBEDDINGS,
        }:
            return f"{self.operation.value} {self.request_model}"
        if (
            self.operation
            in {
                GenAIOperation.INVOKE_AGENT,
                GenAIOperation.CREATE_AGENT,
            }
            and self.agent_name is not None
        ):
            return f"{self.operation.value} {self.agent_name}"
        if self.operation == GenAIOperation.INVOKE_WORKFLOW and self.workflow_name is not None:
            return f"invoke_workflow {self.workflow_name}"
        return str(self.operation.value)


class GenAITelemetryBatch(KernelContract):
    """One validated trace tree plus its evaluation events."""

    batch_id: StableId
    run_id: StableId
    service_name: TelemetryLabel
    service_version: TelemetryLabel
    spans: list[GenAISpan] = Field(min_length=1)
    evaluation_events: list[GenAIEvaluationEvent] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_tree(self) -> GenAITelemetryBatch:
        span_ids = [item.span_id for item in self.spans]
        if len(span_ids) != len(set(span_ids)):
            raise ValueError("span IDs must be unique")
        span_map = {item.span_id: item for item in self.spans}
        roots = 0
        for span in self.spans:
            if span.parent_span_id is None:
                roots += 1
            elif span.parent_span_id not in span_map:
                raise ValueError("span references an unknown parent")
        if roots != 1:
            raise ValueError("telemetry batch requires exactly one root span")
        for span in self.spans:
            seen: set[str] = set()
            cursor: GenAISpan | None = span
            while cursor is not None:
                if cursor.span_id in seen:
                    raise ValueError("span parent graph contains a cycle")
                seen.add(cursor.span_id)
                cursor = (
                    span_map[cursor.parent_span_id] if cursor.parent_span_id is not None else None
                )
        event_ids = [item.event_id for item in self.evaluation_events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("evaluation event IDs must be unique")
        for event in self.evaluation_events:
            parent = span_map.get(event.parent_span_id)
            if parent is None:
                raise ValueError("evaluation event references an unknown span")
            if not (parent.started_at <= event.occurred_at <= parent.ended_at):
                raise ValueError("evaluation event lies outside parent span")
        self.spans = sorted(self.spans, key=lambda item: item.span_id)
        self.evaluation_events = sorted(
            self.evaluation_events,
            key=lambda item: item.event_id,
        )
        return self

    def raw_content_scope_hash(self) -> str:
        """Bind a permission to content digests without exposing the content."""

        return canonical_sha256(
            {
                "batch_id": self.batch_id,
                "run_id": self.run_id,
                "content": [
                    {
                        "span_id": span.span_id,
                        "content_hash": canonical_sha256(span.content),
                    }
                    for span in self.spans
                    if span.content
                ],
            }
        )


class LocalGenAITelemetryPolicy(KernelContract):
    """Frozen local-only export and raw-content retention boundary."""

    policy_id: StableId
    version: TelemetryLabel
    local_only: Literal[True] = True
    content_capture_default: Literal[False] = False
    retain_raw_content: bool = False
    raw_content_permission_id: StableId | None = None
    max_spans: int = Field(default=1_000, ge=1)
    max_evaluation_events: int = Field(default=2_000, ge=0)
    max_otlp_bytes: int = Field(default=16 * 1024 * 1024, ge=1024)
    max_raw_content_bytes: int = Field(default=4 * 1024 * 1024, ge=0)
    semconv_core_version: Literal["1.43.0"] = OTEL_SEMCONV_CORE_VERSION
    semconv_genai_commit: Literal["d74a9bbc419c67dd78ea4fcc26280381ef0bb9db"] = (
        OTEL_GENAI_SEMCONV_COMMIT
    )
    otlp_spec_version: Literal["1.11.0"] = OTLP_SPEC_VERSION

    @model_validator(mode="after")
    def _validate_raw_permission(self) -> LocalGenAITelemetryPolicy:
        if self.retain_raw_content != (self.raw_content_permission_id is not None):
            raise ValueError("raw retention and raw_content_permission_id must be enabled together")
        if self.retain_raw_content and self.max_raw_content_bytes == 0:
            raise ValueError("raw retention requires a positive content byte limit")
        return self


class RawContentGrant(KernelContract):
    """Explicit, expiring permission for one digest-bound local content artifact."""

    permission_id: StableId
    scope_hash: Sha256
    approved_by: StableId
    approved_at: datetime
    expires_at: datetime
    local_only: Literal[True] = True

    @field_validator("approved_at", "expires_at")
    @classmethod
    def _require_utc(cls, value: datetime) -> datetime:
        return _utc(value, "raw-content grant timestamp")

    @model_validator(mode="after")
    def _validate_window(self) -> RawContentGrant:
        if self.expires_at <= self.approved_at:
            raise ValueError("raw-content grant must expire after approval")
        return self

    def permits(
        self,
        *,
        permission_id: str,
        scope_hash: str,
        at_time: datetime,
    ) -> bool:
        """Check identity, content scope, locality, and validity window."""

        checked = _utc(at_time, "raw-content grant check timestamp")
        return (
            self.permission_id == permission_id
            and self.scope_hash == scope_hash
            and self.approved_at <= checked < self.expires_at
        )


class RawContentArtifact(KernelContract):
    """Digest and relative path of an explicitly permissioned local artifact."""

    relative_path: RelativeArtifactPath
    sha256: Sha256
    byte_count: int = Field(ge=0)
    permission_id: StableId
    scope_hash: Sha256

    @field_validator("relative_path")
    @classmethod
    def _require_relative_path(cls, value: str) -> str:
        return _validate_relative_artifact_path(value)


class LocalOtlpExport(KernelContract):
    """Result of one content-addressed local OTLP/JSONL export."""

    export_id: StableId
    batch_id: StableId
    batch_hash: Sha256
    relative_path: RelativeArtifactPath
    sha256: Sha256
    byte_count: int = Field(ge=0)
    span_count: int = Field(ge=1)
    evaluation_event_count: int = Field(ge=0)
    redacted_content_field_count: int = Field(ge=0)
    redacted_attribute_count: int = Field(ge=0)
    raw_content_artifact: RawContentArtifact | None = None
    local_only: Literal[True] = True

    @field_validator("relative_path")
    @classmethod
    def _require_relative_path(cls, value: str) -> str:
        return _validate_relative_artifact_path(value)


class LocalGenAIOtlpExporter:
    """Write one local OTLP/JSON traces object per content-addressed JSONL file."""

    def __init__(
        self,
        export_root: Path | str,
        *,
        raw_artifact_root: Path | str | None = None,
    ) -> None:
        self.export_root = _local_root(export_root, "OTLP export root")
        self.raw_artifact_root = (
            _local_root(raw_artifact_root, "raw telemetry root")
            if raw_artifact_root is not None
            else None
        )

    def export(
        self,
        batch: GenAITelemetryBatch,
        policy: LocalGenAITelemetryPolicy,
        *,
        at_time: datetime,
        raw_content_grant: RawContentGrant | None = None,
    ) -> LocalOtlpExport:
        """Redact content, emit OTLP JSONL, and optionally retain scoped raw content."""

        checked_at = _utc(at_time, "telemetry export timestamp")
        if len(batch.spans) > policy.max_spans:
            raise GenAITelemetryError("telemetry span limit exceeded")
        if len(batch.evaluation_events) > policy.max_evaluation_events:
            raise GenAITelemetryError("telemetry evaluation-event limit exceeded")
        content_field_count = sum(len(span.content) for span in batch.spans)
        payload, redacted_attributes = _otlp_payload(batch, policy)
        serialized = canonical_json(payload).encode("utf-8") + b"\n"
        if len(serialized) > policy.max_otlp_bytes:
            raise GenAITelemetryError("redacted OTLP payload exceeds policy limit")
        validate_persistable_content(payload)
        payload_hash = canonical_sha256(payload)
        filename = f"{batch.batch_id}.{payload_hash[:16]}.traces.jsonl"
        path = self.export_root / filename
        if not policy.retain_raw_content and raw_content_grant is not None:
            raise GenAITelemetryError("raw-content grant supplied while retention is disabled")
        raw_artifact: RawContentArtifact | None = None
        if policy.retain_raw_content and content_field_count:
            if self.raw_artifact_root is None:
                raise GenAITelemetryError(
                    "raw content retention requires a separate local artifact root"
                )
            permission_id = policy.raw_content_permission_id
            if permission_id is None or raw_content_grant is None:
                raise GenAITelemetryError("raw content retention requires an explicit grant")
            scope_hash = batch.raw_content_scope_hash()
            if not raw_content_grant.permits(
                permission_id=permission_id,
                scope_hash=scope_hash,
                at_time=checked_at,
            ):
                raise GenAITelemetryError("raw content grant does not cover this batch and time")
            raw_artifact = self._write_raw_content(
                batch,
                policy=policy,
                grant=raw_content_grant,
            )
        _atomic_content_addressed_write(path, serialized, mode=0o600)
        return LocalOtlpExport(
            export_id=f"otel.{batch.batch_id}.{payload_hash[:16]}",
            batch_id=batch.batch_id,
            batch_hash=batch.content_hash(),
            relative_path=filename,
            sha256=canonical_sha256_bytes(serialized),
            byte_count=len(serialized),
            span_count=len(batch.spans),
            evaluation_event_count=len(batch.evaluation_events),
            redacted_content_field_count=content_field_count,
            redacted_attribute_count=redacted_attributes,
            raw_content_artifact=raw_artifact,
        )

    def _write_raw_content(
        self,
        batch: GenAITelemetryBatch,
        *,
        policy: LocalGenAITelemetryPolicy,
        grant: RawContentGrant,
    ) -> RawContentArtifact:
        if self.raw_artifact_root is None:  # pragma: no cover - guarded by caller
            raise GenAITelemetryError("raw telemetry root is unavailable")
        raw_payload = {
            "schemaVersion": 1,
            "batchId": batch.batch_id,
            "runId": batch.run_id,
            "permissionId": grant.permission_id,
            "scopeHash": grant.scope_hash,
            "content": [
                {
                    "spanId": span.span_id,
                    "fields": span.content,
                }
                for span in batch.spans
                if span.content
            ],
        }
        serialized = canonical_json(raw_payload).encode("utf-8") + b"\n"
        if len(serialized) > policy.max_raw_content_bytes:
            raise GenAITelemetryError("raw content exceeds permissioned policy limit")
        payload_hash = canonical_sha256(raw_payload)
        filename = f"{batch.batch_id}.{payload_hash[:16]}.raw.json"
        path = self.raw_artifact_root / filename
        _atomic_content_addressed_write(path, serialized, mode=0o600)
        return RawContentArtifact(
            relative_path=filename,
            sha256=canonical_sha256_bytes(serialized),
            byte_count=len(serialized),
            permission_id=grant.permission_id,
            scope_hash=grant.scope_hash,
        )


def _otlp_payload(
    batch: GenAITelemetryBatch,
    policy: LocalGenAITelemetryPolicy,
) -> tuple[dict[str, Any], int]:
    trace_id = canonical_sha256({"batch_id": batch.batch_id, "run_id": batch.run_id})[:32]
    span_id_map = {
        span.span_id: canonical_sha256({"batch_id": batch.batch_id, "span_id": span.span_id})[:16]
        for span in batch.spans
    }
    events_by_span: dict[str, list[GenAIEvaluationEvent]] = {}
    for event in batch.evaluation_events:
        events_by_span.setdefault(event.parent_span_id, []).append(event)
    redacted_attributes = 0
    otlp_spans: list[dict[str, Any]] = []
    for span in batch.spans:
        attributes, redacted_count = _span_attributes(span)
        redacted_attributes += redacted_count
        otlp_span: dict[str, Any] = {
            "traceId": trace_id,
            "spanId": span_id_map[span.span_id],
            "name": span.span_name,
            "kind": int(span.kind),
            "startTimeUnixNano": str(_unix_nanos(span.started_at)),
            "endTimeUnixNano": str(_unix_nanos(span.ended_at)),
            "attributes": _otlp_attributes(attributes),
            "status": {"code": int(span.status_code)},
        }
        if span.parent_span_id is not None:
            otlp_span["parentSpanId"] = span_id_map[span.parent_span_id]
        event_payloads = [
            _evaluation_event_payload(item)
            for item in sorted(
                events_by_span.get(span.span_id, []),
                key=lambda item: item.event_id,
            )
        ]
        if event_payloads:
            otlp_span["events"] = event_payloads
        otlp_spans.append(otlp_span)
    resource_attributes: dict[str, JsonValue] = {
        "service.name": batch.service_name,
        "service.version": batch.service_version,
        "deployment.environment.name": "development",
        "autoresearch.run.id": batch.run_id,
        "autoresearch.telemetry.local_only": True,
        "autoresearch.telemetry.content_capture_default": False,
        "autoresearch.otel.semconv.core.version": policy.semconv_core_version,
        "autoresearch.otel.semconv.genai.commit": policy.semconv_genai_commit,
        "autoresearch.otel.otlp.spec.version": policy.otlp_spec_version,
    }
    payload: dict[str, Any] = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": _otlp_attributes(resource_attributes),
                },
                "scopeSpans": [
                    {
                        "scope": {
                            "name": OTEL_SCOPE_NAME,
                            "version": OTEL_SCOPE_VERSION,
                        },
                        "spans": otlp_spans,
                    }
                ],
            }
        ]
    }
    return payload, redacted_attributes


def _span_attributes(span: GenAISpan) -> tuple[dict[str, JsonValue], int]:
    attributes: dict[str, JsonValue] = {
        "gen_ai.operation.name": span.operation.value,
    }
    optional: tuple[tuple[str, JsonValue | None], ...] = (
        ("gen_ai.provider.name", span.provider_name),
        ("gen_ai.request.model", span.request_model),
        ("gen_ai.response.model", span.response_model),
        ("gen_ai.agent.name", span.agent_name),
        ("gen_ai.agent.version", span.agent_version),
        ("gen_ai.workflow.name", span.workflow_name),
        ("gen_ai.tool.name", span.tool_name),
        ("gen_ai.tool.type", span.tool_type),
        ("gen_ai.usage.input_tokens", span.input_tokens),
        ("gen_ai.usage.output_tokens", span.output_tokens),
        ("gen_ai.usage.reasoning.output_tokens", span.reasoning_output_tokens),
        ("error.type", span.error_type),
    )
    for key, value in optional:
        if value is not None:
            attributes[key] = value
    if span.data_source_hash is not None:
        attributes["autoresearch.gen_ai.data_source.sha256"] = span.data_source_hash
    attributes.update(span.attributes)
    if span.content:
        attributes["autoresearch.content.redacted"] = True
        attributes["autoresearch.content.sha256"] = canonical_sha256(span.content)
        attributes["autoresearch.content.field_count"] = len(span.content)
    redacted_count = 0
    safe: dict[str, JsonValue] = {}
    for key, value in attributes.items():
        if key in _CONTENT_ATTRIBUTE_KEYS or _looks_like_content_key(key):
            safe[f"autoresearch.redacted.{canonical_sha256(key)[:12]}.sha256"] = canonical_sha256(
                value
            )
            redacted_count += 1
            continue
        redacted, count = _redact_value(value)
        safe[key] = redacted
        redacted_count += count
    if redacted_count:
        safe["autoresearch.redacted.attribute_count"] = redacted_count
    return dict(sorted(safe.items())), redacted_count


def _evaluation_event_payload(
    event: GenAIEvaluationEvent,
) -> dict[str, Any]:
    attributes: dict[str, JsonValue] = {
        "gen_ai.evaluation.name": event.evaluation_name,
    }
    if event.score_value is not None:
        attributes["gen_ai.evaluation.score.value"] = event.score_value
    if event.score_label is not None:
        attributes["gen_ai.evaluation.score.label"] = event.score_label
    if event.explanation_hash is not None:
        attributes["autoresearch.evaluation.explanation.sha256"] = event.explanation_hash
    if event.response_id_hash is not None:
        attributes["autoresearch.gen_ai.response.id.sha256"] = event.response_id_hash
    if event.error_type is not None:
        attributes["error.type"] = event.error_type
    return {
        "timeUnixNano": str(_unix_nanos(event.occurred_at)),
        "name": "gen_ai.evaluation.result",
        "attributes": _otlp_attributes(attributes),
    }


def _otlp_attributes(
    attributes: Mapping[str, JsonValue],
) -> list[dict[str, Any]]:
    return [
        {
            "key": key,
            "value": _otlp_any_value(value),
        }
        for key, value in sorted(attributes.items())
    ]


def _otlp_any_value(value: JsonValue) -> dict[str, Any]:
    if value is None:
        return {"stringValue": "null"}
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, str):
        return {"stringValue": value}
    if isinstance(value, list):
        return {
            "arrayValue": {
                "values": [_otlp_any_value(item) for item in value],
            }
        }
    if isinstance(value, dict):
        return {
            "kvlistValue": {
                "values": [
                    {
                        "key": key,
                        "value": _otlp_any_value(item),
                    }
                    for key, item in sorted(value.items())
                ],
            }
        }
    raise TypeError(f"unsupported OTLP attribute type: {type(value).__name__}")


def _redact_value(value: JsonValue) -> tuple[JsonValue, int]:
    if isinstance(value, str):
        if _looks_sensitive(value):
            return f"sha256:{canonical_sha256(value)}", 1
        return value, 0
    if isinstance(value, list):
        redacted: list[JsonValue] = []
        count = 0
        for item in value:
            safe, item_count = _redact_value(item)
            redacted.append(safe)
            count += item_count
        return redacted, count
    if isinstance(value, dict):
        redacted_dict: dict[str, JsonValue] = {}
        count = 0
        for key, item in sorted(value.items()):
            if _looks_like_content_key(key):
                redacted_dict[f"redacted_{canonical_sha256(key)[:12]}_sha256"] = canonical_sha256(
                    item
                )
                count += 1
            else:
                safe, item_count = _redact_value(item)
                redacted_dict[key] = safe
                count += item_count
        return redacted_dict, count
    return value, 0


def _looks_sensitive(value: str) -> bool:
    return bool(
        len(value) > 512
        or _EMAIL_PATTERN.search(value)
        or _BEARER_PATTERN.search(value)
        or _API_KEY_PATTERN.search(value)
        or _ABSOLUTE_PATH_PATTERN.search(value)
        or "-----BEGIN PRIVATE KEY-----" in value
    )


def _looks_like_content_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    tokens = set(normalized.split("_"))
    return bool(
        tokens
        & {
            "prompt",
            "completion",
            "message",
            "messages",
            "instruction",
            "instructions",
            "argument",
            "arguments",
            "result",
            "document",
            "documents",
            "query",
            "stacktrace",
            "password",
            "secret",
            "authorization",
        }
    )


def _local_root(value: Path | str, label: str) -> Path:
    path = Path(value)
    windows = PureWindowsPath(str(value))
    if windows.drive.startswith("\\\\") or str(value).startswith("\\\\"):
        raise GenAITelemetryError(f"{label} cannot be a network share")
    if path.exists() and path.is_symlink():
        raise GenAITelemetryError(f"{label} cannot be a symbolic link")
    resolved = path.resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _validate_relative_artifact_path(value: str) -> str:
    windows = PureWindowsPath(value)
    path = Path(value)
    if (
        windows.drive
        or windows.root
        or path.is_absolute()
        or any(part == ".." for part in windows.parts)
        or any(part == ".." for part in path.parts)
    ):
        raise ValueError("artifact path must be relative and cannot traverse parents")
    return value


def _atomic_content_addressed_write(
    path: Path,
    data: bytes,
    *,
    mode: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise GenAITelemetryError(f"content-addressed telemetry collision at {path.name}")
        return
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _unix_nanos(value: datetime) -> int:
    return int(value.timestamp() * 1_000_000_000)


def _utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError(f"{label} must be timezone-aware UTC")
    return value


def canonical_sha256_bytes(value: bytes) -> str:
    """Hash exact file bytes without decoding or JSON reserialization."""

    return hashlib.sha256(value).hexdigest()
