from __future__ import annotations

import json

from autoresearch.literature.doi_verification import (
    DoiVerification,
    ReferenceVerificationReceipt,
    verify_doi,
    verify_reference_records,
)


def _crossref_response(title: str = "Permutation Entropy: A Natural Complexity Measure") -> str:
    return json.dumps(
        {
            "message": {
                "title": [title],
                "author": [
                    {"family": "Bandt", "given": "Christoph"},
                    {"family": "Pompe", "given": "Bernd"},
                ],
                "container-title": ["Physical Review Letters"],
            }
        }
    )


def test_verify_doi_resolves_and_matches_title() -> None:
    def http_get(url: str, timeout: int) -> str:
        del url, timeout
        return _crossref_response()

    result = verify_doi(
        "https://doi.org/10.1103/PhysRevLett.88.174102",
        expected_title="Permutation entropy: a natural complexity measure",
        http_get=http_get,
    )

    assert result.status == "resolved"
    assert result.resolved is True
    assert result.title_match == "match"
    assert result.title_consistent is True
    assert result.resolved_authors == ("Christoph Bandt", "Bernd Pompe")
    assert result.container_title == "Physical Review Letters"
    assert result.doi == "10.1103/physrevlett.88.174102"


def test_verify_doi_flags_a_mismatched_title() -> None:
    def http_get(url: str, timeout: int) -> str:
        del url, timeout
        return _crossref_response(title="An unrelated work")

    result = verify_doi(
        "10.1103/PhysRevLett.88.174102",
        expected_title="Permutation Entropy: A Natural Complexity Measure",
        http_get=http_get,
    )

    assert result.status == "resolved"
    assert result.title_match == "mismatch"
    assert result.title_consistent is False


def test_verify_doi_returns_unknown_match_when_no_title_is_expected() -> None:
    def http_get(url: str, timeout: int) -> str:
        del url, timeout
        return _crossref_response()

    result = verify_doi("10.1103/PhysRevLett.88.174102", http_get=http_get)

    assert result.status == "resolved"
    assert result.title_match == "unknown"
    assert result.title_consistent is True


def test_verify_doi_reports_unresolved_on_404() -> None:
    import urllib.error

    def http_get(url: str, timeout: int) -> str:
        del timeout
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    result = verify_doi("10.1000/does-not-exist", http_get=http_get)

    assert result.status == "unresolved"
    assert result.resolved is False
    assert "404" in (result.reason or "")


def test_verify_doi_reports_error_on_transport_failure() -> None:
    import urllib.error

    def http_get(url: str, timeout: int) -> str:
        del url, timeout
        raise urllib.error.URLError("connection refused")

    result = verify_doi("10.1000/example", http_get=http_get)

    assert result.status == "error"
    assert result.reason is not None


def test_verify_doi_rejects_un_normalizable_input() -> None:
    result = verify_doi("not a doi", http_get=lambda _url, _t: _crossref_response())

    assert result.status == "error"
    assert "format" in (result.reason or "")


def test_verify_doi_tolerates_doi_prefix_forms() -> None:
    seen: list[str] = []

    def http_get(url: str, timeout: int) -> str:
        del timeout
        seen.append(url)
        return _crossref_response()

    result = verify_doi("doi:10.1103/PhysRevLett.88.174102", http_get=http_get)

    assert result.status == "resolved"
    assert seen and seen[0].startswith(
        "https://api.crossref.org/works/10.1103%2Fphysrevlett.88.174102"
    )


def test_to_dict_serializes_verification_fields() -> None:
    payload = DoiVerification(
        doi="10.1000/x",
        status="resolved",
        resolved_title="Title",
        title_match="match",
        resolved_authors=("A Author",),
        container_title="Journal",
    ).to_dict()

    assert payload["doi"] == "10.1000/x"
    assert payload["status"] == "resolved"
    assert payload["title_match"] == "match"
    assert payload["resolved_authors"] == ["A Author"]


def test_verify_reference_records_skips_repository_doi_and_url_only_records() -> None:
    def http_get(url: str, timeout: int) -> str:
        del url, timeout
        return _crossref_response()

    records = [
        {
            "record_id": "r1",
            "title": "Permutation Entropy: A Natural Complexity Measure",
            "doi": "10.1103/PhysRevLett.88.174102",
        },
        {"record_id": "r2", "title": "A preprint", "repository_doi": "10.48550/arXiv.2606.00001"},
        {"record_id": "r3", "title": "No identifier"},
    ]

    receipt = verify_reference_records(records, http_get=http_get)

    assert receipt.skipped_count == 2
    assert len(receipt.verified) == 1
    assert receipt.resolved_count == 1
    assert receipt.mismatch_count == 0
    assert receipt.title_consistent is True


def test_verify_reference_records_detects_title_mismatch() -> None:
    def http_get(url: str, timeout: int) -> str:
        del url, timeout
        return _crossref_response(title="Something else entirely")

    records = [{"record_id": "r1", "title": "Permutation Entropy", "publication_doi": "10.1103/PhysRevLett.88.174102"}]

    receipt = verify_reference_records(records, http_get=http_get)

    assert receipt.mismatch_count == 1
    assert receipt.title_consistent is False


def test_verify_reference_records_receipt_serializes() -> None:
    receipt = ReferenceVerificationReceipt(
        verified=(
            DoiVerification(
                doi="10.1000/x",
                status="resolved",
                resolved_title="T",
                title_match="match",
                resolved_authors=(),
                container_title=None,
            ),
        ),
        skipped_count=3,
    )

    payload = receipt.to_dict()

    assert payload["schema_version"] == "contest-reference-doi-verification-v1"
    assert payload["resolved_count"] == 1
    assert payload["mismatch_count"] == 0
    assert payload["skipped_count"] == 3
    assert len(payload["verified"]) == 1
