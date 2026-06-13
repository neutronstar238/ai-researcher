"""Publication-level quality audit for autonomous research cycles."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
)
from autoresearch.literature import OPTIONAL_LITERATURE_SOURCES
from autoresearch.schemas import file_hash


class PublicationAuditVerdict(str, Enum):
    """Conservative publication-readiness states."""

    PASS = "pass"
    NEEDS_REVISION = "needs_revision"
    FAIL = "fail"


class PublicationAuditCheckStatus(str, Enum):
    """One audit check state."""

    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"


@dataclass(frozen=True)
class PublicationQualityTarget:
    """Minimum bar for a publication-readiness audit."""

    name: str
    display_name: str
    min_score: float
    min_literature_queries: int
    min_literature_documents: int
    min_successful_sources: int
    min_similarity_queries: int
    min_similarity_findings: int
    min_test_rows: int
    require_real_dataset: bool
    require_baseline: bool
    require_ablation: bool
    require_statistical_sanity: bool
    require_novel_contribution: bool
    min_llm_review_quality: float
    min_method_effect_standard_errors: float
    min_verified_citations: int
    min_relevant_verified_citations: int
    min_direct_verified_citations: int
    min_related_work_inspections: int
    min_related_work_abstract_evidence: int
    min_related_work_direct_method_candidates: int
    max_blocked_citations: int


@dataclass(frozen=True)
class PublicationAuditCheck:
    """One evidence-backed quality check."""

    check_id: str
    status: PublicationAuditCheckStatus
    severity: str
    message: str
    evidence_refs: tuple[str, ...] = ()
    next_action: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "status": self.status.value,
            "severity": self.severity,
            "message": self.message,
            "evidence_refs": list(self.evidence_refs),
            "next_action": self.next_action,
        }


@dataclass(frozen=True)
class PublicationAuditReport:
    """Publication-readiness audit output."""

    target: PublicationQualityTarget
    verdict: PublicationAuditVerdict
    score: float
    checks: tuple[PublicationAuditCheck, ...]
    cycle_summary_path: str
    review_path: str | None
    output_path: str
    markdown_path: str
    vault_review_path: str | None = None
    vault_issue_path: str | None = None

    @property
    def publishable(self) -> bool:
        return self.verdict is PublicationAuditVerdict.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": {
                "name": self.target.name,
                "display_name": self.target.display_name,
                "min_score": self.target.min_score,
                "min_literature_queries": self.target.min_literature_queries,
                "min_literature_documents": self.target.min_literature_documents,
                "min_successful_sources": self.target.min_successful_sources,
                "min_similarity_queries": self.target.min_similarity_queries,
                "min_similarity_findings": self.target.min_similarity_findings,
                "min_test_rows": self.target.min_test_rows,
                "require_real_dataset": self.target.require_real_dataset,
                "require_baseline": self.target.require_baseline,
                "require_ablation": self.target.require_ablation,
                "require_statistical_sanity": self.target.require_statistical_sanity,
                "require_novel_contribution": self.target.require_novel_contribution,
                "min_llm_review_quality": self.target.min_llm_review_quality,
                "min_method_effect_standard_errors": self.target.min_method_effect_standard_errors,
                "min_verified_citations": self.target.min_verified_citations,
                "min_relevant_verified_citations": self.target.min_relevant_verified_citations,
                "min_direct_verified_citations": self.target.min_direct_verified_citations,
                "min_related_work_inspections": self.target.min_related_work_inspections,
                "min_related_work_abstract_evidence": (
                    self.target.min_related_work_abstract_evidence
                ),
                "min_related_work_direct_method_candidates": (
                    self.target.min_related_work_direct_method_candidates
                ),
                "max_blocked_citations": self.target.max_blocked_citations,
            },
            "verdict": self.verdict.value,
            "publishable": self.publishable,
            "score": self.score,
            "checks": [check.to_dict() for check in self.checks],
            "cycle_summary_path": self.cycle_summary_path,
            "review_path": self.review_path,
            "output_path": self.output_path,
            "markdown_path": self.markdown_path,
            "vault_review_path": self.vault_review_path,
            "vault_issue_path": self.vault_issue_path,
        }


TARGETS: dict[str, PublicationQualityTarget] = {
    "ccf-b": PublicationQualityTarget(
        name="ccf-b",
        display_name="CCF-B-level conference target",
        min_score=0.82,
        min_literature_queries=4,
        min_literature_documents=20,
        min_successful_sources=2,
        min_similarity_queries=4,
        min_similarity_findings=10,
        min_test_rows=1000,
        require_real_dataset=True,
        require_baseline=True,
        require_ablation=True,
        require_statistical_sanity=True,
        require_novel_contribution=True,
        min_llm_review_quality=0.85,
        min_method_effect_standard_errors=2.0,
        min_verified_citations=8,
        min_relevant_verified_citations=6,
        min_direct_verified_citations=4,
        min_related_work_inspections=8,
        min_related_work_abstract_evidence=6,
        min_related_work_direct_method_candidates=4,
        max_blocked_citations=0,
    ),
    "q3-journal": PublicationQualityTarget(
        name="q3-journal",
        display_name="Q3 journal target",
        min_score=0.78,
        min_literature_queries=4,
        min_literature_documents=20,
        min_successful_sources=2,
        min_similarity_queries=4,
        min_similarity_findings=10,
        min_test_rows=1000,
        require_real_dataset=True,
        require_baseline=True,
        require_ablation=True,
        require_statistical_sanity=True,
        require_novel_contribution=True,
        min_llm_review_quality=0.85,
        min_method_effect_standard_errors=2.0,
        min_verified_citations=10,
        min_relevant_verified_citations=8,
        min_direct_verified_citations=5,
        min_related_work_inspections=10,
        min_related_work_abstract_evidence=8,
        min_related_work_direct_method_candidates=5,
        max_blocked_citations=0,
    ),
    "mvp-demo": PublicationQualityTarget(
        name="mvp-demo",
        display_name="MVP loop correctness target",
        min_score=0.70,
        min_literature_queries=1,
        min_literature_documents=1,
        min_successful_sources=1,
        min_similarity_queries=1,
        min_similarity_findings=1,
        min_test_rows=1,
        require_real_dataset=False,
        require_baseline=False,
        require_ablation=False,
        require_statistical_sanity=False,
        require_novel_contribution=False,
        min_llm_review_quality=0.85,
        min_method_effect_standard_errors=0.0,
        min_verified_citations=0,
        min_relevant_verified_citations=0,
        min_direct_verified_citations=0,
        min_related_work_inspections=0,
        min_related_work_abstract_evidence=0,
        min_related_work_direct_method_candidates=0,
        max_blocked_citations=999,
    ),
}

REQUIRED_PAPER_SECTIONS = (
    "abstract",
    "introduction",
    "related work",
    "method",
    "experiments",
    "results",
    "limitations",
    "conclusion",
    "references",
)

CITATION_RELEVANCE_STOPWORDS = frozenset(
    {
        "about",
        "across",
        "agent",
        "agents",
        "analysis",
        "approach",
        "based",
        "benchmark",
        "benchmarks",
        "character",
        "characters",
        "citation",
        "citations",
        "class",
        "classes",
        "classification",
        "classifications",
        "classifier",
        "classifiers",
        "claim",
        "claims",
        "cycle",
        "cycles",
        "data",
        "dataset",
        "datasets",
        "demo",
        "evidence",
        "experiment",
        "experiments",
        "for",
        "from",
        "generated",
        "generating",
        "generation",
        "feature",
        "features",
        "image",
        "images",
        "improve",
        "improves",
        "improving",
        "learning",
        "method",
        "methods",
        "model",
        "models",
        "over",
        "paper",
        "public",
        "recognition",
        "research",
        "result",
        "results",
        "source",
        "sources",
        "study",
        "system",
        "systems",
        "task",
        "tasks",
        "the",
        "using",
        "with",
    }
)

CITATION_DIRECT_METHOD_TOKENS = frozenset(
    {
        "calibrated",
        "calibration",
        "centroid",
        "diagonal",
        "gaussian",
        "heteroscedastic",
        "mahalanobi",
        "mahalanobis",
        "nearest",
        "prototype",
        "shrinkage",
        "variance",
        "zscore",
    }
)

CITATION_DIRECT_SUPPORT_TOKENS = frozenset(
    {
        "classifier",
        "classification",
        "distance",
        "metric",
        "recognition",
    }
)


def audit_publication_quality(
    *,
    cycle_summary_path: Path | str,
    target: str = "ccf-b",
    review_path: Path | str | None = None,
    output_dir: Path | str | None = None,
    vault_root: Path | str | None = None,
    project_id: str | None = None,
) -> PublicationAuditReport:
    """Audit whether one autonomous cycle is ready to claim publication-level output."""

    summary_path = Path(cycle_summary_path)
    summary = _read_json(summary_path)
    target_config = _target(target)
    resolved_output_dir = Path(output_dir) if output_dir is not None else summary_path.parent
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    checks = (
        *_literature_checks(summary, target_config),
        *_citation_checks(summary, summary_path.parent, target_config),
        *_related_work_inspection_checks(summary, summary_path.parent, target_config),
        *_similarity_checks(summary, summary_path.parent, target_config),
        *_script_and_data_checks(summary, summary_path.parent, target_config),
        *_review_checks(
            summary,
            summary_path.parent,
            target_config,
            review_path=review_path,
        ),
        *_manuscript_checks(summary, summary_path.parent),
    )
    verdict = _verdict(checks, target_config)
    score = _score(checks)

    output_path = resolved_output_dir / "publication-audit.json"
    markdown_path = resolved_output_dir / "publication-audit.md"
    report = PublicationAuditReport(
        target=target_config,
        verdict=verdict,
        score=score,
        checks=tuple(checks),
        cycle_summary_path=summary_path.as_posix(),
        review_path=_path_text(_review_artifact_path(summary, review_path)),
        output_path=output_path.as_posix(),
        markdown_path=markdown_path.as_posix(),
    )
    output_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(_markdown(report), encoding="utf-8")

    if vault_root is not None and project_id:
        review_path, issue_path = _write_vault_audit(report, Path(vault_root), project_id)
        report = PublicationAuditReport(
            target=report.target,
            verdict=report.verdict,
            score=report.score,
            checks=report.checks,
            cycle_summary_path=report.cycle_summary_path,
            review_path=report.review_path,
            output_path=report.output_path,
            markdown_path=report.markdown_path,
            vault_review_path=review_path.as_posix(),
            vault_issue_path=issue_path.as_posix() if issue_path is not None else None,
        )
        output_path.write_text(
            json.dumps(report.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        markdown_path.write_text(_markdown(report), encoding="utf-8")

    return report


def _target(name: str) -> PublicationQualityTarget:
    key = name.strip().lower().replace("_", "-")
    if key in {"ccfb", "ccf-b-level"}:
        key = "ccf-b"
    if key in {"三区", "third-quartile-journal", "q3"}:
        key = "q3-journal"
    try:
        return TARGETS[key]
    except KeyError as exc:
        valid = ", ".join(sorted(TARGETS))
        raise ValueError(f"unknown publication quality target {name!r}; expected one of {valid}") from exc


def _literature_checks(
    summary: dict[str, Any],
    target: PublicationQualityTarget,
) -> list[PublicationAuditCheck]:
    literature = _dict(summary.get("literature"))
    fetches = _dict_list(literature.get("fetches"))
    successful_sources = _successful_sources(fetches)
    required_source_errors, optional_source_errors = _partition_source_errors(fetches)
    query_count = _int(literature.get("query_count"))
    document_count = _int(literature.get("document_count"))

    checks = [
        _threshold_check(
            "literature_query_breadth",
            query_count,
            target.min_literature_queries,
            "blocking",
            f"Literature query breadth is {query_count}; target requires at least {target.min_literature_queries}.",
            "Expand query variants from title, gap, methods, datasets, baselines, negative evidence, and vault context.",
            ("cycle_summary.literature.query_count",),
        ),
        _threshold_check(
            "literature_document_breadth",
            document_count,
            target.min_literature_documents,
            "blocking",
            f"Retrieved normalized literature documents: {document_count}; target requires at least {target.min_literature_documents}.",
            "Run broader ArXiv/Semantic Scholar searches and preserve every source-backed paper before novelty claims.",
            ("cycle_summary.literature.document_count",),
        ),
        _threshold_check(
            "literature_source_breadth",
            len(successful_sources),
            target.min_successful_sources,
            "blocking",
            f"Successful literature sources: {', '.join(successful_sources) or 'none'}; target requires {target.min_successful_sources}.",
            "Resolve source failures or add another public academic source before publication-level novelty claims.",
            ("cycle_summary.literature.fetches",),
        ),
    ]
    if required_source_errors:
        errors = "; ".join(
            f"{_text(fetch.get('source'))}: {_text(fetch.get('error'))}"
            for fetch in required_source_errors
        )
        checks.append(
            PublicationAuditCheck(
                "literature_source_errors",
                PublicationAuditCheckStatus.FAIL,
                "high",
                f"Some literature sources failed: {errors}",
                ("cycle_summary.literature.fetches",),
                "Treat failed source coverage as a novelty-risk blocker until rerun with rate limits/API keys.",
            )
        )
    elif optional_source_errors:
        errors = "; ".join(
            f"{_text(fetch.get('source'))}: {_text(fetch.get('error'))}"
            for fetch in optional_source_errors
        )
        checks.append(
            PublicationAuditCheck(
                "literature_source_errors",
                PublicationAuditCheckStatus.WARNING,
                "medium",
                f"Only optional literature sources failed: {errors}",
                ("cycle_summary.literature.fetches",),
                "Semantic Scholar is optional; keep ArXiv/OpenAlex coverage, then retry the optional source later if its extra metadata is useful.",
            )
        )
    else:
        checks.append(
            PublicationAuditCheck(
                "literature_source_errors",
                PublicationAuditCheckStatus.PASS,
                "info",
                "No literature source errors were recorded.",
                ("cycle_summary.literature.fetches",),
            )
        )
    return checks


def _citation_checks(
    summary: dict[str, Any],
    base_dir: Path,
    target: PublicationQualityTarget,
) -> list[PublicationAuditCheck]:
    citations = _dict(summary.get("citations"))
    metadata_path = _resolve_path(citations.get("metadata_path"), base_dir)
    bib_path = _resolve_path(citations.get("bib_path"), base_dir)
    metadata = _read_json_if_exists(metadata_path)
    if not metadata:
        metadata = citations
    rows = _dict_list(metadata.get("citations"))
    verified = [
        row
        for row in rows
        if _text(row.get("status")) in {"verified_doi", "verified_url"}
    ]
    blocked_ids = tuple(
        str(value)
        for value in _list(
            metadata.get("blocked_document_ids") or citations.get("blocked_document_ids")
        )
    )
    blocked = [row for row in rows if _text(row.get("status")) == "blocked"]
    blocked_count = max(len(blocked), len(blocked_ids), _int(citations.get("blocked_count")))
    relevant, relevance_evidence, anchor_terms = _relevant_verified_citations(
        summary,
        base_dir,
        verified,
        metadata_path=metadata_path,
    )
    direct = _direct_verified_citations(summary, base_dir, verified, metadata_path=metadata_path)
    artifact_ok = bool(
        rows
        and metadata_path is not None
        and metadata_path.exists()
        and bib_path is not None
        and bib_path.exists()
    )
    if target.min_verified_citations <= 0 and not rows:
        return [
            PublicationAuditCheck(
                "citation_package",
                PublicationAuditCheckStatus.PASS,
                "info",
                "Citation package is not required for this publication target.",
                ("cycle_summary.citations",),
            )
        ]

    checks = [
        PublicationAuditCheck(
            "citation_package",
            PublicationAuditCheckStatus.PASS if artifact_ok else PublicationAuditCheckStatus.FAIL,
            "blocking",
            (
                "Citation package "
                f"metadata={'present' if metadata_path and metadata_path.exists() else 'missing'}, "
                f"bibtex={'present' if bib_path and bib_path.exists() else 'missing'}."
            ),
            (
                metadata_path.as_posix()
                if metadata_path is not None
                else "cycle_summary.citations.metadata_path",
                bib_path.as_posix() if bib_path is not None else "cycle_summary.citations.bib_path",
            ),
            None
            if artifact_ok
            else (
                "Generate references.bib and citation metadata from retrieved literature "
                "documents before publication audit."
            ),
        ),
        _threshold_check(
            "verified_citation_breadth",
            len(verified),
            target.min_verified_citations,
            "blocking",
            (
                f"Verified DOI/URL citations: {len(verified)}; target requires at least "
                f"{target.min_verified_citations}."
            ),
            (
                "Attach enough DOI- or URL-backed literature records before using "
                "the manuscript references as publication evidence."
            ),
            ("cycle_summary.citations",),
        ),
        _threshold_check(
            "citation_relevance_breadth",
            len(relevant),
            target.min_relevant_verified_citations,
            "blocking",
            (
                f"Relevant verified citations: {len(relevant)}; target requires at least "
                f"{target.min_relevant_verified_citations}. "
                f"Anchor terms: {', '.join(anchor_terms[:12]) or 'none'}."
            ),
            (
                "Rerun literature search with method-, dataset-, benchmark-, and baseline-aligned "
                "seed queries; then regenerate citation metadata with titles, abstracts, venues, "
                "tags, DOI/URL, and source URIs."
            ),
            relevance_evidence,
        ),
        _threshold_check(
            "citation_directness_breadth",
            len(direct),
            target.min_direct_verified_citations,
            "blocking",
            (
                f"Directly relevant verified citations: {len(direct)}; target requires at least "
                f"{target.min_direct_verified_citations}. Direct citations need strong method anchors "
                "such as prototype, centroid, variance calibration, nearest-centroid, Mahalanobis, "
                "or adjacent metric/classifier evidence, not only generic recognition wording."
            ),
            (
                "Rerun related-work search with direct method-family, benchmark, and baseline "
                "queries; then screen references before treating them as formal related work."
            ),
            relevance_evidence,
        ),
    ]
    blocked_ok = blocked_count <= target.max_blocked_citations
    checks.append(
        PublicationAuditCheck(
            "blocked_citation_count",
            PublicationAuditCheckStatus.PASS if blocked_ok else PublicationAuditCheckStatus.FAIL,
            "blocking",
            f"Blocked citations: {blocked_count}; target allows at most {target.max_blocked_citations}.",
            ("cycle_summary.citations",),
            None
            if blocked_ok
            else (
                "Remove or repair citations without DOI/URL metadata before "
                "publication-level claims."
            ),
        )
    )
    return checks


def _related_work_inspection_checks(
    summary: dict[str, Any],
    base_dir: Path,
    target: PublicationQualityTarget,
) -> list[PublicationAuditCheck]:
    related_work = _dict(summary.get("related_work_inspection"))
    json_path = _resolve_path(related_work.get("json_path"), base_dir)
    markdown_path = _resolve_path(related_work.get("markdown_path"), base_dir)
    payload = _read_json_if_exists(json_path)
    if not payload:
        payload = related_work
    if target.min_related_work_inspections <= 0 and not payload:
        return [
            PublicationAuditCheck(
                "related_work_inspection_package",
                PublicationAuditCheckStatus.PASS,
                "info",
                "Related-work inspection is not required for this publication target.",
                ("cycle_summary.related_work_inspection",),
            )
        ]

    package_ok = bool(
        payload
        and json_path is not None
        and json_path.exists()
        and markdown_path is not None
        and markdown_path.exists()
    )
    inspected_count = _int(payload.get("inspected_count"))
    abstract_backed_count = _int(payload.get("abstract_backed_count"))
    direct_method_count = _int(payload.get("direct_method_count"))
    return [
        PublicationAuditCheck(
            "related_work_inspection_package",
            PublicationAuditCheckStatus.PASS if package_ok else PublicationAuditCheckStatus.FAIL,
            "blocking",
            (
                "Related-work inspection package "
                f"json={'present' if json_path and json_path.exists() else 'missing'}, "
                f"markdown={'present' if markdown_path and markdown_path.exists() else 'missing'}."
            ),
            (
                json_path.as_posix()
                if json_path is not None
                else "cycle_summary.related_work_inspection.json_path",
                markdown_path.as_posix()
                if markdown_path is not None
                else "cycle_summary.related_work_inspection.markdown_path",
            ),
            None
            if package_ok
            else (
                "Generate a source-backed related-work inspection artifact from citation "
                "metadata before publication audit."
            ),
        ),
        _threshold_check(
            "related_work_inspection_breadth",
            inspected_count,
            target.min_related_work_inspections,
            "blocking",
            (
                f"Related-work inspected records: {inspected_count}; target requires at "
                f"least {target.min_related_work_inspections}."
            ),
            "Inspect enough DOI/URL-backed records before treating the related-work trail as screened evidence.",
            ("cycle_summary.related_work_inspection",),
        ),
        _threshold_check(
            "related_work_abstract_evidence",
            abstract_backed_count,
            target.min_related_work_abstract_evidence,
            "blocking",
            (
                f"Abstract-backed related-work records: {abstract_backed_count}; target "
                f"requires at least {target.min_related_work_abstract_evidence}."
            ),
            "Attach source abstracts or source-backed bibliographic summaries before paper-level related-work claims.",
            (
                json_path.as_posix()
                if json_path is not None
                else "cycle_summary.related_work_inspection.json_path",
            ),
        ),
        _threshold_check(
            "related_work_direct_method_candidates",
            direct_method_count,
            target.min_related_work_direct_method_candidates,
            "blocking",
            (
                f"Direct method related-work candidates: {direct_method_count}; target "
                f"requires at least {target.min_related_work_direct_method_candidates}."
            ),
            (
                "Find and inspect directly comparable method-family papers before the "
                "manuscript can claim submission-level positioning."
            ),
            (
                json_path.as_posix()
                if json_path is not None
                else "cycle_summary.related_work_inspection.json_path",
            ),
        ),
    ]


def _relevant_verified_citations(
    summary: dict[str, Any],
    base_dir: Path,
    rows: list[dict[str, Any]],
    *,
    metadata_path: Path | None,
) -> tuple[list[dict[str, Any]], tuple[str, ...], tuple[str, ...]]:
    primary_texts, secondary_texts, evidence_refs = _citation_relevance_context(
        summary,
        base_dir,
        metadata_path=metadata_path,
    )
    primary_tokens = _citation_anchor_tokens(primary_texts)
    all_tokens = _citation_anchor_tokens((*primary_texts, *secondary_texts))
    phrases = _citation_anchor_phrases(primary_texts)
    relevant = [
        row
        for row in rows
        if _citation_row_is_relevant(row, primary_tokens, all_tokens, phrases)
    ]
    anchor_terms = tuple(sorted(primary_tokens))[:24]
    return relevant, evidence_refs, anchor_terms


def _direct_verified_citations(
    summary: dict[str, Any],
    base_dir: Path,
    rows: list[dict[str, Any]],
    *,
    metadata_path: Path | None,
) -> list[dict[str, Any]]:
    primary_texts, secondary_texts, _ = _citation_relevance_context(
        summary,
        base_dir,
        metadata_path=metadata_path,
    )
    primary_tokens = _citation_anchor_tokens(primary_texts)
    all_context_tokens = _citation_anchor_tokens((*primary_texts, *secondary_texts))
    method_tokens = primary_tokens & (
        CITATION_DIRECT_METHOD_TOKENS | CITATION_DIRECT_SUPPORT_TOKENS
    )
    domain_tokens = primary_tokens - method_tokens - CITATION_RELEVANCE_STOPWORDS
    return [
        row
        for row in rows
        if _citation_row_is_direct(row, method_tokens, domain_tokens, all_context_tokens)
    ]


def _citation_relevance_context(
    summary: dict[str, Any],
    base_dir: Path,
    *,
    metadata_path: Path | None,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    candidate = _dict(summary.get("candidate"))
    candidate_metadata = _dict(candidate.get("metadata"))
    demo = _dict(summary.get("demo"))
    run_record_path = _run_record_path(summary, base_dir)
    run_record = _read_json_if_exists(run_record_path)
    task_metadata = _dict(run_record.get("task_metadata"))
    run = _dict(run_record.get("run"))

    primary_fields = (
        "method",
        "proposed_method",
        "method_contribution",
        "mechanism",
        "dataset",
        "benchmark",
        "baseline",
        "ablation",
        "demo",
        "task_id",
    )
    secondary_fields = (
        "title",
        "description",
        "research_gap",
        "limitation",
        "novel_contribution",
        "contribution",
        "seed_document_title",
    )
    primary_texts = _context_values(candidate_metadata, primary_fields)
    primary_texts += _context_values(task_metadata, primary_fields)
    primary_texts += _context_values(run, ("task_id",))
    primary_texts += _context_values(demo, ("demo",))

    secondary_texts = _context_values(candidate, secondary_fields)
    secondary_texts += _context_values(candidate_metadata, secondary_fields)
    secondary_texts += _context_values(task_metadata, secondary_fields)

    refs = ["cycle_summary.candidate", "cycle_summary.demo"]
    if metadata_path is not None:
        refs.append(metadata_path.as_posix())
    if run_record_path is not None:
        refs.append(run_record_path.as_posix())
    return tuple(primary_texts), tuple(secondary_texts), tuple(refs)


def _run_record_path(summary: dict[str, Any], base_dir: Path) -> Path | None:
    demo = _dict(summary.get("demo"))
    explicit = _resolve_path(demo.get("run_record_path"), base_dir)
    if explicit is not None and explicit.exists():
        return explicit
    experiment_dir = _resolve_path(demo.get("experiment_dir"), base_dir)
    if experiment_dir is None:
        return explicit
    candidate = experiment_dir / "run" / "run-record.json"
    if candidate.exists():
        return candidate
    return explicit


def _context_values(payload: dict[str, Any], fields: tuple[str, ...]) -> tuple[str, ...]:
    values: list[str] = []
    for field in fields:
        value = payload.get(field)
        if isinstance(value, dict):
            values.extend(_text(item) for item in value.values())
            continue
        if isinstance(value, list | tuple | set):
            values.extend(_text(item) for item in value)
            continue
        text = _text(value).strip()
        if text:
            values.append(text)
    return tuple(values)


def _citation_anchor_tokens(texts: tuple[str, ...]) -> set[str]:
    return {
        token
        for text in texts
        for token in _semantic_tokens(text)
        if token not in CITATION_RELEVANCE_STOPWORDS
    }


def _citation_anchor_phrases(texts: tuple[str, ...]) -> tuple[str, ...]:
    phrases: set[str] = set()
    for text in texts:
        tokens = [
            token
            for token in _semantic_tokens(text)
            if token not in CITATION_RELEVANCE_STOPWORDS
        ]
        for size in (2, 3):
            for index in range(0, max(0, len(tokens) - size + 1)):
                phrase = " ".join(tokens[index : index + size])
                if phrase:
                    phrases.add(phrase)
    return tuple(sorted(phrases))


def _citation_row_is_relevant(
    row: dict[str, Any],
    primary_tokens: set[str],
    all_tokens: set[str],
    phrases: tuple[str, ...],
) -> bool:
    if not primary_tokens:
        return False
    citation_text = _citation_row_text(row)
    citation_tokens = set(_semantic_tokens(citation_text))
    if not citation_tokens:
        return False
    primary_overlap = citation_tokens & primary_tokens
    all_overlap = citation_tokens & all_tokens
    if len(primary_overlap) >= 2:
        return True
    if primary_overlap and len(all_overlap) >= 3:
        return True
    normalized_text = " ".join(_semantic_tokens(citation_text))
    return any(phrase in normalized_text for phrase in phrases)


def _citation_row_is_direct(
    row: dict[str, Any],
    method_tokens: set[str],
    domain_tokens: set[str],
    _all_context_tokens: set[str],
) -> bool:
    citation_tokens = set(_semantic_tokens(_citation_row_text(row)))
    if not citation_tokens:
        return False
    strong_method_overlap = (
        citation_tokens
        & method_tokens
        & CITATION_DIRECT_METHOD_TOKENS
    )
    domain_overlap = citation_tokens & domain_tokens
    if len(strong_method_overlap) >= 2:
        return True
    if strong_method_overlap and domain_overlap:
        return True
    title_tag_tokens = set(_semantic_tokens(_citation_row_title_tag_text(row)))
    if {"nearest", "centroid"} <= title_tag_tokens:
        return True
    if "prototype" in title_tag_tokens and citation_tokens & {"classifier", "classification"}:
        return True
    return False


def _citation_row_text(row: dict[str, Any]) -> str:
    parts = [
        _text(row.get("title")),
        _text(row.get("abstract")),
        _text(row.get("venue")),
        _text(row.get("source_uri")),
        " ".join(_text(author) for author in _list(row.get("authors"))),
        " ".join(_text(tag) for tag in _list(row.get("tags"))),
    ]
    return "\n".join(part for part in parts if part)


def _citation_row_title_tag_text(row: dict[str, Any]) -> str:
    parts = [
        _text(row.get("title")),
        " ".join(_text(tag) for tag in _list(row.get("tags"))),
    ]
    return "\n".join(part for part in parts if part)


def _semantic_tokens(text: str) -> tuple[str, ...]:
    tokens: list[str] = []
    for raw_token in re.findall(r"[a-z0-9]+", text.casefold().replace("_", " ")):
        if len(raw_token) < 3:
            continue
        token = _normalise_token(raw_token)
        if token:
            tokens.append(token)
    return tuple(tokens)


def _normalise_token(token: str) -> str:
    if token.endswith("ies") and len(token) > 5:
        return f"{token[:-3]}y"
    if token.endswith("ss"):
        return token
    if token.endswith("s") and len(token) > 4:
        return token[:-1]
    return token


def _similarity_checks(
    summary: dict[str, Any],
    base_dir: Path,
    target: PublicationQualityTarget,
) -> list[PublicationAuditCheck]:
    similarity = _dict(summary.get("similarity"))
    fetches = _dict_list(similarity.get("fetches"))
    successful_sources = _successful_sources(fetches)
    required_source_errors, optional_source_errors = _partition_source_errors(fetches)
    query_count = len({_text(fetch.get("query")) for fetch in fetches if _text(fetch.get("query"))})
    finding_count = _int(similarity.get("finding_count"))
    classifications = _similarity_classifications(similarity, base_dir)
    direct_duplicates = classifications.get("direct_duplicate", 0)
    adjacent_work = classifications.get("adjacent_work", 0)
    unknown_findings = classifications.get("unknown", 0)
    classified_findings = sum(
        count for classification, count in classifications.items() if classification != "unknown"
    )

    checks = [
        _threshold_check(
            "similarity_query_breadth",
            query_count,
            target.min_similarity_queries,
            "blocking",
            f"Similarity-check query breadth is {query_count}; target requires at least {target.min_similarity_queries}.",
            "Search candidate title, research gap, method/dataset terms, baselines, negative results, and vault context.",
            ("cycle_summary.similarity.fetches",),
        ),
        _threshold_check(
            "similarity_finding_breadth",
            finding_count,
            target.min_similarity_findings,
            "blocking",
            f"Similarity findings: {finding_count}; target requires at least {target.min_similarity_findings}.",
            "Collect enough adjacent-work evidence before claiming novelty or cross-validation coverage.",
            ("cycle_summary.similarity.finding_count",),
        ),
        _threshold_check(
            "similarity_source_breadth",
            len(successful_sources),
            target.min_successful_sources,
            "blocking",
            f"Successful similarity-check sources: {', '.join(successful_sources) or 'none'}; target requires {target.min_successful_sources}.",
            "Resolve source failures or add another source before publication-level novelty claims.",
            ("cycle_summary.similarity.fetches",),
        ),
    ]
    if required_source_errors:
        errors = "; ".join(
            f"{_text(fetch.get('source'))}: {_text(fetch.get('error'))}"
            for fetch in required_source_errors
        )
        checks.append(
            PublicationAuditCheck(
                "similarity_source_errors",
                PublicationAuditCheckStatus.FAIL,
                "high",
                f"Some similarity-check sources failed: {errors}",
                ("cycle_summary.similarity.fetches",),
                "Rerun cross-search after rate-limit cooldown/API-key setup; do not treat missing sources as negative evidence.",
            )
        )
    elif optional_source_errors:
        errors = "; ".join(
            f"{_text(fetch.get('source'))}: {_text(fetch.get('error'))}"
            for fetch in optional_source_errors
        )
        checks.append(
            PublicationAuditCheck(
                "similarity_source_errors",
                PublicationAuditCheckStatus.WARNING,
                "medium",
                f"Only optional similarity-check sources failed: {errors}",
                ("cycle_summary.similarity.fetches",),
                "Do not treat the optional source outage as negative evidence; keep core-source breadth and retry Semantic Scholar later if needed.",
            )
        )
    else:
        checks.append(
            PublicationAuditCheck(
                "similarity_source_errors",
                PublicationAuditCheckStatus.PASS,
                "info",
                "No similarity-check source errors were recorded.",
                ("cycle_summary.similarity.fetches",),
            )
        )
    if target.require_novel_contribution:
        checks.append(
            _threshold_check(
                "similarity_classified_finding_breadth",
                classified_findings,
                target.min_similarity_findings,
                "blocking",
                f"Evidence-classified similarity findings: {classified_findings}; target requires at least {target.min_similarity_findings}.",
                "Classify enough source-backed similar-work findings before using similarity breadth as novelty support.",
                ("cycle_summary.similarity.summary_path",),
            )
        )
    if target.require_novel_contribution and finding_count > 0 and classified_findings <= 0:
        checks.append(
            PublicationAuditCheck(
                "similarity_classification_coverage",
                PublicationAuditCheckStatus.FAIL,
                "high",
                f"Similarity findings are all unclassified or unknown: unknown={unknown_findings}, classified={classified_findings}.",
                ("cycle_summary.similarity.summary_path",),
                "Resolve unknown similarity classifications into direct_duplicate, adjacent_work, or another supported evidence-backed category before claiming novelty.",
            )
        )
    else:
        checks.append(
            PublicationAuditCheck(
                "similarity_classification_coverage",
                PublicationAuditCheckStatus.PASS,
                "info",
                f"Similarity classification coverage includes {classified_findings} non-unknown findings and {unknown_findings} unknown findings.",
                ("cycle_summary.similarity.summary_path",),
            )
        )
    if direct_duplicates:
        checks.append(
            PublicationAuditCheck(
                "similarity_duplicate_risk",
                PublicationAuditCheckStatus.FAIL,
                "blocking",
                f"Similarity check found {direct_duplicates} direct duplicate candidates.",
                ("cycle_summary.similarity.summary_path",),
                "Reject or substantially reposition the candidate before further experiments.",
            )
        )
    elif adjacent_work:
        checks.append(
            PublicationAuditCheck(
                "similarity_duplicate_risk",
                PublicationAuditCheckStatus.WARNING,
                "high",
                f"Similarity check found {adjacent_work} adjacent-work findings that need positioning.",
                ("cycle_summary.similarity.summary_path",),
                "Write a related-work comparison before publication review.",
            )
        )
    else:
        checks.append(
            PublicationAuditCheck(
                "similarity_duplicate_risk",
                PublicationAuditCheckStatus.PASS,
                "info",
                "No direct duplicate was detected in the current similarity metadata.",
                ("cycle_summary.similarity.summary_path",),
            )
        )
    return checks


def _script_and_data_checks(
    summary: dict[str, Any],
    base_dir: Path,
    target: PublicationQualityTarget,
) -> list[PublicationAuditCheck]:
    demo = _dict(summary.get("demo"))
    experiment_dir = _resolve_path(demo.get("experiment_dir"), base_dir)
    run_record_path = experiment_dir / "run" / "run-record.json" if experiment_dir else None
    if run_record_path is None or not run_record_path.exists():
        return [
            PublicationAuditCheck(
                "script_data_verification",
                PublicationAuditCheckStatus.FAIL,
                "blocking",
                "Run record is missing, so the audit cannot verify that code executed on data.",
                ("cycle_summary.demo.experiment_dir",),
                "Rerun the experiment and preserve run/run-record.json.",
            )
        ]

    run_record = _read_json(run_record_path)
    run = _dict(run_record.get("run"))
    metrics = _dict(_dict(run_record.get("metrics")).get("values"))
    validation = _dict(run_record.get("validation_report"))
    artifacts = _list(run_record.get("artifacts"))
    logs = _list(run_record.get("logs"))
    entrypoint = _resolve_path(_dict(run.get("metadata")).get("entrypoint"), base_dir)
    metrics_path = _resolve_path(run.get("metrics_path"), base_dir)
    data_path = _detect_data_path(experiment_dir, _text(run.get("task_id")))
    artifact_paths_ok = _relative_paths_exist(experiment_dir, artifacts)
    log_paths_ok = _relative_paths_exist(experiment_dir, logs)
    data_hash_ok = bool(
        data_path
        and data_path.exists()
        and _text(run.get("data_hash"))
        and file_hash(data_path) == _text(run.get("data_hash"))
    )
    script_data_ok = all(
        [
            _text(run.get("status")) == "success",
            _int(run.get("exit_code"), default=-1) == 0,
            entrypoint is not None and entrypoint.exists(),
            metrics_path is not None and metrics_path.exists(),
            _text(validation.get("status")) == "passed",
            artifact_paths_ok,
            log_paths_ok,
            data_hash_ok,
        ]
    )
    test_rows = int(float(metrics.get("test_rows", 0) or 0))
    synthetic = _is_synthetic_demo(run_record, experiment_dir)
    baseline_present = _has_baseline_evidence(run_record)
    ablation_present = _has_ablation_evidence(run_record)
    statistical_sanity = _has_statistical_sanity(run_record)
    innovation_present = _has_innovation_evidence(run_record, experiment_dir)
    method_effect_check = _method_effect_check(
        run_record,
        experiment_dir,
        target,
        run_record_path.as_posix(),
    )

    checks = [
        PublicationAuditCheck(
            "script_data_verification",
            PublicationAuditCheckStatus.PASS if script_data_ok else PublicationAuditCheckStatus.FAIL,
            "blocking",
            _script_data_message(script_data_ok, entrypoint, data_path, metrics_path),
            (
                run_record_path.as_posix(),
                entrypoint.as_posix() if entrypoint else "missing_entrypoint",
                data_path.as_posix() if data_path else "missing_data",
                metrics_path.as_posix() if metrics_path else "missing_metrics",
            ),
            None if script_data_ok else "Verify run.py, data hash, metrics, logs, artifacts, and validation output.",
        ),
        _threshold_check(
            "data_strength",
            test_rows,
            target.min_test_rows,
            "blocking",
            f"Validated test rows: {test_rows}; target requires at least {target.min_test_rows}.",
            "Use a real benchmark or a sufficiently sized dataset before claiming publication-level empirical support.",
            (run_record_path.as_posix(),),
        ),
    ]
    if target.require_real_dataset and synthetic:
        checks.append(
            PublicationAuditCheck(
                "dataset_realism",
                PublicationAuditCheckStatus.FAIL,
                "blocking",
                "The experiment uses a synthetic or ScientistBench-Lite fixture; this cannot prove a CCF-B/Q3-level paper claim.",
                (run_record_path.as_posix(),),
                "Run on a real benchmark dataset with documented splits, preprocessing, and baseline comparability.",
            )
        )
    else:
        checks.append(
            PublicationAuditCheck(
                "dataset_realism",
                PublicationAuditCheckStatus.PASS,
                "info",
                "Dataset realism requirement is satisfied for this target.",
                (run_record_path.as_posix(),),
            )
        )
    checks.extend(
        [
            _boolean_requirement_check(
                "baseline_reproduction",
                baseline_present or not target.require_baseline,
                "high",
                "Baseline reproduction evidence is present.",
                "Baseline reproduction evidence is missing.",
                "Run and validate at least one credible baseline with comparable settings.",
                (run_record_path.as_posix(),),
            ),
            _boolean_requirement_check(
                "ablation_coverage",
                ablation_present or not target.require_ablation,
                "high",
                "Ablation evidence is present.",
                "Ablation evidence is missing.",
                "Run ablations for the proposed mechanism before publication review.",
                (run_record_path.as_posix(),),
            ),
            _boolean_requirement_check(
                "statistical_sanity",
                statistical_sanity or not target.require_statistical_sanity,
                "high",
                "Statistical sanity checks are present.",
                "Statistical sanity checks are missing.",
                "Add sample-size, variance/confidence, repeated-run, or significance checks.",
                (run_record_path.as_posix(),),
            ),
            _boolean_requirement_check(
                "method_innovation_evidence",
                innovation_present or not target.require_novel_contribution,
                "high",
                "File-backed method innovation evidence is present.",
                "File-backed method innovation evidence is missing or baseline-only.",
                (
                    "Record a proposed mechanism/contribution in task metadata and "
                    "preserve an innovation/mechanism artifact before publication review."
                ),
                (run_record_path.as_posix(),),
            ),
            method_effect_check,
        ]
    )
    return checks


def _review_checks(
    summary: dict[str, Any],
    base_dir: Path,
    target: PublicationQualityTarget,
    *,
    review_path: Path | str | None,
) -> list[PublicationAuditCheck]:
    review = _review_gate_info(
        summary,
        review_path,
        base_dir,
        min_quality=target.min_llm_review_quality,
    )
    review_source = _path_text(_review_artifact_path(summary, review_path)) or "cycle_summary.review"
    quality = float(review.get("quality_score", 0.0) or 0.0)
    status = _text(review.get("status"))
    verdict = _text(review.get("verdict"))
    passed = status == "passed" and quality >= target.min_llm_review_quality
    checks = [
        PublicationAuditCheck(
            "llm_evidence_review",
            PublicationAuditCheckStatus.PASS if passed else PublicationAuditCheckStatus.FAIL,
            "high",
            (
                f"LLM evidence review status={status or 'missing'}, verdict={verdict or 'missing'}, "
                f"quality_score={quality:.3f}; target requires >= {target.min_llm_review_quality:.2f}."
            ),
            (review_source,),
            None if passed else "Run evidence-constrained LLM review and fix unsupported claims before publication audit.",
        )
    ]
    strict_review_verdict = target.name in {"ccf-b", "q3-journal"}
    if verdict not in {"pass", "needs_revision"}:
        checks.append(
            PublicationAuditCheck(
                "review_verdict_strength",
                PublicationAuditCheckStatus.FAIL,
                "high",
                f"Reviewer verdict is `{verdict or 'missing'}`, not publication-ready.",
                (review_source,),
                "Treat fail/missing reviewer verdicts as blockers.",
            )
        )
    elif strict_review_verdict and verdict != "pass":
        checks.append(
            PublicationAuditCheck(
                "review_verdict_strength",
                PublicationAuditCheckStatus.FAIL,
                "high",
                f"Reviewer verdict is `{verdict}`, not ready for {target.name} publication audit.",
                (review_source,),
                "Resolve reviewer revision items before CCF-B/Q3 publication audit can pass.",
            )
        )
    else:
        checks.append(
            PublicationAuditCheck(
                "review_verdict_strength",
                PublicationAuditCheckStatus.PASS if verdict == "pass" else PublicationAuditCheckStatus.WARNING,
                "medium",
                f"Reviewer verdict is `{verdict}`.",
                (review_source,),
                None if verdict == "pass" else "Resolve reviewer revision items before submission.",
            )
        )
    if review_path is not None:
        checks.append(_review_artifact_binding_check(summary, base_dir, review, review_source))
    return checks


def _review_artifact_binding_check(
    summary: dict[str, Any],
    base_dir: Path,
    review: dict[str, Any],
    review_source: str,
) -> PublicationAuditCheck:
    demo = _dict(summary.get("demo"))
    subject_path = _manuscript_path(summary, base_dir)
    if subject_path is None or not subject_path.exists():
        return PublicationAuditCheck(
            "review_artifact_binding",
            PublicationAuditCheckStatus.FAIL,
            "blocking",
            "Standalone review artifact cannot be bound because the reviewed paper draft is missing.",
            (
                review_source,
                "cycle_summary.paper_manuscript.markdown_path",
                "cycle_summary.demo.report_path",
            ),
            "Regenerate the paper draft before using a standalone review artifact.",
        )

    subject_ok = _review_subject_matches_report(review, subject_path, base_dir)
    required_paths = tuple(
        path
        for path in (
            _resolve_path(demo.get("run_record_path"), base_dir),
            _resolve_path(demo.get("validation_json_path"), base_dir),
            _resolve_path(demo.get("evidence_map_path"), base_dir),
        )
        if path is not None and path.exists()
    )
    covered_paths = tuple(
        path for path in required_paths if _review_evidence_covers_path(review, path, base_dir)
    )
    required_ok = bool(required_paths) and len(covered_paths) == len(required_paths)
    passed = subject_ok and required_ok
    return PublicationAuditCheck(
        "review_artifact_binding",
        PublicationAuditCheckStatus.PASS if passed else PublicationAuditCheckStatus.FAIL,
        "blocking",
        (
            "Standalone review artifact binding "
            f"subject_match={str(subject_ok).lower()}, "
            f"covered_required_evidence={len(covered_paths)}/{len(required_paths)}."
        ),
        (review_source, subject_path.as_posix(), *(path.as_posix() for path in required_paths)),
        None
        if passed
        else (
            "Rerun llm-review against this cycle's paper draft plus run, validation, and evidence-map "
            "artifacts before publication audit."
        ),
    )


def _review_subject_matches_report(
    review: dict[str, Any],
    report_path: Path,
    base_dir: Path,
) -> bool:
    subject_sha = _text(review.get("subject_sha256"))
    if subject_sha:
        return file_hash(report_path) == subject_sha
    subject_path = _resolve_path(review.get("subject_path"), base_dir)
    return subject_path is not None and _same_file(subject_path, report_path)


def _review_evidence_covers_path(review: dict[str, Any], required_path: Path, base_dir: Path) -> bool:
    required_hash = file_hash(required_path)
    for evidence in _dict_list(review.get("evidence")):
        if _text(evidence.get("sha256")) == required_hash:
            return True
        evidence_path = _resolve_path(evidence.get("path"), base_dir)
        if evidence_path is not None and _same_file(evidence_path, required_path):
            return True
    return False


def _review_artifact_path(
    summary: dict[str, Any],
    explicit_path: Path | str | None,
) -> Path | str | None:
    if explicit_path is not None:
        return explicit_path
    review = _dict(summary.get("review"))
    return review.get("output_path")


def _review_gate_info(
    summary: dict[str, Any],
    explicit_path: Path | str | None,
    base_dir: Path,
    *,
    min_quality: float,
) -> dict[str, Any]:
    if explicit_path is None:
        return _dict(summary.get("review"))

    resolved_path = _resolve_path(explicit_path, base_dir)
    payload, error = _read_json_with_error(resolved_path or explicit_path)
    if error:
        return {"status": "unreadable", "output_path": _path_text(explicit_path), "error": error}

    quality = _dict(payload.get("quality"))
    parsed = _dict(quality.get("parsed_output"))
    quality_score = quality.get("score")
    if not isinstance(quality_score, int | float):
        quality_score = payload.get("quality_score")
    status = _text(payload.get("status"))
    if not status and isinstance(quality_score, int | float):
        status = "passed" if quality_score >= min_quality else "below_threshold"
    verdict = _text(payload.get("verdict")) or _text(parsed.get("verdict"))
    return {
        "status": status,
        "verdict": verdict,
        "quality_score": quality_score,
        "output_path": _path_text(explicit_path),
        "subject_path": payload.get("subject_path"),
        "subject_sha256": payload.get("subject_sha256"),
        "evidence": _dict_list(payload.get("evidence")),
    }


def _manuscript_checks(
    summary: dict[str, Any],
    base_dir: Path,
) -> list[PublicationAuditCheck]:
    report_path = _manuscript_path(summary, base_dir)
    if report_path is None or not report_path.exists():
        return [
            PublicationAuditCheck(
                "manuscript_structure",
                PublicationAuditCheckStatus.FAIL,
                "high",
                "No Markdown report or paper draft was found for manuscript-structure audit.",
                ("cycle_summary.paper_manuscript.markdown_path", "cycle_summary.demo.report_path"),
                "Generate a paper draft with required academic sections.",
            )
        ]
    text = report_path.read_text(encoding="utf-8").casefold()
    present = tuple(section for section in REQUIRED_PAPER_SECTIONS if _has_markdown_heading(text, section))
    missing = tuple(section for section in REQUIRED_PAPER_SECTIONS if section not in present)
    if missing:
        return [
            PublicationAuditCheck(
                "manuscript_structure",
                PublicationAuditCheckStatus.FAIL,
                "high",
                "The current report is not a publication-style manuscript; missing sections: "
                + ", ".join(missing),
                (report_path.as_posix(),),
                "Generate an evidence-backed paper draft with abstract, related work, method, experiments, limitations, and references.",
            )
        ]
    return [
        PublicationAuditCheck(
            "manuscript_structure",
            PublicationAuditCheckStatus.PASS,
            "info",
            "All required manuscript sections are present.",
            (report_path.as_posix(),),
        )
    ]


def _manuscript_path(summary: dict[str, Any], base_dir: Path) -> Path | None:
    paper_manuscript = _dict(summary.get("paper_manuscript"))
    for key in ("markdown_path", "path"):
        path = _resolve_path(paper_manuscript.get(key), base_dir)
        if path is not None:
            return path
    return _resolve_path(_dict(summary.get("demo")).get("report_path"), base_dir)


def _threshold_check(
    check_id: str,
    actual: int,
    minimum: int,
    severity: str,
    message: str,
    next_action: str,
    evidence_refs: tuple[str, ...],
) -> PublicationAuditCheck:
    return PublicationAuditCheck(
        check_id,
        PublicationAuditCheckStatus.PASS if actual >= minimum else PublicationAuditCheckStatus.FAIL,
        severity,
        message,
        evidence_refs,
        None if actual >= minimum else next_action,
    )


def _boolean_requirement_check(
    check_id: str,
    passed: bool,
    severity: str,
    pass_message: str,
    fail_message: str,
    next_action: str,
    evidence_refs: tuple[str, ...],
) -> PublicationAuditCheck:
    return PublicationAuditCheck(
        check_id,
        PublicationAuditCheckStatus.PASS if passed else PublicationAuditCheckStatus.FAIL,
        severity,
        pass_message if passed else fail_message,
        evidence_refs,
        None if passed else next_action,
    )


def _score(checks: tuple[PublicationAuditCheck, ...] | list[PublicationAuditCheck]) -> float:
    if not checks:
        return 0.0
    weight_by_severity = {
        "blocking": 2.0,
        "high": 1.5,
        "medium": 1.0,
        "info": 0.5,
    }
    total = 0.0
    earned = 0.0
    for check in checks:
        weight = weight_by_severity.get(check.severity, 1.0)
        total += weight
        if check.status is PublicationAuditCheckStatus.PASS:
            earned += weight
        elif check.status is PublicationAuditCheckStatus.WARNING:
            earned += weight * 0.5
    if total <= 0.0:
        return 0.0
    return round(earned / total, 4)


def _verdict(
    checks: tuple[PublicationAuditCheck, ...] | list[PublicationAuditCheck],
    target: PublicationQualityTarget,
) -> PublicationAuditVerdict:
    score = _score(checks)
    blocking_fail = any(
        check.status is PublicationAuditCheckStatus.FAIL and check.severity == "blocking"
        for check in checks
    )
    hard_fail = any(
        check.status is PublicationAuditCheckStatus.FAIL and check.severity in {"blocking", "high"}
        for check in checks
    )
    if blocking_fail:
        return PublicationAuditVerdict.FAIL
    if hard_fail or score < target.min_score:
        return PublicationAuditVerdict.NEEDS_REVISION
    return PublicationAuditVerdict.PASS


def _markdown(report: PublicationAuditReport) -> str:
    lines = [
        "# Publication Quality Audit",
        "",
        f"- Target: `{report.target.display_name}`",
        f"- Verdict: `{report.verdict.value}`",
        f"- Publishable: `{str(report.publishable).lower()}`",
        f"- Score: `{report.score:.3f}`",
        f"- Cycle summary: `{report.cycle_summary_path}`",
        f"- Review artifact: `{report.review_path or 'cycle_summary.review'}`",
        f"- JSON: `{report.output_path}`",
        f"- Vault review: `{report.vault_review_path or 'not written'}`",
        f"- Vault issue: `{report.vault_issue_path or 'not written'}`",
        "",
        "## Target Gates",
        "",
        f"- Minimum score: `{report.target.min_score}`",
        f"- Literature: `{report.target.min_literature_queries}` queries, `{report.target.min_literature_documents}` documents, `{report.target.min_successful_sources}` successful sources",
        f"- Citations: `{report.target.min_verified_citations}` verified DOI/URL citations, `{report.target.min_relevant_verified_citations}` relevant verified citations, `{report.target.min_direct_verified_citations}` directly relevant verified citations, max `{report.target.max_blocked_citations}` blocked citations",
        f"- Related-work inspection: `{report.target.min_related_work_inspections}` inspected records, `{report.target.min_related_work_abstract_evidence}` abstract-backed records, `{report.target.min_related_work_direct_method_candidates}` direct method candidates",
        f"- Similarity: `{report.target.min_similarity_queries}` queries, `{report.target.min_similarity_findings}` findings, `{report.target.min_successful_sources}` successful sources",
        f"- Data: at least `{report.target.min_test_rows}` validated test rows; real dataset required: `{str(report.target.require_real_dataset).lower()}`",
        f"- Experiment: baseline `{report.target.require_baseline}`, ablation `{report.target.require_ablation}`, statistical sanity `{report.target.require_statistical_sanity}`",
        "",
        "## Checks",
        "",
        "| Check | Status | Severity | Evidence | Message | Next action |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for check in report.checks:
        evidence = ", ".join(f"`{ref}`" for ref in check.evidence_refs) or "`none`"
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{check.check_id}`",
                    f"`{check.status.value}`",
                    f"`{check.severity}`",
                    evidence,
                    _escape_table(check.message),
                    _escape_table(check.next_action or "None"),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `pass` means this audit did not find publication-readiness blockers for the configured target.",
            "- `needs_revision` means the cycle is evidence-bearing but not ready for submission.",
            "- `fail` means the system must not describe the output as CCF-B/Q3-publication-level.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _write_vault_audit(
    report: PublicationAuditReport,
    vault_root: Path,
    project_id: str,
) -> tuple[Path, Path | None]:
    store = MarkdownKnowledgeStore(vault_root)
    now = datetime.now(timezone.utc)
    slug = _slug(Path(report.cycle_summary_path).parent.name or "cycle")
    review_entry = KnowledgeEntry(
        entry_id=f"publication_audit_{project_id}_{slug}",
        entry_type=KnowledgeEntryType.REVIEW_NOTE,
        zone=KnowledgeZone.PROJECT,
        project_id=project_id,
        title=f"Publication audit {slug}",
        tags=["publication-audit", report.verdict.value],
        keywords=["publication-audit", report.target.name, report.verdict.value],
        source_refs=[
            ref
            for ref in (
                report.cycle_summary_path,
                report.review_path,
                report.output_path,
                report.markdown_path,
            )
            if ref
        ],
        related_task_ids=["publication-audit"],
        body=_markdown(report),
        created_at=now,
        updated_at=now,
    )
    review_path = store.write_entry(
        Path("projects") / project_id / "review" / f"publication-audit-{slug}.md",
        review_entry,
    )
    issue_path = None
    if report.verdict is not PublicationAuditVerdict.PASS:
        failed_checks = [check for check in report.checks if check.status is PublicationAuditCheckStatus.FAIL]
        issue_entry = KnowledgeEntry(
            entry_id=f"publication_audit_issue_{project_id}_{slug}",
            entry_type=KnowledgeEntryType.ISSUE_NOTE,
            zone=KnowledgeZone.PROJECT,
            project_id=project_id,
            title=f"Publication audit blockers {slug}",
            tags=["open", "publication-audit", report.verdict.value],
            keywords=["publication-audit", "quality-gate", report.target.name],
            source_refs=[
                ref for ref in (report.review_path, report.output_path, report.markdown_path) if ref
            ],
            links=[review_entry.entry_id],
            related_task_ids=["publication-audit"],
            body=_issue_body(report, review_entry.entry_id, failed_checks),
            created_at=now,
            updated_at=now,
        )
        issue_path = store.write_entry(
            Path("projects") / project_id / "issues" / f"publication-audit-{slug}.md",
            issue_entry,
        )
    return review_path, issue_path


def _issue_body(
    report: PublicationAuditReport,
    review_entry_id: str,
    failed_checks: list[PublicationAuditCheck],
) -> str:
    lines = [
        f"# Publication audit blockers for {Path(report.cycle_summary_path).parent.name}",
        "",
        f"- Review note: [[{review_entry_id}]]",
        f"- Target: `{report.target.display_name}`",
        f"- Verdict: `{report.verdict.value}`",
        f"- Score: `{report.score:.3f}`",
        f"- Issue fingerprint: `publication-audit:{Path(report.cycle_summary_path).parent.name}`",
        "",
        "## Failed Checks",
        "",
    ]
    for check in failed_checks:
        lines.extend(
            [
                f"### {check.check_id}",
                "",
                f"- Severity: `{check.severity}`",
                f"- Evidence refs: {', '.join(f'`{ref}`' for ref in check.evidence_refs) or '`none`'}",
                f"- Message: {check.message}",
                f"- Next action: {check.next_action or 'None'}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _similarity_classifications(similarity: dict[str, Any], base_dir: Path) -> dict[str, int]:
    summary_path = _resolve_path(similarity.get("summary_path"), base_dir)
    if summary_path is None or not summary_path.exists():
        return {}
    text = summary_path.read_text(encoding="utf-8")
    counts: dict[str, int] = {}
    for match in re.finditer(r"Classification:\s*`([^`]+)`", text):
        classification = match.group(1).strip()
        counts[classification] = counts.get(classification, 0) + 1
    return counts


def _successful_sources(fetches: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                _text(fetch.get("source"))
                for fetch in fetches
                if _int(fetch.get("paper_count")) > 0 and not _text(fetch.get("error"))
            }
        )
    )


def _partition_source_errors(
    fetches: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    errored = [fetch for fetch in fetches if _text(fetch.get("error"))]
    required = [
        fetch for fetch in errored if _text(fetch.get("source")) not in OPTIONAL_LITERATURE_SOURCES
    ]
    optional = [
        fetch for fetch in errored if _text(fetch.get("source")) in OPTIONAL_LITERATURE_SOURCES
    ]
    return required, optional


def _script_data_message(
    script_data_ok: bool,
    entrypoint: Path | None,
    data_path: Path | None,
    metrics_path: Path | None,
) -> str:
    if script_data_ok:
        return (
            "Execution record confirms run.py existed, data hash matched the local data file, "
            "metrics were written, artifacts/logs existed, exit_code was 0, and validation passed."
        )
    return (
        "Could not prove script/data execution from local artifacts. "
        f"entrypoint={entrypoint}, data={data_path}, metrics={metrics_path}"
    )


def _detect_data_path(experiment_dir: Path | None, task_id: str) -> Path | None:
    if experiment_dir is None:
        return None
    data_dir = experiment_dir / "data"
    candidates = [data_dir / f"{task_id}.csv"]
    if data_dir.exists():
        candidates.extend(sorted(data_dir.glob("*.csv")))
    for path in candidates:
        if path.exists():
            return path
    return None


def _is_synthetic_demo(run_record: dict[str, Any], experiment_dir: Path | None) -> bool:
    run = _dict(run_record.get("run"))
    task_metadata = _dict(run_record.get("task_metadata"))
    metrics_json = _read_json_if_exists(_dict(run_record.get("metrics")).get("path"))
    metrics_metadata = _dict(metrics_json.get("metadata"))
    if task_metadata.get("real_dataset") is True or metrics_metadata.get("real_dataset") is True:
        return False
    task_id = _text(run.get("task_id")).casefold()
    project_id = _text(run.get("project_id")).casefold()
    if "scientistbench-lite" in project_id or task_id in {"tabular_baseline", "text_classifier_stub"}:
        return True
    if experiment_dir is None:
        return False
    readme = experiment_dir / "README.md"
    report = experiment_dir / "report" / "report.md"
    text = ""
    for path in (readme, report):
        if path.exists():
            text += "\n" + path.read_text(encoding="utf-8", errors="ignore").casefold()
    return "synthetic" in text or "fixture" in text


def _has_baseline_evidence(run_record: dict[str, Any]) -> bool:
    run = _dict(run_record.get("run"))
    task_id = _text(run.get("task_id")).casefold()
    if task_id.endswith("baseline"):
        return True
    text = json.dumps(run_record, sort_keys=True).casefold()
    return "baseline" in text


def _has_ablation_evidence(run_record: dict[str, Any]) -> bool:
    task_metadata = _dict(run_record.get("task_metadata"))
    if _text(task_metadata.get("ablation")):
        return True
    artifacts = " ".join(_text(path) for path in _list(run_record.get("artifacts"))).casefold()
    if "ablation" in artifacts:
        return True
    text = json.dumps(run_record, sort_keys=True).casefold()
    return "ablation" in text


def _has_statistical_sanity(run_record: dict[str, Any]) -> bool:
    validation = _read_json_if_exists(_dict(run_record.get("validation_report")).get("json_path"))
    if _list(validation.get("statistical_notes")):
        return True
    text = json.dumps(run_record, sort_keys=True).casefold()
    return any(term in text for term in ("confidence interval", "p_value", "standard deviation"))


def _has_innovation_evidence(
    run_record: dict[str, Any],
    experiment_dir: Path | None,
) -> bool:
    task_metadata = _dict(run_record.get("task_metadata"))
    run = _dict(run_record.get("run"))
    task_id = _text(run.get("task_id")).casefold()
    explicit_baseline_only = task_metadata.get("baseline_only") is True
    if explicit_baseline_only or task_id.endswith("baseline"):
        return False

    contribution_fields = (
        "novel_contribution",
        "proposed_method",
        "method_contribution",
        "mechanism",
        "contribution",
    )
    has_contribution_metadata = any(
        _text(task_metadata.get(field)).strip() for field in contribution_fields
    )
    if not has_contribution_metadata:
        return False

    innovation_artifacts = _innovation_artifact_paths(run_record)
    if not innovation_artifacts:
        return False
    return _relative_paths_exist(experiment_dir, list(innovation_artifacts))


def _method_effect_check(
    run_record: dict[str, Any],
    experiment_dir: Path | None,
    target: PublicationQualityTarget,
    run_record_ref: str,
) -> PublicationAuditCheck:
    if not target.require_novel_contribution:
        return PublicationAuditCheck(
            "method_effect_evidence",
            PublicationAuditCheckStatus.PASS,
            "info",
            "Positive method-effect evidence is not required for this target.",
            (run_record_ref,),
        )

    artifact_paths = _innovation_artifact_paths(run_record)
    resolved_paths = _existing_relative_paths(experiment_dir, artifact_paths)
    refs = (run_record_ref, *[path.as_posix() for path in resolved_paths])
    if not resolved_paths:
        return PublicationAuditCheck(
            "method_effect_evidence",
            PublicationAuditCheckStatus.FAIL,
            "high",
            "Method-effect evidence is missing because no readable innovation artifact exists.",
            refs,
            "Preserve a JSON innovation artifact with baseline and candidate metrics before publication review.",
        )

    metrics_payload = _dict(_dict(run_record.get("metrics")).get("values"))
    for path in resolved_paths:
        payload = _read_json_if_exists(path)
        evidence_payload = {**metrics_payload, **payload}
        delta = _method_effect_delta(evidence_payload)
        if delta is None:
            continue
        if delta > 0:
            standard_error = _method_effect_standard_error(evidence_payload)
            min_standard_errors = target.min_method_effect_standard_errors
            if min_standard_errors > 0:
                if standard_error is None or standard_error <= 0:
                    return PublicationAuditCheck(
                        "method_effect_evidence",
                        PublicationAuditCheckStatus.FAIL,
                        "high",
                        (
                            "Method candidate has a positive delta but no positive standard-error "
                            "evidence for the configured publication target."
                        ),
                        refs,
                        "Record an uncertainty estimate such as accuracy_standard_error before publication review.",
                    )
                standard_error_ratio = delta / standard_error
                if standard_error_ratio < min_standard_errors:
                    return PublicationAuditCheck(
                        "method_effect_evidence",
                        PublicationAuditCheckStatus.FAIL,
                        "high",
                        (
                            f"Method candidate improved by delta={delta:.6f}, but this is only "
                            f"{standard_error_ratio:.2f} standard errors; target requires "
                            f">={min_standard_errors:.2f}."
                        ),
                        refs,
                        (
                            "Treat the result as weak evidence; rerun with stronger statistical "
                            "support or a more robust method candidate."
                        ),
                    )
            return PublicationAuditCheck(
                "method_effect_evidence",
                PublicationAuditCheckStatus.PASS,
                "high",
                _method_effect_pass_message(delta, standard_error, min_standard_errors),
                refs,
            )
        relation = "tied" if delta == 0 else "underperformed"
        return PublicationAuditCheck(
            "method_effect_evidence",
            PublicationAuditCheckStatus.FAIL,
            "high",
            f"Method candidate {relation} the baseline with recorded delta={delta:.6f}.",
            refs,
            (
                "Do not claim empirical gain; treat this as negative evidence or "
                "validate a stronger method candidate."
            ),
        )

    return PublicationAuditCheck(
        "method_effect_evidence",
        PublicationAuditCheckStatus.FAIL,
        "high",
        "Innovation artifacts exist but do not report a baseline-vs-candidate effect delta.",
        refs,
        "Add a numeric delta such as accuracy_delta_vs_baseline or candidate/baseline metrics.",
    )


def _innovation_artifact_paths(run_record: dict[str, Any]) -> tuple[str, ...]:
    artifact_paths = tuple(_text(path) for path in _list(run_record.get("artifacts")))
    return tuple(
        path_text
        for path_text in artifact_paths
        if any(term in path_text.casefold() for term in ("innovation", "mechanism", "contribution"))
    )


def _existing_relative_paths(root: Path | None, paths: tuple[str, ...]) -> tuple[Path, ...]:
    if root is None:
        return ()
    resolved: list[Path] = []
    for path_text in paths:
        path = Path(path_text)
        candidate = path if path.is_absolute() else root / path
        if candidate.exists():
            resolved.append(candidate)
    return tuple(resolved)


def _method_effect_delta(payload: dict[str, Any]) -> float | None:
    for key in (
        "accuracy_delta_vs_baseline",
        "delta_vs_baseline",
        "metric_delta_vs_baseline",
        "candidate_minus_baseline",
    ):
        delta = _float_or_none(payload.get(key))
        if delta is not None:
            return delta
    candidate = _float_or_none(payload.get("candidate_accuracy"))
    baseline = _float_or_none(payload.get("baseline_accuracy"))
    if candidate is not None and baseline is not None:
        return candidate - baseline
    return None


def _method_effect_standard_error(payload: dict[str, Any]) -> float | None:
    for key in (
        "accuracy_delta_standard_error",
        "delta_standard_error",
        "metric_delta_standard_error",
        "accuracy_standard_error",
        "standard_error",
        "metric_standard_error",
    ):
        standard_error = _float_or_none(payload.get(key))
        if standard_error is not None:
            return standard_error
    return None


def _method_effect_pass_message(
    delta: float,
    standard_error: float | None,
    min_standard_errors: float,
) -> str:
    if min_standard_errors <= 0 or standard_error is None or standard_error <= 0:
        return f"Method candidate improved over baseline with recorded delta={delta:.6f}."
    return (
        f"Method candidate improved over baseline with recorded delta={delta:.6f}, "
        f"which is {delta / standard_error:.2f} standard errors."
    )


def _relative_paths_exist(root: Path | None, paths: list[Any]) -> bool:
    if root is None or not paths:
        return False
    for path_text in paths:
        path = Path(_text(path_text))
        resolved = path if path.is_absolute() else root / path
        if not resolved.exists():
            return False
    return True


def _has_markdown_heading(text: str, heading: str) -> bool:
    escaped = re.escape(heading)
    return re.search(rf"(?m)^#+\s+{escaped}\s*$", text) is not None


def _read_json(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object in {path}")
    return payload


def _read_json_if_exists(path_value: object) -> dict[str, Any]:
    path = Path(_text(path_value))
    if not path.exists():
        return {}
    try:
        return _read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _read_json_with_error(path_value: object) -> tuple[dict[str, Any], str | None]:
    path = Path(_text(path_value))
    if not path.exists():
        return {}, f"{path.as_posix()} does not exist"
    try:
        return _read_json(path), None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {}, str(exc)


def _resolve_path(path_value: object, base_dir: Path) -> Path | None:
    text = _text(path_value)
    if not text:
        return None
    path = Path(text)
    candidates = [path]
    if not path.is_absolute():
        candidates.extend([base_dir / path, Path.cwd() / path])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[Any]:
    if not isinstance(value, list):
        return []
    return value


def _dict_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _path_text(value: object) -> str | None:
    text = _text(value)
    if not text:
        return None
    return Path(text).as_posix()


def _same_file(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve() or left.samefile(right)
    except OSError:
        return left.resolve() == right.resolve()


def _int(value: object, *, default: int = 0) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def _float_or_none(value: object) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower()
    return slug or "publication-audit"
