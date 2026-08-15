from __future__ import annotations

import http.client
import json
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from threading import Barrier, Thread
from typing import Any

import pytest

import autoresearch.competition.contest_direction_stage_checkpoint as checkpoint_module
import autoresearch.llm.client as llm_client_module
from autoresearch.competition.contest_direction_research_loop_cli import (
    _quarantine_partial_output,
)
from autoresearch.competition.contest_direction_stage_checkpoint import (
    ContestDirectionStageCheckpointError,
    literature_search_checkpoint_accounting,
    load_completed_stage,
    paper_verification_checkpoint_accounting,
    provider_checkpoint_accounting,
    provider_checkpoint_count,
    record_completed_stage,
    replayable_literature_searchers,
    replayable_paper_verifier,
    replayable_stage_completion,
    research_loop_literature_search_checkpoint_accounting,
    research_loop_source_checkpoint_accounting,
)
from autoresearch.kernel import canonical_sha256, validate_persistable_content
from autoresearch.literature.privacy import (
    SCHOLARLY_METADATA_PRIVACY_POLICY_VERSION,
    ScholarlyMetadataPrivacyError,
)
from autoresearch.llm.client import LLMClientError, LLMJsonCompletionResult, run_llm_json_completion


class _FakeTransportResponse:
    def __init__(self, body: bytes, *, status: int = 200) -> None:
        self._body = body
        self.status = status
        self.headers = {
            "Content-Type": "application/json; charset=utf-8",
            "X-Request-ID": "synthetic-provider-request",
        }

    def __enter__(self) -> _FakeTransportResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _completion(payload: dict[str, Any]) -> LLMJsonCompletionResult:
    return LLMJsonCompletionResult(
        provider="test",
        base_url="https://provider.example/v1",
        model_name="test-model",
        endpoint="https://provider.example/v1/chat/completions",
        response_text=json.dumps(payload, ensure_ascii=False),
        parsed_json=payload,
        usage={"prompt_tokens": 11, "completion_tokens": 7},
        temperature=0.2,
        reasoning_text="可审计推理",
        reasoning_transport="dashscope_enable_thinking",
    )


def test_provider_response_is_replayed_after_downstream_crash(tmp_path: Path) -> None:
    calls = 0

    def provider(**_kwargs: Any) -> LLMJsonCompletionResult:
        nonlocal calls
        calls += 1
        return _completion({"假设": "有限区间存在可证伪顺序结构"})

    kwargs = {
        "messages": [{"role": "user", "content": "生成假设"}],
        "config_path": Path("config.yaml"),
        "env_path": Path(".env"),
        "max_tokens": 100,
        "temperature": 0.2,
        "response_schema": {"type": "object"},
        "response_schema_name": "hypothesis",
    }
    first = replayable_stage_completion(
        root=tmp_path,
        stage_name="hypothesis",
        stage_input_hash="a" * 64,
        completion=provider,
    )(**kwargs)

    # Simulate a process crash after the paid response but before its stage
    # artifact was materialized.  The new process creates a new wrapper.
    replay = replayable_stage_completion(
        root=tmp_path,
        stage_name="hypothesis",
        stage_input_hash="a" * 64,
        completion=lambda **_kwargs: pytest.fail("provider must not be called twice"),
    )(**kwargs)

    assert replay == first
    assert calls == 1
    assert provider_checkpoint_count(tmp_path, stage_name="hypothesis") == 1


@pytest.mark.parametrize("finish_reason", ["stop", "length"])
def test_http_success_business_json_failure_is_escrowed_and_replayed_without_repay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    finish_reason: str,
) -> None:
    calls = 0
    invalid_content = '{"status":'
    usage = {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
    raw_body = json.dumps(
        {
            "id": "synthetic-provider-response-id",
            "choices": [
                {
                    "finish_reason": finish_reason,
                    "message": {
                        "content": invalid_content,
                        "reasoning_content": "bounded synthetic reasoning",
                    },
                }
            ],
            "usage": usage,
        }
    ).encode("utf-8")

    def opener(
        _request: urllib.request.Request,
        *,
        timeout: int,
    ) -> _FakeTransportResponse:
        nonlocal calls
        del timeout
        calls += 1
        return _FakeTransportResponse(raw_body)

    monkeypatch.setenv("AUTORESEARCH_LLM_API_KEY", "unit-only-placeholder-key")
    kwargs = {
        "messages": [{"role": "user", "content": "Return one synthetic JSON object."}],
        "config_path": Path("missing-config.yaml"),
        "env_path": Path("missing.env"),
        "max_tokens": 32,
        "temperature": 0.0,
        "_http_opener": opener,
        "_request_id_factory": lambda: "request-stage-parse-failure-0001",
    }
    first_provider = replayable_stage_completion(
        root=tmp_path,
        stage_name="hypothesis-brainstorm",
        stage_input_hash="7" * 64,
        completion=run_llm_json_completion,
    )

    with pytest.raises(LLMClientError, match="not valid JSON") as first:
        first_provider(**kwargs)

    failure_paths = list(
        (tmp_path / "checkpoints" / "provider-response-failures" / "hypothesis-brainstorm").glob(
            "*.json"
        )
    )
    assert calls == 1
    assert len(failure_paths) == 1
    failure = json.loads(failure_paths[0].read_text(encoding="utf-8"))
    assert failure["status"] == "parse_failed"
    assert failure["response_text"] == invalid_content
    assert failure["response_usage"] == usage
    assert failure["finish_reason"] == finish_reason
    assert failure["parse_diagnostic"] == {
        "kind": "json_decode_error",
        "lineno": 1,
        "colno": 11,
        "pos": 10,
    }
    assert failure["transport_trace"]["http_status_code"] == 200
    rendered = json.dumps(failure, ensure_ascii=False)
    assert "synthetic-provider-response-id" not in rendered
    assert "bounded synthetic reasoning" not in rendered
    validate_persistable_content(failure)

    replay = replayable_stage_completion(
        root=tmp_path,
        stage_name="hypothesis-brainstorm",
        stage_input_hash="7" * 64,
        completion=lambda **_kwargs: pytest.fail("provider must not be called on replay"),
    )
    with pytest.raises(LLMClientError, match="not valid JSON") as second:
        replay(**kwargs)

    assert calls == 1
    assert second.value.response_text == first.value.response_text
    assert second.value.response_usage == first.value.response_usage
    assert second.value.finish_reason == first.value.finish_reason
    assert second.value.transport_trace == first.value.transport_trace
    assert provider_checkpoint_accounting(
        tmp_path,
        stage_name="hypothesis-brainstorm",
    ) == {
        "attempt_count": 1,
        "completed_count": 0,
        "parse_failed_count": 1,
        "transport_failed_count": 0,
        "terminal_failed_count": 0,
        "outcome_unknown_count": 0,
    }
    assert provider_checkpoint_count(tmp_path, stage_name="hypothesis-brainstorm") == 0


@pytest.mark.parametrize(
    ("tamper_kind", "expected_error"),
    [("usage", "usage differs"), ("diagnostic", "diagnostic differs")],
)
def test_parse_failure_escrow_revalidates_inner_response_and_transport_hashes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper_kind: str,
    expected_error: str,
) -> None:
    raw_body = json.dumps(
        {
            "choices": [{"finish_reason": "stop", "message": {"content": '{"x":'}}],
            "usage": {"total_tokens": 2},
        }
    ).encode("utf-8")
    monkeypatch.setenv("AUTORESEARCH_LLM_API_KEY", "unit-only-placeholder-key")
    kwargs = {
        "messages": [{"role": "user", "content": "Return synthetic JSON."}],
        "config_path": Path("missing-config.yaml"),
        "env_path": Path("missing.env"),
        "_http_opener": lambda *_args, **_kwargs: _FakeTransportResponse(raw_body),
        "_request_id_factory": lambda: "request-stage-parse-failure-0002",
    }
    invoke = replayable_stage_completion(
        root=tmp_path,
        stage_name="provisional-plan",
        stage_input_hash="8" * 64,
        completion=run_llm_json_completion,
    )
    with pytest.raises(LLMClientError, match="not valid JSON"):
        invoke(**kwargs)

    path = next((tmp_path / "checkpoints" / "provider-response-failures").rglob("*.json"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    if tamper_kind == "usage":
        payload["response_usage"]["total_tokens"] = 999
    else:
        payload["parse_diagnostic"]["pos"] += 1
    response = {
        key: payload[key]
        for key in (
            "failure_message",
            "parse_diagnostic",
            "response_text",
            "response_usage",
            "finish_reason",
            "transport_trace",
        )
    }
    payload["failure_response_hash"] = checkpoint_module.canonical_model_hash(response)
    payload["checkpoint_hash"] = checkpoint_module.canonical_model_hash(
        {key: value for key, value in payload.items() if key != "checkpoint_hash"}
    )
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    renamed = path.with_name(
        f"{'8' * 16}-{payload['request_hash']}-{payload['failure_response_hash']}.json"
    )
    path.rename(renamed)

    with pytest.raises(ContestDirectionStageCheckpointError, match=expected_error):
        invoke(**kwargs)


def test_legacy_v1_transport_reservation_cannot_be_upgraded_into_retry_eligibility(
    tmp_path: Path,
) -> None:
    calls = 0

    def provider(**_kwargs: Any) -> LLMJsonCompletionResult:
        nonlocal calls
        calls += 1
        return _completion({"status": "must-not-run"})

    kwargs = {
        "messages": [{"role": "user", "content": "Return synthetic JSON."}],
        "config_path": Path("missing-config.yaml"),
        "env_path": Path("missing.env"),
    }
    request_payload = checkpoint_module._completion_request_payload(kwargs)
    request_hash = checkpoint_module.canonical_model_hash(request_payload)
    request_bytes = b'{"legacy":"reservation-only"}'
    preflight = llm_client_module._build_transport_preflight(
        request_id="request-stage-legacy-reservation-0001",
        adapter_id="autoresearch.openai-compatible-http.v1",
        endpoint="https://provider.example/v1/chat/completions",
        request_payload=request_bytes,
        implementation="injected_test_opener",
    )
    reservation_path = (
        tmp_path
        / "checkpoints"
        / "provider-call-reservations"
        / "independent-scientific-review"
        / f"{'9' * 16}-{request_hash}.json"
    )
    checkpoint_module._record_provider_call_reservation(
        reservation_path,
        stage_name="independent-scientific-review",
        stage_input_hash="9" * 64,
        request_hash=request_hash,
        request_payload=request_payload,
        preflight=preflight,
        request_bytes=request_bytes,
    )
    invoke = replayable_stage_completion(
        root=tmp_path,
        stage_name="independent-scientific-review",
        stage_input_hash="9" * 64,
        completion=provider,
    )
    with pytest.raises(ContestDirectionStageCheckpointError, match="outcome is unknown"):
        invoke(**kwargs)
    assert calls == 0
    assert not list((tmp_path / "checkpoints" / "provider-call-attempts").rglob("*.json"))
    assert provider_checkpoint_accounting(
        tmp_path,
        stage_name="independent-scientific-review",
    ) == {
        "attempt_count": 1,
        "completed_count": 0,
        "parse_failed_count": 0,
        "transport_failed_count": 0,
        "terminal_failed_count": 0,
        "outcome_unknown_count": 1,
    }


def test_persisted_pure_transport_failure_authorizes_exactly_one_physical_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[urllib.request.Request] = []
    request_ids = iter(
        [
            "request-stage-transport-retry-0001",
            "request-stage-transport-retry-0002",
        ]
    )
    raw_body = json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": '{"status":"complete"}'},
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        }
    ).encode("utf-8")

    def opener(request: urllib.request.Request, *, timeout: int) -> _FakeTransportResponse:
        del timeout
        requests.append(request)
        if len(requests) == 1:
            raise urllib.error.URLError("synthetic transport outage")
        return _FakeTransportResponse(raw_body)

    monkeypatch.setenv("AUTORESEARCH_LLM_API_KEY", "unit-only-placeholder-key")
    invoke = replayable_stage_completion(
        root=tmp_path,
        stage_name="focus-selection",
        stage_input_hash="a" * 64,
        completion=run_llm_json_completion,
    )
    result = invoke(
        messages=[{"role": "user", "content": "Return synthetic JSON."}],
        config_path=Path("missing-config.yaml"),
        env_path=Path("missing.env"),
        _http_opener=opener,
        _request_id_factory=lambda: next(request_ids),
    )

    assert result.parsed_json == {"status": "complete"}
    assert len(requests) == 2
    assert requests[0].data == requests[1].data
    observed_ids = [
        next(
            value
            for name, value in request.header_items()
            if name.casefold() == "x-autoresearch-request-id"
        )
        for request in requests
    ]
    assert observed_ids == [
        "request-stage-transport-retry-0001",
        "request-stage-transport-retry-0002",
    ]
    attempt_paths = sorted(
        (tmp_path / "checkpoints" / "provider-call-attempts" / "focus-selection").rglob(
            "attempt-*-reservation.json"
        )
    )
    failure_paths = sorted(
        (tmp_path / "checkpoints" / "provider-call-attempts" / "focus-selection").rglob(
            "attempt-*-transport-failure.json"
        )
    )
    assert len(attempt_paths) == 2
    assert len(failure_paths) == 1
    first_attempt = json.loads(attempt_paths[0].read_text(encoding="utf-8"))
    second_attempt = json.loads(attempt_paths[1].read_text(encoding="utf-8"))
    failure = json.loads(failure_paths[0].read_text(encoding="utf-8"))
    assert failure["failure_code"] == "transport_no_http_response"
    assert "synthetic transport outage" not in json.dumps(failure, ensure_ascii=False)
    assert first_attempt["attempt_index"] == 1
    assert second_attempt["attempt_index"] == 2
    assert (
        first_attempt["transport_preflight"]["request_payload_sha256"]
        == second_attempt["transport_preflight"]["request_payload_sha256"]
    )
    assert (
        first_attempt["transport_preflight"]["request_id"]
        != second_attempt["transport_preflight"]["request_id"]
    )
    assert failure["response_text"] is None
    assert failure["transport_trace"] is None
    assert failure["transport_failure_trace"]["failure_stage"] == "transport"
    assert failure["transport_failure_trace"]["transport_attempted"] is True
    assert failure["transport_failure_trace"]["http_response_received"] is False
    assert provider_checkpoint_accounting(tmp_path, stage_name="focus-selection") == {
        "attempt_count": 2,
        "completed_count": 1,
        "parse_failed_count": 0,
        "transport_failed_count": 1,
        "terminal_failed_count": 0,
        "outcome_unknown_count": 0,
    }


