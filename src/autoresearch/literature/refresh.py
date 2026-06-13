"""Daily online literature refresh pipeline."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
)
from autoresearch.schemas import DocumentRecord

from .cache import RetrievalCache, retrieval_cache_key
from .clients import ArxivClient, OpenAlexClient, SemanticScholarClient, semantic_scholar_enabled
from .models import AcademicPaper, deduplicate_papers
from .storage import paper_to_document_record

DEFAULT_SOURCE_RATE_LIMITS = {
    "arxiv": 3.0,
    "openalex": 1.0,
    "semantic_scholar": 1.0,
}
GENERIC_TERMS = {
    "archived",
    "candidate",
    "completed",
    "draft",
    "evidence",
    "failure",
    "method",
    "paper",
    "pending",
    "ready_for_review",
    "research",
    "research-candidate",
    "review",
}
STOPWORDS = {
    "and",
    "for",
    "from",
    "into",
    "the",
    "using",
    "with",
}


class LiteratureSearchClient(Protocol):
    """Minimal client interface used by the refresh pipeline."""

    def search(self, query: str, *, limit: int = 10) -> list[AcademicPaper]:
        """Return papers for one query."""


@dataclass(frozen=True)
class LiteratureRefreshConfig:
    """Configuration for one daily refresh run."""

    max_queries: int = 5
    min_query_floor: int = 4
    max_results_per_source: int = 20
    cache_ttl_hours: int = 24
    seed_queries: tuple[str, ...] = ()


@dataclass(frozen=True)
class LiteratureQuery:
    """One optimized query derived from vault context."""

    text: str
    origin: str
    vault_paths: tuple[str, ...]


@dataclass(frozen=True)
class SourceFetchRecord:
    """Provenance for one source/query fetch."""

    source: str
    query: str
    cache_key: str
    cache_hit: bool
    paper_count: int
    rate_limit_seconds: float
    vault_paths: tuple[str, ...]
    error: str | None = None


@dataclass(frozen=True)
class LiteratureRefreshReport:
    """Result of one daily online literature refresh."""

    queries: tuple[LiteratureQuery, ...]
    fetches: tuple[SourceFetchRecord, ...]
    papers: tuple[AcademicPaper, ...]
    documents: tuple[DocumentRecord, ...]
    summary_path: Path | None


@dataclass(frozen=True)
class _VaultContext:
    entry: KnowledgeEntry | None
    relative_path: str
    title: str
    keywords: tuple[str, ...]
    body: str


def generate_literature_queries(
    vault_root: Path | str,
    *,
    config: LiteratureRefreshConfig = LiteratureRefreshConfig(),
) -> list[LiteratureQuery]:
    """Generate search queries from Obsidian topics, cards, and candidates."""

    contexts = _load_vault_context(Path(vault_root))
    seed_queries = _seed_queries(config.seed_queries)
    candidates = [*seed_queries, *(_query_from_context(context) for context in contexts)]
    queries = [query for query in candidates if query is not None]
    if not queries:
        queries = _default_queries()

    target_count = min(config.max_queries, max(config.min_query_floor, 0))
    deduplicated = _deduplicate_queries(queries)
    if len(deduplicated) < target_count:
        deduplicated = _deduplicate_queries(
            [
                *deduplicated,
                *_expansion_queries(contexts=contexts, seed_texts=config.seed_queries),
            ]
        )
    return deduplicated[: config.max_queries]


def run_daily_literature_refresh(
    *,
    vault_root: Path | str,
    cache_root: Path | str,
    clients: Mapping[str, LiteratureSearchClient] | None = None,
    now: datetime | None = None,
    config: LiteratureRefreshConfig = LiteratureRefreshConfig(),
    write_summary: bool = True,
) -> LiteratureRefreshReport:
    """Fetch, cache, deduplicate, normalize, and summarize daily literature."""

    timestamp = _normalize_datetime(now)
    source_clients = clients or _default_literature_clients()
    cache = RetrievalCache(cache_root, ttl_hours=config.cache_ttl_hours)
    queries = generate_literature_queries(vault_root, config=config)

    fetches: list[SourceFetchRecord] = []
    papers: list[AcademicPaper] = []
    for query in queries:
        for source, client in source_clients.items():
            cache_config = {
                "origin": query.origin,
                "refresh": "daily",
                "vault_paths": list(query.vault_paths),
            }
            cache_key = retrieval_cache_key(
                query=query.text,
                source=source,
                page=1,
                limit=config.max_results_per_source,
                config=cache_config,
            )
            cached = cache.get(cache_key, now=timestamp)
            cache_hit = cached is not None
            source_papers: list[AcademicPaper] = cached or []
            error: str | None = None
            if cached is None:
                try:
                    source_papers = client.search(query.text, limit=config.max_results_per_source)
                except Exception as exc:  # noqa: BLE001 - source failures must be preserved.
                    error = f"{type(exc).__name__}: {exc}"
                else:
                    cache.set(cache_key, source_papers, now=timestamp)

            papers.extend(source_papers)
            fetches.append(
                SourceFetchRecord(
                    source=source,
                    query=query.text,
                    cache_key=cache_key,
                    cache_hit=cache_hit,
                    paper_count=len(source_papers),
                    rate_limit_seconds=_rate_limit_seconds(source, client),
                    vault_paths=query.vault_paths,
                    error=error,
                )
            )

    unique_papers = deduplicate_papers(papers)
    documents = tuple(
        _document_for_refresh(paper, timestamp=timestamp, queries=queries)
        for paper in unique_papers
    )
    report = LiteratureRefreshReport(
        queries=tuple(queries),
        fetches=tuple(fetches),
        papers=tuple(unique_papers),
        documents=documents,
        summary_path=None,
    )
    if write_summary:
        report = LiteratureRefreshReport(
            queries=report.queries,
            fetches=report.fetches,
            papers=report.papers,
            documents=report.documents,
            summary_path=_write_refresh_summary(Path(vault_root), report, timestamp),
        )
    return report


def _seed_queries(seed_texts: tuple[str, ...]) -> list[LiteratureQuery]:
    queries: list[LiteratureQuery] = []
    for index, seed_text in enumerate(seed_texts, start=1):
        text = _clean_query_text(seed_text)
        if len(_significant_tokens(text)) < 2:
            continue
        queries.append(
            LiteratureQuery(
                text=text,
                origin=f"configured_seed_{index}",
                vault_paths=(),
            )
        )
    return queries


def _default_queries() -> list[LiteratureQuery]:
    defaults = (
        ("automated research agents evidence graph reproducibility", "default"),
        ("self evolving research agents validation gates", "default_self_loop"),
        ("research automation literature retrieval experiment validation", "default_validation"),
        ("knowledge base memory for autonomous scientific agents", "default_memory"),
    )
    return [
        LiteratureQuery(text=text, origin=origin, vault_paths=())
        for text, origin in defaults
    ]


def _default_literature_clients() -> dict[str, LiteratureSearchClient]:
    clients: dict[str, LiteratureSearchClient] = {
        "arxiv": ArxivClient(),
        "openalex": OpenAlexClient(),
    }
    if semantic_scholar_enabled():
        clients["semantic_scholar"] = SemanticScholarClient()
    return clients


def _expansion_queries(
    *,
    contexts: list[_VaultContext],
    seed_texts: tuple[str, ...],
) -> list[LiteratureQuery]:
    expansions: list[LiteratureQuery] = []
    for index, seed_text in enumerate(seed_texts, start=1):
        terms = _significant_tokens(seed_text)
        if len(terms) >= 3:
            core = " ".join(terms[:6])
            expansions.extend(
                [
                    LiteratureQuery(
                        text=_clean_query_text(f"{core} prior work"),
                        origin=f"configured_seed_{index}_prior_work",
                        vault_paths=(),
                    ),
                    LiteratureQuery(
                        text=_clean_query_text(f"{core} benchmark validation"),
                        origin=f"configured_seed_{index}_benchmark",
                        vault_paths=(),
                    ),
                ]
            )

    for context in contexts:
        context_terms = _query_terms(context)
        if len(context_terms) >= 3:
            paths = (context.relative_path,)
            core = " ".join(context_terms[:6])
            expansions.extend(
                [
                    LiteratureQuery(
                        text=_clean_query_text(f"{core} prior work"),
                        origin=f"{_context_priority(context) or 'context'}_prior_work",
                        vault_paths=paths,
                    ),
                    LiteratureQuery(
                        text=_clean_query_text(f"{core} reproducibility validation"),
                        origin=f"{_context_priority(context) or 'context'}_validation",
                        vault_paths=paths,
                    ),
                ]
            )

    expansions.extend(_default_queries())
    return [
        query
        for query in expansions
        if len(_significant_tokens(query.text)) >= 2
    ]


def _load_vault_context(vault_root: Path) -> list[_VaultContext]:
    contexts: list[_VaultContext] = []
    if not vault_root.exists():
        return contexts

    for path in sorted(vault_root.rglob("*.md")):
        relative = path.relative_to(vault_root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        text = path.read_text(encoding="utf-8")
        try:
            entry = KnowledgeEntry.from_markdown(text)
        except (ValueError, ValidationError):
            contexts.extend(_plain_markdown_contexts(relative.as_posix(), text))
            continue
        contexts.append(
            _VaultContext(
                entry=entry,
                relative_path=relative.as_posix(),
                title=entry.title,
                keywords=tuple(entry.keywords),
                body=entry.body,
            )
        )
    return contexts


def _plain_markdown_contexts(relative_path: str, text: str) -> list[_VaultContext]:
    contexts: list[_VaultContext] = []
    if relative_path != "exploration/index.md":
        return contexts
    for line in text.splitlines():
        if line.startswith("## "):
            keyword = line.removeprefix("## ").strip()
            if keyword:
                contexts.append(
                    _VaultContext(
                        entry=None,
                        relative_path=relative_path,
                        title=keyword,
                        keywords=(keyword,),
                        body="",
                    )
                )
    return contexts


def _query_from_context(context: _VaultContext) -> LiteratureQuery | None:
    priority = _context_priority(context)
    if priority is None:
        return None
    terms = _query_terms(context)
    if len(terms) < 2:
        return None
    return LiteratureQuery(
        text=" ".join(terms[:5]),
        origin=priority,
        vault_paths=(context.relative_path,),
    )


def _context_priority(context: _VaultContext) -> str | None:
    if context.entry is None:
        return "topic_index"
    if context.entry.entry_type == KnowledgeEntryType.RESEARCH_CANDIDATE:
        if {"rejected", "archived"} & {tag.casefold() for tag in context.entry.tags}:
            return None
        return "active_candidate_gap"
    if context.entry.entry_type == KnowledgeEntryType.METHOD_CARD:
        return "method_card"
    if context.entry.entry_type == KnowledgeEntryType.DATASET_CARD:
        return "dataset_card"
    if context.entry.entry_type == KnowledgeEntryType.FAILURE_CASE:
        return "failure_pattern"
    if context.entry.zone == KnowledgeZone.PROJECT and context.entry.entry_type in {
        KnowledgeEntryType.PROJECT_PROGRESS,
        KnowledgeEntryType.ISSUE_NOTE,
        KnowledgeEntryType.REVIEW_NOTE,
    }:
        return "project_experience"
    return None


def _query_terms(context: _VaultContext) -> tuple[str, ...]:
    values = [*context.keywords, context.title]
    if context.entry is not None and context.entry.entry_type == KnowledgeEntryType.RESEARCH_CANDIDATE:
        values.append(context.body)
    terms: list[str] = []
    for value in values:
        terms.extend(_clean_query_terms(value))
    return tuple(dict.fromkeys(terms))


def _clean_query_terms(value: str) -> list[str]:
    normalized = re.sub(r"[^a-zA-Z0-9 -]+", " ", value.casefold())
    parts = [" ".join(part.split()) for part in normalized.split(",")]
    terms: list[str] = []
    for part in parts:
        if not part:
            continue
        if part in GENERIC_TERMS or part in STOPWORDS:
            continue
        if " " in part:
            terms.append(part)
            continue
        words = [
            word
            for word in part.split()
            if len(word) > 2 and word not in GENERIC_TERMS and word not in STOPWORDS
        ]
        terms.extend(words)
    return terms


def _clean_query_text(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9 -]+", " ", value.casefold())
    return " ".join(normalized.split())


def _significant_tokens(value: str) -> list[str]:
    return [
        token
        for token in _clean_query_text(value).split()
        if len(token) > 2 and token not in GENERIC_TERMS and token not in STOPWORDS
    ]


def _deduplicate_queries(queries: list[LiteratureQuery]) -> list[LiteratureQuery]:
    unique: dict[str, LiteratureQuery] = {}
    for query in sorted(queries, key=lambda item: (_origin_rank(item.origin), item.text)):
        if query.text not in unique:
            unique[query.text] = query
        else:
            previous = unique[query.text]
            unique[query.text] = LiteratureQuery(
                text=previous.text,
                origin=previous.origin,
                vault_paths=tuple(dict.fromkeys([*previous.vault_paths, *query.vault_paths])),
            )
    return list(unique.values())


def _origin_rank(origin: str) -> int:
    configured_seed_match = re.match(r"configured_seed_(\d+)$", origin)
    if configured_seed_match is not None:
        return int(configured_seed_match.group(1)) - 1
    configured_seed_expansion_match = re.match(r"configured_seed_(\d+)_", origin)
    if configured_seed_expansion_match is not None:
        return 50 + int(configured_seed_expansion_match.group(1))
    order = {
        "active_candidate_gap": 100,
        "failure_pattern": 101,
        "project_experience": 102,
        "method_card": 103,
        "dataset_card": 104,
        "topic_index": 105,
        "default": 106,
        "default_self_loop": 107,
        "default_validation": 108,
        "default_memory": 109,
    }
    return order.get(origin, 999)


def _document_for_refresh(
    paper: AcademicPaper,
    *,
    timestamp: datetime,
    queries: list[LiteratureQuery],
) -> DocumentRecord:
    document = paper_to_document_record(paper, retrieved_at=timestamp)
    return document.model_copy(
        update={
            "metadata": {
                "refresh_queries": [query.text for query in queries],
                "refresh_timestamp": timestamp.isoformat(),
            }
        }
    )


def _write_refresh_summary(
    vault_root: Path,
    report: LiteratureRefreshReport,
    timestamp: datetime,
) -> Path:
    store = MarkdownKnowledgeStore(vault_root)
    entry_id = f"literature_refresh_{timestamp.strftime('%Y%m%d')}"
    entry = KnowledgeEntry(
        entry_id=entry_id,
        entry_type=KnowledgeEntryType.EVIDENCE_NOTE,
        zone=KnowledgeZone.EXPLORATION,
        title=f"Daily literature refresh {timestamp.date().isoformat()}",
        tags=["online-discovery", "literature-refresh"],
        keywords=["literature-refresh", "online-discovery"],
        source_refs=sorted({document.source_uri for document in report.documents}),
        body=_refresh_summary_body(report, timestamp),
    )
    relative_path = Path("exploration") / "topics" / f"{entry_id}.md"
    return store.write_entry(relative_path, entry)


def _refresh_summary_body(report: LiteratureRefreshReport, timestamp: datetime) -> str:
    lines = [
        f"# Daily literature refresh {timestamp.date().isoformat()}",
        "",
        "## Guardrails",
        "",
        "- This note records source metadata and retrieval provenance only.",
        "- Do not infer benchmark scores, paper acceptance, code availability, or experimental outcomes from missing metadata.",
        "- Missing evidence remains `unknown` or `pending verification`.",
        "",
        "## Queries",
        "",
    ]
    for query in report.queries:
        paths = ", ".join(query.vault_paths) if query.vault_paths else "none"
        lines.append(f"- `{query.text}` ({query.origin}; vault paths: {paths})")

    lines.extend(["", "## Fetches", ""])
    for fetch in report.fetches:
        cache_status = "hit" if fetch.cache_hit else "miss"
        error = f", error `{fetch.error}`" if fetch.error else ""
        lines.append(
            f"- `{fetch.source}` query `{fetch.query}`: {fetch.paper_count} papers, "
            f"cache {cache_status}, rate limit `{fetch.rate_limit_seconds}` seconds{error}."
        )

    lines.extend(["", "## Normalized Documents", ""])
    if not report.documents:
        lines.append("- None")
    for document in report.documents:
        lines.append(
            f"- `{document.id}` {document.title} "
            f"({document.source_uri}; source={','.join(document.tags) or 'unknown'})"
        )
    return "\n".join(lines).rstrip() + "\n"


def _rate_limit_seconds(source: str, client: LiteratureSearchClient) -> float:
    rate_limiter = getattr(client, "rate_limiter", None)
    interval = getattr(rate_limiter, "min_interval_seconds", None)
    if isinstance(interval, int | float):
        return float(interval)
    return DEFAULT_SOURCE_RATE_LIMITS.get(source, 1.0)


def _normalize_datetime(value: datetime | None) -> datetime:
    timestamp = value or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)
