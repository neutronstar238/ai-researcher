from datetime import datetime, timezone
from pathlib import Path

import pytest

import autoresearch.research.similarity as similarity_module
from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
)
from autoresearch.literature import AcademicPaper
from autoresearch.research import (
    SimilarityCheckConfig,
    SimilarityFinding,
    UnsupportedSimilarityClaimError,
    generate_similarity_queries,
    run_project_similarity_check,
    validate_similarity_findings,
)
from autoresearch.schemas import CandidateStatus, ResearchCandidate


class _RateLimiter:
    def __init__(self, min_interval_seconds: float) -> None:
        self.min_interval_seconds = min_interval_seconds


class _FakeClient:
    def __init__(
        self,
        papers: list[AcademicPaper],
        rate_limit: float,
        *,
        error: Exception | None = None,
    ) -> None:
        self.papers = papers
        self.rate_limiter = _RateLimiter(rate_limit)
        self.error = error
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, *, limit: int = 10) -> list[AcademicPaper]:
        self.calls.append((query, limit))
        if self.error is not None:
            raise self.error
        return self.papers


class _QueryAwareFakeClient:
    def __init__(self, responses: dict[str, list[AcademicPaper]], rate_limit: float) -> None:
        self.responses = responses
        self.rate_limiter = _RateLimiter(rate_limit)
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, *, limit: int = 10) -> list[AcademicPaper]:
        self.calls.append((query, limit))
        for marker, papers in self.responses.items():
            if marker in query:
                return papers[:limit]
        return []


def test_generate_similarity_queries_uses_candidate_and_vault_context(tmp_path: Path) -> None:
    candidate = _candidate()
    _write_similarity_context(tmp_path, candidate)

    queries = generate_similarity_queries(
        candidate,
        vault_root=tmp_path,
        config=SimilarityCheckConfig(max_queries=8),
    )

    origins = {query.origin for query in queries}
    assert "candidate_title" in origins
    assert "method_dataset_limitation" in origins
    assert "negative_result_search" in origins
    assert any(query.origin == "vault_failure_case" for query in queries)
    assert any("exploration/topics/candidate_1.md" in query.vault_paths for query in queries)


def test_generate_similarity_queries_expands_sparse_candidates_to_query_floor(
    tmp_path: Path,
) -> None:
    candidate = ResearchCandidate(
        id="sparse_candidate",
        title="Evidence-bound self-evolving research loop",
        description=(
            "Improve automated research loops by combining live literature discovery, "
            "local validation, Obsidian memory, and review-driven follow-up tasks."
        ),
        research_gap=(
            "Automated research agents jump from retrieval to writing without durable "
            "evidence memory or validation-gated self-looping."
        ),
        novelty_score=0.55,
        feasibility_score=0.75,
        impact_score=0.65,
        evidence_refs=["doc_1"],
        related_document_ids=["doc_1"],
        status=CandidateStatus.READY_FOR_REVIEW,
        metadata={
            "seed_document_title": (
                "Reporting and Reviewing LLM-Integrated Systems in HCI"
            ),
        },
    )
    (tmp_path / "exploration").mkdir(parents=True)
    (tmp_path / "exploration" / "index.md").write_text(
        "# Exploration Index\n\n## Evidence live sha 20260613 20260612170946\n",
        encoding="utf-8",
    )

    queries = generate_similarity_queries(
        candidate,
        vault_root=tmp_path,
        config=SimilarityCheckConfig(max_queries=4),
    )

    assert len(queries) == 4
    assert len({query.text for query in queries}) == 4
    assert {query.origin for query in queries} >= {
        "candidate_title",
        "research_gap",
        "candidate_description",
        "metadata_seed_document_title",
    }
    assert "vault_topic_index" not in {query.origin for query in queries}


