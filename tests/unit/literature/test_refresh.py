from datetime import datetime, timezone
from pathlib import Path

import pytest

import autoresearch.literature.refresh as refresh_module
from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
)
from autoresearch.literature import (
    AcademicPaper,
    LiteratureRefreshConfig,
    generate_literature_queries,
    run_daily_literature_refresh,
)


class _RateLimiter:
    def __init__(self, min_interval_seconds: float) -> None:
        self.min_interval_seconds = min_interval_seconds


class _FakeClient:
    def __init__(
        self,
        source: str,
        papers: list[AcademicPaper],
        rate_limit: float,
        *,
        error: Exception | None = None,
    ) -> None:
        self.source = source
        self.papers = papers
        self.rate_limiter = _RateLimiter(rate_limit)
        self.error = error
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, *, limit: int = 10) -> list[AcademicPaper]:
        self.calls.append((query, limit))
        if self.error is not None:
            raise self.error
        return self.papers


def test_generate_literature_queries_uses_candidate_and_vault_context(
    tmp_path: Path,
) -> None:
    _write_candidate_context(tmp_path)

    queries = generate_literature_queries(
        tmp_path,
        config=LiteratureRefreshConfig(max_queries=3),
    )

    assert queries[0].origin == "active_candidate_gap"
    assert "agent" in queries[0].text
    assert "weak evidence" in queries[0].text
    assert "exploration/topics/candidate_1.md" in queries[0].vault_paths


def test_daily_refresh_fetches_deduplicates_caches_and_writes_obsidian_summary(
    tmp_path: Path,
) -> None:
    _write_candidate_context(tmp_path)
    now = datetime(2026, 6, 12, 1, 0, tzinfo=timezone.utc)
    shared_paper = AcademicPaper(
        title="Evidence First Agent Review",
        authors=["A. Researcher"],
        abstract="Agent review workflows need stronger evidence.",
        doi="10.1234/agent-review",
        url="https://example.com/agent-review",
        source="arxiv",
    )
    arxiv = _FakeClient("arxiv", [shared_paper], 3.0)
    semantic = _FakeClient(
        "semantic_scholar",
        [shared_paper.model_copy(update={"source": "semantic_scholar"})],
        1.0,
    )

    first = run_daily_literature_refresh(
        vault_root=tmp_path,
        cache_root=tmp_path / ".cache" / "literature",
        clients={"arxiv": arxiv, "semantic_scholar": semantic},
        now=now,
        config=LiteratureRefreshConfig(max_queries=1, max_results_per_source=5),
    )
    second = run_daily_literature_refresh(
        vault_root=tmp_path,
        cache_root=tmp_path / ".cache" / "literature",
        clients={"arxiv": arxiv, "semantic_scholar": semantic},
        now=now,
        config=LiteratureRefreshConfig(max_queries=1, max_results_per_source=5),
    )

    assert arxiv.calls == [(first.queries[0].text, 5)]
    assert semantic.calls == [(first.queries[0].text, 5)]
    assert len(first.papers) == 1
    assert len(first.documents) == 1
    assert [fetch.cache_hit for fetch in first.fetches] == [False, False]
    assert [fetch.cache_hit for fetch in second.fetches] == [True, True]
    assert [fetch.rate_limit_seconds for fetch in first.fetches] == [3.0, 1.0]
    assert first.summary_path is not None
    summary = first.summary_path.read_text(encoding="utf-8")
    assert "## Guardrails" in summary
    assert "pending verification" in summary
    assert "Evidence First Agent Review" in summary
    assert first.queries[0].text in summary
    assert (tmp_path / ".cache" / "literature").exists()


def test_daily_refresh_records_source_errors_and_continues_other_sources(
    tmp_path: Path,
) -> None:
    _write_candidate_context(tmp_path)
    semantic = _FakeClient(
        "semantic_scholar",
        [
            AcademicPaper(
                title="Evidence First Agent Review",
                url="https://example.com/agent-review",
                source="semantic_scholar",
            )
        ],
        1.0,
    )

    report = run_daily_literature_refresh(
        vault_root=tmp_path,
        cache_root=tmp_path / ".cache" / "literature",
        clients={
            "arxiv": _FakeClient("arxiv", [], 3.0, error=RuntimeError("rate limited")),
            "semantic_scholar": semantic,
        },
        config=LiteratureRefreshConfig(max_queries=1, max_results_per_source=5),
    )

    assert len(report.documents) == 1
    assert report.fetches[0].source == "arxiv"
    assert report.fetches[0].error == "RuntimeError: rate limited"
    assert report.fetches[1].source == "semantic_scholar"
    assert report.fetches[1].error is None
    assert report.summary_path is not None
    assert "rate limited" in report.summary_path.read_text(encoding="utf-8")


def test_daily_refresh_default_sources_include_openalex_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_candidate_context(tmp_path)
    paper = AcademicPaper(
        title="Open Evidence Agent Review",
        url="https://openalex.org/W123",
        source="openalex",
    )

    monkeypatch.setattr(
        refresh_module,
        "ArxivClient",
        lambda: _FakeClient("arxiv", [], 3.0),
    )
    monkeypatch.setattr(
        refresh_module,
        "SemanticScholarClient",
        lambda: _FakeClient("semantic_scholar", [], 3.0, error=RuntimeError("rate limited")),
    )
    monkeypatch.setattr(
        refresh_module,
        "OpenAlexClient",
        lambda: _FakeClient("openalex", [paper], 1.0),
    )

    report = run_daily_literature_refresh(
        vault_root=tmp_path,
        cache_root=tmp_path / ".cache" / "literature",
        config=LiteratureRefreshConfig(max_queries=1, max_results_per_source=2),
    )

    assert [fetch.source for fetch in report.fetches] == [
        "arxiv",
        "semantic_scholar",
        "openalex",
    ]
    assert report.fetches[1].error == "RuntimeError: rate limited"
    assert report.documents[0].tags == ["openalex"]
    assert report.summary_path is not None
    assert "openalex" in report.summary_path.read_text(encoding="utf-8")


def _write_candidate_context(vault_root: Path) -> None:
    store = MarkdownKnowledgeStore(vault_root)
    store.write_entry(
        "exploration/topics/candidate_1.md",
        KnowledgeEntry(
            entry_id="candidate_1",
            entry_type=KnowledgeEntryType.RESEARCH_CANDIDATE,
            zone=KnowledgeZone.EXPLORATION,
            title="Reduce Weak Evidence In Agent Review",
            tags=["research-candidate", "ready_for_review"],
            keywords=["agent", "review", "weak evidence"],
            body="Candidate gap: agent review workflows still produce weak evidence.",
        ),
    )
    store.write_entry(
        "exploration/methodologies/agent.md",
        KnowledgeEntry(
            entry_id="method_agent",
            entry_type=KnowledgeEntryType.METHOD_CARD,
            zone=KnowledgeZone.EXPLORATION,
            title="Agent Methods",
            keywords=["agent", "tool use"],
            body="Agent methodology card.",
        ),
    )