def test_two_transport_failures_are_replayed_locally_without_a_third_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    request_ids = iter(
        [
            "request-stage-transport-terminal-0001",
            "request-stage-transport-terminal-0002",
        ]
    )

    def opener(_request: urllib.request.Request, *, timeout: int) -> _FakeTransportResponse:
        nonlocal calls
        del timeout
        calls += 1
        raise urllib.error.URLError(f"synthetic transport outage {calls}")

    monkeypatch.setenv("AUTORESEARCH_LLM_API_KEY", "unit-only-placeholder-key")
    kwargs = {
        "messages": [{"role": "user", "content": "Return synthetic JSON."}],
        "config_path": Path("missing-config.yaml"),
        "env_path": Path("missing.env"),
        "_http_opener": opener,
        "_request_id_factory": lambda: next(request_ids),
    }
    first_invoke = replayable_stage_completion(
        root=tmp_path,
        stage_name="independent-scientific-review",
        stage_input_hash="b" * 64,
        completion=run_llm_json_completion,
    )
    with pytest.raises(LLMClientError, match="request failed") as first_error:
        first_invoke(**kwargs)

    assert calls == 2
    assert first_error.value.response_text is None
    assert first_error.value.transport_failure_trace is not None
    assert first_error.value.transport_failure_trace.failure_stage == "transport"
    replay = replayable_stage_completion(
        root=tmp_path,
        stage_name="independent-scientific-review",
        stage_input_hash="b" * 64,
        completion=lambda **_kwargs: pytest.fail("a third physical attempt is forbidden"),
    )
    with pytest.raises(LLMClientError, match="request failed") as replay_error:
        replay(**kwargs)

    assert calls == 2
    assert replay_error.value.response_text is None
    assert replay_error.value.transport_failure_trace == first_error.value.transport_failure_trace
    assert provider_checkpoint_accounting(
        tmp_path,
        stage_name="independent-scientific-review",
    ) == {
        "attempt_count": 2,
        "completed_count": 0,
        "parse_failed_count": 0,
        "transport_failed_count": 2,
        "terminal_failed_count": 0,
        "outcome_unknown_count": 0,
    }


