"""OpenAI-compatible LLM smoke test client with output quality checks."""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, model_validator

from autoresearch.config import ConfigParser, SystemConfig
from autoresearch.schemas import file_hash

REVIEW_SUBJECT_MAX_CHARS = 36_000
REVIEW_EVIDENCE_MAX_CHARS = 3_000
PROFILE_CONTEXT_TERMS = (
    "agent_profiles",
    "stage_runtime_contexts",
    "stage_agent_contexts",
    "agent profile",
    "profile context",
    "mcp_runtime_contract",
    "mcp runtime contract",
    "runtime contract",
    "skill",
    "skills",
    "mcp",
    "allowlist",
    "allowlists",
)
PROFILE_PROOF_TERMS = (
    "prove",
    "proves",
    "proof",
    "support",
    "supports",
    "supported",
    "validate",
    "validates",
    "validated",
    "verify",
    "verifies",
    "verified",
    "confirm",
    "confirms",
    "confirmed",
    "demonstrate",
    "demonstrates",
    "establish",
    "establishes",
    "evidence for",
)
PROFILE_SCIENTIFIC_CLAIM_TERMS = (
    "scientific result",
    "scientific results",
    "result",
    "results",
    "novelty",
    "benchmark",
    "metric",
    "metrics",
    "accuracy",
    "f1",
    "citation",
    "citations",
    "publication readiness",
    "publishable",
    "tool invocation",
    "tool was invoked",
    "tool use",
)
PROFILE_CONTEXT_NEGATION_TERMS = (
    "not evidence",
    "not proof",
    "cannot prove",
    "does not prove",
    "doesn't prove",
    "process metadata",
    "responsibility boundary",
    "responsibility boundaries",
    "available tool context",
)

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_REQUEST_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$"
_SAFE_RESPONSE_HEADERS = frozenset(
    {
        "content-length",
        "content-type",
        "date",
        "request-id",
        "x-dashscope-request-id",
        "x-request-id",
    }
)
_ORIGINAL_STDLIB_URLOPEN = urllib.request.urlopen
TransportImplementation = Literal[
    "stdlib_urlopen",
    "injected_test_opener",
    "replaced_global_urlopen",
]


class LLMTransportPreflight(BaseModel):
    """Secret-free, process-local commitment emitted before an HTTP request.

    The callback that receives this record may transiently receive the canonical
    request bytes as a separate argument so that a caller can durably reserve and
    hash the call.  Those bytes are deliberately not fields on this model.
    This object never attests that a remote provider or external boundary exists.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["llm-http-transport-preflight-v2"] = "llm-http-transport-preflight-v2"
    request_id: str = Field(pattern=_REQUEST_ID_PATTERN)
    adapter_id: Literal[
        "autoresearch.openai-compatible-http.v1",
        "autoresearch.ollama-native-local-http.v1",
    ]
    transport_scope: Literal["external_service", "local_service"]
    transport_implementation: TransportImplementation
    endpoint: str = Field(min_length=1, max_length=2_048)
    request_method: Literal["POST"] = "POST"
    request_payload_sha256: str = Field(pattern=_SHA256_PATTERN)
    request_payload_size_bytes: int = Field(ge=0)
    external_process_or_service_boundary_crossed: Literal[False] = False
    formal_external_anchor_eligible: Literal[False] = False
    process_local_integrity_only: Literal[True] = True
    independent_signed_gateway_attestation_present: Literal[False] = False
    preflight_sha256: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def _validate_preflight(self) -> LLMTransportPreflight:
        if self.endpoint != _credential_free_endpoint(self.endpoint):
            raise ValueError("transport preflight endpoint is not credential-free")
        expected_scope = _transport_scope(self.adapter_id, self.endpoint)
        if self.transport_scope != expected_scope:
            raise ValueError("transport preflight scope does not match its adapter/endpoint")
        if self.preflight_sha256 != _addressed_model_sha256(self, "preflight_sha256"):
            raise ValueError("transport preflight hash mismatch")
        return self


class LLMHTTPTransportTrace(BaseModel):
    """Process-local integrity record from one completed HTTP response read.

    It stores only hashes and allowlisted header names, never request/response
    bodies, credentials, Authorization, cookies, or complete header values.
    In-process code cannot prove an external provider boundary: formal eligibility
    remains false until a separately trusted gateway supplies a verifiable signature.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["llm-http-transport-trace-v2"] = "llm-http-transport-trace-v2"
    request_id: str = Field(pattern=_REQUEST_ID_PATTERN)
    adapter_id: Literal[
        "autoresearch.openai-compatible-http.v1",
        "autoresearch.ollama-native-local-http.v1",
    ]
    transport_scope: Literal["external_service", "local_service"]
    transport_implementation: TransportImplementation
    endpoint: str = Field(min_length=1, max_length=2_048)
    request_method: Literal["POST"] = "POST"
    request_payload_sha256: str = Field(pattern=_SHA256_PATTERN)
    request_payload_size_bytes: int = Field(ge=0)
    http_status_code: int = Field(ge=100, le=599)
    selected_response_header_names: tuple[str, ...]
    selected_response_headers_sha256: str = Field(pattern=_SHA256_PATTERN)
    raw_response_body_sha256: str = Field(pattern=_SHA256_PATTERN)
    raw_response_body_size_bytes: int = Field(ge=0)
    provider_response_id_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    completion_fields_available: bool
    visible_output_utf8_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    reasoning_output_utf8_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    usage_canonical_json_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    external_process_or_service_boundary_crossed: Literal[False] = False
    formal_external_anchor_eligible: Literal[False] = False
    process_local_integrity_only: Literal[True] = True
    independent_signed_gateway_attestation_present: Literal[False] = False
    transport_metadata_sha256: str = Field(pattern=_SHA256_PATTERN)
    http_metadata_sha256: str = Field(pattern=_SHA256_PATTERN)
    trace_sha256: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def _validate_trace(self) -> LLMHTTPTransportTrace:
        if self.endpoint != _credential_free_endpoint(self.endpoint):
            raise ValueError("transport trace endpoint is not credential-free")
        if self.transport_scope != _transport_scope(self.adapter_id, self.endpoint):
            raise ValueError("transport trace scope does not match its adapter/endpoint")
        if tuple(sorted(set(self.selected_response_header_names))) != (
            self.selected_response_header_names
        ):
            raise ValueError("selected response header names must be sorted and unique")
        if any(name not in _SAFE_RESPONSE_HEADERS for name in self.selected_response_header_names):
            raise ValueError("transport trace contains a non-allowlisted response header")
        output_hashes = (
            self.visible_output_utf8_sha256,
            self.reasoning_output_utf8_sha256,
            self.usage_canonical_json_sha256,
        )
        if self.completion_fields_available != all(value is not None for value in output_hashes):
            raise ValueError("provider payload/output hash completeness mismatch")
        if self.transport_metadata_sha256 != _sha256_bytes(self.transport_metadata_bytes()):
            raise ValueError("transport metadata hash mismatch")
        if self.http_metadata_sha256 != _sha256_bytes(self.http_metadata_bytes()):
            raise ValueError("HTTP metadata hash mismatch")
        if self.trace_sha256 != _addressed_model_sha256(self, "trace_sha256"):
            raise ValueError("transport trace hash mismatch")
        return self

    def transport_metadata_bytes(self) -> bytes:
        """Return the exact secret-free bytes hashed by transport metadata SHA."""

        return _canonical_json_bytes(_transport_metadata_payload(self))

    def http_metadata_bytes(self) -> bytes:
        """Return the exact secret-free bytes hashed by HTTP metadata SHA."""

        return _canonical_json_bytes(_http_metadata_payload(self))

    def verify_completion_payload(
        self,
        *,
        response_text: str,
        reasoning_text: str | None,
        usage: Mapping[str, Any],
    ) -> None:
        """Fail closed if a returned completion no longer matches this trace."""

        if self.visible_output_utf8_sha256 != _sha256_bytes(response_text.encode("utf-8")):
            raise ValueError("visible output no longer matches the transport trace")
        if self.reasoning_output_utf8_sha256 != _sha256_bytes(
            (reasoning_text or "").encode("utf-8")
        ):
            raise ValueError("reasoning output no longer matches the transport trace")
        if self.usage_canonical_json_sha256 != _sha256_bytes(_canonical_json_bytes(usage)):
            raise ValueError("usage no longer matches the transport trace")


