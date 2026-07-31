"""Result-blind search and evidence-packet Harness for Task 263.6.7.2.

The Task 263.6.7.1 protocol is immutable input to this module.  The Harness
implements four bibliographic adapters, content-addressed raw-response storage,
append-only PRISMA-S logs, exact paper deduplication, explicit family/revision
clustering, known-item recall, and empty human-coding packets.  It does not
inspect benchmark outcomes, create an Admission Card, make a screening
decision, or authorize a scientific claim.

Capability probes are deliberately separate from the 28 formal searches.  A
probe can demonstrate that an API still returns the documented response shape,
while formal census execution stays blocked if the frozen pagination contract
cannot exhaust the source without an amendment.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Protocol, TypeVar, cast

import certifi
from pydantic import (
    BaseModel,
    Field,
    TypeAdapter,
    ValidationInfo,
    field_validator,
    model_validator,
)

from autoresearch.kernel.contracts import (
    KernelContract,
    NonEmptyText,
    Sha256,
    StableId,
    canonical_sha256,
)

from .benchmark_validity_protocol import (
    SEARCH_CUTOFF_DATE,
    SEARCH_START_DATE,
    AdmissionGate,
    BenchmarkValidityProtocol,
    ExtractionFieldSpec,
    SearchExecutionLogEntry,
    SearchSourceId,
    SearchSourceSpec,
    SourceQueryBinding,
)
from .workload_qualified_opportunity import InterpreterRuntime, probe_interpreter_runtime

FROZEN_BENCHMARK_VALIDITY_PROTOCOL_HASH = (
    "ed6088c225d5c7f7710ecb69507659003b5b97e06dc7c0ee005a81ed2712e8ed"
)
FROZEN_BENCHMARK_VALIDITY_PROTOCOL_SOURCE_SHA256 = (
    "8ad851870621f524bd2d2710a66f94661b3c0d33a72280bca1f435635111b633"
)

HARNESS_REPORT_FILENAME = "benchmark-validity-harness-report.json"
HARNESS_MARKDOWN_FILENAME = "benchmark-validity-harness-report.md"
HARNESS_PROJECTION_FILENAME = "benchmark-validity-harness-projection.json"
HARNESS_REPLAY_FILENAME = "benchmark-validity-harness-replay.json"
HARNESS_SCHEMA_FILENAME = "benchmark-validity-harness-schemas.json"
HARNESS_MANIFEST_FILENAME = "benchmark-validity-harness-manifest.json"
HARNESS_PAGE_LOG_FILENAME = "benchmark-search-pages.jsonl"
HARNESS_EXECUTION_LOG_FILENAME = "benchmark-search-executions.jsonl"
HARNESS_RAW_DIRECTORY = "raw-responses"
HARNESS_BIBLIOGRAPHIC_DIRECTORY = "bibliographic-records"

HARNESS_RUNNER_SOURCE_PATH = Path(
    "src/autoresearch/research/assets/"
    "frozen_benchmark_validity_harness_probe_v1.py"
)

MAX_RAW_RESPONSE_BYTES = 64 * 1024 * 1024
_ARXIV_ID_RE = re.compile(
    r"(?:arxiv:|arxiv\.org/(?:abs|pdf)/)([a-z-]+(?:\.[A-Z]{2})?/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?",
    re.IGNORECASE,
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_FORBIDDEN_RESULT_KEYS = {
    "admission_card",
    "admission_cards",
    "answer",
    "benchmark_outcome",
    "benchmark_outcomes",
    "candidate_model_output",
    "candidate_model_outputs",
    "gold",
    "gold_answer",
    "gold_hypothesis",
    "judge_output",
    "model_output",
    "model_outputs",
    "reference_answer",
    "reference_program",
    "reserve_result",
    "screening_decision",
}
_SAFE_RESPONSE_HEADERS = {
    "content-type",
    "date",
    "etag",
    "last-modified",
    "retry-after",
    "x-rate-limit-interval",
    "x-rate-limit-limit",
    "x-rate-limit-remaining",
}
_RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
_T = TypeVar("_T", bound=BaseModel)


class BenchmarkValidityHarnessIntegrityError(ValueError):
    """Raised when a Harness contract, log, or artifact no longer verifies."""


class BenchmarkValidityTransportError(RuntimeError):
    """Raised after the frozen bounded transport retry policy is exhausted."""


class FormalSearchBlockedError(RuntimeError):
    """Raised when a known protocol/API mismatch would make search incomplete."""


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        rendered = value.astimezone(timezone.utc).isoformat()
        return rendered[:-6] + "Z" if rendered.endswith("+00:00") else rendered
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


def _canonical_json_text(value: Any) -> str:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _pretty_json_text(value: Any) -> str:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ) + "\n"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8", newline="\n")
        temporary.replace(path)
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def _write_bytes_content_addressed(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if _file_sha256(path) != _sha256_bytes(content):
            raise BenchmarkValidityHarnessIntegrityError(
                f"content-addressed raw response changed: {path}"
            )
        return
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(content)
        if path.exists():
            if _file_sha256(path) != _sha256_bytes(content):
                raise BenchmarkValidityHarnessIntegrityError(
                    f"raw response race produced different bytes: {path}"
                )
            return
        temporary.replace(path)
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def _canonical_url(endpoint_url: str, parameters: Mapping[str, str]) -> str:
    query = urllib.parse.urlencode(
        sorted((str(key), str(value)) for key, value in parameters.items()),
        doseq=False,
        safe="():,$|\"'[]",
    )
    return f"{endpoint_url}?{query}"


def _normalize_space(value: str) -> str:
    return " ".join(value.split())


def normalize_title(value: str) -> str:
    """Return an exact, punctuation-insensitive title identity key."""

    normalized = value.casefold()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def normalize_doi(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().casefold()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        normalized = normalized.removeprefix(prefix)
    return normalized.rstrip(" .") or None


def normalize_arxiv_id(value: str | None) -> str | None:
    if value is None:
        return None
    match = _ARXIV_ID_RE.search(value.strip())
    if match is None:
        candidate = re.sub(r"v\d+$", "", value.strip(), flags=re.IGNORECASE)
        if re.fullmatch(r"(?:[a-z-]+(?:\.[A-Z]{2})?/\d{7}|\d{4}\.\d{4,5})", candidate, re.IGNORECASE):
            return candidate.casefold()
        return None
    return match.group(1).casefold()


def _clean_abstract(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    without_tags = _HTML_TAG_RE.sub(" ", html.unescape(value))
    return _normalize_space(without_tags) or None


def _walk_forbidden(value: Any, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key).casefold().replace("-", "_")
            if key in _FORBIDDEN_RESULT_KEYS and item is not None:
                raise ValueError(f"{path}.{raw_key} is forbidden in the result-blind Harness")
            _walk_forbidden(item, path=f"{path}.{raw_key}")
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, item in enumerate(value):
            _walk_forbidden(item, path=f"{path}[{index}]")


_JSON_VALUE_ADAPTER = TypeAdapter(dict[str, Any])


def _addressed_payload(payload: dict[str, Any], hash_field: str) -> dict[str, Any]:
    """Hash the same JSON representation used by Pydantic after validation."""

    json_payload = cast(
        dict[str, Any],
        _JSON_VALUE_ADAPTER.dump_python(payload, mode="json"),
    )
    normalized = dict(payload)
    normalized[hash_field] = canonical_sha256(json_payload)
    return normalized


def _create_protocol_search_log(**values: Any) -> SearchExecutionLogEntry:
    payload = {
        "schema_version": "benchmark-search-log-entry-v1",
        "benchmark_records_extracted_before_protocol_freeze": False,
        **values,
    }
    return SearchExecutionLogEntry.model_validate(
        _addressed_payload(payload, "log_entry_hash")
    )


class SearchPurpose(str, Enum):
    FORMAL_CENSUS = "formal-census"
    API_CAPABILITY_SMOKE = "api-capability-smoke"
    DETERMINISTIC_CHARACTERIZATION = "deterministic-characterization"


class PageAttemptStatus(str, Enum):
    SUCCEEDED = "succeeded"
    HTTP_ERROR = "http-error"
    TRANSPORT_ERROR = "transport-error"
    PARSE_ERROR = "parse-error"


class SearchRunStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNREACHABLE = "unreachable"
    CAPABILITY_ONLY = "capability-only"


class CompatibilitySeverity(str, Enum):
    INFORMATIONAL = "informational"
    CONDITIONAL_BLOCKER = "conditional-blocker"
    FORMAL_BLOCKER = "formal-blocker"


class HarnessStatus(str, Enum):
    READY_FOR_CAPABILITY_ONLY = "ready-for-capability-only"
    READY_FOR_FORMAL_SEARCH = "ready-for-formal-search"


class FamilyRevisionRole(str, Enum):
    PRIMARY_CROSS_SECTIONAL = "primary-cross-sectional"
    LONGITUDINAL_ONLY = "longitudinal-only"
    PROTOCOL_PILOT = "protocol-pilot"


class AdapterContract(KernelContract):
    """Versioned adapter semantics bound to one frozen search source."""

    schema_version: Literal["benchmark-search-adapter-v1"] = (
        "benchmark-search-adapter-v1"
    )
    source_id: SearchSourceId
    endpoint_url: NonEmptyText
    response_format: NonEmptyText
    page_size: int = Field(ge=1, le=2_000)
    initial_parameter_names: list[StableId]
    pagination_mode: Literal[
        "offset-total",
        "cursor-null",
        "cursor-short-page",
        "single-page-or-frozen-year-split",
    ]
    parser_version: Literal["bibliographic-metadata-only-v1"] = (
        "bibliographic-metadata-only-v1"
    )
    benchmark_outcome_fields_parsed: Literal[False] = False
    adapter_hash: Sha256

    @field_validator("initial_parameter_names")
    @classmethod
    def _sort_parameters(cls, value: list[str]) -> list[str]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("adapter parameter names must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_hash(self) -> AdapterContract:
        if self.adapter_hash != self.calculated_hash():
            raise BenchmarkValidityHarnessIntegrityError("adapter_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdapterContract:
        payload = {"schema_version": "benchmark-search-adapter-v1", **values}
        return cls.model_validate(_addressed_payload(payload, "adapter_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"adapter_hash"})
        )


class ProtocolCompatibilityFinding(KernelContract):
    """An API-contract fact that constrains formal execution."""

    finding_id: StableId
    source_id: SearchSourceId
    severity: CompatibilitySeverity
    frozen_rule: str = Field(min_length=1, max_length=2_048)
    current_documented_rule: str = Field(min_length=1, max_length=2_048)
    documentation_url: NonEmptyText
    formal_search_allowed: bool
    capability_smoke_allowed: Literal[True] = True
    required_action: str = Field(min_length=1, max_length=2_048)
    finding_hash: Sha256

    @model_validator(mode="after")
    def _validate_semantics(self) -> ProtocolCompatibilityFinding:
        if self.severity is CompatibilitySeverity.FORMAL_BLOCKER and self.formal_search_allowed:
            raise ValueError("formal blockers cannot authorize formal search")
        if self.finding_hash != self.calculated_hash():
            raise BenchmarkValidityHarnessIntegrityError("finding_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ProtocolCompatibilityFinding:
        payload = {"capability_smoke_allowed": True, **values}
        return cls.model_validate(_addressed_payload(payload, "finding_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"finding_hash"})
        )


class CapabilityProbeSpec(KernelContract):
    """A one-page API-shape probe that is not a formal protocol query."""

    probe_id: StableId
    source_id: SearchSourceId
    endpoint_url: NonEmptyText
    request_parameters: dict[str, str]
    expected_response_format: Literal["atom-xml", "openalex-json", "crossref-json", "dblp-json"]
    known_item_title: str = Field(min_length=1, max_length=512)
    formal_search_binding: Literal[False] = False
    record_extraction_authorized: Literal[False] = False
    benchmark_outcome_access_authorized: Literal[False] = False
    probe_hash: Sha256

    @field_validator("request_parameters")
    @classmethod
    def _sort_parameters(cls, value: dict[str, str]) -> dict[str, str]:
        return dict(sorted(value.items()))

    @model_validator(mode="after")
    def _validate_probe(self) -> CapabilityProbeSpec:
        if self.probe_hash != self.calculated_hash():
            raise BenchmarkValidityHarnessIntegrityError("capability probe_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> CapabilityProbeSpec:
        payload = {
            "formal_search_binding": False,
            "record_extraction_authorized": False,
            "benchmark_outcome_access_authorized": False,
            **values,
        }
        return cls.model_validate(_addressed_payload(payload, "probe_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"probe_hash"}))


class SearchPageRequest(KernelContract):
    """Exact request metadata; URLs contain only public query parameters."""

    schema_version: Literal["benchmark-search-page-request-v1"] = (
        "benchmark-search-page-request-v1"
    )
    purpose: SearchPurpose
    query_or_probe_id: StableId
    source_id: SearchSourceId
    page_index: int = Field(ge=0)
    attempt_index: int = Field(ge=0, le=5)
    endpoint_url: NonEmptyText
    request_parameters: dict[str, str]
    canonical_url: str = Field(min_length=1, max_length=16_384)
    request_url_sha256: Sha256
    request_hash: Sha256

    @field_validator("request_parameters")
    @classmethod
    def _sort_parameters(cls, value: dict[str, str]) -> dict[str, str]:
        prohibited = {
            key
            for key in value
            if any(token in key.casefold() for token in ("api_key", "apikey", "token", "secret", "password"))
        }
        if prohibited:
            raise ValueError(f"public search request cannot persist secrets: {sorted(prohibited)}")
        return dict(sorted(value.items()))

    @model_validator(mode="after")
    def _validate_request(self) -> SearchPageRequest:
        expected_url = _canonical_url(self.endpoint_url, self.request_parameters)
        if self.canonical_url != expected_url:
            raise ValueError("canonical request URL does not match endpoint and parameters")
        if self.request_url_sha256 != _sha256_text(self.canonical_url):
            raise BenchmarkValidityHarnessIntegrityError("request URL hash mismatch")
        if self.request_hash != self.calculated_hash():
            raise BenchmarkValidityHarnessIntegrityError("request_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> SearchPageRequest:
        parameters = dict(sorted(values.pop("request_parameters").items()))
        canonical_url = _canonical_url(values["endpoint_url"], parameters)
        payload = {
            "schema_version": "benchmark-search-page-request-v1",
            **values,
            "request_parameters": parameters,
            "canonical_url": canonical_url,
            "request_url_sha256": _sha256_text(canonical_url),
        }
        return cls.model_validate(_addressed_payload(payload, "request_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"request_hash"}))


class RawResponseArtifact(KernelContract):
    """Content-addressed envelope for exact response bytes."""

    schema_version: Literal["benchmark-raw-response-v1"] = "benchmark-raw-response-v1"
    request_hash: Sha256
    received_at: datetime
    status_code: int = Field(ge=100, le=599)
    response_headers: dict[str, str]
    final_url_sha256: Sha256
    media_type: NonEmptyText
    body_sha256: Sha256
    body_bytes: int = Field(ge=0, le=MAX_RAW_RESPONSE_BYTES)
    relative_path: NonEmptyText
    artifact_hash: Sha256

    @field_validator("received_at")
    @classmethod
    def _require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("raw response time must be timezone aware")
        return value.astimezone(timezone.utc)

    @field_validator("response_headers")
    @classmethod
    def _sort_headers(cls, value: dict[str, str]) -> dict[str, str]:
        return dict(sorted((key.casefold(), item) for key, item in value.items()))

    @model_validator(mode="after")
    def _validate_artifact(self) -> RawResponseArtifact:
        expected = f"{HARNESS_RAW_DIRECTORY}/{self.body_sha256}.bin"
        if self.relative_path.replace("\\", "/") != expected:
            raise ValueError("raw response path must derive from body SHA-256")
        if self.artifact_hash != self.calculated_hash():
            raise BenchmarkValidityHarnessIntegrityError("raw artifact_hash mismatch")
        return self

    @classmethod
    def create(cls, *, body: bytes, final_url: str, **values: Any) -> RawResponseArtifact:
        body_hash = _sha256_bytes(body)
        payload = {
            "schema_version": "benchmark-raw-response-v1",
            **values,
            "final_url_sha256": _sha256_text(final_url),
            "body_sha256": body_hash,
            "body_bytes": len(body),
            "relative_path": f"{HARNESS_RAW_DIRECTORY}/{body_hash}.bin",
        }
        return cls.model_validate(_addressed_payload(payload, "artifact_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"artifact_hash"}))


class BibliographicRecord(KernelContract):
    """Whitelisted bibliographic metadata; no benchmark result fields exist."""

    schema_version: Literal["benchmark-bibliographic-record-v1"] = (
        "benchmark-bibliographic-record-v1"
    )
    source_id: SearchSourceId
    source_record_id: StableId
    title: str = Field(min_length=1, max_length=1_024)
    normalized_title: str = Field(min_length=1, max_length=1_024)
    authors: list[str]
    first_author_key: str | None = Field(default=None, max_length=256)
    abstract: str | None = Field(default=None, max_length=32_768)
    publication_date: date | None = None
    publication_year: int | None = Field(default=None, ge=1900, le=2100)
    doi: str | None = Field(default=None, max_length=512)
    arxiv_id: str | None = Field(default=None, max_length=128)
    openalex_id: str | None = Field(default=None, max_length=128)
    dblp_key: str | None = Field(default=None, max_length=512)
    stable_locator: str = Field(min_length=1, max_length=2_048)
    raw_response_artifact_hash: Sha256
    retrieved_at: datetime
    benchmark_outcomes_accessed: Literal[False] = False
    record_hash: Sha256

    @field_validator("authors")
    @classmethod
    def _clean_authors(cls, value: list[str]) -> list[str]:
        return [_normalize_space(item) for item in value if item.strip()]

    @field_validator("retrieved_at")
    @classmethod
    def _record_time_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("bibliographic retrieval time must be timezone aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _validate_record(self) -> BibliographicRecord:
        if self.normalized_title != normalize_title(self.title):
            raise ValueError("normalized title does not match title")
        if (
            self.publication_date is not None
            and self.publication_year != self.publication_date.year
        ):
            raise ValueError("publication year must match exact date")
        if self.record_hash != self.calculated_hash():
            raise BenchmarkValidityHarnessIntegrityError("bibliographic record_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> BibliographicRecord:
        title = _normalize_space(str(values["title"]))
        authors = [_normalize_space(str(item)) for item in values.get("authors", []) if str(item).strip()]
        publication_date = values.get("publication_date")
        publication_year = values.get("publication_year")
        if publication_date is not None:
            publication_year = publication_date.year
        payload = {
            "schema_version": "benchmark-bibliographic-record-v1",
            **values,
            "title": title,
            "normalized_title": normalize_title(title),
            "authors": authors,
            "first_author_key": normalize_title(authors[0]) if authors else None,
            "publication_year": publication_year,
            "doi": normalize_doi(values.get("doi")),
            "arxiv_id": normalize_arxiv_id(values.get("arxiv_id")),
            "benchmark_outcomes_accessed": False,
        }
        return cls.model_validate(_addressed_payload(payload, "record_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"record_hash"}))

    def identity_keys(self) -> list[str]:
        keys: list[str] = []
        if self.doi:
            keys.append(f"doi:{self.doi}")
        if self.arxiv_id:
            keys.append(f"arxiv:{self.arxiv_id}")
        if self.openalex_id:
            keys.append(f"openalex:{self.openalex_id.casefold()}")
        if self.dblp_key:
            keys.append(f"dblp:{self.dblp_key.casefold()}")
        if self.first_author_key and self.publication_year:
            keys.append(
                "title-author-year:"
                f"{self.normalized_title}|{self.first_author_key}|{self.publication_year}"
            )
        else:
            keys.append(f"title:{self.normalized_title}")
        return sorted(set(keys))


class ParsedSearchPage(KernelContract):
    """A response projection restricted to bibliographic metadata and paging."""

    source_id: SearchSourceId
    request_hash: Sha256
    raw_response_artifact_hash: Sha256
    records: list[BibliographicRecord]
    total_results: int | None = Field(default=None, ge=0)
    next_parameters: dict[str, str] | None = None
    exhausted: bool
    requires_frozen_year_split: bool = False
    parser_hash: Sha256

    @field_validator("records")
    @classmethod
    def _sort_records(cls, value: list[BibliographicRecord]) -> list[BibliographicRecord]:
        normalized = sorted(value, key=lambda item: item.record_hash)
        if len({item.record_hash for item in normalized}) != len(normalized):
            raise ValueError("one page cannot contain duplicate record hashes")
        return normalized

    @field_validator("next_parameters")
    @classmethod
    def _sort_next(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        return None if value is None else dict(sorted(value.items()))

    @model_validator(mode="after")
    def _validate_page(self) -> ParsedSearchPage:
        if self.exhausted and self.next_parameters is not None:
            raise ValueError("exhausted pages cannot carry a next request")
        if self.requires_frozen_year_split and self.exhausted:
            raise ValueError("a DBLP cap cannot be treated as exhausted")
        if self.parser_hash != self.calculated_hash():
            raise BenchmarkValidityHarnessIntegrityError("parser_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ParsedSearchPage:
        return cls.model_validate(_addressed_payload(values, "parser_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"parser_hash"}))


@dataclass(frozen=True)
class TransportResponse:
    """Exact HTTP response returned by an injectable GET transport."""

    status_code: int
    headers: Mapping[str, str]
    body: bytes
    final_url: str


class HttpGetTransport(Protocol):
    def __call__(
        self,
        *,
        endpoint_url: str,
        parameters: Mapping[str, str],
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_bytes: int,
    ) -> TransportResponse: ...


def urllib_get_transport(
    *,
    endpoint_url: str,
    parameters: Mapping[str, str],
    headers: Mapping[str, str],
    timeout_seconds: float,
    max_bytes: int,
) -> TransportResponse:
    """Fetch one bounded response without decoding or normalizing its bytes."""

    canonical_url = _canonical_url(endpoint_url, parameters)
    request = urllib.request.Request(canonical_url, headers=dict(headers), method="GET")
    context = ssl.create_default_context(cafile=certifi.where())
    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout_seconds,
            context=context,
        ) as response:
            body = cast(bytes, response.read(max_bytes + 1))
            if len(body) > max_bytes:
                raise BenchmarkValidityTransportError(
                    f"response exceeded {max_bytes} bytes"
                )
            return TransportResponse(
                status_code=int(response.status),
                headers={str(key): str(value) for key, value in response.headers.items()},
                body=body,
                final_url=str(response.geturl()),
            )
    except urllib.error.HTTPError as exc:
        body = exc.read(max_bytes + 1)
        if len(body) > max_bytes:
            body = body[:max_bytes]
        return TransportResponse(
            status_code=int(exc.code),
            headers={str(key): str(value) for key, value in exc.headers.items()},
            body=body,
            final_url=str(exc.geturl()),
        )


def _parse_iso_date(value: object) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()[:10]
    try:
        return date.fromisoformat(candidate)
    except ValueError:
        return None


def _date_from_parts(value: object) -> date | None:
    if not isinstance(value, Mapping):
        return None
    raw_parts = value.get("date-parts")
    if not isinstance(raw_parts, list) or not raw_parts:
        return None
    first = raw_parts[0]
    if not isinstance(first, list) or not first:
        return None
    try:
        year = int(first[0])
        month = int(first[1]) if len(first) > 1 else 1
        day = int(first[2]) if len(first) > 2 else 1
        return date(year, month, day)
    except (TypeError, ValueError):
        return None


def _record_in_frozen_window(record: BibliographicRecord) -> bool:
    if record.publication_date is not None:
        return SEARCH_START_DATE <= record.publication_date <= SEARCH_CUTOFF_DATE
    if record.publication_year is not None:
        return SEARCH_START_DATE.year <= record.publication_year <= SEARCH_CUTOFF_DATE.year
    return False


def _safe_source_record_id(source_id: SearchSourceId, raw_identifier: str) -> str:
    normalized = raw_identifier.strip()
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,220}", normalized):
        return f"{source_id.value}:{normalized}"
    return f"{source_id.value}:sha256-{_sha256_text(normalized)[:32]}"


def _arxiv_record(
    entry: ET.Element,
    *,
    artifact: RawResponseArtifact,
) -> BibliographicRecord | None:
    namespace = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }

    def text_at(path: str) -> str | None:
        element = entry.find(path, namespace)
        if element is None or element.text is None:
            return None
        return _normalize_space(element.text)

    title = text_at("atom:title")
    locator = text_at("atom:id")
    if title is None or locator is None:
        return None
    arxiv_id = normalize_arxiv_id(locator)
    if arxiv_id is None:
        return None
    authors = []
    for author in entry.findall("atom:author", namespace):
        name = author.find("atom:name", namespace)
        if name is not None and name.text and name.text.strip():
            authors.append(_normalize_space(name.text))
    published = _parse_iso_date(text_at("atom:published"))
    return BibliographicRecord.create(
        source_id=SearchSourceId.ARXIV,
        source_record_id=_safe_source_record_id(SearchSourceId.ARXIV, arxiv_id),
        title=title,
        authors=authors,
        abstract=_clean_abstract(text_at("atom:summary")),
        publication_date=published,
        publication_year=published.year if published else None,
        doi=text_at("arxiv:doi"),
        arxiv_id=arxiv_id,
        openalex_id=None,
        dblp_key=None,
        stable_locator=locator,
        raw_response_artifact_hash=artifact.artifact_hash,
        retrieved_at=artifact.received_at,
    )


def parse_arxiv_page(
    *,
    request: SearchPageRequest,
    artifact: RawResponseArtifact,
    body: bytes,
) -> ParsedSearchPage:
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise ValueError("arXiv response is not valid Atom XML") from exc
    namespace = {
        "atom": "http://www.w3.org/2005/Atom",
        "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
    }
    total_element = root.find("opensearch:totalResults", namespace)
    try:
        total_results = (
            int(total_element.text)
            if total_element is not None and total_element.text is not None
            else None
        )
    except (TypeError, ValueError):
        total_results = None
    records = [
        record
        for entry in root.findall("atom:entry", namespace)
        if (record := _arxiv_record(entry, artifact=artifact)) is not None
    ]
    if request.purpose is SearchPurpose.FORMAL_CENSUS:
        records = [record for record in records if _record_in_frozen_window(record)]
    start = int(request.request_parameters.get("start", "0"))
    page_size = int(request.request_parameters.get("max_results", "1"))
    returned = len(root.findall("atom:entry", namespace))
    has_more = total_results is not None and start + returned < total_results
    if has_more and returned == 0:
        raise ValueError("arXiv reported remaining records but returned an empty page")
    next_parameters = None
    if has_more:
        next_parameters = dict(request.request_parameters)
        next_parameters["start"] = str(start + page_size)
    return ParsedSearchPage.create(
        source_id=SearchSourceId.ARXIV,
        request_hash=request.request_hash,
        raw_response_artifact_hash=artifact.artifact_hash,
        records=records,
        total_results=total_results,
        next_parameters=next_parameters,
        exhausted=not has_more,
        requires_frozen_year_split=False,
    )


def _openalex_abstract(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    positioned: list[tuple[int, str]] = []
    for word, positions in value.items():
        if not isinstance(word, str) or not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int) and position >= 0:
                positioned.append((position, word))
    positioned.sort()
    if not positioned:
        return None
    return _normalize_space(" ".join(word for _, word in positioned))[:32_768]


def _openalex_record(
    item: Mapping[str, Any],
    *,
    artifact: RawResponseArtifact,
) -> BibliographicRecord | None:
    raw_id = item.get("id")
    title = item.get("display_name") or item.get("title")
    if not isinstance(raw_id, str) or not isinstance(title, str) or not title.strip():
        return None
    openalex_id = raw_id.rstrip("/").rsplit("/", 1)[-1]
    authors: list[str] = []
    raw_authorships = item.get("authorships")
    if isinstance(raw_authorships, list):
        for authorship in raw_authorships:
            if not isinstance(authorship, Mapping):
                continue
            author = authorship.get("author")
            if isinstance(author, Mapping) and isinstance(author.get("display_name"), str):
                authors.append(str(author["display_name"]))
    publication_date = _parse_iso_date(item.get("publication_date"))
    publication_year = item.get("publication_year")
    if not isinstance(publication_year, int):
        publication_year = publication_date.year if publication_date else None
    stable_locator = raw_id
    primary_location = item.get("primary_location")
    if isinstance(primary_location, Mapping):
        landing_page = primary_location.get("landing_page_url")
        if isinstance(landing_page, str) and landing_page.strip():
            stable_locator = landing_page
    arxiv_id = None
    raw_ids = item.get("ids")
    if isinstance(raw_ids, Mapping):
        for value in raw_ids.values():
            if isinstance(value, str) and (candidate := normalize_arxiv_id(value)):
                arxiv_id = candidate
                break
    return BibliographicRecord.create(
        source_id=SearchSourceId.OPENALEX,
        source_record_id=_safe_source_record_id(SearchSourceId.OPENALEX, openalex_id),
        title=title,
        authors=authors,
        abstract=_openalex_abstract(item.get("abstract_inverted_index")),
        publication_date=publication_date,
        publication_year=publication_year,
        doi=item.get("doi") if isinstance(item.get("doi"), str) else None,
        arxiv_id=arxiv_id,
        openalex_id=openalex_id,
        dblp_key=None,
        stable_locator=stable_locator,
        raw_response_artifact_hash=artifact.artifact_hash,
        retrieved_at=artifact.received_at,
    )


def parse_openalex_page(
    *,
    request: SearchPageRequest,
    artifact: RawResponseArtifact,
    body: bytes,
) -> ParsedSearchPage:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("OpenAlex response is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("OpenAlex response root must be an object")
    raw_results = payload.get("results")
    meta = payload.get("meta")
    if not isinstance(raw_results, list) or not isinstance(meta, Mapping):
        raise ValueError("OpenAlex response is missing results/meta")
    records = [
        record
        for item in raw_results
        if isinstance(item, Mapping)
        if (record := _openalex_record(item, artifact=artifact)) is not None
    ]
    if request.purpose is SearchPurpose.FORMAL_CENSUS:
        records = [record for record in records if _record_in_frozen_window(record)]
    raw_total = meta.get("count")
    total_results = int(raw_total) if isinstance(raw_total, int | str) and str(raw_total).isdigit() else None
    next_cursor = meta.get("next_cursor")
    next_parameters = None
    if isinstance(next_cursor, str) and next_cursor:
        next_parameters = dict(request.request_parameters)
        next_parameters["cursor"] = next_cursor
    return ParsedSearchPage.create(
        source_id=SearchSourceId.OPENALEX,
        request_hash=request.request_hash,
        raw_response_artifact_hash=artifact.artifact_hash,
        records=records,
        total_results=total_results,
        next_parameters=next_parameters,
        exhausted=next_parameters is None,
        requires_frozen_year_split=False,
    )


def _crossref_record(
    item: Mapping[str, Any],
    *,
    artifact: RawResponseArtifact,
) -> BibliographicRecord | None:
    raw_titles = item.get("title")
    title = None
    if isinstance(raw_titles, list) and raw_titles and isinstance(raw_titles[0], str):
        title = raw_titles[0]
    elif isinstance(raw_titles, str):
        title = raw_titles
    doi = item.get("DOI")
    if title is None or not title.strip() or not isinstance(doi, str):
        return None
    authors: list[str] = []
    raw_authors = item.get("author")
    if isinstance(raw_authors, list):
        for author in raw_authors:
            if not isinstance(author, Mapping):
                continue
            given = author.get("given") if isinstance(author.get("given"), str) else ""
            family = author.get("family") if isinstance(author.get("family"), str) else ""
            name = _normalize_space(f"{given} {family}")
            if name:
                authors.append(name)
    publication_date = None
    for field_name in ("published", "published-online", "published-print", "issued"):
        publication_date = _date_from_parts(item.get(field_name))
        if publication_date is not None:
            break
    locator = item.get("URL") if isinstance(item.get("URL"), str) else f"https://doi.org/{doi}"
    arxiv_id = None
    alternative_ids = item.get("alternative-id")
    if isinstance(alternative_ids, list):
        for value in alternative_ids:
            if isinstance(value, str) and (candidate := normalize_arxiv_id(value)):
                arxiv_id = candidate
                break
    return BibliographicRecord.create(
        source_id=SearchSourceId.CROSSREF,
        source_record_id=_safe_source_record_id(SearchSourceId.CROSSREF, doi),
        title=title,
        authors=authors,
        abstract=_clean_abstract(item.get("abstract")),
        publication_date=publication_date,
        publication_year=publication_date.year if publication_date else None,
        doi=doi,
        arxiv_id=arxiv_id,
        openalex_id=None,
        dblp_key=None,
        stable_locator=locator,
        raw_response_artifact_hash=artifact.artifact_hash,
        retrieved_at=artifact.received_at,
    )


def parse_crossref_page(
    *,
    request: SearchPageRequest,
    artifact: RawResponseArtifact,
    body: bytes,
) -> ParsedSearchPage:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Crossref response is not valid JSON") from exc
    if not isinstance(payload, Mapping) or not isinstance(payload.get("message"), Mapping):
        raise ValueError("Crossref response is missing message")
    message = cast(Mapping[str, Any], payload["message"])
    raw_items = message.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("Crossref response is missing message.items")
    records = [
        record
        for item in raw_items
        if isinstance(item, Mapping)
        if (record := _crossref_record(item, artifact=artifact)) is not None
    ]
    if request.purpose is SearchPurpose.FORMAL_CENSUS:
        records = [record for record in records if _record_in_frozen_window(record)]
    raw_total = message.get("total-results")
    total_results = int(raw_total) if isinstance(raw_total, int | str) and str(raw_total).isdigit() else None
    rows = int(request.request_parameters.get("rows", "1"))
    short_page = len(raw_items) < rows
    next_cursor = message.get("next-cursor")
    next_parameters = None
    if not short_page:
        if not isinstance(next_cursor, str) or not next_cursor:
            raise ValueError("Crossref full page is missing next-cursor")
        next_parameters = dict(request.request_parameters)
        next_parameters["cursor"] = next_cursor
    return ParsedSearchPage.create(
        source_id=SearchSourceId.CROSSREF,
        request_hash=request.request_hash,
        raw_response_artifact_hash=artifact.artifact_hash,
        records=records,
        total_results=total_results,
        next_parameters=next_parameters,
        exhausted=short_page,
        requires_frozen_year_split=False,
    )


def _dblp_author_names(value: object) -> list[str]:
    if isinstance(value, str):
        return [_normalize_space(value)] if value.strip() else []
    if isinstance(value, Mapping):
        text = value.get("text")
        return [_normalize_space(text)] if isinstance(text, str) and text.strip() else []
    if isinstance(value, list):
        names: list[str] = []
        for item in value:
            names.extend(_dblp_author_names(item))
        return names
    return []


def _dblp_record(
    hit: Mapping[str, Any],
    *,
    artifact: RawResponseArtifact,
) -> BibliographicRecord | None:
    info = hit.get("info")
    if not isinstance(info, Mapping):
        return None
    title = info.get("title")
    key = info.get("key")
    if not isinstance(title, str) or not title.strip() or not isinstance(key, str):
        return None
    raw_authors = info.get("authors")
    author_value = raw_authors.get("author") if isinstance(raw_authors, Mapping) else None
    authors = _dblp_author_names(author_value)
    raw_year = info.get("year")
    publication_year = int(raw_year) if isinstance(raw_year, int | str) and str(raw_year).isdigit() else None
    locator = info.get("url") if isinstance(info.get("url"), str) else f"https://dblp.org/rec/{key}"
    doi = info.get("doi") if isinstance(info.get("doi"), str) else None
    return BibliographicRecord.create(
        source_id=SearchSourceId.DBLP,
        source_record_id=_safe_source_record_id(SearchSourceId.DBLP, key),
        title=html.unescape(title),
        authors=authors,
        abstract=None,
        publication_date=None,
        publication_year=publication_year,
        doi=doi,
        arxiv_id=normalize_arxiv_id(locator),
        openalex_id=None,
        dblp_key=key,
        stable_locator=locator,
        raw_response_artifact_hash=artifact.artifact_hash,
        retrieved_at=artifact.received_at,
    )


def parse_dblp_page(
    *,
    request: SearchPageRequest,
    artifact: RawResponseArtifact,
    body: bytes,
) -> ParsedSearchPage:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("DBLP response is not valid JSON") from exc
    if not isinstance(payload, Mapping) or not isinstance(payload.get("result"), Mapping):
        raise ValueError("DBLP response is missing result")
    result = cast(Mapping[str, Any], payload["result"])
    hits_container = result.get("hits")
    if not isinstance(hits_container, Mapping):
        raise ValueError("DBLP response is missing result.hits")
    raw_hits = hits_container.get("hit", [])
    if isinstance(raw_hits, Mapping):
        raw_hits = [raw_hits]
    if not isinstance(raw_hits, list):
        raise ValueError("DBLP hit collection has an invalid shape")
    records = [
        record
        for hit in raw_hits
        if isinstance(hit, Mapping)
        if (record := _dblp_record(hit, artifact=artifact)) is not None
    ]
    if request.purpose is SearchPurpose.FORMAL_CENSUS:
        records = [record for record in records if _record_in_frozen_window(record)]
    raw_total = hits_container.get("@total")
    total_results = int(raw_total) if isinstance(raw_total, int | str) and str(raw_total).isdigit() else None
    page_size = int(request.request_parameters.get("h", "1000"))
    requires_split = (
        request.purpose is SearchPurpose.FORMAL_CENSUS
        and total_results is not None
        and total_results >= page_size
    )
    return ParsedSearchPage.create(
        source_id=SearchSourceId.DBLP,
        request_hash=request.request_hash,
        raw_response_artifact_hash=artifact.artifact_hash,
        records=records,
        total_results=total_results,
        next_parameters=None,
        exhausted=not requires_split,
        requires_frozen_year_split=requires_split,
    )


_PAGE_PARSERS: dict[
    SearchSourceId,
    Callable[..., ParsedSearchPage],
] = {
    SearchSourceId.ARXIV: parse_arxiv_page,
    SearchSourceId.OPENALEX: parse_openalex_page,
    SearchSourceId.CROSSREF: parse_crossref_page,
    SearchSourceId.DBLP: parse_dblp_page,
}


def parse_search_page(
    *,
    request: SearchPageRequest,
    artifact: RawResponseArtifact,
    body: bytes,
) -> ParsedSearchPage:
    """Parse only fields whitelisted by :class:`BibliographicRecord`."""

    parser = _PAGE_PARSERS[request.source_id]
    return parser(request=request, artifact=artifact, body=body)


class SearchPageLogEntry(KernelContract):
    """One chained request attempt in the append-only PRISMA-S page log."""

    schema_version: Literal["benchmark-search-page-log-v1"] = (
        "benchmark-search-page-log-v1"
    )
    sequence: int = Field(ge=1)
    protocol_hash: Sha256
    request: SearchPageRequest
    status: PageAttemptStatus
    raw_response: RawResponseArtifact | None = None
    parsed_page_hash: Sha256 | None = None
    parsed_record_count: int = Field(ge=0)
    retry_after_seconds: float | None = Field(default=None, ge=0, le=86_400)
    error_type: StableId | None = None
    previous_entry_hash: Sha256 | None = None
    entry_hash: Sha256

    @model_validator(mode="after")
    def _validate_entry(self) -> SearchPageLogEntry:
        if self.sequence == 1 and self.previous_entry_hash is not None:
            raise ValueError("first page-log entry cannot reference a predecessor")
        if self.sequence > 1 and self.previous_entry_hash is None:
            raise ValueError("later page-log entries require a predecessor")
        if self.status is PageAttemptStatus.SUCCEEDED:
            if self.raw_response is None or self.parsed_page_hash is None:
                raise ValueError("successful page logs require raw and parsed artifacts")
        elif self.status is PageAttemptStatus.TRANSPORT_ERROR:
            if self.raw_response is not None or self.parsed_page_hash is not None:
                raise ValueError("transport errors cannot claim a response or parse")
            if self.error_type is None:
                raise ValueError("transport errors require an error type")
        elif self.status is PageAttemptStatus.PARSE_ERROR:
            if self.raw_response is None or self.parsed_page_hash is not None:
                raise ValueError("parse errors retain raw bytes but no parsed artifact")
            if self.error_type is None:
                raise ValueError("parse errors require an error type")
        elif self.status is PageAttemptStatus.HTTP_ERROR and (
            self.raw_response is None or self.parsed_page_hash is not None
        ):
            raise ValueError("HTTP errors retain raw bytes but no parsed artifact")
        if self.entry_hash != self.calculated_hash():
            raise BenchmarkValidityHarnessIntegrityError("page-log entry_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> SearchPageLogEntry:
        payload = {"schema_version": "benchmark-search-page-log-v1", **values}
        return cls.model_validate(_addressed_payload(payload, "entry_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"entry_hash"}))


class SearchRunSummary(KernelContract):
    """Content-addressed outcome of one bibliographic query or capability probe."""

    schema_version: Literal["benchmark-search-run-summary-v1"] = (
        "benchmark-search-run-summary-v1"
    )
    purpose: SearchPurpose
    query_or_probe_id: StableId
    source_id: SearchSourceId
    started_at: datetime
    completed_at: datetime
    status: SearchRunStatus
    completion_reason: StableId
    successful_page_count: int = Field(ge=0)
    request_attempt_count: int = Field(ge=1)
    retry_count: int = Field(ge=0, le=5_000)
    response_count: int = Field(ge=0)
    page_log_entry_hashes: list[Sha256]
    raw_response_artifact_hashes: list[Sha256]
    bibliographic_record_hashes: list[Sha256]
    protocol_search_log: SearchExecutionLogEntry | None = None
    formal_search_execution: bool
    benchmark_outcomes_accessed: Literal[False] = False
    candidate_model_calls: Literal[False] = False
    screening_decisions_created: Literal[False] = False
    admission_cards_created: Literal[False] = False
    summary_hash: Sha256

    @field_validator(
        "page_log_entry_hashes",
        "raw_response_artifact_hashes",
        "bibliographic_record_hashes",
    )
    @classmethod
    def _unique_hashes(cls, value: list[str], info: ValidationInfo) -> list[str]:
        if info.field_name == "page_log_entry_hashes":
            if len(value) != len(set(value)):
                raise ValueError("page log entry hashes must be unique")
            return value
        return sorted(set(value))

    @field_validator("started_at", "completed_at")
    @classmethod
    def _utc_times(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("search-run timestamps must be timezone aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _validate_summary(self) -> SearchRunSummary:
        if self.completed_at < self.started_at:
            raise ValueError("search run completed before it started")
        expected_formal = self.purpose is SearchPurpose.FORMAL_CENSUS
        if self.formal_search_execution != expected_formal:
            raise ValueError("formal-search flag must derive from purpose")
        if expected_formal and self.protocol_search_log is None:
            raise ValueError("formal searches require the frozen protocol log entry")
        if not expected_formal and self.protocol_search_log is not None:
            raise ValueError("capability/characterization runs cannot enter the formal log")
        if self.status is SearchRunStatus.CAPABILITY_ONLY and expected_formal:
            raise ValueError("formal search cannot be labelled capability-only")
        if self.successful_page_count > len(self.page_log_entry_hashes):
            raise ValueError("successful pages exceed logged attempts")
        if self.request_attempt_count != len(self.page_log_entry_hashes):
            raise ValueError("every request attempt must have one page-log entry")
        if self.retry_count > self.request_attempt_count - 1:
            raise ValueError("retry count exceeds request attempts")
        if self.summary_hash != self.calculated_hash():
            raise BenchmarkValidityHarnessIntegrityError("search summary_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> SearchRunSummary:
        payload = {
            "schema_version": "benchmark-search-run-summary-v1",
            "benchmark_outcomes_accessed": False,
            "candidate_model_calls": False,
            "screening_decisions_created": False,
            "admission_cards_created": False,
            **values,
        }
        return cls.model_validate(_addressed_payload(payload, "summary_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"summary_hash"}))


class SearchExecutionLogEnvelope(KernelContract):
    """Append-only chain around formal and capability run summaries."""

    schema_version: Literal["benchmark-search-execution-envelope-v1"] = (
        "benchmark-search-execution-envelope-v1"
    )
    sequence: int = Field(ge=1)
    protocol_hash: Sha256
    purpose: SearchPurpose
    summary_hash: Sha256
    formal_log_entry_hash: Sha256 | None = None
    previous_entry_hash: Sha256 | None = None
    envelope_hash: Sha256

    @model_validator(mode="after")
    def _validate_envelope(self) -> SearchExecutionLogEnvelope:
        if self.sequence == 1 and self.previous_entry_hash is not None:
            raise ValueError("first execution envelope cannot have a predecessor")
        if self.sequence > 1 and self.previous_entry_hash is None:
            raise ValueError("later execution envelopes require a predecessor")
        if self.purpose is SearchPurpose.FORMAL_CENSUS:
            if self.formal_log_entry_hash is None:
                raise ValueError("formal run envelope requires the protocol log hash")
        elif self.formal_log_entry_hash is not None:
            raise ValueError("capability run cannot carry a formal log hash")
        if self.envelope_hash != self.calculated_hash():
            raise BenchmarkValidityHarnessIntegrityError("execution envelope mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> SearchExecutionLogEnvelope:
        payload = {
            "schema_version": "benchmark-search-execution-envelope-v1",
            **values,
        }
        return cls.model_validate(_addressed_payload(payload, "envelope_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"envelope_hash"})
        )


class SearchJournalSnapshot(KernelContract):
    """Immutable snapshot of both append-only chains and all raw bodies."""

    schema_version: Literal["benchmark-search-journal-snapshot-v1"] = (
        "benchmark-search-journal-snapshot-v1"
    )
    protocol_hash: Sha256
    page_entry_count: int = Field(ge=0)
    page_log_sha256: Sha256
    page_last_entry_hash: Sha256 | None = None
    execution_entry_count: int = Field(ge=0)
    execution_log_sha256: Sha256
    execution_last_entry_hash: Sha256 | None = None
    raw_response_hashes: list[Sha256]
    raw_response_bytes: int = Field(ge=0)
    bibliographic_record_hashes: list[Sha256]
    bibliographic_record_count: int = Field(ge=0)
    snapshot_hash: Sha256

    @field_validator("raw_response_hashes", "bibliographic_record_hashes")
    @classmethod
    def _sort_snapshot_hashes(cls, value: list[str]) -> list[str]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("snapshot artifact hashes must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_snapshot(self) -> SearchJournalSnapshot:
        if self.page_entry_count == 0 and self.page_last_entry_hash is not None:
            raise ValueError("empty page log cannot have a last hash")
        if self.execution_entry_count == 0 and self.execution_last_entry_hash is not None:
            raise ValueError("empty execution log cannot have a last hash")
        if self.bibliographic_record_count != len(self.bibliographic_record_hashes):
            raise ValueError("bibliographic snapshot count mismatch")
        if self.snapshot_hash != self.calculated_hash():
            raise BenchmarkValidityHarnessIntegrityError("journal snapshot mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> SearchJournalSnapshot:
        payload = {"schema_version": "benchmark-search-journal-snapshot-v1", **values}
        return cls.model_validate(_addressed_payload(payload, "snapshot_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"snapshot_hash"}))


class AppendOnlyPrismaJournal:
    """Durable raw-response store and append-only chained search journal."""

    def __init__(
        self,
        root: Path,
        *,
        protocol_hash: str,
        lock_timeout_seconds: float = 5.0,
        stale_lock_seconds: float = 120.0,
    ) -> None:
        self.root = root
        self.protocol_hash = protocol_hash
        self.page_log_path = root / HARNESS_PAGE_LOG_FILENAME
        self.execution_log_path = root / HARNESS_EXECUTION_LOG_FILENAME
        self.raw_root = root / HARNESS_RAW_DIRECTORY
        self.bibliographic_root = root / HARNESS_BIBLIOGRAPHIC_DIRECTORY
        self.lock_path = root / ".benchmark-search-journal.lock"
        self.lock_timeout_seconds = lock_timeout_seconds
        self.stale_lock_seconds = stale_lock_seconds
        self.root.mkdir(parents=True, exist_ok=True)
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.bibliographic_root.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _lock(self) -> Iterator[None]:
        deadline = time.monotonic() + self.lock_timeout_seconds
        acquired = False
        while not acquired:
            try:
                fd = os.open(
                    str(self.lock_path),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                try:
                    os.write(
                        fd,
                        _canonical_json_text(
                            {"pid": os.getpid(), "created_at": time.time()}
                        ).encode("utf-8"),
                    )
                finally:
                    os.close(fd)
                acquired = True
            except FileExistsError as exc:
                try:
                    stale = time.time() - self.lock_path.stat().st_mtime > self.stale_lock_seconds
                except FileNotFoundError:
                    continue
                if stale:
                    with suppress(FileNotFoundError):
                        self.lock_path.unlink()
                    continue
                if time.monotonic() >= deadline:
                    raise BenchmarkValidityHarnessIntegrityError(
                        f"search journal lock timed out: {self.lock_path}"
                    ) from exc
                time.sleep(0.025)
        try:
            yield
        finally:
            with suppress(FileNotFoundError):
                self.lock_path.unlink()

    @staticmethod
    def _read_jsonl(path: Path, model: type[_T]) -> list[_T]:
        if not path.exists():
            return []
        entries: list[_T] = []
        with path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.endswith("\n"):
                    raise BenchmarkValidityHarnessIntegrityError(
                        f"append-only log has a partial line at {path}:{line_number}"
                    )
                try:
                    entries.append(model.model_validate_json(line))
                except Exception as exc:
                    raise BenchmarkValidityHarnessIntegrityError(
                        f"invalid append-only entry at {path}:{line_number}"
                    ) from exc
        return entries

    @staticmethod
    def _append_jsonl(path: Path, model: BaseModel) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = (_canonical_json_text(model.model_dump(mode="json")) + "\n").encode(
            "utf-8"
        )
        with path.open("ab") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())

    def _verify_page_chain(
        self,
        entries: Sequence[SearchPageLogEntry],
        *,
        verify_raw: bool,
    ) -> None:
        previous: str | None = None
        for expected_sequence, entry in enumerate(entries, start=1):
            if entry.sequence != expected_sequence:
                raise BenchmarkValidityHarnessIntegrityError("page-log sequence gap")
            if entry.protocol_hash != self.protocol_hash:
                raise BenchmarkValidityHarnessIntegrityError("page log changed protocol")
            if entry.previous_entry_hash != previous:
                raise BenchmarkValidityHarnessIntegrityError("page-log chain mismatch")
            if verify_raw and entry.raw_response is not None:
                raw_path = self.root / entry.raw_response.relative_path
                if not raw_path.is_file():
                    raise BenchmarkValidityHarnessIntegrityError(
                        f"missing raw response: {raw_path}"
                    )
                if _file_sha256(raw_path) != entry.raw_response.body_sha256:
                    raise BenchmarkValidityHarnessIntegrityError(
                        f"raw response hash mismatch: {raw_path}"
                    )
            previous = entry.entry_hash

    def _verify_execution_chain(
        self,
        entries: Sequence[SearchExecutionLogEnvelope],
    ) -> None:
        previous: str | None = None
        for expected_sequence, entry in enumerate(entries, start=1):
            if entry.sequence != expected_sequence:
                raise BenchmarkValidityHarnessIntegrityError("execution-log sequence gap")
            if entry.protocol_hash != self.protocol_hash:
                raise BenchmarkValidityHarnessIntegrityError("execution log changed protocol")
            if entry.previous_entry_hash != previous:
                raise BenchmarkValidityHarnessIntegrityError("execution-log chain mismatch")
            previous = entry.envelope_hash

    def read_page_entries(self, *, verify_raw: bool = True) -> list[SearchPageLogEntry]:
        entries = self._read_jsonl(self.page_log_path, SearchPageLogEntry)
        self._verify_page_chain(entries, verify_raw=verify_raw)
        return entries

    def read_execution_entries(self) -> list[SearchExecutionLogEnvelope]:
        entries = self._read_jsonl(
            self.execution_log_path,
            SearchExecutionLogEnvelope,
        )
        self._verify_execution_chain(entries)
        return entries

    def append_page_attempt(
        self,
        *,
        request: SearchPageRequest,
        status: PageAttemptStatus,
        raw_response: RawResponseArtifact | None,
        body: bytes | None,
        parsed_page: ParsedSearchPage | None,
        retry_after_seconds: float | None,
        error_type: str | None,
    ) -> SearchPageLogEntry:
        with self._lock():
            entries = self.read_page_entries(verify_raw=True)
            if raw_response is not None:
                if body is None:
                    raise ValueError("raw response metadata requires exact body bytes")
                if _sha256_bytes(body) != raw_response.body_sha256:
                    raise BenchmarkValidityHarnessIntegrityError(
                        "raw response body does not match its envelope"
                    )
                _write_bytes_content_addressed(
                    self.root / raw_response.relative_path,
                    body,
                )
            elif body is not None:
                raise ValueError("unbound body bytes cannot enter the journal")
            entry = SearchPageLogEntry.create(
                sequence=len(entries) + 1,
                protocol_hash=self.protocol_hash,
                request=request,
                status=status,
                raw_response=raw_response,
                parsed_page_hash=parsed_page.parser_hash if parsed_page else None,
                parsed_record_count=len(parsed_page.records) if parsed_page else 0,
                retry_after_seconds=retry_after_seconds,
                error_type=error_type,
                previous_entry_hash=entries[-1].entry_hash if entries else None,
            )
            if parsed_page is not None:
                for record in parsed_page.records:
                    record_path = self.bibliographic_root / f"{record.record_hash}.json"
                    rendered = _canonical_json_text(record.model_dump(mode="json")) + "\n"
                    if record_path.exists():
                        loaded = BibliographicRecord.model_validate_json(
                            record_path.read_text(encoding="utf-8")
                        )
                        if loaded.record_hash != record.record_hash:
                            raise BenchmarkValidityHarnessIntegrityError(
                                f"bibliographic record changed: {record_path}"
                            )
                    else:
                        _write_text_atomic(record_path, rendered)
            self._append_jsonl(self.page_log_path, entry)
            self._verify_page_chain(
                [*entries, entry],
                verify_raw=True,
            )
            return entry

    def append_execution(self, summary: SearchRunSummary) -> SearchExecutionLogEnvelope:
        with self._lock():
            entries = self.read_execution_entries()
            envelope = SearchExecutionLogEnvelope.create(
                sequence=len(entries) + 1,
                protocol_hash=self.protocol_hash,
                purpose=summary.purpose,
                summary_hash=summary.summary_hash,
                formal_log_entry_hash=(
                    summary.protocol_search_log.log_entry_hash
                    if summary.protocol_search_log is not None
                    else None
                ),
                previous_entry_hash=entries[-1].envelope_hash if entries else None,
            )
            self._append_jsonl(self.execution_log_path, envelope)
            self._verify_execution_chain([*entries, envelope])
            return envelope

    def load_bibliographic_records(self) -> list[BibliographicRecord]:
        records: list[BibliographicRecord] = []
        for path in sorted(self.bibliographic_root.glob("*.json")):
            record = BibliographicRecord.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            if path.stem != record.record_hash:
                raise BenchmarkValidityHarnessIntegrityError(
                    f"bibliographic filename/hash mismatch: {path}"
                )
            records.append(record)
        return records

    def snapshot(self) -> SearchJournalSnapshot:
        page_entries = self.read_page_entries(verify_raw=True)
        execution_entries = self.read_execution_entries()
        raw_paths = sorted(self.raw_root.glob("*.bin"))
        raw_hashes: list[str] = []
        raw_bytes = 0
        for path in raw_paths:
            digest = _file_sha256(path)
            if path.stem != digest:
                raise BenchmarkValidityHarnessIntegrityError(
                    f"raw response filename/hash mismatch: {path}"
                )
            raw_hashes.append(digest)
            raw_bytes += path.stat().st_size
        records = self.load_bibliographic_records()
        page_log_hash = (
            _file_sha256(self.page_log_path)
            if self.page_log_path.exists()
            else _sha256_bytes(b"")
        )
        execution_log_hash = (
            _file_sha256(self.execution_log_path)
            if self.execution_log_path.exists()
            else _sha256_bytes(b"")
        )
        return SearchJournalSnapshot.create(
            protocol_hash=self.protocol_hash,
            page_entry_count=len(page_entries),
            page_log_sha256=page_log_hash,
            page_last_entry_hash=page_entries[-1].entry_hash if page_entries else None,
            execution_entry_count=len(execution_entries),
            execution_log_sha256=execution_log_hash,
            execution_last_entry_hash=(
                execution_entries[-1].envelope_hash if execution_entries else None
            ),
            raw_response_hashes=raw_hashes,
            raw_response_bytes=raw_bytes,
            bibliographic_record_hashes=[item.record_hash for item in records],
            bibliographic_record_count=len(records),
        )


def _safe_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        str(key).casefold(): _normalize_space(str(value))
        for key, value in headers.items()
        if str(key).casefold() in _SAFE_RESPONSE_HEADERS
    }


def _media_type(headers: Mapping[str, str], source_id: SearchSourceId) -> str:
    content_type = next(
        (
            str(value)
            for key, value in headers.items()
            if str(key).casefold() == "content-type"
        ),
        "",
    )
    if content_type:
        return content_type.split(";", 1)[0].strip().casefold()
    return "application/atom+xml" if source_id is SearchSourceId.ARXIV else "application/json"


def _retry_after(headers: Mapping[str, str]) -> float | None:
    raw = next(
        (
            str(value)
            for key, value in headers.items()
            if str(key).casefold() == "retry-after"
        ),
        None,
    )
    if raw is None:
        return None
    try:
        return min(max(float(raw), 0.0), 86_400.0)
    except ValueError:
        return None


class ResultBlindSearchHarness:
    """Execute frozen requests or one-page API capability probes."""

    def __init__(
        self,
        *,
        protocol: BenchmarkValidityProtocol,
        journal: AppendOnlyPrismaJournal,
        transport: HttpGetTransport = urllib_get_transport,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        timeout_seconds: float = 60.0,
        max_raw_response_bytes: int = MAX_RAW_RESPONSE_BYTES,
        allow_formal_execution: bool = False,
    ) -> None:
        protocol.verify_integrity()
        if protocol.protocol_hash != FROZEN_BENCHMARK_VALIDITY_PROTOCOL_HASH:
            raise BenchmarkValidityHarnessIntegrityError(
                "Harness is not bound to the committed Task 263.6.7.1 protocol"
            )
        if journal.protocol_hash != protocol.protocol_hash:
            raise ValueError("search journal is bound to another protocol")
        self.protocol = protocol
        self.journal = journal
        self.transport = transport
        self.now = now
        self.monotonic = monotonic
        self.sleep = sleep
        self.timeout_seconds = timeout_seconds
        self.max_raw_response_bytes = max_raw_response_bytes
        self.allow_formal_execution = allow_formal_execution
        self._last_request_at: float | None = None
        self._source_specs = {item.source_id: item for item in protocol.search_sources}

    def _pace(self, source_spec: SearchSourceSpec) -> None:
        current = self.monotonic()
        if self._last_request_at is not None:
            remaining = source_spec.request_spacing_seconds - (
                current - self._last_request_at
            )
            if remaining > 0:
                self.sleep(remaining)
                current = self.monotonic()
        self._last_request_at = current

    def execute_capability_probe(self, probe: CapabilityProbeSpec) -> SearchRunSummary:
        if probe.source_id not in self._source_specs:
            raise ValueError("capability probe source is outside the frozen protocol")
        return self._execute(
            purpose=SearchPurpose.API_CAPABILITY_SMOKE,
            query_or_probe_id=probe.probe_id,
            source_id=probe.source_id,
            endpoint_url=probe.endpoint_url,
            initial_parameters=probe.request_parameters,
        )

    def execute_formal_binding(self, binding_id: str) -> SearchRunSummary:
        if not self.allow_formal_execution:
            raise FormalSearchBlockedError(
                "formal search is disabled in Task 263.6.7.2 capability mode"
            )
        binding = next(
            (item for item in self.protocol.query_bindings if item.binding_id == binding_id),
            None,
        )
        if binding is None:
            raise ValueError(f"unknown frozen query binding: {binding_id}")
        blockers = [
            finding.finding_id
            for finding in audit_protocol_adapter_compatibility(self.protocol)
            if finding.source_id is binding.source_id
            and not finding.formal_search_allowed
        ]
        if blockers:
            raise FormalSearchBlockedError(
                f"formal {binding.source_id.value} search needs protocol erratum: {blockers}"
            )
        source_spec = self._source_specs[binding.source_id]
        return self._execute(
            purpose=SearchPurpose.FORMAL_CENSUS,
            query_or_probe_id=binding.binding_id,
            source_id=binding.source_id,
            endpoint_url=source_spec.endpoint_url,
            initial_parameters=binding.request_parameters,
        )

    def _execute(
        self,
        *,
        purpose: SearchPurpose,
        query_or_probe_id: str,
        source_id: SearchSourceId,
        endpoint_url: str,
        initial_parameters: Mapping[str, str],
    ) -> SearchRunSummary:
        started_at = self.now().astimezone(timezone.utc)
        source_spec = self._source_specs[source_id]
        parameters = dict(initial_parameters)
        page_index = 0
        page_logs: list[SearchPageLogEntry] = []
        raw_artifacts: list[RawResponseArtifact] = []
        records: list[BibliographicRecord] = []
        successful_pages = 0
        retry_count = 0
        completion_reason = "unreachable"
        run_status = SearchRunStatus.UNREACHABLE
        first_request_url_hash: str | None = None

        while True:
            parsed_page: ParsedSearchPage | None = None
            page_succeeded = False
            for attempt_index in range(source_spec.retry_count + 1):
                request = SearchPageRequest.create(
                    purpose=purpose,
                    query_or_probe_id=query_or_probe_id,
                    source_id=source_id,
                    page_index=page_index,
                    attempt_index=attempt_index,
                    endpoint_url=endpoint_url,
                    request_parameters=parameters,
                )
                if first_request_url_hash is None:
                    first_request_url_hash = request.request_url_sha256
                self._pace(source_spec)
                try:
                    response = self.transport(
                        endpoint_url=endpoint_url,
                        parameters=parameters,
                        headers={
                            "Accept": (
                                "application/atom+xml"
                                if source_id is SearchSourceId.ARXIV
                                else "application/json"
                            ),
                            "Accept-Encoding": "identity",
                            "User-Agent": "AutoResearch-benchmark-validity-harness/1.0",
                        },
                        timeout_seconds=self.timeout_seconds,
                        max_bytes=self.max_raw_response_bytes,
                    )
                except Exception as exc:  # noqa: BLE001 - transport boundary is recorded.
                    entry = self.journal.append_page_attempt(
                        request=request,
                        status=PageAttemptStatus.TRANSPORT_ERROR,
                        raw_response=None,
                        body=None,
                        parsed_page=None,
                        retry_after_seconds=None,
                        error_type=type(exc).__name__,
                    )
                    page_logs.append(entry)
                    if attempt_index < source_spec.retry_count:
                        retry_count += 1
                        self.sleep(min(float(2**attempt_index), 30.0))
                        continue
                    completion_reason = "transport-retries-exhausted"
                    break

                safe_headers = _safe_headers(response.headers)
                raw_artifact = RawResponseArtifact.create(
                    request_hash=request.request_hash,
                    received_at=self.now(),
                    status_code=response.status_code,
                    response_headers=safe_headers,
                    final_url=response.final_url,
                    media_type=_media_type(response.headers, source_id),
                    body=response.body,
                )
                raw_artifacts.append(raw_artifact)
                if not 200 <= response.status_code < 300:
                    retry_after = _retry_after(response.headers)
                    entry = self.journal.append_page_attempt(
                        request=request,
                        status=PageAttemptStatus.HTTP_ERROR,
                        raw_response=raw_artifact,
                        body=response.body,
                        parsed_page=None,
                        retry_after_seconds=retry_after,
                        error_type=f"http-{response.status_code}",
                    )
                    page_logs.append(entry)
                    if (
                        response.status_code in _RETRYABLE_STATUS_CODES
                        and attempt_index < source_spec.retry_count
                    ):
                        retry_count += 1
                        self.sleep(
                            retry_after
                            if retry_after is not None
                            else min(float(2**attempt_index), 30.0)
                        )
                        continue
                    completion_reason = f"http-{response.status_code}"
                    break

                try:
                    parsed_page = parse_search_page(
                        request=request,
                        artifact=raw_artifact,
                        body=response.body,
                    )
                except Exception as exc:  # noqa: BLE001 - raw bytes must survive parse failure.
                    entry = self.journal.append_page_attempt(
                        request=request,
                        status=PageAttemptStatus.PARSE_ERROR,
                        raw_response=raw_artifact,
                        body=response.body,
                        parsed_page=None,
                        retry_after_seconds=None,
                        error_type=type(exc).__name__,
                    )
                    page_logs.append(entry)
                    completion_reason = "response-parse-failed"
                    break

                entry = self.journal.append_page_attempt(
                    request=request,
                    status=PageAttemptStatus.SUCCEEDED,
                    raw_response=raw_artifact,
                    body=response.body,
                    parsed_page=parsed_page,
                    retry_after_seconds=None,
                    error_type=None,
                )
                page_logs.append(entry)
                records.extend(parsed_page.records)
                successful_pages += 1
                page_succeeded = True
                break

            if not page_succeeded or parsed_page is None:
                run_status = (
                    SearchRunStatus.PARTIAL
                    if successful_pages > 0
                    else SearchRunStatus.UNREACHABLE
                )
                break
            if purpose is SearchPurpose.API_CAPABILITY_SMOKE:
                run_status = SearchRunStatus.CAPABILITY_ONLY
                completion_reason = "one-page-capability-validated"
                break
            if parsed_page.requires_frozen_year_split:
                run_status = SearchRunStatus.PARTIAL
                completion_reason = "dblp-frozen-year-split-not-executable"
                break
            if parsed_page.exhausted:
                run_status = SearchRunStatus.COMPLETE
                completion_reason = "source-exhausted"
                break
            if parsed_page.next_parameters is None:
                run_status = SearchRunStatus.PARTIAL
                completion_reason = "pagination-state-missing"
                break
            page_index += 1
            if page_index >= 10_000:
                run_status = SearchRunStatus.PARTIAL
                completion_reason = "safety-page-cap-reached"
                break
            parameters = dict(parsed_page.next_parameters)

        completed_at = self.now().astimezone(timezone.utc)
        raw_hashes = [item.artifact_hash for item in raw_artifacts]
        record_hashes = [item.record_hash for item in records]
        formal_log = None
        if purpose is SearchPurpose.FORMAL_CENSUS:
            if first_request_url_hash is None:
                raise BenchmarkValidityHarnessIntegrityError(
                    "formal search did not construct a request"
                )
            formal_log = _create_protocol_search_log(
                binding_id=query_or_probe_id,
                executed_at=started_at,
                request_url_sha256=first_request_url_hash,
                response_artifact_sha256=canonical_sha256(raw_hashes),
                response_count=len(records),
                page_count=max(successful_pages, 1),
                status=(
                    "complete"
                    if run_status is SearchRunStatus.COMPLETE
                    else "partial"
                    if successful_pages > 0
                    else "unreachable"
                ),
                retry_count=min(retry_count, 5),
            )
        summary = SearchRunSummary.create(
            purpose=purpose,
            query_or_probe_id=query_or_probe_id,
            source_id=source_id,
            started_at=started_at,
            completed_at=completed_at,
            status=run_status,
            completion_reason=completion_reason,
            successful_page_count=successful_pages,
            request_attempt_count=len(page_logs),
            retry_count=retry_count,
            response_count=len(records),
            page_log_entry_hashes=[item.entry_hash for item in page_logs],
            raw_response_artifact_hashes=raw_hashes,
            bibliographic_record_hashes=record_hashes,
            protocol_search_log=formal_log,
            formal_search_execution=purpose is SearchPurpose.FORMAL_CENSUS,
        )
        self.journal.append_execution(summary)
        return summary


def build_adapter_contracts(
    protocol: BenchmarkValidityProtocol,
) -> list[AdapterContract]:
    """Project the frozen source specifications into executable adapters."""

    protocol.verify_integrity()
    bindings_by_source: dict[SearchSourceId, list[SourceQueryBinding]] = defaultdict(list)
    for binding in protocol.query_bindings:
        bindings_by_source[binding.source_id].append(binding)
    pagination_modes = {
        SearchSourceId.ARXIV: "offset-total",
        SearchSourceId.OPENALEX: "cursor-null",
        SearchSourceId.CROSSREF: "cursor-short-page",
        SearchSourceId.DBLP: "single-page-or-frozen-year-split",
    }
    contracts: list[AdapterContract] = []
    for source_spec in protocol.search_sources:
        parameter_names = {
            key
            for binding in bindings_by_source[source_spec.source_id]
            for key in binding.request_parameters
        }
        contracts.append(
            AdapterContract.create(
                source_id=source_spec.source_id,
                endpoint_url=source_spec.endpoint_url,
                response_format=source_spec.response_format,
                page_size=source_spec.page_size,
                initial_parameter_names=sorted(parameter_names),
                pagination_mode=pagination_modes[source_spec.source_id],
                parser_version="bibliographic-metadata-only-v1",
                benchmark_outcome_fields_parsed=False,
            )
        )
    return sorted(contracts, key=lambda item: item.source_id.value)


def audit_protocol_adapter_compatibility(
    protocol: BenchmarkValidityProtocol,
) -> list[ProtocolCompatibilityFinding]:
    """Audit API semantics without changing the committed protocol."""

    protocol.verify_integrity()
    source_specs = {item.source_id: item for item in protocol.search_sources}
    findings = [
        ProtocolCompatibilityFinding.create(
            finding_id="arxiv-offset-contract-compatible",
            source_id=SearchSourceId.ARXIV,
            severity=CompatibilitySeverity.INFORMATIONAL,
            frozen_rule=source_specs[SearchSourceId.ARXIV].pagination_rule,
            current_documented_rule=(
                "Use start and max_results for deterministic pages; totalResults "
                "provides the exhaustion bound and requests should be spaced."
            ),
            documentation_url=source_specs[SearchSourceId.ARXIV].documentation_url,
            formal_search_allowed=True,
            required_action="Retain exact raw Atom bytes and totalResults for every page.",
        ),
        ProtocolCompatibilityFinding.create(
            finding_id="openalex-cursor-contract-compatible",
            source_id=SearchSourceId.OPENALEX,
            severity=CompatibilitySeverity.INFORMATIONAL,
            frozen_rule=source_specs[SearchSourceId.OPENALEX].pagination_rule,
            current_documented_rule=(
                "Start cursor pagination with * and follow meta.next_cursor for "
                "deep paging until the service returns no continuation cursor."
            ),
            documentation_url=(
                "https://developers.openalex.org/guides/page-through-results"
            ),
            formal_search_allowed=True,
            required_action="Retain every raw JSON page before bibliographic parsing.",
        ),
        ProtocolCompatibilityFinding.create(
            finding_id="crossref-last-cursor-termination-mismatch",
            source_id=SearchSourceId.CROSSREF,
            severity=CompatibilitySeverity.FORMAL_BLOCKER,
            frozen_rule=source_specs[SearchSourceId.CROSSREF].pagination_rule,
            current_documented_rule=(
                "Crossref documents that next-cursor is returned even on the last "
                "page; exhaustion is detected when returned items are fewer than rows."
            ),
            documentation_url=(
                "https://www.crossref.org/documentation/retrieve-metadata/rest-api/"
                "tips-for-using-the-crossref-rest-api/"
            ),
            formal_search_allowed=False,
            required_action=(
                "Freeze a pre-extraction protocol erratum that replaces empty-cursor "
                "termination with the documented short-page rule."
            ),
        ),
        ProtocolCompatibilityFinding.create(
            finding_id="dblp-year-split-query-unspecified",
            source_id=SearchSourceId.DBLP,
            severity=CompatibilitySeverity.CONDITIONAL_BLOCKER,
            frozen_rule=source_specs[SearchSourceId.DBLP].pagination_rule,
            current_documented_rule=(
                "The publication API caps h at 1000 and supports f offsets, but the "
                "frozen protocol requires a year split without binding the four exact "
                "year-qualified backend queries."
            ),
            documentation_url=source_specs[SearchSourceId.DBLP].documentation_url,
            formal_search_allowed=True,
            required_action=(
                "If any DBLP query reports at least 1000 hits, stop partial and freeze "
                "exact 2023/2024/2025/2026 split bindings before continuing."
            ),
        ),
    ]
    return sorted(findings, key=lambda item: item.finding_id)


def build_capability_probe_specs(
    protocol: BenchmarkValidityProtocol,
) -> list[CapabilityProbeSpec]:
    """Create four one-page probes that cannot be mistaken for formal searches."""

    protocol.verify_integrity()
    title = (
        "CORE-Bench: Fostering the Credibility of Published Research Through a "
        "Computational Reproducibility Agent Benchmark"
    )
    endpoints = {item.source_id: item.endpoint_url for item in protocol.search_sources}
    probes = [
        CapabilityProbeSpec.create(
            probe_id="capability-arxiv-core-bench",
            source_id=SearchSourceId.ARXIV,
            endpoint_url=endpoints[SearchSourceId.ARXIV],
            request_parameters={
                "id_list": "2409.11363",
                "max_results": "1",
                "start": "0",
            },
            expected_response_format="atom-xml",
            known_item_title=title,
        ),
        CapabilityProbeSpec.create(
            probe_id="capability-openalex-core-bench",
            source_id=SearchSourceId.OPENALEX,
            endpoint_url=endpoints[SearchSourceId.OPENALEX],
            request_parameters={"per-page": "1", "search": title},
            expected_response_format="openalex-json",
            known_item_title=title,
        ),
        CapabilityProbeSpec.create(
            probe_id="capability-crossref-core-bench",
            source_id=SearchSourceId.CROSSREF,
            endpoint_url=endpoints[SearchSourceId.CROSSREF],
            request_parameters={
                "cursor": "*",
                "query.bibliographic": title,
                "rows": "1",
            },
            expected_response_format="crossref-json",
            known_item_title=title,
        ),
        CapabilityProbeSpec.create(
            probe_id="capability-dblp-core-bench",
            source_id=SearchSourceId.DBLP,
            endpoint_url=endpoints[SearchSourceId.DBLP],
            request_parameters={
                "c": "0",
                "f": "0",
                "format": "json",
                "h": "1",
                "q": "CORE-Bench",
            },
            expected_response_format="dblp-json",
            known_item_title=title,
        ),
    ]
    return sorted(probes, key=lambda item: item.source_id.value)


class PaperDedupCluster(KernelContract):
    """Exact bibliographic identity cluster, not a benchmark family decision."""

    schema_version: Literal["benchmark-paper-dedup-cluster-v1"] = (
        "benchmark-paper-dedup-cluster-v1"
    )
    paper_id: StableId
    primary_identity_key: str = Field(min_length=1, max_length=2_048)
    identity_keys: list[str]
    record_hashes: list[Sha256]
    source_ids: list[SearchSourceId]
    titles: list[str]
    publication_years: list[int]
    conflict_fields: list[StableId]
    benchmark_family_inferred: Literal[False] = False
    cluster_hash: Sha256

    @field_validator(
        "identity_keys",
        "record_hashes",
        "titles",
        "publication_years",
        "conflict_fields",
    )
    @classmethod
    def _sort_unique_values(cls, value: list[Any]) -> list[Any]:
        normalized = sorted(set(value))
        return normalized

    @field_validator("source_ids")
    @classmethod
    def _sort_sources(cls, value: list[SearchSourceId]) -> list[SearchSourceId]:
        return sorted(set(value), key=lambda item: item.value)

    @model_validator(mode="after")
    def _validate_cluster(self) -> PaperDedupCluster:
        if not self.identity_keys or not self.record_hashes:
            raise ValueError("paper cluster needs identity and source records")
        expected_id = f"paper-{_sha256_text(self.primary_identity_key)[:24]}"
        if self.paper_id != expected_id:
            raise ValueError("paper_id must derive from the primary identity")
        if self.cluster_hash != self.calculated_hash():
            raise BenchmarkValidityHarnessIntegrityError("paper cluster_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> PaperDedupCluster:
        primary_identity = str(values["primary_identity_key"])
        payload = {
            "schema_version": "benchmark-paper-dedup-cluster-v1",
            **values,
            "paper_id": f"paper-{_sha256_text(primary_identity)[:24]}",
            "identity_keys": sorted(set(values["identity_keys"])),
            "record_hashes": sorted(set(values["record_hashes"])),
            "source_ids": sorted(
                set(values["source_ids"]), key=lambda item: item.value
            ),
            "titles": sorted(set(values["titles"])),
            "publication_years": sorted(set(values["publication_years"])),
            "conflict_fields": sorted(set(values["conflict_fields"])),
            "benchmark_family_inferred": False,
        }
        return cls.model_validate(_addressed_payload(payload, "cluster_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"cluster_hash"}))


class PaperDeduplicationResult(KernelContract):
    schema_version: Literal["benchmark-paper-dedup-result-v1"] = (
        "benchmark-paper-dedup-result-v1"
    )
    input_record_hashes: list[Sha256]
    clusters: list[PaperDedupCluster]
    input_record_count: int = Field(ge=0)
    unique_paper_count: int = Field(ge=0)
    benchmark_family_count_claimed: Literal[False] = False
    result_hash: Sha256

    @field_validator("input_record_hashes")
    @classmethod
    def _record_hashes_unique(cls, value: list[str]) -> list[str]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("dedup input contains exact duplicate records")
        return normalized

    @field_validator("clusters")
    @classmethod
    def _sort_clusters(cls, value: list[PaperDedupCluster]) -> list[PaperDedupCluster]:
        normalized = sorted(value, key=lambda item: item.paper_id)
        if len({item.paper_id for item in normalized}) != len(normalized):
            raise ValueError("paper IDs must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_result(self) -> PaperDeduplicationResult:
        if self.input_record_count != len(self.input_record_hashes):
            raise ValueError("input-record count mismatch")
        if self.unique_paper_count != len(self.clusters):
            raise ValueError("unique-paper count mismatch")
        clustered = sorted(
            record_hash
            for cluster in self.clusters
            for record_hash in cluster.record_hashes
        )
        if clustered != self.input_record_hashes:
            raise ValueError("every bibliographic record must enter exactly one cluster")
        if self.result_hash != self.calculated_hash():
            raise BenchmarkValidityHarnessIntegrityError("paper dedup result mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> PaperDeduplicationResult:
        payload = {
            "schema_version": "benchmark-paper-dedup-result-v1",
            "benchmark_family_count_claimed": False,
            **values,
            "input_record_hashes": sorted(values["input_record_hashes"]),
            "clusters": sorted(values["clusters"], key=lambda item: item.paper_id),
        }
        return cls.model_validate(_addressed_payload(payload, "result_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"result_hash"}))


def _identity_rank(value: str) -> tuple[int, str]:
    prefixes = ["doi:", "arxiv:", "openalex:", "dblp:", "title-author-year:", "title:"]
    for index, prefix in enumerate(prefixes):
        if value.startswith(prefix):
            return index, value
    return len(prefixes), value


def deduplicate_bibliographic_records(
    records: Sequence[BibliographicRecord],
) -> PaperDeduplicationResult:
    """Deduplicate by the exact identity priority frozen in the protocol."""

    record_list = list(records)
    if len({item.record_hash for item in record_list}) != len(record_list):
        raise ValueError("exact duplicate bibliographic records must be removed first")
    parent = list(range(len(record_list)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root == right_root:
            return
        if left_root < right_root:
            parent[right_root] = left_root
        else:
            parent[left_root] = right_root

    first_by_identity: dict[str, int] = {}
    for index, record in enumerate(record_list):
        for identity in record.identity_keys():
            previous = first_by_identity.get(identity)
            if previous is None:
                first_by_identity[identity] = index
            else:
                union(index, previous)

    grouped: dict[int, list[BibliographicRecord]] = defaultdict(list)
    for index, record in enumerate(record_list):
        grouped[find(index)].append(record)

    clusters: list[PaperDedupCluster] = []
    for members in grouped.values():
        identity_keys = sorted(
            {identity for member in members for identity in member.identity_keys()},
            key=_identity_rank,
        )
        titles = sorted({member.title for member in members})
        years = sorted(
            {
                member.publication_year
                for member in members
                if member.publication_year is not None
            }
        )
        conflict_fields: list[str] = []
        if len({member.normalized_title for member in members}) > 1:
            conflict_fields.append("title")
        if len(years) > 1:
            conflict_fields.append("publication-year")
        dois = {member.doi for member in members if member.doi}
        if len(dois) > 1:
            conflict_fields.append("doi")
        clusters.append(
            PaperDedupCluster.create(
                primary_identity_key=identity_keys[0],
                identity_keys=identity_keys,
                record_hashes=[member.record_hash for member in members],
                source_ids=[member.source_id for member in members],
                titles=titles,
                publication_years=years,
                conflict_fields=conflict_fields,
            )
        )
    return PaperDeduplicationResult.create(
        input_record_hashes=[item.record_hash for item in record_list],
        clusters=clusters,
        input_record_count=len(record_list),
        unique_paper_count=len(clusters),
    )


class KnownItemMatch(KernelContract):
    sentinel_id: StableId
    matched: bool
    paper_ids: list[StableId]
    match_basis: list[Literal["stable-locator", "exact-normalized-title"]]

    @field_validator("paper_ids", "match_basis")
    @classmethod
    def _sort_match_values(cls, value: list[Any]) -> list[Any]:
        return sorted(set(value))

    @model_validator(mode="after")
    def _validate_match(self) -> KnownItemMatch:
        if self.matched != bool(self.paper_ids):
            raise ValueError("known-item match flag must follow matched papers")
        if self.matched != bool(self.match_basis):
            raise ValueError("known-item match basis must follow matched papers")
        return self


class KnownItemRecallReport(KernelContract):
    schema_version: Literal["benchmark-known-item-recall-v1"] = (
        "benchmark-known-item-recall-v1"
    )
    protocol_hash: Sha256
    matches: list[KnownItemMatch]
    known_item_count: int = Field(ge=1)
    matched_count: int = Field(ge=0)
    recall: float = Field(ge=0, le=1)
    threshold: float = Field(ge=0.9, le=1)
    threshold_passed: bool
    formal_recall_claim: bool
    report_hash: Sha256

    @field_validator("matches")
    @classmethod
    def _sort_matches(cls, value: list[KnownItemMatch]) -> list[KnownItemMatch]:
        normalized = sorted(value, key=lambda item: item.sentinel_id)
        if len({item.sentinel_id for item in normalized}) != len(normalized):
            raise ValueError("known-item sentinels must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_recall(self) -> KnownItemRecallReport:
        if self.known_item_count != len(self.matches):
            raise ValueError("known-item denominator mismatch")
        if self.matched_count != sum(item.matched for item in self.matches):
            raise ValueError("known-item numerator mismatch")
        expected = self.matched_count / self.known_item_count
        if abs(self.recall - expected) > 1e-12:
            raise ValueError("known-item recall ratio mismatch")
        if self.threshold_passed != (self.recall >= self.threshold):
            raise ValueError("known-item threshold decision mismatch")
        if self.report_hash != self.calculated_hash():
            raise BenchmarkValidityHarnessIntegrityError("known-item report mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> KnownItemRecallReport:
        payload = {"schema_version": "benchmark-known-item-recall-v1", **values}
        return cls.model_validate(_addressed_payload(payload, "report_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"report_hash"}))


def _locator_tokens(value: str) -> set[str]:
    lowered = value.casefold().strip()
    tokens = {lowered}
    if arxiv_id := normalize_arxiv_id(lowered):
        tokens.add(f"arxiv:{arxiv_id}")
    if (
        lowered.startswith("doi:") or "doi.org/" in lowered
    ) and (doi := normalize_doi(lowered)):
        tokens.add(f"doi:{doi}")
    return tokens


def evaluate_known_item_recall(
    *,
    protocol: BenchmarkValidityProtocol,
    records: Sequence[BibliographicRecord],
    deduplication: PaperDeduplicationResult,
    formal_recall_claim: bool,
) -> KnownItemRecallReport:
    """Evaluate frozen sentinels; capability records cannot claim formal recall."""

    protocol.verify_integrity()
    records_by_hash = {item.record_hash: item for item in records}
    matches: list[KnownItemMatch] = []
    for sentinel in protocol.known_item_sentinels:
        sentinel_title = normalize_title(sentinel.title)
        sentinel_locators = _locator_tokens(sentinel.stable_locator)
        paper_ids: list[str] = []
        bases: set[Literal["stable-locator", "exact-normalized-title"]] = set()
        for cluster in deduplication.clusters:
            cluster_records = [records_by_hash[item] for item in cluster.record_hashes]
            title_match = any(
                item.normalized_title == sentinel_title for item in cluster_records
            )
            locator_match = any(
                bool(
                    sentinel_locators
                    & (
                        _locator_tokens(item.stable_locator)
                        | set(item.identity_keys())
                    )
                )
                for item in cluster_records
            )
            if title_match or locator_match:
                paper_ids.append(cluster.paper_id)
                if title_match:
                    bases.add("exact-normalized-title")
                if locator_match:
                    bases.add("stable-locator")
        matches.append(
            KnownItemMatch(
                sentinel_id=sentinel.sentinel_id,
                matched=bool(paper_ids),
                paper_ids=paper_ids,
                match_basis=sorted(bases),
            )
        )
    matched_count = sum(item.matched for item in matches)
    recall = matched_count / len(matches)
    return KnownItemRecallReport.create(
        protocol_hash=protocol.protocol_hash,
        matches=matches,
        known_item_count=len(matches),
        matched_count=matched_count,
        recall=recall,
        threshold=protocol.known_item_recall_threshold,
        threshold_passed=recall >= protocol.known_item_recall_threshold,
        formal_recall_claim=formal_recall_claim,
    )


class FamilyLineageObservation(KernelContract):
    """Explicit lineage metadata used for deterministic clustering only."""

    schema_version: Literal["benchmark-family-lineage-observation-v1"] = (
        "benchmark-family-lineage-observation-v1"
    )
    observation_id: StableId
    paper_id: StableId
    benchmark_family_id: StableId
    release_id: StableId
    release_date: date
    paper_revision: NonEmptyText
    repository_revision: NonEmptyText | None = None
    dataset_revision: NonEmptyText | None = None
    lineage_keys: list[StableId]
    related_family_ids: list[StableId] = Field(default_factory=list)
    nested_technical_task_count: int = Field(ge=0)
    protocol_development_pilot: bool
    independently_human_validated: bool
    benchmark_outcomes_accessed: Literal[False] = False
    observation_hash: Sha256

    @field_validator("lineage_keys", "related_family_ids")
    @classmethod
    def _sort_lineage_values(cls, value: list[str]) -> list[str]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("family lineage identifiers must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_observation(self) -> FamilyLineageObservation:
        if self.release_date > SEARCH_CUTOFF_DATE:
            raise ValueError("post-cutoff releases cannot enter the frozen map")
        if self.observation_hash != self.calculated_hash():
            raise BenchmarkValidityHarnessIntegrityError("lineage observation mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> FamilyLineageObservation:
        payload = {
            "schema_version": "benchmark-family-lineage-observation-v1",
            "repository_revision": None,
            "dataset_revision": None,
            "benchmark_outcomes_accessed": False,
            **values,
            "lineage_keys": sorted(values["lineage_keys"]),
            "related_family_ids": sorted(values.get("related_family_ids", [])),
        }
        _walk_forbidden(payload)
        return cls.model_validate(_addressed_payload(payload, "observation_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"observation_hash"})
        )

    def cluster_keys(self) -> list[str]:
        return sorted(
            {
                f"family:{self.benchmark_family_id}",
                *(f"family:{item}" for item in self.related_family_ids),
                *(f"lineage:{item}" for item in self.lineage_keys),
            }
        )


class FamilyRevisionAssignment(KernelContract):
    observation_hash: Sha256
    release_id: StableId
    role: FamilyRevisionRole


class FamilyRevisionCluster(KernelContract):
    """One independent family with revisions/tasks retained as nested evidence."""

    schema_version: Literal["benchmark-family-revision-cluster-v1"] = (
        "benchmark-family-revision-cluster-v1"
    )
    cluster_id: StableId
    family_ids: list[StableId]
    lineage_keys: list[StableId]
    assignments: list[FamilyRevisionAssignment]
    selected_primary_release_id: StableId | None = None
    independent_unit_count: Literal[1] = 1
    nested_technical_task_count: int = Field(ge=0)
    protocol_development_pilot: bool
    all_members_human_validated: bool
    primary_cohort_eligible: bool
    cluster_hash: Sha256

    @field_validator("family_ids", "lineage_keys")
    @classmethod
    def _sort_ids(cls, value: list[str]) -> list[str]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("family cluster identifiers must be unique")
        return normalized

    @field_validator("assignments")
    @classmethod
    def _sort_assignments(
        cls,
        value: list[FamilyRevisionAssignment],
    ) -> list[FamilyRevisionAssignment]:
        normalized = sorted(value, key=lambda item: (item.release_id, item.observation_hash))
        if len({item.observation_hash for item in normalized}) != len(normalized):
            raise ValueError("lineage observations cannot be assigned twice")
        return normalized

    @model_validator(mode="after")
    def _validate_cluster(self) -> FamilyRevisionCluster:
        primary = [
            item
            for item in self.assignments
            if item.role is FamilyRevisionRole.PRIMARY_CROSS_SECTIONAL
        ]
        pilots = [
            item
            for item in self.assignments
            if item.role is FamilyRevisionRole.PROTOCOL_PILOT
        ]
        if self.protocol_development_pilot:
            if len(pilots) != len(self.assignments) or self.selected_primary_release_id is not None:
                raise ValueError("protocol pilots cannot produce a primary release")
        else:
            if len(primary) != 1:
                raise ValueError("non-pilot family needs exactly one latest primary revision")
            if self.selected_primary_release_id != primary[0].release_id:
                raise ValueError("selected primary release does not match assignment")
        expected_eligible = (
            not self.protocol_development_pilot and self.all_members_human_validated
        )
        if self.primary_cohort_eligible != expected_eligible:
            raise ValueError("family eligibility must remain human-validation gated")
        if self.cluster_hash != self.calculated_hash():
            raise BenchmarkValidityHarnessIntegrityError("family cluster mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> FamilyRevisionCluster:
        payload = {
            "schema_version": "benchmark-family-revision-cluster-v1",
            "independent_unit_count": 1,
            **values,
        }
        return cls.model_validate(_addressed_payload(payload, "cluster_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"cluster_hash"}))


class FamilyRevisionDeduplicationResult(KernelContract):
    schema_version: Literal["benchmark-family-revision-dedup-v1"] = (
        "benchmark-family-revision-dedup-v1"
    )
    protocol_hash: Sha256
    observation_hashes: list[Sha256]
    clusters: list[FamilyRevisionCluster]
    input_observation_count: int = Field(ge=0)
    independent_family_count: int = Field(ge=0)
    primary_non_pilot_family_count: int = Field(ge=0)
    human_validated_primary_family_count: int = Field(ge=0)
    task_seed_attempt_difficulty_votes_count_as_units: Literal[False] = False
    result_hash: Sha256

    @field_validator("observation_hashes")
    @classmethod
    def _unique_observations(cls, value: list[str]) -> list[str]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("family observations must be unique")
        return normalized

    @field_validator("clusters")
    @classmethod
    def _sort_family_clusters(
        cls,
        value: list[FamilyRevisionCluster],
    ) -> list[FamilyRevisionCluster]:
        return sorted(value, key=lambda item: item.cluster_id)

    @model_validator(mode="after")
    def _validate_result(self) -> FamilyRevisionDeduplicationResult:
        if self.input_observation_count != len(self.observation_hashes):
            raise ValueError("family observation count mismatch")
        if self.independent_family_count != len(self.clusters):
            raise ValueError("independent family count mismatch")
        assigned = sorted(
            item.observation_hash
            for cluster in self.clusters
            for item in cluster.assignments
        )
        if assigned != self.observation_hashes:
            raise ValueError("every lineage observation must be clustered once")
        expected_primary = sum(
            not item.protocol_development_pilot for item in self.clusters
        )
        expected_validated = sum(item.primary_cohort_eligible for item in self.clusters)
        if self.primary_non_pilot_family_count != expected_primary:
            raise ValueError("primary non-pilot family count mismatch")
        if self.human_validated_primary_family_count != expected_validated:
            raise ValueError("human-validated family count mismatch")
        if self.result_hash != self.calculated_hash():
            raise BenchmarkValidityHarnessIntegrityError("family dedup result mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> FamilyRevisionDeduplicationResult:
        payload = {
            "schema_version": "benchmark-family-revision-dedup-v1",
            "task_seed_attempt_difficulty_votes_count_as_units": False,
            **values,
            "observation_hashes": sorted(values["observation_hashes"]),
            "clusters": sorted(values["clusters"], key=lambda item: item.cluster_id),
        }
        return cls.model_validate(_addressed_payload(payload, "result_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"result_hash"}))


def deduplicate_family_revisions(
    *,
    protocol: BenchmarkValidityProtocol,
    observations: Sequence[FamilyLineageObservation],
) -> FamilyRevisionDeduplicationResult:
    """Cluster only explicit lineage keys; never infer family from paper title."""

    protocol.verify_integrity()
    values = list(observations)
    if len({item.observation_hash for item in values}) != len(values):
        raise ValueError("duplicate lineage observations are forbidden")
    pilot_ids = {item.release_id for item in protocol.pilot_boundaries}
    for item in values:
        known_pilot = (
            item.release_id in pilot_ids or item.benchmark_family_id in pilot_ids
        )
        if known_pilot != item.protocol_development_pilot:
            raise ValueError("Task 263.6.6 pilot boundary mismatch")
    parent = list(range(len(values)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root == right_root:
            return
        if left_root < right_root:
            parent[right_root] = left_root
        else:
            parent[left_root] = right_root

    first_by_key: dict[str, int] = {}
    for index, item in enumerate(values):
        for key in item.cluster_keys():
            previous = first_by_key.get(key)
            if previous is None:
                first_by_key[key] = index
            else:
                union(index, previous)
    grouped: dict[int, list[FamilyLineageObservation]] = defaultdict(list)
    for index, item in enumerate(values):
        grouped[find(index)].append(item)

    clusters: list[FamilyRevisionCluster] = []
    for members in grouped.values():
        pilot = any(item.protocol_development_pilot for item in members)
        if pilot and not all(item.protocol_development_pilot for item in members):
            raise ValueError("pilot lineage cannot merge into a prospective family")
        ordered = sorted(
            members,
            key=lambda item: (
                item.release_date,
                item.paper_revision,
                item.repository_revision or "",
                item.dataset_revision or "",
                item.release_id,
            ),
        )
        selected = None if pilot else ordered[-1]
        assignments = []
        for item in ordered:
            if pilot:
                role = FamilyRevisionRole.PROTOCOL_PILOT
            elif item.observation_hash == cast(FamilyLineageObservation, selected).observation_hash:
                role = FamilyRevisionRole.PRIMARY_CROSS_SECTIONAL
            else:
                role = FamilyRevisionRole.LONGITUDINAL_ONLY
            assignments.append(
                FamilyRevisionAssignment(
                    observation_hash=item.observation_hash,
                    release_id=item.release_id,
                    role=role,
                )
            )
        family_ids = sorted(
            {
                item.benchmark_family_id
                for item in members
            }
            | {
                related
                for item in members
                for related in item.related_family_ids
            }
        )
        lineage_keys = sorted(
            {key for item in members for key in item.lineage_keys}
        )
        cluster_seed = "|".join([*family_ids, *lineage_keys])
        all_validated = all(item.independently_human_validated for item in members)
        clusters.append(
            FamilyRevisionCluster.create(
                cluster_id=f"family-{_sha256_text(cluster_seed)[:24]}",
                family_ids=family_ids,
                lineage_keys=lineage_keys,
                assignments=assignments,
                selected_primary_release_id=selected.release_id if selected else None,
                nested_technical_task_count=sum(
                    item.nested_technical_task_count for item in members
                ),
                protocol_development_pilot=pilot,
                all_members_human_validated=all_validated,
                primary_cohort_eligible=not pilot and all_validated,
            )
        )
    return FamilyRevisionDeduplicationResult.create(
        protocol_hash=protocol.protocol_hash,
        observation_hashes=[item.observation_hash for item in values],
        clusters=clusters,
        input_observation_count=len(values),
        independent_family_count=len(clusters),
        primary_non_pilot_family_count=sum(
            not item.protocol_development_pilot for item in clusters
        ),
        human_validated_primary_family_count=sum(
            item.primary_cohort_eligible for item in clusters
        ),
    )


class FrozenScreeningCriterion(KernelContract):
    criterion_id: StableId
    frozen_decision: Literal["include", "exclude"]
    rule: str = Field(min_length=1, max_length=2_048)
    evidence_required: str = Field(min_length=1, max_length=2_048)
    reviewer_a_decision: None = None
    reviewer_b_decision: None = None
    adjudicated_decision: None = None


class FrozenScreeningFormTemplate(KernelContract):
    schema_version: Literal["benchmark-screening-form-template-v1"] = (
        "benchmark-screening-form-template-v1"
    )
    protocol_hash: Sha256
    reviewer_roles: list[StableId]
    adjudicator_role: StableId
    actual_human_identities_assigned: Literal[False] = False
    criteria: list[FrozenScreeningCriterion]
    decisions_created: Literal[False] = False
    llm_screening_allowed: Literal[False] = False
    form_hash: Sha256

    @field_validator("reviewer_roles")
    @classmethod
    def _sort_reviewer_roles(cls, value: list[str]) -> list[str]:
        return sorted(value)

    @field_validator("criteria")
    @classmethod
    def _sort_criteria(
        cls,
        value: list[FrozenScreeningCriterion],
    ) -> list[FrozenScreeningCriterion]:
        return sorted(value, key=lambda item: item.criterion_id)

    @model_validator(mode="after")
    def _validate_form(self) -> FrozenScreeningFormTemplate:
        if len(self.reviewer_roles) != 2 or self.adjudicator_role in self.reviewer_roles:
            raise ValueError("screening form must retain two reviewers and one adjudicator")
        if self.form_hash != self.calculated_hash():
            raise BenchmarkValidityHarnessIntegrityError("screening form mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> FrozenScreeningFormTemplate:
        payload = {
            "schema_version": "benchmark-screening-form-template-v1",
            "actual_human_identities_assigned": False,
            "decisions_created": False,
            "llm_screening_allowed": False,
            **values,
        }
        return cls.model_validate(_addressed_payload(payload, "form_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"form_hash"}))


def build_frozen_screening_form(
    protocol: BenchmarkValidityProtocol,
) -> FrozenScreeningFormTemplate:
    protocol.verify_integrity()
    return FrozenScreeningFormTemplate.create(
        protocol_hash=protocol.protocol_hash,
        reviewer_roles=protocol.human_coding_plan.reviewer_roles,
        adjudicator_role=protocol.human_coding_plan.adjudicator_role,
        criteria=[
            FrozenScreeningCriterion(
                criterion_id=item.criterion_id,
                frozen_decision=item.decision,
                rule=item.rule,
                evidence_required=item.evidence_required,
            )
            for item in protocol.eligibility_criteria
        ],
    )


class EmptyEvidenceField(KernelContract):
    """One unfilled codebook slot; absence is not yet a not-reported decision."""

    field_id: StableId
    critical: bool
    dual_human_code_required: bool
    admission_gate: AdmissionGate | None = None
    value_present: Literal[False] = False
    evidence_state: None = None
    evidence_locators: list[None] = Field(default_factory=list, max_length=0)
    reviewer_a_locked: Literal[False] = False
    reviewer_b_locked: Literal[False] = False
    adjudicated: Literal[False] = False


class EmptyAdmissionEvidencePacketTemplate(KernelContract):
    schema_version: Literal["benchmark-empty-evidence-packet-template-v1"] = (
        "benchmark-empty-evidence-packet-template-v1"
    )
    protocol_hash: Sha256
    fields: list[EmptyEvidenceField]
    field_count: int = Field(ge=40)
    screening_decision: None = None
    benchmark_family_decision: None = None
    admission_card_created: Literal[False] = False
    benchmark_outcomes_accessed: Literal[False] = False
    candidate_model_calls: Literal[False] = False
    template_hash: Sha256

    @field_validator("fields")
    @classmethod
    def _sort_empty_fields(cls, value: list[EmptyEvidenceField]) -> list[EmptyEvidenceField]:
        normalized = sorted(value, key=lambda item: item.field_id)
        if len({item.field_id for item in normalized}) != len(normalized):
            raise ValueError("empty evidence fields must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_template(self) -> EmptyAdmissionEvidencePacketTemplate:
        if self.field_count != len(self.fields):
            raise ValueError("empty evidence field count mismatch")
        if self.template_hash != self.calculated_hash():
            raise BenchmarkValidityHarnessIntegrityError("empty packet template mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> EmptyAdmissionEvidencePacketTemplate:
        payload = {
            "schema_version": "benchmark-empty-evidence-packet-template-v1",
            "screening_decision": None,
            "benchmark_family_decision": None,
            "admission_card_created": False,
            "benchmark_outcomes_accessed": False,
            "candidate_model_calls": False,
            **values,
        }
        return cls.model_validate(_addressed_payload(payload, "template_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"template_hash"}))


def _empty_field(field: ExtractionFieldSpec) -> EmptyEvidenceField:
    return EmptyEvidenceField(
        field_id=field.field_id,
        critical=field.critical,
        dual_human_code_required=field.dual_human_code_required,
        admission_gate=field.admission_gate,
    )


def build_empty_evidence_packet_template(
    protocol: BenchmarkValidityProtocol,
) -> EmptyAdmissionEvidencePacketTemplate:
    protocol.verify_integrity()
    return EmptyAdmissionEvidencePacketTemplate.create(
        protocol_hash=protocol.protocol_hash,
        fields=[_empty_field(item) for item in protocol.extraction_codebook],
        field_count=len(protocol.extraction_codebook),
    )


class EmptyAdmissionEvidencePacket(KernelContract):
    schema_version: Literal["benchmark-empty-evidence-packet-v1"] = (
        "benchmark-empty-evidence-packet-v1"
    )
    packet_id: StableId
    protocol_hash: Sha256
    paper_id: StableId
    paper_cluster_hash: Sha256
    bibliographic_title: str = Field(min_length=1, max_length=1_024)
    fields: list[EmptyEvidenceField]
    screening_decision: None = None
    benchmark_family_decision: None = None
    primary_cohort_eligible: None = None
    actual_human_identities_assigned: Literal[False] = False
    admission_card_created: Literal[False] = False
    benchmark_outcomes_accessed: Literal[False] = False
    candidate_model_calls: Literal[False] = False
    packet_hash: Sha256

    @field_validator("fields")
    @classmethod
    def _sort_packet_fields(cls, value: list[EmptyEvidenceField]) -> list[EmptyEvidenceField]:
        return sorted(value, key=lambda item: item.field_id)

    @model_validator(mode="after")
    def _validate_packet(self) -> EmptyAdmissionEvidencePacket:
        expected_id = f"packet-{_sha256_text(self.paper_cluster_hash)[:24]}"
        if self.packet_id != expected_id:
            raise ValueError("empty packet ID must derive from the paper cluster")
        if self.packet_hash != self.calculated_hash():
            raise BenchmarkValidityHarnessIntegrityError("empty evidence packet mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> EmptyAdmissionEvidencePacket:
        _walk_forbidden(values)
        cluster_hash = str(values["paper_cluster_hash"])
        payload = {
            "schema_version": "benchmark-empty-evidence-packet-v1",
            "packet_id": f"packet-{_sha256_text(cluster_hash)[:24]}",
            "screening_decision": None,
            "benchmark_family_decision": None,
            "primary_cohort_eligible": None,
            "actual_human_identities_assigned": False,
            "admission_card_created": False,
            "benchmark_outcomes_accessed": False,
            "candidate_model_calls": False,
            **values,
        }
        return cls.model_validate(_addressed_payload(payload, "packet_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"packet_hash"}))


def build_empty_evidence_packet(
    *,
    protocol: BenchmarkValidityProtocol,
    paper_cluster: PaperDedupCluster,
) -> EmptyAdmissionEvidencePacket:
    protocol.verify_integrity()
    title = sorted(paper_cluster.titles, key=lambda item: (len(item), item))[0]
    return EmptyAdmissionEvidencePacket.create(
        protocol_hash=protocol.protocol_hash,
        paper_id=paper_cluster.paper_id,
        paper_cluster_hash=paper_cluster.cluster_hash,
        bibliographic_title=title,
        fields=[_empty_field(item) for item in protocol.extraction_codebook],
    )


class BenchmarkValidityHarnessProjection(KernelContract):
    """Result-blind projection accepted by the dependency-free replay probe."""

    schema_version: Literal["benchmark-validity-harness-projection-v1"] = (
        "benchmark-validity-harness-projection-v1"
    )
    protocol_hash: Sha256
    adapter_hashes: dict[SearchSourceId, Sha256]
    compatibility_finding_hashes: list[Sha256]
    formal_blocker_ids: list[StableId]
    capability_probe_hashes: list[Sha256]
    capability_run_hashes: list[Sha256]
    journal_snapshot_hash: Sha256
    paper_deduplication_hash: Sha256
    known_item_recall_hash: Sha256
    known_item_formal_recall_claim: Literal[False] = False
    family_revision_deduplication_hash: Sha256
    screening_form_hash: Sha256
    empty_packet_template_hash: Sha256
    raw_response_count: int = Field(ge=4)
    bibliographic_record_count: int = Field(ge=0)
    capability_probe_count: Literal[4] = 4
    formal_search_execution_count: Literal[0] = 0
    empty_evidence_packet_count: Literal[0] = 0
    admission_card_count: Literal[0] = 0
    actual_human_identities_assigned: Literal[False] = False
    benchmark_outcomes_accessed: Literal[False] = False
    candidate_model_calls: Literal[False] = False
    mechanism_effect_claim_authorized: Literal[False] = False
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    formal_census_authorized: Literal[False] = False
    protocol_erratum_required: Literal[True] = True
    projection_sha256: Sha256

    @field_validator("adapter_hashes")
    @classmethod
    def _sort_adapter_hashes(
        cls,
        value: dict[SearchSourceId, str],
    ) -> dict[SearchSourceId, str]:
        return dict(sorted(value.items(), key=lambda item: item[0].value))

    @field_validator(
        "compatibility_finding_hashes",
        "formal_blocker_ids",
        "capability_probe_hashes",
        "capability_run_hashes",
    )
    @classmethod
    def _sort_projection_lists(cls, value: list[Any]) -> list[Any]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("Harness projection lists must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_projection(self) -> BenchmarkValidityHarnessProjection:
        if set(self.adapter_hashes) != set(SearchSourceId):
            raise ValueError("Harness projection requires all four adapters")
        if len(self.capability_probe_hashes) != 4 or len(self.capability_run_hashes) != 4:
            raise ValueError("Harness projection requires four capability probes")
        if "crossref-last-cursor-termination-mismatch" not in self.formal_blocker_ids:
            raise ValueError("known Crossref protocol blocker must remain explicit")
        if self.projection_sha256 != self.calculated_hash():
            raise BenchmarkValidityHarnessIntegrityError("Harness projection mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> BenchmarkValidityHarnessProjection:
        adapter_hashes = cast(
            Mapping[SearchSourceId, str],
            values["adapter_hashes"],
        )
        list_fields = (
            "compatibility_finding_hashes",
            "formal_blocker_ids",
            "capability_probe_hashes",
            "capability_run_hashes",
        )
        payload = {
            "schema_version": "benchmark-validity-harness-projection-v1",
            "known_item_formal_recall_claim": False,
            "capability_probe_count": 4,
            "formal_search_execution_count": 0,
            "empty_evidence_packet_count": 0,
            "admission_card_count": 0,
            "actual_human_identities_assigned": False,
            "benchmark_outcomes_accessed": False,
            "candidate_model_calls": False,
            "mechanism_effect_claim_authorized": False,
            "public_release_authorized": False,
            "external_submission_authorized": False,
            "formal_census_authorized": False,
            "protocol_erratum_required": True,
            **values,
            "adapter_hashes": dict(
                sorted(adapter_hashes.items(), key=lambda item: item[0].value)
            ),
            **{field: sorted(values[field]) for field in list_fields},
        }
        _walk_forbidden(payload)
        return cls.model_validate(_addressed_payload(payload, "projection_sha256"))

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"projection_sha256"})
        )

    def runner_projection(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"projection_sha256"})


class HarnessReplayObservation(KernelContract):
    schema_version: Literal["benchmark-validity-harness-replay-observation-v1"] = (
        "benchmark-validity-harness-replay-observation-v1"
    )
    runtime: InterpreterRuntime
    projection_sha256: Sha256
    output_file_sha256: Sha256
    output_contract_sha256: Sha256
    benchmark_outcomes_accessed: Literal[False] = False
    candidate_model_calls: Literal[False] = False
    observation_hash: Sha256

    @model_validator(mode="after")
    def _validate_observation(self) -> HarnessReplayObservation:
        if self.observation_hash != self.calculated_hash():
            raise BenchmarkValidityHarnessIntegrityError("Harness replay observation mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> HarnessReplayObservation:
        payload = {
            "schema_version": "benchmark-validity-harness-replay-observation-v1",
            "benchmark_outcomes_accessed": False,
            "candidate_model_calls": False,
            **values,
        }
        return cls.model_validate(_addressed_payload(payload, "observation_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"observation_hash"})
        )


class HarnessReplayCertificate(KernelContract):
    schema_version: Literal["benchmark-validity-harness-replay-certificate-v1"] = (
        "benchmark-validity-harness-replay-certificate-v1"
    )
    protocol_hash: Sha256
    projection_sha256: Sha256
    replay_input_sha256: Sha256
    frozen_runner_sha256: Sha256
    observations: list[HarnessReplayObservation] = Field(min_length=2, max_length=2)
    exact_projection_match: Literal[True] = True
    distinct_interpreter_installations: Literal[True] = True
    benchmark_outcomes_accessed: Literal[False] = False
    candidate_model_calls: Literal[False] = False
    certificate_hash: Sha256

    @field_validator("observations")
    @classmethod
    def _sort_observations(
        cls,
        value: list[HarnessReplayObservation],
    ) -> list[HarnessReplayObservation]:
        normalized = sorted(value, key=lambda item: item.runtime.role_id)
        if len({item.runtime.role_id for item in normalized}) != 2:
            raise ValueError("Harness replay requires two distinct roles")
        return normalized

    @model_validator(mode="after")
    def _validate_certificate(self) -> HarnessReplayCertificate:
        if any(item.projection_sha256 != self.projection_sha256 for item in self.observations):
            raise ValueError("Harness replay projections differ")
        environment_hashes = {
            item.runtime.environment_hash for item in self.observations
        }
        if len(environment_hashes) != 2:
            raise ValueError("Harness replay needs distinct interpreter installations")
        output_hashes = {item.output_contract_sha256 for item in self.observations}
        if len(output_hashes) != 1:
            raise ValueError("Harness replay output contracts differ")
        if self.certificate_hash != self.calculated_hash():
            raise BenchmarkValidityHarnessIntegrityError("Harness replay certificate mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> HarnessReplayCertificate:
        payload = {
            "schema_version": "benchmark-validity-harness-replay-certificate-v1",
            "exact_projection_match": True,
            "distinct_interpreter_installations": True,
            "benchmark_outcomes_accessed": False,
            "candidate_model_calls": False,
            **values,
        }
        return cls.model_validate(_addressed_payload(payload, "certificate_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"certificate_hash"})
        )


def build_harness_replay_payload(
    projection: BenchmarkValidityHarnessProjection,
) -> dict[str, Any]:
    runner_projection = projection.runner_projection()
    return {
        "expected_projection_sha256": canonical_sha256(runner_projection),
        "projection": runner_projection,
    }


def run_harness_replay(
    *,
    projection: BenchmarkValidityHarnessProjection,
    runner_path: Path,
    interpreters: Mapping[str, Path],
    work_dir: Path,
) -> HarnessReplayCertificate:
    """Replay the result-blind Harness projection in two clean interpreters."""

    if set(interpreters) != {"reviewer-a", "reviewer-b"}:
        raise ValueError("Harness replay requires reviewer-a and reviewer-b runtimes")
    work_dir.mkdir(parents=True, exist_ok=True)
    payload = build_harness_replay_payload(projection)
    input_path = work_dir / "benchmark-validity-harness-replay-input.json"
    _write_text_atomic(input_path, _canonical_json_text(payload) + "\n")
    input_hash = _file_sha256(input_path)
    runner_hash = _file_sha256(runner_path)
    observations: list[HarnessReplayObservation] = []
    for role_id, executable in sorted(interpreters.items()):
        runtime = probe_interpreter_runtime(role_id=role_id, executable=executable)
        output_path = work_dir / f"benchmark-validity-harness-{role_id}.json"
        completed = subprocess.run(
            [
                str(executable),
                str(runner_path),
                "--input",
                str(input_path),
                "--output",
                str(output_path),
            ],
            capture_output=True,
            check=False,
            timeout=60,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.decode("utf-8", errors="replace")
            raise BenchmarkValidityHarnessIntegrityError(
                f"Harness replay failed for {role_id}: {stderr[:1000]}"
            )
        output = json.loads(output_path.read_text(encoding="utf-8"))
        if output.get("projection_sha256") != projection.projection_sha256:
            raise BenchmarkValidityHarnessIntegrityError(
                f"Harness replay projection mismatch for {role_id}"
            )
        output_contract_hash = str(output.get("output_sha256", ""))
        if len(output_contract_hash) != 64:
            raise BenchmarkValidityHarnessIntegrityError(
                f"Harness replay output hash missing for {role_id}"
            )
        observations.append(
            HarnessReplayObservation.create(
                runtime=runtime,
                projection_sha256=projection.projection_sha256,
                output_file_sha256=_file_sha256(output_path),
                output_contract_sha256=output_contract_hash,
            )
        )
    return HarnessReplayCertificate.create(
        protocol_hash=projection.protocol_hash,
        projection_sha256=projection.projection_sha256,
        replay_input_sha256=input_hash,
        frozen_runner_sha256=runner_hash,
        observations=observations,
    )


class BenchmarkValidityHarnessReport(KernelContract):
    """Formal capability report; it contains no scientific admission decision."""

    schema_version: Literal["benchmark-validity-harness-report-v1"] = (
        "benchmark-validity-harness-report-v1"
    )
    task_id: Literal["263.6.7.2"] = "263.6.7.2"
    parent_git_commit: StableId
    built_at: datetime
    protocol_hash: Sha256
    protocol_source_sha256: Sha256
    harness_source_sha256: Sha256
    frozen_runner_sha256: Sha256
    adapter_contracts: list[AdapterContract]
    compatibility_findings: list[ProtocolCompatibilityFinding]
    capability_probe_specs: list[CapabilityProbeSpec]
    capability_runs: list[SearchRunSummary]
    journal_snapshot: SearchJournalSnapshot
    paper_deduplication: PaperDeduplicationResult
    known_item_recall: KnownItemRecallReport
    family_revision_deduplication: FamilyRevisionDeduplicationResult
    screening_form: FrozenScreeningFormTemplate
    empty_packet_template: EmptyAdmissionEvidencePacketTemplate
    projection: BenchmarkValidityHarnessProjection
    replay_certificate: HarnessReplayCertificate
    status: Literal["ready-for-capability-only"] = "ready-for-capability-only"
    next_action: Literal["freeze-pagination-erratum-before-formal-census"] = (
        "freeze-pagination-erratum-before-formal-census"
    )
    formal_search_execution_count: Literal[0] = 0
    admission_card_count: Literal[0] = 0
    benchmark_outcomes_accessed: Literal[False] = False
    candidate_model_calls: Literal[False] = False
    report_hash: Sha256

    @field_validator("built_at")
    @classmethod
    def _built_at_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Harness report time must be timezone aware")
        return value.astimezone(timezone.utc)

    @field_validator(
        "adapter_contracts",
        "compatibility_findings",
        "capability_probe_specs",
        "capability_runs",
    )
    @classmethod
    def _sort_report_lists(cls, value: list[Any], info: ValidationInfo) -> list[Any]:
        keys = {
            "adapter_contracts": lambda item: item.source_id.value,
            "compatibility_findings": lambda item: item.finding_id,
            "capability_probe_specs": lambda item: item.probe_id,
            "capability_runs": lambda item: item.query_or_probe_id,
        }
        if info.field_name is None:
            raise ValueError("Harness report list requires a field name")
        return sorted(value, key=keys[info.field_name])

    @model_validator(mode="after")
    def _validate_report(self) -> BenchmarkValidityHarnessReport:
        if self.protocol_hash != FROZEN_BENCHMARK_VALIDITY_PROTOCOL_HASH:
            raise ValueError("Harness report changed the committed protocol")
        if self.protocol_source_sha256 != FROZEN_BENCHMARK_VALIDITY_PROTOCOL_SOURCE_SHA256:
            raise ValueError("Harness report changed the protocol source")
        if {item.source_id for item in self.adapter_contracts} != set(SearchSourceId):
            raise ValueError("Harness report needs four adapters")
        if {item.source_id for item in self.capability_probe_specs} != set(SearchSourceId):
            raise ValueError("Harness report needs four capability specs")
        if {item.source_id for item in self.capability_runs} != set(SearchSourceId):
            raise ValueError("Harness report needs four capability runs")
        if any(item.purpose is not SearchPurpose.API_CAPABILITY_SMOKE for item in self.capability_runs):
            raise ValueError("formal searches cannot enter the Task 263.6.7.2 report")
        if any(item.status is not SearchRunStatus.CAPABILITY_ONLY for item in self.capability_runs):
            raise ValueError("all four API capability probes must validate")
        if self.known_item_recall.formal_recall_claim:
            raise ValueError("capability records cannot claim frozen formal recall")
        if self.projection.protocol_hash != self.protocol_hash:
            raise ValueError("Harness projection is not bound to the protocol")
        if self.replay_certificate.projection_sha256 != self.projection.projection_sha256:
            raise ValueError("Harness replay is not bound to the projection")
        if self.report_hash != self.calculated_hash():
            raise BenchmarkValidityHarnessIntegrityError("Harness report_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> BenchmarkValidityHarnessReport:
        payload = {
            "schema_version": "benchmark-validity-harness-report-v1",
            "task_id": "263.6.7.2",
            "status": "ready-for-capability-only",
            "next_action": "freeze-pagination-erratum-before-formal-census",
            "formal_search_execution_count": 0,
            "admission_card_count": 0,
            "benchmark_outcomes_accessed": False,
            "candidate_model_calls": False,
            **values,
        }
        return cls.model_validate(_addressed_payload(payload, "report_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"report_hash"}))


def build_harness_projection(
    *,
    protocol: BenchmarkValidityProtocol,
    adapter_contracts: Sequence[AdapterContract],
    compatibility_findings: Sequence[ProtocolCompatibilityFinding],
    capability_probe_specs: Sequence[CapabilityProbeSpec],
    capability_runs: Sequence[SearchRunSummary],
    journal_snapshot: SearchJournalSnapshot,
    paper_deduplication: PaperDeduplicationResult,
    known_item_recall: KnownItemRecallReport,
    family_revision_deduplication: FamilyRevisionDeduplicationResult,
    screening_form: FrozenScreeningFormTemplate,
    empty_packet_template: EmptyAdmissionEvidencePacketTemplate,
) -> BenchmarkValidityHarnessProjection:
    protocol.verify_integrity()
    if any(item.purpose is SearchPurpose.FORMAL_CENSUS for item in capability_runs):
        raise ValueError("Task 263.6.7.2 projection cannot contain formal searches")
    blockers = sorted(
        item.finding_id
        for item in compatibility_findings
        if not item.formal_search_allowed
    )
    return BenchmarkValidityHarnessProjection.create(
        protocol_hash=protocol.protocol_hash,
        adapter_hashes={item.source_id: item.adapter_hash for item in adapter_contracts},
        compatibility_finding_hashes=[item.finding_hash for item in compatibility_findings],
        formal_blocker_ids=blockers,
        capability_probe_hashes=[item.probe_hash for item in capability_probe_specs],
        capability_run_hashes=[item.summary_hash for item in capability_runs],
        journal_snapshot_hash=journal_snapshot.snapshot_hash,
        paper_deduplication_hash=paper_deduplication.result_hash,
        known_item_recall_hash=known_item_recall.report_hash,
        family_revision_deduplication_hash=family_revision_deduplication.result_hash,
        screening_form_hash=screening_form.form_hash,
        empty_packet_template_hash=empty_packet_template.template_hash,
        raw_response_count=len(journal_snapshot.raw_response_hashes),
        bibliographic_record_count=journal_snapshot.bibliographic_record_count,
    )


class BenchmarkValidityHarnessManifest(KernelContract):
    schema_version: Literal["benchmark-validity-harness-manifest-v1"] = (
        "benchmark-validity-harness-manifest-v1"
    )
    protocol_hash: Sha256
    report_hash: Sha256
    projection_sha256: Sha256
    replay_certificate_hash: Sha256
    journal_snapshot_hash: Sha256
    files: dict[str, Sha256]
    manifest_hash: Sha256

    @field_validator("files")
    @classmethod
    def _sort_manifest_files(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("Harness manifest cannot be empty")
        if any(Path(key).is_absolute() or ".." in Path(key).parts for key in value):
            raise ValueError("Harness manifest paths must stay relative")
        return dict(sorted((key.replace("\\", "/"), item) for key, item in value.items()))

    @model_validator(mode="after")
    def _validate_manifest(self) -> BenchmarkValidityHarnessManifest:
        if HARNESS_MANIFEST_FILENAME in self.files:
            raise ValueError("Harness manifest cannot hash itself")
        if self.manifest_hash != self.calculated_hash():
            raise BenchmarkValidityHarnessIntegrityError("Harness manifest_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> BenchmarkValidityHarnessManifest:
        payload = {
            "schema_version": "benchmark-validity-harness-manifest-v1",
            **values,
        }
        return cls.model_validate(_addressed_payload(payload, "manifest_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"manifest_hash"}))


HARNESS_CONTRACT_MODELS: tuple[type[BaseModel], ...] = (
    AdapterContract,
    ProtocolCompatibilityFinding,
    CapabilityProbeSpec,
    SearchPageRequest,
    RawResponseArtifact,
    BibliographicRecord,
    ParsedSearchPage,
    SearchPageLogEntry,
    SearchRunSummary,
    SearchExecutionLogEnvelope,
    SearchJournalSnapshot,
    PaperDedupCluster,
    PaperDeduplicationResult,
    KnownItemMatch,
    KnownItemRecallReport,
    FamilyLineageObservation,
    FamilyRevisionAssignment,
    FamilyRevisionCluster,
    FamilyRevisionDeduplicationResult,
    FrozenScreeningCriterion,
    FrozenScreeningFormTemplate,
    EmptyEvidenceField,
    EmptyAdmissionEvidencePacketTemplate,
    EmptyAdmissionEvidencePacket,
    BenchmarkValidityHarnessProjection,
    HarnessReplayObservation,
    HarnessReplayCertificate,
    BenchmarkValidityHarnessReport,
    BenchmarkValidityHarnessManifest,
)


def benchmark_validity_harness_json_schemas() -> dict[str, dict[str, Any]]:
    return {
        model.__name__: model.model_json_schema()
        for model in HARNESS_CONTRACT_MODELS
    }


def render_benchmark_validity_harness_markdown(
    report: BenchmarkValidityHarnessReport,
) -> str:
    """Render a truthful capability report without scientific conclusions."""

    report.model_validate(report.model_dump(mode="json"))
    lines = [
        "# Benchmark-validity result-blind Harness",
        "",
        f"- Task: `{report.task_id}`",
        f"- Status: `{report.status}`",
        f"- Protocol: `{report.protocol_hash}`",
        f"- Report: `{report.report_hash}`",
        f"- Projection: `{report.projection.projection_sha256}`",
        f"- Replay certificate: `{report.replay_certificate.certificate_hash}`",
        f"- Raw responses retained: `{len(report.journal_snapshot.raw_response_hashes)}`",
        f"- Bibliographic records retained: `{report.journal_snapshot.bibliographic_record_count}`",
        "- Formal search executions: `0`",
        "- Admission Cards: `0`",
        "- Benchmark outcomes accessed: `false`",
        "- Candidate model calls: `false`",
        "",
        "## API capability probes",
        "",
        "| Source | Status | Pages | Records | Raw artifacts |",
        "|---|---|---:|---:|---:|",
    ]
    for capability_run in report.capability_runs:
        lines.append(
            f"| {capability_run.source_id.value} | {capability_run.status.value} | "
            f"{capability_run.successful_page_count} | {capability_run.response_count} | "
            f"{len(capability_run.raw_response_artifact_hashes)} |"
        )
    lines.extend(
        [
            "",
            "## Formal-execution blockers",
            "",
        ]
    )
    for finding in report.compatibility_findings:
        if finding.formal_search_allowed:
            continue
        lines.extend(
            [
                f"### {finding.finding_id}",
                "",
                finding.current_documented_rule,
                "",
                f"Required action: {finding.required_action}",
                "",
                f"Documentation: {finding.documentation_url}",
                "",
            ]
        )
    lines.extend(
        [
            "## Human boundary",
            "",
            "The screening form and 42-field evidence-packet template are empty. "
            "No reviewer identity, screening decision, family decision, evidence "
            "state, gate decision, or Admission Card has been manufactured.",
            "",
            "## Next action",
            "",
            "Freeze a pre-extraction pagination erratum for Crossref and an exact "
            "conditional DBLP year-split rule before executing the 28 formal queries. "
            "The later census still requires two real independent reviewers and a "
            "distinct adjudicator.",
            "",
        ]
    )
    return "\n".join(lines)


def _artifact_file_map(output_dir: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(item for item in output_dir.rglob("*") if item.is_file()):
        relative = path.relative_to(output_dir).as_posix()
        if relative == HARNESS_MANIFEST_FILENAME or path.name.startswith("."):
            continue
        files[relative] = _file_sha256(path)
    return files


def write_benchmark_validity_harness(
    output_dir: Path,
    report: BenchmarkValidityHarnessReport,
) -> BenchmarkValidityHarnessManifest:
    """Persist the report and bind every journal/raw/record artifact."""

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / HARNESS_REPORT_FILENAME
    projection_path = output_dir / HARNESS_PROJECTION_FILENAME
    replay_path = output_dir / HARNESS_REPLAY_FILENAME
    schema_path = output_dir / HARNESS_SCHEMA_FILENAME
    markdown_path = output_dir / HARNESS_MARKDOWN_FILENAME
    _write_text_atomic(
        report_path,
        _canonical_json_text(report.model_dump(mode="json")) + "\n",
    )
    _write_text_atomic(
        projection_path,
        _canonical_json_text(report.projection.model_dump(mode="json")) + "\n",
    )
    _write_text_atomic(
        replay_path,
        _canonical_json_text(report.replay_certificate.model_dump(mode="json")) + "\n",
    )
    _write_text_atomic(
        schema_path,
        _pretty_json_text(benchmark_validity_harness_json_schemas()),
    )
    _write_text_atomic(
        markdown_path,
        render_benchmark_validity_harness_markdown(report),
    )
    files = _artifact_file_map(output_dir)
    required = {
        HARNESS_REPORT_FILENAME,
        HARNESS_PROJECTION_FILENAME,
        HARNESS_REPLAY_FILENAME,
        HARNESS_SCHEMA_FILENAME,
        HARNESS_MARKDOWN_FILENAME,
        HARNESS_PAGE_LOG_FILENAME,
        HARNESS_EXECUTION_LOG_FILENAME,
    }
    missing = sorted(required - set(files))
    if missing:
        raise BenchmarkValidityHarnessIntegrityError(
            f"Harness persistence is missing required files: {missing}"
        )
    manifest = BenchmarkValidityHarnessManifest.create(
        protocol_hash=report.protocol_hash,
        report_hash=report.report_hash,
        projection_sha256=report.projection.projection_sha256,
        replay_certificate_hash=report.replay_certificate.certificate_hash,
        journal_snapshot_hash=report.journal_snapshot.snapshot_hash,
        files=files,
    )
    _write_text_atomic(
        output_dir / HARNESS_MANIFEST_FILENAME,
        _canonical_json_text(manifest.model_dump(mode="json")) + "\n",
    )
    return manifest


def load_benchmark_validity_harness(
    output_dir: Path,
) -> tuple[BenchmarkValidityHarnessReport, BenchmarkValidityHarnessManifest]:
    """Recursively rehash and validate the complete capability package."""

    manifest = BenchmarkValidityHarnessManifest.model_validate_json(
        (output_dir / HARNESS_MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    actual_files = _artifact_file_map(output_dir)
    if set(actual_files) != set(manifest.files):
        missing = sorted(set(manifest.files) - set(actual_files))
        unexpected = sorted(set(actual_files) - set(manifest.files))
        raise BenchmarkValidityHarnessIntegrityError(
            f"Harness file inventory changed; missing={missing}, unexpected={unexpected}"
        )
    for relative, expected_hash in manifest.files.items():
        if actual_files[relative] != expected_hash:
            raise BenchmarkValidityHarnessIntegrityError(
                f"Harness artifact hash mismatch: {relative}"
            )
    report = BenchmarkValidityHarnessReport.model_validate_json(
        (output_dir / HARNESS_REPORT_FILENAME).read_text(encoding="utf-8")
    )
    if report.report_hash != manifest.report_hash:
        raise BenchmarkValidityHarnessIntegrityError("manifest/report binding mismatch")
    if report.projection.projection_sha256 != manifest.projection_sha256:
        raise BenchmarkValidityHarnessIntegrityError("manifest/projection binding mismatch")
    if report.replay_certificate.certificate_hash != manifest.replay_certificate_hash:
        raise BenchmarkValidityHarnessIntegrityError("manifest/replay binding mismatch")
    journal = AppendOnlyPrismaJournal(
        output_dir,
        protocol_hash=report.protocol_hash,
    )
    reconstructed_snapshot = journal.snapshot()
    if reconstructed_snapshot.snapshot_hash != report.journal_snapshot.snapshot_hash:
        raise BenchmarkValidityHarnessIntegrityError("journal snapshot binding mismatch")
    if reconstructed_snapshot.snapshot_hash != manifest.journal_snapshot_hash:
        raise BenchmarkValidityHarnessIntegrityError("manifest/journal binding mismatch")
    projection = BenchmarkValidityHarnessProjection.model_validate_json(
        (output_dir / HARNESS_PROJECTION_FILENAME).read_text(encoding="utf-8")
    )
    replay = HarnessReplayCertificate.model_validate_json(
        (output_dir / HARNESS_REPLAY_FILENAME).read_text(encoding="utf-8")
    )
    if projection.projection_sha256 != report.projection.projection_sha256:
        raise BenchmarkValidityHarnessIntegrityError("persisted projection differs")
    if replay.certificate_hash != report.replay_certificate.certificate_hash:
        raise BenchmarkValidityHarnessIntegrityError("persisted replay differs")
    return report, manifest


def execute_benchmark_validity_capability_harness(
    *,
    protocol: BenchmarkValidityProtocol,
    output_dir: Path,
    protocol_source_path: Path,
    harness_source_path: Path,
    runner_path: Path,
    interpreters: Mapping[str, Path],
    replay_work_dir: Path,
    parent_git_commit: str,
    built_at: datetime,
    transport: HttpGetTransport = urllib_get_transport,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[BenchmarkValidityHarnessReport, BenchmarkValidityHarnessManifest]:
    """Run four one-page capability probes and seal a result-blind package."""

    protocol.verify_integrity()
    if protocol.protocol_hash != FROZEN_BENCHMARK_VALIDITY_PROTOCOL_HASH:
        raise BenchmarkValidityHarnessIntegrityError("unexpected protocol hash")
    if (
        _file_sha256(protocol_source_path)
        != FROZEN_BENCHMARK_VALIDITY_PROTOCOL_SOURCE_SHA256
    ):
        raise BenchmarkValidityHarnessIntegrityError("protocol source changed after freeze")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(
            f"capability output must be a new empty directory: {output_dir}"
        )
    journal = AppendOnlyPrismaJournal(
        output_dir,
        protocol_hash=protocol.protocol_hash,
    )
    harness = ResultBlindSearchHarness(
        protocol=protocol,
        journal=journal,
        transport=transport,
        now=now,
        monotonic=monotonic,
        sleep=sleep,
        allow_formal_execution=False,
    )
    adapters = build_adapter_contracts(protocol)
    compatibility = audit_protocol_adapter_compatibility(protocol)
    probes = build_capability_probe_specs(protocol)
    runs = [harness.execute_capability_probe(item) for item in probes]
    snapshot = journal.snapshot()
    records = journal.load_bibliographic_records()
    paper_deduplication = deduplicate_bibliographic_records(records)
    known_item_recall = evaluate_known_item_recall(
        protocol=protocol,
        records=records,
        deduplication=paper_deduplication,
        formal_recall_claim=False,
    )
    family_deduplication = deduplicate_family_revisions(
        protocol=protocol,
        observations=[],
    )
    screening_form = build_frozen_screening_form(protocol)
    empty_packet_template = build_empty_evidence_packet_template(protocol)
    projection = build_harness_projection(
        protocol=protocol,
        adapter_contracts=adapters,
        compatibility_findings=compatibility,
        capability_probe_specs=probes,
        capability_runs=runs,
        journal_snapshot=snapshot,
        paper_deduplication=paper_deduplication,
        known_item_recall=known_item_recall,
        family_revision_deduplication=family_deduplication,
        screening_form=screening_form,
        empty_packet_template=empty_packet_template,
    )
    replay_certificate = run_harness_replay(
        projection=projection,
        runner_path=runner_path,
        interpreters=interpreters,
        work_dir=replay_work_dir,
    )
    report = BenchmarkValidityHarnessReport.create(
        parent_git_commit=parent_git_commit,
        built_at=built_at,
        protocol_hash=protocol.protocol_hash,
        protocol_source_sha256=FROZEN_BENCHMARK_VALIDITY_PROTOCOL_SOURCE_SHA256,
        harness_source_sha256=_file_sha256(harness_source_path),
        frozen_runner_sha256=_file_sha256(runner_path),
        adapter_contracts=adapters,
        compatibility_findings=compatibility,
        capability_probe_specs=probes,
        capability_runs=runs,
        journal_snapshot=snapshot,
        paper_deduplication=paper_deduplication,
        known_item_recall=known_item_recall,
        family_revision_deduplication=family_deduplication,
        screening_form=screening_form,
        empty_packet_template=empty_packet_template,
        projection=projection,
        replay_certificate=replay_certificate,
    )
    manifest = write_benchmark_validity_harness(output_dir, report)
    return report, manifest


__all__ = [
    "FROZEN_BENCHMARK_VALIDITY_PROTOCOL_HASH",
    "FROZEN_BENCHMARK_VALIDITY_PROTOCOL_SOURCE_SHA256",
    "HARNESS_BIBLIOGRAPHIC_DIRECTORY",
    "HARNESS_CONTRACT_MODELS",
    "HARNESS_EXECUTION_LOG_FILENAME",
    "HARNESS_MANIFEST_FILENAME",
    "HARNESS_MARKDOWN_FILENAME",
    "HARNESS_PAGE_LOG_FILENAME",
    "HARNESS_PROJECTION_FILENAME",
    "HARNESS_RAW_DIRECTORY",
    "HARNESS_REPLAY_FILENAME",
    "HARNESS_REPORT_FILENAME",
    "HARNESS_RUNNER_SOURCE_PATH",
    "HARNESS_SCHEMA_FILENAME",
    "AdapterContract",
    "AppendOnlyPrismaJournal",
    "BenchmarkValidityHarnessIntegrityError",
    "BenchmarkValidityHarnessManifest",
    "BenchmarkValidityHarnessProjection",
    "BenchmarkValidityHarnessReport",
    "BenchmarkValidityTransportError",
    "BibliographicRecord",
    "CapabilityProbeSpec",
    "CompatibilitySeverity",
    "EmptyAdmissionEvidencePacket",
    "EmptyAdmissionEvidencePacketTemplate",
    "EmptyEvidenceField",
    "FamilyLineageObservation",
    "FamilyRevisionAssignment",
    "FamilyRevisionCluster",
    "FamilyRevisionDeduplicationResult",
    "FamilyRevisionRole",
    "FormalSearchBlockedError",
    "FrozenScreeningCriterion",
    "FrozenScreeningFormTemplate",
    "HarnessReplayCertificate",
    "HarnessReplayObservation",
    "HarnessStatus",
    "HttpGetTransport",
    "KnownItemMatch",
    "KnownItemRecallReport",
    "PageAttemptStatus",
    "PaperDedupCluster",
    "PaperDeduplicationResult",
    "ParsedSearchPage",
    "ProtocolCompatibilityFinding",
    "RawResponseArtifact",
    "ResultBlindSearchHarness",
    "SearchExecutionLogEnvelope",
    "SearchJournalSnapshot",
    "SearchPageLogEntry",
    "SearchPageRequest",
    "SearchPurpose",
    "SearchRunStatus",
    "SearchRunSummary",
    "TransportResponse",
    "audit_protocol_adapter_compatibility",
    "benchmark_validity_harness_json_schemas",
    "build_adapter_contracts",
    "build_capability_probe_specs",
    "build_empty_evidence_packet",
    "build_empty_evidence_packet_template",
    "build_frozen_screening_form",
    "build_harness_projection",
    "build_harness_replay_payload",
    "deduplicate_bibliographic_records",
    "deduplicate_family_revisions",
    "evaluate_known_item_recall",
    "execute_benchmark_validity_capability_harness",
    "load_benchmark_validity_harness",
    "normalize_arxiv_id",
    "normalize_doi",
    "normalize_title",
    "parse_arxiv_page",
    "parse_crossref_page",
    "parse_dblp_page",
    "parse_openalex_page",
    "parse_search_page",
    "render_benchmark_validity_harness_markdown",
    "run_harness_replay",
    "urllib_get_transport",
    "write_benchmark_validity_harness",
]