def test_terminal_transport_error_never_exposes_raw_exception_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_reason = "synthetic.person@example.test"
    calls = 0
    request_ids = iter(["request-secret-safe-0001", "request-secret-safe-0002"])

    def opener(_request: urllib.request.Request, *, timeout: int) -> _FakeTransportResponse:
        nonlocal calls
        del timeout
        calls += 1
        raise urllib.error.URLError(secret_reason)

    monkeypatch.setenv("AUTORESEARCH_LLM_API_KEY", "unit-only-placeholder-key")
    invoke = replayable_stage_completion(
        root=tmp_path,
        stage_name="independent-scientific-review",
        stage_input_hash="b" * 64,
        completion=run_llm_json_completion,
    )
    with pytest.raises(LLMClientError, match="provider transport request failed") as error:
        invoke(
            messages=[{"role": "user", "content": "Return synthetic JSON."}],
            config_path=Path("missing-config.yaml"),
            env_path=Path("missing.env"),
            _http_opener=opener,
            _request_id_factory=lambda: next(request_ids),
        )

    assert calls == 2
    assert secret_reason not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__ is True
    assert secret_reason not in "".join(traceback.format_exception(error.value))
    persisted = "\n".join(path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.json"))
    assert secret_reason not in persisted


def test_crash_after_first_transport_trace_can_resume_only_the_second_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    first_ids = iter(["request-stage-crash-retry-0001"])
    raw_body = json.dumps(
        {
            "choices": [{"message": {"content": '{"status":"complete"}'}}],
            "usage": {"total_tokens": 4},
        }
    ).encode("utf-8")

    def opener(request: urllib.request.Request, *, timeout: int) -> _FakeTransportResponse:
        nonlocal calls
        del request, timeout
        calls += 1
        if calls == 1:
            raise urllib.error.URLError("synthetic first-attempt outage")
        return _FakeTransportResponse(raw_body)

    def crash_before_second_preflight() -> str:
        try:
            return next(first_ids)
        except StopIteration:
            raise SystemExit("synthetic crash before attempt-2 reservation") from None

    monkeypatch.setenv("AUTORESEARCH_LLM_API_KEY", "unit-only-placeholder-key")
    kwargs = {
        "messages": [{"role": "user", "content": "Return synthetic JSON."}],
        "config_path": Path("missing-config.yaml"),
        "env_path": Path("missing.env"),
        "_http_opener": opener,
        "_request_id_factory": crash_before_second_preflight,
    }
    invoke = replayable_stage_completion(
        root=tmp_path,
        stage_name="provisional-plan",
        stage_input_hash="c" * 64,
        completion=run_llm_json_completion,
    )
    with pytest.raises(SystemExit, match="before attempt-2"):
        invoke(**kwargs)

    resumed = replayable_stage_completion(
        root=tmp_path,
        stage_name="provisional-plan",
        stage_input_hash="c" * 64,
        completion=run_llm_json_completion,
    )
    result = resumed(
        **{
            **kwargs,
            "_request_id_factory": lambda: "request-stage-crash-retry-0002",
        }
    )
    assert result.parsed_json == {"status": "complete"}
    assert calls == 2
    assert (
        provider_checkpoint_accounting(tmp_path, stage_name="provisional-plan")["attempt_count"]
        == 2
    )


def test_crash_after_second_reservation_is_fail_closed_on_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    request_ids = iter(
        [
            "request-stage-second-reservation-0001",
            "request-stage-second-reservation-0002",
        ]
    )

    def opener(_request: urllib.request.Request, *, timeout: int) -> _FakeTransportResponse:
        nonlocal calls
        del timeout
        calls += 1
        if calls == 1:
            raise urllib.error.URLError("synthetic first-attempt outage")
        raise SystemExit("synthetic crash after attempt-2 reservation")

    monkeypatch.setenv("AUTORESEARCH_LLM_API_KEY", "unit-only-placeholder-key")
    kwargs = {
        "messages": [{"role": "user", "content": "Return synthetic JSON."}],
        "config_path": Path("missing-config.yaml"),
        "env_path": Path("missing.env"),
        "_http_opener": opener,
        "_request_id_factory": lambda: next(request_ids),
    }
    invoke = replayable_stage_completion(
        root=tmp_path,
        stage_name="final-plan-revision",
        stage_input_hash="d" * 64,
        completion=run_llm_json_completion,
    )
    with pytest.raises(SystemExit, match="after attempt-2 reservation"):
        invoke(**kwargs)

    with pytest.raises(ContestDirectionStageCheckpointError, match="outcome is unknown"):
        invoke(**kwargs)
    assert calls == 2
    assert provider_checkpoint_accounting(tmp_path, stage_name="final-plan-revision") == {
        "attempt_count": 2,
        "completed_count": 0,
        "parse_failed_count": 0,
        "transport_failed_count": 1,
        "terminal_failed_count": 0,
        "outcome_unknown_count": 1,
    }


@pytest.mark.parametrize("status", [429, 503])
def test_http_response_failure_is_never_transport_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    calls = 0

    def opener(_request: urllib.request.Request, *, timeout: int) -> _FakeTransportResponse:
        nonlocal calls
        del timeout
        calls += 1
        return _FakeTransportResponse(b'{"error":"synthetic unavailable"}', status=status)

    monkeypatch.setenv("AUTORESEARCH_LLM_API_KEY", "unit-only-placeholder-key")
    invoke = replayable_stage_completion(
        root=tmp_path,
        stage_name="targeted-literature-query",
        stage_input_hash="e" * 64,
        completion=run_llm_json_completion,
    )
    kwargs = {
        "messages": [{"role": "user", "content": "Return synthetic JSON."}],
        "config_path": Path("missing-config.yaml"),
        "env_path": Path("missing.env"),
        "_http_opener": opener,
        "_request_id_factory": lambda: "request-stage-http-terminal-0001",
    }
    with pytest.raises(LLMClientError, match=f"HTTP {status}") as exc_info:
        invoke(**kwargs)

    assert calls == 1
    assert exc_info.value.transport_failure_trace is not None
    assert exc_info.value.transport_failure_trace.failure_stage == "http_response"
    assert exc_info.value.transport_failure_trace.http_response_received is True
    assert not list(
        (tmp_path / "checkpoints" / "provider-call-attempts").rglob("*transport-failure.json")
    )
    terminal_paths = list((tmp_path / "checkpoints" / "provider-terminal-failures").rglob("*.json"))
    assert len(terminal_paths) == 1
    terminal = json.loads(terminal_paths[0].read_text(encoding="utf-8"))
    assert terminal["status"] == "response_failed"
    assert terminal["response_text"] is None
    assert terminal["transport_failure_trace"]["failure_stage"] == "http_response"
    assert "synthetic unavailable" not in json.dumps(terminal, ensure_ascii=False)

    with pytest.raises(LLMClientError, match=f"HTTP {status}") as replay_error:
        invoke(**kwargs)
    assert calls == 1
    assert replay_error.value.transport_failure_trace == exc_info.value.transport_failure_trace
    assert provider_checkpoint_accounting(tmp_path, stage_name="targeted-literature-query") == {
        "attempt_count": 1,
        "completed_count": 0,
        "parse_failed_count": 0,
        "transport_failed_count": 0,
        "terminal_failed_count": 1,
        "outcome_unknown_count": 0,
    }


@pytest.mark.parametrize("raw_body", [b"\xff", b"{", b"[]"])
def test_received_http_body_decode_or_envelope_failure_is_terminal_and_replayed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raw_body: bytes,
) -> None:
    calls = 0

    def opener(_request: urllib.request.Request, *, timeout: int) -> _FakeTransportResponse:
        nonlocal calls
        del timeout
        calls += 1
        return _FakeTransportResponse(raw_body)

    monkeypatch.setenv("AUTORESEARCH_LLM_API_KEY", "unit-only-placeholder-key")
    kwargs = {
        "messages": [{"role": "user", "content": "Return synthetic JSON."}],
        "config_path": Path("missing-config.yaml"),
        "env_path": Path("missing.env"),
        "_http_opener": opener,
        "_request_id_factory": lambda: "request-stage-envelope-terminal-0001",
    }
    invoke = replayable_stage_completion(
        root=tmp_path,
        stage_name="provisional-plan",
        stage_input_hash="f" * 64,
        completion=run_llm_json_completion,
    )
    with pytest.raises(LLMClientError) as first:
        invoke(**kwargs)
    assert first.value.transport_trace is not None

    with pytest.raises(LLMClientError) as replay:
        invoke(**kwargs)
    assert calls == 1
    assert replay.value.transport_trace == first.value.transport_trace


def test_terminal_failure_replay_rejects_rehashed_attempt_index_and_renamed_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTORESEARCH_LLM_API_KEY", "unit-only-placeholder-key")
    kwargs = {
        "messages": [{"role": "user", "content": "Return synthetic JSON."}],
        "config_path": Path("missing-config.yaml"),
        "env_path": Path("missing.env"),
        "_http_opener": lambda *_args, **_kwargs: _FakeTransportResponse(
            b'{"error":"synthetic unavailable"}', status=503
        ),
        "_request_id_factory": lambda: "request-terminal-index-tamper-0001",
    }
    invoke = replayable_stage_completion(
        root=tmp_path,
        stage_name="targeted-literature-query",
        stage_input_hash="0" * 64,
        completion=run_llm_json_completion,
    )
    with pytest.raises(LLMClientError, match="HTTP 503"):
        invoke(**kwargs)

    path = next((tmp_path / "checkpoints" / "provider-terminal-failures").rglob("*.json"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["attempt_index"] = 2
    payload["checkpoint_hash"] = checkpoint_module.canonical_model_hash(
        {key: value for key, value in payload.items() if key != "checkpoint_hash"}
    )
    renamed = path.with_name(path.name.replace("attempt-01", "attempt-02"))
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    path.rename(renamed)

    with pytest.raises(ContestDirectionStageCheckpointError, match="binding|attempt index"):
        invoke(**kwargs)


def test_terminal_failure_replay_rejects_rehashed_code_trace_kind_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTORESEARCH_LLM_API_KEY", "unit-only-placeholder-key")
    kwargs = {
        "messages": [{"role": "user", "content": "Return synthetic JSON."}],
        "config_path": Path("missing-config.yaml"),
        "env_path": Path("missing.env"),
        "_http_opener": lambda *_args, **_kwargs: _FakeTransportResponse(
            b'{"error":"synthetic unavailable"}', status=503
        ),
        "_request_id_factory": lambda: "request-terminal-code-tamper-0001",
    }
    invoke = replayable_stage_completion(
        root=tmp_path,
        stage_name="targeted-literature-query",
        stage_input_hash="1" * 64,
        completion=run_llm_json_completion,
    )
    with pytest.raises(LLMClientError, match="HTTP 503"):
        invoke(**kwargs)

    path = next((tmp_path / "checkpoints" / "provider-terminal-failures").rglob("*.json"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    old_failure_hash = payload["failure_hash"]
    payload["failure_code"] = "http_response_decode_failure"
    material = {
        key: payload[key]
        for key in (
            "failure_code",
            "response_text",
            "response_usage",
            "finish_reason",
            "transport_trace",
            "transport_failure_trace",
        )
    }
    payload["failure_hash"] = checkpoint_module.canonical_model_hash(material)
    payload["checkpoint_hash"] = checkpoint_module.canonical_model_hash(
        {key: value for key, value in payload.items() if key != "checkpoint_hash"}
    )
    renamed = path.with_name(path.name.replace(old_failure_hash, payload["failure_hash"]))
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    path.rename(renamed)

    with pytest.raises(
        ContestDirectionStageCheckpointError,
        match="terminal response failure fields are invalid",
    ):
        invoke(**kwargs)


def test_attempt_two_business_parse_failure_binds_second_reservation_and_never_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    request_ids = iter(
        [
            "request-stage-cross-terminal-0001",
            "request-stage-cross-terminal-0002",
        ]
    )
    raw_body = json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"content": '{"status":'},
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        }
    ).encode("utf-8")

    def opener(_request: urllib.request.Request, *, timeout: int) -> _FakeTransportResponse:
        nonlocal calls
        del timeout
        calls += 1
        if calls == 1:
            raise urllib.error.URLError("synthetic first-attempt outage")
        return _FakeTransportResponse(raw_body)

    monkeypatch.setenv("AUTORESEARCH_LLM_API_KEY", "unit-only-placeholder-key")
    kwargs = {
        "messages": [{"role": "user", "content": "Return synthetic JSON."}],
        "config_path": Path("missing-config.yaml"),
        "env_path": Path("missing.env"),
        "_http_opener": opener,
        "_request_id_factory": lambda: next(request_ids),
    }
    invoke = replayable_stage_completion(
        root=tmp_path,
        stage_name="final-plan-revision",
        stage_input_hash="1" * 64,
        completion=run_llm_json_completion,
    )
    with pytest.raises(LLMClientError, match="not valid JSON") as first:
        invoke(**kwargs)
    assert calls == 2
    assert first.value.transport_trace is not None
    assert first.value.transport_trace.request_id == "request-stage-cross-terminal-0002"

    with pytest.raises(LLMClientError, match="not valid JSON") as replay:
        invoke(**kwargs)
    assert calls == 2
    assert replay.value.transport_trace == first.value.transport_trace
    assert provider_checkpoint_accounting(tmp_path, stage_name="final-plan-revision") == {
        "attempt_count": 2,
        "completed_count": 0,
        "parse_failed_count": 1,
        "transport_failed_count": 1,
        "terminal_failed_count": 0,
        "outcome_unknown_count": 0,
    }


@pytest.mark.parametrize(
    "read_error",
    [
        OSError("synthetic response read failed"),
        http.client.IncompleteRead(b"", 10),
    ],
)
def test_response_read_failure_is_not_misclassified_as_retryable_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    read_error: BaseException,
) -> None:
    calls = 0

    class ReadFailureResponse(_FakeTransportResponse):
        def read(self) -> bytes:
            raise read_error

    def opener(_request: urllib.request.Request, *, timeout: int) -> _FakeTransportResponse:
        nonlocal calls
        del timeout
        calls += 1
        return ReadFailureResponse(b"")

    monkeypatch.setenv("AUTORESEARCH_LLM_API_KEY", "unit-only-placeholder-key")
    kwargs = {
        "messages": [{"role": "user", "content": "Return synthetic JSON."}],
        "config_path": Path("missing-config.yaml"),
        "env_path": Path("missing.env"),
        "_http_opener": opener,
        "_request_id_factory": lambda: "request-stage-read-failure-0001",
    }
    invoke = replayable_stage_completion(
        root=tmp_path,
        stage_name="independent-scientific-review",
        stage_input_hash="2" * 64,
        completion=run_llm_json_completion,
    )
    with pytest.raises(LLMClientError, match="response processing failed") as error:
        invoke(**kwargs)
    assert calls == 1
    assert error.value.transport_failure_trace is None

    with pytest.raises(ContestDirectionStageCheckpointError, match="outcome is unknown"):
        invoke(**kwargs)
    assert calls == 1