class LLMTransportFailureTrace(BaseModel):
    """Secret-free process-local integrity record for a failed HTTP attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["llm-http-transport-failure-v2"] = "llm-http-transport-failure-v2"
    request_id: str = Field(pattern=_REQUEST_ID_PATTERN)
    adapter_id: Literal[
        "autoresearch.openai-compatible-http.v1",
        "autoresearch.ollama-native-local-http.v1",
    ]
    transport_scope: Literal["external_service", "local_service"]
    transport_implementation: TransportImplementation
    endpoint: str = Field(min_length=1, max_length=2_048)
    request_method: Literal["POST"] = "POST"
    request_payload_sha256: str = Field(pattern=_SHA256_PATTERN)
    request_payload_size_bytes: int = Field(ge=0)
    failure_stage: Literal["pre_transport_callback", "transport", "http_response"]
    error_type: str = Field(min_length=1, max_length=128)
    http_status_code: int | None = Field(default=None, ge=100, le=599)
    selected_response_header_names: tuple[str, ...] = ()
    selected_response_headers_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    raw_response_body_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    raw_response_body_size_bytes: int | None = Field(default=None, ge=0)
    provider_response_id_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    transport_attempted: bool
    http_response_received: bool
    external_process_or_service_boundary_crossed: Literal[False] = False
    formal_external_anchor_eligible: Literal[False] = False
    process_local_integrity_only: Literal[True] = True
    independent_signed_gateway_attestation_present: Literal[False] = False
    transport_metadata_sha256: str = Field(pattern=_SHA256_PATTERN)
    http_metadata_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    failure_trace_sha256: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def _validate_failure_trace(self) -> LLMTransportFailureTrace:
        if self.endpoint != _credential_free_endpoint(self.endpoint):
            raise ValueError("failure trace endpoint is not credential-free")
        if self.transport_scope != _transport_scope(self.adapter_id, self.endpoint):
            raise ValueError("failure trace scope does not match its adapter/endpoint")
        response_fields = (
            self.http_status_code,
            self.selected_response_headers_sha256,
            self.raw_response_body_sha256,
            self.raw_response_body_size_bytes,
        )
        if self.http_response_received != all(value is not None for value in response_fields):
            raise ValueError("failure trace response metadata completeness mismatch")
        if self.failure_stage == "http_response" and not self.http_response_received:
            raise ValueError("HTTP failure must bind its response")
        if self.failure_stage != "http_response" and self.http_response_received:
            raise ValueError("non-HTTP failure cannot claim a response")
        if self.failure_stage == "pre_transport_callback" and self.transport_attempted:
            raise ValueError("pre-transport callback failure cannot claim transport")
        if self.failure_stage == "transport" and not self.transport_attempted:
            raise ValueError("transport failure must record an attempted request")
        if tuple(sorted(set(self.selected_response_header_names))) != (
            self.selected_response_header_names
        ):
            raise ValueError("failure response header names must be sorted and unique")
        if any(name not in _SAFE_RESPONSE_HEADERS for name in self.selected_response_header_names):
            raise ValueError("failure trace contains a non-allowlisted response header")
        if self.transport_metadata_sha256 != _sha256_bytes(self.transport_metadata_bytes()):
            raise ValueError("failure transport metadata hash mismatch")
        if self.http_response_received:
            if self.http_metadata_sha256 != _sha256_bytes(self.http_metadata_bytes()):
                raise ValueError("failure HTTP metadata hash mismatch")
        elif self.http_metadata_sha256 is not None:
            raise ValueError("failure without HTTP response cannot carry HTTP metadata")
        if self.failure_trace_sha256 != _addressed_model_sha256(self, "failure_trace_sha256"):
            raise ValueError("transport failure trace hash mismatch")
        return self

    def transport_metadata_bytes(self) -> bytes:
        """Return the exact secret-free transport metadata bytes."""

        return _canonical_json_bytes(_transport_metadata_payload(self))

    def http_metadata_bytes(self) -> bytes:
        """Return response metadata bytes; fail if no HTTP response was received."""

        if not self.http_response_received:
            raise ValueError("transport failure has no HTTP response metadata")
        return _canonical_json_bytes(_failure_http_metadata_payload(self))


TransportPreflightHook = Callable[[LLMTransportPreflight, bytes], None]
HTTPResponseOpener = Callable[..., Any]
RequestIdFactory = Callable[[], str]


@dataclass(frozen=True)
class _HTTPJSONExchange:
    payload: dict[str, Any]
    preflight: LLMTransportPreflight
    raw_response_body: bytes
    http_status_code: int
    selected_response_header_names: tuple[str, ...]
    selected_response_headers_sha256: str


@dataclass(frozen=True)
class _TracedCompletionResponse:
    payload: dict[str, Any]
    trace: LLMHTTPTransportTrace


class LLMClientError(RuntimeError):
    """Raised when a live LLM smoke request cannot complete."""

    def __init__(
        self,
        message: str,
        *,
        response_text: str | None = None,
        response_usage: dict[str, Any] | None = None,
        finish_reason: str | None = None,
        transport_preflight: LLMTransportPreflight | None = None,
        transport_trace: LLMHTTPTransportTrace | None = None,
        transport_failure_trace: LLMTransportFailureTrace | None = None,
    ) -> None:
        super().__init__(message)
        self.response_text = response_text
        self.response_usage = response_usage or {}
        self.finish_reason = finish_reason
        self.transport_preflight = transport_preflight or (
            _preflight_from_trace(transport_trace) if transport_trace is not None else None
        )
        self.transport_trace = transport_trace
        self.transport_failure_trace = transport_failure_trace
        self.raw_response_body_sha256 = (
            transport_trace.raw_response_body_sha256
            if transport_trace is not None
            else (
                transport_failure_trace.raw_response_body_sha256
                if transport_failure_trace is not None
                else None
            )
        )

    def attach_transport_trace(
        self,
        trace: LLMHTTPTransportTrace,
    ) -> LLMClientError:
        """Attach an already completed HTTP trace without replacing error context."""

        self.transport_preflight = self.transport_preflight or _preflight_from_trace(trace)
        self.transport_trace = trace
        self.raw_response_body_sha256 = trace.raw_response_body_sha256
        return self


class LLMOutputQuality(BaseModel):
    """Local quality checks for the smoke-test model output."""

    score: float = Field(ge=0.0, le=1.0)
    checks: dict[str, bool]
    issues: list[str] = Field(default_factory=list)
    parsed_output: dict[str, Any] | None = None


class LLMSmokeResult(BaseModel):
    """Source-backed result from a live provider call."""

    provider: str
    base_url: str
    model_name: str
    endpoint: str
    response_text: str
    usage: dict[str, Any] = Field(default_factory=dict)
    quality: LLMOutputQuality
    attempts: int = Field(default=1, ge=1)


class LLMEvidenceArtifact(BaseModel):
    """Local evidence artifact supplied to an LLM reviewer."""

    evidence_id: str
    path: str
    sha256: str
    excerpt: str


class LLMReviewQuality(BaseModel):
    """Local checks for an LLM-as-reviewer response."""

    score: float = Field(ge=0.0, le=1.0)
    checks: dict[str, bool]
    issues: list[str] = Field(default_factory=list)
    parsed_output: dict[str, Any] | None = None


class LLMReviewResult(BaseModel):
    """Source-constrained LLM review result with local evidence provenance."""

    provider: str
    base_url: str
    model_name: str
    endpoint: str
    subject_path: str
    subject_sha256: str
    evidence: list[LLMEvidenceArtifact]
    response_text: str
    usage: dict[str, Any] = Field(default_factory=dict)
    quality: LLMReviewQuality
    attempts: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _bind_parsed_review_to_raw_response(self) -> LLMReviewResult:
        try:
            decoded = json.loads(_strip_json_fences(self.response_text))
        except json.JSONDecodeError:
            decoded = None
        expected = decoded if isinstance(decoded, dict) else None
        if self.quality.parsed_output != expected:
            raise ValueError("review parsed_output does not match the exact raw response_text")
        return self


class LLMJsonCompletionResult(BaseModel):
    """Raw JSON completion result from the configured provider."""

    provider: str
    base_url: str
    model_name: str
    endpoint: str
    response_text: str
    parsed_json: dict[str, Any]
    transport_normalization: Literal[
        "none",
        "discarded_trailing_closing_delimiters",
        "discarded_leading_self_revision",
    ] = "none"
    normalization_suffix: str | None = Field(
        default=None,
        min_length=1,
        max_length=200_000,
    )
    usage: dict[str, Any] = Field(default_factory=dict)
    temperature: float = Field(ge=0.0)
    # Task 267.3.1: explicit reasoning output.  This records HOW a candidate was
    # authored.  It is process evidence only and must never satisfy an evidence
    # gate, a metric claim, or a publication claim.
    reasoning_text: str | None = Field(default=None, max_length=200_000)
    reasoning_is_evidence: Literal[False] = False
    reasoning_transport: Literal[
        "absent",
        "dashscope_enable_thinking",
        "anthropic_thinking_block",
    ] = "absent"
    # A manually constructed/test-double result has no transport evidence by
    # default.  Only the real HTTP path in this module attaches this trace.
    transport_trace: LLMHTTPTransportTrace | None = None
    # Optional task-aware working-context provenance.  Ordinary one-shot calls
    # leave all four fields absent.  A context-managed caller records the base
    # active-task prompt separately from the actual delivered prompt and binds
    # both to a write-once preparation artifact.
    request_messages_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    source_messages_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    context_preparation_hash: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    context_preparation_path: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _validate_transport_normalization(self) -> LLMJsonCompletionResult:
        context_fields = (
            self.request_messages_sha256,
            self.source_messages_sha256,
            self.context_preparation_hash,
            self.context_preparation_path,
        )
        if any(item is not None for item in context_fields) and not all(
            item is not None for item in context_fields
        ):
            raise ValueError("task-aware context provenance fields must be all present")
        normalized = self.transport_normalization != "none"
        if normalized != (self.normalization_suffix is not None):
            raise ValueError("JSON transport normalization suffix presence mismatch")
        if self.normalization_suffix is not None:
            if self.transport_normalization == "discarded_trailing_closing_delimiters":
                delimiters = self.normalization_suffix.strip()
                if (
                    len(self.normalization_suffix) > 4
                    or not delimiters
                    or any(marker not in "]}" for marker in delimiters)
                ):
                    raise ValueError(
                        "JSON transport normalization suffix is not a closing delimiter"
                    )
            elif self.transport_normalization == "discarded_leading_self_revision":
                if not self.response_text.startswith(self.normalization_suffix):
                    raise ValueError("JSON self-revision prefix differs from raw response")
                selected = self.response_text[len(self.normalization_suffix) :].strip()
                try:
                    parsed = json.loads(selected)
                except json.JSONDecodeError as exc:
                    raise ValueError("selected JSON self-revision is invalid") from exc
                if parsed != self.parsed_json:
                    raise ValueError("selected JSON self-revision payload changed")
        if self.transport_trace is not None:
            self.transport_trace.verify_completion_payload(
                response_text=self.response_text,
                reasoning_text=self.reasoning_text,
                usage=self.usage,
            )
            if _credential_free_endpoint(self.endpoint) != self.transport_trace.endpoint:
                raise ValueError("completion endpoint differs from its transport trace")
        return self


def run_llm_smoke_test(
    *,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    timeout_seconds: int | None = None,
    max_tokens: int | None = None,
) -> LLMSmokeResult:
    """Call the configured OpenAI-compatible model and validate its output."""

    env_file = Path(env_path)
    if env_file.exists():
        load_dotenv(env_file, override=True)

    config_file = Path(config_path)
    config = (
        ConfigParser().parse_file(config_file, model_type=SystemConfig)
        if config_file.exists()
        else SystemConfig()
    )
    if not isinstance(config, SystemConfig):
        msg = f"Expected SystemConfig from {config_file}"
        raise LLMClientError(msg)

    llm = config.deployment.llm
    api_key = os.getenv(llm.api_key_env)
    if not api_key:
        msg = f"Missing API key environment variable {llm.api_key_env}; run deploy-setup first"
        raise LLMClientError(msg)

    endpoint = _chat_completions_endpoint(llm.base_url)
    response, _ = _completion_payload_and_trace(
        _post_chat_completion(
            endpoint=endpoint,
            api_key=api_key,
            model_name=llm.model_name,
            timeout_seconds=timeout_seconds or llm.request_timeout_seconds,
            max_tokens=max_tokens,
            messages=_smoke_messages(),
            provider=llm.provider,
        )
    )
    content = _extract_message_content(response)
    quality = evaluate_llm_output_quality(content, secret_values=[api_key])
    attempts = 1
    if _has_failed_output_critical_checks(quality):
        attempts += 1
        response, _ = _completion_payload_and_trace(
            _post_chat_completion(
                endpoint=endpoint,
                api_key=api_key,
                model_name=llm.model_name,
                timeout_seconds=timeout_seconds or llm.request_timeout_seconds,
                max_tokens=max_tokens,
                messages=_smoke_repair_messages(
                    previous_response=content,
                    issues=quality.issues,
                ),
                provider=llm.provider,
            )
        )
        content = _extract_message_content(response)
        quality = evaluate_llm_output_quality(content, secret_values=[api_key])
    return LLMSmokeResult(
        provider=llm.provider,
        base_url=llm.base_url,
        model_name=llm.model_name,
        endpoint=endpoint,
        response_text=content,
        usage=response.get("usage", {}) if isinstance(response.get("usage"), dict) else {},
        quality=quality,
        attempts=attempts,
    )


def run_llm_evidence_review(
    *,
    subject_path: Path | str,
    evidence_paths: list[Path | str],
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    timeout_seconds: int | None = None,
    max_tokens: int | None = None,
) -> LLMReviewResult:
    """Ask the configured model to review output using only local evidence artifacts."""

    if not evidence_paths:
        msg = "at least one local evidence file is required for LLM review"
        raise LLMClientError(msg)

    config, api_key = _load_llm_config_and_api_key(config_path=config_path, env_path=env_path)
    llm = config.deployment.llm
    endpoint = _chat_completions_endpoint(llm.base_url)
    subject_file = Path(subject_path)
    subject_text = _read_limited_text(
        subject_file,
        label="subject",
        max_chars=REVIEW_SUBJECT_MAX_CHARS,
    )
    evidence = [
        _read_evidence_artifact(index=index, path=Path(path))
        for index, path in enumerate(evidence_paths, start=1)
    ]
    response, _ = _completion_payload_and_trace(
        _post_chat_completion(
            endpoint=endpoint,
            api_key=api_key,
            model_name=llm.model_name,
            timeout_seconds=timeout_seconds or llm.request_timeout_seconds,
            max_tokens=max_tokens,
            messages=_review_messages(
                subject_path=subject_file,
                subject_text=subject_text,
                evidence=evidence,
            ),
            provider=llm.provider,
        )
    )
    content = _extract_message_content(response)
    quality = evaluate_llm_review_quality(
        content,
        evidence_ids=[artifact.evidence_id for artifact in evidence],
        secret_values=[api_key],
    )
    attempts = 1
    if _has_failed_review_critical_checks(quality):
        attempts += 1
        response, _ = _completion_payload_and_trace(
            _post_chat_completion(
                endpoint=endpoint,
                api_key=api_key,
                model_name=llm.model_name,
                timeout_seconds=timeout_seconds or llm.request_timeout_seconds,
                max_tokens=max_tokens,
                messages=_review_repair_messages(
                    previous_response=content,
                    issues=quality.issues,
                    evidence=evidence,
                ),
                provider=llm.provider,
            )
        )
        content = _extract_message_content(response)
        quality = evaluate_llm_review_quality(
            content,
            evidence_ids=[artifact.evidence_id for artifact in evidence],
            secret_values=[api_key],
        )
    return LLMReviewResult(
        provider=llm.provider,
        base_url=llm.base_url,
        model_name=llm.model_name,
        endpoint=endpoint,
        subject_path=subject_file.as_posix(),
        subject_sha256=file_hash(subject_file),
        evidence=evidence,
        response_text=content,
        usage=response.get("usage", {}) if isinstance(response.get("usage"), dict) else {},
        quality=quality,
        attempts=attempts,
    )


def run_llm_json_completion(
    *,
    messages: list[dict[str, str]],
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    timeout_seconds: int | None = None,
    max_tokens: int | None = None,
    temperature: float = 0.0,
    reasoning_effort: str | None = None,
    thinking_mode: Literal["enabled", "disabled"] | None = None,
    thinking_budget: int | None = None,
    response_schema: dict[str, Any] | None = None,
    response_schema_name: str = "autoresearch_output",
    transport_preflight_hook: TransportPreflightHook | None = None,
    _http_opener: HTTPResponseOpener | None = None,
    _request_id_factory: RequestIdFactory | None = None,
) -> LLMJsonCompletionResult:
    """Call the configured OpenAI-compatible model and require one JSON object.

    ``transport_preflight_hook`` runs synchronously after canonical request bytes
    and a client request ID exist but before the opener is invoked.  It is the
    runner's fail-closed point for a durable budget/pre-call reservation.  The
    two underscore-prefixed injections are deterministic unit-test seams only;
    production callers leave them unset.  Every emitted trace is still only
    process-local integrity evidence and cannot establish a remote provider or
    formal external boundary without an independently signed gateway record.
    """

    config, api_key = _load_llm_config_and_api_key(config_path=config_path, env_path=env_path)
    llm = config.deployment.llm
    effective_thinking_mode, effective_thinking_budget = resolve_thinking_configuration(
        provider=llm.provider,
        model_name=llm.model_name,
        thinking_mode=thinking_mode,
        thinking_budget=thinking_budget,
    )
    if reasoning_effort == "none" and llm.provider.lower().startswith("ollama"):
        endpoint = _ollama_native_chat_endpoint(llm.base_url)
        transported = _post_ollama_native_json_completion(
            endpoint=endpoint,
            api_key=api_key,
            model_name=llm.model_name,
            timeout_seconds=timeout_seconds or llm.request_timeout_seconds,
            max_tokens=max_tokens,
            messages=messages,
            temperature=temperature,
            response_schema=response_schema,
            capture_transport_trace=True,
            transport_preflight_hook=transport_preflight_hook,
            _http_opener=_http_opener,
            _request_id_factory=_request_id_factory,
        )
    else:
        endpoint = _chat_completions_endpoint(llm.base_url)
        transported = _post_chat_completion(
            endpoint=endpoint,
            api_key=api_key,
            model_name=llm.model_name,
            timeout_seconds=timeout_seconds or llm.request_timeout_seconds,
            max_tokens=max_tokens,
            messages=messages,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            thinking_mode=effective_thinking_mode,
            thinking_budget=effective_thinking_budget,
            provider=llm.provider,
            response_schema=response_schema,
            response_schema_name=response_schema_name,
            capture_transport_trace=True,
            transport_preflight_hook=transport_preflight_hook,
            _http_opener=_http_opener,
            _request_id_factory=_request_id_factory,
        )
    response, transport_trace = _completion_payload_and_trace(transported)
    try:
        content = _extract_message_content(response)
    except LLMClientError as exc:
        if transport_trace is not None:
            exc.attach_transport_trace(transport_trace)
        raise
    try:
        parsed, transport_normalization, normalization_suffix = _parse_json_completion_content(
            content
        )
    except json.JSONDecodeError as exc:
        raise LLMClientError(
            f"LLM JSON completion was not valid JSON: {exc.msg}",
            response_text=content,
            response_usage=(
                response.get("usage", {}) if isinstance(response.get("usage"), dict) else {}
            ),
            finish_reason=_response_finish_reason(response),
            transport_trace=transport_trace,
        ) from exc
    if not isinstance(parsed, dict):
        raise LLMClientError(
            "LLM JSON completion top-level value is not an object",
            response_text=content,
            response_usage=(
                response.get("usage", {}) if isinstance(response.get("usage"), dict) else {}
            ),
            finish_reason=_response_finish_reason(response),
            transport_trace=transport_trace,
        )
    reasoning_text = _extract_reasoning_content(response)
    usage = response.get("usage", {}) if isinstance(response.get("usage"), dict) else {}
    return LLMJsonCompletionResult(
        provider=llm.provider,
        base_url=llm.base_url,
        model_name=llm.model_name,
        endpoint=(transport_trace.endpoint if transport_trace is not None else endpoint),
        response_text=content,
        parsed_json=parsed,
        transport_normalization=transport_normalization,
        normalization_suffix=normalization_suffix,
        usage=usage,
        temperature=temperature,
        reasoning_text=reasoning_text,
        reasoning_transport=(
            reasoning_transport_for_provider(llm.provider)
            if effective_thinking_mode is not None
            else "absent"
        ),
        transport_trace=transport_trace,
    )


def _completion_payload_and_trace(
    transported: dict[str, Any] | _TracedCompletionResponse,
) -> tuple[dict[str, Any], LLMHTTPTransportTrace | None]:
    """Normalize old/test-double responses and traced HTTP responses."""

    if isinstance(transported, _TracedCompletionResponse):
        return transported.payload, transported.trace
    return transported, None


def _extract_reasoning_content(response: dict[str, Any]) -> str | None:
    """Return provider reasoning text when present, as explicit recorded output."""

    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return None
    reasoning = message.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning.strip():
        return reasoning[:200_000]
    return None


def evaluate_llm_output_quality(
    response_text: str,
    *,
    secret_values: list[str] | None = None,
) -> LLMOutputQuality:
    """Score model smoke output for structure, evidence discipline, and secret safety."""

    checks: dict[str, bool] = {
        "non_empty": bool(response_text.strip()),
        "valid_json": False,
        "status_ok": False,
        "summary_present": False,
        "evidence_policy_present": False,
        "risks_present": False,
        "next_steps_present": False,
        "no_secret_leak": _has_no_secret_leak(response_text, secret_values or []),
        "no_fake_urls": not bool(re.search(r"https?://", response_text, flags=re.IGNORECASE)),
    }
    issues: list[str] = []
    parsed: dict[str, Any] | None = None
    try:
        decoded = json.loads(_strip_json_fences(response_text))
    except json.JSONDecodeError as exc:
        issues.append(f"Response is not valid JSON: {exc.msg}")
    else:
        if isinstance(decoded, dict):
            parsed = decoded
            checks["valid_json"] = True
            checks["status_ok"] = decoded.get("status") == "ok"
            checks["summary_present"] = _short_text(decoded.get("summary"))
            checks["evidence_policy_present"] = _mentions_evidence_policy(
                decoded.get("evidence_policy")
            )
            checks["risks_present"] = _string_list_has_items(decoded.get("risks"), minimum=2)
            checks["next_steps_present"] = _string_list_has_items(
                decoded.get("next_steps"),
                minimum=2,
            )
        else:
            issues.append("Response JSON top-level value is not an object")

    for check, passed in checks.items():
        if not passed:
            issues.append(f"Quality check failed: {check}")

    score = round(sum(1 for passed in checks.values() if passed) / len(checks), 3)
    critical_checks = (
        "valid_json",
        "status_ok",
        "summary_present",
        "evidence_policy_present",
        "risks_present",
        "next_steps_present",
        "no_secret_leak",
        "no_fake_urls",
    )
    if any(not checks[check] for check in critical_checks):
        score = min(score, 0.5)
    return LLMOutputQuality(score=score, checks=checks, issues=issues, parsed_output=parsed)


def evaluate_llm_review_quality(
    response_text: str,
    *,
    evidence_ids: list[str],
    secret_values: list[str] | None = None,
) -> LLMReviewQuality:
    """Score an LLM reviewer response for local evidence discipline."""

    known_ids = set(evidence_ids)
    checks: dict[str, bool] = {
        "non_empty": bool(response_text.strip()),
        "valid_json": False,
        "verdict_present": False,
        "summary_present": False,
        "findings_present": False,
        "finding_refs_present": False,
        "finding_refs_known": False,
        "unsupported_claims_present": False,
        "next_steps_present": False,
        "profile_context_not_used_as_scientific_evidence": False,
        "no_secret_leak": _has_no_secret_leak(response_text, secret_values or []),
        "no_fake_urls": not bool(re.search(r"https?://", response_text, flags=re.IGNORECASE)),
    }
    issues: list[str] = []
    parsed: dict[str, Any] | None = None
    try:
        decoded = json.loads(_strip_json_fences(response_text))
    except json.JSONDecodeError as exc:
        issues.append(f"Review response is not valid JSON: {exc.msg}")
    else:
        if isinstance(decoded, dict):
            parsed = decoded
            checks["valid_json"] = True
            checks["verdict_present"] = decoded.get("verdict") in {
                "pass",
                "needs_revision",
                "fail",
            }
            checks["summary_present"] = _short_text(decoded.get("summary"))
            findings = decoded.get("findings")
            checks["findings_present"] = isinstance(findings, list) and bool(findings)
            refs_by_finding = _finding_evidence_refs(findings)
            checks["finding_refs_present"] = bool(refs_by_finding) and all(refs_by_finding)
            checks["finding_refs_known"] = bool(refs_by_finding) and all(
                ref in known_ids for refs in refs_by_finding for ref in refs
            )
            checks["unsupported_claims_present"] = isinstance(
                decoded.get("unsupported_claims"),
                list,
            )
            checks["next_steps_present"] = _string_list_has_items(
                decoded.get("next_steps"),
                minimum=1,
            )
            checks[
                "profile_context_not_used_as_scientific_evidence"
            ] = not _review_misuses_profile_context(findings)
        else:
            issues.append("Review response JSON top-level value is not an object")

    for check, passed in checks.items():
        if not passed:
            issues.append(f"Review quality check failed: {check}")

    score = round(sum(1 for passed in checks.values() if passed) / len(checks), 3)
    critical_checks = (
        "valid_json",
        "verdict_present",
        "summary_present",
        "findings_present",
        "finding_refs_present",
        "finding_refs_known",
        "unsupported_claims_present",
        "next_steps_present",
        "profile_context_not_used_as_scientific_evidence",
        "no_secret_leak",
        "no_fake_urls",
    )
    if any(not checks[check] for check in critical_checks):
        score = min(score, 0.5)
    return LLMReviewQuality(score=score, checks=checks, issues=issues, parsed_output=parsed)


def _has_failed_output_critical_checks(quality: LLMOutputQuality) -> bool:
    critical_checks = (
        "valid_json",
        "status_ok",
        "summary_present",
        "evidence_policy_present",
        "risks_present",
        "next_steps_present",
        "no_secret_leak",
        "no_fake_urls",
    )
    return any(not quality.checks.get(check, False) for check in critical_checks)


def _has_failed_review_critical_checks(quality: LLMReviewQuality) -> bool:
    critical_checks = (
        "valid_json",
        "verdict_present",
        "summary_present",
        "findings_present",
        "finding_refs_present",
        "finding_refs_known",
        "unsupported_claims_present",
        "next_steps_present",
        "profile_context_not_used_as_scientific_evidence",
        "no_secret_leak",
        "no_fake_urls",
    )
    return any(not quality.checks.get(check, False) for check in critical_checks)


_DEFAULT_THINKING_BUDGET = 4_000


def _is_qwen37_max(*, provider: str, model_name: str) -> bool:
    normalized_provider = provider.strip().casefold()
    normalized_model = model_name.strip().casefold()
    return (
        "dashscope" in normalized_provider
        or "qwen" in normalized_provider
        or normalized_provider == "aliyun-bailian"
    ) and (normalized_model == "qwen3.7-max" or normalized_model.startswith("qwen3.7-max-"))


def resolve_thinking_configuration(
    *,
    provider: str,
    model_name: str,
    thinking_mode: Literal["enabled", "disabled"] | None,
    thinking_budget: int | None,
) -> tuple[Literal["enabled", "disabled"] | None, int | None]:
    """Make Qwen3.7 Max's provider-default thinking behavior explicit."""

    if not _is_qwen37_max(provider=provider, model_name=model_name):
        return thinking_mode, thinking_budget
    effective_mode: Literal["enabled", "disabled"] = thinking_mode or "enabled"
    if effective_mode == "disabled":
        if thinking_budget is not None:
            raise LLMClientError("thinking_budget must be None when thinking is disabled")
        return effective_mode, None
    effective_budget = thinking_budget if thinking_budget is not None else _DEFAULT_THINKING_BUDGET
    if effective_budget < 1:
        raise LLMClientError("thinking_budget must be positive when thinking is enabled")
    return effective_mode, effective_budget


