"""Literature retrieval models and utilities."""

from .cache import RetrievalCache, RetrievalCacheRecord, retrieval_cache_key
from .clients import ArxivClient, RateLimiter, RetryConfig, SemanticScholarClient
from .models import AcademicPaper, deduplicate_papers, normalize_doi, normalize_title

__all__ = [
    "AcademicPaper",
    "ArxivClient",
    "RateLimiter",
    "RetrievalCache",
    "RetrievalCacheRecord",
    "RetryConfig",
    "SemanticScholarClient",
    "deduplicate_papers",
    "normalize_doi",
    "normalize_title",
    "retrieval_cache_key",
]