def test_transport_error_message_without_a_qualifying_trace_never_retries(
    tmp_path: Path,
) -> None:
    calls = 0
    request_bytes = b'{"synthetic":"request"}'

    def lookalike_provider(
        *,
        transport_preflight_hook: object,
        **_kwargs: object,
    ) -> LLMJsonCompletionResult:
        nonlocal calls
        calls += 1
        assert callable(transport_preflight_hook)
        preflight = llm_client_module._build_transport_preflight(
            request_id="request-lookalike-no-trace-0001",
            adapter_id="autoresearch.openai-compatible-http.v1",
            endpoint="https://provider.example/v1/chat/completions",
            request_payload=request_bytes,
            implementation="injected_test_opener",
        )
        transport_preflight_hook(preflight, request_bytes)
        raise LLMClientError("synthetic WinError 10060 transport-looking message")

    kwargs = {"messages": [{"role": "user", "content": "Return synthetic JSON."}]}
    invoke = replayable_stage_completion(
        root=tmp_path,
        stage_name="focus-selection",
        stage_input_hash="3" * 64,
        completion=lookalike_provider,
    )
    with pytest.raises(LLMClientError, match="10060"):
        invoke(**kwargs)
    with pytest.raises(ContestDirectionStageCheckpointError, match="outcome is unknown"):
        invoke(**kwargs)

    assert calls == 1
    assert not list(
        (tmp_path / "checkpoints" / "provider-call-attempts").rglob("*transport-failure.json")
    )


def test_transport_failure_replay_rejects_rehashed_non_null_response_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_ids = iter(["request-tamper-0001", "request-tamper-0002"])

    def opener(_request: urllib.request.Request, *, timeout: int) -> _FakeTransportResponse:
        del timeout
        raise urllib.error.URLError("synthetic transport outage")

    monkeypatch.setenv("AUTORESEARCH_LLM_API_KEY", "unit-only-placeholder-key")
    kwargs = {
        "messages": [{"role": "user", "content": "Return synthetic JSON."}],
        "config_path": Path("missing-config.yaml"),
        "env_path": Path("missing.env"),
        "_http_opener": opener,
        "_request_id_factory": lambda: next(request_ids),
    }
    invoke = replayable_stage_completion(
        root=tmp_path,
        stage_name="independent-scientific-review",
        stage_input_hash="4" * 64,
        completion=run_llm_json_completion,
    )
    with pytest.raises(LLMClientError, match="request failed"):
        invoke(**kwargs)

    path = next(
        path
        for path in (tmp_path / "checkpoints" / "provider-call-attempts").rglob(
            "attempt-02-transport-failure.json"
        )
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["response_text"] = "synthetic non-null response"
    material = {
        key: payload[key]
        for key in (
            "failure_code",
            "response_text",
            "response_usage",
            "finish_reason",
            "transport_trace",
            "transport_failure_trace",
        )
    }
    payload["failure_hash"] = checkpoint_module.canonical_model_hash(material)
    payload["checkpoint_hash"] = checkpoint_module.canonical_model_hash(
        {key: value for key, value in payload.items() if key != "checkpoint_hash"}
    )
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ContestDirectionStageCheckpointError, match="strictly retry-eligible"):
        invoke(**kwargs)


