"""Pre-extraction API-pagination erratum for Task 263.6.7.2.1.

The original Task 263.6.7.1 protocol remains immutable.  This module binds a
result-free additive erratum to that protocol and the completed Task 263.6.7.2
Harness.  It corrects Crossref terminal-page semantics, clarifies OpenAlex
cursor exhaustion, and replaces the unsupported DBLP year-split fallback with
a retained partial/stop when the documented 1,000-hit cap is reached.

No formal query, bibliographic record, screening decision, benchmark outcome,
Admission Card, model call, human identity, or publication permission may
enter the erratum package.
"""

from __future__ import annotations

import hashlib
import json
import os
import ssl
import subprocess
import tempfile
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal, cast

import certifi
from pydantic import Field, TypeAdapter, field_validator, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    NonEmptyText,
    Sha256,
    StableId,
    canonical_sha256,
)

from .benchmark_validity_harness import (
    FROZEN_BENCHMARK_VALIDITY_PROTOCOL_HASH,
    FROZEN_BENCHMARK_VALIDITY_PROTOCOL_SOURCE_SHA256,
    BenchmarkValidityHarnessManifest,
    BenchmarkValidityHarnessReport,
)
from .benchmark_validity_protocol import BenchmarkValidityProtocol, SearchSourceId
from .workload_qualified_opportunity import InterpreterRuntime, probe_interpreter_runtime

PARENT_HARNESS_COMMIT = "312ebe47117ffb0bd78bd17c5c96d71f3ea48127"
PARENT_HARNESS_SOURCE_SHA256 = "501261fc6b82199f34a812ed02f0547dbadcd267c395ba6fc9186196fbd5c3dc"
PARENT_HARNESS_REPORT_HASH = "fbb2a633bb57f0bb9f9f1471b58e8b4b8367098923f07c052d712758cbef9a10"
PARENT_HARNESS_PROJECTION_HASH = "30bdad36006badccca89f335ff092e34c2c7f3a5a4586e5aba982689c7ba8b2d"
PARENT_HARNESS_MANIFEST_HASH = "688599b0b46c1502c79e9046f53dd96183989f6fcba8134bc8491d26eef18b3f"

PAGINATION_ERRATUM_REPORT_FILENAME = "benchmark-pagination-erratum-report.json"
PAGINATION_ERRATUM_MARKDOWN_FILENAME = "benchmark-pagination-erratum-report.md"
PAGINATION_ERRATUM_PROJECTION_FILENAME = "benchmark-pagination-erratum-projection.json"
PAGINATION_ERRATUM_REPLAY_FILENAME = "benchmark-pagination-erratum-replay.json"
PAGINATION_ERRATUM_SCHEMA_FILENAME = "benchmark-pagination-erratum-schemas.json"
PAGINATION_ERRATUM_MANIFEST_FILENAME = "benchmark-pagination-erratum-manifest.json"
PAGINATION_ERRATUM_DOCUMENTATION_DIRECTORY = "documentation"
PAGINATION_ERRATUM_RUNNER_SOURCE_PATH = Path(
    "src/autoresearch/research/assets/" "frozen_benchmark_validity_pagination_erratum_probe_v1.py"
)

DBLP_CAP_POLICY: Literal["retain-partial-and-stop-no-documented-year-filter"] = (
    "retain-partial-and-stop-no-documented-year-filter"
)
RESOLVED_FINDING_IDS = [
    "crossref-last-cursor-termination-mismatch",
    "dblp-year-split-query-unspecified",
]
_FORBIDDEN_RESULT_KEYS = {
    "admission_card",
    "admission_cards",
    "answer",
    "benchmark_outcome",
    "benchmark_outcomes",
    "candidate_model_output",
    "candidate_model_outputs",
    "gold_answer",
    "judge_output",
    "model_output",
    "model_outputs",
    "reference_answer",
    "reserve_result",
    "screening_decision",
}
_JSON_PAYLOAD_ADAPTER = TypeAdapter(dict[str, Any])


class PaginationErratumIntegrityError(ValueError):
    """Raised when the erratum or any bound artifact no longer verifies."""


