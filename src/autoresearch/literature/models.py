"""Academic paper metadata and deduplication helpers."""

from __future__ import annotations

import re
from datetime import date
from difflib import SequenceMatcher
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PublicationStatus = Literal["unknown", "preprint", "published", "withdrawn", "retracted"]


class AcademicPaper(BaseModel):
    """Structured metadata for a retrieved academic paper."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    authors: list[str] = Field(default_factory=list)
    abstract: str | None = None
    publication_date: date | None = None
    venue: str | None = None
    doi: str | None = None
    repository_doi: str | None = None
    url: str | None = None
    citation_count: int | None = Field(default=None, ge=0)
    citation_count_source: str | None = None
    citation_count_as_of: date | None = None
    publication_status: PublicationStatus = "unknown"
    status_source: str | None = None
    status_as_of: date | None = None
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
    """Deduplicate papers without collapsing conflicting bibliographic identities.

    Publication DOIs and repository DOIs are separate identifier namespaces.  An
    exact match within either namespace is sufficient, while a conflict within a
    namespace is conclusive evidence that two records must remain distinct.  Title
    fallback is used only when there is no such conflict and at least one normalized
    author overlaps; this prevents same-title homonyms from mixing citation, status,
    or abstract metadata downstream.
    """

    unique: list[AcademicPaper] = []

    for paper in papers:
        if any(
            _same_bibliographic_work(
                paper,
                existing,
                title_similarity_threshold=title_similarity_threshold,
            )
            for existing in unique
        ):
            continue

        unique.append(paper)

    return unique


def _same_bibliographic_work(
    left: AcademicPaper,
    right: AcademicPaper,
    *,
    title_similarity_threshold: float,
) -> bool:
    if left == right:
        return True

    left_doi = normalize_doi(left.doi)
    right_doi = normalize_doi(right.doi)
    left_repository_doi = normalize_doi(left.repository_doi)
    right_repository_doi = normalize_doi(right.repository_doi)

    if left_doi and right_doi and left_doi != right_doi:
        return False
    if left_repository_doi and right_repository_doi and left_repository_doi != right_repository_doi:
        return False
    if (left_doi and right_repository_doi and left_doi == right_repository_doi) or (
        left_repository_doi and right_doi and left_repository_doi == right_doi
    ):
        return False
    if left_doi and right_doi and left_doi == right_doi:
        return True
    if left_repository_doi and right_repository_doi and left_repository_doi == right_repository_doi:
        return True

    if _title_similarity(left.title, right.title) < title_similarity_threshold:
        return False
    left_authors = {_normalize_author(author) for author in left.authors}
    right_authors = {_normalize_author(author) for author in right.authors}
    left_authors.discard("")
    right_authors.discard("")
    return bool(left_authors and right_authors and left_authors.intersection(right_authors))


def _normalize_author(value: str) -> str:
    normalized = "".join(
        character if character.isalnum() else " " for character in value.casefold()
    )
    return " ".join(normalized.split())