def test_sensitive_parse_response_is_not_persisted_and_blocks_automatic_repay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    sensitive_fragment = "synthetic.person@example.test"
    raw_body = json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": f'{{"contact":"{sensitive_fragment}"'},
                }
            ],
            "usage": {"total_tokens": 4},
        }
    ).encode("utf-8")

    def opener(_request: urllib.request.Request, *, timeout: int) -> _FakeTransportResponse:
        nonlocal calls
        del timeout
        calls += 1
        return _FakeTransportResponse(raw_body)

    monkeypatch.setenv("AUTORESEARCH_LLM_API_KEY", "unit-only-placeholder-key")
    kwargs = {
        "messages": [{"role": "user", "content": "Return synthetic JSON."}],
        "config_path": Path("missing-config.yaml"),
        "env_path": Path("missing.env"),
        "_http_opener": opener,
        "_request_id_factory": lambda: "request-stage-sensitive-0001",
    }
    invoke = replayable_stage_completion(
        root=tmp_path,
        stage_name="final-plan-revision",
        stage_input_hash="6" * 64,
        completion=run_llm_json_completion,
    )

    with pytest.raises(ContestDirectionStageCheckpointError, match="invalid or unsafe"):
        invoke(**kwargs)

    assert calls == 1
    assert not list((tmp_path / "checkpoints" / "provider-response-failures").rglob("*.json"))
    persisted = "\n".join(path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.json"))
    assert sensitive_fragment not in persisted
    with pytest.raises(ContestDirectionStageCheckpointError, match="outcome is unknown"):
        invoke(**kwargs)
    assert calls == 1
    assert provider_checkpoint_accounting(tmp_path, stage_name="final-plan-revision") == {
        "attempt_count": 1,
        "completed_count": 0,
        "parse_failed_count": 0,
        "transport_failed_count": 0,
        "terminal_failed_count": 0,
        "outcome_unknown_count": 1,
    }


def test_provider_wrapper_preserves_custom_completion_without_preflight_keyword(
    tmp_path: Path,
) -> None:
    calls = 0

    def provider(
        *,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> LLMJsonCompletionResult:
        nonlocal calls
        calls += 1
        assert messages == [{"role": "user", "content": "synthetic request"}]
        assert max_tokens == 12
        return _completion({"status": "complete"})

    invoke = replayable_stage_completion(
        root=tmp_path,
        stage_name="focus-selection",
        stage_input_hash="5" * 64,
        completion=provider,
    )

    first = invoke(
        messages=[{"role": "user", "content": "synthetic request"}],
        max_tokens=12,
    )
    replay = invoke(
        messages=[{"role": "user", "content": "synthetic request"}],
        max_tokens=12,
    )

    assert calls == 1
    assert replay == first
    assert provider_checkpoint_accounting(tmp_path, stage_name="focus-selection") == {
        "attempt_count": 1,
        "completed_count": 1,
        "parse_failed_count": 0,
        "transport_failed_count": 0,
        "terminal_failed_count": 0,
        "outcome_unknown_count": 0,
    }


def test_nested_replayable_wrappers_do_not_duplicate_provider_call_or_accounting(
    tmp_path: Path,
) -> None:
    calls = 0

    def provider(**_kwargs: Any) -> LLMJsonCompletionResult:
        nonlocal calls
        calls += 1
        return _completion({"status": "complete"})

    inner = replayable_stage_completion(
        root=tmp_path,
        stage_name="targeted-literature-query",
        stage_input_hash="4" * 64,
        completion=provider,
    )
    outer = replayable_stage_completion(
        root=tmp_path,
        stage_name="targeted-literature-query",
        stage_input_hash="4" * 64,
        completion=inner,
    )
    kwargs = {
        "messages": [{"role": "user", "content": "synthetic request"}],
        "max_tokens": 12,
    }

    first = outer(**kwargs)
    replay = outer(**kwargs)

    assert calls == 1
    assert replay == first
    assert len(list((tmp_path / "checkpoints" / "provider-responses").rglob("*.json"))) == 1
    assert provider_checkpoint_accounting(tmp_path, stage_name="targeted-literature-query") == {
        "attempt_count": 1,
        "completed_count": 1,
        "parse_failed_count": 0,
        "transport_failed_count": 0,
        "terminal_failed_count": 0,
        "outcome_unknown_count": 0,
    }


def test_legacy_alias_reservation_cannot_lock_a_canonical_owner_replay(
    tmp_path: Path,
) -> None:
    calls = 0

    def provider(**_kwargs: Any) -> LLMJsonCompletionResult:
        nonlocal calls
        calls += 1
        return _completion({"status": "complete"})

    kwargs = {
        "messages": [{"role": "user", "content": "synthetic source request"}],
        "max_tokens": 12,
    }
    canonical_root = tmp_path / "run"
    canonical = replayable_stage_completion(
        root=canonical_root,
        stage_name="focus-selection",
        stage_input_hash="5" * 64,
        completion=provider,
    )
    first = canonical(**kwargs)

    alias_root = canonical_root / "literature" / "refinement"
    alias_request = checkpoint_module._completion_request_payload(kwargs)
    alias_request_hash = checkpoint_module.canonical_model_hash(alias_request)
    request_bytes = b'{"legacy":"redundant-alias"}'
    preflight = llm_client_module._build_transport_preflight(
        request_id="request-legacy-alias-reservation-0001",
        adapter_id="autoresearch.openai-compatible-http.v1",
        endpoint="https://provider.example/v1/chat/completions",
        request_payload=request_bytes,
        implementation="injected_test_opener",
    )
    alias_reservation_path = (
        alias_root
        / "checkpoints"
        / "provider-call-reservations"
        / "direction-focus-selection"
        / f"{'6' * 16}-{alias_request_hash}.json"
    )
    checkpoint_module._record_provider_call_reservation(
        alias_reservation_path,
        stage_name="direction-focus-selection",
        stage_input_hash="6" * 64,
        request_hash=alias_request_hash,
        request_payload=alias_request,
        preflight=preflight,
        request_bytes=request_bytes,
    )

    redundant = replayable_stage_completion(
        root=alias_root,
        stage_name="direction-focus-selection",
        stage_input_hash="6" * 64,
        completion=canonical,
    )
    replay = redundant(**kwargs)

    assert replay == first
    assert calls == 1
    assert provider_checkpoint_count(canonical_root, stage_name="focus-selection") == 1
    assert (
        provider_checkpoint_accounting(
            alias_root,
            stage_name="direction-focus-selection",
        )["outcome_unknown_count"]
        == 1
    )


@pytest.mark.parametrize(
    "untrusted",
    [
        "sk-proj-abcdefghijklmnop",
        "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890",
        "研究者@例子.公司",
    ],
)
def test_provider_escrow_blocks_sensitive_request_before_hash_file_or_provider(
    tmp_path: Path,
    untrusted: str,
) -> None:
    calls = 0

    def provider(**_kwargs: Any) -> LLMJsonCompletionResult:
        nonlocal calls
        calls += 1
        return _completion({"status": "must-not-run"})

    invoke = replayable_stage_completion(
        root=tmp_path,
        stage_name="standalone-review",
        stage_input_hash="e" * 64,
        completion=provider,
    )

    with pytest.raises(ContestDirectionStageCheckpointError, match="sensitive provider request"):
        invoke(messages=[{"role": "user", "content": untrusted}], max_tokens=10)

    assert calls == 0
    assert provider_checkpoint_count(tmp_path, stage_name="standalone-review") == 0
    assert not list(tmp_path.rglob("*.json"))


def test_provider_escrow_scans_provider_visible_schema_strings_before_dispatch(
    tmp_path: Path,
) -> None:
    calls = 0

    def provider(**_kwargs: Any) -> LLMJsonCompletionResult:
        nonlocal calls
        calls += 1
        return _completion({"status": "must-not-run"})

    invoke = replayable_stage_completion(
        root=tmp_path,
        stage_name="schema-review",
        stage_input_hash="1" * 64,
        completion=provider,
    )

    with pytest.raises(ContestDirectionStageCheckpointError, match="sensitive provider request"):
        invoke(
            messages=[{"role": "user", "content": "safe request"}],
            response_schema={
                "type": "object",
                "description": "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890",
            },
        )

    assert calls == 0
    assert not list(tmp_path.rglob("*.json"))


@pytest.mark.parametrize(
    "untrusted_query",
    [
        "sk-proj-abcdefghijklmnop",
        "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890",
        "研究者@例子.公司",
    ],
)
def test_literature_escrow_blocks_sensitive_query_before_hash_file_or_source(
    tmp_path: Path,
    untrusted_query: str,
) -> None:
    calls = 0

    def source(_query: str, *, limit: int) -> list[Any]:
        nonlocal calls
        assert limit == 5
        calls += 1
        return []

    search = replayable_literature_searchers(
        root=tmp_path,
        searchers={"openalex": source},
    )["openalex"]

    with pytest.raises(ContestDirectionStageCheckpointError, match="sensitive literature request"):
        search(untrusted_query, limit=5)

    assert calls == 0
    assert not list(tmp_path.rglob("*.json"))


def test_legacy_sensitive_provider_escrow_stays_byte_exact_but_is_not_replayed(
    tmp_path: Path,
) -> None:
    stage_name = "legacy-review"
    stage_input_hash = "f" * 64
    kwargs = {
        "messages": [{"role": "user", "content": "sk-proj-abcdefghijklmnop"}],
        "max_tokens": 10,
    }
    request = checkpoint_module._completion_request_payload(kwargs)
    request_hash = checkpoint_module.canonical_model_hash(request)
    completion = _completion({"status": "historical"}).model_dump(mode="json")
    payload = {
        "schema_version": "contest-direction-provider-response-checkpoint-v1",
        "stage_name": stage_name,
        "stage_input_hash": stage_input_hash,
        "request_hash": request_hash,
        "request": request,
        "completion": completion,
        "completion_hash": checkpoint_module.canonical_model_hash(completion),
    }
    payload["checkpoint_hash"] = checkpoint_module.canonical_model_hash(payload)
    path = (
        tmp_path
        / "checkpoints"
        / "provider-responses"
        / stage_name
        / f"{stage_input_hash[:16]}-{request_hash}.json"
    )
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    original_bytes = path.read_bytes()
    calls = 0

    def provider(**_kwargs: Any) -> LLMJsonCompletionResult:
        nonlocal calls
        calls += 1
        return _completion({"status": "must-not-run"})

    invoke = replayable_stage_completion(
        root=tmp_path,
        stage_name=stage_name,
        stage_input_hash=stage_input_hash,
        completion=provider,
    )

    with pytest.raises(ContestDirectionStageCheckpointError, match="sensitive provider request"):
        invoke(**kwargs)

    assert calls == 0
    assert path.read_bytes() == original_bytes


def test_disabling_thinking_uses_a_new_provider_checkpoint_request(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    def provider(**kwargs: Any) -> LLMJsonCompletionResult:
        calls.append(kwargs)
        return _completion({"status": "complete"})

    invoke = replayable_stage_completion(
        root=tmp_path,
        stage_name="provisional-plan",
        stage_input_hash="f" * 64,
        completion=provider,
    )
    common = {
        "messages": [{"role": "user", "content": "生成内部预实验基线"}],
        "max_tokens": 14_000,
        "temperature": 0.2,
    }
    invoke(**common, thinking_mode="enabled", thinking_budget=3_000)
    invoke(**common, thinking_mode="disabled", thinking_budget=None)
    invoke(**common, thinking_mode="disabled", thinking_budget=None)

    assert [call["thinking_mode"] for call in calls] == ["enabled", "disabled"]
    assert provider_checkpoint_count(tmp_path, stage_name="provisional-plan") == 2


def test_response_replay_requires_exact_request_and_detects_tampering(
    tmp_path: Path,
) -> None:
    provider = replayable_stage_completion(
        root=tmp_path,
        stage_name="review",
        stage_input_hash="b" * 64,
        completion=lambda **_kwargs: _completion({"recommendation": "pass"}),
    )
    kwargs = {"messages": [{"role": "user", "content": "评审"}], "max_tokens": 10}
    provider(**kwargs)
    checkpoint = next((tmp_path / "checkpoints" / "provider-responses").rglob("*.json"))
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    payload["completion"]["parsed_json"]["recommendation"] = "fail"
    checkpoint.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ContestDirectionStageCheckpointError, match="binding/hash mismatch"):
        provider(**kwargs)


def test_completed_stage_rehashes_bound_artifacts(tmp_path: Path) -> None:
    artifact = tmp_path / "stage" / "artifact.json"
    artifact.parent.mkdir()
    artifact.write_text('{"status":"complete"}\n', encoding="utf-8")

    receipt = record_completed_stage(
        root=tmp_path,
        ordinal=3,
        stage_name="pilot",
        stage_input_hash="c" * 64,
        artifacts=(artifact,),
    )
    replay = load_completed_stage(
        root=tmp_path,
        ordinal=3,
        stage_name="pilot",
        stage_input_hash="c" * 64,
    )
    assert replay == receipt

    artifact.write_text('{"status":"changed"}\n', encoding="utf-8")
    with pytest.raises(ContestDirectionStageCheckpointError, match="bytes changed"):
        load_completed_stage(
            root=tmp_path,
            ordinal=3,
            stage_name="pilot",
            stage_input_hash="c" * 64,
        )


def test_literature_source_response_is_replayed_without_second_api_call(
    tmp_path: Path,
) -> None:
    calls = 0
    paper = {
        "title": "Prime gaps and residue classes",
        "authors": ["A"],
        "abstract": "A source-backed abstract.",
        "url": "https://example.org/paper",
        "source": "openalex",
    }

    def source(_query: str, *, limit: int) -> list[Any]:
        nonlocal calls
        calls += 1
        assert limit == 20
        from autoresearch.literature.models import AcademicPaper

        return [AcademicPaper.model_validate(paper)]

    first = replayable_literature_searchers(
        root=tmp_path,
        searchers={"openalex": source},
    )["openalex"]("prime gaps", limit=20)
    replay = replayable_literature_searchers(
        root=tmp_path,
        searchers={
            "openalex": lambda *_args, **_kwargs: pytest.fail(
                "completed API response must not be requested again"
            )
        },
    )["openalex"]("prime gaps", limit=20)

    assert calls == 1
    assert replay == first


@pytest.mark.parametrize("source_name", ["arxiv", "openalex", "semantic_scholar"])
def test_literature_source_checkpoint_normalizes_public_contact_identifiers_for_all_sources(
    tmp_path: Path,
    source_name: str,
) -> None:
    from autoresearch.literature.models import AcademicPaper

    paper = AcademicPaper(
        title="A source-backed normalization method",
        authors=["A. Researcher"],
        abstract=(
            "AVAILABILITY: public implementation. "
            "CONTACT: first.last@example.ac.uk SUPPLEMENTARY INFORMATION: online."
        ),
        url="https://doi.org/10.1000/example",
        source=source_name,
    )
    result = replayable_literature_searchers(
        root=tmp_path,
        searchers={source_name: lambda _query, *, limit: [paper][:limit]},
    )[source_name]("normalization method", limit=5)

    assert result[0].abstract is not None
    assert "example.ac.uk" not in result[0].abstract
    checkpoint = next(
        (tmp_path / "checkpoints" / "literature-searches" / source_name).glob("*.json")
    )
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "contest-direction-literature-search-checkpoint-v2"
    assert (
        payload["privacy_normalization"]["policy_version"]
        == SCHOLARLY_METADATA_PRIVACY_POLICY_VERSION
    )
    assert payload["privacy_normalization"]["total_redactions"] == 1
    assert payload["privacy_normalization"]["field_redaction_counts"] == {
        "papers[0].abstract": {"direct_email_identifier": 1}
    }
    validate_persistable_content(payload["papers"])


def test_truncated_private_key_source_result_writes_only_safe_failed_checkpoint(
    tmp_path: Path,
) -> None:
    from autoresearch.literature.models import AcademicPaper

    calls = 0

    def source(_query: str, *, limit: int) -> list[AcademicPaper]:
        nonlocal calls
        assert limit == 5
        calls += 1
        return [
            AcademicPaper(
                title="Unsafe source record",
                abstract=(
                    "-----BEGIN PRIVATE KEY-----\n"
                    "SUPERSECRETMATERIAL1234567890\nnormal trailing evidence"
                ),
                source="openalex",
            )
        ]

    search = replayable_literature_searchers(
        root=tmp_path,
        searchers={"openalex": source},
    )["openalex"]

    with pytest.raises(ScholarlyMetadataPrivacyError):
        search("safe query", limit=5)

    checkpoints = list((tmp_path / "checkpoints" / "literature-searches").rglob("*.json"))
    assert calls == 1
    assert len(checkpoints) == 1
    payload = json.loads(checkpoints[0].read_text(encoding="utf-8"))
    rendered = json.dumps(payload, ensure_ascii=False)
    assert payload["status"] == "failed"
    assert payload["papers"] == []
    assert payload["privacy_normalization"]["redaction_counts"]["private_key_material"] == 1
    assert "SUPERSECRETMATERIAL" not in rendered
    assert "normal trailing evidence" not in rendered
    validate_persistable_content(payload)


def test_old_unsanitized_literature_checkpoint_replays_exactly_without_rewrite_or_refetch(
    tmp_path: Path,
) -> None:
    request = {"source": "openalex", "query": "normalization method", "limit": 5}
    request_hash = checkpoint_module.canonical_model_hash(request)
    old_payload = {
        "schema_version": "contest-direction-literature-search-checkpoint-v1",
        "request": request,
        "request_hash": request_hash,
        "status": "completed",
        "papers": [
            {
                "title": "Legacy source record",
                "authors": ["A. Researcher"],
                "abstract": "CONTACT: first.last@example.ac.uk",
                "publication_date": None,
                "venue": None,
                "doi": None,
                "repository_doi": None,
                "url": None,
                "citation_count": None,
                "citation_count_source": None,
                "citation_count_as_of": None,
                "publication_status": "unknown",
                "status_source": None,
                "status_as_of": None,
                "source": "openalex",
            }
        ],
        "papers_hash": "0" * 64,
        "error_type": None,
        "error_message": None,
    }
    old_payload["papers_hash"] = checkpoint_module.canonical_model_hash(
        {"papers": old_payload["papers"]}
    )
    old_payload["checkpoint_hash"] = checkpoint_module.canonical_model_hash(old_payload)
    path = tmp_path / "checkpoints" / "literature-searches" / "openalex" / f"{request_hash}.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(old_payload, ensure_ascii=False), encoding="utf-8")
    original_bytes = path.read_bytes()
    calls = 0

    def source(_query: str, *, limit: int) -> list[Any]:
        nonlocal calls
        assert limit == 5
        calls += 1
        return []

    replay = replayable_literature_searchers(
        root=tmp_path,
        searchers={"openalex": source},
    )["openalex"]("normalization method", limit=5)

    assert calls == 0
    assert replay[0].abstract == "CONTACT: first.last@example.ac.uk"
    assert path.read_bytes() == original_bytes
    assert literature_search_checkpoint_accounting(tmp_path)["completed_count"] == 1


def test_v2_literature_checkpoint_revalidates_inner_privacy_receipt_hash(
    tmp_path: Path,
) -> None:
    from autoresearch.literature.models import AcademicPaper

    paper = AcademicPaper(
        title="Safe source record",
        abstract="Safe abstract.",
        source="openalex",
    )
    search = replayable_literature_searchers(
        root=tmp_path,
        searchers={"openalex": lambda _query, *, limit: [paper][:limit]},
    )["openalex"]
    search("safe query", limit=5)
    path = next((tmp_path / "checkpoints" / "literature-searches").rglob("*.json"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["privacy_normalization"]["total_redactions"] = 1
    payload["checkpoint_hash"] = checkpoint_module.canonical_model_hash(
        {key: value for key, value in payload.items() if key != "checkpoint_hash"}
    )
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ContestDirectionStageCheckpointError, match="privacy-normalization"):
        search("safe query", limit=5)


def test_v2_checkpoint_with_frozen_v1_privacy_receipt_replays_exact_bytes(
    tmp_path: Path,
) -> None:
    request = {"source": "openalex", "query": "safe legacy-v2 query", "limit": 5}
    request_hash = checkpoint_module.canonical_model_hash(request)
    papers = [
        {
            "title": "Safe legacy-v2 source record",
            "authors": [],
            "abstract": "Safe abstract.",
            "publication_date": None,
            "venue": None,
            "doi": None,
            "repository_doi": None,
            "url": None,
            "citation_count": None,
            "citation_count_source": None,
            "citation_count_as_of": None,
            "publication_status": "unknown",
            "status_source": None,
            "status_as_of": None,
            "source": "openalex",
        }
    ]
    privacy = {
        "schema_version": "scholarly-metadata-privacy-receipt-v1",
        "policy_version": "scholarly-metadata-privacy-v1",
        "redaction_counts": {
            "api_key_pattern": 0,
            "bearer_credential": 0,
            "direct_email_identifier": 0,
            "private_key_material": 0,
        },
        "field_redaction_counts": {},
        "total_redactions": 0,
    }
    privacy["receipt_hash"] = canonical_sha256(privacy)
    payload = {
        "schema_version": "contest-direction-literature-search-checkpoint-v2",
        "request": request,
        "request_hash": request_hash,
        "status": "completed",
        "papers": papers,
        "papers_hash": checkpoint_module.canonical_model_hash({"papers": papers}),
        "privacy_normalization": privacy,
        "error_type": None,
        "error_message": None,
    }
    payload["checkpoint_hash"] = checkpoint_module.canonical_model_hash(payload)
    path = tmp_path / "checkpoints" / "literature-searches" / "openalex" / f"{request_hash}.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    original_bytes = path.read_bytes()
    calls = 0

    def source(_query: str, *, limit: int) -> list[Any]:
        nonlocal calls
        assert limit == 5
        calls += 1
        return []

    replay = replayable_literature_searchers(
        root=tmp_path,
        searchers={"openalex": source},
    )["openalex"]("safe legacy-v2 query", limit=5)

    assert calls == 0
    assert replay[0].title == "Safe legacy-v2 source record"
    assert path.read_bytes() == original_bytes


def test_literature_source_accounting_revalidates_completed_and_failed_denominator(
    tmp_path: Path,
) -> None:
    from autoresearch.literature.models import AcademicPaper

    paper = AcademicPaper(
        title="Synthetic array evidence",
        authors=("A",),
        abstract="A source-backed synthetic abstract.",
        url="https://example.org/synthetic-array",
        source="openalex",
    )
    searchers = replayable_literature_searchers(
        root=tmp_path,
        searchers={
            "openalex": lambda _query, *, limit: [paper][:limit],
            "arxiv": lambda _query, *, limit: (_ for _ in ()).throw(
                RuntimeError(f"source unavailable at limit {limit}")
            ),
        },
    )
    searchers["openalex"]("synthetic array", limit=5)
    with pytest.raises(RuntimeError, match="source unavailable"):
        searchers["arxiv"]("synthetic counterevidence", limit=5)

    accounting = literature_search_checkpoint_accounting(tmp_path)

    assert accounting == {
        "request_count": 2,
        "completed_count": 1,
        "failed_count": 1,
        "by_source": {
            "arxiv": {"request_count": 1, "completed_count": 0, "failed_count": 1},
            "openalex": {"request_count": 1, "completed_count": 1, "failed_count": 0},
        },
    }

    checkpoint = next(
        (tmp_path / "checkpoints" / "literature-searches" / "openalex").glob("*.json")
    )
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    payload["papers"][0]["title"] = "tampered"
    checkpoint.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ContestDirectionStageCheckpointError, match="checkpoint"):
        literature_search_checkpoint_accounting(tmp_path)


def test_research_loop_literature_accounting_aggregates_all_production_stage_roots(
    tmp_path: Path,
) -> None:
    from autoresearch.literature.models import AcademicPaper

    paper = AcademicPaper(
        title="Synthetic mechanism evidence",
        authors=("A",),
        abstract="A source-backed synthetic abstract.",
        url="https://example.org/synthetic-mechanism",
        source="openalex",
    )
    stage_roots = {
        "broad": tmp_path / "literature" / "broad",
        "refinement": tmp_path / "literature" / "refinement",
        "gap-repair": tmp_path / "literature" / "gap-repair",
    }
    broad = replayable_literature_searchers(
        root=stage_roots["broad"],
        searchers={"openalex": lambda _query, *, limit: [paper][:limit]},
    )
    refinement = replayable_literature_searchers(
        root=stage_roots["refinement"],
        searchers={
            "arxiv": lambda _query, *, limit: (_ for _ in ()).throw(
                RuntimeError(f"synthetic refinement failure {limit}")
            )
        },
    )
    repair = replayable_literature_searchers(
        root=stage_roots["gap-repair"],
        searchers={"openalex": lambda _query, *, limit: [paper][:limit]},
    )

    broad["openalex"]("synthetic broad mechanism", limit=5)
    with pytest.raises(RuntimeError, match="synthetic refinement failure"):
        refinement["arxiv"]("synthetic counterevidence", limit=5)
    repair["openalex"]("synthetic authority repair", limit=5)

    assert research_loop_literature_search_checkpoint_accounting(tmp_path) == {
        "request_count": 3,
        "completed_count": 2,
        "failed_count": 1,
        "by_source": {
            "arxiv": {"request_count": 1, "completed_count": 0, "failed_count": 1},
            "openalex": {"request_count": 2, "completed_count": 2, "failed_count": 0},
        },
    }


def test_research_loop_literature_accounting_rejects_unregistered_checkpoint_root(
    tmp_path: Path,
) -> None:
    def empty_source(_query: str, *, limit: int) -> list[Any]:
        assert limit == 5
        return []

    replayable_literature_searchers(
        root=tmp_path / "literature" / "unregistered-stage",
        searchers={"openalex": empty_source},
    )["openalex"]("synthetic unregistered request", limit=5)

    with pytest.raises(
        ContestDirectionStageCheckpointError,
        match="unregistered literature search checkpoint root",
    ):
        research_loop_literature_search_checkpoint_accounting(tmp_path)


def test_research_loop_literature_accounting_rejects_duplicate_registered_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage_root = tmp_path / "literature" / "broad"
    stage_root.mkdir(parents=True)
    monkeypatch.setattr(
        checkpoint_module,
        "_RESEARCH_LOOP_LITERATURE_STAGE_ROOTS",
        (Path("literature/broad"), Path("literature/broad")),
    )

    with pytest.raises(
        ContestDirectionStageCheckpointError,
        match="stage roots resolve to a duplicate path",
    ):
        research_loop_literature_search_checkpoint_accounting(tmp_path)


def test_research_loop_literature_accounting_rejects_registered_path_escape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        checkpoint_module,
        "_RESEARCH_LOOP_LITERATURE_STAGE_ROOTS",
        (tmp_path.parent,),
    )

    with pytest.raises(
        ContestDirectionStageCheckpointError,
        match="stage root escapes the research loop",
    ):
        research_loop_literature_search_checkpoint_accounting(tmp_path)


def test_finalist_status_verification_is_replayed_without_second_api_call(
    tmp_path: Path,
) -> None:
    from autoresearch.literature.models import AcademicPaper

    paper = AcademicPaper(
        title="A preprint",
        authors=("A",),
        abstract="Prime gap analysis.",
        url="https://arxiv.org/abs/1234.5678",
        source="arxiv",
        publication_status="preprint",
    )
    calls = 0

    def verify(value: AcademicPaper) -> AcademicPaper:
        nonlocal calls
        calls += 1
        return value.model_copy(update={"publication_status": "withdrawn"})

    first = replayable_paper_verifier(
        root=tmp_path,
        verifier_name="arxiv-finalist-status",
        verifier=verify,
    )(paper)
    replay = replayable_paper_verifier(
        root=tmp_path,
        verifier_name="arxiv-finalist-status",
        verifier=lambda _paper: pytest.fail("status endpoint must not be called twice"),
    )(paper)

    assert first == replay
    assert replay.publication_status == "withdrawn"
    assert calls == 1


def test_source_checkpoint_accounting_separates_physical_search_and_status_attempts(
    tmp_path: Path,
) -> None:
    from urllib.error import URLError

    from autoresearch.literature.clients import (
        ArxivClient,
        OpenAlexClient,
        RateLimiter,
        RetryConfig,
    )
    from autoresearch.literature.models import AcademicPaper

    openalex_calls = 0

    def openalex_get(
        _url: str,
        _params: dict[str, str | int],
        _headers: Any,
    ) -> str:
        nonlocal openalex_calls
        openalex_calls += 1
        if openalex_calls == 1:
            raise URLError("synthetic retry")
        return '{"results": []}'

    openalex = OpenAlexClient(
        http_get=openalex_get,
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=2, backoff_seconds=0),
        sleep=lambda _seconds: None,
    )
    searchers = replayable_literature_searchers(
        root=tmp_path / "literature" / "broad",
        searchers={"openalex": openalex.search},
    )
    assert searchers["openalex"]("topic-neutral causal structure", limit=2) == []

    arxiv = ArxivClient(
        http_get=lambda _url, _params, _headers: "<main>active preprint</main>",
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=1, backoff_seconds=0),
    )
    paper = AcademicPaper(
        title="Topic-neutral preprint",
        url="https://arxiv.org/abs/2601.00001",
        publication_status="preprint",
        source="arxiv",
    )
    replayable_paper_verifier(
        root=tmp_path,
        verifier_name="arxiv-focus-status",
        verifier=arxiv.verify_status,
    )(paper)

    accounting = research_loop_source_checkpoint_accounting(tmp_path)

    assert accounting["literature_searches"] == {
        "request_count": 1,
        "completed_count": 1,
        "failed_count": 0,
        "by_source": {"openalex": {"request_count": 1, "completed_count": 1, "failed_count": 0}},
    }
    assert accounting["paper_status_verifications"] == {
        "requested_count": 1,
        "completed_count": 1,
        "failed_count": 0,
        "by_verifier": {
            "arxiv-focus-status": {
                "requested_count": 1,
                "completed_count": 1,
                "failed_count": 0,
            }
        },
    }
    physical = accounting["physical_http_attempts"]
    assert physical["accounting_status"] == "verified_current_protocol"
    assert physical["literature_searches"] == {
        "requested_count": 2,
        "completed_count": 1,
        "failed_count": 1,
        "outcome_unknown_count": 0,
        "by_source": {
            "openalex": {
                "requested_count": 2,
                "completed_count": 1,
                "failed_count": 1,
                "outcome_unknown_count": 0,
            }
        },
    }
    assert physical["paper_status_verifications"] == {
        "requested_count": 1,
        "completed_count": 1,
        "failed_count": 0,
        "outcome_unknown_count": 0,
        "by_verifier": {
            "arxiv-focus-status": {
                "requested_count": 1,
                "completed_count": 1,
                "failed_count": 0,
                "outcome_unknown_count": 0,
            }
        },
    }