class DocumentationFetchError(RuntimeError):
    """Raised when a primary documentation snapshot cannot be retained."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _file_sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_json_text(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _pretty_json_text(value: Any) -> str:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )


def _write_text_atomic(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_bytes_once(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != value:
            raise PaginationErratumIntegrityError(
                f"content-addressed documentation path changed: {path}"
            )
        return
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _addressed_payload(payload: dict[str, Any], hash_field: str) -> dict[str, Any]:
    json_payload = _JSON_PAYLOAD_ADAPTER.dump_python(payload, mode="json")
    normalized = dict(payload)
    normalized[hash_field] = canonical_sha256(json_payload)
    return normalized


def _walk_forbidden(value: Any, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key).casefold().replace("-", "_")
            if key in _FORBIDDEN_RESULT_KEYS and item is not None:
                raise ValueError(f"{path}.{raw_key} is forbidden in the result-free erratum")
            _walk_forbidden(item, path=f"{path}.{raw_key}")
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, item in enumerate(value):
            _walk_forbidden(item, path=f"{path}[{index}]")


@dataclass(frozen=True)
class DocumentationDefinition:
    document_id: str
    url: str
    required_markers: tuple[str, ...]
    absent_markers: tuple[str, ...] = ()


@dataclass(frozen=True)
class DocumentationResponse:
    status_code: int
    media_type: str
    body: bytes
    final_url: str


DocumentationFetcher = Callable[[str], DocumentationResponse]


def documentation_definitions() -> list[DocumentationDefinition]:
    """Return the four primary documentation surfaces frozen by this erratum."""

    return [
        DocumentationDefinition(
            document_id="crossref-cursor-guidance",
            url=(
                "https://www.crossref.org/documentation/retrieve-metadata/rest-api/"
                "tips-for-using-the-crossref-rest-api/"
            ),
            required_markers=(
                "cursor=*",
                "returns a cursor even on the last page",
                "less than the requested rows",
            ),
        ),
        DocumentationDefinition(
            document_id="dblp-api-parameters",
            url="https://dblp.org/faq/13501473.html",
            required_markers=(
                "query string to search for",
                "capped at 1000",
                "first hit in the numbered sequence",
            ),
        ),
        DocumentationDefinition(
            document_id="dblp-query-syntax",
            url="https://dblp.org/faq/1474589.html",
            required_markers=(
                "prefix search",
                "exact word",
                "advanced search options",
                "to do.",
            ),
            absent_markers=("year:", "publication_year:"),
        ),
        DocumentationDefinition(
            document_id="openalex-cursor-guidance",
            url="https://developers.openalex.org/guides/page-through-results",
            required_markers=(
                "cursor=*",
                "next_cursor",
                "repeat until",
                "is empty.",
            ),
        ),
    ]


def fetch_documentation_response(url: str) -> DocumentationResponse:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html,text/plain;q=0.9,*/*;q=0.1",
            "Accept-Encoding": "identity",
            "User-Agent": "AutoResearch-benchmark-pagination-erratum/1.0",
        },
        method="GET",
    )
    context = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(request, timeout=60, context=context) as response:
        body = response.read(4 * 1024 * 1024 + 1)
        if len(body) > 4 * 1024 * 1024:
            raise DocumentationFetchError("documentation response exceeds four MiB")
        return DocumentationResponse(
            status_code=int(response.status),
            media_type=response.headers.get_content_type(),
            body=body,
            final_url=response.geturl(),
        )


class RuleChangeKind(str, Enum):
    UNCHANGED = "unchanged"
    CLARIFIED_NO_CHANGE = "clarified-no-change"
    CORRECTIVE_CLARIFICATION = "corrective-clarification"
    CORRECTIVE_STOP = "corrective-stop"


class TerminalCondition(str, Enum):
    OFFSET_TOTAL = "offset-reaches-total-results"
    OPENALEX_NULL_EMPTY = "next-cursor-null-and-results-empty"
    CROSSREF_SHORT_PAGE = "returned-item-count-less-than-requested-rows"
    DBLP_BELOW_CAP_OR_STOP = "single-response-below-cap-or-partial-stop"


class DocumentationSnapshot(KernelContract):
    schema_version: Literal["benchmark-pagination-documentation-snapshot-v1"] = (
        "benchmark-pagination-documentation-snapshot-v1"
    )
    document_id: StableId
    url: NonEmptyText
    retrieved_at: datetime
    status_code: Literal[200] = 200
    media_type: NonEmptyText
    final_url_sha256: Sha256
    body_sha256: Sha256
    body_bytes: int = Field(ge=1, le=4 * 1024 * 1024)
    relative_path: NonEmptyText
    required_markers: list[str]
    absent_markers: list[str]
    required_markers_verified: Literal[True] = True
    absent_markers_verified: Literal[True] = True
    snapshot_hash: Sha256

    @field_validator("retrieved_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("documentation retrieval time must be timezone aware")
        return value.astimezone(timezone.utc)

    @field_validator("required_markers", "absent_markers")
    @classmethod
    def _sort_markers(cls, value: list[str]) -> list[str]:
        normalized = sorted({item.casefold() for item in value})
        if any(not item for item in normalized):
            raise ValueError("documentation markers cannot be empty")
        return normalized

    @model_validator(mode="after")
    def _validate_snapshot(self) -> DocumentationSnapshot:
        expected = (
            f"{PAGINATION_ERRATUM_DOCUMENTATION_DIRECTORY}/"
            f"{self.document_id}-{self.body_sha256}.bin"
        )
        if self.relative_path.replace("\\", "/") != expected:
            raise ValueError("documentation path must derive from ID and body hash")
        if self.snapshot_hash != self.calculated_hash():
            raise PaginationErratumIntegrityError("documentation snapshot hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        definition: DocumentationDefinition,
        response: DocumentationResponse,
        retrieved_at: datetime,
    ) -> DocumentationSnapshot:
        if response.status_code != 200:
            raise DocumentationFetchError(
                f"documentation returned HTTP {response.status_code}: {definition.url}"
            )
        text = response.body.decode("utf-8", errors="replace").casefold()
        required = sorted({item.casefold() for item in definition.required_markers})
        absent = sorted({item.casefold() for item in definition.absent_markers})
        missing = [item for item in required if item not in text]
        unexpected = [item for item in absent if item in text]
        if missing:
            raise DocumentationFetchError(
                f"documentation markers missing for {definition.document_id}: {missing}"
            )
        if unexpected:
            raise DocumentationFetchError(
                f"undocumented DBLP year-filter assumption appeared: {unexpected}"
            )
        body_hash = _sha256_bytes(response.body)
        payload = {
            "schema_version": "benchmark-pagination-documentation-snapshot-v1",
            "document_id": definition.document_id,
            "url": definition.url,
            "retrieved_at": retrieved_at,
            "status_code": 200,
            "media_type": response.media_type,
            "final_url_sha256": _sha256_text(response.final_url),
            "body_sha256": body_hash,
            "body_bytes": len(response.body),
            "relative_path": (
                f"{PAGINATION_ERRATUM_DOCUMENTATION_DIRECTORY}/"
                f"{definition.document_id}-{body_hash}.bin"
            ),
            "required_markers": required,
            "absent_markers": absent,
            "required_markers_verified": True,
            "absent_markers_verified": True,
        }
        return cls.model_validate(_addressed_payload(payload, "snapshot_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"snapshot_hash"}))


class SourcePaginationAmendment(KernelContract):
    schema_version: Literal["benchmark-source-pagination-amendment-v1"] = (
        "benchmark-source-pagination-amendment-v1"
    )
    source_id: SearchSourceId
    change_kind: RuleChangeKind
    original_rule: str = Field(min_length=1, max_length=2_048)
    amended_rule: str = Field(min_length=1, max_length=2_048)
    initial_parameters: dict[str, str]
    continuation_field: str | None = Field(default=None, max_length=256)
    terminal_condition: TerminalCondition
    cap_policy: NonEmptyText
    documented_year_filter_available: bool | None = None
    formal_execution_condition: str = Field(min_length=1, max_length=2_048)
    documentation_snapshot_ids: list[StableId]
    query_terms_changed: Literal[False] = False
    date_window_changed: Literal[False] = False
    endpoint_changed: Literal[False] = False
    study_unit_changed: Literal[False] = False
    codebook_changed: Literal[False] = False
    endpoint_analysis_changed: Literal[False] = False
    amendment_hash: Sha256

    @field_validator("initial_parameters")
    @classmethod
    def _sort_parameters(cls, value: dict[str, str]) -> dict[str, str]:
        return dict(sorted(value.items()))

    @field_validator("documentation_snapshot_ids")
    @classmethod
    def _sort_docs(cls, value: list[str]) -> list[str]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("amendment documentation IDs must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_hash(self) -> SourcePaginationAmendment:
        if self.change_kind is not RuleChangeKind.UNCHANGED and not self.documentation_snapshot_ids:
            raise ValueError("a changed or clarified rule needs primary documentation")
        if self.amendment_hash != self.calculated_hash():
            raise PaginationErratumIntegrityError("source amendment hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> SourcePaginationAmendment:
        payload = {
            "schema_version": "benchmark-source-pagination-amendment-v1",
            "continuation_field": None,
            "documented_year_filter_available": None,
            "query_terms_changed": False,
            "date_window_changed": False,
            "endpoint_changed": False,
            "study_unit_changed": False,
            "codebook_changed": False,
            "endpoint_analysis_changed": False,
            **values,
            "initial_parameters": dict(sorted(values["initial_parameters"].items())),
            "documentation_snapshot_ids": sorted(values["documentation_snapshot_ids"]),
        }
        return cls.model_validate(_addressed_payload(payload, "amendment_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"amendment_hash"}))

    def runner_projection(self) -> dict[str, Any]:
        return {
            "change_kind": self.change_kind.value,
            "initial_parameters": self.initial_parameters,
            "continuation_field": self.continuation_field,
            "terminal_condition": self.terminal_condition.value,
            "cap_policy": self.cap_policy,
            "documented_year_filter_available": self.documented_year_filter_available,
        }


class ProtocolDeviationLedgerEntry(KernelContract):
    schema_version: Literal["benchmark-pagination-deviation-entry-v1"] = (
        "benchmark-pagination-deviation-entry-v1"
    )
    deviation_id: StableId
    source_id: SearchSourceId
    finding_id: StableId
    original_rule: str = Field(min_length=1, max_length=2_048)
    corrected_rule: str = Field(min_length=1, max_length=2_048)
    rationale: str = Field(min_length=1, max_length=4_096)
    detected_before_first_formal_query: Literal[True] = True
    detected_before_first_nonpilot_extraction: Literal[True] = True
    result_information_used: Literal[False] = False
    benchmark_outcomes_accessed: Literal[False] = False
    candidate_model_calls: Literal[False] = False
    original_protocol_artifact_modified: Literal[False] = False
    entry_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> ProtocolDeviationLedgerEntry:
        if self.entry_hash != self.calculated_hash():
            raise PaginationErratumIntegrityError("deviation ledger hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ProtocolDeviationLedgerEntry:
        payload = {
            "schema_version": "benchmark-pagination-deviation-entry-v1",
            "detected_before_first_formal_query": True,
            "detected_before_first_nonpilot_extraction": True,
            "result_information_used": False,
            "benchmark_outcomes_accessed": False,
            "candidate_model_calls": False,
            "original_protocol_artifact_modified": False,
            **values,
        }
        return cls.model_validate(_addressed_payload(payload, "entry_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"entry_hash"}))


class ParentHarnessEvidence(KernelContract):
    """Small immutable boundary that attests the completed parent Harness package."""

    schema_version: Literal["benchmark-pagination-parent-harness-evidence-v1"] = (
        "benchmark-pagination-parent-harness-evidence-v1"
    )
    protocol_hash: Sha256
    harness_source_sha256: Sha256
    report_hash: Sha256
    projection_sha256: Sha256
    manifest_hash: Sha256
    status: Literal["ready-for-capability-only"] = "ready-for-capability-only"
    formal_search_execution_count: Literal[0] = 0
    benchmark_outcomes_accessed: Literal[False] = False
    candidate_model_calls: Literal[False] = False
    evidence_hash: Sha256

    @model_validator(mode="after")
    def _validate_evidence(self) -> ParentHarnessEvidence:
        if self.protocol_hash != FROZEN_BENCHMARK_VALIDITY_PROTOCOL_HASH:
            raise ValueError("parent Harness protocol changed")
        if self.harness_source_sha256 != PARENT_HARNESS_SOURCE_SHA256:
            raise ValueError("parent Harness source changed")
        if self.report_hash != PARENT_HARNESS_REPORT_HASH:
            raise ValueError("parent Harness report changed")
        if self.projection_sha256 != PARENT_HARNESS_PROJECTION_HASH:
            raise ValueError("parent Harness projection changed")
        if self.manifest_hash != PARENT_HARNESS_MANIFEST_HASH:
            raise ValueError("parent Harness manifest changed")
        if self.evidence_hash != self.calculated_hash():
            raise PaginationErratumIntegrityError("parent Harness evidence hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ParentHarnessEvidence:
        payload = {
            "schema_version": "benchmark-pagination-parent-harness-evidence-v1",
            "status": "ready-for-capability-only",
            "formal_search_execution_count": 0,
            "benchmark_outcomes_accessed": False,
            "candidate_model_calls": False,
            **values,
        }
        return cls.model_validate(_addressed_payload(payload, "evidence_hash"))

    @classmethod
    def from_artifacts(
        cls,
        *,
        report: BenchmarkValidityHarnessReport,
        manifest: BenchmarkValidityHarnessManifest,
    ) -> ParentHarnessEvidence:
        checked_report = BenchmarkValidityHarnessReport.model_validate(
            report.model_dump(mode="json")
        )
        checked_manifest = BenchmarkValidityHarnessManifest.model_validate(
            manifest.model_dump(mode="json")
        )
        if checked_manifest.protocol_hash != checked_report.protocol_hash:
            raise PaginationErratumIntegrityError(
                "parent Harness manifest/protocol binding mismatch"
            )
        if checked_manifest.report_hash != checked_report.report_hash:
            raise PaginationErratumIntegrityError("parent Harness manifest/report binding mismatch")
        if checked_manifest.projection_sha256 != checked_report.projection.projection_sha256:
            raise PaginationErratumIntegrityError(
                "parent Harness manifest/projection binding mismatch"
            )
        if checked_manifest.journal_snapshot_hash != checked_report.journal_snapshot.snapshot_hash:
            raise PaginationErratumIntegrityError(
                "parent Harness manifest/journal binding mismatch"
            )
        return cls.create(
            protocol_hash=checked_report.protocol_hash,
            harness_source_sha256=checked_report.harness_source_sha256,
            report_hash=checked_report.report_hash,
            projection_sha256=checked_report.projection.projection_sha256,
            manifest_hash=checked_manifest.manifest_hash,
            status=checked_report.status,
            formal_search_execution_count=checked_report.formal_search_execution_count,
            benchmark_outcomes_accessed=checked_report.benchmark_outcomes_accessed,
            candidate_model_calls=checked_report.candidate_model_calls,
        )

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"evidence_hash"}))


class BenchmarkValidityPaginationErratum(KernelContract):
    schema_version: Literal["benchmark-pagination-erratum-v1"] = "benchmark-pagination-erratum-v1"
    task_id: Literal["263.6.7.2.1"] = "263.6.7.2.1"
    protocol_hash: Sha256
    protocol_source_sha256: Sha256
    parent_harness_commit: StableId
    parent_harness_source_sha256: Sha256
    parent_harness_report_hash: Sha256
    parent_harness_projection_hash: Sha256
    parent_harness_manifest_hash: Sha256
    frozen_at: datetime
    documentation_snapshots: list[DocumentationSnapshot]
    amendments: list[SourcePaginationAmendment]
    deviation_ledger: list[ProtocolDeviationLedgerEntry]
    resolved_finding_ids: list[StableId]
    dblp_cap_policy: Literal["retain-partial-and-stop-no-documented-year-filter"] = DBLP_CAP_POLICY
    status: Literal["frozen-pre-extraction-erratum"] = "frozen-pre-extraction-erratum"
    formal_search_authorized: Literal[True] = True
    formal_search_execution_count: Literal[0] = 0
    bibliographic_record_count: Literal[0] = 0
    screening_decision_count: Literal[0] = 0
    admission_card_count: Literal[0] = 0
    benchmark_outcomes_accessed: Literal[False] = False
    candidate_model_calls: Literal[False] = False
    actual_human_identities_assigned: Literal[False] = False
    human_coding_authorized: Literal[False] = False
    publication_claim_authorized: Literal[False] = False
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    erratum_hash: Sha256

    @field_validator("frozen_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("erratum freeze time must be timezone aware")
        return value.astimezone(timezone.utc)

    @field_validator("documentation_snapshots")
    @classmethod
    def _sort_snapshots(
        cls,
        value: list[DocumentationSnapshot],
    ) -> list[DocumentationSnapshot]:
        normalized = sorted(value, key=lambda item: item.document_id)
        if len({item.document_id for item in normalized}) != len(normalized):
            raise ValueError("documentation snapshot IDs must be unique")
        return normalized

    @field_validator("amendments")
    @classmethod
    def _sort_amendments(
        cls,
        value: list[SourcePaginationAmendment],
    ) -> list[SourcePaginationAmendment]:
        normalized = sorted(value, key=lambda item: item.source_id.value)
        if len({item.source_id for item in normalized}) != len(normalized):
            raise ValueError("pagination amendments must be source-unique")
        return normalized

    @field_validator("deviation_ledger")
    @classmethod
    def _sort_deviations(
        cls,
        value: list[ProtocolDeviationLedgerEntry],
    ) -> list[ProtocolDeviationLedgerEntry]:
        normalized = sorted(value, key=lambda item: item.deviation_id)
        if len({item.deviation_id for item in normalized}) != len(normalized):
            raise ValueError("deviation IDs must be unique")
        return normalized

    @field_validator("resolved_finding_ids")
    @classmethod
    def _sort_findings(cls, value: list[str]) -> list[str]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("resolved finding IDs must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_erratum(self) -> BenchmarkValidityPaginationErratum:
        if self.protocol_hash != FROZEN_BENCHMARK_VALIDITY_PROTOCOL_HASH:
            raise ValueError("erratum changed the original protocol hash")
        if self.protocol_source_sha256 != FROZEN_BENCHMARK_VALIDITY_PROTOCOL_SOURCE_SHA256:
            raise ValueError("erratum changed the original protocol source")
        if self.parent_harness_commit != PARENT_HARNESS_COMMIT:
            raise ValueError("erratum parent Harness commit changed")
        if self.parent_harness_source_sha256 != PARENT_HARNESS_SOURCE_SHA256:
            raise ValueError("erratum parent Harness source changed")
        if self.parent_harness_report_hash != PARENT_HARNESS_REPORT_HASH:
            raise ValueError("erratum parent Harness report changed")
        if self.parent_harness_projection_hash != PARENT_HARNESS_PROJECTION_HASH:
            raise ValueError("erratum parent Harness projection changed")
        if self.parent_harness_manifest_hash != PARENT_HARNESS_MANIFEST_HASH:
            raise ValueError("erratum parent Harness manifest changed")
        expected_docs = {item.document_id for item in documentation_definitions()}
        if {item.document_id for item in self.documentation_snapshots} != expected_docs:
            raise ValueError("erratum requires four exact documentation snapshots")
        if {item.source_id for item in self.amendments} != set(SearchSourceId):
            raise ValueError("erratum requires one rule for every source")
        if self.resolved_finding_ids != sorted(RESOLVED_FINDING_IDS):
            raise ValueError("erratum resolved-finding set changed")
        if {item.finding_id for item in self.deviation_ledger} != set(RESOLVED_FINDING_IDS):
            raise ValueError("deviation ledger must explain both corrected findings")
        rules = {item.source_id: item for item in self.amendments}
        self._validate_source_rules(rules)
        _walk_forbidden(self.model_dump(mode="python", exclude={"erratum_hash"}))
        if self.erratum_hash != self.calculated_hash():
            raise PaginationErratumIntegrityError("pagination erratum hash mismatch")
        return self

    @staticmethod
    def _validate_source_rules(
        rules: Mapping[SearchSourceId, SourcePaginationAmendment],
    ) -> None:
        arxiv = rules[SearchSourceId.ARXIV]
        if (
            arxiv.change_kind is not RuleChangeKind.UNCHANGED
            or arxiv.initial_parameters != {"start": "0"}
            or arxiv.continuation_field != "start"
            or arxiv.terminal_condition is not TerminalCondition.OFFSET_TOTAL
            or arxiv.cap_policy != "not-applicable"
        ):
            raise ValueError("arXiv pagination rule changed unexpectedly")
        openalex = rules[SearchSourceId.OPENALEX]
        if (
            openalex.change_kind is not RuleChangeKind.CLARIFIED_NO_CHANGE
            or openalex.initial_parameters != {"cursor": "*"}
            or openalex.continuation_field != "meta.next_cursor"
            or openalex.terminal_condition is not TerminalCondition.OPENALEX_NULL_EMPTY
            or openalex.cap_policy != "not-applicable"
        ):
            raise ValueError("OpenAlex pagination clarification changed")
        crossref = rules[SearchSourceId.CROSSREF]
        if (
            crossref.change_kind is not RuleChangeKind.CORRECTIVE_CLARIFICATION
            or crossref.initial_parameters != {"cursor": "*"}
            or crossref.continuation_field != "message.next-cursor"
            or crossref.terminal_condition is not TerminalCondition.CROSSREF_SHORT_PAGE
            or crossref.cap_policy != "not-applicable"
        ):
            raise ValueError("Crossref corrective pagination rule changed")
        dblp = rules[SearchSourceId.DBLP]
        if (
            dblp.change_kind is not RuleChangeKind.CORRECTIVE_STOP
            or dblp.initial_parameters != {"c": "0", "f": "0", "h": "1000"}
            or dblp.continuation_field is not None
            or dblp.terminal_condition is not TerminalCondition.DBLP_BELOW_CAP_OR_STOP
            or dblp.cap_policy != DBLP_CAP_POLICY
            or dblp.documented_year_filter_available is not False
        ):
            raise ValueError("DBLP cap-stop rule changed")
        if any(
            item.query_terms_changed
            or item.date_window_changed
            or item.endpoint_changed
            or item.study_unit_changed
            or item.codebook_changed
            or item.endpoint_analysis_changed
            for item in rules.values()
        ):
            raise ValueError("pagination erratum changed a protected research dimension")

    @classmethod
    def create(cls, **values: Any) -> BenchmarkValidityPaginationErratum:
        snapshots = sorted(values["documentation_snapshots"], key=lambda item: item.document_id)
        amendments = sorted(values["amendments"], key=lambda item: item.source_id.value)
        deviations = sorted(values["deviation_ledger"], key=lambda item: item.deviation_id)
        payload = {
            "schema_version": "benchmark-pagination-erratum-v1",
            "task_id": "263.6.7.2.1",
            "dblp_cap_policy": DBLP_CAP_POLICY,
            "status": "frozen-pre-extraction-erratum",
            "formal_search_authorized": True,
            "formal_search_execution_count": 0,
            "bibliographic_record_count": 0,
            "screening_decision_count": 0,
            "admission_card_count": 0,
            "benchmark_outcomes_accessed": False,
            "candidate_model_calls": False,
            "actual_human_identities_assigned": False,
            "human_coding_authorized": False,
            "publication_claim_authorized": False,
            "public_release_authorized": False,
            "external_submission_authorized": False,
            **values,
            "documentation_snapshots": snapshots,
            "amendments": amendments,
            "deviation_ledger": deviations,
            "resolved_finding_ids": sorted(values["resolved_finding_ids"]),
        }
        return cls.model_validate(_addressed_payload(payload, "erratum_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"erratum_hash"}))

    def verify_integrity(self) -> None:
        self.model_validate(self.model_dump(mode="json"))


class PaginationRuleProjection(KernelContract):
    change_kind: RuleChangeKind
    initial_parameters: dict[str, str]
    continuation_field: str | None = None
    terminal_condition: TerminalCondition
    cap_policy: NonEmptyText
    documented_year_filter_available: bool | None = None

    @field_validator("initial_parameters")
    @classmethod
    def _sort_parameters(cls, value: dict[str, str]) -> dict[str, str]:
        return dict(sorted(value.items()))


class PaginationErratumProjection(KernelContract):
    schema_version: Literal["benchmark-pagination-erratum-projection-v1"] = (
        "benchmark-pagination-erratum-projection-v1"
    )
    task_id: Literal["263.6.7.2.1"] = "263.6.7.2.1"
    protocol_hash: Sha256
    parent_harness_report_hash: Sha256
    erratum_hash: Sha256
    documentation_snapshot_hashes: dict[StableId, Sha256]
    amendment_hashes: dict[SearchSourceId, Sha256]
    source_rules: dict[SearchSourceId, PaginationRuleProjection]
    deviation_entry_hashes: list[Sha256]
    resolved_finding_ids: list[StableId]
    status: Literal["frozen-pre-extraction-erratum"] = "frozen-pre-extraction-erratum"
    formal_search_authorized: Literal[True] = True
    formal_search_execution_count: Literal[0] = 0
    bibliographic_record_count: Literal[0] = 0
    screening_decision_count: Literal[0] = 0
    admission_card_count: Literal[0] = 0
    benchmark_outcomes_accessed: Literal[False] = False
    candidate_model_calls: Literal[False] = False
    actual_human_identities_assigned: Literal[False] = False
    human_coding_authorized: Literal[False] = False
    publication_claim_authorized: Literal[False] = False
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    projection_sha256: Sha256

    @field_validator("documentation_snapshot_hashes")
    @classmethod
    def _sort_doc_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        return dict(sorted(value.items()))

    @field_validator("amendment_hashes", "source_rules")
    @classmethod
    def _sort_source_maps(cls, value: dict[Any, Any]) -> dict[Any, Any]:
        return dict(sorted(value.items(), key=lambda item: item[0].value))

    @field_validator("deviation_entry_hashes", "resolved_finding_ids")
    @classmethod
    def _sort_lists(cls, value: list[str]) -> list[str]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("projection lists must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_projection(self) -> PaginationErratumProjection:
        if set(self.amendment_hashes) != set(SearchSourceId):
            raise ValueError("projection needs four amendment hashes")
        if set(self.source_rules) != set(SearchSourceId):
            raise ValueError("projection needs four source rules")
        if set(self.documentation_snapshot_hashes) != {
            item.document_id for item in documentation_definitions()
        }:
            raise ValueError("projection needs four documentation snapshots")
        if self.resolved_finding_ids != sorted(RESOLVED_FINDING_IDS):
            raise ValueError("projection finding set changed")
        if self.projection_sha256 != self.calculated_hash():
            raise PaginationErratumIntegrityError("erratum projection hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> PaginationErratumProjection:
        doc_hashes = cast(Mapping[str, str], values["documentation_snapshot_hashes"])
        amendment_hashes = cast(Mapping[SearchSourceId, str], values["amendment_hashes"])
        source_rules = cast(
            Mapping[SearchSourceId, PaginationRuleProjection], values["source_rules"]
        )
        payload = {
            "schema_version": "benchmark-pagination-erratum-projection-v1",
            "task_id": "263.6.7.2.1",
            "status": "frozen-pre-extraction-erratum",
            "formal_search_authorized": True,
            "formal_search_execution_count": 0,
            "bibliographic_record_count": 0,
            "screening_decision_count": 0,
            "admission_card_count": 0,
            "benchmark_outcomes_accessed": False,
            "candidate_model_calls": False,
            "actual_human_identities_assigned": False,
            "human_coding_authorized": False,
            "publication_claim_authorized": False,
            "public_release_authorized": False,
            "external_submission_authorized": False,
            **values,
            "documentation_snapshot_hashes": dict(sorted(doc_hashes.items())),
            "amendment_hashes": dict(
                sorted(amendment_hashes.items(), key=lambda item: item[0].value)
            ),
            "source_rules": dict(sorted(source_rules.items(), key=lambda item: item[0].value)),
            "deviation_entry_hashes": sorted(values["deviation_entry_hashes"]),
            "resolved_finding_ids": sorted(values["resolved_finding_ids"]),
        }
        _walk_forbidden(payload)
        return cls.model_validate(_addressed_payload(payload, "projection_sha256"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"projection_sha256"}))

    def runner_projection(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"projection_sha256"})


class PaginationErratumReplayObservation(KernelContract):
    schema_version: Literal["benchmark-pagination-erratum-replay-observation-v1"] = (
        "benchmark-pagination-erratum-replay-observation-v1"
    )
    runtime: InterpreterRuntime
    projection_sha256: Sha256
    output_file_sha256: Sha256
    output_contract_sha256: Sha256
    benchmark_outcomes_accessed: Literal[False] = False
    candidate_model_calls: Literal[False] = False
    observation_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> PaginationErratumReplayObservation:
        if self.observation_hash != self.calculated_hash():
            raise PaginationErratumIntegrityError("replay observation hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> PaginationErratumReplayObservation:
        payload = {
            "schema_version": "benchmark-pagination-erratum-replay-observation-v1",
            "benchmark_outcomes_accessed": False,
            "candidate_model_calls": False,
            **values,
        }
        return cls.model_validate(_addressed_payload(payload, "observation_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"observation_hash"}))


class PaginationErratumReplayCertificate(KernelContract):
    schema_version: Literal["benchmark-pagination-erratum-replay-certificate-v1"] = (
        "benchmark-pagination-erratum-replay-certificate-v1"
    )
    protocol_hash: Sha256
    projection_sha256: Sha256
    replay_input_sha256: Sha256
    frozen_runner_sha256: Sha256
    observations: list[PaginationErratumReplayObservation]
    exact_projection_match: Literal[True] = True
    distinct_interpreter_installations: Literal[True] = True
    benchmark_outcomes_accessed: Literal[False] = False
    candidate_model_calls: Literal[False] = False
    certificate_hash: Sha256

    @field_validator("observations")
    @classmethod
    def _sort_observations(
        cls,
        value: list[PaginationErratumReplayObservation],
    ) -> list[PaginationErratumReplayObservation]:
        normalized = sorted(value, key=lambda item: item.runtime.role_id)
        if len({item.runtime.role_id for item in normalized}) != 2:
            raise ValueError("erratum replay needs two distinct roles")
        return normalized

    @model_validator(mode="after")
    def _validate_certificate(self) -> PaginationErratumReplayCertificate:
        if any(item.projection_sha256 != self.projection_sha256 for item in self.observations):
            raise ValueError("erratum replay projections differ")
        if len({item.runtime.environment_hash for item in self.observations}) != 2:
            raise ValueError("erratum replay needs distinct interpreter installations")
        if len({item.output_contract_sha256 for item in self.observations}) != 1:
            raise ValueError("erratum replay output contracts differ")
        if self.certificate_hash != self.calculated_hash():
            raise PaginationErratumIntegrityError("replay certificate hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> PaginationErratumReplayCertificate:
        observations = sorted(values["observations"], key=lambda item: item.runtime.role_id)
        payload = {
            "schema_version": "benchmark-pagination-erratum-replay-certificate-v1",
            "exact_projection_match": True,
            "distinct_interpreter_installations": True,
            "benchmark_outcomes_accessed": False,
            "candidate_model_calls": False,
            **values,
            "observations": observations,
        }
        return cls.model_validate(_addressed_payload(payload, "certificate_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"certificate_hash"}))


class BenchmarkValidityPaginationErratumReport(KernelContract):
    schema_version: Literal["benchmark-pagination-erratum-report-v1"] = (
        "benchmark-pagination-erratum-report-v1"
    )
    task_id: Literal["263.6.7.2.1"] = "263.6.7.2.1"
    parent_git_commit: StableId
    built_at: datetime
    integrated_harness_source_sha256: Sha256
    erratum_source_sha256: Sha256
    frozen_runner_sha256: Sha256
    erratum: BenchmarkValidityPaginationErratum
    projection: PaginationErratumProjection
    replay_certificate: PaginationErratumReplayCertificate
    status: Literal["frozen-pre-extraction-erratum"] = "frozen-pre-extraction-erratum"
    next_action: Literal["assign-three-human-roles-before-census"] = (
        "assign-three-human-roles-before-census"
    )
    formal_search_execution_count: Literal[0] = 0
    bibliographic_record_count: Literal[0] = 0
    admission_card_count: Literal[0] = 0
    benchmark_outcomes_accessed: Literal[False] = False
    candidate_model_calls: Literal[False] = False
    report_hash: Sha256

    @field_validator("built_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("erratum report time must be timezone aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _validate_report(self) -> BenchmarkValidityPaginationErratumReport:
        if self.parent_git_commit != PARENT_HARNESS_COMMIT:
            raise ValueError("erratum report parent must be the completed Harness commit")
        if self.erratum.erratum_hash != self.projection.erratum_hash:
            raise ValueError("projection is not bound to the erratum")
        if self.projection.projection_sha256 != self.replay_certificate.projection_sha256:
            raise ValueError("replay is not bound to the projection")
        if self.frozen_runner_sha256 != self.replay_certificate.frozen_runner_sha256:
            raise ValueError("report runner hash differs from replay")
        if self.report_hash != self.calculated_hash():
            raise PaginationErratumIntegrityError("erratum report hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> BenchmarkValidityPaginationErratumReport:
        payload = {
            "schema_version": "benchmark-pagination-erratum-report-v1",
            "task_id": "263.6.7.2.1",
            "status": "frozen-pre-extraction-erratum",
            "next_action": "assign-three-human-roles-before-census",
            "formal_search_execution_count": 0,
            "bibliographic_record_count": 0,
            "admission_card_count": 0,
            "benchmark_outcomes_accessed": False,
            "candidate_model_calls": False,
            **values,
        }
        return cls.model_validate(_addressed_payload(payload, "report_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"report_hash"}))


class PaginationErratumManifest(KernelContract):
    schema_version: Literal["benchmark-pagination-erratum-manifest-v1"] = (
        "benchmark-pagination-erratum-manifest-v1"
    )
    protocol_hash: Sha256
    erratum_hash: Sha256
    report_hash: Sha256
    projection_sha256: Sha256
    replay_certificate_hash: Sha256
    files: dict[NonEmptyText, Sha256]
    manifest_hash: Sha256

    @field_validator("files")
    @classmethod
    def _sort_files(cls, value: dict[str, str]) -> dict[str, str]:
        return dict(sorted(value.items()))

    @model_validator(mode="after")
    def _validate_manifest(self) -> PaginationErratumManifest:
        if self.manifest_hash != self.calculated_hash():
            raise PaginationErratumIntegrityError("erratum manifest hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> PaginationErratumManifest:
        payload = {
            "schema_version": "benchmark-pagination-erratum-manifest-v1",
            **values,
            "files": dict(sorted(values["files"].items())),
        }
        return cls.model_validate(_addressed_payload(payload, "manifest_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"manifest_hash"}))


ERRATUM_CONTRACT_MODELS = (
    DocumentationSnapshot,
    SourcePaginationAmendment,
    ProtocolDeviationLedgerEntry,
    ParentHarnessEvidence,
    BenchmarkValidityPaginationErratum,
    PaginationRuleProjection,
    PaginationErratumProjection,
    PaginationErratumReplayObservation,
    PaginationErratumReplayCertificate,
    BenchmarkValidityPaginationErratumReport,
    PaginationErratumManifest,
)


def pagination_erratum_json_schemas() -> dict[str, dict[str, Any]]:
    return {model.__name__: model.model_json_schema() for model in ERRATUM_CONTRACT_MODELS}


def fetch_documentation_snapshots(
    *,
    output_dir: Path,
    retrieved_at: datetime,
    fetcher: DocumentationFetcher = fetch_documentation_response,
) -> list[DocumentationSnapshot]:
    snapshots: list[DocumentationSnapshot] = []
    for definition in documentation_definitions():
        response = fetcher(definition.url)
        snapshot = DocumentationSnapshot.create(
            definition=definition,
            response=response,
            retrieved_at=retrieved_at,
        )
        _write_bytes_once(output_dir / snapshot.relative_path, response.body)
        snapshots.append(snapshot)
    return sorted(snapshots, key=lambda item: item.document_id)


def _build_amendments(
    protocol: BenchmarkValidityProtocol,
) -> list[SourcePaginationAmendment]:
    originals = {item.source_id: item.pagination_rule for item in protocol.search_sources}
    return [
        SourcePaginationAmendment.create(
            source_id=SearchSourceId.ARXIV,
            change_kind=RuleChangeKind.UNCHANGED,
            original_rule=originals[SearchSourceId.ARXIV],
            amended_rule=originals[SearchSourceId.ARXIV],
            initial_parameters={"start": "0"},
            continuation_field="start",
            terminal_condition=TerminalCondition.OFFSET_TOTAL,
            cap_policy="not-applicable",
            formal_execution_condition=(
                "Continue exact offset pages until start plus returned entries reaches "
                "opensearch.totalResults; retain the original three-second spacing."
            ),
            documentation_snapshot_ids=[],
        ),
        SourcePaginationAmendment.create(
            source_id=SearchSourceId.OPENALEX,
            change_kind=RuleChangeKind.CLARIFIED_NO_CHANGE,
            original_rule=originals[SearchSourceId.OPENALEX],
            amended_rule=(
                "Begin with cursor=*; follow meta.next_cursor exactly; terminate only "
                "when next_cursor is null and results is empty; retain every raw page."
            ),
            initial_parameters={"cursor": "*"},
            continuation_field="meta.next_cursor",
            terminal_condition=TerminalCondition.OPENALEX_NULL_EMPTY,
            cap_policy="not-applicable",
            formal_execution_condition=(
                "A null cursor with non-empty results is retained as partial rather "
                "than silently declared exhausted."
            ),
            documentation_snapshot_ids=["openalex-cursor-guidance"],
        ),
        SourcePaginationAmendment.create(
            source_id=SearchSourceId.CROSSREF,
            change_kind=RuleChangeKind.CORRECTIVE_CLARIFICATION,
            original_rule=originals[SearchSourceId.CROSSREF],
            amended_rule=(
                "Begin with cursor=*; pass message.next-cursor to the next request; "
                "terminate when returned item count is less than requested rows because "
                "Crossref returns a cursor even on the last page."
            ),
            initial_parameters={"cursor": "*"},
            continuation_field="message.next-cursor",
            terminal_condition=TerminalCondition.CROSSREF_SHORT_PAGE,
            cap_policy="not-applicable",
            formal_execution_condition=(
                "Every full page requires a non-empty next-cursor; every short page is "
                "terminal and its raw response remains in the PRISMA-S journal."
            ),
            documentation_snapshot_ids=["crossref-cursor-guidance"],
        ),
        SourcePaginationAmendment.create(
            source_id=SearchSourceId.DBLP,
            change_kind=RuleChangeKind.CORRECTIVE_STOP,
            original_rule=originals[SearchSourceId.DBLP],
            amended_rule=(
                "Use the exact frozen q with f=0,h=1000,c=0. If @total is below "
                "1000, retain the single response and post-filter metadata years. If "
                "@total is at least 1000, retain the capped response as partial and "
                "stop; do not invent an undocumented year-field query or alter terms."
            ),
            initial_parameters={"c": "0", "f": "0", "h": "1000"},
            continuation_field=None,
            terminal_condition=TerminalCondition.DBLP_BELOW_CAP_OR_STOP,
            cap_policy=DBLP_CAP_POLICY,
            documented_year_filter_available=False,
            formal_execution_condition=(
                "Only a query with @total below 1000 can be complete. A capped query "
                "forces partial-source reporting and the registered diagnostic stop."
            ),
            documentation_snapshot_ids=[
                "dblp-api-parameters",
                "dblp-query-syntax",
            ],
        ),
    ]


def _build_deviation_ledger(
    amendments: Sequence[SourcePaginationAmendment],
) -> list[ProtocolDeviationLedgerEntry]:
    rules = {item.source_id: item for item in amendments}
    crossref = rules[SearchSourceId.CROSSREF]
    dblp = rules[SearchSourceId.DBLP]
    return [
        ProtocolDeviationLedgerEntry.create(
            deviation_id="crossref-terminal-page-correction",
            source_id=SearchSourceId.CROSSREF,
            finding_id="crossref-last-cursor-termination-mismatch",
            original_rule=crossref.original_rule,
            corrected_rule=crossref.amended_rule,
            rationale=(
                "Current primary documentation states that Crossref returns a cursor "
                "even on the last page and requires short-page termination. The "
                "correction was detected by a result-blind capability probe before "
                "any formal query or non-pilot extraction."
            ),
        ),
        ProtocolDeviationLedgerEntry.create(
            deviation_id="dblp-unsupported-year-split-stop",
            source_id=SearchSourceId.DBLP,
            finding_id="dblp-year-split-query-unspecified",
            original_rule=dblp.original_rule,
            corrected_rule=dblp.amended_rule,
            rationale=(
                "DBLP documents free-text query syntax, f/h pagination, and a 1000-hit "
                "cap but no year-field filter. An invented year token could match title "
                "or venue text and cannot establish exhaustive partitioning, so capped "
                "queries are retained as partial and stop prospectively."
            ),
        ),
    ]


def build_pagination_erratum(
    *,
    protocol: BenchmarkValidityProtocol,
    parent_harness_evidence: ParentHarnessEvidence,
    documentation_snapshots: Sequence[DocumentationSnapshot],
    frozen_at: datetime,
) -> BenchmarkValidityPaginationErratum:
    protocol.verify_integrity()
    if protocol.protocol_hash != FROZEN_BENCHMARK_VALIDITY_PROTOCOL_HASH:
        raise PaginationErratumIntegrityError("unexpected original protocol")
    ParentHarnessEvidence.model_validate(parent_harness_evidence.model_dump(mode="json"))
    amendments = _build_amendments(protocol)
    return BenchmarkValidityPaginationErratum.create(
        protocol_hash=protocol.protocol_hash,
        protocol_source_sha256=FROZEN_BENCHMARK_VALIDITY_PROTOCOL_SOURCE_SHA256,
        parent_harness_commit=PARENT_HARNESS_COMMIT,
        parent_harness_source_sha256=parent_harness_evidence.harness_source_sha256,
        parent_harness_report_hash=parent_harness_evidence.report_hash,
        parent_harness_projection_hash=parent_harness_evidence.projection_sha256,
        parent_harness_manifest_hash=parent_harness_evidence.manifest_hash,
        frozen_at=frozen_at,
        documentation_snapshots=list(documentation_snapshots),
        amendments=amendments,
        deviation_ledger=_build_deviation_ledger(amendments),
        resolved_finding_ids=RESOLVED_FINDING_IDS,
    )


def build_pagination_erratum_projection(
    erratum: BenchmarkValidityPaginationErratum,
) -> PaginationErratumProjection:
    erratum.verify_integrity()
    return PaginationErratumProjection.create(
        protocol_hash=erratum.protocol_hash,
        parent_harness_report_hash=erratum.parent_harness_report_hash,
        erratum_hash=erratum.erratum_hash,
        documentation_snapshot_hashes={
            item.document_id: item.snapshot_hash for item in erratum.documentation_snapshots
        },
        amendment_hashes={item.source_id: item.amendment_hash for item in erratum.amendments},
        source_rules={
            item.source_id: PaginationRuleProjection.model_validate(item.runner_projection())
            for item in erratum.amendments
        },
        deviation_entry_hashes=[item.entry_hash for item in erratum.deviation_ledger],
        resolved_finding_ids=erratum.resolved_finding_ids,
    )


def build_pagination_erratum_replay_payload(
    projection: PaginationErratumProjection,
) -> dict[str, Any]:
    runner_projection = projection.runner_projection()
    return {
        "expected_projection_sha256": canonical_sha256(runner_projection),
        "projection": runner_projection,
    }


def run_pagination_erratum_replay(
    *,
    projection: PaginationErratumProjection,
    runner_path: Path,
    interpreters: Mapping[str, Path],
    work_dir: Path,
) -> PaginationErratumReplayCertificate:
    if set(interpreters) != {"reviewer-a", "reviewer-b"}:
        raise ValueError("erratum replay requires reviewer-a and reviewer-b")
    work_dir.mkdir(parents=True, exist_ok=True)
    payload = build_pagination_erratum_replay_payload(projection)
    input_path = work_dir / "benchmark-pagination-erratum-replay-input.json"
    _write_text_atomic(input_path, _canonical_json_text(payload) + "\n")
    observations: list[PaginationErratumReplayObservation] = []
    for role_id, executable in sorted(interpreters.items()):
        runtime = probe_interpreter_runtime(role_id=role_id, executable=executable)
        output_path = work_dir / f"benchmark-pagination-erratum-{role_id}.json"
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
            raise PaginationErratumIntegrityError(
                f"erratum replay failed for {role_id}: {stderr[:1000]}"
            )
        output = json.loads(output_path.read_text(encoding="utf-8"))
        if output.get("projection_sha256") != projection.projection_sha256:
            raise PaginationErratumIntegrityError(
                f"erratum replay projection mismatch for {role_id}"
            )
        output_contract_hash = str(output.get("output_sha256", ""))
        if len(output_contract_hash) != 64:
            raise PaginationErratumIntegrityError(
                f"erratum replay output hash missing for {role_id}"
            )
        observations.append(
            PaginationErratumReplayObservation.create(
                runtime=runtime,
                projection_sha256=projection.projection_sha256,
                output_file_sha256=_file_sha256(output_path),
                output_contract_sha256=output_contract_hash,
            )
        )
    return PaginationErratumReplayCertificate.create(
        protocol_hash=projection.protocol_hash,
        projection_sha256=projection.projection_sha256,
        replay_input_sha256=_file_sha256(input_path),
        frozen_runner_sha256=_file_sha256(runner_path),
        observations=observations,
    )


def render_pagination_erratum_markdown(
    report: BenchmarkValidityPaginationErratumReport,
) -> str:
    lines = [
        "# Benchmark-validity API-pagination erratum",
        "",
        f"- Task: `{report.task_id}`",
        f"- Status: `{report.status}`",
        f"- Original protocol: `{report.erratum.protocol_hash}`",
        f"- Erratum: `{report.erratum.erratum_hash}`",
        f"- Projection: `{report.projection.projection_sha256}`",
        f"- Replay: `{report.replay_certificate.certificate_hash}`",
        "- Formal searches executed: `0`",
        "- Bibliographic records extracted: `0`",
        "- Benchmark outcomes accessed: `false`",
        "- Candidate model calls: `false`",
        "",
        "## Frozen source rules",
        "",
        "| Source | Change | Terminal condition | Cap policy |",
        "|---|---|---|---|",
    ]
    for amendment in report.erratum.amendments:
        lines.append(
            f"| {amendment.source_id.value} | {amendment.change_kind.value} | "
            f"{amendment.terminal_condition.value} | {amendment.cap_policy} |"
        )
    lines.extend(
        [
            "",
            "## Method boundary",
            "",
            "Crossref now starts at `cursor=*` and terminates on a short page. "
            "OpenAlex requires `cursor=*` and null-cursor/empty-results exhaustion. "
            "DBLP retains the exact frozen query; a reported total of at least 1000 "
            "is retained as partial and stops because the official search syntax "
            "does not document a year-field filter.",
            "",
            "The original protocol artifact is unchanged. Query terms, date window, "
            "endpoints, study unit, codebook, endpoints, stop logic, outcomes, and "
            "downstream permissions were not selected using research results.",
            "",
            "## Next action",
            "",
            "Assign two real independent reviewers and one distinct adjudicator "
            "before Task 263.6.7.3. A capped DBLP query forces the registered "
            "partial/diagnostic endpoint rather than an invented split.",
            "",
        ]
    )
    return "\n".join(lines)


def _artifact_file_map(output_dir: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(item for item in output_dir.rglob("*") if item.is_file()):
        relative = path.relative_to(output_dir).as_posix()
        if relative == PAGINATION_ERRATUM_MANIFEST_FILENAME or path.name.startswith("."):
            continue
        files[relative] = _file_sha256(path)
    return files


def write_pagination_erratum(
    output_dir: Path,
    report: BenchmarkValidityPaginationErratumReport,
) -> PaginationErratumManifest:
    _write_text_atomic(
        output_dir / PAGINATION_ERRATUM_REPORT_FILENAME,
        _canonical_json_text(report.model_dump(mode="json")) + "\n",
    )
    _write_text_atomic(
        output_dir / PAGINATION_ERRATUM_PROJECTION_FILENAME,
        _canonical_json_text(report.projection.model_dump(mode="json")) + "\n",
    )
    _write_text_atomic(
        output_dir / PAGINATION_ERRATUM_REPLAY_FILENAME,
        _canonical_json_text(report.replay_certificate.model_dump(mode="json")) + "\n",
    )
    _write_text_atomic(
        output_dir / PAGINATION_ERRATUM_SCHEMA_FILENAME,
        _pretty_json_text(pagination_erratum_json_schemas()),
    )
    _write_text_atomic(
        output_dir / PAGINATION_ERRATUM_MARKDOWN_FILENAME,
        render_pagination_erratum_markdown(report),
    )
    files = _artifact_file_map(output_dir)
    required = {
        PAGINATION_ERRATUM_REPORT_FILENAME,
        PAGINATION_ERRATUM_PROJECTION_FILENAME,
        PAGINATION_ERRATUM_REPLAY_FILENAME,
        PAGINATION_ERRATUM_SCHEMA_FILENAME,
        PAGINATION_ERRATUM_MARKDOWN_FILENAME,
        *(item.relative_path for item in report.erratum.documentation_snapshots),
    }
    if missing := sorted(required - set(files)):
        raise PaginationErratumIntegrityError(
            f"erratum persistence is missing required files: {missing}"
        )
    manifest = PaginationErratumManifest.create(
        protocol_hash=report.erratum.protocol_hash,
        erratum_hash=report.erratum.erratum_hash,
        report_hash=report.report_hash,
        projection_sha256=report.projection.projection_sha256,
        replay_certificate_hash=report.replay_certificate.certificate_hash,
        files=files,
    )
    _write_text_atomic(
        output_dir / PAGINATION_ERRATUM_MANIFEST_FILENAME,
        _canonical_json_text(manifest.model_dump(mode="json")) + "\n",
    )
    return manifest


def load_pagination_erratum(
    output_dir: Path,
) -> tuple[BenchmarkValidityPaginationErratumReport, PaginationErratumManifest]:
    manifest = PaginationErratumManifest.model_validate_json(
        (output_dir / PAGINATION_ERRATUM_MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    actual = _artifact_file_map(output_dir)
    if set(actual) != set(manifest.files):
        raise PaginationErratumIntegrityError("erratum artifact inventory changed")
    for relative, expected in manifest.files.items():
        if actual[relative] != expected:
            raise PaginationErratumIntegrityError(f"erratum artifact hash mismatch: {relative}")
    report = BenchmarkValidityPaginationErratumReport.model_validate_json(
        (output_dir / PAGINATION_ERRATUM_REPORT_FILENAME).read_text(encoding="utf-8")
    )
    if report.report_hash != manifest.report_hash:
        raise PaginationErratumIntegrityError("manifest/report binding mismatch")
    if report.erratum.erratum_hash != manifest.erratum_hash:
        raise PaginationErratumIntegrityError("manifest/erratum binding mismatch")
    if report.projection.projection_sha256 != manifest.projection_sha256:
        raise PaginationErratumIntegrityError("manifest/projection binding mismatch")
    if report.replay_certificate.certificate_hash != manifest.replay_certificate_hash:
        raise PaginationErratumIntegrityError("manifest/replay binding mismatch")
    for snapshot in report.erratum.documentation_snapshots:
        body = (output_dir / snapshot.relative_path).read_bytes()
        if _sha256_bytes(body) != snapshot.body_sha256 or len(body) != snapshot.body_bytes:
            raise PaginationErratumIntegrityError(
                f"documentation body changed: {snapshot.document_id}"
            )
    projection = PaginationErratumProjection.model_validate_json(
        (output_dir / PAGINATION_ERRATUM_PROJECTION_FILENAME).read_text(encoding="utf-8")
    )
    replay = PaginationErratumReplayCertificate.model_validate_json(
        (output_dir / PAGINATION_ERRATUM_REPLAY_FILENAME).read_text(encoding="utf-8")
    )
    if projection.projection_sha256 != report.projection.projection_sha256:
        raise PaginationErratumIntegrityError("persisted projection differs")
    if replay.certificate_hash != report.replay_certificate.certificate_hash:
        raise PaginationErratumIntegrityError("persisted replay differs")
    return report, manifest


def execute_pagination_erratum_freeze(
    *,
    protocol: BenchmarkValidityProtocol,
    parent_harness_evidence: ParentHarnessEvidence,
    output_dir: Path,
    integrated_harness_source_path: Path,
    erratum_source_path: Path,
    runner_path: Path,
    interpreters: Mapping[str, Path],
    replay_work_dir: Path,
    parent_git_commit: str,
    built_at: datetime,
    fetcher: DocumentationFetcher = fetch_documentation_response,
) -> tuple[BenchmarkValidityPaginationErratumReport, PaginationErratumManifest]:
    if parent_git_commit != PARENT_HARNESS_COMMIT:
        raise PaginationErratumIntegrityError(
            "erratum must be parented by the completed Task 263.6.7.2 commit"
        )
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"erratum output must be a new empty directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshots = fetch_documentation_snapshots(
        output_dir=output_dir,
        retrieved_at=built_at,
        fetcher=fetcher,
    )
    erratum = build_pagination_erratum(
        protocol=protocol,
        parent_harness_evidence=parent_harness_evidence,
        documentation_snapshots=snapshots,
        frozen_at=built_at,
    )
    projection = build_pagination_erratum_projection(erratum)
    replay = run_pagination_erratum_replay(
        projection=projection,
        runner_path=runner_path,
        interpreters=interpreters,
        work_dir=replay_work_dir,
    )
    report = BenchmarkValidityPaginationErratumReport.create(
        parent_git_commit=parent_git_commit,
        built_at=built_at,
        integrated_harness_source_sha256=_file_sha256(integrated_harness_source_path),
        erratum_source_sha256=_file_sha256(erratum_source_path),
        frozen_runner_sha256=_file_sha256(runner_path),
        erratum=erratum,
        projection=projection,
        replay_certificate=replay,
    )
    return report, write_pagination_erratum(output_dir, report)


__all__ = [
    "DBLP_CAP_POLICY",
    "ERRATUM_CONTRACT_MODELS",
    "PAGINATION_ERRATUM_DOCUMENTATION_DIRECTORY",
    "PAGINATION_ERRATUM_MANIFEST_FILENAME",
    "PAGINATION_ERRATUM_MARKDOWN_FILENAME",
    "PAGINATION_ERRATUM_PROJECTION_FILENAME",
    "PAGINATION_ERRATUM_REPLAY_FILENAME",
    "PAGINATION_ERRATUM_REPORT_FILENAME",
    "PAGINATION_ERRATUM_RUNNER_SOURCE_PATH",
    "PAGINATION_ERRATUM_SCHEMA_FILENAME",
    "PARENT_HARNESS_COMMIT",
    "PARENT_HARNESS_MANIFEST_HASH",
    "PARENT_HARNESS_PROJECTION_HASH",
    "PARENT_HARNESS_REPORT_HASH",
    "PARENT_HARNESS_SOURCE_SHA256",
    "RESOLVED_FINDING_IDS",
    "BenchmarkValidityPaginationErratum",
    "BenchmarkValidityPaginationErratumReport",
    "DocumentationDefinition",
    "DocumentationFetchError",
    "DocumentationFetcher",
    "DocumentationResponse",
    "DocumentationSnapshot",
    "PaginationErratumIntegrityError",
    "PaginationErratumManifest",
    "PaginationErratumProjection",
    "PaginationErratumReplayCertificate",
    "PaginationErratumReplayObservation",
    "PaginationRuleProjection",
    "ParentHarnessEvidence",
    "ProtocolDeviationLedgerEntry",
    "RuleChangeKind",
    "SourcePaginationAmendment",
    "TerminalCondition",
    "build_pagination_erratum",
    "build_pagination_erratum_projection",
    "build_pagination_erratum_replay_payload",
    "documentation_definitions",
    "execute_pagination_erratum_freeze",
    "fetch_documentation_response",
    "fetch_documentation_snapshots",
    "load_pagination_erratum",
    "pagination_erratum_json_schemas",
    "render_pagination_erratum_markdown",
    "run_pagination_erratum_replay",
    "write_pagination_erratum",
]
