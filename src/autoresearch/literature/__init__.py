"""Literature retrieval models and utilities."""

from .cache import RetrievalCache, RetrievalCacheRecord, retrieval_cache_key
from .clients import (
    OPTIONAL_LITERATURE_SOURCES,
    ArxivClient,
    CircuitBreakerOpenError,
    OpenAlexClient,
    RateLimitCircuitBreaker,
    RateLimiter,
    RetryConfig,
    SemanticScholarClient,
    SourceCircuitStateLockError,
    SourceRateLimitError,
    semantic_scholar_enabled,
)
from .models import AcademicPaper, deduplicate_papers, normalize_doi, normalize_title
from .refresh import (
    LiteratureQuery,
    LiteratureRefreshConfig,
    LiteratureRefreshReport,
    LiteratureSearchClient,
    SourceFetchRecord,
    generate_literature_queries,
    run_daily_literature_refresh,
)
from .storage import paper_to_document_record, paper_to_knowledge_entry, store_paper_notes

__all__ = [
    "AcademicPaper",
    "ArxivClient",
    "CircuitBreakerOpenError",
    "LiteratureQuery",
    "LiteratureRefreshConfig",
    "LiteratureRefreshReport",
    "LiteratureSearchClient",
    "OPTIONAL_LITERATURE_SOURCES",
    "OpenAlexClient",
    "RateLimitCircuitBreaker",
    "RateLimiter",
    "RetrievalCache",
    "RetrievalCacheRecord",
    "RetryConfig",
    "SemanticScholarClient",
    "SourceCircuitStateLockError",
    "SourceRateLimitError",
    "SourceFetchRecord",
    "deduplicate_papers",
    "generate_literature_queries",
    "normalize_doi",
    "normalize_title",
    "paper_to_document_record",
    "paper_to_knowledge_entry",
    "retrieval_cache_key",
    "run_daily_literature_refresh",
    "semantic_scholar_enabled",
    "store_paper_notes",
]