def test_failed_paper_status_call_is_replayed_and_counted_without_second_dispatch(
    tmp_path: Path,
) -> None:
    from urllib.error import URLError

    from autoresearch.literature.clients import ArxivClient, RateLimiter, RetryConfig
    from autoresearch.literature.models import AcademicPaper

    calls = 0

    def fail(_url: str, _params: dict[str, str | int], _headers: Any) -> str:
        nonlocal calls
        calls += 1
        raise URLError("synthetic source failure")

    client = ArxivClient(
        http_get=fail,
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=2, backoff_seconds=0),
        sleep=lambda _seconds: None,
    )
    paper = AcademicPaper(
        title="Topic-neutral failed status check",
        url="https://arxiv.org/abs/2601.00002",
        publication_status="preprint",
        source="arxiv",
    )
    verify = replayable_paper_verifier(
        root=tmp_path,
        verifier_name="arxiv-finalist-status",
        verifier=client.verify_status,
    )

    with pytest.raises(URLError):
        verify(paper)
    with pytest.raises(ContestDirectionStageCheckpointError, match="replayed paper verification"):
        verify(paper)

    assert calls == 2
    assert paper_verification_checkpoint_accounting(tmp_path) == {
        "requested_count": 1,
        "completed_count": 0,
        "failed_count": 1,
        "by_verifier": {
            "arxiv-finalist-status": {
                "requested_count": 1,
                "completed_count": 0,
                "failed_count": 1,
            }
        },
    }
    physical = research_loop_source_checkpoint_accounting(tmp_path)["physical_http_attempts"]
    assert physical["accounting_status"] == "verified_current_protocol"
    assert physical["paper_status_verifications"]["requested_count"] == 2
    assert physical["paper_status_verifications"]["completed_count"] == 0
    assert physical["paper_status_verifications"]["failed_count"] == 2


