from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from collections.abc import Mapping
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.research import benchmark_validity_harness as harness_module
from autoresearch.research.benchmark_validity_harness import (
    FROZEN_BENCHMARK_VALIDITY_PROTOCOL_HASH,
    FROZEN_BENCHMARK_VALIDITY_PROTOCOL_SOURCE_SHA256,
    HARNESS_RAW_DIRECTORY,
    AppendOnlyPrismaJournal,
    BenchmarkValidityHarnessIntegrityError,
    BibliographicRecord,
    CompatibilitySeverity,
    EmptyAdmissionEvidencePacket,
    FamilyLineageObservation,
    FormalSearchBlockedError,
    RawResponseArtifact,
    ResultBlindSearchHarness,
    SearchPageRequest,
    SearchPurpose,
    SearchRunStatus,
    TransportResponse,
    audit_protocol_adapter_compatibility,
    benchmark_validity_harness_json_schemas,
    build_adapter_contracts,
    build_capability_probe_specs,
    build_empty_evidence_packet,
    build_empty_evidence_packet_template,
    build_frozen_screening_form,
    deduplicate_bibliographic_records,
    deduplicate_family_revisions,
    evaluate_known_item_recall,
    execute_benchmark_validity_capability_harness,
    load_benchmark_validity_harness,
    parse_arxiv_page,
    parse_crossref_page,
    parse_dblp_page,
    parse_openalex_page,
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
    ROOT
    / "src/autoresearch/research/assets/frozen_benchmark_validity_protocol_probe_v1.py"
)
HARNESS_SOURCE = ROOT / "src/autoresearch/research/benchmark_validity_harness.py"
HARNESS_RUNNER = (
    ROOT
    / "src/autoresearch/research/assets/frozen_benchmark_validity_harness_probe_v1.py"
)
FROZEN_AT = datetime(2026, 7, 31, 9, 38, 52, 843137, tzinfo=timezone.utc)
CHECKED_AT = datetime(2026, 7, 31, 10, 0, tzinfo=timezone.utc)
PARENT_COMMIT = "b890aef4b5f254275f9edb2509fe6f1b4a0ae9f2"


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _protocol() -> BenchmarkValidityProtocol:
    protocol = build_benchmark_validity_protocol(
        frozen_at=FROZEN_AT,
        parent_git_commit=PARENT_COMMIT,
        protocol_source_sha256=_file_hash(PROTOCOL_SOURCE),
        frozen_runner_sha256=_file_hash(PROTOCOL_RUNNER),
    )
    assert protocol.protocol_hash == FROZEN_BENCHMARK_VALIDITY_PROTOCOL_HASH
    return protocol


def _request(
    source_id: SearchSourceId,
    *,
    parameters: dict[str, str],
    purpose: SearchPurpose = SearchPurpose.API_CAPABILITY_SMOKE,
) -> SearchPageRequest:
    endpoint = {
        SearchSourceId.ARXIV: "https://export.arxiv.org/api/query",
        SearchSourceId.OPENALEX: "https://api.openalex.org/works",
        SearchSourceId.CROSSREF: "https://api.crossref.org/works",
        SearchSourceId.DBLP: "https://dblp.org/search/publ/api",
    }[source_id]
    return SearchPageRequest.create(
        purpose=purpose,
        query_or_probe_id=f"fixture-{source_id.value}",
        source_id=source_id,
        page_index=0,
        attempt_index=0,
        endpoint_url=endpoint,
        request_parameters=parameters,
    )


def _artifact(request: SearchPageRequest, body: bytes) -> RawResponseArtifact:
    return RawResponseArtifact.create(
        request_hash=request.request_hash,
        received_at=CHECKED_AT,
        status_code=200,
        response_headers={"content-type": "application/json"},
        final_url=request.canonical_url,
        media_type=(
            "application/atom+xml"
            if request.source_id is SearchSourceId.ARXIV
            else "application/json"
        ),
        body=body,
    )


def _arxiv_xml(*, total: int = 1, title: str = "CORE-Bench") -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <opensearch:totalResults>{total}</opensearch:totalResults>
  <entry>
    <id>https://arxiv.org/abs/2409.11363v2</id>
    <title>{title}</title>
    <summary>Computational reproducibility benchmark.</summary>
    <published>2024-09-17T00:00:00Z</published>
    <author><name>Alice Example</name></author>
    <arxiv:doi>10.5555/core-bench</arxiv:doi>
  </entry>
