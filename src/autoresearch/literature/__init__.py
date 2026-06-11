"""Literature retrieval models and utilities."""

from .clients import ArxivClient, RateLimiter, RetryConfig, SemanticScholarClient
from .models import AcademicPaper, deduplicate_papers, normalize_doi, normalize_title

__all__ = [
    "AcademicPaper",
    "ArxivClient",
    "RateLimiter",
    "RetryConfig",
    "SemanticScholarClient",
    "deduplicate_papers",
    "normalize_doi",
    "normalize_title",
]
