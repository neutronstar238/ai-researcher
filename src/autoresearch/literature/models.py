"""Academic paper metadata and deduplication helpers."""

from __future__ import annotations

import re
from datetime import date
from difflib import SequenceMatcher

from pydantic import BaseModel, ConfigDict, Field


class AcademicPaper(BaseModel):
    """Structured metadata for a retrieved academic paper."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    authors: list[str] = Field(default_factory=list)
    abstract: str | None = None
    publication_date: date | None = None
    venue: str | None = None
    doi: str | None = None
    url: str | None = None
    citation_count: int = Field(default=0, ge=0)
    source: str = Field(min_length=1)


def normalize_doi(doi: str | None) -> str | None:
    if doi is None:
        return None

    normalized = doi.strip().lower()
    normalized = normalized.removeprefix("https://doi.org/")
    normalized = normalized.removeprefix("http://doi.org/")
    normalized = normalized.removeprefix("doi:")
    return normalized or None


def normalize_title(title: str) -> str:
    normalized = title.casefold()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _title_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, normalize_title(left), normalize_title(right)).ratio()


def deduplicate_papers(
    papers: list[AcademicPaper], *, title_similarity_threshold: float = 0.92
) -> list[AcademicPaper]:
    """Deduplicate papers by DOI first, then high-similarity title."""

    unique: list[AcademicPaper] = []
    seen_dois: set[str] = set()

    for paper in papers:
        doi = normalize_doi(paper.doi)
        if doi is not None:
            if doi in seen_dois:
                continue
            seen_dois.add(doi)

        if any(
            _title_similarity(paper.title, existing.title) >= title_similarity_threshold
            for existing in unique
        ):
            continue

        unique.append(paper)

    return unique
