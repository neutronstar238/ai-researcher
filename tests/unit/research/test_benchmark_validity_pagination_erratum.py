from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.research import benchmark_validity_pagination_erratum as erratum_module
from autoresearch.research.benchmark_validity_harness import (
    AppendOnlyPrismaJournal,
    FormalSearchBlockedError,
    RawResponseArtifact,
    ResultBlindSearchHarness,
    SearchPageRequest,
    SearchPurpose,
    SearchRunStatus,
    TransportResponse,
    parse_openalex_page,
)
from autoresearch.research.benchmark_validity_pagination_erratum import (
    DBLP_CAP_POLICY,
    PAGINATION_ERRATUM_DOCUMENTATION_DIRECTORY,
    PARENT_HARNESS_MANIFEST_HASH,
    PARENT_HARNESS_PROJECTION_HASH,
    PARENT_HARNESS_REPORT_HASH,
    PARENT_HARNESS_SOURCE_SHA256,
    BenchmarkValidityPaginationErratum,
    DocumentationFetchError,
    DocumentationResponse,
    DocumentationSnapshot,
    PaginationErratumIntegrityError,
    ParentHarnessEvidence,
    RuleChangeKind,
    TerminalCondition,
    build_pagination_erratum,
    build_pagination_erratum_projection,
    build_pagination_erratum_replay_payload,
    documentation_definitions,
    execute_pagination_erratum_freeze,
    load_pagination_erratum,
)
from autoresearch.research.benchmark_validity_protocol import (
    BenchmarkValidityProtocol,
    SearchSourceId,
    build_benchmark_validity_protocol,
)
from autoresearch.research.workload_qualified_opportunity import InterpreterRuntime

ROOT = Path(__file__).resolve().parents[3]
PROTOCOL_SOURCE = ROOT / "src/autoresearch/research/benchmark_validity_protocol.py"
PROTOCOL_RUNNER = (
    ROOT / "src/autoresearch/research/assets/frozen_benchmark_validity_protocol_probe_v1.py"
)
ERRATUM_SOURCE = ROOT / "src/autoresearch/research/benchmark_validity_pagination_erratum.py"
INTEGRATED_HARNESS_SOURCE = ROOT / "src/autoresearch/research/benchmark_validity_harness.py"
ERRATUM_RUNNER = (
    ROOT / "src/autoresearch/research/assets/"
    "frozen_benchmark_validity_pagination_erratum_probe_v1.py"
)
FROZEN_AT = datetime(2026, 7, 31, 9, 38, 52, 843137, tzinfo=timezone.utc)
CHECKED_AT = datetime(2026, 7, 31, 18, 0, tzinfo=timezone.utc)
PROTOCOL_PARENT_COMMIT = "b890aef4b5f254275f9edb2509fe6f1b4a0ae9f2"


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _protocol() -> BenchmarkValidityProtocol:
    return build_benchmark_validity_protocol(
        frozen_at=FROZEN_AT,
        parent_git_commit=PROTOCOL_PARENT_COMMIT,
        protocol_source_sha256=_file_hash(PROTOCOL_SOURCE),
        frozen_runner_sha256=_file_hash(PROTOCOL_RUNNER),
    )


def _parent_evidence(protocol: BenchmarkValidityProtocol) -> ParentHarnessEvidence:
    return ParentHarnessEvidence.create(
        protocol_hash=protocol.protocol_hash,
        harness_source_sha256=PARENT_HARNESS_SOURCE_SHA256,
        report_hash=PARENT_HARNESS_REPORT_HASH,
        projection_sha256=PARENT_HARNESS_PROJECTION_HASH,
        manifest_hash=PARENT_HARNESS_MANIFEST_HASH,
    )


def _documentation_response(url: str) -> DocumentationResponse:
    definition = next(item for item in documentation_definitions() if item.url == url)
    body = ("\n".join(definition.required_markers) + "\n").encode()
    return DocumentationResponse(
        status_code=200,
        media_type="text/html",
        body=body,
        final_url=url,
    )


def _documentation_snapshots() -> list[DocumentationSnapshot]:
    return [
        DocumentationSnapshot.create(
            definition=definition,
            response=_documentation_response(definition.url),
            retrieved_at=CHECKED_AT,
        )
        for definition in documentation_definitions()
    ]


def _erratum() -> BenchmarkValidityPaginationErratum:
    protocol = _protocol()
    return build_pagination_erratum(
        protocol=protocol,
        parent_harness_evidence=_parent_evidence(protocol),
        documentation_snapshots=_documentation_snapshots(),
        frozen_at=CHECKED_AT,
    )


def _runtime(role_id: str) -> InterpreterRuntime:
    suffix = "a" if role_id == "reviewer-a" else "b"
    return InterpreterRuntime.create(
        role_id=role_id,
        executable_locator_hash=canonical_sha256(f"pagination-python-{suffix}"),
        executable_sha256=("3" if suffix == "a" else "4") * 64,
        python_version="Python 3.10.test",
    )