def reasoning_transport_for_provider(
    provider: str,
) -> Literal["dashscope_enable_thinking", "anthropic_thinking_block"]:
    """Return the reasoning-parameter dialect a provider actually accepts.

    Task 267.3.1.  Kept provider-neutral: engine code passes a normalized
    `thinking_mode` and this function maps it onto the vendor's real field names.
    """

    normalized = provider.casefold()
    if "dashscope" in normalized or "qwen" in normalized or "ollama" in normalized:
        return "dashscope_enable_thinking"
    if "anthropic" in normalized or "claude" in normalized:
        return "anthropic_thinking_block"
    # Unknown providers use the OpenAI-compatible DashScope-style field, which is
    # the dialect this deployment has actually verified live.
    return "dashscope_enable_thinking"


def _reasoning_parameters(
    *,
    provider: str,
    thinking_mode: Literal["enabled", "disabled"],
    thinking_budget: int | None,
) -> dict[str, Any]:
    """Build the provider-correct reasoning payload fields.

    Always bounds the reasoning budget when reasoning is enabled: unbounded
    reasoning on `qwen3-max` produced 81,933 completion tokens for a trivial
    prompt and an intermittently empty `content`.
    """

    transport = reasoning_transport_for_provider(provider)
    if transport == "anthropic_thinking_block":
        return {"thinking": {"type": thinking_mode}}
    if thinking_mode != "enabled":
        return {"enable_thinking": False}
    return {
        "enable_thinking": True,
        "thinking_budget": (
            thinking_budget if thinking_budget is not None else _DEFAULT_THINKING_BUDGET
        ),
    }


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _addressed_model_sha256(model: BaseModel, hash_field: str) -> str:
    return _sha256_bytes(_canonical_json_bytes(model.model_dump(mode="json", exclude={hash_field})))