def test_legacy_logical_source_checkpoints_do_not_backfill_physical_attempts(
    tmp_path: Path,
) -> None:
    from autoresearch.literature.models import AcademicPaper

    paper = AcademicPaper(
        title="Legacy logical record",
        url="https://example.org/legacy",
        source="openalex",
    )
    replayable_literature_searchers(
        root=tmp_path / "literature" / "broad",
        searchers={"openalex": lambda _query, *, limit: [paper][:limit]},
    )["openalex"]("legacy logical query", limit=1)
    replayable_paper_verifier(
        root=tmp_path,
        verifier_name="legacy-status",
        verifier=lambda value: value,
    )(
        paper.model_copy(
            update={
                "source": "arxiv",
                "url": "https://arxiv.org/abs/2601.00003",
                "publication_status": "preprint",
            }
        )
    )

    physical = research_loop_source_checkpoint_accounting(tmp_path)["physical_http_attempts"]

    assert physical["accounting_status"] == "legacy_unavailable"
    assert physical["literature_searches"]["requested_count"] is None
    assert physical["paper_status_verifications"]["requested_count"] is None


def test_source_reservation_without_outcome_is_unknown_and_never_redispatched(
    tmp_path: Path,
) -> None:
    from autoresearch.literature.clients import OpenAlexClient, RateLimiter, RetryConfig

    calls = 0

    def crash(_url: str, _params: dict[str, str | int], _headers: Any) -> str:
        nonlocal calls
        calls += 1
        raise KeyboardInterrupt

    client = OpenAlexClient(
        http_get=crash,
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=1, backoff_seconds=0),
    )
    search = replayable_literature_searchers(
        root=tmp_path / "literature" / "broad",
        searchers={"openalex": client.search},
    )["openalex"]

    with pytest.raises(KeyboardInterrupt):
        search("topic-neutral crash boundary", limit=1)
    with pytest.raises(ContestDirectionStageCheckpointError, match="refusing redispatch"):
        search("topic-neutral crash boundary", limit=1)

    assert calls == 1
    physical = research_loop_source_checkpoint_accounting(tmp_path)["physical_http_attempts"]
    assert physical["accounting_status"] == "verified_current_protocol"
    assert physical["literature_searches"]["requested_count"] == 1
    assert physical["literature_searches"]["outcome_unknown_count"] == 1


def test_completed_http_with_malformed_payload_is_physical_success_logical_failure(
    tmp_path: Path,
) -> None:
    from autoresearch.literature.clients import OpenAlexClient, RateLimiter, RetryConfig

    client = OpenAlexClient(
        http_get=lambda _url, _params, _headers: "not-json",
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=1, backoff_seconds=0),
    )
    search = replayable_literature_searchers(
        root=tmp_path / "literature" / "broad",
        searchers={"openalex": client.search},
    )["openalex"]

    with pytest.raises(json.JSONDecodeError):
        search("topic-neutral malformed response", limit=1)

    accounting = research_loop_source_checkpoint_accounting(tmp_path)
    assert accounting["literature_searches"]["failed_count"] == 1
    physical = accounting["physical_http_attempts"]["literature_searches"]
    assert physical["requested_count"] == 1
    assert physical["completed_count"] == 1
    assert physical["failed_count"] == 0


def test_untrusted_exception_type_never_reaches_source_checkpoint_bytes(
    tmp_path: Path,
) -> None:
    from autoresearch.literature.clients import OpenAlexClient, RateLimiter, RetryConfig

    secret = "leak@example.org"
    unsafe_error = type(secret, (RuntimeError,), {})
    client = OpenAlexClient(
        http_get=lambda _url, _params, _headers: (_ for _ in ()).throw(
            unsafe_error("Bearer private-token")
        ),
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=1, backoff_seconds=0),
    )
    search = replayable_literature_searchers(
        root=tmp_path / "literature" / "broad",
        searchers={"openalex": client.search},
    )["openalex"]

    with pytest.raises(unsafe_error):
        search("topic-neutral private failure", limit=1)

    checkpoint_bytes = b"\n".join(path.read_bytes() for path in sorted(tmp_path.rglob("*.json")))
    assert secret.encode() not in checkpoint_bytes
    assert b"private-token" not in checkpoint_bytes


def test_custom_object_cannot_forge_physical_tracing_capability(tmp_path: Path) -> None:
    from autoresearch.literature.models import AcademicPaper

    class ForgedSearcher:
        source_http_attempt_tracing_supported = True

        def search(self, _query: str, *, limit: int) -> list[AcademicPaper]:
            return [AcademicPaper(title="Custom result", source="openalex")][:limit]

    search = replayable_literature_searchers(
        root=tmp_path / "literature" / "broad",
        searchers={"openalex": ForgedSearcher().search},
    )["openalex"]
    assert len(search("topic-neutral forged marker", limit=1)) == 1

    physical = research_loop_source_checkpoint_accounting(tmp_path)["physical_http_attempts"]
    assert physical["accounting_status"] == "legacy_unavailable"
    assert physical["literature_searches"]["requested_count"] is None