def test_generate_similarity_queries_prioritizes_concise_novelty_stress_queries(
    tmp_path: Path,
) -> None:
    candidate = ResearchCandidate(
        id="pendigits_variance_candidate",
        title="Variance-calibrated prototype classifiers for UCI Pendigits",
        description=(
            "Evaluate whether diagonal per-class variance calibration improves a "
            "nearest-prototype classifier."
        ),
        research_gap=(
            "Nearest-centroid baselines are reproducible and interpretable, but a "
            "publication claim requires checking whether variance-calibrated prototype "
            "distance has already been covered by Gaussian, Mahalanobis, or "
            "metric-learning classifiers on handwritten digit benchmarks."
        ),
        novelty_score=0.45,
        feasibility_score=0.85,
        impact_score=0.55,
        evidence_refs=["doc_1"],
        related_document_ids=["doc_1"],
        status=CandidateStatus.READY_FOR_REVIEW,
        metadata={
            "method": "diagonal variance-calibrated prototypes with variance shrinkage",
            "dataset": "UCI Pen-Based Recognition of Handwritten Digits",
            "benchmark": "UCI Pendigits",
            "baseline": "nearest centroid classifier and z-score centroid ablation",
            "limitation": (
                "single public benchmark; adjacent Gaussian, Mahalanobis, and "
                "distance-metric classifiers may already cover the mechanism"
            ),
        },
    )

    queries = generate_similarity_queries(
        candidate,
        vault_root=tmp_path,
        config=SimilarityCheckConfig(max_queries=4),
    )

    assert [query.origin for query in queries] == [
        "candidate_title",
        "method_dataset_search",
        "baseline_dataset_search",
        "limitation_risk_search",
    ]
    assert queries[1].text == "diagonal variance-calibrated prototypes variance shrinkage uci pendigits"
    assert queries[2].text == "nearest centroid classifier z-score ablation uci pendigits"
    assert queries[3].text == "mahalanobis distance metric gaussian prototype classifiers uci pendigits"
    assert all("publication claim requires" not in query.text for query in queries)
    assert all(len(query.text.split()) <= 10 for query in queries)


def test_project_similarity_check_writes_source_backed_obsidian_summary(
    tmp_path: Path,
) -> None:
    candidate = _candidate()
    _write_similarity_context(tmp_path, candidate)
    now = datetime(2026, 6, 12, 2, 0, tzinfo=timezone.utc)
    duplicate = AcademicPaper(
        title="Reduce Weak Evidence In Agent On Review",
        abstract="Agent review workflows with weak evidence.",
        doi="10.1234/direct",
        url="https://example.com/direct",
        source="arxiv",
    )
    adjacent = AcademicPaper(
        title="Agent review benchmark still has weak evidence",
        abstract="Agent methods on the review benchmark report limited evidence quality.",
        url="https://example.com/adjacent",
        source="semantic_scholar",
    )
    arxiv = _FakeClient([duplicate], 3.0)
    semantic = _FakeClient([adjacent], 1.0)

    report = run_project_similarity_check(
        candidate=candidate,
        vault_root=tmp_path,
        cache_root=tmp_path / ".cache" / "similarity",
        clients={
            "arxiv": arxiv,
            "semantic_scholar": semantic,
            "broken_source": _FakeClient([], 1.0, error=RuntimeError("offline")),
        },
        now=now,
        config=SimilarityCheckConfig(max_queries=1, max_results_per_source=3),
    )
    cached_report = run_project_similarity_check(
        candidate=candidate,
        vault_root=tmp_path,
        cache_root=tmp_path / ".cache" / "similarity",
        clients={"arxiv": arxiv, "semantic_scholar": semantic},
        now=now,
        config=SimilarityCheckConfig(max_queries=1, max_results_per_source=3),
        write_summary=False,
    )

    assert arxiv.calls == [(report.queries[0].text, 3)]
    assert semantic.calls == [(report.queries[0].text, 3)]
    assert len(report.findings) == 2
    assert {finding.classification for finding in report.findings} >= {
        "direct_duplicate",
        "adjacent_work",
    }
    assert report.fetches[-1].error == "RuntimeError: offline"
    assert [fetch.cache_hit for fetch in cached_report.fetches] == [True, True]
    assert report.summary_path is not None
    summary = report.summary_path.read_text(encoding="utf-8")
    assert "## Findings" in summary
    assert "pending verification" in summary
    assert "https://example.com/direct" in summary
    assert "RuntimeError: offline" in summary