def _credential_free_endpoint(endpoint: str) -> str:
    """Validate and canonicalize an HTTP endpoint without silently dropping data."""

    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("LLM HTTP endpoint must include an http(s) host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("LLM HTTP endpoint must not contain userinfo")
    if parsed.query:
        raise ValueError("LLM HTTP endpoint must not contain a query")
    if parsed.fragment:
        raise ValueError("LLM HTTP endpoint must not contain a fragment")
    hostname = parsed.hostname.casefold()
    host = f"[{hostname}]" if ":" in hostname else hostname
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("LLM HTTP endpoint has an invalid port") from exc
    netloc = f"{host}:{port}" if port is not None else host
    return urllib.parse.urlunsplit((parsed.scheme.casefold(), netloc, parsed.path or "/", "", ""))


def _transport_scope(
    adapter_id: str,
    endpoint: str,
) -> Literal["external_service", "local_service"]:
    if adapter_id == "autoresearch.ollama-native-local-http.v1":
        return "local_service"
    hostname = urllib.parse.urlsplit(endpoint).hostname
    if hostname is None:
        raise ValueError("LLM HTTP endpoint has no host")
    normalized = hostname.casefold().rstrip(".")
    if normalized in {"localhost", "localhost.localdomain"} or normalized.endswith(".localhost"):
        return "local_service"
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return "local_service" if normalized.endswith(".local") else "external_service"
    return (
        "local_service"
        if (
            address.is_loopback
            or address.is_private
            or address.is_link_local
            or address.is_unspecified
        )
        else "external_service"
    )


def _transport_metadata_payload(
    item: LLMTransportPreflight | LLMHTTPTransportTrace | LLMTransportFailureTrace,
) -> dict[str, Any]:
    return {
        "adapter_id": item.adapter_id,
        "endpoint": item.endpoint,
        "external_process_or_service_boundary_crossed": (
            item.external_process_or_service_boundary_crossed
        ),
        "formal_external_anchor_eligible": item.formal_external_anchor_eligible,
        "independent_signed_gateway_attestation_present": (
            item.independent_signed_gateway_attestation_present
        ),
        "process_local_integrity_only": item.process_local_integrity_only,
        "request_id": item.request_id,
        "request_method": item.request_method,
        "request_payload_sha256": item.request_payload_sha256,
        "request_payload_size_bytes": item.request_payload_size_bytes,
        "transport_implementation": item.transport_implementation,
        "transport_scope": item.transport_scope,
    }


def _http_metadata_payload(trace: LLMHTTPTransportTrace) -> dict[str, Any]:
    return {
        "http_status_code": trace.http_status_code,
        "provider_response_id_sha256": trace.provider_response_id_sha256,
        "raw_response_body_sha256": trace.raw_response_body_sha256,
        "raw_response_body_size_bytes": trace.raw_response_body_size_bytes,
        "selected_response_header_names": list(trace.selected_response_header_names),
        "selected_response_headers_sha256": trace.selected_response_headers_sha256,
    }


def _failure_http_metadata_payload(
    trace: LLMTransportFailureTrace,
) -> dict[str, Any]:
    return {
        "http_status_code": trace.http_status_code,
        "provider_response_id_sha256": trace.provider_response_id_sha256,
        "raw_response_body_sha256": trace.raw_response_body_sha256,
        "raw_response_body_size_bytes": trace.raw_response_body_size_bytes,
        "selected_response_header_names": list(trace.selected_response_header_names),
        "selected_response_headers_sha256": trace.selected_response_headers_sha256,
    }


def _preflight_from_trace(trace: LLMHTTPTransportTrace) -> LLMTransportPreflight:
    values: dict[str, Any] = {
        "schema_version": "llm-http-transport-preflight-v2",
        "request_id": trace.request_id,
        "adapter_id": trace.adapter_id,
        "transport_scope": trace.transport_scope,
        "transport_implementation": trace.transport_implementation,
        "endpoint": trace.endpoint,
        "request_method": "POST",
        "request_payload_sha256": trace.request_payload_sha256,
        "request_payload_size_bytes": trace.request_payload_size_bytes,
        "external_process_or_service_boundary_crossed": False,
        "formal_external_anchor_eligible": False,
        "process_local_integrity_only": True,
        "independent_signed_gateway_attestation_present": False,
    }
    values["preflight_sha256"] = _sha256_bytes(_canonical_json_bytes(values))
    return LLMTransportPreflight.model_validate(values)


def _build_transport_preflight(
    *,
    request_id: str,
    adapter_id: Literal[
        "autoresearch.openai-compatible-http.v1",
        "autoresearch.ollama-native-local-http.v1",
    ],
    endpoint: str,
    request_payload: bytes,
    implementation: TransportImplementation,
) -> LLMTransportPreflight:
    safe_endpoint = _credential_free_endpoint(endpoint)
    values: dict[str, Any] = {
        "schema_version": "llm-http-transport-preflight-v2",
        "request_id": request_id,
        "adapter_id": adapter_id,
        "transport_scope": _transport_scope(adapter_id, safe_endpoint),
        "transport_implementation": implementation,
        "endpoint": safe_endpoint,
        "request_method": "POST",
        "request_payload_sha256": _sha256_bytes(request_payload),
        "request_payload_size_bytes": len(request_payload),
        "external_process_or_service_boundary_crossed": False,
        "formal_external_anchor_eligible": False,
        "process_local_integrity_only": True,
        "independent_signed_gateway_attestation_present": False,
    }
    values["preflight_sha256"] = _sha256_bytes(_canonical_json_bytes(values))
    return LLMTransportPreflight.model_validate(values)


def _normalized_selected_response_headers(
    headers: object,
) -> tuple[tuple[str, ...], str]:
    items_method = getattr(headers, "items", None)
    raw_items = items_method() if callable(items_method) else []
    selected: list[tuple[str, str]] = []
    for raw_name, raw_value in raw_items:
        name = str(raw_name).strip().casefold()
        if name not in _SAFE_RESPONSE_HEADERS:
            continue
        value = re.sub(r"\s+", " ", str(raw_value).strip())
        value = re.sub(r"(?i)bearer\s+\S+", "Bearer ***", value)
        value = _redact_api_key(value)
        selected.append((name, value))
    selected.sort()
    names = tuple(sorted({name for name, _ in selected}))
    return names, _sha256_bytes(_canonical_json_bytes(selected))


def _response_status(response: object) -> int:
    status = getattr(response, "status", None)
    if not isinstance(status, int):
        getcode = getattr(response, "getcode", None)
        status = getcode() if callable(getcode) else 200
    if not isinstance(status, int) or not 100 <= status <= 599:
        raise LLMClientError("LLM API response did not expose a valid HTTP status")
    return status


def _provider_response_id_sha256(payload: Mapping[str, Any] | None) -> str | None:
    if payload is None:
        return None
    value = payload.get("id")
    if not isinstance(value, str) or not value.strip():
        return None
    return _sha256_bytes(value.encode("utf-8"))


def _completion_field_hashes(
    payload: Mapping[str, Any] | None,
) -> tuple[str | None, str | None, str | None]:
    if payload is None:
        return None, None, None
    try:
        visible = _extract_message_content(dict(payload))
    except LLMClientError:
        return None, None, None
    reasoning = _extract_reasoning_content(dict(payload))
    usage = payload.get("usage")
    usage_mapping = usage if isinstance(usage, dict) else {}
    return (
        _sha256_bytes(visible.encode("utf-8")),
        _sha256_bytes((reasoning or "").encode("utf-8")),
        _sha256_bytes(_canonical_json_bytes(usage_mapping)),
    )


def _build_http_transport_trace(
    exchange: _HTTPJSONExchange,
    completion_payload: Mapping[str, Any] | None,
) -> LLMHTTPTransportTrace:
    visible_hash, reasoning_hash, usage_hash = _completion_field_hashes(completion_payload)
    values: dict[str, Any] = {
        "schema_version": "llm-http-transport-trace-v2",
        "request_id": exchange.preflight.request_id,
        "adapter_id": exchange.preflight.adapter_id,
        "transport_scope": exchange.preflight.transport_scope,
        "transport_implementation": exchange.preflight.transport_implementation,
        "endpoint": exchange.preflight.endpoint,
        "request_method": "POST",
        "request_payload_sha256": exchange.preflight.request_payload_sha256,
        "request_payload_size_bytes": exchange.preflight.request_payload_size_bytes,
        "http_status_code": exchange.http_status_code,
        "selected_response_header_names": exchange.selected_response_header_names,
        "selected_response_headers_sha256": exchange.selected_response_headers_sha256,
        "raw_response_body_sha256": _sha256_bytes(exchange.raw_response_body),
        "raw_response_body_size_bytes": len(exchange.raw_response_body),
        "provider_response_id_sha256": _provider_response_id_sha256(exchange.payload),
        "completion_fields_available": visible_hash is not None,
        "visible_output_utf8_sha256": visible_hash,
        "reasoning_output_utf8_sha256": reasoning_hash,
        "usage_canonical_json_sha256": usage_hash,
        "external_process_or_service_boundary_crossed": False,
        "formal_external_anchor_eligible": False,
        "process_local_integrity_only": True,
        "independent_signed_gateway_attestation_present": False,
    }
    transport_payload = {
        key: values[key]
        for key in (
            "adapter_id",
            "endpoint",
            "external_process_or_service_boundary_crossed",
            "formal_external_anchor_eligible",
            "independent_signed_gateway_attestation_present",
            "process_local_integrity_only",
            "request_id",
            "request_method",
            "request_payload_sha256",
            "request_payload_size_bytes",
            "transport_implementation",
            "transport_scope",
        )
    }
    http_payload = {
        "http_status_code": values["http_status_code"],
        "provider_response_id_sha256": values["provider_response_id_sha256"],
        "raw_response_body_sha256": values["raw_response_body_sha256"],
        "raw_response_body_size_bytes": values["raw_response_body_size_bytes"],
        "selected_response_header_names": list(exchange.selected_response_header_names),
        "selected_response_headers_sha256": values["selected_response_headers_sha256"],
    }
    values["transport_metadata_sha256"] = _sha256_bytes(_canonical_json_bytes(transport_payload))
    values["http_metadata_sha256"] = _sha256_bytes(_canonical_json_bytes(http_payload))
    values["trace_sha256"] = _sha256_bytes(_canonical_json_bytes(values))
    return LLMHTTPTransportTrace.model_validate(values)


def _build_transport_failure_trace(
    *,
    preflight: LLMTransportPreflight,
    failure_stage: Literal["pre_transport_callback", "transport", "http_response"],
    error_type: str,
    http_status_code: int | None = None,
    response_headers: object | None = None,
    raw_response_body: bytes | None = None,
    provider_response_id_sha256: str | None = None,
) -> LLMTransportFailureTrace:
    response_received = http_status_code is not None and raw_response_body is not None
    names: tuple[str, ...] = ()
    headers_hash: str | None = None
    if response_received:
        names, headers_hash = _normalized_selected_response_headers(response_headers)
    values: dict[str, Any] = {
        "schema_version": "llm-http-transport-failure-v2",
        "request_id": preflight.request_id,
        "adapter_id": preflight.adapter_id,
        "transport_scope": preflight.transport_scope,
        "transport_implementation": preflight.transport_implementation,
        "endpoint": preflight.endpoint,
        "request_method": "POST",
        "request_payload_sha256": preflight.request_payload_sha256,
        "request_payload_size_bytes": preflight.request_payload_size_bytes,
        "failure_stage": failure_stage,
        "error_type": error_type[:128],
        "http_status_code": http_status_code,
        "selected_response_header_names": names,
        "selected_response_headers_sha256": headers_hash,
        "raw_response_body_sha256": (
            _sha256_bytes(raw_response_body) if raw_response_body is not None else None
        ),
        "raw_response_body_size_bytes": (
            len(raw_response_body) if raw_response_body is not None else None
        ),
        "provider_response_id_sha256": provider_response_id_sha256,
        "transport_attempted": failure_stage != "pre_transport_callback",
        "http_response_received": response_received,
        "external_process_or_service_boundary_crossed": False,
        "formal_external_anchor_eligible": False,
        "process_local_integrity_only": True,
        "independent_signed_gateway_attestation_present": False,
    }
    transport_payload = {
        key: values[key]
        for key in (
            "adapter_id",
            "endpoint",
            "external_process_or_service_boundary_crossed",
            "formal_external_anchor_eligible",
            "independent_signed_gateway_attestation_present",
            "process_local_integrity_only",
            "request_id",
            "request_method",
            "request_payload_sha256",
            "request_payload_size_bytes",
            "transport_implementation",
            "transport_scope",
        )
    }
    values["transport_metadata_sha256"] = _sha256_bytes(_canonical_json_bytes(transport_payload))
    if response_received:
        http_payload = {
            "http_status_code": values["http_status_code"],
            "provider_response_id_sha256": values["provider_response_id_sha256"],
            "raw_response_body_sha256": values["raw_response_body_sha256"],
            "raw_response_body_size_bytes": values["raw_response_body_size_bytes"],
            "selected_response_header_names": list(names),
            "selected_response_headers_sha256": values["selected_response_headers_sha256"],
        }
        values["http_metadata_sha256"] = _sha256_bytes(_canonical_json_bytes(http_payload))
    else:
        values["http_metadata_sha256"] = None
    values["failure_trace_sha256"] = _sha256_bytes(_canonical_json_bytes(values))
    return LLMTransportFailureTrace.model_validate(values)


def _post_http_json_object(
    *,
    endpoint: str,
    api_key: str,
    timeout_seconds: int,
    payload: Mapping[str, Any],
    adapter_id: Literal[
        "autoresearch.openai-compatible-http.v1",
        "autoresearch.ollama-native-local-http.v1",
    ],
    error_label: str,
    transport_preflight_hook: TransportPreflightHook | None,
    _http_opener: HTTPResponseOpener | None,
    _request_id_factory: RequestIdFactory | None,
) -> _HTTPJSONExchange:
    request_payload = _canonical_json_bytes(payload)
    request_id_factory = _request_id_factory or (lambda: f"ar-{uuid.uuid4().hex}")
    request_id = request_id_factory()
    implementation: TransportImplementation
    if _http_opener is not None:
        implementation = "injected_test_opener"
    elif urllib.request.urlopen is _ORIGINAL_STDLIB_URLOPEN:
        implementation = "stdlib_urlopen"
    else:
        implementation = "replaced_global_urlopen"
    try:
        preflight = _build_transport_preflight(
            request_id=request_id,
            adapter_id=adapter_id,
            endpoint=endpoint,
            request_payload=request_payload,
            implementation=implementation,
        )
    except (TypeError, ValueError) as exc:
        raise LLMClientError(f"{error_label} transport preflight was invalid") from exc
    if transport_preflight_hook is not None:
        try:
            transport_preflight_hook(preflight, request_payload)
        except Exception as exc:
            failure = _build_transport_failure_trace(
                preflight=preflight,
                failure_stage="pre_transport_callback",
                error_type=type(exc).__name__,
            )
            raise LLMClientError(
                f"{error_label} pre-transport reservation callback failed: {type(exc).__name__}",
                transport_preflight=preflight,
                transport_failure_trace=failure,
            ) from exc
    request = urllib.request.Request(
        preflight.endpoint,
        data=request_payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-AutoResearch-Request-ID": preflight.request_id,
        },
        method="POST",
    )
    if request.full_url != preflight.endpoint:
        raise LLMClientError(
            f"{error_label} request endpoint differs from its recorded preflight",
            transport_preflight=preflight,
        )
    opener = _http_opener or urllib.request.urlopen
    response_obtained = False
    try:
        response_context = opener(request, timeout=timeout_seconds)
        response_obtained = True
        with response_context as response:
            raw_response_body = response.read()
            if not isinstance(raw_response_body, bytes):
                raise TypeError("HTTP response body is not bytes")
            http_status_code = _response_status(response)
            header_names, headers_hash = _normalized_selected_response_headers(
                getattr(response, "headers", None)
            )
    except urllib.error.HTTPError as exc:
        if response_obtained:
            raise LLMClientError(
                f"{error_label} response processing failed: {type(exc).__name__}",
                transport_preflight=preflight,
            ) from exc
        try:
            error_body = exc.read()
        except Exception:
            error_body = b""
        if not isinstance(error_body, bytes):
            error_body = str(error_body).encode("utf-8", errors="replace")
        decoded_error: Mapping[str, Any] | None = None
        try:
            possible_error = json.loads(error_body.decode("utf-8"))
            if isinstance(possible_error, dict):
                decoded_error = possible_error
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        failure = _build_transport_failure_trace(
            preflight=preflight,
            failure_stage="http_response",
            error_type=type(exc).__name__,
            http_status_code=exc.code,
            response_headers=exc.headers,
            raw_response_body=error_body,
            provider_response_id_sha256=_provider_response_id_sha256(decoded_error),
        )
        raise LLMClientError(
            f"{error_label} HTTP {exc.code}; response body retained by SHA-256 only",
            transport_preflight=preflight,
            transport_failure_trace=failure,
        ) from exc
    except urllib.error.URLError as exc:
        if response_obtained:
            raise LLMClientError(
                f"{error_label} response processing failed: {type(exc).__name__}",
                transport_preflight=preflight,
            ) from exc
        failure = _build_transport_failure_trace(
            preflight=preflight,
            failure_stage="transport",
            error_type=type(exc).__name__,
        )
        reason = _redact_api_key(str(exc.reason), secret_values=[api_key])
        raise LLMClientError(
            f"{error_label} request failed: {reason}",
            transport_preflight=preflight,
            transport_failure_trace=failure,
        ) from exc
    except TimeoutError as exc:
        if response_obtained:
            raise LLMClientError(
                f"{error_label} response processing failed: {type(exc).__name__}",
                transport_preflight=preflight,
            ) from exc
        failure = _build_transport_failure_trace(
            preflight=preflight,
            failure_stage="transport",
            error_type=type(exc).__name__,
        )
        raise LLMClientError(
            f"{error_label} request timed out",
            transport_preflight=preflight,
            transport_failure_trace=failure,
        ) from exc
    except (http.client.HTTPException, ConnectionError, OSError, TypeError) as exc:
        if response_obtained:
            raise LLMClientError(
                f"{error_label} response processing failed: {type(exc).__name__}",
                transport_preflight=preflight,
            ) from exc
        failure = _build_transport_failure_trace(
            preflight=preflight,
            failure_stage="transport",
            error_type=type(exc).__name__,
        )
        safe_error = _redact_api_key(str(exc), secret_values=[api_key])
        raise LLMClientError(
            f"{error_label} request failed: {type(exc).__name__}: {safe_error}",
            transport_preflight=preflight,
            transport_failure_trace=failure,
        ) from exc

    if not 200 <= http_status_code <= 299:
        failure = _build_transport_failure_trace(
            preflight=preflight,
            failure_stage="http_response",
            error_type="NonSuccessHTTPStatus",
            http_status_code=http_status_code,
            response_headers=getattr(response, "headers", None),
            raw_response_body=raw_response_body,
        )
        raise LLMClientError(
            f"{error_label} HTTP {http_status_code}",
            transport_preflight=preflight,
            transport_failure_trace=failure,
        )
    incomplete_exchange = _HTTPJSONExchange(
        payload={},
        preflight=preflight,
        raw_response_body=raw_response_body,
        http_status_code=http_status_code,
        selected_response_header_names=header_names,
        selected_response_headers_sha256=headers_hash,
    )
    try:
        decoded = json.loads(raw_response_body.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise LLMClientError(
            f"{error_label} response was not UTF-8",
            transport_preflight=preflight,
            transport_trace=_build_http_transport_trace(incomplete_exchange, None),
        ) from exc
    except json.JSONDecodeError as exc:
        raise LLMClientError(
            f"{error_label} response was not JSON: {exc.msg}",
            transport_preflight=preflight,
            transport_trace=_build_http_transport_trace(incomplete_exchange, None),
        ) from exc
    if not isinstance(decoded, dict):
        raise LLMClientError(
            f"{error_label} response JSON top-level value is not an object",
            transport_preflight=preflight,
            transport_trace=_build_http_transport_trace(incomplete_exchange, None),
        )
    return _HTTPJSONExchange(
        payload=decoded,
        preflight=preflight,
        raw_response_body=raw_response_body,
        http_status_code=http_status_code,
        selected_response_header_names=header_names,
        selected_response_headers_sha256=headers_hash,
    )


def _post_chat_completion(
    *,
    endpoint: str,
    api_key: str,
    model_name: str,
    timeout_seconds: int,
    max_tokens: int | None,
    messages: list[dict[str, str]] | None = None,
    temperature: float = 0.0,
    reasoning_effort: str | None = None,
    thinking_mode: Literal["enabled", "disabled"] | None = None,
    thinking_budget: int | None = None,
    provider: str = "",
    response_schema: dict[str, Any] | None = None,
    response_schema_name: str = "autoresearch_output",
    capture_transport_trace: bool = False,
    transport_preflight_hook: TransportPreflightHook | None = None,
    _http_opener: HTTPResponseOpener | None = None,
    _request_id_factory: RequestIdFactory | None = None,
) -> dict[str, Any] | _TracedCompletionResponse:
    effective_thinking_mode, effective_thinking_budget = resolve_thinking_configuration(
        provider=provider,
        model_name=model_name,
        thinking_mode=thinking_mode,
        thinking_budget=thinking_budget,
    )
    payload = {
        "model": model_name,
        "messages": messages or _smoke_messages(),
        "temperature": temperature,
        "response_format": (
            {
                "type": "json_schema",
                "json_schema": {
                    "name": response_schema_name,
                    "strict": True,
                    "schema": response_schema,
                },
            }
            if response_schema is not None
            else {"type": "json_object"}
        ),
    }
    if max_tokens is not None:
        # This public argument has always represented the visible-answer budget.
        # DashScope documents the same semantics for ``max_tokens``: reasoning is
        # bounded independently by ``thinking_budget``.  Substituting
        # ``max_completion_tokens`` here would turn the answer budget into a total
        # reasoning-plus-answer budget and makes valid short-answer calls fail when
        # the independently requested thinking budget is larger.
        payload["max_tokens"] = max_tokens
    if reasoning_effort is not None:
        payload["reasoning_effort"] = reasoning_effort
    if effective_thinking_mode is not None:
        # Task 267.3.1: dispatch the provider-correct reasoning parameter.
        # The Anthropic-shaped `{"thinking": {"type": ...}}` field is silently
        # ignored by DashScope, which returns HTTP 200 with empty
        # `reasoning_content`, so the reasoning chain was never engaged.
        payload.update(
            _reasoning_parameters(
                provider=provider,
                thinking_mode=effective_thinking_mode,
                thinking_budget=effective_thinking_budget,
            )
        )
    exchange = _post_http_json_object(
        endpoint=endpoint,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        payload=payload,
        adapter_id="autoresearch.openai-compatible-http.v1",
        error_label="LLM API",
        transport_preflight_hook=transport_preflight_hook,
        _http_opener=_http_opener,
        _request_id_factory=_request_id_factory,
    )
    if not capture_transport_trace:
        return exchange.payload
    return _TracedCompletionResponse(
        payload=exchange.payload,
        trace=_build_http_transport_trace(exchange, exchange.payload),
    )


def _ollama_native_chat_endpoint(base_url: str) -> str:
    """Translate an Ollama OpenAI-compatible base URL to its native chat endpoint."""

    safe_base_url = _credential_free_endpoint(base_url.rstrip("/"))
    parsed = urllib.parse.urlsplit(safe_base_url)
    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[:-3]
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, f"{path}/api/chat", "", ""))


