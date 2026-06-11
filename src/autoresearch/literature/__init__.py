"""Literature retrieval models and utilities."""

from .cache import RetrievalCache, RetrievalCacheRecord, retrieval_cache_key
from .clients import ArxivClient, RateLimiter, RetryConfig, SemanticScholarClient
from .models import AcademicPaper, deduplicate_papers, normalize_doi, normalize_title
from .storage import paper_to_document_record, paper_to_knowledge_entry, store_paper_notes

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
    "paper_to_document_record",
    "paper_to_knowledge_entry",
    "retrieval_cache_key",
    "store_paper_notes",
]