def _formal_request(source_id: SearchSourceId) -> SearchPageRequest:
    endpoint = {
        SearchSourceId.OPENALEX: "https://api.openalex.org/works",
    }[source_id]
    return SearchPageRequest.create(
        purpose=SearchPurpose.FORMAL_CENSUS,
        query_or_probe_id=f"fixture-{source_id.value}",
        source_id=source_id,
        page_index=0,
        attempt_index=0,
        endpoint_url=endpoint,
        request_parameters={"cursor": "*", "per-page": "100"},
    )


def _artifact(request: SearchPageRequest, body: bytes) -> RawResponseArtifact:
    return RawResponseArtifact.create(
        request_hash=request.request_hash,
        received_at=CHECKED_AT,
        status_code=200,
        response_headers={"content-type": "application/json"},
        final_url=request.canonical_url,
        media_type="application/json",
        body=body,
    )


def _crossref_body() -> bytes:
    return json.dumps(
        {
            "status": "ok",
            "message": {
                "total-results": 1,
                "next-cursor": "cursor-is-still-returned",
                "items": [
                    {
                        "DOI": "10.5555/pagination-test",
                        "title": ["Pagination test"],
                        "author": [{"given": "Alice", "family": "Example"}],
                        "published": {"date-parts": [[2024, 7, 1]]},
                    }
                ],
            },
        }
    ).encode()


def _dblp_body(*, total: int) -> bytes:
    return json.dumps(
        {
            "result": {
                "hits": {
                    "@total": str(total),
                    "@sent": "1",
                    "hit": [
                        {
                            "info": {
                                "key": "conf/example/Pagination24",
                                "title": "Pagination test",
                                "authors": {"author": "Alice Example"},
                                "year": "2024",
                                "url": "https://dblp.org/rec/conf/example/Pagination24",
                            }
                        }
                    ],
                }
            }
        }
    ).encode()


class RecordingTransport:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.calls: list[dict[str, str]] = []

    def __call__(
        self,
        *,
        endpoint_url: str,
        parameters: Mapping[str, str],
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_bytes: int,
    ) -> TransportResponse:
        del headers, timeout_seconds, max_bytes
        self.calls.append(dict(parameters))
        return TransportResponse(
            status_code=200,
            headers={"Content-Type": "application/json"},
            body=self.body,
            final_url=endpoint_url,
        )


def test_erratum_freezes_documented_rules_without_result_activity() -> None:
    erratum = _erratum()
    rules = {item.source_id: item for item in erratum.amendments}

    assert erratum.formal_search_execution_count == 0
    assert erratum.bibliographic_record_count == 0
    assert erratum.screening_decision_count == 0
    assert erratum.admission_card_count == 0
    assert erratum.benchmark_outcomes_accessed is False
    assert erratum.candidate_model_calls is False
    assert rules[SearchSourceId.ARXIV].change_kind is RuleChangeKind.UNCHANGED
    assert rules[SearchSourceId.ARXIV].documentation_snapshot_ids == []
    assert (
        rules[SearchSourceId.CROSSREF].terminal_condition is TerminalCondition.CROSSREF_SHORT_PAGE
    )
    assert rules[SearchSourceId.CROSSREF].initial_parameters == {"cursor": "*"}
    assert rules[SearchSourceId.DBLP].cap_policy == DBLP_CAP_POLICY
    assert rules[SearchSourceId.DBLP].documented_year_filter_available is False
    assert all(not item.query_terms_changed for item in rules.values())


def test_primary_documentation_markers_fail_closed() -> None:
    crossref = documentation_definitions()[0]
    with pytest.raises(DocumentationFetchError, match="markers missing"):
        DocumentationSnapshot.create(
            definition=crossref,
            response=DocumentationResponse(
                status_code=200,
                media_type="text/html",
                body=b"cursor=* only",
                final_url=crossref.url,
            ),
            retrieved_at=CHECKED_AT,
        )

    dblp_syntax = next(
        item for item in documentation_definitions() if item.document_id == "dblp-query-syntax"
    )
    body = "\n".join((*dblp_syntax.required_markers, "year:2024")).encode()
    with pytest.raises(DocumentationFetchError, match="year-filter assumption"):
        DocumentationSnapshot.create(
            definition=dblp_syntax,
            response=DocumentationResponse(
                status_code=200,
                media_type="text/html",
                body=body,
                final_url=dblp_syntax.url,
            ),
            retrieved_at=CHECKED_AT,
        )


def test_openalex_null_cursor_needs_an_empty_result_page() -> None:
    request = _formal_request(SearchSourceId.OPENALEX)
    nonempty_body = json.dumps(
        {
            "meta": {"count": 1, "next_cursor": None},
            "results": [
                {
                    "id": "https://openalex.org/W1",
                    "display_name": "Pagination test",
                    "publication_date": "2024-07-01",
                }
            ],
        }
    ).encode()
    nonempty = parse_openalex_page(
        request=request,
        artifact=_artifact(request, nonempty_body),
        body=nonempty_body,
    )
    assert nonempty.exhausted is False
    assert nonempty.next_parameters is None

    empty_body = json.dumps({"meta": {"count": 1, "next_cursor": None}, "results": []}).encode()
    empty = parse_openalex_page(
        request=request,
        artifact=_artifact(request, empty_body),
        body=empty_body,
    )
    assert empty.exhausted is True