def _post_ollama_native_json_completion(
    *,
    endpoint: str,
    api_key: str,
    model_name: str,
    timeout_seconds: int,
    max_tokens: int | None,
    messages: list[dict[str, str]],
    temperature: float,
    response_schema: dict[str, Any] | None,
    capture_transport_trace: bool = False,
    transport_preflight_hook: TransportPreflightHook | None = None,
    _http_opener: HTTPResponseOpener | None = None,
    _request_id_factory: RequestIdFactory | None = None,
) -> dict[str, Any] | _TracedCompletionResponse:
    """Use Ollama's native ``think=false`` path and normalize its response.

    Ollama's OpenAI-compatible endpoint currently accepts ``reasoning_effort``
    but does not disable thinking for Qwen 3.5. Short structured calls can
    therefore spend the complete output budget on hidden reasoning and return
    an empty message. The native endpoint has an explicit ``think`` switch.
    The public client selects this adapter only for an Ollama provider and an
    explicit ``reasoning_effort="none"`` request.
    """

    options: dict[str, Any] = {"temperature": temperature}
    if max_tokens is not None:
        options["num_predict"] = max_tokens
    payload: dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "stream": False,
        "think": False,
        "format": response_schema or "json",
        "options": options,
    }
    exchange = _post_http_json_object(
        endpoint=endpoint,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        payload=payload,
        adapter_id="autoresearch.ollama-native-local-http.v1",
        error_label="Ollama native API",
        transport_preflight_hook=transport_preflight_hook,
        _http_opener=_http_opener,
        _request_id_factory=_request_id_factory,
    )
    decoded = exchange.payload
    incomplete_trace = _build_http_transport_trace(exchange, None)
    message = decoded.get("message")
    if not isinstance(message, dict):
        raise LLMClientError(
            "Ollama native API response did not include a message",
            transport_trace=incomplete_trace,
        )
    content = message.get("content")
    if not isinstance(content, str):
        raise LLMClientError(
            "Ollama native API message content is not text",
            transport_trace=incomplete_trace,
        )
    normalized = {
        "choices": [
            {
                "finish_reason": decoded.get("done_reason"),
                "message": {"role": message.get("role", "assistant"), "content": content},
            }
        ],
        "usage": {
            "prompt_tokens": int(decoded.get("prompt_eval_count") or 0),
            "completion_tokens": int(decoded.get("eval_count") or 0),
            "total_tokens": int(decoded.get("prompt_eval_count") or 0)
            + int(decoded.get("eval_count") or 0),
        },
    }
    if not capture_transport_trace:
        return normalized
    return _TracedCompletionResponse(
        payload=normalized,
        trace=_build_http_transport_trace(exchange, normalized),
    )


