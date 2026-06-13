"""Validate citations and generate BibTeX from verified document metadata."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import urlparse

from autoresearch.literature.models import normalize_doi
from autoresearch.schemas import DocumentRecord


class CitationStatus(str, Enum):
    """Verification status for one citation."""

    VERIFIED_DOI = "verified_doi"
    VERIFIED_URL = "verified_url"
    BLOCKED = "blocked"


class CitationGenerationError(RuntimeError):
    """Raised when citations cannot be validated or written."""


class _CitationMetadata(TypedDict):
    abstract: str | None
    venue: str | None
    source_uri: str | None
    authors: tuple[str, ...]
    tags: tuple[str, ...]


@dataclass(frozen=True)
class CitationValidation:
    """Citation verification result for one document."""

    document_id: str
    title: str
    status: CitationStatus
    bibtex_key: str | None
    doi: str | None = None
    url: str | None = None
    reason: str | None = None
    abstract: str | None = None
    venue: str | None = None
    source_uri: str | None = None
    authors: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "title": self.title,
            "status": self.status.value,
            "bibtex_key": self.bibtex_key,
            "doi": self.doi,
            "url": self.url,
            "reason": self.reason,
            "abstract": self.abstract,
            "venue": self.venue,
            "source_uri": self.source_uri,
            "authors": list(self.authors),
            "tags": list(self.tags),
        }


@dataclass(frozen=True)
class BibtexArtifact:
    """Generated BibTeX paths and citation verification results."""

    bib_path: str
    metadata_path: str
    citations: tuple[CitationValidation, ...]

    @property
    def blocked_document_ids(self) -> tuple[str, ...]:
        return tuple(
            citation.document_id
            for citation in self.citations
            if citation.status is CitationStatus.BLOCKED
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bib_path": self.bib_path,
            "metadata_path": self.metadata_path,
            "blocked_document_ids": list(self.blocked_document_ids),
            "citations": [citation.to_dict() for citation in self.citations],
        }


def validate_citations(documents: list[DocumentRecord]) -> list[CitationValidation]:
    """Validate whether documents have DOI or URL-backed citation metadata."""

    if not documents:
        msg = "at least one document is required for citation validation"
        raise CitationGenerationError(msg)
    keys = _unique_keys(documents)
    validations: list[CitationValidation] = []
    for document in documents:
        doi = normalize_doi(document.doi)
        url = _document_url(document)
        metadata = _citation_metadata(document)
        if doi is not None:
            validations.append(
                CitationValidation(
                    document_id=document.id,
                    title=document.title,
                    status=CitationStatus.VERIFIED_DOI,
                    bibtex_key=keys[document.id],
                    doi=doi,
                    url=url,
                    **metadata,
                )
            )
            continue
        if url is not None:
            validations.append(
                CitationValidation(
                    document_id=document.id,
                    title=document.title,
                    status=CitationStatus.VERIFIED_URL,
                    bibtex_key=keys[document.id],
                    url=url,
                    **metadata,
                )
            )
            continue
        validations.append(
            CitationValidation(
                document_id=document.id,
                title=document.title,
                status=CitationStatus.BLOCKED,
                bibtex_key=None,
                reason="citation lacks DOI or URL",
                **metadata,
            )
        )
    return validations


def generate_bibtex(
    documents: list[DocumentRecord],
    output_dir: Path | str,
    *,
    filename: str = "references.bib",
) -> BibtexArtifact:
    """Generate BibTeX for verified citations and metadata for blocked ones."""

    output_path = Path(output_dir).resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    bib_path = output_path / filename
    metadata_path = bib_path.with_suffix(".metadata.json")
    validations = validate_citations(documents)
    documents_by_id = {document.id: document for document in documents}
    bibtex = _render_bibtex(validations, documents_by_id)
    bib_path.write_text(bibtex, encoding="utf-8")

    artifact = BibtexArtifact(
        bib_path=bib_path.as_posix(),
        metadata_path=metadata_path.as_posix(),
        citations=tuple(validations),
    )
    metadata_path.write_text(
        json.dumps(artifact.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return artifact


def _render_bibtex(
    validations: list[CitationValidation],
    documents_by_id: dict[str, DocumentRecord],
) -> str:
    entries: list[str] = []
    for validation in validations:
        document = documents_by_id[validation.document_id]
        if validation.status is CitationStatus.BLOCKED:
            entries.append(
                f"% BLOCKED {document.id}: {validation.reason or 'unverified citation'}"
            )
            continue
        entries.append(_bibtex_entry(document, validation))
    return "\n\n".join(entries) + "\n"


def _bibtex_entry(
    document: DocumentRecord,
    validation: CitationValidation,
) -> str:
    entry_type = "article" if validation.doi is not None else "misc"
    fields = [
        ("title", document.title),
        ("author", _authors(document)),
    ]
    year = _publication_year(document)
    if year is not None:
        fields.append(("year", year))
    if document.venue is not None:
        fields.append(("journal", document.venue))
    if validation.doi is not None:
        fields.append(("doi", validation.doi))
    if validation.url is not None:
        fields.append(("url", validation.url))
    field_lines = [
        f"  {name} = {{{_bibtex_escape(value)}}}"
        for name, value in fields
        if value
    ]
    return (
        f"@{entry_type}{{{validation.bibtex_key},\n"
        + ",\n".join(field_lines)
        + "\n}"
    )


def _unique_keys(documents: list[DocumentRecord]) -> dict[str, str]:
    keys: dict[str, str] = {}
    counts: dict[str, int] = {}
    for document in documents:
        base = _citation_key(document)
        count = counts.get(base, 0)
        counts[base] = count + 1
        keys[document.id] = base if count == 0 else f"{base}{count + 1}"
    return keys


def _citation_key(document: DocumentRecord) -> str:
    year = _publication_year(document) or "noyear"
    first_author = document.authors[0].split()[-1] if document.authors else "unknown"
    slug = re.sub(r"[^a-z0-9]+", "", f"{first_author}{year}".casefold())
    return slug or f"citation{document.id}"


def _document_url(document: DocumentRecord) -> str | None:
    parsed = urlparse(document.source_uri)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return document.source_uri
    return None


def _authors(document: DocumentRecord) -> str:
    return " and ".join(document.authors) if document.authors else "Unknown"


def _publication_year(document: DocumentRecord) -> str | None:
    return str(document.publication_date.year) if document.publication_date else None


def _bibtex_escape(value: str) -> str:
    return value.replace("\\", r"\textbackslash{}").replace("{", r"\{").replace("}", r"\}")


def _citation_metadata(document: DocumentRecord) -> _CitationMetadata:
    return {
        "abstract": _optional_text(getattr(document, "abstract", None)),
        "venue": _optional_text(getattr(document, "venue", None)),
        "source_uri": _optional_text(getattr(document, "source_uri", None)),
        "authors": tuple(str(author) for author in getattr(document, "authors", ()) or ()),
        "tags": tuple(str(tag) for tag in getattr(document, "tags", ()) or ()),
    }


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