def test_project_similarity_default_sources_include_openalex_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AUTORESEARCH_ENABLE_SEMANTIC_SCHOLAR", raising=False)
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    candidate = _candidate()
    _write_similarity_context(tmp_path, candidate)
    paper = AcademicPaper(
        title="OpenAlex agent review evidence",
        abstract="Agent review workflows need evidence.",
        url="https://openalex.org/W456",
        source="openalex",
    )

    monkeypatch.setattr(
        similarity_module,
        "ArxivClient",
        lambda: _FakeClient([], 3.0),
    )
    monkeypatch.setattr(
        similarity_module,
        "SemanticScholarClient",
        lambda: _FakeClient([], 3.0, error=RuntimeError("rate limited")),
    )
    monkeypatch.setattr(
        similarity_module,
        "OpenAlexClient",
        lambda: _FakeClient([paper], 1.0),
    )

    report = run_project_similarity_check(
        candidate=candidate,
        vault_root=tmp_path,
        cache_root=tmp_path / ".cache" / "similarity",
        config=SimilarityCheckConfig(max_queries=1, max_results_per_source=2),
    )

    assert [fetch.source for fetch in report.fetches] == ["arxiv", "openalex"]
    assert report.findings[0].source_database == "openalex"
    assert report.summary_path is not None
    assert "openalex" in report.summary_path.read_text(encoding="utf-8")


def test_project_similarity_includes_semantic_scholar_only_when_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTORESEARCH_ENABLE_SEMANTIC_SCHOLAR", "1")
    candidate = _candidate()
    _write_similarity_context(tmp_path, candidate)
    paper = AcademicPaper(
        title="Semantic Scholar agent review evidence",
        abstract="Agent review workflows need evidence.",
        url="https://api.semanticscholar.org/paper/123",
        source="semantic_scholar",
    )

    monkeypatch.setattr(similarity_module, "ArxivClient", lambda: _FakeClient([], 3.0))
    monkeypatch.setattr(similarity_module, "OpenAlexClient", lambda: _FakeClient([], 1.0))
    monkeypatch.setattr(
        similarity_module,
        "SemanticScholarClient",
        lambda: _FakeClient([paper], 3.0),
    )

    report = run_project_similarity_check(
        candidate=candidate,
        vault_root=tmp_path,
        cache_root=tmp_path / ".cache" / "similarity",
        config=SimilarityCheckConfig(max_queries=1, max_results_per_source=2),
    )

    assert [fetch.source for fetch in report.fetches] == [
        "arxiv",
        "openalex",
        "semantic_scholar",
    ]
    assert report.findings[0].source_database == "semantic_scholar"


def test_project_similarity_classifies_conservative_token_overlap(
    tmp_path: Path,
) -> None:
    candidate = ResearchCandidate(
        id="variance_candidate",
        title="Improve public handwriting classifiers with calibrated centroids",
        description="Evaluate a diagonal variance calibrated prototype method.",
        research_gap="Nearest-centroid baselines underuse class-specific variance.",
        novelty_score=0.7,
        feasibility_score=0.8,
        impact_score=0.6,
        evidence_refs=["doc_1"],
        related_document_ids=["doc_1"],
        status=CandidateStatus.READY_FOR_REVIEW,
        metadata={
            "method": "diagonal variance calibrated prototypes",
            "dataset": "pendigits",
        },
    )
    paper = AcademicPaper(
        title="Variance calibrated prototypes distances for Pendigits recognition",
        abstract=(
            "A source-backed study of diagonal variance calibration for prototype "
            "prototypes classification on the Pendigits benchmark."
        ),
        url="https://example.com/variance",
        source="openalex",
    )

    report = run_project_similarity_check(
        candidate=candidate,
        vault_root=tmp_path,
        cache_root=tmp_path / ".cache" / "similarity",
        clients={"openalex": _FakeClient([paper], 1.0)},
        config=SimilarityCheckConfig(max_queries=1, max_results_per_source=1),
    )

    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.classification == "adjacent_work"
    assert any("method token overlap" in basis for basis in finding.classification_basis)
    assert any("dataset token overlap" in basis for basis in finding.classification_basis)
    assert report.summary_path is not None
    summary = report.summary_path.read_text(encoding="utf-8")
    assert "method token overlap" in summary
    assert "dataset token overlap" in summary


