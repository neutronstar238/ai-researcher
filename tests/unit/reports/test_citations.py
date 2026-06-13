import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.reports import (
    CitationGenerationError,
    CitationStatus,
    generate_bibtex,
    validate_citations,
)
from autoresearch.schemas import DocumentRecord


def test_validate_citations_reports_doi_url_and_blocked_statuses() -> None:
    documents = _documents()

    validations = validate_citations(documents)

    assert [validation.status for validation in validations] == [
        CitationStatus.VERIFIED_DOI,
        CitationStatus.VERIFIED_URL,
        CitationStatus.BLOCKED,
    ]
    assert validations[0].doi == "10.1234/example"
    assert validations[1].url == "https://example.com/url-paper"
    assert validations[2].reason == "citation lacks DOI or URL"
    assert validations[0].abstract == "Evidence-bound autonomous research loop."
    assert validations[0].venue == "AutoResearch Workshop"
    assert validations[0].authors == ("A. Researcher",)
    assert validations[0].tags == ("evidence", "research-loop")


def test_generate_bibtex_writes_verified_entries_and_blocked_metadata(
    tmp_path: Path,
) -> None:
    documents = _documents()

    artifact = generate_bibtex(documents, tmp_path / "paper")

    bibtex = Path(artifact.bib_path).read_text(encoding="utf-8")
    metadata = json.loads(Path(artifact.metadata_path).read_text(encoding="utf-8"))
    assert "@article{researcher2026" in bibtex
    assert "doi = {10.1234/example}" in bibtex
    assert "@misc{reviewer2026" in bibtex
    assert "url = {https://example.com/url-paper}" in bibtex
    assert "% BLOCKED doc_blocked: citation lacks DOI or URL" in bibtex
    assert artifact.blocked_document_ids == ("doc_blocked",)
    assert metadata["blocked_document_ids"] == ["doc_blocked"]
    assert metadata["citations"][0]["abstract"] == "Evidence-bound autonomous research loop."
    assert metadata["citations"][0]["venue"] == "AutoResearch Workshop"
    assert metadata["citations"][0]["source_uri"] == "https://example.com/doi-paper"
    assert metadata["citations"][0]["authors"] == ["A. Researcher"]
    assert metadata["citations"][0]["tags"] == ["evidence", "research-loop"]
    assert [citation["status"] for citation in metadata["citations"]] == [
        "verified_doi",
        "verified_url",
        "blocked",
    ]


def test_validate_citations_rejects_empty_document_list() -> None:
    with pytest.raises(CitationGenerationError, match="at least one"):
        validate_citations([])


def _documents() -> list[DocumentRecord]:
    publication_date = datetime(2026, 6, 11, tzinfo=timezone.utc)
    return [
        DocumentRecord(
            id="doc_doi",
            title="Evidence First Research",
            source_uri="https://example.com/doi-paper",
            authors=["A. Researcher"],
            abstract="Evidence-bound autonomous research loop.",
            publication_date=publication_date,
            venue="AutoResearch Workshop",
            doi="DOI:10.1234/EXAMPLE",
            tags=["evidence", "research-loop"],
        ),
        DocumentRecord(
            id="doc_url",
            title="URL Backed Research",
            source_uri="https://example.com/url-paper",
            authors=["B. Reviewer"],
            publication_date=publication_date,
            venue="ExampleConf",
        ),
        DocumentRecord(
            id="doc_blocked",
            title="Unverifiable Local Note",
            source_uri="local-note",
            authors=["C. Author"],
            publication_date=publication_date,
        ),
    ]