def _smoke_messages() -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are the AI-Researcher deployment smoke-test model. "
                "Return only one valid JSON object. Do not include markdown fences. "
                "Do not invent URLs, paper titles, benchmark scores, or external results. "
                "Do not encode JSON arrays as strings."
            ),
        },
        {
            "role": "user",
            "content": (
                "Create a concise deployment readiness note for AI-Researcher. "
                "Use this exact JSON object shape: "
                '{"status":"ok","summary":"...","evidence_policy":"...",'
                '"risks":["...","..."],"next_steps":["...","..."]}. '
                "`risks` and `next_steps` must be real JSON arrays, not quoted strings. "
                "The summary must say that unverified research outcomes remain pending "
                "verification. The evidence_policy must mention source-backed evidence "
                "or independent fact-checking."
            ),
        },
    ]


def _smoke_repair_messages(
    *,
    previous_response: str,
    issues: list[str],
) -> list[dict[str, str]]:
    issue_text = "; ".join(issues[:8])
    return [
        {
            "role": "system",
            "content": (
                "You are repairing a failed AI-Researcher deployment smoke-test response. "
                "Return only one syntactically valid JSON object. Do not include markdown "
                "fences, comments, URLs, or quoted JSON arrays."
            ),
        },
        {
            "role": "user",
            "content": (
                "The previous response failed deterministic local quality checks. "
                f"Failed checks and parser errors: {issue_text}. "
                "Return a corrected object with exactly these keys and value types: "
                '{"status":"ok","summary":"...","evidence_policy":"...",'
                '"risks":["...","..."],"next_steps":["...","..."]}. '
                "Both `risks` and `next_steps` must be arrays of strings. "
                "The summary must say that unverified research outcomes remain pending "
                "verification. The evidence_policy must mention source-backed evidence "
                "or independent fact-checking.\n\n"
                f"Previous invalid response:\n{previous_response[:2000]}"
            ),
        },
    ]