def test_project_similarity_classifies_query_backed_method_family_overlap(
    tmp_path: Path,
) -> None:
    candidate = _pendigits_candidate()
    prototype_paper = AcademicPaper(
        title="Learning Prototype Classifiers for Long-Tailed Recognition",
        abstract=(
            "Prototype classifiers compare learned class prototypes for recognition "
            "under long-tailed class distributions."
        ),
        url="https://example.com/prototype",
        source="openalex",
    )
    centroid_paper = AcademicPaper(
        title="Visual Recognition with Deep Nearest Centroids",
        abstract=(
            "Nearest centroid classifiers are studied as interpretable visual "
            "recognition models."
        ),
        url="https://example.com/centroids",
        source="openalex",
    )
    mahalanobis_paper = AcademicPaper(
        title="Large Margin Nearest Neighbor Classification using Curved Mahalanobis Distances",
        abstract=(
            "A Mahalanobis distance metric learning method for nearest-neighbor "
            "classification."
        ),
        url="https://example.com/mahalanobis",
        source="openalex",
    )
    client = _QueryAwareFakeClient(
        {
            "diagonal variance-calibrated prototypes": [prototype_paper],
            "nearest centroid": [centroid_paper],
            "mahalanobis": [mahalanobis_paper],
        },
        1.0,
    )

    report = run_project_similarity_check(
        candidate=candidate,
        vault_root=tmp_path,
        cache_root=tmp_path / ".cache" / "similarity",
        clients={"openalex": client},
        config=SimilarityCheckConfig(max_queries=4, max_results_per_source=3),
    )

    classifications = {finding.title: finding.classification for finding in report.findings}
    assert classifications == {
        prototype_paper.title: "adjacent_work",
        centroid_paper.title: "adjacent_work",
        mahalanobis_paper.title: "adjacent_work",
    }
    assert all(
        any("query family overlap" in basis for basis in finding.classification_basis)
        for finding in report.findings
    )
    assert len([finding for finding in report.findings if finding.classification != "unknown"]) == 3


def test_project_similarity_keeps_weak_token_overlap_unknown(tmp_path: Path) -> None:
    candidate = ResearchCandidate(
        id="weak_overlap_candidate",
        title="Improve public handwriting classifiers with calibrated centroids",
        description="Evaluate a diagonal variance calibrated prototype method.",
        research_gap="Nearest-centroid baselines underuse class-specific variance.",
        novelty_score=0.7,
        feasibility_score=0.8,
        impact_score=0.6,
        evidence_refs=["doc_1"],
        related_document_ids=["doc_1"],
        status=CandidateStatus.READY_FOR_REVIEW,
        metadata={
            "method": "diagonal variance calibrated prototypes",
            "dataset": "pendigits",
        },
    )
    paper = AcademicPaper(
        title="Variance study for a generic classifier benchmark",
        abstract="A broad survey without the target method or dataset evidence.",
        url="https://example.com/weak",
        source="openalex",
    )

    report = run_project_similarity_check(
        candidate=candidate,
        vault_root=tmp_path,
        cache_root=tmp_path / ".cache" / "similarity",
        clients={"openalex": _FakeClient([paper], 1.0)},
        config=SimilarityCheckConfig(max_queries=1, max_results_per_source=1),
    )

    assert len(report.findings) == 1
    assert report.findings[0].classification == "unknown"


def test_project_similarity_requires_method_anchor_for_variance_overlap(
    tmp_path: Path,
) -> None:
    candidate = _pendigits_candidate()
    paper = AcademicPaper(
        title=(
            "Shrinkage MMSE estimators of covariances beyond the zero-mean "
            "and stationary variance assumptions"
        ),
        abstract=(
            "A diagonal covariance shrinkage estimator for variance assumptions "
            "in a generic statistical estimation setting."
        ),
        url="https://example.com/shrinkage",
        source="arxiv",
    )

    report = run_project_similarity_check(
        candidate=candidate,
        vault_root=tmp_path,
        cache_root=tmp_path / ".cache" / "similarity",
        clients={"arxiv": _FakeClient([paper], 3.0)},
        config=SimilarityCheckConfig(max_queries=1, max_results_per_source=1),
    )

    assert len(report.findings) == 1
    assert report.findings[0].classification == "unknown"


