from datetime import date

import pytest
from pydantic import ValidationError

from autoresearch.literature import AcademicPaper, normalize_doi, normalize_title


def test_academic_paper_model_accepts_required_metadata() -> None:
    paper = AcademicPaper(
        title="Evidence First Research",
        authors=["A. Researcher", "B. Reviewer"],
        abstract="A structured paper.",
        publication_date=date(2026, 6, 11),
        venue="AutoResearch Workshop",
        doi="10.1234/example",
        url="https://example.com/paper",
        citation_count=5,
        source="arxiv",
    )

    assert paper.title == "Evidence First Research"
    assert paper.citation_count == 5


def test_academic_paper_model_rejects_invalid_required_fields() -> None:
    with pytest.raises(ValidationError):
        AcademicPaper(title="", source="", citation_count=-1)


def test_paper_normalizers_are_stable() -> None:
    assert normalize_doi("DOI:10.1234/ABC") == "10.1234/abc"
    assert normalize_doi("https://doi.org/10.1234/ABC") == "10.1234/abc"
    assert normalize_title(" Evidence-First: Research! ") == "evidence first research"