def test_concurrent_same_logical_source_call_has_one_dispatch_owner(tmp_path: Path) -> None:
    from autoresearch.literature.clients import OpenAlexClient, RateLimiter, RetryConfig

    rendezvous = Barrier(2)
    release = Barrier(2)
    calls = 0
    errors: list[BaseException] = []

    def get(_url: str, _params: dict[str, str | int], _headers: Any) -> str:
        nonlocal calls
        calls += 1
        rendezvous.wait(timeout=5)
        release.wait(timeout=5)
        return '{"results": []}'

    client = OpenAlexClient(
        http_get=get,
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=1, backoff_seconds=0),
    )
    search = replayable_literature_searchers(
        root=tmp_path / "literature" / "broad",
        searchers={"openalex": client.search},
    )["openalex"]

    def first() -> None:
        try:
            search("topic-neutral concurrent request", limit=1)
        except BaseException as exc:  # captured for deterministic join assertion
            errors.append(exc)

    thread = Thread(target=first)
    thread.start()
    rendezvous.wait(timeout=5)
    with pytest.raises(ContestDirectionStageCheckpointError):
        search("topic-neutral concurrent request", limit=1)
    release.wait(timeout=5)
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert errors == []
    assert calls == 1
    physical = research_loop_source_checkpoint_accounting(tmp_path)["physical_http_attempts"]
    assert physical["literature_searches"]["requested_count"] == 1


def test_search_physical_source_cannot_be_rehashed_away_from_logical_actor(
    tmp_path: Path,
) -> None:
    from autoresearch.literature.clients import OpenAlexClient, RateLimiter, RetryConfig

    client = OpenAlexClient(
        http_get=lambda _url, _params, _headers: '{"results": []}',
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=1, backoff_seconds=0),
    )
    search = replayable_literature_searchers(
        root=tmp_path / "literature" / "broad",
        searchers={"openalex": client.search},
    )["openalex"]
    assert search("topic-neutral source identity", limit=1) == []
    operation_root = next(
        (tmp_path / "literature" / "broad" / "checkpoints" / "source-http-attempts")
        .joinpath("literature_searches", "openalex")
        .iterdir()
    )
    registration_path = operation_root / "registration.json"
    owner_path = operation_root / "dispatch-owner.json"
    reservation_path = operation_root / "attempt-001-reservation.json"
    outcome_path = operation_root / "attempt-001-outcome.json"
    registration = json.loads(registration_path.read_text(encoding="utf-8"))
    owner = json.loads(owner_path.read_text(encoding="utf-8"))
    reservation = json.loads(reservation_path.read_text(encoding="utf-8"))
    outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
    registration["source"] = "arxiv"
    owner["source"] = "arxiv"
    reservation["source"] = "arxiv"
    reservation["transport_request"]["source"] = "arxiv"
    reservation["transport_request_hash"] = checkpoint_module.canonical_model_hash(
        reservation["transport_request"]
    )
    outcome["source"] = "arxiv"
    outcome["transport_request_hash"] = reservation["transport_request_hash"]
    for payload in (registration, owner, reservation):
        payload["checkpoint_hash"] = checkpoint_module.canonical_model_hash(
            {key: value for key, value in payload.items() if key != "checkpoint_hash"}
        )
    outcome["reservation_hash"] = reservation["checkpoint_hash"]
    outcome["checkpoint_hash"] = checkpoint_module.canonical_model_hash(
        {key: value for key, value in outcome.items() if key != "checkpoint_hash"}
    )
    for path, payload in (
        (registration_path, registration),
        (owner_path, owner),
        (reservation_path, reservation),
        (outcome_path, outcome),
    ):
        path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ContestDirectionStageCheckpointError, match="actor/source"):
        research_loop_source_checkpoint_accounting(tmp_path)


def test_same_source_physical_chain_cannot_be_relabelled_to_another_logical_query(
    tmp_path: Path,
) -> None:
    from autoresearch.literature.clients import OpenAlexClient, RateLimiter, RetryConfig

    stage_root = tmp_path / "literature" / "broad"
    replayable_literature_searchers(
        root=stage_root,
        searchers={"openalex": lambda _query, *, limit: []},  # noqa: ARG005
    )["openalex"]("old topic-neutral query", limit=1)
    client = OpenAlexClient(
        http_get=lambda _url, _params, _headers: '{"results": []}',
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=1, backoff_seconds=0),
    )
    replayable_literature_searchers(
        root=stage_root,
        searchers={"openalex": client.search},
    )["openalex"]("new topic-neutral query", limit=1)
    logical_paths = tuple(
        (stage_root / "checkpoints" / "literature-searches" / "openalex").glob("*.json")
    )
    logical_by_query = {
        json.loads(path.read_text(encoding="utf-8"))["request"]["query"]: path
        for path in logical_paths
    }
    old_path = logical_by_query["old topic-neutral query"]
    new_path = logical_by_query["new topic-neutral query"]
    old_hash = old_path.stem
    new_hash = new_path.stem
    new_path.unlink()
    source_root = (
        stage_root / "checkpoints" / "source-http-attempts" / "literature_searches" / "openalex"
    )
    operation_root = source_root / new_hash
    rebound_root = source_root / old_hash
    operation_root.rename(rebound_root)
    registration_path = rebound_root / "registration.json"
    owner_path = rebound_root / "dispatch-owner.json"
    reservation_path = rebound_root / "attempt-001-reservation.json"
    outcome_path = rebound_root / "attempt-001-outcome.json"
    registration = json.loads(registration_path.read_text(encoding="utf-8"))
    owner = json.loads(owner_path.read_text(encoding="utf-8"))
    reservation = json.loads(reservation_path.read_text(encoding="utf-8"))
    outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
    registration["logical_request"] = json.loads(old_path.read_text(encoding="utf-8"))["request"]
    for payload in (registration, owner, reservation, outcome):
        payload["logical_request_hash"] = old_hash
    for payload in (registration, owner, reservation):
        payload["checkpoint_hash"] = checkpoint_module.canonical_model_hash(
            {key: value for key, value in payload.items() if key != "checkpoint_hash"}
        )
    outcome["reservation_hash"] = reservation["checkpoint_hash"]
    outcome["checkpoint_hash"] = checkpoint_module.canonical_model_hash(
        {key: value for key, value in outcome.items() if key != "checkpoint_hash"}
    )
    for path, payload in (
        (registration_path, registration),
        (owner_path, owner),
        (reservation_path, reservation),
        (outcome_path, outcome),
    ):
        path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        ContestDirectionStageCheckpointError,
        match="logical request and physical transport differ",
    ):
        research_loop_source_checkpoint_accounting(tmp_path)


def test_unregistered_literature_stage_physical_attempt_is_rejected(tmp_path: Path) -> None:
    from autoresearch.literature.clients import OpenAlexClient, RateLimiter, RetryConfig

    calls = 0

    def crash(_url: str, _params: dict[str, str | int], _headers: Any) -> str:
        nonlocal calls
        calls += 1
        raise KeyboardInterrupt

    client = OpenAlexClient(
        http_get=crash,
        rate_limiter=RateLimiter(0),
        retry=RetryConfig(max_attempts=1, backoff_seconds=0),
    )
    search = replayable_literature_searchers(
        root=tmp_path / "literature" / "unregistered",
        searchers={"openalex": client.search},
    )["openalex"]
    with pytest.raises(KeyboardInterrupt):
        search("topic-neutral unregistered crash", limit=1)

    assert calls == 1
    with pytest.raises(ContestDirectionStageCheckpointError, match="unregistered source HTTP"):
        research_loop_source_checkpoint_accounting(tmp_path)


def test_v2_paper_verification_revalidates_inner_privacy_receipt_hash(
    tmp_path: Path,
) -> None:
    from autoresearch.literature.models import AcademicPaper

    paper = AcademicPaper(
        title="Safe preprint",
        source="arxiv",
        publication_status="preprint",
    )
    verify = replayable_paper_verifier(
        root=tmp_path,
        verifier_name="status-check",
        verifier=lambda value: value,
    )
    verify(paper)
    path = next((tmp_path / "checkpoints" / "paper-verifications").rglob("*.json"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["request_privacy_normalization"]["total_redactions"] = 1
    payload["checkpoint_hash"] = checkpoint_module.canonical_model_hash(
        {key: value for key, value in payload.items() if key != "checkpoint_hash"}
    )
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ContestDirectionStageCheckpointError, match="privacy-normalization"):
        verify(paper)


def test_legacy_paper_verification_replays_exact_bytes_without_privacy_rewrite(
    tmp_path: Path,
) -> None:
    from autoresearch.literature.models import AcademicPaper

    paper = AcademicPaper(
        title="Legacy preprint",
        authors=("A",),
        abstract="CONTACT: first.last@example.ac.uk",
        url="https://arxiv.org/abs/1234.5678",
        source="arxiv",
        publication_status="preprint",
    )
    request = paper.model_dump(mode="json")
    request_hash = checkpoint_module.canonical_model_hash(request)
    verified = paper.model_copy(update={"publication_status": "withdrawn"})
    verified_payload = verified.model_dump(mode="json")
    payload = {
        "schema_version": "contest-direction-paper-verification-checkpoint-v1",
        "verifier_name": "arxiv-finalist-status",
        "request": request,
        "request_hash": request_hash,
        "verified_paper": verified_payload,
        "verified_paper_hash": checkpoint_module.canonical_model_hash(verified_payload),
    }
    payload["checkpoint_hash"] = checkpoint_module.canonical_model_hash(payload)
    path = (
        tmp_path
        / "checkpoints"
        / "paper-verifications"
        / "arxiv-finalist-status"
        / f"{request_hash}.json"
    )
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    original_bytes = path.read_bytes()
    calls = 0

    def verifier(_paper: AcademicPaper) -> AcademicPaper:
        nonlocal calls
        calls += 1
        return _paper

    replay = replayable_paper_verifier(
        root=tmp_path,
        verifier_name="arxiv-finalist-status",
        verifier=verifier,
    )(paper)

    assert calls == 0
    assert replay == verified
    assert path.read_bytes() == original_bytes


def test_partial_stage_output_is_quarantined_without_deletion(tmp_path: Path) -> None:
    stage = tmp_path / "hypothesis-stage"
    stage.mkdir()
    interrupted = stage / "paid-response-sidecar.json"
    interrupted.write_bytes(b'{"status":"interrupted"}\n')

    quarantined = _quarantine_partial_output(tmp_path, stage, "d" * 64)

    assert quarantined is not None
    assert not stage.exists()
    assert (quarantined / interrupted.name).read_bytes() == (b'{"status":"interrupted"}\n')