def _load_llm_config_and_api_key(
    *,
    config_path: Path | str,
    env_path: Path | str,
) -> tuple[SystemConfig, str]:
    env_file = Path(env_path)
    if env_file.exists():
        load_dotenv(env_file, override=True)

    config_file = Path(config_path)
    config = (
        ConfigParser().parse_file(config_file, model_type=SystemConfig)
        if config_file.exists()
        else SystemConfig()
    )
    if not isinstance(config, SystemConfig):
        msg = f"Expected SystemConfig from {config_file}"
        raise LLMClientError(msg)

    llm = config.deployment.llm
    api_key = os.getenv(llm.api_key_env)
    if not api_key:
        msg = f"Missing API key environment variable {llm.api_key_env}; run deploy-setup first"
        raise LLMClientError(msg)
    return config, api_key


def _read_evidence_artifact(*, index: int, path: Path) -> LLMEvidenceArtifact:
    excerpt = _read_limited_text(
        path,
        label=f"evidence_{index}",
        max_chars=REVIEW_EVIDENCE_MAX_CHARS,
    )
    return LLMEvidenceArtifact(
        evidence_id=f"evidence_{index}",
        path=path.as_posix(),
        sha256=file_hash(path),
        excerpt=excerpt,
    )


def _read_limited_text(path: Path, *, label: str, max_chars: int) -> str:
    if not path.exists():
        msg = f"{label} file is missing: {path.as_posix()}"
        raise LLMClientError(msg)
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        msg = f"{label} file must be UTF-8 text: {path.as_posix()}"
        raise LLMClientError(msg) from exc
    return text[:max_chars]


