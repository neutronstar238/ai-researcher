from datetime import datetime, timedelta, timezone
from pathlib import Path

from autoresearch.literature import AcademicPaper, RetrievalCache, retrieval_cache_key


def _paper(title: str) -> AcademicPaper:
    return AcademicPaper(title=title, source="arxiv")


def test_retrieval_cache_key_includes_query_source_page_limit_and_config() -> None:
    base = retrieval_cache_key(
        query="agent",
        source="arxiv",
        page=1,
        limit=10,
        config={"sort": "relevance"},
    )
    different_query = retrieval_cache_key(
        query="other",
        source="arxiv",
        page=1,
        limit=10,
        config={"sort": "relevance"},
    )
    different_config = retrieval_cache_key(
        query="agent",
        source="arxiv",
        page=1,
        limit=10,
        config={"sort": "date"},
    )

    assert base != different_query
    assert base != different_config


def test_retrieval_cache_reuses_identical_query_and_misses_different_query(
    tmp_path: Path,
) -> None:
    cache = RetrievalCache(tmp_path)
    calls: list[str] = []

    def fetch_agent() -> list[AcademicPaper]:
        calls.append("agent")
        return [_paper("Agent Paper")]

    first = cache.get_or_fetch(
        query="agent",
        source="arxiv",
        page=1,
        limit=10,
        config={"sort": "relevance"},
        fetcher=fetch_agent,
    )
    second = cache.get_or_fetch(
        query="agent",
        source="arxiv",
        page=1,
        limit=10,
        config={"sort": "relevance"},
        fetcher=fetch_agent,
    )
    third = cache.get_or_fetch(
        query="different",
        source="arxiv",
        page=1,
        limit=10,
        config={"sort": "relevance"},
        fetcher=lambda: [_paper("Different Paper")],
    )

    assert calls == ["agent"]
    assert first == second
    assert third == [_paper("Different Paper")]


def test_retrieval_cache_expires_after_24_hours(tmp_path: Path) -> None:
    cache = RetrievalCache(tmp_path, ttl_hours=24)
    key = retrieval_cache_key(query="agent", source="arxiv", page=1, limit=10, config={})
    now = datetime(2026, 6, 11, 10, 0, tzinfo=timezone.utc)

    cache.set(key, [_paper("Agent Paper")], now=now)

    assert cache.get(key, now=now + timedelta(hours=23, minutes=59)) == [_paper("Agent Paper")]
    assert cache.get(key, now=now + timedelta(hours=24, minutes=1)) is None
