from datetime import date

import pytest
from pydantic import ValidationError

from autoresearch.literature import (
    AcademicPaper,
    deduplicate_papers,
    normalize_doi,
    normalize_title,
)


def test_academic_paper_model_accepts_required_metadata() -> None:
    paper = AcademicPaper(
        title="Evidence First Research",
        authors=["A. Researcher", "B. Reviewer"],
        abstract="A structured paper.",
        publication_date=date(2026, 6, 11),
        venue="AutoResearch Workshop",
        doi="10.1234/example",
        repository_doi="10.48550/arXiv.2606.00001",
        url="https://example.com/paper",
        citation_count=5,
        citation_count_source="openalex",
        citation_count_as_of=date(2026, 6, 11),
        publication_status="published",
        status_source="openalex",
        status_as_of=date(2026, 6, 11),
        source="arxiv",
    )

    assert paper.title == "Evidence First Research"
    assert paper.citation_count == 5
    assert paper.citation_count_source == "openalex"
    assert paper.publication_status == "published"


def test_academic_paper_defaults_unreported_citation_metadata_to_unknown() -> None:
    paper = AcademicPaper.model_validate({"title": "Legacy paper", "source": "arxiv"})

    assert paper.citation_count is None
    assert paper.citation_count_source is None
    assert paper.citation_count_as_of is None
    assert paper.repository_doi is None
    assert paper.publication_status == "unknown"
    assert paper.status_source is None
    assert paper.status_as_of is None


def test_academic_paper_model_rejects_invalid_required_fields() -> None:
    with pytest.raises(ValidationError):
        AcademicPaper(title="", source="", citation_count=-1)


def test_paper_normalizers_are_stable() -> None:
    assert normalize_doi("DOI:10.1234/ABC") == "10.1234/abc"
    assert normalize_doi("https://doi.org/10.1234/ABC") == "10.1234/abc"
    assert normalize_title(" Evidence-First: Research! ") == "evidence first research"


def _identity_paper(
    *,
    title: str = "A shared study title",
    authors: list[str] | None = None,
    doi: str | None = None,
    repository_doi: str | None = None,
) -> AcademicPaper:
    return AcademicPaper(
        title=title,
        authors=authors if authors is not None else ["A. Researcher"],
        doi=doi,
        repository_doi=repository_doi,
        url="https://example.org/work",
        source="test",
    )


def test_deduplication_keeps_same_title_records_with_conflicting_publication_dois() -> None:
    first = _identity_paper(doi="10.1000/work-a")
    second = _identity_paper(doi="10.1000/work-b")

    assert deduplicate_papers([first, second]) == [first, second]


def test_deduplication_keeps_same_title_records_with_conflicting_repository_dois() -> None:
    first = _identity_paper(repository_doi="10.48550/arxiv.2401.00001")
    second = _identity_paper(repository_doi="10.48550/arxiv.2401.00002")

    assert deduplicate_papers([first, second]) == [first, second]


def test_deduplication_matches_repository_doi_only_within_repository_namespace() -> None:
    repository_copy = _identity_paper(
        title="Repository version title",
        repository_doi="10.48550/arxiv.2401.00001",
    )
    same_repository_work = _identity_paper(
        title="Substantially renamed repository version",
        authors=["Different Metadata Author"],
        repository_doi="DOI:10.48550/ARXIV.2401.00001",
    )
    publication_namespace_record = _identity_paper(
        title="Repository version title",
        doi="10.48550/arxiv.2401.00001",
    )

    assert deduplicate_papers(
        [repository_copy, same_repository_work, publication_namespace_record]
    ) == [repository_copy, publication_namespace_record]


def test_title_fallback_requires_author_overlap_when_identifiers_are_missing() -> None:
    first = _identity_paper(authors=["A. Researcher", "B. Scholar"])
    punctuation_variant = _identity_paper(
        title="A shared study title!",
        authors=["A Researcher"],
    )
    same_title_homonym = _identity_paper(authors=["Unrelated Author"])
    authorless_homonym = _identity_paper(authors=[])

    assert deduplicate_papers(
        [first, punctuation_variant, same_title_homonym, authorless_homonym]
    ) == [first, same_title_homonym, authorless_homonym]


def test_deduplication_is_reflexive_for_an_exact_metadata_poor_record() -> None:
    canonical = _identity_paper(authors=[], doi=None, repository_doi=None)
    exact_copy = canonical.model_copy(deep=True)
    distinct_authorless_work = canonical.model_copy(
        update={
            "source": "another-index",
            "url": "https://example.org/a-different-work",
        }
    )

    assert deduplicate_papers([canonical, exact_copy, distinct_authorless_work]) == [
        canonical,
        distinct_authorless_work,
    ]
