"""Tests for local-only, redacted GenAI OTLP/JSONL export."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from autoresearch.kernel import canonical_sha256
from autoresearch.observability import (
    OTEL_GENAI_SEMCONV_COMMIT,
    OTEL_SEMCONV_CORE_VERSION,
    OTLP_SPEC_VERSION,
    GenAIEvaluationEvent,
    GenAIOperation,
    GenAISpan,
    GenAITelemetryBatch,
    GenAITelemetryError,
    LocalGenAIOtlpExporter,
    LocalGenAITelemetryPolicy,
    OtelSpanKind,
    OtelStatusCode,
    RawContentArtifact,
    RawContentGrant,
)

BASE_TIME = datetime(2026, 7, 29, 9, 0, tzinfo=timezone.utc)
PRIVATE_PROMPT = "private prompt for the local fixture"
PRIVATE_OUTPUT = "private model output for the local fixture"


def _span(**overrides: object) -> GenAISpan:
    values: dict[str, object] = {
        "span_id": "span.agent",
        "operation": GenAIOperation.INVOKE_AGENT,
        "started_at": BASE_TIME,
        "ended_at": BASE_TIME + timedelta(seconds=5),
        "agent_name": "research-agent",
        "agent_version": "1",
    }
    values.update(overrides)
    return GenAISpan.model_validate(values)


def _batch() -> GenAITelemetryBatch:
    root = _span()
    inference = _span(
        span_id="span.inference",
        parent_span_id=root.span_id,
        operation=GenAIOperation.CHAT,
        kind=OtelSpanKind.CLIENT,
        started_at=BASE_TIME + timedelta(seconds=1),
        ended_at=BASE_TIME + timedelta(seconds=3),
        provider_name="local-fixture",
        request_model="fixture-model",
        response_model="fixture-model-v1",
        input_tokens=11,
        output_tokens=7,
        reasoning_output_tokens=2,
        agent_name=None,
        agent_version=None,
        attributes={
            "autoresearch.user.label": "researcher@example.org",
            "autoresearch.metadata": {
                "prompt": "nested private metadata",
                "safe": "fixture",
            },
        },
        content={
            "gen_ai.input.messages": [{"role": "user", "content": PRIVATE_PROMPT}],
            "gen_ai.output.messages": [{"role": "assistant", "content": PRIVATE_OUTPUT}],
        },
    )
    tool = _span(
        span_id="span.tool",
        parent_span_id=root.span_id,
        operation=GenAIOperation.EXECUTE_TOOL,
        started_at=BASE_TIME + timedelta(seconds=3),
        ended_at=BASE_TIME + timedelta(seconds=4),
        tool_name="vault.read",
        tool_type="function",
        agent_name=None,
        agent_version=None,
    )
    event = GenAIEvaluationEvent(
        event_id="evaluation.event.1",
        parent_span_id=inference.span_id,
        occurred_at=BASE_TIME + timedelta(seconds=2),
        evaluation_name="evidence_match",
        score_value=1.0,
        score_label="pass",
        explanation_hash=canonical_sha256("private explanation"),
        response_id_hash=canonical_sha256("response-1"),
    )
    return GenAITelemetryBatch(
        batch_id="telemetry.batch.1",
        run_id="run.fixture.1",
        service_name="autoresearch",
        service_version="1.0.0",
        spans=[tool, inference, root],
        evaluation_events=[event],
    )


def _policy(**overrides: object) -> LocalGenAITelemetryPolicy:
    values: dict[str, object] = {
        "policy_id": "telemetry.policy",
        "version": "1",
    }
    values.update(overrides)
    return LocalGenAITelemetryPolicy.model_validate(values)


def _load_export(path: Path) -> dict[str, object]:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert isinstance(payload, dict)
    return payload


def _exported_spans(payload: dict[str, object]) -> list[dict[str, object]]:
    resource_spans = payload["resourceSpans"]
    assert isinstance(resource_spans, list)
    resource = resource_spans[0]
    assert isinstance(resource, dict)
    scope_spans = resource["scopeSpans"]
    assert isinstance(scope_spans, list)
    scope = scope_spans[0]
    assert isinstance(scope, dict)
    spans = scope["spans"]
    assert isinstance(spans, list)
    assert all(isinstance(item, dict) for item in spans)
    return spans


def _decode_any_value(value: dict[str, object]) -> object:
    for key in ("stringValue", "boolValue", "intValue", "doubleValue"):
        if key in value:
            return value[key]
    if "arrayValue" in value:
        array = value["arrayValue"]
        assert isinstance(array, dict)
        values = array["values"]
        assert isinstance(values, list)
        return [_decode_any_value(item) for item in values]
    if "kvlistValue" in value:
        kvlist = value["kvlistValue"]
        assert isinstance(kvlist, dict)
        values = kvlist["values"]
        assert isinstance(values, list)
        decoded: dict[str, object] = {}
        for item in values:
            assert isinstance(item, dict)
            key = item["key"]
            nested = item["value"]
            assert isinstance(key, str)
            assert isinstance(nested, dict)
            decoded[key] = _decode_any_value(nested)
        return decoded
    raise AssertionError(f"unknown OTLP AnyValue: {value}")


def _attributes(items: object) -> dict[str, object]:
    assert isinstance(items, list)
    decoded: dict[str, object] = {}
    for item in items:
        assert isinstance(item, dict)
        key = item["key"]
        value = item["value"]
        assert isinstance(key, str)
        assert isinstance(value, dict)
        decoded[key] = _decode_any_value(value)
    return decoded


def test_export_writes_valid_local_otlp_jsonl_without_raw_content(
    tmp_path: Path,
) -> None:
    batch = _batch()
    exporter = LocalGenAIOtlpExporter(tmp_path / "otel")

    result = exporter.export(batch, _policy(), at_time=BASE_TIME)
    path = tmp_path / "otel" / result.relative_path
    payload = _load_export(path)
    serialized = path.read_text(encoding="utf-8")
    spans = _exported_spans(payload)
    by_name = {item["name"]: item for item in spans}

    assert path.is_file()
    assert result.raw_content_artifact is None
    assert result.redacted_content_field_count == 2
    assert result.redacted_attribute_count >= 2
    assert result.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert PRIVATE_PROMPT not in serialized
    assert PRIVATE_OUTPUT not in serialized
    assert "researcher@example.org" not in serialized
    assert "nested private metadata" not in serialized
    assert set(by_name) == {
        "invoke_agent research-agent",
        "chat fixture-model",
        "execute_tool vault.read",
    }

    inference = by_name["chat fixture-model"]
    assert re.fullmatch(r"[0-9a-f]{32}", str(inference["traceId"]))
    assert re.fullmatch(r"[0-9a-f]{16}", str(inference["spanId"]))
    assert re.fullmatch(r"[0-9a-f]{16}", str(inference["parentSpanId"]))
    assert isinstance(inference["kind"], int)
    assert isinstance(inference["startTimeUnixNano"], str)
    assert isinstance(inference["endTimeUnixNano"], str)
    inference_attributes = _attributes(inference["attributes"])
    assert inference_attributes["gen_ai.operation.name"] == "chat"
    assert inference_attributes["gen_ai.usage.input_tokens"] == "11"
    assert inference_attributes["autoresearch.content.redacted"] is True
    assert re.fullmatch(
        r"[0-9a-f]{64}",
        str(inference_attributes["autoresearch.content.sha256"]),
    )
    assert str(inference_attributes["autoresearch.user.label"]).startswith("sha256:")
    nested = inference_attributes["autoresearch.metadata"]
    assert isinstance(nested, dict)
    assert "prompt" not in nested

    events = inference["events"]
    assert isinstance(events, list)
    assert events[0]["name"] == "gen_ai.evaluation.result"
    event_attributes = _attributes(events[0]["attributes"])
    assert event_attributes["gen_ai.evaluation.name"] == "evidence_match"
    assert event_attributes["gen_ai.evaluation.score.value"] == 1.0

    resource_spans = payload["resourceSpans"]
    assert isinstance(resource_spans, list)
    resource = resource_spans[0]
    assert isinstance(resource, dict)
    resource_node = resource["resource"]
    assert isinstance(resource_node, dict)
    resource_attributes = _attributes(resource_node["attributes"])
    assert (
        resource_attributes["autoresearch.otel.semconv.core.version"] == OTEL_SEMCONV_CORE_VERSION
    )
    assert (
        resource_attributes["autoresearch.otel.semconv.genai.commit"] == OTEL_GENAI_SEMCONV_COMMIT
    )
    assert resource_attributes["autoresearch.otel.otlp.spec.version"] == OTLP_SPEC_VERSION
    assert resource_attributes["autoresearch.telemetry.local_only"] is True
    assert resource_attributes["autoresearch.telemetry.content_capture_default"] is False


def test_export_is_content_addressed_and_idempotent(tmp_path: Path) -> None:
    exporter = LocalGenAIOtlpExporter(tmp_path / "otel")
    batch = _batch()

    first = exporter.export(batch, _policy(), at_time=BASE_TIME)
    first_bytes = (tmp_path / "otel" / first.relative_path).read_bytes()
    second = exporter.export(batch, _policy(), at_time=BASE_TIME)

    assert second == first
    assert (tmp_path / "otel" / second.relative_path).read_bytes() == first_bytes
    assert list((tmp_path / "otel").glob("*.jsonl")) == [tmp_path / "otel" / first.relative_path]


def test_raw_content_requires_a_digest_bound_expiring_local_grant(
    tmp_path: Path,
) -> None:
    batch = _batch()
    policy = _policy(
        retain_raw_content=True,
        raw_content_permission_id="permission.raw",
    )
    exporter = LocalGenAIOtlpExporter(
        tmp_path / "otel",
        raw_artifact_root=tmp_path / "raw",
    )

    with pytest.raises(GenAITelemetryError, match="explicit grant"):
        exporter.export(batch, policy, at_time=BASE_TIME)

    wrong_scope = RawContentGrant(
        permission_id="permission.raw",
        scope_hash=canonical_sha256("wrong"),
        approved_by="operator.fixture",
        approved_at=BASE_TIME - timedelta(minutes=1),
        expires_at=BASE_TIME + timedelta(minutes=1),
    )
    with pytest.raises(GenAITelemetryError, match="does not cover"):
        exporter.export(
            batch,
            policy,
            at_time=BASE_TIME,
            raw_content_grant=wrong_scope,
        )

    expired = wrong_scope.model_copy(
        update={
            "scope_hash": batch.raw_content_scope_hash(),
            "approved_at": BASE_TIME - timedelta(minutes=2),
            "expires_at": BASE_TIME - timedelta(minutes=1),
        }
    )
    with pytest.raises(GenAITelemetryError, match="does not cover"):
        exporter.export(
            batch,
            policy,
            at_time=BASE_TIME,
            raw_content_grant=expired,
        )

    grant = RawContentGrant(
        permission_id="permission.raw",
        scope_hash=batch.raw_content_scope_hash(),
        approved_by="operator.fixture",
        approved_at=BASE_TIME - timedelta(minutes=1),
        expires_at=BASE_TIME + timedelta(minutes=1),
    )
    result = exporter.export(
        batch,
        policy,
        at_time=BASE_TIME,
        raw_content_grant=grant,
    )

    assert result.raw_content_artifact is not None
    raw_path = tmp_path / "raw" / result.raw_content_artifact.relative_path
    otlp_path = tmp_path / "otel" / result.relative_path
    assert PRIVATE_PROMPT in raw_path.read_text(encoding="utf-8")
    assert PRIVATE_OUTPUT in raw_path.read_text(encoding="utf-8")
    assert PRIVATE_PROMPT not in otlp_path.read_text(encoding="utf-8")
    assert result.raw_content_artifact.sha256 == hashlib.sha256(raw_path.read_bytes()).hexdigest()


def test_disabled_retention_rejects_an_unexpected_grant(tmp_path: Path) -> None:
    batch = _batch()
    grant = RawContentGrant(
        permission_id="permission.raw",
        scope_hash=batch.raw_content_scope_hash(),
        approved_by="operator.fixture",
        approved_at=BASE_TIME - timedelta(minutes=1),
        expires_at=BASE_TIME + timedelta(minutes=1),
    )

    with pytest.raises(GenAITelemetryError, match="retention is disabled"):
        LocalGenAIOtlpExporter(tmp_path / "otel").export(
            batch,
            _policy(),
            at_time=BASE_TIME,
            raw_content_grant=grant,
        )


def test_content_like_custom_attribute_is_rejected() -> None:
    with pytest.raises(ValidationError, match="content-like"):
        _span(attributes={"autoresearch.prompt": "should not be here"})


def test_batch_rejects_invalid_parent_graph_and_event_time() -> None:
    root = _span()
    second_root = _span(span_id="span.second")
    with pytest.raises(ValidationError, match="exactly one root"):
        GenAITelemetryBatch(
            batch_id="batch.two-roots",
            run_id="run.fixture",
            service_name="autoresearch",
            service_version="1",
            spans=[root, second_root],
        )

    cycle_a = _span(
        span_id="span.cycle.a",
        parent_span_id="span.cycle.b",
    )
    cycle_b = _span(
        span_id="span.cycle.b",
        parent_span_id="span.cycle.a",
    )
    with pytest.raises(ValidationError, match="cycle"):
        GenAITelemetryBatch(
            batch_id="batch.cycle",
            run_id="run.fixture",
            service_name="autoresearch",
            service_version="1",
            spans=[root, cycle_a, cycle_b],
        )

    event = GenAIEvaluationEvent(
        event_id="event.outside",
        parent_span_id=root.span_id,
        occurred_at=BASE_TIME + timedelta(seconds=6),
        evaluation_name="fixture",
        score_label="pass",
    )
    with pytest.raises(ValidationError, match="outside parent span"):
        GenAITelemetryBatch(
            batch_id="batch.outside-event",
            run_id="run.fixture",
            service_name="autoresearch",
            service_version="1",
            spans=[root],
            evaluation_events=[event],
        )


def test_export_limits_and_local_path_boundaries_fail_closed(
    tmp_path: Path,
) -> None:
    exporter = LocalGenAIOtlpExporter(tmp_path / "otel")
    with pytest.raises(GenAITelemetryError, match="payload exceeds"):
        exporter.export(
            _batch(),
            _policy(max_otlp_bytes=1024),
            at_time=BASE_TIME,
        )

    batch = _batch()
    raw_exporter = LocalGenAIOtlpExporter(
        tmp_path / "otel-raw",
        raw_artifact_root=tmp_path / "raw",
    )
    grant = RawContentGrant(
        permission_id="permission.raw",
        scope_hash=batch.raw_content_scope_hash(),
        approved_by="operator.fixture",
        approved_at=BASE_TIME - timedelta(minutes=1),
        expires_at=BASE_TIME + timedelta(minutes=1),
    )
    with pytest.raises(GenAITelemetryError, match="payload exceeds"):
        raw_exporter.export(
            batch,
            _policy(
                retain_raw_content=True,
                raw_content_permission_id="permission.raw",
                max_otlp_bytes=1024,
            ),
            at_time=BASE_TIME,
            raw_content_grant=grant,
        )
    assert not list((tmp_path / "raw").glob("*.json"))

    with pytest.raises(GenAITelemetryError, match="network share"):
        LocalGenAIOtlpExporter(r"\\server\share")

    with pytest.raises(ValidationError, match="relative"):
        RawContentArtifact(
            relative_path="../outside.json",
            sha256=canonical_sha256("artifact"),
            byte_count=1,
            permission_id="permission.raw",
            scope_hash=canonical_sha256("scope"),
        )


def test_error_span_requires_low_cardinality_error_type() -> None:
    with pytest.raises(ValidationError, match="requires a low-cardinality"):
        _span(status_code=OtelStatusCode.ERROR)

    span = _span(
        status_code=OtelStatusCode.ERROR,
        error_type="policy_denied",
    )
    assert span.error_type == "policy_denied"