def test_formal_crossref_requires_erratum_then_stops_on_short_page(
    tmp_path: Path,
) -> None:
    protocol = _protocol()
    transport = RecordingTransport(_crossref_body())
    blocked = ResultBlindSearchHarness(
        protocol=protocol,
        journal=AppendOnlyPrismaJournal(tmp_path / "blocked", protocol_hash=protocol.protocol_hash),
        transport=transport,
        allow_formal_execution=True,
        now=lambda: CHECKED_AT,
        monotonic=lambda: 0.0,
        sleep=lambda _: None,
    )
    with pytest.raises(FormalSearchBlockedError, match="protocol erratum"):
        blocked.execute_formal_binding("crossref:literature-discovery")

    authorized = ResultBlindSearchHarness(
        protocol=protocol,
        journal=AppendOnlyPrismaJournal(
            tmp_path / "authorized", protocol_hash=protocol.protocol_hash
        ),
        transport=transport,
        allow_formal_execution=True,
        pagination_erratum=_erratum(),
        now=lambda: CHECKED_AT,
        monotonic=lambda: 0.0,
        sleep=lambda _: None,
    )
    result = authorized.execute_formal_binding("crossref:literature-discovery")

    assert result.status is SearchRunStatus.COMPLETE
    assert result.completion_reason == "source-exhausted"
    assert result.successful_page_count == 1
    assert len(transport.calls) == 1
    assert transport.calls[0]["cursor"] == "*"


def test_capped_dblp_response_is_retained_partial_without_year_query(
    tmp_path: Path,
) -> None:
    protocol = _protocol()
    transport = RecordingTransport(_dblp_body(total=1000))
    harness = ResultBlindSearchHarness(
        protocol=protocol,
        journal=AppendOnlyPrismaJournal(tmp_path / "dblp", protocol_hash=protocol.protocol_hash),
        transport=transport,
        allow_formal_execution=True,
        pagination_erratum=_erratum(),
        now=lambda: CHECKED_AT,
        monotonic=lambda: 0.0,
        sleep=lambda _: None,
    )
    result = harness.execute_formal_binding("dblp:literature-discovery")

    assert result.status is SearchRunStatus.PARTIAL
    assert result.completion_reason == "dblp-cap-retained-partial-stop"
    assert result.successful_page_count == 1
    assert len(transport.calls) == 1
    assert transport.calls[0]["f"] == "0"
    assert transport.calls[0]["h"] == "1000"
    assert "year" not in transport.calls[0]
    assert "year:" not in transport.calls[0]["q"]


def test_frozen_runner_rejects_result_bearing_projection(tmp_path: Path) -> None:
    projection = build_pagination_erratum_projection(_erratum())
    payload = build_pagination_erratum_replay_payload(projection)
    payload["projection"]["model_output"] = "forbidden"
    payload["expected_projection_sha256"] = canonical_sha256(payload["projection"])
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(ERRATUM_RUNNER),
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )

    assert completed.returncode != 0
    assert "result-bearing field is forbidden" in completed.stderr


def test_mocked_erratum_package_replays_loads_and_rejects_tamper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    protocol = _protocol()

    def fake_probe(*, role_id: str, executable: Path) -> InterpreterRuntime:
        del executable
        return _runtime(role_id)

    monkeypatch.setattr(erratum_module, "probe_interpreter_runtime", fake_probe)
    output_dir = tmp_path / "erratum"
    report, manifest = execute_pagination_erratum_freeze(
        protocol=protocol,
        parent_harness_evidence=_parent_evidence(protocol),
        output_dir=output_dir,
        integrated_harness_source_path=INTEGRATED_HARNESS_SOURCE,
        erratum_source_path=ERRATUM_SOURCE,
        runner_path=ERRATUM_RUNNER,
        interpreters={
            "reviewer-a": Path(sys.executable),
            "reviewer-b": Path(sys.executable),
        },
        replay_work_dir=tmp_path / "replay",
        parent_git_commit=erratum_module.PARENT_HARNESS_COMMIT,
        built_at=CHECKED_AT,
        fetcher=_documentation_response,
    )
    loaded_report, loaded_manifest = load_pagination_erratum(output_dir)

    assert report.report_hash == loaded_report.report_hash
    assert manifest.manifest_hash == loaded_manifest.manifest_hash
    assert report.replay_certificate.exact_projection_match
    assert report.formal_search_execution_count == 0
    assert report.integrated_harness_source_sha256 == _file_hash(INTEGRATED_HARNESS_SOURCE)
    assert report.bibliographic_record_count == 0
    assert report.benchmark_outcomes_accessed is False
    assert len(report.erratum.documentation_snapshots) == 4

    raw_path = next((output_dir / PAGINATION_ERRATUM_DOCUMENTATION_DIRECTORY).glob("*.bin"))
    raw_path.write_bytes(raw_path.read_bytes() + b"tamper")
    with pytest.raises(PaginationErratumIntegrityError, match="artifact hash mismatch"):
        load_pagination_erratum(output_dir)