def _review_messages(
    *,
    subject_path: Path,
    subject_text: str,
    evidence: list[LLMEvidenceArtifact],
) -> list[dict[str, str]]:
    evidence_block = "\n\n".join(
        (
            f"[{artifact.evidence_id}] path={artifact.path} sha256={artifact.sha256}\n"
            f"{artifact.excerpt}"
        )
        for artifact in evidence
    )
    allowed_ids = ", ".join(artifact.evidence_id for artifact in evidence)
    return [
        {
            "role": "system",
            "content": (
                "You are the AI-Researcher quality reviewer. Return only JSON. "
                "Judge the subject only against the provided local evidence artifacts. "
                "Every finding must cite one or more provided evidence IDs exactly. "
                "Use only the outer evidence IDs supplied by this prompt as citations. "
                "Agent profile context, including agent_profiles, stage_runtime_contexts, "
                "stage_agent_contexts, skills, MCP allowlists, and mcp_runtime_contracts, "
                "is process metadata only. "
                "It may support findings about responsibility boundaries or available tool "
                "context, but it is not evidence for scientific results, novelty, benchmark "
                "metrics, citation validity, or publication readiness. A profile does not "
                "prove a tool was invoked. "
                "Do not invent URLs, papers, metrics, benchmark results, or files. "
                "Do not encode JSON arrays as strings."
            ),
        },
        {
            "role": "user",
            "content": (
                "Review the subject output for evidence support, unsupported claims, "
                "missing caveats, and next actions. Use this exact JSON object shape: "
                '{"verdict":"pass|needs_revision|fail","summary":"...",'
                '"findings":[{"severity":"info|warning|blocking","claim":"...",'
                '"evidence_refs":["evidence_1"]}],"unsupported_claims":["..."],'
                '"next_steps":["..."]}. `findings`, `evidence_refs`, `unsupported_claims`, '
                "and `next_steps` must be real JSON arrays, not quoted strings. "
                "Every finding must have at least one evidence_refs "
                "entry from the provided local evidence IDs. If you cannot cite a provided "
                "evidence ID for a claim, put that claim in unsupported_claims instead of "
                "findings. Allowed evidence_refs values are exactly: "
                f"{allowed_ids}. Do not use file names, paths, source_run_id values, "
                "or nested id/evidence_ref values from inside evidence files as "
                "evidence_refs. If the subject report cites internal metric evidence "
                "edge IDs, treat those subject citations as valid when the IDs appear "
                "inside a provided evidence-map artifact; this rule does not change "
                "the outer evidence_refs IDs required in your JSON. Use verdict `pass` "
                "when unsupported_claims is empty and all findings are informational. "
                "Use `needs_revision` only when there is at least one unsupported claim, "
                "missing caveat, warning finding, blocking finding, or concrete revision "
                "action. next_steps must contain at least one non-empty string; if the "
                "verdict is pass, use a maintenance step such as keeping the evidence "
                "bundle attached.\n\n"
                f"SUBJECT path={subject_path.as_posix()}\n{subject_text}\n\n"
                f"LOCAL EVIDENCE\n{evidence_block}"
            ),
        },
    ]


def _review_repair_messages(
    *,
    previous_response: str,
    issues: list[str],
    evidence: list[LLMEvidenceArtifact],
) -> list[dict[str, str]]:
    issue_text = "; ".join(issues[:10])
    allowed_ids = ", ".join(artifact.evidence_id for artifact in evidence)
    return [
        {
            "role": "system",
            "content": (
                "You are repairing a failed AI-Researcher local-evidence review response. "
                "Return only one syntactically valid JSON object. Do not include markdown "
                "fences, comments, URLs, quoted JSON arrays, or new uncited claims. "
                "Agent profile context is process metadata only; it cannot prove scientific "
                "results, publication readiness, or tool invocation."
            ),
        },
        {
            "role": "user",
            "content": (
                "The previous review response failed deterministic local quality checks. "
                f"Failed checks and parser errors: {issue_text}. "
                "Return a corrected object with exactly these keys and value types: "
                '{"verdict":"pass|needs_revision|fail","summary":"...",'
                '"findings":[{"severity":"info|warning|blocking","claim":"...",'
                '"evidence_refs":["evidence_1"]}],"unsupported_claims":["..."],'
                '"next_steps":["..."]}. '
                "All array fields must be real JSON arrays, not quoted strings. "
                f"Allowed evidence_refs values are exactly: {allowed_ids}. "
                "Do not cite file paths, URLs, paper titles, source_run_id values, or "
                "nested evidence ids. Do not add findings that were not in the previous "
                "response. If a previous finding lacks an allowed evidence ref, move its "
                "claim into unsupported_claims instead of guessing a ref. next_steps must "
                "contain at least one non-empty string. Use verdict `pass` when "
                "unsupported_claims is empty and all findings are informational; use "
                "`needs_revision` only for a concrete revision item.\n\n"
                f"Previous invalid response:\n{previous_response[:3000]}"
            ),
        },
    ]


def _extract_message_content(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMClientError("LLM API response did not include choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise LLMClientError("LLM API first choice is not an object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise LLMClientError("LLM API first choice did not include a message object")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise LLMClientError(
            "LLM API message content is empty; if you manually set --max-tokens, "
            "remove it or raise the provider-specific value",
            response_text=content if isinstance(content, str) else None,
            response_usage=(
                response.get("usage", {}) if isinstance(response.get("usage"), dict) else {}
            ),
            finish_reason=_response_finish_reason(response),
        )
    return content.strip()


def _response_finish_reason(response: dict[str, Any]) -> str | None:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    finish_reason = first.get("finish_reason")
    return finish_reason if isinstance(finish_reason, str) else None


def _finding_evidence_refs(findings: Any) -> list[list[str]]:
    if not isinstance(findings, list):
        return []
    refs_by_finding: list[list[str]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            refs_by_finding.append([])
            continue
        refs = finding.get("evidence_refs")
        if not isinstance(refs, list):
            refs_by_finding.append([])
            continue
        refs_by_finding.append([ref for ref in refs if isinstance(ref, str) and ref.strip()])
    return refs_by_finding


def _review_misuses_profile_context(findings: Any) -> bool:
    if not isinstance(findings, list):
        return False
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        claim = finding.get("claim")
        if isinstance(claim, str) and _misuses_profile_context_as_evidence(claim):
            return True
    return False


def _misuses_profile_context_as_evidence(text: str) -> bool:
    lower = text.lower()
    if any(term in lower for term in PROFILE_CONTEXT_NEGATION_TERMS):
        return False
    return (
        any(term in lower for term in PROFILE_CONTEXT_TERMS)
        and any(term in lower for term in PROFILE_PROOF_TERMS)
        and any(term in lower for term in PROFILE_SCIENTIFIC_CLAIM_TERMS)
    )


def _chat_completions_endpoint(base_url: str) -> str:
    return _credential_free_endpoint(base_url.rstrip("/")).rstrip("/") + "/chat/completions"


def _strip_json_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped


def _parse_json_completion_content(
    text: str,
) -> tuple[
    object,
    Literal[
        "none",
        "discarded_trailing_closing_delimiters",
        "discarded_leading_self_revision",
    ],
    str | None,
]:
    """Parse JSON with narrow, auditable provider transport normalizations."""

    stripped = _strip_json_fences(text)
    try:
        return json.loads(stripped), "none", None
    except json.JSONDecodeError as exc:
        if exc.msg != "Extra data":
            raise
    decoder = json.JSONDecoder()
    parsed, end = decoder.raw_decode(stripped)
    suffix = stripped[end:]
    delimiters = suffix.strip()
    if 1 <= len(suffix) <= 4 and delimiters and set(delimiters) <= {"]", "}"}:
        return parsed, "discarded_trailing_closing_delimiters", suffix
    if not isinstance(parsed, dict):
        raise json.JSONDecodeError("Extra data", stripped, end)
    final_candidate: tuple[dict[str, Any], int] | None = None
    for position in range(end, len(stripped)):
        if stripped[position] != "{":
            continue
        try:
            candidate, candidate_end = decoder.raw_decode(stripped, position)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(candidate, dict)
            and not stripped[candidate_end:].strip()
            and set(candidate) == set(parsed)
        ):
            final_candidate = (candidate, position)
    if final_candidate is None:
        raise json.JSONDecodeError("Extra data", stripped, end)
    candidate, position = final_candidate
    stripped_offset = text.find(stripped)
    if stripped_offset < 0:
        raise json.JSONDecodeError("Extra data", stripped, end)
    discarded_prefix = text[: stripped_offset + position]
    if not 1 <= len(discarded_prefix) <= 200_000:
        raise json.JSONDecodeError("Extra data", stripped, end)
    return candidate, "discarded_leading_self_revision", discarded_prefix


def _has_no_secret_leak(text: str, secret_values: list[str]) -> bool:
    if re.search(r"sk-[A-Za-z0-9_-]{12,}", text):
        return False
    return all(secret not in text for secret in secret_values if secret)


def _short_text(value: Any) -> bool:
    return isinstance(value, str) and 20 <= len(value.strip()) <= 800


def _mentions_evidence_policy(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    lower = value.lower()
    return any(
        phrase in lower
        for phrase in (
            "evidence",
            "source",
            "verified",
            "verification",
            "fact-check",
            "fact checking",
            "factcheck",
            "pending",
            "unknown",
        )
    )


def _string_list_has_items(value: Any, *, minimum: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= minimum
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def _redact_api_key(
    text: str,
    *,
    secret_values: list[str] | None = None,
) -> str:
    redacted = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "sk-***", text)
    for secret in secret_values or []:
        if secret:
            redacted = redacted.replace(secret, "***")
    return redacted
