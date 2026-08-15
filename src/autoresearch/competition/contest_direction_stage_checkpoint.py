"""Durable stage and provider-response checkpoints for the direction loop.

The lightweight contest direction loop deliberately does not adopt the full
campaign state machine.  It still needs one property from that runtime: after a
provider response has been received, a process crash must not turn resume into a
second paid request.  This module supplies that narrow property with write-once,
hash-bound response escrows and completed-stage receipts.

The escrow wraps an existing completion callable.  It persists the exact
``LLMJsonCompletionResult`` before returning it to the scientific stage.  A
subsequent invocation with the same stage/input/request hashes returns that exact
completion locally.  It does not reinterpret, summarize, or edit model content.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.kernel import SensitiveContentError, validate_persistable_content
from autoresearch.literature.clients import (
    OPENALEX_SELECT_FIELDS,
    OPENALEX_TITLE_ABSTRACT_FILTER_PREFIX,
    SEMANTIC_SCHOLAR_SEARCH_FIELDS,
    ArxivClient,
    OpenAlexClient,
    SemanticScholarClient,
    SourceHTTPAttemptEvent,
    bind_source_http_attempt_observer,
    source_http_attempt_tracing_supported,
)
from autoresearch.literature.models import AcademicPaper
from autoresearch.literature.privacy import (
    ScholarlyMetadataPrivacyError,
    ScholarlyMetadataPrivacyReceipt,
    normalize_untrusted_scholarly_papers,
    normalize_untrusted_scholarly_text,
)
from autoresearch.llm.client import (
    LLMClientError,
    LLMHTTPTransportTrace,
    LLMJsonCompletionResult,
    LLMTransportFailureTrace,
    LLMTransportPreflight,
    TransportPreflightHook,
    _parse_json_completion_content,
)

_SAFE_STAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LITERATURE_SEARCH_CHECKPOINT_SCHEMA = "contest-direction-literature-search-checkpoint-v2"
_LEGACY_LITERATURE_SEARCH_CHECKPOINT_SCHEMA = "contest-direction-literature-search-checkpoint-v1"
_PAPER_VERIFICATION_CHECKPOINT_SCHEMA = "contest-direction-paper-verification-checkpoint-v2"
_LEGACY_PAPER_VERIFICATION_CHECKPOINT_SCHEMA = "contest-direction-paper-verification-checkpoint-v1"
_PAPER_VERIFICATION_FAILURE_SCHEMA = "contest-direction-paper-verification-failure-v1"
_SOURCE_HTTP_REGISTRATION_SCHEMA = "contest-direction-source-http-registration-v1"
_SOURCE_HTTP_RESERVATION_SCHEMA = "contest-direction-source-http-attempt-reservation-v1"
_SOURCE_HTTP_OUTCOME_SCHEMA = "contest-direction-source-http-attempt-outcome-v1"
_SOURCE_HTTP_FAILURE_TYPE = "source_http_attempt_failed"
_SOURCE_LOGICAL_FAILURE_TYPE = "source_call_failed"
_PROVIDER_RESPONSE_CHECKPOINT_SCHEMA = "contest-direction-provider-response-checkpoint-v1"
_PROVIDER_CALL_RESERVATION_SCHEMA = "contest-direction-provider-call-reservation-v1"
_PROVIDER_PARSE_FAILURE_SCHEMA = "contest-direction-provider-parse-failure-checkpoint-v1"
_PROVIDER_CALL_ATTEMPT_SCHEMA = "contest-direction-provider-call-attempt-v2"
_PROVIDER_TRANSPORT_FAILURE_SCHEMA = "contest-direction-provider-transport-failure-v1"
_PROVIDER_TERMINAL_FAILURE_SCHEMA = "contest-direction-provider-terminal-failure-v1"
_PROVIDER_CHECKPOINT_OWNER_ATTR = "_autoresearch_provider_checkpoint_owner"
_PROVIDER_RESERVATION_KEYS = frozenset(
    {
        "schema_version",
        "stage_name",
        "stage_input_hash",
        "request_hash",
        "request",
        "transport_preflight",
        "checkpoint_hash",
    }
)
_PROVIDER_PARSE_FAILURE_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "stage_name",
        "stage_input_hash",
        "request_hash",
        "request",
        "failure_type",
        "failure_message",
        "parse_diagnostic",
        "response_text",
        "response_usage",
        "finish_reason",
        "transport_trace",
        "failure_response_hash",
        "checkpoint_hash",
    }
)
_PROVIDER_CALL_ATTEMPT_KEYS = frozenset(
    {
        "schema_version",
        "stage_name",
        "stage_input_hash",
        "request_hash",
        "request",
        "attempt_index",
        "transport_preflight",
        "checkpoint_hash",
    }
)
_PROVIDER_TRANSPORT_FAILURE_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "stage_name",
        "stage_input_hash",
        "request_hash",
        "request",
        "attempt_index",
        "failure_type",
        "failure_code",
        "response_text",
        "response_usage",
        "finish_reason",
        "transport_trace",
        "transport_failure_trace",
        "failure_hash",
        "checkpoint_hash",
    }
)
_PROVIDER_TERMINAL_FAILURE_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "stage_name",
        "stage_input_hash",
        "request_hash",
        "request",
        "attempt_index",
        "failure_type",
        "failure_code",
        "response_text",
        "response_usage",
        "finish_reason",
        "transport_trace",
        "transport_failure_trace",
        "failure_hash",
        "checkpoint_hash",
    }
)
_RESEARCH_LOOP_LITERATURE_STAGE_ROOTS = (
    Path("literature/broad"),
    Path("literature/refinement"),
    Path("literature/gap-repair"),
)
_SOURCE_HTTP_CATEGORIES = frozenset({"literature_searches", "paper_status_verifications"})


class ContestDirectionStageCheckpointError(RuntimeError):
    """Raised when a saved stage/provider checkpoint cannot be trusted."""


class _DurableSourceHTTPAttemptRecorder:
    """Write one logical source operation's physical HTTP attempt trail."""

    def __init__(
        self,
        *,
        root: Path,
        category: str,
        actor: str,
        source: str,
        logical_request_hash: str,
        logical_request: Mapping[str, Any],
        operation: str,
    ) -> None:
        if category not in _SOURCE_HTTP_CATEGORIES:
            raise ContestDirectionStageCheckpointError("source HTTP category is invalid")
        expected_operation = {
            "literature_searches": "literature_search",
            "paper_status_verifications": "paper_status_verification",
        }[category]
        if operation != expected_operation:
            raise ContestDirectionStageCheckpointError(
                "source HTTP category and operation disagree"
            )
        self.category = category
        self.actor = _validated_stage(actor)
        self.source = _validated_stage(source)
        self.logical_request_hash = _validated_hash(
            logical_request_hash,
            label="source logical request",
        )
        self.logical_request = dict(logical_request)
        if canonical_model_hash(self.logical_request) != self.logical_request_hash:
            raise ContestDirectionStageCheckpointError(
                "source HTTP logical request differs from its request hash"
            )
        try:
            validate_persistable_content(self.logical_request)
        except SensitiveContentError as exc:
            raise ContestDirectionStageCheckpointError(
                "source HTTP logical request is unsafe"
            ) from exc
        self.operation = operation
        self.root = (
            _checkpoint_root(root)
            / "source-http-attempts"
            / self.category
            / self.actor
            / self.logical_request_hash
        )
        registration_path = self.root / "registration.json"
        registration_existed = registration_path.is_file()
        registration: dict[str, Any] = {
            "schema_version": _SOURCE_HTTP_REGISTRATION_SCHEMA,
            "category": self.category,
            "actor": self.actor,
            "source": self.source,
            "logical_request_hash": self.logical_request_hash,
            "logical_request": self.logical_request,
            "operation": self.operation,
            "tracing_status": "instrumented_physical_http_attempts",
        }
        registration["checkpoint_hash"] = canonical_model_hash(registration)
        _write_once_json(registration_path, registration)
        _load_source_http_registration(registration_path)
        if registration_existed:
            raise ContestDirectionStageCheckpointError(
                "source HTTP operation was already registered without a logical terminal; "
                "refusing redispatch"
            )
        self._claim_dispatch_owner()

    def _claim_dispatch_owner(self) -> None:
        owner_path = self.root / "dispatch-owner.json"
        owner: dict[str, Any] = {
            "schema_version": "contest-direction-source-http-dispatch-owner-v1",
            "category": self.category,
            "actor": self.actor,
            "source": self.source,
            "logical_request_hash": self.logical_request_hash,
            "operation": self.operation,
            "owner_nonce": uuid.uuid4().hex,
        }
        owner["checkpoint_hash"] = canonical_model_hash(owner)
        owner_path.parent.mkdir(parents=True, exist_ok=True)
        raw = (json.dumps(owner, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
            "utf-8"
        )
        try:
            descriptor = os.open(owner_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise ContestDirectionStageCheckpointError(
                "source HTTP logical operation already has a dispatch owner"
            ) from exc
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            owner_path.unlink(missing_ok=True)
            raise

    def __call__(self, event: SourceHTTPAttemptEvent) -> None:
        if (
            event.source != self.source
            or event.operation != self.operation
            or event.attempt_index < 1
            or event.max_attempts < event.attempt_index
            or event.max_attempts > 100
            or not event.endpoint
            or "?" in event.endpoint
            or "#" in event.endpoint
        ):
            raise ContestDirectionStageCheckpointError(
                "source HTTP attempt event differs from its registered operation"
            )
        transport_request = {
            "source": event.source,
            "operation": event.operation,
            "method": "GET",
            "endpoint": event.endpoint,
            "public_params": dict(event.public_params),
            "excluded_credential_fields": list(event.excluded_credential_fields),
        }
        if any(
            field in event.public_params
            for field in ("api_key", "mailto", "x-api-key", "authorization")
        ):
            raise ContestDirectionStageCheckpointError(
                "source HTTP attempt exposed a credential-bearing parameter"
            )
        _validate_source_http_transport_binding(
            {
                "category": self.category,
                "actor": self.actor,
                "source": self.source,
                "operation": self.operation,
                "logical_request_hash": self.logical_request_hash,
                "logical_request": self.logical_request,
            },
            transport_request,
        )
        try:
            validate_persistable_content(transport_request)
        except SensitiveContentError as exc:
            raise ContestDirectionStageCheckpointError(
                "source HTTP attempt request metadata is unsafe"
            ) from exc
        transport_request_hash = canonical_model_hash(transport_request)
        reservation_path = self.root / f"attempt-{event.attempt_index:03d}-reservation.json"
        if event.phase == "reservation":
            if event.response_text is not None or event.error is not None:
                raise ContestDirectionStageCheckpointError(
                    "source HTTP reservation contains an outcome"
                )
            reservation: dict[str, Any] = {
                "schema_version": _SOURCE_HTTP_RESERVATION_SCHEMA,
                "category": self.category,
                "actor": self.actor,
                "source": self.source,
                "logical_request_hash": self.logical_request_hash,
                "operation": self.operation,
                "attempt_index": event.attempt_index,
                "max_attempts": event.max_attempts,
                "transport_request": transport_request,
                "transport_request_hash": transport_request_hash,
            }
            reservation["checkpoint_hash"] = canonical_model_hash(reservation)
            _write_once_json(reservation_path, reservation)
            _load_source_http_reservation(reservation_path)
            return
        reservation = _load_source_http_reservation(reservation_path)
        if (
            reservation["category"] != self.category
            or reservation["actor"] != self.actor
            or reservation["source"] != self.source
            or reservation["logical_request_hash"] != self.logical_request_hash
            or reservation["operation"] != self.operation
            or reservation["attempt_index"] != event.attempt_index
            or reservation["max_attempts"] != event.max_attempts
            or reservation["transport_request_hash"] != transport_request_hash
        ):
            raise ContestDirectionStageCheckpointError(
                "source HTTP outcome differs from its reservation"
            )
        outcome: dict[str, Any] = {
            "schema_version": _SOURCE_HTTP_OUTCOME_SCHEMA,
            "category": self.category,
            "actor": self.actor,
            "source": self.source,
            "logical_request_hash": self.logical_request_hash,
            "operation": self.operation,
            "attempt_index": event.attempt_index,
            "reservation_hash": reservation["checkpoint_hash"],
            "transport_request_hash": transport_request_hash,
            "status": event.phase,
            "response_sha256": None,
            "response_size_bytes": None,
            "error_type": None,
            "error_code": None,
        }
        if event.phase == "completed":
            if not isinstance(event.response_text, str) or event.error is not None:
                raise ContestDirectionStageCheckpointError(
                    "completed source HTTP outcome lacks response text"
                )
            response_bytes = event.response_text.encode("utf-8")
            outcome["response_sha256"] = hashlib.sha256(response_bytes).hexdigest()
            outcome["response_size_bytes"] = len(response_bytes)
        elif event.phase == "failed":
            if event.response_text is not None or event.error is None:
                raise ContestDirectionStageCheckpointError(
                    "failed source HTTP outcome lacks its transient exception"
                )
            status_code = getattr(event.error, "code", None)
            outcome["error_type"] = _SOURCE_HTTP_FAILURE_TYPE
            outcome["error_code"] = (
                f"http_{status_code}"
                if isinstance(status_code, int) and not isinstance(status_code, bool)
                else "source_http_attempt_failed"
            )
        else:
            raise ContestDirectionStageCheckpointError("source HTTP outcome phase is invalid")
        outcome["checkpoint_hash"] = canonical_model_hash(outcome)
        outcome_path = self.root / f"attempt-{event.attempt_index:03d}-outcome.json"
        try:
            validate_persistable_content(outcome)
        except SensitiveContentError as exc:
            raise ContestDirectionStageCheckpointError(
                "source HTTP outcome is unsafe before persistence"
            ) from exc
        _write_once_json(outcome_path, outcome)
        _load_source_http_outcome(outcome_path, reservation=reservation)


def _source_http_attempt_recorder(
    *,
    root: Path,
    category: str,
    actor: str,
    source: str,
    logical_request_hash: str,
    logical_request: Mapping[str, Any],
    operation: str,
    call: Callable[..., Any],
) -> _DurableSourceHTTPAttemptRecorder | None:
    if not source_http_attempt_tracing_supported(call):
        return None
    return _DurableSourceHTTPAttemptRecorder(
        root=root,
        category=category,
        actor=actor,
        source=source,
        logical_request_hash=logical_request_hash,
        logical_request=logical_request,
        operation=operation,
    )


def replayable_literature_searchers(
    *,
    root: Path | str,
    searchers: Mapping[str, Callable[..., Sequence[AcademicPaper]]],
) -> dict[str, Callable[..., list[AcademicPaper]]]:
    """Checkpoint every source/query response before returning it upstream.

    This keeps broader retrieval honest without repeating an already completed
    source request after a process crash.  A recorded source failure is replayed
    as a local error as well; resume never silently upgrades a historical failed
    request into a new network attempt.
    """

    checkpoint_root = _checkpoint_root(root) / "literature-searches"
    wrapped: dict[str, Callable[..., list[AcademicPaper]]] = {}
    for raw_source, searcher in searchers.items():
        source = _validated_stage(str(raw_source))

        def invoke(
            query: str,
            limit: int = 10,
            *,
            _source: str = source,
            _searcher: Callable[..., Sequence[AcademicPaper]] = searcher,
        ) -> list[AcademicPaper]:
            request = {"source": _source, "query": str(query), "limit": int(limit)}
            try:
                validate_persistable_content(request)
            except SensitiveContentError as exc:
                raise ContestDirectionStageCheckpointError(
                    "sensitive literature request blocked before source dispatch"
                ) from exc
            request_hash = canonical_model_hash(request)
            path = checkpoint_root / _source / f"{request_hash}.json"
            if path.is_file():
                return _load_literature_search(path, request=request)
            recorder = _source_http_attempt_recorder(
                root=Path(root),
                category="literature_searches",
                actor=_source,
                source=_source,
                logical_request_hash=request_hash,
                logical_request=request,
                operation="literature_search",
                call=_searcher,
            )
            try:
                if recorder is None:
                    source_papers = list(_searcher(query, limit=limit))
                else:
                    with bind_source_http_attempt_observer(recorder):
                        source_papers = list(_searcher(query, limit=limit))
                normalized_papers, privacy_receipt = normalize_untrusted_scholarly_papers(
                    source_papers
                )
                papers = list(normalized_papers)
            except Exception as exc:
                if isinstance(exc, ScholarlyMetadataPrivacyError):
                    safe_error = "literature source call failed"
                    privacy_receipt = exc.receipt
                else:
                    try:
                        _, privacy_receipt = normalize_untrusted_scholarly_text(
                            str(exc)[:2_000],
                            field_path="error_message",
                        )
                        safe_error = "literature source call failed"
                    except ScholarlyMetadataPrivacyError as privacy_exc:
                        safe_error = "literature source call failed"
                        privacy_receipt = privacy_exc.receipt
                payload: dict[str, Any] = {
                    "schema_version": _LITERATURE_SEARCH_CHECKPOINT_SCHEMA,
                    "request": request,
                    "request_hash": request_hash,
                    "status": "failed",
                    "papers": [],
                    "papers_hash": None,
                    "privacy_normalization": privacy_receipt.model_dump(mode="json"),
                    "error_type": _SOURCE_LOGICAL_FAILURE_TYPE,
                    "error_message": safe_error,
                }
                payload["checkpoint_hash"] = canonical_model_hash(payload)
                try:
                    validate_persistable_content(payload)
                except SensitiveContentError as privacy_exc:
                    raise ContestDirectionStageCheckpointError(
                        "literature failure checkpoint is unsafe before persistence"
                    ) from privacy_exc
                _write_once_json(path, payload)
                raise
            normalized = [paper.model_dump(mode="json") for paper in papers]
            payload = {
                "schema_version": _LITERATURE_SEARCH_CHECKPOINT_SCHEMA,
                "request": request,
                "request_hash": request_hash,
                "status": "completed",
                "papers": normalized,
                "papers_hash": canonical_model_hash({"papers": normalized}),
                "privacy_normalization": privacy_receipt.model_dump(mode="json"),
                "error_type": None,
                "error_message": None,
            }
            payload["checkpoint_hash"] = canonical_model_hash(payload)
            _write_once_json(path, payload)
            return papers

        wrapped[source] = invoke
    return wrapped


def replayable_paper_verifier(
    *,
    root: Path | str,
    verifier_name: str,
    verifier: Callable[[AcademicPaper], AcademicPaper],
) -> Callable[[AcademicPaper], AcademicPaper]:
    """Persist a bounded finalist-enrichment response before returning it."""

    name = _validated_stage(verifier_name)
    checkpoint_root = _checkpoint_root(root) / "paper-verifications" / name

    def invoke(paper: AcademicPaper) -> AcademicPaper:
        legacy_request = paper.model_dump(mode="json")
        legacy_request_hash = canonical_model_hash(legacy_request)
        legacy_path = checkpoint_root / f"{legacy_request_hash}.json"
        if legacy_path.is_file():
            return _load_paper_verification(
                legacy_path,
                verifier_name=name,
                request=legacy_request,
            )
        normalized_request, request_privacy = normalize_untrusted_scholarly_papers((paper,))
        request_paper = normalized_request[0]
        request = request_paper.model_dump(mode="json")
        request_hash = canonical_model_hash(request)
        path = checkpoint_root / f"{request_hash}.json"
        if path.is_file():
            return _load_paper_verification(
                path,
                verifier_name=name,
                request=request,
            )
        recorder = _source_http_attempt_recorder(
            root=Path(root),
            category="paper_status_verifications",
            actor=name,
            source=request_paper.source,
            logical_request_hash=request_hash,
            logical_request=request,
            operation="paper_status_verification",
            call=verifier,
        )
        try:
            if recorder is None:
                verified_paper = verifier(request_paper)
            else:
                with bind_source_http_attempt_observer(recorder):
                    verified_paper = verifier(request_paper)
        except Exception:
            failure_payload: dict[str, Any] = {
                "schema_version": _PAPER_VERIFICATION_FAILURE_SCHEMA,
                "status": "failed",
                "verifier_name": name,
                "request": request,
                "request_hash": request_hash,
                "request_privacy_normalization": request_privacy.model_dump(mode="json"),
                "verified_paper": None,
                "verified_paper_hash": None,
                "response_privacy_normalization": None,
                "error_type": _SOURCE_LOGICAL_FAILURE_TYPE,
                "error_message": "paper status verification failed",
            }
            failure_payload["checkpoint_hash"] = canonical_model_hash(failure_payload)
            try:
                validate_persistable_content(failure_payload)
            except SensitiveContentError as privacy_exc:
                raise ContestDirectionStageCheckpointError(
                    "paper verification failure is unsafe before persistence"
                ) from privacy_exc
            _write_once_json(path, failure_payload)
            raise
        normalized_verified, response_privacy = normalize_untrusted_scholarly_papers(
            (verified_paper,)
        )
        verified_paper = normalized_verified[0]
        verified_payload = verified_paper.model_dump(mode="json")
        checkpoint_payload: dict[str, Any] = {
            "schema_version": _PAPER_VERIFICATION_CHECKPOINT_SCHEMA,
            "verifier_name": name,
            "request": request,
            "request_hash": request_hash,
            "request_privacy_normalization": request_privacy.model_dump(mode="json"),
            "verified_paper": verified_payload,
            "verified_paper_hash": canonical_model_hash(verified_payload),
            "response_privacy_normalization": response_privacy.model_dump(mode="json"),
        }
        checkpoint_payload["checkpoint_hash"] = canonical_model_hash(checkpoint_payload)
        _write_once_json(path, checkpoint_payload)
        return verified_paper

    return invoke


def replayable_stage_completion(
    *,
    root: Path | str,
    stage_name: str,
    stage_input_hash: str,
    completion: Callable[..., LLMJsonCompletionResult],
) -> Callable[..., LLMJsonCompletionResult]:
    """Return a completion callable that writes before handing a response back.

    Multiple calls in one stage (including the three parallel hypothesis calls)
    are keyed by the complete, credential-free request contract.  Configuration
    and environment paths are represented only as paths; API-key bytes are never
    read or retained here.
    """

    stage = _validated_stage(stage_name)
    input_hash = _validated_hash(stage_input_hash, label="stage input")
    if bool(getattr(completion, _PROVIDER_CHECKPOINT_OWNER_ATTR, False)):
        return completion
    checkpoint_root = _checkpoint_root(root)

    def invoke(**kwargs: Any) -> LLMJsonCompletionResult:
        request_payload = _completion_request_payload(kwargs)
        try:
            _validate_string_values(request_payload)
        except SensitiveContentError as exc:
            raise ContestDirectionStageCheckpointError(
                "sensitive provider request blocked before provider dispatch"
            ) from exc
        request_hash = canonical_model_hash(request_payload)
        path = (
            checkpoint_root
            / "provider-responses"
            / stage
            / f"{input_hash[:16]}-{request_hash}.json"
        )
        reservation_path = (
            checkpoint_root
            / "provider-call-reservations"
            / stage
            / f"{input_hash[:16]}-{request_hash}.json"
        )
        failure_paths = _provider_parse_failure_paths(
            checkpoint_root,
            stage_name=stage,
            stage_input_hash=input_hash,
            request_hash=request_hash,
        )
        terminal_paths = _provider_terminal_failure_paths(
            checkpoint_root,
            stage_name=stage,
            stage_input_hash=input_hash,
            request_hash=request_hash,
        )
        attempt_reservations = _load_provider_call_attempts(
            checkpoint_root,
            stage_name=stage,
            stage_input_hash=input_hash,
            request_hash=request_hash,
            request_payload=request_payload,
        )
        transport_failures = _load_provider_transport_failures(
            checkpoint_root,
            stage_name=stage,
            stage_input_hash=input_hash,
            request_hash=request_hash,
            request_payload=request_payload,
            attempt_reservations=attempt_reservations,
        )
        if attempt_reservations and reservation_path.is_file():
            legacy = _load_provider_call_reservation(
                reservation_path,
                stage_name=stage,
                stage_input_hash=input_hash,
                request_hash=request_hash,
                request_payload=request_payload,
            )
            if not _same_transport_preflight(legacy, attempt_reservations[1]):
                raise ContestDirectionStageCheckpointError(
                    "legacy provider reservation differs from attempt-1 reservation"
                )
        if path.is_file():
            if failure_paths or terminal_paths:
                raise ContestDirectionStageCheckpointError(
                    "provider request has conflicting completed and failed responses"
                )
            completion_result = _load_completion_escrow(
                path,
                stage_name=stage,
                stage_input_hash=input_hash,
                request_hash=request_hash,
                request_payload=request_payload,
            )
            if attempt_reservations:
                completion_request_id = (
                    completion_result.transport_trace.request_id
                    if completion_result.transport_trace is not None
                    else None
                )
                completion_attempt = (
                    next(
                        (
                            index
                            for index, reservation in attempt_reservations.items()
                            if reservation.request_id == completion_request_id
                        ),
                        None,
                    )
                    if completion_request_id is not None
                    else max(attempt_reservations)
                )
                if completion_attempt is None:
                    raise ContestDirectionStageCheckpointError(
                        "provider completion does not bind a physical attempt"
                    )
                terminal_attempts = {*transport_failures, completion_attempt}
                if completion_attempt in transport_failures:
                    raise ContestDirectionStageCheckpointError(
                        "provider completion conflicts with a transport failure"
                    )
                if terminal_attempts != set(attempt_reservations):
                    raise ContestDirectionStageCheckpointError(
                        "provider completion leaves a physical attempt outcome unknown"
                    )
            return completion_result
        if failure_paths and terminal_paths:
            raise ContestDirectionStageCheckpointError(
                "provider request has conflicting parse and terminal failure responses"
            )
        if failure_paths:
            if len(failure_paths) != 1:
                raise ContestDirectionStageCheckpointError(
                    "provider request has multiple parse-failure response escrows"
                )
            parse_attempt_index, reservation = _reservation_for_response_failure(
                failure_paths[0],
                attempt_reservations=attempt_reservations,
                legacy_reservation_path=reservation_path,
                stage_name=stage,
                stage_input_hash=input_hash,
                request_hash=request_hash,
                request_payload=request_payload,
            )
            if parse_attempt_index is not None:
                if parse_attempt_index in transport_failures:
                    raise ContestDirectionStageCheckpointError(
                        "provider parse failure conflicts with a transport failure"
                    )
                if {*transport_failures, parse_attempt_index} != set(attempt_reservations):
                    raise ContestDirectionStageCheckpointError(
                        "provider parse failure leaves a physical attempt outcome unknown"
                    )
            _replay_provider_parse_failure(
                failure_paths[0],
                stage_name=stage,
                stage_input_hash=input_hash,
                request_hash=request_hash,
                request_payload=request_payload,
                reservation=reservation,
            )
        if terminal_paths:
            if len(terminal_paths) != 1:
                raise ContestDirectionStageCheckpointError(
                    "provider request has multiple terminal failure escrows"
                )
            terminal_attempt_index, reservation = _reservation_for_response_failure(
                terminal_paths[0],
                attempt_reservations=attempt_reservations,
                legacy_reservation_path=reservation_path,
                stage_name=stage,
                stage_input_hash=input_hash,
                request_hash=request_hash,
                request_payload=request_payload,
            )
            if terminal_attempt_index is None:
                raise ContestDirectionStageCheckpointError(
                    "provider terminal failure has no physical attempt index"
                )
            if terminal_attempt_index in transport_failures:
                raise ContestDirectionStageCheckpointError(
                    "provider terminal failure conflicts with a transport failure"
                )
            if {*transport_failures, terminal_attempt_index} != set(attempt_reservations):
                raise ContestDirectionStageCheckpointError(
                    "provider terminal failure leaves a physical attempt outcome unknown"
                )
            _replay_provider_terminal_failure(
                terminal_paths[0],
                stage_name=stage,
                stage_input_hash=input_hash,
                request_hash=request_hash,
                request_payload=request_payload,
                reservation=reservation,
                expected_attempt_index=terminal_attempt_index,
            )

        if attempt_reservations:
            if 2 in attempt_reservations:
                if 1 not in transport_failures:
                    raise ContestDirectionStageCheckpointError(
                        "provider attempt-2 lacks a qualifying attempt-1 transport failure"
                    )
                if 2 in transport_failures:
                    raise transport_failures[2]
                raise ContestDirectionStageCheckpointError(
                    "provider attempt-2 was reserved but its outcome is unknown; automatic repayment is blocked"
                )
            if 1 in transport_failures:
                attempt_index = 2
            else:
                raise ContestDirectionStageCheckpointError(
                    "provider attempt-1 was reserved but its outcome is unknown; automatic repayment is blocked"
                )
        elif reservation_path.is_file():
            _load_provider_call_reservation(
                reservation_path,
                stage_name=stage,
                stage_input_hash=input_hash,
                request_hash=request_hash,
                request_payload=request_payload,
            )
            raise ContestDirectionStageCheckpointError(
                "provider call was reserved but its outcome is unknown; automatic repayment is blocked"
            )
        else:
            attempt_index = 1

        existing_preflight_hook: TransportPreflightHook | None = kwargs.get(
            "transport_preflight_hook"
        )
        if existing_preflight_hook is not None and not callable(existing_preflight_hook):
            raise ContestDirectionStageCheckpointError("transport_preflight_hook must be callable")

        while True:
            active_reservation: LLMTransportPreflight | None = None
            current_attempt_index = attempt_index

            def reserve_provider_call(
                preflight: LLMTransportPreflight,
                request_bytes: bytes,
                *,
                _attempt_index: int = current_attempt_index,
            ) -> None:
                nonlocal active_reservation
                _record_provider_call_attempt(
                    checkpoint_root,
                    stage_name=stage,
                    stage_input_hash=input_hash,
                    request_hash=request_hash,
                    request_payload=request_payload,
                    attempt_index=_attempt_index,
                    preflight=preflight,
                    request_bytes=request_bytes,
                )
                if _attempt_index == 1:
                    _record_provider_call_reservation(
                        reservation_path,
                        stage_name=stage,
                        stage_input_hash=input_hash,
                        request_hash=request_hash,
                        request_payload=request_payload,
                        preflight=preflight,
                        request_bytes=request_bytes,
                    )
                if existing_preflight_hook is not None:
                    existing_preflight_hook(preflight, request_bytes)
                active_reservation = preflight

            call_kwargs = dict(kwargs)
            if _accepts_transport_preflight_hook(completion):
                call_kwargs["transport_preflight_hook"] = reserve_provider_call
            try:
                result = completion(**call_kwargs)
                break
            except LLMClientError as exc:
                if active_reservation is not None and _is_provider_business_json_parse_failure(exc):
                    _record_provider_parse_failure(
                        checkpoint_root,
                        stage_name=stage,
                        stage_input_hash=input_hash,
                        request_hash=request_hash,
                        request_payload=request_payload,
                        reservation=active_reservation,
                        error=exc,
                    )
                elif active_reservation is not None and _is_known_nonretry_response_failure(exc):
                    _record_provider_terminal_failure(
                        checkpoint_root,
                        stage_name=stage,
                        stage_input_hash=input_hash,
                        request_hash=request_hash,
                        request_payload=request_payload,
                        attempt_index=current_attempt_index,
                        reservation=active_reservation,
                        error=exc,
                    )
                elif active_reservation is not None and _is_retryable_transport_failure(
                    exc,
                    reservation=active_reservation,
                ):
                    _record_provider_transport_failure(
                        checkpoint_root,
                        stage_name=stage,
                        stage_input_hash=input_hash,
                        request_hash=request_hash,
                        request_payload=request_payload,
                        attempt_index=current_attempt_index,
                        reservation=active_reservation,
                        error=exc,
                    )
                    if current_attempt_index == 1:
                        attempt_index = 2
                        continue
                    failure_path = _provider_transport_failure_path(
                        _provider_attempt_root(
                            checkpoint_root,
                            stage_name=stage,
                            stage_input_hash=input_hash,
                            request_hash=request_hash,
                        ),
                        current_attempt_index,
                    )
                    safe_failure = _load_provider_transport_failure(
                        failure_path,
                        stage_name=stage,
                        stage_input_hash=input_hash,
                        request_hash=request_hash,
                        request_payload=request_payload,
                        attempt_index=current_attempt_index,
                        reservation=active_reservation,
                    )
                    raise safe_failure from None
                raise
        result_payload = result.model_dump(mode="json")
        payload: dict[str, Any] = {
            "schema_version": _PROVIDER_RESPONSE_CHECKPOINT_SCHEMA,
            "stage_name": stage,
            "stage_input_hash": input_hash,
            "request_hash": request_hash,
            "request": request_payload,
            "completion": result_payload,
            "completion_hash": canonical_model_hash(result_payload),
        }
        payload["checkpoint_hash"] = canonical_model_hash(payload)
        _write_once_json(path, payload)
        return result

    setattr(invoke, _PROVIDER_CHECKPOINT_OWNER_ATTR, True)
    return invoke


def _accepts_transport_preflight_hook(completion: Callable[..., Any]) -> bool:
    try:
        parameters = inspect.signature(completion).parameters
    except (TypeError, ValueError):
        return False
    explicit = parameters.get("transport_preflight_hook")
    if explicit is not None and explicit.kind in {
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    }:
        return True
    return any(item.kind == inspect.Parameter.VAR_KEYWORD for item in parameters.values())


def record_completed_stage(
    *,
    root: Path | str,
    ordinal: int,
    stage_name: str,
    stage_input_hash: str,
    artifacts: Sequence[Path | str],
) -> dict[str, Any]:
    """Write or revalidate one immutable completed-stage receipt."""

    if ordinal < 1:
        raise ContestDirectionStageCheckpointError("stage ordinal must be positive")
    run_root = Path(root).expanduser().resolve()
    stage = _validated_stage(stage_name)
    input_hash = _validated_hash(stage_input_hash, label="stage input")
    bindings = tuple(_file_binding(run_root, value) for value in artifacts)
    if not bindings:
        raise ContestDirectionStageCheckpointError("completed stage must bind an artifact")
    payload: dict[str, Any] = {
        "schema_version": "contest-direction-stage-checkpoint-v1",
        "ordinal": ordinal,
        "stage_name": stage,
        "stage_input_hash": input_hash,
        "artifacts": list(bindings),
    }
    payload["checkpoint_hash"] = canonical_model_hash(payload)
    path = _checkpoint_root(run_root) / "completed-stages" / f"{ordinal:02d}-{stage}.json"
    if path.is_file():
        existing = _read_json(path)
        if existing != payload:
            raise ContestDirectionStageCheckpointError(
                f"completed stage checkpoint differs from existing bytes: {stage}"
            )
    else:
        _write_once_json(path, payload)
    return payload


def load_completed_stage(
    *,
    root: Path | str,
    ordinal: int,
    stage_name: str,
    stage_input_hash: str,
) -> dict[str, Any] | None:
    """Load a receipt and re-hash every bound artifact, or return ``None``."""

    run_root = Path(root).expanduser().resolve()
    stage = _validated_stage(stage_name)
    input_hash = _validated_hash(stage_input_hash, label="stage input")
    path = _checkpoint_root(run_root) / "completed-stages" / f"{ordinal:02d}-{stage}.json"
    if not path.exists():
        return None
    payload = _read_json(path)
    expected_hash = canonical_model_hash(
        {key: value for key, value in payload.items() if key != "checkpoint_hash"}
    )
    if (
        payload.get("schema_version") != "contest-direction-stage-checkpoint-v1"
        or payload.get("ordinal") != ordinal
        or payload.get("stage_name") != stage
        or payload.get("stage_input_hash") != input_hash
        or payload.get("checkpoint_hash") != expected_hash
    ):
        raise ContestDirectionStageCheckpointError(
            f"completed stage checkpoint identity/hash mismatch: {stage}"
        )
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ContestDirectionStageCheckpointError(
            f"completed stage checkpoint has no artifacts: {stage}"
        )
    for binding in artifacts:
        if not isinstance(binding, Mapping):
            raise ContestDirectionStageCheckpointError(
                f"completed stage artifact binding is invalid: {stage}"
            )
        _verify_file_binding(run_root, binding)
    return payload


def provider_checkpoint_count(root: Path | str, *, stage_name: str) -> int:
    """Count completed v1 response escrows for one stage."""

    return provider_checkpoint_accounting(root, stage_name=stage_name)["completed_count"]


def provider_checkpoint_accounting(root: Path | str, *, stage_name: str) -> dict[str, int]:
    """Count physical provider attempts and classify every durable outcome."""

    stage = _validated_stage(stage_name)
    checkpoint_root = _checkpoint_root(root)
    completed: dict[tuple[str, str], dict[str, Any]] = {}
    completed_request_ids: dict[tuple[str, str], str | None] = {}
    completed_root = checkpoint_root / "provider-responses" / stage
    for checkpoint in sorted(completed_root.glob("*.json")):
        if checkpoint.is_symlink() or not checkpoint.is_file():
            raise ContestDirectionStageCheckpointError(
                f"provider response checkpoint path is invalid: {checkpoint}"
            )
        payload = _read_json(checkpoint)
        stage_input_hash, request_hash, request = _provider_artifact_identity(
            payload,
            path=checkpoint,
            stage_name=stage,
        )
        if checkpoint.name != f"{stage_input_hash[:16]}-{request_hash}.json":
            raise ContestDirectionStageCheckpointError(
                f"provider response checkpoint path identity mismatch: {checkpoint}"
            )
        completion = _load_completion_escrow(
            checkpoint,
            stage_name=stage,
            stage_input_hash=stage_input_hash,
            request_hash=request_hash,
            request_payload=request,
        )
        identity = (stage_input_hash, request_hash)
        if identity in completed:
            raise ContestDirectionStageCheckpointError(
                "provider completed-response identity is duplicated"
            )
        completed[identity] = request
        completed_request_ids[identity] = (
            completion.transport_trace.request_id
            if completion.transport_trace is not None
            else None
        )

    reservations: dict[tuple[str, str], tuple[dict[str, Any], LLMTransportPreflight]] = {}
    reservation_root = checkpoint_root / "provider-call-reservations" / stage
    for reservation_path in sorted(reservation_root.glob("*.json")):
        if reservation_path.is_symlink() or not reservation_path.is_file():
            raise ContestDirectionStageCheckpointError(
                f"provider call reservation path is invalid: {reservation_path}"
            )
        payload = _read_json(reservation_path)
        stage_input_hash, request_hash, request = _provider_artifact_identity(
            payload,
            path=reservation_path,
            stage_name=stage,
        )
        preflight = _load_provider_call_reservation(
            reservation_path,
            stage_name=stage,
            stage_input_hash=stage_input_hash,
            request_hash=request_hash,
            request_payload=request,
        )
        identity = (stage_input_hash, request_hash)
        if identity in reservations:
            raise ContestDirectionStageCheckpointError(
                "provider call reservation identity is duplicated"
            )
        reservations[identity] = (request, preflight)

    attempts: dict[tuple[str, str], dict[int, LLMTransportPreflight]] = {}
    transport_failed: dict[tuple[tuple[str, str], int], LLMClientError] = {}
    attempts_root = checkpoint_root / "provider-call-attempts" / stage
    for attempt_directory in sorted(attempts_root.glob("*")):
        if attempt_directory.is_symlink() or not attempt_directory.is_dir():
            raise ContestDirectionStageCheckpointError(
                f"provider attempt directory is invalid: {attempt_directory}"
            )
        first_path = _provider_attempt_reservation_path(attempt_directory, 1)
        if not first_path.is_file():
            raise ContestDirectionStageCheckpointError(
                f"provider attempt directory has no attempt-1 reservation: {attempt_directory}"
            )
        first_payload = _read_json(first_path)
        stage_input_hash, request_hash, request = _provider_artifact_identity(
            first_payload,
            path=first_path,
            stage_name=stage,
        )
        if attempt_directory.name != f"{stage_input_hash[:16]}-{request_hash}":
            raise ContestDirectionStageCheckpointError(
                f"provider attempt directory identity mismatch: {attempt_directory}"
            )
        identity = (stage_input_hash, request_hash)
        if identity in attempts:
            raise ContestDirectionStageCheckpointError(
                "provider physical-attempt identity is duplicated"
            )
        physical = _load_provider_call_attempts(
            checkpoint_root,
            stage_name=stage,
            stage_input_hash=stage_input_hash,
            request_hash=request_hash,
            request_payload=request,
        )
        failures = _load_provider_transport_failures(
            checkpoint_root,
            stage_name=stage,
            stage_input_hash=stage_input_hash,
            request_hash=request_hash,
            request_payload=request,
            attempt_reservations=physical,
        )
        if 2 in physical and 1 not in failures:
            raise ContestDirectionStageCheckpointError(
                "provider attempt-2 lacks a qualifying attempt-1 transport failure"
            )
        attempts[identity] = physical
        for attempt_index, error in failures.items():
            transport_failed[(identity, attempt_index)] = error
        legacy_item = reservations.get(identity)
        if legacy_item is not None and (
            legacy_item[0] != request or not _same_transport_preflight(legacy_item[1], physical[1])
        ):
            raise ContestDirectionStageCheckpointError(
                "legacy reservation differs from physical attempt-1"
            )

    parse_failed: dict[tuple[str, str], dict[str, Any]] = {}
    parse_failed_request_ids: dict[tuple[str, str], str] = {}
    failure_root = checkpoint_root / "provider-response-failures" / stage
    for failure_path in sorted(failure_root.glob("*.json")):
        if failure_path.is_symlink() or not failure_path.is_file():
            raise ContestDirectionStageCheckpointError(
                f"provider parse-failure checkpoint path is invalid: {failure_path}"
            )
        payload = _read_json(failure_path)
        stage_input_hash, request_hash, request = _provider_artifact_identity(
            payload,
            path=failure_path,
            stage_name=stage,
        )
        identity = (stage_input_hash, request_hash)
        if identity in parse_failed:
            raise ContestDirectionStageCheckpointError(
                "provider parse-failure response identity is duplicated"
            )
        _, reservation = _reservation_for_response_failure(
            failure_path,
            attempt_reservations=attempts.get(identity, {}),
            legacy_reservation_path=(
                checkpoint_root
                / "provider-call-reservations"
                / stage
                / f"{stage_input_hash[:16]}-{request_hash}.json"
            ),
            stage_name=stage,
            stage_input_hash=stage_input_hash,
            request_hash=request_hash,
            request_payload=request,
        )
        try:
            _replay_provider_parse_failure(
                failure_path,
                stage_name=stage,
                stage_input_hash=stage_input_hash,
                request_hash=request_hash,
                request_payload=request,
                reservation=reservation,
            )
        except LLMClientError as error:
            if error.transport_trace is None:
                raise ContestDirectionStageCheckpointError(
                    "provider parse-failure replay lost its transport trace"
                ) from error
            parse_failed_request_ids[identity] = error.transport_trace.request_id
        parse_failed[identity] = request

    terminal_failed: dict[tuple[str, str], tuple[dict[str, Any], int, str]] = {}
    terminal_root = checkpoint_root / "provider-terminal-failures" / stage
    for terminal_path in sorted(terminal_root.glob("*.json")):
        if terminal_path.is_symlink() or not terminal_path.is_file():
            raise ContestDirectionStageCheckpointError(
                f"provider terminal-failure checkpoint path is invalid: {terminal_path}"
            )
        payload = _read_json(terminal_path)
        stage_input_hash, request_hash, request = _provider_artifact_identity(
            payload,
            path=terminal_path,
            stage_name=stage,
        )
        identity = (stage_input_hash, request_hash)
        if identity in terminal_failed:
            raise ContestDirectionStageCheckpointError(
                "provider terminal-failure identity is duplicated"
            )
        terminal_attempt_index, reservation = _reservation_for_response_failure(
            terminal_path,
            attempt_reservations=attempts.get(identity, {}),
            legacy_reservation_path=(
                checkpoint_root
                / "provider-call-reservations"
                / stage
                / f"{stage_input_hash[:16]}-{request_hash}.json"
            ),
            stage_name=stage,
            stage_input_hash=stage_input_hash,
            request_hash=request_hash,
            request_payload=request,
        )
        try:
            _replay_provider_terminal_failure(
                terminal_path,
                stage_name=stage,
                stage_input_hash=stage_input_hash,
                request_hash=request_hash,
                request_payload=request,
                reservation=reservation,
                expected_attempt_index=terminal_attempt_index,
            )
        except LLMClientError as error:
            trace = error.transport_trace or error.transport_failure_trace
            if trace is None:
                raise ContestDirectionStageCheckpointError(
                    "provider terminal-failure replay lost its transport trace"
                ) from error
            terminal_attempt_index = payload.get("attempt_index")
            if not isinstance(terminal_attempt_index, int) or terminal_attempt_index not in {
                1,
                2,
            }:
                raise ContestDirectionStageCheckpointError(
                    "provider terminal-failure attempt index is invalid"
                ) from error
            terminal_failed[identity] = (
                request,
                terminal_attempt_index,
                trace.request_id,
            )

    terminal_kinds = (completed.keys(), parse_failed.keys(), terminal_failed.keys())
    overlap = (
        (terminal_kinds[0] & terminal_kinds[1])
        | (terminal_kinds[0] & terminal_kinds[2])
        | (terminal_kinds[1] & terminal_kinds[2])
    )
    if overlap:
        raise ContestDirectionStageCheckpointError(
            "provider request has conflicting terminal outcomes"
        )
    identities = (
        completed.keys()
        | reservations.keys()
        | attempts.keys()
        | parse_failed.keys()
        | terminal_failed.keys()
    )
    attempt_count = 0
    outcome_unknown_count = 0
    for identity in identities:
        identity_attempts = attempts.get(identity)
        if not identity_attempts:
            attempt_count += 1
            if (
                identity in reservations
                and identity not in completed
                and identity not in parse_failed
                and identity not in terminal_failed
            ):
                outcome_unknown_count += 1
            continue
        attempt_count += len(identity_attempts)
        terminal_attempts = {
            attempt_index
            for (failure_identity, attempt_index) in transport_failed
            if failure_identity == identity
        }
        request_id_to_attempt = {
            preflight.request_id: attempt_index
            for attempt_index, preflight in identity_attempts.items()
        }
        completion_request_id = completed_request_ids.get(identity)
        if identity in completed:
            completed_attempt = (
                request_id_to_attempt.get(completion_request_id)
                if completion_request_id is not None
                else max(identity_attempts)
            )
            if completed_attempt is None:
                raise ContestDirectionStageCheckpointError(
                    "provider completion does not bind a recorded physical attempt"
                )
            if completed_attempt in terminal_attempts:
                raise ContestDirectionStageCheckpointError(
                    "provider physical attempt has conflicting transport/completed outcomes"
                )
            terminal_attempts.add(completed_attempt)
        parse_request_id = parse_failed_request_ids.get(identity)
        if parse_request_id is not None:
            parse_attempt = request_id_to_attempt.get(parse_request_id)
            if parse_attempt is None:
                raise ContestDirectionStageCheckpointError(
                    "provider parse failure does not bind a recorded physical attempt"
                )
            if parse_attempt in terminal_attempts:
                raise ContestDirectionStageCheckpointError(
                    "provider physical attempt has conflicting transport/parse outcomes"
                )
            terminal_attempts.add(parse_attempt)
        terminal_item = terminal_failed.get(identity)
        if terminal_item is not None:
            _, terminal_attempt, terminal_request_id = terminal_item
            if request_id_to_attempt.get(terminal_request_id) != terminal_attempt:
                raise ContestDirectionStageCheckpointError(
                    "provider terminal failure does not bind its physical attempt"
                )
            if terminal_attempt in terminal_attempts:
                raise ContestDirectionStageCheckpointError(
                    "provider physical attempt has conflicting failure outcomes"
                )
            terminal_attempts.add(terminal_attempt)
        if not terminal_attempts.issubset(identity_attempts):
            raise ContestDirectionStageCheckpointError(
                "provider terminal accounting references an absent physical attempt"
            )
        outcome_unknown_count += len(identity_attempts) - len(terminal_attempts)
    return {
        "attempt_count": attempt_count,
        "completed_count": len(completed),
        "parse_failed_count": len(parse_failed),
        "transport_failed_count": len(transport_failed),
        "terminal_failed_count": len(terminal_failed),
        "outcome_unknown_count": outcome_unknown_count,
    }


def _provider_artifact_identity(
    payload: Mapping[str, Any],
    *,
    path: Path,
    stage_name: str,
) -> tuple[str, str, dict[str, Any]]:
    stage_input_hash = payload.get("stage_input_hash")
    request_hash = payload.get("request_hash")
    request = payload.get("request")
    if (
        payload.get("stage_name") != stage_name
        or not isinstance(stage_input_hash, str)
        or not _SHA256.fullmatch(stage_input_hash)
        or not isinstance(request_hash, str)
        or not _SHA256.fullmatch(request_hash)
        or not isinstance(request, Mapping)
        or canonical_model_hash(dict(request)) != request_hash
    ):
        raise ContestDirectionStageCheckpointError(
            f"provider checkpoint identity/request hash mismatch: {path}"
        )
    return stage_input_hash, request_hash, dict(request)


def literature_search_checkpoint_accounting(root: Path | str) -> dict[str, Any]:
    """Revalidate and count every durable literature source request.

    The result is an all-attempt denominator: completed and failed source
    requests both count.  No count is returned unless every discovered JSON
    checkpoint has a valid path identity, request hash, payload hash, status,
    and (for completed requests) valid ``AcademicPaper`` payloads.
    """

    stage_root = Path(root).expanduser().resolve()
    checkpoint_root = _checkpoint_root(stage_root) / "literature-searches"
    if not checkpoint_root.exists():
        return {
            "request_count": 0,
            "completed_count": 0,
            "failed_count": 0,
            "by_source": {},
        }
    if not checkpoint_root.is_dir():
        raise ContestDirectionStageCheckpointError(
            "literature search checkpoint root is not a directory"
        )
    resolved_checkpoint_root = checkpoint_root.resolve()
    try:
        resolved_checkpoint_root.relative_to(stage_root)
    except ValueError as exc:
        raise ContestDirectionStageCheckpointError(
            "literature search checkpoint root escapes its stage root"
        ) from exc
    by_source: dict[str, dict[str, int]] = {}
    for path in sorted(checkpoint_root.rglob("*.json")):
        if path.is_symlink():
            raise ContestDirectionStageCheckpointError(
                f"literature search checkpoint cannot be a symlink: {path}"
            )
        resolved_path = path.resolve()
        try:
            relative = resolved_path.relative_to(resolved_checkpoint_root)
        except ValueError as exc:
            raise ContestDirectionStageCheckpointError(
                f"literature search checkpoint path escapes its root: {path}"
            ) from exc
        if len(relative.parts) != 2:
            raise ContestDirectionStageCheckpointError(
                f"literature search checkpoint path is invalid: {path}"
            )
        source = _validated_stage(relative.parts[0])
        payload = _read_json(path)
        request = payload.get("request")
        papers = payload.get("papers")
        if not isinstance(request, Mapping) or not isinstance(papers, list):
            raise ContestDirectionStageCheckpointError(
                f"literature search checkpoint payload is invalid: {path}"
            )
        request_payload = dict(request)
        request_hash = canonical_model_hash(request_payload)
        expected_hash = canonical_model_hash(
            {key: value for key, value in payload.items() if key != "checkpoint_hash"}
        )
        schema_version = payload.get("schema_version")
        if (
            schema_version
            not in {
                _LEGACY_LITERATURE_SEARCH_CHECKPOINT_SCHEMA,
                _LITERATURE_SEARCH_CHECKPOINT_SCHEMA,
            }
            or request_payload.get("source") != source
            or payload.get("request_hash") != request_hash
            or path.name != f"{request_hash}.json"
            or payload.get("checkpoint_hash") != expected_hash
        ):
            raise ContestDirectionStageCheckpointError(
                f"literature search checkpoint binding/hash mismatch: {path}"
            )
        status = payload.get("status")
        if schema_version == _LITERATURE_SEARCH_CHECKPOINT_SCHEMA:
            _load_privacy_receipt(payload.get("privacy_normalization"), path=path)
            try:
                validate_persistable_content(request_payload)
            except SensitiveContentError as exc:
                raise ContestDirectionStageCheckpointError(
                    f"literature search checkpoint request is unsafe: {path}"
                ) from exc
        if status == "completed":
            if (
                payload.get("papers_hash") != canonical_model_hash({"papers": papers})
                or payload.get("error_type") is not None
                or payload.get("error_message") is not None
            ):
                raise ContestDirectionStageCheckpointError(
                    f"literature completed-search checkpoint is inconsistent: {path}"
                )
            try:
                validated_papers = tuple(AcademicPaper.model_validate(item) for item in papers)
                if schema_version == _LITERATURE_SEARCH_CHECKPOINT_SCHEMA:
                    validate_persistable_content(
                        [item.model_dump(mode="json") for item in validated_papers]
                    )
            except Exception as exc:
                raise ContestDirectionStageCheckpointError(
                    f"literature search checkpoint contains an invalid paper: {path}"
                ) from exc
        elif status == "failed":
            if (
                papers
                or not str(payload.get("error_type") or "")
                or payload.get("papers_hash") is not None
            ):
                raise ContestDirectionStageCheckpointError(
                    f"literature failed-search checkpoint is inconsistent: {path}"
                )
            if schema_version == _LITERATURE_SEARCH_CHECKPOINT_SCHEMA:
                try:
                    validate_persistable_content(payload.get("error_message"))
                except SensitiveContentError as exc:
                    raise ContestDirectionStageCheckpointError(
                        f"literature failed-search checkpoint error is unsafe: {path}"
                    ) from exc
        else:
            raise ContestDirectionStageCheckpointError(
                f"literature search checkpoint status is invalid: {path}"
            )
        counts = by_source.setdefault(
            source,
            {"request_count": 0, "completed_count": 0, "failed_count": 0},
        )
        counts["request_count"] += 1
        counts[f"{status}_count"] += 1
    ordered = {source: by_source[source] for source in sorted(by_source)}
    return {
        "request_count": sum(item["request_count"] for item in ordered.values()),
        "completed_count": sum(item["completed_count"] for item in ordered.values()),
        "failed_count": sum(item["failed_count"] for item in ordered.values()),
        "by_source": ordered,
    }


def research_loop_literature_search_checkpoint_accounting(
    root: Path | str,
) -> dict[str, Any]:
    """Aggregate every production literature-search checkpoint subtree.

    Retrieval checkpoints are scoped to the broad, targeted-refinement and
    bounded gap-repair stage roots so that each stage can replay independently.
    A batch failure receipt, however, needs their combined all-attempt
    denominator.  This function enumerates only those registered roots, rejects
    aliases or unregistered checkpoint trees, and delegates every file to the
    strict stage-local validator above before adding any count.
    """

    run_root = Path(root).expanduser().resolve()
    if run_root.exists() and not run_root.is_dir():
        raise ContestDirectionStageCheckpointError(
            "research-loop accounting root is not a directory"
        )
    literature_root = run_root / "literature"
    expected_checkpoint_roots: dict[Path, Path] = {}
    seen_stage_roots: set[Path] = set()
    for relative_stage_root in _RESEARCH_LOOP_LITERATURE_STAGE_ROOTS:
        lexical_stage_root = run_root / relative_stage_root
        if not lexical_stage_root.exists():
            continue
        resolved_stage_root = lexical_stage_root.resolve()
        try:
            resolved_stage_root.relative_to(run_root)
        except ValueError as exc:
            raise ContestDirectionStageCheckpointError(
                "registered literature stage root escapes the research loop"
            ) from exc
        if resolved_stage_root != lexical_stage_root.absolute():
            raise ContestDirectionStageCheckpointError(
                "registered literature stage root cannot be a path alias"
            )
        if resolved_stage_root in seen_stage_roots:
            raise ContestDirectionStageCheckpointError(
                "registered literature stage roots resolve to a duplicate path"
            )
        seen_stage_roots.add(resolved_stage_root)
        lexical_checkpoint_root = lexical_stage_root / "checkpoints" / "literature-searches"
        if lexical_checkpoint_root.exists():
            resolved_checkpoint_root = lexical_checkpoint_root.resolve()
            try:
                resolved_checkpoint_root.relative_to(resolved_stage_root)
            except ValueError as exc:
                raise ContestDirectionStageCheckpointError(
                    "literature search checkpoint root escapes its registered stage root"
                ) from exc
            if resolved_checkpoint_root in expected_checkpoint_roots:
                raise ContestDirectionStageCheckpointError(
                    "registered literature checkpoint roots resolve to a duplicate path"
                )
            expected_checkpoint_roots[resolved_checkpoint_root] = resolved_stage_root

    if literature_root.exists():
        if not literature_root.is_dir():
            raise ContestDirectionStageCheckpointError(
                "research-loop literature root is not a directory"
            )
        resolved_literature_root = literature_root.resolve()
        try:
            resolved_literature_root.relative_to(run_root)
        except ValueError as exc:
            raise ContestDirectionStageCheckpointError(
                "research-loop literature root escapes the research loop"
            ) from exc
        if resolved_literature_root != literature_root.absolute():
            raise ContestDirectionStageCheckpointError(
                "research-loop literature root cannot be a path alias"
            )
        for candidate in sorted(resolved_literature_root.rglob("literature-searches")):
            if candidate.parent.name != "checkpoints":
                continue
            resolved_candidate = candidate.resolve()
            try:
                resolved_candidate.relative_to(resolved_literature_root)
            except ValueError as exc:
                raise ContestDirectionStageCheckpointError(
                    "literature search checkpoint root escapes the literature root"
                ) from exc
            if resolved_candidate != candidate.absolute():
                raise ContestDirectionStageCheckpointError(
                    "literature search checkpoint root cannot be a path alias"
                )
            if resolved_candidate not in expected_checkpoint_roots:
                raise ContestDirectionStageCheckpointError(
                    f"unregistered literature search checkpoint root: {candidate}"
                )

    by_source: dict[str, dict[str, int]] = {}
    for stage_root in expected_checkpoint_roots.values():
        accounting = literature_search_checkpoint_accounting(stage_root)
        for source, counts in accounting["by_source"].items():
            aggregate = by_source.setdefault(
                source,
                {"request_count": 0, "completed_count": 0, "failed_count": 0},
            )
            for field in ("request_count", "completed_count", "failed_count"):
                aggregate[field] += counts[field]
    ordered = {source: by_source[source] for source in sorted(by_source)}
    return {
        "request_count": sum(item["request_count"] for item in ordered.values()),
        "completed_count": sum(item["completed_count"] for item in ordered.values()),
        "failed_count": sum(item["failed_count"] for item in ordered.values()),
        "by_source": ordered,
    }


def paper_verification_checkpoint_accounting(root: Path | str) -> dict[str, Any]:
    """Revalidate logical paper-status verification terminal checkpoints."""

    run_root = Path(root).expanduser().resolve()
    checkpoint_root = _checkpoint_root(run_root) / "paper-verifications"
    if not checkpoint_root.exists():
        return {
            "requested_count": 0,
            "completed_count": 0,
            "failed_count": 0,
            "by_verifier": {},
        }
    if not checkpoint_root.is_dir() or checkpoint_root.is_symlink():
        raise ContestDirectionStageCheckpointError("paper verification checkpoint root is invalid")
    resolved_root = checkpoint_root.resolve()
    by_verifier: dict[str, dict[str, int]] = {}
    for path in sorted(checkpoint_root.rglob("*.json")):
        if path.is_symlink() or not path.is_file():
            raise ContestDirectionStageCheckpointError(
                f"paper verification checkpoint path is invalid: {path}"
            )
        try:
            relative = path.resolve().relative_to(resolved_root)
        except ValueError as exc:
            raise ContestDirectionStageCheckpointError(
                f"paper verification checkpoint escapes its root: {path}"
            ) from exc
        if len(relative.parts) != 2:
            raise ContestDirectionStageCheckpointError(
                f"paper verification checkpoint path is invalid: {path}"
            )
        verifier = _validated_stage(relative.parts[0])
        status, _ = _validate_paper_verification_checkpoint(
            path,
            verifier_name=verifier,
        )
        counts = by_verifier.setdefault(
            verifier,
            {"requested_count": 0, "completed_count": 0, "failed_count": 0},
        )
        counts["requested_count"] += 1
        counts[f"{status}_count"] += 1
    ordered = {verifier: by_verifier[verifier] for verifier in sorted(by_verifier)}
    return {
        "requested_count": sum(item["requested_count"] for item in ordered.values()),
        "completed_count": sum(item["completed_count"] for item in ordered.values()),
        "failed_count": sum(item["failed_count"] for item in ordered.values()),
        "by_verifier": ordered,
    }


def research_loop_source_checkpoint_accounting(root: Path | str) -> dict[str, Any]:
    """Return separate logical and physical source-call ledgers.

    Old logical checkpoints are never reverse-engineered into physical HTTP
    counts. If any logical operation predates physical instrumentation, the
    corresponding physical totals are explicitly unavailable.
    """

    run_root = Path(root).expanduser().resolve()
    logical_searches = research_loop_literature_search_checkpoint_accounting(run_root)
    logical_status = paper_verification_checkpoint_accounting(run_root)
    search_roots = tuple(
        run_root / relative_stage_root
        for relative_stage_root in _RESEARCH_LOOP_LITERATURE_STAGE_ROOTS
    )
    _validate_registered_source_http_roots(run_root, search_roots=search_roots)
    search_logical_identities = _literature_search_logical_identities(search_roots)
    status_logical_identities = _paper_verification_logical_identities(run_root)
    physical_searches = _source_http_category_accounting(
        roots=search_roots,
        category="literature_searches",
        group_field="by_source",
        logical_identities=search_logical_identities,
    )
    physical_status = _source_http_category_accounting(
        roots=(run_root,),
        category="paper_status_verifications",
        group_field="by_verifier",
        logical_identities=status_logical_identities,
    )
    physical_status_value = (
        "verified_current_protocol"
        if physical_searches is not None and physical_status is not None
        else "legacy_unavailable"
    )
    unavailable_search: dict[str, Any] = {
        "requested_count": None,
        "completed_count": None,
        "failed_count": None,
        "outcome_unknown_count": None,
        "by_source": {},
    }
    unavailable_status: dict[str, Any] = {
        "requested_count": None,
        "completed_count": None,
        "failed_count": None,
        "outcome_unknown_count": None,
        "by_verifier": {},
    }
    return {
        "checkpoint_status": "verified_local_checkpoints",
        "logical_operation_semantics": (
            "terminal_checkpointed_source_operations_not_physical_http_attempts"
        ),
        "literature_searches": logical_searches,
        "paper_status_verifications": logical_status,
        "physical_http_attempts": {
            "schema_version": "contest-direction-source-http-attempt-accounting-v1",
            "accounting_status": physical_status_value,
            "attempt_semantics": "one_reservation_per_dispatched_http_get_attempt",
            "legacy_backfill_performed": False,
            "literature_searches": (
                physical_searches if physical_searches is not None else unavailable_search
            ),
            "paper_status_verifications": (
                physical_status if physical_status is not None else unavailable_status
            ),
        },
    }


def _validate_registered_source_http_roots(
    run_root: Path,
    *,
    search_roots: Sequence[Path],
) -> None:
    allowed: dict[Path, frozenset[str]] = {
        (_checkpoint_root(run_root) / "source-http-attempts").resolve(): frozenset(
            {"paper_status_verifications"}
        )
    }
    for stage_root in search_roots:
        source_root = (_checkpoint_root(stage_root) / "source-http-attempts").resolve()
        if source_root in allowed:
            raise ContestDirectionStageCheckpointError(
                "registered source HTTP roots resolve to a duplicate path"
            )
        allowed[source_root] = frozenset({"literature_searches"})
    if not run_root.exists():
        return
    for candidate in sorted(run_root.rglob("source-http-attempts")):
        if candidate.is_symlink() or not candidate.is_dir():
            raise ContestDirectionStageCheckpointError(
                f"source HTTP checkpoint root is invalid: {candidate}"
            )
        resolved = candidate.resolve()
        try:
            resolved.relative_to(run_root)
        except ValueError as exc:
            raise ContestDirectionStageCheckpointError(
                f"source HTTP checkpoint root escapes the research loop: {candidate}"
            ) from exc
        categories = allowed.get(resolved)
        if categories is None or resolved != candidate.absolute():
            raise ContestDirectionStageCheckpointError(
                f"unregistered source HTTP checkpoint root: {candidate}"
            )
        for entry in candidate.iterdir():
            if entry.is_symlink() or not entry.is_dir() or entry.name not in categories:
                raise ContestDirectionStageCheckpointError(
                    f"source HTTP checkpoint root contains an unregistered category: {entry}"
                )


def _source_http_category_accounting(
    *,
    roots: Sequence[Path],
    category: str,
    group_field: str,
    logical_identities: set[tuple[str, str, str]],
) -> dict[str, Any] | None:
    registrations: list[dict[str, Any]] = []
    registration_identities: set[tuple[str, str, str]] = set()
    reservation_rows: list[dict[str, Any]] = []
    outcome_rows: list[dict[str, Any]] = []
    for root in roots:
        scope = root.expanduser().resolve().as_posix()
        category_root = _checkpoint_root(root) / "source-http-attempts" / category
        if not category_root.exists():
            continue
        if not category_root.is_dir() or category_root.is_symlink():
            raise ContestDirectionStageCheckpointError(
                f"source HTTP category root is invalid: {category_root}"
            )
        for registration_path in sorted(category_root.rglob("registration.json")):
            if registration_path.is_symlink():
                raise ContestDirectionStageCheckpointError(
                    f"source HTTP registration cannot be a symlink: {registration_path}"
                )
            registration = _load_source_http_registration(registration_path)
            registrations.append(registration)
            registration_identity = (
                scope,
                str(registration["actor"]),
                str(registration["logical_request_hash"]),
            )
            if registration_identity in registration_identities:
                raise ContestDirectionStageCheckpointError(
                    "source HTTP registrations contain duplicate logical identities"
                )
            registration_identities.add(registration_identity)
            operation_root = registration_path.parent
            unexpected = tuple(
                path
                for path in operation_root.iterdir()
                if path.is_dir()
                or (
                    path.is_file()
                    and path.name not in {"registration.json", "dispatch-owner.json"}
                    and not re.fullmatch(
                        r"attempt-[0-9]{3}-(?:reservation|outcome)\.json",
                        path.name,
                    )
                )
            )
            if unexpected:
                raise ContestDirectionStageCheckpointError(
                    f"source HTTP attempt directory contains an unexpected entry: {unexpected[0]}"
                )
            _load_source_http_dispatch_owner(
                operation_root / "dispatch-owner.json",
                registration=registration,
            )
            reservations = [
                _load_source_http_reservation(path)
                for path in sorted(operation_root.glob("attempt-*-reservation.json"))
            ]
            indices = [int(item["attempt_index"]) for item in reservations]
            if indices != list(range(1, len(indices) + 1)):
                raise ContestDirectionStageCheckpointError(
                    "source HTTP physical attempt reservations are not contiguous"
                )
            if reservations:
                request_hashes = {str(item["transport_request_hash"]) for item in reservations}
                max_attempts = {int(item["max_attempts"]) for item in reservations}
                if len(request_hashes) != 1 or len(max_attempts) != 1:
                    raise ContestDirectionStageCheckpointError(
                        "source HTTP retries changed request identity or attempt limit"
                    )
            outcomes_by_attempt: dict[int, dict[str, Any]] = {}
            for path in sorted(operation_root.glob("attempt-*-outcome.json")):
                match = re.fullmatch(r"attempt-([0-9]{3})-outcome\.json", path.name)
                if match is None:
                    raise ContestDirectionStageCheckpointError(
                        f"source HTTP outcome path is invalid: {path}"
                    )
                attempt_index = int(match.group(1))
                reservation = next(
                    (item for item in reservations if item["attempt_index"] == attempt_index),
                    None,
                )
                if reservation is None:
                    raise ContestDirectionStageCheckpointError(
                        "source HTTP outcome has no reservation"
                    )
                if attempt_index in outcomes_by_attempt:
                    raise ContestDirectionStageCheckpointError(
                        "source HTTP attempt has duplicate outcomes"
                    )
                outcomes_by_attempt[attempt_index] = _load_source_http_outcome(
                    path,
                    reservation=reservation,
                )
            completed_indices = [
                index
                for index, item in outcomes_by_attempt.items()
                if item["status"] == "completed"
            ]
            if len(completed_indices) > 1 or (
                completed_indices and max(indices, default=0) > completed_indices[0]
            ):
                raise ContestDirectionStageCheckpointError(
                    "source HTTP retries continued after a completed response"
                )
            unknown_indices = set(indices).difference(outcomes_by_attempt)
            if unknown_indices and max(indices, default=0) > min(unknown_indices):
                raise ContestDirectionStageCheckpointError(
                    "source HTTP retry continued after an outcome-unknown attempt"
                )
            reservation_rows.extend(reservations)
            outcome_rows.extend(outcomes_by_attempt.values())
        for path in sorted(category_root.rglob("*.json")):
            if path.name in {"registration.json", "dispatch-owner.json"} or re.fullmatch(
                r"attempt-[0-9]{3}-(?:reservation|outcome)\.json",
                path.name,
            ):
                if not (path.parent / "registration.json").is_file():
                    raise ContestDirectionStageCheckpointError(
                        f"orphan source HTTP checkpoint has no registration: {path}"
                    )
                continue
            raise ContestDirectionStageCheckpointError(
                f"source HTTP category contains an unexpected checkpoint: {path}"
            )
    if not logical_identities.issubset(registration_identities):
        return None
    grouped: dict[str, dict[str, int]] = {}
    for registration in registrations:
        grouped.setdefault(
            str(registration["actor"]),
            {
                "requested_count": 0,
                "completed_count": 0,
                "failed_count": 0,
                "outcome_unknown_count": 0,
            },
        )
    for reservation in reservation_rows:
        grouped[str(reservation["actor"])]["requested_count"] += 1
    for outcome in outcome_rows:
        grouped[str(outcome["actor"])][f"{outcome['status']}_count"] += 1
    for item in grouped.values():
        item["outcome_unknown_count"] = (
            item["requested_count"] - item["completed_count"] - item["failed_count"]
        )
    ordered = {actor: grouped[actor] for actor in sorted(grouped)}
    return {
        "requested_count": sum(item["requested_count"] for item in ordered.values()),
        "completed_count": sum(item["completed_count"] for item in ordered.values()),
        "failed_count": sum(item["failed_count"] for item in ordered.values()),
        "outcome_unknown_count": sum(item["outcome_unknown_count"] for item in ordered.values()),
        group_field: ordered,
    }


def _literature_search_logical_identities(
    roots: Sequence[Path],
) -> set[tuple[str, str, str]]:
    identities: set[tuple[str, str, str]] = set()
    for root in roots:
        scope = root.expanduser().resolve().as_posix()
        checkpoint_root = _checkpoint_root(root) / "literature-searches"
        if not checkpoint_root.is_dir():
            continue
        literature_search_checkpoint_accounting(root)
        for path in sorted(checkpoint_root.rglob("*.json")):
            payload = _read_json(path)
            source = str(dict(payload["request"])["source"])
            request_hash = str(payload["request_hash"])
            identity = (scope, source, request_hash)
            if identity in identities:
                raise ContestDirectionStageCheckpointError(
                    "literature logical checkpoints contain a duplicate identity"
                )
            identities.add(identity)
    return identities


def _paper_verification_logical_identities(
    root: Path,
) -> set[tuple[str, str, str]]:
    scope = root.expanduser().resolve().as_posix()
    checkpoint_root = _checkpoint_root(root) / "paper-verifications"
    if not checkpoint_root.is_dir():
        return set()
    paper_verification_checkpoint_accounting(root)
    identities: set[tuple[str, str, str]] = set()
    for path in sorted(checkpoint_root.rglob("*.json")):
        payload = _read_json(path)
        identity = (scope, str(payload["verifier_name"]), str(payload["request_hash"]))
        if identity in identities:
            raise ContestDirectionStageCheckpointError(
                "paper verification checkpoints contain a duplicate identity"
            )
        identities.add(identity)
    return identities


def _validate_source_http_logical_request(
    registration: Mapping[str, Any],
) -> dict[str, Any]:
    logical_request = registration.get("logical_request")
    if not isinstance(logical_request, Mapping):
        raise ContestDirectionStageCheckpointError(
            "source HTTP registration logical request is invalid"
        )
    request = dict(logical_request)
    if canonical_model_hash(request) != registration.get("logical_request_hash"):
        raise ContestDirectionStageCheckpointError(
            "source HTTP registration logical request hash mismatch"
        )
    category = registration.get("category")
    if category == "literature_searches":
        if (
            frozenset(request) != {"source", "query", "limit"}
            or request.get("source") != registration.get("source")
            or not isinstance(request.get("query"), str)
            or not isinstance(request.get("limit"), int)
            or isinstance(request.get("limit"), bool)
        ):
            raise ContestDirectionStageCheckpointError(
                "source HTTP literature logical request is inconsistent"
            )
    elif category == "paper_status_verifications":
        try:
            paper = AcademicPaper.model_validate(request)
        except Exception as exc:
            raise ContestDirectionStageCheckpointError(
                "source HTTP paper-status logical request is invalid"
            ) from exc
        if paper.model_dump(mode="json") != request or paper.source != registration.get("source"):
            raise ContestDirectionStageCheckpointError(
                "source HTTP paper-status logical request is inconsistent"
            )
    else:
        raise ContestDirectionStageCheckpointError(
            "source HTTP registration logical category is invalid"
        )
    try:
        validate_persistable_content(request)
    except SensitiveContentError as exc:
        raise ContestDirectionStageCheckpointError(
            "source HTTP registration logical request is unsafe"
        ) from exc
    return request


def _validate_source_http_transport_binding(
    registration: Mapping[str, Any],
    transport_request: Mapping[str, Any],
) -> None:
    logical_request = _validate_source_http_logical_request(registration)
    public_params = transport_request.get("public_params")
    excluded = transport_request.get("excluded_credential_fields")
    if not isinstance(public_params, Mapping) or not isinstance(excluded, list):
        raise ContestDirectionStageCheckpointError(
            "source HTTP transport request fields are invalid"
        )
    params = dict(public_params)
    if any(not isinstance(item, str) for item in excluded) or len(excluded) != len(set(excluded)):
        raise ContestDirectionStageCheckpointError(
            "source HTTP excluded credential fields are invalid"
        )
    category = registration.get("category")
    source = registration.get("source")
    endpoint = transport_request.get("endpoint")
    if category == "paper_status_verifications":
        if source != "arxiv" or endpoint != logical_request.get("url") or params or excluded:
            raise ContestDirectionStageCheckpointError(
                "paper-status logical request and physical transport differ"
            )
        return
    query = str(logical_request["query"])
    limit = int(logical_request["limit"])
    if source == "arxiv":
        expected_params: dict[str, str | int] = {
            "search_query": query,
            "start": 0,
            "max_results": limit,
        }
        expected_endpoint = ArxivClient.api_url
        allowed_excluded: set[str] = set()
    elif source == "semantic_scholar":
        expected_params = {
            "query": query,
            "limit": limit,
            "fields": SEMANTIC_SCHOLAR_SEARCH_FIELDS,
        }
        expected_endpoint = SemanticScholarClient.api_url
        allowed_excluded = {"headers.x-api-key"}
    elif source == "openalex":
        expected_params = {
            "per_page": min(max(limit, 1), 100),
            "select": OPENALEX_SELECT_FIELDS,
        }
        if query.startswith(OPENALEX_TITLE_ABSTRACT_FILTER_PREFIX):
            expected_params["filter"] = query
        else:
            expected_params["search"] = query[:1200]
        expected_endpoint = OpenAlexClient.api_url
        allowed_excluded = {"api_key", "mailto"}
    else:
        raise ContestDirectionStageCheckpointError(
            "source HTTP logical request uses an unsupported built-in source"
        )
    if (
        endpoint != expected_endpoint
        or params != expected_params
        or not set(excluded).issubset(allowed_excluded)
    ):
        raise ContestDirectionStageCheckpointError(
            "literature logical request and physical transport differ"
        )


def _load_source_http_registration(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    expected_hash = canonical_model_hash(
        {key: value for key, value in payload.items() if key != "checkpoint_hash"}
    )
    category = payload.get("category")
    actor = payload.get("actor")
    logical_request_hash = payload.get("logical_request_hash")
    operation = payload.get("operation")
    if (
        frozenset(payload)
        != {
            "schema_version",
            "category",
            "actor",
            "source",
            "logical_request_hash",
            "logical_request",
            "operation",
            "tracing_status",
            "checkpoint_hash",
        }
        or payload.get("schema_version") != _SOURCE_HTTP_REGISTRATION_SCHEMA
        or category not in _SOURCE_HTTP_CATEGORIES
        or not isinstance(actor, str)
        or actor != _validated_stage(actor)
        or not isinstance(payload.get("source"), str)
        or payload.get("source") != _validated_stage(str(payload.get("source")))
        or (category == "literature_searches" and payload.get("source") != actor)
        or not isinstance(logical_request_hash, str)
        or not _SHA256.fullmatch(logical_request_hash)
        or operation
        != {
            "literature_searches": "literature_search",
            "paper_status_verifications": "paper_status_verification",
        }[str(category)]
        or payload.get("tracing_status") != "instrumented_physical_http_attempts"
        or path.name != "registration.json"
        or path.parent.name != logical_request_hash
        or path.parent.parent.name != actor
        or path.parent.parent.parent.name != category
        or path.parent.parent.parent.parent.name != "source-http-attempts"
        or payload.get("checkpoint_hash") != expected_hash
    ):
        if category == "literature_searches" and payload.get("source") != actor:
            raise ContestDirectionStageCheckpointError(
                f"source HTTP literature actor/source mismatch: {path}"
            )
        raise ContestDirectionStageCheckpointError(
            f"source HTTP registration binding/hash mismatch: {path}"
        )
    try:
        validate_persistable_content(payload)
    except SensitiveContentError as exc:
        raise ContestDirectionStageCheckpointError(
            f"source HTTP registration is unsafe: {path}"
        ) from exc
    _validate_source_http_logical_request(payload)
    return payload


def _load_source_http_dispatch_owner(
    path: Path,
    *,
    registration: Mapping[str, Any],
) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ContestDirectionStageCheckpointError(
            f"source HTTP registration lacks its exclusive dispatch owner: {path}"
        )
    payload = _read_json(path)
    expected_hash = canonical_model_hash(
        {key: value for key, value in payload.items() if key != "checkpoint_hash"}
    )
    if (
        frozenset(payload)
        != {
            "schema_version",
            "category",
            "actor",
            "source",
            "logical_request_hash",
            "operation",
            "owner_nonce",
            "checkpoint_hash",
        }
        or payload.get("schema_version") != "contest-direction-source-http-dispatch-owner-v1"
        or any(
            payload.get(field) != registration.get(field)
            for field in ("category", "actor", "source", "logical_request_hash", "operation")
        )
        or not isinstance(payload.get("owner_nonce"), str)
        or re.fullmatch(r"[0-9a-f]{32}", str(payload.get("owner_nonce"))) is None
        or payload.get("checkpoint_hash") != expected_hash
    ):
        raise ContestDirectionStageCheckpointError(
            f"source HTTP dispatch owner binding/hash mismatch: {path}"
        )
    return payload


def _load_source_http_reservation(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    expected_hash = canonical_model_hash(
        {key: value for key, value in payload.items() if key != "checkpoint_hash"}
    )
    transport_request = payload.get("transport_request")
    attempt_index = payload.get("attempt_index")
    max_attempts = payload.get("max_attempts")
    logical_request_hash = payload.get("logical_request_hash")
    if (
        frozenset(payload)
        != {
            "schema_version",
            "category",
            "actor",
            "source",
            "logical_request_hash",
            "operation",
            "attempt_index",
            "max_attempts",
            "transport_request",
            "transport_request_hash",
            "checkpoint_hash",
        }
        or payload.get("schema_version") != _SOURCE_HTTP_RESERVATION_SCHEMA
        or payload.get("category") not in _SOURCE_HTTP_CATEGORIES
        or not isinstance(attempt_index, int)
        or isinstance(attempt_index, bool)
        or not isinstance(max_attempts, int)
        or isinstance(max_attempts, bool)
        or not 1 <= attempt_index <= max_attempts <= 100
        or not isinstance(logical_request_hash, str)
        or not _SHA256.fullmatch(logical_request_hash)
        or not isinstance(transport_request, Mapping)
        or frozenset(transport_request)
        != {
            "source",
            "operation",
            "method",
            "endpoint",
            "public_params",
            "excluded_credential_fields",
        }
        or transport_request.get("source") != payload.get("source")
        or transport_request.get("operation") != payload.get("operation")
        or transport_request.get("method") != "GET"
        or not isinstance(transport_request.get("endpoint"), str)
        or "?" in str(transport_request.get("endpoint"))
        or "#" in str(transport_request.get("endpoint"))
        or not isinstance(transport_request.get("public_params"), Mapping)
        or any(
            field in transport_request.get("public_params", {})
            for field in ("api_key", "mailto", "x-api-key", "authorization")
        )
        or not isinstance(transport_request.get("excluded_credential_fields"), list)
        or payload.get("transport_request_hash") != canonical_model_hash(dict(transport_request))
        or path.name != f"attempt-{attempt_index:03d}-reservation.json"
        or path.parent.name != logical_request_hash
        or path.parent.parent.name != payload.get("actor")
        or path.parent.parent.parent.name != payload.get("category")
        or payload.get("checkpoint_hash") != expected_hash
    ):
        raise ContestDirectionStageCheckpointError(
            f"source HTTP reservation binding/hash mismatch: {path}"
        )
    registration = _load_source_http_registration(path.parent / "registration.json")
    if any(
        payload.get(field) != registration.get(field)
        for field in ("category", "actor", "source", "logical_request_hash", "operation")
    ):
        raise ContestDirectionStageCheckpointError(
            f"source HTTP reservation differs from registration: {path}"
        )
    _validate_source_http_transport_binding(registration, transport_request)
    try:
        validate_persistable_content(payload)
    except SensitiveContentError as exc:
        raise ContestDirectionStageCheckpointError(
            f"source HTTP reservation is unsafe: {path}"
        ) from exc
    return payload


def _load_source_http_outcome(
    path: Path,
    *,
    reservation: Mapping[str, Any],
) -> dict[str, Any]:
    payload = _read_json(path)
    expected_hash = canonical_model_hash(
        {key: value for key, value in payload.items() if key != "checkpoint_hash"}
    )
    attempt_index = reservation.get("attempt_index")
    status = payload.get("status")
    response_sha = payload.get("response_sha256")
    response_size = payload.get("response_size_bytes")
    if (
        frozenset(payload)
        != {
            "schema_version",
            "category",
            "actor",
            "source",
            "logical_request_hash",
            "operation",
            "attempt_index",
            "reservation_hash",
            "transport_request_hash",
            "status",
            "response_sha256",
            "response_size_bytes",
            "error_type",
            "error_code",
            "checkpoint_hash",
        }
        or payload.get("schema_version") != _SOURCE_HTTP_OUTCOME_SCHEMA
        or any(
            payload.get(field) != reservation.get(field)
            for field in (
                "category",
                "actor",
                "source",
                "logical_request_hash",
                "operation",
                "attempt_index",
                "transport_request_hash",
            )
        )
        or payload.get("reservation_hash") != reservation.get("checkpoint_hash")
        or status not in {"completed", "failed"}
        or path.name != f"attempt-{attempt_index:03d}-outcome.json"
        or payload.get("checkpoint_hash") != expected_hash
    ):
        raise ContestDirectionStageCheckpointError(
            f"source HTTP outcome binding/hash mismatch: {path}"
        )
    if status == "completed":
        if (
            not isinstance(response_sha, str)
            or not _SHA256.fullmatch(response_sha)
            or not isinstance(response_size, int)
            or isinstance(response_size, bool)
            or response_size < 0
            or payload.get("error_type") is not None
            or payload.get("error_code") is not None
        ):
            raise ContestDirectionStageCheckpointError(
                f"completed source HTTP outcome is inconsistent: {path}"
            )
    elif (
        response_sha is not None
        or response_size is not None
        or payload.get("error_type") != _SOURCE_HTTP_FAILURE_TYPE
        or payload.get("error_code")
        not in {
            "source_http_attempt_failed",
            *{f"http_{code}" for code in range(100, 600)},
        }
    ):
        raise ContestDirectionStageCheckpointError(
            f"failed source HTTP outcome is inconsistent: {path}"
        )
    try:
        validate_persistable_content(payload)
    except SensitiveContentError as exc:
        raise ContestDirectionStageCheckpointError(
            f"source HTTP outcome is unsafe: {path}"
        ) from exc
    return payload


def _provider_parse_failure_paths(
    checkpoint_root: Path,
    *,
    stage_name: str,
    stage_input_hash: str,
    request_hash: str,
) -> tuple[Path, ...]:
    root = checkpoint_root / "provider-response-failures" / stage_name
    if not root.exists():
        return ()
    prefix = f"{stage_input_hash[:16]}-{request_hash}-"
    paths = tuple(sorted(root.glob(f"{prefix}*.json")))
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ContestDirectionStageCheckpointError(
                f"provider parse-failure escrow path is invalid: {path}"
            )
    return paths


def _provider_terminal_failure_paths(
    checkpoint_root: Path,
    *,
    stage_name: str,
    stage_input_hash: str,
    request_hash: str,
) -> tuple[Path, ...]:
    root = checkpoint_root / "provider-terminal-failures" / stage_name
    if not root.exists():
        return ()
    prefix = f"{stage_input_hash[:16]}-{request_hash}-attempt-"
    paths = tuple(sorted(root.glob(f"{prefix}*.json")))
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ContestDirectionStageCheckpointError(
                f"provider terminal-failure escrow path is invalid: {path}"
            )
    return paths


def _provider_attempt_root(
    checkpoint_root: Path,
    *,
    stage_name: str,
    stage_input_hash: str,
    request_hash: str,
) -> Path:
    return (
        checkpoint_root
        / "provider-call-attempts"
        / stage_name
        / f"{stage_input_hash[:16]}-{request_hash}"
    )


def _provider_attempt_reservation_path(root: Path, attempt_index: int) -> Path:
    return root / f"attempt-{attempt_index:02d}-reservation.json"


def _provider_transport_failure_path(root: Path, attempt_index: int) -> Path:
    return root / f"attempt-{attempt_index:02d}-transport-failure.json"


def _preflight_binding(preflight: LLMTransportPreflight) -> tuple[object, ...]:
    return (
        preflight.adapter_id,
        preflight.transport_scope,
        preflight.transport_implementation,
        preflight.endpoint,
        preflight.request_method,
        preflight.request_payload_sha256,
        preflight.request_payload_size_bytes,
    )


def _same_transport_preflight(
    left: LLMTransportPreflight,
    right: LLMTransportPreflight,
) -> bool:
    return left.request_id == right.request_id and _preflight_binding(left) == _preflight_binding(
        right
    )


def _record_provider_call_attempt(
    checkpoint_root: Path,
    *,
    stage_name: str,
    stage_input_hash: str,
    request_hash: str,
    request_payload: Mapping[str, Any],
    attempt_index: int,
    preflight: LLMTransportPreflight,
    request_bytes: bytes,
) -> None:
    if attempt_index not in {1, 2}:
        raise ContestDirectionStageCheckpointError("provider attempt index must be 1 or 2")
    if not isinstance(request_bytes, bytes):
        raise ContestDirectionStageCheckpointError(
            "provider attempt preflight request payload is not bytes"
        )
    try:
        validated = LLMTransportPreflight.model_validate(preflight.model_dump(mode="json"))
    except Exception as exc:
        raise ContestDirectionStageCheckpointError(
            "provider attempt transport preflight is invalid"
        ) from exc
    if (
        validated.request_payload_size_bytes != len(request_bytes)
        or validated.request_payload_sha256 != hashlib.sha256(request_bytes).hexdigest()
    ):
        raise ContestDirectionStageCheckpointError(
            "provider attempt request bytes differ from their preflight"
        )
    attempt_root = _provider_attempt_root(
        checkpoint_root,
        stage_name=stage_name,
        stage_input_hash=stage_input_hash,
        request_hash=request_hash,
    )
    if attempt_index == 2:
        first = _load_provider_call_attempt(
            _provider_attempt_reservation_path(attempt_root, 1),
            stage_name=stage_name,
            stage_input_hash=stage_input_hash,
            request_hash=request_hash,
            request_payload=request_payload,
            attempt_index=1,
        )
        first_failure_path = _provider_transport_failure_path(attempt_root, 1)
        if not first_failure_path.is_file():
            raise ContestDirectionStageCheckpointError(
                "provider attempt-2 lacks a persisted attempt-1 transport failure"
            )
        _load_provider_transport_failure(
            first_failure_path,
            stage_name=stage_name,
            stage_input_hash=stage_input_hash,
            request_hash=request_hash,
            request_payload=request_payload,
            attempt_index=1,
            reservation=first,
        )
        if first.request_id == validated.request_id:
            raise ContestDirectionStageCheckpointError("provider retry must use a new request id")
        if _preflight_binding(first) != _preflight_binding(validated):
            raise ContestDirectionStageCheckpointError(
                "provider retry request bytes or transport binding changed"
            )
    payload: dict[str, Any] = {
        "schema_version": _PROVIDER_CALL_ATTEMPT_SCHEMA,
        "stage_name": stage_name,
        "stage_input_hash": stage_input_hash,
        "request_hash": request_hash,
        "request": dict(request_payload),
        "attempt_index": attempt_index,
        "transport_preflight": validated.model_dump(mode="json"),
    }
    try:
        _validate_string_values(payload)
    except SensitiveContentError as exc:
        raise ContestDirectionStageCheckpointError(
            "sensitive provider attempt reservation blocked before provider dispatch"
        ) from exc
    payload["checkpoint_hash"] = canonical_model_hash(payload)
    _write_once_json(_provider_attempt_reservation_path(attempt_root, attempt_index), payload)


def _load_provider_call_attempt(
    path: Path,
    *,
    stage_name: str,
    stage_input_hash: str,
    request_hash: str,
    request_payload: Mapping[str, Any],
    attempt_index: int,
) -> LLMTransportPreflight:
    if path.is_symlink() or not path.is_file():
        raise ContestDirectionStageCheckpointError(
            f"provider attempt reservation is missing or invalid: {path}"
        )
    payload = _read_json(path)
    expected_hash = canonical_model_hash(
        {key: value for key, value in payload.items() if key != "checkpoint_hash"}
    )
    preflight_payload = payload.get("transport_preflight")
    if (
        frozenset(payload) != _PROVIDER_CALL_ATTEMPT_KEYS
        or payload.get("schema_version") != _PROVIDER_CALL_ATTEMPT_SCHEMA
        or payload.get("stage_name") != stage_name
        or payload.get("stage_input_hash") != stage_input_hash
        or payload.get("request_hash") != request_hash
        or payload.get("request") != dict(request_payload)
        or canonical_model_hash(dict(request_payload)) != request_hash
        or payload.get("attempt_index") != attempt_index
        or path.name != f"attempt-{attempt_index:02d}-reservation.json"
        or not isinstance(preflight_payload, Mapping)
        or payload.get("checkpoint_hash") != expected_hash
    ):
        raise ContestDirectionStageCheckpointError(
            f"provider attempt reservation binding/hash mismatch: {path}"
        )
    try:
        _validate_string_values(payload)
        return LLMTransportPreflight.model_validate(preflight_payload)
    except Exception as exc:
        raise ContestDirectionStageCheckpointError(
            f"provider attempt reservation is invalid or unsafe: {path}"
        ) from exc


def _load_provider_call_attempts(
    checkpoint_root: Path,
    *,
    stage_name: str,
    stage_input_hash: str,
    request_hash: str,
    request_payload: Mapping[str, Any],
) -> dict[int, LLMTransportPreflight]:
    root = _provider_attempt_root(
        checkpoint_root,
        stage_name=stage_name,
        stage_input_hash=stage_input_hash,
        request_hash=request_hash,
    )
    attempts: dict[int, LLMTransportPreflight] = {}
    for attempt_index in (1, 2):
        path = _provider_attempt_reservation_path(root, attempt_index)
        if path.is_file() or path.is_symlink():
            attempts[attempt_index] = _load_provider_call_attempt(
                path,
                stage_name=stage_name,
                stage_input_hash=stage_input_hash,
                request_hash=request_hash,
                request_payload=request_payload,
                attempt_index=attempt_index,
            )
    unexpected = tuple(sorted(root.glob("attempt-*-reservation.json")))
    expected = {_provider_attempt_reservation_path(root, index).resolve() for index in attempts}
    if any(path.resolve() not in expected for path in unexpected):
        raise ContestDirectionStageCheckpointError(
            f"provider attempt reservation index/path is invalid: {root}"
        )
    if 2 in attempts and 1 not in attempts:
        raise ContestDirectionStageCheckpointError("provider attempt-2 exists without attempt-1")
    if 2 in attempts:
        if attempts[1].request_id == attempts[2].request_id:
            raise ContestDirectionStageCheckpointError("provider retry reused its request id")
        if _preflight_binding(attempts[1]) != _preflight_binding(attempts[2]):
            raise ContestDirectionStageCheckpointError(
                "provider retry request bytes or transport binding differ"
            )
    return attempts


def _transport_failure_material(error: LLMClientError) -> dict[str, Any]:
    trace = error.transport_failure_trace
    return {
        "failure_code": "transport_no_http_response",
        "response_text": error.response_text,
        "response_usage": dict(error.response_usage),
        "finish_reason": error.finish_reason,
        "transport_trace": (
            error.transport_trace.model_dump(mode="json")
            if error.transport_trace is not None
            else None
        ),
        "transport_failure_trace": (trace.model_dump(mode="json") if trace is not None else None),
    }


def _validate_transport_failure_material(
    *,
    material: Mapping[str, Any],
    reservation: LLMTransportPreflight,
) -> LLMTransportFailureTrace:
    usage = material.get("response_usage")
    trace_payload = material.get("transport_failure_trace")
    if (
        material.get("failure_code") != "transport_no_http_response"
        or material.get("response_text") is not None
        or not isinstance(usage, Mapping)
        or dict(usage)
        or material.get("finish_reason") is not None
        or material.get("transport_trace") is not None
        or not isinstance(trace_payload, Mapping)
    ):
        raise ContestDirectionStageCheckpointError(
            "provider transport failure is not strictly retry-eligible"
        )
    try:
        _validate_string_values(material)
        trace = LLMTransportFailureTrace.model_validate(trace_payload)
    except Exception as exc:
        raise ContestDirectionStageCheckpointError(
            "provider transport failure is invalid or unsafe"
        ) from exc
    if (
        trace.failure_stage != "transport"
        or not trace.transport_attempted
        or trace.http_response_received
        or trace.http_status_code is not None
        or trace.raw_response_body_sha256 is not None
        or trace.raw_response_body_size_bytes is not None
        or trace.provider_response_id_sha256 is not None
        or trace.request_id != reservation.request_id
        or trace.adapter_id != reservation.adapter_id
        or trace.transport_scope != reservation.transport_scope
        or trace.transport_implementation != reservation.transport_implementation
        or trace.endpoint != reservation.endpoint
        or trace.request_method != reservation.request_method
        or trace.request_payload_sha256 != reservation.request_payload_sha256
        or trace.request_payload_size_bytes != reservation.request_payload_size_bytes
    ):
        raise ContestDirectionStageCheckpointError(
            "provider transport failure differs from its reserved attempt"
        )
    return trace


def _is_retryable_transport_failure(
    error: LLMClientError,
    *,
    reservation: LLMTransportPreflight,
) -> bool:
    try:
        _validate_transport_failure_material(
            material=_transport_failure_material(error),
            reservation=reservation,
        )
    except ContestDirectionStageCheckpointError:
        return False
    return True


def _record_provider_transport_failure(
    checkpoint_root: Path,
    *,
    stage_name: str,
    stage_input_hash: str,
    request_hash: str,
    request_payload: Mapping[str, Any],
    attempt_index: int,
    reservation: LLMTransportPreflight,
    error: LLMClientError,
) -> None:
    material = _transport_failure_material(error)
    _validate_transport_failure_material(material=material, reservation=reservation)
    failure_hash = canonical_model_hash(material)
    payload: dict[str, Any] = {
        "schema_version": _PROVIDER_TRANSPORT_FAILURE_SCHEMA,
        "status": "transport_failed",
        "stage_name": stage_name,
        "stage_input_hash": stage_input_hash,
        "request_hash": request_hash,
        "request": dict(request_payload),
        "attempt_index": attempt_index,
        "failure_type": "LLMClientError",
        **material,
        "failure_hash": failure_hash,
    }
    payload["checkpoint_hash"] = canonical_model_hash(payload)
    root = _provider_attempt_root(
        checkpoint_root,
        stage_name=stage_name,
        stage_input_hash=stage_input_hash,
        request_hash=request_hash,
    )
    _write_once_json(_provider_transport_failure_path(root, attempt_index), payload)


def _load_provider_transport_failure(
    path: Path,
    *,
    stage_name: str,
    stage_input_hash: str,
    request_hash: str,
    request_payload: Mapping[str, Any],
    attempt_index: int,
    reservation: LLMTransportPreflight,
) -> LLMClientError:
    if path.is_symlink() or not path.is_file():
        raise ContestDirectionStageCheckpointError(
            f"provider transport failure is missing or invalid: {path}"
        )
    payload = _read_json(path)
    expected_hash = canonical_model_hash(
        {key: value for key, value in payload.items() if key != "checkpoint_hash"}
    )
    material = {
        key: payload.get(key)
        for key in (
            "failure_code",
            "response_text",
            "response_usage",
            "finish_reason",
            "transport_trace",
            "transport_failure_trace",
        )
    }
    failure_hash = canonical_model_hash(material)
    if (
        frozenset(payload) != _PROVIDER_TRANSPORT_FAILURE_KEYS
        or payload.get("schema_version") != _PROVIDER_TRANSPORT_FAILURE_SCHEMA
        or payload.get("status") != "transport_failed"
        or payload.get("stage_name") != stage_name
        or payload.get("stage_input_hash") != stage_input_hash
        or payload.get("request_hash") != request_hash
        or payload.get("request") != dict(request_payload)
        or canonical_model_hash(dict(request_payload)) != request_hash
        or payload.get("attempt_index") != attempt_index
        or payload.get("failure_type") != "LLMClientError"
        or payload.get("failure_hash") != failure_hash
        or path.name != f"attempt-{attempt_index:02d}-transport-failure.json"
        or payload.get("checkpoint_hash") != expected_hash
    ):
        raise ContestDirectionStageCheckpointError(
            f"provider transport failure binding/hash mismatch: {path}"
        )
    trace = _validate_transport_failure_material(material=material, reservation=reservation)
    return LLMClientError(
        "provider transport request failed",
        transport_preflight=reservation,
        transport_failure_trace=trace,
    )


def _load_provider_transport_failures(
    checkpoint_root: Path,
    *,
    stage_name: str,
    stage_input_hash: str,
    request_hash: str,
    request_payload: Mapping[str, Any],
    attempt_reservations: Mapping[int, LLMTransportPreflight],
) -> dict[int, LLMClientError]:
    root = _provider_attempt_root(
        checkpoint_root,
        stage_name=stage_name,
        stage_input_hash=stage_input_hash,
        request_hash=request_hash,
    )
    failures: dict[int, LLMClientError] = {}
    for attempt_index in (1, 2):
        path = _provider_transport_failure_path(root, attempt_index)
        if not path.exists() and not path.is_symlink():
            continue
        reservation = attempt_reservations.get(attempt_index)
        if reservation is None:
            raise ContestDirectionStageCheckpointError(
                "provider transport failure has no matching attempt reservation"
            )
        failures[attempt_index] = _load_provider_transport_failure(
            path,
            stage_name=stage_name,
            stage_input_hash=stage_input_hash,
            request_hash=request_hash,
            request_payload=request_payload,
            attempt_index=attempt_index,
            reservation=reservation,
        )
    unexpected = tuple(sorted(root.glob("attempt-*-transport-failure.json")))
    expected = {_provider_transport_failure_path(root, index).resolve() for index in failures}
    if any(path.resolve() not in expected for path in unexpected):
        raise ContestDirectionStageCheckpointError(
            f"provider transport failure index/path is invalid: {root}"
        )
    if 2 in failures and 1 not in failures:
        raise ContestDirectionStageCheckpointError(
            "provider attempt-2 transport failure exists without attempt-1 failure"
        )
    return failures


def _reservation_for_response_failure(
    path: Path,
    *,
    attempt_reservations: Mapping[int, LLMTransportPreflight],
    legacy_reservation_path: Path,
    stage_name: str,
    stage_input_hash: str,
    request_hash: str,
    request_payload: Mapping[str, Any],
) -> tuple[int | None, LLMTransportPreflight]:
    payload = _read_json(path)
    trace_payload = payload.get("transport_trace") or payload.get("transport_failure_trace")
    request_id = trace_payload.get("request_id") if isinstance(trace_payload, Mapping) else None
    matches = [
        (attempt_index, reservation)
        for attempt_index, reservation in attempt_reservations.items()
        if reservation.request_id == request_id
    ]
    if attempt_reservations:
        if len(matches) != 1:
            raise ContestDirectionStageCheckpointError(
                "provider response failure does not bind exactly one physical attempt"
            )
        return matches[0]
    return (
        None,
        _load_provider_call_reservation(
            legacy_reservation_path,
            stage_name=stage_name,
            stage_input_hash=stage_input_hash,
            request_hash=request_hash,
            request_payload=request_payload,
        ),
    )


def _is_known_nonretry_response_failure(error: LLMClientError) -> bool:
    failure = error.transport_failure_trace
    return bool(
        error.response_text is None
        and error.transport_trace is not None
        or (
            error.response_text is None
            and failure is not None
            and failure.failure_stage == "http_response"
            and failure.http_response_received
        )
    )


def _terminal_failure_material(error: LLMClientError) -> dict[str, Any]:
    failure = error.transport_failure_trace
    return {
        "failure_code": (
            "http_status_failure"
            if failure is not None and failure.failure_stage == "http_response"
            else "http_response_decode_failure"
        ),
        "response_text": error.response_text,
        "response_usage": dict(error.response_usage),
        "finish_reason": error.finish_reason,
        "transport_trace": (
            error.transport_trace.model_dump(mode="json")
            if error.transport_trace is not None
            else None
        ),
        "transport_failure_trace": (
            error.transport_failure_trace.model_dump(mode="json")
            if error.transport_failure_trace is not None
            else None
        ),
    }


def _validate_terminal_failure_material(
    *,
    material: Mapping[str, Any],
    reservation: LLMTransportPreflight,
) -> tuple[LLMHTTPTransportTrace | None, LLMTransportFailureTrace | None]:
    usage = material.get("response_usage")
    success_trace_payload = material.get("transport_trace")
    failure_trace_payload = material.get("transport_failure_trace")
    failure_code = material.get("failure_code")
    if (
        failure_code not in {"http_status_failure", "http_response_decode_failure"}
        or material.get("response_text") is not None
        or not isinstance(usage, Mapping)
        or dict(usage)
        or material.get("finish_reason") is not None
        or (isinstance(success_trace_payload, Mapping))
        == (isinstance(failure_trace_payload, Mapping))
        or (
            isinstance(success_trace_payload, Mapping)
            and failure_code != "http_response_decode_failure"
        )
        or (isinstance(failure_trace_payload, Mapping) and failure_code != "http_status_failure")
    ):
        raise ContestDirectionStageCheckpointError(
            "provider terminal response failure fields are invalid"
        )
    try:
        _validate_string_values(material)
        success_trace = (
            LLMHTTPTransportTrace.model_validate(success_trace_payload)
            if isinstance(success_trace_payload, Mapping)
            else None
        )
        failure_trace = (
            LLMTransportFailureTrace.model_validate(failure_trace_payload)
            if isinstance(failure_trace_payload, Mapping)
            else None
        )
    except Exception as exc:
        raise ContestDirectionStageCheckpointError(
            "provider terminal response failure is invalid or unsafe"
        ) from exc
    trace = success_trace or failure_trace
    if trace is None:
        raise ContestDirectionStageCheckpointError(
            "provider terminal response failure has no transport trace"
        )
    if (
        trace.request_id != reservation.request_id
        or trace.adapter_id != reservation.adapter_id
        or trace.transport_scope != reservation.transport_scope
        or trace.transport_implementation != reservation.transport_implementation
        or trace.endpoint != reservation.endpoint
        or trace.request_method != reservation.request_method
        or trace.request_payload_sha256 != reservation.request_payload_sha256
        or trace.request_payload_size_bytes != reservation.request_payload_size_bytes
    ):
        raise ContestDirectionStageCheckpointError(
            "provider terminal response failure differs from its reservation"
        )
    if failure_trace is not None and (
        failure_trace.failure_stage != "http_response" or not failure_trace.http_response_received
    ):
        raise ContestDirectionStageCheckpointError(
            "provider terminal failure does not prove an HTTP response"
        )
    return success_trace, failure_trace


def _record_provider_terminal_failure(
    checkpoint_root: Path,
    *,
    stage_name: str,
    stage_input_hash: str,
    request_hash: str,
    request_payload: Mapping[str, Any],
    attempt_index: int,
    reservation: LLMTransportPreflight,
    error: LLMClientError,
) -> None:
    material = _terminal_failure_material(error)
    _validate_terminal_failure_material(material=material, reservation=reservation)
    failure_hash = canonical_model_hash(material)
    payload: dict[str, Any] = {
        "schema_version": _PROVIDER_TERMINAL_FAILURE_SCHEMA,
        "status": "response_failed",
        "stage_name": stage_name,
        "stage_input_hash": stage_input_hash,
        "request_hash": request_hash,
        "request": dict(request_payload),
        "attempt_index": attempt_index,
        "failure_type": "LLMClientError",
        **material,
        "failure_hash": failure_hash,
    }
    payload["checkpoint_hash"] = canonical_model_hash(payload)
    path = (
        checkpoint_root
        / "provider-terminal-failures"
        / stage_name
        / (
            f"{stage_input_hash[:16]}-{request_hash}-attempt-{attempt_index:02d}-"
            f"{failure_hash}.json"
        )
    )
    _write_once_json(path, payload)


def _replay_provider_terminal_failure(
    path: Path,
    *,
    stage_name: str,
    stage_input_hash: str,
    request_hash: str,
    request_payload: Mapping[str, Any],
    reservation: LLMTransportPreflight,
    expected_attempt_index: int | None,
) -> None:
    payload = _read_json(path)
    expected_hash = canonical_model_hash(
        {key: value for key, value in payload.items() if key != "checkpoint_hash"}
    )
    material = {
        key: payload.get(key)
        for key in (
            "failure_code",
            "response_text",
            "response_usage",
            "finish_reason",
            "transport_trace",
            "transport_failure_trace",
        )
    }
    failure_hash = canonical_model_hash(material)
    attempt_index = payload.get("attempt_index")
    if (
        frozenset(payload) != _PROVIDER_TERMINAL_FAILURE_KEYS
        or payload.get("schema_version") != _PROVIDER_TERMINAL_FAILURE_SCHEMA
        or payload.get("status") != "response_failed"
        or payload.get("stage_name") != stage_name
        or payload.get("stage_input_hash") != stage_input_hash
        or payload.get("request_hash") != request_hash
        or payload.get("request") != dict(request_payload)
        or canonical_model_hash(dict(request_payload)) != request_hash
        or attempt_index not in {1, 2}
        or attempt_index != expected_attempt_index
        or payload.get("failure_type") != "LLMClientError"
        or payload.get("failure_hash") != failure_hash
        or path.name
        != (
            f"{stage_input_hash[:16]}-{request_hash}-attempt-{attempt_index:02d}-"
            f"{failure_hash}.json"
        )
        or payload.get("checkpoint_hash") != expected_hash
    ):
        raise ContestDirectionStageCheckpointError(
            f"provider terminal failure binding/content-address mismatch: {path}"
        )
    success_trace, failure_trace = _validate_terminal_failure_material(
        material=material,
        reservation=reservation,
    )
    replay_message = (
        f"provider HTTP {failure_trace.http_status_code} response failed"
        if failure_trace is not None
        else "provider HTTP response decoding or validation failed"
    )
    raise LLMClientError(
        replay_message,
        transport_preflight=reservation,
        transport_trace=success_trace,
        transport_failure_trace=failure_trace,
    )


def _record_provider_call_reservation(
    path: Path,
    *,
    stage_name: str,
    stage_input_hash: str,
    request_hash: str,
    request_payload: Mapping[str, Any],
    preflight: LLMTransportPreflight,
    request_bytes: bytes,
) -> None:
    if not isinstance(request_bytes, bytes):
        raise ContestDirectionStageCheckpointError(
            "provider preflight request payload is not bytes"
        )
    try:
        validated_preflight = LLMTransportPreflight.model_validate(
            preflight.model_dump(mode="json")
        )
    except Exception as exc:
        raise ContestDirectionStageCheckpointError(
            "provider call reservation preflight is invalid"
        ) from exc
    if (
        validated_preflight.request_payload_size_bytes != len(request_bytes)
        or validated_preflight.request_payload_sha256 != hashlib.sha256(request_bytes).hexdigest()
    ):
        raise ContestDirectionStageCheckpointError(
            "provider call reservation request bytes differ from their preflight"
        )
    payload: dict[str, Any] = {
        "schema_version": _PROVIDER_CALL_RESERVATION_SCHEMA,
        "stage_name": stage_name,
        "stage_input_hash": stage_input_hash,
        "request_hash": request_hash,
        "request": dict(request_payload),
        "transport_preflight": validated_preflight.model_dump(mode="json"),
    }
    try:
        _validate_string_values(payload)
    except SensitiveContentError as exc:
        raise ContestDirectionStageCheckpointError(
            "sensitive provider call reservation blocked before provider dispatch"
        ) from exc
    payload["checkpoint_hash"] = canonical_model_hash(payload)
    _write_once_json(path, payload)


def _load_provider_call_reservation(
    path: Path,
    *,
    stage_name: str,
    stage_input_hash: str,
    request_hash: str,
    request_payload: Mapping[str, Any],
) -> LLMTransportPreflight:
    if path.is_symlink() or not path.is_file():
        raise ContestDirectionStageCheckpointError(
            "provider response has no trustworthy pre-call reservation"
        )
    payload = _read_json(path)
    expected_hash = canonical_model_hash(
        {key: value for key, value in payload.items() if key != "checkpoint_hash"}
    )
    preflight_payload = payload.get("transport_preflight")
    if (
        frozenset(payload) != _PROVIDER_RESERVATION_KEYS
        or payload.get("schema_version") != _PROVIDER_CALL_RESERVATION_SCHEMA
        or payload.get("stage_name") != stage_name
        or payload.get("stage_input_hash") != stage_input_hash
        or payload.get("request_hash") != request_hash
        or payload.get("request") != dict(request_payload)
        or canonical_model_hash(dict(request_payload)) != request_hash
        or path.name != f"{stage_input_hash[:16]}-{request_hash}.json"
        or not isinstance(preflight_payload, Mapping)
        or payload.get("checkpoint_hash") != expected_hash
    ):
        raise ContestDirectionStageCheckpointError(
            f"provider call reservation binding/hash mismatch: {path}"
        )
    try:
        _validate_string_values(payload)
        return LLMTransportPreflight.model_validate(preflight_payload)
    except Exception as exc:
        raise ContestDirectionStageCheckpointError(
            f"provider call reservation is invalid or unsafe: {path}"
        ) from exc


def _is_provider_business_json_parse_failure(error: LLMClientError) -> bool:
    trace = error.transport_trace
    return bool(
        trace is not None
        and 200 <= trace.http_status_code <= 299
        and trace.completion_fields_available
        and isinstance(error.response_text, str)
        and (
            str(error).startswith("LLM JSON completion was not valid JSON:")
            or str(error) == "LLM JSON completion top-level value is not an object"
        )
    )


def _parse_failure_diagnostic(
    error: LLMClientError,
    response_text: str,
) -> dict[str, Any]:
    cause = error.__cause__
    if isinstance(cause, json.JSONDecodeError):
        diagnostic = {
            "kind": "json_decode_error",
            "lineno": cause.lineno,
            "colno": cause.colno,
            "pos": cause.pos,
        }
        _revalidate_parse_diagnostic(response_text, diagnostic)
        return diagnostic
    if str(error) == "LLM JSON completion top-level value is not an object":
        diagnostic = {"kind": "top_level_non_object"}
        _revalidate_parse_diagnostic(response_text, diagnostic)
        return diagnostic
    raise ContestDirectionStageCheckpointError(
        "provider parse failure has no mechanical parser diagnostic"
    )


def _revalidate_parse_diagnostic(
    response_text: str,
    diagnostic: Mapping[str, Any],
) -> None:
    kind = diagnostic.get("kind")
    if kind == "json_decode_error":
        if frozenset(diagnostic) != {"kind", "lineno", "colno", "pos"}:
            raise ContestDirectionStageCheckpointError(
                "provider JSON parse diagnostic fields are invalid"
            )
        try:
            _parse_json_completion_content(response_text)
        except json.JSONDecodeError as exc:
            if (
                diagnostic.get("lineno") != exc.lineno
                or diagnostic.get("colno") != exc.colno
                or diagnostic.get("pos") != exc.pos
            ):
                raise ContestDirectionStageCheckpointError(
                    "provider JSON parse diagnostic differs from local replay"
                ) from exc
            return
        raise ContestDirectionStageCheckpointError(
            "provider JSON parse diagnostic no longer reproduces"
        )
    if kind == "top_level_non_object":
        if frozenset(diagnostic) != {"kind"}:
            raise ContestDirectionStageCheckpointError(
                "provider top-level parse diagnostic fields are invalid"
            )
        try:
            parsed, _, _ = _parse_json_completion_content(response_text)
        except json.JSONDecodeError as exc:
            raise ContestDirectionStageCheckpointError(
                "provider top-level parse diagnostic no longer reproduces"
            ) from exc
        if isinstance(parsed, dict):
            raise ContestDirectionStageCheckpointError(
                "provider top-level parse diagnostic now resolves to an object"
            )
        return
    raise ContestDirectionStageCheckpointError("provider parse diagnostic kind is invalid")


def _provider_failure_material(
    *,
    error_message: str,
    response_text: str,
    response_usage: Mapping[str, Any],
    finish_reason: str | None,
    transport_trace: LLMHTTPTransportTrace,
    parse_diagnostic: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "failure_message": error_message,
        "parse_diagnostic": dict(parse_diagnostic),
        "response_text": response_text,
        "response_usage": dict(response_usage),
        "finish_reason": finish_reason,
        "transport_trace": transport_trace.model_dump(mode="json"),
    }


def _validate_parse_failure_response(
    *,
    material: Mapping[str, Any],
    reservation: LLMTransportPreflight,
) -> LLMHTTPTransportTrace:
    response_text = material.get("response_text")
    response_usage = material.get("response_usage")
    finish_reason = material.get("finish_reason")
    parse_diagnostic = material.get("parse_diagnostic")
    trace_payload = material.get("transport_trace")
    if (
        not isinstance(response_text, str)
        or not isinstance(response_usage, Mapping)
        or not isinstance(parse_diagnostic, Mapping)
        or (finish_reason is not None and not isinstance(finish_reason, str))
        or not isinstance(trace_payload, Mapping)
    ):
        raise ContestDirectionStageCheckpointError(
            "provider parse-failure response fields are invalid"
        )
    try:
        _validate_string_values(material)
        trace = LLMHTTPTransportTrace.model_validate(trace_payload)
    except Exception as exc:
        raise ContestDirectionStageCheckpointError(
            "provider parse-failure response is invalid or unsafe"
        ) from exc
    reservation_fields = (
        "request_id",
        "adapter_id",
        "transport_scope",
        "transport_implementation",
        "endpoint",
        "request_method",
        "request_payload_sha256",
        "request_payload_size_bytes",
    )
    if any(getattr(trace, field) != getattr(reservation, field) for field in reservation_fields):
        raise ContestDirectionStageCheckpointError(
            "provider parse-failure transport trace differs from its reservation"
        )
    if not 200 <= trace.http_status_code <= 299 or not trace.completion_fields_available:
        raise ContestDirectionStageCheckpointError(
            "provider parse-failure escrow does not bind a completed HTTP response"
        )
    if (
        trace.visible_output_utf8_sha256
        != hashlib.sha256(response_text.encode("utf-8")).hexdigest()
    ):
        raise ContestDirectionStageCheckpointError(
            "provider parse-failure response text differs from its transport trace"
        )
    if trace.usage_canonical_json_sha256 != canonical_model_hash(dict(response_usage)):
        raise ContestDirectionStageCheckpointError(
            "provider parse-failure usage differs from its transport trace"
        )
    _revalidate_parse_diagnostic(response_text, parse_diagnostic)
    return trace


def _record_provider_parse_failure(
    checkpoint_root: Path,
    *,
    stage_name: str,
    stage_input_hash: str,
    request_hash: str,
    request_payload: Mapping[str, Any],
    reservation: LLMTransportPreflight,
    error: LLMClientError,
) -> None:
    trace = error.transport_trace
    response_text = error.response_text
    if trace is None or response_text is None:
        raise ContestDirectionStageCheckpointError(
            "provider parse failure has no completed HTTP response"
        )
    material = _provider_failure_material(
        error_message=str(error),
        response_text=response_text,
        response_usage=error.response_usage,
        finish_reason=error.finish_reason,
        transport_trace=trace,
        parse_diagnostic=_parse_failure_diagnostic(error, response_text),
    )
    _validate_parse_failure_response(material=material, reservation=reservation)
    failure_hash = canonical_model_hash(material)
    payload: dict[str, Any] = {
        "schema_version": _PROVIDER_PARSE_FAILURE_SCHEMA,
        "status": "parse_failed",
        "stage_name": stage_name,
        "stage_input_hash": stage_input_hash,
        "request_hash": request_hash,
        "request": dict(request_payload),
        "failure_type": "LLMClientError",
        **material,
        "failure_response_hash": failure_hash,
    }
    payload["checkpoint_hash"] = canonical_model_hash(payload)
    path = (
        checkpoint_root
        / "provider-response-failures"
        / stage_name
        / f"{stage_input_hash[:16]}-{request_hash}-{failure_hash}.json"
    )
    _write_once_json(path, payload)


def _replay_provider_parse_failure(
    path: Path,
    *,
    stage_name: str,
    stage_input_hash: str,
    request_hash: str,
    request_payload: Mapping[str, Any],
    reservation: LLMTransportPreflight,
) -> None:
    payload = _read_json(path)
    expected_hash = canonical_model_hash(
        {key: value for key, value in payload.items() if key != "checkpoint_hash"}
    )
    material = {
        key: payload.get(key)
        for key in (
            "failure_message",
            "parse_diagnostic",
            "response_text",
            "response_usage",
            "finish_reason",
            "transport_trace",
        )
    }
    failure_hash = canonical_model_hash(material)
    if (
        frozenset(payload) != _PROVIDER_PARSE_FAILURE_KEYS
        or payload.get("schema_version") != _PROVIDER_PARSE_FAILURE_SCHEMA
        or payload.get("status") != "parse_failed"
        or payload.get("stage_name") != stage_name
        or payload.get("stage_input_hash") != stage_input_hash
        or payload.get("request_hash") != request_hash
        or payload.get("request") != dict(request_payload)
        or canonical_model_hash(dict(request_payload)) != request_hash
        or payload.get("failure_type") != "LLMClientError"
        or payload.get("failure_response_hash") != failure_hash
        or path.name != f"{stage_input_hash[:16]}-{request_hash}-{failure_hash}.json"
        or payload.get("checkpoint_hash") != expected_hash
    ):
        raise ContestDirectionStageCheckpointError(
            f"provider parse-failure checkpoint binding/content-address mismatch: {path}"
        )
    trace = _validate_parse_failure_response(material=material, reservation=reservation)
    response_usage = material["response_usage"]
    if not isinstance(response_usage, Mapping):
        raise ContestDirectionStageCheckpointError(
            "provider parse-failure usage is invalid after validation"
        )
    raise LLMClientError(
        str(material["failure_message"]),
        response_text=str(material["response_text"]),
        response_usage=dict(response_usage),
        finish_reason=(
            str(material["finish_reason"]) if material["finish_reason"] is not None else None
        ),
        transport_trace=trace,
    )


def _load_completion_escrow(
    path: Path,
    *,
    stage_name: str,
    stage_input_hash: str,
    request_hash: str,
    request_payload: Mapping[str, Any],
) -> LLMJsonCompletionResult:
    payload = _read_json(path)
    expected_hash = canonical_model_hash(
        {key: value for key, value in payload.items() if key != "checkpoint_hash"}
    )
    completion = payload.get("completion")
    if (
        payload.get("schema_version") != "contest-direction-provider-response-checkpoint-v1"
        or payload.get("stage_name") != stage_name
        or payload.get("stage_input_hash") != stage_input_hash
        or payload.get("request_hash") != request_hash
        or payload.get("request") != dict(request_payload)
        or not isinstance(completion, Mapping)
        or payload.get("completion_hash") != canonical_model_hash(dict(completion))
        or payload.get("checkpoint_hash") != expected_hash
    ):
        raise ContestDirectionStageCheckpointError(
            f"provider response checkpoint binding/hash mismatch: {path}"
        )
    try:
        return LLMJsonCompletionResult.model_validate(completion)
    except Exception as exc:
        raise ContestDirectionStageCheckpointError(
            f"provider response checkpoint completion is invalid: {path}"
        ) from exc


def _load_paper_verification(
    path: Path,
    *,
    verifier_name: str,
    request: Mapping[str, Any],
) -> AcademicPaper:
    status, validated = _validate_paper_verification_checkpoint(
        path,
        verifier_name=verifier_name,
        request=request,
    )
    if status == "failed":
        payload = _read_json(path)
        raise ContestDirectionStageCheckpointError(
            "replayed paper verification failure "
            f"{payload.get('error_type')}: {payload.get('error_message')}"
        )
    if validated is None:
        raise ContestDirectionStageCheckpointError(
            f"paper verification checkpoint has no completed paper: {path}"
        )
    return validated


def _validate_paper_verification_checkpoint(
    path: Path,
    *,
    verifier_name: str | None = None,
    request: Mapping[str, Any] | None = None,
) -> tuple[str, AcademicPaper | None]:
    payload = _read_json(path)
    expected_hash = canonical_model_hash(
        {key: value for key, value in payload.items() if key != "checkpoint_hash"}
    )
    schema_version = payload.get("schema_version")
    actual_verifier_name = payload.get("verifier_name")
    actual_request = payload.get("request")
    if not isinstance(actual_verifier_name, str) or not isinstance(actual_request, Mapping):
        raise ContestDirectionStageCheckpointError(
            f"paper verification checkpoint identity is invalid: {path}"
        )
    request_payload = dict(actual_request)
    request_hash = canonical_model_hash(request_payload)
    if (
        (verifier_name is not None and actual_verifier_name != verifier_name)
        or (request is not None and request_payload != dict(request))
        or payload.get("request_hash") != request_hash
        or path.parent.name != actual_verifier_name
        or path.name != f"{request_hash}.json"
        or payload.get("checkpoint_hash") != expected_hash
    ):
        raise ContestDirectionStageCheckpointError(
            f"paper verification checkpoint binding/hash mismatch: {path}"
        )
    if schema_version == _PAPER_VERIFICATION_FAILURE_SCHEMA:
        if (
            frozenset(payload)
            != {
                "schema_version",
                "status",
                "verifier_name",
                "request",
                "request_hash",
                "request_privacy_normalization",
                "verified_paper",
                "verified_paper_hash",
                "response_privacy_normalization",
                "error_type",
                "error_message",
                "checkpoint_hash",
            }
            or payload.get("status") != "failed"
            or payload.get("verified_paper") is not None
            or payload.get("verified_paper_hash") is not None
            or payload.get("response_privacy_normalization") is not None
            or not isinstance(payload.get("error_type"), str)
            or payload.get("error_message") != "paper status verification failed"
        ):
            raise ContestDirectionStageCheckpointError(
                f"paper verification failure checkpoint is inconsistent: {path}"
            )
        _load_privacy_receipt(payload.get("request_privacy_normalization"), path=path)
        try:
            validate_persistable_content(request_payload)
            validate_persistable_content(payload.get("error_type"))
        except SensitiveContentError as exc:
            raise ContestDirectionStageCheckpointError(
                f"paper verification failure checkpoint is unsafe: {path}"
            ) from exc
        return "failed", None
    verified = payload.get("verified_paper")
    if (
        schema_version
        not in {
            _LEGACY_PAPER_VERIFICATION_CHECKPOINT_SCHEMA,
            _PAPER_VERIFICATION_CHECKPOINT_SCHEMA,
        }
        or not isinstance(verified, Mapping)
        or payload.get("verified_paper_hash") != canonical_model_hash(dict(verified))
    ):
        raise ContestDirectionStageCheckpointError(
            f"paper verification checkpoint binding/hash mismatch: {path}"
        )
    if schema_version == _PAPER_VERIFICATION_CHECKPOINT_SCHEMA:
        _load_privacy_receipt(payload.get("request_privacy_normalization"), path=path)
        _load_privacy_receipt(payload.get("response_privacy_normalization"), path=path)
        try:
            validate_persistable_content(request_payload)
        except SensitiveContentError as exc:
            raise ContestDirectionStageCheckpointError(
                f"paper verification checkpoint request is unsafe: {path}"
            ) from exc
    try:
        validated = AcademicPaper.model_validate(verified)
        if schema_version == _PAPER_VERIFICATION_CHECKPOINT_SCHEMA:
            validate_persistable_content(validated.model_dump(mode="json"))
        return "completed", validated
    except Exception as exc:
        raise ContestDirectionStageCheckpointError(
            f"paper verification checkpoint contains invalid metadata: {path}"
        ) from exc


def _load_literature_search(
    path: Path,
    *,
    request: Mapping[str, Any],
) -> list[AcademicPaper]:
    payload = _read_json(path)
    expected_hash = canonical_model_hash(
        {key: value for key, value in payload.items() if key != "checkpoint_hash"}
    )
    papers = payload.get("papers")
    schema_version = payload.get("schema_version")
    if (
        schema_version
        not in {
            _LEGACY_LITERATURE_SEARCH_CHECKPOINT_SCHEMA,
            _LITERATURE_SEARCH_CHECKPOINT_SCHEMA,
        }
        or payload.get("request") != dict(request)
        or payload.get("request_hash") != canonical_model_hash(dict(request))
        or payload.get("checkpoint_hash") != expected_hash
        or not isinstance(papers, list)
    ):
        raise ContestDirectionStageCheckpointError(
            f"literature search checkpoint binding/hash mismatch: {path}"
        )
    if schema_version == _LITERATURE_SEARCH_CHECKPOINT_SCHEMA:
        _load_privacy_receipt(payload.get("privacy_normalization"), path=path)
        try:
            validate_persistable_content(dict(request))
        except SensitiveContentError as exc:
            raise ContestDirectionStageCheckpointError(
                f"literature search checkpoint request is unsafe: {path}"
            ) from exc
    if payload.get("status") == "failed":
        if papers or not str(payload.get("error_type") or ""):
            raise ContestDirectionStageCheckpointError(
                f"literature failed-search checkpoint is inconsistent: {path}"
            )
        if schema_version == _LITERATURE_SEARCH_CHECKPOINT_SCHEMA:
            try:
                validate_persistable_content(payload.get("error_message"))
            except SensitiveContentError as exc:
                raise ContestDirectionStageCheckpointError(
                    f"literature failed-search checkpoint error is unsafe: {path}"
                ) from exc
        raise ContestDirectionStageCheckpointError(
            "replayed literature source failure "
            f"{payload.get('error_type')}: {payload.get('error_message') or ''}"
        )
    if payload.get("status") != "completed" or payload.get("papers_hash") != canonical_model_hash(
        {"papers": papers}
    ):
        raise ContestDirectionStageCheckpointError(
            f"literature completed-search checkpoint is inconsistent: {path}"
        )
    try:
        validated = [AcademicPaper.model_validate(item) for item in papers]
        if schema_version == _LITERATURE_SEARCH_CHECKPOINT_SCHEMA:
            validate_persistable_content([item.model_dump(mode="json") for item in validated])
        return validated
    except Exception as exc:
        raise ContestDirectionStageCheckpointError(
            f"literature search checkpoint contains an invalid paper: {path}"
        ) from exc


def _load_privacy_receipt(
    value: object,
    *,
    path: Path,
) -> ScholarlyMetadataPrivacyReceipt:
    try:
        return ScholarlyMetadataPrivacyReceipt.model_validate(value)
    except Exception as exc:
        raise ContestDirectionStageCheckpointError(
            f"literature privacy-normalization receipt is invalid: {path}"
        ) from exc


def _completion_request_payload(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    messages = kwargs.get("messages")
    if not isinstance(messages, list) or not all(isinstance(item, Mapping) for item in messages):
        raise ContestDirectionStageCheckpointError(
            "checkpointed completion requires a JSON message list"
        )
    return {
        "messages": [dict(item) for item in messages],
        "config_path": str(kwargs.get("config_path", "config.yaml")),
        "env_path": str(kwargs.get("env_path", ".env")),
        "timeout_seconds": kwargs.get("timeout_seconds"),
        "max_tokens": kwargs.get("max_tokens"),
        "temperature": kwargs.get("temperature"),
        "thinking_mode": kwargs.get("thinking_mode"),
        "thinking_budget": kwargs.get("thinking_budget"),
        "response_schema": kwargs.get("response_schema"),
        "response_schema_name": kwargs.get("response_schema_name"),
    }


def _validate_string_values(value: object) -> None:
    if isinstance(value, str):
        validate_persistable_content(value)
        return
    if isinstance(value, Mapping):
        for item in value.values():
            _validate_string_values(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        for item in value:
            _validate_string_values(item)


def _checkpoint_root(root: Path | str) -> Path:
    return Path(root).expanduser().resolve() / "checkpoints"


def _validated_stage(stage_name: str) -> str:
    if not _SAFE_STAGE.fullmatch(stage_name):
        raise ContestDirectionStageCheckpointError("stage name is not safe")
    return stage_name


def _validated_hash(value: str, *, label: str) -> str:
    if not _SHA256.fullmatch(value):
        raise ContestDirectionStageCheckpointError(f"{label} must be a SHA-256")
    return value


def _file_binding(root: Path, value: Path | str) -> dict[str, Any]:
    path = Path(value).expanduser().resolve()
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ContestDirectionStageCheckpointError(
            f"completed stage artifact escapes run root: {path}"
        ) from exc
    if not path.is_file():
        raise ContestDirectionStageCheckpointError(
            f"completed stage artifact does not exist: {path}"
        )
    raw = path.read_bytes()
    return {
        "relative_path": relative,
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _verify_file_binding(root: Path, binding: Mapping[str, Any]) -> None:
    relative = str(binding.get("relative_path") or "")
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ContestDirectionStageCheckpointError(
            "completed stage artifact binding escapes run root"
        ) from exc
    if not path.is_file():
        raise ContestDirectionStageCheckpointError(
            f"completed stage artifact is missing: {relative}"
        )
    raw = path.read_bytes()
    if (
        binding.get("size_bytes") != len(raw)
        or binding.get("sha256") != hashlib.sha256(raw).hexdigest()
    ):
        raise ContestDirectionStageCheckpointError(
            f"completed stage artifact bytes changed: {relative}"
        )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContestDirectionStageCheckpointError(
            f"checkpoint is not valid UTF-8 JSON: {path}"
        ) from exc
    if not isinstance(payload, dict):
        raise ContestDirectionStageCheckpointError(f"checkpoint is not an object: {path}")
    return payload


def _write_once_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        existing = path.read_bytes()
        if existing != raw:
            raise ContestDirectionStageCheckpointError(
                f"refusing to overwrite different checkpoint bytes: {path}"
            ) from exc
        return
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


__all__ = [
    "ContestDirectionStageCheckpointError",
    "load_completed_stage",
    "literature_search_checkpoint_accounting",
    "paper_verification_checkpoint_accounting",
    "provider_checkpoint_accounting",
    "provider_checkpoint_count",
    "record_completed_stage",
    "replayable_literature_searchers",
    "replayable_paper_verifier",
    "replayable_stage_completion",
    "research_loop_literature_search_checkpoint_accounting",
    "research_loop_source_checkpoint_accounting",
]
