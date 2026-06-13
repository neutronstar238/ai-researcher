"""Online similarity and novelty cross-checks for project-start approval."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from pydantic import ValidationError

from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
)
from autoresearch.literature import (
    AcademicPaper,
    ArxivClient,
    LiteratureSearchClient,
    OpenAlexClient,
    RetrievalCache,
    SemanticScholarClient,
    deduplicate_papers,
    paper_to_document_record,
    retrieval_cache_key,
    semantic_scholar_enabled,
)
from autoresearch.schemas import DocumentRecord, ResearchCandidate

SIMILARITY_CLASSIFICATIONS = {
    "direct_duplicate",
    "adjacent_work",
    "supporting_prior_work",
    "contradictory_evidence",
    "benchmark_gap",
    "unknown",
}
NEGATIVE_TERMS = (
    "contradict",
    "fail",
    "negative result",
    "not improve",
    "does not",
    "limitation",
    "limited",
)
RISK_QUERY_PHRASES = (
    "mahalanobis",
    "metric learning",
    "distance metric",
    "gaussian",
    "nearest centroid",
    "prototype",
    "skin color",
    "skin colour",
    "skin detection",
    "skin segmentation",
    "bayesian",
    "illumination",
)
DEFAULT_SOURCE_RATE_LIMITS = {
    "arxiv": 3.0,
    "openalex": 1.0,
    "semantic_scholar": 1.0,
}
STOPWORDS = {
    "and",
    "for",
    "from",
    "into",
    "that",
    "the",
    "this",
    "using",
    "with",
}
BENCHMARK_TERMS = {
    "benchmark",
    "benchmarks",
    "dataset",
    "datasets",
    "recognition",
    "classification",
    "classifier",
    "classifiers",
}
METHOD_ANCHOR_TOKENS = {
    "classification",
    "classifier",
    "classifiers",
    "cluster",
    "clustering",
    "centroid",
    "centroids",
    "mahalanobis",
    "prototype",
    "prototypes",
}


@dataclass(frozen=True)
class _MethodFamily:
    name: str
    terms: tuple[str, ...]
    supporting_terms: tuple[str, ...] = ()
    min_document_terms: int = 1
    min_supporting_terms: int = 0


@dataclass(frozen=True)
class _MethodFamilyMatch:
    family: str
    document_terms: tuple[str, ...]
    context_terms: tuple[str, ...]
    supporting_terms: tuple[str, ...]


METHOD_FAMILIES = (
    _MethodFamily(
        name="prototype_classification",
        terms=(
            "prototype",
            "prototypes",
            "prototype classifier",
            "prototype classifiers",
            "prototype based",
            "nearest prototype",
            "centroid",
            "centroids",
            "nearest centroid",
            "nearest centroids",
        ),
        supporting_terms=(
            "classification",
            "classifier",
            "classifiers",
            "recognition",
            "learning",
            "few shot",
            "few-shot",
            "long tailed",
            "long-tailed",
        ),
        min_supporting_terms=1,
    ),
    _MethodFamily(
        name="mahalanobis_metric",
        terms=(
            "mahalanobis",
            "metric learning",
            "distance metric",
            "distance metrics",
            "large margin nearest neighbor",
            "nearest neighbor",
        ),
        supporting_terms=(
            "classification",
            "classifier",
            "classifiers",
            "learning",
            "verification",
            "estimation",
        ),
        min_supporting_terms=1,
    ),
    _MethodFamily(
        name="clustering_classifier",
        terms=("clustering", "cluster", "clusters", "k means", "k-means", "prototype based"),
        supporting_terms=("classification", "classifier", "classifiers"),
    ),
    _MethodFamily(
        name="skin_color_segmentation",
        terms=(
            "human skin detection",
            "skin detection",
            "skin segmentation",
            "skin image segmentation",
            "skin lesion segmentation",
            "skin color classifier",
            "skin colour classifier",
            "skin color model",
            "skin colour model",
            "rgb ratio",
            "hybrid color space",
            "hybrid colour space",
        ),
        supporting_terms=(
            "classification",
            "classifier",
            "classifiers",
            "color",
            "colour",
            "detection",
            "hsv",
            "rgb",
            "segmentation",
            "ycbcr",
        ),
        min_supporting_terms=1,
    ),
)


class UnsupportedSimilarityClaimError(ValueError):
    """Raised when a similarity finding contains unsupported claims."""


@dataclass(frozen=True)
class SimilarityCheckConfig:
    """Configuration for candidate similarity and novelty checks."""

    max_queries: int = 6
    min_query_floor: int = 4
    max_results_per_source: int = 10
    cache_ttl_hours: int = 24


@dataclass(frozen=True)
class SimilarityQuery:
    """One online search query for candidate cross-checking."""

    text: str
    origin: str
    vault_paths: tuple[str, ...]


@dataclass(frozen=True)
class SimilarityFetchRecord:
    """Provenance for one source/query request."""

    source: str
    query: str
    cache_key: str
    cache_hit: bool
    paper_count: int
    rate_limit_seconds: float
    vault_paths: tuple[str, ...]
    error: str | None = None


@dataclass(frozen=True)
class SimilarityFinding:
    """Source-backed classification for one retrieved document."""

    document_id: str
    title: str
    source_uri: str
    source_database: str
    query: str
    retrieved_at: datetime
    classification: str
    confidence: float
    evidence_refs: tuple[str, ...]
    classification_basis: tuple[str, ...]
    doi: str | None = None
    venue: str | None = None
    unsupported_claims: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectSimilarityReport:
    """Result of a project-start online similarity and novelty check."""

    candidate_id: str
    queries: tuple[SimilarityQuery, ...]
    fetches: tuple[SimilarityFetchRecord, ...]
    papers: tuple[AcademicPaper, ...]
    documents: tuple[DocumentRecord, ...]
    findings: tuple[SimilarityFinding, ...]
    summary_path: Path | None


def generate_similarity_queries(
    candidate: ResearchCandidate,
    *,
    vault_root: Path | str,
    config: SimilarityCheckConfig = SimilarityCheckConfig(),
) -> list[SimilarityQuery]:
    """Generate broad online search variants from a candidate and vault context."""

    candidate_paths = _candidate_vault_paths(candidate, Path(vault_root))
    raw_queries = [
        SimilarityQuery(_clean_query(candidate.title), "candidate_title", candidate_paths),
    ]
    raw_queries.extend(_structured_metadata_queries(candidate, candidate_paths))
    raw_queries.append(SimilarityQuery(_clean_query(candidate.research_gap), "research_gap", candidate_paths))

    metadata_query = _metadata_query(candidate, ("method", "dataset", "limitation"))
    if metadata_query:
        raw_queries.append(SimilarityQuery(metadata_query, "method_dataset_limitation", candidate_paths))

    baseline_query = _metadata_query(candidate, ("method", "dataset"))
    if baseline_query:
        raw_queries.append(
            SimilarityQuery(f"{baseline_query} baseline", "known_baseline_search", candidate_paths)
        )

    negative_query = _metadata_query(candidate, ("limitation", "dataset"))
    if negative_query:
        raw_queries.append(
            SimilarityQuery(
                f"{negative_query} negative results",
                "negative_result_search",
                candidate_paths,
            )
        )

    raw_queries.extend(_vault_context_queries(candidate, Path(vault_root)))
    queries = _deduplicate_queries(
        [query for query in raw_queries if len(_significant_tokens(query.text)) >= 2]
    )
    target_count = min(config.max_queries, max(config.min_query_floor, 0))
    if len(queries) < target_count:
        queries = _deduplicate_queries(
            [
                *queries,
                *_candidate_expansion_queries(candidate, candidate_paths),
            ]
        )
    return queries[: config.max_queries]


def run_project_similarity_check(
    *,
    candidate: ResearchCandidate,
    vault_root: Path | str,
    cache_root: Path | str,
    clients: Mapping[str, LiteratureSearchClient] | None = None,
    now: datetime | None = None,
    config: SimilarityCheckConfig = SimilarityCheckConfig(),
    write_summary: bool = True,
) -> ProjectSimilarityReport:
    """Run source-backed online similarity and novelty checking for one candidate."""

    timestamp = _normalize_datetime(now)
    source_clients = clients or _default_similarity_clients()
    cache = RetrievalCache(cache_root, ttl_hours=config.cache_ttl_hours)
    queries = generate_similarity_queries(candidate, vault_root=vault_root, config=config)

    fetches: list[SimilarityFetchRecord] = []
    papers: list[AcademicPaper] = []
    query_by_source_uri: dict[str, SimilarityQuery] = {}
    for query in queries:
        for source, client in source_clients.items():
            cache_config = {
                "candidate_id": candidate.id,
                "origin": query.origin,
                "similarity_check": "project_start",
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
                except Exception as exc:  # noqa: BLE001 - source failures must remain visible.
                    error = f"{type(exc).__name__}: {exc}"
                else:
                    cache.set(cache_key, source_papers, now=timestamp)

            for paper in source_papers:
                source_uri = paper.url or (f"doi:{paper.doi}" if paper.doi else paper.title)
                query_by_source_uri.setdefault(source_uri, query)
            papers.extend(source_papers)
            fetches.append(
                SimilarityFetchRecord(
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
        paper_to_document_record(paper, retrieved_at=timestamp)
        for paper in unique_papers
    )
    findings = tuple(
        _finding_for_document(
            candidate,
            document,
            query_by_source_uri.get(document.source_uri, queries[0] if queries else None),
            timestamp,
        )
        for document in documents
    )
    validate_similarity_findings(findings)

    report = ProjectSimilarityReport(
        candidate_id=candidate.id,
        queries=tuple(queries),
        fetches=tuple(fetches),
        papers=tuple(unique_papers),
        documents=documents,
        findings=findings,
        summary_path=None,
    )
    if write_summary:
        report = ProjectSimilarityReport(
            candidate_id=report.candidate_id,
            queries=report.queries,
            fetches=report.fetches,
            papers=report.papers,
            documents=report.documents,
            findings=report.findings,
            summary_path=_write_similarity_summary(Path(vault_root), candidate, report, timestamp),
        )
    return report


def _default_similarity_clients() -> dict[str, LiteratureSearchClient]:
    clients: dict[str, LiteratureSearchClient] = {
        "arxiv": ArxivClient(),
        "openalex": OpenAlexClient(),
    }
    if semantic_scholar_enabled():
        clients["semantic_scholar"] = SemanticScholarClient()
    return clients


def validate_similarity_findings(findings: tuple[SimilarityFinding, ...]) -> None:
    """Reject findings that include unsupported or provenance-free claims."""

    for finding in findings:
        if finding.unsupported_claims:
            msg = f"unsupported similarity claims: {', '.join(finding.unsupported_claims)}"
            raise UnsupportedSimilarityClaimError(msg)
        if finding.classification not in SIMILARITY_CLASSIFICATIONS:
            msg = f"unsupported similarity classification: {finding.classification}"
            raise UnsupportedSimilarityClaimError(msg)
        if not finding.source_uri or not finding.query or not finding.evidence_refs:
            msg = f"similarity finding for {finding.document_id} lacks source provenance"
            raise UnsupportedSimilarityClaimError(msg)
        if not finding.classification_basis:
            msg = f"similarity finding for {finding.document_id} lacks classification basis"
            raise UnsupportedSimilarityClaimError(msg)


def validate_similarity_report_for_candidate(
    candidate: ResearchCandidate,
    report: ProjectSimilarityReport | None,
) -> ProjectSimilarityReport:
    """Validate that a candidate has a usable online similarity report."""

    if report is None:
        msg = "project-start online similarity report is required before project creation"
        raise PermissionError(msg)
    if report.candidate_id != candidate.id:
        msg = "similarity report candidate_id does not match candidate"
        raise ValueError(msg)
    if report.summary_path is None or not report.summary_path.exists():
        msg = "similarity report summary_path must exist before project creation"
        raise PermissionError(msg)
    if not report.fetches:
        msg = "similarity report must record at least one online source fetch"
        raise PermissionError(msg)
    if not report.findings:
        msg = "similarity report must contain at least one source-backed finding"
        raise PermissionError(msg)
    validate_similarity_findings(report.findings)
    return report


def link_similarity_report_to_project(
    *,
    report: ProjectSimilarityReport,
    vault_root: Path | str,
    project_id: str,
) -> Path:
    """Write a project-zone Obsidian note linking the pre-approval similarity check."""

    validate_similarity_findings(report.findings)
    root = Path(vault_root)
    store = MarkdownKnowledgeStore(root)
    summary_target = _summary_link_target(root, report.summary_path)
    entry = KnowledgeEntry(
        entry_id=f"similarity_check_{report.candidate_id}_{project_id}",
        entry_type=KnowledgeEntryType.EVIDENCE_NOTE,
        zone=KnowledgeZone.PROJECT,
        project_id=project_id,
        title=f"Project-start similarity check for {report.candidate_id}",
        tags=["online-discovery", "similarity-check", "project-start"],
        keywords=["similarity-check", "novelty-check", report.candidate_id],
        source_refs=sorted({finding.source_uri for finding in report.findings}),
        body=_project_similarity_link_body(report, summary_target),
    )
    relative_path = (
        Path("projects")
        / project_id
        / "knowledge"
        / f"similarity_check_{report.candidate_id}.md"
    )
    return store.write_entry(relative_path, entry)


def _finding_for_document(
    candidate: ResearchCandidate,
    document: DocumentRecord,
    query: SimilarityQuery | None,
    timestamp: datetime,
) -> SimilarityFinding:
    classification, confidence, basis = _classify_document(candidate, document, query)
    return SimilarityFinding(
        document_id=document.id,
        title=document.title,
        source_uri=document.source_uri,
        source_database=document.tags[0] if document.tags else "unknown",
        query=query.text if query is not None else "unknown",
        retrieved_at=timestamp,
        classification=classification,
        confidence=confidence,
        evidence_refs=(document.id, document.source_uri),
        classification_basis=basis,
        doi=document.doi,
        venue=document.venue,
    )


def _classify_document(
    candidate: ResearchCandidate,
    document: DocumentRecord,
    query: SimilarityQuery | None,
) -> tuple[str, float, tuple[str, ...]]:
    candidate_title = _clean_query(candidate.title)
    document_title = _clean_query(document.title)
    document_text = _clean_query(f"{document.title} {document.abstract or ''} {document.venue or ''}")
    document_match_text = _match_text(document_text)
    title_similarity = SequenceMatcher(None, candidate_title, document_title).ratio()
    method = _metadata_text(candidate, "method")
    dataset = _metadata_text(candidate, "dataset")
    limitation = _metadata_text(candidate, "limitation")
    document_tokens = set(_significant_tokens(document_text))
    method_tokens = _metadata_tokens(candidate, "method")
    dataset_tokens = _metadata_tokens(candidate, "dataset")
    method_matches = _matched_tokens(method_tokens, document_tokens)
    dataset_matches = _matched_tokens(dataset_tokens, document_tokens)
    dataset_alias_matches = _dataset_alias_matches(candidate, document_match_text)
    family_matches = _method_family_matches(candidate, document_match_text, query)

    if title_similarity >= 0.78:
        return (
            "direct_duplicate",
            0.9,
            (f"title similarity {title_similarity:.2f} with candidate title",),
        )
    if method and dataset and method in document_text and dataset in document_text:
        return (
            "adjacent_work",
            0.75,
            (f"metadata contains method `{method}` and dataset `{dataset}`",),
        )
    if any(term in document_text for term in NEGATIVE_TERMS) and (
        limitation and limitation in document_text
    ):
        return (
            "contradictory_evidence",
            0.65,
            (f"metadata contains limitation `{limitation}` and negative-evidence terms",),
        )
    if _has_conservative_method_overlap(method_tokens, method_matches) and dataset_matches:
        token_basis = (
            f"method token overlap {', '.join(method_matches)} from `{method}`",
            f"dataset token overlap {', '.join(dataset_matches)} from `{dataset}`",
        )
        return (
            "adjacent_work",
            0.68,
            token_basis,
        )
    if family_matches and dataset_alias_matches:
        family_dataset_basis = (
            *_method_family_basis(family_matches, query),
            f"dataset alias overlap {', '.join(dataset_alias_matches)}",
        )
        return (
            "adjacent_work",
            0.72,
            family_dataset_basis,
        )
    if family_matches and query is not None and query.origin in {
        "baseline_dataset_search",
        "limitation_risk_search",
        "method_dataset_search",
    }:
        return (
            "adjacent_work",
            0.64,
            _method_family_basis(family_matches, query),
        )
    if dataset_alias_matches and _has_benchmark_language(document_tokens):
        return (
            "benchmark_gap",
            0.6,
            (f"dataset alias overlap {', '.join(dataset_alias_matches)} with benchmark language",),
        )
    if dataset and dataset in document_text and "benchmark" in document_text:
        return (
            "benchmark_gap",
            0.6,
            (f"metadata references dataset or benchmark `{dataset}`",),
        )
    if method and method in document_text:
        return (
            "supporting_prior_work",
            0.55,
            (f"metadata references method `{method}`",),
        )
    if _has_conservative_method_overlap(method_tokens, method_matches):
        return (
            "supporting_prior_work",
            0.5,
            (f"method token overlap {', '.join(method_matches)} from `{method}`",),
        )
    if family_matches:
        return (
            "supporting_prior_work",
            0.55,
            _method_family_basis(family_matches, query),
        )
    return (
        "unknown",
        0.25,
        ("source metadata did not support a stronger classification; pending verification",),
    )


def _metadata_tokens(candidate: ResearchCandidate, key: str) -> tuple[str, ...]:
    return tuple(_significant_tokens(_metadata_text(candidate, key)))


def _dataset_alias_matches(candidate: ResearchCandidate, document_text: str) -> tuple[str, ...]:
    aliases = _dataset_aliases(candidate)
    return _matched_terms(aliases, document_text)


def _dataset_aliases(candidate: ResearchCandidate) -> tuple[str, ...]:
    raw_parts = [
        candidate.title,
        _metadata_text(candidate, "dataset"),
        _metadata_text(candidate, "benchmark"),
    ]
    raw_text = _match_text(" ".join(part for part in raw_parts if part))
    aliases: list[str] = []
    for key in ("dataset", "benchmark"):
        value = _metadata_text(candidate, key)
        if value:
            aliases.append(value)
    if "pendigits" in raw_text or ("pen based" in raw_text and "digit" in raw_text):
        aliases.extend(
            [
                "pendigits",
                "uci pendigits",
                "pen based",
                "pen based recognition",
                "handwritten digit",
                "handwritten digits",
                "digit recognition",
            ]
        )
    if "skin segmentation" in raw_text or "skin non skin" in raw_text:
        aliases.extend(
            [
                "skin segmentation",
                "uci skin segmentation",
                "skin image segmentation",
                "skin non skin",
                "skin nonskin",
            ]
        )
    return tuple(dict.fromkeys(_match_text(alias) for alias in aliases if _match_text(alias)))


def _method_family_matches(
    candidate: ResearchCandidate,
    document_text: str,
    query: SimilarityQuery | None,
) -> tuple[_MethodFamilyMatch, ...]:
    context_text = _method_family_context(candidate, query)
    matches: list[_MethodFamilyMatch] = []
    for family in METHOD_FAMILIES:
        context_terms = _matched_terms(family.terms, context_text)
        if not context_terms:
            continue
        document_terms = _matched_terms(family.terms, document_text)
        supporting_terms = _matched_terms(family.supporting_terms, document_text)
        if len(document_terms) < family.min_document_terms:
            continue
        if len(supporting_terms) < family.min_supporting_terms:
            continue
        matches.append(
            _MethodFamilyMatch(
                family=family.name,
                document_terms=document_terms,
                context_terms=context_terms,
                supporting_terms=supporting_terms,
            )
        )
    return tuple(matches)


def _method_family_context(
    candidate: ResearchCandidate,
    query: SimilarityQuery | None,
) -> str:
    metadata = " ".join(value for value in candidate.metadata.values() if isinstance(value, str))
    query_text = query.text if query is not None else ""
    query_origin = query.origin if query is not None else ""
    return _match_text(
        " ".join(
            [
                candidate.title,
                candidate.description,
                candidate.research_gap,
                metadata,
                query_text,
                query_origin,
            ]
        )
    )


def _method_family_basis(
    matches: tuple[_MethodFamilyMatch, ...],
    query: SimilarityQuery | None,
) -> tuple[str, ...]:
    query_basis = (
        f"query `{query.text}` ({query.origin})"
        if query is not None
        else "candidate metadata without source query"
    )
    basis: list[str] = []
    for match in matches:
        support = (
            f"; supporting terms {', '.join(match.supporting_terms)}"
            if match.supporting_terms
            else ""
        )
        basis.append(
            "query family overlap "
            f"{match.family}: document terms {', '.join(match.document_terms)}; "
            f"candidate/query terms {', '.join(match.context_terms)}"
            f"{support}; source {query_basis}"
        )
    return tuple(basis)


def _matched_terms(needles: tuple[str, ...], haystack_text: str) -> tuple[str, ...]:
    if not needles:
        return ()
    haystack_tokens = set(haystack_text.split())
    matches: list[str] = []
    for raw_needle in needles:
        needle = _match_text(raw_needle)
        if not needle:
            continue
        if " " in needle:
            if needle in haystack_text:
                matches.append(needle)
            continue
        if needle in haystack_tokens:
            matches.append(needle)
    return tuple(dict.fromkeys(matches))


def _has_benchmark_language(document_tokens: set[str]) -> bool:
    return bool(document_tokens & BENCHMARK_TERMS)


def _matched_tokens(needles: tuple[str, ...], haystack: set[str]) -> tuple[str, ...]:
    return tuple(token for token in needles if token in haystack)


def _has_conservative_overlap(
    needles: tuple[str, ...],
    matches: tuple[str, ...],
) -> bool:
    if not needles:
        return False
    required = 1 if len(needles) <= 2 else max(2, (len(needles) + 1) // 2)
    return len(matches) >= required


def _has_conservative_method_overlap(
    method_tokens: tuple[str, ...],
    method_matches: tuple[str, ...],
) -> bool:
    if not _has_conservative_overlap(method_tokens, method_matches):
        return False
    candidate_anchors = set(method_tokens) & METHOD_ANCHOR_TOKENS
    if not candidate_anchors:
        return True
    return bool(set(method_matches) & candidate_anchors)


def _write_similarity_summary(
    vault_root: Path,
    candidate: ResearchCandidate,
    report: ProjectSimilarityReport,
    timestamp: datetime,
) -> Path:
    store = MarkdownKnowledgeStore(vault_root)
    entry_id = f"similarity_check_{candidate.id}"
    entry = KnowledgeEntry(
        entry_id=entry_id,
        entry_type=KnowledgeEntryType.EVIDENCE_NOTE,
        zone=KnowledgeZone.EXPLORATION,
        title=f"Project-start similarity check for {candidate.title}",
        tags=["online-discovery", "similarity-check", "novelty-check"],
        keywords=_summary_keywords(candidate),
        source_refs=sorted({finding.source_uri for finding in report.findings}),
        body=_similarity_summary_body(candidate, report, timestamp),
    )
    relative_path = Path("exploration") / "topics" / f"{entry_id}.md"
    return store.write_entry(relative_path, entry)


def _similarity_summary_body(
    candidate: ResearchCandidate,
    report: ProjectSimilarityReport,
    timestamp: datetime,
) -> str:
    lines = [
        f"# Project-start similarity check for {candidate.title}",
        "",
        f"- Candidate ID: `{candidate.id}`",
        f"- Retrieved at: `{timestamp.isoformat()}`",
        "",
        "## Guardrails",
        "",
        "- This note records source metadata, query provenance, and explicit classification basis only.",
        "- Do not invent paper results, benchmark scores, venue status, code availability, or experimental outcomes.",
        "- Missing evidence remains `unknown` or `pending verification`.",
        "",
        "## Queries",
        "",
    ]
    for query in report.queries:
        paths = ", ".join(query.vault_paths) if query.vault_paths else "candidate metadata"
        lines.append(f"- `{query.text}` ({query.origin}; vault paths: {paths})")

    lines.extend(["", "## Source Fetches", ""])
    for fetch in report.fetches:
        status = "hit" if fetch.cache_hit else "miss"
        error = f", error `{fetch.error}`" if fetch.error else ""
        lines.append(
            f"- `{fetch.source}` query `{fetch.query}`: {fetch.paper_count} papers, "
            f"cache {status}, rate limit `{fetch.rate_limit_seconds}` seconds{error}."
        )

    lines.extend(["", "## Findings", ""])
    if not report.findings:
        lines.append("- None; online evidence remains `pending verification`.")
    for finding in report.findings:
        basis = "; ".join(finding.classification_basis)
        lines.extend(
            [
                f"### {finding.title}",
                "",
                f"- Classification: `{finding.classification}`",
                f"- Confidence: `{finding.confidence}`",
                f"- Source database: `{finding.source_database}`",
                f"- Source URL/DOI: `{finding.source_uri}` / `{finding.doi or 'unknown'}`",
                f"- Venue status: `{finding.venue or 'unknown'}`",
                f"- Query text: `{finding.query}`",
                f"- Retrieval timestamp: `{finding.retrieved_at.isoformat()}`",
                f"- Evidence refs: {', '.join(f'`{ref}`' for ref in finding.evidence_refs)}",
                f"- Classification basis: {basis}",
                "- Code availability: `unknown`",
                "- Experimental outcomes: `pending verification`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _project_similarity_link_body(report: ProjectSimilarityReport, summary_target: str) -> str:
    counts: dict[str, int] = {}
    for finding in report.findings:
        counts[finding.classification] = counts.get(finding.classification, 0) + 1
    lines = [
        f"# Project-start similarity check for {report.candidate_id}",
        "",
        f"- Exploration summary: [[{summary_target}]]",
        f"- Candidate ID: `{report.candidate_id}`",
        f"- Online findings: `{len(report.findings)}`",
        "",
        "## Classification Counts",
        "",
    ]
    for classification in sorted(counts):
        lines.append(f"- `{classification}`: {counts[classification]}")
    lines.extend(
        [
            "",
            "## Approval Guardrail",
            "",
            "- This project was created only after a source-backed online similarity check existed.",
            "- Missing benchmark results, code availability, and experimental outcomes remain `pending verification`.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _vault_context_queries(
    candidate: ResearchCandidate,
    vault_root: Path,
) -> list[SimilarityQuery]:
    if not vault_root.exists():
        return []
    candidate_terms = set(_significant_tokens(_candidate_search_text(candidate)))
    queries: list[SimilarityQuery] = []
    for path in sorted(vault_root.rglob("*.md")):
        relative = path.relative_to(vault_root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        text = path.read_text(encoding="utf-8")
        try:
            entry = KnowledgeEntry.from_markdown(text)
        except (ValueError, ValidationError):
            query = _plain_topic_query(candidate_terms, relative.as_posix(), text)
            if query is not None:
                queries.append(query)
            continue
        if entry.entry_type not in {
            KnowledgeEntryType.DATASET_CARD,
            KnowledgeEntryType.FAILURE_CASE,
            KnowledgeEntryType.METHOD_CARD,
            KnowledgeEntryType.SKILL_CARD,
            KnowledgeEntryType.STRATEGY_CARD,
        }:
            continue
        entry_terms = set(_significant_tokens(_entry_search_text(entry)))
        if candidate_terms & entry_terms:
            text_query = _clean_query(" ".join([entry.title, *entry.keywords, candidate.title]))
            queries.append(
                SimilarityQuery(
                    text=text_query,
                    origin=f"vault_{entry.entry_type.value}",
                    vault_paths=(relative.as_posix(),),
                )
            )
    return queries


def _candidate_expansion_queries(
    candidate: ResearchCandidate,
    candidate_paths: tuple[str, ...],
) -> list[SimilarityQuery]:
    queries: list[SimilarityQuery] = []
    if candidate.description:
        queries.append(
            SimilarityQuery(
                _clean_query(candidate.description),
                "candidate_description",
                candidate_paths,
            )
        )
    for key in ("seed_document_title", "seed_title", "topic", "benchmark", "dataset"):
        value = candidate.metadata.get(key)
        if isinstance(value, str):
            queries.append(
                SimilarityQuery(
                    _clean_query(value),
                    f"metadata_{key}",
                    candidate_paths,
                )
            )

    core_terms = _significant_tokens(_candidate_search_text(candidate))[:8]
    if len(core_terms) >= 3:
        queries.append(
            SimilarityQuery(
                _clean_query(" ".join([*core_terms[:6], "prior work"])),
                "core_prior_work",
                candidate_paths,
            )
        )
        queries.append(
            SimilarityQuery(
                _clean_query(" ".join([*core_terms[:6], "benchmark validation"])),
                "core_benchmark_validation",
                candidate_paths,
            )
        )
    return [query for query in queries if len(_significant_tokens(query.text)) >= 2]


def _structured_metadata_queries(
    candidate: ResearchCandidate,
    candidate_paths: tuple[str, ...],
) -> list[SimilarityQuery]:
    queries: list[SimilarityQuery] = []
    dataset = _preferred_dataset_text(candidate)
    method_query = _compact_metadata_query(
        (_metadata_text(candidate, "method"), dataset),
        max_tokens=10,
    )
    if method_query:
        queries.append(SimilarityQuery(method_query, "method_dataset_search", candidate_paths))

    baseline_query = _compact_metadata_query(
        (_metadata_text(candidate, "baseline"), dataset),
        max_tokens=10,
    )
    if baseline_query:
        queries.append(SimilarityQuery(baseline_query, "baseline_dataset_search", candidate_paths))

    risk_query = _limitation_risk_query(candidate, dataset)
    if risk_query:
        queries.append(SimilarityQuery(risk_query, "limitation_risk_search", candidate_paths))
    return queries


def _preferred_dataset_text(candidate: ResearchCandidate) -> str:
    return _metadata_text(candidate, "benchmark") or _metadata_text(candidate, "dataset")


def _limitation_risk_query(candidate: ResearchCandidate, dataset: str) -> str:
    limitation = _metadata_text(candidate, "limitation")
    if not limitation:
        return ""
    limitation_match_text = limitation.replace("-", " ")
    risk_tokens: list[str] = []
    for phrase in RISK_QUERY_PHRASES:
        if _clean_query(phrase) in limitation_match_text:
            risk_tokens.extend(_significant_tokens(phrase))
    if not risk_tokens:
        return ""
    context_terms = [
        token
        for token in _significant_tokens(" ".join([candidate.title, _metadata_text(candidate, "method")]))
        if token.startswith("classif") or token.startswith("prototype")
    ]
    return _compact_tokens(
        [*risk_tokens, *context_terms[:2], *_significant_tokens(dataset)[:4]],
        max_tokens=10,
    )


def _compact_metadata_query(parts: tuple[str, ...], *, max_tokens: int) -> str:
    tokens: list[str] = []
    for part in parts:
        tokens.extend(_significant_tokens(part))
    return _compact_tokens(tokens, max_tokens=max_tokens)


def _compact_tokens(tokens: list[str], *, max_tokens: int) -> str:
    unique = list(dict.fromkeys(tokens))
    return _clean_query(" ".join(unique[:max_tokens]))


def _plain_topic_query(
    candidate_terms: set[str],
    relative_path: str,
    text: str,
) -> SimilarityQuery | None:
    if relative_path != "exploration/index.md":
        return None
    for line in text.splitlines():
        if not line.startswith("## "):
            continue
        title = line.removeprefix("## ").strip()
        if _is_low_value_topic_title(title):
            continue
        title_terms = set(_significant_tokens(title))
        if candidate_terms & title_terms:
            return SimilarityQuery(
                text=_clean_query(title),
                origin="vault_topic_index",
                vault_paths=(relative_path,),
            )
    return None


def _is_low_value_topic_title(title: str) -> bool:
    tokens = _clean_query(title).split()
    numeric_like = sum(
        1
        for token in tokens
        if token.isdigit() or re.fullmatch(r"[0-9a-f]{8,}", token) is not None
    )
    operational_tokens = {"autopilot", "ci", "cycle", "dry", "live", "manual", "sha", "task"}
    return numeric_like >= 2 and bool(operational_tokens & set(tokens))


def _candidate_vault_paths(candidate: ResearchCandidate, vault_root: Path) -> tuple[str, ...]:
    if not vault_root.exists():
        return ()
    paths: list[str] = []
    for path in sorted(vault_root.rglob("*.md")):
        relative = path.relative_to(vault_root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        try:
            entry = KnowledgeEntry.from_markdown(path.read_text(encoding="utf-8"))
        except (ValueError, ValidationError):
            continue
        if entry.entry_id == candidate.id:
            paths.append(relative.as_posix())
    return tuple(paths)


def _deduplicate_queries(queries: list[SimilarityQuery]) -> list[SimilarityQuery]:
    unique: dict[str, SimilarityQuery] = {}
    for query in queries:
        if not query.text:
            continue
        if query.text not in unique:
            unique[query.text] = query
            continue
        previous = unique[query.text]
        unique[query.text] = SimilarityQuery(
            text=previous.text,
            origin=previous.origin,
            vault_paths=tuple(dict.fromkeys([*previous.vault_paths, *query.vault_paths])),
        )
    return list(unique.values())


def _metadata_query(candidate: ResearchCandidate, keys: tuple[str, ...]) -> str:
    parts = [_metadata_text(candidate, key) for key in keys]
    return _clean_query(" ".join(part for part in parts if part))


def _metadata_text(candidate: ResearchCandidate, key: str) -> str:
    value = candidate.metadata.get(key)
    if isinstance(value, str):
        return _clean_query(value)
    return ""


def _candidate_search_text(candidate: ResearchCandidate) -> str:
    metadata = " ".join(value for value in candidate.metadata.values() if isinstance(value, str))
    return _clean_query(" ".join([candidate.title, candidate.research_gap, candidate.description, metadata]))


def _entry_search_text(entry: KnowledgeEntry) -> str:
    return _clean_query(" ".join([entry.title, *entry.tags, *entry.keywords, entry.body]))


def _summary_keywords(candidate: ResearchCandidate) -> list[str]:
    keywords = {"similarity-check", "novelty-check", candidate.id}
    keywords.update(_significant_tokens(_candidate_search_text(candidate))[:8])
    return sorted(keywords)


def _clean_query(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9 -]+", " ", value.casefold())
    return " ".join(normalized.split())


def _match_text(value: str) -> str:
    return _clean_query(value).replace("-", " ")


def _significant_tokens(value: str) -> list[str]:
    tokens = [
        token
        for token in _clean_query(value).split()
        if len(token) > 2 and token not in STOPWORDS
    ]
    return list(dict.fromkeys(tokens))


def _summary_link_target(vault_root: Path, summary_path: Path | None) -> str:
    if summary_path is None:
        return "pending verification"
    try:
        return summary_path.relative_to(vault_root).with_suffix("").as_posix()
    except ValueError:
        return summary_path.with_suffix("").as_posix()


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
