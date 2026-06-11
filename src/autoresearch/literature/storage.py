"""Store retrieved literature metadata in the Obsidian knowledge base."""

from __future__ import annotations

import re
from datetime import datetime, time, timezone
from pathlib import Path

from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
)
from autoresearch.schemas import DocumentRecord

from .models import AcademicPaper


def paper_to_document_record(
    paper: AcademicPaper, *, retrieved_at: datetime | None = None
) -> DocumentRecord:
    publication_date = (
        datetime.combine(paper.publication_date, time.min, tzinfo=timezone.utc)
        if paper.publication_date is not None
        else None
    )
    source_uri = paper.url or (f"doi:{paper.doi}" if paper.doi is not None else paper.title)
    return DocumentRecord(
        title=paper.title,
        source_uri=source_uri,
        source_type="paper",
        authors=paper.authors,
        abstract=paper.abstract,
        publication_date=publication_date,
        venue=paper.venue,
        doi=paper.doi,
        tags=[paper.source],
        retrieved_at=retrieved_at or datetime.now(timezone.utc),
    )


def paper_to_knowledge_entry(
    paper: AcademicPaper,
    document: DocumentRecord,
    *,
    project_id: str | None = None,
) -> KnowledgeEntry:
    source_refs = [document.source_uri]
    if document.doi is not None:
        source_refs.append(f"doi:{document.doi}")

    return KnowledgeEntry(
        entry_id=document.id,
        entry_type=KnowledgeEntryType.PAPER_NOTE,
        zone=KnowledgeZone.PROJECT if project_id is not None else KnowledgeZone.EXPLORATION,
        title=document.title,
        project_id=project_id,
        tags=["paper", paper.source],
        keywords=[paper.source],
        source_refs=source_refs,
        body=_paper_note_body(paper, document),
    )


def store_paper_notes(
    store: MarkdownKnowledgeStore,
    papers: list[AcademicPaper],
    *,
    project_id: str | None = None,
    retrieved_at: datetime | None = None,
) -> list[DocumentRecord]:
    documents: list[DocumentRecord] = []
    for paper in papers:
        document = paper_to_document_record(paper, retrieved_at=retrieved_at)
        entry = paper_to_knowledge_entry(paper, document, project_id=project_id)
        store.write_entry(_paper_note_path(document, project_id=project_id), entry)
        documents.append(document)
    return documents


def _paper_note_path(document: DocumentRecord, *, project_id: str | None) -> Path:
    filename = f"{_slugify(document.title)}-{document.id}.md"
    if project_id is not None:
        return Path("projects") / project_id / "knowledge" / filename
    return Path("exploration") / "topics" / filename


def _paper_note_body(paper: AcademicPaper, document: DocumentRecord) -> str:
    authors = ", ".join(document.authors) if document.authors else "Unknown"
    lines = [
        f"# {document.title}",
        "",
        f"- Source: {paper.source}",
        f"- URL: {document.source_uri}",
        f"- DOI: {document.doi or 'N/A'}",
        f"- Venue: {document.venue or 'N/A'}",
        f"- Publication date: {document.publication_date.date().isoformat() if document.publication_date else 'N/A'}",
        f"- Retrieved at: {document.retrieved_at.isoformat()}",
        f"- Authors: {authors}",
        "",
        "## Abstract",
        "",
        document.abstract or "No abstract provided by source metadata.",
    ]
    return "\n".join(lines)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "paper"
