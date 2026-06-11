"""Literature retrieval models and utilities."""

from .models import AcademicPaper, deduplicate_papers, normalize_doi, normalize_title

__all__ = [
    "AcademicPaper",
    "deduplicate_papers",
    "normalize_doi",
    "normalize_title",
]