def test_similarity_findings_reject_unsupported_claims() -> None:
    finding = SimilarityFinding(
        document_id="doc_1",
        title="Unsupported claim",
        source_uri="https://example.com/paper",
        source_database="arxiv",
        query="agent review",
        retrieved_at=datetime(2026, 6, 12, tzinfo=timezone.utc),
        classification="direct_duplicate",
        confidence=0.9,
        evidence_refs=("doc_1",),
        classification_basis=("title similarity 0.9",),
        unsupported_claims=("claims benchmark improvement without source metadata",),
    )

    with pytest.raises(UnsupportedSimilarityClaimError):
        validate_similarity_findings((finding,))


def _candidate() -> ResearchCandidate:
    return ResearchCandidate(
        id="candidate_1",
        title="Reduce Weak Evidence In Agent On Review",
        description="Explore stronger evidence capture for agent review workflows.",
        research_gap="Agent review workflows still produce weak evidence.",
        novelty_score=0.7,
        feasibility_score=0.8,
        impact_score=0.6,
        evidence_refs=["doc_1"],
        related_document_ids=["doc_1"],
        status=CandidateStatus.READY_FOR_REVIEW,
        metadata={
            "method": "agent",
            "dataset": "review",
            "limitation": "weak evidence",
        },
    )


def _pendigits_candidate() -> ResearchCandidate:
    return ResearchCandidate(
        id="pendigits_variance_candidate",
        title="Variance-calibrated prototype classifiers for UCI Pendigits",
        description=(
            "Evaluate whether diagonal per-class variance calibration improves a "
            "nearest-prototype classifier."
        ),
        research_gap=(
            "Nearest-centroid baselines are reproducible and interpretable, but a "
            "publication claim requires checking whether variance-calibrated prototype "
            "distance has already been covered by Gaussian, Mahalanobis, or "
            "metric-learning classifiers on handwritten digit benchmarks."
        ),
        novelty_score=0.45,
        feasibility_score=0.85,
        impact_score=0.55,
        evidence_refs=["doc_1"],
        related_document_ids=["doc_1"],
        status=CandidateStatus.READY_FOR_REVIEW,
        metadata={
            "method": "diagonal variance-calibrated prototypes with variance shrinkage",
            "dataset": "UCI Pen-Based Recognition of Handwritten Digits",
            "benchmark": "UCI Pendigits",
            "baseline": "nearest centroid classifier and z-score centroid ablation",
            "limitation": (
                "single public benchmark; adjacent Gaussian, Mahalanobis, and "
                "distance-metric classifiers may already cover the mechanism"
            ),
        },
    )


def _write_similarity_context(vault_root: Path, candidate: ResearchCandidate) -> None:
    store = MarkdownKnowledgeStore(vault_root)
    store.write_entry(
        "exploration/topics/candidate_1.md",
        KnowledgeEntry(
            entry_id=candidate.id,
            entry_type=KnowledgeEntryType.RESEARCH_CANDIDATE,
            zone=KnowledgeZone.EXPLORATION,
            title=candidate.title,
            tags=["research-candidate", candidate.status.value],
            keywords=["agent", "review", "weak evidence"],
            source_refs=candidate.evidence_refs,
            body=candidate.research_gap,
        ),
    )
    store.write_entry(
        "exploration/failure_patterns/weak-evidence.md",
        KnowledgeEntry(
            entry_id="failure_weak_evidence",
            entry_type=KnowledgeEntryType.FAILURE_CASE,
            zone=KnowledgeZone.EXPLORATION,
            title="Weak Evidence Failure",
            keywords=["agent", "weak evidence"],
            body="Prior local runs produced weak evidence.",
        ),
    )