</feed>""".encode()


def _openalex_json(*, next_cursor: str | None = None) -> bytes:
    return json.dumps(
        {
            "meta": {"count": 1, "next_cursor": next_cursor},
            "results": [
                {
                    "id": "https://openalex.org/W123",
                    "display_name": "CORE-Bench",
                    "doi": "https://doi.org/10.5555/core-bench",
                    "publication_date": "2024-09-17",
                    "publication_year": 2024,
                    "authorships": [
                        {"author": {"display_name": "Alice Example"}}
                    ],
                    "abstract_inverted_index": {
                        "Computational": [0],
                        "benchmark": [1],
                    },
                    "primary_location": {
                        "landing_page_url": "https://openalex.org/W123"
                    },
                    "ids": {"openalex": "https://openalex.org/W123"},
                }
            ],
        }
    ).encode()


def _crossref_json(*, item_count: int = 1, next_cursor: str = "still-present") -> bytes:
    item = {
        "DOI": "10.5555/core-bench",
        "title": ["CORE-Bench"],
        "author": [{"given": "Alice", "family": "Example"}],
        "published": {"date-parts": [[2024, 9, 17]]},
        "URL": "https://doi.org/10.5555/core-bench",
        "abstract": "<jats:p>Computational benchmark.</jats:p>",
    }
    return json.dumps(
        {
            "status": "ok",
            "message": {
                "total-results": item_count,
                "next-cursor": next_cursor,
                "items": [item for _ in range(item_count)],
            },
        }
    ).encode()


def _dblp_json(*, total: int = 1) -> bytes:
    return json.dumps(
        {
            "result": {
                "hits": {
                    "@total": str(total),
                    "@sent": "1",
                    "hit": [
                        {
                            "info": {
                                "key": "journals/tmlr/Example24",
                                "title": "CORE-Bench",
                                "authors": {"author": ["Alice Example"]},
                                "year": "2024",
                                "doi": "10.5555/core-bench",
                                "url": "https://dblp.org/rec/journals/tmlr/Example24",
                            }
                        }
                    ],
                }
            }
        }
    ).encode()


def _response_for_endpoint(endpoint_url: str) -> bytes:
    if "arxiv" in endpoint_url:
        return _arxiv_xml()
    if "openalex" in endpoint_url:
        return _openalex_json()
    if "crossref" in endpoint_url:
        return _crossref_json()
    if "dblp" in endpoint_url:
        return _dblp_json()
    raise AssertionError(endpoint_url)


class ScriptedTransport:
    def __init__(self) -> None:
        self.responses: dict[str, list[TransportResponse]] = defaultdict(list)
        self.calls: list[tuple[str, dict[str, str]]] = []

    def queue(self, endpoint_fragment: str, *responses: TransportResponse) -> None:
        self.responses[endpoint_fragment].extend(responses)

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
        self.calls.append((endpoint_url, dict(parameters)))
        for fragment, responses in self.responses.items():
            if fragment in endpoint_url and responses:
                return responses.pop(0)
        body = _response_for_endpoint(endpoint_url)
        media_type = "application/atom+xml" if "arxiv" in endpoint_url else "application/json"
        return TransportResponse(
            status_code=200,
            headers={"Content-Type": media_type},
            body=body,
            final_url=endpoint_url,
        )


def _runtime(role_id: str) -> InterpreterRuntime:
    suffix = "a" if role_id == "reviewer-a" else "b"
    return InterpreterRuntime.create(
        role_id=role_id,
        executable_locator_hash=canonical_sha256(f"python-{suffix}"),
        executable_sha256=("1" if suffix == "a" else "2") * 64,
        python_version="Python 3.10.test",
    )


def test_harness_contracts_bind_protocol_and_block_known_pagination_drift(
    tmp_path: Path,
) -> None:
    protocol = _protocol()

    assert _file_hash(PROTOCOL_SOURCE) == FROZEN_BENCHMARK_VALIDITY_PROTOCOL_SOURCE_SHA256
    contracts = build_adapter_contracts(protocol)
    assert {item.source_id for item in contracts} == set(SearchSourceId)
    findings = audit_protocol_adapter_compatibility(protocol)
    crossref = next(item for item in findings if item.source_id is SearchSourceId.CROSSREF)
    assert crossref.severity is CompatibilitySeverity.FORMAL_BLOCKER
    assert crossref.formal_search_allowed is False
    assert "last page" in crossref.current_documented_rule
    probes = build_capability_probe_specs(protocol)
    assert len(probes) == 4
    assert all(not item.formal_search_binding for item in probes)
    crossref_probe = next(
        item for item in probes if item.source_id is SearchSourceId.CROSSREF
    )
    assert crossref_probe.request_parameters["cursor"] == "*"
    form = build_frozen_screening_form(protocol)
    packet_template = build_empty_evidence_packet_template(protocol)
    assert len(form.criteria) == len(protocol.eligibility_criteria)
    assert len(packet_template.fields) == 42
    assert not any(field.value_present for field in packet_template.fields)

    journal = AppendOnlyPrismaJournal(tmp_path, protocol_hash=protocol.protocol_hash)
    harness = ResultBlindSearchHarness(
        protocol=protocol,
        journal=journal,
        transport=ScriptedTransport(),
        allow_formal_execution=False,
    )
    with pytest.raises(FormalSearchBlockedError, match="disabled"):
        harness.execute_formal_binding("arxiv:literature-discovery")

    harness = ResultBlindSearchHarness(
        protocol=protocol,
        journal=journal,
        transport=ScriptedTransport(),
        allow_formal_execution=True,
    )
    with pytest.raises(FormalSearchBlockedError, match="protocol erratum"):
        harness.execute_formal_binding("crossref:literature-discovery")


def test_all_four_parsers_preserve_documented_pagination_boundaries() -> None:
    arxiv_request = _request(
        SearchSourceId.ARXIV,
        parameters={"start": "0", "max_results": "1"},
    )
    arxiv_body = _arxiv_xml(total=2)
    arxiv_page = parse_arxiv_page(
        request=arxiv_request,
        artifact=_artifact(arxiv_request, arxiv_body),
        body=arxiv_body,
    )
    assert arxiv_page.next_parameters == {"start": "1", "max_results": "1"}
    assert not arxiv_page.exhausted

    openalex_request = _request(
        SearchSourceId.OPENALEX,
        parameters={"cursor": "*", "per-page": "1", "search": "CORE-Bench"},
    )
    openalex_body = _openalex_json(next_cursor="cursor-2")
    openalex_page = parse_openalex_page(
        request=openalex_request,
        artifact=_artifact(openalex_request, openalex_body),
        body=openalex_body,
    )
    assert openalex_page.next_parameters is not None
    assert openalex_page.next_parameters["cursor"] == "cursor-2"

    crossref_request = _request(
        SearchSourceId.CROSSREF,
        parameters={"cursor": "*", "rows": "2"},
    )
    crossref_body = _crossref_json(item_count=1, next_cursor="still-present")
    crossref_page = parse_crossref_page(
        request=crossref_request,
        artifact=_artifact(crossref_request, crossref_body),
        body=crossref_body,
    )
    assert crossref_page.exhausted
    assert crossref_page.next_parameters is None

    dblp_request = _request(
        SearchSourceId.DBLP,
        purpose=SearchPurpose.FORMAL_CENSUS,
        parameters={"q": "agent$", "h": "1000", "f": "0", "c": "0"},
    )
    dblp_body = _dblp_json(total=1000)
    dblp_page = parse_dblp_page(
        request=dblp_request,
        artifact=_artifact(dblp_request, dblp_body),
        body=dblp_body,
    )
    assert dblp_page.requires_frozen_year_split
    assert not dblp_page.exhausted
    assert dblp_page.next_parameters is None


def test_retry_raw_response_journal_and_tamper_detection(tmp_path: Path) -> None:
    protocol = _protocol()
    journal = AppendOnlyPrismaJournal(tmp_path, protocol_hash=protocol.protocol_hash)
    transport = ScriptedTransport()
    transport.queue(
        "arxiv",
        TransportResponse(
            status_code=429,
            headers={"Content-Type": "text/plain", "Retry-After": "0"},
            body=b"rate limited",
            final_url="https://export.arxiv.org/api/query",
        ),
        TransportResponse(
            status_code=200,
            headers={"Content-Type": "application/atom+xml"},
            body=_arxiv_xml(),
            final_url="https://export.arxiv.org/api/query",
        ),
    )
    sleeps: list[float] = []
    harness = ResultBlindSearchHarness(
        protocol=protocol,
        journal=journal,
        transport=transport,
        now=lambda: CHECKED_AT,
        monotonic=lambda: 0.0,
        sleep=sleeps.append,
    )
    probe = next(
        item
        for item in build_capability_probe_specs(protocol)
        if item.source_id is SearchSourceId.ARXIV
    )
    summary = harness.execute_capability_probe(probe)

    assert summary.status is SearchRunStatus.CAPABILITY_ONLY
    assert summary.request_attempt_count == 2
    assert summary.retry_count == 1
    assert summary.response_count == 1
    assert len(journal.read_page_entries()) == 2
    assert len(journal.read_execution_entries()) == 1
    snapshot = journal.snapshot()
    assert len(snapshot.raw_response_hashes) == 2
    assert snapshot.bibliographic_record_count == 1
    assert 0.0 in sleeps

    raw_path = next((tmp_path / HARNESS_RAW_DIRECTORY).glob("*.bin"))
    raw_path.write_bytes(raw_path.read_bytes() + b"tamper")
    with pytest.raises(BenchmarkValidityHarnessIntegrityError, match="raw response hash"):
        journal.snapshot()


def _sentinel_records(protocol: BenchmarkValidityProtocol, count: int) -> list[BibliographicRecord]:
    records: list[BibliographicRecord] = []
    for index, sentinel in enumerate(protocol.known_item_sentinels[:count]):
        records.append(
            BibliographicRecord.create(
                source_id=SearchSourceId.ARXIV,
                source_record_id=f"arxiv:sentinel-{index}",
                title=sentinel.title,
                authors=[f"Author {index}"],
                abstract=None,
                publication_date=date(2025, 1, min(index + 1, 28)),
                publication_year=2025,
                doi=None,
                arxiv_id=None,
                openalex_id=None,
                dblp_key=None,
                stable_locator=sentinel.stable_locator,
                raw_response_artifact_hash=f"{index + 1:064x}"[-64:],
                retrieved_at=CHECKED_AT,
            )
        )
    return records


def test_paper_deduplication_and_known_item_recall_are_exact() -> None:
    protocol = _protocol()
    records = _sentinel_records(protocol, 15)
    duplicate = BibliographicRecord.create(
        **{
            **records[0].model_dump(
                mode="python",
                exclude={"schema_version", "record_hash", "source_record_id", "source_id"},
            ),
            "source_id": SearchSourceId.OPENALEX,
            "source_record_id": "openalex:W999",
            "openalex_id": "W999",
            "raw_response_artifact_hash": "f" * 64,
        }
    )
    all_records = [*records, duplicate]
    deduplication = deduplicate_bibliographic_records(all_records)

    assert deduplication.input_record_count == 16
    assert deduplication.unique_paper_count == 15
    assert any(len(item.record_hashes) == 2 for item in deduplication.clusters)
    recall = evaluate_known_item_recall(
        protocol=protocol,
        records=all_records,
        deduplication=deduplication,
        formal_recall_claim=True,
    )
    assert recall.matched_count == 15
    assert recall.recall == 15 / 16
    assert recall.threshold_passed

    fourteen = _sentinel_records(protocol, 14)
    failed = evaluate_known_item_recall(
        protocol=protocol,
        records=fourteen,
        deduplication=deduplicate_bibliographic_records(fourteen),
        formal_recall_claim=True,
    )
    assert failed.recall == 14 / 16
    assert not failed.threshold_passed


def test_family_revision_dedup_prevents_task_and_revision_pseudoreplication() -> None:
    protocol = _protocol()
    observations = [
        FamilyLineageObservation.create(
            observation_id="family-a-v1",
            paper_id="paper-a",
            benchmark_family_id="family-a",
            release_id="family-a-v1",
            release_date=date(2024, 1, 1),
            paper_revision="v1",
            repository_revision="commit-1",
            dataset_revision="dataset-1",
            lineage_keys=["task-pool-a", "generator-a"],
            nested_technical_task_count=90,
            protocol_development_pilot=False,
            independently_human_validated=False,
        ),
        FamilyLineageObservation.create(
            observation_id="family-a-v2",
            paper_id="paper-a2",
            benchmark_family_id="renamed-family-a",
            related_family_ids=["family-a"],
            release_id="family-a-v2",
            release_date=date(2025, 1, 1),
            paper_revision="v2",
            repository_revision="commit-2",
            dataset_revision="dataset-2",
            lineage_keys=["task-pool-a", "generator-a"],
            nested_technical_task_count=270,
            protocol_development_pilot=False,
            independently_human_validated=False,
        ),
        FamilyLineageObservation.create(
            observation_id="core-bench-pilot",
            paper_id="paper-core",
            benchmark_family_id="core-bench",
            release_id="core-bench",
            release_date=date(2024, 9, 17),
            paper_revision="v1",
            lineage_keys=["core-paper-pool"],
            nested_technical_task_count=270,
            protocol_development_pilot=True,
            independently_human_validated=True,
        ),
    ]
    result = deduplicate_family_revisions(protocol=protocol, observations=observations)

    assert result.input_observation_count == 3
    assert result.independent_family_count == 2
    assert result.primary_non_pilot_family_count == 1
    assert result.human_validated_primary_family_count == 0
    nonpilot = next(item for item in result.clusters if not item.protocol_development_pilot)
    assert nonpilot.selected_primary_release_id == "family-a-v2"
    assert nonpilot.independent_unit_count == 1
    assert nonpilot.nested_technical_task_count == 360
    assert not nonpilot.primary_cohort_eligible
    pilot = next(item for item in result.clusters if item.protocol_development_pilot)
    assert pilot.selected_primary_release_id is None
    assert not pilot.primary_cohort_eligible


def test_empty_evidence_packet_has_no_decisions_or_outcomes() -> None:
    protocol = _protocol()
    records = _sentinel_records(protocol, 1)
    cluster = deduplicate_bibliographic_records(records).clusters[0]
    packet = build_empty_evidence_packet(protocol=protocol, paper_cluster=cluster)

    assert len(packet.fields) == 42
    assert packet.screening_decision is None
    assert packet.benchmark_family_decision is None
    assert packet.primary_cohort_eligible is None
    assert packet.admission_card_created is False
    assert packet.benchmark_outcomes_accessed is False
    assert all(item.evidence_state is None for item in packet.fields)
    assert all(not item.value_present for item in packet.fields)

    payload = packet.model_dump(mode="python", exclude={"packet_hash"})
    payload["model_output"] = "forbidden"
    with pytest.raises(ValueError, match="model_output is forbidden"):
        EmptyAdmissionEvidencePacket.create(**payload)


def test_mocked_full_capability_package_replays_and_rejects_tamper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    protocol = _protocol()

    def fake_probe(*, role_id: str, executable: Path) -> InterpreterRuntime:
        del executable
        return _runtime(role_id)

    monkeypatch.setattr(harness_module, "probe_interpreter_runtime", fake_probe)
    output_dir = tmp_path / "formal"
    report, manifest = execute_benchmark_validity_capability_harness(
        protocol=protocol,
        output_dir=output_dir,
        protocol_source_path=PROTOCOL_SOURCE,
        harness_source_path=HARNESS_SOURCE,
        runner_path=HARNESS_RUNNER,
        interpreters={
            "reviewer-a": Path(sys.executable),
            "reviewer-b": Path(sys.executable),
        },
        replay_work_dir=tmp_path / "replay",
        parent_git_commit="2dcd0af",
        built_at=CHECKED_AT,
        transport=ScriptedTransport(),
        now=lambda: CHECKED_AT,
        monotonic=lambda: 0.0,
        sleep=lambda _: None,
    )
    loaded_report, loaded_manifest = load_benchmark_validity_harness(output_dir)

    assert report.report_hash == loaded_report.report_hash
    assert manifest.manifest_hash == loaded_manifest.manifest_hash
    assert report.projection.formal_search_execution_count == 0
    assert report.projection.capability_probe_count == 4
    assert report.projection.protocol_erratum_required
    assert report.projection.formal_census_authorized is False
    assert report.replay_certificate.exact_projection_match
    assert len(report.journal_snapshot.raw_response_hashes) == 4
    assert report.paper_deduplication.unique_paper_count == 1
    assert report.family_revision_deduplication.independent_family_count == 0
    assert report.known_item_recall.formal_recall_claim is False
    schemas = benchmark_validity_harness_json_schemas()
    assert "EmptyAdmissionEvidencePacket" in schemas
    assert "BenchmarkValidityHarnessReport" in schemas

    raw_path = next((output_dir / HARNESS_RAW_DIRECTORY).glob("*.bin"))
    raw_path.write_bytes(raw_path.read_bytes() + b"tamper")
    with pytest.raises(BenchmarkValidityHarnessIntegrityError, match="artifact hash mismatch"):
        load_benchmark_validity_harness(output_dir)


def test_result_bearing_projection_payload_is_rejected_by_frozen_runner(
    tmp_path: Path,
) -> None:
    payload = {
        "expected_projection_sha256": "0" * 64,
        "projection": {
            "schema_version": "benchmark-validity-harness-projection-v1",
            "model_output": "forbidden",
        },
    }
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    import subprocess

    completed = subprocess.run(
        [
            sys.executable,
            str(HARNESS_RUNNER),
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
    assert "model_output is forbidden" in completed.stderr
